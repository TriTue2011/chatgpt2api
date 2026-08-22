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


class MucLogKhiHubChuaLenTests(unittest.TestCase):
    """Lần dò ĐẦU tới hub cùng container bị từ chối → INFO, không phải WARNING.

    Đo trên máy chủ 22/08/2026 sau một lần khởi động lại: 26 dòng WARNING
    `mcp_call_failed` dồn trong 17 mili giây, rồi 26 dòng `mcp_tools_loaded`.
    Tức hệ thống tự hồi đủ 26 công cụ, nhưng vẫn kêu như vừa hỏng nặng.

    Cái giá thật của báo động sai ở đây: một chùm 26 dòng lúc khởi động trông Y
    HỆT một lần hub chết thật, nên không ai phân biệt được nữa.
    """

    def _muc_log(self, url: str, exc: Exception, so_lan_hong_truoc: int = 0):
        """Trả về mức log mà `_call` dùng khi gặp `exc`."""
        client = mcp_client.MCPSession(url)
        client._failure_count = so_lan_hong_truoc
        ghi: list[tuple[str, dict]] = []
        with mock.patch.object(mcp_client.logger, "info",
                               lambda d: ghi.append(("info", d))), \
             mock.patch.object(mcp_client.logger, "warning",
                               lambda d: ghi.append(("warning", d))), \
             mock.patch.object(mcp_client.urllib.request, "urlopen",
                               side_effect=exc):
            client._call("tools/list")
        return ghi[0][0] if ghi else None

    @staticmethod
    def _tu_choi() -> Exception:
        """Đúng hình dạng lỗi thật: URLError bọc ConnectionRefusedError."""
        import urllib.error
        return urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

    def test_lan_dau_hub_cung_container_thi_chi_INFO(self):
        self.assertEqual(
            self._muc_log("http://127.0.0.1:8005/vn_news/mcp", self._tu_choi()),
            "info")

    def test_lan_thu_hai_thi_len_WARNING(self):
        """Hub chết thật vẫn kêu — chỉ chậm một nhịp cooldown 8 giây."""
        self.assertEqual(
            self._muc_log("http://127.0.0.1:8005/vn_news/mcp", self._tu_choi(),
                          so_lan_hong_truoc=1),
            "warning")

    def test_hub_o_MAY_KHAC_thi_WARNING_ngay_lan_dau(self):
        """Chỉ hub cùng container mới có cớ 'đang khởi động cùng nhau'."""
        self.assertEqual(
            self._muc_log("http://10.9.9.9:8005/vn_news/mcp", self._tu_choi()),
            "warning")

    def test_loi_KHAC_connection_refused_thi_WARNING(self):
        """Timeout hay lỗi giao thức không phải chuyện 'chưa kịp lắng nghe'."""
        self.assertEqual(
            self._muc_log("http://127.0.0.1:8005/vn_news/mcp", TimeoutError("qua han")),
            "warning")
