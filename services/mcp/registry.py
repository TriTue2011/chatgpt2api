"""Registry of configured MCP servers.

Holds one `MCPClient` per server, persists configurations via the
chatgpt2api `config.data["mcp_servers"]` map, and exposes the merged
tool catalogue to the chat-completion request flow.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from services.config import config
from services.mcp.client import MCPClient, MCPCallResult, MCPError, MCPServerConfig, MCPTool
from utils.log import logger


# Separator between server id and tool name in the OpenAI function name.
# Underscores keep the name a valid identifier across all OpenAI tokenisers,
# unlike `/` or `:` which some servers reject.
TOOL_NAME_SEP = "__"


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _coerce_config(raw: Any) -> MCPServerConfig | None:
    """Build an `MCPServerConfig` from a dict in `config.data["mcp_servers"]`.

    Returns None for entries that are missing required fields, so a single
    bad config can't poison the registry.
    """
    if not isinstance(raw, dict):
        return None
    server_id = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or server_id).strip()
    url = str(raw.get("url") or "").strip()
    if not server_id or not url:
        return None
    return MCPServerConfig(
        id=server_id,
        name=name,
        url=url,
        api_key=str(raw.get("api_key") or ""),
        enabled=bool(raw.get("enabled", True)),
        transport=str(raw.get("transport") or "http"),
        headers=dict(raw.get("headers") or {}),
    )


class MCPRegistry:
    """Manages the set of configured MCP servers and their cached tools.

    Thread-safe. Configuration changes (add/update/remove) reload the
    affected client; existing clients keep their session/initialized state
    so we don't re-handshake on every chat turn.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._clients: dict[str, MCPClient] = {}
        # Track config version so list_tools cache invalidates on edits.
        self._config_version: int = 0

    # ----------------------------------------------------- config persistence

    def _load_configs(self) -> list[MCPServerConfig]:
        raw_list = config.data.get("mcp_servers") or []
        if not isinstance(raw_list, list):
            return []
        out: list[MCPServerConfig] = []
        for raw in raw_list:
            cfg = _coerce_config(raw)
            if cfg:
                out.append(cfg)
        return out

    def _save_configs(self, configs: list[MCPServerConfig]) -> None:
        config.data["mcp_servers"] = [
            {
                "id": c.id,
                "name": c.name,
                "url": c.url,
                "api_key": c.api_key,
                "enabled": c.enabled,
                "transport": c.transport,
                "headers": dict(c.headers or {}),
            }
            for c in configs
        ]
        config._save()
        self._config_version += 1

    # ----------------------------------------------------- client lifecycle

    def _ensure_client(self, cfg: MCPServerConfig) -> MCPClient:
        existing = self._clients.get(cfg.id)
        if existing and existing.config.url == cfg.url and existing.config.api_key == cfg.api_key:
            # Update mutable fields without losing session state.
            existing.config.name = cfg.name
            existing.config.enabled = cfg.enabled
            existing.config.headers = cfg.headers
            return existing
        client = MCPClient(cfg)
        self._clients[cfg.id] = client
        return client

    def reload(self) -> None:
        """Re-sync internal client map with `config.data["mcp_servers"]`."""
        with self._lock:
            configs = self._load_configs()
            wanted_ids = {c.id for c in configs}
            for cfg in configs:
                self._ensure_client(cfg)
            for stale_id in list(self._clients.keys()):
                if stale_id not in wanted_ids:
                    self._clients.pop(stale_id, None)

    # ----------------------------------------------------- public API

    def list_servers(self) -> list[MCPServerConfig]:
        with self._lock:
            self.reload()
            return [c.config for c in self._clients.values()]

    def add_or_update(self, cfg: MCPServerConfig) -> MCPServerConfig:
        with self._lock:
            configs = self._load_configs()
            if not cfg.id:
                cfg.id = _generate_id()
            replaced = False
            for i, existing in enumerate(configs):
                if existing.id == cfg.id:
                    configs[i] = cfg
                    replaced = True
                    break
            if not replaced:
                configs.append(cfg)
            self._save_configs(configs)
            self._ensure_client(cfg)
            return cfg

    def remove(self, server_id: str) -> bool:
        with self._lock:
            configs = self._load_configs()
            new_configs = [c for c in configs if c.id != server_id]
            if len(new_configs) == len(configs):
                return False
            self._save_configs(new_configs)
            self._clients.pop(server_id, None)
            return True

    def test(self, server_id: str) -> tuple[bool, str]:
        """Ping a server. Returns (ok, message_or_tools_summary)."""
        with self._lock:
            self.reload()
            client = self._clients.get(server_id)
            if not client:
                return False, "server not found"
            try:
                tools = client.list_tools(force_refresh=True)
                return True, f"OK — {len(tools)} tool(s) available"
            except MCPError as exc:
                return False, str(exc)
            except Exception as exc:
                return False, f"unexpected error: {exc}"

    # ----------------------------------------------------- tool catalogue

    def collect_tools(self) -> list[tuple[MCPTool, str]]:
        """Return all tools from enabled servers, paired with their prefixed name.

        The prefix is `<server_id>__` so the chat-completion layer can
        route a tool call back to the right server without ambiguity.
        """
        with self._lock:
            self.reload()
            out: list[tuple[MCPTool, str]] = []
            for client in self._clients.values():
                if not client.config.enabled:
                    continue
                try:
                    tools = client.list_tools()
                except Exception as exc:
                    logger.warning({"event": "mcp_list_tools_failed", "server": client.config.id, "error": str(exc)})
                    continue
                for tool in tools:
                    prefixed_name = f"{client.config.id}{TOOL_NAME_SEP}{tool.name}"
                    out.append((tool, prefixed_name))
            return out

    def call_tool_by_prefixed_name(self, prefixed_name: str, arguments: dict[str, Any] | None) -> MCPCallResult:
        """Dispatch a tool call back to the server it came from.

        `prefixed_name` is `<server_id>__<tool_name>` as produced by
        `collect_tools`. If the prefix is missing we treat the whole
        string as a tool name and try every enabled server in order —
        last-resort fallback for callers that didn't preserve the prefix.
        """
        if TOOL_NAME_SEP in prefixed_name:
            server_id, _, tool_name = prefixed_name.partition(TOOL_NAME_SEP)
        else:
            server_id, tool_name = "", prefixed_name

        with self._lock:
            self.reload()
            if server_id and server_id in self._clients:
                return self._clients[server_id].call_tool(tool_name, arguments)
            for client in self._clients.values():
                if not client.config.enabled:
                    continue
                try:
                    return client.call_tool(tool_name, arguments)
                except MCPError:
                    continue
            raise MCPError(f"no MCP server can handle tool {prefixed_name!r}")


# Singleton — chat-completion layer imports `mcp_registry`.
mcp_registry = MCPRegistry()
