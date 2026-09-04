"""Runtime helpers — call the local model pipeline + extract media.

Capabilities route work to concrete provider models (cx/claude/gma/flow…) by
POSTing to this instance's own ``/v1/chat/completions`` — that reuses the whole
existing pipeline (HA fast-path, search injection, provider dispatch, image
generation) instead of re-implementing it. Concrete model prefixes are used
(never ``agent/*``) so the orchestrator can't recurse into itself.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
import uuid
from typing import Any, Optional

from services.config import config
from services.local_gateway import gateway_v1_url

logger = logging.getLogger(__name__)

_LOCAL = f"{gateway_v1_url()}/chat/completions"
# Markdown image the image-gen pipeline emits: ![[Generated Image 0]](http://…)
_IMG_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")
#: Ảnh trả THẲNG trong chữ dạng data-URI — một số nhà cung cấp làm vậy thay vì
#: đưa URL http. Đo 04/09 trên nhánh "AI image".
_IMG_DATA_RE = re.compile(r"data:image/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]+", re.I)

# Model KHÔNG hỗ trợ native function-call đôi khi phát tool call dạng text:
#   ```xml <tool_call name="schedule">{"op":"create",…}</tool_call>```
# Nếu không bóc ra, orchestrator thấy tool_calls rỗng → RÒ nguyên văn ra người
# dùng ("tool call name=schedule op=create…"). Bóc về tool_calls chuẩn để thực thi.
_XML_TC_RE = re.compile(r'<tool_call\s+name=["\'](.+?)["\']>(.*?)</tool_call>', re.DOTALL)
_XML_TC_SELF_RE = re.compile(r'<tool_call\s+name=["\'](.+?)["\']\s*/>', re.DOTALL)


#: Tên khoá mà các model không-native hay dùng khi tự viết tool call ra JSON.
_JSON_TEN = ("tool", "name", "tool_name", "function", "action")
_JSON_ARGS = ("args", "arguments", "parameters", "params", "input")


def _boc_tool_call_json(text: str,
                        ten_hop_le: Optional[set[str]] = None) -> Optional[list[dict[str, Any]]]:
    """Bóc tool call model viết dạng JSON TRẦN (không XML, không native).

    Đo thật 03/09: model `nemotron-3-ultra-free` trả về đúng chuỗi
    ``{"tool": "search_web", "args": {...}}`` và nó đi thẳng ra màn hình người
    dùng — vì bộ bóc cũ chỉ hiểu thẻ ``<tool_call>``.

    Chỉ nhận khi TOÀN BỘ nội dung là một object JSON như vậy, và khi có danh
    sách tool thì tên phải nằm trong đó. Hai chốt này để không nuốt nhầm câu trả
    lời JSON hợp lệ mà người dùng thật sự hỏi xin.
    """
    t = (text or "").strip()
    if not t:
        return None
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.DOTALL)
    if m:
        t = m.group(1).strip()
    if not (t.startswith("{") and t.endswith("}")):
        return None
    try:
        obj = json.loads(t)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    ten = next((str(obj[k]).strip() for k in _JSON_TEN
                if isinstance(obj.get(k), str) and str(obj[k]).strip()), "")
    if not ten:
        return None
    if ten_hop_le is not None and ten not in ten_hop_le:
        return None
    args = next((obj[k] for k in _JSON_ARGS if isinstance(obj.get(k), dict)), {})
    return [{"id": f"agent_json_{uuid.uuid4().hex[:8]}", "type": "function",
             "function": {"name": ten,
                          "arguments": json.dumps(args, ensure_ascii=False)}}]


def extract_text_tool_calls(
        text: str, ten_hop_le: Optional[set[str]] = None) -> Optional[list[dict[str, Any]]]:
    """Bóc tool call viết dạng text (XML hoặc JSON trần) → list tool_calls chuẩn."""
    if not text:
        return None
    if "<tool_call" not in text:
        return _boc_tool_call_json(text, ten_hop_le)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in _XML_TC_RE.finditer(text):
        name = m.group(1).strip()
        raw = (m.group(2) or "").strip()
        try:
            args = json.loads(raw) if raw else {}
        except Exception:
            try:  # newline chưa escape trong string JSON
                fixed = re.sub(r'".*?"',
                               lambda mm: mm.group(0).replace("\n", "\\n").replace("\r", "\\r"),
                               raw, flags=re.DOTALL)
                args = json.loads(fixed)
            except Exception:
                logger.warning("agent.runtime: bỏ tool_call XML không parse được: %s", raw[:120])
                continue
        if not isinstance(args, dict):
            args = {}
        if name in seen:
            continue
        seen.add(name)
        out.append({"id": f"agent_xml_{uuid.uuid4().hex[:8]}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
    for m in _XML_TC_SELF_RE.finditer(text):
        name = m.group(1).strip()
        if name in seen:
            continue
        seen.add(name)
        out.append({"id": f"agent_xml_{uuid.uuid4().hex[:8]}", "type": "function",
                    "function": {"name": name, "arguments": "{}"}})
    return out or None


def _normalize_text_tool_calls(data: dict[str, Any],
                              ten_hop_le: Optional[set[str]] = None) -> None:
    """Nếu model trả tool call dạng text (không native) → nhét vào message.tool_calls
    và dọn phần XML khỏi content để KHÔNG rò ra người dùng. Sửa tại chỗ (in-place)."""
    try:
        msg = ((data.get("choices") or [{}])[0].get("message")) or {}
    except Exception:
        return
    if not isinstance(msg, dict) or msg.get("tool_calls"):
        return
    content = msg.get("content")
    if not isinstance(content, str) or not content.strip():
        return
    calls = extract_text_tool_calls(content, ten_hop_le)
    if not calls:
        return
    if "<tool_call" in content:
        cleaned = re.sub(r"```xml\s*.*?```", "", content, flags=re.DOTALL)
        cleaned = _XML_TC_SELF_RE.sub("", _XML_TC_RE.sub("", cleaned)).strip()
    else:
        cleaned = ""   # cả nội dung LÀ lệnh gọi, không còn chữ nào cho người đọc
    msg["tool_calls"] = calls
    msg["content"] = cleaned
    data["choices"][0]["message"] = msg


def _base() -> str:
    b = str(config.get().get("api_base_url", "")).strip().rstrip("/")
    return (b + "/chat/completions") if b else _LOCAL


def call_model(
    model: str,
    messages: list[dict[str, Any]],
    *,
    tools: Optional[list[dict]] = None,
    timeout: int = 180,
    max_tokens: int = 900,
    allow_fastpath: bool = False,
    no_smart_home: bool = False,
    allowed_groups: Optional[set[str]] = None,
    modalities: Optional[list[str]] = None,
    channel: str = "",
    response_format: Optional[dict[str, Any]] = None,
    pham_vi: str = "",
    doc_them: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Call a concrete provider model, return the raw OpenAI response dict.

    Never raises — on failure returns ``{"error": "..."}`` so the caller can
    report the error to the user instead of crashing the turn.

    HA voice fast-paths (date/lunar/weather/sensor canned answers) are skipped
    by default — they hijack conversational questions ("mai thứ mấy" → today's
    date). ``allow_fastpath=True`` opts back in (control_home needs the HA
    intent fast-path to actually switch devices).
    """
    # P0 privacy: redact MK/token/PII before any model call
    safe_messages = messages
    try:
        from services.privacy_gate import redact_messages, is_enabled as _priv_on
        if _priv_on():
            sid = f"agent:{channel or 'local'}"
            safe_messages = redact_messages(messages, session_id=sid)
    except Exception:
        safe_messages = messages

    payload: dict[str, Any] = {"model": model, "messages": safe_messages,
                               "stream": False, "max_tokens": max_tokens,
                               # Skip Agent-runs double-count (orchestrator journals the turn)
                               "x_agent_internal": True}
    if pham_vi:
        # Khoá phạm vi ĐẦY ĐỦ của lượt (kênh/chat/topic/người) cho memory_service:
        # isolate + honor kết nối bộ nhớ (doc_them). Không có nó, lời gọi
        # agent-internal sẽ bị memory_service BỎ QUA (không dùng kho chung global —
        # xem memory_service.prepare) để không rò dữ liệu chéo giữa các nhóm/chat.
        payload["_mem_scope"] = pham_vi
        payload["_mem_doc_them"] = list(doc_them or [])
    if not allow_fastpath:
        payload["x_skip_fastpath"] = True
    if channel:
        # 'tg'|'zalo'|'zalop' → tầng branch routing của gateway đọc cài đặt
        # nhánh RIÊNG kênh này (agent_branches_by_channel) trước nhánh chung.
        payload["x_channel"] = channel
    if no_smart_home:
        # Thread bị lọc chức năng (không có nhóm homeassistant) → yêu cầu
        # pipeline gateway TẮT tích hợp HA (kẻo nó tự thực thi lệnh nhà).
        payload["x_no_smart_home"] = True
    if allowed_groups is not None:
        # Bộ lọc chức năng đầy đủ của thread → gateway tự tắt các tích hợp
        # ngoài danh sách (HA tools, ssh server-admin, web search tự động).
        payload["x_allowed_groups"] = sorted(allowed_groups)
    if modalities:
        # ['image'] → gateway đi thẳng pipeline image_chat (hỗ trợ ảnh NGUỒN
        # trong message — img2img); dispatch thường coi ảnh là vision chat.
        payload["modalities"] = modalities
    if tools:
        payload["tools"] = tools
    if response_format:
        # Xin JSON tường minh. Hai việc: gateway ép JSON thuần ở lối ra
        # (`enforce_response_format`), VÀ tắt bước đổi sang văn xuôi cho TTS —
        # verbalize xoá { } " : nên JSON đi qua nó là chuỗi không parse được.
        # Đo thật 2026-07-30: không có cờ này, model của phần Giáo viên (combo
        # "AI text") bị định tuyến nhánh sang một model không mang marker `:text`,
        # và JSON về tới nơi thành `mucsat,de...` — caller báo "model không trả
        # đúng dạng" trong khi nội dung model trả vốn đúng.
        payload["response_format"] = response_format
    try:
        req = urllib.request.Request(
            _base(), data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {config.auth_key}",
                     # Header nội bộ: gateway CHỈ tin x_agent_internal khi header
                     # này khớp auth_key (client ngoài không đặt được) — chống
                     # né Agent run journal bằng cách tự gắn cờ trong body.
                     "X-Agent-Internal-Key": str(config.auth_key or ""),
                     "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        # Model phát tool call dạng text/XML (không native) → chuẩn hóa thành
        # tool_calls để orchestrator THỰC THI, thay vì rò text ra người dùng.
        if tools:
            try:
                # Đưa kèm TÊN TOOL vừa gửi: chỉ đổi thành tool_call khi tên có
                # thật, để không nuốt nhầm câu trả lời JSON người dùng hỏi xin.
                _ten = {str(((t or {}).get("function") or {}).get("name") or "").strip()
                        for t in (tools or []) if isinstance(t, dict)}
                _normalize_text_tool_calls(data, {x for x in _ten if x})
            except Exception as exc:
                logger.debug("agent.runtime: normalize tool_calls lỗi: %s", exc)
        return data
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        logger.warning("agent.runtime: %s → HTTP %s %s", model, e.code, body)
        return {"error": f"HTTP {e.code}: {body}"}
    except Exception as exc:
        logger.warning("agent.runtime: %s → %s", model, str(exc)[:150])
        return {"error": str(exc)[:200]}


def call_video(
    prompt: str,
    *,
    model: str = "flow/veo-3.1-fast",
    timeout: int = 330,
    **kwargs,
) -> dict[str, Any]:
    """Generate a video via the local /v1/video/generations (Flow/Veo/Agnes).

    Returns the raw response dict ({"data":[{"url","b64_json",…}]}) or
    {"error": "..."} — never raises.
    """
    url = _base().replace("/chat/completions", "/video/generations")
    payload = {"model": model, "prompt": prompt, "n": 1, **kwargs}
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {config.auth_key}",
                     "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        logger.warning("agent.runtime: video %s → HTTP %s %s", model, e.code, body)
        return {"error": f"HTTP {e.code}: {body}"}
    except Exception as exc:
        logger.warning("agent.runtime: video %s → %s", model, str(exc)[:150])
        return {"error": str(exc)[:200]}


def content_of(resp: dict[str, Any]) -> str:
    """Extract assistant text content from an OpenAI response dict."""
    try:
        c = ((resp.get("choices") or [{}])[0].get("message", {}) or {}).get("content") or ""
        if isinstance(c, list):
            return " ".join(str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in c)
        return str(c)
    except Exception:
        return ""


def _luu_anh_data_uri(data_uri: str) -> Optional[str]:
    """``data:image/…;base64,…`` → URL ``/images/…``; None nếu không phải ảnh thật.

    KHÔNG tự đệm ``=`` cho đủ bộ bốn: sai độ dài nghĩa là chuỗi đã bị CẮT, đệm
    vào chỉ dựng ra một tấm ảnh hỏng rồi gửi đi. Giải mã được cũng chưa đủ —
    ``"abcQ"`` cũng ra 3 byte hợp lệ — nên phải đúng magic bytes mới nhận.
    """
    try:
        import base64
        from services.image_utils import sniff_format
        from services.protocol.conversation import save_image_bytes
        raw = base64.b64decode(data_uri.split(",", 1)[1], validate=True)
        if not sniff_format(raw):
            logger.warning("first_image_url: %d byte không phải ảnh, bỏ", len(raw))
            return None
        return save_image_bytes(raw) or None
    except Exception as exc:
        logger.warning("first_image_url: lưu ảnh data-URI lỗi: %s", exc)
        return None


def first_image_url(text: str) -> Optional[str]:
    """URL ảnh đầu tiên trong chữ, hoặc None.

    Nhận CẢ ảnh nhúng dạng data-URI, và đổi nó thành URL ``/images/…`` ngay tại
    đây — vì đó mới là thứ MỌI kênh gửi được. Trả về data-URI trần là đặt bẫy:
    kênh nào chưa biết xử lý sẽ đem cả chuỗi base64 gửi đi như văn bản.

    Lỗi thật 04/09 13:38: nhà cung cấp trả ``![image_1](data:image/png;base64,…)``
    — ảnh hợp lệ, chỉ khác dạng. Hàm này khi ấy chỉ nhận ``http(s)://`` nên trả
    None, `_h_generate_image` hiểu là "không lấy được ảnh" rồi trả NGUYÊN chuỗi
    base64 làm câu trả lời; qua vài tầng nữa người dùng nhận một tệp .docx chứa
    base64 thay vì tấm ảnh.

    Ba nơi gọi hàm này — tạo ảnh qua trợ lý, tạo ảnh từ ảnh (`photo_intent`),
    ảnh minh hoạ bài giảng (`teacher_images`) — nên sửa ở đây là sửa cả ba.
    """
    m = _IMG_RE.search(text or "")
    if m:
        return m.group(1)
    m = _IMG_DATA_RE.search(text or "")
    return _luu_anh_data_uri(m.group(0)) if m else None


# Link audio/video pipeline gma/nhạc emit: [▶️ Bấm để nghe/xem ...](http://…/x.mp3)
_AUDIO_URL_RE = re.compile(r"\((https?://[^)\s]+\.(?:mp3|m4a|wav|ogg))\)", re.I)
_VIDEO_URL_RE = re.compile(r"\((https?://[^)\s]+\.(?:mp4|webm))\)", re.I)


def first_audio_url(text: str) -> Optional[str]:
    m = _AUDIO_URL_RE.search(text or "")
    return m.group(1) if m else None


def first_video_url(text: str) -> Optional[str]:
    m = _VIDEO_URL_RE.search(text or "")
    return m.group(1) if m else None
