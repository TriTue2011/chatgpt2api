"""Trần số vòng model-gọi-tool trong một lượt (`_MAX_STEPS`).

Đo thật 12/08 trên máy chủ: nhánh «để em viết bài Facebook» tiêu hết trần 4
bước cho use_skill → read_webpage → find_in_text ×2 → read_webpage rồi trả về
"Em xử lý hơi lâu…" khi chưa viết được chữ nào — runs.sqlite ghi
status=max_steps, 33,8 giây. Mọi việc dạng "tra tài liệu rồi viết" đều chết
giữa đường ở trần đó.

File riêng, KHÔNG gộp vào test_orchestrate_watchdog.py: test treo ở đó cố tình
rò một thread `time.sleep(300)`, chạy riêng file ấy là phải chờ hết 5 phút.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.agent.orchestrator as orch  # noqa: E402
from test._fakes import install_data_dir  # noqa: E402


def _luot_goi_tool(i: int) -> dict:
    """Một lượt model đòi gọi tool. Tên tool không tồn tại là đủ: vòng lặp trả
    "(không có công cụ …)" rồi đi tiếp — ở đây chỉ đếm số vòng."""
    return {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": f"c{i}", "type": "function",
         "function": {"name": "tool_khong_ton_tai", "arguments": "{}"}}]}}]}


_XONG = {"choices": [{"message": {"content": "Đây là bài nháp ạ."}}]}


class TranSoBuocTests(unittest.TestCase):
    def test_nam_vong_goi_tool_van_ve_duoc_cau_tra_loi(self) -> None:
        seq = [_luot_goi_tool(i) for i in range(5)] + [_XONG]
        with install_data_dir():
            with mock.patch.object(orch, "call_model", side_effect=seq) as fake:
                out = orch.orchestrate("đọc trang kia rồi viết bài", "zalop_step")
        self.assertIn("nháp", (out.get("text") or "").lower())
        self.assertNotIn("hơi lâu", out.get("text") or "")
        self.assertEqual(fake.call_count, 6)

    def test_van_con_tran_de_khong_chay_vo_han(self) -> None:
        """Nới bước không có nghĩa là bỏ trần — hết bước vẫn phải trả lời."""
        seq = [_luot_goi_tool(i) for i in range(orch._MAX_STEPS + 3)]
        with install_data_dir():
            with mock.patch.object(orch, "call_model", side_effect=seq) as fake:
                out = orch.orchestrate("cứ gọi tool mãi", "zalop_step2")
        self.assertEqual(fake.call_count, orch._MAX_STEPS)
        self.assertTrue(str(out.get("text") or "").strip())



class TranTokenTests(unittest.TestCase):
    """Đo thật 12/08 21:29: bài Facebook 300–450 từ bị cắt ngang giữa câu vì
    runtime mặc định max_tokens=900. Tiếng Việt tốn cỡ 2 token/từ."""

    def test_vong_lap_xin_du_token_cho_mot_bai_viet(self) -> None:
        with install_data_dir():
            with mock.patch.object(orch, "call_model",
                                   return_value=_XONG) as fake:
                orch.orchestrate("viết giúp tôi một bài dài", "zalop_tok")
        # Bài dài nhất luồng Facebook đặt hàng là 1000 từ ≈ 2000 token tiếng
        # Việt, chưa tính lời dẫn — trần phải dư ra kha khá.
        self.assertGreaterEqual(fake.call_args.kwargs.get("max_tokens", 0), 3000)

if __name__ == "__main__":
    unittest.main()
