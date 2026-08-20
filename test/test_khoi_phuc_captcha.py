"""Khôi phục tài khoản Google khi bị CAPTCHA — bỏ sớm và báo đúng nguyên nhân.

Đo thật 30/07 với benbap2011@gmail.com:

    10:02:57 clicked account tile
    10:03:01 auto_login: captcha detected for google-benbap2011, waiting manual solve
    10:08:02 closed browser after onboard state=failed      ← 5 PHÚT sau
    recover_failed ... tried: ["T2-freshen"]

Hai lỗi cộng lại:

1. `need_captcha` KHÔNG có trong danh sách trạng thái "cần người", nên vòng poll
   chờ hết ngân sách ~310 s mới bỏ. Chờ thêm không làm captcha biến mất — chỉ giữ
   một phiên trình duyệt ngồi im ở màn hình captcha, và lịch quét 45 phút/lần lại
   đốt tiếp 5 phút nữa.
2. Thông báo gợi ý "Kiểm tra profile Google / pass+TOTP / codex_auto_list + IMAP"
   — đưa người đọc đi sai hướng, vì mật khẩu/TOTP/IMAP đều đúng cả. Log biết là
   captcha mà thông báo không nói.
"""
from __future__ import annotations

import unittest
from unittest import mock

from services import account_recovery as ar


class TestNhanRaCanNguoi(unittest.TestCase):
    def test_need_captcha_nam_trong_danh_sach_can_nguoi(self):
        self.assertIn("need_captcha", ar._CAN_NGUOI)

    def test_van_giu_need_code_va_need_tap(self):
        for st in ("need_code", "need_tap"):
            self.assertIn(st, ar._CAN_NGUOI)


class TestBoSomKhiCaptcha(unittest.TestCase):
    """Gặp captcha là trả về NGAY, không chờ hết ngân sách 310 giây."""

    def _chay(self, states: list[str]) -> tuple[bool, int]:
        goi = {"n": 0}

        class _R:
            def __init__(self, payload):
                self._p = payload

            def json(self):
                return self._p

        def post(url, **kw):
            return _R({"state": "running"})

        def get(url, **kw):
            i = min(goi["n"], len(states) - 1)
            goi["n"] += 1
            return _R({"state": states[i]})

        fake = mock.Mock(post=post, get=get)
        with mock.patch.dict("sys.modules", {"requests": fake}), \
                mock.patch.object(ar, "_solver_cfg", lambda: ("http://x", "k")), \
                mock.patch.object(ar.time, "sleep", lambda *_: None):
            ok = ar._freshen_google("google-test")
        return ok, goi["n"]

    def test_captcha_bo_ngay_sau_lan_kiem_dau(self):
        ok, so_lan = self._chay(["need_captcha"])
        self.assertFalse(ok)
        self.assertEqual(so_lan, 1,
                         "phải bỏ ngay lần đầu, không quay 62 vòng")

    def test_thanh_cong_van_tra_true(self):
        ok, _ = self._chay(["running", "running", "success"])
        self.assertTrue(ok)

    def test_ghi_lai_trang_thai_cuoi_de_bao_dung_nguyen_nhan(self):
        self._chay(["need_captcha"])
        self.assertEqual(ar.trang_thai_dang_nhap_cuoi("google-test"), "need_captcha")

    def test_profile_chua_thu_thi_tra_chuoi_rong(self):
        self.assertEqual(ar.trang_thai_dang_nhap_cuoi("google-chua-bao-gio"), "")


class TestThongBaoNoiDungNguyenNhan(unittest.TestCase):
    """Nguyên nhân cụ thể phải thắng gợi ý chung — người đọc không đi soi oan."""

    def _hint(self, trang_thai: str, is_google: bool = True) -> str:
        with mock.patch.object(ar, "trang_thai_dang_nhap_cuoi",
                               lambda _p: trang_thai):
            # Dựng lại đúng nhánh chọn hint trong recover_account.
            tt = ar.trang_thai_dang_nhap_cuoi("p") if is_google else ""
            if tt == "need_captcha":
                return ("Google đang bắt CAPTCHA — vào noVNC cổng 6080 gõ captcha, hệ thống "
                        "TỰ tiếp tục mật khẩu + 2FA. Mật khẩu/TOTP/IMAP không liên quan.")
            if tt in ("need_code", "need_tap"):
                return ("Google đòi mã 2FA phải người bấm (profile này chưa có TOTP) — "
                        "xử lý trên noVNC cổng 6080, hoặc thêm TOTP cho profile.")
            if not is_google:
                return "Thêm dòng email|pass vào Settings Codex"
            return "Kiểm tra profile Google / pass+TOTP / codex_auto_list + IMAP"

    def test_captcha_khong_bao_di_kiem_tra_mat_khau(self):
        h = self._hint("need_captcha")
        self.assertIn("CAPTCHA", h)
        self.assertIn("6080", h)
        self.assertNotIn("Kiểm tra profile Google", h)

    def test_van_giu_goi_y_cu_khi_khong_ro_nguyen_nhan(self):
        self.assertIn("Kiểm tra profile Google", self._hint("failed"))

    def test_ma_nguon_that_co_nhanh_captcha(self):
        """Khoá lại rằng nhánh này TỒN TẠI trong mã, không chỉ trong test.

        Cắt khúc tới đúng chỗ chuỗi chọn hint kết thúc (`_notify(` ngay sau nó),
        KHÔNG đếm ký tự. Cửa sổ 1400 ký tự của bản trước là một con số tình cờ:
        thêm một nhánh mới vào chuỗi — nhánh tài khoản OpenAI gốc, 20/08/2026 —
        là đẩy nhánh captcha ra ngoài cửa sổ, và build đỏ vì một nhánh vẫn còn
        nguyên vẹn.
        """
        import inspect
        src = inspect.getsource(ar)
        i = src.index("tried_s = ")
        khuc = src[i:src.index("_notify(", i)]
        self.assertIn("need_captcha", khuc)
        self.assertIn("6080", khuc)


if __name__ == "__main__":
    unittest.main()
