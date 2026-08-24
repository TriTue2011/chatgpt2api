"""Tự xoá tin: phải nhớ tin ĐÃ GỬI và phải giữ luật cho các lần sau.

Đo thật 24/08/2026 trên khung chat Zalo cá nhân:

  06:23  người dùng: "Tin tức hôm nay"        → bot gửi bản tin
  06:23  người dùng: "Tự động xóa phản hồi tin tức hôm nay sau 15 phút"
  06:24  bot: "em chưa có công cụ tự xoá phản hồi trong khung chat này"

Bản cũ chỉ hẹn xoá được câu trả lời của ĐÚNG lượt đang chạy, mà câu người dùng
nói lại về tin đã gửi xong ở lượt trước. Chủ máy chốt thêm: "thu hồi này là
thực hiện cả sau này, trừ khi user yêu cầu xoá yêu cầu" — nên luật phải sống
qua các lượt sau, và do CODE áp chứ không nhờ model nhớ gọi lại công cụ.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth-key")

from services import zalo_personal as zp            # noqa: E402
from services.agent import capabilities as caps     # noqa: E402

ACC = "own-1"
THREAD = "6643404425553198601"
KHOA = f"zalop:{ACC}:{THREAD}"


class _LuatGia:
    """Kho luật trong RAM, thay cho config.json."""

    def __init__(self, ban_dau: dict | None = None):
        self.data = {zp._KHOA_LUAT_TU_XOA: dict(ban_dau or {})}

    def __enter__(self):
        self._p1 = mock.patch.object(zp, "_cfg", side_effect=lambda: self.data)
        self._p2 = mock.patch.object(zp.config, "update", side_effect=self.data.update)
        self._p1.start()
        self._p2.start()
        zp._msg_ctx.account = ACC
        zp._msg_ctx.thread_id = THREAD
        zp._msg_ctx.thread_type = 0
        zp.dat_ttl_luot_nay(0)
        return self

    def __exit__(self, *a):
        self._p1.stop()
        self._p2.stop()

    @property
    def luat(self) -> dict:
        return self.data.get(zp._KHOA_LUAT_TU_XOA) or {}


class LuatTheoTuKhoaTests(unittest.TestCase):
    """Luật nêu 'tin tức' thì chỉ bắt tin tức — không quét sạch mọi câu trả lời."""

    def test_khong_co_luat_thi_khong_ap_gi(self):
        with _LuatGia():
            self.assertEqual(zp.ap_luat_tu_xoa(ACC, THREAD, "Tin tức hôm nay"), 0)
            self.assertEqual(zp.ttl_luot_nay(), 0)

    def test_khop_tu_khoa_thi_dat_ttl_cho_luot(self):
        with _LuatGia({KHOA: {"giay": 900, "tu_khoa": ["tin tức"]}}):
            self.assertEqual(zp.ap_luat_tu_xoa(ACC, THREAD, "Tin tức hôm nay"), 900)
            self.assertEqual(zp.ttl_luot_nay(), 900_000)

    def test_khong_ke_dau_va_hoa_thuong(self):
        with _LuatGia({KHOA: {"giay": 900, "tu_khoa": ["tin tức"]}}):
            self.assertEqual(zp.ap_luat_tu_xoa(ACC, THREAD, "cho xem TIN TUC nào"), 900)

    def test_lech_chu_de_thi_khong_dung_toi(self):
        with _LuatGia({KHOA: {"giay": 900, "tu_khoa": ["tin tức"]}}):
            self.assertEqual(zp.ap_luat_tu_xoa(ACC, THREAD, "Thời tiết hôm nay?"), 0)
            self.assertEqual(zp.ttl_luot_nay(), 0)

    def test_khong_neu_tu_khoa_thi_ap_moi_cau(self):
        with _LuatGia({KHOA: {"giay": 60, "tu_khoa": []}}):
            self.assertEqual(zp.ap_luat_tu_xoa(ACC, THREAD, "chào em"), 60)

    def test_khung_chat_khac_khong_bi_lay(self):
        with _LuatGia({KHOA: {"giay": 900, "tu_khoa": []}}):
            self.assertEqual(zp.ap_luat_tu_xoa(ACC, "khung-khac", "Tin tức hôm nay"), 0)


class CongCuTuXoaTests(unittest.TestCase):
    def _goi(self, args: dict, thu_hoi=None):
        gia = thu_hoi or (lambda *a, **kw: {"ok": True, "so_tin": 1})
        with mock.patch.object(zp, "hen_thu_hoi_tin_da_gui", side_effect=gia) as m:
            ra = caps.get("tu_xoa_tin").handler(args, {"channel": "zalo"})
        return ra, m

    def test_dat_ca_ba_phan_trong_mot_lan_goi(self):
        """Lượt này + tin đã gửi + luật lâu dài."""
        with _LuatGia() as kho:
            ra, m = self._goi({"sau_bao_lau": "15 phút", "ap_cho": "tin tức"})
            self.assertEqual(zp.ttl_luot_nay(), 900_000, "quên lượt đang chạy")
            m.assert_called_once()
            self.assertEqual(m.call_args.args[0], THREAD)
            self.assertEqual(m.call_args.args[1], 900)
            self.assertEqual(kho.luat[KHOA]["giay"], 900, "không giữ luật cho lần sau")
            self.assertEqual(kho.luat[KHOA]["tu_khoa"], ["tin tức"])
        self.assertIn("15 phút", ra.get("text") or "")

    def test_khong_thu_hoi_duoc_tin_cu_thi_noi_ra(self):
        """Im lặng ở đây là người dùng tưởng tin cũ cũng sẽ tự mất."""
        with _LuatGia():
            ra, _ = self._goi({"sau_giay": 120},
                              thu_hoi=lambda *a, **kw: {"ok": False,
                                                        "error": "khong con nho tin nao"})
        self.assertIn("chưa thu hồi được", ra.get("text") or "")

    def test_chi_lan_nay_thi_khong_dat_luat(self):
        with _LuatGia() as kho:
            self._goi({"sau_giay": 60, "lau_dai": False})
            self.assertEqual(kho.luat, {}, "không xin lâu dài mà vẫn ghi luật")
            self.assertEqual(zp.ttl_luot_nay(), 60_000)

    def test_khong_dung_toi_tin_cu_khi_bao_khong(self):
        with _LuatGia():
            _, m = self._goi({"sau_giay": 60, "tin_da_gui": 0})
            m.assert_not_called()

    def test_tat_thi_bo_han_luat(self):
        with _LuatGia({KHOA: {"giay": 900, "tu_khoa": ["tin tức"]}}) as kho:
            ra, _ = self._goi({"tat": True})
            self.assertEqual(kho.luat, {}, "bảo thôi mà luật vẫn còn")
            self.assertEqual(zp.ttl_luot_nay(), 0)
        self.assertIn("bỏ hẳn", ra.get("text") or "")

    def test_hoi_khong_kem_tham_so_thi_bao_dang_dat_gi(self):
        with _LuatGia({KHOA: {"giay": 900, "tu_khoa": ["tin tức"]}}):
            ra, _ = self._goi({})
            self.assertIn("15 phút", ra.get("text") or "")
            self.assertIn("tin tức", ra.get("text") or "")

    def test_kenh_khac_zalo_thi_noi_that(self):
        ra = caps.get("tu_xoa_tin").handler({"sau_giay": 60}, {"channel": "telegram"})
        self.assertIn("Zalo", ra.get("text") or "")


if __name__ == "__main__":
    unittest.main()
