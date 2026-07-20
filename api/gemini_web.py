"""Gemini web-cookie provider — gemini.google.com qua HTTP API (gemini_webapi).

Đường thứ 3 cho Gemini, song song với:
  - gemini_free (gemini/): AI Studio API key, generativelanguage.googleapis.com
  - gemini_web  (gmw/):    DOM scrape qua captcha-solver browser (chậm)

Path này nói chuyện THẲNG với backend gemini.google.com bằng cookie Google
(`__Secure-1PSID` + `__Secure-1PSIDTS`) — pattern y hệt Claude free sessionKey
(tham khảo https://github.com/luuquangvu/Gemini-FastAPI, lib HanaokaYuzu/Gemini-API).

Cookie lấy theo thứ tự:
  1. config providers.gemini_web_api.psid / psidts (dán tay)
  2. captcha-solver GET /v1/gemini-web/{profile}/cookies (reuse Google profile
     đã onboard — như Claude fetch sessionKey), cache 5'.

Model prefix: gma/ (vd gma/auto, gma/gemini-3-flash). Hỗ trợ vision (files),
downscale 896 qua knob gemini_vision_max_dim (0 = tắt).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import time
import uuid
from typing import Any, Iterator

from curl_cffi import requests


# ── Hotfix: Google chuyển media nhạc từ candidate[12][86] sang [12][0]['87'] ─
# gemini_webapi 2026-07 vẫn đọc [12][86] → media=[] dù nhạc đã tạo (Lyria).
# Wrap _parse_candidate: nếu lib không thấy media thì tự bóc ở vị trí mới,
# cấu trúc bên trong y hệt ([0][1][7]=thumb+mp3, [1][1][7]=thumb+mp4).
def _patch_music_parsing() -> None:
    from gemini_webapi.client import GeminiClient
    from gemini_webapi.types import GeneratedMedia
    from gemini_webapi.utils.parsing import get_nested_value

    if getattr(GeminiClient._parse_candidate, "_music87_patched", False):
        return
    orig = GeminiClient._parse_candidate

    def patched(self, candidate_data, cid, rid, rcid):
        out = orig(self, candidate_data, cid, rid, rcid)
        try:
            text, thoughts, web_images, gen_images, gen_videos, gen_media = out
            if gen_media:
                return out
            media_data = get_nested_value(candidate_data, [12, 0, "87"], [])
            if not media_data:
                return out
            mp3_list = get_nested_value(media_data, [0, 1, 7], [])
            mp4_list = get_nested_value(media_data, [1, 1, 7], [])
            mp3_thumb, mp3_url = (mp3_list[0], mp3_list[1]) if len(mp3_list) >= 2 else ("", "")
            mp4_thumb, mp4_url = (mp4_list[0], mp4_list[1]) if len(mp4_list) >= 2 else ("", "")
            if not (mp3_url or mp4_url):
                return out
            title = str(get_nested_value(media_data, [0, 1, 2], "") or "").strip() or "[Media]"
            gen_media = [GeneratedMedia(
                url=mp4_url, thumbnail=mp4_thumb,
                mp3_url=mp3_url, mp3_thumbnail=mp3_thumb, title=title,
                cid=cid, rid=rid, rcid=rcid, client_ref=self, proxy=self.proxy,
            )]
            return (text, thoughts, web_images, gen_images, gen_videos, gen_media)
        except Exception:
            return out

    patched._music87_patched = True
    GeminiClient._parse_candidate = patched


try:
    _patch_music_parsing()
except Exception:
    pass


def _config():
    from services.config import config
    return config


def _logger():
    from utils.log import logger
    return logger


def _cfg() -> dict[str, Any]:
    return (_config().data.get("providers") or {}).get("gemini_web_api") or {}


# ── Cookie source ────────────────────────────────────────────────────────────

_cookie_cache: dict[str, tuple[float, dict[str, str]]] = {}
_COOKIE_TTL = 300  # captcha-solver fetch cache


def _solver_cfg() -> dict[str, str]:
    """captcha-solver url/key: own config → gemini_web → flow (same solver)."""
    providers = _config().data.get("providers") or {}
    for name in ("gemini_web_api", "gemini_web", "flow"):
        c = providers.get(name) or {}
        raw = str(c.get("captcha_solver_url") or "").strip()
        if raw:
            from services.captcha import captcha_base
            return {"url": captcha_base(raw), "api_key": str(c.get("captcha_solver_api_key") or "")}
    return {"url": "", "api_key": ""}


def _store_profiles(groups: set[str]) -> list[str]:
    """Tên profile solver lấy TỪ KHO TÀI KHOẢN (account_service), cho các account
    thuộc `groups`. Tên profile được lưu ở field email/profile/name (vd account
    gemini_web_api có email='google-benbap115'). Nhờ vậy mọi account đã onboard
    tự xuất hiện — khỏi khai báo tay trong providers.*.profiles."""
    try:
        from services.account_service import account_service, account_group
        accs = account_service._accounts
        items = list(accs.values()) if isinstance(accs, dict) else list(accs)
    except Exception:
        return []
    out: list[str] = []
    for a in items:
        if not isinstance(a, dict) or account_group(a) not in groups:
            continue
        p = str(a.get("profile") or a.get("email") or a.get("name") or "").strip()
        if p and p not in out:
            out.append(p)
    return out


def _profiles() -> list[str]:
    cfg = _cfg()
    profiles: list[str] = []

    for entry in (cfg.get("accounts") or []):
        if isinstance(entry, dict):
            p = str(entry.get("profile") or "").strip()
            if p and p not in profiles:
                profiles.append(p)

    profs = cfg.get("profiles")
    if isinstance(profs, list):
        for p in profs:
            p = str(p).strip()
            if p and p not in profiles:
                profiles.append(p)

    # Tự đọc thêm từ kho tài khoản (account group gemini_web_api).
    for p in _store_profiles({"gemini_web_api"}):
        if p not in profiles:
            profiles.append(p)

    if not profiles:
        # fallback: dùng chính profile của gemini_web DOM scrape (đã login sẵn)
        gw = (_config().data.get("providers") or {}).get("gemini_web") or {}
        gw_accs = gw.get("accounts") if isinstance(gw.get("accounts"), list) else []
        for a in gw_accs:
            if isinstance(a, dict):
                p = str(a.get("profile") or "").strip()
                if p and p not in profiles:
                    profiles.append(p)
        p = str(gw.get("profile") or "").strip()
        if p and p not in profiles:
            profiles.append(p)
            
    return profiles or ["gemini-web-default"]


def _fetch_cookies_from_solver(profile: str) -> dict[str, str]:
    now = time.time()
    hit = _cookie_cache.get(profile)
    if hit and (now - hit[0]) < _COOKIE_TTL:
        return hit[1]
    sc = _solver_cfg()
    if not sc["url"]:
        return {}
    try:
        headers = {"Authorization": f"Bearer {sc['api_key']}"} if sc["api_key"] else {}
        r = requests.get(f"{sc['url']}/v1/gemini-web/{profile}/cookies",
                         headers=headers, timeout=30, impersonate="chrome110")
        if r.status_code == 200:
            cookies = (r.json() or {}).get("cookies") or {}
            if cookies.get("__Secure-1PSID"):
                _cookie_cache[profile] = (now, cookies)
                return cookies
        _logger().warning({"event": "gma_cookie_fetch_failed", "profile": profile,
                           "status": r.status_code, "body": r.text[:120]})
    except Exception as exc:
        _logger().warning({"event": "gma_cookie_fetch_error", "profile": profile,
                           "error": str(exc)[:120]})
    return {}


def _get_cookies_ranked(required_features: list[str] = None) -> list[tuple[str, str, str]]:
    """Return a list of (psid, psidts, profile) ranked by health/quota.
    Falls back to single psid config if present."""
    cfg = _cfg()
    psid = str(cfg.get("psid") or "").strip()
    if psid:
        return [(psid, str(cfg.get("psidts") or "").strip(), "static-config")]
        
    from services.account_service import account_service
    profiles = _profiles()
    raw_accounts = [{"profile": p, "status": "active"} for p in profiles]
    
    ranked = account_service.normalize_and_rank_accounts(
        raw_accounts,
        account_type="gemini_web_api",
        required_features=required_features or ["text"],
    )
    
    results = []
    missing = []
    for acc in ranked:
        profile = acc.get("profile")
        if not profile: continue
        c = _fetch_cookies_from_solver(profile)
        if c.get("__Secure-1PSID"):
            results.append((c["__Secure-1PSID"], c.get("__Secure-1PSIDTS", ""), profile))
        else:
            missing.append(profile)

    # Rank AUTHENTICATED profiles (account status AVAILABLE) first so vision/
    # image requests hit a working account immediately instead of churning
    # through guest cookies (which reject with 1100/UNAUTHENTICATED). Stable
    # sort preserves the health/quota order within each tier.
    def _auth_rank(item: tuple[str, str, str]) -> int:
        hit = _auth_status.get(item[0][:32])
        if hit is None:
            return 1          # unknown → middle
        return 0 if hit[1] else 2   # authenticated first, guest last
    results.sort(key=_auth_rank)

    # Self-heal: no usable 1PSID in the WHOLE pool → the Google session expired;
    # relogin the missing profiles (SSO/full via saved creds, cooldown-bounded).
    # Only when the pool is fully down so a working pool is never disturbed; the
    # next request re-fetches cookies once the solver finishes.
    if not results and missing:
        try:
            from services.solver_selfheal import try_relogin, GEMINI
            sc = _solver_cfg()
            for p in missing:
                try_relogin(sc.get("url", ""), sc.get("api_key", ""), GEMINI, p)
        except Exception:
            pass

    return results

def is_available() -> bool:
    return len(_get_cookies_ranked()) > 0


# ── Dedicated asyncio loop (gemini_webapi là async-only) ────────────────────

_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            t = threading.Thread(target=_loop.run_forever, daemon=True,
                                 name="gemini-webapi-loop")
            t.start()
        return _loop


def _run(coro, timeout: float = 240):
    return asyncio.run_coroutine_threadsafe(coro, _get_loop()).result(timeout)


# ── Client cache ─────────────────────────────────────────────────────────────

_clients: dict[str, Any] = {}
_client_lock = threading.Lock()

# psid[:32] -> (ts, is_available). Records whether a profile's cookies are
# AUTHENTICATED (account status AVAILABLE) vs guest (UNAUTHENTICATED). Used to
# rank authenticated accounts first so vision/image hit a working account.
_auth_status: dict[str, tuple[float, bool]] = {}


def _record_auth_status(key: str, cli) -> None:
    try:
        st = getattr(cli, "account_status", None)
        avail = st is not None and getattr(st, "name", "") == "AVAILABLE"
        _auth_status[key] = (time.time(), bool(avail))
    except Exception:
        pass


def _get_client(psid: str, psidts: str):
    key = psid[:32]
    with _client_lock:
        cli = _clients.get(key)
        if cli is not None:
            return cli
        from gemini_webapi import GeminiClient
        cli = GeminiClient(secure_1psid=psid, secure_1psidts=psidts or None, watchdog_timeout=180, timeout=180)
        _run(cli.init(timeout=180, auto_close=False, auto_refresh=True), timeout=60)
        _clients[key] = cli
        _record_auth_status(key, cli)
        _logger().info({"event": "gma_client_init", "psid_prefix": psid[:12],
                        "auth": _auth_status.get(key, (0, None))[1]})
        return cli


def _drop_client(psid: str) -> None:
    with _client_lock:
        _clients.pop(psid[:32], None)
    _cookie_cache.clear()


def prewarm_clients() -> int:
    """Pre-build & cache the GeminiClient for every configured gma account so the
    FIRST real request doesn't pay the ~10s cli.init() cold-start (measured:
    cold 10s vs warm 2.4–3.7s). Idempotent — _get_client returns the cached
    client if already warm. Called from the web_prewarmer loop."""
    try:
        creds = _get_cookies_ranked(required_features=["text"])
    except Exception as exc:
        _logger().warning({"event": "gma_prewarm_creds_failed", "error": str(exc)[:120]})
        return 0
    warmed = 0
    for psid, psidts, profile in creds:
        try:
            _get_client(psid, psidts)
            warmed += 1
        except Exception as exc:
            _logger().warning({"event": "gma_prewarm_failed", "profile": str(profile)[:40],
                               "error": str(exc)[:120]})
    if warmed:
        _logger().info({"event": "gma_prewarm_done", "clients": warmed})
    return warmed


# ── Model & message helpers ──────────────────────────────────────────────────

# Tên thân thiện theo UI Gemini (3.5 Flash / 3.1 Pro + Tiêu chuẩn/Mở rộng) →
# model_name nội bộ của gemini_webapi. "Mở rộng" = tier advanced (tư duy sâu).
# Lib KHÔNG có model "Flash-Lite" riêng → map về flash. Tên lib gốc vẫn route OK.
_GMA_ALIASES = {
    # Tên khớp UI Gemini (không dấu cho an toàn client) — bộ hiển thị chính
    "3.5-flash": "gemini-3-flash",                  # 3.5 Flash (Tiêu chuẩn)
    "3.5-flash-mo-rong": "gemini-3-flash-advanced", # 3.5 Flash (Mở rộng)
    "3.1-pro": "gemini-3-pro",                      # 3.1 Pro (Tiêu chuẩn)
    "3.1-pro-mo-rong": "gemini-3-pro-advanced",     # 3.1 Pro (Mở rộng)
    "3.1-flash-lite": "gemini-3-flash",             # Flash-Lite (lib chưa tách → flash)
    # Alias cũ — vẫn nhận để không vỡ request đã cấu hình
    "flash": "gemini-3-flash",
    "flash-lite": "gemini-3-flash",
    "flash-thinking": "gemini-3-flash-thinking",
    "flash-extended": "gemini-3-flash-advanced",
    "pro": "gemini-3-pro",
    "pro-extended": "gemini-3-pro-advanced",
}


def _resolve_model(model: str, prompt: str = ""):

    """alias → gemini_webapi Model enum; None = để server tự chọn."""
    m = str(model or "").strip().lower()
    for pfx in ("gma/", "gemini-web/", "gemini_web_api/"):
        if m.startswith(pfx):
            m = m[len(pfx):]
            break
    # 1. Smart routing first! If UI selected auto, we intercept music prompts.
    if not m or m == "auto":
        p = prompt.lower()
        is_drawing = any(k in p for k in ("vẽ", "tạo ảnh", "bức ảnh", "poster", "hình nền", "ảnh bìa"))
        is_music = any(k in p for k in ("nhạc", "bài hát", "music", "song", "audio", "hát", "giai điệu", "ballad", "pop", "rap"))
        
        if is_music:
            if is_drawing and not any(k in p for k in ("tạo nhạc", "sáng tác", "làm nhạc", "viết nhạc")):
                pass
            else:
                m = "3.1-pro"
        # Vẽ ảnh cũng route Pro: flash hay decline giả "limit resets" (như nhạc)
        if (not m or m == "auto") and is_drawing:
            m = "3.1-pro"

    # 2. If it's still auto, fallback to config
    if not m or m == "auto":
        try:
            from services.config import config as _config
            ms = _config.data.get("model_settings") or {}
            
            # Check explicit default_model
            default_model = (ms.get("default_models") or {}).get("gemini_web_api")
            if default_model:
                m = str(default_model).strip()
                if m.startswith("gma/"):
                    m = m[4:]
                    
            # Fallback to first enabled model
            if not m or m == "auto":
                enabled = (ms.get("enabled_models") or {}).get("gemini_web_api")
                if isinstance(enabled, list):
                    for em in enabled:
                        em = str(em).strip()
                        if em.startswith("gma/"):
                            em = em[4:]
                        if em and em != "auto":
                            m = em
                            break
        except Exception:
            pass

    if not m or m == "auto":
        m = str(_cfg().get("model") or "").strip().lower()
        
    if not m or m == "auto":
        m = "3.5-flash"

    m = _GMA_ALIASES.get(m, m)
    try:
        from gemini_webapi.constants import Model
        return Model.from_name(m)
    except Exception:
        _logger().info({"event": "gma_unknown_model_fallback", "model": m})
        return None


def _downscale(data: bytes, mime: str) -> tuple[bytes, str]:
    try:
        max_dim = int(_config().data.get("gemini_vision_max_dim", 896) or 0)
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
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
        resized = img.convert("RGB") if img.mode not in ("RGB", "L") else img
        resized = resized.resize(size, Image.LANCZOS)
        buf = BytesIO()
        resized.save(buf, format="JPEG", quality=85)
        out = buf.getvalue()
        _logger().info({"event": "gma_image_downscaled", "from": [w, h],
                        "to": list(size), "bytes": [len(data), len(out)]})
        return out, "image/jpeg"
    except Exception:
        return data, mime


def _prepare_files(messages: list[dict[str, Any]]) -> list[str]:
    """image_url parts → temp files (gemini_webapi nhận path). Caller xoá sau."""
    import base64
    paths: list[str] = []
    for msg in messages or []:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for p in content:
            if not isinstance(p, dict) or p.get("type") != "image_url":
                continue
            url = str(((p.get("image_url") or {}).get("url") or "")).strip()
            data, mime = b"", "image/png"
            if url.startswith("data:"):
                try:
                    head, b64 = url.split(",", 1)
                    mime = (head[5:].split(";")[0] or "image/png").lower()
                    data = base64.b64decode(b64)
                except Exception:
                    continue
            elif url.startswith("http"):
                try:
                    rr = requests.get(url, timeout=20, impersonate="chrome110")
                    if rr.status_code == 200 and rr.content:
                        mime = (rr.headers.get("content-type") or "image/png").split(";")[0].lower()
                        data = rr.content
                except Exception:
                    continue
            if not data:
                continue
            data, mime = _downscale(data, mime)
            ext = {"image/jpeg": ".jpg", "image/png": ".png",
                   "image/webp": ".webp", "image/gif": ".gif"}.get(mime, ".png")
            fd, path = tempfile.mkstemp(suffix=ext, prefix="gma_")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            paths.append(path)
    return paths


def _cleanup(paths: list[str]) -> None:
    for p in paths:
        try:
            os.unlink(p)
        except Exception:
            pass


def _openai_chunk(model: str, cid: str, created: int,
                  delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
    return {
        "id": cid, "object": "chat.completion.chunk", "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


# ── Media local storage ──────────────────────────────────────────────────────

def _save_media_via_client(media_obj, gma_dir, full_size: bool = False) -> str | None:
    """Download ảnh/nhạc dùng method .save() của gemini_webapi (authenticated session).
    Trả về relative path gma/{filename} hoặc None nếu thất bại.

    full_size=True (ảnh sinh ra): tải bản gốc thay vì thumbnail (khớp reference
    Gemini-FastAPI). Nếu bản full 403/lỗi thì tự thử lại bản mặc định."""
    try:
        filename = f"{uuid.uuid4().hex}"
        # _run() dùng ThreadPoolExecutor riêng + asyncio.run → safe trong FastAPI workers
        try:
            saved = _run(media_obj.save(path=str(gma_dir), filename=filename,
                                        **({"full_size": True} if full_size else {})))
        except Exception:
            if not full_size:
                raise
            _logger().info({"event": "gma_media_fullsize_retry"})
            saved = _run(media_obj.save(path=str(gma_dir), filename=filename))

        # GeneratedMedia returns a dict like {'audio': path, 'video': path}
        saved_path = None
        if isinstance(saved, dict):
            # Nhạc: ưu tiên audio (.mp3); GeneratedVideo thường chỉ có key video
            saved_path = saved.get("audio") or saved.get("video")
        elif isinstance(saved, str):
            saved_path = saved
            
        if saved_path and os.path.exists(str(saved_path)):
            fname = os.path.basename(str(saved_path))
            _logger().info({"event": "gma_media_saved", "file": fname})
            return f"gma/{fname}"
            
        _logger().warning({"event": "gma_media_save_empty", "saved": str(saved)})
    except Exception as exc:
        _logger().warning({"event": "gma_media_save_error", "error": str(exc)[:200]})
    return None


# ── Handler (main /v1/chat/completions router) ──────────────────────────────

def _generate_stream(client, prompt: str, files: list[str], model_enum, base_url: str = "", cookies: dict | None = None):
    kwargs: dict[str, Any] = {}
    if files:
        kwargs["files"] = files
    if model_enum is not None:
        kwargs["model"] = model_enum

    _base = (base_url or "").rstrip("/")
    from services.config import config as _cfg
    gma_dir = _cfg.images_dir / "gma"
    gma_dir.mkdir(parents=True, exist_ok=True)

    import queue, asyncio, uuid
    q = queue.Queue()

    async def _task():
        try:
            # gemini_webapi streams via generate_content_stream() — an async
            # generator yielding ModelOutput deltas (text_delta + media). NOT
            # generate_content(stream=True) (that returns a complete object and
            # isn't async-iterable). Media (images/music/videos) may arrive on
            # any chunk, so accumulate + dedupe across the whole stream.
            seen: set = set()
            imgs: list = []
            mus: list = []
            vids: list = []
            async for chunk in client.generate_content_stream(prompt, **kwargs):
                td = getattr(chunk, "text_delta", "") or ""
                if td:
                    q.put(("text", td))
                for coll, dst in ((getattr(chunk, "images", None) or [], imgs),
                                  (getattr(chunk, "media", None) or [], mus),
                                  (getattr(chunk, "videos", None) or [], vids)):
                    for it in coll:
                        k = getattr(it, "url", None) or id(it)
                        if k not in seen:
                            seen.add(k)
                            dst.append(it)
            q.put(("media", {"images": imgs, "media": mus, "videos": vids}))
        except Exception as e:
            q.put(("error", e))
        finally:
            q.put(("done", None))

    asyncio.run_coroutine_threadsafe(_task(), _get_loop())

    md_text = ""
    while True:
        mtype, mdata = q.get()
        if mtype == "done":
            break
        elif mtype == "error":
            raise mdata
        elif mtype == "text":
            yield mdata
        elif mtype == "media":
            images = mdata.get("images", [])
            for img in images:
                saved_rel = _save_media_via_client(img, gma_dir, full_size=True)
                if saved_rel:
                    title = str(getattr(img, "title", "") or "Ảnh").replace("[", "").replace("]", "").strip() or "Ảnh"
                    md_text += f"\n\n![{title}]({_base}/images/{saved_rel})"
                else:
                    cdn_url = getattr(img, "url", "")
                    if cdn_url: md_text += f"\n\n![Generated Image]({cdn_url})"

            for attr, label, ext in [("media", "🎵 Nhạc", ".mp3"), ("videos", "🎬 Video", ".mp4")]:
                media_list = mdata.get(attr, [])
                for m in media_list:
                    title = getattr(m, "title", f"Generated {label}")
                    thumb_url = getattr(m, "mp4_thumbnail", "") or getattr(m, "thumbnail_url", "")
                    rel = _save_media_via_client(m, gma_dir)
                    if rel:
                        final_url = f"{_base}/images/{rel}" if _base else f"/images/{rel}"
                        if thumb_url:
                            thumb_rel = None
                            try:
                                thumb_filename = f"{uuid.uuid4().hex}.jpg"
                                thumb_path = gma_dir / thumb_filename
                                import requests as sync_req
                                tr = sync_req.get(thumb_url, timeout=30)
                                if tr.status_code == 200:
                                    thumb_path.write_bytes(tr.content)
                                    thumb_rel = f"gma/{thumb_filename}"
                            except Exception: pass

                            if thumb_rel:
                                thumb_final = f"{_base}/images/{thumb_rel}" if _base else f"/images/{thumb_rel}"
                                md_text += f"\n\n[![{title}]({thumb_final})]({final_url})\n\n[▶️ Bấm để nghe/xem]({final_url})"
                            else:
                                md_text += f"\n\n[▶️ Bấm để nghe/xem {label}: {title}]({final_url})"
                        else:
                            md_text += f"\n\n[▶️ Bấm để nghe/xem {label}: {title}]({final_url})"
                    else:
                        cdn_url = getattr(m, "url", "") or getattr(m, "mp3_url", "")
                        if cdn_url: md_text += f"\n\n[{label}: {title}]({cdn_url})"

            if md_text:
                yield md_text

def _generate_text(client, prompt: str, files: list[str], model_enum, base_url: str = "", cookies: dict | None = None) -> str:
    res = ""
    for chunk in _generate_stream(client, prompt, files, model_enum, base_url, cookies):
        res += chunk
    return res


import json
import re

TOOL_WRAP_HINT = (
    "\n\n### SYSTEM: TOOL CALLING PROTOCOL (MANDATORY) ###\n"
    "If tool execution is required, you MUST adhere to this EXACT protocol. No exceptions.\n\n"
    "1. OUTPUT RESTRICTION: Your response MUST contain ONLY the [ToolCalls] block. Conversational filler, preambles, or concluding remarks are STRICTLY PROHIBITED.\n"
    "2. WRAPPING LOGIC: Every parameter value MUST be enclosed in a markdown code block. Use 3 backticks (```) by default. If the value contains backticks, the outer fence MUST be longer than any sequence inside (e.g., ````).\n"
    "3. TAG SYMMETRY: All tags MUST be balanced and closed in the exact reverse order of opening. Incomplete or unclosed blocks are strictly prohibited.\n\n"
    "REQUIRED SYNTAX:\n"
    "[ToolCalls]\n"
    "[Call:tool_name]\n"
    "[CallParameter:parameter_name]\n"
    "```\n"
    "value\n"
    "```\n"
    "[/CallParameter]\n"
    "[/Call]\n"
    "[/ToolCalls]\n\n"
    "CRITICAL: Do NOT mix natural language with protocol tags. Either respond naturally OR provide the protocol block alone. There is no middle ground."
)

def _build_tool_prompt(tools: list[dict[str, Any]]) -> str:
    if not tools:
        return ""
    lines = [
        "SYSTEM INTERFACE: You have access to the following technical tools. You MUST invoke them when necessary to fulfill the request, strictly adhering to the provided JSON schemas."
    ]
    for tool_obj in tools:
        func = tool_obj.get("function", {})
        desc = func.get("description", "No description provided.")
        lines.append(f"Tool `{func.get('name')}`: {desc}")
        if func.get("parameters"):
            lines.extend(["Arguments JSON schema:", json.dumps(func.get("parameters"), ensure_ascii=False)])
        else:
            lines.append("Arguments JSON schema: {}")
            
    lines.append(TOOL_WRAP_HINT)
    return "\n".join(lines)

def _extract_tool_calls(text: str) -> tuple[str, list[dict[str, Any]]]:
    tool_calls = []
    call_re = re.compile(r"\[Call:([^]]+)\](.*?)\[/Call\]", re.DOTALL | re.IGNORECASE)
    param_re = re.compile(r"\[CallParameter:([^]]+)\](.*?)\[/CallParameter\]", re.DOTALL | re.IGNORECASE)
    
    for match in call_re.finditer(text):
        name = match.group(1).strip()
        body = match.group(2)
        args_dict = {}
        
        param_matches = list(param_re.finditer(body))
        if param_matches:
            for pmatch in param_matches:
                pname = pmatch.group(1).strip()
                pval = pmatch.group(2).strip()
                pval = re.sub(r"^`{3,}.*?\n", "", pval)
                pval = re.sub(r"\n`{3,}$", "", pval).strip()
                try:
                    args_dict[pname] = json.loads(pval)
                except Exception:
                    args_dict[pname] = pval
        else:
            clean_body = body.strip()
            clean_body = re.sub(r"^`{3,}.*?\n", "", clean_body)
            clean_body = re.sub(r"\n`{3,}$", "", clean_body).strip()
            if clean_body.startswith("{"):
                try:
                    args_dict = json.loads(clean_body)
                except Exception:
                    pass
                    
        tool_calls.append({
            "id": f"call_{uuid.uuid4().hex[:16]}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(args_dict, ensure_ascii=False)
            }
        })
        
    cleaned_text = re.sub(r"\[ToolCalls\].*?\[/ToolCalls\]", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    return cleaned_text, tool_calls

def _flatten_messages_with_tools(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> str:
    parts = []
    
    if tools:
        sys_prompt = _build_tool_prompt(tools)
        parts.append(f"System: {sys_prompt}")
        
    for msg in messages or []:
        role = str(msg.get("role") or "user")
        content = msg.get("content", "")
        
        text = ""
        if isinstance(content, list):
            text = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("type") == "text")
        else:
            text = str(content or "")
            
        if role == "tool":
            tool_name = msg.get("name", "unknown")
            text = f"[ToolResults]\n[Result:{tool_name}]\n[ToolResult]\n{text}\n[/ToolResult]\n[/Result]\n[/ToolResults]"
            
        tool_calls = msg.get("tool_calls", [])
        if role == "assistant" and tool_calls:
            calls_text = []
            for tc in tool_calls:
                func = tc.get("function", {})
                args = func.get("arguments", "{}")
                try:
                    args_dict = json.loads(args)
                    formatted_params = ""
                    for k, v in args_dict.items():
                        v_str = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else str(v)
                        formatted_params += f"[CallParameter:{k}]\n```\n{v_str}\n```\n[/CallParameter]\n"
                    calls_text.append(f"[Call:{func.get('name')}]\n{formatted_params}[/Call]")
                except Exception:
                    calls_text.append(f"[Call:{func.get('name')}]\n```\n{args}\n```\n[/Call]")
                    
            if calls_text:
                text += ("\n" if text else "") + "[ToolCalls]\n" + "\n".join(calls_text) + "\n[/ToolCalls]"
                
        if not text.strip():
            continue
            
        label = {"system": "System", "assistant": "Assistant", "user": "User", "tool": "Tool"}.get(role, role.capitalize())
        parts.append(f"{label}: {text}")
        
    parts.append("Assistant:")
    return "\n\n".join(parts)


def handle_gemini_web_api_chat(
    model: str,
    messages: list[dict[str, Any]],
    stream: Any,
    body: dict[str, Any] | None = None,
    base_url: str = "",
) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """Provider handler cho router chính (gma/* models)."""
    from services.account_service import account_service

    # Lấy tools từ request body
    tools = body.get("tools") if body else None
    prompt = _flatten_messages_with_tools(messages, tools)
    files = _prepare_files(messages)
    model_enum = _resolve_model(model, prompt)
    if files:
        _logger().info({"event": "gma_images", "count": len(files)})
    _logger().info({"event": "gma_request", "model": str(model_enum or "auto"),
                    "msg_count": len(messages or [])})

    req_features = ["file_upload"] if files else ["text"]
    available_creds = _get_cookies_ranked(required_features=req_features)
    if not available_creds:
        _cleanup(files)
        raise RuntimeError(
            "Gemini web-api not configured or all accounts exhausted: set providers.gemini_web_api.psid "
            "(cookie __Secure-1PSID) or onboard a gemini_web profile")

    def _call_with_retry() -> str:
        last_exc = None
        for psid, psidts, profile in available_creds:
            try:
                client = _get_client(psid, psidts)
                # Vision/upload only works on AUTHENTICATED accounts — skip a
                # known-guest account fast (≈init cost) instead of paying a full
                # upload+generate that rejects with 1100.
                if files:
                    st = getattr(client, "account_status", None)
                    if st is not None and getattr(st, "name", "") != "AVAILABLE":
                        _logger().info({"event": "gma_skip_guest", "profile": profile})
                        _drop_client(psid)
                        try:
                            from services.solver_selfheal import try_relogin, GEMINI
                            sc = _solver_cfg()
                            try_relogin(sc.get("url", ""), sc.get("api_key", ""), GEMINI, profile)
                        except Exception:
                            pass
                        last_exc = last_exc or RuntimeError("guest account cannot do vision/upload")
                        continue
                # Build Google session cookies for CDN download (ảnh/nhạc)
                _cookies = {"__Secure-1PSID": psid}
                if psidts:
                    _cookies["__Secure-1PSIDTS"] = psidts
                text = _generate_text(client, prompt, files, model_enum, base_url=base_url, cookies=_cookies)

                # Detect quota limits in text response
                lower_text = str(text).lower()
                if any(k in lower_text for k in ("reached your limit", "đạt đến giới hạn", "usage cap", "hết lượt", "limit resets", "more images", "giới hạn tạo nhạc", "giới hạn của bạn được đặt lại", "giới hạn của tôi")):
                    raise RuntimeError(f"QUOTA_EXHAUSTED: {text[:100]}")

                return text
            except Exception as exc:
                err = str(exc).lower()
                
                # Quota exhaustion
                if "quota_exhausted" in err:
                    _logger().warning({"event": "gma_quota_hit", "profile": profile})
                    if profile and profile != "static-config":
                        account_service.record_profile_quota_failure(
                            profile=profile,
                            quota_type="file_upload" if files else "text_limit",
                            account_type="gemini_web_api"
                        )
                    last_exc = exc
                    continue
                    
                # Session UNAUTHENTICATED / expired 1PSID / generate rejected
                # (Gemini "1100"): the stored cookies are stale. SELF-HEAL — since
                # gma reuses the Google account, relogin-via-google refreshes the
                # profile's authenticated cookies (rides Google SSO if the session
                # is still alive; full login otherwise). Bounded by a 5-min
                # per-profile cooldown; the NEXT request picks up fresh cookies.
                _needs_relogin = any(k in err for k in (
                    "auth", "cookie", "1psid", "401", "403",
                    "1100", "unauthenticated", "failed to generate",
                ))
                if _needs_relogin:
                    _logger().warning({"event": "gma_session_selfheal", "profile": profile, "error": str(exc)[:120]})
                    _drop_client(psid)
                    # Chỉ tự khôi phục PROFILE THẬT (google-*). Bỏ qua
                    # placeholder 'gemini-web-default'/'static-config' (không có
                    # phiên Google/creds → recover chỉ tổ spam ❌).
                    if profile and profile.startswith("google-"):
                        # Thang tái dùng → đăng nhập Google → báo Telegram, chạy
                        # thread nền, debounce 30ph/profile trong hàm.
                        try:
                            import threading as _t
                            from services.account_recovery import gma_recover_and_notify
                            _t.Thread(target=gma_recover_and_notify,
                                      args=(profile, str(exc)[:60]), daemon=True).start()
                        except Exception:
                            pass
                    last_exc = exc
                    continue

                raise exc
        
        # If we loop through all credentials and fail
        if last_exc:
            raise last_exc
        raise RuntimeError("No available accounts to fulfill request")

    cid = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    if stream:
        def sse() -> Iterator[dict[str, Any]]:
            try:
                last_exc = None
                success = False
                for psid, psidts, profile in available_creds:
                    try:
                        client = _get_client(psid, psidts)
                        if files:
                            st = getattr(client, "account_status", None)
                            if st is not None and getattr(st, "name", "") != "AVAILABLE":
                                _drop_client(psid)
                                continue
                        _cookies = {"__Secure-1PSID": psid}
                        if psidts: _cookies["__Secure-1PSIDTS"] = psidts
                        
                        yield _openai_chunk(model, cid, created, {"role": "assistant", "content": ""})
                        
                        full_text = ""
                        if getattr(model_enum, "name", "") == "BASIC_PRO":
                            initial_msg = "⏳ Hệ thống đang xử lý tạo media/nhạc (quá trình này mất khoảng 60-90 giây), vui lòng đợi...\n\n"
                            full_text += initial_msg
                            yield _openai_chunk(model, cid, created, {"content": initial_msg})
                        for chunk in _generate_stream(client, prompt, files, model_enum, base_url=base_url, cookies=_cookies):
                            full_text += chunk
                            yield _openai_chunk(model, cid, created, {"content": chunk})
                            
                        lower_text = full_text.lower()
                        if any(k in lower_text for k in ("reached your limit", "đạt đến giới hạn", "usage cap", "hết lượt", "giới hạn tạo nhạc", "giới hạn của bạn được đặt lại", "giới hạn của tôi")):
                            raise RuntimeError("QUOTA_EXHAUSTED")
                            
                        success = True
                        break
                    except Exception as exc:
                        err = str(exc).lower()
                        if "quota" in err: last_exc = exc; continue
                        if any(k in err for k in ("auth", "cookie", "1psid", "401", "403", "1100")):
                            _drop_client(psid)
                            last_exc = exc
                            continue
                        raise
                        
                if not success and last_exc:
                    raise last_exc
                    
                yield _openai_chunk(model, cid, created, {}, finish="stop")
            finally:
                _cleanup(files)
        return sse()

    try:
        text = _call_with_retry()
        clean_text, tool_calls = _extract_tool_calls(text)
    finally:
        _cleanup(files)
        
    msg: dict[str, Any] = {"role": "assistant"}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    else:
        msg["content"] = clean_text
        
    return {
        "id": cid, "object": "chat.completion", "created": created, "model": model,
        "choices": [{"index": 0, "message": msg,
                     "finish_reason": "tool_calls" if tool_calls else "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

def handle_gemini_web_api_image_gen(prompt: str, n: int = 1, response_format: str = "url", base_url: str = "") -> dict[str, Any]:
    """OpenAI /v1/images/generations handler for Gemini Web API."""
    from services.account_service import account_service
    from curl_cffi import requests as cffi_requests
    import base64
    import time
    
    available_creds = _get_cookies_ranked(required_features=["text"])
    if not available_creds:
        raise RuntimeError("No gemini_web_api accounts available")
        
    # Auto-prepend drawing instruction for Gemini if using the Image Gen endpoint
    prompt_lower = prompt.lower()
    if not any(k in prompt_lower for k in ("vẽ", "draw", "tạo ảnh", "tạo hình", "generate image")):
        prompt = f"Vẽ một bức ảnh thật đẹp mô tả: {prompt}"
        
    # Flash trả decline giả "limit resets" cho ảnh (giống nhạc) — Pro vẽ được.
    from gemini_webapi.constants import Model as _Model

    last_exc = None
    for psid, psidts, profile in available_creds:
        try:
            client = _get_client(psid, psidts)
            resp = _run(client.generate_content(prompt, model=_Model.BASIC_PRO))
            all_media = []
            for attr in ("images", "media", "videos"):
                if hasattr(resp, attr):
                    all_media.extend(getattr(resp, attr) or [])
                    
            if not all_media:
                # Detect quota limits
                text = str(getattr(resp, "text", "") or "").lower()
                if any(k in text for k in ("reached your limit", "giới hạn", "usage cap", "hết lượt", "limit resets", "more images", "your limit")):
                    _logger().warning({"event": "gma_quota_hit_detail", "profile": getattr(resp, "profile", "unknown"), "response": text[:250]})
                    raise RuntimeError(f"QUOTA_EXHAUSTED: {text[:250]}")
                raise RuntimeError(f"No media generated. Text response: {text[:250]}")
                
            data = []
            for m_obj in all_media[:n]:
                from services.config import config as _cfg
                gma_dir = _cfg.images_dir / "gma"
                gma_dir.mkdir(parents=True, exist_ok=True)
                saved_rel = _save_media_via_client(m_obj, gma_dir)
                
                if saved_rel:
                    base = base_url.rstrip("/")
                    final_url = f"{base}/images/{saved_rel}" if base else f"/images/{saved_rel}"
                    
                    if response_format == "b64_json" and final_url.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                        try:
                            import base64
                            img_data = (gma_dir / saved_rel.split("/")[-1]).read_bytes()
                            data.append({"b64_json": base64.b64encode(img_data).decode("ascii")})
                        except Exception:
                            data.append({"url": final_url})
                    else:
                        data.append({"url": final_url})
                else:
                    # Fallback
                    u = getattr(m_obj, "url", "")
                    if u:
                        data.append({"url": u})
                    
            return {"created": int(time.time()), "data": data}
            
        except Exception as exc:
            err = str(exc).lower()
            if "quota_exhausted" in err:
                _logger().warning({"event": "gma_quota_hit", "profile": profile})
                if profile and profile != "static-config":
                    account_service.record_profile_quota_failure(
                        profile=profile,
                        quota_type="text_limit",
                        account_type="gemini_web_api"
                    )
                last_exc = exc
                continue
                
            if any(k in err for k in ("auth", "cookie", "1psid", "401", "403")):
                _logger().warning({"event": "gma_auth_retry", "profile": profile, "error": str(exc)[:120]})
                _drop_client(psid)
                if profile and profile != "static-config":
                    try:
                        account_service.update_account(profile, {"status": "disabled"})
                    except Exception:
                        pass
                last_exc = exc
                continue

            raise exc

    if last_exc:
        raise last_exc
    raise RuntimeError("No available accounts to fulfill image request")








