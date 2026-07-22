from __future__ import annotations

import itertools
import json
import re
import time
import uuid
from typing import Any, Iterable, Iterator

from fastapi import HTTPException

from services.protocol.conversation import (
    ConversationRequest,
    ImageOutput,
    TOOL_CALL_RE,
    TOOL_CALL_SELF_CLOSING_RE,
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
from services.verbalize import verbalize
from services.model_cooldown import model_cooldown
from services.provider_circuit import provider_circuit
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


def _prefetch_stream(gen: Iterator[dict[str, Any]], error_msg: str) -> Iterator[dict[str, Any]]:
    """Pre-fetch first element from a stream generator so auth/connection
    errors are raised synchronously inside the caller's try/except block.

    Without this, lazy generators from stream_text_chat_completion /
    _stream_chatgpt_addon would raise errors only when iterated by
    _wrap_mcp_stream, which silently catches exceptions and returns an
    empty SSE stream — the client sees a 200 OK with no data.
    """
    try:
        first = next(gen)
    except StopIteration:
        raise RuntimeError(error_msg)
    return itertools.chain([first], gen)


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


def _adapter_image_chat(
    model: str,
    prompt: str,
    n: int,
    images: list[tuple[bytes, str, str]] | None = None,
) -> str | None:
    """Bridge chat-image requests to the /v1/images/generations adapter path.

    Models with a dedicated image adapter (flow/, gemini-image/, sdwebui/…)
    never worked through the ChatGPT/Codex account pool below — the pool only
    speaks the ChatGPT web / codex image flows. Returns the chat markdown
    content, or None when the model belongs to the pool.

    When ``images`` is non-empty (img2img / edit), they are passed as body.images
    so adapters that support reference images (gemini-image, custom_openai_image,
    flow if solver accepts) can use them. Adapters that ignore images still run
    text→image with the prompt alone.
    """
    try:
        route = backend_router.route(model)
    except Exception:
        return None
    from services.image_providers import is_image_provider
    if route.provider == "chatgpt" or not is_image_provider(route.provider):
        return None
    from services.protocol import openai_v1_image_generations as imgen
    # Absolute URLs: the agent/telegram consumers download the image over HTTP,
    # so a bare "/images/…" path is unusable for them.
    base = str(config.base_url or "").strip().rstrip("/") or "http://127.0.0.1:80"
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "response_format": "url",
        "base_url": base,
    }
    # Img2img: pass raw (bytes, filename, mime) for adapter edit paths
    if images:
        body["images"] = list(images)
        # Hint for adapters that distinguish text2img vs edit
        body["extra_body"] = {
            **(body.get("extra_body") if isinstance(body.get("extra_body"), dict) else {}),
            "has_reference_image": True,
        }
    result = imgen.handle(body)
    if not isinstance(result, dict):
        return None
    def _abs(u: str) -> str:
        return u if u.startswith("http") else base + u
    links = [f"![image_{i}]({_abs(str(item.get('url')))})"
             for i, item in enumerate(result.get("data") or [], start=1)
             if isinstance(item, dict) and item.get("url")]
    if links:
        return "\n\n".join(links)
    # b64_json responses
    b64_links = []
    for i, item in enumerate(result.get("data") or [], start=1):
        if not isinstance(item, dict):
            continue
        b64 = item.get("b64_json")
        if b64:
            b64_links.append(f"![image_{i}](data:image/png;base64,{b64})")
    if b64_links:
        return "\n\n".join(b64_links)
    return str(result.get("message") or "Image generation completed but no images returned.")


def image_chat_response(body: dict[str, Any]) -> dict[str, Any]:
    model, prompt, n, images = chat_image_args(body)
    content = _adapter_image_chat(model, prompt, n, images)
    if content is not None:
        return completion_response(model, content)
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
    content = _adapter_image_chat(model, prompt, n, images)
    if content is not None:
        cid = f"chatcmpl-{uuid.uuid4().hex}"
        ts = int(time.time())
        yield completion_chunk(model, {"role": "assistant", "content": content}, None, cid, ts)
        yield completion_chunk(model, {}, "stop", cid, ts)
        return
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


# ---------------------------------------------------------------------------
# Combo Code (pipeline bố-con) — kiểu Aider architect/editor: "bố" (model
# mạnh) lập kế hoạch ngắn, "con" (model rẻ/nhanh) viết code dài theo kế hoạch
# → tiết kiệm 30-50% token đầu ra của model đắt. TÁCH BIỆT hoàn toàn với
# combo thường: config key riêng `pipeline_models` (khu "Combo Code" trên UI):
#   {"code": {"architects": ["claude/auto"], "editors": ["cgf/auto", "gma/3.1-pro"]}}

_PIPELINE_ARCHITECT_PROMPT = (
    "Bạn là kiến trúc sư trưởng (architect). Phân tích yêu cầu và lập KẾ HOẠCH "
    "triển khai NGẮN GỌN cho một lập trình viên thực thi: liệt kê các bước, "
    "file/hàm cần sửa, thuật toán, edge case cần xử lý. KHÔNG viết code đầy đủ "
    "— chỉ mô tả và pseudo-code khi thật cần. Trả lời bằng ngôn ngữ của người "
    "dùng, tối đa 400 từ.\n"
    # ponytail + caveman (nội bộ): ưu tiên tối thiểu + nén bản plan.
    "Ưu tiên giải pháp TỐI THIỂU: tái dùng thứ đã có > thư viện chuẩn > viết "
    "mới; KHÔNG abstraction/cấu hình thừa (YAGNI). Kế hoạch NÉN: gạch đầu dòng, "
    "mỗi bước 1 câu, không văn xuôi mở đầu."
)

_PIPELINE_EDITOR_PROMPT = (
    "Bạn là lập trình viên thực thi (editor). Kiến trúc sư trưởng đã duyệt kế "
    "hoạch dưới đây cho yêu cầu của người dùng. Hãy triển khai CHÍNH XÁC theo "
    "kế hoạch, xuất code hoàn chỉnh chạy được, không hỏi lại, không bàn thêm "
    "phương án khác.\n"
    # ponytail: thang quyết định lười; caveman: chỉ xuất code, bỏ rào đón.
    "Tư duy senior LƯỜI — code tốt nhất là code không phải viết: YAGNI → tái "
    "dùng repo → thư viện chuẩn → tính năng nền tảng → deps đã có → one-liner → "
    "cuối cùng mới viết TỐI THIỂU. Không abstraction cho code dùng một lần, sửa "
    "đúng chỗ cần. Trình bày NÉN: chỉ code + chú thích thật cần, KHÔNG lời mở "
    "đầu/tóm tắt dài/liệt kê phương án khác.\n"
    # QUAN TRỌNG: chống global prompt 'trả lời tiếng Việt' làm dịch cú pháp code.
    "GIỮ NGUYÊN CÚ PHÁP CODE bằng ký hiệu/tiếng Anh chuẩn (toán tử %, //, **, "
    "==, and/or/not, từ khóa def/return/if...). TUYỆT ĐỐI KHÔNG dịch code sang "
    "tiếng Việt — vd phải viết ký hiệu '%' CHỨ KHÔNG viết chữ 'phần trăm'. Chỉ "
    "phần giải thích (ngoài code) mới dùng tiếng Việt.\n\n"
    "=== KẾ HOẠCH ĐÃ DUYỆT ===\n{plan}\n=== HẾT KẾ HOẠCH ==="
)

_PIPELINE_REVIEWER_PROMPT = (
    "Bạn là người KIỂM DUYỆT code (reviewer). Dưới đây là YÊU CẦU, KẾ HOẠCH đã "
    "duyệt, và CODE do lập trình viên viết. Hãy soi kỹ: code có đúng yêu cầu + "
    "kế hoạch không, có bug/thiếu sót/edge case bỏ lỡ không, có chạy được không.\n"
    "- Nếu ĐẠT: trả về đúng một dòng 'APPROVED'.\n"
    "- Nếu CHƯA đạt: liệt kê NGẮN GỌN các lỗi cần sửa (gạch đầu dòng), KHÔNG "
    "viết lại code. Bắt đầu bằng 'REVISE:'.\n\n"
    "=== YÊU CẦU ===\n{request}\n=== KẾ HOẠCH ===\n{plan}\n=== CODE ===\n{code}"
)

_PIPELINE_REVISE_PROMPT = (
    "Reviewer yêu cầu sửa các điểm sau. Hãy sửa CODE cho đúng, xuất code hoàn "
    "chỉnh chạy được, KHÔNG giải thích.\n\n=== GÓP Ý CẦN SỬA ===\n{feedback}\n"
    "=== CODE HIỆN TẠI ===\n{code}"
)

_PIPELINE_PLAN_MAX_CHARS = 8000


def _pipeline_reviewer_model() -> str:
    """Model kiểm duyệt (bố soi con) — config agent_branches.code_reviewer.
    Trống = tắt tầng review (giữ hành vi cũ: con viết xong trả thẳng)."""
    try:
        from services.config import config as _c
        return str((_c.data.get("agent_branches") or {}).get("code_reviewer") or "").strip()
    except Exception:
        return ""


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else str(c)
    return ""


def _pipeline_extract_content(result: Any) -> str:
    if isinstance(result, dict):
        try:
            choices = result.get("choices") or []
            msg = choices[0].get("message") or {}
            return str(msg.get("content") or "")
        except Exception:
            return ""
    try:
        return collect_chat_content(result)
    except Exception:
        return ""


def _run_pipeline_review(
    combo_name: str,
    editor_route: Any,
    editor_messages: list[dict[str, Any]],
    body: dict[str, Any],
    reviewer: str,
    plan: str,
    request: str,
    max_rounds: int = 2,
) -> str:
    """Con viết (non-stream) → bố soi → chưa đạt thì chỉnh (≤max_rounds). Trả
    code cuối. Best-effort: reviewer/editor lỗi thì trả code đang có."""
    ns_body = {**body, "stream": False}
    code = _pipeline_extract_content(
        _dispatch(editor_route, editor_messages, None, None, ns_body)).strip()
    for rnd in range(max_rounds):
        try:
            rv_route = backend_router.route(reviewer)
            rv_msgs = [{"role": "user", "content": _PIPELINE_REVIEWER_PROMPT.format(
                request=request[:2000], plan=plan[:4000], code=code[:12000])}]
            verdict = _pipeline_extract_content(
                _dispatch(rv_route, rv_msgs, None, None, ns_body)).strip()
        except Exception as exc:
            logger.warning({"event": "pipeline_review_err", "combo": combo_name, "error": str(exc)[:150]})
            break
        up = verdict.upper()
        if "APPROVED" in up or "REVISE" not in up:
            logger.info({"event": "pipeline_review_ok", "combo": combo_name, "round": rnd})
            break
        logger.info({"event": "pipeline_review_revise", "combo": combo_name, "round": rnd, "notes": verdict[:200]})
        try:
            revise_msgs = list(editor_messages) + [{"role": "system",
                "content": _PIPELINE_REVISE_PROMPT.format(feedback=verdict[:2000], code=code[:12000])}]
            new_code = _pipeline_extract_content(
                _dispatch(editor_route, revise_msgs, None, None, ns_body)).strip()
            if new_code:
                code = new_code
        except Exception as exc:
            logger.warning({"event": "pipeline_revise_err", "combo": combo_name, "error": str(exc)[:150]})
            break
    return code


def _run_pipeline_combo(
    combo_name: str,
    architects: list[str],
    editors: list[str],
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    body: dict[str, Any],
) -> dict[str, Any] | Iterator[dict[str, Any]]:
    # ---- Tầng 1: architect (bố) — non-stream, không tool, chỉ lập plan ----
    plan = ""
    plan_model = ""
    arch_body = dict(body)
    arch_body["stream"] = False
    arch_messages = [{"role": "system", "content": _PIPELINE_ARCHITECT_PROMPT}] + list(messages)
    for am in architects:
        try:
            route = backend_router.route(_strip_marker(am))
            cooldown = model_cooldown.get_cooldown_info(route.model)
            if cooldown:
                logger.warning({"event": "pipeline_architect_cooldown", "combo": combo_name, "model": am, **cooldown})
                continue
            logger.info({"event": "pipeline_architect_try", "combo": combo_name, "provider": route.provider, "model": route.model})
            result = _dispatch(route, arch_messages, None, None, arch_body)
            content = _pipeline_extract_content(result).strip()
            if content:
                plan = content[:_PIPELINE_PLAN_MAX_CHARS]
                plan_model = am
                model_cooldown.record_success("pipeline:" + combo_name, route.model)
                logger.info({"event": "pipeline_architect_ok", "combo": combo_name, "model": am, "plan_chars": len(plan)})
                break
        except Exception as exc:
            logger.warning({"event": "pipeline_architect_fail", "combo": combo_name, "model": am, "error": str(exc)[:200]})
            continue

    # ---- Tầng 2: editor (con) — stream theo client, fallback chain ----
    editor_messages = list(messages)
    if plan:
        editor_messages.append({"role": "system", "content": _PIPELINE_EDITOR_PROMPT.format(plan=plan)})
    else:
        # Tất cả architect chết → degrade về gọi thẳng editor, không hard-fail
        logger.warning({"event": "pipeline_no_plan", "combo": combo_name, "architects": architects})

    # Tầng 3 (tuỳ chọn): reviewer (bố soi con). Bật khi agent_branches.code_reviewer
    # có model. Khi bật → con viết NON-STREAM để soi được, bố review, chưa đạt thì
    # chỉnh (≤2 vòng), rồi trả code cuối. Không có tool-call trong nhánh này.
    reviewer = _pipeline_reviewer_model() if not tools else ""

    last_error = ""
    for em in editors:
        try:
            route = backend_router.route(_strip_marker(em))
            cooldown = model_cooldown.get_cooldown_info(route.model)
            if cooldown:
                last_error = cooldown["message"]
                logger.warning({"event": "pipeline_editor_cooldown", "combo": combo_name, "model": em, **cooldown})
                continue
            logger.info({"event": "pipeline_editor_try", "combo": combo_name, "provider": route.provider, "model": route.model, "has_plan": bool(plan), "architect": plan_model, "reviewer": reviewer or "off"})
            if reviewer:
                code = _run_pipeline_review(combo_name, route, editor_messages, body,
                                            reviewer, plan, _last_user_text(messages))
                model_cooldown.record_success("pipeline:" + combo_name, route.model)
                if body.get("stream"):
                    def _final_stream(_c=code):
                        cid = f"chatcmpl-{uuid.uuid4().hex}"; ts = int(time.time())
                        yield completion_chunk(combo_name, {"role": "assistant", "content": _c}, None, cid, ts)
                        yield completion_chunk(combo_name, {}, "stop", cid, ts)
                    return _final_stream()
                return completion_response(model=combo_name, content=code, messages=messages)
            result = _dispatch(route, editor_messages, tools, tool_choice, body)
            model_cooldown.record_success("pipeline:" + combo_name, route.model)
            return result
        except Exception as exc:
            last_error = str(exc)
            logger.warning({"event": "pipeline_editor_fail", "combo": combo_name, "model": em, "error": last_error[:200]})
            model_cooldown.record_failure(
                account_id="pipeline:" + combo_name, model=em,
                status_code=_extract_status(last_error), error_body=last_error, provider="",
            )
            continue
    err_msg = f"All pipeline editors failed. Last error: {last_error[:200]}"
    if body.get("stream"):
        def _err_stream():
            cid = f"chatcmpl-{uuid.uuid4().hex}"
            ts = int(time.time())
            yield completion_chunk(combo_name, {"role": "assistant", "content": err_msg}, None, cid, ts)
            yield completion_chunk(combo_name, {}, "stop", cid, ts)
        return _err_stream()
    return completion_response(model=combo_name, content=err_msg, messages=messages)


def _emit_content_chunk(tmpl: dict | None, text: str) -> dict[str, Any]:
    import copy
    if isinstance(tmpl, dict) and tmpl.get("choices"):
        c = copy.deepcopy(tmpl)
    else:
        c = {"id": f"chatcmpl-{uuid.uuid4().hex}", "object": "chat.completion.chunk",
             "created": int(time.time()), "choices": [{"index": 0}]}
    c["choices"][0]["delta"] = {"content": text}
    c["choices"][0]["finish_reason"] = None
    return c


def _verbalize_stream(gen: Iterator[dict]) -> Iterator[dict]:
    """Gom CONTENT của stream model, verbalize rồi phát (cho TTS đọc văn xuôi).
    tool_calls / role / finish được giữ nguyên. Buffer cả câu nên đúng đơn vị."""
    buf, tmpl = "", None
    for chunk in gen:
        try:
            ch = (chunk.get("choices") or [{}])[0]
            delta = ch.get("delta") or {}
            fin = ch.get("finish_reason")
        except Exception:
            yield chunk
            continue
        if delta.get("tool_calls"):
            yield chunk
            continue
        if delta.get("content"):
            buf += delta["content"]
            if tmpl is None:
                tmpl = chunk
            continue
        if fin and buf:
            try:
                yield _emit_content_chunk(tmpl, verbalize(buf))
            except Exception:
                yield _emit_content_chunk(tmpl, buf)
            buf = ""
        yield chunk
    if buf:
        try:
            yield _emit_content_chunk(tmpl, verbalize(buf))
        except Exception:
            yield _emit_content_chunk(tmpl, buf)


def _verbalize_result(result):
    """Bọc kết quả model (dict hoặc stream) → văn xuôi cho TTS."""
    if isinstance(result, dict):
        try:
            msg = result["choices"][0]["message"]
            if isinstance(msg.get("content"), str):
                msg["content"] = verbalize(msg["content"])
        except Exception:
            pass
        return result
    return _verbalize_stream(result)


def handle(body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """Wrapper: privacy gate → memory → flow chat chính.

    Privacy (P0): redact MK/token/PII trước khi messages chạm model/log/memory.
    prepare() recall + inject ký ức; capture() lưu lượt sau response.
    """
    # Re-bind request_id bag on this worker thread (LoggedCall runs via threadpool)
    try:
        from services import request_context as rc
        rid = str((body or {}).get("_request_id") or "").strip()
        if rid:
            rc.begin(rid)
    except Exception:
        pass
    # P0/P1 — privacy gate (never send plaintext secrets to LLM)
    try:
        from services.privacy_gate import apply_to_body
        body = apply_to_body(body if isinstance(body, dict) else {})
    except Exception:
        pass
    # HA AI Task structured / json_object: inject schema prompt + post-enforce JSON
    # (Codex/GMA often ignore native response_format.json_schema).
    # Plain questions (no response_format) are NOT forced into JSON here.
    try:
        from services.protocol.response_format import inject_response_format_prompt, wants_structured_output
        body = inject_response_format_prompt(body if isinstance(body, dict) else {})
        if wants_structured_output(body if isinstance(body, dict) else None):
            logger.info({"event": "structured_output_active", "has_response_format": True})
    except Exception as _rf_exc:
        logger.warning({"event": "response_format_inject_skip", "error": str(_rf_exc)[:200]})
    mem_ctx = None
    try:
        from services.memory_service import memory_service
        mem_ctx = memory_service.prepare(body)
    except Exception:
        mem_ctx = None
    result = _handle_main(body)
    if mem_ctx is not None:
        try:
            result = mem_ctx.capture(result)
        except Exception:
            pass
    # TTS văn xuôi: chỉ với câu trả lời MODEL (search/RAG/codex) cho request HA
    # giọng nói. Local fast-path đã verbalize qua _vz; traffic chat/API không đụng.
    try:
        if body.get("_via_model") and _wants_verbalize(body.get("model"), body.get("messages") or []):
            result = _verbalize_result(result)
    except Exception:
        pass
    # Enforce pure JSON for response_format json_schema / json_object
    # and for HA camera vision prompts that need from_json (blueprint JSON mode).
    try:
        from services.protocol.response_format import (
            enforce_response_format,
            enforce_vision_json_if_needed,
        )
        result = enforce_response_format(result, body if isinstance(body, dict) else None)
        result = enforce_vision_json_if_needed(result, body if isinstance(body, dict) else None)
    except Exception as _rf_exc:
        logger.warning({"event": "response_format_enforce_error", "error": str(_rf_exc)[:150]})
    return result


# --- HA RT2 fast-path -------------------------------------------------------
# A Home Assistant device command costs TWO model round-trips: RT1 the model
# emits a Hass* tool_call, HA runs it locally (instant), then RT2 HA sends the
# tool result back and the model only reads out a confirmation line. For control
# actions that fully succeeded the device is ALREADY switched after RT1 — RT2 is
# pure latency (2-8s). We synthesize that confirmation at the gateway and skip
# the second model call. Queries (response_type=query_answer) and any failure
# fall through to the model, which still has to phrase the data / apologise.
_HASS_ACTION_VERB = {
    "HassTurnOn": "bật",
    "HassTurnOff": "tắt",
    "HassLightSet": "chỉnh",
    "HassClimateSetTemperature": "đặt nhiệt độ",
    "HassSetTemperature": "đặt nhiệt độ",
    "HassClimateSetHvacMode": "chỉnh chế độ",
    "HassCoverOpen": "mở",
    "HassCoverClose": "đóng",
    "HassCoverSetPosition": "chỉnh",
    "HassSetPosition": "chỉnh",
    "HassMediaPause": "tạm dừng",
    "HassMediaUnpause": "phát tiếp",
    "HassMediaNext": "chuyển bài",
    "HassMediaPrevious": "quay lại bài",
    "HassMediaSearchAndPlay": "phát",
    "HassSetVolume": "chỉnh âm lượng",
    "HassVacuumStart": "bật",
    "HassVacuumReturnToBase": "đưa về dock",
}


def _ha_confirm_text(messages: list[dict[str, Any]]) -> str | None:
    """Templated confirmation for an HA RT2 control-result follow-up, else None.

    Returns None (let the model run) unless EVERY tool call after the last user
    turn is a whitelisted control action whose result is action_done with no
    failures — so queries and partial failures keep the normal model path.
    """
    last_user = -1
    for i, m in enumerate(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            last_user = i
    if last_user < 0:
        return None

    tail = messages[last_user + 1:]
    # tool_call_id -> tool name, from assistant turns in the tail.
    call_names: dict[str, str] = {}
    for m in tail:
        if isinstance(m, dict) and m.get("role") == "assistant":
            for tc in (m.get("tool_calls") or []):
                cid, fn = tc.get("id"), (tc.get("function") or {})
                if cid and fn.get("name"):
                    call_names[cid] = fn["name"]
    if not call_names:
        return None  # no tool round after last user -> this is RT1

    pairs: list[tuple[str, str]] = []
    saw_result = False
    for m in tail:
        if not isinstance(m, dict) or m.get("role") != "tool":
            continue
        saw_result = True
        name = call_names.get(m.get("tool_call_id"))
        if not name or name not in _HASS_ACTION_VERB:
            return None  # unknown / non-control tool -> let model handle
        verb = _HASS_ACTION_VERB[name]
        try:
            data = json.loads(m.get("content") or "")
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict) or data.get("response_type") != "action_done":
            return None  # query_answer etc -> model must phrase the data
        d = data.get("data") or {}
        if d.get("failed"):
            return None  # partial failure -> let model apologise/explain
        succ = [s for s in (d.get("success") or []) if isinstance(s, dict) and s.get("name")]
        # Build "Đèn trần ở Phòng học": entity names qualified by the area/floor
        # HA targeted. HA only returns the area when the command specified one
        # (i.e. a duplicate-name disambiguation), so the location appears exactly
        # when it adds clarity. Area-only commands name the area itself.
        ents = [str(s.get("name")) for s in succ if s.get("type") not in ("area", "floor")]
        locs = [str(s.get("name")) for s in succ if s.get("type") in ("area", "floor")]
        if not ents:
            ents, locs = locs, []
        names = ", ".join(dict.fromkeys(ents))  # dedup, keep order
        phrase = f"{names} ở {locs[0]}" if (names and locs) else names
        pairs.append((verb, phrase))

    if not saw_result or not pairs:
        return None

    order: list[str] = []
    by_verb: dict[str, list[str]] = {}
    for verb, ent in pairs:
        if verb not in by_verb:
            by_verb[verb] = []
            order.append(verb)
        if ent and ent not in by_verb[verb]:
            by_verb[verb].append(ent)

    segs = [f"{v} {', '.join(by_verb[v])}" if by_verb[v] else v for v in order]
    confirm = "Đã " + ", ".join(segs) + " rồi ạ."
    # Câu lệnh có kèm hỏi cảm biến ("...nhiệt độ phòng khách") → trả lời nốt.
    sensor = _read_sensor_text(messages)
    return confirm + (" " + sensor + "." if sensor else "")


# Vietnamese control verbs → HA intent tool. Broad synonyms; anything unclear
# falls through to the model. Device names & areas are NOT hardcoded — they are
# matched against the live HA registry (different HA = different devices/areas).
_LOCAL_ON_VERBS = {"bat", "mo", "len", "on", "khoi", "kich"}
_LOCAL_OFF_VERBS = {"tat", "dong", "ngat", "off", "ngung", "cup"}
_LOCAL_CANON_DOMAINS = ("light", "switch", "fan")
# Generic device-class nouns → HA domain (folded; keep đ as _fold_diacritics does,
# plus the d-form as a fallback for STT that drops the đ). Used when no specific
# entity name matched: "tắt đèn phòng khách" → all lights in that area.
_LOCAL_DEVICE_CLASS = {
    "đen": "light", "den": "light", "bong đen": "light", "bong den": "light",
    "quat": "fan",
    "đieu hoa": "climate", "dieu hoa": "climate", "may lanh": "climate",
    "cong tac": "switch", "o cam": "switch",
    "rem": "cover", "rem cua": "cover", "man cua": "cover", "cua cuon": "cover",
    "khoa": "lock", "khoa cua": "lock",
    "binh nong lanh": "water_heater", "may nuoc nong": "water_heater",
}
# Sensor-value questions → HA device_class + Vietnamese label. Keys are matched on
# a đ→d-flattened query so "độ sáng"/"do sang" both hit. Used by the read-path so
# the gateway reports the REAL sensor value instead of letting the model guess.
_SENSOR_QUERY = {
    "illuminance":    (["do sang", "anh sang", "chieu sang", "cuong do sang", "lux"], "Độ sáng"),
    "temperature":    (["nhiet do"], "Nhiệt độ"),
    "humidity":       (["do am"], "Độ ẩm"),
    "battery":        (["pin", "battery"], "Pin"),
    "power":          (["cong suat"], "Công suất"),
    "carbon_dioxide": (["co2", "khi co2"], "CO2"),
    "pm25":           (["bui min", "pm25", "pm2 5"], "Bụi mịn PM2.5"),
    "pressure":       (["ap suat"], "Áp suất"),
}


def _find_sublist(hay: list[str], needle: list[str]) -> int:
    """Index where `needle` occurs contiguously in `hay`, else -1."""
    if not needle or len(needle) > len(hay):
        return -1
    for i in range(len(hay) - len(needle) + 1):
        if hay[i:i + len(needle)] == needle:
            return i
    return -1


def _find_all_sub(hay: list[str], needle: list[str]) -> list[int]:
    """All start indices where `needle` occurs contiguously in `hay`."""
    if not needle or len(needle) > len(hay):
        return []
    return [i for i in range(len(hay) - len(needle) + 1)
            if hay[i:i + len(needle)] == needle]


def _ha_local_intent(messages: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Resolve clear control command(s) into HassTurnOn/Off tool_calls WITHOUT the
    model — the fast path. Supports MULTI-device / MULTI-action utterances
    ("bật đèn trần, tắt đèn nhà tắm, bật đèn ngủ") → a LIST of tool_calls. Returns
    the list, or None to let the model handle it (no verb / nothing resolvable).

    Anchors device & area on the LIVE registry; nothing about a specific HA is
    hardcoded. Each control verb opens a segment running until the next verb;
    devices named without their own verb inherit the current one
    ("bật đèn trần, đèn ngủ" → both on)."""
    last_user = -1
    for i, m in enumerate(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            last_user = i
    if last_user < 0:
        return None
    for m in messages[last_user + 1:]:
        if isinstance(m, dict) and m.get("role") in ("tool", "assistant"):
            return None

    try:
        from services.ha_client import (
            _fold_diacritics, get_states, get_exposed_entity_ids, get_ha_area_index,
        )
    except Exception:
        return None
    text = _extract_last_user_text(messages)
    import re as _re
    folded = _re.sub(r"[^\w\s]", " ", _fold_diacritics(str(text or "")))
    toks = folded.split()
    if not toks:
        return None
        
    # Automation / hẹn giờ / đặt lịch KHÔNG phải lệnh điều khiển tức thì — phải
    # để model tạo automation thay vì bật/tắt ngay. Bắt cả typo ("automaiton",
    # "automtion"… qua \bauto) và mọi mốc/khoảng thời gian trong câu ("lúc
    # 10h30", "22 gio", "sau 5 phut", "hang ngay") vì có thời gian = có lịch.
    if ("kich ban" in folded or "tu dong" in folded
            or "script" in folded or "scene" in folded or "ngu canh" in folded
            or _re.search(r"\bauto", folded)
            or _re.search(r"\btao\b", folded)
            or _re.search(r"\b(hen gio|dat lich|len lich|hang ngay|moi ngay|dinh ky)\b", folded)
            or _re.search(r"\bluc\s+\d", folded)
            or _re.search(r"\b\d{1,2}\s*(h|gio|phut|giay)\b", folded)
            or _re.search(r"\b\d{1,2}h\d{1,2}\b", folded)
            or _re.search(r"\bsau\s+\d", folded)):
        return None

    # Verb positions split the utterance into action segments.
    verbs = []  # (index, service)
    for i, t in enumerate(toks):
        if t in _LOCAL_ON_VERBS:
            verbs.append((i, "HassTurnOn"))
        elif t in _LOCAL_OFF_VERBS:
            verbs.append((i, "HassTurnOff"))
    if not verbs:
        return None

    states = get_states(use_cache=True) or []
    exposed = get_exposed_entity_ids(use_cache=True) or set()
    idx = get_ha_area_index()
    area_names = idx.get("area_names") or {}
    entity_area = idx.get("entity_area") or {}
    entity_aliases = idx.get("entity_aliases") or {}

    # Controllable entity name (friendly_name OR alias) -> [(eid, domain, name)].
    ent_by_name: dict[str, list[tuple[str, str, str]]] = {}
    for s in states:
        eid = s.get("entity_id", "")
        if exposed and eid not in exposed:
            continue
        dom = eid.split(".")[0] if "." in eid else ""
        if dom not in _LOCAL_CANON_DOMAINS:
            continue
        orig = (s.get("attributes", {}) or {}).get("friendly_name", "")
        for nf in {_fold_diacritics(orig).strip()} | set(entity_aliases.get(eid, [])):
            if nf:
                ent_by_name.setdefault(nf, []).append((eid, dom, orig))

    _CONN = {"o", "tai", "ben", "trong", "khu", "vuc", "vung", "cua"}

    def _area_in(region: list[str]):
        """Area name at the FRONT of `region` (after optional connector words like
        ở/tại). Adjacency matters so an area belonging to a LATER clause
        ("đèn nhà tắm, nhiệt độ phòng khách") isn't grabbed by this device."""
        i = 0
        while i < len(region) and region[i] in _CONN:
            i += 1
        sub = region[i:]
        best_a, best_n = None, 0
        for af, ao in area_names.items():
            at = af.split()
            if sub[:len(at)] == at and len(at) > best_n:
                best_a, best_n = ao, len(at)
        return best_a

    def _segment_controls(service: str, seg: list[str]) -> list[tuple[str, dict]]:
        """All controls in one verb-segment → [(service, args)…]."""
        # Non-overlapping entity-name matches, longest first.
        spans = []
        for nf in ent_by_name:
            nt = nf.split()
            for pos in _find_all_sub(seg, nt):
                spans.append((pos, pos + len(nt), nf))
        spans.sort(key=lambda x: -(x[1] - x[0]))
        used = [False] * len(seg)
        chosen = []
        for st, en, nf in spans:
            if any(used[st:en]):
                continue
            for i in range(st, en):
                used[i] = True
            chosen.append((st, en, nf))
        out: list[tuple[str, dict]] = []
        if chosen:
            chosen.sort(key=lambda x: x[0])
            for j, (st, en, nf) in enumerate(chosen):
                nxt = chosen[j + 1][0] if j + 1 < len(chosen) else len(seg)
                area = _area_in(seg[en:nxt])  # area between this device and next
                cands = ent_by_name[nf]
                if area:
                    in_area = [c for c in cands if entity_area.get(c[0]) == area]
                    if len(in_area) == 1:
                        eid, dom, orig = in_area[0]
                        out.append((service, {"name": orig, "area": area, "domain": [dom], "_eids": [eid]}))
                    elif len(in_area) > 1:
                        # Multi-signal rank when several in same area
                        try:
                            from services.ha_intent_rank import pick_entity_among
                            picked = pick_entity_among(
                                seg, in_area, service=service, area_hint=area,
                            )
                        except Exception:
                            picked = None
                        if picked:
                            eid, dom, orig = picked
                            out.append((service, {"name": orig, "area": area, "domain": [dom], "_eids": [eid]}))
                    continue
                if len(cands) == 1:
                    eid, dom, orig = cands[0]
                    out.append((service, {"name": orig, "domain": [dom], "_eids": [eid]}))
                elif len(cands) > 1:
                    # duplicate name + no area → multi-signal rank (assist-canonicalizer style)
                    try:
                        from services.ha_intent_rank import rank_candidates
                        soft_area = _area_in(seg) or ""
                        labeled = []
                        for eid, dom, orig in cands:
                            ar = entity_area.get(eid) or ""
                            labeled.append((f"{orig} {ar}".strip(), (eid, dom, orig)))
                        hit = rank_candidates(
                            " ".join(seg) + (" " + soft_area if soft_area else ""),
                            labeled,
                            service=service,
                        )
                        picked = hit.payload if hit else None
                    except Exception:
                        picked = None
                    if picked:
                        eid, dom, orig = picked
                        ar = entity_area.get(eid)
                        args = {"name": orig, "domain": [dom], "_eids": [eid]}
                        if ar:
                            args["area"] = ar
                        out.append((service, args))
                # still ambiguous → skip
            return out
        # Generic device-class + area (whole class in an area); hoặc + từ "tất cả"
        # → toàn bộ class ("tắt hết đèn" → tắt mọi light, không cần area).
        for phrase, dom in sorted(_LOCAL_DEVICE_CLASS.items(), key=lambda kv: -len(kv[0].split())):
            ct = phrase.split()
            poss = _find_all_sub(seg, ct)
            if poss:
                area = _area_in(seg[poss[0] + len(ct):])
                if area:
                    eids = [s.get("entity_id") for s in states if s.get("entity_id", "").startswith(dom+".") and entity_area.get(s.get("entity_id")) == area]
                    if eids:
                        out.append((service, {"area": area, "domain": [dom], "_eids": eids}))
                elif any(w in " ".join(seg) for w in ("het", "tat ca", "toan bo")):
                    eids = [s.get("entity_id") for s in states if s.get("entity_id", "").startswith(dom+".")]
                    if eids:
                        out.append((service, {"domain": [dom], "_eids": eids}))
                break
        return out

    results: list[tuple[str, dict]] = []
    for k, (vi, svc) in enumerate(verbs):
        seg_end = verbs[k + 1][0] if k + 1 < len(verbs) else len(toks)
        results.extend(_segment_controls(svc, toks[vi + 1:seg_end]))

    if not results:
        return None
    return [
        {"id": f"call_{uuid.uuid4().hex[:24]}", "type": "function",
         "function": {"name": svc, "arguments": json.dumps(args, ensure_ascii=False)}}
        for svc, args in results
    ]


def _ha_local_level(messages: list[dict[str, Any]]) -> str | None:
    """Fast-path cục bộ cho lệnh MỨC: tốc độ quạt (%), quay/dừng quay quạt, độ
    sáng đèn (%). HA-native intent không set được các mức này, nên ta tự gọi
    call_service tới HA rồi trả thẳng câu xác nhận (chạy cho cả HA lẫn dashboard).
    Trả text, hoặc None để rơi xuống path khác."""
    last_user = -1
    for i, m in enumerate(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            last_user = i
    if last_user < 0:
        return None
    for m in messages[last_user + 1:]:
        if isinstance(m, dict) and m.get("role") in ("tool", "assistant"):
            return None
    try:
        from services.ha_client import (
            _fold_diacritics, get_states, get_exposed_entity_ids, call_service,
            get_ha_area_index,
        )
    except Exception:
        return None
    import re as _re
    raw = str(_extract_last_user_text(messages) or "")
    folded = _fold_diacritics(raw)
    fd = folded.replace("đ", "d")
    toks = _re.sub(r"[^\w\s]", " ", folded).split()
    if not toks:
        return None
        
    if "automation" in fd or "kich ban" in fd or "tu dong" in fd:
        return None

    mpct = _re.search(r"(\d{1,3})\s*(?:%|phan\s*tram)", folded)
    pct = max(0, min(100, int(mpct.group(1)))) if mpct else None
    # Mức/số/nấc rời (vd "bật quạt số 1", "quạt mức 3") — KHÔNG có '%'.
    _ml = _re.search(r"(?:so|muc|nac|cap|che do|level|number)\s*(\d{1,2})", fd) or _re.search(r"quat\s+(\d{1,2})\b", fd)
    lvl_num = int(_ml.group(1)) if (_ml and pct is None) else None
    # Mức bằng CHỮ → khái niệm chuẩn; sẽ khớp ĐÚNG TÊN preset (không suy ra vị trí):
    # thấp/cao = low/high; thấp nhất/cao nhất = lowest/highest; trung bình = medium.
    _concept_names = {
        "lowest":  {"lowest", "thap nhat", "min", "minimum", "yeu nhat", "nho nhat", "cham nhat"},
        "low":     {"low", "thap", "yeu", "nhe", "weak"},
        "medium":  {"medium", "middle", "med", "mid", "trung binh", "vua", "normal", "binh thuong", "giua"},
        "high":    {"high", "cao", "manh", "strong"},
        "highest": {"highest", "cao nhat", "max", "maximum", "manh nhat", "lon nhat",
                    "nhanh nhat", "toi da", "het co", "turbo", "boost", "full"},
    }
    _concept_pct = {"lowest": 1, "low": 25, "medium": 50, "high": 75, "highest": 100}
    concept = None
    if _re.search(r"\b(?:thap nhat|yeu nhat|nho nhat|cham nhat|lowest|minimum|min)\b", fd):
        concept = "lowest"
    elif _re.search(r"\b(?:cao nhat|manh nhat|lon nhat|nhanh nhat|toi da|het co|highest|maximum|max|turbo)\b", fd):
        concept = "highest"
    elif _re.search(r"\b(?:thap|yeu|nhe|low|weak)\b", fd):
        concept = "low"
    elif _re.search(r"\b(?:cao|manh|high|strong)\b", fd):
        concept = "high"
    elif _re.search(r"\b(?:trung binh|vua phai|medium|middle|binh thuong|normal|mid|chinh giua|o giua|giua)\b", fd) or "vua" in toks:
        concept = "medium"
    osc_off = any(p in fd for p in ("dung quay", "ngung quay", "tat quay", "khong quay",
                                    "dung xoay", "ngung xoay", "tat xoay", "khong xoay"))
    osc_on = (not osc_off) and ("quay" in toks or "xoay" in toks or "dao chieu" in fd)
    if pct is None and lvl_num is None and concept is None and not osc_on and not osc_off:
        return None

    states = get_states(use_cache=True) or []
    exposed = get_exposed_entity_ids(use_cache=True) or set()
    ent: dict[str, list[tuple[str, str, str]]] = {}
    attrs_by_eid: dict[str, dict] = {}
    for s in states:
        eid = s.get("entity_id", "")
        dom = eid.split(".")[0] if "." in eid else ""
        if dom not in ("fan", "light", "select", "input_select"):
            continue
        if exposed and eid not in exposed:
            continue
        a = s.get("attributes", {}) or {}
        attrs_by_eid[eid] = a
        orig = a.get("friendly_name", "")
        nf = _fold_diacritics(orig).strip()
        if nf:
            ent.setdefault(nf, []).append((eid, dom, orig))

    best = None  # (eid, dom, orig, namelen)
    for nf, cands in ent.items():
        nt = nf.split()
        if not nt or len(cands) != 1:
            continue
        for i in range(len(toks) - len(nt) + 1):
            if toks[i:i + len(nt)] == nt and (best is None or len(nt) > best[3]):
                e, d, o = cands[0]
                best = (e, d, o, len(nt))
                break
    # Khớp tên RÚT GỌN: câu chứa một đoạn LIÊN TIẾP của tên thiết bị (≥2 từ),
    # vd "cánh gió dọc" ↔ "Cánh gió dọc Panasonic". Chỉ nhận khi DUY NHẤT.
    if best is None:
        sub_hits: dict[int, list[tuple[str, str, str]]] = {}
        for nf, cands in ent.items():
            nt = nf.split()
            if len(cands) != 1 or len(nt) < 2:
                continue
            longest = 0
            for a in range(len(nt)):
                for b in range(len(nt), a + 1, -1):
                    if b - a >= 2 and _find_sublist(toks, nt[a:b]) >= 0:
                        longest = max(longest, b - a)
                        break
            if longest >= 2:
                sub_hits.setdefault(longest, []).append(cands[0])
        for k in sorted(sub_hits, reverse=True):
            if len(sub_hits[k]) == 1:
                best = (*sub_hits[k][0], k)
                break
    # Không khớp tên đầy đủ → lọc theo domain + KHU VỰC nêu trong câu, để hỗ trợ
    # NHIỀU quạt/đèn cùng loại (vd "quạt phòng ngủ số 1" dù quạt đặt tên chung).
    if best is None:
        wanted = "fan" if (osc_on or osc_off or "quat" in toks) else ("light" if ("sang" in toks or "den" in toks) else None)
        if wanted:
            idx = get_ha_area_index()
            area_names = idx.get("area_names") or {}
            entity_area = idx.get("entity_area") or {}
            named_areas = [ao for af, ao in area_names.items() if _find_sublist(toks, af.split()) >= 0]
            pool = [(e, d, o) for v in ent.values() for (e, d, o) in v if d == wanted]
            if named_areas:  # nêu khu vực → chỉ giữ thiết bị thuộc khu vực đó
                pool = [t for t in pool if entity_area.get(t[0]) in named_areas]
            if len(pool) == 1:  # còn đúng 1 → chốt
                e, d, o = pool[0]
                best = (e, d, o, 0)
    if best is None:
        return None
    eid, dom, orig, _ = best

    attrs = attrs_by_eid.get(eid, {})
    done: list[str] = []
    invalid = None  # mức nêu rõ nhưng quạt KHÔNG có → báo lại, không thực hiện
    try:
        if dom == "fan":
            if osc_off:
                if call_service("fan", "oscillate", {"entity_id": eid, "oscillating": False}):
                    done.append("dừng quay")
            elif osc_on:
                if call_service("fan", "oscillate", {"entity_id": eid, "oscillating": True}):
                    done.append("quay")
            presets = [str(p) for p in (attrs.get("preset_modes") or [])]
            pfold = [_fold_diacritics(p).replace("đ", "d").lower().strip() for p in presets]
            supports_speed = bool(int(attrs.get("supported_features") or 0) & 1)
            level_req = lvl_num is not None or concept is not None
            target = None
            if presets:
                if lvl_num is not None:
                    if str(lvl_num) in presets:           # tên preset trùng số → lấy
                        target = str(lvl_num)
                    elif 1 <= lvl_num <= len(presets):    # còn lại: theo VỊ TRÍ 1-based
                        target = presets[lvl_num - 1]
                    # vượt số mức → để target None (báo lỗi, không thực hiện)
                elif concept is not None:                 # chữ → khớp ĐÚNG TÊN preset
                    for nfp, cp in zip(pfold, presets):
                        if nfp in _concept_names[concept]:
                            target = cp
                            break
            if target is not None:
                if call_service("fan", "set_preset_mode", {"entity_id": eid, "preset_mode": target}):
                    done.append(f"mức {target}")
            elif supports_speed and (pct is not None or concept is not None):
                spd = pct if pct is not None else _concept_pct.get(concept)
                if spd is not None and call_service("fan", "set_percentage", {"entity_id": eid, "percentage": spd}):
                    done.append(f"tốc độ {spd}%")
            elif pct is not None and presets:             # quạt chỉ-preset nhận '%' → preset gần nhất
                cp = presets[min(len(presets) - 1, max(0, round(pct / 100 * len(presets)) - 1))]
                if call_service("fan", "set_preset_mode", {"entity_id": eid, "preset_mode": cp}):
                    done.append(f"mức {cp}")
            if not done and level_req and presets:        # mức yêu cầu không có thật
                invalid = f"{orig} chỉ có các mức: " + ", ".join(presets) + "."
        elif dom == "light":
            bright = pct if pct is not None else (_concept_pct.get(concept) if concept else None)
            if bright is not None:
                if call_service("light", "turn_on", {"entity_id": eid, "brightness_pct": bright}):
                    done.append(f"độ sáng {bright}%")
        elif dom in ("select", "input_select"):
            # Cửa gió/chế độ dạng chọn: khớp CHỮ vào ĐÚNG TÊN option (highest/high/
            # middle/low/lowest…). Không có option tương ứng → báo lại, không thực hiện.
            options = [str(o) for o in (attrs.get("options") or [])]
            ofold = [_fold_diacritics(o).replace("đ", "d").lower().strip() for o in options]
            target = None
            if concept is not None:
                for of, o in zip(ofold, options):
                    if of in _concept_names[concept]:
                        target = o
                        break
            if target is not None:
                if call_service(dom, "select_option", {"entity_id": eid, "option": target}):
                    done.append(f"chế độ {target}")
            elif concept is not None and options:
                invalid = f"{orig} chỉ có: " + ", ".join(options) + "."
    except Exception as exc:
        logger.warning({"event": "ha_local_level_exec_failed", "error": str(exc)[:150]})
        return None
    if invalid:
        return invalid
    if not done:
        return None
    return f"Đã chỉnh {orig}: " + ", ".join(done) + "."


def _ha_local_query(messages: list[dict[str, Any]]) -> str | None:
    """Answer a sensor-VALUE question (độ sáng/nhiệt độ/độ ẩm…) by reading the
    REAL sensor from the live registry and templating the reply — no model, so it
    can't hallucinate a number. Returns the answer text, or None to let the model
    handle it (no sensor type recognised, no matching/exposed sensor, ambiguous)."""
    import re as _re
    last_user = -1
    for i, m in enumerate(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            last_user = i
    if last_user < 0:
        return None
    for m in messages[last_user + 1:]:
        if isinstance(m, dict) and m.get("role") in ("tool", "assistant"):
            return None

    try:
        from services.ha_client import _fold_diacritics
    except Exception:
        return None
    toks = _re.sub(r"[^\w\s]", " ", _fold_diacritics(str(_extract_last_user_text(messages) or ""))).split()
    if not toks:
        return None
    flat = " ".join(toks).replace("đ", "d")
    if "automation" in flat or "kich ban" in flat or "tu dong" in flat:
        if any(w in flat for w in ("danh sach", "liet ke", "tat ca", "nhung")):
            from services.ha_client import get_states
            states = get_states(use_cache=True) or []
            matches = []
            for s in states:
                eid = s.get("entity_id", "")
                if eid.startswith("automation.") or eid.startswith("script."):
                    name = s.get("attributes", {}).get("friendly_name", "")
                    state = s.get("state", "unknown")
                    state_vn = "đang bật" if state == "on" else ("đang tắt" if state == "off" else state)
                    matches.append(f"- {name} ({eid}): {state_vn}")
            if matches:
                return "Dạ, danh sách các kịch bản / automation hiện có trong hệ thống:\n" + "\n".join(matches) + "\n\n(Lưu ý: trạng thái bật/tắt ở đây là trạng thái kích hoạt của kịch bản, không phải thiết bị thực tế ạ)."
            return "Dạ, em không tìm thấy automation hay kịch bản nào trong hệ thống."
        else:
            return None
    # Fast path for "liệt kê đèn/quạt đang bật" (list devices that are ON)
    if any(w in flat for w in ("dang bat", "con bat", "chua tat", "nao sang", "dang chay")):
        from services.ha_client import get_states, get_exposed_entity_ids
        states = get_states(use_cache=True) or []
        exposed = get_exposed_entity_ids(use_cache=True) or set()
        wanted = []
        if "quat" in flat: wanted.append(("fan", "Quạt"))
        if "den" in flat or "sang" in flat: wanted.append(("light", "Đèn"))
        if "dieu hoa" in flat or "may lanh" in flat: wanted.append(("climate", "Điều hòa"))
        if wanted:
            res_parts = []
            for dom, label in wanted:
                on_ents = []
                for s in states:
                    eid = s.get("entity_id", "")
                    if exposed and eid not in exposed:
                        continue
                    if eid.startswith(f"{dom}.") and str(s.get("state")).lower() in ("on", "playing", "cool", "heat", "auto"):
                        on_ents.append(s.get("attributes", {}).get("friendly_name", ""))
                on_ents = list(filter(None, set(on_ents)))
                if on_ents:
                    res_parts.append(f"{label} đang bật: " + ", ".join(on_ents))
            if res_parts:
                return " ".join(res_parts) + " ạ."
            else:
                names = " hoặc ".join(l for _, l in wanted)
                return f"Dạ, hiện tại không có {names.lower()} nào đang bật ạ."

    # A control verb means it's a command, not a value question → not ours.
    if any(t in _LOCAL_ON_VERBS or t in _LOCAL_OFF_VERBS for t in toks):
        return None
    txt = _read_sensor_text(messages)
    if txt:
        return txt + " ạ."
    return None


def _read_sensor_text(messages: list[dict[str, Any]]) -> str | None:
    """Đọc giá trị cảm biến THẬT cho (các) loại cảm biến + khu vực nêu trong câu
    của user. Hỗ trợ NHIỀU khu vực ('nhiệt độ phòng khách, phòng học'). Trả câu
    plain-text (số dùng dấu phẩy), hoặc None. Dùng cho cả _ha_local_query (RT1) và
    _ha_confirm_text (RT2 — trả lời phần hỏi cảm biến lẫn trong lệnh điều khiển)."""
    import re as _re
    try:
        from services.ha_client import (
            _fold_diacritics, get_states, get_exposed_entity_ids, get_ha_area_index,
        )
    except Exception:
        return None
    toks = _re.sub(r"[^\w\s]", " ", _fold_diacritics(str(_extract_last_user_text(messages) or ""))).split()
    if not toks:
        return None
    flat = " ".join(toks).replace("đ", "d")
    dc = label = None
    for _dc, (kws, lbl) in _SENSOR_QUERY.items():
        if any(kw in flat for kw in kws):
            dc, label = _dc, lbl
            break
    if not dc:
        return None
    idx = get_ha_area_index()
    area_names = idx.get("area_names") or {}
    entity_area = idx.get("entity_area") or {}
    # "nhiệt độ các phòng / tất cả phòng" → đọc MỌI khu vực; ngược lại chỉ khu
    # vực nêu tên.
    if any(p in flat for p in ("cac phong", "tat ca phong", "toan bo phong",
                               "moi phong", "cac khu vuc", "het cac phong",
                               "tung phong", "moi noi")):
        areas = list(dict.fromkeys(area_names.values()))
    else:
        areas = []  # tất cả khu vực nêu tên trong câu (giữ thứ tự)
        for af, ao in area_names.items():
            if _find_sublist(toks, af.split()) >= 0 and ao not in areas:
                areas.append(ao)
    states = get_states(use_cache=True) or []
    exposed = get_exposed_entity_ids(use_cache=True) or set()
    readings: list[tuple[str | None, str]] = []
    for ao in (areas or [None]):
        af_area = _fold_diacritics(ao) if ao else ""
        matches = []
        for s in states:
            eid = s.get("entity_id", "")
            if exposed and eid not in exposed:
                continue
            a = s.get("attributes", {}) or {}
            if a.get("device_class") != dc:
                continue
            if ao:
                fnf = _fold_diacritics(a.get("friendly_name", ""))
                if entity_area.get(eid) != ao and af_area not in fnf:
                    continue
            matches.append(s)
        if len(matches) != 1:
            continue
        s = matches[0]
        val = s.get("state")
        if val is None or str(val).strip().lower() in ("unknown", "unavailable", "none", ""):
            continue
        unit = (s.get("attributes", {}) or {}).get("unit_of_measurement", "") or ""
        try:
            f = round(float(val), 1)
            num = str(int(f)) if f == int(f) else str(f)
        except (TypeError, ValueError):
            num = str(val)
        readings.append((ao, f"{num.replace('.', ',')} {unit}".strip()))
    if not readings:
        return None
    if len(readings) == 1 and readings[0][0] is None:
        return f"{label} hiện {readings[0][1]}"
    parts = [f"{ao.lower()} {v}" if ao else v for ao, v in readings]
    return f"{label} " + ", ".join(parts)


def _uv_cat(uv: float) -> str:
    """Phân mức tia cực tím (đọc xuôi, không nêu số cho đỡ ngang tai)."""
    if uv < 3:
        return "thấp"
    if uv < 6:
        return "trung bình"
    if uv < 8:
        return "cao"
    if uv < 11:
        return "rất cao"
    return "cực kỳ cao"


def _pm25_cat(v: float) -> str:
    """Phân loại chất lượng không khí theo PM2.5 (µg/m³, ngưỡng US EPA)."""
    if v <= 12:
        return "tốt"
    if v <= 35.4:
        return "trung bình"
    if v <= 55.4:
        return "kém"
    if v <= 150.4:
        return "xấu"
    if v <= 250.4:
        return "rất xấu"
    return "nguy hại"


_WEATHER_VI = {
    "sunny": "nắng", "clear-night": "trời quang", "partlycloudy": "ít mây",
    "cloudy": "nhiều mây", "rainy": "có mưa", "pouring": "mưa to",
    "lightning": "có giông", "lightning-rainy": "giông kèm mưa", "fog": "sương mù",
    "hail": "mưa đá", "snowy": "có tuyết", "snowy-rainy": "mưa tuyết",
    "windy": "gió mạnh", "windy-variant": "gió mạnh", "exceptional": "thời tiết đặc biệt",
}
# City extraction for geocoding. Strips weather lead-ins, connectors (ở/tại),
# trailing time/question words and a leading admin prefix (quận/huyện/…) by
# WINDOW, never by per-word filtering — so multi-word names whose syllables
# collide with filler stay intact (Cần *Giờ*, *Côn* Đảo, *Bảo* Lộc, *Mai* Châu).
# (folded, ascii) — order matters: longest lead-in first.
_CITY_LEADS = ("du bao thoi tiet", "thoi tiet", "du bao", "nhiet do",
               "chat luong khong khi", "khong khi", "ngoai troi", "troi")
_CITY_CONNECTORS = ("o", "tai", "khu vuc", "vung")
_CITY_TRAILS = ("co mua khong", "sap mua khong", "co mua hay khong",
                "khi nao mua", "luc nao mua", "co mua", "sap mua", "mua khong",
                "nhu the nao", "the nao", "ra sao", "hom nay", "ngay mai",
                "bay gio", "hien tai", "hien gio", "luc nay", "dang", "the",
                "vay", "khong", "mua", "a", "nhi", "voi", "di")
_CITY_ADMIN_PREFIX = ("thanh pho", "tp", "tinh", "quan", "huyen",
                      "thi xa", "thi tran", "phuong", "xa")


def _extract_weather_city(raw: str) -> str:
    """Isolate a VN place name from a weather query for geocoding — strips
    lead-ins/connectors/trailing time-words and a leading admin prefix by token
    window, WITHOUT touching middle syllables. Returns '' if nothing remains."""
    import re
    from services.ha_client import _fold_diacritics
    words = [w for w in re.split(r"\s+", raw.strip()) if w]
    if not words:
        return ""
    fw = [_fold_diacritics(w).replace("đ", "d").strip(".,!?;:()\"'").lower() for w in words]
    lo, hi = 0, len(words)
    changed = True
    while changed and lo < hi:  # strip leading weather lead-ins / connectors
        changed = False
        rest = " ".join(fw[lo:hi])
        for L in _CITY_LEADS:
            if rest == L or rest.startswith(L + " "):
                lo += len(L.split()); changed = True; break
        if not changed and fw[lo] in _CITY_CONNECTORS:
            lo += 1; changed = True
    changed = True
    while changed and lo < hi:  # strip trailing time/question words
        changed = False
        rest = " ".join(fw[lo:hi])
        for T in _CITY_TRAILS:
            if rest == T or rest.endswith(" " + T):
                hi -= len(T.split()); changed = True; break
    if lo < hi:  # strip a leading admin prefix (GeoNames stores bare names)
        rest = " ".join(fw[lo:hi])
        for P in _CITY_ADMIN_PREFIX:
            if rest != P and rest.startswith(P + " "):
                lo += len(P.split()); break
    return " ".join(words[lo:hi]).strip(" ,.?!")


def _clean_weather_text(s: str) -> str:
    """Restore Vietnamese diacritics on the geocoding-MCP weather labels so the
    answer reads naturally (the tool emits ASCII labels)."""
    for a, b in (("Thoi tiet", "Thời tiết"), ("Nhiet do", "Nhiệt độ"),
                 ("cam giac", "cảm giác"), ("Do am", "Độ ẩm"), ("Gio:", "Gió:"),
                 ("May:", "Mây:"), ("Huong gio", "Hướng gió"), ("Tam nhin", "Tầm nhìn"),
                 ("Ap suat", "Áp suất"), ("Luong mua", "Lượng mưa")):
        s = s.replace(a, b)
    return s.strip()


_WEATHER_KW = ("thoi tiet", "du bao thoi tiet", "ngoai troi", "troi co",
               "troi hom nay", "troi the nao", "chat luong khong khi", "khong khi",
               "aqi", "bui min", "pm2", "pm10", "tia uv", "chi so uv",
               "nhiet do ngoai", "co mua khong", "sap mua", "co nang khong")
# Common words to ignore when checking whether a weather query names ANOTHER
# place (a leftover unknown word → fall through to search instead of answering
# the user's own location).
_WEATHER_STOP = {
    "thoi", "tiet", "hom", "nay", "mai", "qua", "the", "nao", "bao", "nhieu", "co",
    "khong", "nhu", "gi", "la", "o", "tai", "ngoai", "troi", "hien", "bay", "gio",
    "sang", "chieu", "toi", "du", "chi", "so", "uv", "aqi", "bui", "min", "pm2",
    "pm10", "khi", "chat", "luong", "nhiet", "do", "am", "mua", "nang", "day", "va",
    "cho", "minh", "anh", "em", "a", "ngay", "tuan", "ban", "oi", "voi", "di", "con",
    "nong", "lanh", "mat", "dep", "xau", "muc", "cua", "nhi", "bi", "se", "dang", "ra",
}


# Trạng thái on/off → chữ tiếng Việt (đọc bằng giọng nói, không ký tự).
_STATE_VI = {
    "on": "đang bật", "off": "đang tắt",
    "open": "đang mở", "opening": "đang mở", "closed": "đang đóng", "closing": "đang đóng",
    "locked": "đang khóa", "unlocked": "đang mở khóa",
    "heat": "đang sưởi", "cool": "đang làm mát", "dry": "đang hút ẩm", "fan_only": "đang quạt gió",
    "playing": "đang phát", "paused": "đang tạm dừng",
}


def _ha_local_status(messages: list[dict[str, Any]]) -> str | None:
    """Trả lời câu hỏi TRẠNG THÁI on/off của thiết bị ("trạng thái đèn phòng học",
    "đèn ngủ bật chưa") bằng cách đọc state THẬT từ registry — tức thì, không qua
    model. BẢO THỦ: chỉ trả khi khớp đúng MỘT entity (theo tên, hoặc noun thiết bị +
    khu vực); không rõ → None để model lo, nên không bao giờ nói sai."""
    import re as _re
    last_user = -1
    for i, m in enumerate(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            last_user = i
    if last_user < 0:
        return None
    for m in messages[last_user + 1:]:
        if isinstance(m, dict) and m.get("role") in ("tool", "assistant"):
            return None
    try:
        from services.ha_client import (
            _fold_diacritics, get_states, get_exposed_entity_ids, get_ha_area_index,
        )
    except Exception:
        return None
    toks = _re.sub(r"[^\w\s]", " ", _fold_diacritics(str(_extract_last_user_text(messages) or ""))).split()
    if not toks:
        return None
    flat = " ".join(toks)
    # Phải là câu HỎI trạng thái (lệnh điều khiển đã được _ha_local_intent xử lý trước).
    has_q = ("trang thai" in flat or "tinh trang" in flat or
             (any(v in toks for v in ("bat", "tat", "mo", "dong", "khoa")) and
              any(q in toks for q in ("chua", "khong"))))
    if not has_q:
        return None

    states = get_states(use_cache=True) or []
    exposed = get_exposed_entity_ids(use_cache=True) or set()
    idx = get_ha_area_index()
    area_names = idx.get("area_names") or {}
    entity_area = idx.get("entity_area") or {}
    entity_aliases = idx.get("entity_aliases") or {}
    smap = {s.get("entity_id"): s for s in states}
    _DOMS = _LOCAL_CANON_DOMAINS + ("cover", "lock", "climate", "water_heater", "media_player")

    area = None
    for af, ao in area_names.items():
        if _find_sublist(toks, af.split()) >= 0:
            area = ao
            break

    # 1) khớp theo TÊN entity (friendly_name/alias), ưu tiên tên dài nhất.
    ent_by_name: dict[str, list[str]] = {}
    for s in states:
        eid = s.get("entity_id", "")
        if exposed and eid not in exposed:
            continue
        if (eid.split(".")[0] if "." in eid else "") not in _DOMS:
            continue
        orig = (s.get("attributes", {}) or {}).get("friendly_name", "")
        for nf in {_fold_diacritics(orig).strip()} | set(entity_aliases.get(eid, [])):
            if nf:
                ent_by_name.setdefault(nf, []).append(eid)

    target = None
    for nf in sorted(ent_by_name, key=lambda x: -len(x.split())):
        if _find_sublist(toks, nf.split()) >= 0:
            cands = ent_by_name[nf]
            if area:
                cands = [e for e in cands if entity_area.get(e) == area]
            if len(cands) == 1:
                target = cands[0]
            break

    # Khớp đúng 1 entity cụ thể → trả trạng thái của nó.
    if target:
        s = smap.get(target) or {}
        word = _STATE_VI.get(str(s.get("state")).strip().lower())
        if word:
            name = (s.get("attributes", {}) or {}).get("friendly_name", "") or target
            return f"{name} {word} ạ."

    # ── AGGREGATE: trạng thái CHUNG (cả nhóm / cả phòng / cả nhà) ──────────────
    _ON = {"on", "open", "playing", "heat", "cool", "dry", "fan_only", "unlocked", "home"}
    _LABEL = {"light": "đèn", "switch": "công tắc", "fan": "quạt", "cover": "rèm cửa",
              "lock": "khóa", "climate": "điều hòa", "water_heater": "bình nóng lạnh",
              "media_player": "thiết bị phát"}
    _ONOFF = {"light": ("đang bật", "đang tắt"), "switch": ("đang bật", "đang tắt"),
              "fan": ("đang bật", "đang tắt"), "cover": ("đang mở", "đang đóng"),
              "lock": ("đang mở khóa", "đang khóa"), "climate": ("đang bật", "đang tắt"),
              "water_heater": ("đang bật", "đang tắt"), "media_player": ("đang phát", "đang dừng")}

    def _is_on(st): return str(st).strip().lower() in _ON
    def _nm(s): return (s.get("attributes", {}) or {}).get("friendly_name", "") or s.get("entity_id", "")
    def _ents(domains, area_filter=None):
        out = []
        for s in states:
            eid = s.get("entity_id", "")
            if exposed and eid not in exposed:
                continue
            if (eid.split(".")[0] if "." in eid else "") not in domains:
                continue
            if area_filter and entity_area.get(eid) != area_filter:
                continue
            out.append(s)
        return out

    dom = None
    for noun, d in sorted(_LOCAL_DEVICE_CLASS.items(), key=lambda x: -len(x[0].split())):
        if _find_sublist(toks, noun.split()) >= 0:
            dom = d
            break

    # 2a) Một NHÓM thiết bị (+ khu vực tùy chọn): "trạng thái đèn", "trạng thái công tắc".
    if dom:
        ents = _ents((dom,), area)
        if ents:
            w_on, w_off = _ONOFF.get(dom, ("đang bật", "đang tắt"))
            lbl = _LABEL.get(dom, "thiết bị")
            scope = f" {area.lower()}" if area else ""
            on = [_nm(s) for s in ents if _is_on(s.get("state"))]
            off = [_nm(s) for s in ents if not _is_on(s.get("state"))]
            scope = f" {area.lower()}" if area else ""
            if on and off:
                return (f"{lbl.capitalize()}{scope}: {len(on)} cái {w_on} ({', '.join(on)}); "
                        f"{len(off)} cái {w_off} ({', '.join(off)}) ạ.")
            if on:
                return f"Tất cả {len(on)} {lbl}{scope} đều {w_on} ({', '.join(on)}) ạ."
            return f"Tất cả {len(off)} {lbl}{scope} đều {w_off} ạ."

    # 2b) KHU VỰC (nêu tên phòng, không nêu nhóm): liệt kê ĐẦY ĐỦ MỌI thiết bị +
    #     cảm biến exposed trong khu vực đó (thiết bị→bật/tắt, cảm biến→giá trị).
    if area:
        _AREA_DOMS = _DOMS + ("sensor", "binary_sensor", "vacuum", "humidifier")
        ents = [s for s in states
                if (not exposed or s.get("entity_id") in exposed)
                and (s.get("entity_id", "").split(".")[0]) in _AREA_DOMS
                and entity_area.get(s.get("entity_id")) == area]
        items = []
        for s in sorted(ents, key=lambda x: x.get("entity_id", "")):
            nm = _nm(s)
            stl = str(s.get("state")).strip().lower()
            w = _STATE_VI.get(stl)
            if w:
                items.append(f"{nm} {w}")
            elif stl not in ("", "unknown", "unavailable", "none"):
                unit = (s.get("attributes", {}) or {}).get("unit_of_measurement", "")
                disp = _re.sub(r"(\d)\.(\d)", r"\1,\2", str(s.get("state")))  # 79.92 → 79,92 (dấu phẩy VN)
                items.append(f"{nm} {disp}{unit}".rstrip())
        if items:
            return f"{area}: " + "; ".join(items) + " ạ."

    # 2c) CẢ NHÀ ("trạng thái nhà") → để MODEL tổng hợp rich (thiết bị + cảm biến +
    # điện + thời tiết + lịch); local khó gom đủ các nguồn ngoài (thời tiết/lịch).
    return None


def _ha_local_weather(
    messages: list[dict[str, Any]],
    *,
    keep_units: bool = False,
) -> str | None:
    """Answer weather questions from the AccuWeather (or any exposed weather.*)
    entity in HA — accurate for the user's location, no broken geocode, no model
    guessing. General → condition+temp+humidity(+rain); specific → AQI/UV/wind.

    keep_units=True: giữ °C/% (chat / AI text / agent).
    keep_units=False: văn xuôi TTS ("30 độ", "79 phần trăm") cho HA giọng nói.
    """
    last_user = -1
    for i, m in enumerate(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            last_user = i
    if last_user < 0:
        return None
    for m in messages[last_user + 1:]:
        if isinstance(m, dict) and m.get("role") in ("tool", "assistant"):
            return None
    try:
        from services.ha_client import _fold_diacritics, get_states, get_exposed_entity_ids
    except Exception:
        return None
    fd = _fold_diacritics(str(_extract_last_user_text(messages) or "")).replace("đ", "d")
    if not any(k in fd for k in _WEATHER_KW):
        return None

    states = get_states(use_cache=True) or []
    exposed = get_exposed_entity_ids(use_cache=True) or set()
    # Collect exposed weather entities (prefer AccuWeather), each with its folded
    # location name. Nothing hardcoded — works for any user's location(s).
    pool: list[tuple[dict, str, str, bool]] = []
    has_accu = False
    for s in states:
        eid = s.get("entity_id", "")
        if not eid.startswith("weather.") or (exposed and eid not in exposed):
            continue
        disp = (s.get("attributes", {}) or {}).get("friendly_name", "").replace("AccuWeather", "").strip()
        lf = _fold_diacritics(disp).replace("đ", "d").strip()
        is_accu = "accuweather" in eid
        has_accu = has_accu or is_accu
        pool.append((s, lf, disp, is_accu))
    if not pool:
        return None
    if has_accu:
        pool = [w for w in pool if w[3]]

    # Match the query to a configured location; else default to the first — unless
    # the query names some OTHER place (leftover unknown word) → None → search.
    we = loc = None
    for s, lf, disp, _ in pool:
        if lf and lf in fd:
            we, loc = s, disp
            break
    if we is None:
        loc_words = set()
        for _, lf, _, _ in pool:
            loc_words.update(lf.split())
        leftover = set(t for t in fd.split()
                       if t.isalpha() and len(t) >= 2 and t not in _WEATHER_STOP and t not in loc_words)
        if leftover:
            # Names another VN place → fetch its weather via the geocoding MCP
            # (Open-Meteo), so ANY province/city is covered without pre-adding it
            # to AccuWeather. Keep original diacritics for the geocoder.
            raw = str(_extract_last_user_text(messages) or "")
            city = _extract_weather_city(raw)
            if not city:
                return None
            # Câu hỏi "sắp mưa không" → MinuteCast (mưa 15' tới); còn lại → thời tiết.
            rain = any(k in fd for k in ("co mua", "sap mua", "mua khong",
                                         "con mua", "khi nao mua", "luc nao mua"))
            tool = "get_minutecast" if rain else "get_current_weather"
            try:
                from services.mcp_client import call_mcp_tool
                res = call_mcp_tool(tool, {"city": city})
            except Exception:
                res = None
            if res and str(res).strip():
                return _clean_weather_text(str(res))
            return None
        we, loc = pool[0][0], pool[0][2]
    a = we.get("attributes", {}) or {}
    prefix = we.get("entity_id", "").split(".", 1)[-1]
    loc = loc or "ngoài trời"
    sens = {s.get("entity_id", ""): s for s in states
            if s.get("entity_id", "").startswith(f"sensor.{prefix}_")}

    def _v(suffix):
        s = sens.get(f"sensor.{prefix}_{suffix}")
        if not s:
            return None
        val = s.get("state")
        if val is None or str(val).strip().lower() in ("unknown", "unavailable", "none", ""):
            return None
        unit = (s.get("attributes", {}) or {}).get("unit_of_measurement", "") or ""
        return f"{val} {unit}".strip()

    # Specific aspects override the general report.
    if any(k in fd for k in ("khong khi", "aqi", "bui min", "pm2", "pm10")):
        pm25, pm10 = _v("pm2_5"), _v("pm10")
        if pm25 or pm10:
            bits = []
            if pm25:
                bits.append(f"PM2.5 {pm25}")
            if pm10:
                bits.append(f"PM10 {pm10}")
            return f"Chất lượng không khí {loc}: " + ", ".join(bits) + "."
    if "uv" in fd:
        s = sens.get(f"sensor.{prefix}_uv_index")
        uv = s.get("state") if s else None
        if uv not in (None, "unknown", "unavailable", "", "none"):
            return f"Chỉ số UV {loc} hiện {uv}."
    if any(k in fd for k in ("co mua", "sap mua")):
        mc = _v("minutecast_precipitation")
        if mc:
            return f"{loc}: {mc}."

    # General weather report.
    # keep_units=True (chat / AI text / agent): giữ °C, % — không đổi sang văn xuôi TTS.
    # keep_units=False (HA Assist giọng nói / default): "30 độ", "79 phần trăm".
    def _r(x):
        try:
            return str(round(float(x)))
        except (TypeError, ValueError):
            return str(x)
    cond = _WEATHER_VI.get(str(we.get("state") or ""), we.get("state") or "")
    temp = a.get("temperature")
    hum = a.get("humidity")
    out = f"Thời tiết {loc} hiện {cond}" if cond else f"Thời tiết {loc}"
    if temp is not None:
        out += f", khoảng {_r(temp)}°C" if keep_units else f", khoảng {_r(temp)} độ"
    if hum is not None:
        out += f", độ ẩm {_r(hum)}%" if keep_units else f", độ ẩm {_r(hum)} phần trăm"
    out = out.rstrip(", ") + "."
    uv_s = sens.get(f"sensor.{prefix}_uv_index")
    uv = uv_s.get("state") if uv_s else None
    try:
        out += f" Chỉ số tia cực tím ở mức {_uv_cat(float(uv))}." if uv not in (None, "unknown", "unavailable", "", "none") else ""
    except (TypeError, ValueError):
        pass
    pm25 = _v("pm2_5")
    if pm25:
        try:
            out += f" Chất lượng không khí ở mức {_pm25_cat(float(str(pm25).split()[0].replace(',', '.')))}."
        except (ValueError, IndexError):
            pass
    mc = _v("minutecast_precipitation")
    if mc and "mua" not in mc.lower():  # only append the "no rain" hint, keep it short
        out += f" {mc}."
    # Phase 4 (native weather): cảnh báo dông/mưa rất to/gió giật 12h tới cho
    # vị trí nhà (Open-Meteo, cache 15') — chỉ thêm khi CÓ gì đáng báo.
    try:
        from services.weather_extras import storm_warning
        _w = storm_warning()
        if _w:
            out += f" {_w}"
    except Exception:
        pass
    return out.rstrip()


_LUNAR_KW = ("am lich", "duong lich", "lich am", "lich duong", "can chi",
             "hoang dao", "ngay am", "ngay duong", "doi ngay", "qui doi", "quy doi", "mung",
             "lich hom nay", "lich ngay mai", "xem lich", "coi lich", "tiet khi",
             "ngay bao nhieu am", "hom nay ngay gi")
# "Việc nên làm / nên tránh / ngày tốt-xấu / trực" → thập nhị trực fast-answer.
_ACTIVITY_KW = ("viec nen lam", "nen lam gi", "nen tranh", "viec kieng", "kieng ky",
                "kieng gi", "ngay tot", "ngay xau", "tot xau", "co nen", "hop lam gi",
                "ngay dep", "truc gi", "lam viec gi", "nen kieng", "co tot khong",
                "co dep khong", "lam gi tot")


def _ha_local_lunar(messages: list[dict[str, Any]]) -> str | None:
    """Answer âm/dương-lịch questions by computing locally (Hồ Ngọc Đức) — accurate
    & instant, no MCP/model. Handles 'âm lịch hôm nay', solar→lunar and lunar→solar
    date conversion. Returns text, or None to fall through."""
    import re as _re
    last_user = -1
    for i, m in enumerate(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            last_user = i
    if last_user < 0:
        return None
    for m in messages[last_user + 1:]:
        if isinstance(m, dict) and m.get("role") in ("tool", "assistant"):
            return None
    try:
        from services.ha_client import _fold_diacritics
        from services import lunar_vn as L
    except Exception:
        return None
    raw = str(_extract_last_user_text(messages) or "")
    f = _fold_diacritics(raw)
    fd = f.replace("đ", "d")

    # Time-only fast-path: "mấy giờ", "bây giờ", "giờ rồi" → trả giờ ngay.
    if ("may gio" in fd or "bay gio" in fd or "gio roi" in fd) and "hoang dao" not in fd and "gio tot" not in fd:
        import datetime as _dt
        from zoneinfo import ZoneInfo as _Z
        now = _dt.datetime.now(_Z("Asia/Ho_Chi_Minh"))
        return (f"Bây giờ là {now.hour} giờ {now.minute:02d} phút, "
                f"{L._weekday_vn(now.day, now.month, now.year)}, "
                f"ngày {now.day} tháng {now.month} năm {now.year} dương lịch.")

    # Weekday fast-path: "thứ mấy" — của 1 ngày CỤ THỂ (D/M/Y, có thể âm lịch)
    # hoặc hôm nay / ngày mai / hôm qua → trả thứ ngay.
    if _re.search(r"thu\s*may", fd):
        _wd = _mwd = _ywd = None
        _lunar_in = False
        _m2 = _re.search(r"(ngay|mung|mong)\s+(\d{1,2})\s+thang\s+(\d{1,2})(?:\s+nam\s+(\d{4}))?", fd)
        _m1 = _re.search(r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?:\s*[/\-.]\s*(\d{2,4}))?", f)
        if _m2:
            _wd = int(_m2.group(2)); _mwd = int(_m2.group(3))
            _ywd = int(_m2.group(4)) if _m2.group(4) else L._today_vn()[2]
            _lunar_in = _m2.group(1) in ("mung", "mong") or bool(_re.search(r"\bam\b", fd))
        elif _m1:
            _wd = int(_m1.group(1)); _mwd = int(_m1.group(2))
            _ywd = int(_m1.group(3)) if _m1.group(3) else L._today_vn()[2]
            if _ywd < 100:
                _ywd += 2000
            _lunar_in = bool(_re.search(r"\bam\b", fd))
        if _wd is not None and 1 <= _mwd <= 12 and 1 <= _wd <= 31:
            if _lunar_in:
                _sd, _sm, _sy = L.lunar_to_solar(_wd, _mwd, _ywd)
                if (_sd, _sm, _sy) == (0, 0, 0):
                    return None
                _wd, _mwd, _ywd = _sd, _sm, _sy
            try:
                return f"Ngày {_wd} tháng {_mwd} năm {_ywd} dương lịch là {L._weekday_vn(_wd, _mwd, _ywd)}."
            except Exception:
                return None
        # Không có ngày cụ thể → hôm nay / mai / mốt / hôm qua / hôm kia.
        # Bắt cả dạng nói tắt "mai thứ mấy" (không có chữ "ngày") — trước đây
        # chỉ khớp "ngay mai" nên câu hỏi về MAI bị trả nhầm thành hôm nay.
        _dd, _mm, _yy = L._today_vn()
        _off, _lbl = 0, "Hôm nay"
        if "hom kia" in fd:
            _off, _lbl = -2, "Hôm kia"
        elif "hom qua" in fd:
            _off, _lbl = -1, "Hôm qua"
        elif "ngay kia" in fd or "ngay mot" in fd or "mai mot" in fd or _re.search(r"\bmot\b", fd):
            _off, _lbl = 2, "Ngày mốt"
        elif "ngay mai" in fd or _re.search(r"\bmai\b", fd):
            _off, _lbl = 1, "Ngày mai"
        if _off:
            from datetime import date as _date, timedelta as _td
            _t = _date(_yy, _mm, _dd) + _td(days=_off)
            _dd, _mm, _yy = _t.day, _t.month, _t.year
        return f"{_lbl} là {L._weekday_vn(_dd, _mm, _yy)}, ngày {_dd} tháng {_mm} năm {_yy} dương lịch."

    is_activity = any(k in fd for k in _ACTIVITY_KW)
    if not is_activity and not any(k in fd for k in _LUNAR_KW) and not (
            ("hom nay" in fd or "ngay mai" in fd or "hom qua" in fd)
            and ("ngay gi" in fd or "ngay bao nhieu" in fd or "ngay may" in fd)):
        return None

    today = L._today_vn()

    # Parse a date. Word-form "(ngày|mùng) D tháng M [năm Y]" first, else "D/M[/Y]".
    d = mth = yy = None
    lunar_input = False
    m2 = _re.search(r"(ngay|mung|mong)\s+(\d{1,2})\s+thang\s+(\d{1,2})(?:\s+nam\s+(\d{4}))?", fd)
    m1 = _re.search(r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?:\s*[/\-.]\s*(\d{2,4}))?", f)
    ask_solar_out = any(p in fd for p in ("sang duong", "ra duong", "duong lich la", "duong lich ngay",
                                          "la ngay nao duong", "ngay may duong", "duong la ngay", "ngay duong cua"))
    ask_lunar_out = any(p in fd for p in ("am lich la", "la am lich", "sang am", "ra am", "am lich ngay",
                                          "doi sang am", "am lich ngay nao", "la ngay nao am", "ngay am la", "ngay am cua"))
    if m2:
        kw = m2.group(1); d = int(m2.group(2)); mth = int(m2.group(3))
        yy = int(m2.group(4)) if m2.group(4) else None
        if kw in ("mung", "mong"):
            lunar_input = True                       # "mùng" is always a lunar day
        elif ask_solar_out:
            lunar_input = True                       # want dương out → input is âm
        elif ask_lunar_out:
            lunar_input = False                      # want âm out → input is dương
        else:
            lunar_input = bool(_re.search(r"\bam\b", fd))                 # "âm" attached → lunar date
    elif m1:
        d = int(m1.group(1)); mth = int(m1.group(2))
        yy = int(m1.group(3)) if m1.group(3) else None
        if yy is not None and yy < 100:
            yy += 2000
        # Slash-form D/M/Y is conventionally a SOLAR date, unless they explicitly
        # say it's âm and ask for dương out.
        lunar_input = ask_solar_out

    if d is None:
        # No explicit date → today (or tomorrow/yesterday).
        dd, mm, y = today
        if "ngay mai" in fd:
            from datetime import date, timedelta
            t = date(y, mm, dd) + timedelta(days=1); dd, mm, y = t.day, t.month, t.year
        elif "hom qua" in fd:
            from datetime import date, timedelta
            t = date(y, mm, dd) - timedelta(days=1); dd, mm, y = t.day, t.month, t.year
        dw = ("Hôm nay" if (dd, mm, y) == today else
              "Ngày mai" if "ngay mai" in fd else
              "Hôm qua" if "hom qua" in fd else "")
        if is_activity:
            txt = L.describe_activities(dd, mm, y)
            return (f"{dw}, " + txt[0].lower() + txt[1:]) if dw else txt
        return (f"{dw} là " if dw else "") + L.describe_solar(dd, mm, y)

    if not (1 <= mth <= 12 and 1 <= d <= 31):
        return None
    if is_activity:
        # Việc nên làm of an explicit date — resolve to its solar date first.
        if lunar_input:
            sd, sm, sy = L.lunar_to_solar(d, mth, yy or today[2])
            if (sd, sm, sy) == (0, 0, 0):
                return None
        else:
            sd, sm, sy = d, mth, yy or today[2]
        return L.describe_activities(sd, sm, sy)
    if lunar_input:
        return L.describe_lunar(d, mth, yy or today[2])
    return L.describe_solar(d, mth, yy or today[2])


def _is_voice_request(messages: list[dict[str, Any]]) -> bool:
    """Request từ Home Assistant → nhiều khả năng câu trả lời qua TTS. Nhận diện
    qua system prompt đặc trưng của HA (không hardcode theo user)."""
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "system":
            c = m.get("content")
            txt = c if isinstance(c, str) else (str(c) if c else "")
            low = txt.lower()
            if "home assistant" in low or "smart home" in low:
                return True
    return False


def _wants_verbalize(model: str | None, messages: list[dict[str, Any]]) -> bool:
    """Có nên đổi câu trả lời sang VĂN XUÔI (cho TTS) không.

    - tên chứa ':tts'/':voice'/':vanxuoi'  -> CÓ (ép văn xuôi).
    - tên chứa ':raw'/':text'/':chat'  -> KHÔNG (giữ ký tự, vd combo riêng cho pipeline gõ chữ).
    - **combo** (vd ``AI text`` = [cx/auto:text, gma/auto:text]): nếu MỌI bước
      có marker giữ ký tự (:text/:raw/…) và KHÔNG có :tts → KHÔNG verbalize.
      (Trước đây chỉ nhìn tên combo ``AI text`` — thiếu ``:text`` → vẫn verbalize
      dù sub-model đã gắn :text.)
    - không có dấu hiệu             -> mặc định: LUÔN LÀ CÓ (để đảm bảo HA đọc được dù user có đổi system prompt).
    """
    import re
    m = (model or "").lower()
    if re.search(r"[:#](tts|voice|vanxuoi)\b", m):
        return True
    if re.search(r"[:#](raw|text|chat|kytu|symbol)\b", m):
        return False
    # Combo Code (pipeline bố-con) = OUTPUT LÀ CODE → phải giữ ký tự literal,
    # KHÔNG verbalize (nếu không '%' bị đổi thành 'phần trăm', code không chạy).
    # Model TTS/voice thường khác vẫn verbalize như cũ.
    try:
        from services.config import config as _c
        data = _c.data if hasattr(_c, "data") else _c.get()
        if _strip_marker(model) in (data.get("pipeline_models") or {}):
            return False
        # Combo models: suy ra từ TỪNG BƯỚC (cx/auto:text…), không chỉ tên combo.
        combo_keep = _combo_wants_keep_literal(model, data.get("combo_models") or {})
        if combo_keep is not None:
            return not combo_keep  # keep_literal True → verbalize False
    except Exception:
        pass
    return True


def _combo_wants_keep_literal(model: str | None, combos: dict) -> bool | None:
    """None = không phải combo / không rõ. True = mọi bước :text/:raw… → giữ ký tự.
    False = combo có :tts hoặc bước không marker giữ ký tự → verbalize (mặc định TTS)."""
    import re
    if not model or not isinstance(combos, dict) or not combos:
        return None
    name = str(model).strip().lower()
    steps = None
    for k, v in combos.items():
        if str(k).strip().lower() == name:
            steps = v
            break
    if not isinstance(steps, list) or not steps:
        return None
    keep_re = re.compile(r"[:#](raw|text|chat|kytu|symbol)\b", re.I)
    tts_re = re.compile(r"[:#](tts|voice|vanxuoi)\b", re.I)
    any_step = False
    for s in steps:
        ss = str(s or "")
        if not ss.strip():
            continue
        any_step = True
        if tts_re.search(ss):
            return False  # có bước TTS → verbalize
        if not keep_re.search(ss):
            return False  # bước không :text → không coi combo "giữ ký tự"
    if not any_step:
        return None
    return True


def _strip_marker(model: str | None) -> str:
    """Cắt hậu tố marker (':tts'/':text'/'#raw'...) khỏi tên model để DISPATCH
    đúng model thật. Vd 'cx/auto:text' -> dispatch 'cx/auto' (vẫn nhận biết để
    giữ ký tự). Combo tên có chữ 'Text' (cách) thì giữ nguyên, không cắt."""
    if not model:
        return model or ""
    return re.sub(r"[:#](tts|voice|vanxuoi|raw|text|chat|kytu|symbol)\b", "",
                  model, flags=re.IGNORECASE).strip()


def _is_generation_task(body: dict[str, Any], messages: list[dict[str, Any]]) -> bool:
    """True nếu request là task SINH nội dung (vd HA `ai_task.generate_data`) chứ
    KHÔNG phải câu hỏi giọng nói. Khi đó BỎ QUA mọi fast-path nội bộ (lunar/status/
    query/intent/confirm) — vì prompt sinh nội dung thường chứa "âm lịch"/"trạng thái"
    nhưng thực ra cần model VIẾT ra nội dung (vd JSON title/message), nếu fast-path
    chặn sẽ trả nhầm văn bản canned. Đo trên TIN NHẮN USER cuối (không tính system,
    vì system prompt HA cũng dài) → voice query ngắn, task sinh nội dung dài/đòi format."""
    try:
        if body.get("response_format"):
            return True
        txt = str(_extract_last_user_text(messages) or "")
    except Exception:
        return False
    if len(txt) > 240:                       # voice query gần như không bao giờ dài vậy
        return True
    try:
        from services.ha_client import _fold_diacritics
        fd = _fold_diacritics(txt)
    except Exception:
        fd = txt.lower()
    gen_kw = ("tra ve json", "chi tra ve", "raw json", "json thuan", "dinh dang json",
              "viet mot", "viet thong bao", "soan thong bao", "structure", "instructions:")
    return any(k in fd for k in gen_kw)


def _exec_local_tool_calls(local_tcs: list[dict[str, Any]]) -> None:
    """Thực thi tool_call đã resolve cục bộ — HassTurnOn/Off (kèm _eids) gọi
    call_service thẳng tới HA từng entity, còn lại chạy qua MCP tool — song
    song; raise nếu có lệnh lỗi để caller quyết định fallback."""
    import concurrent.futures
    import json
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(local_tcs)) as pool:
        futures = []
        for tc in local_tcs:
            args_str = tc.get("function", {}).get("arguments", "{}")
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except Exception:
                args = {}
            tool_name = tc.get("function", {}).get("name", "")
            if tool_name in ("HassTurnOn", "HassTurnOff") and "_eids" in args:
                from services.ha_client import call_service
                svc = "turn_on" if tool_name == "HassTurnOn" else "turn_off"
                for eid in args["_eids"]:
                    dom = eid.split(".")[0]
                    futures.append(pool.submit(call_service, dom, svc, {"entity_id": eid}))
            else:
                futures.append(pool.submit(_execute_mcp_tool, tool_name, args))
        for f in concurrent.futures.as_completed(futures, timeout=10):
            f.result()


def ha_local_fastpath_answer(user_text: str) -> tuple[str | None, bool]:
    """Fast-path HA cho kênh chat bot (Telegram/Zalo — orchestrator gọi TRƯỚC
    khi đụng model): chạy trên MỘT câu người dùng, KHÔNG cần provider AI nào.
    Lệnh điều khiển rõ ràng được THỰC THI ngay (call_service thẳng tới HA);
    câu hỏi giá trị cảm biến / trạng thái on-off / âm lịch / thời tiết trả lời
    từ dữ liệu thật. Trả (văn mẫu, đã_điều_khiển); (None, False) khi không
    fast-path nào khớp → caller đi đường model như cũ."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": str(user_text or "")}]
    try:
        level = _ha_local_level(messages)
    except Exception as exc:
        level = None
        logger.warning({"event": "ha_local_level_error", "error": str(exc)[:150]})
    if level:
        return level, True
    try:
        tcs = _ha_local_intent(messages)
    except Exception as exc:
        tcs = None
        logger.warning({"event": "ha_local_intent_error", "error": str(exc)[:150]})
    if tcs:
        try:
            _exec_local_tool_calls(tcs)
        except Exception as exc:
            # Lệnh không chạy được (HA down…) → nhả cho đường model xử lý tiếp.
            logger.warning({"event": "ha_canonical_exec_failed", "error": str(exc)})
        else:
            return "Đã thực hiện xong lệnh điều khiển thiết bị.", True
    for fn in (_ha_local_query, _ha_local_status, _ha_local_lunar):
        try:
            r = fn(messages)
        except Exception as exc:
            r = None
            logger.warning({"event": "ha_bot_fastpath_error",
                            "fn": fn.__name__, "error": str(exc)[:150]})
        if r and isinstance(r, str) and r.strip():
            return r.strip(), False
    # Bot chat (Tele/Zalo): giữ °C/% — HA Assist giọng nói dùng RT1 + :tts riêng.
    try:
        r = _ha_local_weather(messages, keep_units=True)
    except Exception as exc:
        r = None
        logger.warning({"event": "ha_bot_fastpath_error",
                        "fn": "_ha_local_weather", "error": str(exc)[:150]})
    if r and isinstance(r, str) and r.strip():
        return r.strip(), False
    return None, False


def _collect_fastpath_facts(messages: list[dict[str, Any]]) -> str:
    """Run the READ-ONLY HA fast-paths and return their facts joined, for the
    agent to phrase naturally. Only pulls data (date/lunar, weather, sensor &
    device status) — never the control/confirm fast-paths (those act on the
    home). Each helper returns None when it doesn't apply, so this stays cheap.

    Weather/sensor facts dùng keep_units=True (giữ °C/%) — agent chat/Tele/Zalo
    gõ chữ, không phải TTS Assist.
    """
    facts: list[str] = []
    for fn in (_ha_local_lunar, _ha_local_status, _ha_local_query):
        try:
            r = fn(messages)
        except Exception:
            r = None
        if r and isinstance(r, str) and r.strip():
            facts.append(r.strip())
    try:
        r = _ha_local_weather(messages, keep_units=True)
    except Exception:
        r = None
    if r and isinstance(r, str) and r.strip():
        facts.append(r.strip())
    # De-dup while preserving order (lunar + status can overlap on dates).
    seen: set[str] = set()
    uniq = [f for f in facts if not (f in seen or seen.add(f))]
    return "\n".join(uniq)


_err_notify_last: dict[str, float] = {}
_ERR_NOTIFY_DEDUP = 30.0  # suppress the same error within this window


def notify_error_tg(where: str, model: str, error: str, user_text: str = "") -> None:
    """Best-effort push of a failure to the admin Telegram chats so the user can
    debug (không cần lục log). Deduped so a burst of the same error doesn't spam.
    Gated by config `telegram_notify_errors` (default on)."""
    try:
        if not config.get().get("telegram_notify_errors", True):
            return
        sig = f"{where}|{model}|{(error or '')[:80]}"
        now = time.time()
        if now - _err_notify_last.get(sig, 0.0) < _ERR_NOTIFY_DEDUP:
            return
        _err_notify_last[sig] = now
        q = (user_text or "").strip().replace("\n", " ")
        if len(q) > 220:
            q = q[:220] + "…"
        try:
            from services.privacy_gate import scrub_for_log
            q = scrub_for_log(q)
            error = scrub_for_log(error or "")
        except Exception:
            pass
        msg = ("⚠️ chatgpt2api LỖI\n"
               f"• Chỗ: {where}\n"
               f"• Model/combo: {model}\n"
               f"• Lỗi: {(error or '(không rõ)')[:900]}")
        if q:
            msg += f"\n• Câu hỏi: {q}"
        from services.notifier import notify_admin
        notify_admin(msg)
    except Exception:
        pass


# --- Branch routing toàn cục --------------------------------------------------
# agent_branches (Settings → Telegram/Agent) là "setting việc" DUY NHẤT của chủ
# nhà: Vẽ/tạo ảnh, Phân tích ảnh, Tạo nhạc, Tạo video, Viết/sửa code (+ Kiểm
# duyệt code). Lớp này soi TIN NHẮN USER CUỐI của mọi request /v1/chat/completions
# — tab chat, HA, Telegram, app ngoài… — việc thuộc nhánh nào thì đổi sang model
# nhánh đó; CHAT THƯỜNG giữ nguyên model client chọn ("AI Model trong tab chat").
# Tắt toàn bộ bằng config `branch_routing_global=false`.

_BRANCH_TEXT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("image_gen", ("ve anh", "tao anh", "ve hinh", "tao hinh", "ve cho", "ve giup",
                   "ve mot", "ve 1 ", "ve lai", "tao logo", "ve logo", "tao poster",
                   "tao icon", "tao hinh anh", "generate image", "draw a ")),
    ("video_gen", ("tao video", "lam video", "tao clip", "lam clip", "tao doan video",
                   "tao 1 video", "tao mot video", "generate video")),
    ("music_gen", ("tao nhac", "tao bai hat", "tao ban nhac", "sang tac nhac",
                   "sang tac bai hat", "viet bai hat", "lam bai hat", "lam nhac",
                   "compose music", "make a song")),
    ("code",      ("viet code", "sua code", "viet chuong trinh", "viet ham",
                   "viet script", "viet doan code", "code giup", "sua loi code",
                   "fix bug", "fix code", "debug", "refactor", "lap trinh",
                   "viet function", "toi uu code", "review code", "kiem tra code",
                   "sua file", "viet file", "viet ung dung", "write code")),
)


def _last_user_has_images(messages: list[dict[str, Any]]) -> bool:
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):
                return any(isinstance(p, dict) and str(p.get("type") or "") in
                           ("image_url", "input_image", "image") for p in c)
            return False
    return False


def _detect_branch(folded: str, has_images: bool) -> str | None:
    """Loại việc của câu (đã bỏ dấu, lowercase) → tên nhánh, None = chat thường.
    Ảnh đính kèm không kèm từ khóa vẽ = Phân tích ảnh (vision)."""
    for branch, kws in _BRANCH_TEXT_KEYWORDS:
        if any(k in folded for k in kws):
            return branch
    if has_images:
        return "vision"
    return None


def _branch_code_review(code_model: str, reviewer: str,
                        messages: list[dict[str, Any]],
                        body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]] | None:
    """Nhánh code có Kiểm duyệt: con viết → bố soi → chưa đạt thì sửa (≤2 vòng).
    Gọi đệ quy qua _handle_main (cờ _branch_inner chặn lặp) nên model đơn hay
    combo đều chạy được. Trả None = rơi về flow thường (lỗi sẽ báo đúng đường)."""
    def _call(model_id: str, msgs: list[dict[str, Any]]) -> str:
        sub = dict(body)
        sub.pop("tools", None)
        sub.pop("tool_choice", None)
        sub.update({"model": model_id, "messages": msgs, "stream": False,
                    "_branch_inner": True})
        return _pipeline_extract_content(_handle_main(sub)).strip()

    request = _last_user_text(messages)
    try:
        code = _call(code_model, list(messages))
    except Exception as exc:
        logger.warning({"event": "branch_code_write_err", "model": code_model,
                        "error": str(exc)[:150]})
        return None
    if not code:
        return None
    for rnd in range(2):
        try:
            verdict = _call(reviewer, [{"role": "user",
                "content": _PIPELINE_REVIEWER_PROMPT.format(
                    request=request[:2000],
                    plan="(không có — yêu cầu trực tiếp từ chat)",
                    code=code[:12000])}])
        except Exception as exc:
            logger.warning({"event": "branch_review_err", "reviewer": reviewer,
                            "error": str(exc)[:150]})
            break
        up = verdict.upper()
        if "APPROVED" in up or "REVISE" not in up:
            logger.info({"event": "branch_review_ok", "round": rnd})
            break
        logger.info({"event": "branch_review_revise", "round": rnd,
                     "notes": verdict[:200]})
        try:
            new_code = _call(code_model, list(messages) + [{"role": "system",
                "content": _PIPELINE_REVISE_PROMPT.format(
                    feedback=verdict[:2000], code=code[:12000])}])
            if new_code:
                code = new_code
        except Exception as exc:
            logger.warning({"event": "branch_revise_err", "error": str(exc)[:150]})
            break
    if body.get("stream"):
        def _rv_stream(_c=code):
            cid = f"chatcmpl-{uuid.uuid4().hex}"
            ts = int(time.time())
            yield completion_chunk(code_model, {"role": "assistant", "content": _c}, None, cid, ts)
            yield completion_chunk(code_model, {}, "stop", cid, ts)
        return _rv_stream()
    return completion_response(model=code_model, content=code, messages=messages)


def _apply_branch_routing(body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]] | None:
    """Đổi body["model"] sang model nhánh khi request là việc chuyên biệt (trả
    None để flow thường tiếp tục); riêng nhánh code có reviewer thì chạy luôn
    vòng viết→soi→sửa và trả kết quả hoàn chỉnh."""
    if body.get("_branch_inner") or body.get("tools") or body.get("tool_choice"):
        return None
    if not config.get().get("branch_routing_global", True):
        return None
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    text = str(_extract_last_user_text(messages) or "")
    if not text.strip():
        return None
    try:
        from services.ha_client import _fold_diacritics
        folded = _fold_diacritics(text).lower()
    except Exception:
        folded = text.lower()
    branch = _detect_branch(folded, _last_user_has_images(messages))
    if not branch:
        return None
    # Client đã chủ động xin ảnh (model ảnh / modalities image) → giữ nguyên.
    if branch in ("image_gen", "vision") and is_image_chat_request(body):
        return None
    # Câu quản trị server (ssh/fs) phải giữ flow tool — không phải viết code.
    if branch == "code":
        try:
            from services.mcp_client import is_server_admin_query
            if is_server_admin_query(text, messages):
                return None
        except Exception:
            pass
    from services.agent.branches import branch_model
    # x_channel ('tg'|'zalo'|'zalop') → nhánh RIÊNG kênh đó, fallback nhánh chung.
    target = str(branch_model(branch, str(body.get("x_channel") or "")) or "").strip()
    if not target:
        return None
    cur = _strip_marker(str(body.get("model") or ""))
    if _strip_marker(target) != cur:
        body["model"] = target
        logger.info({"event": "branch_reroute", "branch": branch,
                     "from": cur, "to": target})
    if branch != "code":
        return None
    reviewer = _pipeline_reviewer_model()
    if not reviewer or body.get("response_format"):
        return None
    if backend_router.get_pipeline(_strip_marker(target)):
        return None  # pipeline Combo Code đã có tầng reviewer riêng bên trong
    return _branch_code_review(target, reviewer,
                               [m for m in messages if isinstance(m, dict)], body)


def _handle_main(body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    try:
        import json
        with open("/tmp/last_req.json", "w", encoding="utf-8") as f:
            f.write(json.dumps(body, ensure_ascii=False))
    except Exception:
        pass

    # Setting việc trên Tele áp dụng cho MỌI client — chat thường mới dùng model tab.
    try:
        _branch_result = _apply_branch_routing(body)
    except Exception as exc:
        _branch_result = None
        logger.warning({"event": "branch_route_error", "error": str(exc)[:150]})
    if _branch_result is not None:
        return _branch_result

    # Image chat requests always use existing DALL-E flow
    if is_image_chat_request(body):
        if body.get("stream"):
            return image_chat_events(body)
        return image_chat_response(body)

    model, messages, tools, tool_choice = text_chat_parts(body)

    # HA (trợ lý giọng nói) → câu trả lời được TTS đọc nên đổi ký tự/đơn vị sang
    # VĂN XUÔI ("°C"→"độ C", "20/06"→"ngày 20 tháng 6"...). Request thường (chat/
    # API) giữ nguyên ký tự cho dễ đọc bằng mắt.
    voice = _wants_verbalize(model, messages)
    model = _strip_marker(model)  # 'cx/auto:text' -> 'cx/auto' để dispatch đúng
    def _vz(t):
        return verbalize(t) if (voice and t) else t

    # Task sinh nội dung (ai_task.generate_data...) → bỏ qua MỌI fast-path nội bộ
    # để model thật sinh đúng output (tránh prompt chứa "âm lịch"/"trạng thái" bị
    # fast-path chặn rồi trả nhầm văn bản canned).
    # x_skip_fastpath: agent-originated conversational calls (Tiểu Vy). We do NOT
    # want the canned short-circuits (they read like a robot: "Hôm nay là Thứ
    # Sáu..."), but we DO want their accurate data. So instead of dropping the
    # fast-paths, we RUN the read-only ones and hand their facts to the model as
    # grounding context — the model phrases the answer naturally. The canned
    # returns are suppressed via _gen_task; control actions opt back in.
    _agent_mode = bool(body.get("x_skip_fastpath"))
    _gen_task = _is_generation_task(body, messages) or _agent_mode
    # Thread bị lọc thiếu nhóm homeassistant → KHÔNG thu thập facts từ HA
    # (trạng thái đèn/cảm biến…) — đây là kênh rò cuối cùng khiến thread bị
    # lọc vẫn "biết" đèn đang bật dù tool + context + HA tools đã chặn hết.
    if _agent_mode and not _thread_denies(body, "homeassistant"):
        try:
            _facts = _collect_fastpath_facts(messages)
        except Exception as _exc:
            _facts = ""
            logger.warning({"event": "agent_fastpath_facts_error", "error": str(_exc)[:120]})
        if _facts:
            logger.info({"event": "agent_fastpath_facts", "chars": len(_facts)})
            _insert = len(messages)
            for _i, _m in enumerate(messages):
                if isinstance(_m, dict) and _m.get("role") != "system":
                    _insert = _i
                    break
            messages.insert(_insert, {
                "role": "system",
                "content": ("Thông tin thực tế lấy từ hệ thống nhà (dùng để trả lời "
                            "TỰ NHIÊN, ấm áp — KHÔNG đọc lại nguyên văn máy móc):\n" + _facts)})
    elif _is_generation_task(body, messages):
        logger.info({"event": "ha_fastpath_skip_gen_task"})

    # HA RT2 fast-path: a control command already ran on the previous turn;
    # synthesize the confirmation and skip the second model round-trip (~2-8s).
    _ha_confirm = None if _gen_task else _vz(_ha_confirm_text(messages))
    if _ha_confirm is not None:
        logger.info({"event": "ha_confirm_shortcircuit", "text": _ha_confirm})
        if body.get("stream"):
            def _confirm_stream():
                cid = f"chatcmpl-{uuid.uuid4().hex}"
                ts = int(time.time())
                yield completion_chunk(model, {"role": "assistant", "content": _ha_confirm}, None, cid, ts)
                yield completion_chunk(model, {}, "stop", cid, ts)
            return _confirm_stream()
        return completion_response(model, _ha_confirm, messages=messages)

    # RT1 LEVEL fast-path: tốc độ quạt (%), quay/dừng quay quạt, độ sáng đèn (%) —
    # HA-native intent không set được mức này, nên tự call_service rồi trả xác nhận.
    try:
        _level = None if _gen_task else _vz(_ha_local_level(messages))
    except Exception as exc:
        _level = None
        logger.warning({"event": "ha_local_level_error", "error": str(exc)[:150]})
    if _level:
        logger.info({"event": "ha_local_level_answered", "text": _level})
        if body.get("stream"):
            def _level_stream():
                cid = f"chatcmpl-{uuid.uuid4().hex}"
                ts = int(time.time())
                yield completion_chunk(model, {"role": "assistant", "content": _level}, None, cid, ts)
                yield completion_chunk(model, {}, "stop", cid, ts)
            return _level_stream()
        return completion_response(model, _level, messages=messages)

    # RT1 fast-path: resolve a clear control command locally → emit the
    # HassTurnOn/Off tool_call WITHOUT the model (~ms vs ~5s codex). HA then
    # executes it. Unclear/ambiguous commands return None → normal model path.
    try:
        _local_tcs = None if _gen_task else _ha_local_intent(messages)
    except Exception as exc:
        _local_tcs = None
        logger.warning({"event": "ha_local_intent_error", "error": str(exc)[:150]})
    if _local_tcs:
        logger.info({"event": "ha_local_canonicalized", "n": len(_local_tcs),
                     "calls": [f'{t["function"]["name"]}:{t["function"]["arguments"]}'
                               for t in _local_tcs]})
                               
        if not body.get("_is_ha_request"):
            try:
                _exec_local_tool_calls(_local_tcs)
                final_text = "Đã thực hiện xong lệnh điều khiển thiết bị."
                if body.get("stream"):
                    def _stream_local():
                        cid = f"chatcmpl-{uuid.uuid4().hex}"
                        ts = int(time.time())
                        yield completion_chunk(model, {"role": "assistant", "content": final_text}, None, cid, ts)
                        yield completion_chunk(model, {}, "stop", cid, ts)
                    return _stream_local()
                return completion_response(model, final_text, messages=messages)
            except Exception as exc:
                logger.warning({"event": "ha_canonical_exec_failed", "error": str(exc)})
                # Fallthrough to normal model path if local execution fails

        if body.get("stream"):
            def _local_stream():
                cid = f"chatcmpl-{uuid.uuid4().hex}"
                ts = int(time.time())
                yield completion_chunk(model, {"role": "assistant", "content": None,
                                               "tool_calls": [{**tc, "index": i}
                                                              for i, tc in enumerate(_local_tcs)]},
                                       None, cid, ts)
                yield completion_chunk(model, {}, "tool_calls", cid, ts)
            return _local_stream()
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}", "object": "chat.completion",
            "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "finish_reason": "tool_calls",
                         "message": {"role": "assistant", "content": None,
                                     "tool_calls": _local_tcs}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    # RT1 read fast-path: a sensor-VALUE question (độ sáng/nhiệt độ/độ ẩm…) →
    # read the real sensor and answer directly, so the model can't fabricate a
    # value. Unrecognised / ambiguous → None → normal model path.
    try:
        _local_ans = None if _gen_task else _ha_local_query(messages)
    except Exception as exc:
        _local_ans = None
        logger.warning({"event": "ha_local_query_error", "error": str(exc)[:150]})
    _local_ans = _vz(_local_ans)
    if _local_ans:
        logger.info({"event": "ha_local_query_answered", "text": _local_ans})
        if body.get("stream"):
            def _query_stream():
                cid = f"chatcmpl-{uuid.uuid4().hex}"
                ts = int(time.time())
                yield completion_chunk(model, {"role": "assistant", "content": _local_ans}, None, cid, ts)
                yield completion_chunk(model, {}, "stop", cid, ts)
            return _query_stream()
        return completion_response(model, _local_ans, messages=messages)

    # RT1 status fast-path: câu hỏi TRẠNG THÁI thiết bị on/off ("trạng thái đèn
    # phòng học") → đọc state thật, trả tức thì (~ms) thay vì ~3s qua model.
    try:
        _status = None if _gen_task else _vz(_ha_local_status(messages))
    except Exception as exc:
        _status = None
        logger.warning({"event": "ha_local_status_error", "error": str(exc)[:150]})
    if _status:
        logger.info({"event": "ha_local_status_answered", "text": _status})
        if body.get("stream"):
            def _status_stream():
                cid = f"chatcmpl-{uuid.uuid4().hex}"
                ts = int(time.time())
                yield completion_chunk(model, {"role": "assistant", "content": _status}, None, cid, ts)
                yield completion_chunk(model, {}, "stop", cid, ts)
            return _status_stream()
        return completion_response(model, _status, messages=messages)

    # RT1 lunar fast-path: âm/dương-lịch questions computed locally (Hồ Ngọc Đức)
    # → accurate + instant, no MCP, no model guessing.
    try:
        _lunar = None if _gen_task else _ha_local_lunar(messages)
    except Exception as exc:
        _lunar = None
        logger.warning({"event": "ha_local_lunar_error", "error": str(exc)[:150]})
    _lunar = _vz(_lunar)
    if _lunar:
        logger.info({"event": "ha_local_lunar_answered", "text": _lunar[:80]})
        if body.get("stream"):
            def _lunar_stream():
                cid = f"chatcmpl-{uuid.uuid4().hex}"
                ts = int(time.time())
                yield completion_chunk(model, {"role": "assistant", "content": _lunar}, None, cid, ts)
                yield completion_chunk(model, {}, "stop", cid, ts)
            return _lunar_stream()
        return completion_response(model, _lunar, messages=messages)

    # RT1 weather fast-path: read the AccuWeather/HA weather entity directly →
    # accurate for the user's location (no broken geocode), no model guessing.
    # keep_units khi model :text / combo AI text (voice=False).
    try:
        _wea = None if _gen_task else _ha_local_weather(messages, keep_units=not voice)
    except Exception as exc:
        _wea = None
        logger.warning({"event": "ha_local_weather_error", "error": str(exc)[:150]})
    _wea = _vz(_wea)
    if _wea:
        logger.info({"event": "ha_local_weather_answered", "text": _wea[:80]})
        if body.get("stream"):
            def _weather_stream():
                cid = f"chatcmpl-{uuid.uuid4().hex}"
                ts = int(time.time())
                yield completion_chunk(model, {"role": "assistant", "content": _wea}, None, cid, ts)
                yield completion_chunk(model, {}, "stop", cid, ts)
            return _weather_stream()
        return completion_response(model, _wea, messages=messages)

    # Từ đây trở đi là luồng MODEL (codex/search/RAG…). Đánh dấu để handle() bọc
    # verbalize cho TTS (local fast-path ở trên đã tự verbalize qua _vz).
    body["_via_model"] = True

    # Detect vision request once — both combo and single-model paths use this
    # to skip MCP/HA tool injection (saves ~2.5s discovery + removes 60+ tools
    # that vision models have to scan before answering).
    is_vision_request = _messages_have_images(messages)

    # Detect HA intent on the PRISTINE user message before any search/HA
    # injection runs. Search results often contain phrases like "mở cửa"
    # (trading session jargon) or "đèn" (news headline) that would trip
    # the HA regex if we checked post-injection.
    # x_no_smart_home / x_allowed_groups: request từ thread bị lọc chức năng
    # (không có nhóm homeassistant) — TẮT hẳn tích hợp HA của pipeline cho
    # request này (inject context + HA tools), kẻo gateway tự phát hiện câu HA
    # rồi tự thực thi, vòng qua mặt bộ lọc của orchestrator.
    if _thread_denies(body, "homeassistant"):
        ha_query_pristine = False
    else:
        try:
            from services.ha_client import is_ha_query as _is_ha
            ha_query_pristine = _is_ha(messages)
        except Exception:
            ha_query_pristine = False
        
    original_user_text = _extract_last_user_text(messages)

    # effort=none cho 2 nhóm chỉ-gọi-tool-rồi-trả-thẳng, không cần reasoning:
    #  - lệnh điều khiển ("bật/tắt đèn…") → chỉ emit HassTurnOn.
    #  - câu realtime có MCP chuyên dụng (giá vàng/cổ phiếu…) → gọi tool rồi liệt
    #    kê kết quả. Cắt reasoning ở CẢ 2 lượt codex (decide + format) → nhanh.
    # Câu hỏi mở ("nhiệt độ", kiến thức) giữ reasoning mặc định cho câu trả tốt.
    try:
        from services.mcp_client import query_has_specialized_mcp as _qhs
        _no_reason = _is_smarthome_query(original_user_text) or _qhs(original_user_text)
    except Exception:
        _no_reason = _is_smarthome_query(original_user_text)
    if _no_reason and not body.get("_force_effort"):
        body["_force_effort"] = "none"

    # PRE-FETCH no-arg realtime tools (giá vàng/xăng/tỷ giá/âm lịch hôm nay): call
    # the tool server-side NOW and inject the result as context, so the model
    # answers in ONE round-trip instead of two (decide-tool → read-tool). The
    # MCP tool is then NOT shipped (prefetched=True) so it won't be re-called.
    if not body.get("_prefetched"):
        try:
            from services.mcp_client import prefetch_realtime_context
            _pf = prefetch_realtime_context(original_user_text)
        except Exception as exc:
            _pf = None
            logger.warning({"event": "prefetch_error", "error": str(exc)[:150]})
        if _pf:
            body["_prefetched"] = True
            _ctx = {"role": "system", "content":
                    "[DỮ LIỆU THỜI GIAN THỰC vừa tra cứu — trả lời ngắn gọn, chính xác "
                    "dựa trên dữ liệu này, KHÔNG gọi thêm công cụ]:\n" + _pf}
            _lu = max((i for i, m in enumerate(messages)
                       if isinstance(m, dict) and m.get("role") == "user"), default=len(messages) - 1)
            messages = messages[:_lu] + [_ctx] + messages[_lu:]
            logger.info({"event": "realtime_prefetched", "chars": len(_pf)})

    # PRE-FETCH KIẾN THỨC KHO (điện nước / y tế / giáo dục…): gọi ask_<kho>(question)
    # server-side → nhét kết quả vào ngữ cảnh, model chỉ FORMAT 1 lượt (nhanh, đặt
    # effort=none) thay vì codex tự suy luận trả lời dài. Đồng thời kho TỰ HỌC vì
    # kb_ask kích hoạt write-back. Tool không được ship lại (prefetched=True).
    if not body.get("_prefetched"):
        try:
            from services.mcp_client import prefetch_kb_context
            _kb = prefetch_kb_context(original_user_text)
        except Exception as exc:
            _kb = None
            logger.warning({"event": "kb_prefetch_error", "error": str(exc)[:150]})
        if _kb:
            body["_prefetched"] = True
            if not body.get("_force_effort"):
                body["_force_effort"] = "none"   # chỉ format → bỏ reasoning cho nhanh
            _ctx = {"role": "system", "content":
                    "[KIẾN THỨC vừa tra cứu từ kho tri thức — trả lời NGẮN GỌN, tự "
                    "nhiên, dễ nghe dựa trên thông tin này; bỏ phần thừa/lạc đề; "
                    "KHÔNG gọi thêm công cụ]:\n" + _kb}
            _lu = max((i for i, m in enumerate(messages)
                       if isinstance(m, dict) and m.get("role") == "user"), default=len(messages) - 1)
            messages = messages[:_lu] + [_ctx] + messages[_lu:]
            logger.info({"event": "kb_prefetched", "chars": len(_kb)})

    # Combo Code (pipeline bố-con) — config pipeline_models, TÁCH BIỆT hoàn
    # toàn với combo_models bên dưới.
    _pipeline = backend_router.get_pipeline(model)
    if _pipeline:
        return _run_pipeline_combo(model, _pipeline["architects"], _pipeline["editors"], messages, tools, tool_choice, body)

    # Check if this is a combo model — try each model until success
    if backend_router.is_combo(model):
        routes = backend_router.route_combo(model)
        last_error = ""

        # Skip web search for (a) pure HA queries — answered from the registry,
        # and (b) queries with a dedicated realtime MCP (giá vàng/thời tiết/cổ
        # phiếu…) — the model calls that tool directly (realtime + chính xác +
        # nhanh hơn ~13s web search). The model still keeps web_search_exa as a
        # fallback tool either way.
        try:
            from services.mcp_client import query_has_specialized_mcp
            _has_mcp = query_has_specialized_mcp(original_user_text)
        except Exception:
            _has_mcp = False
        if _has_mcp:
            logger.info({"event": "search_skipped", "reason": "dedicated_mcp"})

        search_injected = False
        if _should_inject_search(body, ha_query_pristine, is_vision_request, _has_mcp, original_user_text):
            before_size = _messages_size(messages)
            messages_copy = search_service.process_messages(messages)
            search_injected = _messages_size(messages_copy) > before_size
            # Auto-curate search results to RAG after response (best-effort bg)
            _curate_search_results(messages_copy)
            # Đã có sẵn dữ liệu search → model chỉ TỔNG HỢP, không cần reasoning sâu.
            # Cắt effort cho câu HA (giọng nói) → giảm 20-25s xuống ~10-15s.
            if search_injected and (ha_query_pristine or body.get("_is_ha_request")) and not body.get("_force_effort"):
                body["_force_effort"] = "none"
        else:
            messages_copy = messages
            
        # Mirror the non-combo path: inject HA registry as a system message for
        # HA-related queries so the LLM can answer in ONE round-trip instead of
        # doing GetLiveContext / ha_get_state -> wait -> final answer (saves ~7s).
        for _route_idx, route in enumerate(routes):
            messages_for_route = list(messages_copy)
            ha_context_injected = False
            if ha_query_pristine and route.provider != "chatgpt_free":
                try:
                    from services.ha_client import inject_ha_context
                    before_len = len(messages_for_route)
                    messages_for_route = inject_ha_context(messages_for_route)
                    ha_context_injected = len(messages_for_route) > before_len
                except Exception:
                    pass

            if not _thread_denies(body, "server"):
                messages_for_route = _inject_server_admin_context(messages_for_route, original_user_text)
            tools_with_mcp = _inject_mcp_tools(
                tools, skip_ha_search=ha_context_injected,
                is_vision=is_vision_request, search_injected=search_injected,
                user_text=original_user_text,
                is_free_model=(route.provider == "chatgpt_free"),
                prefetched=bool(body.get("_prefetched")),
                messages=messages_for_route,
                no_smart_home=_thread_denies(body, "homeassistant"),
                no_server_admin=_thread_denies(body, "server"),
            )
            try:
                # Combo-level demote: skip a provider this combo recently saw
                # fail with a real cooldown (429/quota/5xx/auth) — failures are
                # recorded under the synthetic "combo:<name>" key below, so an
                # exhausted provider drops to the back automatically and the next
                # healthy one is tried first ("hết quota thì đá xuống cuối").
                # 413 is NOT cooled, so a one-off big payload never demotes it.
                if not model_cooldown.is_available("combo:" + model, route.model):
                    logger.info({"event": "combo_skip_cooling", "combo": model, "provider": route.provider, "model": route.model})
                    last_error = f"{route.model} đang cooldown (combo-level)"
                    continue

                # Circuit-breaker per provider: mạch đang MỞ (fail liên tiếp) →
                # bỏ qua nhanh khỏi đốt timeout. KHÔNG chặn route CUỐI — luôn
                # giữ 1 đường thoát để không chết cứng.
                if _route_idx < len(routes) - 1 and not provider_circuit.allow(route.provider):
                    logger.info({"event": "combo_skip_circuit", "combo": model, "provider": route.provider})
                    last_error = f"{route.provider} circuit open (fail liên tiếp)"
                    continue

                cooldown = model_cooldown.get_cooldown_info(route.model)
                if cooldown:
                    logger.warning({"event": "model_cooldown_skip", "model": route.model, **cooldown})
                    last_error = cooldown["message"]
                    continue

                # ChatGPT Free has a hard ~45KB backend limit (413 Payload Too
                # Large). A HA control request carries the Assist system prompt
                # plus its tool schemas (entity names embedded as enums) — often
                # >45KB. No free account can serve that (they all 413 identically),
                # so detecting the oversize up front lets us skip the free tier and
                # go straight to a provider that accepts large payloads (cx/gemini)
                # instead of burning a ~30s rotating-and-413 attempt.
                if route.provider == "chatgpt_free":
                    try:
                        # Measure the SLIMMED payload (enums stripped) — the same
                        # transform _dispatch applies — so we only skip the free
                        # tier when it genuinely can't fit, not before slimming.
                        slim_tools = _slim_tools_for_free(tools_with_mcp)
                        raw_json = json.dumps(messages_for_route, ensure_ascii=False, default=str)
                        import re
                        slim_json = re.sub(r'"data:image/[^;]+;base64,[^"]+"', '""', raw_json)
                        payload_bytes = (
                            len(slim_json.encode("utf-8"))
                            + len(json.dumps(slim_tools or [], ensure_ascii=False, default=str).encode("utf-8"))
                        )
                    except Exception:
                        payload_bytes = 0
                    if payload_bytes > 42_000:
                        logger.info({"event": "combo_skip_free_oversized", "bytes": payload_bytes, "model": route.model})
                        last_error = "payload exceeds ChatGPT Free 45KB limit"
                        continue

                logger.info({
                    "event": "combo_try",
                    "combo": model,
                    "provider": route.provider,
                    "model": route.model,
                    "is_vision": bool(is_vision_request),
                    "structured": bool(
                        body.get("_response_format_meta")
                        or body.get("response_format")
                        or body.get("_structured_output")
                    ),
                })

                result = _dispatch(route, messages_for_route, tools_with_mcp, tool_choice, body)
                # Execute MCP tools server-side for combo too
                if not isinstance(result, dict):
                    result = _wrap_mcp_stream(result, messages_for_route, route, body)
                elif isinstance(result, dict):
                    result = _execute_mcp_tools_in_response(messages_for_route, result, route, body)
                # Do NOT strip markdown/italics when client asked for JSON
                # (response_format) — underscore rules mangle humans_detected keys.
                _struct = bool(body.get("_response_format_meta") or body.get("response_format") or body.get("_structured_output"))
                result = _maybe_strip_markdown(
                    result,
                    messages_for_route,
                    force=(ha_context_injected or bool(body.get("_is_ha_request"))) and not _struct,
                )
                result = _maybe_verbalize(result, voice)
                model_cooldown.record_success("combo:" + model, route.model)
                provider_circuit.record_success(route.provider)
                return result
            except Exception as exc:
                last_error = str(exc)
                logger.warning({"event": "combo_fail", "combo": model, "provider": route.provider, "error": last_error[:200]})
                model_cooldown.record_failure(
                    account_id="combo:" + model, model=route.model,
                    status_code=_extract_status(last_error), error_body=last_error, provider=route.provider,
                )
                provider_circuit.record_failure(route.provider, _extract_status(last_error), last_error)
                continue
        err_msg = f"All providers failed. Last error: {last_error[:200]}"
        notify_error_tg(f"Combo '{model}' cạn provider", model, last_error, original_user_text)
        if body.get("stream"):
            def _err_stream():
                cid = f"chatcmpl-{uuid.uuid4().hex}"
                ts = int(time.time())
                yield completion_chunk(model, {"role": "assistant", "content": err_msg}, None, cid, ts)
                yield completion_chunk(model, {}, "stop", cid, ts)
            return _err_stream()
        return completion_response(model=model, content=err_msg, messages=messages)

    # Single model — route directly
    route = backend_router.route(model, messages)

    # Apply search injection for all backends — but skip when the user query
    # is a pure HA command/status (answered from registry), a vision task, or has
    # a dedicated realtime MCP (giá vàng/thời tiết…) the model can call directly.
    try:
        from services.mcp_client import query_has_specialized_mcp
        _has_mcp = query_has_specialized_mcp(original_user_text)
    except Exception:
        _has_mcp = False
    if _has_mcp:
        logger.info({"event": "search_skipped", "reason": "dedicated_mcp"})
    search_injected = False
    if _should_inject_search(body, ha_query_pristine, is_vision_request, _has_mcp, original_user_text):
        before_size = _messages_size(messages)
        messages = search_service.process_messages(messages)
        search_injected = _messages_size(messages) > before_size
        # Tổng hợp đa nguồn xong → curate (write-back) về kho IntentRouter chọn.
        _curate_search_results(messages)
        # Đã có dữ liệu search → chỉ tổng hợp, cắt reasoning cho câu HA → nhanh hơn.
        if search_injected and (ha_query_pristine or body.get("_is_ha_request")) and not body.get("_force_effort"):
            body["_force_effort"] = "none"

    # Inject HA smart home context only when the PRISTINE user message looked
    # like an HA query. This avoids false positives from search-result text.
    ha_context_injected = False
    if ha_query_pristine and route.provider != "chatgpt_free":
        try:
            from services.ha_client import inject_ha_context
            before_len = len(messages)
            messages = inject_ha_context(messages)
            ha_context_injected = len(messages) > before_len
        except Exception:
            pass

    # Inject MCP tools from enabled presets
    if not _thread_denies(body, "server"):
        messages = _inject_server_admin_context(messages, original_user_text)
    tools = _inject_mcp_tools(
        tools, skip_ha_search=ha_context_injected,
        is_vision=is_vision_request, search_injected=search_injected,
        user_text=original_user_text,
        is_free_model=(route.provider == "chatgpt_free"),
        prefetched=bool(body.get("_prefetched")),
        messages=messages,
        no_smart_home=_thread_denies(body, "homeassistant"),
        no_server_admin=_thread_denies(body, "server"),
    )

    # Single-model: KHÔNG chặn bằng circuit (không có route thay thế) — chỉ ghi
    # nhận kết quả để combo/health nhìn thấy sức khỏe provider.
    try:
        result = _dispatch(route, messages, tools, tool_choice, body)
    except Exception as exc:
        provider_circuit.record_failure(route.provider, _extract_status(str(exc)), str(exc))
        raise
    provider_circuit.record_success(route.provider)

    # Execute MCP tools server-side — HA doesn't know these tools
    if not isinstance(result, dict):
        # Streaming (Iterator) — wrap to intercept tool calls
        if route.provider != "chatgpt_free":
            result = _wrap_mcp_stream(result, messages, route, body)
    elif isinstance(result, dict):
        result = _execute_mcp_tools_in_response(messages, result, route, body)
        import json
        logger.info({"event": "debug_final_result", "result": json.dumps(result, ensure_ascii=False)[:2000]})

    _struct = bool(body.get("_response_format_meta") or body.get("response_format") or body.get("_structured_output"))
    result = _maybe_strip_markdown(
        result,
        messages,
        force=(ha_context_injected or bool(body.get("_is_ha_request"))) and not _struct,
    )
    result = _maybe_verbalize(result, voice)
    try:
        import json
        with open("/tmp/last_response.json", "w", encoding="utf-8") as f:
            if isinstance(result, dict):
                f.write(json.dumps(result, ensure_ascii=False))
            else:
                f.write("STREAM_GENERATOR")
    except Exception:
        pass
    return result


def _maybe_strip_markdown(result, messages, force=False):
    """Always strip backend artifacts (citation markers etc.). Conditionally
    strip markdown when:
    - the request looks like a plain-text surface (device-keyword heuristic), OR
    - the caller forces it (e.g. HA voice / Conversation API which cannot
      render markdown tables — `giá xăng hôm nay` should arrive as plain
      text on HA even though it has no device keyword).
    Stream and dict results are both supported.
    """
    # Always strip backend artifacts — these never belong in user-facing text
    if isinstance(result, dict):
        result = _strip_artifacts_in_response(result)
    else:
        result = _strip_artifacts_in_stream(result)
    # Conditionally strip markdown on top
    if not (force or _request_wants_plain_text(messages)):
        return result
    if isinstance(result, dict):
        return _strip_markdown_in_response(result)
    return _strip_markdown_in_stream(result)


def _strip_artifacts_in_response(result: dict[str, Any]) -> dict[str, Any]:
    choices = result.get("choices") or []
    for ch in choices:
        msg = ch.get("message") if isinstance(ch, dict) else None
        if isinstance(msg, dict):
            txt = msg.get("content")
            if isinstance(txt, str):
                msg["content"] = _strip_artifacts_inline(txt)
    return result


def _strip_artifacts_in_stream(it: Iterator[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for chunk in it:
        try:
            choices = chunk.get("choices") or []
            for ch in choices:
                if not isinstance(ch, dict):
                    continue
                delta = ch.get("delta")
                if isinstance(delta, dict):
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        delta["content"] = _strip_artifacts_inline(content)
        except Exception:
            pass
        yield chunk


def _maybe_verbalize(result, voice=False):
    if not voice:
        return result
    if isinstance(result, dict):
        return _verbalize_in_response(result)
    return _verbalize_in_stream(result)


def _verbalize_in_response(result: dict[str, Any]) -> dict[str, Any]:
    choices = result.get("choices") or []
    for ch in choices:
        msg = ch.get("message") if isinstance(ch, dict) else None
        if isinstance(msg, dict):
            txt = msg.get("content")
            if isinstance(txt, str):
                from services.verbalize import verbalize
                msg["content"] = verbalize(txt)
    return result


def _verbalize_in_stream(it: Iterator[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    from services.verbalize import verbalize
    for chunk in it:
        try:
            choices = chunk.get("choices") or []
            for ch in choices:
                if not isinstance(ch, dict):
                    continue
                delta = ch.get("delta")
                if isinstance(delta, dict):
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        # keep_edges: giữ dấu cách ở biên chunk, kẻo chữ dính nhau
                        # ("Xinchàoanh…") khi model TTS không có ':text'.
                        delta["content"] = verbalize(content, keep_edges=True)
        except Exception:
            pass
        yield chunk


def _thread_denies(body: dict, group: str) -> bool:
    """Bộ lọc chức năng theo thread — orchestrator/bot gửi kèm `x_allowed_groups`
    (list tên nhóm được phép). True = request này KHÔNG được dùng nhóm `group`,
    pipeline phải tắt hẳn tích hợp tương ứng (HA / server-admin / web search),
    kẻo gateway tự phát hiện ý định rồi tự thực thi, vòng qua mặt bộ lọc.
    Thiếu field / sai kiểu = không lọc (tương thích client thường)."""
    if group == "homeassistant" and bool(body.get("x_no_smart_home")):
        return True
    ag = body.get("x_allowed_groups")
    if not isinstance(ag, list):
        return False
    return group not in {str(g) for g in ag}


def _should_inject_search(body: dict, ha_pristine: bool, is_vision: bool,
                          has_mcp: bool, text: str) -> bool:
    """Có chạy search SONG SONG (MCP federated + backends + ChatGPT native search)
    rồi để model tổng hợp + curate vào RAG hay không.

    Câu KIẾN THỨC — KỂ CẢ qua HA — đều bật, để tổng hợp đa nguồn cho câu không có
    trong kho. TRỪ: vision; realtime MCP chuyên dụng (giá vàng/thời tiết…); đã
    prefetch (kho/realtime — tránh search 2 lần); và — với HA — chat vu vơ / lệnh
    điều khiển (giữ phản hồi nhanh)."""
    if not search_service.is_enabled or is_vision or has_mcp or body.get("_prefetched"):
        return False
    if _thread_denies(body, "web"):
        return False  # thread bị lọc, không có nhóm 'web' → không tự search hộ
    is_ha = bool(ha_pristine) or bool(body.get("_is_ha_request"))
    if not is_ha:
        return True
    try:
        return bool(text) and not _is_trivial_chat(text) and not _is_smarthome_query(text)
    except Exception:
        return False


def _curate_search_results(messages: list[dict[str, Any]]) -> None:
    """Extract last user query + search results → curate to RAG in background."""
    try:
        query = ""
        search_text = ""
        for m in reversed(messages):
            if m.get("role") == "user" and not query:
                c = m.get("content", "")
                query = c if isinstance(c, str) else str(c)[:200]
            if m.get("role") == "system" and "Search results" in str(m.get("content", "")):
                search_text = str(m.get("content", ""))[:2000]
        if query and search_text:
            # Curate into the topic KB the IntentRouter picked (kb_tu_nhien,
            # kb_y_te, …) instead of a catch-all kb_general, so the enrichment
            # loop deposits knowledge where ask_<col> will later find it.
            collection = ""
            try:
                from services.search_service import _intent_router
                cols = _intent_router.detect(query).get("kb_collections") or []
                collection = cols[0] if cols else ""
            except Exception:
                collection = ""
            search_service.curate_response(query, search_text, collection)
    except Exception:
        pass


def _auto_search_enrich(query: str) -> str:
    """Run search alongside MCP tool execution for richer context."""
    if not search_service.is_enabled:
        return ""
    try:
        results = search_service.search_all(query)
        if not results:
            return ""
        lines = ["\n---\n## Kết quả tìm kiếm bổ sung\n"]
        for r in results[:5]:
            title = r.get("title", "")
            snippet = (r.get("snippet") or "")[:300]
            url = r.get("url", "")
            if title:
                lines.append(f"- **{title}**")
            if snippet:
                lines.append(f"  {snippet}")
            if url:
                lines.append(f"  {url}")
        return "\n".join(lines)
    except Exception:
        return ""


def _extract_user_query(messages: list[dict[str, Any]]) -> str:
    """Get the last user message text for search enrichment."""
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, str):
                return c[:200]
            if isinstance(c, list):
                return str(c[0].get("text", ""))[:200] if c else ""
    return ""


def _wrap_mcp_stream(
    stream_iter, messages: list[dict[str, Any]], route, body: dict[str, Any]
):
    """Wrap a streaming response to execute MCP/HA tools and return final answer.

    Collects the full stream, checks for server-side tool calls, executes them in
    an agentic loop (multi-step: e.g. ha_search_entities → ha_get_state → answer),
    then streams the final LLM response.
    """
    # Collect full response from stream
    chunks = []
    full_content = ""
    model = ""
    # Accumulate tool_call deltas BY INDEX. Codex streams a function_call across
    # two chunks: first carries the name (empty args), second carries the full
    # args (no name). Overwriting (final = tc) would keep only the last → name
    # lost → the call isn't recognised as an MCP/HA tool and leaks through to the
    # client (HA → "Tool not found"). Merge name + arguments per index instead.
    tc_acc: dict[int, dict[str, Any]] = {}

    try:
        for chunk in stream_iter:
            chunks.append(chunk)
            if isinstance(chunk, dict):
                model = chunk.get("model", model)
                delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                full_content += delta.get("content") or ""
                for t in (delta.get("tool_calls") or []):
                    idx = t.get("index", 0) or 0
                    slot = tc_acc.setdefault(idx, {"id": "", "type": "function",
                                                   "function": {"name": "", "arguments": ""}})
                    if t.get("id"):
                        slot["id"] = t["id"]
                    fn = t.get("function") or {}
                    if fn.get("name"):
                        slot["function"]["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["function"]["arguments"] += fn["arguments"]
    except Exception as exc:
        logger.error({"event": "mcp_stream_error", "error": str(exc)[:300],
                       "chunks_collected": len(chunks)})
        for c in chunks:
            yield c
        return

    # Merged tool calls (name + full arguments), ordered by index.
    final_tool_calls: list | None = (
        [tc_acc[i] for i in sorted(tc_acc)] if tc_acc else None
    )

    # No native tool_calls — check for XML tool calls in content text.
    # ChatGPT web backend models output ```xml <tool_call> instead of
    # native function-call objects. Parse them so server-side tools
    # (GetLiveContext, ha_*) are executed here.
    was_xml = False
    if not final_tool_calls:
        xml_calls = _extract_xml_tool_calls_from_text(full_content)
        if xml_calls:
            was_xml = True
            final_tool_calls = []
            for i, xc in enumerate(xml_calls):
                fn = xc.get("function", {})
                final_tool_calls.append({
                    "id": f"xml_stream_{i}",
                    "type": "function",
                    "function": {
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments", "{}"),
                    },
                })

    # No tool calls → stream as-is
    if not final_tool_calls:
        for c in chunks:
            yield c
        return

    # Filter to server-side tools only
    from services.mcp_client import get_enabled_mcp_tools
    from services.ha_client import get_ha_tools
    known_server_tools = {
        t.get("function", {}).get("name", "")
        for t in get_enabled_mcp_tools() + get_ha_tools()
    }

    mcp_calls = [tc for tc in final_tool_calls
                 if tc.get("function", {}).get("name", "") in known_server_tools]

    if not mcp_calls:
        if was_xml:
            import re
            clean_content = re.sub(
                r"```xml\s*<tool_call[^`]*```", "", full_content,
                flags=re.DOTALL,
            ).strip()
            completion_id = f"chatcmpl-{uuid.uuid4().hex}"
            created = int(time.time())
            if clean_content:
                yield completion_chunk(model, {"role": "assistant", "content": clean_content}, None, completion_id, created)
            tool_calls_delta = [{"index": i, "id": tc["id"], "type": "function", "function": tc["function"]} for i, tc in enumerate(final_tool_calls)]
            yield completion_chunk(model, {"role": "assistant", "tool_calls": tool_calls_delta}, None, completion_id, created)
            yield completion_chunk(model, {}, "tool_calls", completion_id, created)
            return

        for c in chunks:
            yield c
        return

    # Build a synthetic non-stream result to feed into the agentic loop
    # Strip XML tool-call fence from content — tool_calls carry the intent.
    import re
    clean_content = re.sub(
        r"```xml\s*<tool_call[^`]*```", "", full_content,
        flags=re.DOTALL,
    ).strip()
    synthetic_result = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": clean_content,
                "tool_calls": final_tool_calls,
            },
            "finish_reason": "tool_calls",
        }],
    }

    # Run agentic loop (handles multi-step chains)
    try:
        final_result = _execute_mcp_tools_in_response(messages, synthetic_result, route, body)
    except Exception as exc:
        logger.warning({"event": "mcp_stream_loop_failed", "error": str(exc)})
        for c in chunks:
            yield c
        return

    # Stream the final result back to client
    if hasattr(final_result, "__iter__") and not isinstance(final_result, (dict, str)):
        yield from final_result
    elif isinstance(final_result, dict):
        # Convert non-streaming result into stream chunks
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        choice = (final_result.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        tool_calls = (choice.get("message") or {}).get("tool_calls")
        yield completion_chunk(model, {"role": "assistant", "content": content}, None, completion_id, created)
        if tool_calls:
            tool_calls_delta = [{"index": i, "id": tc.get("id"), "type": "function", "function": tc.get("function")} for i, tc in enumerate(tool_calls)]
            yield completion_chunk(model, {"tool_calls": tool_calls_delta}, None, completion_id, created)
            yield completion_chunk(model, {}, "tool_calls", completion_id, created)
        else:
            yield completion_chunk(model, {}, "stop", completion_id, created)
    else:
        for c in chunks:
            yield c


def _looks_like_tool_error(s: str | None) -> bool:
    """Heuristic: did an MCP tool result come back as a failure OR empty/zero data
    (not real data)? Empty/zero counts as failure so the search fallback kicks in
    (vd get_market_overview trả VN-Index=0, RAG store "chưa có dữ liệu")."""
    if not s or len(str(s).strip()) < 20:
        return True
    t = str(s).lower()[:400]
    return any(m in t for m in (
        # hard errors
        "tool error:", "returned no result", "tool \"", "not found",
        "validation error", "missing required", "unexpected keyword",
        "homeassistanterror", "traceback", "exception",
        # empty / no-data (→ fallback search)
        "chưa có dữ liệu", "chua co du lieu", "không có dữ liệu", "khong co du lieu",
        "no data", "n/a", "vn-index**: 0",
    ))


def _mcp_error_fallback(query: str) -> str | None:
    """A dedicated MCP tool failed → fall back to the configured search service
    (cài đặt tab tìm kiếm). search_all() already fans out to MCP tools + web +
    combo backends IN PARALLEL internally and merges, so it's robust even when
    one MCP is down. Returns formatted text, or None if search is off/empty."""
    if not query.strip() or not search_service.is_enabled:
        return None
    try:
        results = search_service.search_all(query)
    except Exception as exc:
        logger.warning({"event": "mcp_fallback_failed", "error": str(exc)[:200]})
        return None
    lines: list[str] = []
    for r in (results or []):
        if not isinstance(r, dict):
            continue
        title = str(r.get("title") or "").strip()
        snippet = str(r.get("snippet") or r.get("content") or "").strip()
        seg = " — ".join(p for p in (title, snippet) if p)
        if seg:
            lines.append("- " + seg)
    text = "\n".join(lines)[:4000]
    return text or None


def _cap_mcp_result(text: str, limit: int = 8000) -> str:
    """Cap an MCP tool result before it goes back to the model. Some tools dump
    huge tables (vd get_gold_prices ~50KB: DOJI + BTMC + PNJ + interbank) — the
    model must RE-READ all of it to summarise, which dominates RT2 latency. The
    headline data sits at the top, so head-truncate with a marker."""
    if not text or len(text) <= limit:
        return text
    return text[:limit] + "\n…(đã rút gọn — trả lời từ phần dữ liệu trên)"


def _execute_mcp_tools_in_response(
    messages: list[dict[str, Any]], result: dict, route, body: dict[str, Any],
    max_iterations: int = 4,
) -> dict[str, Any]:
    """Execute MCP/HA tool calls in an agentic loop until final answer or max_iterations.

    Supports multi-step tool chains like:
      ha_search_entities → ha_get_state → final LLM answer
    """
    from services.mcp_client import get_enabled_mcp_tools
    from services.ha_client import get_ha_tools

    current_result = result
    current_messages = list(messages)

    for iteration in range(max_iterations):
        choice = (current_result.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        tool_calls = list(msg.get("tool_calls") or [])
        xml_calls = None

        # ChatGPT web backend returns XML tool calls in text content,
        # not native function-call objects. Parse them so server-side
        # tools (GetLiveContext, ha_*) are executed here instead of
        # being passed through as text to HA pipeline.
        if not tool_calls:
            content_text = msg.get("content") or ""
            xml_calls = _extract_xml_tool_calls_from_text(content_text)
            if xml_calls:
                for i, xc in enumerate(xml_calls):
                    fn = xc.get("function", {})
                    tool_calls.append({
                        "id": f"xml_{iteration}_{i}",
                        "type": "function",
                        "function": {
                            "name": fn.get("name", ""),
                            "arguments": fn.get("arguments", "{}"),
                        },
                    })

        if not tool_calls:
            return current_result  # No more tool calls → final answer

        # Identify server-side vs native (HA pipeline) tools
        known_server_tools = {
            t.get("function", {}).get("name", "")
            for t in get_enabled_mcp_tools() + get_ha_tools()
        }

        mcp_calls = []
        native_calls = []
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            if name in known_server_tools:
                mcp_calls.append(tc)
            else:
                native_calls.append(tc)

        if not mcp_calls:
            return current_result  # Only native HA tools → pass through

        # Strip XML tool-call fence from content so the model doesn't
        # see duplicate calls when we re-query with native tool_calls.
        assistant_content = msg.get("content") or ""
        if xml_calls:
            import re
            assistant_content = re.sub(
                r"```xml\s*<tool_call[^`]*```", "", assistant_content,
                flags=re.DOTALL,
            ).strip()

        # Append assistant message with all server-side tool calls
        current_messages.append({
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": mcp_calls,
        })
        _tool_results_start = len(current_messages)  # tool results appended below

        # Execute ALL server-side tool calls IN PARALLEL for speed
        is_action_only = len(mcp_calls) > 0 and all(
            tc.get("function", {}).get("name", "").startswith("Hass") or
            tc.get("function", {}).get("name") == "ha_call_service"
            for tc in mcp_calls
        ) and not native_calls

        if len(mcp_calls) > 1:
            # Parallel execution for multiple tool calls
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(mcp_calls)) as pool:
                future_map = {}
                for tc in mcp_calls:
                    args_str = tc.get("function", {}).get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except Exception:
                        args = {}
                    tool_name = tc.get("function", {}).get("name", "")
                    logger.info({"event": "mcp_tool_exec_parallel", "tool": tool_name})
                    future_map[pool.submit(_execute_mcp_tool, tool_name, args)] = tc

                # Collect results and append to messages
                for future in concurrent.futures.as_completed(future_map, timeout=30):
                    tc = future_map[future]
                    tool_name = tc.get("function", {}).get("name", "")
                    tool_id = tc.get("id", f"mcp_{iteration}")
                    try:
                        mcp_result = future.result()
                    except Exception as exc:
                        mcp_result = f"Tool error: {exc}"
                    if mcp_result is None:
                        mcp_result = f"Tool '{tool_name}' returned no result."
                    current_messages.append({
                        "role": "tool", "tool_call_id": tool_id,
                        "name": tool_name, "content": _cap_mcp_result(mcp_result),
                    })
        else:
            # Single tool call — sequential is fine
            for tc in mcp_calls:
                args_str = tc.get("function", {}).get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except Exception:
                    args = {}
                tool_name = tc.get("function", {}).get("name", "")
                tool_id = tc.get("id", f"mcp_{iteration}")
                logger.info({"event": "mcp_tool_exec", "tool": tool_name, "iteration": iteration})
                mcp_result = _execute_mcp_tool(tool_name, args)
                if mcp_result is None:
                    mcp_result = f"Tool '{tool_name}' returned no result."
                current_messages.append({
                    "role": "tool", "tool_call_id": tool_id,
                    "name": tool_name, "content": _cap_mcp_result(mcp_result),
                })

        # Fallback: a dedicated MCP tool failed (lỗi / không có data) → kéo dữ
        # liệu từ search service (cài đặt tab tìm kiếm) + Exa SONG SONG rồi đưa
        # vào ngữ cảnh, để model trả lời từ dữ liệu thật thay vì bịa. Chỉ chạy
        # khi không phải lệnh điều khiển và có tool đọc bị lỗi.
        if not is_action_only:
            failed = [m for m in current_messages[_tool_results_start:]
                      if m.get("role") == "tool" and _looks_like_tool_error(m.get("content"))]
            if failed:
                q = _extract_last_user_text(messages)
                logger.info({"event": "mcp_error_fallback_start",
                             "failed_tools": [m.get("name") for m in failed], "query": q[:60]})
                fb = _mcp_error_fallback(q)
                if fb:
                    current_messages.append({
                        "role": "system",
                        "content": ("[Công cụ chuyên dụng lỗi — DỮ LIỆU WEB DỰ PHÒNG cho "
                                    f"câu hỏi \"{q}\". Trả lời từ dữ liệu này:]\n{fb}"),
                    })
                    logger.info({"event": "mcp_error_fallback_injected", "chars": len(fb)})

        if is_action_only:
            logger.info({"event": "ha_fast_short_circuit"})
            # KHÔNG báo thành công khống: tool result lỗi ("Lỗi gọi ...", Tool
            # error, TypeError...) → trả lỗi thật + đẩy Telegram để còn debug.
            def _act_failed(_content: Any) -> bool:
                t = str(_content or "").strip().lower()
                return (not t or t.startswith("lỗi") or t.startswith("loi ")
                        or "tool error" in t or "unexpected keyword" in t
                        or "traceback" in t or "exception" in t)
            _failed_acts = [m for m in current_messages[_tool_results_start:]
                            if m.get("role") == "tool" and _act_failed(m.get("content"))]
            # Tạo automation: create_automation_and_verify đã kiểm duyệt + verify
            # server-side → kết quả tool ("✅…"/"⚠️…") LÀ câu trả lời cuối, dùng
            # verbatim (không đè bằng câu thành công đóng hộp). Telegram do CHÍNH
            # create_automation_and_verify báo (cả ✅ lẫn ⚠️/❌) — đừng notify lại
            # ở đây kẻo ping đúp.
            _auto_msg = None
            _verified_tools = {"ha_upsert_config", "ha_upsert_helper", "ha_write_config_file"}
            if any(tc.get("function", {}).get("arguments", "").find("create_automation_by_ai") != -1
                   or tc.get("function", {}).get("name") in _verified_tools
                   for tc in mcp_calls):
                for m in reversed(current_messages[_tool_results_start:]):
                    if m.get("role") == "tool" and m.get("content"):
                        _auto_msg = str(m.get("content")); break
            final_text = msg.get("content")
            if _auto_msg:
                final_text = _auto_msg
            elif _failed_acts:
                final_text = "⚠️ Lệnh KHÔNG thực hiện được — " + "; ".join(
                    f"{m.get('name')}: {str(m.get('content'))[:150]}" for m in _failed_acts[:3])
                logger.warning({"event": "ha_action_failed",
                                "tools": [m.get("name") for m in _failed_acts]})
                try:
                    notify_error_tg("ha_action", current_result.get("model", ""),
                                    final_text, _extract_last_user_text(messages))
                except Exception:
                    pass
            if not final_text:
                final_text = "Đã thực hiện xong lệnh điều khiển thiết bị."
            if body.get("stream"):
                def _stream_fast_short_circuit():
                    cid = f"chatcmpl-{uuid.uuid4().hex}"
                    yield completion_chunk(current_result.get("model", ""), {"role": "assistant", "content": final_text}, None, cid)
                    yield completion_chunk(current_result.get("model", ""), {}, "stop", cid)
                return _stream_fast_short_circuit()
            return {
                "id": f"chatcmpl-{uuid.uuid4().hex}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": current_result.get("model", ""),
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": final_text,
                    },
                    "finish_reason": "stop",
                }],
            }

        # Re-dispatch with updated messages
        tools = _inject_mcp_tools(body.get("tools"), is_free_model=(route.provider == "chatgpt_free"), messages=current_messages,
                                  no_smart_home=_thread_denies(body, "homeassistant"),
                                  no_server_admin=_thread_denies(body, "server"))
        try:
            current_result = _dispatch(route, current_messages, tools, body.get("tool_choice"), body)
            if not isinstance(current_result, dict):
                # Got a stream back — yield it directly
                return current_result
        except Exception as exc:
            logger.warning({"event": "mcp_followup_failed", "error": str(exc), "iteration": iteration})
            return current_result

    return current_result


def _slim_tools_for_free(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Shrink tool schemas for the ChatGPT Free path (~45KB hard limit).

    Home Assistant's Assist tools embed the full exposed-entity list as `enum`
    arrays on their parameters (e.g. 117 entities × dozens of intent tools = tens
    of KB), which is the dominant payload bloat that 413s the free backend. We
    drop the enums/examples and clamp over-long descriptions. The tools still
    work — the model passes the entity name as a free string, and the targeted HA
    context already lists the valid names. Returns the tools unchanged when
    there's nothing to trim.
    """
    if not tools:
        return tools
    import copy
    slimmed: list[dict[str, Any]] = []
    for t in tools:
        if not isinstance(t, dict):
            slimmed.append(t)
            continue
        t = copy.deepcopy(t)
        params = (t.get("function") or {}).get("parameters") or {}
        props = params.get("properties")
        if isinstance(props, dict):
            for p in props.values():
                if not isinstance(p, dict):
                    continue
                p.pop("enum", None)
                p.pop("examples", None)
                items = p.get("items")
                if isinstance(items, dict):
                    items.pop("enum", None)
                    items.pop("examples", None)
                desc = p.get("description")
                if isinstance(desc, str) and len(desc) > 200:
                    p["description"] = desc[:200]
        slimmed.append(t)
    return slimmed


def _dispatch(route, messages, tools, tool_choice, body):
    """Dispatch to the correct provider handler."""
    route.model = _strip_marker(route.model)
    # RTK compression thresholds — 24KB → 80KB → 100KB. We sit at the
    # chatgpt.com hard-limit cap; over-cap payloads still get compressed
    # by _rtk_compress_messages so requests never 413.
    # File upload bypass runs independently of RTK — when enabled for chatgpt
    # provider, large user messages (>80KB) are uploaded to /backend-api/files
    # and referenced via asset_pointer instead of being head+tail compressed.
    file_upload_enabled = (route.provider in ("chatgpt", "chatgpt_free"))
    if route.provider in ("chatgpt", "chatgpt_free"):
        rtk_on = config.rtk_enabled
        rtk_threshold = 100_000
    else:
        rtk_on = config.rtk_other_enabled
        rtk_threshold = 100_000
    if rtk_on or file_upload_enabled:
        from services.protocol.conversation import _rtk_compress_messages
        file_upload_threshold = 80_000 if file_upload_enabled else 0
        messages = _rtk_compress_messages(messages, rtk_threshold, file_upload_threshold=file_upload_threshold)

    if route.provider == "opencode":
        return _handle_opencode_chat(route.model, messages, body.get("stream"), body)
    elif route.provider in ("openai_oauth", "codex"):
        return _handle_openai_oauth_chat(route.model, messages, tools, tool_choice, body.get("stream"), body)
    elif route.provider == "gemini_free":
        return _handle_gemini_chat(route.model, messages, body.get("stream"), body)
    elif route.provider == "antigravity":
        return _handle_antigravity_chat(route.model, messages, tools, tool_choice, body.get("stream"), body)
    elif route.provider == "nvidia_nim":
        return _handle_nvidia_chat(route.model, messages, tools, tool_choice, body.get("stream"), body)
    elif route.provider == "gemini_web":
        from services.providers.web_proxy import handle_gemini_web_chat
        return handle_gemini_web_chat(route.model, messages, body.get("stream"), body)
    elif route.provider.startswith("custom:"):
        return _handle_custom_openai_chat(route.provider, route.model, messages, tools, tool_choice, body.get("stream"), body)
    elif route.provider in ("chatgpt_free", "chatgpt"):
        # Standalone free-tier module. `chatgpt/` and bare/unprefixed models are
        # now aliases for free — handle_free_chat owns the whole free path
        # (vision-fallback to gemini, tool→user normalization, free-pool
        # rotation). Codex/paid traffic uses cx/ | codex/ | paid/; OpenAI-API
        # (sk-/standard) uses oai/.
        from services.providers.chatgpt_free import handle_free_chat
        # cgf/auto → ROUTE NHANH: chatgpt.com free bắt buộc proof-of-work (~6s).
        # Với riêng alias /auto, thử Codex OAuth (API thẳng ~3s) TRƯỚC; thiếu
        # account/lỗi → fallback NGUYÊN VẸN về free pool (không mất tính năng).
        # cgf/auto | free/auto → thử route Codex nhanh. Bắt theo MODEL GỐC (body)
        # vì route() đã resolve "auto" thành model free mặc định.
        _cgf_auto_fast = str((body or {}).get("model") or "").strip().lower() in ("cgf/auto", "free/auto")
        if _cgf_auto_fast:
            try:
                return _handle_openai_oauth_chat("auto", messages, tools, tool_choice, body.get("stream"), body)
            except Exception as exc:
                logger.info({"event": "cgf_auto_codex_fallback_free", "error": str(exc)[:150]})
        # Strip entity-enum bloat from HA's tool schemas so the payload fits the
        # free backend's ~45KB limit (see _slim_tools_for_free).
        tools = _slim_tools_for_free(tools)
        return handle_free_chat(route.model, messages, tools, tool_choice, body.get("stream"), body, route)
    elif route.provider == "openai_api":
        # 3rd path kept separate (đại ca's decision): raw OpenAI API key (sk-)
        # or `standard` JWT accounts → api.openai.com via custom:openai.
        return _handle_openai_api_chat(route.model, messages, tools, tool_choice, body.get("stream"), body)
    elif route.provider == "claude":
        # claude.ai free web (claude/ | clf/ | cc/) — same backend as the
        # dedicated /v1/claude/* endpoint, reachable from the main route so
        # HA/automations can pick claude models from /v1/models directly.
        from api.claude import handle_claude_chat
        return handle_claude_chat(route.model, messages, body.get("stream"), body)
    elif route.provider == "gemini_web_api":
        # gemini.google.com qua cookie 1PSID (gma/ | gemini-web/) — HTTP API
        # trực tiếp (gemini_webapi), nhanh hơn DOM scrape gmw/.
        from api.gemini_web import handle_gemini_web_api_chat
        _base_url = str(body.get("base_url") or "").rstrip("/")
        return handle_gemini_web_api_chat(route.model, messages, body.get("stream"), body, base_url=_base_url)
    else:
        logger.warning({"event": "unknown_provider", "provider": route.provider, "fallback": "chatgpt_free"})
        from services.providers.chatgpt_free import handle_free_chat
        tools = _slim_tools_for_free(tools)
        return handle_free_chat(route.model, messages, tools, tool_choice, body.get("stream"), body, route)


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


def _convert_images_for_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert internal image format → OpenAI vision API format.
    Downloads HTTP URLs and converts to base64 (OpenAI can't fetch external URLs).
    """
    import base64
    from curl_cffi import requests as cffi_requests
    result: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            new_parts = []
            for part in content:
                if isinstance(part, dict):
                    ptype = part.get("type", "")
                    if ptype == "image":
                        data = part.get("data")
                        mime = part.get("mime", "image/png")
                        if isinstance(data, bytes):
                            b64 = base64.b64encode(data).decode("ascii")
                            new_parts.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{b64}"},
                            })
                        elif isinstance(data, str) and data.startswith("data:"):
                            new_parts.append({
                                "type": "image_url",
                                "image_url": {"url": data},
                            })
                        continue
                    elif ptype == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if isinstance(url, str) and url.startswith("data:"):
                            new_parts.append(part)  # Already base64
                        elif isinstance(url, str) and url.startswith("http"):
                            # Download and convert to base64 (OpenAI can't fetch external URLs)
                            try:
                                # Use standard requests for image downloads (no impersonation needed)
                                import urllib.request
                                req = urllib.request.Request(url, headers={
                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                                })
                                with urllib.request.urlopen(req, timeout=15) as resp:
                                    img_data = resp.read()
                                    mime = resp.headers.get("Content-Type", "image/jpeg")
                                    b64 = base64.b64encode(img_data).decode("ascii")
                                    new_parts.append({
                                        "type": "image_url",
                                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                                    })
                            except Exception as e:
                                logger.warning({"event": "image_download_failed", "url": url[:120], "error": str(e)[:100]})
                        continue
                new_parts.append(part)
            result.append({**msg, "content": new_parts})
        else:
            result.append(msg)
    return result


def _ensure_openai_provider():
    """Auto-create openai custom provider if missing (for web session routing)."""
    from services.providers.custom_openai import get_custom_providers
    providers = get_custom_providers()
    if "openai" not in providers:
        cfg = config.data
        cfg.setdefault("custom_providers", {})["openai"] = {
            "name": "OpenAI",
            "prefix": "openai",
            "base_url": "https://api.openai.com",
            "api_key": "sk-auto-created",
            "enabled": True,
        }
        config._save()
        logger.info({"event": "openai_provider_auto_created"})


def _handle_openai_api_chat(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    stream: bool,
    body: dict[str, Any],
) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """OpenAI-API path (3rd group, kept fully separate from free & codex).

    Serves raw OpenAI API-key (sk-...) or `standard`/`openai` JWT accounts by
    calling api.openai.com through the custom:openai provider. Reached only via
    the explicit `oai/` prefix — never auto-detected inside the free path.
    """
    openai_model = model[4:] if model.startswith("oai/") else model
    if not openai_model or openai_model in ("auto", "chatgpt/auto"):
        openai_model = config.openai_default_model or "gpt-4o"
    if openai_model.startswith("chatgpt/"):
        openai_model = openai_model[len("chatgpt/"):]

    token = account_service.get_text_access_token(account_type="openai")
    if not token:
        raise RuntimeError("no usable OpenAI-API (sk-/standard) account")

    messages = _restore_tool_messages(messages)
    messages = _convert_images_for_openai(messages)
    _ensure_openai_provider()

    logger.info({"event": "openai_api_chat_routed", "model": openai_model})
    return _handle_custom_openai_chat(
        "custom:openai", openai_model, messages, tools, tool_choice,
        stream, body, force_token=token,
    )

# Device keywords that should trigger tool call forcing
_FORCE_TOOL_KEYWORDS = [
    "trạng thái", "bật", "tắt", "mở", "đóng", "kiểm tra",
    "đèn", "quạt", "cửa", "điều hòa", "máy lạnh", "camera",
    "cảm biến", "công tắc", "ổ cắm", "rèm", "bình nóng lạnh",
    "tivi", "ti vi", "loa", "máy bơm", "nhiệt độ", "độ ẩm",
    "phòng khách", "phòng ngủ", "phòng học", "phòng bếp",
    "ban công", "nhà tắm", "nhà vệ sinh", "hành lang", "sân",
    "tầng", "cầu thang", "garage", "cổng",
    "thiết bị", "toàn bộ", "tất cả", "thời tiết",
]

# Greetings and trivial chat patterns that never need MCP tools.
# Matching is prefix-based: if the user message starts with one of these
# (after stripping), it's considered a trivial chat and MCP tools are skipped.
_TRIVIAL_GREETINGS = [
    "xin chào", "chào", "hello", "hi ", "hi.", "hi\n", "hey", "ê ", "alo", "a lô",
    "good morning", "good afternoon", "good evening",
    "cảm ơn", "thanks", "thank you",
    "tạm biệt", "bye", "goodbye",
    "có đó không", "khỏe không", "ăn cơm chưa",
    "ok", "okay", "được rồi", "ừ ", "ờ ",
]

# Tool-relevant domain keywords — if any of these appear in the user text,
# the query is NOT trivial and needs MCP tools.
_TOOL_DOMAIN_KEYWORDS = [
    "thời tiết", "nhiệt độ", "mưa", "nắng", "bão", "gió", "áp suất", "độ ẩm",
    "tìm", "kiếm", "search", "tra cứu", "wikipedia", "định nghĩa",
    "chứng khoán", "cổ phiếu", "giá vàng", "tỷ giá", "ngoại tệ", "xăng dầu",
    "tin tức", "báo ", "tin mới", "bản tin",
    "arxiv", "nghiên cứu", "paper", "bài báo",
    "luật ", "nghị định", "thông tư",
    "bệnh", "thuốc", "triệu chứng", "y tế", "bác sĩ",
    "học ", "giáo dục", "bài tập", "giảng", "trường",
    "youtube", "video", "transcript",
    "dịch", "translate", "phiên âm",
    "lịch âm", "âm lịch", "ngày", "tết",
]


def _is_trivial_chat(user_text: str) -> bool:
    """Return True if this is a simple greeting/chat that doesn't need MCP tools."""
    if not user_text:
        return False
    text = user_text.strip()
    text_lower = text.lower()
    # Must be reasonably short to be trivial
    if len(text) > 80:
        return False
    # Must not contain tool-relevant keywords (weather, search, stocks, etc.)
    for kw in _TOOL_DOMAIN_KEYWORDS:
        if kw in text_lower:
            return False
    # Must not contain HA device keywords
    for kw in _FORCE_TOOL_KEYWORDS:
        if kw in text_lower:
            return False
    # Must start with a known greeting pattern OR be very short (< 15 chars)
    for g in _TRIVIAL_GREETINGS:
        if text_lower.startswith(g):
            return True
    if len(text) <= 12:
        return True
    return False


def _extract_last_user_text(messages: list[dict[str, Any]]) -> str:
    """Extract the text of the last user message — handles BOTH a plain string
    and HA's structured list content (e.g. [{"type":"text","text":"trạng thái
    nhà"}, {"type":"image_url",...}]). Returning "" for list content silently
    broke the status/control tool heuristics on real HA requests."""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                return " ".join(
                    str(p.get("text") or "") for p in c
                    if isinstance(p, dict) and p.get("type") in ("text", "input_text")
                )
            return ""
    return ""


def _prefetch_ha_context_if_needed(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    token: str,
) -> list[dict[str, Any]]:
    """Pre-fetch HA device context BEFORE calling the LLM (chatgpt free path).

    HA sends a single HTTP request and reads a single streaming response.
    There is no way to do a 2nd LLM call inside the same connection.

    Strategy (mirrors how Codex reasons):
    1. Extract device/room keywords from user query
    2. Call ha_search_entities to find matching entity_ids (compact result)
    3. Call ha_get_state on each matched entity for live on/off state
    4. Inject compact result (~500 chars) into user message
    Falls back to a short summary from format_states_context if no specific
    entity is found.
    """
    # UNCONDITIONALLY trim HA's own exposed-entity dump for chatgpt_free.
    # When ~600+ entities are exposed to Assist, HA appends a 40KB+ block
    # "areas and the devices in this smart home" to the system prompt.
    # chatgpt.com free rejects payloads >45KB (413), so we always cut it.
    _HA_ASSIST_MARKER = "areas and the devices in this smart home"
    cleaned_messages = []
    for m in messages:
        content = str(m.get("content", ""))
        if m.get("role") == "system" and _HA_ASSIST_MARKER in content:
            idx = content.find(_HA_ASSIST_MARKER)
            line_start = content.rfind("\n", 0, idx)
            trimmed = (content[:line_start] if line_start > 0 else content[:idx]).rstrip()
            logger.info({"event": "ha_prefetch_trim_assist_entities",
                         "removed_chars": len(content) - len(trimmed)})
            cleaned_messages.append({**m, "content": trimmed})
            continue
        cleaned_messages.append(m)
    messages = cleaned_messages

    from services.ha_client import is_ha_query

    # ── Pre-execution for complex HA queries (no agentic loop on free path) ──
    # MUST run BEFORE is_ha_query gate because is_ha_query returns False for
    # "services", "automation" etc. (no device keyword) — but these still need
    # real HA API data injected so the LLM can answer with real data.
    user_text_early = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content", "")
            user_text_early = c if isinstance(c, str) else " ".join(
                str(p.get("text", "")) for p in c if isinstance(p, dict)
            )
            break
    user_lower_early = user_text_early.lower()

    # Skip if already injected real data
    _HA_DATA_MARKERS = [
        "DỮ LIỆU THỰC TỪ HOME ASSISTANT — error_log",
        "DỮ LIỆU THỰC TỪ HOME ASSISTANT — services",
        "DỮ LIỆU THỰC TỪ HOME ASSISTANT — automation",
        "DỮ LIỆU THỜI GIAN THỰC TỪ HOME ASSISTANT",
    ]
    already_injected = any(
        marker in str(m.get("content", ""))
        for m in messages
        for marker in _HA_DATA_MARKERS
    )

    if not already_injected:
        # --- 1. Error log query ---
        _LOG_KEYWORDS = ["error_log", "log lỗi", "log loi", "nhật ký", "nhat ky",
                         "rớt mạng", "rot mang", "mất kết nối", "mat ket noi",
                         "lỗi kết nối", "loi ket noi", "đọc log", "doc log"]
        if any(kw in user_lower_early for kw in _LOG_KEYWORDS):
            try:
                from services.ha_client import _get_ha_config
                import urllib.request as _urlreq
                cfg = _get_ha_config()
                if cfg:
                    req = _urlreq.Request(
                        f"{cfg['url']}/api/error_log",
                        headers={"Authorization": f"Bearer {cfg['token']}"},
                    )
                    raw_log = _urlreq.urlopen(req, timeout=12).read().decode("utf-8", "replace")
                    log_lines = raw_log.splitlines()
                    relevant = [l for l in log_lines if any(kw in l for kw in
                        ("ERROR", "WARNING", "unavailable", "timeout", "disconnected",
                         "connection", "Disconnected", "Timeout", "Failed"))]
                    if not relevant:
                        relevant = log_lines[-50:]
                    else:
                        relevant = relevant[-80:]
                    log_ctx = "\n".join(relevant)
                    inject_ctx = (
                        f"\n\n[DỮ LIỆU THỰC TỪ HOME ASSISTANT — error_log]:\n"
                        f"Đây là nội dung log lỗi thực tế vừa được truy xuất từ hệ thống.\n"
                        f"Hãy phân tích và trả lời câu hỏi của người dùng dựa trên log này.\n\n"
                        f"{log_ctx}\n"
                    )
                    logger.info({"event": "ha_prefetch_error_log", "lines": len(relevant)})
                    injected = []
                    flag = False
                    for m in reversed(messages):
                        if m.get("role") == "user" and not flag:
                            injected.append({**m, "content": str(m.get("content", "")) + inject_ctx})
                            flag = True
                        else:
                            injected.append(m)
                    return list(reversed(injected))
            except Exception as exc:
                logger.warning({"event": "ha_prefetch_error_log_failed", "error": str(exc)[:120]})

        # --- 2. Services / notify query ---
        _SVC_KEYWORDS = ["dịch vụ", "dich vu", "service", "notify", "thông báo", "thong bao",
                         "gửi tin", "gui tin", "push notification", "điện thoại", "dien thoai"]
        if any(kw in user_lower_early for kw in _SVC_KEYWORDS):
            try:
                from services.ha_client import _get_services, _get_ha_config
                cfg = _get_ha_config()
                if cfg:
                    services_data = _get_services()
                    if services_data:
                        priority_domains = ["notify", "pyscript", "light", "switch", "climate", "fan",
                                            "cover", "lock", "automation", "script", "media_player"]
                        lines = ["Các dịch vụ (services) có thể gọi trong hệ thống:"]
                        for domain in priority_domains:
                            if domain in services_data:
                                svcs = services_data[domain]
                                lines.append(f"\n[{domain}]: {', '.join(svcs[:20])}")
                        for domain, svcs in services_data.items():
                            if domain not in priority_domains:
                                lines.append(f"[{domain}]: {', '.join(svcs[:5])}")
                        svc_summary = "\n".join(lines)[:6000]
                        inject_ctx = (
                            f"\n\n[DỮ LIỆU THỰC TỪ HOME ASSISTANT — services]:\n"
                            f"Đây là danh sách services thực tế đang có trong hệ thống.\n"
                            f"Hãy trả lời câu hỏi dựa trên dữ liệu này, bao gồm các notify service cụ thể.\n\n"
                            f"{svc_summary}\n"
                        )
                        logger.info({"event": "ha_prefetch_services", "domains": len(services_data)})
                        injected = []
                        flag = False
                        for m in reversed(messages):
                            if m.get("role") == "user" and not flag:
                                injected.append({**m, "content": str(m.get("content", "")) + inject_ctx})
                                flag = True
                            else:
                                injected.append(m)
                        return list(reversed(injected))
            except Exception as exc:
                logger.warning({"event": "ha_prefetch_services_failed", "error": str(exc)[:120]})

        # --- 3. Automation create/clone query ---
        import re as _re
        _AUTO_CREATE_KEYWORDS = ["tạo automation", "tao automation", "tạo kịch bản", "tao kich ban",
                                  "tạo auto", "clone automation", "nhân bản"]
        _AUTO_REF_RE = _re.compile(r"automation\.[\w]+")
        if any(kw in user_lower_early for kw in _AUTO_CREATE_KEYWORDS):
            ref_ids = _AUTO_REF_RE.findall(user_text_early)
            try:
                from services.ha_client import _get_ha_config
                import urllib.request as _urlreq
                cfg = _get_ha_config()
                if cfg:
                    ctx_parts = []
                    if ref_ids:
                        for auto_id in ref_ids[:3]:
                            req = _urlreq.Request(
                                f"{cfg['url']}/api/states/{auto_id}",
                                headers={"Authorization": f"Bearer {cfg['token']}",
                                         "Content-Type": "application/json"},
                            )
                            try:
                                state_data = json.loads(_urlreq.urlopen(req, timeout=8).read())
                                attrs = state_data.get("attributes", {})
                                ctx_parts.append(
                                    f"Automation '{auto_id}':\n"
                                    f"- Tên: {attrs.get('friendly_name', auto_id)}\n"
                                    f"- Trạng thái: {state_data.get('state', 'unknown')}\n"
                                    f"- ID: {attrs.get('id', '')}\n"
                                )
                            except Exception:
                                pass
                    auto_ctx = "\n".join(ctx_parts) if ctx_parts else "Không có dữ liệu automation tham chiếu."
                    overview_txt = ""
                    try:
                        from services.ha_client import get_states, _build_overview_context
                        states = get_states(use_cache=True) or []
                        overview_txt = f"\n\n[DỮ LIỆU THỰC TỪ HOME ASSISTANT — overview]:\n{_build_overview_context(states)}\n\n"
                    except Exception:
                        pass
                    
                    inject_ctx = (
                        f"\n\n[DỮ LIỆU THỰC TỪ HOME ASSISTANT — automation]:\n"
                        f"{auto_ctx}\n"
                        f"{overview_txt}"
                        f"NẾU người dùng yêu cầu TẠO automation mới, BẠN BẮT BUỘC PHẢI sử dụng công cụ `ha_call_service` với:\n"
                        f"- domain: 'pyscript'\n"
                        f"- service: 'create_automation_by_ai'\n"
                        f"- data: {{'message': '<Đoạn code YAML hoàn chỉnh của automation, bắt đầu bằng - id: ...>'}}\n"
                        f"BẮT BUỘC: Automation YAML phải có trường `id:` (nên tự random id độc nhất) và `alias:` (tên). Hành động phải sử dụng entity_id chính xác có trong danh sách thiết bị trên.\n"
                    )
                    logger.info({"event": "ha_prefetch_automation", "ids": ref_ids[:3] if ref_ids else []})
                    injected = []
                    flag = False
                    for m in reversed(messages):
                        if m.get("role") == "user" and not flag:
                            injected.append({**m, "content": str(m.get("content", "")) + inject_ctx})
                            flag = True
                        else:
                            injected.append(m)
                    return list(reversed(injected))
            except Exception as exc:
                logger.warning({"event": "ha_prefetch_automation_failed", "error": str(exc)[:120]})

    # Skip HA prefetch if search results are already injected.
    _SEARCH_RESULT_MARKER = "kết quả tìm kiếm"
    for m in messages:
        if m.get("role") == "user" and _SEARCH_RESULT_MARKER in str(m.get("content", "")).lower():
            logger.info({"event": "ha_prefetch_skip", "reason": "search_results_already_injected"})
            return messages

    if not is_ha_query(messages):
        return messages


    # Only pre-fetch if user query is about device state

    user_text = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content", "")
            user_text = c if isinstance(c, str) else " ".join(
                str(p.get("text", "")) for p in c if isinstance(p, dict)
            )
            break

    if not _has_device_keyword(user_text):
        return messages

    # Already has live tool result injected? Skip.
    for m in messages:
        if m.get("role") == "user" and "KẾT QUẢ TỪ HỆ THỐNG" in str(m.get("content", "")):
            return messages
        if m.get("role") == "user" and "DỮ LIỆU THỜI GIAN THỰC TỪ HOME ASSISTANT" in str(m.get("content", "")):
            return messages


    # ── Targeted lookup (Codex-style: search → get_state) ──────────────────
    # Extract room/device keywords from query. Use the same keyword list
    # the static registry uses so lookup is consistent.
    import unicodedata as _ud

    def _strip_diacritics(t: str) -> str:
        nfkd = _ud.normalize("NFKD", t.lower())
        return "".join(c for c in nfkd if not _ud.combining(c))

    user_folded = _strip_diacritics(user_text)

    # Keywords to search for in HA: room names + device type words
    _SEARCH_TOKENS = [
        # rooms
        "ban công", "bep", "phong ngu", "phong khach", "phong hoc",
        "phong tam", "hanh lang", "san", "cau thang", "garage",
        # devices
        "den", "quat", "dieu hoa", "may lanh", "rem", "cua",
        "cong tac", "o cam", "khoa", "may bom",
    ]
    _TOKEN_MAP = {
        # map folded → Vietnamese search term for ha_search_entities
        "ban cong": "ban công", "bep": "bếp", "phong ngu": "phòng ngủ",
        "phong khach": "phòng khách", "phong hoc": "phòng học",
        "phong tam": "phòng tắm", "hanh lang": "hành lang",
        "den": "đèn", "quat": "quạt", "dieu hoa": "điều hòa",
        "may lanh": "máy lạnh", "rem": "rèm", "cua": "cửa",
        "cong tac": "công tắc", "o cam": "ổ cắm", "khoa": "khóa",
        "may bom": "máy bơm",
    }

    found_tokens: list[str] = []
    for tok in _SEARCH_TOKENS:
        # Check if the room/device token is in the user query (ignoring diacritics)
        # We replace spaces with empty string to match "ban công" -> "bancong" if needed,
        # but the simplest is just checking tok in user_folded.
        # But wait, tok is already diacritic-less in _SEARCH_TOKENS except for room names?
        # Let's fix _SEARCH_TOKENS to be fully folded.
        pass

    # Let's just do a direct multi-token search on the cached states.
    context_lines: list[str] = []
    
    # Extract ALL tokens from user_folded to match against entity names
    user_words = user_folded.split()
    
    # Check if this is a general query
    general_phrases = ["trang thai nha", "tong quan", "ca nha", "tat ca", "tinh hinh", "nha hien tai", "trong nha"]
    is_general = any(p in user_folded for p in general_phrases)
    
    if is_general:
        # Force fallback (full context) for general queries
        search_words = set()
    else:
        # Meaningful words to look for (ignore stop words)
        search_words = set([w for w in user_words if len(w) > 1 and w not in (
            "dang", "bat", "hay", "tat", "cho", "xin", "hoi", "thong", "tin",
            "trang", "thai", "cua", "co", "khong", "la", "gi", "nhe", "nha", "oi",
            "hien", "tai", "tat", "ca", "cac", "thiet", "bi"
        )])
    
    
    try:
        from services.ha_client import get_states
        # Real-time: a status query must reflect the CURRENT state, not the
        # hourly cache. Fetch fresh (refreshes the shared cache too, so the
        # exposed-only block below reuses it without a second HA call).
        states = get_states(use_cache=False)
        if states:
            # Score each entity by how many search words it matches
            matched_entities = []
            for s in states:
                eid = s.get("entity_id", "").lower()
                name = s.get("attributes", {}).get("friendly_name", "")
                name_folded = _strip_diacritics(name)
                # Combine eid and folded name for searching
                searchable = f"{eid} {name_folded}"
                
                score = sum(1 for w in search_words if w in searchable)
                if score > 0:
                    matched_entities.append((score, s))
            
            # Sort by score descending, take top 15
            matched_entities.sort(key=lambda x: x[0], reverse=True)
            
            for score, s in matched_entities[:15]:
                # If score is too low and we have many matches, maybe skip. 
                # But taking top 15 is safe.
                eid = s.get("entity_id", "")
                st = str(s.get("state", "unknown"))
                attrs = s.get("attributes", {}) or {}
                name = attrs.get("friendly_name", eid)
                unit = attrs.get("unit_of_measurement", "")
                state_str = f"{st} {unit}".strip() if unit else st
                context_lines.append(f"- {name} ({eid}): **{state_str}**")
                
    except Exception as exc:
        logger.warning({"event": "ha_prefetch_search_failed", "error": str(exc)[:80]})


    # Preferred fallback for general queries: report exactly the entities HA
    # exposes to Assist (curated ≈116) with their live states — not all ~989.
    # Honors the user's "Expose" config and keeps the injected context small.
    if not context_lines:
        try:
            from services.ha_client import get_states, get_exposed_entity_ids
            exposed = get_exposed_entity_ids()
            if exposed:
                ex_lines = []
                for s in get_states():
                    eid = s.get("entity_id", "")
                    if eid not in exposed:
                        continue
                    attrs = s.get("attributes", {}) or {}
                    name = attrs.get("friendly_name", eid)
                    st = str(s.get("state", "unknown"))
                    unit = str(attrs.get("unit_of_measurement", "") or "").strip()
                    state_str = f"{st} {unit}".strip() if unit else st
                    ex_lines.append(f"- {name} ({eid}): **{state_str}**")
                if ex_lines:
                    context_lines = ex_lines
                    logger.info({"event": "ha_prefetch_exposed_only",
                                 "exposed_total": len(exposed),
                                 "lines": len(ex_lines)})
        except Exception as exc:
            logger.warning({"event": "ha_prefetch_exposed_failed",
                            "error": str(exc)[:80]})

    if not context_lines:
        # Fallback: use static cache but only take the controllable device lines
        # (skip sensors/weather) and limit to 25000 chars total
        try:
            from services.ha_client import format_states_context
            cached = format_states_context()
            # Smart filter: only include ACTIVE core devices, ALL doors/locks, and IMPORTANT sensors
            compact_lines = []
            for line in cached.splitlines():
                lower = line.lower()
                
                is_core = any(x in lower for x in ('light.', 'switch.', 'climate.', 'fan.', 'cover.', 'lock.'))
                is_sensor = any(x in lower for x in ('sensor.', 'binary_sensor.'))
                
                if not (is_core or is_sensor):
                    continue
                    
                # Remove the check that skips off devices so ALL lights/switches are visible
                        
                # For sensors, only include important ones to avoid spam
                if is_sensor:
                    important_keywords = [
                        'nhiệt độ', 'độ ẩm', 'chuyển động', 'khói', 'cửa', 'pin', 'power', 
                        'nhiet', 'am', 'door', 'motion', 'smoke', 'battery',
                        'âm lịch', 'rằm', 'giỗ', 'công suất', 'điện', 'aptomat', 'hôm nay',
                        'lịch', 'calendar', 'aqi', 'không khí', 'air'
                    ]
                    if not any(k in lower for k in important_keywords):
                        continue
                        
                compact_lines.append(line)
                if len("\n".join(compact_lines)) > 25000: # Safe upper bound
                    break
            if compact_lines:
                context_lines = compact_lines
                logger.info({"event": "ha_prefetch_fallback_compact",
                             "lines": len(context_lines)})
        except Exception:
            pass

    if not context_lines:
        logger.info({"event": "ha_prefetch_no_data"})
        return messages

    live_summary = "\n".join(context_lines)
    logger.info({"event": "ha_prefetch_ok", "context_len": len(live_summary)})

    msg_context = (
        f"\n\n[DỮ LIỆU THỜI GIAN THỰC TỪ HOME ASSISTANT]:\n"
        f"Đây là danh sách trạng thái hiện tại của các thiết bị.\n"
        f"Nguyên tắc trả lời:\n"
        f"1. Nếu user hỏi TỔNG QUAN (ví dụ: trạng thái nhà): Hãy trình bày theo ĐÚNG THỨ TỰ sau để đảm bảo luôn đầy đủ, không bị thiếu sót ngẫu nhiên:\n"
        f"   - An ninh & Cửa: Trạng thái cửa chính, khoá, các cảm biến chuyển động/khói.\n"
        f"   - Nhiệt độ & Môi trường: Quạt, Điều hoà, nhiệt độ/độ ẩm các phòng, thời tiết/AQI ngoài trời.\n"
        f"   - Ánh sáng: Gom nhóm trạng thái của toàn bộ các đèn.\n"
        f"   - Thiết bị & Điện năng: Aptomat tổng, công suất, điện tiêu thụ, bình nóng lạnh.\n"
        f"   - Pin: Chỉ nhắc đến các thiết bị sắp hết pin (0-15%) hoặc cảnh báo cần thiết.\n"
        f"   - Sự kiện & Âm lịch: Lịch âm, ngày rằm, ngày giỗ.\n"
        f"   Tuyệt đối BỎ QUA các thông số kỹ thuật mạng (như Remote UI, Ping, thiết bị nội bộ) không liên quan đến sinh hoạt.\n"
        f"2. Nếu user hỏi THIẾT BỊ CỤ THỂ: Trả lời CHỈ BẰNG 1 CÂU DUY NHẤT (ví dụ: 'Đèn phòng học đang tắt'). TUYỆT ĐỐI CẤM giải thích dài dòng. CẤM nhắc đến các thông số phụ (như manual, auto, công tắc, automation) trừ khi user chủ động hỏi.\n"
        f"Mỗi dòng dữ liệu bên dưới có định dạng: `Tên (entity_id) | Trạng thái`.\n\n"
        f"{live_summary}\n"
    )

    # Strip static Device Registry (server's own) — live prefetch replaces it.
    cleaned_messages = []
    for m in messages:
        content = str(m.get("content", ""))
        if m.get("role") == "system" and "Device Registry" in content:
            logger.info({"event": "ha_prefetch_strip_registry", "reason": "live_context_available"})
            continue
        cleaned_messages.append(m)
    messages = cleaned_messages

    # Hard cap: measure current payload size, trim context to fit within 38KB total
    # chatgpt.com free rejects payloads >45KB (413). Leave 7KB headroom for overhead.
    _MAX_PAYLOAD_CHARS = 38_000
    current_payload_chars = sum(len(str(m.get("content", ""))) for m in messages)
    available = _MAX_PAYLOAD_CHARS - current_payload_chars
    if available < 500:
        logger.info({"event": "ha_prefetch_skip_payload_full",
                     "current_chars": current_payload_chars, "max": _MAX_PAYLOAD_CHARS})
        return messages
    if len(msg_context) > available:
        msg_context = msg_context[:available]
        logger.info({"event": "ha_prefetch_context_trimmed",
                     "trimmed_to": available, "original": len(live_summary)})

    # Inject into the LAST user message
    injected = []
    injected_flag = False
    for m in reversed(messages):
        if m.get("role") == "user" and not injected_flag:
            new_content = str(m.get("content", "")) + msg_context
            injected.append({**m, "content": new_content})
            injected_flag = True
        else:
            injected.append(m)

    return list(reversed(injected))



def _has_device_keyword(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in _FORCE_TOOL_KEYWORDS)


def _request_wants_plain_text(messages: list[dict[str, Any]]) -> bool:
    """Heuristic: last user turn looks like a device-control / status query
    aimed at HA voice or a plain-text surface. We strip markdown for these so
    `**tắt**` doesn't leak through as literal asterisks. Skip when the message
    explicitly contains a markdown table — user clearly wants rich formatting.

    Also force plain text when a system message explicitly forbids markdown
    (e.g. the HA "AI Agent" voice prompt: "Format responses using plain text
    only. Do not use markdown..."). This covers search/knowledge answers
    ("giá xăng", "giá vàng") that have no device keyword but still must arrive
    as plain text — while the sibling agent whose prompt says "using markdown"
    is left untouched.
    """
    for m in messages:
        if m.get("role") != "system":
            continue
        sys_text = m.get("content")
        if isinstance(sys_text, str):
            low = sys_text.lower()
            if "plain text only" in low or "do not use markdown" in low or "không dùng markdown" in low:
                return True
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(
                str(p.get("text") or "") for p in content
                if isinstance(p, dict) and p.get("type") in ("text", "input_text")
            )
        else:
            text = ""
        if not text:
            return False
        # Hint: user wrote a table or explicitly asked for one → keep markdown
        if "|--" in text or "bảng" in text.lower() or "table" in text.lower():
            return False
        return _has_device_keyword(text)
    return False


# Markdown patterns we strip. Bold / italic / inline code / strike / headings.
# Tables (lines with `|`) and code fences (```...```) are left alone.
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MD_BOLD_UNDER = re.compile(r"__(.+?)__", re.DOTALL)
_MD_ITALIC_STAR = re.compile(r"(?<![*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![*\w])")
_MD_ITALIC_UNDER = re.compile(r"(?<![_\w])_(?!\s)([^_\n]+?)(?<!\s)_(?![_\w])")
_MD_CODE = re.compile(r"`([^`\n]+)`")
_MD_STRIKE = re.compile(r"~~(.+?)~~", re.DOTALL)
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)

# Backend artifact patterns that should NEVER reach the user.
# ChatGPT web-search backends sometimes leak raw citation markers when the
# response isn't converted to proper inline citations.
#   citeturn0search0 / citeturn0search0turn0search2turn0search8 / ...
#   [oaicite:0] / 【oaicite:0】 / oaicite:N (various brackets)
_CITE_TURN = re.compile(r"cite(?:turn\d+\w+)+")
_OAICITE = re.compile(r"[\[【]?\s*oaicite[^\]】\)]*[\]】\)]?")
# Tool-call args leaking as text: `entity["city","Hà Nội",...]` — match the
# `entity[ "string", "string", ... ]` shape with at least one quoted arg so we
# don't accidentally strip valid `entity[0]` / `entity[i]` code in answers.
# Also handles ChatGPT's private-use Unicode wrappers \ue200...\ue202...\ue201 that
# the web model inserts around entity references in its streamed output.
_ENTITY_LEAK = re.compile(
    r'\ue200?'               # optional Unicode start sentinel
    r'\bentity'
    r'\ue202?'               # optional Unicode bracket-open sentinel
    r'\[\s*"[^"]*"(?:\s*,\s*"[^"]*")*\s*\]'  # ["arg","arg",...] body
    r'\ue201?'               # optional Unicode end sentinel
)
# Internal trace appended by openai_backend_api._api_messages_to_conversation_messages
# when an assistant turn carried tool_calls. The ChatGPT web model sometimes
# echoes this line verbatim at the start of its next answer (observed on
# "trạng thái nhà" → "[System Log: You executed tool GetLiveContext with args {}]").
# It is internal bookkeeping and must never reach the user.
_SYSLOG_LEAK = re.compile(r"\n*\[System Log:[^\]]*\]\n*")
# ChatGPT web model leaks image-gen directives: image_group{"aspect_ratio":...}
_IMAGE_GROUP_LEAK = re.compile(r'\bimage_group\s*\{[^}]*\}', re.DOTALL)
# After entity[] removal, orphan "- :" bullet lines remain
_ORPHAN_BULLET = re.compile(r'^-\s*:\s*$', re.MULTILINE)


def _strip_artifacts_inline(text: str) -> str:
    if not text:
        return text
    out = _CITE_TURN.sub("", text)
    out = _OAICITE.sub("", out)
    out = _ENTITY_LEAK.sub("", out)
    out = _IMAGE_GROUP_LEAK.sub("", out)
    out = _SYSLOG_LEAK.sub("", out)
    out = _ORPHAN_BULLET.sub("", out)
    return out


def _looks_like_json_payload(text: str) -> bool:
    """True when the model returned structured JSON (HA vision / automation).

    HA forces plain-text markdown stripping for Conversation API. That is right
    for voice answers (`**tắt đèn**`) but wrong for camera analysis that must
    stay valid JSON — italic-underscore rules and similar can mangle keys like
    ``humans_detected`` or leave HA structured-data parsers with empty defaults.
    """
    s = (text or "").strip()
    if not s:
        return False
    # fenced ```json ... ```
    if s.startswith("```"):
        body = s.strip("`").lstrip()
        if body.lower().startswith("json"):
            body = body[4:].lstrip()
        s = body
    # HA vision / AI Task field names — never run italic-underscore strip
    # (would turn humans_detected → "humans detected" and break JSON keys)
    if "humans_detected" in s or "animals_detected" in s:
        return True
    if re.search(r'"\w+_\w+"\s*:', s):
        return True
    if not (s.startswith("{") or s.startswith("[")):
        return False
    # Generic JSON object / array
    if s.startswith("{") and (":" in s) and ("\"" in s or "'" in s):
        return True
    if s.startswith("["):
        return True
    return False


def _strip_markdown_inline(text: str) -> str:
    if not text:
        return text
    # Preserve JSON / snake_case structured payloads for HA AI Task
    if _looks_like_json_payload(text):
        return _strip_artifacts_inline(text)
    out = _strip_artifacts_inline(text)
    out = _MD_BOLD.sub(r"\1", out)
    out = _MD_BOLD_UNDER.sub(r"\1", out)
    out = _MD_ITALIC_STAR.sub(r"\1", out)
    out = _MD_ITALIC_UNDER.sub(r"\1", out)
    out = _MD_CODE.sub(r"\1", out)
    out = _MD_STRIKE.sub(r"\1", out)
    out = _MD_HEADING.sub("", out)
    return out


def _strip_markdown_in_response(result: dict[str, Any]) -> dict[str, Any]:
    choices = result.get("choices") or []
    for ch in choices:
        msg = ch.get("message") if isinstance(ch, dict) else None
        if isinstance(msg, dict):
            txt = msg.get("content")
            if isinstance(txt, str):
                msg["content"] = _strip_markdown_inline(txt)
    return result


def _strip_markdown_in_stream(it: Iterator[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Collect ALL content chunks, strip markdown on the joined text, then
    replay them as: pass-through (non-content chunks) + one stripped content
    chunk just before the finish_reason chunk.

    Why not stream-strip incrementally: markdown markers like `**` can span
    multiple chunks and the OpenAI streaming protocol has no way to "un-emit"
    a character already sent. Per-chunk strip heuristics leak the opening
    marker when its close hasn't arrived yet. Device-control responses are
    short (~100 chars) so dropping live-typing UX is acceptable.

    Tool-call chunks (delta.tool_calls) pass through unchanged so MCP/HA
    server-side execution still works.
    """
    pending: list[dict[str, Any]] = []
    full_text = ""
    emitted_final = False
    for chunk in it:
        try:
            choices = chunk.get("choices") or []
            has_finish = False
            has_content = False
            for ch in choices:
                if not isinstance(ch, dict):
                    continue
                if ch.get("finish_reason"):
                    has_finish = True
                delta = ch.get("delta")
                if isinstance(delta, dict):
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        full_text += content
                        # Strip content from THIS chunk; we'll re-emit the
                        # whole stripped text just before the finish chunk.
                        delta["content"] = ""
                        has_content = True

            if has_finish and not emitted_final and full_text:
                import logging
                logging.getLogger("uvicorn.error").info({"event": "debug_final_stream", "text": full_text[:1000]})
                
                # Emit the stripped full text as a content chunk first
                stripped = _strip_markdown_inline(full_text)
                content_chunk = {
                    "id": chunk.get("id"),
                    "object": chunk.get("object"),
                    "created": chunk.get("created"),
                    "model": chunk.get("model"),
                    "choices": [{
                        "index": 0,
                        "delta": {"content": stripped},
                        "finish_reason": None,
                    }],
                }
                yield content_chunk
                emitted_final = True
        except Exception:
            pass
        yield chunk


def _inject_tool_force_hint(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    # Legacy: No longer used since HA redesigned
    return messages


def _stream_chatgpt_addon(backend, messages, model, tools, tool_choice):
    """Stream from chatgpt.com backend, extracting XML tool calls from response."""
    messages = _inject_tool_force_hint(messages, tools)
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    sent_role = False
    accumulated = ""
    request = ConversationRequest(model=model, messages=messages, tools=tools, tool_choice=tool_choice)
    for delta_text in stream_text_deltas(backend, request):
        accumulated += delta_text
        if not sent_role:
            sent_role = True
            yield completion_chunk(model, {"role": "assistant", "content": delta_text}, None, completion_id, created)
        else:
            yield completion_chunk(model, {"content": delta_text}, None, completion_id, created)

    if tools:
        tool_calls = _extract_xml_tool_calls_from_text(accumulated)
        if tool_calls:
            yield {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"tool_calls": tool_calls}, "finish_reason": None}],
            }

    if not sent_role:
        yield completion_chunk(model, {"role": "assistant", "content": ""}, None, completion_id, created)
    yield completion_chunk(model, {}, "stop", completion_id, created)


def _chatgpt_addon_completion(model, messages, tools, tool_choice):
    """Non-streaming chatgpt.com backend, extracting XML tool calls from response."""
    messages = _inject_tool_force_hint(messages, tools)
    backend = text_backend()
    request = ConversationRequest(model=model, messages=messages, tools=tools, tool_choice=tool_choice)
    content = collect_text(backend, request)

    if tools:
        tool_calls = _extract_xml_tool_calls_from_text(content)
        if tool_calls:
            return {
                "id": f"chatcmpl-{uuid.uuid4().hex}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": tool_calls,
                    },
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens": count_message_tokens(messages, model),
                    "completion_tokens": count_text_tokens(content, model),
                    "total_tokens": count_message_tokens(messages, model) + count_text_tokens(content, model),
                },
            }

    return completion_response(model, content, messages=messages)


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

    # Resolve auto using enabled_models order from settings
    if opencode_model == "auto" or not opencode_model:
        ms = config.data.get("model_settings") or {}
        enabled = (ms.get("enabled_models") or {}).get("opencode") if isinstance(ms, dict) else None
        if isinstance(enabled, list):
            for m in enabled:
                m = str(m).strip()
                if not m or m == "auto":
                    continue
                if m.startswith("oc/"):
                    m = m[3:]
                if m:
                    opencode_model = m
                    break

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
        tool_calls = _extract_tool_calls_from_text(content) or _extract_xml_tool_calls_from_text(content)
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


def _extract_xml_tool_calls_from_text(text: str) -> list[dict[str, Any]] | None:
    """Parse XML-wrapped tool calls from chatgpt.com backend text responses.

    The AI is instructed by _build_tool_prompt to wrap tool calls in:
    ```xml
    <tool_call name="tool_name">{"arg": "value"}</tool_call>
    ```

    Returns OpenAI-format tool_calls list, or None if no tool calls found.
    """
    if not text or not text.strip():
        return None

    import re as _re

    # Prefer matches inside ```xml ... ``` fenced blocks
    fence_pattern = _re.compile(r'```(?:xml)?\s*\n?(.*?)```', _re.DOTALL)
    fence_matches = fence_pattern.findall(text)
    search_text = " ".join(fence_matches) if fence_matches else text

    tool_calls = []
    seen_names: set[str] = set()

    for match in TOOL_CALL_RE.finditer(search_text):
        name = match.group(1).strip()
        args_text = match.group(2).strip()
        try:
            if args_text:
                import re as _re
                def _escape_nl(m):
                    return m.group(0).replace('\n', '\\n').replace('\r', '\\r')
                # Escape unescaped newlines inside JSON string values
                args_text_fixed = _re.sub(r'".*?"', _escape_nl, args_text, flags=_re.DOTALL)
                args = json.loads(args_text_fixed)
            else:
                args = {}
            if not isinstance(args, dict):
                args = {}
        except (json.JSONDecodeError, TypeError):
            logger.warning({"event": "xml_tool_call_parse_failed", "name": name, "args_raw": args_text[:200]})
            continue

        if name in seen_names:
            continue
        seen_names.add(name)

        tool_calls.append({
            "id": f"call_{uuid.uuid4().hex[:12]}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(args, ensure_ascii=False),
            },
        })

    # Self-closing <tool_call name="X"/>
    for match in TOOL_CALL_SELF_CLOSING_RE.finditer(search_text):
        name = match.group(1).strip()
        if name not in seen_names:
            seen_names.add(name)
            tool_calls.append({
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            })

    return tool_calls if tool_calls else None


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

    pure_model = model
    for _p in ("cx/", "codex/", "paid/"):
        if pure_model.startswith(_p):
            pure_model = pure_model[len(_p):]
            break
    if not pure_model or pure_model == "auto":
        pure_model = "auto"

    logger.info({
        "event": "openai_oauth_chat",
        "model": pure_model,
        "stream": stream,
    })

    temperature = body.get("temperature")
    max_tokens = body.get("max_tokens")
    force_effort = body.get("_force_effort")

    attempted: set[str] = set()
    last_error = ""
    usage_limit_hits = 0
    max_account_switches = 8  # codext-style: try up to 8 accounts before giving up

    while True:
        try:
            token = codex_oauth.get_token_for_request(attempted)
        except RuntimeError as exc:
            raise RuntimeError(str(exc))  # Raise so combo can fallback

        if token in attempted or usage_limit_hits >= max_account_switches:
            break
        attempted.add(token)

        # A paid account that landed in the codex pool *by plan only* (logged
        # in via Google → chatgpt.com web JWT, no real Codex token) is tagged
        # by plan, NOT by a "codex" type. Route it to the shared chatgpt.com
        # transport instead of the Codex responses API. We key off the account
        # TYPE tag (not JWT introspection): a real Codex onboard always tags
        # type="codex"; detect_token_type() is unreliable here because it
        # returns "google" for codex tokens issued through a Google login
        # before it ever checks chatgpt_account_id. "phân nhóm theo plan, tự
        # đổi route". On any lookup failure, default to the Codex path.
        try:
            _acc = account_service.get_account(token) or {}
            _is_real_codex = "codex" in str(_acc.get("type") or "").split(",")
        except Exception as _exc:
            logger.warning({"event": "codex_type_lookup_failed", "error": str(_exc)[:120]})
            _is_real_codex = True
        if not _is_real_codex:
            from services.providers.chatgpt_free import call_chatgpt_web
            logger.info({"event": "codex_webjwt_fallback", "reason": "paid_plan_no_codex_token"})
            account_service.mark_text_used(token)
            return call_chatgpt_web(token, pure_model, messages, tools, tool_choice, stream, body)

        try:
            if stream:
                result = codex_oauth.chat_completions(
                    access_token=token, messages=messages, model=pure_model,
                    stream=True, temperature=temperature, max_tokens=max_tokens,
                    tools=tools, tool_choice=tool_choice, force_effort=force_effort,
                )
                # On successful stream start, clear any parked resume for this token
                try:
                    from services.account_switch_resume import account_switch_resume
                    account_switch_resume.clear_parked(token[:40], reason="stream_started")
                except Exception:
                    pass
                return result
            else:
                result = codex_oauth.chat_completions(
                    access_token=token, messages=messages, model=pure_model,
                    stream=False, temperature=temperature, max_tokens=max_tokens,
                    tools=tools, tool_choice=tool_choice, force_effort=force_effort,
                )
                account_service.mark_text_used(token)
                # Clear any parked resume on success
                try:
                    from services.account_switch_resume import account_switch_resume
                    account_switch_resume.clear_parked(token[:40], reason="success")
                except Exception:
                    pass
                return result
        except Exception as exc:
            last_error = str(exc)
            err_lower = last_error.lower()
            # On 401/expired → skip this token, try next
            if any(x in err_lower for x in ("expired", "401")):
                continue
            # On usage limit → codext-style: park resume prompt, demote, try next account.
            # NOT a token-refresh case (probe: refresh JWT still 429 same resets_at).
            if any(x in err_lower for x in ("usage_limit", "quota", "capacity")):
                usage_limit_hits += 1
                # Park a recovery prompt for this account (codext-style)
                try:
                    if config.auto_switch_on_rate_limit:
                        from services.account_switch_resume import account_switch_resume
                        resume_prompt = config.usage_limit_resume_prompt
                        if resume_prompt is not None:
                            account_switch_resume.set_resume_prompt(resume_prompt)
                        account_switch_resume.park_task(
                            account_id=token[:40],
                            model=pure_model,
                            messages=messages,
                        )
                except Exception:
                    pass
                # Account is already demoted + marked limited in the provider,
                # so the next get_token_for_request() will pick the NEXT account.
                # Do not refresh_token here — quota ≠ expired JWT.
                continue
            # On 400/429 → try next token
            if any(x in err_lower for x in ("400", "429", "rate")):
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
        # Try enabled_models order first, then provider config, then default
        ms = config.data.get("model_settings") or {}
        enabled = (ms.get("enabled_models") or {}).get("gemini_free") if isinstance(ms, dict) else None
        chosen = ""
        if isinstance(enabled, list):
            for m in enabled:
                m = str(m).strip()
                if not m or m == "auto":
                    continue
                for prefix in ("gemini/", "gemini_free/"):
                    if m.startswith(prefix):
                        m = m[len(prefix):]
                        break
                if m:
                    chosen = m
                    break
        if not chosen:
            provider_cfg = (config.data.get("providers") or {}).get("gemini_free") or {}
            chosen = str(provider_cfg.get("model") or "") or GEMINI_DEFAULT_MODEL
        pure_model = chosen

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


def _handle_antigravity_chat(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    stream: bool,
    body: dict[str, Any],
) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """Use Antigravity rotated Google Cloud companion tokens for chat completions."""
    from services.providers.antigravity import antigravity_provider

    pure_model = model[3:] if model.startswith("ag/") else model
    if not pure_model or pure_model == "auto":
        ms = config.data.get("model_settings") or {}
        enabled = (ms.get("enabled_models") or {}).get("antigravity") if isinstance(ms, dict) else None
        chosen = ""
        if isinstance(enabled, list):
            for m in enabled:
                m = str(m).strip()
                if not m or m == "auto":
                    continue
                if m.startswith("ag/"):
                    m = m[3:]
                if m:
                    chosen = m
                    break
        pure_model = chosen or "gemini-3.1-pro-high"

    logger.info({
        "event": "antigravity_chat",
        "model": pure_model,
        "stream": stream,
    })

    temperature = body.get("temperature")
    max_tokens = body.get("max_tokens")

    attempted: set[str] = set()
    last_error = ""

    while True:
        try:
            account = antigravity_provider.get_token_for_request(attempted)
        except RuntimeError as exc:
            raise RuntimeError(str(exc))

        token = account.get("access_token", "")
        if not token or token in attempted:
            break
        attempted.add(token)

        try:
            if stream:
                return antigravity_provider.chat_completions(
                    account=account, messages=messages, model=pure_model,
                    stream=True, temperature=temperature, max_tokens=max_tokens,
                    tools=tools, tool_choice=tool_choice,
                )
            else:
                result = antigravity_provider.chat_completions(
                    account=account, messages=messages, model=pure_model,
                    stream=False, temperature=temperature, max_tokens=max_tokens,
                    tools=tools, tool_choice=tool_choice,
                )
                account_service.mark_text_used(token)
                return result
        except Exception as exc:
            last_error = str(exc)
            # On 401/expired → skip this token, try next
            if any(x in last_error.lower() for x in ("expired", "401", "unauthorized")):
                continue
            # On 400/429/quota → try next
            if any(x in last_error.lower() for x in ("400", "429", "rate", "quota")):
                continue
            break

    raise RuntimeError(f"Antigravity error: {last_error}")


def _messages_size(messages: list[dict[str, Any]] | None) -> int:
    """Total character count across all message content — used to detect
    whether search_service or HA context injected anything new."""
    if not messages:
        return 0
    total = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += len(c)
        elif isinstance(c, list):
            for part in c:
                if isinstance(part, dict):
                    total += len(str(part.get("text", "")))
    return total


def _messages_have_images(messages: list[dict[str, Any]] | None) -> bool:
    """True when any message carries an image_url / input_image part.

    Used to detect vision requests so we can skip MCP/HA tool injection — a
    "phân tích ảnh" task never needs Wikipedia / weather / device control,
    and the 60+ tool definitions just bloat the prompt + slow vision models
    that have to scan the tool list before answering.
    """
    for m in messages or []:
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") in ("image_url", "input_image"):
                return True
    return False


_STATUS_QUERY_KEYWORDS = [
    "trạng thái", "tình trạng", "liệt kê", "có những", "kiểm tra", "thế nào",
    "ra sao", "tổng quan", "như thế nào", "đang bật", "đang tắt", "bao nhiêu",
]
_CONTROL_VERBS = [
    "bật", "tắt", "mở", "đóng", "đặt", "chỉnh", "tăng", "giảm", "kích hoạt",
    "khởi động", "dừng", "khoá", "khóa", "mở khoá", "mở khóa", "set ", "tạo", "sửa", "xoá", "đọc", "gửi",
    # Cách nói điều khiển khác (skip MCP): ngắt/cúp/ngừng/vặn… Bỏ các từ dễ
    # nhập nhằng (lật→"lật lọng", gạt→"lừa gạt", kích→"kích thước") — những câu
    # đó vẫn bắt được qua DANH TỪ THIẾT BỊ bên dưới, an toàn hơn.
    "ngắt", "cúp", "ngừng", "tạm dừng", "vặn",
    "turn ", "toggle", "switch ",
]

# Danh từ thiết bị nhà — neo nhận diện lệnh smart-home theo DANH TỪ (hữu hạn,
# đặc trưng) thay vì đuổi theo động từ vô hạn/vùng miền. Câu điều khiển luôn gọi
# tên thiết bị nên đây là tín hiệu đáng tin để skip MCP.
_HOME_NOUNS = [
    "đèn", "quạt", "điều hòa", "điều hoà", "máy lạnh", "tivi", "ti vi",
    "rèm", "ổ cắm", "ổ điện", "công tắc", "bình nóng", "máy bơm", "máy giặt",
    "cảm biến", "loa", "máy lọc", "home assistant", "hass", "dịch vụ", "service", "thông báo", "notify",
    "automation", "kịch bản", "script", "log", "nhật ký", "pin",
]


def _is_status_only_query(text: str) -> bool:
    """True for a pure status/listing question with NO control verb. Such a
    query is answered entirely from the prefetched live context, so we can ship
    ZERO tools — HA otherwise attaches ~40 control tools whose schemas bloat the
    free-account payload past chatgpt.com's limit (→ 413 → generic reply)."""
    t = (text or "").lower()
    complex_kws = ["automation", "tự động", "tu dong", "log", "nhật ký", "nhat ky", "kịch bản", "kich ban", "script", "yaml", "config", "cài đặt", "cai dat", "home assistant", "hass", "dịch vụ", "service", "thông báo", "notify"]
    if any(kw in t for kw in complex_kws):
        return False
    if not any(k in t for k in _STATUS_QUERY_KEYWORDS):
        return False
    if any(v in t for v in _CONTROL_VERBS):
        return False
    return True


def _is_smarthome_query(text: str) -> bool:
    """True for a smart-home command/status query — has a control verb
    (bật/tắt/ngắt…) OR names a home device (đèn/quạt/điều hòa…). Tiếng Việt có
    vô số động từ đồng nghĩa + vùng miền, nên ta neo vào DANH TỪ THIẾT BỊ: câu
    điều khiển luôn gọi tên thiết bị → bắt được dù động từ lạ. Những câu này chỉ
    cần tool điều khiển của HA, không cần ~43 MCP info tools → skip để nhẹ
    payload. Câu hỏi info (thời tiết/vàng/luật…) không có verb lẫn danh từ thiết
    bị → giữ MCP."""
    t = (text or "").lower()
    return any(v in t for v in _CONTROL_VERBS) or any(n in t for n in _HOME_NOUNS)


def _inject_server_admin_context(messages: list[dict[str, Any]], user_text: str) -> list[dict[str, Any]]:
    """For a server-admin query, append the declared-server list + 'use ssh_run,
    don't ask the user' instruction to the last user message. Keeps the model
    from treating a server name (nvr/ha) as a device it must ask about."""
    try:
        from services.mcp_client import is_server_admin_query, server_admin_system_hint
        if not is_server_admin_query(user_text, messages):
            return messages
        hint = server_admin_system_hint()
        if not hint:
            return messages
        out = list(messages)
        for i in range(len(out) - 1, -1, -1):
            if out[i].get("role") == "user":
                out[i] = {**out[i], "content": str(out[i].get("content", "")) + "\n\n" + hint}
                logger.info({"event": "server_admin_context_injected"})
                return out
        return out
    except Exception as exc:
        logger.warning({"event": "server_admin_context_failed", "error": str(exc)})
        return messages


def _inject_mcp_tools(
    tools: list[dict[str, Any]] | None,
    skip_ha_search: bool = False,
    is_vision: bool = False,
    search_injected: bool = False,
    user_text: str = "",
    is_free_model: bool = False,
    prefetched: bool = False,
    messages: list[dict[str, Any]] | None = None,
    no_smart_home: bool = False,
    no_server_admin: bool = False,
) -> list[dict[str, Any]] | None:
    """Inject tools from enabled MCP servers + HA into the tools list.

    `no_smart_home` / `no_server_admin`: thread bị lọc chức năng (thiếu nhóm
    homeassistant / server) → TUYỆT ĐỐI không inject HA tools / ssh-fs tools,
    dù câu hỏi trông giống smart-home hay server-admin."""
    logger.info({"event": "mcp_inject_start", "input_tools": len(tools or [])})
    try:
        from services.mcp_client import is_server_admin_query
        _is_admin = (not no_server_admin) and is_server_admin_query(user_text, messages)

        # Realtime data already fetched server-side and injected as context →
        # ship NO tool so the model just formats it (one round-trip, no re-call).
        if prefetched:
            logger.info({"event": "mcp_inject_skipped", "reason": "prefetched_realtime"})
            return tools if tools else None

        # Vision request — skip all injection. Return the caller's tools as-is.
        if is_vision:
            logger.info({"event": "mcp_inject_skipped", "reason": "vision_request"})
            return tools if tools else None

        # Pure status/listing query whose answer is already in the prefetched
        # live context → ship NO tools. Drops HA's ~40 control-tool schemas
        # (the dominant payload bloat that 413s the free backend and makes the
        # model reply "what do you want me to do?"). Control queries keep tools.
        if (skip_ha_search or is_free_model) and _is_status_only_query(user_text) and not _is_admin:
            logger.info({"event": "mcp_inject_skipped", "reason": "status_only_query_free_or_ha"})
            return None

        if is_free_model and not _is_smarthome_query(user_text) and not _is_admin:
            logger.info({"event": "mcp_inject_skipped", "reason": "free_model_no_agentic_loop"})
            return tools if tools else None

        # Search results already injected. We used to skip tool injection here
        # to save prompt space, but users want to see explicit tool calls
        # (e.g. for weather) or fallback to them if search timed out.
        if search_injected:
            logger.info({"event": "mcp_inject_proceeding", "reason": "search_injected_but_tools_requested"})
            # Do NOT return early, let the tools be injected so the LLM can explicitly call them if needed.

        from services.mcp_client import get_relevant_mcp_tools
        from services.ha_client import get_ha_tools

        # Skip the MCP discovery + injection when the prompt already carries the
        # HA registry — those tools won't be useful here and the LLM may waste
        # a round-trip calling one.
        if _is_admin:
            # Server-admin query (nvr/ha ssh/file op) → inject only ssh_/fs_ tools.
            mcp_tools = get_relevant_mcp_tools(user_text, messages)
            logger.info({"event": "mcp_inject_got_tools", "reason": "server_admin", "count": len(mcp_tools)})
        elif skip_ha_search:
            mcp_tools = []
            logger.info({"event": "mcp_inject_skipped", "reason": "ha_context_injected"})
        elif not tools and _is_trivial_chat(user_text):
            # Trivial greeting/chat with no explicit tools requested — skip
            # all 43 MCP tools. The payload would exceed ChatGPT's per-account
            # size limit and cause 413 errors. Keep HA tools for smart home.
            mcp_tools = []
            logger.info({"event": "mcp_inject_skipped", "reason": "trivial_chat"})
        elif not no_smart_home and _is_smarthome_query(user_text):
            # For simple smarthome queries (status check, turn on/off), we skip
            # external MCP tools to keep the payload tiny (fast TTFT ~1s). The 4
            # native HA tools (GetLiveContext, ha_call_service...) are always kept
            # below and are enough for 99% of daily use.
            # But if the user asks for complex tasks (automation, logs, config),
            # we must inject the full external MCP tools (like ha-mcp's 78 tools).
            complex_kws = ["automation", "tự động", "tu dong", "log", "nhật ký", "nhat ky", "kịch bản", "kich ban", "script", "yaml", "config", "cài đặt", "cai dat", "home assistant", "hass", "dịch vụ", "service", "thông báo", "notify"]
            if any(kw in user_text.lower() for kw in complex_kws):
                from services.mcp_client import get_enabled_mcp_tools
                mcp_tools = get_enabled_mcp_tools()
                logger.info({"event": "mcp_inject_got_tools", "reason": "complex_smarthome_kept_mcp", "count": len(mcp_tools)})
            else:
                mcp_tools = []
                logger.info({"event": "mcp_inject_skipped", "reason": "simple_smarthome_query"})
        else:
            mcp_tools = get_relevant_mcp_tools(user_text, messages)
            logger.info({"event": "mcp_inject_got_tools", "count": len(mcp_tools), "relevant": True})

        if no_server_admin and mcp_tools:
            # Thread bị lọc thiếu nhóm 'server' — get_relevant_mcp_tools vẫn có
            # thể trả ssh_/fs_ khi câu trông giống server-admin → lột ra ở đây.
            mcp_tools = [t for t in mcp_tools
                         if not (t.get("function", {}) or {}).get("name", "").startswith(("ssh_", "fs_"))]

        tools = list(tools or [])
        existing_names = {t.get("function", {}).get("name", "") for t in tools}

        client_is_ha = any(name.startswith("Hass") or name == "GetLiveContext" for name in existing_names)
        # HA clients bring their own control tools (HassTurnOn, etc.) but
        # we keep read-only query tools so the LLM can call GetLiveContext
        # to fetch live device state, matching how Gemini pipeline works.
        if no_smart_home:
            # Thread bị lọc chức năng, không có nhóm homeassistant → KHÔNG đưa
            # HA tools cho model (kẻo nó tự trả lời/điều khiển nhà, qua mặt lọc).
            ha_tools = []
            logger.info({"event": "ha_tools_skipped", "reason": "thread_filter_no_homeassistant"})
        elif _is_admin:
            # Server op (ssh/file) never needs HA device tools — keep payload lean.
            ha_tools = []
        elif client_is_ha:
            ha_tools = get_ha_tools()
            _keep_readonly = {"GetLiveContext", "ha_search_entities", "ha_get_state", "ha_call_service",
                              "ha_upsert_config", "ha_upsert_helper", "ha_read_config_file",
                              "ha_write_config_file", "ha_home_map", "ha_pyscript_setup"}
            ha_tools = [t for t in ha_tools if t.get("function", {}).get("name", "") in _keep_readonly]
        else:
            ha_tools = get_ha_tools()

        # Keep all HA tools. We used to drop read-only tools here assuming the
        # context was prefetched, but only ChatGPT Free actually prefetches.
        # Gemini needs these tools to dynamically query states.
        if skip_ha_search:
            logger.info({"event": "ha_read_tools_kept", "reason": "model_needs_tools"})
        all_new_tools = mcp_tools + ha_tools
        if not all_new_tools:
            return tools if tools else None

        for mt in all_new_tools:
            if mt.get("function", {}).get("name", "") not in existing_names:
                tools.append(mt)
        logger.info({"event": "mcp_tools_injected", "mcp_count": len(mcp_tools),
                     "ha_count": len(ha_tools), "total_tools": len(tools)})
        return tools
    except Exception as exc:
        logger.warning({"event": "mcp_tools_inject_failed", "error": str(exc)})
        return tools


def _execute_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> str | None:
    """Execute an MCP or HA tool call and return the result text."""
    # Try MCP first
    try:
        from services.mcp_client import call_mcp_tool
        result = call_mcp_tool(tool_name, arguments)
        if result is not None:
            return result
    except Exception as exc:
        logger.warning({"event": "mcp_tool_call_failed", "tool": tool_name, "error": str(exc)})
    # Try HA tools
    try:
        from services.ha_client import execute_ha_tool
        result = execute_ha_tool(tool_name, arguments)
        if result is not None:
            return result
    except Exception as exc:
        logger.warning({"event": "ha_tool_call_failed", "tool": tool_name, "error": str(exc)})
    return None
