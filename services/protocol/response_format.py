"""OpenAI ``response_format`` support for providers that lack native json_schema.

Home Assistant AI Task (via hass_local_openai_llm) sends::

    response_format: {
      "type": "json_schema",
      "json_schema": {"name": "...", "strict": true, "schema": {...}}
    }

Codex / GMA / free web paths often ignore this field. We:

1. Inject a compact schema instruction into messages (so the model fills fields).
2. Post-process the assistant content into a single-line valid JSON object
   matching the requested properties (defaults for missing keys).

Also supports ``{"type": "json_object"}``.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Iterator

try:
    from utils.log import logger
except Exception:  # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_OBJ = re.compile(r"\{[\s\S]*\}")


def parse_response_format(body: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return normalized meta or None if not a JSON structured request."""
    if not isinstance(body, dict):
        return None
    rf = body.get("response_format")
    if not isinstance(rf, dict):
        return None
    rtype = str(rf.get("type") or "").strip().lower()
    if rtype not in {"json_object", "json_schema"}:
        return None
    name = ""
    schema: dict[str, Any] = {}
    if rtype == "json_schema":
        js = rf.get("json_schema") if isinstance(rf.get("json_schema"), dict) else {}
        name = str(js.get("name") or "response").strip() or "response"
        raw_schema = js.get("schema")
        if isinstance(raw_schema, dict):
            schema = raw_schema
        # Some clients nest schema under json_schema itself without "schema"
        elif any(k in js for k in ("properties", "type")):
            schema = {k: v for k, v in js.items() if k not in {"name", "strict"}}
    return {
        "type": rtype,
        "name": name,
        "schema": schema,
        "strict": bool((rf.get("json_schema") or {}).get("strict")) if rtype == "json_schema" else False,
    }


def _schema_properties(schema: dict[str, Any]) -> dict[str, Any]:
    props = schema.get("properties")
    return props if isinstance(props, dict) else {}


def _prop_type(info: Any) -> str:
    if not isinstance(info, dict):
        return "string"
    t = info.get("type")
    if isinstance(t, list):
        for x in t:
            if x and x != "null":
                return str(x)
        return "string"
    return str(t or "string")


def _default_for_type(typ: str) -> Any:
    if typ in {"integer", "number"}:
        return 0
    if typ == "boolean":
        return False
    if typ == "array":
        return []
    if typ == "object":
        return {}
    return ""


def _describe_schema(schema: dict[str, Any]) -> str:
    props = _schema_properties(schema)
    if not props:
        return "{}"
    required = schema.get("required")
    req = set(required) if isinstance(required, list) else set(props.keys())
    lines: list[str] = []
    example: dict[str, Any] = {}
    for key, info in props.items():
        typ = _prop_type(info)
        desc = ""
        if isinstance(info, dict):
            desc = str(info.get("description") or "").strip()
            desc = re.sub(r"\s+", " ", desc)[:220]
        flag = "required" if key in req else "optional"
        lines.append(f'- "{key}" ({typ}, {flag}){": " + desc if desc else ""}')
        example[key] = _default_for_type(typ)
    sample = json.dumps(example, ensure_ascii=False, separators=(",", ":"))
    return (
        "Return ONLY one JSON object (no markdown fences, no prose before/after).\n"
        "Keys and types:\n"
        + "\n".join(lines)
        + "\nExact shape example (replace values):\n"
        + sample
        + "\nRules: Vietnamese text with diacritics where applicable; "
        "numbers as JSON numbers not strings; empty string \"\" when no text; "
        "single line preferred."
    )


def build_instruction(meta: dict[str, Any], *, has_images: bool = False) -> str:
    if meta.get("type") == "json_object":
        base = (
            "You must respond with a single valid JSON object only. "
            "No markdown code fences, no explanation outside the JSON."
        )
    else:
        schema = meta.get("schema") if isinstance(meta.get("schema"), dict) else {}
        name = str(meta.get("name") or "response")
        header = f"Structured output required (json_schema name={name}).\n"
        base = header + _describe_schema(schema)
    if has_images:
        base += (
            "\n\nIMAGE GROUNDING (mandatory):\n"
            "- Only describe people/objects VISIBLE in the attached image(s).\n"
            "- Do NOT invent people, rooms, clothing, or actions not clearly shown.\n"
            "- If the image is empty/blurry/uncertain: set integer counts to 0 and "
            "say uncertainty in the summary fields.\n"
            "- Prefer under-counting over hallucinating extra people."
        )
    return base


# Dấu nhận biết tin nhắn system do CHÍNH máy chủ chèn để ép JSON. Là hằng số ở
# tầng module vì nơi khác cũng phải nhận ra nó: `_chi_giu_loi_dan_anh` bỏ prompt
# hệ thống của HA nhưng PHẢI giữ tin này lại — bỏ nó là model phân tích đúng mà
# trả lời văn xuôi, rồi khâu ép JSON điền mặc định thành "0 người".
MARKER_JSON_SCHEMA = "[response_format_json_schema]"


def inject_response_format_prompt(body: dict[str, Any]) -> dict[str, Any]:
    """Mutate body messages to enforce JSON schema for non-native providers.

    Stores ``_response_format_meta`` on body for post-processing.

    Only runs when the client sent ``response_format`` (json_schema / json_object).
    Plain chat / image Q&A without response_format is left alone.
    """
    meta = parse_response_format(body)
    if not meta:
        return body
    body["_response_format_meta"] = meta
    body["_structured_output"] = True
    instruction = build_instruction(meta, has_images=body_has_images(body))
    messages = body.get("messages")
    if not isinstance(messages, list):
        messages = []
        body["messages"] = messages
    # Avoid double-inject on retries
    marker = MARKER_JSON_SCHEMA
    for m in messages:
        if isinstance(m, dict) and marker in str(m.get("content") or ""):
            return body
    sys_msg = {
        "role": "system",
        "content": f"{marker}\n{instruction}",
    }
    # Insert after existing system messages so HA task instructions stay first
    insert_at = 0
    for i, m in enumerate(messages):
        if isinstance(m, dict) and m.get("role") == "system":
            insert_at = i + 1
        else:
            break
    messages.insert(insert_at, sys_msg)
    logger.info({
        "event": "response_format_injected",
        "type": meta.get("type"),
        "name": meta.get("name"),
        "props": list(_schema_properties(meta.get("schema") or {}).keys())[:20],
        "has_images": body_has_images(body),
    })
    return body


def extract_json_object(text: str) -> dict[str, Any] | None:
    if not text or not str(text).strip():
        return None
    s = str(text).strip()
    # strip think tags if any
    s = re.sub(r"<think>[\s\S]*?</think>", "", s, flags=re.I).strip()
    m = _JSON_FENCE.search(s)
    if m:
        s = m.group(1).strip()
    # direct parse
    for candidate in (s,):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
            if isinstance(obj, list) and obj and isinstance(obj[0], dict):
                return obj[0]
        except Exception:
            pass
    # first {...}
    m2 = _OBJ.search(s)
    if m2:
        blob = m2.group(0)
        try:
            obj = json.loads(blob)
            if isinstance(obj, dict):
                return obj
        except Exception:
            # trailing commas / soft fix
            try:
                fixed = re.sub(r",\s*}", "}", blob)
                fixed = re.sub(r",\s*]", "]", fixed)
                obj = json.loads(fixed)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass
    return None


def recover_fields_from_mangled(text: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    """Recover field values when markdown-strip destroyed JSON underscores/quotes.

    Observed mangled form (after italic-underscore strip)::

        humans detected2,humans detected summaryPhát hiện 2 người...,animals detected0,...
    """
    props = _schema_properties(schema)
    if not props or not text:
        return None
    s = str(text)
    # Prefer longer keys first so summary/description beat base name
    keys = sorted(props.keys(), key=lambda k: len(k), reverse=True)
    # Map key → flexible regex (underscore or space)
    spans: list[tuple[int, int, str]] = []
    for key in keys:
        parts = [re.escape(p) for p in key.split("_") if p]
        if not parts:
            continue
        pat = r"[\s_]*".join(parts)
        for m in re.finditer(pat, s, flags=re.I):
            spans.append((m.start(), m.end(), key))
            break  # first occurrence per key
    if not spans:
        return None
    spans.sort(key=lambda x: x[0])
    out: dict[str, Any] = {}
    for i, (start, end, key) in enumerate(spans):
        val_end = spans[i + 1][0] if i + 1 < len(spans) else len(s)
        raw = s[end:val_end]
        # trim separators left by mangled JSON
        raw = raw.lstrip(" \t:=,;\"'{([")
        raw = raw.rstrip(" \t,;\"'})]\n\r")
        # stop at next obvious key fragment if any leftover
        typ = _prop_type(props[key])
        if typ in {"integer", "number"}:
            nm = re.search(r"-?\d+(?:[.,]\d+)?", raw)
            raw = nm.group(0) if nm else "0"
        out[key] = raw
    if not out:
        return None
    logger.info({
        "event": "response_format_recovered_mangled",
        "keys": list(out.keys()),
    })
    return out


def _coerce_value(val: Any, typ: str) -> Any:
    if typ in {"integer", "number"}:
        if val is None or val == "":
            return 0
        try:
            if typ == "integer":
                return int(float(val))
            return float(val)
        except Exception:
            return 0
    if typ == "boolean":
        if isinstance(val, bool):
            return val
        if str(val).strip().lower() in {"1", "true", "yes", "on"}:
            return True
        return False
    if typ == "array":
        return val if isinstance(val, list) else []
    if typ == "object":
        return val if isinstance(val, dict) else {}
    if val is None:
        return ""
    return str(val)


def _normalize_key_map(keys: list[str]) -> dict[str, str]:
    """Map collapsed key (no underscore, lower) → original."""
    out: dict[str, str] = {}
    for k in keys:
        out[re.sub(r"[^a-z0-9]", "", k.lower())] = k
    return out


def coerce_to_schema(data: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Ensure all schema properties present with correct types."""
    props = _schema_properties(schema)
    if not props:
        return data
    collapsed = _normalize_key_map(list(props.keys()))
    # also index incoming keys collapsed
    incoming: dict[str, Any] = {}
    for k, v in data.items():
        incoming[str(k)] = v
        incoming[re.sub(r"[^a-z0-9]", "", str(k).lower())] = v

    out: dict[str, Any] = {}
    for key, info in props.items():
        typ = _prop_type(info)
        if key in data:
            raw = data[key]
        else:
            ck = re.sub(r"[^a-z0-9]", "", key.lower())
            raw = incoming.get(ck, _default_for_type(typ))
        out[key] = _coerce_value(raw, typ)
    return out


class KhongPhanTichDuocAnh(RuntimeError):
    """Model không trả JSON đọc được cho một yêu cầu phân tích ảnh.

    Tồn tại để phân biệt hai chuyện mà bản cũ gộp làm một: "đã phân tích và
    thấy 0 người" với "không phân tích được". Xem :func:`normalize_content`.
    """


def normalize_content(text: str, meta: dict[str, Any] | None, *,
                      cho_phep_mac_dinh: bool = True) -> str:
    """Return single-line JSON string suitable for HA structured parse.

    `cho_phep_mac_dinh=False`: không đọc được JSON thì NÉM
    :class:`KhongPhanTichDuocAnh` thay vì dựng object toàn giá trị mặc định.

    Vì sao phải có công tắc đó — đây là lỗi nguy hiểm nhất đã gặp: schema camera
    khai `humans_detected` kiểu integer, mà mặc định của integer là **0**. Nên
    khi mọi provider vision đều hỏng và request rơi xuống một model CHỈ-CHỮ,
    model đó trả vài dòng văn xuôi, hàm này không bóc được JSON, rồi dựng ra
    `{"humans_detected": 0, ...}` và Home Assistant đọc thành "KHÔNG CÓ NGƯỜI".
    Một hệ báo động im lặng báo an toàn còn tệ hơn một hệ báo lỗi ầm ĩ: người
    dùng không có cách nào biết rằng chẳng có tấm ảnh nào từng được nhìn.
    """
    if not meta:
        return text
    schema = meta.get("schema") if isinstance(meta.get("schema"), dict) else {}
    obj = extract_json_object(text)
    if obj is None and schema:
        obj = recover_fields_from_mangled(text, schema)
    if obj is None:
        props = _schema_properties(schema)
        if props and not cho_phep_mac_dinh:
            logger.error({
                "event": "vision_khong_doc_duoc_json",
                "props": list(props.keys()),
                "raw_preview": str(text or "")[:300],
                "ly_do": "model không trả JSON — KHÔNG dựng giá trị mặc định vì "
                         "humans_detected=0 sẽ bị đọc thành 'không có người'",
            })
            raise KhongPhanTichDuocAnh(
                "Không phân tích được ảnh: model trả về văn bản không phải JSON. "
                "Thường là vì mọi provider vision đều hỏng và yêu cầu rơi xuống một "
                "model chỉ xử lý chữ. KHÔNG suy ra 'không có người' từ kết quả này."
            )
        if props:
            # Đường không-vision: dựng mặc định như cũ để client cấu trúc vẫn
            # parse được. Ở đây "0" không mang nghĩa an toàn/nguy hiểm nào.
            obj = {k: _default_for_type(_prop_type(info)) for k, info in props.items()}
            logger.warning({
                "event": "response_format_fallback_defaults",
                "props": list(obj.keys()),
                "raw_preview": str(text or "")[:300],
            })
        else:
            obj = {}
    else:
        if schema:
            obj = coerce_to_schema(obj, schema)
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _content_from_result(result: dict[str, Any]) -> str:
    try:
        choices = result.get("choices") or []
        if not choices:
            return ""
        msg = (choices[0] or {}).get("message") or {}
        c = msg.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            parts = []
            for p in c:
                if isinstance(p, dict) and p.get("type") in ("text", "output_text"):
                    parts.append(str(p.get("text") or ""))
            return "".join(parts)
    except Exception:
        pass
    return ""


def _set_content(result: dict[str, Any], content: str) -> dict[str, Any]:
    choices = result.get("choices") or []
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message")
        if isinstance(msg, dict):
            msg["content"] = content
        else:
            choices[0]["message"] = {"role": "assistant", "content": content}
    return result


# Default schema used by TriTue2011 camera blueprint (JSON / structured humans+animals)
_VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "humans_detected": {"type": "integer"},
        "humans_detected_summary": {"type": "string"},
        "humans_detected_description": {"type": "string"},
        "animals_detected": {"type": "integer"},
        "animals_detected_summary": {"type": "string"},
        "animals_detected_description": {"type": "string"},
        # Blueprint dùng ô này để chọn tấm ảnh nét nhất khi chỉ gửi một tấm.
        # Không khai ở đây thì nó bị lược đi và người nhận luôn nhận tấm giữa.
        "khung_ro_nhat": {"type": "integer"},
    },
    "required": [
        "humans_detected",
        "humans_detected_summary",
        "humans_detected_description",
        "animals_detected",
        "animals_detected_summary",
        "animals_detected_description",
    ],
}


# Chế độ An ninh của cùng blueprint hỏi ba trường khác hẳn. Ép nó về lược đồ
# người+thú ở trên là xoá mất `human_action` và `security_suspicious`, và Home
# Assistant đọc ra một lượt "không có ai, không đáng ngờ" — đúng kiểu hỏng im
# lặng: báo động vẫn chạy, chỉ là không bao giờ báo gì.
_VISION_SCHEMA_AN_NINH = {
    "type": "object",
    "properties": {
        "humans_detected": {"type": "integer"},
        "human_action": {"type": "string"},
        "security_suspicious": {"type": "boolean"},
        "khung_ro_nhat": {"type": "integer"},
    },
    "required": ["humans_detected", "human_action", "security_suspicious"],
}


def _chon_vision_schema(body: dict[str, Any] | None) -> dict[str, Any]:
    """Lược đồ nào hợp với lời dặn đang gửi tới.

    Nhận dạng bằng chính tên trường mà lời dặn yêu cầu, thay vì đoán theo chế
    độ — blueprint đổi chế độ thì tên trường đổi theo, nên đây là dấu hiệu chắc
    chắn nhất.
    """
    joined = "\n".join(_message_text_blobs(body)).lower()
    if "security_suspicious" in joined or "human_action" in joined:
        return _VISION_SCHEMA_AN_NINH
    return _VISION_SCHEMA


_VISION_PROMPT_MARKERS = (
    "humans_detected",
    "animals_detected",
    "humans detected",
    "animals detected",
    "chuỗi hình ảnh",
    "chuoi hinh anh",
    "phân tích chuỗi ảnh",
    "phan tich chuoi anh",
    "phân tích chuỗi hình",
    "camera blueprint",
    "humans_detected_summary",
    "humans_detected_description",
    "animals_detected_summary",
    "animals_detected_description",
)


def _message_text_blobs(body: dict[str, Any] | None) -> list[str]:
    blobs: list[str] = []
    if not isinstance(body, dict):
        return blobs
    for m in body.get("messages") or []:
        if not isinstance(m, dict):
            continue
        c = m.get("content")
        if isinstance(c, str) and c.strip():
            blobs.append(c)
        elif isinstance(c, list):
            for p in c:
                if not isinstance(p, dict):
                    continue
                if p.get("type") in ("text", "input_text"):
                    tx = str(p.get("text") or "")
                    if tx.strip():
                        blobs.append(tx)
    return blobs


def body_has_images(body: dict[str, Any] | None) -> bool:
    if not isinstance(body, dict):
        return False
    try:
        for m in body.get("messages") or []:
            if not isinstance(m, dict):
                continue
            c = m.get("content")
            if isinstance(c, list):
                for p in c:
                    if isinstance(p, dict) and p.get("type") in ("image_url", "input_image", "image"):
                        return True
    except Exception:
        pass
    return False


def wants_structured_output(body: dict[str, Any] | None) -> bool:
    """True when client asked for JSON via OpenAI response_format."""
    if not isinstance(body, dict):
        return False
    if body.get("_response_format_meta"):
        return True
    return parse_response_format(body) is not None


def _looks_like_vision_analysis(text: str, body: dict[str, Any] | None) -> bool:
    """Detect HA camera blueprint / structured vision tasks ONLY.

    Important: plain questions with an image (e.g. \"ảnh này là gì?\") must
    return False so we do NOT force humans_detected JSON on free-form chat.
    """
    # Explicit OpenAI structured request is handled by enforce_response_format
    if wants_structured_output(body):
        return False

    t = (text or "")
    low = t.lower()
    if "humans_detected" in low or "humans detected" in low:
        return True
    if "animals_detected" in low or "animals detected" in low:
        return True

    # Only scan *request* messages for blueprint markers — not every HA+image
    joined = "\n".join(_message_text_blobs(body)).lower()
    if not joined:
        return False
    for marker in _VISION_PROMPT_MARKERS:
        if marker in joined:
            return True
    # Vietnamese camera-automation phrasing without English field names
    if ("chuỗi hình" in joined or "chuoi hinh" in joined) and (
        "người" in joined or "nguoi" in joined or "động vật" in joined or "dong vat" in joined
    ):
        return True
    return False


def enforce_response_format(
    result: dict[str, Any] | Iterator[dict[str, Any]],
    body: dict[str, Any] | None,
) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """Post-process completion / stream to pure JSON when response_format set."""
    meta = None
    if isinstance(body, dict):
        meta = body.get("_response_format_meta") or parse_response_format(body)
    if not meta:
        return result

    if isinstance(result, dict):
        raw = _content_from_result(result)
        cleaned = normalize_content(raw, meta)
        if cleaned != raw:
            logger.info({
                "event": "response_format_enforced",
                "type": meta.get("type"),
                "in_chars": len(raw or ""),
                "out_chars": len(cleaned),
            })
        return _set_content(result, cleaned)

    # Stream: collect content, emit one JSON chunk (like markdown strip)
    return _enforce_stream(result, meta)


def enforce_vision_json_if_needed(
    result: dict[str, Any] | Iterator[dict[str, Any]],
    body: dict[str, Any] | None,
) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """Repair camera-analysis JSON for HA blueprint JSON mode (no response_format).

    Blueprint parse path: ``from_json`` on ``humans_detected_report_raw.data``.
    If markdown-strip destroyed underscores/quotes, from_json fails → HA shows 0.
    """
    if isinstance(body, dict) and (body.get("_response_format_meta") or parse_response_format(body)):
        # already handled by enforce_response_format
        return result

    meta = {"type": "json_object", "schema": _chon_vision_schema(body), "name": "vision_ha"}

    if isinstance(result, dict):
        raw = _content_from_result(result)
        if not _looks_like_vision_analysis(raw, body):
            # also check request messages for vision task even if answer empty
            if not _looks_like_vision_analysis("", body):
                return result
        # cho_phep_mac_dinh=False: đây CHÍNH LÀ đường camera của Home Assistant.
        # Không bóc được JSON thì ném, không dựng `humans_detected: 0` giả.
        #
        # Chỉ fail-closed khi request THẬT SỰ có ảnh. `_looks_like_vision_analysis`
        # nhận dạng bằng cụm từ ("chuỗi hình ảnh", "humans_detected"…), mà một
        # câu chat bình thường cũng có thể chứa chúng — lúc đó ném lỗi là biến
        # một cuộc trò chuyện đang chạy tốt thành 502.
        co_anh = body_has_images(body)
        cleaned = normalize_content(raw, meta, cho_phep_mac_dinh=not co_anh)
        # Only rewrite if we improved parseability
        if cleaned and (cleaned != raw or extract_json_object(raw) is None):
            try:
                json.loads(cleaned)
                logger.info({
                    "event": "vision_json_enforced",
                    "in_chars": len(raw or ""),
                    "out_chars": len(cleaned),
                    "preview": cleaned[:180],
                })
                return _set_content(result, cleaned)
            except Exception:
                return result
        return result

    # stream: wrap only if request looks like vision
    if not _looks_like_vision_analysis("", body):
        return result

    # Gom TOÀN BỘ stream NGAY BÂY GIỜ, không nằm trong generator.
    #
    # Vì sao quan trọng: phần dựng JSON vốn đã phải đọc hết stream mới làm được
    # (nó cần `full`), nên bọc trong generator chẳng tiết kiệm gì — chỉ khiến
    # việc gom xảy ra ở lần `next()` đầu tiên, tức SAU khi tầng HTTP đã gửi
    # header và mở SSE. Lúc đó ném lỗi thì không còn cách nào trả 502: người
    # gọi nhận một stream đứt giữa chừng. Gom ở đây thì lỗi nổ TRƯỚC khi phản
    # hồi bắt đầu, và `/v1/chat/completions` trả 502 tử tế.
    full = ""
    model = ""
    cid = ""
    created = int(time.time())
    pending: list[dict[str, Any]] = []
    for chunk in result:
        if not isinstance(chunk, dict):
            continue
        model = model or str(chunk.get("model") or "")
        cid = cid or str(chunk.get("id") or "")
        created = int(chunk.get("created") or created)
        try:
            for ch in chunk.get("choices") or []:
                delta = (ch or {}).get("delta") or {}
                if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                    full += delta["content"]
        except Exception:
            pass
        pending.append(chunk)

    def _phat(chunks: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
        yield from chunks

    if not _looks_like_vision_analysis(full, body) and extract_json_object(full) is None:
        return _phat(pending)

    # CÙNG luật với nhánh non-stream. Bỏ sót chỗ này là bỏ sót ĐÚNG đường mà
    # Home Assistant đi (blueprint camera gọi stream), nên bản vá trước vẫn để
    # lọt `{"humans_detected": 0}` bịa ra từ một câu văn xuôi.
    co_anh = body_has_images(body)
    cleaned = normalize_content(full, meta, cho_phep_mac_dinh=not co_anh)
    try:
        json.loads(cleaned)
    except Exception:
        return _phat(pending)
    logger.info({
        "event": "vision_json_enforced_stream",
        "in_chars": len(full),
        "out_chars": len(cleaned),
        "preview": cleaned[:180],
    })
    rid = cid or f"chatcmpl-{uuid.uuid4().hex}"
    return _phat([
        {
            "id": rid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model or "json",
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": cleaned},
                         "finish_reason": None}],
        },
        {
            "id": rid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model or "json",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
    ])


def _enforce_stream(
    it: Iterator[dict[str, Any]],
    meta: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    full = ""
    model = ""
    cid = ""
    created = int(time.time())
    for chunk in it:
        if not isinstance(chunk, dict):
            continue
        model = model or str(chunk.get("model") or "")
        cid = cid or str(chunk.get("id") or "")
        created = int(chunk.get("created") or created)
        try:
            for ch in chunk.get("choices") or []:
                if not isinstance(ch, dict):
                    continue
                delta = ch.get("delta") or {}
                if isinstance(delta, dict):
                    c = delta.get("content")
                    if isinstance(c, str) and c:
                        full += c
                # drop tool_calls / other deltas for structured pure-JSON mode
        except Exception:
            pass

    cleaned = normalize_content(full, meta)
    logger.info({
        "event": "response_format_enforced_stream",
        "type": meta.get("type"),
        "in_chars": len(full),
        "out_chars": len(cleaned),
        "preview": cleaned[:200],
    })
    rid = cid or f"chatcmpl-{uuid.uuid4().hex}"
    yield {
        "id": rid,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model or "json",
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant", "content": cleaned},
            "finish_reason": None,
        }],
    }
    yield {
        "id": rid,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model or "json",
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop",
        }],
    }
