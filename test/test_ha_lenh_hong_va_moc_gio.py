"""Lệnh nhà hỏng thì không được nói "đã bật", và lượt đường tắt phải để lại mốc giờ.

SỰ CỐ 13/09/2026 12:29. "Bật đèn tủ lạnh, đèn cửa sổ" mất 22 giây; nhật ký nhà
cho thấy đèn đổi trạng thái ở giây 18,7. Đo lại cùng câu trên máy chủ chỉ ra 3
giây — không có mốc nào nói 18,7 giây kia trôi ở chặng nào, còn log container
mất sạch mỗi lần triển khai. Nên mốc giờ phải nằm trong `meta` của nhật ký lượt
chạy (`runs.sqlite`), thứ sống qua các lần triển khai.

Khi soi thì lộ thêm lỗi "không kiểm chứng kết quả": `ha_client.call_service`
nuốt lỗi và trả False, nhưng `_exec_local_tool_calls` bỏ qua giá trị đó — lệnh
bị Home Assistant từ chối hay hết giờ vẫn bị coi là xong, và bot trả lời "đã
thực hiện xong" với cái đèn còn tắt.
"""
from __future__ import annotations

import json
import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.agent.orchestrator as orch  # noqa: E402
import services.ha_client as ha_client  # noqa: E402
import services.protocol.openai_v1_chat_complete as api  # noqa: E402
from services.agent import run_journal, state  # noqa: E402

LENH_BAT_HAI_DEN = [
    {"function": {"name": "HassTurnOn",
                  "arguments": json.dumps({"name": "Đèn tủ lạnh", "_eids": ["light.a"]})}},
    {"function": {"name": "HassTurnOn",
                  "arguments": json.dumps({"name": "Đèn cửa sổ", "_eids": ["light.b"]})}},
]


class LenhHAHongPhaiRaiseTests(unittest.TestCase):

    def test_HA_tu_choi_mot_lenh_thi_raise(self):
        with patch.object(ha_client, "call_service",
                          side_effect=lambda d, s, data: data["entity_id"] != "light.b"):
            with self.assertRaises(RuntimeError):
                api._exec_local_tool_calls(LENH_BAT_HAI_DEN)

    def test_HA_nhan_du_thi_khong_raise(self):
        with patch.object(ha_client, "call_service", return_value=True):
            api._exec_local_tool_calls(LENH_BAT_HAI_DEN)

    def test_duong_tat_KHONG_noi_da_xong_khi_HA_tu_choi(self):
        with patch.object(api, "_ha_local_level", return_value=None), \
             patch.object(api, "_ha_local_intent", return_value=LENH_BAT_HAI_DEN), \
             patch.object(ha_client, "call_service", return_value=False):
            van, dieu_khien, _ = api.ha_local_fastpath_chi_tiet("Bật đèn tủ lạnh, đèn cửa sổ")
        self.assertNotEqual(van, "Đã thực hiện xong lệnh điều khiển thiết bị.")
        self.assertFalse(dieu_khien, "lệnh chưa chạy thì không được coi là đã điều khiển")


class DuongTatGhiMocGioTests(unittest.TestCase):

    def test_meta_nhat_ky_co_moc_tung_chang(self):
        bat: dict = {}

        def _duong_tat(_cau):
            time.sleep(0.06)       # dò + gọi HA
            return ("Đã thực hiện xong lệnh điều khiển thiết bị.", True, "_ha_local_intent")

        def _dien_dat(*a, **k):
            time.sleep(0.03)
            return {"choices": [{"message": {"content": "Em đã bật rồi ạ."}}]}

        with patch.object(api, "ha_local_fastpath_chi_tiet", side_effect=_duong_tat), \
             patch.object(orch, "call_model", side_effect=_dien_dat), \
             patch.object(orch, "_persist_history", lambda *a, **k: None), \
             patch.object(state, "load_memory", return_value=""), \
             patch.object(run_journal, "log_run", side_effect=lambda **k: bat.update(k)):
            orch._orchestrate_locked("Bật đèn tủ lạnh, đèn cửa sổ", "u_test_moc_gio",
                                     ha_fastpath=True)

        self.assertEqual(bat.get("status"), "ha_fastpath")
        gd = (bat.get("meta") or {}).get("giai_doan") or {}
        self.assertEqual(set(gd), {"truoc_ms", "do_va_lam_ms", "dien_dat_ms"})
        self.assertGreaterEqual(gd["do_va_lam_ms"], 50, "chặng gọi HA phải đo được")
        self.assertGreaterEqual(gd["dien_dat_ms"], 25, "chặng diễn đạt phải đo được")
        self.assertGreaterEqual(gd["truoc_ms"], 0)
        self.assertLessEqual(sum(gd.values()), bat["duration_ms"] + 5,
                             "tổng các chặng không được vượt thời gian cả lượt")


if __name__ == "__main__":
    unittest.main()
