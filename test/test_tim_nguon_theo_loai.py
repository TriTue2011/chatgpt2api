"""Tìm nguồn theo ĐÚNG LOẠI SÁCH (SGK / SGV / vở bài tập / tập huấn).

Lỗi đang khoá lại: `find_sources` cũ chỉ có câu tìm riêng cho "sgk" và "nangcao";
sgv/vbt/tap_huan rơi vào nhánh mặc định và đi tìm đúng chữ "sách giáo khoa" — trả
về sách HỌC SINH rồi nạp vào kho SGV/VBT. Kho có số, nhãn ghi đúng loại, mà nội
dung sai quyển: bot đem sách của học sinh ra làm hướng dẫn cho giáo viên. Không
có lỗi nào để lần ra.

Phần xếp hạng cũng phải biết loại: `terms` chỉ chấm lớp–môn–bộ sách–năm nên SGK và
SGV cùng lớp cùng môn được điểm BẰNG NHAU.
"""
from __future__ import annotations

import unittest

from services.agent import sgk_fetch as sf


class TestCauTimTheoLoai(unittest.TestCase):
    def test_moi_loai_co_cum_tu_rieng(self):
        for kind in ("sgv", "vbt", "tap_huan"):
            with self.subTest(kind):
                self.assertIn(kind, sf._KIND_PHRASES)
                self.assertTrue(sf._KIND_PHRASES[kind])

    def test_sgv_hoi_bang_sach_giao_vien_khong_phai_sach_giao_khoa(self):
        cum = " ".join(sf._KIND_PHRASES["sgv"]).lower()
        self.assertIn("sách giáo viên", cum)
        self.assertNotIn("sách giáo khoa", cum)

    def test_sgv_co_ca_ten_hanh_chinh_khbd(self):
        """Nhiều nơi đăng dưới tên 'kế hoạch bài dạy' chứ không ghi 'sách giáo
        viên' — thiếu cụm này là mất một nhóm nguồn lớn."""
        cum = " ".join(sf._KIND_PHRASES["sgv"]).lower()
        self.assertTrue("kế hoạch bài dạy" in cum or "khbd" in cum)


class TestXepHangTheoLoai(unittest.TestCase):
    def _diem(self, title: str, kind: str) -> float:
        return sf._score_candidate(
            "https://x.tld/a.pdf", title, 4, "toán", "", "", kind,
        )["confidence"]

    def test_tim_sgv_thi_sgv_phai_tren_sgk(self):
        sgv = self._diem("Sách giáo viên Toán 4 pdf", "sgv")
        sgk = self._diem("Sách giáo khoa Toán 4 pdf", "sgv")
        self.assertGreater(sgv, sgk,
                           f"SGV {sgv} phải cao hơn SGK {sgk} khi đang tìm SGV")

    def test_tim_sgk_thi_sgk_phai_tren_sgv(self):
        sgk = self._diem("Sách giáo khoa Toán 4 pdf", "sgk")
        sgv = self._diem("Sách giáo viên Toán 4 pdf", "sgk")
        self.assertGreater(sgk, sgv,
                           f"SGK {sgk} phải cao hơn SGV {sgv} khi đang tìm SGK")

    def test_tim_vbt_thi_vo_bai_tap_phai_tren_sgk(self):
        vbt = self._diem("Vở bài tập Toán 4 pdf", "vbt")
        sgk = self._diem("Sách giáo khoa Toán 4 pdf", "vbt")
        self.assertGreater(vbt, sgk)

    def test_khbd_cung_duoc_cong_diem_khi_tim_sgv(self):
        khbd = self._diem("Kế hoạch bài dạy KHBD Toán 4 pdf", "sgv")
        tron = self._diem("Toán 4 pdf", "sgv")
        self.assertGreater(khbd, tron)

    def test_khong_loai_han_khi_thieu_cum_trong_tieu_de(self):
        """Hạ điểm, KHÔNG loại hẳn: có nơi tiêu đề thiếu chữ mà tên tệp lại đúng.
        Loại hẳn là tự bỏ nguồn dùng được."""
        self.assertGreater(self._diem("Toán 4 Kết nối tri thức pdf", "sgv"), 0)


if __name__ == "__main__":
    unittest.main()
