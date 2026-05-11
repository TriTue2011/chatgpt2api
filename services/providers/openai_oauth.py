"""
Codex OAuth Provider — uses 9router Codex tokens to call chatgpt.com/backend-api/codex/responses.

This is the EXACT same endpoint 9router uses. No api.openai.com — the tokens
work with chatgpt.com's Codex Responses API. No 24KB limit, native tool calling.

Format: OpenAI Responses API (not chat/completions).
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Iterator

from curl_cffi import requests

from services.config import config
from services.account_service import account_service
from utils.log import logger

CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
CODEX_HEADERS = {
    "originator": "codex-cli",
    "User-Agent": "codex-cli/1.0.18 (Windows; x64)",
    "Content-Type": "application/json",
    "Accept": "text/event-stream",
}


def _chat_to_responses_input(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                              tool_choice: Any = None, instructions: str | None = None) -> dict[str, Any]:
    """Convert OpenAI chat format → Codex Responses API format."""
    body: dict[str, Any] = {"stream": True}

    input_items: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(str(part.get("text", "")))
            content = " ".join(text_parts)
        else:
            content = str(content or "")

        if role == "system":
            instructions = (instructions or "") + "\n" + content
            continue

        responses_role = "user" if role == "user" else "assistant"
        input_items.append({"role": responses_role, "content": content})

    body["input"] = input_items

    if instructions and instructions.strip():
        body["instructions"] = instructions.strip()

    if tools:
        body["tools"] = [{
            "type": "function",
            "name": t.get("function", {}).get("name", ""),
            "description": t.get("function", {}).get("description", ""),
            "parameters": t.get("function", {}).get("parameters", {}),
        } for t in tools if isinstance(t, dict)]

    if tool_choice:
        body["tool_choice"] = tool_choice

    return body


def _responses_to_chat_chunk(event: dict[str, Any], model: str, completion_id: str, created: int) -> dict[str, Any] | None:
    """Convert Codex Responses SSE event → OpenAI chat completion chunk."""
    event_type = event.get("type", "")

    if event_type == "response.output_text.delta":
        delta = event.get("delta", "")
        return {
            "id": completion_id, "object": "chat.completion.chunk",
            "created": created, "model": model,
            "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
        }

    if event_type == "response.output_item.done":
        item = event.get("item", {})
        if item.get("type") == "function_call":
            return {
                "id": completion_id, "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [{"index": 0, "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": item.get("call_id", ""),
                        "type": "function",
                        "function": {
                            "name": item.get("name", ""),
                            "arguments": item.get("arguments", ""),
                        },
                    }]
                }, "finish_reason": None}],
            }

    if event_type == "response.completed":
        return {
            "id": completion_id, "object": "chat.completion.chunk",
            "created": created, "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }

    if event_type == "error":
        return {
            "id": completion_id, "object": "chat.completion.chunk",
            "created": created, "model": model,
            "choices": [{"index": 0, "delta": {
                "content": f"Codex error: {event.get('message', 'unknown')}"
            }, "finish_reason": "stop"}],
        }

    return None


class CodexOAuthProvider:
    """Direct Codex OAuth — no 9router dependency."""

    def chat_completions(
        self,
        access_token: str,
        messages: list[dict[str, Any]],
        model: str = "auto",
        stream: bool = True,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        **kwargs,
    ) -> dict[str, Any] | Iterator[str]:
        """Call Codex Responses API with OAuth token."""

        body = _chat_to_responses_input(messages, tools, tool_choice)

        if model and model != "auto":
            body["model"] = model
        if temperature is not None:
            body["temperature"] = temperature

        headers = dict(CODEX_HEADERS)
        headers["Authorization"] = f"Bearer {access_token}"
        headers["Accept"] = "text/event-stream" if stream else "application/json"
        body["stream"] = stream

        logger.info({
            "event": "codex_request",
            "model": model or "auto",
            "stream": stream,
            "message_count": len(messages),
        })

        try:
            resp = requests.post(
                CODEX_URL, headers=headers, json=body,
                timeout=300, stream=stream,
                impersonate="chrome110",
            )

            if resp.status_code == 401:
                raise RuntimeError("Codex OAuth token expired — refresh needed")
            if resp.status_code >= 400:
                error_text = ""
                try:
                    error_text = resp.text[:500]
                except Exception:
                    pass
                raise RuntimeError(f"Codex error {resp.status_code}: {error_text[:200]}")

            if stream:
                return self._stream_response(resp, model or "auto")
            else:
                return self._non_stream_response(resp, model or "auto", messages)

        except requests.RequestsError as exc:
            raise RuntimeError(f"Codex connection failed: {exc}") from exc

    def _stream_response(self, response, model: str) -> Iterator[str]:
        """Convert Codex SSE → OpenAI-compatible SSE chunks."""
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        sent_role = False

        try:
            for raw_line in response.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="ignore") if isinstance(raw_line, bytes) else str(raw_line)
                line = line.strip()
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                chunk = _responses_to_chat_chunk(event, model, completion_id, created)
                if chunk:
                    if not sent_role and chunk["choices"][0]["delta"].get("content"):
                        chunk["choices"][0]["delta"]["role"] = "assistant"
                        sent_role = True
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        except Exception as exc:
            logger.error({"event": "codex_stream_error", "error": str(exc)})

        yield "data: [DONE]\n\n"

    def _non_stream_response(self, response, model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Handle non-streaming Codex response."""
        data = response.json()
        output_text = ""
        tool_calls = []

        for item in data.get("output", []):
            if item.get("type") == "message":
                for content_item in item.get("content", []):
                    if content_item.get("type") == "output_text":
                        output_text += content_item.get("text", "")
            elif item.get("type") == "function_call":
                tool_calls.append({
                    "id": item.get("call_id", ""),
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments", ""),
                    },
                })

        message = {"role": "assistant", "content": output_text}
        if tool_calls:
            message["tool_calls"] = tool_calls

        from services.protocol.openai_v1_chat_complete import count_message_tokens, count_text_tokens

        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": count_message_tokens(messages, model),
                "completion_tokens": count_text_tokens(output_text, model),
                "total_tokens": count_message_tokens(messages, model) + count_text_tokens(output_text, model),
            },
        }

    def get_token_for_request(self, exclude_tokens: set[str] | None = None) -> str:
        """Get next available Codex OAuth token from account pool."""
        excluded = set(exclude_tokens or set())
        with account_service._lock:
            candidates = [
                token
                for item in account_service._accounts.values()
                if item.get("type") == "codex"
                and item.get("status") not in {"禁用", "异常"}
                and (token := item.get("access_token") or "")
                and token not in excluded
            ]
            if not candidates:
                raise RuntimeError("No Codex OAuth tokens. Import 9router backup or add OAuth token.")
            token = candidates[account_service._index % len(candidates)]
            account_service._index += 1
            return token


# Singleton
codex_oauth = CodexOAuthProvider()
