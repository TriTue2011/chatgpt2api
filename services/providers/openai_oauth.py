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
CODEX_DEFAULT_MODEL = "gpt-5.5"  # First try; fallback through supported models only
# gpt-5.4 and gpt-5.3-codex are NOT supported with ChatGPT free accounts (400 error)
CODEX_AUTO_FALLBACK = ["gpt-5.5"]
CODEX_HEADERS = {
    "originator": "codex-cli",
    "User-Agent": "codex-cli/1.0.18 (Windows; x64)",
    "Content-Type": "application/json",
    "Accept": "text/event-stream",
}


_CODEX_401_DISABLE_THRESHOLD = 3  # consecutive 401s before disabling — a single
                                  # 401 is often transient (token-rotation race,
                                  # brief upstream blip), so don't kill on the first.


def _codex_count_401(access_token: str, reason: str) -> bool:
    """Register a 401 for this account. Disable it ONLY after N consecutive 401s;
    otherwise just demote it (rotate to tail) and let other accounts serve. The
    streak resets to 0 on the next successful response, so transient 401s never
    accumulate into a wrongful disable. Returns True if disabled this call."""
    try:
        acc = account_service.get_account(access_token) or {}
        n = int(acc.get("codex_401_count") or 0) + 1
        if n >= _CODEX_401_DISABLE_THRESHOLD:
            account_service.update_account(access_token, {"status": "disabled", "codex_401_count": 0})
            logger.warning({"event": "codex_account_disabled", "reason": reason, "fails": n})
            return True
        account_service.update_account(access_token, {"codex_401_count": n})
        account_service.demote_account(access_token)  # try other accounts first
        logger.warning({"event": "codex_401_soft", "reason": reason, "fails": n,
                        "threshold": _CODEX_401_DISABLE_THRESHOLD})
        return False
    except Exception as exc:
        logger.warning({"event": "codex_count_401_error", "error": str(exc)[:120]})
        return False


def _is_openai_api_only(token: str) -> bool:
    """Check if token only works with api.openai.com (not chatgpt.com).
    Detected by: no user_id set (never successfully refreshed from chatgpt.com).
    """
    return False  # Let the account's refresh status determine eligibility


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


def _strip_empty_tool_args(arguments: str) -> str:
    """Drop empty-valued slots ("" / [] / {} / null) from a tool_call's JSON
    arguments. HA's intent slot validation rejects blank optional slots
    (area:"", floor:"", device_class:[]) with InvalidSlotInfo, and gpt-5.x fills
    every optional field with an empty default — which made every device command
    fail. Keep 0 / False (can be meaningful, e.g. brightness:0). Non-JSON args
    pass through unchanged."""
    try:
        data = json.loads(arguments)
    except (ValueError, TypeError):
        return arguments
    if not isinstance(data, dict):
        return arguments
    cleaned = {k: v for k, v in data.items() if v not in ("", [], {}, None)}
    if cleaned == data:
        return arguments
    return json.dumps(cleaned, ensure_ascii=False)


def _narrow_hass_tool_args(name: str, arguments: str) -> str:
    """For HA intent tools, decide whether to keep the `area`/`floor` the model
    attached to a specific entity `name`.

    DROP it when the location is just echoed inside the device name
    ("Đèn nhà tắm" + area "Nhà tắm") — otherwise HA widens the command to the
    whole area. KEEP it when the location adds NEW info ("Đèn trần" + area
    "Phòng học") — HA needs it to disambiguate duplicate names, which it rejects
    with MatchFailedError/DUPLICATE_NAME otherwise.

    This is a deterministic, registry-cache-free check (substring of folded
    names), so it doesn't lag behind live HA exposure edits. count_name_matches
    is only a secondary 'keep' signal. Area-only commands (no name) untouched."""
    if not str(name).startswith("Hass"):
        return arguments
    try:
        data = json.loads(arguments)
    except (ValueError, TypeError):
        return arguments
    if not isinstance(data, dict):
        return arguments
    if data.get("name") and (data.get("area") or data.get("floor")):
        from services.ha_client import _fold_diacritics
        nm = _fold_diacritics(str(data.get("name") or "")).strip()
        loc = _fold_diacritics(str(data.get("area") or data.get("floor") or "")).strip()
        redundant = bool(loc) and loc in nm  # location already named in the entity
        n_match = -1
        if redundant:
            try:
                from services.ha_client import count_name_matches
                n_match = count_name_matches(data["name"])
            except Exception:
                pass
        # Keep area unless it's a redundant echo AND the name isn't itself ambiguous.
        if redundant and n_match < 2:
            data.pop("area", None)
            data.pop("floor", None)
            logger.info({"event": "ha_narrow_drop_area", "tool": name,
                         "name": data.get("name"), "reason": "redundant_loc", "matches": n_match})
            return json.dumps(data, ensure_ascii=False)
        logger.info({"event": "ha_narrow_keep_area", "tool": name, "name": data.get("name"),
                     "area": data.get("area"), "floor": data.get("floor"),
                     "redundant": redundant, "matches": n_match})
        return arguments
    logger.info({"event": "ha_narrow_noop", "tool": name,
                 "name": data.get("name"), "has_area": bool(data.get("area") or data.get("floor"))})
    return arguments


def _clean_tool_args(name: str, arguments: str) -> str:
    """Strip empty slots, then narrow HA intent calls to the named entity."""
    return _narrow_hass_tool_args(name, _strip_empty_tool_args(arguments))


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

    if event_type == "response.output_item.added":
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
                            "arguments": "",
                        },
                    }]
                }, "finish_reason": None}],
            }

    if event_type == "response.output_item.done":
        item = event.get("item", {})
        if item.get("type") == "function_call":
            # Emit the function call's COMPLETE arguments here. The incremental
            # stream events were matched against a typo'd type
            # ("response.function_call.arguments.delta" instead of
            # "response.function_call_arguments.delta"), so arguments never
            # reached the client — HA got tool_calls with empty args and
            # rejected them ("Service handler cannot target all devices"). The
            # done item always carries the full arguments string, so source
            # them from here (independent of the delta event name).
            return {
                "id": completion_id, "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [{"index": 0, "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": item.get("call_id", ""),
                        "type": "function",
                        "function": {"arguments": _clean_tool_args(item.get("name", ""), item.get("arguments", ""))},
                    }]
                }, "finish_reason": None}],
            }
        return None

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

def _log_event(event: dict):
    try:
        with open("/tmp/codex_events.log", "a", encoding="utf-8") as f:
            import json
            f.write(json.dumps(event) + "\n")
    except:
        pass


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
        force_effort: str | None = None,
        **kwargs,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        """Call Codex Responses API with OAuth token.

        force_effort: default reasoning effort when the model name carries no
        effort suffix — HA control commands pass "none" to skip the reasoning
        pass (cuts RT1 ~4-5s → ~2s) since emitting a tool_call needs no thinking.
        """

        instructions = None
        base_body = _chat_to_responses_input(messages, tools, tool_choice, instructions)

        # Resolve model — auto uses user-configured order from model_settings.enabled_models,
        # falls back to CODEX_AUTO_FALLBACK if no config. Filter to only valid Codex models.
        is_auto = not model or model == "auto"
        if is_auto:
            try:
                from services.config import config as _config
                ms = _config.data.get("model_settings") or {}
                enabled = (ms.get("enabled_models") or {}).get("openai_oauth") if isinstance(ms, dict) else None
                user_order: list[str] = []
                if isinstance(enabled, list):
                    for m in enabled:
                        m = str(m).strip()
                        if not m:
                            continue
                        if m.startswith("cx/"):
                            m = m[3:]
                        # Skip "auto" placeholder AFTER stripping prefix
                        if not m or m == "auto":
                            continue
                        if m not in user_order:
                            user_order.append(m)
                models_to_try = user_order if user_order else list(CODEX_AUTO_FALLBACK)
            except Exception:
                models_to_try = list(CODEX_AUTO_FALLBACK)
        else:
            models_to_try = [model]

        last_error = ""
        for try_idx, try_model in enumerate(models_to_try):
            if try_idx > 0:
                logger.warning({"event": "codex_fallback", "from": models_to_try[try_idx-1],
                                "to": try_model})

            body = dict(base_body)  # fresh copy each attempt
            resolved_model = try_model

            # Parse 9router effort/review suffixes from model name
            _EFFORT_LEVELS = {"xhigh", "high", "medium", "low", "none"}
            _suffixes = resolved_model.split("-")
            _effort = None
            _review = False
            _seen: list[str] = []
            for _s in reversed(_suffixes):
                if _s == "review":
                    _review = True
                elif _s in _EFFORT_LEVELS and _effort is None:
                    _effort = _s
                else:
                    _seen.insert(0, _s)
            if _effort or _review:
                resolved_model = "-".join(_seen)
                if _review:
                    body["include"] = body.get("include", []) or []
                    if isinstance(body["include"], list):
                        body["include"].append("reasoning")
            # Suffix effort wins; otherwise honor the caller-forced default
            # (HA control commands force "none").
            _eff = _effort or force_effort
            if _eff:
                body["reasoning"] = {"effort": _eff}

            body["model"] = resolved_model
            body["store"] = False
            body["stream"] = True
            if "instructions" not in body or not body.get("instructions"):
                body["instructions"] = "You are a helpful assistant."

            for key in ("temperature", "top_p", "frequency_penalty", "presence_penalty",
                         "n", "seed", "logprobs", "top_logprobs", "user",
                         "stream_options", "safety_identifier", "metadata",
                         "parallel_tool_calls"):
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
                    # Try OAuth refresh once before giving up on this token
                    refreshed = _try_refresh_token(access_token)
                    if refreshed:
                        access_token = refreshed
                        headers["Authorization"] = f"Bearer {access_token}"
                        # Re-issue the same request with the new token
                        try:
                            resp.close()
                        except Exception:
                            pass
                        resp = requests.post(
                            CODEX_URL, headers=headers, json=body,
                            timeout=300, stream=True,
                            impersonate="chrome110",
                        )
                        if resp.status_code == 401:
                            # Refresh worked but the new token is still 401. Could be
                            # transient (rotation race) — count it; disable only after
                            # N strikes so one blip doesn't kill a healthy account.
                            _codex_count_401(access_token, "401_after_refresh")
                            raise RuntimeError("Codex OAuth token 401 after refresh")
                    else:
                        # Couldn't refresh (no refresh_token, or a transient failure).
                        # Count the 401 and rotate away; disable only after N strikes.
                        _codex_count_401(access_token, "401_no_refresh")
                        raise RuntimeError("Codex OAuth token 401 (refresh unavailable)")
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
                    # Auto-mark account state for quota/forbidden errors so the pool
                    # rotates away from this token without manual intervention.
                    err_lower = error_text.lower()
                    is_quota_burnt = (
                        resp.status_code == 429
                        and ("usage_limit_reached" in err_lower or "quota" in err_lower)
                    )
                    if resp.status_code == 403 or "forbidden" in err_lower:
                        account_service.update_account(access_token, {"status": "disabled"})
                        logger.warning({"event": "codex_account_disabled",
                                        "reason": "403_forbidden"})
                    elif resp.status_code == 429 or "quota" in err_lower or "rate" in err_lower:
                        # Read the exact reset time Codex tells us — `x-codex-primary-reset-at`
                        # is a unix-epoch second when this account regains its primary
                        # window. Stash it as ISO restore_at so quota_watcher auto-flips
                        # the account back to "active" once it passes instead of leaving
                        # it stuck "limited" forever.
                        restore_iso = None
                        reset_at_hdr = resp_headers.get("x-codex-primary-reset-at") or ""
                        try:
                            if reset_at_hdr and str(reset_at_hdr).strip().isdigit():
                                from datetime import datetime, timezone as _tz
                                restore_iso = datetime.fromtimestamp(
                                    int(reset_at_hdr), tz=_tz.utc
                                ).isoformat()
                        except Exception:
                            restore_iso = None
                        # Fallback: extract resets_at from JSON body (codex free plan
                        # returns it in the body, not as a header).
                        if not restore_iso:
                            try:
                                body_json = json.loads(error_text)
                                err_obj = body_json.get("error") if isinstance(body_json, dict) else None
                                if isinstance(err_obj, dict):
                                    resets_at = int(err_obj.get("resets_at") or 0)
                                    if resets_at > 0:
                                        from datetime import datetime, timezone as _tz2
                                        restore_iso = datetime.fromtimestamp(
                                            resets_at, tz=_tz2.utc
                                        ).isoformat()
                            except Exception:
                                pass
                        updates = {"status": "limited", "quota": 0}
                        if restore_iso:
                            updates["restore_at"] = restore_iso
                        account_service.update_account(access_token, updates)
                        # Demote to back of queue — user's requested rotation:
                        # account #1 burns out → goes to #N, #2 becomes the
                        # new #1 for the next request.
                        account_service.demote_account(access_token)
                        logger.warning({"event": "codex_account_limited",
                                        "reason": "429_quota",
                                        "restore_at": restore_iso,
                                        "action": "demoted_to_tail"})
                    msg = f"Codex error {resp.status_code}: {error_text[:200]}"
                    # Plan-level quota exhaustion → trying other models on the SAME
                    # already-burnt token yields the same 429. Abort the model
                    # fallback chain immediately so the caller (combo) can move
                    # to a different provider — saves ~2s per skipped retry.
                    if is_quota_burnt:
                        logger.info({"event": "codex_quota_burnt_fast_fail",
                                     "model": resolved_model,
                                     "remaining_models": len(models_to_try) - try_idx - 1})
                        raise RuntimeError(msg)
                    if try_idx < len(models_to_try) - 1:
                        last_error = msg
                        continue
                    raise RuntimeError(msg)

                # Success — clear any 401 streak so transient failures never
                # accumulate into a wrongful disable on a healthy account.
                try:
                    if (account_service.get_account(access_token) or {}).get("codex_401_count"):
                        account_service.update_account(access_token, {"codex_401_count": 0})
                except Exception:
                    pass
                if stream:
                    return self._stream_response(resp, resolved_model)
                else:
                    text = ""
                    tool_calls: list[dict[str, Any]] = []
                    for chunk in self._stream_response(resp, resolved_model):
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        text += delta.get("content", "")
                        # Codex streams each function call as separate fragments:
                        # 'output_item.added' carries the name (empty args), then
                        # 'output_item.done' carries the full arguments (no name).
                        # Merge them by fragment shape: a name starts a new call,
                        # an args-only fragment continues the current one. (Naive
                        # extend() here left tool_calls split, so args never
                        # reached the caller.)
                        for frag in (delta.get("tool_calls") or []):
                            fn = frag.get("function") or {}
                            if fn.get("name"):
                                tool_calls.append({
                                    "id": frag.get("id", ""),
                                    "type": "function",
                                    "function": {"name": fn.get("name", ""),
                                                 "arguments": fn.get("arguments", "") or ""},
                                })
                            elif tool_calls:
                                if fn.get("arguments"):
                                    tool_calls[-1]["function"]["arguments"] += fn["arguments"]
                                if frag.get("id") and not tool_calls[-1].get("id"):
                                    tool_calls[-1]["id"] = frag["id"]
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
        """Convert Codex SSE → OpenAI chat completion chunks (dicts)."""
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        sent_role = False
        has_tool_call = False

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
                except Exception:
                    continue

                _log_event(event)

                chunk = _responses_to_chat_chunk(event, model, completion_id, created)
                if chunk:
                    delta = chunk["choices"][0]["delta"]
                    if not sent_role and (delta.get("content") is not None or delta.get("tool_calls") is not None):
                        delta["role"] = "assistant"
                        sent_role = True
                    if delta.get("tool_calls"):
                        has_tool_call = True
                    if chunk["choices"][0].get("finish_reason") == "stop" and has_tool_call:
                        chunk["choices"][0]["finish_reason"] = "tool_calls"
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
                        "arguments": _clean_tool_args(item.get("name", ""), item.get("arguments", "")),
                    },
                })

        message = {"role": "assistant", "content": output_text}
        if tool_calls:
            message["tool_calls"] = tool_calls

        finish_reason = "tool_calls" if tool_calls else "stop"

        from services.protocol.openai_v1_chat_complete import count_message_tokens, count_text_tokens

        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": {
                "prompt_tokens": count_message_tokens(messages, model),
                "completion_tokens": count_text_tokens(output_text, model),
                "total_tokens": count_message_tokens(messages, model) + count_text_tokens(output_text, model),
            },
        }

    def get_token_for_request(self, exclude_tokens: set[str] | None = None) -> str:
        """Priority-FIFO Codex token picker — filtered to codex-typed accounts.

        Free-typed JWT accounts (ChatGPT-free) are skipped here so codex
        retries don't burn through them. The chatgpt provider picks free
        tokens via `account_service.get_text_access_token(account_type="free")`.
        """
        from services.account_service import account_group
        excluded = set(exclude_tokens or set())
        with account_service._lock:
            all_items = list(account_service._accounts.values())
            # Filter to the canonical codex/paid pool: real Codex tokens AND
            # paid-plan accounts (plus/go/business) per account_group(). A
            # paid account that only carries a chatgpt.com web JWT is still in
            # this pool — _handle_openai_oauth_chat detects the web JWT and
            # routes it through the shared chatgpt.com transport instead of the
            # Codex responses API.
            codex_items = [
                i for i in all_items
                if account_group(i) == "codex"
            ]
            logger.info({
                "event": "codex_debug",
                "total_accounts": len(all_items),
                "codex_count": len(codex_items),
                "statuses": [i.get("status") for i in codex_items],
                "has_jwt": sum(1 for i in codex_items if str(i.get("access_token","")).startswith("eyJ")),
            })
            candidates: list[tuple[str, dict]] = []
            for item in codex_items:
                if item.get("status") in ("disabled", "error", "limited"):
                    continue
                token = item.get("access_token") or ""
                if not token or not token.startswith("eyJ"):
                    continue
                if token in excluded:
                    continue
                if _is_openai_api_only(token):
                    continue
                candidates.append((token, item))
            if candidates:
                # smart_pool.weighted: chọn theo success-rate + né vừa dùng;
                # tắt/1 ứng viên → FIFO đầu tiên y hệt cũ.
                if len(candidates) > 1 and account_service._weighted_enabled():
                    return max(candidates, key=lambda c: account_service._selection_weight(c[1]))[0]
                return candidates[0][0]
            raise RuntimeError("No Codex OAuth tokens available. Add via OAuth login or import 9router backup.")


def _try_refresh_token(stale_access_token: str) -> str | None:
    """Refresh a Codex OAuth access_token using its stored refresh_token.

    Returns the new access_token on success, None if no refresh_token is stored
    or the refresh failed transiently. On unrecoverable refresh errors
    (refresh_token_reused / invalid_grant) the account is marked disabled
    so the pool stops handing it out.
    """
    if not stale_access_token:
        return None
    with account_service._lock:
        item = account_service._accounts.get(stale_access_token)
        if not item:
            return None
        refresh_token = item.get("refresh_token") or ""
        device_id = item.get("device_id") or None
    if not refresh_token:
        return None

    from services.codex_token_refresh import refresh_codex_token
    result = refresh_codex_token(refresh_token, device_id=device_id)
    if not result:
        return None
    if result.get("error") == "unrecoverable":
        # Disable ngay để request hiện tại xoay account khác, ĐỒNG THỜI kích hoạt
        # tự đăng nhập lại qua session Google ở thread nền (không chặn request).
        account_service.update_account(stale_access_token, {"status": "disabled"})
        logger.warning({"event": "codex_account_disabled_after_refresh_fail",
                        "code": result.get("code")})
        try:
            acct = account_service.get_account(stale_access_token) or item
            try:
                from services.log_service import LOG_TYPE_ACCOUNT, log_service
                em = str((acct or {}).get("email") or "")[:80]
                log_service.add(
                    LOG_TYPE_ACCOUNT,
                    f"Codex refresh_token lỗi ({result.get('code')}) — disable + khôi phục nhiều tầng",
                    {
                        "email": em,
                        "reason": f"refresh {result.get('code')}",
                        "source": "codex_oauth",
                        "group": "codex",
                    },
                )
            except Exception:
                pass
            import threading as _t
            from services.account_recovery import codex_google_relogin_and_notify
            _t.Thread(target=codex_google_relogin_and_notify,
                      args=(dict(acct), f"refresh {result.get('code')}"),
                      daemon=True).start()
        except Exception as _exc:
            logger.warning({"event": "codex_grelogin_spawn_failed", "error": str(_exc)[:120]})
        return None

    new_access = result.get("access_token") or ""
    new_refresh = result.get("refresh_token") or refresh_token
    expires_at = result.get("expires_at") or None
    if not new_access:
        return None

    # Persist new credentials. The access_token is the dict key, so when it
    # rotates we delete the old entry and reinsert under the new key.
    with account_service._lock:
        old = account_service._accounts.pop(stale_access_token, None) or {}
        merged = {**old, "access_token": new_access, "refresh_token": new_refresh,
                  "status": "active"}
        if expires_at:
            merged["expires_at"] = expires_at
        normalized = account_service._normalize_account(merged)
        if normalized is not None:
            account_service._accounts[new_access] = normalized
        account_service._save_accounts()
    logger.info({"event": "codex_token_refreshed"})
    return new_access


# Singleton
codex_oauth = CodexOAuthProvider()
