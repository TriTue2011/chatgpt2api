"""Hồ sơ học sinh: lớp SUY TỪ NĂM SINH, tự lên lớp mỗi năm.

Bối cảnh: trước đây lớp là số khai tay trong hồ sơ, nên mỗi tháng 9 phải đi sửa
lại toàn bộ học sinh — và quên sửa thì bot dạy sai lớp mà không ai biết. Giờ chỉ
lưu năm sinh, lớp tính tại thời điểm gọi:

    lớp = năm_học_bắt_đầu − năm_sinh − 5        (VN vào lớp 1 lúc 6 tuổi)

Hai bất biến quan trọng nhất ở đây:
  1. Ngoài phạm vi lớp 1–12 phải trả 0, KHÔNG kẹp về 1 hay 12 — kẹp là bịa ra
     một lớp rồi SGK/đề/lộ trình phía sau đều sai lặng lẽ.
  2. Phải có đường KHAI TAY ghi đè: học lại, học vượt, vào lớp 1 muộn đều làm
     công thức sai.
"""

from __future__ import annotations

import datetime
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pytestmark = pytest.mark.pure

_SRC = _ROOT / "services" / "agent" / "teacher_path.py"
D = datetime.date


def _load(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Nạp teacher_path với DATA_DIR trỏ tmp, chặn chuỗi import nặng.

    Mọi thay đổi `sys.modules` đi qua `monkeypatch` để pytest trả lại nguyên
    trạng sau mỗi test. Gán trần thì module giả `services.config` còn nằm đó
    suốt phiên, và MỌI file test chạy sau file này đều chết ở bước import.
    """
    for name in ("services", "services.config", "services.agent",
                 "services.agent.teacher_path"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    pkg = types.ModuleType("services")
    pkg.__path__ = [str(_ROOT / "services")]
    monkeypatch.setitem(sys.modules, "services", pkg)
    cfg = types.ModuleType("services.config")
    cfg.DATA_DIR = data_dir
    monkeypatch.setitem(sys.modules, "services.config", cfg)
    ag = types.ModuleType("services.agent")
    ag.__path__ = [str(_ROOT / "services" / "agent")]
    monkeypatch.setitem(sys.modules, "services.agent", ag)
    spec = importlib.util.spec_from_file_location(
        "services.agent.teacher_path", _SRC)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture()
def tp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    return _load(tmp_path, monkeypatch)


class TestNamHoc:
    def test_moc_chuyen_la_thang_8(self, tp):
        """Tháng 8 chứ không phải tháng 9: tháng 8 đã tựu trường và giáo viên
        soạn bài cho lớp MỚI — hiện lớp cũ lúc đó là vô dụng."""
        assert tp.SCHOOL_YEAR_CUTOFF_MONTH == 8
        assert tp.school_year_start(D(2026, 7, 31)) == 2025
        assert tp.school_year_start(D(2026, 8, 1)) == 2026
        assert tp.school_year_start(D(2026, 12, 31)) == 2026
        assert tp.school_year_start(D(2027, 5, 20)) == 2026


class TestSuyLop:
    def test_moc_vao_lop_1(self, tp):
        """Sinh năm Y vào lớp 1 tháng 9 năm Y+6."""
        assert tp.grade_from_birth_year(2019, D(2025, 9, 5)) == 1
        assert tp.grade_from_birth_year(2020, D(2026, 9, 5)) == 1

    def test_tu_len_lop_khi_qua_thang_8(self, tp):
        """Đây là lý do tồn tại của cả tính năng: không phải sửa tay mỗi năm."""
        assert tp.grade_from_birth_year(2019, D(2026, 7, 31)) == 1
        assert tp.grade_from_birth_year(2019, D(2026, 8, 1)) == 2
        assert tp.grade_from_birth_year(2019, D(2027, 9, 1)) == 3

    def test_lop_12_va_qua_tuoi(self, tp):
        assert tp.grade_from_birth_year(2009, D(2026, 9, 1)) == 12
        # Đã tốt nghiệp → 0, KHÔNG kẹp về 12.
        assert tp.grade_from_birth_year(2008, D(2026, 9, 1)) == 0

    def test_chua_du_tuoi_tra_0(self, tp):
        assert tp.grade_from_birth_year(2021, D(2026, 9, 1)) == 0

    @pytest.mark.parametrize("xau", [None, "", "abc", 0, -5, 3000, 1899, [], {}])
    def test_dau_vao_xau_tra_0(self, tp, xau):
        assert tp.grade_from_birth_year(xau, D(2026, 9, 1)) == 0

    def test_chuoi_so_van_nhan(self, tp):
        assert tp.grade_from_birth_year("2019", D(2026, 9, 1)) == 2


class TestResolveGrade:
    def test_suy_tu_nam_sinh(self, tp):
        r = tp.resolve_grade({"birth_year": 2019}, D(2026, 9, 1))
        assert r["grade"] == 2
        assert r["grade_source"] == "năm sinh"
        assert r["age"] == 7
        assert r["school_year"] == "2026–2027"

    def test_khai_tay_ghi_de(self, tp):
        r = tp.resolve_grade({"birth_year": 2019, "grade": 5}, D(2026, 9, 1))
        assert r["grade"] == 5
        assert r["grade_source"] == "khai tay"
        # Vẫn giữ số suy được để UI đối chiếu "khai tay lệch với năm sinh".
        assert r["grade_computed"] == 2
        assert r["grade_override"] == 5

    def test_khai_tay_sai_thi_bo(self, tp):
        for bad in (0, 13, 99, -1, "x", None):
            r = tp.resolve_grade({"birth_year": 2019, "grade": bad}, D(2026, 9, 1))
            assert r["grade"] == 2, bad
            assert r["grade_override"] is None, bad

    def test_khong_biet_gi(self, tp):
        r = tp.resolve_grade({}, D(2026, 9, 1))
        assert r["grade"] == 0
        assert r["grade_source"] == "chưa biết"

    def test_khai_tay_van_dung_khi_khong_co_nam_sinh(self, tp):
        r = tp.resolve_grade({"grade": 7}, D(2026, 9, 1))
        assert r["grade"] == 7 and r["grade_source"] == "khai tay"


class TestHoSo:
    def test_tao_moi_luu_nam_sinh(self, tp):
        p = tp.get_or_create_profile("an", display_name="Nguyễn Văn An",
                                     birth_year=2019)
        assert p["birth_year"] == 2019
        assert p["display_name"] == "Nguyễn Văn An"
        assert p["grade"] == 0, "không truyền lớp thì không được tự khai tay"

    def test_list_students_kem_lop_da_suy(self, tp):
        tp.get_or_create_profile("an", display_name="An", birth_year=2019)
        rows = tp.list_students()
        assert len(rows) == 1
        r = rows[0]
        assert r["birth_year"] == 2019
        assert r["grade"] >= 1, "list phải trả lớp đã suy, không phải 0"
        assert r["grade_source"] == "năm sinh"
        assert r["school_year"]

    def test_nam_sinh_xau_luu_thanh_none(self, tp):
        p = tp.get_or_create_profile("b", display_name="B", birth_year="abc")
        assert p["birth_year"] is None

    def test_update_bo_khai_tay(self, tp):
        """`grade=None` phải BỎ ghi đè — POST coi 0 là 'không truyền' nên
        không có cách nào xoá, đó là lý do có update_profile riêng."""
        tp.get_or_create_profile("an", display_name="An", birth_year=2019, grade=5)
        assert tp.resolve_grade(tp.get_profile("an"), D(2026, 9, 1))["grade"] == 5
        tp.update_profile("an", grade=None)
        r = tp.resolve_grade(tp.get_profile("an"), D(2026, 9, 1))
        assert r["grade"] == 2 and r["grade_source"] == "năm sinh"

    def test_update_doi_nam_sinh(self, tp):
        tp.get_or_create_profile("an", display_name="An", birth_year=2019)
        tp.update_profile("an", birth_year=2015)
        assert tp.get_profile("an")["birth_year"] == 2015

    def test_update_xoa_nam_sinh(self, tp):
        tp.get_or_create_profile("an", display_name="An", birth_year=2019)
        tp.update_profile("an", birth_year="")
        assert tp.get_profile("an")["birth_year"] is None

    def test_update_ho_so_khong_ton_tai(self, tp):
        assert tp.update_profile("khong-co", birth_year=2019) is None

    def test_get_or_create_khong_xoa_khai_tay_bang_grade_0(self, tp):
        """grade=0 nghĩa là 'không truyền', không được coi là 'xoá'."""
        tp.get_or_create_profile("an", display_name="An", birth_year=2019, grade=5)
        tp.get_or_create_profile("an", display_name="An", grade=0)
        assert tp.get_profile("an")["grade"] == 5

    def test_moi_hoc_sinh_doc_lap(self, tp):
        tp.get_or_create_profile("an", display_name="An", birth_year=2019)
        tp.get_or_create_profile("binh", display_name="Bình", birth_year=2013)
        rows = {r["student_key"]: r for r in tp.list_students()}
        assert rows["an"]["grade"] != rows["binh"]["grade"]
        assert rows["an"]["birth_year"] == 2019
        assert rows["binh"]["birth_year"] == 2013


class TestUIKhopBackend:
    """Công thức trên UI phải khớp backend — lệch là hiện lớp sai lúc nhập."""

    _UI = _ROOT / "web" / "src" / "app" / "teacher" / "page.tsx"

    def test_ui_dung_cung_cong_thuc(self):
        src = self._UI.read_text(encoding="utf-8")
        assert "sy - Number(newBirth) - 5" in src, (
            "UI phải dùng đúng công thức năm_học − năm_sinh − 5"
        )

    def test_ui_khoa_tab_khi_chua_chon_hoc_sinh(self):
        src = self._UI.read_text(encoding="utf-8")
        assert "const NEED_STUDENT" in src
        for t in ("lesson", "homework", "placement", "parent"):
            assert f'"{t}"' in src[src.index("const NEED_STUDENT"):
                                   src.index("const NEED_STUDENT") + 400], t
        # Kho SGK dùng CHUNG nên KHÔNG được nằm trong danh sách khoá.
        head = src[src.index("const NEED_STUDENT"):src.index("const NEED_STUDENT") + 400]
        assert '"import"' not in head, "Kho SGK không được đòi chọn học sinh"

    def test_ui_khai_need_student_truoc_khi_dung(self):
        """Khai sau chỗ dùng là TDZ ReferenceError lúc render — trang trắng."""
        src = self._UI.read_text(encoding="utf-8")
        i = src.index("const NEED_STUDENT")
        for use in ("NEED_STUDENT.includes(tab)", "NEED_STUDENT.includes(t.id)"):
            assert src.index(use) > i, use
