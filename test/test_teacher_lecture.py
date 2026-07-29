"""Bài giảng hai khung: các bất biến giữ cho nó không dạy sai và không trắng khung.

Kiểm theo NGUỒN (không import module — kéo theo cả config/storage), đủ để khoá:
  1. Lớp lấy từ HỒ SƠ học sinh, không nhận từ tham số — nhận từ ngoài là mở
     đường soạn bài lớp 5 cho em lớp 2 chỉ vì UI truyền nhầm.
  2. SGV chỉ vào lời cô: prompt phải cấm chép lời SGV vào text học sinh.
  3. Trang: model chỉ được ghi trang THẤY trong tư liệu, không đoán.
  4. Offset trang in ↔ thứ tự ảnh do MỘT nơi phát (PAGE_OFFSET) và trả ra API —
     UI cộng, không tự đoán (đo thật: bìa là ảnh 1, in = thứ tự − 1).
  5. `books_for` đọc đúng khoá của `list_books` ({url, subjects tuple}) và đếm
     `pages` bằng len — đã từng viết sai thành detail_url/subject/int(list).
  6. Bốn route mới có mặt và đều require_admin + threadpool.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pytestmark = pytest.mark.pure

_TL = (_ROOT / "services" / "agent" / "teacher_lecture.py").read_text(encoding="utf-8")
_API = (_ROOT / "api" / "teacher.py").read_text(encoding="utf-8")
_UI = (_ROOT / "web" / "src" / "app" / "teacher" / "lecture-tab.tsx").read_text(encoding="utf-8")
_PAGE = (_ROOT / "web" / "src" / "app" / "teacher" / "page.tsx").read_text(encoding="utf-8")


class TestLopTuHoSo:
    def test_generate_khong_nhan_grade(self):
        i = _TL.index("def generate(")
        sig = _TL[i:_TL.index(")", i)]
        assert "grade" not in sig, "lớp phải lấy từ hồ sơ, không nhận từ ngoài"

    def test_lay_lop_tu_list_students(self):
        i = _TL.index("def generate(")
        body = _TL[i:i + 2500]
        assert "list_students" in body and 'stu.get("grade")' in body


class TestPromptDungVaiKho:
    def test_cam_chep_sgv_vao_loi_hoc_sinh(self):
        assert "không chép lời SGV" in _TL

    def test_cam_doan_trang(self):
        assert "không đoán trang" in _TL.replace("TUYỆT ĐỐI ", "")

    def test_hoi_dung_tool_theo_vai(self):
        for tool in ("ask_sgk", "ask_sgv", "ask_phan_bo"):
            assert tool in _TL, tool


class TestOffsetTrang:
    def test_mot_noi_phat_offset(self):
        assert "PAGE_OFFSET = 1" in _TL
        assert '"offset": PAGE_OFFSET' in _TL

    def test_ui_cong_offset_khong_tu_doan(self):
        assert "p + book.offset" in _UI
        assert "offset: number" in _UI


class TestBooksForDungKhoa:
    """list_books trả {slug,url,subjects,volume,book_set,grade} — đã từng viết
    sai thành detail_url/subject và int(list) nổ TypeError."""

    def test_dung_url_va_subjects(self):
        i = _TL.index("def books_for(")
        body = _TL[i:_TL.index("def toc(")]
        assert 'b.get("url")' in body
        assert 'b.get("subjects")' in body, "sách gộp có NHIỀU mã môn — so bằng chứa"
        assert 'b.get("detail_url")' not in body
        assert 'b.get("subject")' not in body.replace('b.get("subjects")', "")

    def test_dem_pages_bang_len(self):
        i = _TL.index("def books_for(")
        body = _TL[i:_TL.index("def toc(")]
        assert 'len(rec.get("pages")' in body
        assert 'int(rec.get("pages")' not in body


class TestMucLuc:
    def test_toc_va_save_toc_ton_tai(self):
        assert "def toc(" in _TL and "def save_toc(" in _TL

    def test_api_toc(self):
        assert '"/api/teacher/lecture/toc"' in _API

    def test_ca_hai_tab_dung_chung_nguon(self):
        """Bài giảng và Bài tập cùng gọi /lecture/toc — hai nguồn là lệch nhau."""
        assert "/api/teacher/lecture/toc" in _UI
        assert "/api/teacher/lecture/toc" in _PAGE


class TestRoutes:
    def test_du_bon_route(self):
        for r in ("/api/teacher/lecture/books", "/api/teacher/lecture/generate",
                  "/api/teacher/lecture/last", "/api/teacher/lecture/ask"):
            assert f'"{r}"' in _API, r

    def test_deu_require_admin_va_threadpool(self):
        i = _API.index('"/api/teacher/lecture/books"')
        j = _API.index('"/api/teacher/pages"')
        blob = _API[i:j]
        assert blob.count("require_admin") >= 5
        assert blob.count("run_in_threadpool") >= 5, (
            "books_for bò mạng, generate gọi model — chạy thẳng trong async là "
            "chặn event loop, cả gateway đứng hình")


class TestTabHaiTang:
    def test_tab_moi_can_hoc_sinh(self):
        assert '"lecture", "lesson", "homework", "placement", "parent", "sgkview"' in _PAGE

    def test_component_o_module_scope_file_rieng(self):
        """Định nghĩa lồng trong TeacherPage là họ lỗi React #310 đã phải vá."""
        assert 'from "./lecture-tab"' in _PAGE
        assert "export function LectureTab" in _UI
