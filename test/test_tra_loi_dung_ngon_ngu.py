"""Câu trả lời phải đúng ngôn ngữ, và rớt kết nối thoáng qua thì thử lại — không đẩy lượt xuống model yếu.

Chủ máy 06/10/2026 «sao lại tiếng lạ thế»: Zalo trả lời lẫn tiếng Nga rồi tiếng Trung. Đo trên runs.sqlite: model
chính rớt kết nối MỘT lần (curl 56) → bị phạt nghỉ 60 s; Gemini hỏng bước 2 (thiếu thought_signature); cuối chuỗi
nemotron trả lời tiếng Nga — không bước nào kiểm câu trả lời. Đo 7 ngày: 4 lượt có chữ lạ.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.protocol import openai_v1_chat_complete as m  # noqa: E402

NGA = "Dạ, con đã tra cứu — это единственное доступное резюме за последние дни."
VIET = "Dạ, con đã tra cứu nhật ký nhóm 30 ngày gần đây."


def _tra(chu: str) -> dict:
    return {"id": "x", "object": "chat.completion", "choices": [
        {"index": 0, "message": {"role": "assistant", "content": chu}, "finish_reason": "stop"}]}


class DemChuLaTests(unittest.TestCase):
    def test_chu_nga_trung_la_chu_la_viet_va_hy_lap_thi_khong(self):
        self.assertGreaterEqual(m._chu_la(NGA, "ai ít nhắn nhất"), m._CHU_LA_TOI_THIEU)
        self.assertGreaterEqual(m._chu_la("xem ai xuất hiện ít nhất trong那些天", "ai ít nhắn"), m._CHU_LA_TOI_THIEU)
        self.assertEqual(0, m._chu_la("Điện trở R = U/I, góc α = 30°, Δt = 2 s, π ≈ 3,14 😊", "tính giúp"))

    def test_chu_co_san_trong_cau_hoi_thi_khong_tinh(self):
        self.assertEqual(0, m._chu_la("«你好» nghĩa là xin chào", "dịch giúp 你好 sang tiếng Việt"))

    def test_chi_doc_cau_tra_loi_chu_khong_doc_stream_hay_goi_cong_cu(self):
        self.assertEqual(VIET, m._chu_tra_loi(_tra(VIET)))
        self.assertIsNone(m._chu_tra_loi(iter([])))
        goi = _tra("")
        goi["choices"][0]["message"]["tool_calls"] = [{"id": "c1"}]
        self.assertIsNone(m._chu_tra_loi(goi))


class VongThuModelTests(unittest.TestCase):
    """Chạy thật `_handle_main` qua vòng thử model, chỉ thay đường gọi model (`_dispatch`)."""

    def _chay(self, dispatch):
        from services.backend_router import BackendRoute
        routes = [BackendRoute("p_dau", "m_dau"), BackendRoute("p_sau", "m_sau")]
        goi: list[str] = []

        def _gia(route, msgs, *a, **k):
            goi.append(route.model + ("+dan" if "Viết lại TOÀN BỘ bằng tiếng Việt" in str(msgs[-1].get("content")) else ""))
            return dispatch(route, msgs)

        body = {"model": "AI text", "stream": False, "x_no_smart_home": True, "x_allowed_groups": [],
                "messages": [{"role": "user", "content": "ai ít nhắn nhất trong 30 ngày"}]}
        with mock.patch.object(m.backend_router, "get_pipeline", return_value=None), \
             mock.patch.object(m.backend_router, "route_combo", return_value=routes), \
             mock.patch.object(m.backend_router, "is_combo", return_value=True, create=True), \
             mock.patch.object(m.provider_order, "reorder", side_effect=lambda r: r), \
             mock.patch.object(m, "_dispatch", side_effect=_gia), \
             mock.patch.object(m, "_inject_mcp_tools", side_effect=lambda tools, **k: tools), \
             mock.patch.object(m.model_cooldown, "is_available", return_value=True), \
             mock.patch.object(m.model_cooldown, "record_failure"), \
             mock.patch.object(m.model_cooldown, "record_success"), \
             mock.patch.object(m.model_cooldown, "get_cooldown_info", return_value=None), \
             mock.patch.object(m.provider_circuit, "allow", return_value=True), \
             mock.patch.object(m.provider_circuit, "record_failure"), \
             mock.patch.object(m.provider_circuit, "record_success"), \
             mock.patch.object(m.provider_order, "record_failure"), \
             mock.patch.object(m.provider_order, "record_success"):
            kq = m._handle_main(body)
        return m._chu_tra_loi(kq), goi

    def test_tra_loi_tieng_nga_thi_nhac_lai_roi_sang_model_ke(self):
        chu, goi = self._chay(lambda r, msgs: _tra(NGA if r.model == "m_dau" else VIET))
        self.assertEqual(VIET, chu)
        self.assertEqual(["m_dau", "m_dau+dan", "m_sau"], goi)

    def test_nhac_mot_lan_ma_sua_duoc_thi_giu_model_dau(self):
        chu, goi = self._chay(lambda r, msgs: _tra(VIET if "Viết lại" in str(msgs[-1].get("content")) else NGA))
        self.assertEqual(VIET, chu)
        self.assertEqual(["m_dau", "m_dau+dan"], goi)

    def test_rot_ket_noi_nhanh_thi_thu_lai_chinh_model_do(self):
        lan = {"n": 0}

        def _goi(r, msgs):
            lan["n"] += 1
            if lan["n"] == 1:
                raise RuntimeError("OpenAI OAuth error: Codex connection failed: curl: (56) Connection closed abruptly")
            return _tra(VIET)
        chu, goi = self._chay(_goi)
        self.assertEqual((VIET, ["m_dau", "m_dau"]), (chu, goi))

    def test_loi_co_ma_http_thi_khong_thu_lai_ma_sang_model_ke(self):
        def _goi(r, msgs):
            if r.model == "m_dau":
                raise RuntimeError("Gemini error 400: Function call is missing a thought_signature")
            return _tra(VIET)
        chu, goi = self._chay(_goi)
        self.assertEqual((VIET, ["m_dau", "m_sau"]), (chu, goi))
