"""Giá xăng đọc từ chính trang Petrolimex, không từ bản chép đã đứng.

Chủ máy 06/10/2026 (ảnh trang Petrolimex 15:00 1/10): bot báo «RON 95 chưa có dữ liệu», E5 26.390 — nguồn webgia.com
đứng ở 14:02 1/10, không theo kịp lần Petrolimex đổi tên sản phẩm. Chữ dưới đây chép đúng khối bảng giá trang chủ
Petrolimex hiển thị (đọc bằng Chrome không giao diện, 06/10/2026).
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

# petrol.py nạp fastmcp (chỉ có trong ảnh) và bs4 (CI không có) ở đầu tệp; phần cần test không dùng tới — dựng giả
# khi thiếu để test chạy được cả ở CI.
_gia: list[str] = []
for _ten in ("fastmcp", "bs4"):
    if importlib.util.find_spec(_ten) is None and _ten not in sys.modules:
        _m = types.ModuleType(_ten)
        _m.FastMCP = lambda *a, **k: types.SimpleNamespace(tool=lambda *a, **k: (lambda f: f))
        _m.BeautifulSoup = object
        sys.modules[_ten] = _m
        _gia.append(_ten)

_P = Path(__file__).resolve().parent.parent / "vn-mcp-hub" / "src" / "vn" / "petrol.py"
_spec = importlib.util.spec_from_file_location("vn_petrol_thu", _P)
petrol = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(petrol)
for _ten in _gia:          # gỡ ngay: test khác dùng importorskip("bs4") phải còn thấy bs4 THIẾU
    sys.modules.pop(_ten, None)

KHOI = """Giá bán lẻ xăng dầu
Sản phẩm
Vùng 1
Vùng 2
Xăng E10 RON 95 Mức 5
28.180
28.740
Xăng E10 RON 95 Mức 3
27.180
27.720
Xăng E5 RON 92 Mức 2
26.560
27.090
DO 0,001S Mức 5
31.110
31.730
DO 0,05S Mức 2
29.710
30.300
Dầu hỏa 2-K
29.770
30.360
*đơn vị: VND
Giá của Petrolimex cập nhật lúc  15:00 - 1/10/2026
Tìm kiếm cây xăng quanh bạn"""


def test_doc_dung_bang_petrolimex_ten_moi():
    d = petrol.doc_bang_petrolimex(KHOI)
    assert d["updated_at"] == "15:00 - 1/10/2026"
    assert [r["product"] for r in d["rows"]] == [
        "Xăng E10 RON 95 Mức 5", "Xăng E10 RON 95 Mức 3", "Xăng E5 RON 92 Mức 2",
        "DO 0,001S Mức 5", "DO 0,05S Mức 2", "Dầu hỏa 2-K"]
    assert d["rows"][0] == {"product": "Xăng E10 RON 95 Mức 5", "vung_1": "28.180", "vung_2": "28.740"}


def test_khong_nhan_ra_thi_rong_de_lui_nguon_phu():
    assert petrol.doc_bang_petrolimex("trang lỗi")["rows"] == []


def test_nguon_phu_phai_noi_ro(monkeypatch):
    monkeypatch.setattr(petrol, "_fetch_petrolimex", lambda: {"updated_at": "", "rows": []})
    monkeypatch.setattr(petrol, "_fetch_petrol", lambda: {"updated_at": "14:02:05 01/10/2026", "rows": [
        {"product": "Xăng E5 RON 92-II", "vung_1": "26.390", "vung_2": "26.910"}]})
    petrol._dem.update(luc=0.0, data=None)
    ra = petrol.get_petrol_prices("all") if callable(petrol.get_petrol_prices) else petrol.get_petrol_prices.fn("all")
    assert "Nguồn PHỤ" in ra and "14:02:05 01/10/2026" in ra
