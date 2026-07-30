"""Tài liệu KHÔNG theo tập phải nạp MỘT lần, không gắn nhãn tập.

Đo thật 30/07 trên taphuan, lớp 4 Toán:

    toan-4-tap-mot → sgv-toan-4.4915432412   290 trang
    toan-4-tap-hai → sgv-toan-4.4915435263   290 trang

Cùng slug `sgv-toan-4`, cùng 290 trang, chỉ khác ID: SGV Toán 4 là MỘT quyển cho
cả năm nhưng kho liệt kê dưới cả hai tập. Slug của nó KHÔNG có tập.

Nếu tin theo quyển sách học sinh cha thì nạp 580 trang cho 290 trang nội dung,
gắn hai nhãn tập khác nhau cho CÙNG một quyển. Kho có số đẹp, UI hiện "2 tập",
mà thật ra là một quyển nhân đôi — không lỗi nào báo ra.

Vở bài tập thì NGƯỢC LẠI: `vbt-toan-4-tap-mot-bai-mau` có tập trong slug, hai tập
là hai tài liệu thật, phải nạp cả hai.
"""
from __future__ import annotations

import unittest

from services.agent import sgk_bulk as sb
from services.agent import teacher_workspace as tw

SGV_T1 = "https://taphuan.nxbgd.vn/tap-huan/doc-sach/sgv-toan-4.4915432412"
SGV_T2 = "https://taphuan.nxbgd.vn/tap-huan/doc-sach/sgv-toan-4.4915435263"
VBT_T1 = "https://taphuan.nxbgd.vn/tap-huan/doc-sach/vbt-toan-4-tap-mot-bai-mau.4727378442"
VBT_T2 = "https://taphuan.nxbgd.vn/tap-huan/doc-sach/vbt-toan-4-tap-hai-bai-mau.4727381421"

B1 = {"grade": 4, "subject": "toan", "slug": "toan-4-tap-mot-939781966",
      "volume": "tập một", "book_set": ""}
B2 = {"grade": 4, "subject": "toan", "slug": "toan-4-tap-hai-939791544",
      "volume": "tập hai", "book_set": ""}


class TestNhanRaTaiLieuKhongTheoTap(unittest.TestCase):
    def test_sgv_khong_theo_tap(self):
        self.assertFalse(sb._theo_tap(SGV_T1))
        self.assertFalse(sb._theo_tap(SGV_T2))

    def test_vbt_co_theo_tap(self):
        self.assertTrue(sb._theo_tap(VBT_T1))
        self.assertTrue(sb._theo_tap(VBT_T2))

    def test_bo_id_khoi_slug(self):
        self.assertEqual(sb._slug_tai_lieu(SGV_T1), "sgv-toan-4")
        self.assertEqual(sb._slug_tai_lieu(VBT_T1), "vbt-toan-4-tap-mot-bai-mau")


class TestKhongNapHaiLan(unittest.TestCase):
    def test_sgv_hai_tap_ra_MOT_khoa(self):
        """Khoá trùng → lần thứ hai bị skip_done bỏ qua, nạp đúng một lần."""
        self.assertEqual(sb._doc_key(B1, "sgv", SGV_T1),
                         sb._doc_key(B2, "sgv", SGV_T2))

    def test_khoa_sgv_khong_chua_tap_va_khong_chua_id(self):
        k = sb._doc_key(B1, "sgv", SGV_T1)
        self.assertNotIn("tap-mot", k)
        self.assertNotIn("tap_mot", k)
        self.assertNotIn("4915432412", k)

    def test_vbt_hai_tap_van_la_HAI_khoa(self):
        """Hai tập vở bài tập là hai tài liệu thật — gộp khoá là mất một tập."""
        self.assertNotEqual(sb._doc_key(B1, "vbt", VBT_T1),
                            sb._doc_key(B2, "vbt", VBT_T2))

    def test_kind_khac_nhau_khong_gop_khoa(self):
        self.assertNotEqual(sb._doc_key(B1, "sgv", SGV_T1),
                            sb._doc_key(B1, "tap_huan", SGV_T1))


class TestNhanKhongRoTap(unittest.TestCase):
    """`import_sgk_pdf` suy `volume` TỪ NHÃN, nên nhãn sai là metadata sai."""

    def _vol(self, book, kind, url) -> str:
        return tw.detect_volume(sb._label_of(book, "toan", kind, reader_url=url))

    def test_sgv_khong_co_nhan_tap(self):
        self.assertEqual(self._vol(B1, "sgv", SGV_T1), "")
        self.assertEqual(self._vol(B2, "sgv", SGV_T2), "")

    def test_slug_cha_khong_ro_tap_vao_nhan(self):
        """Bỏ nhãn tập là CHƯA ĐỦ: slug cha `toan-4-tap-mot-…` vẫn rò chữ
        "tap-mot" và detect_volume đọc được. Phải thay bằng slug tài liệu."""
        lb = sb._label_of(B1, "toan", "sgv", reader_url=SGV_T1)
        self.assertNotIn("tap-mot", lb)
        self.assertIn("sgv-toan-4", lb)

    def test_vbt_van_giu_nhan_tap(self):
        self.assertEqual(self._vol(B1, "vbt", VBT_T1), "tập một")
        self.assertEqual(self._vol(B2, "vbt", VBT_T2), "tập hai")

    def test_khong_truyen_reader_url_thi_giu_hanh_vi_cu(self):
        """Chỗ gọi cũ không truyền reader_url — không được đổi kết quả của họ."""
        self.assertEqual(self._vol(B1, "sgv", ""), "tập một")


if __name__ == "__main__":
    unittest.main()
