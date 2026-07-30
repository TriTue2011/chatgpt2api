"""Ghi đè (mode=replace) phải ghi đè THẬT ở RAG, không chỉ file .md.

Đo 2026-07-29: replace chỉ ghi đè file .md lớp–môn; chunk cũ nằm lại trong
Chroma vĩnh viễn → thay SGK năm học mới xong bot trộn sách cũ + sách mới, và
lỗi này im lặng. Khoá ba mảnh:
  1. hub có /api/rag/forget xoá theo TIỀN TỐ source, chặn prefix < 8 kí tự
     (lời gọi cụt tay không được quét bay cả kho), và KHÔNG tăng offset sau khi
     xoá (dòng sau dồn lên chỗ trống — tăng là nhảy cóc).
  2. import_sgk_pdf gọi forget TRƯỚC khi nạp; xoá hỏng thì DỪNG, không nạp đè.
  3. UI nạp tay có ô chọn LOẠI và gửi kind theo cả hai đường (URL + upload).
"""
from __future__ import annotations
import sys
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
pytestmark = pytest.mark.pure

_HUB = (_ROOT / "vn-mcp-hub" / "src" / "main.py").read_text(encoding="utf-8")
_TW = (_ROOT / "services" / "agent" / "teacher_workspace.py").read_text(encoding="utf-8")
_PAGE = (_ROOT / "web" / "src" / "app" / "teacher" / "page.tsx").read_text(encoding="utf-8")


class TestHubForget:
    def test_route_ton_tai(self):
        assert '"/api/rag/forget/{collection}"' in _HUB

    def test_chan_prefix_ngan(self):
        i = _HUB.index("def rag_forget")
        body = _HUB[i:i + 2600]
        assert "len(prefix) < 8" in body

    def test_khong_tang_offset_sau_khi_xoa(self):
        i = _HUB.index("def rag_forget")
        body = _HUB[i:i + 2600]
        assert "continue" in body and "KHÔNG tăng offset" in body


class TestReplaceGoiForget:
    def test_goi_truoc_khi_nap(self):
        i = _TW.index('if mode == "replace":')
        j = _TW.index("push_sgk_to_rag(", i)
        assert "/api/rag/forget/" in _TW[i:j], "forget phải chạy TRƯỚC khi nạp"

    def test_xoa_hong_thi_dung(self):
        i = _TW.index('if mode == "replace":')
        # Cửa sổ phải phủ hết khối replace: bản đầu lấy 1800 ký tự và đã vỡ ngay
        # khi khối được thêm chú thích (return result trượt ra ngoài cửa sổ dù
        # hành vi không đổi). Cắt tới điểm nạp RAG — ranh giới thật của khối.
        j = _TW.index("Best-effort", i)
        body = _TW[i:j]
        assert "return result" in body, "xoá hỏng mà nạp tiếp là tạo bản trộn"

    def test_pham_vi_theo_lop_mon(self):
        i = _TW.index('if mode == "replace":')
        assert 'f"teacher_sgk/lop{g}/{sub}/"' in _TW[i:i + 1200]


class TestUiCoChonLoai:
    def test_co_state_kind(self):
        assert "impKind" in _PAGE

    def test_gui_kind_ca_hai_duong(self):
        assert "kind: impKind" in _PAGE          # đường URL
        assert 'fd.append("kind", impKind)' in _PAGE  # đường upload

    def test_du_bon_loai(self):
        for v in ('value="sgk"', 'value="sgv"', 'value="vbt"', 'value="tap_huan"'):
            assert v in _PAGE, v

