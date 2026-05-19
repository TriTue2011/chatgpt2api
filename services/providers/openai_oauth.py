"""
Codex OAuth Provider — uses Codex OAuth tokens to call api.openai.com directly.

9router's Codex tokens are OpenAI OAuth tokens. They work with
api.openai.com/v1/chat/completions exactly like API keys.

Note: chatgpt.com/backend-api/codex/responses is ONLY used by the ChatGPT free
addon flow, NOT by this Codex OAuth provider.
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

CODEX_URL = "https://api.openai.com/v1/chat/completions"
CODEX_DEFAULT_MODEL = "gpt-4o"
CODEX_HEADERS = {
    "Content-Type": "application/json",
}


def _is_openai_api_only(token: str) -> bool:
    """Check if token only works with api.openai.com (not chatgpt.com).
    Detected by: no user_id set (never successfully refreshed from chatgpt.com).
    """
    return False  # Let the account's refresh status determine eligibility


def _chat_to_responses_input(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                              tool_choice: Any = None, instructions: str | None = None) -> dict[str, Any]:
    """Deprecated — Codex now uses api.openai.com/v1/chat/completions natively (no Responses-format conversion)."""
    return {"messages": list(messages or [])}


def _responses_to_chat_chunk(event: dict[str, Any], model: str, completion_id: str, created: int) -> dict[str, Any] | None:
    """Deprecated — Codex now uses api.openai.com/v1/chat/completions which already returns chat-completion chunks."""
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
        # Build standard chat/completions body (api.openai.com format)
        chat_messages: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "tool":
                chat_messages.append({
                    "role": "tool",
                    "tool_call_id": str(msg.get("tool_call_id") or ""),
                    "content": content if isinstance(content, str) else str(content or ""),
                })
                continue
            if role == "assistant" and isinstance(msg.get("tool_calls"), list) and msg["tool_calls"]:
                chat_messages.append({
                    "role": "assistant",
                    "content": content if isinstance(content, str) else "",
                    "tool_calls": msg["tool_calls"],
                })
                continue
            chat_messages.append({"role": role, "content": content})

        base_body: dict[str, Any] = {"messages": chat_messages}
        if tools:
            base_body["tools"] = tools
        if tool_choice:
            base_body["tool_choice"] = tool_choice
        if temperature is not None:
            base_body["temperature"] = temperature
        if max_tokens is not None:
            base_body["max_tokens"] = max_tokens

        # Resolve model — auto uses default; respect enabled_models filter if set
        is_auto = not model or model == "auto"
        if is_auto:
            from services.config import config as _cfg
            ms = _cfg.data.get("model_settings") or {}
            enabled_models = (ms.get("enabled_models") or {}).get("openai_oauth") if isinstance(ms, dict) else None
            if enabled_models:
                enabled_clean = [
                    (m[3:] if m.startswith("cx/") else m)
                    for m in enabled_models
                    if m and m not in ("auto", "cx/auto")
                ]
                models_to_try = [m for m in enabled_clean if m] or [CODEX_DEFAULT_MODEL]
            else:
                models_to_try = [CODEX_DEFAULT_MODEL]
        else:
            models_to_try = [model]

        last_error = ""
        for try_idx, try_model in enumerate(models_to_try):
            if try_idx > 0:
                logger.warning({"event": "codex_fallback", "from": models_to_try[try_idx-1],
                                "to": try_model})

            body = dict(base_body)  # fresh copy each attempt
            resolved_model = try_model

            # Parse effort/review suffixes (kept for compatibility — ignored by api.openai.com)
            _EFFORT_LEVELS = {"xhigh", "high", "medium", "low", "none"}
            _suffixes = resolved_model.split("-")
            _effort = None
            _seen: list[str] = []
            for _s in reversed(_suffixes):
                if _s == "review":
                    pass  # api.openai.com doesn't accept review include
                elif _s in _EFFORT_LEVELS and _effort is None:
                    _effort = _s
                else:
                    _seen.insert(0, _s)
            if _effort:
                resolved_model = "-".join(_seen)
                # reasoning only valid for o-series; harmless extra field for chat/completions
                body["reasoning_effort"] = _effort

            body["model"] = resolved_model
            body["stream"] = stream

            # Strip Responses-only fields if present from a previous build pass
            for key in ("store", "instructions", "include", "reasoning"):
                body.pop(key, None)

            headers = dict(CODEX_HEADERS)
            headers["Authorization"] = f"Bearer {access_token}"

            logger.info({
                "event": "codex_request",
                "model": resolved_model,
                "try": try_idx + 1,
                "message_count": len(messages),
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
                        raw = b""
                        for chunk in resp.iter_content(chunk_size=8192):
                            if chunk:
                                raw += chunk if isinstance(chunk, bytes) else chunk.encode()
                                if len(raw) > 10000:
                                    break
                        if raw:
                            error_text = raw.decode("utf-8", errors="ignore")[:1000]
                    except Exception:
                        try:
                            error_text = (resp.text or "")[:1000]
                        except Exception:
                            pass
                    resp_headers = dict(resp.headers) if hasattr(resp, 'headers') else {}
                    logger.error({
                        "event": "codex_upstream_error",
                        "status": resp.status_code,
                        "model": resolved_model,
                        "error": error_text,
                        "headers": {k: str(v)[:200] for k, v in resp_headers.items()},
                    })
                    msg = f"Codex error {resp.status_code}: {error_text[:200]}"
                    if try_idx < len(models_to_try) - 1:
                        last_error = msg
                        continue
                    raise RuntimeError(msg)

                # Success
                if stream:
                    return self._stream_response(resp, resolved_model)
                else:
                    text = ""
                    tool_calls = []
                    for chunk in self._stream_response(resp, resolved_model):
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
                        "model": resolved_model,
                        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                        "usage": {
                            "prompt_tokens": count_message_tokens(messages, resolved_model),
                            "completion_tokens": count_text_tokens(text, resolved_model),
                            "total_tokens": count_message_tokens(messages, resolved_model) + count_text_tokens(text, resolved_model),
                        },
                    }

            except requests.RequestsError as exc:
                msg = f"Codex connection failed: {exc}"
                if try_idx < len(models_to_try) - 1:
                    last_error = msg
                    continue
                raise RuntimeError(msg) from exc

        raise RuntimeError(f"All Codex models failed: {last_error}")

    def _stream_response(self, response, model: str) -> Iterator[dict[str, Any]]:
        """Pass through OpenAI chat/completions SSE → dict chunks."""
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())

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

                # api.openai.com already returns chat.completion.chunk shape — pass through
                if isinstance(event, dict) and event.get("choices"):
                    if "id" not in event:
                        event["id"] = completion_id
                    if "created" not in event:
                        event["created"] = created
                    if "model" not in event:
                        event["model"] = model
                    yield event

        except Exception as exc:
            logger.error({"event": "codex_stream_error", "error": str(exc)})

        yield {
            "id": completion_id, "object": "chat.completion.chunk",
            "created": created, "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }

    def _non_stream_response(self, response, model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Handle non-streaming chat/completions response (parse standard OpenAI shape)."""
        data = response.json()
        # api.openai.com already returns OpenAI chat.completion shape — pass through
        if isinstance(data, dict) and data.get("choices"):
            return data
        # Fallback: empty completion
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}],
        }

    def get_token_for_request(self, exclude_tokens: set[str] | None = None) -> str:
        """Get next available JWT token for Codex OAuth. Accepts any JWT token."""
        excluded = set(exclude_tokens or set())
        with account_service._lock:
            all_items = list(account_service._accounts.values())
            logger.info({
                "event": "codex_debug",
                "total_accounts": len(all_items),
                "statuses": [i.get("status") for i in all_items],
                "types": [i.get("type") for i in all_items],
                "has_jwt": sum(1 for i in all_items if str(i.get("access_token","")).startswith("eyJ")),
            })
            candidates = [
                token
                for item in all_items
                if item.get("status") not in ("disabled", "error")
                and (token := item.get("access_token") or "")
                and token.startswith("eyJ")
                and token not in excluded
                # Skip tokens that only work with api.openai.com (web session)
                and not _is_openai_api_only(token)
            ]
            if not candidates:
                raise RuntimeError("No Codex OAuth tokens available. Add via OAuth login or import 9router backup.")
            token = candidates[account_service._index % len(candidates)]
            account_service._index += 1
            return token


# Singleton
codex_oauth = CodexOAuthProvider()
