"""Model không gọi được tool thì gateway phải tự tra web hộ.

Lỗi thật 19/08/2026 trên Zalo Bot: hỏi "sân nhỏ cỏ đen" ba lượt liền, không lượt
nào chạm Internet — bot bịa mô tả từ kiến thức sẵn có.

Hai lớp cùng trượt:
  1. Lượt của trợ lý mang theo `tools` (có `web_search`), nên gateway CỐ Ý không
     tiêm kết quả tìm kiếm — nhường quyền quyết định cho model. Đúng thiết kế,
     và có lý do: xem chú thích ca "lịch hẹn" 10/08 trong _should_inject_search.
  2. Nhưng model phục vụ kênh này là `chatgpt_free` — ChatGPT web qua reverse.
     Đo thật: lượt mang đủ tools trả về finish_reason=stop, tool_calls RỖNG, kèm
     nguyên cục `image_group{…}` trong nội dung. Nó không dùng tool bao giờ.

Nhường quyền cho một model không biết nhận quyền = không ai tra cứu. Nên ngoại lệ
đó chỉ áp cho model thật sự gọi được tool.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.pure

TOOLS = [{"type": "function", "function": {"name": "web_search",
                                           "description": "Tra cứu web",
                                           "parameters": {"type": "object", "properties": {}}}}]


@pytest.fixture()
def bat_search(monkeypatch):
    """Bật dịch vụ tìm kiếm để phép thử không phụ thuộc cấu hình máy chạy test."""
    from services.protocol import openai_v1_chat_complete as m
    from services.search_service import SearchService
    monkeypatch.setattr(SearchService, "is_enabled", property(lambda self: True))
    return m


class TestNhanBietModelBoQuaTools:
    def test_model_web_reverse_bi_diem_mat(self):
        from services.protocol.openai_v1_chat_complete import _model_bo_qua_tools
        assert _model_bo_qua_tools("chatgpt_free") is True
        assert _model_bo_qua_tools("chatgpt_free:text") is True, "marker :text không được che mất provider"

    def test_model_goi_duoc_tool_khong_bi_diem_mat(self):
        from services.protocol.openai_v1_chat_complete import _model_bo_qua_tools
        for ten in ("cx/gpt-5.5:text", "gemini_free/gemini-3.6-flash",
                    "nv/openai/gpt-oss-120b", "oc/mimo-v2.5-free"):
            assert _model_bo_qua_tools(ten) is False, ten

    def test_ten_rong_thi_giu_hanh_vi_cu(self):
        from services.protocol.openai_v1_chat_complete import _model_bo_qua_tools
        assert _model_bo_qua_tools("") is False

    def test_ten_khong_co_tien_to_provider_tinh_la_web(self):
        """`backend_router.resolve_model` mặc định đẩy tên trần sang provider
        `chatgpt` (ChatGPT web), nên tên trần cũng phải được tiêm search hộ —
        đúng nơi nó thật sự chạy, không phải nơi cái tên gợi ra."""
        from services.protocol.openai_v1_chat_complete import _model_bo_qua_tools
        assert _model_bo_qua_tools("gpt-4") is True


class TestQuyetDinhTiemSearch:
    def _hoi(self, m, model: str) -> bool:
        body = {"x_agent_internal": True, "tools": TOOLS, "model": model}
        return m._should_inject_search(body, False, False, False, "sân nhỏ cỏ đen")

    def test_model_web_reverse_thi_tiem_ho(self, bat_search):
        assert self._hoi(bat_search, "chatgpt_free") is True

    def test_model_goi_duoc_tool_van_duoc_nhuong_quyen(self, bat_search):
        """Không được phá thiết kế cũ: model biết gọi tool thì nó tự quyết."""
        assert self._hoi(bat_search, "cx/gpt-5.5:text") is False

    def test_vision_van_khong_tiem(self, bat_search):
        body = {"x_agent_internal": True, "tools": TOOLS, "model": "chatgpt_free"}
        assert bat_search._should_inject_search(body, False, True, False, "ảnh này là gì") is False

    def test_da_prefetch_thi_khong_tiem_hai_lan(self, bat_search):
        body = {"x_agent_internal": True, "tools": TOOLS, "model": "chatgpt_free", "_prefetched": True}
        assert bat_search._should_inject_search(body, False, False, False, "sân nhỏ cỏ đen") is False

    def test_thread_bi_loc_khong_co_nhom_web_thi_khong_tiem(self, bat_search):
        body = {"x_agent_internal": True, "tools": TOOLS, "model": "chatgpt_free",
                "x_allowed_groups": ["homeassistant"]}
        assert bat_search._should_inject_search(body, False, False, False, "sân nhỏ cỏ đen") is False
