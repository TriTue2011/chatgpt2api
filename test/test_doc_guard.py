"""Hàng rào bom tài liệu: ZIP (docx/pptx/xlsx/epub) và PDF.

Cùng loại lỗi với ảnh bom nén, chỉ khác định dạng. `.docx`/`.pptx`/`.xlsx` đều
là file ZIP; một ZIP 40 KB khai báo được vài GB sau giải nén. MarkItDown và OCR
giải nén THẬT, nên trần byte ở tầng upload không thấy gì — file thật sự nhỏ.

Dấu hiệu đặc trưng là **tỉ lệ nén**: tài liệu thật hiếm khi vượt 100:1, còn bom
nén thường 1000:1 trở lên.
"""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import doc_guard  # noqa: E402
from services.doc_guard import (  # noqa: E402
    DocRejected,
    kiem_tai_lieu,
    kiem_tai_lieu_theo_duong_dan,
)


def _zip_bom(so_byte: int = 60 * 1024 * 1024) -> bytes:
    """ZIP nhỏ chứa một entry toàn số 0 — nén cực mạnh, đúng hình dạng quả bom."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"\0" * so_byte)
    return buf.getvalue()


def _zip_binh_thuong() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", os.urandom(200_000))  # ngẫu nhiên → gần như không nén
    return buf.getvalue()


class ZipBomTests(unittest.TestCase):
    def test_ti_le_nen_bat_thuong_bi_chan(self):
        raw = _zip_bom()
        self.assertLess(len(raw), 1024 * 1024,
                        "test phải dùng file NHỎ, nếu không là kiểm nhầm trần byte")
        with self.assertRaises(DocRejected) as ctx:
            kiem_tai_lieu(raw, ten="bom.docx")
        self.assertIn("tỉ lệ nén", str(ctx.exception))

    def test_tai_lieu_that_van_qua(self):
        kiem_tai_lieu(_zip_binh_thuong(), ten="that.docx")

    def test_qua_nhieu_thanh_phan_bi_chan(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for i in range(doc_guard.MAX_ZIP_ENTRIES + 1):
                z.writestr(f"p/{i}.xml", b"x")
        with self.assertRaises(DocRejected) as ctx:
            kiem_tai_lieu(buf.getvalue(), ten="nhieu.docx")
        self.assertIn("quá nhiều thành phần", str(ctx.exception))

    def test_zip_slip_bi_chan(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("../../etc/passwd", b"x")
        with self.assertRaises(DocRejected) as ctx:
            kiem_tai_lieu(buf.getvalue(), ten="slip.docx")
        self.assertIn("đường dẫn không hợp lệ", str(ctx.exception))


class PdfTests(unittest.TestCase):
    def test_qua_nhieu_trang_bi_chan(self):
        raw = b"%PDF-1.7\n" + b"/Type /Page\n" * (doc_guard.MAX_PDF_PAGES + 5)
        with self.assertRaises(DocRejected) as ctx:
            kiem_tai_lieu(raw, ten="day.pdf")
        self.assertIn("quá nhiều trang", str(ctx.exception))

    def test_pdf_binh_thuong_van_qua(self):
        kiem_tai_lieu(b"%PDF-1.7\n" + b"/Type /Page\n" * 20, ten="ok.pdf")


class TheoDuongDanTests(unittest.TestCase):
    """Nhánh dùng thật: tệp đã nằm trên đĩa, KHÔNG được nạp cả tệp vào RAM."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _ghi(self, ten: str, raw: bytes) -> str:
        p = Path(self.tmp.name) / ten
        p.write_bytes(raw)
        return str(p)

    def test_zip_bom_tren_dia_bi_chan(self):
        with self.assertRaises(DocRejected) as ctx:
            kiem_tai_lieu_theo_duong_dan(self._ghi("bom.docx", _zip_bom()))
        self.assertIn("tỉ lệ nén", str(ctx.exception))

    def test_tai_lieu_that_tren_dia_van_qua(self):
        kiem_tai_lieu_theo_duong_dan(self._ghi("that.docx", _zip_binh_thuong()))

    def test_pdf_nhieu_trang_tren_dia_bi_chan(self):
        raw = b"%PDF-1.7\n" + b"/Type /Page\n" * (doc_guard.MAX_PDF_PAGES + 5)
        with self.assertRaises(DocRejected):
            kiem_tai_lieu_theo_duong_dan(self._ghi("day.pdf", raw))

    def test_tep_rong_bi_chan(self):
        with self.assertRaises(DocRejected):
            kiem_tai_lieu_theo_duong_dan(self._ghi("rong.pdf", b""))

    def test_dem_trang_vat_qua_ranh_gioi_khoi(self):
        """Quét theo khối 1MB: mẫu nằm vắt qua ranh giới vẫn phải đếm được."""
        dem = doc_guard.MAX_PDF_PAGES + 50
        raw = b"%PDF-1.7\n" + (b"x" * 999_999 + b"/Type /Page\n") * 3 + b"/Type /Page\n" * dem
        with self.assertRaises(DocRejected):
            kiem_tai_lieu_theo_duong_dan(self._ghi("vat.pdf", raw))


class DiemVaoChungTests(unittest.TestCase):
    def test_extract_markdown_goi_cong_kiem(self):
        """Guard phải nằm ở `extract_markdown`, KHÔNG phải `markdown_pdf_so`.

        `extract_markdown` mới là điểm vào chung của mọi kênh và nó bao cả nhánh
        Office — nhánh đó gọi MarkItDown THẲNG nên guard đặt trong
        `markdown_pdf_so` không che được. `markdown_pdf_so` lại có hợp đồng "trả
        '' để caller rơi về đường cũ", ném lỗi ở đó là phá hợp đồng.
        """
        src = (GOC / "services/pdf_intent.py").read_text(encoding="utf-8")
        self.assertIn("kiem_tai_lieu_theo_duong_dan", src)
        vi_tri_guard = src.index("kiem_tai_lieu_theo_duong_dan(pdf_path)")
        vi_tri_extract = src.index("def extract_markdown(")
        vi_tri_pdf_so = src.index("def markdown_pdf_so(")
        self.assertGreater(vi_tri_guard, vi_tri_extract,
                           "guard phải nằm TRONG extract_markdown")
        self.assertGreater(vi_tri_extract, vi_tri_pdf_so,
                           "giả định thứ tự hàm trong file đã đổi — xem lại test này")


if __name__ == "__main__":
    unittest.main()
