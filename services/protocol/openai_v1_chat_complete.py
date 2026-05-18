from __future__ import annotations

import json
import time
import uuid
from typing import Any, Iterable, Iterator

from fastapi import HTTPException

from services.protocol.conversation import (
    ConversationRequest,
    ImageOutput,
    collect_image_outputs,
    collect_text,
    count_message_tokens,
    count_text_tokens,
    encode_images,
    normalize_messages,
    stream_image_outputs_with_pool,
    stream_text_deltas,
    text_backend,
)
from services.account_service import account_service
from services.backend_router import backend_router
from services.config import config
from services.model_cooldown import model_cooldown
from services.search_service import search_service
from utils.helper import build_chat_image_markdown_content, extract_chat_image, extract_chat_prompt, is_image_chat_request, parse_image_count
from utils.log import logger


def _extract_status(error_text: str) -> int:
    """Extract HTTP status code from error message text."""
    import re
    text = str(error_text)
    match = re.search(r'\b(4\d\d|5\d\d|error\s+(\d+))', text, re.IGNORECASE)
    if match:
        code = match.group(2) or match.group(1)
        try:
            return int(code)
        except ValueError:
            pass
    # Check for keyword patterns
    lower = text.lower()
    if "401" in lower or "unauthorized" in lower: return 401
    if "402" in lower: return 402
    if "403" in lower or "forbidden" in lower: return 403
    if "404" in lower: return 404
    if "429" in lower or "rate" in lower or "quota" in lower: return 429
    if "503" in lower or "502" in lower or "500" in lower: return 500
    return 0


def completion_chunk(model: str, delta: dict[str, Any], finish_reason: str | None = None, completion_id: str = "", created: int | None = None) -> dict[str, Any]:
    return {
        "id": completion_id or f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion.chunk",
        "created": created or int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def completion_response(
    model: str,
    content: str,
    created: int | None = None,
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prompt_tokens = count_message_tokens(messages, model) if messages else 0
    completion_tokens = count_text_tokens(content, model) if messages else 0
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": created or int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def stream_text_chat_completion(backend, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None, tool_choice: Any = None) -> Iterator[dict[str, Any]]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    sent_role = False
    request = ConversationRequest(model=model, messages=messages, tools=tools, tool_choice=tool_choice)
    for delta_text in stream_text_deltas(backend, request):
        if not sent_role:
            sent_role = True
            yield completion_chunk(model, {"role": "assistant", "content": delta_text}, None, completion_id, created)
        else:
            yield completion_chunk(model, {"content": delta_text}, None, completion_id, created)
    if not sent_role:
        yield completion_chunk(model, {"role": "assistant", "content": ""}, None, completion_id, created)
    yield completion_chunk(model, {}, "stop", completion_id, created)


def collect_chat_content(chunks: Iterable[dict[str, Any]]) -> str:
    parts: list[str] = []
    for chunk in chunks:
        choices = chunk.get("choices")
        first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        delta = first.get("delta") if isinstance(first.get("delta"), dict) else {}
        content = str(delta.get("content") or "")
        if content:
            parts.append(content)
    return "".join(parts)


def chat_messages_from_body(body: dict[str, Any]) -> list[dict[str, Any]]:
    messages = body.get("messages")
    if isinstance(messages, list) and messages:
        return [message for message in messages if isinstance(message, dict)]
    prompt = str(body.get("prompt") or "").strip()
    if prompt:
        return [{"role": "user", "content": prompt}]
    raise HTTPException(status_code=400, detail={"error": "messages or prompt is required"})


def chat_image_args(body: dict[str, Any]) -> tuple[str, str, int, list[tuple[bytes, str, str]]]:
    model = str(body.get("model") or "gpt-image-2").strip() or "gpt-image-2"
    prompt = extract_chat_prompt(body)
    if not prompt:
        raise HTTPException(status_code=400, detail={"error": "prompt is required"})
    images = [
        (data, f"image_{idx}.png", mime)
        for idx, (data, mime) in enumerate(extract_chat_image(body), start=1)
    ]
    return model, prompt, parse_image_count(body.get("n")), images


def text_chat_parts(body: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]] | None, Any]:
    model = str(body.get("model") or "auto").strip() or "auto"
    messages = chat_messages_from_body(body)
    tools = body.get("tools")
    if isinstance(tools, list) and tools:
        tools = [t for t in tools if isinstance(t, dict)]
    else:
        tools = None
    tool_choice = body.get("tool_choice")
    return model, messages, tools, tool_choice


def image_result_content(result: dict[str, Any]) -> str:
    data = result.get("data")
    if isinstance(data, list) and data:
        return build_chat_image_markdown_content(result)
    return str(result.get("message") or "Image generation completed.")


def image_chat_response(body: dict[str, Any]) -> dict[str, Any]:
    model, prompt, n, images = chat_image_args(body)
    result = collect_image_outputs(stream_image_outputs_with_pool(ConversationRequest(
        prompt=prompt,
        model=model,
        n=n,
        response_format="b64_json",
        images=encode_images(images) or None,
    )))
    return completion_response(model, image_result_content(result), int(result.get("created") or 0) or None)


def image_chat_events(body: dict[str, Any]) -> Iterator[dict[str, Any]]:
    model, prompt, n, images = chat_image_args(body)
    image_outputs = stream_image_outputs_with_pool(ConversationRequest(
        prompt=prompt,
        model=model,
        n=n,
        response_format="b64_json",
        images=encode_images(images) or None,
    ))
    yield from stream_image_chat_completion(image_outputs, model)


def stream_image_chat_completion(image_outputs: Iterable[ImageOutput], model: str) -> Iterator[dict[str, Any]]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    sent_role = False
    sent_text = ""
    for output in image_outputs:
        content = ""
        if output.kind == "progress":
            content = output.text
            sent_text += content
        elif output.kind == "result":
            content = build_chat_image_markdown_content({"data": output.data})
        elif output.kind == "message":
            content = output.text[len(sent_text):] if output.text.startswith(sent_text) else output.text
        if not content:
            continue
        if not sent_role:
            sent_role = True
            yield completion_chunk(model, {"role": "assistant", "content": content}, None, completion_id, created)
        else:
            yield completion_chunk(model, {"content": content}, None, completion_id, created)
    if not sent_role:
        yield completion_chunk(model, {"role": "assistant", "content": ""}, None, completion_id, created)
    yield completion_chunk(model, {}, "stop", completion_id, created)


def handle(body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    # Image chat requests always use existing DALL-E flow
    if is_image_chat_request(body):
        if body.get("stream"):
            return image_chat_events(body)
        return image_chat_response(body)

    model, messages, tools, tool_choice = text_chat_parts(body)

    # Check if this is a combo model — try each model until success
    if backend_router.is_combo(model):
        routes = backend_router.route_combo(model)
        last_error = ""
        for route in routes:
            try:
                # Check cooldown before trying this provider
                cooldown = model_cooldown.get_cooldown_info(route.model)
                if cooldown:
                    logger.warning({"event": "model_cooldown_skip", "model": route.model, **cooldown})
                    last_error = cooldown["message"]
                    continue

                logger.info({"event": "combo_try", "combo": model, "provider": route.provider, "model": route.model})
                if search_service.is_enabled and route.provider != "chatgpt":
                    messages_copy = search_service.process_messages(messages)
                else:
                    messages_copy = messages
                result = _dispatch(route, messages_copy, tools, tool_choice, body)
                # Record success on cooldown manager
                model_cooldown.record_success("combo:" + model, route.model)
                return result
            except Exception as exc:
                last_error = str(exc)
                logger.warning({"event": "combo_fail", "combo": model, "provider": route.provider, "error": last_error[:200]})
                # Record failure for per-model cooldown
                model_cooldown.record_failure(
                    account_id="combo:" + model,
                    model=route.model,
                    status_code=_extract_status(last_error),
                    error_body=last_error,
                    provider=route.provider,
                )
                continue
        return completion_response(model=model, content=f"All providers failed. Last error: {last_error[:200]}", messages=messages)

    # Single model — route directly
    route = backend_router.route(model, messages)

    # Apply search injection for non-ChatGPT backends
    if search_service.is_enabled and route.provider != "chatgpt":
        messages = search_service.process_messages(messages)

    return _dispatch(route, messages, tools, tool_choice, body)


def _dispatch(route, messages, tools, tool_choice, body):
    """Dispatch to the correct provider handler."""
    if route.provider == "opencode":
        return _handle_opencode_chat(route.model, messages, body.get("stream"), body)
    elif route.provider == "ninerouter":
        return _handle_ninerouter_chat(route.model, messages, tools, tool_choice, body.get("stream"), body)
    elif route.provider in ("openai_oauth", "codex"):
        return _handle_openai_oauth_chat(route.model, messages, tools, tool_choice, body.get("stream"), body)
    elif route.provider == "gemini_free":
        return _handle_gemini_chat(route.model, messages, body.get("stream"), body)
    elif route.provider == "nvidia_nim":
        return _handle_nvidia_chat(route.model, messages, tools, tool_choice, body.get("stream"), body)
    elif route.provider.startswith("custom:"):
        return _handle_custom_openai_chat(route.provider, route.model, messages, tools, tool_choice, body.get("stream"), body)
    elif route.provider == "chatgpt":
        return _handle_chatgpt_chat(route.model, messages, tools, tool_choice, body.get("stream"), body)
    else:
        logger.warning({"event": "unknown_provider", "provider": route.provider, "fallback": "chatgpt"})
        return _handle_chatgpt_chat(route.model, messages, tools, tool_choice, body.get("stream"), body)


def _restore_tool_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Undo normalize_messages tool→user conversion for OpenAI API compatibility.

    normalize_messages preserves tool_call_id field even when converting to user role.
    We check for that field to restore proper tool messages.
    """
    import re
    result: list[dict[str, Any]] = []
    stop_pattern = re.compile(r'\n\n\[STOP:.*$', re.DOTALL)

    for msg in messages:
        tool_call_id = str(msg.get("tool_call_id") or "")
        if msg.get("role") == "user" and tool_call_id:
            # This was originally a tool message — restore it
            content = str(msg.get("content") or "")
            # Strip [STOP:...] failure suffix if present
            content = stop_pattern.sub("", content).strip()
            result.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})
        else:
            result.append(msg)
    return result


def _handle_chatgpt_chat(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    stream: bool,
    body: dict[str, Any],
) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """ChatGPT flow — auto-detects token type and routes to correct API."""
    # RTK-style compression for large payloads (chatgpt/ only)
    from services.protocol.conversation import _rtk_compress_messages
    messages = _rtk_compress_messages(messages, 24_000)

    # Pick token preferring api.openai.com audience (for chatgpt/ models)
    from services.account_service import detect_token_audience, _TOKEN_AUDIENCE_OPENAI_API, _TOKEN_AUDIENCE_CHATGPT
    token = account_service.get_text_access_token()

    # If token is api.openai.com type → route through OpenAI API provider
    if token and detect_token_audience(token) == _TOKEN_AUDIENCE_OPENAI_API:
        logger.info({"event": "chatgpt_openai_api_routed"})
        # Map chatgpt.com model names to valid OpenAI API models
        openai_model = model if model != "auto" else "gpt-4.1-mini"
        if openai_model.startswith("chatgpt/"):
            openai_model = openai_model[len("chatgpt/"):]
        if openai_model == "auto":
            openai_model = "gpt-4.1-mini"

        # Undo tool→user conversion: OpenAI API needs native tool role messages
        messages = _restore_tool_messages(messages)

        return _handle_custom_openai_chat(
            "custom:openai", openai_model, messages, tools, tool_choice, stream, body,
            force_token=token,
        )

    if token and detect_token_audience(token) in ("unknown", _TOKEN_AUDIENCE_CHATGPT):
        # Route through chatgpt.com backend
        if stream:
            return stream_text_chat_completion(text_backend(), messages, model, tools, tool_choice)
        request = ConversationRequest(model=model, messages=messages, tools=tools, tool_choice=tool_choice)
        return completion_response(model, collect_text(text_backend(), request), messages=messages)

    # Fallback: no token or unknown type
    if stream:
        return stream_text_chat_completion(text_backend(), messages, model, tools, tool_choice)
    request = ConversationRequest(model=model, messages=messages, tools=tools, tool_choice=tool_choice)
    return completion_response(model, collect_text(text_backend(), request), messages=messages)


def _handle_opencode_chat(
    model: str,
    messages: list[dict[str, Any]],
    stream: bool,
    body: dict[str, Any],
) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """OpenCode chat — no 24KB payload limit, no auth required."""
    from services.providers.opencode import opencode_provider

    # Strip oc/ prefix if present
    opencode_model = model
    if model.startswith("oc/"):
        opencode_model = model[3:]
    elif model == "auto":
        opencode_model = "auto"

    logger.info({
        "event": "opencode_chat_routed",
        "model": opencode_model,
        "stream": stream,
        "message_count": len(messages),
    })

    temperature = float(body.get("temperature") or 0.7)
    max_tokens = body.get("max_tokens")

    if stream:
        return _stream_opencode_response(opencode_model, messages, temperature, max_tokens, body)
    else:
        return _opencode_completion_response(opencode_model, messages, temperature, max_tokens)


def _stream_opencode_response(
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int | None,
    body: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    """Stream response from OpenCode — extract tool calls from text if present."""
    from services.providers.opencode import opencode_provider

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    sent_role = False
    accumulated = ""

    try:
        sse_stream = opencode_provider.chat_completions(
            messages=messages, model=model, stream=True,
            temperature=temperature, max_tokens=max_tokens,
        )

        for line in sse_stream:
            if line.startswith("data: "):
                payload = line[6:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    delta_text = ""
                    choices = chunk.get("choices", [])
                    if choices and isinstance(choices[0], dict):
                        delta_text = str(choices[0].get("delta", {}).get("content", "") or "")
                    accumulated += delta_text
                    chunk["id"] = completion_id
                    chunk["created"] = created
                    chunk["model"] = model
                    if delta_text and not sent_role:
                        chunk["choices"][0]["delta"] = {"role": "assistant", "content": delta_text}
                        sent_role = True
                    yield chunk
                except Exception:
                    continue

        # On completion, check if response contains tool calls
        tool_calls = _extract_tool_calls_from_text(accumulated)
        if tool_calls:
            yield {
                "id": completion_id, "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [{"index": 0, "delta": {"tool_calls": tool_calls}, "finish_reason": None}],
            }

        if not sent_role:
            yield completion_chunk(model, {"role": "assistant", "content": ""}, None, completion_id, created)
        yield completion_chunk(model, {}, "stop", completion_id, created)

    except Exception as exc:
        logger.error({"event": "opencode_stream_fatal", "error": str(exc)})
        yield completion_chunk(model, {"role": "assistant", "content": f"OpenCode error: {exc}"}, "stop", completion_id, created)


def _opencode_completion_response(
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int | None,
) -> dict[str, Any]:
    """Non-streaming response from OpenCode — parse text JSON into native tool_calls."""
    from services.providers.opencode import opencode_provider

    try:
        result = opencode_provider.chat_completions(
            messages=messages,
            model=model,
            stream=False,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = ""
        choices = result.get("choices", [])
        if choices and isinstance(choices[0], dict):
            content = str(choices[0].get("message", {}).get("content", "") or "")

        # Parse text JSON tool calls into native format
        tool_calls = _extract_tool_calls_from_text(content)
        message = {"role": "assistant", "content": ""}
        if tool_calls:
            message["tool_calls"] = tool_calls
        else:
            message["content"] = content

        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": count_message_tokens(messages, model),
                "completion_tokens": count_text_tokens(content, model),
                "total_tokens": count_message_tokens(messages, model) + count_text_tokens(content, model),
            },
        }

    except Exception as exc:
        logger.error({"event": "opencode_completion_error", "error": str(exc)})
        return completion_response(
            model=model,
            content=f"OpenCode error: {exc}",
            messages=messages,
        )


# ── Helper for entity_id → domain conversion ──

def _convert_params(params):
    """Convert OpenCode params to HA-compatible format (entity_ids → domain)."""
    if isinstance(params, dict) and "entity_ids" in params:
        eids = params["entity_ids"]
        if isinstance(eids, list) and eids:
            domains = list(set(eid.split(".")[0] for eid in eids if isinstance(eid, str)))
            return {"domain": domains}
    if isinstance(params, list):
        if all(isinstance(x, str) for x in params):
            if any("." in str(x) for x in params):
                domains = list(set(str(x).split(".")[0] for x in params))
                return {"domain": domains}
            return {"entities": params}
        return {"entities": params}
    if not isinstance(params, dict):
        return {}
    return params


def _extract_tool_calls_from_text(text: str) -> list[dict[str, Any]] | None:
    """Parse text tool calls from OpenCode response.

    Only extract if the response is PURELY a tool call (no conversational answer).
    If there's text after the tool call JSON, assume it's already a complete answer.
    """
    if not text:
        return None
    import re as _re

    # Check if this is a pure tool call — first non-whitespace is a tool name or JSON
    stripped = text.strip()

    # If text contains both a tool call AND a conversational answer (after the JSON),
    # the answer is the main intent — don't extract tool call
    # Pattern: "ToolName\n{json}\n\nAnswer text..." → already answered, skip

    # Format 1: JSON with "action" key
    match = _re.search(r'\{[^{}]*"action"\s*:\s*"([^"]+)"\s*[,}][^{}]*\}', stripped)
    if match:
        # Only use if this is MOSTLY a tool call (not followed by long text)
        after_json = stripped[match.end():].strip()
        if len(after_json) < 50:  # Short or no follow-up text → pure tool call
            try:
                data = json.loads(match.group(0))
                action = data.get("action", "")
                params = _convert_params(data.get("params") or data.get("entity_ids") or data.get("domain") or {})
                if action:
                    return [{"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                             "function": {"name": action, "arguments": json.dumps(params, ensure_ascii=False)}}]
            except (json.JSONDecodeError, AttributeError):
                pass

    # Format 2: ToolName\n{JSON}
    match = _re.search(r'^([A-Z][A-Za-z0-9_]+)\s*\n\s*(\[[^\]]*\]|\{[^{}]*\})', stripped)
    if match:
        after_json = stripped[match.end():].strip()
        if len(after_json) < 50:
            try:
                tool_name = match.group(1)
                params = _convert_params(json.loads(match.group(2)))
                if not isinstance(params, dict): params = {}
                return [{"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                         "function": {"name": tool_name, "arguments": json.dumps(params, ensure_ascii=False)}}]
            except (json.JSONDecodeError, AttributeError):
                pass

    # Format 3: {"tool": "X"} or {"name": "X"}
    match = _re.search(r'\{\s*"(?:tool|name)"\s*:\s*"([^"]+)"\s*,\s*"parameters"\s*:\s*(\{.*?\}|\[.*?\])\s*\}', stripped, _re.DOTALL)
    if match:
        after_json = stripped[match.end():].strip()
        if len(after_json) < 50:
            try:
                tool_name = match.group(1)
                params = _convert_params(json.loads(match.group(2)))
                if not isinstance(params, dict): params = {}
                return [{"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                         "function": {"name": tool_name, "arguments": json.dumps(params, ensure_ascii=False)}}]
            except (json.JSONDecodeError, AttributeError):
                pass

    return None


def _handle_openai_oauth_chat(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    stream: bool,
    body: dict[str, Any],
) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """Use Codex OAuth token to call chatgpt.com/backend-api/codex/responses — same as 9router."""
    from services.providers.openai_oauth import codex_oauth

    pure_model = model[3:] if model.startswith("cx/") else model
    if not pure_model or pure_model == "auto":
        pure_model = "auto"

    logger.info({
        "event": "openai_oauth_chat",
        "model": pure_model,
        "stream": stream,
    })

    temperature = body.get("temperature")
    max_tokens = body.get("max_tokens")

    attempted: set[str] = set()
    last_error = ""

    while True:
        try:
            token = codex_oauth.get_token_for_request(attempted)
        except RuntimeError as exc:
            raise RuntimeError(str(exc))  # Raise so combo can fallback

        if token in attempted:
            break
        attempted.add(token)

        try:
            if stream:
                return codex_oauth.chat_completions(
                    access_token=token, messages=messages, model=pure_model,
                    stream=True, temperature=temperature, max_tokens=max_tokens,
                    tools=tools, tool_choice=tool_choice,
                )
            else:
                result = codex_oauth.chat_completions(
                    access_token=token, messages=messages, model=pure_model,
                    stream=False, temperature=temperature, max_tokens=max_tokens,
                    tools=tools, tool_choice=tool_choice,
                )
                account_service.mark_text_used(token)
                return result
        except Exception as exc:
            last_error = str(exc)
            # On 401 → remove bad token and try next
            if any(x in last_error.lower() for x in ("expired", "401")):
                account_service.remove_invalid_token(token, "codex_oauth")
                continue
            # On 400/429 → try next token (don't remove, might be temporary)
            if any(x in last_error.lower() for x in ("400", "429", "rate")):
                continue
            break

    # Raise exception so combo fallback can try next provider
    raise RuntimeError(f"OpenAI OAuth error: {last_error}")


def _handle_gemini_chat(
    model: str,
    messages: list[dict[str, Any]],
    stream: bool,
    body: dict[str, Any],
) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """Gemini AI Studio chat — native function calling support."""
    from services.providers.gemini_free import gemini_provider, GEMINI_DEFAULT_MODEL

    pure_model = model
    for prefix in ("gemini/", "gemini_free/"):
        if model.startswith(prefix):
            pure_model = model[len(prefix):]
            break
    if not pure_model or pure_model == "auto":
        # Use user's configured model from settings, fallback to default
        provider_cfg = (config.data.get("providers") or {}).get("gemini_free") or {}
        pure_model = str(provider_cfg.get("model") or "") or GEMINI_DEFAULT_MODEL

    logger.info({"event": "gemini_chat", "model": pure_model})

    temperature = body.get("temperature")
    max_tokens = body.get("max_tokens")
    tools = body.get("tools")
    tool_choice = body.get("tool_choice")

    try:
        # Gemini always streams via SSE API — iterator handles both cases
        result_iter = gemini_provider.chat_completions(
            messages=messages, model=pure_model,
            temperature=temperature, max_tokens=max_tokens,
            tools=tools, tool_choice=tool_choice,
        )
        if stream:
            return result_iter
        else:
            # Collect stream into single response
            content = ""
            tc = []
            for chunk in result_iter:
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content += delta.get("content", "")
                if delta.get("tool_calls"):
                    tc = delta["tool_calls"]
            msg = {"role": "assistant", "content": content}
            if tc:
                msg["tool_calls"] = tc
            return {
                "id": f"chatcmpl-{uuid.uuid4().hex}", "object": "chat.completion",
                "created": int(time.time()), "model": pure_model,
                "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
    except Exception as exc:
        logger.error({"event": "gemini_fatal", "error": str(exc)})
        return completion_response(model=model, content=f"Gemini error: {exc}", messages=messages)


def _handle_nvidia_chat(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    stream: bool,
    body: dict[str, Any],
) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """NVIDIA NIM chat — OpenAI-compatible proxy, no format conversion needed."""
    from services.providers.nvidia_nim import nvidia_nim_provider

    pure_model = model
    if model.startswith("nv/"):
        pure_model = model[3:]

    logger.info({"event": "nvidia_nim_chat", "model": pure_model, "stream": stream})

    temperature = body.get("temperature")
    max_tokens = body.get("max_tokens")

    try:
        result = nvidia_nim_provider.chat_completions(
            messages=messages, model=pure_model, stream=stream,
            temperature=temperature, max_tokens=max_tokens,
            tools=tools, tool_choice=tool_choice,
            top_p=body.get("top_p"),
            frequency_penalty=body.get("frequency_penalty"),
            presence_penalty=body.get("presence_penalty"),
        )
        if stream:
            return result
        else:
            return result
    except Exception as exc:
        logger.error({"event": "nvidia_nim_fatal", "error": str(exc)})
        return completion_response(
            model=model,
            content=f"NVIDIA NIM error: {exc}",
            messages=messages,
        )


def _handle_custom_openai_chat(
    provider_key: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    stream: bool,
    body: dict[str, Any],
    force_token: str = "",
) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """Custom OpenAI-compatible provider — generic proxy.

    If force_token is provided, it overrides the provider's configured API key.
    Used for OpenAI API tokens detected from chatgpt/ requests.
    """
    from services.providers.custom_openai import CustomOpenAIProvider, get_custom_providers

    # Extract provider ID from "custom:deepseek" format
    provider_id = provider_key[len("custom:"):]

    providers = get_custom_providers()
    cfg = dict(providers.get(provider_id) or {})
    if not cfg:
        return completion_response(
            model=model,
            content=f"Custom provider '{provider_id}' not found or disabled",
            messages=messages,
        )

    if force_token:
        cfg["api_key"] = force_token

    provider = CustomOpenAIProvider(cfg)

    logger.info({"event": "custom_openai_chat", "provider": provider.name, "model": model})

    temperature = body.get("temperature")
    max_tokens = body.get("max_tokens")

    try:
        result = provider.chat_completions(
            messages=messages, model=model, stream=stream,
            temperature=temperature, max_tokens=max_tokens,
            tools=tools, tool_choice=tool_choice,
            top_p=body.get("top_p"),
            frequency_penalty=body.get("frequency_penalty"),
            presence_penalty=body.get("presence_penalty"),
        )
        if stream:
            return result
        else:
            return result
    except Exception as exc:
        logger.error({"event": "custom_openai_fatal", "provider": provider.name, "error": str(exc)})
        return completion_response(
            model=model,
            content=f"[{provider.name}] Error: {exc}",
            messages=messages,
        )
