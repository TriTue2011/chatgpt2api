"""Nhiều API key cho backend tìm kiếm, xoay khi hết hạn mức.

Brave cho 2.000 request/tháng, Serper 2.500 — hết là backend đó câm cho tới
tháng sau. Trước bản này cả hai chỉ đọc ĐÚNG MỘT `api_key`, nên có thêm khoá
cũng vô ích.

Đo trên máy chủ 08/08/2026, tìm "thời tiết Hà Nội hôm nay": gemini grounding
rỗng (429), serper rỗng (chưa khoá), brave rỗng (chưa khoá) — chỉ SearXNG và
MCP trả kết quả. Nên đường có khoá cần chịu tải tốt hơn, không phải chết ở
khoá đầu tiên.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.search_service import XoayKhoa  # noqa: E402

TRANG = (GOC / "web/src/app/search/page.tsx").read_text(encoding="utf-8")


class XoayKhoaTests(unittest.TestCase):
    def setUp(self):
        from services.config import config
        self.config = config
        self._cu = config.data
        self.addCleanup(lambda: setattr(config, "data", self._cu))
        self.xoay = XoayKhoa("brave")

    def _dat(self, **gemini_free):
        self.config.data = {"providers": {"brave": gemini_free}}

    def test_gop_api_key_don_va_api_keys(self):
        self._dat(api_key="k1", api_keys=["k2", "k3"])
        self.assertEqual(self.xoay.danh_sach(), ["k1", "k2", "k3"])

    def test_khong_lap_khoa_khi_don_da_nam_trong_danh_sach(self):
        self._dat(api_key="k1", api_keys=["k1", "k2"])
        self.assertEqual(self.xoay.danh_sach(), ["k1", "k2"])

    def test_chi_co_api_key_don_van_chay(self):
        self._dat(api_key="k1")
        self.assertEqual(self.xoay.danh_sach(), ["k1"])

    def test_khong_co_khoa_thi_rong(self):
        self._dat()
        self.assertEqual(self.xoay.kha_dung(), [])

    def test_khoa_bi_treo_thi_khong_duoc_dung(self):
        self._dat(api_keys=["k1", "k2"])
        self.xoay.treo_khoa("k1", "HTTP 429")
        self.assertEqual(self.xoay.kha_dung(), ["k2"])

    def test_treo_het_han_thi_dung_lai_duoc(self):
        self._dat(api_keys=["k1"])
        self.xoay.treo_khoa("k1", "HTTP 429")
        self.xoay._treo["k1"] = time.time() - 1
        self.assertEqual(self.xoay.kha_dung(), ["k1"])

    def test_XOAY_VONG_chu_khong_luon_bat_dau_tu_khoa_dau(self):
        """Luôn bắt đầu từ khoá #1 thì nó gánh hết lưu lượng và hết hạn trước."""
        self._dat(api_keys=["k1", "k2", "k3"])
        dau = [self.xoay.kha_dung()[0] for _ in range(3)]
        self.assertEqual(dau, ["k1", "k2", "k3"], f"không xoay vòng: {dau}")

    def test_treo_het_moi_khoa_thi_tra_rong(self):
        self._dat(api_keys=["k1", "k2"])
        self.xoay.treo_khoa("k1")
        self.xoay.treo_khoa("k2")
        self.assertEqual(self.xoay.kha_dung(), [])


class BackendDungXoayKhoaTests(unittest.TestCase):
    def _than(self, ten_lop: str) -> str:
        src = (GOC / "services/search_service.py").read_text(encoding="utf-8")
        i = src.index(f"class {ten_lop}(SearchBackend):")
        return src[i:i + 2200]

    def test_brave_va_serper_deu_xoay(self):
        for lop, pid in (("BraveSearch", "brave"), ("SerperSearch", "serper")):
            than = self._than(lop)
            self.assertIn(f'XoayKhoa("{pid}")', than, f"{lop} chưa xoay khoá")
            self.assertIn("for api_key in khoa_ds", than)

    def test_gap_429_thi_THU_KHOA_KE_TIEP_chu_khong_bo_cuoc(self):
        for lop in ("BraveSearch", "SerperSearch"):
            than = self._than(lop)
            i = than.index("429")
            self.assertIn("continue", than[i:i + 260], f"{lop} bỏ cuộc ngay ở 429")

    def test_KHONG_dung_de_quy_de_thu_lai(self):
        """`GeminiGrounding` bản cũ gọi lại chính nó sau mỗi 429 — đúng cái đã
        phải sửa ở `providers/gemini_free.py`: mỗi lần thử lại chồng một khung
        stack, và ngoại lệ thật bị chôn dưới chuỗi lời gọi dài."""
        for lop in ("BraveSearch", "SerperSearch"):
            self.assertNotIn("return self.search(", self._than(lop))


class GiaoDienTabSearchTests(unittest.TestCase):
    def test_co_o_nhap_nhieu_khoa(self):
        self.assertIn("BACKEND_CAN_KHOA", TRANG)
        self.assertIn("Mỗi dòng một khoá", TRANG)

    def test_chi_hien_o_nhap_cho_backend_DANG_dung(self):
        self.assertIn("combo.filter((b) => BACKEND_CAN_KHOA[b])", TRANG)

    def test_chi_LUU_backend_dang_trong_combo(self):
        """Gửi cả backend đã bỏ ra sẽ ghi đè cấu hình của chúng bằng rỗng."""
        i = TRANG.index("async function save")
        self.assertIn("combo.includes(ten)", TRANG[i:i + 1400])

    def test_KHONG_con_o_gemini_rieng_o_tab_nay(self):
        """Hai chỗ sửa cùng một trường thì sớm muộn cũng lệch nhau — và ô ở đây
        chỉ nhận MỘT khoá, nên lưu từ đây sẽ đè danh sách nhiều khoá bên Cài
        đặt."""
        self.assertNotIn("setGeminiKey", TRANG)
        self.assertIn("Cài đặt → Gemini", TRANG)

    def test_searxng_khong_bi_doi_khoa(self):
        """SearXNG tự host, không có API key nào để mà nhập."""
        i = TRANG.index("BACKEND_CAN_KHOA")
        self.assertNotIn("searxng", TRANG[i:i + 400])


if __name__ == "__main__":
    unittest.main()
