"""Base URL của vn-mcp-hub nội bộ.

Hub phục vụ ``/api/rag/curate/<collection>`` — nạp SGK vào RAG và vòng lặp tự
học đều POST vào đó. Bản cũ suy ra hub bằng cách lấy MCP server ĐẦU TIÊN có
``/mcp`` trong URL, không xét enabled và không phân biệt nội bộ/bên ngoài. Khi
một MCP công khai (Exa) nằm đầu danh sách, mọi lượt POST bắn sang
``https://mcp.exa.ai/api/rag/curate/...`` và ăn 404 IM LẶNG: sách nạp "xong"
nhưng hỏi lại thì RAG rỗng.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.config import config, hub_base_url  # noqa: E402

_LOCAL = "http://127.0.0.1:8005/vn_news/mcp"
_REMOTE = "https://mcp.exa.ai/mcp"


class HubBaseUrlTests(unittest.TestCase):
    def test_explicit_key_wins(self) -> None:
        with mock.patch.dict(config.data, {"mcp_hub_url": "http://hub.local:9000/"}):
            self.assertEqual(hub_base_url(), "http://hub.local:9000")

    def test_remote_mcp_first_is_never_used_as_hub(self) -> None:
        """Đây chính là lỗi cũ: Exa đứng đầu → hub trỏ ra Internet."""
        servers = {
            "exa": {"url": _REMOTE, "enabled": True},
            "vn_news": {"url": _LOCAL, "enabled": True},
        }
        with mock.patch.dict(config.data, {"mcp_hub_url": "", "mcp_servers": servers}):
            got = hub_base_url()
        self.assertNotIn("exa.ai", got, "hub không bao giờ được trỏ ra MCP công khai")
        self.assertEqual(got, "http://127.0.0.1:8005")

    def test_disabled_local_server_is_skipped(self) -> None:
        servers = {
            "off": {"url": "http://127.0.0.1:9999/x/mcp", "enabled": False},
            "on": {"url": _LOCAL, "enabled": True},
        }
        with mock.patch.dict(config.data, {"mcp_hub_url": "", "mcp_servers": servers}):
            self.assertEqual(hub_base_url(), "http://127.0.0.1:8005")

    def test_falls_back_to_default_when_only_remote(self) -> None:
        servers = {"exa": {"url": _REMOTE, "enabled": True}}
        with mock.patch.dict(config.data, {"mcp_hub_url": "", "mcp_servers": servers}):
            self.assertEqual(hub_base_url(), "http://127.0.0.1:8005")

    def test_teacher_workspace_uses_the_same_resolver(self) -> None:
        """teacher_workspace từng có bản sao riêng của luật này."""
        from services.agent import teacher_workspace as tw
        servers = {"exa": {"url": _REMOTE, "enabled": True}, "vn": {"url": _LOCAL, "enabled": True}}
        with mock.patch.dict(config.data, {"mcp_hub_url": "", "mcp_servers": servers}):
            self.assertEqual(tw.config_hub_url(), "http://127.0.0.1:8005")


if __name__ == "__main__":
    unittest.main()
