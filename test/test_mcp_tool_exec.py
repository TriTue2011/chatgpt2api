"""Vòng chạy tool MCP trong một lượt trả lời.

Bối cảnh: một lỗi treo câm từng làm bot không phản hồi qua Zalo/Telegram.
Model quạt ra 8 lệnh `get_news` giống hệt nhau; 8 thread cùng đấm một
mcp-session-id mà FastMCP không phục vụ song song được → 7 thread treo;
`as_completed(timeout=30)` ném TimeoutError; khối `with ThreadPoolExecutor`
gọi shutdown(wait=True) khi thoát → chặn vĩnh viễn. Không exception nào nổi
lên nên không có log, không có fallback, kênh im lặng tuyệt đối.

Ba tính chất dưới đây là thứ giữ cho lỗi đó không quay lại.
"""

from __future__ import annotations

import os
import time
import types
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.ha_client as ha_client  # noqa: E402
import services.mcp_client as mcp_client  # noqa: E402
import services.protocol.openai_v1_chat_complete as m  # noqa: E402

_ROUTE = types.SimpleNamespace(provider="openai_oauth", model="gpt-5.5")
_FINAL = {"model": "gpt-5.5", "choices": [{
    "index": 0, "message": {"role": "assistant", "content": "FINAL"},
    "finish_reason": "stop"}]}


def _result_with(calls: list[tuple[str, str, str]]) -> dict:
    """calls = [(tool_call_id, tên tool, chuỗi JSON tham số), ...]"""
    return {"model": "gpt-5.5", "choices": [{"index": 0, "message": {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": cid, "type": "function",
                        "function": {"name": name, "arguments": args}}
                       for cid, name, args in calls]}}]}


class McpToolExecTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dispatch = m._dispatch
        self._exec = m._execute_mcp_tool
        self._budget = m._MCP_TOOLS_BUDGET
        # _execute_mcp_tools_in_response import hai hàm này BÊN TRONG thân hàm,
        # nên phải vá tận module gốc chứ vá trên `m` không ăn.
        self._known = mcp_client.get_enabled_mcp_tools
        self._ha = ha_client.get_ha_tools
        self._inject = m._inject_mcp_tools
        self.sent: list[dict] = []

        def fake_dispatch(route, messages, tools, tool_choice, body):
            self.sent = list(messages)
            return _FINAL

        m._dispatch = fake_dispatch
        # Cho gateway coi 'get_news' là tool server-side, khỏi cần MCP thật.
        mcp_client.get_enabled_mcp_tools = lambda: [
            {"type": "function", "function": {"name": "get_news", "parameters": {}}}]
        ha_client.get_ha_tools = lambda: []
        m._inject_mcp_tools = lambda *a, **k: []

    def tearDown(self) -> None:
        m._dispatch = self._dispatch
        m._execute_mcp_tool = self._exec
        m._MCP_TOOLS_BUDGET = self._budget
        mcp_client.get_enabled_mcp_tools = self._known
        ha_client.get_ha_tools = self._ha
        m._inject_mcp_tools = self._inject

    def _run(self, calls):
        return m._execute_mcp_tools_in_response(
            [{"role": "user", "content": "tin tức hôm nay"}],
            _result_with(calls), _ROUTE, {"stream": False})

    def _tool_msgs(self):
        return [x for x in self.sent if x.get("role") == "tool"]

    def test_duplicate_calls_execute_once_but_all_ids_answered(self) -> None:
        """8 lệnh trùng → chạy 1 lần, nhưng MỖI tool_call_id vẫn phải có đáp."""
        ran: list[str] = []

        def counting(name, args):
            ran.append(name)
            return "tin tức thật " + "x" * 40

        m._execute_mcp_tool = counting
        self._run([("call_%d" % i, "get_news", "{}") for i in range(8)])

        self.assertEqual(len(ran), 1, "lệnh trùng phải được gộp còn 1 lượt chạy")
        self.assertEqual([x["tool_call_id"] for x in self._tool_msgs()],
                         ["call_%d" % i for i in range(8)],
                         "thiếu/lệch tool_call_id là lượt sau provider từ chối payload")

    def test_distinct_calls_all_execute(self) -> None:
        """Tham số khác nhau thì KHÔNG được gộp nhầm."""
        ran: list[dict] = []

        def counting(name, args):
            ran.append(args)
            return "dữ liệu " + "y" * 40

        m._execute_mcp_tool = counting
        self._run([("c0", "get_news", '{"topic":"a"}'),
                   ("c1", "get_news", '{"topic":"b"}')])

        self.assertEqual(len(ran), 2)
        self.assertEqual(len(self._tool_msgs()), 2)

    def test_control_commands_are_never_deduped(self) -> None:
        """Lệnh điều khiển trùng nhau PHẢI chạy đủ số lần.

        Hai lệnh y hệt có thể là cố ý ("tăng âm lượng 2 lần") — gộp lại là
        chạy thiếu, thiết bị sai trạng thái mà bot vẫn báo xong.
        """
        ran: list[str] = []

        def counting(name, args):
            ran.append(name)
            return "Đã thực hiện " + "k" * 40

        m._execute_mcp_tool = counting
        mcp_client.get_enabled_mcp_tools = lambda: [
            {"type": "function", "function": {"name": "ha_call_service", "parameters": {}}}]
        self._run([("c0", "ha_call_service", '{"domain":"media_player","service":"volume_up"}'),
                   ("c1", "ha_call_service", '{"domain":"media_player","service":"volume_up"}')])

        self.assertEqual(len(ran), 2, "lệnh điều khiển không được gộp")

    def test_hung_tool_does_not_block_forever(self) -> None:
        """Một tool treo cứng KHÔNG được giữ luôn cả request.

        Đây là tính chất quan trọng nhất: kênh chat gọi orchestrate() thẳng
        trong tiến trình và không có timeout nào ở trên, nên treo ở đây là bot
        câm vĩnh viễn.
        """
        m._MCP_TOOLS_BUDGET = 2

        def hanging(name, args):
            if args.get("topic") == "hang":
                time.sleep(300)
            return "dữ liệu tốt " + "z" * 40

        m._execute_mcp_tool = hanging
        t0 = time.time()
        out = self._run([("c0", "get_news", '{"topic":"hang"}'),
                         ("c1", "get_news", '{"topic":"ok"}')])
        elapsed = time.time() - t0

        self.assertLess(elapsed, 30, "phải thoát theo ngân sách, không chờ vô hạn")
        self.assertEqual(out["choices"][0]["message"]["content"], "FINAL")

        by_id = {x["tool_call_id"]: str(x["content"]) for x in self._tool_msgs()}
        self.assertEqual(set(by_id), {"c0", "c1"}, "tool treo vẫn phải có message trả về")
        # Tool treo thành 'returned no result' → _looks_like_tool_error bắt được
        # → kéo web search dự phòng, trả lời thiếu nguồn còn hơn im lặng.
        self.assertTrue(m._looks_like_tool_error(by_id["c0"]))


if __name__ == "__main__":
    unittest.main()
