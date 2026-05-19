"""MCP tool execution loop.

When the LLM returns a `tool_calls` array containing one or more MCP
tools (i.e. names with the `<server_id>__` prefix), this module:

1. Splits the tool calls into MCP-bound vs caller-bound (Home Assistant
   etc.). Non-MCP calls are passed through untouched.
2. Executes the MCP-bound calls against the registry.
3. Appends `role=tool` messages with the results to the message history.
4. Re-invokes the chat completion so the LLM can produce a final answer
   that incorporates the tool results.

Loop terminates when:
- LLM responds with `finish_reason=stop` (no more tool calls)
- Loop iteration limit hit (safety against infinite loops)
- Any non-recoverable error in dispatch
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable

from services.mcp.converter import (
    execute_mcp_tool_call,
    is_mcp_tool_call,
    parse_tool_arguments,
)
from utils.log import logger


# Hard cap on how many times we go round the LLM <-> tool loop before
# giving up. Real workflows rarely need more than 3-4 iterations.
MAX_TOOL_ITERATIONS = 6


def split_tool_calls(tool_calls: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition tool_calls into (mcp_calls, passthrough_calls).

    A call is MCP-bound iff its function name has the registry's prefix
    AND a configured server with that prefix exists. Anything else is
    passthrough so existing handlers (Home Assistant GetLiveContext,
    etc.) keep working.
    """
    mcp_calls: list[dict[str, Any]] = []
    passthrough: list[dict[str, Any]] = []
    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") or {}
        name = str(fn.get("name") or "")
        if name and is_mcp_tool_call(name):
            mcp_calls.append(call)
        else:
            passthrough.append(call)
    return mcp_calls, passthrough


def execute_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run each MCP-bound tool call and return tool-result messages.

    Output messages have OpenAI's `role=tool` shape:
        {"role": "tool", "tool_call_id": "...", "content": "..."}
    """
    results: list[dict[str, Any]] = []
    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        call_id = str(call.get("id") or f"call_{uuid.uuid4().hex[:12]}")
        fn = call.get("function") or {}
        name = str(fn.get("name") or "")
        raw_args = fn.get("arguments")
        logger.info({"event": "mcp_tool_invoke", "tool": name, "call_id": call_id})
        text = execute_mcp_tool_call(name, raw_args)
        results.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": text,
            }
        )
    return results


def build_assistant_tool_call_message(tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    """The LLM's tool call must be re-added as the assistant turn before
    the tool results, so the next call sees the full conversation.

    OpenAI requires `tool_calls` items to be { id, type:"function", function:{name,arguments} }.
    Some providers omit `type` so we normalise it here.
    """
    cleaned: list[dict[str, Any]] = []
    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") or {}
        args = fn.get("arguments")
        if not isinstance(args, str):
            try:
                args = json.dumps(args or {}, ensure_ascii=False)
            except Exception:
                args = "{}"
        cleaned.append(
            {
                "id": str(call.get("id") or f"call_{uuid.uuid4().hex[:12]}"),
                "type": "function",
                "function": {
                    "name": str(fn.get("name") or ""),
                    "arguments": args,
                },
            }
        )
    return {"role": "assistant", "content": "", "tool_calls": cleaned}


def extract_tool_calls_from_completion(completion: dict[str, Any]) -> list[dict[str, Any]]:
    """Pick the tool_calls array out of a non-streaming chat completion."""
    if not isinstance(completion, dict):
        return []
    choices = completion.get("choices") or []
    if not choices:
        return []
    msg = (choices[0] or {}).get("message") or {}
    return list(msg.get("tool_calls") or [])


def run_tool_loop(
    messages: list[dict[str, Any]],
    initial_completion: dict[str, Any],
    re_invoke: Callable[[list[dict[str, Any]]], dict[str, Any]],
) -> dict[str, Any]:
    """Drive the LLM <-> MCP tool loop until a final answer arrives.

    Args:
        messages: original message list passed to the first chat call.
        initial_completion: the response that came back containing tool_calls.
        re_invoke: callable that takes an updated message list and returns
                   the next chat completion. The chat layer owns this so it
                   can keep model/route/tool_choice consistent.

    Returns the final completion (with tool_calls all resolved).
    """
    completion = initial_completion
    working_messages = list(messages or [])

    for iteration in range(MAX_TOOL_ITERATIONS):
        tool_calls = extract_tool_calls_from_completion(completion)
        if not tool_calls:
            return completion

        mcp_calls, passthrough = split_tool_calls(tool_calls)
        if not mcp_calls:
            # No MCP calls — let caller handle the rest (HA, etc.).
            return completion

        if passthrough:
            logger.info({
                "event": "mcp_loop_partial",
                "mcp_count": len(mcp_calls),
                "passthrough_count": len(passthrough),
                "note": "returning early so caller can handle non-MCP calls",
            })
            return completion

        # Append the assistant's tool-call turn, then the results.
        working_messages.append(build_assistant_tool_call_message(mcp_calls))
        working_messages.extend(execute_tool_calls(mcp_calls))

        try:
            completion = re_invoke(working_messages)
        except Exception as exc:
            logger.warning({"event": "mcp_loop_reinvoke_failed", "iteration": iteration, "error": str(exc)})
            return completion

    logger.warning({"event": "mcp_loop_max_iterations", "limit": MAX_TOOL_ITERATIONS})
    return completion
