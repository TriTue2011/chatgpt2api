"""Hồ sơ Flow đang BẬN tạo ảnh không được coi là MẤT PHIÊN.

SỰ CỐ 09/08/2026. Chủ máy nhận chuỗi thông báo:

    ⚠️ Flow — google-benbap2011  Lỗi: quét định kỳ: mất phiên labs.google
    🔧 [T1] mất phiên → [T2] đang đăng nhập lại tài khoản Google…
    ❌ KHÔNG tự khôi phục được. Cần đăng nhập lại tay (noVNC cổng 6080).

rồi hỏi lại: "tôi thấy vẫn vào và tạo được mà nhỉ". Đúng — tài khoản hoàn toàn
khoẻ.

CHUỖI NHÂN QUẢ

`_flow_session_trang_thai` hỏi `/v1/google/flow/get-or-create-project`. Endpoint
đó lấy trình duyệt bằng `pool.page()`, mà hàm này fast-failover **429 Account
Busy** ngay khi hồ sơ đang bị lượt khác giữ — tức đúng lúc tài khoản đang tạo
ảnh hoặc video. Bản cũ chỉ đọc `project_id`, nên 429 rơi vào nhánh "không có
project_id" và bị kết luận là mất phiên.

Từ một kết luận sai đó: bộ quét báo động, T2 chạy đăng nhập lại Google (tuần tự
trên toàn hệ thống, vài phút, và mỗi lần đăng nhập tự động là một lần mời Google
bung captcha), kiểm lại vẫn bận, rồi kết luận cần người vào tay. Cái giá của một
lỗi đọc mã trạng thái là: báo động giả, đốt thời gian, và tăng rủi ro captcha
cho một tài khoản không hỏng gì.

Ba trạng thái phải tách bạch: 'ok' (có project_id), 'ban' (429), 'mat' (còn lại).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))


class _PhanHoi:
    def __init__(self, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self._body = body if body is not None else {}

    def json(self):
        return self._body


def _trang_thai(phan_hoi) -> str:
    """Gọi hàm thật với `requests.post` giả."""
    from services import account_recovery as ar
    with mock.patch.object(ar, "_solver_cfg", return_value=("http://solver", "k")):
        with mock.patch("requests.post", return_value=phan_hoi):
            return ar._flow_session_trang_thai("google-benbap2011")


class BaTrangThaiTests(unittest.TestCase):
    def test_429_la_BAN_chu_khong_phai_mat(self):
        # Đây là ca gây ra sự cố: hồ sơ đang tạo ảnh.
        self.assertEqual(_trang_thai(_PhanHoi(429, {"detail": "Account Busy"})), "ban")

    def test_co_project_id_la_ok(self):
        self.assertEqual(_trang_thai(_PhanHoi(200, {"project_id": "abc-123"})), "ok")

    def test_200_nhung_rong_la_mat(self):
        self.assertEqual(_trang_thai(_PhanHoi(200, {})), "mat")

    def test_loi_that_van_la_mat(self):
        self.assertEqual(_trang_thai(_PhanHoi(502, {"detail": "boom"})), "mat")

    def test_ban_khong_duoc_tinh_la_ok(self):
        """`_flow_session_ok` phải giữ nghĩa hẹp: chỉ 'ok' mới là True.

        Bận nghĩa là CHƯA chứng minh được phiên còn sống — không được nói dối
        theo chiều ngược lại chỉ để tránh báo động giả.
        """
        from services import account_recovery as ar
        with mock.patch.object(ar, "_flow_session_trang_thai", return_value="ban"):
            self.assertFalse(ar._flow_session_ok("p"))
        with mock.patch.object(ar, "_flow_session_trang_thai", return_value="ok"):
            self.assertTrue(ar._flow_session_ok("p"))


class KhongBaoDongKhiBanTests(unittest.TestCase):
    """Bận thì im lặng bỏ qua — không báo Telegram, không chạy T2."""

    def test_khong_notify_va_khong_dang_nhap_lai_khi_ban(self):
        from services import account_recovery as ar
        ar._last_attempt.clear()
        with mock.patch.object(ar, "_flow_session_trang_thai", return_value="ban") as tt, \
             mock.patch.object(ar, "_notify") as notify, \
             mock.patch.object(ar, "_freshen_google") as freshen:
            ar.flow_recover_and_notify("google-benbap2011", reason="quét định kỳ")
        tt.assert_called_once()
        notify.assert_not_called()      # không một dòng báo động nào
        freshen.assert_not_called()     # không đăng nhập lại Google vô ích

    def test_mat_that_thi_van_bao_dong_va_chay_T2(self):
        from services import account_recovery as ar
        ar._last_attempt.clear()
        with mock.patch.object(ar, "_flow_session_trang_thai", return_value="mat"), \
             mock.patch.object(ar, "_notify") as notify, \
             mock.patch.object(ar, "_freshen_google", return_value=False) as freshen:
            ar.flow_recover_and_notify("google-benbap2011", reason="quét định kỳ")
        self.assertTrue(notify.called, "mất phiên thật thì phải báo")
        freshen.assert_called_once()

    def test_khoe_thi_bao_T1_con_song(self):
        from services import account_recovery as ar
        ar._last_attempt.clear()
        with mock.patch.object(ar, "_flow_session_trang_thai", return_value="ok"), \
             mock.patch.object(ar, "_notify") as notify, \
             mock.patch.object(ar, "_freshen_google") as freshen:
            ar.flow_recover_and_notify("google-benbap2011", reason="401 lúc dùng")
        freshen.assert_not_called()
        self.assertTrue(any("còn sống" in str(c) for c in notify.call_args_list))


if __name__ == "__main__":
    unittest.main()
