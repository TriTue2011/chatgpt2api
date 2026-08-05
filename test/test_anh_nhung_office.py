"""Ảnh nhúng trong .docx/.xlsx/.pptx phải ra tới bản Markdown như PDF.

markitdown bóc chữ rất tốt nhưng bỏ hẳn ảnh: một file Word đầy sơ đồ đi qua nó
chỉ còn chữ, RAG mất sạch phần hình. Ảnh nằm nguyên trong thư mục media của file
nén OOXML nên lấy ra không cần thêm thư viện nào.
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

from PIL import Image  # noqa: E402

from services import pdf_images  # noqa: E402


def _png(w: int, h: int) -> bytes:
    """PNG nhiễu ngẫu nhiên — ảnh một màu nén xuống vài trăm byte, lọt lưới lọc."""
    im = Image.frombytes("RGB", (w, h), os.urandom(w * h * 3))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _dung_file(duong_dan: Path, cac_muc: dict) -> None:
    with zipfile.ZipFile(duong_dan, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        for ten, noi_dung in cac_muc.items():
            zf.writestr(ten, noi_dung)


class AnhNhungOfficeTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.thu_muc = Path(self.tmp.name)
        kho = self.thu_muc / "kho"
        kho.mkdir()
        self._dir_goc = pdf_images._dir
        self._caption_goc = pdf_images._caption
        pdf_images._dir = lambda: kho
        pdf_images._caption = lambda jpeg: "sơ đồ khối"
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr, pdf_images, "_dir", self._dir_goc)
        self.addCleanup(setattr, pdf_images, "_caption", self._caption_goc)

    def _tao(self, ten: str, cac_muc: dict) -> str:
        p = self.thu_muc / ten
        _dung_file(p, cac_muc)
        return str(p)

    def test_docx_lay_duoc_anh_va_caption(self):
        p = self._tao("bao-cao.docx", {
            "word/document.xml": "<w:document/>",
            "word/media/image1.png": _png(200, 200),
        })
        anh = pdf_images.extract_office_images(p)
        self.assertEqual(len(anh), 1)
        self.assertEqual(anh[0]["caption"], "sơ đồ khối")
        # Ảnh phải nằm thật trên đĩa để bot gửi lại được qua image://<uuid>.
        self.assertTrue((pdf_images._dir() / f"{anh[0]['id']}.jpg").exists())

    def test_pptx_va_xlsx_cung_duong(self):
        for ten, muc in (("slide.pptx", "ppt/media/image1.png"),
                         ("so-lieu.xlsx", "xl/media/image1.png")):
            with self.subTest(ten=ten):
                p = self._tao(ten, {muc: _png(200, 200)})
                self.assertEqual(len(pdf_images.extract_office_images(p)), 1)

    def test_bo_icon_nho_va_dinh_dang_vector(self):
        p = self._tao("nhieu-rac.docx", {
            "word/media/image1.png": _png(40, 40),      # icon: nhỏ hơn _MIN_DIM
            "word/media/image2.emf": os.urandom(50_000),  # vector: PIL không mở
            "word/media/image3.png": _png(200, 200),   # ảnh thật
        })
        anh = pdf_images.extract_office_images(p)
        self.assertEqual(len(anh), 1)

    def test_sap_theo_so_tu_nhien(self):
        """image2 phải đứng trước image10 — sắp theo chuỗi thuần thì ngược lại."""
        self.assertLess(pdf_images._khoa_tu_nhien("image2.png"),
                        pdf_images._khoa_tu_nhien("image10.png"))

    def test_ton_trong_tran_so_anh(self):
        muc = {f"word/media/image{i}.png": _png(150, 150) for i in range(1, 6)}
        p = self._tao("nhieu-anh.docx", muc)
        self.assertEqual(len(pdf_images.extract_office_images(p, max_images=2)), 2)

    def test_file_khong_phai_zip_khong_no(self):
        """.doc/.xls/.ppt đời cũ không phải ZIP — trả rỗng, không ném lỗi."""
        p = self.thu_muc / "cu.doc"
        p.write_bytes(b"\xd0\xcf\x11\xe0 khong phai zip")
        self.assertEqual(pdf_images.extract_office_images(str(p)), [])

    def test_office_khong_co_anh_thi_rong(self):
        p = self._tao("chi-chu.docx", {"word/document.xml": "<w:document/>"})
        self.assertEqual(pdf_images.extract_office_images(p), [])


class MucHinhAnhTests(unittest.TestCase):
    """Office không có số trang — dòng ảnh không được ghi 'Trang 0'."""

    def test_office_khong_ghi_so_trang(self):
        md = pdf_images.markdown_section([{"id": "ab" * 8, "page": 0, "caption": "biểu đồ"}])
        self.assertNotIn("Trang", md)
        self.assertIn("![biểu đồ](image://abababababababab)", md)

    def test_pdf_van_ghi_so_trang(self):
        md = pdf_images.markdown_section([{"id": "cd" * 8, "page": 3, "caption": "ảnh"}])
        self.assertIn("- Trang 3: ![ảnh]", md)


class DuongOfficeGanAnhTests(unittest.TestCase):
    """`extract_markdown` nhánh Office phải gắn phần hình ảnh như ba nhánh PDF."""

    def _src(self) -> str:
        return (GOC / "services" / "pdf_intent.py").read_text("utf-8")

    def test_nhanh_office_goi_image_section(self):
        import ast

        src = self._src()
        ham = next(n for n in ast.parse(src).body
                   if isinstance(n, ast.FunctionDef) and n.name == "extract_markdown")
        than = ast.get_source_segment(src, ham) or ""
        dau = than.index("if la_office(pdf_path):")
        khoi = than[dau:than.index("markdown_pdf_so", dau)]
        self.assertIn("_image_section(pdf_path)", khoi)

    def test_image_section_chia_duong_theo_loai_file(self):
        src = self._src()
        than = src[src.index("def _image_section("):]
        self.assertIn("extract_office_images", than[:600])


if __name__ == "__main__":
    unittest.main()
