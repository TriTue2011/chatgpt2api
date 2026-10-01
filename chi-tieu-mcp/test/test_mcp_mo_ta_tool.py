"""Test mô tả tool MCP (docstring trong app/main.py) -- phần LLM của C2A đọc
để quyết định gọi tool nào, nên câu chữ ở đây là hành vi thật của bot."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.mark.asyncio
async def test_chi_phi_dac_biet_dan_bot_khong_ghi_lai_khoan_da_khai_bao(mcp_that):
    """I1 (review Hũ âm tự bù 23/09/2026), người dùng chọn A: khai báo = đã
    chi. Docstring cũ dặn "khi khoản chi thật xảy ra vẫn phải gọi
    ghi_chi_tieu" -> bot làm đúng lời dặn thì bị trừ 2 lần."""
    mcp, _ = mcp_that
    # Gộp khoảng trắng: docstring xuống dòng ở đâu không quan trọng.
    mo_ta = {t.name: " ".join(t.description.split()) for t in await mcp.list_tools()}
    assert "vẫn phải" not in mo_ta["khai_bao_chi_phi_dac_biet"]
    assert "KHÔNG gọi ghi_chi_tieu" in mo_ta["khai_bao_chi_phi_dac_biet"]
    assert "khai_bao_chi_phi_dac_biet" in mo_ta["ghi_chi_tieu"]
    assert "chi_phi_dac_biet_thang_nay" in mo_ta["ghi_chi_tieu"]


def _cat_nhu_c2a(mo_ta: str) -> str:
    """Bản rút gọn C2A gửi model free (`_compact_expense_tools`, bản vá 25/09/2026):
    gộp khoảng trắng, cắt 420 ký tự, lùi về dấu '. ' cuối nếu nó quá nửa đoạn."""
    s = " ".join(mo_ta.split())[:420]
    cham = s.rfind(". ")
    return s[:cham + 1] if cham > 210 else s


@pytest.mark.asyncio
async def test_ghi_chi_tieu_dau_mo_ta_dan_khoan_moi_luon_goi_tool(mcp_that):
    """Lỗi thật 25/09/2026 19:50: tóm tắt hội thoại của C2A có "Đã ghi nhận chi tiêu:
    đổ xăng 60.000đ" (lần đổ trước) -> model coi "Chi 60k đổ xăng" là tin lặp, trả lời
    "em ghi nhận" mà KHÔNG gọi tool, sổ không có dòng mới. Model free chỉ thấy khoảng
    420 ký tự đầu của mô tả, nên quy tắc phải nằm trong đoạn đó."""
    mcp, _ = mcp_that
    mo_ta = {t.name: t.description for t in await mcp.list_tools()}
    dau = _cat_nhu_c2a(mo_ta["ghi_chi_tieu"])
    assert "khoản MỚI" in dau
    assert "LUÔN gọi tool này" in dau
    assert "da_ghi=true" in dau
    # Mã hũ vẫn phải còn trong bản rút gọn, không thì model đoán sai mã.
    for ma in ("thiet_yeu", "gia_dinh", "hoc_tap", "du_phong", "huong_thu", "tu_do_tai_chinh"):
        assert ma in dau
