"""PDF số → Markdown bằng pdf-inspector, chạy CỤC BỘ, có đường lùi.

pdf-inspector là lõi Rust nạp thẳng vào tiến trình (PyO3): không gọi dịch vụ
nào, không gửi tệp đi đâu. Quan trọng với PDF của gia đình — phần lớn là giấy
tờ, học bạ, hoá đơn.

File này khoá HAI thứ:

  1. BA CỔNG rơi về đường cũ. Đường cũ có OCR còn đường mới thì không, nên đi
     nhầm đường là MẤT NỘI DUNG trong im lặng — kiểu hỏng tệ hơn nhiều so với
     chậm. Cổng: không phải `text_based`; thư viện tự báo font hỏng; markdown
     rỗng. Thiếu thư viện cũng phải rơi về đường cũ, không được vỡ.

  2. Chạy THẬT với thư viện thật (bỏ qua nếu chưa cài): dựng một PDF hợp lệ
     ngay trong test rồi đọc lại, để bản nâng cấp thư viện làm hỏng giao diện
     là biết ngay.
"""
from __future__ import annotations

import os
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import pdf_intent  # noqa: E402
import services  # noqa: E402


def _thay_pdf_to_word(gia):
    """Giả lập services.pdf_to_word cho pdf_intent.

    Chỉ vá sys.modules là KHÔNG đủ: pdf_intent dùng ``from services import
    pdf_to_word``, mà dạng này lấy THUỘC TÍNH trên gói ``services`` khi module
    con đã từng được nạp — lúc đó bản vá sys.modules bị bỏ qua và test nhận
    module thật. Trước đây may mà chưa test nào nạp nó trước; thêm một tệp test
    có nạp là hỏng ngay, đúng như đã xảy ra 18/08.
    """
    return (mock.patch.dict(sys.modules, {"services.pdf_to_word": gia}),
            mock.patch.object(services, "pdf_to_word", gia, create=True))


def pdf_toi_thieu(dong: str = "Bao cao thang Bay") -> bytes:
    """Một PDF MỘT TRANG hợp lệ, xref tính đúng offset.

    Tự dựng thay vì kèm tệp mẫu: không thêm nhị phân vào repo, và nội dung nằm
    ngay trong test nên đọc là biết đang mong chờ chữ gì.
    """
    noi_dung = f"BT /F1 24 Tf 72 700 Td ({dong}) Tj ET".encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(noi_dung)).encode() + b" >>\nstream\n"
        + noi_dung + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    ra = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(ra))
        ra += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref_at = len(ra)
    ra += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        ra += f"{off:010d} 00000 n \n".encode()
    ra += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
           f"startxref\n{xref_at}\n%%EOF\n").encode()
    return bytes(ra)


class _KetQua:
    """Giả kết quả `PdfResult` của pdf-inspector."""

    def __init__(self, **kw):
        self.pdf_type = kw.get("pdf_type", "text_based")
        self.markdown = kw.get("markdown", "# Tiêu đề\n\nnội dung")
        self.has_encoding_issues = kw.get("has_encoding_issues", False)
        self.page_count = kw.get("page_count", 1)
        self.processing_time_ms = kw.get("processing_time_ms", 5)
        self.pages_needing_ocr = kw.get("pages_needing_ocr", [])


class _ThuVienGia:
    def __init__(self, kq=None, no=None):
        self.kq, self.no, self.goi = kq or _KetQua(), no, []

    def process_pdf(self, path, pages=None):
        self.goi.append((path, pages))
        if self.no:
            raise self.no
        return self.kq


def _voi_thu_vien(tv):
    return mock.patch.dict(sys.modules, {"pdf_inspector": tv})


class BaCongRoiVeDuongCu(unittest.TestCase):
    """Đường cũ có OCR; đi nhầm đường là mất nội dung trong im lặng."""

    def test_pdf_scan_thi_KHONG_lay(self):
        with _voi_thu_vien(_ThuVienGia(_KetQua(pdf_type="scanned", markdown="lac dac"))):
            self.assertEqual(pdf_intent.markdown_pdf_so("/tmp/a.pdf"), "")

    def test_pdf_anh_thi_KHONG_lay(self):
        with _voi_thu_vien(_ThuVienGia(_KetQua(pdf_type="image_based"))):
            self.assertEqual(pdf_intent.markdown_pdf_so("/tmp/a.pdf"), "")

    def test_pdf_mixed_thi_KHONG_lay(self):
        """Trang cần OCR sẽ ra rỗng → nội dung mất mà không ai báo."""
        with _voi_thu_vien(_ThuVienGia(_KetQua(pdf_type="mixed",
                                               pages_needing_ocr=[2]))):
            self.assertEqual(pdf_intent.markdown_pdf_so("/tmp/a.pdf"), "")

    def test_thu_vien_bao_font_hong_thi_KHONG_tin(self):
        with _voi_thu_vien(_ThuVienGia(_KetQua(has_encoding_issues=True))):
            self.assertEqual(pdf_intent.markdown_pdf_so("/tmp/a.pdf"), "")

    def test_markdown_rong_thi_roi_ve_duong_cu(self):
        for md in ("", "   \n ", None):
            with _voi_thu_vien(_ThuVienGia(_KetQua(markdown=md))):
                self.assertEqual(pdf_intent.markdown_pdf_so("/tmp/a.pdf"), "", repr(md))

    def test_thu_vien_nem_loi_thi_KHONG_vo(self):
        with _voi_thu_vien(_ThuVienGia(no=RuntimeError("hỏng"))):
            self.assertEqual(pdf_intent.markdown_pdf_so("/tmp/a.pdf"), "")

    def test_chua_cai_thu_vien_thi_chay_y_nhu_truoc(self):
        with mock.patch.dict(sys.modules, {"pdf_inspector": None}):
            self.assertEqual(pdf_intent.markdown_pdf_so("/tmp/a.pdf"), "")


class DuongNhanh(unittest.TestCase):
    def test_pdf_so_thi_lay_markdown(self):
        with _voi_thu_vien(_ThuVienGia(_KetQua(markdown="# Báo cáo\n\nnội dung"))):
            self.assertIn("Báo cáo", pdf_intent.markdown_pdf_so("/tmp/a.pdf"))

    def test_max_pages_gioi_han_so_trang_doc(self):
        tv = _ThuVienGia()
        with _voi_thu_vien(tv):
            pdf_intent.markdown_pdf_so("/tmp/a.pdf", max_pages=3)
        self.assertEqual(tv.goi[-1][1], [1, 2, 3])

    def test_khong_max_pages_thi_doc_ca_tai_lieu(self):
        tv = _ThuVienGia()
        with _voi_thu_vien(tv):
            pdf_intent.markdown_pdf_so("/tmp/a.pdf")
        self.assertIsNone(tv.goi[-1][1])

    def test_max_pages_0_la_TAT_CA_trang(self):
        """0 = tất cả, theo đúng quy ước `scan_pdf_markdown` đang dùng."""
        tv = _ThuVienGia()
        with _voi_thu_vien(tv):
            pdf_intent.markdown_pdf_so("/tmp/a.pdf", max_pages=0)
        self.assertIsNone(tv.goi[-1][1])


class GhepVaoExtractMarkdown(unittest.TestCase):
    def test_di_duong_nhanh_thi_KHONG_dung_toi_duong_cu(self):
        """Đường cũ mở tài liệu bằng PyMuPDF và có thể gọi model OCR — tốn."""
        tv = _ThuVienGia(_KetQua(markdown="# Xong"))
        p2w = mock.MagicMock()
        va_sys, va_goi = _thay_pdf_to_word(p2w)
        with _voi_thu_vien(tv), va_sys, va_goi, \
             mock.patch.object(pdf_intent, "_image_section", return_value=""):
            ra = pdf_intent.extract_markdown("/tmp/a.pdf")
        self.assertEqual(ra, "# Xong")
        p2w.analyze_pdf.assert_not_called()

    def test_van_gan_muc_hinh_anh_nhu_duong_cu(self):
        """Đổi engine mà đánh rơi mục ảnh là lặng lẽ bớt nội dung."""
        with _voi_thu_vien(_ThuVienGia(_KetQua(markdown="# Xong"))), \
             mock.patch.object(pdf_intent, "_image_section",
                               return_value="\n\n## Hình ảnh trong tài liệu\n- a"):
            self.assertIn("Hình ảnh trong tài liệu",
                          pdf_intent.extract_markdown("/tmp/a.pdf"))

    def test_roi_ve_duong_cu_thi_van_chay_nhu_truoc(self):
        p2w = mock.MagicMock()
        p2w.analyze_pdf.return_value = {"scanned": True, "text_quality": "good"}
        p2w.scan_pdf_markdown.return_value = "chữ từ OCR"
        va_sys, va_goi = _thay_pdf_to_word(p2w)
        with _voi_thu_vien(_ThuVienGia(_KetQua(pdf_type="scanned"))), va_sys, va_goi:
            self.assertEqual(pdf_intent.extract_markdown("/tmp/a.pdf"), "chữ từ OCR")
        p2w.analyze_pdf.assert_called_once()


class ChayThatVoiThuVienThat(unittest.TestCase):
    """Bỏ qua khi chưa cài; CI cài đủ nên đây là lưới chống nâng cấp làm hỏng."""

    def setUp(self):
        self.pi = __import__("pytest").importorskip("pdf_inspector")

    def test_doc_duoc_pdf_tu_dung(self):
        r = self.pi.process_pdf_bytes(pdf_toi_thieu("Bao cao thang Bay 2026"))
        self.assertEqual(r.pdf_type, "text_based")
        self.assertIn("Bao cao thang Bay 2026", r.markdown or "")
        self.assertFalse(r.has_encoding_issues)

    def test_cac_truong_pipeline_dang_dua_vao_van_con(self):
        r = self.pi.process_pdf_bytes(pdf_toi_thieu())
        for truong in ("pdf_type", "markdown", "has_encoding_issues",
                       "page_count", "pages_needing_ocr", "processing_time_ms"):
            self.assertTrue(hasattr(r, truong), truong)

    def test_khong_phai_pdf_thi_nem_loi_va_pipeline_nuot(self):
        with mock.patch.object(pdf_intent, "_image_section", return_value=""):
            self.assertEqual(pdf_intent.markdown_pdf_so(__file__), "")


if __name__ == "__main__":
    unittest.main()
