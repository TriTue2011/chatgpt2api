"""Fast-path HA phải chịu bộ lọc nhóm — key vai 'user' KHÔNG điều khiển/đọc
trạng thái nhà qua fast-path.

Báo cáo bảo mật 07/08 (Critical): role ceiling ở api/ai.py đặt x_allowed_groups
đúng, nhưng fast-path (_ha_local_level/_ha_local_intent…) chạy TRƯỚC khi tôn
trọng nó → key user vẫn bật/tắt thiết bị. Nay 5 fast-path (confirm/level/intent
/query/status) gác thêm _thread_denies(body, "homeassistant").
"""
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class HaFastpathGateTests(unittest.TestCase):
    def setUp(self):
        from services.protocol.openai_v1_chat_complete import _thread_denies
        from api.ai import _effective_allowed_groups
        self._denies = _thread_denies
        self._eff = _effective_allowed_groups

    def test_body_vai_user_thi_chan_homeassistant(self):
        # Trần vai 'user' (cụm D) → x_allowed_groups KHÔNG có homeassistant.
        allow = self._eff("user", None, None)
        body = {"x_allowed_groups": allow}
        self.assertTrue(self._denies(body, "homeassistant"),
                        "fast-path HA phải bị chặn cho vai user")

    def test_body_admin_khong_dat_thi_khong_chan(self):
        # admin không trần → x_allowed_groups None → _thread_denies False.
        eff = self._eff("admin", None, None)
        self.assertIsNone(eff)
        body = {}  # không có x_allowed_groups
        self.assertFalse(self._denies(body, "homeassistant"),
                         "admin vẫn được fast-path HA")

    def test_x_no_smart_home_cung_chan(self):
        self.assertTrue(self._denies({"x_no_smart_home": True}, "homeassistant"))

    def test_thread_cho_phep_ha_thi_khong_chan(self):
        body = {"x_allowed_groups": ["homeassistant", "web"]}
        self.assertFalse(self._denies(body, "homeassistant"))


if __name__ == "__main__":
    unittest.main()
