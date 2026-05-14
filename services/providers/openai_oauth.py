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
CODEX_DEFAULT_MODEL = "gpt-5.3-codex"
CODEX_HEADERS = {
    "originator": "codex-cli",
    "User-Agent": "codex-cli/1.0.18 (Windows; x64)",
    "Content-Type": "application/json",
    "Accept": "text/event-stream",
}


def _chat_to_responses_input(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                              tool_choice: Any = None, instructions: str | None = None) -> dict[str, Any]:
    """Convert OpenAI chat format → Codex Responses API format.

    Handles the full conversation flow including tool calls:
    - system → instructions
    - user → input_item (role="user")
    - assistant (text) → input_item (role="assistant")
    - assistant (tool_calls) → function_call items
    - tool (result) → function_call_output items
    """
    body: dict[str, Any] = {"stream": True}

    input_items: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, list):
            text_parts = []
            image_parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        text_parts.append(str(part.get("text", "")))
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            header, b64 = url.split(",", 1)
                            mime = header.split(";")[0].replace("data:", "")
                            image_parts.append({"type": "input_image", "image_url": url})
                        elif url:
                            image_parts.append({"type": "input_image", "image_url": url})
                    elif part.get("type") == "input_image":
                        image_parts.append(part)
            content = " ".join(text_parts) if text_parts else ""
            # Build Responses-format content with images
            if image_parts:
                items = []
                if content:
                    items.append({"type": "input_text", "text": content})
                for img in image_parts:
                    img_url = img.get("image_url", "")
                    if isinstance(img_url, str) and img_url.startswith("data:"):
                        # Inline base64 image
                        items.append({"type": "input_image", "image_url": img_url})
                    elif isinstance(img_url, str):
                        items.append({"type": "input_image", "image_url": img_url})
                input_items.append({"role": "user", "content": items})
                continue
        else:
            content = str(content or "")

        if role == "system":
            instructions = (instructions or "") + "\n" + content
            continue

        # Tool call result → function_call_output in Responses API
        if role == "tool":
            tool_call_id = str(msg.get("tool_call_id") or "")
            input_items.append({
                "type": "function_call_output",
                "call_id": tool_call_id,
                "output": content,
            })
            continue

        # Assistant message with tool_calls → function_call items
        if role == "assistant":
            tool_calls = msg.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                # First, add any text content the assistant said before calling tools
                if content and content.strip():
                    input_items.append({"role": "assistant", "content": content})
                # Then add each function_call as an item
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        fn = tc.get("function") or {}
                        input_items.append({
                            "type": "function_call",
                            "call_id": str(tc.get("id") or ""),
                            "name": str(fn.get("name") or ""),
                            "arguments": str(fn.get("arguments") or ""),
                        })
                continue
            # Regular assistant text response
            input_items.append({"role": "assistant", "content": content})
            continue

        # User message
        if role == "user":
            input_items.append({"role": "user", "content": content})
        else:
            input_items.append({"role": "user", "content": content})

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
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        """Call Codex Responses API with OAuth token."""

        instructions = None
        body = _chat_to_responses_input(messages, tools, tool_choice, instructions)

        # Codex requires these four to be set
        model = model if model and model != "auto" else CODEX_DEFAULT_MODEL
        body["model"] = model
        body["store"] = False
        body["stream"] = True  # Codex requires streaming
        if "instructions" not in body or not body.get("instructions"):
            body["instructions"] = "You are a helpful assistant."

        # Codex rejects these parameters — strip them (like 9router does)
        for key in ("temperature", "top_p", "frequency_penalty", "presence_penalty",
                     "n", "seed", "logprobs", "top_logprobs", "user",
                     "stream_options", "safety_identifier", "metadata",
                     "parallel_tool_calls"):
            body.pop(key, None)

        # Pass max_tokens as max_output_tokens (Responses API format)
        # Only if explicitly provided — don't set a default (Codex may reject it)
        if max_tokens:
            body["max_output_tokens"] = max_tokens

        headers = dict(CODEX_HEADERS)
        headers["Authorization"] = f"Bearer {access_token}"

        logger.info({
            "event": "codex_request",
            "model": model,
            "stream": True,
            "message_count": len(messages),
            "body_keys": list(body.keys()),
            "has_instructions": bool(body.get("instructions")),
            "input_count": len(body.get("input", [])),
        })

        try:
            resp = requests.post(
                CODEX_URL, headers=headers, json=body,
                timeout=300, stream=True,
                impersonate="chrome110",
            )

            if resp.status_code == 401:
                raise RuntimeError("Codex OAuth token expired")
            if resp.status_code >= 400:
                error_text = ""
                try:
                    error_text = resp.text[:500]
                except Exception:
                    pass
                logger.error({
                    "event": "codex_upstream_error",
                    "status": resp.status_code,
                    "error": error_text,
                })
                raise RuntimeError(f"Codex error {resp.status_code}: {error_text[:200]}")

            # Codex always streams — collect if caller requested non-streaming
            if stream:
                return self._stream_response(resp, model or "auto")
            else:
                # Collect stream into single response
                text = ""
                tool_calls = []
                for chunk in self._stream_response(resp, model or "auto"):
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    text += delta.get("content", "")
                    if delta.get("tool_calls"):
                        tool_calls.extend(delta["tool_calls"])
                    if delta.get("finish_reason") == "stop":
                        break

                message = {"role": "assistant", "content": text}
                if tool_calls:
                    message["tool_calls"] = tool_calls

                from services.protocol.openai_v1_chat_complete import count_message_tokens, count_text_tokens

                return {
                    "id": f"chatcmpl-{uuid.uuid4().hex}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model or "auto",
                    "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                    "usage": {
                        "prompt_tokens": count_message_tokens(messages, model or "auto"),
                        "completion_tokens": count_text_tokens(text, model or "auto"),
                        "total_tokens": count_message_tokens(messages, model or "auto") + count_text_tokens(text, model or "auto"),
                    },
                }

        except requests.RequestsError as exc:
            raise RuntimeError(f"Codex connection failed: {exc}") from exc

    def _stream_response(self, response, model: str) -> Iterator[dict[str, Any]]:
        """Convert Codex SSE → OpenAI chat completion chunks (dicts)."""
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
                    yield chunk

        except Exception as exc:
            logger.error({"event": "codex_stream_error", "error": str(exc)})

        if not sent_role:
            yield {
                "id": completion_id, "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
            }
        yield {
            "id": completion_id, "object": "chat.completion.chunk",
            "created": created, "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }

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
        """Get next available Codex OAuth token (JWT only — not web session tokens)."""
        excluded = set(exclude_tokens or set())
        with account_service._lock:
            candidates = [
                token
                for item in account_service._accounts.values()
                if item.get("status") not in {"禁用", "异常"}
                and (token := item.get("access_token") or "")
                and token not in excluded
                # Only use Codex OAuth tokens (JWT starting with eyJ)
                and token.startswith("eyJ")
            ]
            if not candidates:
                raise RuntimeError("No Codex OAuth tokens available. Add via OAuth login or import 9router backup.")
            token = candidates[account_service._index % len(candidates)]
            account_service._index += 1
            return token


# Singleton
codex_oauth = CodexOAuthProvider()
