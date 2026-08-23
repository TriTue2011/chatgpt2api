"""MCP client compatibility at the public ``MCPSession`` seam.

The fake servers speak real JSON-RPC over localhost HTTP.  They are protocol
peers (S7), not mocks of ``mcp_client`` internals, so these tests keep working
if the implementation is later replaced by the official MCP SDK.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator
from unittest import mock

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import mcp_client  # noqa: E402
from services.mcp_client import MCPSession  # noqa: E402


pytestmark = pytest.mark.integration


class _ModernN8nHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    requests: list[dict[str, Any]] = []

    def log_message(self, _format: str, *_args: Any) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP hook
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = json.loads(raw)
        type(self).requests.append({
            "body": body,
            "headers": {k.lower(): v for k, v in self.headers.items()},
        })
        method = body["method"]
        params = body.get("params") or {}

        if method == "server/discover":
            result = {
                "resultType": "complete",
                "supportedVersions": ["2026-07-28"],
                "capabilities": {"tools": {}},
                "instructions": "Use these workflow tools carefully.",
                "_meta": {
                    "io.modelcontextprotocol/serverInfo": {
                        "name": "n8n-instance",
                        "version": "2.33.0",
                    }
                },
            }
        elif method == "tools/list" and not params.get("cursor"):
            result = {
                "tools": [{
                    "name": "search_workflows",
                    "description": "Search workflows",
                    "inputSchema": {"type": "object", "properties": {}},
                }],
                "nextCursor": "page-2",
                "ttlMs": 60000,
                "cacheScope": "private",
            }
        elif method == "tools/list":
            result = {
                "tools": [{
                    "name": "execute_workflow",
                    "description": "Execute a workflow",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workflowId": {"type": "string"},
                        "region": {"type": "string", "x-mcp-header": "Region"},
                        "greeting": {"type": "string", "x-mcp-header": "Greeting"},
                    },
                    "required": ["workflowId"],
                },
                }]
            }
        elif method == "tools/call":
            result = {
                "content": [],
                "structuredContent": {
                    "executionId": "e-123",
                    "status": "success",
                },
                "isError": False,
            }
        else:
            self.send_error(404)
            return

        payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class _LegacyN8nHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    requests: list[dict[str, Any]] = []

    def log_message(self, _format: str, *_args: Any) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP hook
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = json.loads(raw)
        headers = {k.lower(): v for k, v in self.headers.items()}
        type(self).requests.append({"body": body, "headers": headers})
        method = body["method"]

        if method == "server/discover":
            envelope = {
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32601, "message": "Method not found"},
            }
        elif method == "initialize":
            envelope = {
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "n8n-trigger", "version": "1.120.0"},
                },
            }
        elif method == "notifications/initialized":
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        elif method == "tools/list":
            envelope = {
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"tools": [{
                    "name": "run_order_flow",
                    "description": "Run an n8n workflow",
                    "inputSchema": {"type": "object", "properties": {}},
                }]},
            }
        elif method == "tools/call":
            envelope = {
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "content": [{"type": "text", "text": "workflow finished"}],
                    "isError": False,
                },
            }
        else:
            self.send_error(404)
            return

        payload = json.dumps(envelope).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        if method == "initialize":
            self.send_header("Mcp-Session-Id", "n8n-session-1")
        event = b"event: message\ndata: " + payload + b"\n\n"
        self.send_header("Content-Length", str(len(event)))
        self.end_headers()
        self.wfile.write(event)


class _CollisionHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    label = "unset"
    requests: list[dict[str, Any]] = []

    def log_message(self, _format: str, *_args: Any) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP hook
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        type(self).requests.append({"body": body})
        method = body["method"]
        if method == "server/discover":
            result = {
                "resultType": "complete",
                "supportedVersions": ["2026-07-28"],
                "capabilities": {"tools": {}},
                "_meta": {"io.modelcontextprotocol/serverInfo": {
                    "name": self.label,
                    "version": "1",
                }},
            }
        elif method == "tools/list":
            result = {"tools": [{
                "name": "lookup",
                "description": f"Lookup on {self.label}",
                "inputSchema": {"type": "object", "properties": {}},
            }]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": self.label}]}
        else:
            self.send_error(404)
            return
        payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class _AlphaHandler(_CollisionHandler):
    label = "alpha"


class _BetaHandler(_CollisionHandler):
    label = "beta"


class _LegacySseHandler(BaseHTTPRequestHandler):
    """Deprecated HTTP+SSE transport still emitted by older MCP servers."""

    protocol_version = "HTTP/1.1"
    events: queue.Queue[dict[str, Any]] = queue.Queue()
    requests: list[dict[str, Any]] = []

    def log_message(self, _format: str, *_args: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/sse":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(b"event: endpoint\ndata: /messages\n\n")
        self.wfile.flush()
        while True:
            try:
                envelope = type(self).events.get(timeout=5)
            except queue.Empty:
                return
            payload = json.dumps(envelope).encode()
            self.wfile.write(b"event: message\ndata: " + payload + b"\n\n")
            self.wfile.flush()

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/messages":
            self.send_error(405)
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        type(self).requests.append({
            "body": body,
            "headers": {k.lower(): v for k, v in self.headers.items()},
        })
        method = body["method"]
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "legacy-sse", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": [{
                "name": "old_workflow",
                "description": "Old SSE workflow",
                "inputSchema": {"type": "object", "properties": {}},
            }]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": "sse finished"}]}
        elif method == "notifications/initialized":
            result = None
        else:
            self.send_error(404)
            return
        self.send_response(202)
        self.send_header("Content-Length", "0")
        self.end_headers()
        if "id" in body:
            type(self).events.put({"jsonrpc": "2.0", "id": body["id"], "result": result})


@contextmanager
def _serve(handler: type[BaseHTTPRequestHandler]) -> Iterator[str]:
    handler.requests = []  # type: ignore[attr-defined]
    if hasattr(handler, "events"):
        handler.events = queue.Queue()  # type: ignore[attr-defined]
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/mcp-server/http"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_n8n_modern_protocol_discovers_every_tool_page_and_calls_tools() -> None:
    with _serve(_ModernN8nHandler) as url:
        client = MCPSession(url, headers={"X-Tenant": "school-a"})

        tools = client.get_tools()
        result = client.call_tool("execute_workflow", {
            "workflowId": "wf-1",
            "region": "asia-east1",
            "greeting": "Chào n8n",
        })

    assert [t["function"]["name"] for t in tools] == [
        "search_workflows",
        "execute_workflow",
    ]
    assert json.loads(result or "null") == {
        "executionId": "e-123",
        "status": "success",
    }
    assert client.tools_ttl_ms == 60000

    requests = _ModernN8nHandler.requests
    assert [r["body"]["method"] for r in requests] == [
        "server/discover",
        "tools/list",
        "tools/list",
        "tools/call",
    ]
    for request in requests:
        assert request["headers"]["mcp-protocol-version"] == "2026-07-28"
        assert request["headers"]["mcp-method"] == request["body"]["method"]
        assert request["headers"]["x-tenant"] == "school-a"
        meta = request["body"]["params"]["_meta"]
        assert meta["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
        assert meta["io.modelcontextprotocol/clientInfo"]["name"] == "chatgpt2api"
    assert requests[-1]["headers"]["mcp-name"] == "execute_workflow"
    assert requests[-1]["headers"]["mcp-param-region"] == "asia-east1"
    assert requests[-1]["headers"]["mcp-param-greeting"] == "=?base64?Q2jDoG8gbjhu?="


def test_n8n_legacy_fallback_keeps_session_auth_and_negotiated_version() -> None:
    with _serve(_LegacyN8nHandler) as url:
        client = MCPSession(
            url,
            "n8n-personal-token",
            headers={"X-N8N-Project": "sales", "Host": "attacker.invalid"},
        )

        tools = client.get_tools()
        result = client.call_tool("run_order_flow", {})

    assert [t["function"]["name"] for t in tools] == ["run_order_flow"]
    assert result == "workflow finished"
    assert client.protocol_version == "2024-11-05"
    assert client.server_name == "n8n-trigger"

    requests = _LegacyN8nHandler.requests
    assert [r["body"]["method"] for r in requests] == [
        "server/discover",
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]
    assert "mcp-protocol-version" not in requests[1]["headers"]
    for request in requests[2:]:
        assert request["headers"]["mcp-protocol-version"] == "2024-11-05"
        assert request["headers"]["mcp-session-id"] == "n8n-session-1"
        assert request["headers"]["authorization"] == "Bearer n8n-personal-token"
        assert request["headers"]["x-n8n-project"] == "sales"
        assert request["headers"]["host"] != "attacker.invalid"


def test_duplicate_tool_names_stay_callable_on_the_correct_server() -> None:
    with _serve(_AlphaHandler) as alpha_url, _serve(_BetaHandler) as beta_url:
        installed = [
            {"id": "alpha", "name": "Alpha", "url": alpha_url, "enabled": True},
            {"id": "beta", "name": "Beta", "url": beta_url, "enabled": True},
        ]
        with mock.patch.object(mcp_client.config, "data", {"mcp_servers": installed}), \
             mock.patch.dict(mcp_client._sessions, {}, clear=True):
            mcp_client.invalidate_tools_cache()
            tools = mcp_client.get_enabled_mcp_tools()
            first = mcp_client.call_mcp_tool("lookup", {})
            second = mcp_client.call_mcp_tool("beta__lookup", {})
            mcp_client.invalidate_tools_cache()

    assert [t["function"]["name"] for t in tools] == ["lookup", "beta__lookup"]
    assert first == "alpha"
    assert second == "beta"


@pytest.mark.parametrize("transport", ["sse", "auto"])
def test_legacy_http_sse_transport_explicit_and_auto_fallback(transport: str) -> None:
    with _serve(_LegacySseHandler) as streamable_url:
        sse_url = streamable_url.replace("/mcp-server/http", "/sse")
        client = MCPSession(sse_url, transport=transport)
        tools = client.get_tools()
        result = client.call_tool("old_workflow", {})

    assert [t["function"]["name"] for t in tools] == ["old_workflow"]
    assert result == "sse finished"
    assert client.protocol_version == "2024-11-05"
    assert [r["body"]["method"] for r in _LegacySseHandler.requests] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]


def test_public_validator_reports_negotiated_protocol_without_exposing_credentials() -> None:
    with _serve(_ModernN8nHandler) as url:
        report = mcp_client.validate_mcp_server(
            url,
            api_key="must-not-leak",
            headers={"X-Tenant": "private-tenant"},
            transport="auto",
        )

    rendered = json.dumps(report)
    assert report["ok"] is True
    assert report["name"] == "n8n-instance"
    assert report["protocol_version"] == "2026-07-28"
    assert report["transport"] == "streamable_http"
    assert [tool["name"] for tool in report["tools"]] == [
        "search_workflows",
        "execute_workflow",
    ]
    assert "must-not-leak" not in rendered
    assert "private-tenant" not in rendered


# ── Tương thích rộng: SSE giữ mở, lỗi tool, MRTR, server không có tool ──────


def _send_json(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: int = 200) -> None:
    raw = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _discover(name: str, capabilities: dict[str, Any]) -> dict[str, Any]:
    return {
        "resultType": "complete",
        "supportedVersions": ["2026-07-28"],
        "capabilities": capabilities,
        "instructions": "",
        "_meta": {"io.modelcontextprotocol/serverInfo": {"name": name, "version": "1"}},
    }


class _ModernBase(BaseHTTPRequestHandler):
    """Server MCP 2026-07-28 tối giản để các lớp con chỉ khai phần khác nhau."""

    protocol_version = "HTTP/1.1"
    requests: list[dict[str, Any]] = []
    ten = "modern"
    capabilities: dict[str, Any] = {"tools": {}}
    tools: list[dict[str, Any]] = []
    loi_discover = False
    loi_tools_list = False

    def log_message(self, _format: str, *_args: Any) -> None:
        pass

    def _loi_method(self, body: dict[str, Any]) -> None:
        _send_json(self, {
            "jsonrpc": "2.0", "id": body["id"],
            "error": {"code": -32601, "message": "Method not found"},
        }, status=404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP hook
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        type(self).requests.append({
            "body": body,
            "headers": {k.lower(): v for k, v in self.headers.items()},
        })
        method = body["method"]
        if method == "server/discover":
            if type(self).loi_discover:
                self._loi_method(body)
                return
            _send_json(self, {"jsonrpc": "2.0", "id": body["id"],
                              "result": _discover(type(self).ten, type(self).capabilities)})
        elif method == "tools/list":
            if type(self).loi_tools_list:
                self._loi_method(body)
                return
            _send_json(self, {"jsonrpc": "2.0", "id": body["id"],
                              "result": {"resultType": "complete", "tools": list(type(self).tools)}})
        elif method == "tools/call":
            self.goi_tool(body)
        else:
            self.send_error(404)

    def goi_tool(self, body: dict[str, Any]) -> None:
        _send_json(self, {"jsonrpc": "2.0", "id": body["id"],
                          "result": {"resultType": "complete", "content": []}})


class _KeepOpenSseHandler(_ModernBase):
    """Trả phản hồi trên dòng SSE rồi GIỮ dòng mở (chỉ SHOULD mới phải đóng)."""

    ten = "keep-open"
    tools = [{"name": "cham", "description": "Chạy lâu",
              "inputSchema": {"type": "object", "properties": {}}}]
    giu_them = 3.0

    def goi_tool(self, body: dict[str, Any]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {
            "resultType": "complete", "content": [{"type": "text", "text": "xong"}],
        }}).encode()
        self.wfile.write(b": keep-alive\n\n")
        self.wfile.write(b"event: message\ndata: " + payload + b"\n\n")
        self.wfile.flush()
        het = time.monotonic() + type(self).giu_them
        while time.monotonic() < het:
            try:
                self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
            except OSError:
                return
            time.sleep(0.05)


class _ToolErrorHandler(_ModernBase):
    ten = "loi-tool"
    tools = [{"name": "tra_cuu", "description": "Tra cứu",
              "inputSchema": {"type": "object", "properties": {}}}]

    def goi_tool(self, body: dict[str, Any]) -> None:
        _send_json(self, {"jsonrpc": "2.0", "id": body["id"],
                          "error": {"code": -32602, "message": "Thiếu tham số 'ma_so'"}})


class _MrtrHandler(_ModernBase):
    ten = "mrtr"
    tools = [
        {"name": "tao_db", "description": "Tạo DB",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "hoi_nguoi_dung", "description": "Hỏi người dùng",
         "inputSchema": {"type": "object", "properties": {}}},
    ]

    def goi_tool(self, body: dict[str, Any]) -> None:
        params = body.get("params") or {}
        if params.get("name") == "hoi_nguoi_dung":
            result = {
                "resultType": "input_required",
                "inputRequests": {"github_login": {
                    "method": "elicitation/create",
                    "params": {"mode": "form", "message": "Tên GitHub?"},
                }},
                "requestState": "khong-dung-toi",
            }
        elif params.get("requestState") == "trang-thai-1":
            result = {"resultType": "complete",
                      "content": [{"type": "text", "text": "đã tạo xong"}]}
        else:
            result = {"resultType": "input_required", "requestState": "trang-thai-1"}
        _send_json(self, {"jsonrpc": "2.0", "id": body["id"], "result": result})


class _NoToolsHandler(_ModernBase):
    ten = "chi-co-resources"
    capabilities = {"resources": {}}
    loi_tools_list = True


class _NoDiscoverHandler(_ModernBase):
    ten = "thieu-discover"
    loi_discover = True
    tools = [{"name": "chay", "description": "Chạy",
              "inputSchema": {"type": "object", "properties": {}}}]


class _HeaderSchemaHandler(_ModernBase):
    ten = "header-schema"
    tools = [
        {"name": "trien_khai", "description": "Triển khai", "inputSchema": {
            "type": "object",
            "properties": {
                "vung": {"type": "object", "properties": {
                    "ma": {"type": "string", "x-mcp-header": "Region"},
                }},
                "so_luong": {"type": "integer", "x-mcp-header": "Count"},
            },
        }},
        {"name": "khai_sai", "description": "Trùng tên header", "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "string", "x-mcp-header": "Dup"},
                "b": {"type": "string", "x-mcp-header": "dup"},
            },
        }},
    ]

    def goi_tool(self, body: dict[str, Any]) -> None:
        _send_json(self, {"jsonrpc": "2.0", "id": body["id"], "result": {
            "resultType": "complete", "content": [{"type": "text", "text": "ok"}]}})


class _FragileSseHandler(BaseHTTPRequestHandler):
    """HTTP+SSE cũ: đóng dòng GET ngay sau mỗi lần trả kết quả tools/call."""

    protocol_version = "HTTP/1.1"
    events: queue.Queue[dict[str, Any] | None] = queue.Queue()
    requests: list[dict[str, Any]] = []
    gets = 0
    lan_goi = 0

    def log_message(self, _format: str, *_args: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/sse":
            self.send_error(404)
            return
        type(self).gets += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b"event: endpoint\ndata: /messages\n\n")
        self.wfile.flush()
        while True:
            try:
                envelope = type(self).events.get(timeout=5)
            except queue.Empty:
                return
            if envelope is None:
                return
            payload = json.dumps(envelope).encode()
            self.wfile.write(b"event: message\ndata: " + payload + b"\n\n")
            self.wfile.flush()

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/messages":
            self.send_error(405)
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        type(self).requests.append({"body": body})
        method = body["method"]
        dong_dong = False
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "sse-mong-manh", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "viec", "description": "Việc",
                                 "inputSchema": {"type": "object", "properties": {}}}]}
        elif method == "tools/call":
            type(self).lan_goi += 1
            result = {"content": [{"type": "text", "text": f"lần {type(self).lan_goi}"}]}
            dong_dong = True
        else:
            result = None
        self.send_response(202)
        self.send_header("Content-Length", "0")
        self.end_headers()
        if "id" in body:
            type(self).events.put({"jsonrpc": "2.0", "id": body["id"], "result": result})
        if dong_dong:
            type(self).events.put(None)


def test_streamable_http_giu_dong_sse_mo_van_tra_ket_qua_ngay() -> None:
    """Đọc tới phản hồi rồi đóng, không đợi server đóng dòng.

    Bản cũ gọi `resp.read()` nên phải chờ server đóng — server nào giữ dòng
    lâu hơn timeout là mất trắng kết quả đã về.
    """
    with _serve(_KeepOpenSseHandler) as url:
        client = MCPSession(url)
        assert [t["function"]["name"] for t in client.get_tools()] == ["cham"]
        bat_dau = time.monotonic()
        ket_qua = client.call_tool("cham", {})
        troi_qua = time.monotonic() - bat_dau

    assert ket_qua == "xong"
    assert troi_qua < _KeepOpenSseHandler.giu_them / 2


def test_loi_tools_call_duoc_noi_ro_va_khong_goi_lai_vo_ich() -> None:
    with _serve(_ToolErrorHandler) as url:
        client = MCPSession(url)
        client.get_tools()
        ket_qua = client.call_tool("tra_cuu", {})

    assert "Thiếu tham số 'ma_so'" in (ket_qua or "")
    methods = [r["body"]["method"] for r in _ToolErrorHandler.requests]
    assert methods.count("tools/call") == 1


def test_mrtr_gui_lai_request_state_va_bao_khi_can_hoi_nguoi_that() -> None:
    with _serve(_MrtrHandler) as url:
        client = MCPSession(url)
        client.get_tools()
        xong = client.call_tool("tao_db", {"ten": "db-1"})
        can_hoi = client.call_tool("hoi_nguoi_dung", {})

    assert xong == "đã tạo xong"
    goi = [r["body"] for r in _MrtrHandler.requests if r["body"]["method"] == "tools/call"]
    assert goi[1]["params"]["requestState"] == "trang-thai-1"
    assert goi[1]["params"]["arguments"] == {"ten": "db-1"}
    assert goi[0]["id"] != goi[1]["id"]
    assert "elicitation/create" in (can_hoi or "")


def test_server_chi_co_resources_van_duoc_coi_la_dang_song() -> None:
    with _serve(_NoToolsHandler) as url:
        client = MCPSession(url)
        assert client.get_tools() == []
        assert client.ensure_connected() is True

    assert client._failure_count == 0
    assert client.server_name == "chi-co-resources"


def test_server_moi_thieu_discover_khong_bi_tut_ve_initialize() -> None:
    with _serve(_NoDiscoverHandler) as url:
        client = MCPSession(url)
        tools = client.get_tools()

    assert [t["function"]["name"] for t in tools] == ["chay"]
    assert client.protocol_version == "2026-07-28"
    assert "initialize" not in [r["body"]["method"] for r in _NoDiscoverHandler.requests]


def test_x_mcp_header_long_nhau_duoc_gui_va_tool_khai_sai_bi_loai() -> None:
    with _serve(_HeaderSchemaHandler) as url:
        client = MCPSession(url)
        ten = [t["function"]["name"] for t in client.get_tools()]
        client.call_tool("trien_khai", {"vung": {"ma": "asia-southeast1"}, "so_luong": 3})

    assert ten == ["trien_khai"]
    goi = next(r for r in _HeaderSchemaHandler.requests if r["body"]["method"] == "tools/call")
    assert goi["headers"]["mcp-param-region"] == "asia-southeast1"
    assert goi["headers"]["mcp-param-count"] == "3"


def test_dong_sse_cu_bi_dut_thi_noi_lai_chu_khong_hong_vinh_vien() -> None:
    _FragileSseHandler.gets = 0
    _FragileSseHandler.lan_goi = 0
    with _serve(_FragileSseHandler) as streamable_url:
        sse_url = streamable_url.replace("/mcp-server/http", "/sse")
        client = MCPSession(sse_url, transport="sse")
        assert [t["function"]["name"] for t in client.get_tools()] == ["viec"]
        mot = client.call_tool("viec", {})
        for _ in range(200):
            if not client._sse_reader_alive:
                break
            time.sleep(0.02)
        assert client._sse_reader_alive is False
        hai = client.call_tool("viec", {})

    assert (mot, hai) == ("lần 1", "lần 2")
    assert _FragileSseHandler.gets == 2


class _SchemaLaHandler(_ModernBase):
    """Server khai tool thiếu/sai `inputSchema` — vẫn phải dùng được."""

    ten = "schema-la"
    tools = [
        {"name": "khong_schema", "description": "Không có schema", "inputSchema": None},
        {"name": "thieu_han", "description": "Thiếu hẳn khoá schema"},
    ]


def test_tool_thieu_input_schema_khong_lam_hong_dinh_nghia_tool() -> None:
    with _serve(_SchemaLaHandler) as url:
        client = MCPSession(url)
        tools = client.get_tools()

    assert [t["function"]["name"] for t in tools] == ["khong_schema", "thieu_han"]
    assert all(t["function"]["parameters"] == {"type": "object", "properties": {}}
               for t in tools)
