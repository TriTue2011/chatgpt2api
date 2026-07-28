"""Danh mục môn theo từng lớp + di trú mã môn `van` → `tviet`.

Bối cảnh 2026-07-28: trước đây mã `van` mang nhãn "Ngữ văn / TV" cho cả 12 lớp
— gộp hai môn khác nhau vào một mã. Lớp 1–5 học **Tiếng Việt**, lớp 6–12 học
**Ngữ văn**; chính file seed cũng đã là hai môn (`lop1/van.md` mở đầu
"# Tiếng Việt lớp 1"). Tương tự lớp 4–9 là MỘT quyển "Lịch sử và Địa lí", tách
thành `su` + `dia` là tự đổi tên sách.

Tách mã môn ⇒ dữ liệu đã có trên máy chủ (`sgk/lop{1..5}/van.md`, workspace
`lop{1..5}-van`) sẽ mồ côi nếu không di trú. Bộ test này chốt cả hai mặt.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pytestmark = pytest.mark.pure

_TW_SRC = _ROOT / "services" / "agent" / "teacher_workspace.py"


def _load_tw(data_dir: Path):
    """Nạp teacher_workspace với DATA_DIR trỏ vào tmp, bỏ qua chuỗi import nặng.

    Import thẳng `services.agent` sẽ kéo theo orchestrator → sqlalchemy…; ở đây
    chỉ cần một hằng số nên chặn bằng module giả cho nhanh và không phụ thuộc.
    """
    for name in ("services", "services.config", "services.agent",
                 "services.agent.teacher_workspace"):
        sys.modules.pop(name, None)
    pkg = types.ModuleType("services")
    pkg.__path__ = [str(_ROOT / "services")]
    sys.modules["services"] = pkg
    cfg = types.ModuleType("services.config")
    cfg.DATA_DIR = data_dir
    sys.modules["services.config"] = cfg
    ag = types.ModuleType("services.agent")
    ag.__path__ = [str(_ROOT / "services" / "agent")]
    sys.modules["services.agent"] = ag
    spec = importlib.util.spec_from_file_location(
        "services.agent.teacher_workspace", _TW_SRC,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture()
def tw(tmp_path: Path):
    return _load_tw(tmp_path)


class TestDanhMucMon:
    def test_moi_ma_mon_co_dung_mot_nhan(self, tw):
        for s in tw.SUBJECTS:
            assert s in tw.SUBJECT_LABEL, f"mã {s} thiếu nhãn"
        # Nhãn không được gộp hai môn bằng dấu "/" như "Ngữ văn / TV" trước đây.
        for s, label in tw.SUBJECT_LABEL.items():
            assert "/" not in label, f"nhãn {s!r} = {label!r} còn gộp hai môn"

    def test_tieng_viet_va_ngu_van_la_hai_ma_khac_nhau(self, tw):
        assert tw.SUBJECT_LABEL["tviet"] == "Tiếng Việt"
        assert tw.SUBJECT_LABEL["van"] == "Ngữ văn"
        for g in (1, 2, 3, 4, 5):
            assert "tviet" in tw.subjects_for(g), f"lớp {g} phải có Tiếng Việt"
            assert "van" not in tw.subjects_for(g), f"lớp {g} không học Ngữ văn"
        for g in range(6, 13):
            assert "van" in tw.subjects_for(g), f"lớp {g} phải có Ngữ văn"
            assert "tviet" not in tw.subjects_for(g), f"lớp {g} không học Tiếng Việt"

    def test_lich_su_va_dia_li_giu_nguyen_ten_o_lop_4_9(self, tw):
        assert tw.SUBJECT_LABEL["sudia"] == "Lịch sử và Địa lí"
        for g in range(4, 10):
            subs = tw.subjects_for(g)
            assert "sudia" in subs, f"lớp {g} phải có Lịch sử và Địa lí"
            # Không được tách một quyển thành hai môn.
            assert "su" not in subs and "dia" not in subs, f"lớp {g} bị tách"
        for g in (10, 11, 12):
            subs = tw.subjects_for(g)
            assert "su" in subs and "dia" in subs, f"lớp {g} là hai quyển riêng"
            assert "sudia" not in subs

    def test_lop_1_3_khong_co_mon_cua_cap_tren(self, tw):
        for g in (1, 2, 3):
            subs = tw.subjects_for(g)
            assert subs == ("toan", "tviet", "anh"), f"lớp {g}: {subs}"

    def test_tieng_anh_o_ca_12_lop(self, tw):
        # Danh mục taphuan thiếu Tiếng Anh ở lớp 10 và 12 (lớp 11 lại có, cùng
        # bộ mã môn) — đó là thiếu sót dữ liệu bên NXBGD, người vận hành đã xác
        # nhận lớp 12 có Tiếng Anh. Chốt lại để không ai "sửa theo số đo".
        for g in tw.GRADES:
            assert "anh" in tw.subjects_for(g), f"lớp {g} thiếu Tiếng Anh"

    def test_vat_li_chi_o_thpt(self, tw):
        for g in range(1, 10):
            assert "ly" not in tw.subjects_for(g), f"lớp {g} không có Vật lí riêng"
        for g in (10, 11, 12):
            assert "ly" in tw.subjects_for(g)

    def test_workspace_mot_cho_moi_lop_mon(self, tw):
        d = tw._default_workspaces()
        assert len(d) == sum(len(tw.subjects_for(g)) for g in tw.GRADES)
        for g in tw.GRADES:
            for sub in tw.subjects_for(g):
                assert f"lop{g}-{sub}" in d
        # Tổ hợp KHÔNG tồn tại thì không được sinh workspace.
        for bad in ("lop1-ly", "lop1-van", "lop6-tviet", "lop10-sudia",
                    "lop4-su", "lop2-dia"):
            assert bad not in d, f"sinh workspace vô nghĩa: {bad}"

    def test_sgk_expected_dem_theo_tung_lop(self, tw):
        st = tw.status_public()
        assert st["sgk_expected"] == sum(len(tw.subjects_for(g)) for g in tw.GRADES)


class TestBiDanhMon:
    @pytest.mark.parametrize(("nhap", "mong"), [
        ("tv", "tviet"), ("tiếng việt", "tviet"), ("tieng_viet", "tviet"),
        ("văn", "van"), ("ngữ văn", "van"), ("ngu_van", "van"),
        ("lịch sử và địa lí", "sudia"), ("su_dia", "sudia"),
        ("lịch sử", "su"), ("địa lí", "dia"), ("vật lí", "ly"),
        ("khoa học tự nhiên", "khtn"),
        # GDCD (6–9) và Giáo dục kinh tế & pháp luật (10–12) là hai sách khác
        # tên: `ktpl` từng bị bảng bí danh trỏ ngược về `gdcd`.
        ("kt&pl", "ktpl"), ("ktpl", "ktpl"), ("giáo dục công dân", "gdcd"),
        ("hoá học", "hoa"), ("tin học", "tin"), ("Toán", "toan"),
    ])
    def test_nhan_dung(self, tw, nhap, mong):
        assert tw._normalize_subject(nhap) == mong

    def test_mon_chua_ho_tro_tra_none(self, tw):
        # Lớp 3 trong kho có Tiếng Hàn nhưng hệ thống chưa có mã ngoại ngữ 2.
        assert tw._normalize_subject("tieng han") is None
        assert tw._normalize_subject("") is None

    def test_khong_co_khoa_trung_trong_bang_bi_danh(self):
        """Dict literal: khoá sau ghi đè khoá trước, IM LẶNG.

        Đây đúng là cách `ktpl` bị trỏ về `gdcd` — khai mã mới ở trên nhưng bên
        dưới còn dòng cũ. Quét AST vì sau khi Python nạp xong thì bản trùng đã
        biến mất, không test được từ giá trị runtime.
        """
        tree = ast.parse(_TW_SRC.read_text(encoding="utf-8"))
        found = False
        for node in ast.walk(tree):
            target = None
            if isinstance(node, ast.AnnAssign):
                target = getattr(node.target, "id", None)
            elif isinstance(node, ast.Assign) and node.targets:
                target = getattr(node.targets[0], "id", None)
            if target != "SUBJECT_ALIASES" or not isinstance(node.value, ast.Dict):
                continue
            found = True
            keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
            dup = sorted({k for k in keys if keys.count(k) > 1})
            assert not dup, f"khoá trùng trong SUBJECT_ALIASES: {dup}"
        assert found, "không tìm thấy khai báo SUBJECT_ALIASES để quét"


class TestDiTruVanSangTviet:
    def _dung_du_lieu_cu(self, tmp_path: Path):
        sgk = tmp_path / "agent" / "teacher" / "sgk"
        for g in range(1, 6):
            (sgk / f"lop{g}").mkdir(parents=True, exist_ok=True)
            (sgk / f"lop{g}" / "van.md").write_text(
                f"# Tiếng Việt lớp {g}\n\nNỘI DUNG NGƯỜI DÙNG {g}\n", encoding="utf-8",
            )
        ws = tmp_path / "agent" / "teacher" / "workspaces.json"
        ws.parent.mkdir(parents=True, exist_ok=True)
        data = {
            f"lop{g}-van": {
                "id": f"lop{g}-van", "name": "cũ", "grade": g,
                "level": "tieu_hoc", "subjects": ["van"], "description": "ghi chú cũ",
            } for g in range(1, 6)
        }
        data["lop6-van"] = {
            "id": "lop6-van", "name": "Ngữ văn 6", "grade": 6, "level": "thcs",
            "subjects": ["van"], "description": "PHẢI GIỮ NGUYÊN",
        }
        ws.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return sgk, ws

    def test_doi_ten_file_va_giu_nguyen_noi_dung(self, tmp_path: Path):
        sgk, _ = self._dung_du_lieu_cu(tmp_path)
        tw = _load_tw(tmp_path)
        tw._seeded = False
        tw._ensure_seeded()
        for g in range(1, 6):
            new = sgk / f"lop{g}" / "tviet.md"
            assert new.is_file(), f"lớp {g}: chưa đổi tên"
            # Di trú phải chạy TRƯỚC seed, nếu không seed ghi bản mẫu lên và
            # xoá sạch nội dung người dùng đã nạp.
            assert f"NỘI DUNG NGƯỜI DÙNG {g}" in new.read_text(encoding="utf-8"), (
                f"lớp {g}: nội dung bị seed ghi đè"
            )
            assert not (sgk / f"lop{g}" / "van.md").exists(), f"lớp {g}: van.md còn sót"

    def test_chuyen_workspace_lop_1_5_va_khong_dung_lop_6(self, tmp_path: Path):
        _, ws = self._dung_du_lieu_cu(tmp_path)
        tw = _load_tw(tmp_path)
        tw._seeded = False
        tw._ensure_seeded()
        cur = json.loads(ws.read_text(encoding="utf-8"))
        for g in range(1, 6):
            assert f"lop{g}-tviet" in cur, f"thiếu lop{g}-tviet"
            assert f"lop{g}-van" not in cur, f"còn lop{g}-van"
            assert cur[f"lop{g}-tviet"]["subjects"] == ["tviet"]
            assert cur[f"lop{g}-tviet"]["description"] == "ghi chú cũ", "mất dữ liệu cũ"
        assert cur["lop6-van"]["description"] == "PHẢI GIỮ NGUYÊN", "lop6-van bị đụng"

    def test_chay_lai_nhieu_lan_vo_hai(self, tmp_path: Path):
        sgk, _ = self._dung_du_lieu_cu(tmp_path)
        tw = _load_tw(tmp_path)
        for _ in range(3):
            tw._seeded = False
            tw._ensure_seeded()
        for g in range(1, 6):
            assert f"NỘI DUNG NGƯỜI DÙNG {g}" in (
                sgk / f"lop{g}" / "tviet.md"
            ).read_text(encoding="utf-8")

    def test_khong_ghi_de_khi_dich_da_ton_tai(self, tmp_path: Path):
        """Đã có tviet.md mới hơn thì van.md cũ KHÔNG được đè lên."""
        sgk, _ = self._dung_du_lieu_cu(tmp_path)
        (sgk / "lop1" / "tviet.md").write_text("BẢN MỚI", encoding="utf-8")
        tw = _load_tw(tmp_path)
        tw._seeded = False
        tw._ensure_seeded()
        assert (sgk / "lop1" / "tviet.md").read_text(encoding="utf-8") == "BẢN MỚI"


class TestMoTaToolKhongLechDanhMuc:
    """Mô tả tool là thứ DUY NHẤT bot đọc để biết có những mã môn nào.

    `capabilities.py` import teacher_workspace muộn (tránh vòng import qua
    `services/agent/__init__`), nên không dựng được chuỗi mô tả từ danh mục lúc
    nạp module. Vì vậy danh sách phải viết tay — và bộ test này là thứ chặn nó
    lệch. Viết thiếu mã môn thì bot không bao giờ truyền mã đó.
    """

    _CAP = _ROOT / "services" / "agent" / "capabilities.py"

    def test_moi_ma_mon_deu_xuat_hien_trong_mo_ta_tool(self, tw):
        src = self._CAP.read_text(encoding="utf-8")
        # Chỉ soi phần khai báo tool, bỏ chú thích để không tính nhầm.
        code = "\n".join(
            ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
        )
        for sub in tw.SUBJECTS:
            assert f"|{sub}|" in code or f"|{sub}" in code or f"{sub}|" in code, (
                f"mã môn {sub!r} không có trong mô tả tool nào — bot sẽ không dùng"
            )

    def test_khong_con_danh_sach_3_mon_cu(self):
        for path in (
            self._CAP,
            _ROOT / "services" / "agent" / "soul.md",
            _ROOT / "services" / "agent" / "skills_default"
            / "giao-vien-tieu-hoc" / "SKILL.md",
        ):
            code = "\n".join(
                ln for ln in path.read_text(encoding="utf-8").splitlines()
                if not ln.lstrip().startswith("#")
            )
            assert "toan|van|anh" not in code, f"{path.name} còn danh sách 3 môn cũ"

    def test_regex_workspace_nhan_moi_ma_mon(self, tw):
        """`_ws_grade_subject` viết cứng 3 môn thì lop1-tviet / lop10-ly rơi về
        mặc định lớp 5 · Toán — trả lời sai lớp sai môn mà không báo lỗi."""
        import re as _re
        pat = _re.compile(r"lop(\d{1,2})-(%s)$" % "|".join(tw.SUBJECTS))
        for g in tw.GRADES:
            for sub in tw.subjects_for(g):
                wid = f"lop{g}-{sub}"
                m = pat.match(wid)
                assert m, f"{wid} không khớp"
                assert int(m.group(1)) == g and m.group(2) == sub


class TestSeedKhopDanhMuc:
    def test_file_seed_dung_ten_moi(self):
        """Seed lớp 1–5 phải là tviet.md, lớp 6–12 là van.md."""
        seed = _ROOT / "services" / "agent" / "teacher_default" / "sgk"
        for g in range(1, 6):
            assert (seed / f"lop{g}" / "tviet.md").is_file(), f"lớp {g} thiếu tviet.md"
            assert not (seed / f"lop{g}" / "van.md").exists(), f"lớp {g} còn van.md"
        for g in range(6, 13):
            assert (seed / f"lop{g}" / "van.md").is_file(), f"lớp {g} thiếu van.md"
            assert not (seed / f"lop{g}" / "tviet.md").exists()

    def test_noi_dung_seed_khop_ten_mon(self):
        seed = _ROOT / "services" / "agent" / "teacher_default" / "sgk"
        assert "Tiếng Việt" in (seed / "lop1" / "tviet.md").read_text(encoding="utf-8")
        assert "Ngữ văn" in (seed / "lop6" / "van.md").read_text(encoding="utf-8")
