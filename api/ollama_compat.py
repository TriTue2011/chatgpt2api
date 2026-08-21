"""Lớp dịch giao thức Ollama → đường chat OpenAI sẵn có của gateway.

Vì sao cần: Home Assistant có sẵn integration **Ollama** (tạo được entity
`ai_task` mà blueprint cảnh báo camera đòi), nhưng nó chỉ nói giao thức Ollama.
Còn hai đầu ta có đều nói OpenAI: gateway này, và llama.cpp chạy model thị giác
tại nhà. Đo 19/08/2026: `GET /api/tags` trên cả llama.cpp lẫn gateway đều không
phải API Ollama (một cái 404, một cái trả trang web), nên HA không kết nối được.

Router này KHÔNG chứa logic AI nào. Nó chỉ đổi hình dạng request/response rồi
gọi đúng `openai_v1_chat_complete.handle` mà `/v1/chat/completions` đang dùng —
mọi thứ phía sau (định tuyến model, privacy gate, ký ức, tool) giữ nguyên.

Ollama gốc không có xác thực. HA vẫn cho nhập API key và gửi kèm header, nên ở
đây dùng CHUNG `require_identity` với các route khác: gateway này mở ra LAN, để
ngỏ một cửa không xác thực là mở luôn đường gọi model cho cả mạng.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterator

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from api.support import require_identity
from services.protocol import openai_v1_chat_complete

logger = logging.getLogger(__name__)

# Ollama đánh dấu thời điểm theo RFC3339; HA chỉ hiển thị lại nên định dạng đủ đúng là được.
def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000000000Z", time.gmtime())


def _danh_sach_model() -> list[str]:
    """Tên model gateway đang phục vụ. Lỗi thì trả rỗng — config flow của HA
    vẫn mở được và người dùng gõ tay tên model."""
    try:
        from services.protocol import openai_v1_models
        data = openai_v1_models.list_models(False, True)
        return [str(m.get("id")) for m in (data.get("data") or []) if m.get("id")]
    except Exception as exc:
        logger.warning({"event": "ollama_list_models_loi", "error": str(exc)[:150]})
        return []


def _doi_messages(messages: list[dict]) -> list[dict]:
    """Ollama để ảnh trong `images` (base64 THUẦN, không có tiền tố data:).
    OpenAI đòi ảnh nằm trong content dạng data URI."""
    ra: list[dict] = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        vai = str(m.get("role") or "user")
        chu = m.get("content")
        anh = m.get("images") or []
        if not anh:
            ra.append({"role": vai, "content": chu if chu is not None else ""})
            continue
        noi: list[dict] = []
        if chu:
            noi.append({"type": "text", "text": str(chu)})
        for a in anh:
            s = str(a or "").strip()
            if not s:
                continue
            # Client tử tế có thể đã kèm sẵn data URI — đừng bọc hai lần.
            url = s if s.startswith("data:") else "data:image/jpeg;base64," + s
            noi.append({"type": "image_url", "image_url": {"url": url}})
        ra.append({"role": vai, "content": noi})
    return ra


def _doi_format(fmt: Any) -> dict | None:
    """`format` của Ollama: "json" hoặc THẲNG một JSON Schema (HA structured
    output gửi kiểu này) → response_format của OpenAI."""
    if not fmt:
        return None
    if isinstance(fmt, str):
        return {"type": "json_object"} if fmt.strip().lower() == "json" else None
    if isinstance(fmt, dict):
        return {"type": "json_schema",
                "json_schema": {"name": "ollama_format", "schema": fmt, "strict": False}}
    return None


def _tra_loi(model: str, noi_dung: str, tool_calls: list | None = None,
             usage: dict | None = None) -> dict:
    msg: dict[str, Any] = {"role": "assistant", "content": noi_dung}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    u = usage or {}
    return {
        "model": model,
        "created_at": _now(),
        "message": msg,
        "done": True,
        "done_reason": "stop",
        "total_duration": 0,
        "load_duration": 0,
        "prompt_eval_count": int(u.get("prompt_tokens") or 0),
        "eval_count": int(u.get("completion_tokens") or 0),
    }


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/version")
    async def version(authorization: str | None = Header(default=None)):
        # HA gọi để dò xem đầu kia có phải Ollama không. Không đòi xác thực ở
        # đây: nó không lộ gì ngoài một chuỗi phiên bản, và bắt xác thực làm
        # config flow của HA báo lỗi mơ hồ trước khi kịp hỏi API key.
        return {"version": "0.5.1-chatgpt2api"}

    @router.get("/api/tags")
    async def tags(authorization: str | None = Header(default=None)):
        require_identity(authorization)
        ds = await run_in_threadpool(_danh_sach_model)
        return {"models": [{
            "name": m, "model": m, "modified_at": _now(), "size": 0, "digest": "",
            "details": {"parent_model": "", "format": "gguf", "family": "",
                        "families": [], "parameter_size": "", "quantization_level": ""},
        } for m in ds]}

    @router.post("/api/show")
    async def show(body: dict, authorization: str | None = Header(default=None)):
        require_identity(authorization)
        ten = str((body or {}).get("model") or (body or {}).get("name") or "").strip()
        if not ten:
            raise HTTPException(status_code=400, detail="model is required")
        # `capabilities` là thứ HA đọc để biết model có nhận ảnh và gọi tool
        # được không. Gateway định tuyến sang nhiều backend khác nhau nên không
        # có cách nào biết chắc cho từng tên model; khai đủ để HA không tự khoá
        # tính năng, còn model không làm được thì lỗi hiện ở lượt gọi thật.
        return {
            "license": "", "modelfile": "", "parameters": "", "template": "",
            "details": {"family": "", "families": [], "parameter_size": "",
                        "quantization_level": ""},
            "model_info": {"general.architecture": "chatgpt2api"},
            "capabilities": ["completion", "vision", "tools", "insert"],
        }

    @router.post("/api/chat")
    async def chat(body: dict, authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        body = body or {}
        model = str(body.get("model") or "").strip()
        if not model:
            raise HTTPException(status_code=400, detail="model is required")

        payload: dict[str, Any] = {
            "model": model,
            "messages": _doi_messages(body.get("messages") or []),
            "stream": bool(body.get("stream")),
            "_principal": str(identity.get("id") or ""),
        }
        rf = _doi_format(body.get("format"))
        if rf:
            payload["response_format"] = rf
        if body.get("tools"):
            payload["tools"] = body["tools"]
        # `options` của Ollama gói tham số sinh; chỉ chuyển những cái có tương ứng.
        opts = body.get("options") or {}
        if isinstance(opts, dict):
            if opts.get("temperature") is not None:
                payload["temperature"] = opts["temperature"]
            # num_predict = số token tối đa sinh ra; -1/0 nghĩa là không giới hạn.
            npd = opts.get("num_predict")
            if isinstance(npd, int) and npd > 0:
                payload["max_tokens"] = npd

        ket_qua = await run_in_threadpool(openai_v1_chat_complete.handle, payload)

        if not payload["stream"]:
            if not isinstance(ket_qua, dict):
                # Lõi trả iterator dù xin non-stream (nhánh hiếm) → gom lại.
                gom = ""
                tc_acc: dict[int, dict[str, Any]] = {}
                for chunk in ket_qua:  # type: ignore[union-attr]
                    delta = _lay_phan(chunk)
                    gom += str(delta.get("content") or "")
                    _gom_tool_delta(tc_acc, delta.get("tool_calls") or [])
                tools = _tool_calls_ollama([tc_acc[i] for i in sorted(tc_acc)])
                return _tra_loi(model, gom, tools or None)
            ch = (ket_qua.get("choices") or [{}])[0]
            msg = ch.get("message") or {}
            return _tra_loi(model, str(msg.get("content") or ""),
                            msg.get("tool_calls"), ket_qua.get("usage"))

        # Ollama stream = JSON từng dòng, KHÔNG phải SSE "data:" như OpenAI.
        def _phat() -> Iterator[bytes]:
            tc_acc: dict[int, dict[str, Any]] = {}
            try:
                if isinstance(ket_qua, dict):
                    ch = (ket_qua.get("choices") or [{}])[0]
                    msg = _message_ollama(ch.get("message") or {})
                    yield (json.dumps({"model": model, "created_at": _now(),
                                       "message": msg,
                                       "done": False}, ensure_ascii=False) + "\n").encode()
                else:
                    for chunk in ket_qua:  # type: ignore[union-attr]
                        delta = _lay_phan(chunk)
                        noi = str(delta.get("content") or "")
                        _gom_tool_delta(tc_acc, delta.get("tool_calls") or [])
                        if noi:
                            yield (json.dumps({"model": model, "created_at": _now(),
                                               "message": {"role": "assistant",
                                                           "content": noi},
                                               "done": False}, ensure_ascii=False) + "\n").encode()
                    if tc_acc:
                        tools = _tool_calls_ollama([tc_acc[i] for i in sorted(tc_acc)])
                        yield (json.dumps({"model": model, "created_at": _now(),
                                           "message": {"role": "assistant", "content": "",
                                                       "tool_calls": tools},
                                           "done": False}, ensure_ascii=False) + "\n").encode()
            except Exception as exc:
                logger.warning({"event": "ollama_stream_loi", "error": str(exc)[:150]})
            yield (json.dumps(_tra_loi(model, ""), ensure_ascii=False) + "\n").encode()

        return StreamingResponse(_phat(), media_type="application/x-ndjson")

    return router


def _message_ollama(phan: Any) -> dict[str, Any]:
    """Giữ cả chữ lẫn tool call khi đổi một message/delta sang khuôn Ollama."""
    phan = phan if isinstance(phan, dict) else {}
    msg: dict[str, Any] = {
        "role": "assistant",
        "content": str(phan.get("content") or ""),
    }
    if phan.get("tool_calls"):
        msg["tool_calls"] = _tool_calls_ollama(phan["tool_calls"])
    return msg


def _lay_phan(chunk: Any) -> dict[str, Any]:
    try:
        delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
        return delta if isinstance(delta, dict) else {}
    except Exception:
        return {}


def _gom_tool_delta(acc: dict[int, dict[str, Any]], calls: Any) -> None:
    """Ghép name + arguments bị OpenAI chia qua nhiều delta theo cùng index."""
    for tc in calls if isinstance(calls, list) else []:
        if not isinstance(tc, dict):
            continue
        try:
            index = int(tc.get("index") or 0)
        except (TypeError, ValueError):
            index = 0
        slot = acc.setdefault(index, {"id": "", "type": "function",
                                      "function": {"name": "", "arguments": ""}})
        if tc.get("id"):
            slot["id"] = tc["id"]
        if tc.get("type"):
            slot["type"] = tc["type"]
        fn = tc.get("function") or {}
        if isinstance(fn, dict):
            if fn.get("name"):
                slot["function"]["name"] = fn["name"]
            if fn.get("arguments") is not None:
                slot["function"]["arguments"] += str(fn["arguments"])


def _tool_calls_ollama(calls: Any) -> list[dict[str, Any]]:
    """Đổi arguments JSON-string của OpenAI thành object Ollama yêu cầu."""
    ra: list[dict[str, Any]] = []
    for tc in calls if isinstance(calls, list) else []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        if not isinstance(fn, dict):
            continue
        arguments = fn.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                # Giữ nguyên để không làm mất dữ liệu model; client sẽ báo đúng
                # lỗi JSON thay vì nhận một object bịa hoặc một tool call rỗng.
                pass
        moi: dict[str, Any] = {
            "function": {"name": str(fn.get("name") or ""),
                         "arguments": arguments},
        }
        for key in ("id", "type"):
            if tc.get(key):
                moi[key] = tc[key]
        ra.append(moi)
    return ra
