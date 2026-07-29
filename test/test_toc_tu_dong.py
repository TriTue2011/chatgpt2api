"""Tự gieo mục lục khi nạp sách qua file/URL.

Vì sao có bộ test này: dropdown "chọn bài" của tab Bài giảng đọc file mục lục có
cấu trúc, mà trước bản này CHỈ có đường gieo tay (`save_toc` không endpoint nào
gọi). Hệ quả: sách nạp qua giao diện tra cứu được nhưng ô chọn bài trống — người
dùng thấy sách "đã nạp" mà không chọn được bài nào, không có gì báo vì sao.

Khuôn nhận dạng lấy từ 82 quyển đã đọc tay: dòng mục lục bộ Kết nối luôn có dạng
"<Bài|Unit|Chủ đề|Chương|Tuần> <số>. <tên> <nối> <trang>".
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ham():
    """Nạp riêng hai thứ cần dùng — module đầy đủ cần fitz/chromadb."""
    src = (ROOT / "services" / "agent" / "teacher_lecture.py").read_text("utf-8")
    i = src.index("_TOC_LINE_RE = re.compile(")
    j = src.index("def save_toc")
    ns: dict = {"re": re, "Any": object}
    exec(src[i:j].replace("dict[str, Any]", "dict"), ns)  # noqa: S102
    return ns["toc_tu_markdown"]


class TestRutMucLuc:
    def test_khuon_toan_tieu_hoc(self):
        f = _ham()
        md = (" Bài 1. Ôn tập các số đến 1 000 — 6\n"
              " Bài 2. Ôn tập phép cộng, phép trừ trong phạm vi 1 000 — 9\n"
              " Bài 3. Tìm thành phần trong phép cộng, phép trừ — 11\n")
        r = f(md, tap="tập một")
        assert [x["bai"] for x in r] == ["1", "2", "3"]
        assert r[1]["ten"] == "Ôn tập phép cộng, phép trừ trong phạm vi 1 000"
        assert r[2]["trang"] == 11
        assert r[0]["tap"] == "tập một"

    def test_khuon_unit_tieng_anh(self):
        f = _ham()
        r = f(" Unit 6. Our school facilities — 44\n Unit 7. Our timetables — 50\n")
        assert [x["bai"] for x in r] == ["Unit 6", "Unit 7"]

    def test_bo_dong_trich_dan_trong_than_sach(self):
        """"xem lại Bài 2 trang 9" KHÔNG phải mục lục — số trang thụt lùi."""
        f = _ham()
        md = (" Bài 10. Trao đổi chất qua màng tế bào — 64\n"
              "Trong bài học, xem lại Bài 2 trang 9 để đối chiếu.\n")
        r = f(md)
        assert [x["bai"] for x in r] == ["10"]

    def test_moi_so_bai_giu_ban_dau_tien(self):
        f = _ham()
        md = " Bài 5. Tên đúng ở mục lục — 20\n Bài 5. Nhắc lại ở giữa sách — 88\n"
        r = f(md)
        assert len(r) == 1 and r[0]["ten"] == "Tên đúng ở mục lục"

    def test_bo_dong_khong_phai_muc_luc(self):
        f = _ham()
        assert f("Hôm nay học Toán rất vui.\nMột hai ba bốn năm.\n") == []

    def test_trang_vo_ly_bi_bo(self):
        f = _ham()
        assert f(" Bài 1. Tên bài — 0\n") == []
        assert f(" Bài 1. Tên bài — 1234\n") == []

    def test_ten_qua_ngan_bi_bo(self):
        f = _ham()
        assert f(" Bài 1. A — 6\n") == []


class TestNoiVaoDuongNap:
    def test_import_goi_ham_gieo_muc_luc(self):
        src = (ROOT / "services" / "agent" / "teacher_workspace.py").read_text("utf-8")
        assert "toc_tu_markdown" in src, "đường nạp chưa gieo mục lục"
        assert "if not tl.toc(g, sub):" in src, \
            "phải kiểm tra mục lục đã có trước khi gieo"

    def test_khong_ghi_de_muc_luc_gieo_tay(self):
        """Bản gieo tay soát theo ảnh sách; bản tự rút phụ thuộc OCR — không được
        ghi đè bản tốt hơn bằng bản kém hơn."""
        src = (ROOT / "services" / "agent" / "teacher_workspace.py").read_text("utf-8")
        i = src.index("toc_tu_markdown")
        doan = src[i - 600:i + 400]
        assert "toc_kept" in doan or "không ghi đè" in doan.lower()
