"""Test tầng MCP (app/main.py): tham số số nguyên của tool KHÔNG nhận true/false.

Review toàn nhánh Hũ âm tự bù 23/09/2026 (Rec 4): qua MCP, `so_tien: true` bị
pydantic (chế độ lỏng) ép thành 1 và ghi 1 VNĐ. Kiểm tra trong tools.py không
bắt được vì tới đó giá trị đã là 1 -- nên test phải đi đúng đường C2A gọi:
FastMCP call_tool trên app.main.mcp thật.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp.exceptions import ToolError


def _so_dong(db_path) -> int:
    """Tổng số dòng mọi bảng -- để chắc tool bị từ chối KHÔNG ghi gì."""
    ket_noi = sqlite3.connect(db_path)
    try:
        bang = [r[0] for r in ket_noi.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return sum(ket_noi.execute(f"SELECT COUNT(*) FROM {b}").fetchone()[0] for b in bang)
    finally:
        ket_noi.close()


# Giá trị hợp lệ theo kiểu cho các tham số KHÔNG phải số nguyên, để lỗi (nếu
# có) chỉ có thể đến từ đúng tham số số nguyên đang thử.
_GIA_TRI_MAU = {"string": "x", "boolean": False, "array": [], "object": {}}


@pytest.mark.asyncio
async def test_moi_tham_so_so_nguyen_cua_moi_tool_tu_choi_true_false(mcp_that):
    """Quét inputSchema của MỌI tool (gồm cả tool thêm sau này): tham số
    "integer" nào cũng phải từ chối true/false bằng đúng thông báo của bộ
    chặn. Thiếu bộ chặn thì true/false thành 1/0, tool chạy thật và trả dict
    lỗi nghiệp vụ thay vì ToolError -> test hỏng."""
    mcp, db_path = mcp_that
    da_thu = []
    for tool in await mcp.list_tools():
        thuoc_tinh = tool.inputSchema.get("properties", {})
        so_nguyen = [ten for ten, s in thuoc_tinh.items() if s.get("type") == "integer"]
        for ten in so_nguyen:
            for gia_tri in (True, False):
                tham_so = {k: 1 if k in so_nguyen else _GIA_TRI_MAU[s["type"]] for k, s in thuoc_tinh.items()}
                tham_so[ten] = gia_tri
                with pytest.raises(ToolError, match="true/false"):
                    await mcp.call_tool(tool.name, tham_so)
                da_thu.append((tool.name, ten))
    # so_tien của 5 tool ghi + id của tach_giao_dich, mỗi cái thử true và
    # false. Nếu schema đổi khỏi "integer" (LLM thấy khác đi) thì quét ra ít hơn.
    assert len(set(da_thu)) >= 6
    assert _so_dong(db_path) == 0


@pytest.mark.asyncio
async def test_ghi_chi_tieu_so_tien_true_khong_ghi_1_vnd(mcp_that):
    mcp, db_path = mcp_that
    with pytest.raises(ToolError, match="true/false"):
        await mcp.call_tool("ghi_chi_tieu", {"hu_ma": "thiet_yeu", "so_tien": True, "ghi_chu": "ăn trưa"})
    assert _so_dong(db_path) == 0


@pytest.mark.asyncio
async def test_so_tien_dang_chuoi_so_hoac_so_thuc_tron_van_ghi_dung(mcp_that):
    """Cố tình KHÔNG dùng StrictInt: LLM đôi khi gửi số dạng chuỗi, pydantic ép
    "50000" -> 50000 là đúng ý người dùng -- chỉ true/false mới là rác."""
    mcp, db_path = mcp_that
    for gia_tri in (50000, "50000", 50000.0):
        await mcp.call_tool("ghi_chi_tieu", {"hu_ma": "thiet_yeu", "so_tien": gia_tri, "ghi_chu": "ăn trưa"})
    ket_noi = sqlite3.connect(db_path)
    try:
        so_tien = [r[0] for r in ket_noi.execute("SELECT so_tien FROM chi_tieu ORDER BY id")]
    finally:
        ket_noi.close()
    assert so_tien == [50000, 50000, 50000]
