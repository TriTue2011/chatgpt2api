"""Convert MCP tool catalogue to OpenAI Function Calling format and back.

Two directions:
1. `mcp_tools_to_openai` — at request time, take all enabled MCP tools and
   produce the `tools=[...]` array that goes into the chat-completion call.
2. `parse_openai_tool_call` — when the LLM responds with a `tool_calls`
   entry, decode it back to (server_id, tool_name, arguments) so the
   registry can dispatch to the right server.
"""

from __future__ import annotations

import json
from typing import Any

from services.mcp.registry import TOOL_NAME_SEP, mcp_registry


def mcp_tools_to_openai(existing_tools: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Build the OpenAI tools array including any tools the caller already has.

    Caller-supplied tools win on name collision: if a Home Assistant tool
    and an MCP tool share a name, HA's stays. This matches what the user
    asked for — HA-first, MCP as augmentation.
    """
    out: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for tool in existing_tools or []:
        if not isinstance(tool, dict):
            continue
        name = ((tool.get("function") or {}).get("name")) if tool.get("type") == "function" else None
        if name:
            seen_names.add(str(name))
        out.append(tool)

    for mcp_tool, prefixed_name in mcp_registry.collect_tools():
        if prefixed_name in seen_names:
            continue
        out.append(
            {
                "type": "function",
                "function": {
                    "name": prefixed_name,
                    "description": mcp_tool.description or mcp_tool.name,
                    "parameters": mcp_tool.input_schema or {"type": "object", "properties": {}},
                },
            }
        )
        seen_names.add(prefixed_name)

    return out


def is_mcp_tool_call(tool_name: str) -> bool:
    """Cheap check before doing any work — does this name look like an MCP tool?

    The registry verifies routing properly, but the chat layer needs to
    decide whether to forward a call to MCP or let the existing handler
    (e.g. Home Assistant) keep it.
    """
    if not tool_name or TOOL_NAME_SEP not in tool_name:
        return False
    server_id, _, _ = tool_name.partition(TOOL_NAME_SEP)
    if not server_id:
        return False
    return any(c.config.id == server_id for c in mcp_registry._clients.values())


def parse_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
    """OpenAI returns `arguments` as a JSON-encoded string. Be defensive.

    Some providers (or proxy layers) hand back already-decoded dicts; we
    accept both, and on parse failure return an empty dict so the call
    still goes through with no arguments rather than crashing the turn.
    """
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if not isinstance(raw_arguments, str) or not raw_arguments.strip():
        return {}
    try:
        decoded = json.loads(raw_arguments)
        return decoded if isinstance(decoded, dict) else {}
    except json.JSONDecodeError:
        return {}


def execute_mcp_tool_call(tool_name: str, raw_arguments: Any) -> str:
    """Run a single tool call against MCP and return text for the LLM.

    Errors are converted to a short error string rather than raised — a
    failed tool shouldn't kill the chat turn, the LLM can recover by
    apologising or trying a different approach.
    """
    arguments = parse_tool_arguments(raw_arguments)
    try:
        result = mcp_registry.call_tool_by_prefixed_name(tool_name, arguments)
    except Exception as exc:
        return f"[MCP tool error: {exc}]"
    if result.is_error:
        return f"[MCP tool returned error: {result.content[:500]}]"
    return result.content or "[MCP tool returned no content]"
