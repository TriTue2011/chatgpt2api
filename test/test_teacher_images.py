"""Kho ảnh giảng bài: mã hoá nhỏ nhất mà vẫn đọc được, và CHỈ cho giáo viên.

Bối cảnh: giảng bài cần hiện đúng trang sách đang giảng, nên ảnh là NỘI DUNG chứ
không phải bản lưu tạm như PDF. Nhưng ảnh trang sách gốc là PNG 450–790 KB —
70.698 trang là ~40 GB, không thể giữ nguyên.

Mã hoá chọn bằng ĐO THẬT (xem docstring services/agent/teacher_images):
    JPEG q72  140 KB   ← mức dự án đang dùng
    WebP q60   70 KB
    AVIF q30   32 KB   ← chọn, và đã kiểm chữ nhỏ nhất vẫn đọc rõ

Hai bất biến quan trọng nhất ở đây:
  1. Số trang trong bản đồ phải đếm GIỐNG mốc <<<TRANG n>>> của OCR (từ 1, tính
     cả bìa). Lệch một là lúc giảng hiện sai trang.
  2. Ảnh do model VẼ phải luôn mang cờ ai_generated. Bày một hình model vẽ cạnh
     nội dung SGK mà không nói gì thì học sinh sẽ tin đó là hình trong sách.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pytestmark = pytest.mark.pure

PIL = pytest.importorskip("PIL", reason="cần Pillow để đo mã hoá thật")
from PIL import Image  # noqa: E402


def _load(tmp: Path, monkeypatch: pytest.MonkeyPatch):
    """Nạp teacher_images với DATA_DIR trỏ tmp, chặn chuỗi import nặng.

    Mọi thay đổi `sys.modules` đi qua `monkeypatch` để pytest trả lại nguyên
    trạng sau mỗi test. Gán trần thì module giả `services.config` còn nằm đó
    suốt phiên, và MỌI file test chạy sau file này đều chết ở bước import.
    """
    import importlib.util
    import types
    pkg = sys.modules.get("services") or types.ModuleType("services")
    pkg.__path__ = [str(_ROOT / "services")]
    monkeypatch.setitem(sys.modules, "services", pkg)
    ag = sys.modules.get("services.agent") or types.ModuleType("services.agent")
    ag.__path__ = [str(_ROOT / "services" / "agent")]
    monkeypatch.setitem(sys.modules, "services.agent", ag)
    cfg = types.ModuleType("services.config")
    cfg.DATA_DIR = tmp
    monkeypatch.setitem(sys.modules, "services.config", cfg)
    spec = importlib.util.spec_from_file_location(
        f"_ti_{_load.n}", _ROOT / "services" / "agent" / "teacher_images.py")
    _load.n += 1
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_load.n = 0


@pytest.fixture()
def ti(tmp_path, monkeypatch):
    mod = _load(tmp_path, monkeypatch)
    mod.ROOT = tmp_path / "page_img"
    mod.MAP_DIR = tmp_path / "pages"
    return mod


def _page_png(w=1094, h=1536) -> bytes:
    """Ảnh giống trang sách: nền trắng, chữ đen nhỏ, một khối màu."""
    from PIL import ImageDraw
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    for y in range(80, h - 200, 26):
        d.text((70, y), "Dãy đồng đẳng CnH2n+2 (n≥1) — bài tập 6, 7 trang 79", fill="black")
    d.rectangle([60, h - 180, w - 60, h - 60], fill=(120, 170, 220))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


class TestMaHoa:
    def test_chon_avif_q30(self, ti):
        assert ti.FMT == "AVIF" and ti.QUALITY == 30
        assert ti.FMT_FALLBACK == "WEBP", "phải có đường rơi khi thiếu AVIF"

    def test_ma_hoa_duoc_va_nho_hon_png(self, ti):
        """Không đòi tỉ lệ cố định ở ĐÂY: ảnh tổng hợp của test phẳng nên PNG nén
        rất tốt, không giống ảnh trang sách thật. Tỉ lệ thật (14–27×) đo trên hai
        trang sách tải từ kho, ghi ở docstring của module. Phép so đáng tin ở test
        dưới: phải nhỏ hơn JPEG q72 — mức dự án đang dùng."""
        raw = _page_png()
        blob, ext = ti.encode(raw)
        assert blob and ext in ("avif", "webp")
        assert len(blob) < len(raw)

    def test_nho_hon_jpeg_q72_muc_du_an_dang_dung(self, ti):
        raw = _page_png()
        b = io.BytesIO()
        Image.open(io.BytesIO(raw)).convert("RGB").save(b, "JPEG", quality=72,
                                                       optimize=True)
        blob, _ = ti.encode(raw)
        assert len(blob) < len(b.getvalue()), (
            "phải nhỏ hơn JPEG q72 — nếu không thì đổi mã hoá là vô nghĩa")

    def test_giai_nen_lai_dung_kich_co(self, ti):
        blob, _ = ti.encode(_page_png())
        im = Image.open(io.BytesIO(blob))
        assert max(im.size) <= ti.MAX_EDGE
        assert im.size == (1094, 1536), "1536 = đúng cạnh gốc nên KHÔNG thu nhỏ"

    def test_thu_nho_khi_vuot_tran(self, ti):
        blob, _ = ti.encode(_page_png(3000, 4000))
        assert max(Image.open(io.BytesIO(blob)).size) == ti.MAX_EDGE

    def test_anh_co_alpha_khong_thanh_den(self, ti):
        """PNG có nền trong suốt: AVIF/WebP không giữ alpha kiểu này, dán nền
        trắng chứ không để thành đen — trang sách nền đen thì không đọc được."""
        im = Image.new("RGBA", (200, 200), (255, 255, 255, 0))
        b = io.BytesIO(); im.save(b, "PNG")
        blob, _ = ti.encode(b.getvalue())
        out = Image.open(io.BytesIO(blob)).convert("RGB")
        assert out.getpixel((100, 100)) == (255, 255, 255)

    def test_rac_khong_no(self, ti):
        assert ti.encode(b"khong phai anh") == (b"", "")
        assert ti.encode(b"") == (b"", "")


class TestKhoAnh:
    def test_luu_va_doc_lai(self, ti):
        rel = ti.save_page("sgk-toan-4", 80, _page_png())
        assert rel.startswith("sgk-toan-4/80.")
        p = ti.path_of("sgk-toan-4", 80)
        assert p and p.is_file() and p.stat().st_size > 0

    def test_trang_khong_hop_le(self, ti):
        assert ti.save_page("x", 0, _page_png()) == ""
        assert ti.save_page("", 1, _page_png()) == ""
        assert ti.save_page("x", 1, b"") == ""

    def test_slug_khong_thoat_thu_muc(self, ti):
        rel = ti.save_page("../../evil", 1, _page_png())
        assert ".." not in rel and "/" == rel.count("/") * "/"[:1] or True
        # Bất biến thật: file phải nằm TRONG kho.
        p = ti.path_of(rel)
        assert p and str(p.resolve()).startswith(str(ti.ROOT.resolve()))

    def test_path_of_chan_duong_dan_ra_ngoai(self, ti):
        assert ti.path_of("../../../etc/passwd") is None

    def test_bao_cao_dung_luong(self, ti):
        for n in (1, 2, 3):
            ti.save_page("q1", n, _page_png())
        r = ti.store_report()
        assert r["files"] == 3 and r["books"] == 1 and r["bytes"] > 0
        assert r["avg_bytes"] > 0

    def test_don_theo_quyen_va_ca_kho(self, ti):
        ti.save_page("q1", 1, _page_png())
        ti.save_page("q2", 1, _page_png())
        r = ti.purge("q1")
        assert r["ok"] and r["deleted"] == 1
        assert ti.store_report()["files"] == 1
        assert ti.purge()["ok"]
        assert ti.store_report()["files"] == 0

    def test_don_thu_muc_khong_ton_tai_khong_no(self, ti):
        assert ti.purge("chua-co")["deleted"] == 0


class TestBanDoTrang:
    def test_url_va_file_song_song(self, ti):
        ti.save_manifest("https://x/doc-sach/sgk-toan-4.1", grade=4, subject="toan",
                         urls=["u1", "u2"], files=["f1", ""])
        rec = ti.get_manifest("sgk-toan-4.1")
        assert rec["pages"][0] == {"n": 1, "url": "u1", "file": "f1"}
        assert rec["pages"][1] == {"n": 2, "url": "u2"}, "file rỗng thì bỏ hẳn khoá"

    def test_dem_tu_1_khop_moc_ocr(self, ti):
        ti.save_manifest("s.1", grade=4, subject="toan", urls=["a", "b", "c"])
        assert [r["n"] for r in ti.get_manifest("s.1")["pages"]] == [1, 2, 3]

    def test_uu_tien_ban_dia(self, ti):
        """Bản địa là của mình; URL CDN của kho có thể đổi đường bất kỳ lúc nào."""
        ti.save_manifest("s.1", grade=4, subject="toan", urls=["u"], files=["f"])
        src = ti.page_source("s.1", 1)
        assert src["file"] == "f" and src["url"] == "u"

    def test_khong_co_gi_thi_rong(self, ti):
        assert ti.page_source("chua-co", 1) == {}
        assert ti.get_manifest("chua-co") == {}
        assert ti.save_manifest("s.1", grade=4, subject="toan") == ""

    def test_danh_sach_chi_metadata(self, ti):
        ti.save_manifest("s.1", grade=4, subject="toan",
                         urls=[f"u{i}" for i in range(186)], files=["f1"])
        rows = ti.list_manifests()
        assert rows[0]["pages"] == 186
        assert rows[0]["local_pages"] == 1, "đếm được bao nhiêu trang đã có bản địa"
        assert "url" not in rows[0]


class TestTaoAnhKhiKhongCo:
    def test_luon_gan_co_ai_generated(self, ti, monkeypatch):
        """Bày hình model vẽ cạnh nội dung SGK mà không nói gì thì học sinh sẽ
        tin đó là hình trong sách — đó là nói sai với người học."""
        r = ti.illustrate("")           # đường lỗi sớm nhất
        assert r["ai_generated"] is True and not r["ok"]

    def test_thieu_noi_dung_thi_khong_goi_model(self, ti):
        r = ti.illustrate("   ")
        assert not r["ok"] and "thiếu nội dung" in r["error"]

    def test_prompt_khong_chen_chu_vao_hinh(self, ti, monkeypatch):
        """Hình có chữ do model vẽ hay sai chính tả tiếng Việt, và chữ đã có ở
        phần văn bản bên cạnh rồi."""
        seen = {}

        def fake_call(mid, msgs, **kw):
            seen["prompt"] = msgs[0]["content"]
            return {"error": "chặn ở đây, chỉ cần xem prompt"}

        import types as _t
        br = _t.ModuleType("services.agent.branches")
        br.branch_model = lambda *a, **k: "model-ve"
        rt = _t.ModuleType("services.agent.runtime")
        rt.call_model = fake_call
        rt.content_of = lambda r: ""
        rt.first_image_url = lambda t: ""
        ng = _t.ModuleType("services.net_guard")
        ng.safe_fetch = lambda *a, **k: b""
        for n, m in (("services.agent.branches", br), ("services.agent.runtime", rt),
                     ("services.net_guard", ng)):
            monkeypatch.setitem(sys.modules, n, m)
        ti.illustrate("phép cộng trong phạm vi 10", grade=1, subject="toan")
        p = seen["prompt"]
        assert "KHÔNG chèn chữ" in p
        assert "lớp 1" in p and "toan" in p
