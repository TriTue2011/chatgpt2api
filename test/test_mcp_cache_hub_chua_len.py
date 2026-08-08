"""Cache tool MCP không được đóng băng kết quả RỖNG khi hub chưa lên.

Hiện trường: hub nằm CÙNG container và mất ~40s để mount hết MCP, còn gateway
lên trước. Lần dò đầu tiên gặp "connection refused" → danh sách tool rỗng, và
bản cũ cache nó suốt _TOOLS_CACHE_TTL = 15 phút. Kết quả là bot mất sạch tool
trong 15 phút dù hub đã sẵn sàng từ giây thứ 40 ("MCP count: 0" trong log khởi
động ngày 08/08).
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import mcp_client  # noqa: E402


class _PhienGia:
    """MCPSession giả: nối được hay không do test quyết định."""

    def __init__(self, noi_duoc: bool, tools=None):
        self.noi_duoc = noi_duoc
        self._tools = tools or []

    def ensure_connected(self):
        return self.noi_duoc

    def get_tools(self):
        return list(self._tools)


def _mot_tool(ten):
    return {"type": "function", "function": {"name": ten, "description": "", "parameters": {}}}


class CacheTtlTests(unittest.TestCase):
    def setUp(self):
        mcp_client.invalidate_tools_cache()
        self._cfg = mock.patch.object(
            mcp_client.config, "data",
            {"mcp_servers": [{"name": "hub", "url": "http://127.0.0.1:8005/x/mcp", "enabled": True}]},
        )
        self._cfg.start()
        self.addCleanup(self._cfg.stop)
        self.addCleanup(mcp_client.invalidate_tools_cache)

    def _chay_voi(self, phien):
        with mock.patch.dict(mcp_client._sessions, {}, clear=True), \
             mock.patch.object(mcp_client, "MCPSession", lambda *a, **kw: phien):
            return mcp_client.get_enabled_mcp_tools()

    def test_hub_chua_len_thi_ttl_ngan(self):
        tools = self._chay_voi(_PhienGia(noi_duoc=False))
        self.assertEqual(tools, [])
        self.assertEqual(mcp_client._tools_cache_ttl, mcp_client._TOOLS_CACHE_FAIL_TTL)
        self.assertLess(mcp_client._tools_cache_ttl, 60.0,
                        "hub chưa lên mà vẫn giữ cache rỗng hàng phút là lỗi cũ tái diễn")

    def test_hub_len_roi_thi_ttl_day_du(self):
        tools = self._chay_voi(_PhienGia(noi_duoc=True, tools=[_mot_tool("vn_weather")]))
        self.assertEqual(len(tools), 1)
        self.assertEqual(mcp_client._tools_cache_ttl, mcp_client._TOOLS_CACHE_TTL)

    def test_server_song_nhung_khong_co_tool_van_cache_day_du(self):
        """Rỗng vì server thật sự không có tool ≠ rỗng vì không nối được."""
        tools = self._chay_voi(_PhienGia(noi_duoc=True, tools=[]))
        self.assertEqual(tools, [])
        self.assertEqual(mcp_client._tools_cache_ttl, mcp_client._TOOLS_CACHE_TTL)

    def test_do_lai_sau_khi_ttl_ngan_het_han(self):
        """Hub lên muộn: lần gọi sau khi hết TTL ngắn phải thấy tool."""
        self._chay_voi(_PhienGia(noi_duoc=False))
        self.assertEqual(mcp_client._tools_cache, [])
        # Giả lập đã trôi qua TTL ngắn.
        mcp_client._tools_cache_ts -= (mcp_client._TOOLS_CACHE_FAIL_TTL + 1)
        tools = self._chay_voi(_PhienGia(noi_duoc=True, tools=[_mot_tool("vn_weather")]))
        self.assertEqual([t["function"]["name"] for t in tools], ["vn_weather"])


if __name__ == "__main__":
    unittest.main()
