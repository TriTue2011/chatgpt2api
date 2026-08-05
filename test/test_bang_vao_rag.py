"""Bảng trong Word/Excel phải giữ nguyên hàng khi vào kho RAG.

`_md_from_pdf_text` gộp các dòng liền nhau thành một đoạn văn — đúng cho văn
xuôi bóc từ PDF, sai cho bảng. Đo trên đầu ra markitdown của một .xlsx: 9 hàng
bảng vào, 2 dòng ra, không còn biết ô nào thuộc hàng nào. Excel gần như chỉ toàn
bảng nên mất bảng là mất gần hết nội dung nạp vào kho.
"""
import os
import re
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent.teacher_workspace import _md_from_pdf_text  # noqa: E402

MD_EXCEL = """## Bảng lương

| Họ tên | Bộ phận | Lương |
| --- | --- | --- |
| Nguyễn Văn A | Kỹ thuật | 25000000 |
| Trần Thị B | Kinh doanh | 18000000 |
| Lê Văn C | Kỹ thuật | 30000000 |

## Chấm công

| Họ tên | Ngày công |
| --- | --- |
| Nguyễn Văn A | 22 |
| Trần Thị B | 20 |
"""


def _dong_bang(md: str) -> list:
    return [d.strip() for d in md.splitlines() if d.strip().startswith("|")]


class BangGiuNguyenHangTests(unittest.TestCase):

    def test_du_so_hang_bang(self):
        ra = _md_from_pdf_text(MD_EXCEL, title="Bảng lương tháng 7")
        self.assertEqual(len(_dong_bang(ra)), len(_dong_bang(MD_EXCEL)))

    def test_moi_hang_dung_mot_dong_rieng(self):
        ra = _md_from_pdf_text(MD_EXCEL, title="Bảng lương tháng 7")
        self.assertIn("| Nguyễn Văn A | Kỹ thuật | 25000000 |", ra.splitlines())
        # Dấu hiệu bị dồn: một dòng chứa hai hàng khác nhau.
        for d in _dong_bang(ra):
            self.assertNotIn("| |", d, f"hai hàng bị dồn chung một dòng: {d}")

    def test_co_dong_trong_truoc_bang(self):
        """Thiếu dòng trống phía trên thì markdown không nhận ra đó là bảng."""
        ra = _md_from_pdf_text(MD_EXCEL, title="Bảng lương tháng 7")
        dong = ra.splitlines()
        for i, d in enumerate(dong):
            if d.startswith("|") and i and not dong[i - 1].startswith("|"):
                self.assertEqual(dong[i - 1].strip(), "",
                                 "bảng phải có một dòng trống phía trên")

    def test_van_giu_heading_theo_muc(self):
        ra = _md_from_pdf_text(MD_EXCEL, title="Bảng lương tháng 7")
        self.assertEqual(len(re.findall(r"^##\s+", ra, re.M)), 2)


class VanXuoiVanGopNhuCuTests(unittest.TestCase):
    """Chỉ hàng bảng được tách — văn xuôi bóc từ PDF vẫn gộp thành đoạn như cũ."""

    def test_dong_van_xuoi_van_gop_thanh_doan(self):
        raw = "Bài 1: Số tự nhiên\nDòng một của đoạn\nDòng hai của đoạn\n"
        ra = _md_from_pdf_text(raw, title="Toán 4")
        self.assertIn("Dòng một của đoạn Dòng hai của đoạn", ra)


if __name__ == "__main__":
    unittest.main()
