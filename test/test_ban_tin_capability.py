"""Công cụ ``ban_tin`` — bản tin chia mục phải tới được tay model (25/09/2026).

Sự cố thật: chủ máy nhận bản tin sáng 25/09 gần như trống ("Chưa tìm thấy đủ tin"
ở 9 chỗ) và báo "Lỗi tin tức". Đo ``runs.sqlite`` 14–25/09: ngày nào bản tin theo
lịch cũng 6–13 mục "Chưa", công cụ gọi chỉ là ``web_search`` 1–2 lần.

Nguyên nhân: công cụ bản tin chia mục (MCP ``get_news_sections``) chỉ được gọi từ
đường tắt tin tức, mà đường tắt chỉ bắt câu < 40 ký tự; lời dặn của lịch dài ~330
ký tự nên rơi xuống model — và model không có công cụ đó. Gọi thử trong c2a cùng
ngày: ``get_news_sections`` trả đủ 8 mục trong 7,9 giây, 0 mục "Chưa".
"""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import capabilities as caps  # noqa: E402


def test_ban_tin_co_trong_so_va_thuoc_nhom_web() -> None:
    # Nhóm "web": thread nào tra cứu được thì lấy được bản tin; thiếu nhóm thì
    # bị coi là "_ungrouped" và CHẶN ở mọi thread có bộ lọc.
    assert "ban_tin" in caps.CAPABILITIES
    assert caps._CAP_GROUP["ban_tin"] == "web"


def test_ban_tin_goi_mcp_theo_dang_nguoi_dung_da_dan() -> None:
    goi = {}

    def gia(ten, args):
        goi["ten"], goi["args"] = ten, args
        return "**⚽ Thể thao**\n- Tin 1"

    dang = {"tom_tat": False, "in_dam": False, "emoji": True, "chi_viet": True}
    with mock.patch("services.mcp_client.call_mcp_tool", gia), \
            mock.patch("services.agent.orchestrator._dang_bay_tin", lambda pv: dang), \
            mock.patch("services.agent.orchestrator._pham_vi", lambda uid: "pv"):
        ra = caps.CAPABILITIES["ban_tin"].handler({}, {"user_id": "zalo_1"})
    assert ra["text"].startswith("**⚽ Thể thao**")
    assert goi["ten"] == "get_news_sections"
    assert goi["args"] == {"per_section": 3, "kem_tom_tat": False, "in_dam": False,
                           "dung_emoji": True, "chi_tieng_viet": True, "chu_de": ""}


def test_ban_tin_nguon_hong_thi_chi_duong_web_search() -> None:
    with mock.patch("services.mcp_client.call_mcp_tool", lambda *a: ""), \
            mock.patch("services.agent.orchestrator._pham_vi", lambda uid: ""):
        ra = caps.CAPABILITIES["ban_tin"].handler({}, {"user_id": "u"})
    assert "web_search" in ra["text"]


def test_chi_dan_tin_chung_tro_toi_ban_tin() -> None:
    """Bảng chỉ đường và mô tả web_search không còn bảo model tự chia 8 mục
    từ một lượt web_search — đúng cái làm bản tin trống."""
    from services.agent import orchestrator as orch

    nhanh = " ".join(t for nhom, _kw, t in orch._BANG_CHI_DUONG if nhom == "web")
    assert "ban_tin" in nhanh
    assert "gọi ban_tin" in caps.CAPABILITIES["web_search"].workflow
