"""MCP tra 5 kho dạy học — và điều kiện để nó THẬT SỰ bật được.

Bài học đã trả giá: `device_fs` từng được mount đầy đủ trong hub mà vẫn vô dụng,
vì thiếu khai ở `services/mcp_presets.py` và ở GROUPS của tab MCP trên web. Bot
chỉ dùng MCP qua gateway, nên thiếu MỘT trong bốn chỗ khai là tool tồn tại mà
không ai bật được. Test dưới khoá đủ cả bốn.

Bất biến thứ hai: MÔ TẢ TOOL là thứ DUY NHẤT dạy bot khi nào dùng kho nào —
không có bảng định tuyến nào khác. Nên docstring phải nêu câu hỏi mẫu, và phải
phân biệt được cặp dễ lẫn nhất: "bài 3 dạy GÌ" (SGK) khác "DẠY bài 3 thế nào"
(SGV).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pytestmark = pytest.mark.pure

_SRC = _ROOT / "vn-mcp-hub" / "src" / "kb" / "giao_vien.py"
_HUB = _ROOT / "vn-mcp-hub" / "src" / "main.py"
_PRESETS = _ROOT / "services" / "mcp_presets.py"
_WEB = _ROOT / "web" / "src" / "app" / "mcp" / "page.tsx"


def _tree() -> ast.Module:
    return ast.parse(_SRC.read_text(encoding="utf-8"))


def _funcs() -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in _tree().body if isinstance(n, ast.FunctionDef)}


def _sgk_fn():
    """Lấy riêng `_sgk_collection` để chạy thật, KHÔNG nạp cả module.

    Nạp cả module là kéo theo fastmcp + Chroma; ở đây chỉ cần một hàm thuần
    chuỗi. Kèm các hằng tên kho vì hàm tham chiếu tới chúng.
    """
    src = _SRC.read_text(encoding="utf-8")
    consts = "\n".join(re.findall(r'^C_\w+ = "[^"]+"', src, re.M))
    block = src[src.index("def _sgk_collection"):src.index("@mcp.tool()")]
    ns: dict = {}
    exec("import re\n" + consts + "\n" + block, ns)  # noqa: S102 — hàm thuần
    return ns["_sgk_collection"]


class TestKhaiDuBonCho:
    def test_hub_mount(self):
        src = _HUB.read_text(encoding="utf-8")
        assert '("kb_giao_vien", "src.kb.giao_vien")' in src

    def test_hub_meta(self):
        src = _HUB.read_text(encoding="utf-8")
        assert '"kb_giao_vien": (' in src

    def test_preset_gateway(self):
        """Bot CHỈ dùng MCP qua gateway — thiếu preset là mount xong vẫn vô dụng."""
        src = _PRESETS.read_text(encoding="utf-8")
        assert 'id="kb_giao_vien"' in src
        assert "127.0.0.1:8005/kb_giao_vien/mcp" in src

    def test_web_groups(self):
        """Không có trong GROUPS thì tab MCP không hiện ô để bật."""
        src = _WEB.read_text(encoding="utf-8")
        assert 'id:"kb_giao_vien"' in src

    def test_web_dem_lai_totalCount(self):
        """totalCount lệch số phần tử thì UI hiện '7/8 đã cài' sai vĩnh viễn."""
        src = _WEB.read_text(encoding="utf-8")
        i = src.index('id:"kb_dien_nuoc"')
        line = src[src.rindex("\n", 0, i) + 1: src.index("\n", i)]
        n_items = line.count('{id:"')
        m = re.search(r"totalCount:(\d+)", line)
        assert m and int(m.group(1)) == n_items, (
            f"{n_items} kho nhưng totalCount={m.group(1) if m else '?'}")


class TestNamKhoTachBiet:
    def test_du_nam_tool_hoi(self):
        f = _funcs()
        for name in ("ask_sgk", "ask_sgv", "ask_bai_tap", "ask_phan_bo",
                     "ask_tai_lieu"):
            assert name in f, name

    def test_co_tool_xem_trang_thai(self):
        assert "trang_thai_kho" in _funcs()

    def test_moi_tool_mot_collection_khac_nhau(self):
        src = _SRC.read_text(encoding="utf-8")
        names = set(re.findall(r'^C_\w+ = "([^"]+)"', src, re.M))
        assert len(names) == 5, f"phải 5 kho khác nhau, thấy {names}"
        assert "kb_giao_duc" in names

    def test_sgk_theo_bo_sach(self):
        """Nạp bộ khác vào kb_giao_duc_bo{N} mà không có đường hỏi thì cũng như
        chưa nạp."""
        fn = _sgk_fn()
        assert fn("") == "kb_giao_duc"
        assert fn("3") == "kb_giao_duc_bo3"

    def test_bo_chi_nhan_chu_so(self):
        """Tên collection ghép từ tham số — không được nhét ký tự lạ vào."""
        fn = _sgk_fn()
        assert fn("../evil") == "kb_giao_duc"
        assert fn("3; drop") == "kb_giao_duc_bo3"
        assert fn("bo3") == "kb_giao_duc_bo3"


class TestMoTaDayBotChonKho:
    """Mô tả tool là thứ DUY NHẤT định tuyến — không có bảng nào khác."""

    def test_phan_biet_day_gi_va_day_the_nao(self):
        f = _funcs()
        sgk = ast.get_docstring(f["ask_sgk"]) or ""
        sgv = ast.get_docstring(f["ask_sgv"]) or ""
        assert "dạy gì" in sgk and "CÁCH DẠY" in sgk.upper()
        assert "dạy bài 3 thế nào" in sgv

    def test_moi_tool_co_cau_hoi_mau(self):
        f = _funcs()
        for name in ("ask_sgk", "ask_sgv", "ask_bai_tap", "ask_phan_bo",
                     "ask_tai_lieu"):
            doc = ast.get_docstring(f[name]) or ""
            assert '"' in doc, f"{name}: docstring phải nêu câu hỏi mẫu"
            assert len(doc) > 200, f"{name}: mô tả quá ngắn để bot chọn đúng kho"

    def test_bai_tap_noi_ro_chi_la_mau(self):
        """135/145 quyển trên kho là bài mẫu. Không nói rõ thì bot khẳng định
        'vở bài tập có bài X' khi kho chỉ có vài trang mẫu."""
        doc = ast.get_docstring(_funcs()["ask_bai_tap"]) or ""
        assert "BÀI MẪU" in doc and "135/145" in doc

    def test_phan_bo_la_kho_duy_nhat_co_tuan_tiet(self):
        doc = ast.get_docstring(_funcs()["ask_phan_bo"]) or ""
        assert "tuần" in doc and "tiết" in doc
        assert "DUY NHẤT" in doc

    def test_trang_thai_phan_biet_chua_nap_va_khong_thay(self):
        doc = ast.get_docstring(_funcs()["trang_thai_kho"]) or ""
        assert "CHƯA" in doc.upper() and "không tìm thấy" in doc

    def test_meta_hub_neu_ro_cach_chon(self):
        """Mô tả MCP quyết định bot có bật/định tuyến đúng hay không."""
        src = _HUB.read_text(encoding="utf-8")
        i = src.index('"kb_giao_vien": (')
        meta = src[i:i + 700]
        assert "dạy gì" in meta and "thế nào" in meta
