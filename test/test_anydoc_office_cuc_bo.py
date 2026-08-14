"""Tệp Office → Markdown bằng anydoc, chạy CỤC BỘ, có đường lùi markitdown.

anydoc là lõi Rust nạp thẳng vào tiến trình (PyO3), cùng nhà với pdf-inspector:
không dựng thêm tiến trình, không mở cổng, không gửi tệp đi đâu. Quan trọng vì
đây là đường mà tài liệu người lạ gửi tới bot đi qua.

File này khoá BỐN thứ:

  1. BỐN CỔNG rơi về markitdown. Khác nhánh PDF, ở đây đi nhầm đường KHÔNG mất
     nội dung (markitdown vẫn đọc ra chữ) — nhưng rơi mà không có ai đỡ thì tệp
     đính kèm ra rỗng và người dùng không biết vì sao. Cổng: thiếu thư viện;
     anydoc không nhận định dạng; tệp hỏng/đặt mật khẩu; Markdown ra rỗng.

  2. anydoc ĐI TRƯỚC markitdown. Đây là toàn bộ lý do của bản thay đổi:
     markitdown nối chữ từng đoạn nên mất bảng. Nếu ai đó đảo thứ tự thì tính
     năng biến mất mà mọi test khác vẫn xanh.

  3. Mục hình ảnh vẫn được gắn. Cả anydoc lẫn markitdown đều chỉ trả CHỮ, ảnh
     do `_image_section` lấy riêng — đổi engine mà đánh rơi mục ảnh là lặng lẽ
     bớt nội dung.

  4. Chạy THẬT với thư viện thật (bỏ qua nếu chưa cài): dựng một .docx hợp lệ
     CÓ BẢNG ngay trong test rồi đọc lại. Bảng là thứ duy nhất biện minh cho
     việc thêm thư viện này, nên nó phải có test chứng minh.
"""
from __future__ import annotations

import io
import os
import pathlib
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import pdf_intent  # noqa: E402

_NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def docx_toi_thieu(tieu_de: str = "Bao cao thang Bay",
                   bang: tuple[tuple[str, str], ...] = (("Ten", "So"),
                                                        ("Hoa don", "12"))) -> bytes:
    """Một .docx hợp lệ tối thiểu, có MỘT bảng. Tự dựng thay vì kèm tệp mẫu:
    không thêm nhị phân vào repo, và nội dung nằm ngay trong test nên đọc là
    biết đang mong chờ chữ gì (cùng lối với `pdf_toi_thieu`)."""
    def o(v: str) -> str:
        return (f'<w:tc><w:p><w:r><w:t>{v}</w:t></w:r></w:p></w:tc>')

    hang = "".join(f"<w:tr>{o(a)}{o(b)}</w:tr>" for a, b in bang)
    doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_NS_W}"><w:body>'
        f'<w:p><w:r><w:t>{tieu_de}</w:t></w:r></w:p>'
        f'<w:tbl>{hang}</w:tbl>'
        '</w:body></w:document>'
    )
    ct = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{_NS_CT}">'
        '<Default Extension="rels" ContentType="application/vnd.'
        'openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_NS_REL}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


# Bốn lớp lỗi anydoc thật sự ném ra (xem python/anydoc/_anydoc.pyi của họ).
# Code chỉ bắt `Exception` nên tên lớp không đổi hành vi — nhưng nó VÀO LOG, và
# log là thứ duy nhất để biết vì sao một tệp rơi về đường lùi.
class UnsupportedError(Exception):
    pass


class EncryptedError(Exception):
    pass


class MalformedError(Exception):
    pass


class ResourceLimitError(Exception):
    pass


class _ThuVienGia:
    def __init__(self, md: str | None = "# Tiêu đề\n\n| a | b |\n| - | - |", no=None):
        self.md, self.no, self.goi = md, no, []

    def to_markdown(self, path):
        self.goi.append(path)
        if self.no:
            raise self.no
        return self.md


def _voi_thu_vien(tv):
    return mock.patch.dict(sys.modules, {"anydoc": tv})


class BonCongRoiVeMarkitdown(unittest.TestCase):
    def test_chua_cai_thu_vien_thi_roi_ve_duong_lui(self):
        with mock.patch.dict(sys.modules, {"anydoc": None}):
            self.assertEqual(pdf_intent.markdown_office_so("/tmp/a.docx"), "")

    def test_khong_nhan_dinh_dang_thi_roi_ve_duong_lui(self):
        """.xls nhị phân cũ và .html KHÔNG nằm trong bảng định dạng anydoc."""
        for duoi in (".xls", ".html"):
            with _voi_thu_vien(_ThuVienGia(no=UnsupportedError("không nhận"))):
                self.assertEqual(pdf_intent.markdown_office_so("/tmp/a" + duoi), "", duoi)

    def test_tep_hong_hay_dat_mat_khau_thi_roi_ve_duong_lui(self):
        for loi in (EncryptedError("có mật khẩu"), MalformedError("hỏng"),
                    ResourceLimitError("quá hạn"), RuntimeError("gì đó")):
            with _voi_thu_vien(_ThuVienGia(no=loi)):
                self.assertEqual(pdf_intent.markdown_office_so("/tmp/a.docx"), "",
                                 type(loi).__name__)

    def test_markdown_rong_thi_roi_ve_duong_lui(self):
        for md in ("", "   \n ", None):
            with _voi_thu_vien(_ThuVienGia(md=md)):
                self.assertEqual(pdf_intent.markdown_office_so("/tmp/a.docx"), "",
                                 repr(md))


class DuongNhanh(unittest.TestCase):
    def test_doc_duoc_thi_lay_markdown(self):
        with _voi_thu_vien(_ThuVienGia(md="# Báo cáo\n\n| Tên | Số |")):
            ra = pdf_intent.markdown_office_so("/tmp/a.docx")
        self.assertIn("Báo cáo", ra)
        self.assertIn("| Tên | Số |", ra)

    def test_KHONG_tu_gan_muc_hinh_anh(self):
        """Hợp đồng giống `markdown_pdf_so`: gắn ảnh là việc của caller."""
        with _voi_thu_vien(_ThuVienGia(md="# Xong")), \
             mock.patch.object(pdf_intent, "_image_section",
                               return_value="\n\nKHONG_DUOC_CO"):
            self.assertEqual(pdf_intent.markdown_office_so("/tmp/a.docx"), "# Xong")


class GhepVaoExtractMarkdown(unittest.TestCase):
    """Nhánh Office của `extract_markdown`: anydoc trước, markitdown sau."""

    @staticmethod
    def _markitdown_gia(text: str = "chữ phẳng, mất bảng"):
        mi = mock.MagicMock()
        mi.MarkItDown.return_value.convert.return_value.text_content = text
        return mock.patch.dict(sys.modules, {"markitdown": mi}), mi

    def test_anydoc_doc_duoc_thi_KHONG_goi_markitdown(self):
        """Đảo thứ tự là mất bảng — cả lý do của bản thay đổi nằm ở đây."""
        va, mi = self._markitdown_gia()
        with _voi_thu_vien(_ThuVienGia(md="# Có bảng\n\n| a | b |")), va, \
             mock.patch.object(pdf_intent, "_image_section", return_value=""):
            ra = pdf_intent.extract_markdown("/tmp/a.docx")
        self.assertEqual(ra, "# Có bảng\n\n| a | b |")
        mi.MarkItDown.assert_not_called()

    def test_anydoc_khong_nhan_thi_markitdown_do(self):
        va, mi = self._markitdown_gia("chữ từ markitdown")
        with _voi_thu_vien(_ThuVienGia(no=UnsupportedError("không nhận"))), va, \
             mock.patch.object(pdf_intent, "_image_section", return_value=""):
            ra = pdf_intent.extract_markdown("/tmp/a.xls")
        self.assertEqual(ra, "chữ từ markitdown")
        mi.MarkItDown.assert_called_once()

    def test_ca_hai_duong_hong_thi_tra_rong_chu_khong_vo(self):
        mi = mock.MagicMock()
        mi.MarkItDown.side_effect = RuntimeError("markitdown cũng hỏng")
        with _voi_thu_vien(_ThuVienGia(no=UnsupportedError("không nhận"))), \
             mock.patch.dict(sys.modules, {"markitdown": mi}):
            self.assertEqual(pdf_intent.extract_markdown("/tmp/a.docx"), "")

    def test_van_gan_muc_hinh_anh_nhu_truoc(self):
        """Cả hai engine chỉ trả CHỮ; ảnh do _image_section lấy riêng."""
        va, _ = self._markitdown_gia()
        with _voi_thu_vien(_ThuVienGia(md="# Xong")), va, \
             mock.patch.object(pdf_intent, "_image_section",
                               return_value="\n\n## Hình ảnh trong tài liệu\n- a"):
            ra = pdf_intent.extract_markdown("/tmp/a.pptx")
        self.assertIn("Hình ảnh trong tài liệu", ra)

    def test_nhanh_office_KHONG_xuong_hai_buoc_pdf(self):
        """Hai bước PDF chắc chắn hỏng với .docx — xuống đó là mở file vô ích."""
        va, _ = self._markitdown_gia()
        p2w = mock.MagicMock()
        with _voi_thu_vien(_ThuVienGia(md="# Xong")), va, \
             mock.patch.dict(sys.modules, {"services.pdf_to_word": p2w}), \
             mock.patch.object(pdf_intent, "_image_section", return_value=""):
            pdf_intent.extract_markdown("/tmp/a.docx")
        p2w.analyze_pdf.assert_not_called()


class ChayThatVoiThuVienThat(unittest.TestCase):
    """Bỏ qua khi chưa cài (máy dev chỉ có Python 3.9, anydoc đòi ≥3.10).
    Image chạy Python 3.13 nên đây là lưới chống nâng cấp thư viện làm hỏng."""

    def setUp(self):
        self.ad = __import__("pytest").importorskip("anydoc")

    def _tep(self, data: bytes, duoi: str) -> str:
        f = tempfile.NamedTemporaryFile(suffix=duoi, delete=False)
        f.write(data)
        f.close()
        self.addCleanup(lambda: os.path.exists(f.name) and os.unlink(f.name))
        return f.name

    def test_doc_duoc_docx_tu_dung_va_GIU_BANG(self):
        p = self._tep(docx_toi_thieu("Bao cao thang Bay 2026"), ".docx")
        md = pdf_intent.markdown_office_so(p)
        self.assertIn("Bao cao thang Bay 2026", md)
        for o in ("Ten", "So", "Hoa don", "12"):
            self.assertIn(o, md, o)
        # Bảng phải ra CÚ PHÁP BẢNG của GFM, không phải chữ phẳng — đây đúng là
        # thứ markitdown làm mất và là lý do thêm thư viện này.
        self.assertIn("|", md)

    def test_cac_ham_pipeline_dang_dua_vao_van_con(self):
        for ten in ("to_markdown", "to_markdown_bytes", "to_document",
                    "format_from_path"):
            self.assertTrue(hasattr(self.ad, ten), ten)

    def test_khong_phai_tai_lieu_thi_tra_rong_chu_khong_vo(self):
        self.assertEqual(pdf_intent.markdown_office_so(__file__), "")


if __name__ == "__main__":
    unittest.main()
