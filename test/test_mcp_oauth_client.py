"""Authenticated MCP lifecycle at the HTTP boundary, including replay policy."""
import io
import json
from email.message import Message
from urllib.error import HTTPError, URLError

import pytest

from services import mcp_client, mcp_oauth
from test.test_mcp_oauth import Provider, RESOURCE, CALLBACK, ISSUER


class Response(io.BytesIO):
    status = 200

    def getheader(self, name):
        return "application/json" if name.lower() == "content-type" else None


@pytest.fixture
def setup(tmp_path, monkeypatch):
    provider = Provider()
    manager = mcp_oauth.OAuthManager(mcp_oauth.OAuthStore(tmp_path), provider)
    start = manager.begin(RESOURCE, CALLBACK, "binding")
    manager.finish(start["state"], "binding", code="code", issuer=ISSUER)
    monkeypatch.setattr(mcp_oauth, "_manager", manager)
    return manager, provider, start["oauth_id"]


def wire(monkeypatch, *, reject=0, network_failure=False):
    calls = []
    def open_request(self, request, timeout):
        body = json.loads(request.data)
        calls.append((body, request.get_header("Authorization")))
        method = body["method"]
        if method == "server/discover":
            payload = {"error": {"code": -32601, "message": "Method not found"}}
        elif method == "initialize":
            payload = {"result": {"protocolVersion": "2025-11-25", "serverInfo": {"name": "OAuth Test", "version": "1"}, "capabilities": {"tools": {}}}}
        elif method == "notifications/initialized":
            return Response(b"")
        elif method == "tools/list":
            payload = {"result": {"tools": [{"name": "lookup", "description": "Lookup", "inputSchema": {"type": "object"}}]}}
        elif method == "tools/call":
            count = sum(c[0]["method"] == "tools/call" for c in calls)
            if network_failure:
                raise URLError("secret-access must not leak")
            if count <= reject:
                raise HTTPError(RESOURCE, 401, "Unauthorized", Message(), Response(b"secret-access"))
            payload = {"result": {"content": [{"type": "text", "text": "Vietnam research"}]}}
        else:
            raise AssertionError(method)
        return Response(json.dumps({"jsonrpc": "2.0", "id": body.get("id"), **payload}).encode())
    monkeypatch.setattr(mcp_client.MCPSession, "_open_request", open_request)
    return calls


def test_discover_call_refresh_and_disconnect_cached_session(setup, monkeypatch):
    manager, provider, oauth_id = setup
    calls = wire(monkeypatch, reject=1)
    session = mcp_client.MCPSession(RESOURCE, oauth_id=oauth_id, transport="streamable_http")
    assert session.ensure_connected()
    assert session.get_tools()[0]["function"]["name"] == "lookup"
    assert "Vietnam research" in session.call_tool("lookup", {})
    tool_calls = [c for c in calls if c[0]["method"] == "tools/call"]
    assert [c[1] for c in tool_calls] == ["Bearer secret-access", "Bearer refreshed-access"]
    assert provider.refreshes == 1
    assert session.api_key == ""
    count = len(calls)
    manager.disconnect(oauth_id)
    assert session.call_tool("lookup", {}) is None
    assert len(calls) == count  # No stale authenticated session can send a request.


def test_second_401_requires_reauth_and_timeout_never_replays(setup, monkeypatch):
    manager, provider, oauth_id = setup
    calls = wire(monkeypatch, reject=10)
    session = mcp_client.MCPSession(RESOURCE, oauth_id=oauth_id, transport="streamable_http")
    session.call_tool("lookup", {})
    assert sum(c[0]["method"] == "tools/call" for c in calls) == 2
    assert provider.refreshes == 1
    assert manager.status(oauth_id)["status"] == "reauth_required"


def test_network_error_sanitized_without_tool_replay(setup, monkeypatch):
    manager, provider, oauth_id = setup
    calls = wire(monkeypatch, network_failure=True)
    session = mcp_client.MCPSession(RESOURCE, oauth_id=oauth_id, transport="streamable_http")
    result = session.call_tool("lookup", {})
    assert "secret-access" not in str(result)
    assert sum(c[0]["method"] == "tools/call" for c in calls) == 1
    assert provider.refreshes == 0


def test_oauth_session_identity_and_disabled_alias_cannot_route(setup, monkeypatch):
    _, _, oauth_id = setup
    calls = wire(monkeypatch)
    config = {"mcp_servers": {"ext_oauth": {"url": RESOURCE, "oauth_id": oauth_id, "transport": "streamable_http"}}}
    monkeypatch.setattr(mcp_client.config, "data", config)
    monkeypatch.setattr(mcp_client, "_sessions", {})
    monkeypatch.setattr(mcp_client, "_tool_routes", {})
    mcp_client.invalidate_tools_cache()
    try:
        name, key, tools, connected, _ = mcp_client._collect_tools_one(config["mcp_servers"]["ext_oauth"])
        assert connected
        assert key != mcp_client._session_key(RESOURCE, "", {}, "streamable_http", "other-connection")
        mcp_client._tool_routes["alias"] = (key, "lookup")
        config["mcp_servers"]["ext_oauth"]["enabled"] = False
        assert mcp_client.call_mcp_tool("alias", {}) is None
        assert not any(c[0]["method"] == "tools/call" for c in calls)
    finally:
        mcp_client.invalidate_tools_cache()
