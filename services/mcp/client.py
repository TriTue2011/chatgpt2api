"""MCP (Model Context Protocol) client over HTTP/SSE.

Implements the JSON-RPC 2.0 wire protocol for MCP. Supports the streamable
HTTP transport and the older SSE transport.

References:
- https://spec.modelcontextprotocol.io/specification/server/tools/
- https://spec.modelcontextprotocol.io/specification/basic/transports/

Wire format (request):
    POST <url>
    Content-Type: application/json
    Accept: application/json, text/event-stream
    Authorization: Bearer <api_key>   # optional, server-specific

    {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}

Wire format (response):
    Either single JSON body, or text/event-stream with one or more
    `data: {...}` events that contain the JSON-RPC response.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from curl_cffi import requests

from utils.log import logger


# JSON-RPC 2.0 method names defined by the MCP spec.
MCP_METHOD_INITIALIZE = "initialize"
MCP_METHOD_LIST_TOOLS = "tools/list"
MCP_METHOD_CALL_TOOL = "tools/call"
MCP_METHOD_PING = "ping"

# Required by initialize. Bumping this risks breaking older servers.
MCP_PROTOCOL_VERSION = "2025-03-26"

# Conservative timeouts so a hung server can never wedge a chat turn.
DEFAULT_REQUEST_TIMEOUT = 30
DEFAULT_TOOL_CALL_TIMEOUT = 60


@dataclass
class MCPTool:
    """A tool exposed by a remote MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_id: str = ""

    def to_openai_function(self, prefix: str = "") -> dict[str, Any]:
        """Convert to OpenAI Function Calling format.

        Returns shape compatible with chat.completions tools array:
            {"type": "function", "function": {name, description, parameters}}
        """
        full_name = f"{prefix}{self.name}" if prefix else self.name
        return {
            "type": "function",
            "function": {
                "name": full_name,
                "description": self.description or self.name,
                "parameters": self.input_schema or {"type": "object", "properties": {}},
            },
        }


@dataclass
class MCPServerConfig:
    """User-supplied configuration for a single MCP server."""

    id: str
    name: str
    url: str
    api_key: str = ""
    enabled: bool = True
    transport: str = "http"  # "http" (streamable) | "sse"
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class MCPCallResult:
    """Result of a tools/call invocation, normalised for downstream LLM injection."""

    content: str = ""
    is_error: bool = False
    raw: Any = None

    @classmethod
    def from_response(cls, payload: Any) -> "MCPCallResult":
        """Normalise the MCP `content` array into a single string.

        MCP responses are an array of typed parts (text, image, resource).
        For LLM consumption we flatten everything to text — image parts are
        replaced with a placeholder so the model knows something visual was
        returned without us having to fetch and re-encode the bytes.
        """
        if not isinstance(payload, dict):
            return cls(content=str(payload), raw=payload)
        parts = payload.get("content") or []
        if not isinstance(parts, list):
            return cls(content=str(parts), is_error=bool(payload.get("isError")), raw=payload)
        chunks: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            ptype = str(part.get("type") or "")
            if ptype == "text":
                chunks.append(str(part.get("text") or ""))
            elif ptype == "image":
                chunks.append("[image returned by tool — not included]")
            elif ptype == "resource":
                res = part.get("resource") or {}
                chunks.append(str(res.get("text") or res.get("uri") or ""))
        return cls(
            content="\n".join(c for c in chunks if c).strip(),
            is_error=bool(payload.get("isError")),
            raw=payload,
        )


class MCPError(Exception):
    """Raised when an MCP server returns a JSON-RPC error or the transport fails."""

    def __init__(self, message: str, code: int = -1, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


class MCPClient:
    """Stateful MCP client over streamable HTTP / SSE.

    The client lazily initialises the session on first use. Each instance
    represents one configured server, so a registry should hold one client
    per `MCPServerConfig`.
    """

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._session_id: str = ""
        self._initialized: bool = False
        self._next_id: int = 0
        self._tools_cache: list[MCPTool] = []
        self._tools_cached_at: float = 0.0

    # ------------------------------------------------------------------ helpers

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        for k, v in (self.config.headers or {}).items():
            if k and v:
                headers[str(k)] = str(v)
        return headers

    @staticmethod
    def _parse_sse_body(text: str) -> Any:
        """Extract the first JSON-RPC payload from a text/event-stream body.

        SSE lines look like `data: {...}` separated by blank lines. We
        only need the first `data:` event because MCP responses are
        single messages, not multi-event streams.
        """
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                continue
        return None

    def _post(self, body: dict[str, Any], timeout: int) -> dict[str, Any]:
        """Send a JSON-RPC request and decode the JSON or SSE response."""
        try:
            resp = requests.post(
                self.config.url,
                json=body,
                headers=self._build_headers(),
                timeout=timeout,
                impersonate="chrome120",
            )
        except Exception as exc:
            raise MCPError(f"transport error: {exc}") from exc

        # Capture session id from server (streamable HTTP transport).
        sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid

        if resp.status_code >= 400:
            raise MCPError(f"http {resp.status_code}: {resp.text[:300]}", code=resp.status_code)

        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "text/event-stream" in ctype:
            data = self._parse_sse_body(resp.text)
        else:
            try:
                data = resp.json()
            except Exception:
                data = self._parse_sse_body(resp.text)

        if not isinstance(data, dict):
            raise MCPError(f"unexpected response shape: {str(data)[:200]}")
        if "error" in data and data["error"]:
            err = data["error"]
            if isinstance(err, dict):
                raise MCPError(str(err.get("message") or err), code=int(err.get("code") or -1), data=err.get("data"))
            raise MCPError(str(err))
        return data

    # ------------------------------------------------------------------ rpc methods

    def initialize(self) -> None:
        """Perform the MCP `initialize` handshake exactly once per session."""
        if self._initialized:
            return
        body = {
            "jsonrpc": "2.0",
            "id": self._new_id(),
            "method": MCP_METHOD_INITIALIZE,
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "chatgpt2api", "version": "1.0"},
            },
        }
        self._post(body, DEFAULT_REQUEST_TIMEOUT)

        # Spec requires a notification after initialize.
        notify = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        try:
            requests.post(
                self.config.url,
                json=notify,
                headers=self._build_headers(),
                timeout=10,
                impersonate="chrome120",
            )
        except Exception as exc:
            logger.warning({"event": "mcp_notify_initialized_failed", "server": self.config.id, "error": str(exc)})
        self._initialized = True

    def list_tools(self, force_refresh: bool = False) -> list[MCPTool]:
        """Fetch the tool catalogue. Cached for 5 minutes by default."""
        if not force_refresh and self._tools_cache and (time.time() - self._tools_cached_at) < 300:
            return list(self._tools_cache)

        self.initialize()
        body = {
            "jsonrpc": "2.0",
            "id": self._new_id(),
            "method": MCP_METHOD_LIST_TOOLS,
        }
        data = self._post(body, DEFAULT_REQUEST_TIMEOUT)
        result = data.get("result") or {}
        raw_tools = result.get("tools") or []

        tools: list[MCPTool] = []
        for t in raw_tools:
            if not isinstance(t, dict):
                continue
            name = str(t.get("name") or "").strip()
            if not name:
                continue
            tools.append(
                MCPTool(
                    name=name,
                    description=str(t.get("description") or ""),
                    input_schema=dict(t.get("inputSchema") or {}),
                    server_id=self.config.id,
                )
            )
        self._tools_cache = tools
        self._tools_cached_at = time.time()
        logger.info({"event": "mcp_tools_listed", "server": self.config.id, "count": len(tools)})
        return list(tools)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> MCPCallResult:
        """Invoke a tool by name. Returns text content suitable for LLM context."""
        self.initialize()
        body = {
            "jsonrpc": "2.0",
            "id": self._new_id(),
            "method": MCP_METHOD_CALL_TOOL,
            "params": {
                "name": name,
                "arguments": arguments or {},
            },
        }
        data = self._post(body, DEFAULT_TOOL_CALL_TIMEOUT)
        return MCPCallResult.from_response(data.get("result") or {})

    def ping(self) -> bool:
        """Used by the config UI to test a server before saving."""
        try:
            self.initialize()
            self.list_tools(force_refresh=True)
            return True
        except Exception as exc:
            logger.warning({"event": "mcp_ping_failed", "server": self.config.id, "error": str(exc)})
            return False
