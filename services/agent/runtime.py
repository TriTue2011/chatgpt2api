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
from typing import Any, Optional

from services.config import config

logger = logging.getLogger(__name__)

_LOCAL = "http://127.0.0.1:80/v1/chat/completions"
# Markdown image the image-gen pipeline emits: ![[Generated Image 0]](http://…)
_IMG_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")


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
) -> dict[str, Any]:
    """Call a concrete provider model, return the raw OpenAI response dict.

    Never raises — on failure returns ``{"error": "..."}`` so the caller can
    report the error to the user instead of crashing the turn.

    HA voice fast-paths (date/lunar/weather/sensor canned answers) are skipped
    by default — they hijack conversational questions ("mai thứ mấy" → today's
    date). ``allow_fastpath=True`` opts back in (control_home needs the HA
    intent fast-path to actually switch devices).
    """
    payload: dict[str, Any] = {"model": model, "messages": messages,
                               "stream": False, "max_tokens": max_tokens}
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
    try:
        req = urllib.request.Request(
            _base(), data=json.dumps(payload).encode(),
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
) -> dict[str, Any]:
    """Generate a video via the local /v1/video/generations (Flow/Veo).

    Returns the raw response dict ({"data":[{"url","b64_json",…}]}) or
    {"error": "..."} — never raises.
    """
    url = _base().replace("/chat/completions", "/video/generations")
    payload = {"model": model, "prompt": prompt, "n": 1}
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


def first_image_url(text: str) -> Optional[str]:
    m = _IMG_RE.search(text or "")
    return m.group(1) if m else None


# Link audio/video pipeline gma/nhạc emit: [▶️ Bấm để nghe/xem ...](http://…/x.mp3)
_AUDIO_URL_RE = re.compile(r"\((https?://[^)\s]+\.(?:mp3|m4a|wav|ogg))\)", re.I)
_VIDEO_URL_RE = re.compile(r"\((https?://[^)\s]+\.(?:mp4|webm))\)", re.I)


def first_audio_url(text: str) -> Optional[str]:
    m = _AUDIO_URL_RE.search(text or "")
    return m.group(1) if m else None


def first_video_url(text: str) -> Optional[str]:
    m = _VIDEO_URL_RE.search(text or "")
    return m.group(1) if m else None
