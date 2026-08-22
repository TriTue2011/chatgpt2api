"""Tự nạp kho slide lúc khởi động — deploy là dùng được, KHÔNG gói dữ liệu vào image.

Bối cảnh: nội dung slide là tài liệu của NXB Giáo dục, mà repo dự án là repo CÔNG
KHAI — commit nội dung vào đó là phát hành lại tài liệu của họ. Nên repo chỉ có
CODE, còn container tự tải từ nguồn công khai lúc chạy và ghi vào volume dữ liệu.

Bốn bất biến dễ sai nhất, tất cả đều hỏng IM LẶNG nếu sai:

  1. Slide ẢNH (chữ nằm trong ảnh chèn vào) KHÔNG được nạp ở đây — nạp vào là
     kho có một mẩu tiêu đề rồi ai đọc state cũng tưởng bộ đó đã xong.
  2. Nhiều quyển dùng CHUNG một bộ slide (tập một + tập hai). Nạp mỗi bộ một lần.
  3. Phải chờ hub lên. Hub là tiến trình RIÊNG dưới supervisord, app chính lên
     trước — đẩy sớm thì cả 101 bộ lỗi "connection refused" rồi ghi state failed.
  4. Chỉ tự chạy LẦN ĐẦU. Đã có state nghĩa là người vận hành đã nạp hoặc đã cố
     ý dừng; tự chạy lại là đi ngược quyết định của họ.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pytestmark = pytest.mark.pure

_SRC = _ROOT / "services" / "agent" / "teacher_seed.py"


def _load(tmp: Path, monkeypatch: pytest.MonkeyPatch):
    """Nạp teacher_seed với DATA_DIR trỏ tmp, chặn chuỗi import nặng.

    Mọi thay đổi `sys.modules` đi qua `monkeypatch` để pytest trả lại nguyên
    trạng sau mỗi test. Gán trần thì module giả `services.config` còn nằm đó
    suốt phiên, và MỌI file test chạy sau file này đều chết ở bước import.
    """
    pkg = sys.modules.get("services") or types.ModuleType("services")
    pkg.__path__ = [str(_ROOT / "services")]
    monkeypatch.setitem(sys.modules, "services", pkg)
    ag = sys.modules.get("services.agent") or types.ModuleType("services.agent")
    ag.__path__ = [str(_ROOT / "services" / "agent")]
    monkeypatch.setitem(sys.modules, "services.agent", ag)
    cfg = types.ModuleType("services.config")
    cfg.DATA_DIR = tmp
    monkeypatch.setitem(sys.modules, "services.config", cfg)
    spec = importlib.util.spec_from_file_location(f"_ts_{_load.n}", _SRC)
    _load.n += 1
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_load.n = 0


def _gan_module_gia(monkeypatch: pytest.MonkeyPatch, ten: str, mod) -> None:
    """Đặt module giả vào CẢ sys.modules lẫn thuộc tính của gói cha.

    `from services.agent import X` đọc THUỘC TÍNH trên gói trước, chỉ rơi về
    sys.modules khi gói chưa có thuộc tính đó. Vá mỗi sys.modules thì test đậu
    hay hỏng tuỳ vào file chạy trước có nạp bản thật hay không — `run()` sẽ gọi
    bản thật, đi ra mạng, và `pushed` rỗng.
    """
    monkeypatch.setitem(sys.modules, ten, mod)
    goi, _, con = ten.rpartition(".")
    cha = sys.modules.get(goi)
    if cha is not None:
        monkeypatch.setattr(cha, con, mod, raising=False)


@pytest.fixture()
def ts(tmp_path, monkeypatch):
    mod = _load(tmp_path, monkeypatch)
    mod.STATE_PATH = tmp_path / "slide_seed_state.json"
    mod.CATALOG = tmp_path / "khong-co.json"      # buộc đi đường cào
    mod._GAP = 0                                   # test không cần nghỉ
    tw = types.ModuleType("services.agent.teacher_workspace")
    tw.GRADES = tuple(range(1, 13))
    tw.SUBJECT_LABEL = {"toan": "Toán", "tviet": "Tiếng Việt"}
    tw.config_hub_url = lambda: "http://127.0.0.1:8005"
    tw.pushed = []

    def _push(md, *, title, grade, subject, source, collection):
        tw.pushed.append({"title": title, "grade": grade, "subject": subject,
                          "source": source, "collection": collection,
                          "chars": len(md)})
        return {"ok": True, "chunks_added": 3}

    tw.push_sgk_to_rag = _push
    _gan_module_gia(monkeypatch, "services.agent.teacher_workspace", tw)
    mod._tw = tw
    return mod


BOOKS = [
    {"detail_url": "https://taphuan.nxbgd.vn/tap-huan/chi-tiet-sach/toan-1-tap-mot.1",
     "slug": "toan-1-tap-mot.1", "grade": 1, "subject": "toan", "book_set": ""},
    {"detail_url": "https://taphuan.nxbgd.vn/tap-huan/chi-tiet-sach/toan-1-tap-hai.2",
     "slug": "toan-1-tap-hai.2", "grade": 1, "subject": "toan", "book_set": ""},
]
GID_A = "A" * 30
GID_B = "B" * 30


def _wire(ts, *, ids_by_url, text_by_gid):
    ts._books = lambda *a, **k: BOOKS
    ts._slide_ids = lambda url: ids_by_url.get(url, [])
    ts._slide_text = lambda gid: text_by_gid.get(gid, "")


class TestNguongSlideAnh:
    def test_gan_nhu_khong_co_chu_thi_bo_han(self, ts):
        """Nạp mẩu tiêu đề rồi ghi 'ok' là state báo xong mà kho rỗng nghĩa."""
        _wire(ts, ids_by_url={BOOKS[0]["detail_url"]: [GID_A]},
              text_by_gid={GID_A: "TIÊU ĐỀ NGẮN"})
        r = ts.run()
        assert r["thin"] == 1 and r["ok"] == 0
        assert ts._tw.pushed == [], "không được đẩy gì vào kho"
        assert ts.read_state()["slides"][GID_A]["status"] == "thin"

    def test_chu_mong_van_nap_nhung_KHONG_ghi_ok(self, ts):
        """Bộ Toán 1: 656 ký tự cho 15 slide — chữ đó là tên tác giả + một đoạn
        quan điểm, phần dạy nằm trong ảnh. Vẫn nạp phần chữ (có ích), nhưng ghi
        'thin_ok' và cảnh báo NGAY trong nội dung chunk, để bot không khẳng định
        chắc nịch dựa trên vài dòng tiêu đề."""
        _wire(ts, ids_by_url={BOOKS[0]["detail_url"]: [GID_A]},
              text_by_gid={GID_A: "x" * 656})
        r = ts.run()
        assert r["thin_ok"] == 1 and r["ok"] == 0
        assert len(ts._tw.pushed) == 1
        assert "chưa OCR" in ts._tw.pushed[0]["title"]
        assert ts.read_state()["slides"][GID_A]["status"] == "thin_ok"

    def test_loi_tai_KHAC_slide_anh(self, ts):
        """Gộp hai thứ này thì một sự cố mạng bị ghi thành 'slide ảnh': cả 101 bộ
        đều thin và lượt nạp báo THÀNH CÔNG trong khi kho rỗng. Đã dính thật khi
        chạy thử — /export/txt chuyển hướng sang googleusercontent.com và bị
        net_guard chặn."""
        _wire(ts, ids_by_url={BOOKS[0]["detail_url"]: [GID_A]}, text_by_gid={})
        ts._slide_text = lambda gid: None
        r = ts.run()
        assert r["failed"] == 1 and r["thin"] == 0
        assert ts.read_state()["slides"][GID_A]["status"] == "failed"

    def test_chu_day_thi_nap(self, ts):
        _wire(ts, ids_by_url={BOOKS[0]["detail_url"]: [GID_A]},
              text_by_gid={GID_A: "x" * 3000})
        r = ts.run()
        assert r["ok"] == 1 and r["chunks"] == 3
        assert len(ts._tw.pushed) == 1
        assert ts._tw.pushed[0]["collection"] == "kb_giao_duc_slide"

    def test_nguong_dung_so_do_that(self, ts):
        assert ts._RICH_MIN == 1000, (
            "trên 97 bộ tải được chỉ 1 bộ dưới 1.000 ký tự; trung vị 14.031")
        assert ts._KEEP_MIN < ts._RICH_MIN

    def test_allowlist_co_host_chuyen_huong(self, ts):
        assert "googleusercontent.com" in ts._GSLIDE_HOSTS, (
            "/export/txt trả 302 sang doc-XX-YY-slides.googleusercontent.com")


class TestNoiLai:
    def test_bo_qua_bo_da_nap(self, ts):
        _wire(ts, ids_by_url={BOOKS[0]["detail_url"]: [GID_A]},
              text_by_gid={GID_A: "x" * 3000})
        ts.run()
        ts._tw.pushed.clear()
        r2 = ts.run()
        assert r2["skipped"] == 1 and r2["ok"] == 0
        assert ts._tw.pushed == [], "chạy lại không được nạp lại"

    def test_force_nap_lai(self, ts):
        _wire(ts, ids_by_url={BOOKS[0]["detail_url"]: [GID_A]},
              text_by_gid={GID_A: "x" * 3000})
        ts.run()
        ts._tw.pushed.clear()
        r2 = ts.run(force=True)
        assert r2["ok"] == 1 and len(ts._tw.pushed) == 1

    def test_bo_slide_dung_chung_chi_nap_mot_lan(self, ts):
        """Tập một và tập hai thường trỏ CÙNG một bộ slide."""
        _wire(ts, ids_by_url={BOOKS[0]["detail_url"]: [GID_A],
                              BOOKS[1]["detail_url"]: [GID_A]},
              text_by_gid={GID_A: "x" * 3000})
        r = ts.run()
        assert r["ok"] == 1, "cùng một bộ slide chỉ nạp một lần"
        assert len(ts._tw.pushed) == 1

    def test_hai_bo_khac_nhau_nap_ca_hai(self, ts):
        _wire(ts, ids_by_url={BOOKS[0]["detail_url"]: [GID_A],
                              BOOKS[1]["detail_url"]: [GID_B]},
              text_by_gid={GID_A: "x" * 3000, GID_B: "y" * 3000})
        assert ts.run()["ok"] == 2

    def test_limit_de_thu_truoc(self, ts):
        _wire(ts, ids_by_url={BOOKS[0]["detail_url"]: [GID_A],
                              BOOKS[1]["detail_url"]: [GID_B]},
              text_by_gid={GID_A: "x" * 3000, GID_B: "y" * 3000})
        assert ts.run(limit=1)["ok"] == 1

    def test_loi_day_ghi_nhan_khong_no(self, ts):
        _wire(ts, ids_by_url={BOOKS[0]["detail_url"]: [GID_A]},
              text_by_gid={GID_A: "x" * 3000})
        ts._tw.push_sgk_to_rag = lambda *a, **k: {"ok": False, "errors": ["hub sập"]}
        r = ts.run()
        assert r["failed"] == 1 and r["ok"] == 0
        assert ts.read_state()["slides"][GID_A]["status"] == "failed"


class TestTuChayLucKhoiDong:
    def test_chua_co_state_thi_chay(self, ts, monkeypatch):
        called = {}
        monkeypatch.setattr(ts, "start", lambda **kw: called.update(kw) or {"ok": True})
        ts.autostart_if_empty()
        assert called.get("wait_hub") is True, (
            "phải chờ hub: hub là tiến trình riêng, lên sau app chính")

    def test_da_co_state_thi_khong_chay(self, ts, monkeypatch):
        _wire(ts, ids_by_url={BOOKS[0]["detail_url"]: [GID_A]},
              text_by_gid={GID_A: "x" * 3000})
        ts.run()
        hit = []
        monkeypatch.setattr(ts, "start", lambda **kw: hit.append(1))
        r = ts.autostart_if_empty()
        assert not hit and "đã nạp" in str(r.get("skipped"))

    def test_co_ham_cho_hub(self, ts):
        assert callable(ts.wait_for_hub)


class TestKhongGoiDuLieuVaoImage:
    """Điều kiện người vận hành đặt ra: đẩy GitHub thì không được nằm trong image."""

    def test_dockerfile_khong_copy_docs_hay_data(self):
        df = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
        for line in df.splitlines():
            if line.startswith("COPY "):
                assert not line.startswith(("COPY docs", "COPY data")), line

    def test_cao_danh_muc_khi_khong_co_file(self, ts, monkeypatch):
        """docs/ không vào image, nên trong container phải tự cào — đọc file là
        chắc chắn rỗng."""
        tp = types.ModuleType("services.agent.sgk_taphuan")
        tp.list_books = lambda g, all_sets=False: (
            [{"url": f"https://x/chi-tiet-sach/toan-{g}.1", "slug": f"toan-{g}.1",
              "subjects": ("toan",), "book_set": ""}] if g == 1 else [])
        _gan_module_gia(monkeypatch, "services.agent.sgk_taphuan", tp)
        rows = ts._books([1, 2])
        assert len(rows) == 1 and rows[0]["subject"] == "toan"
        assert rows[0]["grade"] == 1

    def test_bo_quyen_khong_nhan_ra_mon(self, ts, monkeypatch):
        tp = types.ModuleType("services.agent.sgk_taphuan")
        tp.list_books = lambda g, all_sets=False: [
            {"url": "https://x/1", "slug": "tieng-han-3.1", "subjects": (),
             "book_set": ""}]
        _gan_module_gia(monkeypatch, "services.agent.sgk_taphuan", tp)
        assert ts._books([3]) == []

    def test_app_noi_vao_luc_khoi_dong(self):
        src = (_ROOT / "api" / "app.py").read_text(encoding="utf-8")
        assert "teacher_seed import autostart_if_empty" in src
        assert "autostart_if_empty()" in src
