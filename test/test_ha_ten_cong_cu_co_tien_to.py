"""HA 2026.9 đổi tên MỌI công cụ LLM thành ``<domain>__<tên>``.

SỰ CỐ 26/09/2026 19:27 (pipeline debug của HA): "Tắt hết đèn" → c2a đường tắt gửi
``HassTurnOff`` → HA trả ``Tool "HassTurnOff" not found`` → không đèn nào tắt, lượt
kết thúc không câu trả lời, loa im. Tên thật HA cấp là ``intent__HassTurnOff``
(``homeassistant/components/intent/llm.py``); cả ``light__HassLightSet``,
``homeassistant__GetLiveContext``, ``llm__GetDateTime``… cùng đổi.

Chốt ba điều: gửi đi đúng tên HA cấp; nhận lại (vòng 2) theo tên gốc; HA không cấp
công cụ đó thì c2a tự làm và trả lời bằng chữ chứ không gửi công cụ lạ.
"""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.protocol.openai_v1_chat_complete as api  # noqa: E402

LENH = [{"id": "c1", "type": "function",
         "function": {"name": "HassTurnOff",
                      "arguments": json.dumps({"domain": ["light"], "_eids": ["light.a", "light.b"]})}}]


def _cong_cu(*ten: str) -> list[dict]:
    return [{"type": "function", "function": {"name": t, "parameters": {}}} for t in ten]


def _chay(tools: list[dict]):
    body = {"model": "cx/auto", "_is_ha_request": True, "tools": tools,
            "messages": [{"role": "user", "content": "Tắt hết đèn"}]}
    with patch.object(api, "_apply_branch_routing", return_value=None), \
         patch.object(api, "_ha_local_level", return_value=None), \
         patch.object(api, "_ha_local_intent", return_value=[dict(t) for t in LENH]), \
         patch.object(api, "_exec_local_tool_calls") as tu_lam:
        return api._handle_main(body), tu_lam


class TenCongCuHaTests(unittest.TestCase):

    def test_ten_goc(self):
        self.assertEqual(api._ten_goc_ha("intent__HassTurnOff"), "HassTurnOff")
        self.assertEqual(api._ten_goc_ha("homeassistant__GetLiveContext"), "GetLiveContext")
        self.assertEqual(api._ten_goc_ha("HassTurnOff"), "HassTurnOff")

    def test_ha_moi_gui_dung_ten_co_tien_to(self):
        ra, tu_lam = _chay(_cong_cu("intent__HassTurnOn", "intent__HassTurnOff", "homeassistant__GetLiveContext"))
        ten = [t["function"]["name"] for t in ra["choices"][0]["message"]["tool_calls"]]
        self.assertEqual(ten, ["intent__HassTurnOff"])
        tu_lam.assert_not_called()

    def test_ha_cu_van_ten_cu(self):
        ra, _ = _chay(_cong_cu("HassTurnOn", "HassTurnOff"))
        self.assertEqual(ra["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "HassTurnOff")

    def test_ha_khong_cap_cong_cu_thi_c2a_tu_lam(self):
        """Agent HA tắt Assist API: gửi công cụ lạ là HA báo "not found" rồi im."""
        ra, tu_lam = _chay(_cong_cu("llm__GetDateTime"))
        tu_lam.assert_called_once()
        self.assertEqual(ra["choices"][0]["finish_reason"], "stop")
        self.assertIn("Đã thực hiện", ra["choices"][0]["message"]["content"])

    def test_vong_hai_nhan_ten_co_tien_to(self):
        ket_qua = {"response_type": "action_done",
                   "data": {"success": [{"name": "Đèn bếp", "type": "entity"}], "failed": []}}
        msgs = [{"role": "user", "content": "Tắt đèn bếp"},
                {"role": "assistant", "content": None,
                 "tool_calls": [{"id": "c1", "type": "function",
                                 "function": {"name": "intent__HassTurnOff", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "c1", "content": json.dumps(ket_qua, ensure_ascii=False)}]
        self.assertEqual(api._ha_confirm_text(msgs), "Đã tắt Đèn bếp rồi ạ.")


if __name__ == "__main__":
    unittest.main()
