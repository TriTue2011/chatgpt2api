from __future__ import annotations

import re
import time
import uuid
import json
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
    stream_conversation_events,
    text_backend,
)
from utils.helper import build_chat_image_markdown_content, extract_chat_image, extract_chat_prompt, is_image_chat_request, parse_image_count


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
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prompt_tokens = count_message_tokens(messages, model) if messages else 0
    completion_tokens = count_text_tokens(content, model) if messages else 0
    
    message = {"role": "assistant", "content": content}
    finish_reason = "stop"
    
    if tool_calls:
        message["tool_calls"] = tool_calls
        message["content"] = None
        finish_reason = "tool_calls"
        
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": created or int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": finish_reason,
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _iter_stream_segments(text: str, chunk_size: int = 64):
    """Yield stream segments while keeping words intact. Mirrors Gemini-FastAPI _iter_stream_segments."""
    if not text:
        return
    token_pattern = re.compile(r"\s+|\S+\s*")
    pending = ""
    for match in token_pattern.finditer(text):
        token = match.group(0)
        if len(token) > chunk_size:
            if pending:
                yield pending
                pending = ""
            for idx in range(0, len(token), chunk_size):
                yield token[idx: idx + chunk_size]
            continue
        if pending and len(pending) + len(token) > chunk_size:
            yield pending
            pending = ""
        pending += token
    if pending:
        yield pending


def _buffered_tool_chat_completion(backend, request: ConversationRequest) -> Iterator[dict[str, Any]]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    model = request.model
    
    # Collect the entire response
    content, tool_calls = collect_chat_content_and_tools(stream_conversation_events(backend, request))
    
    # If we have text, we parse it to extract and remove any injected tool calls
    if content:
        # Import here to avoid circular dependencies if any, or just use the parsing logic
        from services.protocol.conversation import extract_and_remove_tool_calls
        cleaned_content, extracted_tool_calls = extract_and_remove_tool_calls(content)
        content = cleaned_content
        if extracted_tool_calls:
            tool_calls.extend(extracted_tool_calls)

        
    # Yield role start chunk (always first, separately - matches Gemini-FastAPI exactly)
    yield completion_chunk(model, {"role": "assistant"}, None, completion_id, created)

    # Yield cleaned text in segments
    if content:
        for segment in _iter_stream_segments(content):
            yield completion_chunk(model, {"content": segment}, None, completion_id, created)

    # Yield tool calls (with index, as required by OpenAI streaming spec)
    if tool_calls:
        tool_calls_delta = [{**call, "index": idx} for idx, call in enumerate(tool_calls)]
        yield completion_chunk(model, {"tool_calls": tool_calls_delta}, None, completion_id, created)
        yield completion_chunk(model, {}, "tool_calls", completion_id, created)
        return

    yield completion_chunk(model, {}, "stop", completion_id, created)

def stream_text_chat_completion(backend, request: ConversationRequest) -> Iterator[dict[str, Any]]:
    if request.tools:
        # Buffer and process at the end to reliably extract injected tool calls
        yield from _buffered_tool_chat_completion(backend, request)
        return

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    sent_role = False
    model = request.model
    
    from services.protocol.conversation import CITATION_RE
    
    def _filtered_events():
        buffer = ""
        for event in stream_conversation_events(backend, request):
            if event.get("type") == "conversation.delta":
                delta = str(event.get("delta") or "")
                if not delta:
                    continue
                buffer += delta
                # Use [ \t]* instead of \s* to avoid eating newlines, which breaks markdown lists
                buffer = re.sub(r'[ \t]*\ue200.*?\ue201[ \t]*', '', buffer)
                buffer = CITATION_RE.sub("", buffer)
                buffer = re.sub(r'[^\s]*citeturn[^\s]*', '', buffer, flags=re.IGNORECASE)
                
                # Strip Markdown for TTS
                buffer = re.sub(r'[*#_]', '', buffer)
                buffer = re.sub(r'-{3,}', '', buffer)
                buffer = re.sub(r'(?m)^\s*[-+]\s+', '', buffer)
                buffer = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', buffer)
                
                # If a citation marker has started but not finished, hold the buffer
                if "\ue200" in buffer and "\ue201" not in buffer:
                    continue
                    
                if len(buffer) > 50:
                    yield {"type": "conversation.delta", "delta": buffer[:-30]}
                    buffer = buffer[-30:]
            else:
                yield event
        if buffer:
            # Use [ \t]* instead of \s* to avoid eating newlines, which breaks markdown lists
            buffer = re.sub(r'[ \t]*\ue200.*?\ue201[ \t]*', '', buffer)
            buffer = CITATION_RE.sub("", buffer)
            buffer = re.sub(r'[^\s]*citeturn[^\s]*', '', buffer, flags=re.IGNORECASE)
            
            # Strip Markdown for TTS
            buffer = re.sub(r'[*#_]', '', buffer)
            buffer = re.sub(r'-{3,}', '', buffer)
            buffer = re.sub(r'(?m)^\s*[-+]\s+', '', buffer)
            buffer = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', buffer)
            
            yield {"type": "conversation.delta", "delta": buffer}

            
    for event in _filtered_events():
        if event.get("type") == "conversation.delta":
            delta_text = str(event.get("delta") or "")
            if not delta_text:
                continue
            if not sent_role:
                sent_role = True
                yield completion_chunk(model, {"role": "assistant", "content": delta_text}, None, completion_id, created)
            else:
                yield completion_chunk(model, {"content": delta_text}, None, completion_id, created)
        
        elif event.get("type") == "conversation.tool_calls":
            tool_calls = event.get("tool_calls") or []
            if not sent_role:
                sent_role = True
                yield completion_chunk(model, {"role": "assistant", "tool_calls": tool_calls}, None, completion_id, created)
            else:
                yield completion_chunk(model, {"tool_calls": tool_calls}, None, completion_id, created)
            yield completion_chunk(model, {}, "tool_calls", completion_id, created)
            return

    if not sent_role:
        yield completion_chunk(model, {"role": "assistant", "content": ""}, None, completion_id, created)
    yield completion_chunk(model, {}, "stop", completion_id, created)



def collect_chat_content_and_tools(events: Iterable[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") == "conversation.delta":
            delta = str(event.get("delta") or "")
            if delta:
                parts.append(delta)
        elif event.get("type") == "conversation.tool_calls":
            tool_calls.extend(event.get("tool_calls") or [])
    return "".join(parts), tool_calls


# Backward-compatible alias used by anthropic_v1_messages.py
def collect_chat_content(events: Iterable[dict[str, Any]]) -> str:
    content, _ = collect_chat_content_and_tools(events)
    return content


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
    tools = body.get("tools")
    tool_choice = body.get("tool_choice")
    messages = normalize_messages(chat_messages_from_body(body), tools=tools, tool_choice=tool_choice)
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
    if body.get("stream"):
        if is_image_chat_request(body):
            return image_chat_events(body)
        model, messages, tools, tool_choice = text_chat_parts(body)
        request = ConversationRequest(model=model, messages=messages, tools=tools, tool_choice=tool_choice)
        return stream_text_chat_completion(text_backend(), request)
    
    if is_image_chat_request(body):
        return image_chat_response(body)
        
    model, messages, tools, tool_choice = text_chat_parts(body)
    request = ConversationRequest(model=model, messages=messages, tools=tools, tool_choice=tool_choice)
    content, tool_calls = collect_chat_content_and_tools(stream_conversation_events(text_backend(), request))
    
    if content:
        from services.protocol.conversation import extract_and_remove_tool_calls
        cleaned_content, extracted_tool_calls = extract_and_remove_tool_calls(content)
        content = cleaned_content
        if extracted_tool_calls:
            tool_calls.extend(extracted_tool_calls)
            
    return completion_response(model, content, messages=messages, tool_calls=tool_calls)
