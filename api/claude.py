"""
Claude — fully standalone, OpenAI-compatible router for the claude.ai web backend.

Design goals (đại ca's requirements):
  * COMPLETELY separate from chatgpt / gemini / the shared flow. Everything Claude
    lives in THIS one file, so editing it can never break the other providers.
  * Still speaks the OpenAI standard: request/response use the OpenAI
    chat.completions schema, exposed under its own base path:
        POST /v1/claude/chat/completions      (stream + non-stream)
        GET  /v1/claude/models
    Point any OpenAI client/SDK at base_url ".../v1/claude" and it just works.

Backend: "free" path — drives claude.ai's own web API with a logged-in session
cookie (consumes the account's Claude.ai quota, no per-token billing), mirroring
how chatgpt_free uses chatgpt.com. Paid API / OAuth subscription is a future add.

Wire-up (one line, added to api/app.py — the full chatgpt2api app only):
    app.include_router(claude.create_router())

Config (config.json → providers.claude):
    "claude": { "session_key": "sk-ant-sid01-...", "model": "auto",
                "timezone": "Asia/Ho_Chi_Minh" }
Get session_key from claude.ai → DevTools → Application → Cookies → `sessionKey`.

NOTE: claude.ai is reverse-engineered + Cloudflare-protected; endpoints drift.
Untested against the live site from the dev box — verify on the server with a
real cookie and adjust the completion path / _parse_stream event shapes if needed.
"""

from __future__ import annotations

import base64
import json
import re
import time
import uuid
from typing import Any, Iterator

from curl_cffi import requests, CurlMime
from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

# ── Lazy imports (avoid import cycles at module load) ───────────────────────

def _config():
    from services.config import config
    return config


def _logger():
    from utils.log import logger
    return logger


# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

CLAUDE_BASE_URL = "https://claude.ai"
ROOT_PARENT_UUID = "00000000-0000-4000-8000-000000000000"

# Friendly aliases → claude.ai internal model ids. Unknown values pass through;
# "auto"/"" → omit model field (let claude.ai pick the account default).
CLAUDE_MODEL_ALIASES: dict[str, str] = {
    "sonnet": "claude-sonnet-5",
    "sonnet-5": "claude-sonnet-5",
    "sonnet-4.6": "claude-sonnet-4-6",
    "sonnet-4.5": "claude-sonnet-4-5",
    "opus": "claude-opus-4-8",
    "opus-4.8": "claude-opus-4-8",
    "opus-4.7": "claude-opus-4-7",
    "opus-4.6": "claude-opus-4-6",
    "opus-3": "claude-3-opus-20240229",
    "opus-4.1": "claude-opus-4-1",
    "haiku": "claude-haiku-4-5",
    "haiku-4.5": "claude-haiku-4-5",
    "fable-5": "claude-fable-5",
}


# ═══════════════════════════════════════════════════════════════════════════
# Request model (OpenAI standard)
# ═══════════════════════════════════════════════════════════════════════════

class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = "claude/auto"
    messages: list[dict[str, Any]] = Field(default_factory=list)
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any | None = None


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _claude_cfg() -> dict[str, Any]:
    cfg = (_config().data.get("providers") or {}).get("claude") or {}
    return cfg if isinstance(cfg, dict) else {}


def _base_url() -> str:
    base = str(_claude_cfg().get("base_url") or "").rstrip("/")
    return base or CLAUDE_BASE_URL


# sessionKey fetched from the captcha-solver, cached per profile (5-min TTL)
# so we don't hit the onboard service on every chat request.
_SOLVER_KEY_TTL = 300.0
_solver_key_cache: dict[str, tuple[float, str]] = {}

# session_key → profile_name: populated when fetching from captcha-solver,
# used by _record_quota_failure to persist failures against the stable profile.
_profile_by_session: dict[str, str] = {}

# Per-profile cooldown for the self-heal re-login (relogin-via-google). After a
# restart the solver's in-RAM sessionKey is gone; we re-login via the profile's
# persisted Google session (SSO), but only retry a given profile every 5 min so
# a profile that genuinely can't onboard doesn't relaunch Chrome each request.
_RELOGIN_COOLDOWN = 300.0
_relogin_cooldown: dict[str, float] = {}

# Debounce Telegram cho tự-khôi-phục Claude (30ph/key) để không spam.
_claude_notify_at: dict[str, float] = {}


def _claude_notify(key: str, text: str) -> None:
    now = time.time()
    if now - _claude_notify_at.get(key, 0.0) < 1800.0:
        return
    _claude_notify_at[key] = now
    try:
        from services.notifier import notify_admin
        notify_admin(text)
    except Exception:
        pass

# ── Lỗi quota Claude → ánh xạ sang loại hạn mức ─────────────────────────────
_QUOTA_PATTERNS: list[tuple[str, str]] = [
    ("rate limit",              "text_limit"),
    ("too many requests",       "text_limit"),
    ("overloaded",              "text_limit"),
    ("usage limit",             "text_limit"),
    ("exceeded",                "text_limit"),
    ("file size",               "file_upload"),
    ("file upload",             "file_upload"),
    ("image upload",            "file_upload"),
    ("upload failed",           "file_upload"),
    ("vision",                  "file_upload"),
    ("cannot analyze",          "advanced_data_analysis"),
    ("unable to analyze",       "advanced_data_analysis"),
    ("analysis",                "advanced_data_analysis"),
]


def _fetch_session_key_from_solver(cfg: dict[str, Any], excluded_keys: set[str] | None = None) -> str:
    """Pull a logged-in claude.ai sessionKey from the captcha-solver.

    Iterates ALL profiles in providers.claude.profiles[] (or accounts[].profile)
    and returns the first available key that is NOT in excluded_keys.
    This enables automatic pool rotation through all Google accounts already
    onboarded in the captcha-solver — no manual session key entry needed.
    """
    from services.captcha import captcha_base
    base = captcha_base(cfg.get("captcha_solver_url"))
    if not base:
        return ""
    excluded = excluded_keys or set()

    # Collect ALL profiles: accounts[].profile first, then profiles[], then single profile
    profiles: list[str] = []
    for entry in (cfg.get("accounts") or []):
        if isinstance(entry, dict):
            p = str(entry.get("profile") or "").strip()
            if p and p not in profiles:
                profiles.append(p)
    for p in (cfg.get("profiles") or []):
        p = str(p or "").strip()
        if p and p not in profiles:
            profiles.append(p)
    legacy = str(cfg.get("profile") or "").strip()
    if legacy and legacy not in profiles:
        profiles.append(legacy)
    # Tự đọc thêm profile từ kho tài khoản — CHỈ nhóm 'claude' (TÁCH RIÊNG với
    # gemini_web_api). Account claude là account đã onboard claude.ai; gemini là
    # pool riêng, không dùng chung.
    try:
        from api.gemini_web import _store_profiles
        for p in _store_profiles({"claude"}):
            if p not in profiles:
                profiles.append(p)
    except Exception:
        pass
    if not profiles:
        profiles = ["claude-web-default"]

    api_key = str(cfg.get("captcha_solver_api_key") or "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    # PASS 1 — REUSE: cached or freshly-scraped sessionKey for any profile.
    for profile in profiles:
        cached = _solver_key_cache.get(profile)
        if cached and (time.time() - cached[0]) < _SOLVER_KEY_TTL and cached[1] and cached[1] not in excluded:
            return cached[1]
        try:
            resp = requests.get(
                f"{base}/v1/claude-web/{profile}/session",
                headers=headers, timeout=15, impersonate="chrome110",
            )
            if resp.status_code == 200:
                key = str((resp.json() or {}).get("session_key") or "")
                if key:
                    _solver_key_cache[profile] = (time.time(), key)
                    _profile_by_session[key] = profile  # persist mapping
                    if key not in excluded:
                        return key
        except Exception as exc:
            _logger().warning({"event": "claude_solver_key_fetch_failed", "profile": profile, "error": str(exc)[:120]})

    # PASS 2 — SELF-HEAL: không có session sống (điển hình: sau khi restart,
    # sessionKey trong RAM của solver mất) → ĐĂNG NHẬP LẠI qua phiên Google đã lưu
    # của profile (SSO, không cần mật khẩu) rồi lấy lại key. Bounded + cooldown.
    now = time.time()

    def _claude_relogin_once(base: str, headers: dict, profile: str, excluded: set) -> str:
        """1 lượt relogin-via-google + poll sessionKey ~20s. Trả key hoặc ''."""
        try:
            _logger().info({"event": "claude_solver_trigger_relogin", "profile": profile})
            requests.post(f"{base}/v1/claude-web/{profile}/relogin-via-google",
                          headers=headers, timeout=30, impersonate="chrome110")
        except Exception as exc:
            _logger().warning({"event": "claude_solver_relogin_failed", "profile": profile, "error": str(exc)[:120]})
            return ""
        for _ in range(5):
            time.sleep(4)
            try:
                s = requests.get(f"{base}/v1/claude-web/{profile}/session",
                                 headers=headers, timeout=10, impersonate="chrome110")
                if s.status_code == 200:
                    key = str((s.json() or {}).get("session_key") or "")
                    if key:
                        _solver_key_cache[profile] = (time.time(), key)
                        _profile_by_session[key] = profile
                        _logger().info({"event": "claude_solver_relogin_ok", "profile": profile})
                        _claude_notify(f"ok:{profile}",
                            f"✅ Claude — {profile}\nKhôi phục xong (đăng nhập lại Google + lấy session).")
                        return key if key not in excluded else ""
            except Exception:
                pass
        return ""

    for profile in profiles:
        if now - _relogin_cooldown.get(profile, 0) < _RELOGIN_COOLDOWN:
            continue
        _relogin_cooldown[profile] = now
        key = _claude_relogin_once(base, headers, profile, excluded)
        if key:
            return key
        # Tái dùng lỗi — thường kẹt Google 'challenge/pwd' vì claude.ai OAuth
        # dùng prompt=consent (bắt nhập lại mật khẩu). LÀM TƯƠI session Google
        # trước (auto-login-saved dùng creds+totp đã lưu, chạy được trên VPS)
        # rồi tái dùng lại — session tươi sẽ không hỏi mật khẩu nữa.
        try:
            from services.account_recovery import _freshen_google
            _logger().info({"event": "claude_freshen_google", "profile": profile})
            if _freshen_google(profile):
                key = _claude_relogin_once(base, headers, profile, excluded)
                if key:
                    return key
        except Exception as exc:
            _logger().warning({"event": "claude_freshen_err", "profile": profile, "error": str(exc)[:120]})
        # Chỉ xử lý 1 profile mỗi lần gọi để giới hạn độ trễ; request sau (profile
        # này đang cooldown) sẽ rơi xuống PASS 1 lấy session khi solver xong.
        break
    # Không lấy được session key từ bất kỳ profile nào (kể cả sau relogin) →
    # Claude tạm không dùng được. Báo Telegram (debounce 30ph).
    if profiles:
        _claude_notify("fail:all",
            "❌ Claude — tất cả tài khoản\nKhông lấy được session (đăng nhập lại "
            "Google cũng không xong). Có thể hết phiên/bị chặn — cần xử lý tay "
            "(noVNC cổng 6080).")
    return ""


def _resolve_model(model: str) -> str:
    """alias/prefixed model → claude.ai internal id; '' means auto (omit)."""
    m = str(model or "").strip()
    for pfx in ("cc/", "claude/", "clf/", "cl/"):
        if m.startswith(pfx):
            m = m[len(pfx):].strip()
            break
    
    # Strip effort / thinking / web-search suffixes (may be chained, e.g.
    # "-thinking-search") so the base model still resolves.
    _sfxs = ("-search", "-websearch", "-low", "-medium", "-high", "-max", "-thinking", "-think")
    stripped = True
    while stripped:
        stripped = False
        for sfx in _sfxs:
            if m.endswith(sfx):
                m = m[:-len(sfx)]
                stripped = True
    
    if not m or m == "auto":
        m = str(_claude_cfg().get("model") or "").strip()
    if not m or m == "auto":
        return ""
    return CLAUDE_MODEL_ALIASES.get(m, m)


def _flatten_messages(messages: list[dict[str, Any]]) -> str:
    """OpenAI message array → single claude.ai prompt string.

    claude.ai keeps history server-side and takes one `prompt`, so for a
    stateless OpenAI-style request we serialise the whole conversation into one
    turn with System/User/Assistant prefixes (same approach as reference clients).
    """
    parts: list[str] = []
    for msg in messages or []:
        role = str(msg.get("role") or "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            text = " ".join(
                str(p.get("text", ""))
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        else:
            text = str(content or "")
        if not text.strip():
            continue
        label = {"system": "System", "assistant": "Assistant", "user": "User"}.get(role, role.capitalize())
        parts.append(f"{label}: {text}")
    parts.append("Assistant:")
    return "\n\n".join(parts)


_IMG_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
            "image/gif": "gif", "image/webp": "webp"}


def _downscale_image(data: bytes, mime: str) -> tuple[bytes, str]:
    """Cap the longest side before upload (camera frames are 1920-2688px).

    claude.ai charges vision tokens by pixel area, so smaller frames mean a
    faster, cheaper analysis with no real loss for person/object detection.
    Config key claude_vision_max_dim (default 896, 0 = off) mirrors the
    chatgpt_vision_max_dim knob.
    """
    try:
        max_dim = int(_config().data.get("claude_vision_max_dim", 896) or 0)
    except Exception:
        max_dim = 896
    if not max_dim:
        return data, mime
    try:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(data))
        w, h = img.size
        if max(w, h) <= max_dim:
            return data, mime
        scale = max_dim / float(max(w, h))
        new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
        resized = img.convert("RGB") if img.mode not in ("RGB", "L") else img
        resized = resized.resize(new_size, Image.LANCZOS)
        buf = BytesIO()
        resized.save(buf, format="JPEG", quality=85)
        out = buf.getvalue()
        _logger().info({"event": "claude_image_downscaled", "from": [w, h],
                        "to": list(new_size), "bytes": [len(data), len(out)]})
        return out, "image/jpeg"
    except Exception as exc:
        _logger().debug({"event": "claude_image_downscale_skipped", "error": str(exc)[:120]})
        return data, mime


def _extract_images(messages: list[dict[str, Any]]) -> list[tuple[bytes, str]]:
    """Pull (bytes, mime) for every OpenAI `image_url` part (data: URI or http URL)."""
    out: list[tuple[bytes, str]] = []
    for msg in messages or []:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for p in content:
            if not isinstance(p, dict) or p.get("type") != "image_url":
                continue
            url = str(((p.get("image_url") or {}).get("url") or "")).strip()
            if url.startswith("data:"):
                try:
                    head, b64 = url.split(",", 1)
                    mime = (head[5:].split(";")[0] or "image/png").lower()
                    out.append(_downscale_image(base64.b64decode(b64), mime))
                except Exception:
                    pass
            elif url.startswith("http"):
                try:
                    rr = requests.get(url, timeout=20, impersonate="chrome110")
                    if rr.status_code == 200 and rr.content:
                        mime = (rr.headers.get("content-type") or "image/png").split(";")[0].lower()
                        out.append(_downscale_image(rr.content, mime))
                except Exception:
                    pass
    return out


def _collect_text(chunks: Iterator[dict[str, Any]]) -> str:
    """Drain an OpenAI-chunk iterator into the full assistant text. Blocking —
    call via run_in_threadpool so claude.ai's network reads don't stall the loop."""
    content = ""
    for chunk in chunks:
        content += chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
    return content


def _openai_chunk(model: str, cid: str, created: int, delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
    return {
        "id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


# ═══════════════════════════════════════════════════════════════════════════
# claude.ai web backend
# ═══════════════════════════════════════════════════════════════════════════

class ClaudeFreeBackend:
    """claude.ai web backend via session cookie. Returns OpenAI-format chunks."""

    def __init__(self) -> None:
        self._session: Any = None
        self._session_cookie: str = ""
        self._org_id: str = ""
        self._conv_id: str = ""

    def _cookie_header(self) -> str:
        cfg = _claude_cfg()
        full = str(cfg.get("cookie") or "").strip()
        if full:
            return full
        key = str(cfg.get("session_key") or "").strip()
        if key:
            return f"sessionKey={key}"
        # No static cookie → reuse a Google-account session onboarded via the
        # captcha-solver (same path as ChatGPT/Flow login).
        key = _fetch_session_key_from_solver(cfg)
        return f"sessionKey={key}" if key else ""

    @property
    def is_available(self) -> bool:
        return bool(self._cookie_header())

    @property
    def session(self):
        cookie = self._cookie_header()
        if not cookie:
            raise RuntimeError("Claude: missing providers.claude.session_key / cookie / captcha_solver_url")
        # Rebuild the session when the cookie changes (sessionKey rotation or a
        # different Google profile) so we never send a stale credential.
        if self._session is None or self._session_cookie != cookie:
            s = requests.Session(impersonate="chrome110")
            s.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Content-Type": "application/json",
                "Origin": CLAUDE_BASE_URL,
                "Referer": CLAUDE_BASE_URL + "/chats",
                "anthropic-client-platform": "web_claude_ai",
                "Cookie": cookie,
            })
            self._session = s
            self._session_cookie = cookie
            self._org_id = ""  # re-resolve org for the new credential
            self._conv_id = ""  # and drop the cached conversation
        return self._session

    def _org_id_get(self) -> str:
        if self._org_id:
            return self._org_id
        pinned = str(_claude_cfg().get("organization_uuid") or "").strip()
        if pinned:
            self._org_id = pinned
            return pinned
        resp = self.session.get(f"{_base_url()}/api/organizations", timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f"Claude org lookup failed {resp.status_code}: {resp.text[:160]}")
        orgs = resp.json()
        org_id = ""
        if isinstance(orgs, list) and orgs:
            chat_orgs = [o for o in orgs if isinstance(o, dict) and "chat" in (o.get("capabilities") or [])]
            org_id = (chat_orgs[0] if chat_orgs else orgs[0]).get("uuid", "")
        elif isinstance(orgs, dict):
            org_id = orgs.get("uuid", "")
        if not org_id:
            raise RuntimeError("Claude org lookup: no organization (session_key expired?)")
        self._org_id = org_id
        return org_id

    def _create_conversation(self, org_id: str) -> str:
        conv = str(uuid.uuid4())
        url = f"{_base_url()}/api/organizations/{org_id}/chat_conversations"
        resp = self.session.post(url, json={"uuid": conv, "name": ""}, timeout=30)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Claude create-conversation failed {resp.status_code}: {resp.text[:160]}")
        try:
            return resp.json().get("uuid", conv)
        except Exception:
            return conv

    def _upload_image(self, org_id: str, data: bytes, mime: str) -> str:
        """Upload one image to claude.ai (POST /api/{org}/upload, multipart),
        returning its file_uuid for the completion `files` field (or '')."""
        s = self.session
        ct = s.headers.pop("Content-Type", None)  # multipart must set its own
        try:
            mp = CurlMime()
            ext = _IMG_EXT.get(mime, "png")
            mp.addpart(name="file", filename=f"image.{ext}", content_type=mime, data=data)
            resp = s.post(f"{_base_url()}/api/{org_id}/upload", multipart=mp, timeout=60)
            if resp.status_code == 200:
                return str((resp.json() or {}).get("file_uuid") or "")
            _logger().warning({"event": "claude_upload_failed", "status": resp.status_code, "body": resp.text[:160]})
        except Exception as exc:
            _logger().warning({"event": "claude_upload_error", "error": str(exc)})
        finally:
            s.headers["Content-Type"] = ct or "application/json"
        return ""

    def _conversation_get(self, org_id: str) -> str:
        """Create a fresh conversation for every request to avoid history bleed
        and image accumulation across different frontend chats."""
        return self._create_conversation(org_id)

    def chat(self, messages: list[dict[str, Any]], model: str) -> Iterator[dict[str, Any]]:
        """Always-streaming generator of OpenAI chat.completion.chunk dicts."""
        if not self.is_available:
            raise RuntimeError("Claude not configured (providers.claude.session_key)")

        org_id = self._org_id_get()
        internal_model = _resolve_model(model)

        # Home Assistant: for smart-home questions prefetch the LIVE device
        # state and inject a compact summary so Claude can answer (read-only —
        # device control needs function calling, only on the paid path). Reuses
        # the ChatGPT free prefetch; no-op when HA is unconfigured or non-HA.
        try:
            from services.protocol.openai_v1_chat_complete import _prefetch_ha_context_if_needed
            messages = _prefetch_ha_context_if_needed(messages, None, "")
        except Exception as _ha_exc:
            _logger().debug({"event": "claude_ha_prefetch_skipped", "error": str(_ha_exc)[:120]})

        # Vision: upload any image_url parts and reference them by file_uuid.
        file_uuids: list[str] = []
        for data, mime in _extract_images(messages):
            fu = self._upload_image(org_id, data, mime)
            if fu:
                file_uuids.append(fu)
        if file_uuids:
            _logger().info({"event": "claude_images", "count": len(file_uuids)})

        payload: dict[str, Any] = {
            "prompt": _flatten_messages(messages),
            "parent_message_uuid": ROOT_PARENT_UUID,
            "timezone": str(_claude_cfg().get("timezone") or "Asia/Ho_Chi_Minh"),
            "attachments": [],
            "files": file_uuids,
            "sync_sources": [],
            "rendering_mode": "messages",
        }
        if internal_model:
            payload["model"] = internal_model
            
        raw_m = str(model or "").lower()
        effort = None
        if "-low" in raw_m: effort = "low"
        elif "-medium" in raw_m: effort = "medium"
        elif "-high" in raw_m: effort = "high"
        elif "-max" in raw_m: effort = "max"
        
        thinking = "-thinking" in raw_m or "-think" in raw_m
        
        if thinking or effort:
            if thinking:
                payload["thinking_mode"] = "auto"
            if effort:
                payload["effort"] = effort

        # Web search: opt-in via "-search"/"-websearch" model suffix or the
        # providers.claude.web_search config flag (claude.ai free supports it).
        if "-search" in raw_m or "-websearch" in raw_m or bool(_claude_cfg().get("web_search")):
            payload["tools"] = [{"type": "web_search_v0", "name": "web_search"}]

        _logger().info({"event": "claude_request", "model": internal_model or "auto", "effort": effort, "thinking": thinking, "msg_count": len(messages or [])})

        # Reuse the cached conversation; a stale/expired one 4xx's, so drop it
        # and retry once with a fresh conversation.
        last_status, last_body = 0, ""
        for attempt in (1, 2):
            conv_id = self._conversation_get(org_id)
            url = f"{_base_url()}/api/organizations/{org_id}/chat_conversations/{conv_id}/completion"
            resp = self.session.post(
                url, json=payload, timeout=300, stream=True,
                headers={"Accept": "text/event-stream"},
            )
            if resp.status_code == 200:
                return self._parse_stream(resp, model)
            last_status = resp.status_code
            try:
                # stream=True → phải đọc content để lấy body lỗi (resp.text hay rỗng).
                last_body = (resp.content or b"")[:300].decode("utf-8", "ignore")
            except Exception:
                try:
                    last_body = resp.text[:300]
                except Exception:
                    last_body = ""
            self._conv_id = ""  # stale conversation → recreate on next attempt
        raise RuntimeError(f"Claude completion failed {last_status}: {last_body}")

    def _parse_stream(self, response, request_model: str) -> Iterator[dict[str, Any]]:
        cid = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        sent_role = False
        actual_model = request_model

        try:
            for raw in response.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8", "ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
                line = line.strip()
                if not line or line.startswith(":") or line.startswith("event:"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue

                etype = str(event.get("type") or "")
                if etype == "error" or event.get("error"):
                    raise RuntimeError(f"Claude stream error: {str(event.get('error') or event)[:200]}")

                if etype == "message_start":
                    if isinstance(event.get("message"), dict):
                        m = event["message"].get("model")
                        if m:
                            actual_model = m

                # Incremental text across known claude.ai event shapes.
                text = ""
                if isinstance(event.get("completion"), str):
                    text = event["completion"]
                elif isinstance(event.get("delta"), dict):
                    text = str(event["delta"].get("text") or "")
                elif etype == "content_block_delta":
                    text = str((event.get("delta") or {}).get("text") or "")

                if text:
                    if not sent_role:
                        sent_role = True
                        yield _openai_chunk(actual_model, cid, created, {"role": "assistant", "content": text})
                    else:
                        yield _openai_chunk(actual_model, cid, created, {"content": text})

                if etype in ("message_stop", "completion_stop") or event.get("stop_reason"):
                    break
        except Exception as exc:
            _logger().error({"event": "claude_stream_error", "error": str(exc)})
            if not sent_role:
                yield _openai_chunk(actual_model, cid, created, {"role": "assistant", "content": f"[claude error] {exc}"})
        finally:
            try:
                response.close()
            except Exception:
                pass

        if not sent_role:
            yield _openai_chunk(actual_model, cid, created, {"role": "assistant", "content": ""})
        yield _openai_chunk(actual_model, cid, created, {}, finish="stop")


_backend = ClaudeFreeBackend()
_backends_by_key: dict[str, ClaudeFreeBackend] = {}

def _pick_session_key_from_pool(
    excluded: set[str],
    requires_image: bool = False,
) -> str:
    """Pick next Claude session key, rotating through ALL available sources.

    Priority order:
    1. account_service pool (type=claude) — manually added accounts
    2. captcha-solver profiles — ALL Google accounts already onboarded
       (providers.claude.accounts[]/profiles[]) iterated automatically
    3. Static session_key in config — last resort single account
    """
    # 1. Account service pool (manually added, full quota tracking)
    try:
        from services.account_service import account_service
        key = account_service.get_claude_session_key(
            excluded_tokens=excluded,
            requires_image=requires_image,
        )
        if key:
            return key
    except Exception:
        pass

    # 2. Captcha-solver profiles — iterate ALL, skip excluded
    cfg = _claude_cfg()
    key = _fetch_session_key_from_solver(cfg, excluded_keys=excluded)
    if key:
        return key

    # 3. Static config key fallback
    static = str(cfg.get("session_key") or "").strip()
    return static if static and static not in excluded else ""


def _classify_quota_error(error_msg: str) -> str:
    """Map a Claude error message to an exhausted quota type."""
    msg = error_msg.lower()
    for pattern, quota_type in _QUOTA_PATTERNS:
        if pattern in msg:
            return quota_type
    return "text_limit"


def _record_quota_failure(session_key: str, quota_type: str, attempt: int) -> None:
    """Write quota failure to account_service so UI and routing are updated.

    Handles both cases:
    - account_service pool accounts (JWT as access_token) → direct update
    - captcha-solver profiles (session_key from solver) → persist via profile name
    """
    try:
        from services.account_service import account_service
        from datetime import datetime
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Case 1: captcha-solver profile — use stable profile name for persistence
        profile = _profile_by_session.get(session_key)
        if profile:
            account_service.record_profile_quota_failure(
                profile=profile,
                quota_type=quota_type,
                account_type="claude",
            )
            _logger().info({
                "event": "claude_profile_rotate",
                "reason": "quota_burnt",
                "exhausted_item": quota_type,
                "profile": profile,
                "rotated_at": now_str,
                "attempt": attempt,
            })
            return

        # Case 2: account_service pool account (session_key IS the access_token)
        if quota_type == "file_upload":
            account_service.mark_image_failed(session_key)
        elif quota_type == "advanced_data_analysis":
            account_service.mark_analysis_failed(session_key)
        else:
            account_service.demote_account(session_key)
        account_service.update_account(session_key, {
            "last_quota_exhausted": quota_type,
            "last_quota_exhausted_at": now_str,
        })
        acc = account_service.get_account(session_key)
        email = (acc or {}).get("email") or session_key[:24]
        _logger().info({
            "event": "claude_account_rotate",
            "reason": "quota_burnt",
            "exhausted_item": quota_type,
            "account": email,
            "rotated_at": now_str,
            "attempt": attempt,
        })
    except Exception as exc:
        _logger().warning({"event": "claude_quota_record_failed", "error": str(exc)[:120]})


def _mark_claude_ok(session_key: str) -> None:
    """Claude chạy OK → reset account về active (self-heal badge 'error' kẹt lại từ
    lần 403 tạm thời). Account claude lưu theo PROFILE NAME (vd google-benbap115),
    nên tra ngược qua _profile_by_session rồi update theo profile."""
    try:
        from services.account_service import account_service
        tok = _profile_by_session.get(session_key) or session_key
        acc = account_service.get_account(tok)
        if acc and acc.get("status") != "active":
            account_service.update_account(tok, {"status": "active", "fail": 0})
    except Exception:
        pass


def handle_claude_chat(
    model: str,
    messages: list[dict[str, Any]],
    stream: Any,
    body: dict[str, Any] | None = None,
) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """Provider handler with multi-account pool rotation.

    Iterates through available Claude accounts in FIFO order.
    On quota/auth error, marks the account and tries the next one.
    """
    requires_image = any(
        isinstance(p, dict) and p.get("type") == "image_url"
        for m in messages
        for p in (m.get("content") if isinstance(m.get("content"), list) else [])
    )
    excluded: set[str] = set()
    max_attempts = 8
    last_error: Exception | None = None
    global _backends_by_key

    for attempt in range(max_attempts):
        session_key = _pick_session_key_from_pool(excluded, requires_image)
        if not session_key:
            break
        if session_key not in _backends_by_key:
            class _KeyedBackend(ClaudeFreeBackend):
                def _cookie_header(self_inner) -> str:
                    return f"sessionKey={session_key}"
            _backends_by_key[session_key] = _KeyedBackend()

        keyed = _backends_by_key[session_key]
        try:
            if stream:
                _mark_claude_ok(session_key)
                return keyed.chat(messages, model)
            content = _collect_text(keyed.chat(messages, model))
            _mark_claude_ok(session_key)
            return {
                "id": f"chatcmpl-{uuid.uuid4().hex}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
        except Exception as exc:
            last_error = exc
            err_msg = str(exc).lower()
            # claude.ai thường trả 4xx/5xx với body RỖNG ("Claude completion failed 429: "),
            # nên phải phân loại theo MÃ HTTP, không chỉ theo chữ trong body.
            _ms = re.search(r"failed\s+(\d{3})", err_msg)
            status = int(_ms.group(1)) if _ms else 0
            is_quota = status in (429, 529) or any(p in err_msg for p in (
                "rate limit", "too many", "overloaded", "exceeded",
                "usage limit", "file", "upload", "vision", "analysis",
            ))
            is_auth = status in (401, 403) or any(p in err_msg for p in (
                "session", "unauthorized", "expired",
            ))
            is_transient = status in (400, 408, 500, 502, 503, 504)
            if is_quota:
                quota_type = _classify_quota_error(str(exc))
                _record_quota_failure(session_key, quota_type, attempt)
            elif is_auth:
                try:
                    from services.account_service import account_service
                    account_service.update_account(session_key, {"status": "error"})
                except Exception:
                    pass
                _logger().warning({"event": "claude_auth_error", "attempt": attempt, "error": str(exc)[:120]})
            elif is_transient:
                # 400/5xx có thể do account/phiên này → thử account khác thay vì fail luôn.
                _logger().warning({"event": "claude_transient_rotate", "status": status, "attempt": attempt})
            else:
                raise  # lỗi thực sự không rõ → bubble up ngay
            excluded.add(session_key)
            continue

    # All accounts exhausted or no pool configured
    if last_error is not None:
        raise last_error
    raise RuntimeError("Không có tài khoản Claude khả dụng")


# ═══════════════════════════════════════════════════════════════════════════
# Router (OpenAI-compatible, dedicated /v1/claude/* path)
# ═══════════════════════════════════════════════════════════════════════════

def create_router() -> APIRouter:
    router = APIRouter(prefix="/v1/claude", tags=["claude"])

    @router.post("/chat/completions")
    async def claude_chat_completions(
        body: ChatCompletionRequest,
        authorization: str | None = Header(default=None),
    ):
        """OpenAI-format chat completion served by the claude.ai web backend."""
        from api.support import require_identity
        require_identity(authorization)

        model = str(body.model or "claude/auto")
        messages = body.messages or []

        if not _backend.is_available:
            raise HTTPException(
                status_code=503,
                detail={"error": "Claude not configured: set providers.claude.session_key in config.json"},
            )

        if body.stream:
            # Run the whole claude.ai call lazily INSIDE the generator so tokens
            # flush to the client as they arrive. Starlette iterates this sync
            # generator in a threadpool, so the blocking reads never stall the
            # event loop. (Previously chat() was awaited up-front, buffering the
            # entire response before the first byte → TTFB == total.)
            def sse() -> Iterator[str]:
                try:
                    for chunk in _backend.chat(messages, model):
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                except Exception as exc:
                    _logger().error({"event": "claude_chat_failed", "error": str(exc)})
                    yield f"data: {json.dumps({'error': {'message': f'Claude backend error: {exc}'}}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(sse(), media_type="text/event-stream")

        # Non-stream: collect off the event loop.
        try:
            chunks = await run_in_threadpool(_backend.chat, messages, model)
            content = await run_in_threadpool(_collect_text, chunks)
        except Exception as exc:
            _logger().error({"event": "claude_chat_failed", "error": str(exc)})
            raise HTTPException(status_code=502, detail={"error": f"Claude backend error: {exc}"})
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}", "object": "chat.completion",
            "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    @router.get("/models")
    async def claude_models(authorization: str | None = Header(default=None)):
        from api.support import require_identity
        require_identity(authorization)
        ids = ["claude/auto", "claude/auto-search", "claude/sonnet-4.5", "claude/sonnet-4.5-search"]
        for b in ["sonnet-5", "sonnet-4.6", "opus-4.8", "haiku-4.5"]:
            for e in ["", "-medium", "-high", "-max"]:
                for t in ["", "-thinking"]:
                    ids.append(f"claude/{b}{e}{t}")
        # Any model also accepts a trailing "-search" to enable web search.
        return {
            "object": "list",
            "data": [{"id": i, "object": "model", "owned_by": "claude"} for i in ids],
        }

    return router
