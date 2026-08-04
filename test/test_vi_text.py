"""Chuẩn hoá tiếng Việt cho tìm kiếm: fold (bỏ dấu) + segment (pyvi mềm).

fold phải khớp không phụ thuộc dấu KỂ CẢ đ→d. segment phải AN TOÀN khi thiếu
pyvi (trả nguyên văn) — bật/tắt pyvi không đổi tính đúng, chỉ đổi độ mịn.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import vi_text  # noqa: E402


class Fold(unittest.TestCase):
    def test_bo_thanh_dieu_va_dau_nguyen_am(self):
        self.assertEqual(vi_text.fold("tôi có lịch"), "toi co lich")
        self.assertEqual(vi_text.fold("Học Sinh"), "hoc sinh")
        self.assertEqual(vi_text.fold("ăn ớ ũ ị ề"), "an o u i e")

    def test_fold_ca_chu_D(self):
        """đ→d là ca FTS remove_diacritics KHÔNG làm được — bắt buộc ở đây."""
        self.assertEqual(vi_text.fold("đông"), "dong")
        self.assertEqual(vi_text.fold("được đi Đà Nẵng"), "duoc di da nang")

    def test_khop_hai_chieu(self):
        """Gõ có dấu hay không dấu, fold về cùng chuỗi → khớp nhau."""
        self.assertEqual(vi_text.fold("điện nước"), vi_text.fold("dien nuoc"))

    def test_rong_khong_vo(self):
        self.assertEqual(vi_text.fold(""), "")
        self.assertEqual(vi_text.fold(None), "")


class SegmentMem(unittest.TestCase):
    def test_thieu_pyvi_tra_nguyen_van(self):
        # Giả lập pyvi không có: reset cache + patch import lỗi.
        with mock.patch.object(vi_text, "_seg", None), \
             mock.patch.object(vi_text, "_seg_tried", False), \
             mock.patch.dict(sys.modules, {"pyvi": None}):
            self.assertEqual(vi_text.segment("học sinh giỏi"), "học sinh giỏi")
            self.assertFalse(vi_text.co_pyvi())

    def test_khoa_tim_thieu_pyvi_van_fold(self):
        with mock.patch.object(vi_text, "_seg", None), \
             mock.patch.object(vi_text, "_seg_tried", True):
            # segment trả nguyên văn → khoa_tim = fold(nguyên văn)
            self.assertEqual(vi_text.khoa_tim("Điện Nước"), "dien nuoc")

    def test_segment_co_pyvi_thi_dung_no(self):
        fake = lambda s: s.replace("học sinh", "học_sinh")  # noqa: E731
        with mock.patch.object(vi_text, "_seg", fake), \
             mock.patch.object(vi_text, "_seg_tried", True):
            self.assertEqual(vi_text.segment("học sinh"), "học_sinh")
            self.assertEqual(vi_text.khoa_tim("học sinh"), "hoc_sinh")


class WikiTimKhongDau(unittest.TestCase):
    """wiki.search khớp không dấu qua vi_text.fold (không migration, xử lý đ)."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="wiki-vi-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from services.agent import wiki as w
        self.w = w
        w._reset_for_tests(self.tmp)
        self.cfg = {}
        p = mock.patch("services.config.config.get", side_effect=lambda: self.cfg)
        p.start()
        self.addCleanup(p.stop)

    def test_go_khong_dau_van_tim_ra(self):
        self.w.ingest("Lịch tiêm phòng của con vào thứ Ba", title="tiêm phòng")
        self.assertTrue(self.w.search("tiem phong"))     # gõ không dấu
        self.assertTrue(self.w.search("lich"))

    def test_khop_ca_chu_D(self):
        self.w.ingest("Hoá đơn tiền điện tháng này", title="tiền điện")
        self.assertTrue(self.w.search("tien dien"))      # điện -> dien

    def test_co_dau_van_tim_duoc(self):
        self.w.ingest("Ghi chú về xe máy màu đỏ", title="xe máy")
        self.assertTrue(self.w.search("xe máy"))


if __name__ == "__main__":
    unittest.main()
