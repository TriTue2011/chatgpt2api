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
import re
import tempfile
import threading
import time
import uuid
from typing import Any, Iterator

from curl_cffi import requests
from fastapi import HTTPException


def _ghim_cache_cookie_ben() -> None:
    """Giữ tài khoản Google/Gemini SỐNG qua restart container.

    gemini_webapi bật auto_refresh: mỗi ~600s nó xoay `__Secure-1PSIDTS` (cookie
    Google hết hạn nhanh) và GHI cookie mới vào một file cache. Nhưng mặc định
    file đó nằm ở `tempfile.gettempdir()/gemini_webapi` = /tmp — thư mục NẰM
    TRONG container, bị xoá sạch mỗi lần dựng lại container (Re-pull image).

    Hậu quả đo thật 31/07: trong lúc container chạy thì cookie luôn tươi (chat
    được), nhưng vừa restart là mất cache → client init lại bằng cookie CŨ lưu
    trong config → "UNAUTHENTICATED, cookies expired" → phải đăng nhập lại tay
    trên noVNC. Đây đúng là nỗi đau "login lại nhiều lần" của chủ máy.

    Trỏ `GEMINI_COOKIE_PATH` về vùng đĩa BỀN (mount /app/data → /opt/c2a/data)
    thì cookie đã làm mới sống qua restart, và lần init sau đọc lại bản tươi
    (get_access_token glob .cached_cookies_*.json trong thư mục này). Đặt bằng
    biến môi trường vì `_get_cookie_cache_dir()` đọc os.getenv mỗi lần gọi —
    chỉ cần set TRƯỚC lần init/rotate đầu tiên, mà module này import trước mọi
    lời gọi gemini. Không đè nếu vận hành đã tự đặt sẵn.
    """
    if os.getenv("GEMINI_COOKIE_PATH"):
        return
    try:
        from services.config import DATA_DIR
        goc = os.path.join(str(DATA_DIR), "gemini_cookies")
    except Exception:
        goc = os.path.join(tempfile.gettempdir(), "gemini_webapi")
    try:
        os.makedirs(goc, exist_ok=True)
        os.environ["GEMINI_COOKIE_PATH"] = goc
        # Mang cache TƯƠI hiện có (nếu container này đã chạy và xoay cookie) sang
        # chỗ bền, để bản vá có hiệu lực NGAY mà không chờ hết một chu kỳ 600s.
        cu = os.path.join(tempfile.gettempdir(), "gemini_webapi")
        if os.path.isdir(cu) and os.path.abspath(cu) != os.path.abspath(goc):
            import shutil
            for ten in os.listdir(cu):
                if not ten.startswith(".cached_cookies_"):
                    continue
                dich = os.path.join(goc, ten)
                # Chỉ chép khi bản /tmp mới hơn (là bản vừa được xoay).
                if (not os.path.exists(dich)
                        or os.path.getmtime(os.path.join(cu, ten)) > os.path.getmtime(dich)):
                    shutil.copy2(os.path.join(cu, ten), dich)
    except Exception:
        pass


_ghim_cache_cookie_ben()


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


_TU_VE = ("vẽ", "tạo ảnh", "tao anh", "bức ảnh", "poster", "hình nền", "ảnh bìa", "ve ")
_DANH_TU_NHAC = ("nhạc", "nhac", "bài hát", "bai hat", "giai điệu", "giai dieu",
                 "ballad", "balad", "edm", "lofi", "music", "song", "melody")
_DONG_TU_TAO = ("tạo", "tao", "sáng tác", "sang tac", "làm", "lam", "viết", "viet",
                "sản xuất", "san xuat", "compose", "generate", "make", "cho tôi", "cho toi")
# Câu PHÁT nhạc / HỎI lời — KHÔNG phải tạo, dù có chữ "bài hát/nhạc".
_TU_PHAT_HOI = ("mở ", "mo ", "nghe ", "phát ", "phat ", "lời ", "loi ", "là gì",
                "la gi", "ca sĩ", "ca si", "của ai", "cua ai", "hợp âm", "hop am",
                "tìm ", "tim ")


def _la_yeu_cau_nhac(prompt: str) -> bool:
    """Câu có phải YÊU CẦU TẠO NHẠC không.

    Loại 'vẽ ảnh bìa album nhạc' (là vẽ), 'mở bài hát' (phát), 'lời bài hát là gì'
    (hỏi lời). Cần: có danh từ nhạc + động từ tạo, và không dính ngữ cảnh phát/hỏi/vẽ.
    Dùng chung ở cả định tuyến model lẫn chỗ tiêm instruction ép sinh."""
    p = (prompt or "").lower()
    if any(d in p for d in _TU_VE):
        return False
    if not any(n in p for n in _DANH_TU_NHAC):
        return False
    if any(k in p for k in _TU_PHAT_HOI):
        return False
    return any(v in p for v in _DONG_TU_TAO)


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

# Profile placeholder do ô "profile" mặc định của thẻ Cài đặt sinh ra
# (gemini-web-default, claude-web-default…) — KHÔNG phải account đã onboard.
# Cùng một biểu thức với api/accounts._is_placeholder_profile và bộ chọn
# reuse-profile của web, để ba nơi không lệch nhau.
_PLACEHOLDER_RE = re.compile(r"(^|[-_])default$", re.IGNORECASE)


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


def generate_music_via_browser(prompt: str, timeout: int = 240) -> dict[str, Any]:
    """Tạo NHẠC qua captcha-solver (điều khiển trình duyệt gemini.google.com).

    Lyria không gọi được qua HTTP API nên phải đi trình duyệt. Thử lần lượt các
    hồ sơ gemini_web đã đăng nhập; hồ sơ nào ra nhạc thì trả về ngay.

    Trả {"video_b64","url","title"} hoặc {"error": "..."}.
    """
    sc = _solver_cfg()
    url = sc.get("url")
    if not url:
        return {"error": "chưa cấu hình captcha-solver cho gemini_web"}
    profiles = _profiles()
    if not profiles:
        return {"error": "chưa có hồ sơ gemini_web nào đã đăng nhập"}
    last = ""
    for profile in profiles[:3]:   # thử tối đa 3 hồ sơ, đủ để vượt hồ sơ hỏng
        try:
            r = requests.post(
                f"{url}/v1/gemini-web/generate-music",
                json={"profile": profile, "prompt": prompt, "timeout": timeout},
                headers={"Authorization": f"Bearer {sc.get('api_key', '')}"},
                timeout=timeout + 45,
            )
            if r.status_code == 200:
                d = r.json()
                vid = d.get("video") or {}
                if vid.get("b64") or vid.get("url"):
                    _logger().info({"event": "gma_music_ok", "profile": profile,
                                    "elapsed_ms": d.get("elapsed_ms")})
                    return {"video_b64": vid.get("b64", ""), "url": vid.get("url", ""),
                            "title": vid.get("title", "Bản nhạc")}
                last = "solver trả rỗng"
            else:
                last = f"HTTP {r.status_code}: {str(r.text)[:150]}"
                _logger().warning({"event": "gma_music_fail", "profile": profile, "err": last})
        except Exception as exc:
            last = str(exc)[:150]
            _logger().warning({"event": "gma_music_err", "profile": profile, "err": last})
    return {"error": last or "tạo nhạc thất bại"}


def _store_profiles(groups: set[str]) -> list[str]:
    """Tên profile solver lấy TỪ KHO TÀI KHOẢN (account_service), cho các account
    thuộc `groups`. Tên profile được lưu ở field email/profile/name (vd account
    gemini_web_api có email='google-benbap115'). Nhờ vậy mọi account đã onboard
    tự xuất hiện — khỏi khai báo tay trong providers.*.profiles."""
    try:
        from services.account_service import account_service, account_group
        # FIX race: _accounts la dict song, doc truc tiep khong lock co the
        # RuntimeError "dictionary changed size during iteration" neu co mutate
        # dong thoi (rotation profile crash). list_accounts() da tu lock+copy.
        items = account_service.list_accounts()
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

    # Bỏ các profile PLACEHOLDER (…-default) khi đã có profile thật.
    #
    # Vì sao: kho tài khoản có một entry `gemini-web-default` với status=active —
    # sinh ra từ ô "profile" mặc định của thẻ Cài đặt, KHÔNG phải account Google đã
    # onboard. Nó đứng cùng 9 profile thật trong vòng xoay, nên mỗi lượt lấy cookie
    # hệ thống lại gọi captcha-solver cho nó; solver MỞ MỘT PHIÊN TRÌNH DUYỆT rồi
    # trả 404 "__Secure-1PSID missing". Đo trên máy chủ (log 22:59): 9 profile thật
    # 200 OK, riêng cái này 404 kèm một lần `opened context profile=…-default`.
    # Hai hậu quả thật: (1) tốn CPU/RAM mở browser vô ích mỗi vòng, và phiên đó có
    # thể GIÀNH LOCK trình duyệt đúng lúc người dùng đang đăng nhập tay — đúng cảm
    # giác "đăng nhập nhiều tầng, đăng nhập xong lại bắt đăng nhập"; (2) nếu nó
    # được chọn để trả lời thì Gemini đáp "Permission denied or unauthenticated".
    #
    # Dùng lại đúng quy tắc của api/accounts._is_placeholder_profile để UI và
    # đường chạy không lệch nhau. Chỉ lọc KHI CÒN profile thật — nếu người dùng
    # chưa onboard cái nào thì vẫn để nguyên để onboard được.
    thuc = [p for p in profiles if not _PLACEHOLDER_RE.search(p)]
    if thuc and len(thuc) != len(profiles):
        bo = [p for p in profiles if p not in thuc]
        _logger().info({"event": "gma_bo_profile_placeholder", "bo": bo,
                        "con_lai": len(thuc)})
        profiles = thuc

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

    # Round-robin rotate pool so load spreads across healthy GMA accounts
    # (GeminiClientPool-style), not always burning #1.
    if len(results) > 1:
        try:
            n = int(_rr_offset[0] or 0) % len(results)
            _rr_offset[0] = n + 1
            results = results[n:] + results[:n]
        except Exception:
            pass

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


# ── Quota phrase detection (Flash often fakes "limit resets") ───────────────

# Hard signals of real quota exhaustion (Google quota UI style).
_REAL_QUOTA_PHRASES = (
    "reached your limit",
    "you've reached your limit",
    "you have reached your limit",
    "đạt đến giới hạn",
    "usage cap",
    "hết lượt",
    "more images",
    "giới hạn tạo nhạc",
    "giới hạn của bạn được đặt lại",
    "giới hạn của tôi",
    "try again later",
    "quota exceeded",
)
# Soft phrases that Flash often returns as *policy decline* for image/music,
# NOT a real account-wide text quota — do NOT brick the whole profile for text.
_FAKE_LIMIT_ONLY = (
    "limit resets",
    "your limit will reset",
    "giới hạn sẽ được đặt lại",
)


def _looks_like_real_gma_quota(text: str, *, has_files: bool = False) -> bool:
    """True only when response is a real quota block worth demoting the account.

    Flash frequently declines image/music with "limit resets" even when chat text
    still works — treating that as text_limit bricks the profile incorrectly.
    """
    t = (text or "").lower().strip()
    if not t:
        return False
    if any(p in t for p in _REAL_QUOTA_PHRASES):
        return True
    # Soft phrase alone: only treat as quota when we asked for media/files
    if has_files and any(p in t for p in _FAKE_LIMIT_ONLY):
        # Still likely image-only — mark image fail later, not whole text_limit
        return True
    if not has_files and any(p in t for p in _FAKE_LIMIT_ONLY):
        # Text-only "limit resets" → almost always fake policy decline
        _logger().info({"event": "gma_fake_limit_ignored", "sample": t[:120]})
        return False
    return False


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
# Round-robin cursor for multi-account GMA pool (GeminiClientPool-style).
_rr_offset: list[int] = [0]
# Stagger client.init across accounts (seconds between inits during prewarm).
_STAGGER_MIN = 2.0
_STAGGER_MAX = 8.0

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


# Lock init RIÊNG từng client (học GeminiClientPool của Gemini-FastAPI):
# một account nguội/chết đang init lại KHÔNG được chặn request của account khác.
_init_locks: dict[str, threading.Lock] = {}


def _get_client(psid: str, psidts: str):
    key = psid[:32]
    with _client_lock:
        cli = _clients.get(key)
        if cli is not None:
            return cli
        khoa_init = _init_locks.setdefault(key, threading.Lock())
    # init NGOÀI _client_lock — trước đây giữ lock toàn cục suốt cả init (tới
    # 60s): một account chết re-init là mọi request khác đứng chờ, kể cả
    # request chỉ cần client ĐÃ cache.
    with khoa_init:
        with _client_lock:
            cli = _clients.get(key)     # double-check: thread khác vừa init xong
            if cli is not None:
                return cli
        from gemini_webapi import GeminiClient
        cli = GeminiClient(secure_1psid=psid, secure_1psidts=psidts or None, watchdog_timeout=180, timeout=180)
        # Timeout ngoài (200) phải LỚN HƠN timeout trong (180): trước đây ngoài
        # 60 < trong 180 nên future bị bỏ sau 60s nhưng coroutine init vẫn chạy
        # tiếp trên loop nền với auto_refresh — client "mồ côi" xoay 1PSIDTS
        # song song với lần init sau của chính profile đó (race hỏng cookie).
        _run(cli.init(timeout=180, auto_close=False, auto_refresh=True), timeout=200)
        with _client_lock:
            _clients[key] = cli
        _record_auth_status(key, cli)
        _logger().info({"event": "gma_client_init", "psid_prefix": psid[:12],
                        "auth": _auth_status.get(key, (0, None))[1]})
        return cli


def _drop_client(psid: str, profile: str | None = None) -> None:
    """Bỏ client hỏng + cookie cache CỦA RIÊNG profile đó.

    Trước đây chỗ này _cookie_cache.clear() cả pool: một profile hỏng auth là
    mọi profile khoẻ phải gọi lại captcha-solver để lấy cookie (mỗi lần solver
    mở một browser context — tốn CPU và giành lock với đăng nhập tay).
    """
    with _client_lock:
        _clients.pop(psid[:32], None)
    if profile:
        _cookie_cache.pop(profile, None)
        return
    # Không biết profile → tìm entry mang đúng psid này (vẫn hẹp hơn clear cả pool)
    for ten, (_ts, ck) in list(_cookie_cache.items()):
        if ck.get("__Secure-1PSID") == psid:
            _cookie_cache.pop(ten, None)


def prewarm_clients() -> int:
    """Pre-build & cache the GeminiClient for every configured gma account so the
    FIRST real request doesn't pay the ~10s cli.init() cold-start (measured:
    cold 10s vs warm 2.4–3.7s). Idempotent — _get_client returns the cached
    client if already warm. Called from the web_prewarmer loop.

    Inits are staggered (2–8s) like GeminiClientPool to avoid cookie stampede.
    """
    try:
        # Revive stuck limited GMA profiles before ranking
        try:
            from services.account_service import account_service as _as
            _as.revive_stuck_limited(max_age_hours=24.0)
        except Exception:
            pass
        creds = _get_cookies_ranked(required_features=["text"])
    except Exception as exc:
        _logger().warning({"event": "gma_prewarm_creds_failed", "error": str(exc)[:120]})
        return 0
    warmed = 0
    import random as _rnd
    to_init = []
    for psid, psidts, profile in creds:
        if psid[:32] not in _clients:
            to_init.append((psid, psidts, profile))
        else:
            warmed += 1
    for i, (psid, psidts, profile) in enumerate(to_init):
        try:
            _get_client(psid, psidts)
            warmed += 1
        except Exception as exc:
            _logger().warning({"event": "gma_prewarm_failed", "profile": str(profile)[:40],
                               "error": str(exc)[:120]})
        if i < len(to_init) - 1:
            time.sleep(_rnd.uniform(_STAGGER_MIN, _STAGGER_MAX))
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
    # Hai tên này ĐÃ được liệt kê trong gma_models của /v1/models từ trước nhưng
    # KHÔNG có ở bảng này, nên chọn chúng trong giao diện là rơi thẳng vào nhánh
    # gma_unknown_model_fallback: trả HTTP 200 bằng model auto, không báo gì.
    # Đích của chúng là hai giá trị đã có sẵn ở trên, không phải tên mới bịa ra.
    "3.1-flash": "gemini-3-flash",
    "3.1-flash-thu-nghiem": "gemini-3-flash-thinking",
    # Alias cũ — vẫn nhận để không vỡ request đã cấu hình
    "flash": "gemini-3-flash",
    "flash-lite": "gemini-3-flash",
    "flash-thinking": "gemini-3-flash-thinking",
    "flash-extended": "gemini-3-flash-advanced",
    "pro": "gemini-3-pro",
    "pro-extended": "gemini-3-pro-advanced",
}


def _resolve_model(model: str, prompt: str = ""):

    """alias → gemini_webapi Model enum; None = để server tự chọn.

    Người gọi CHỈ ĐÍCH DANH một model không tồn tại → ném 400. Chỉ `auto` mới
    được phép rơi về mặc định.
    """
    m = str(model or "").strip().lower()
    for pfx in ("gma/", "gemini-web/", "gemini_web_api/"):
        if m.startswith(pfx):
            m = m[len(pfx):]
            break
    # Ghi lại NGAY: `m` bị gán lại nhiều lần bên dưới (định tuyến theo prompt,
    # default trong config), nên hỏi sau là không còn phân biệt được "người dùng
    # chọn" với "hệ thống tự chọn".
    nguoi_dung_chi_dinh = bool(m) and m != "auto"
    # 1. Smart routing first! If UI selected auto, we intercept music prompts.
    if not m or m == "auto":
        p = prompt.lower()
        is_drawing = any(k in p for k in ("vẽ", "tạo ảnh", "bức ảnh", "poster", "hình nền", "ảnh bìa"))

        # Nhạc → FLASH, KHÔNG phải Pro. Đo thật 31/07: route Pro (gemini-3-pro)
        # trả "gemini-3-pro is not available … UNAUTHENTICATED"; Flash
        # (gemini-3-flash) thì xác thực được nên thoái thác THẬT THÀ thay vì báo
        # lỗi khó hiểu. (Nhạc THẬT vẫn cần đường trình duyệt — Lyria không gọi
        # được qua HTTP; xem ghi chú ở chỗ ghép prompt.) Dùng `_la_yeu_cau_nhac`
        # thay cho bộ từ khoá thô — không nhầm "mở bài hát"/"lời bài hát là gì".
        if _la_yeu_cau_nhac(prompt):
            m = "3.5-flash"
        # Vẽ ảnh vẫn route Pro (ảnh sinh được qua HTTP — năng lực gốc của model).
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

    da_khai = m                      # tên NGƯỜI DÙNG khai, trước khi đổi alias
    m = _GMA_ALIASES.get(m, m)
    # Tách HAI nguyên nhân, đừng gộp: thư viện thiếu/hỏng là lỗi của bản triển
    # khai, không phải của người gọi. Gộp chung thì một lần import hỏng sẽ làm
    # MỌI model hợp lệ trả 400 — hỏng hẳn kênh Gemini (test bắt được đúng chỗ này).
    try:
        from gemini_webapi.constants import Model
    except Exception as exc:
        _logger().warning({
            "event": "gma_thu_vien_khong_nap_duoc",
            "error": str(exc)[:150],
            "thuc_te": "auto (server Gemini tự chọn)",
        })
        return None
    try:
        return Model.from_name(m)
    except Exception:
        if nguoi_dung_chi_dinh:
            # Người gọi chọn ĐÍCH DANH một model không tồn tại. Rơi về auto ở
            # đây là trả HTTP 200 bằng MODEL KHÁC — họ tưởng đang dùng A mà
            # thực tế nhận B, và không có cách nào biết. Đo thật 08/08:
            # `gma/3.6-flash` trả "OK" trong khi chạy model auto.
            # Ném 400 TRƯỚC khi gọi upstream: không tốn lượt, và nói đúng lỗi.
            _logger().warning({
                "event": "gma_model_khong_ton_tai",
                "yeu_cau": da_khai,
                "sau_alias": m,
            })
            raise HTTPException(status_code=400, detail={
                "error": f"Model '{da_khai}' không tồn tại ở Gemini Web. "
                         "Xem danh sách hợp lệ trong GET /v1/models (tiền tố gma/), "
                         "hoặc dùng 'gma/auto' để hệ thống tự chọn.",
                "code": "model_not_found",
            })
        # Đường AUTO: hệ thống tự chọn nên rơi về mặc định là hợp lý — người gọi
        # không hề khai model nào để mà sai. Vẫn ghi warning vì nó cho biết cấu
        # hình `default_models`/`enabled_models` đang trỏ vào một tên đã chết.
        _logger().warning({
            "event": "gma_unknown_model_fallback",
            "sau_alias": m,
            "thuc_te": "auto (server Gemini tự chọn)",
            "canh_bao": "Tên model trong cấu hình không còn tồn tại — đang chạy bằng "
                        "mặc định của server. Sửa default_models/enabled_models.",
        })
        return None


def _downscale(data: bytes, mime: str) -> tuple[bytes, str]:
    try:
        max_dim = int(_config().data.get("gemini_vision_max_dim", 896) or 0)
    except Exception:
        max_dim = 896
    # max_dim = 0 → tắt thu nhỏ nhưng VẪN chuẩn hoá định dạng. UnsupportedImage
    # (HEIC/JXL/file tải hỏng) để NỔI LÊN cho combo nhận ra "lỗi tại tấm ảnh",
    # thay vì đẩy bytes rác lên gemini rồi nhận lỗi upstream mơ hồ.
    from services.image_utils import UnsupportedImage, normalize
    try:
        out, out_mime = normalize(data, max_dim=max_dim, jpeg_quality=85)
    except UnsupportedImage:
        raise
    except Exception:
        return data, mime
    if out is not data:
        _logger().info({"event": "gma_image_downscaled",
                        "bytes": [len(data), len(out)], "mime": out_mime})
    return out, out_mime


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
                # Không `continue` khi hỏng: âm thầm bỏ ảnh rồi vẫn gọi model là
                # cách sinh ra "phân tích ảnh" mà chẳng có ảnh nào — đúng kiểu
                # hỏng của sự cố camera 08/08.
                from services.image_guard import ImageRejected, giai_ma_data_url
                try:
                    data, mime = giai_ma_data_url(url, ten="ảnh gửi Gemini")
                except ImageRejected as exc:
                    raise HTTPException(status_code=400, detail={"error": exc.ly_do}) from exc
            elif url.startswith("http"):
                # URL do client cung cấp → SSRF guard trước khi tải.
                try:
                    from services import net_guard
                    data = net_guard.fetch_media(url, timeout=20, max_bytes=25 * 1024 * 1024)
                    mime = "image/png"
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
        # message.txt nằm trong thư mục riêng gma_txt_* (để giữ đúng TÊN TỆP
        # khi upload) — xoá luôn thư mục rỗng đó.
        try:
            cha = os.path.dirname(p)
            if os.path.basename(cha).startswith("gma_txt_"):
                os.rmdir(cha)
        except Exception:
            pass


# ── Prompt quá dài → đính kèm message.txt (học từ Gemini-FastAPI) ───────────

# gemini.google.com nhận ~1M ký tự/lượt; chừa 10% an toàn như Gemini-FastAPI.
_GMA_MAX_CHARS_MAC_DINH = 900_000

_LOI_NHAN_TEP_DAI = (
    "The full input is too long to send inline, so it is attached as "
    "message.txt. Read the attached message.txt and respond as if its "
    "contents were the user's message in this conversation."
)


def _gioi_han_ky_tu() -> int:
    try:
        return int(_cfg().get("max_chars") or _GMA_MAX_CHARS_MAC_DINH)
    except Exception:
        return _GMA_MAX_CHARS_MAC_DINH


def _dong_goi_prompt_dai(prompt: str, files: list[str],
                         gioi_han: int | None = None) -> tuple[str, list[str]]:
    """Prompt vượt trần ký tự → ghi NGUYÊN VĂN vào tệp message.txt đính kèm.

    Trước đây payload lớn chỉ có đường nén head+tail (mất chữ ở giữa). Đính tệp
    thì Gemini đọc trọn nội dung — không mất gì. Cần tài khoản đăng nhập để
    upload (guest bị chặn 1100) — đường chọn account sẵn có đã ưu tiên
    authenticated khi files không rỗng nên tự khớp.
    Trả (prompt_mới, files_mới); tệp mới do caller _cleanup như files thường.
    """
    lim = gioi_han if gioi_han is not None else _gioi_han_ky_tu()
    if len(prompt) <= lim:
        return prompt, files
    d = tempfile.mkdtemp(prefix="gma_txt_")
    duong = os.path.join(d, "message.txt")
    with open(duong, "w", encoding="utf-8") as f:
        f.write(prompt)
    _logger().info({"event": "gma_prompt_dinh_tep", "chars": len(prompt)})
    return _LOI_NHAN_TEP_DAI, [duong] + list(files)


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
            # Ảnh Gemini SINH RA mang watermark ngôi sao góc phải-dưới — gỡ tại
            # chỗ trước khi trả đường dẫn. Chỉ đụng GeneratedImage: ảnh
            # WebImage (Gemini nhặt từ tìm kiếm web) là ảnh của người khác.
            # Bọc riêng để lỗi ở bước gỡ chỉ bỏ qua việc gỡ, không làm mất ảnh
            # đã tải; ghi qua file tạm + os.replace để không bao giờ để lại
            # file cụt khi ghi dở chừng.
            try:
                from gemini_webapi.types import GeneratedImage
                from services.gemini_watermark import maybe_remove_watermark, removal_enabled
                if (isinstance(media_obj, GeneratedImage) and removal_enabled()
                        and fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))):
                    with open(str(saved_path), "rb") as fh:
                        cleaned = maybe_remove_watermark(fh.read(), origin="gma")
                    if cleaned is not None:
                        tmp_path = f"{saved_path}.tmp"
                        with open(tmp_path, "wb") as fh:
                            fh.write(cleaned)
                        os.replace(tmp_path, str(saved_path))
            except Exception as exc:
                _logger().warning({"event": "gma_watermark_skip", "file": fname,
                                   "error": str(exc)[:200]})
            _logger().info({"event": "gma_media_saved", "file": fname})
            return f"gma/{fname}"
            
        _logger().warning({"event": "gma_media_save_empty", "saved": str(saved)})
    except Exception as exc:
        _logger().warning({"event": "gma_media_save_error", "error": str(exc)[:200]})
    return None


# ── Handler (main /v1/chat/completions router) ──────────────────────────────

def _generate_stream(client, prompt: str, files: list[str], model_enum, base_url: str = "", cookies: dict | None = None, chat_session=None):
    kwargs: dict[str, Any] = {}
    if files:
        kwargs["files"] = files
    if model_enum is not None:
        kwargs["model"] = model_enum
    # Gắn vào một ChatSession thì gemini_webapi tự cập nhật metadata
    # [cid, rid, rcid] trong lúc stream — sau lượt này caller đọc
    # chat_session.metadata để LƯU KHO và lượt sau tiếp nối cuộc chat native
    # thay vì phát lại lịch sử (học từ Gemini-FastAPI).
    if chat_session is not None:
        kwargs["chat"] = chat_session

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

def _generate_text(client, prompt: str, files: list[str], model_enum, base_url: str = "", cookies: dict | None = None, chat_session=None) -> str:
    res = ""
    for chunk in _generate_stream(client, prompt, files, model_enum, base_url, cookies, chat_session=chat_session):
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


class _LocToolCallStream:
    """Chặn khối [ToolCalls]/[Call:…] lộ ra stream SSE khi request có tools.

    Trước đây đường stream phát thẳng text_delta nên client thấy nguyên văn
    protocol tool-call thay vì nhận delta `tool_calls` (đường non-stream thì
    extract đàng hoàng). Bộ lọc này (rút gọn từ StreamingOutputFilter của
    Gemini-FastAPI): feed() trả phần chữ AN TOÀN để phát ngay; từ marker
    [ToolCalls]/[Call: trở đi thì nuốt hết (caller extract từ full_text lúc
    kết stream); đuôi chunk trông như marker đang dở ("[Tool", "[Ca") được
    GIỮ LẠI chờ chunk sau, khỏi phát nhầm nửa marker.
    """

    _MARKER = re.compile(r"\[(?:ToolCalls\]|Call:)", re.IGNORECASE)
    _DUOI_DO_DANG = re.compile(r"\[[A-Za-z]{0,9}$")

    def __init__(self) -> None:
        self._giu = ""
        self._chan = False

    def feed(self, chunk: str) -> str:
        if self._chan:
            return ""
        buf = self._giu + chunk
        m = self._MARKER.search(buf)
        if m:
            self._chan = True
            self._giu = ""
            return buf[: m.start()]
        t = self._DUOI_DO_DANG.search(buf)
        if t:
            self._giu = buf[t.start():]
            return buf[: t.start()]
        self._giu = ""
        return buf

    def flush(self) -> str:
        """Hết stream: trả đuôi đang giữ nếu hoá ra KHÔNG phải marker."""
        if self._chan:
            return ""
        out = self._giu
        self._giu = ""
        return out


# ── Kho tiếp nối hội thoại native (metadata cid/rid/rcid) ────────────────────

def _ten_model_cho_kho(model: str) -> str:
    """Khoá model trong kho: tên người dùng khai (đã bỏ tiền tố, hạ chữ thường).

    Không dùng enum đã resolve — smart-routing theo prompt có thể đổi enum giữa
    các lượt của cùng một cuộc chat, làm hash lệch dù client giữ nguyên model.
    """
    m = str(model or "").strip().lower()
    for pfx in ("gma/", "gemini-web/", "gemini_web_api/"):
        if m.startswith(pfx):
            m = m[len(pfx):]
            break
    return m or "auto"


def _tim_tiep_noi(messages: list[dict[str, Any]], ten_kho: str):
    """Khớp prefix lịch sử với kho; hỏng kho thì coi như không khớp (chỉ tối ưu)."""
    try:
        from services.gma_conversation_store import kho_gma
        khop = kho_gma().tim(messages, ten_kho)
        if khop and khop["so_tin"] < len(messages):
            return khop
    except Exception as exc:
        _logger().warning({"event": "gma_kho_tim_loi", "error": str(exc)[:120]})
    return None


def _luu_tiep_noi(messages: list[dict[str, Any]], ten_kho: str, profile: str,
                  chat_session, tin_assistant: dict[str, Any]) -> None:
    """Lưu (lịch sử + câu trả lời) → metadata phiên native, cho lượt sau tiếp nối."""
    try:
        meta = list(getattr(chat_session, "metadata", None) or [])
        if not meta or not meta[0]:
            return
        from services.gma_conversation_store import kho_gma
        kho_gma().luu(list(messages) + [tin_assistant], ten_kho,
                      str(profile or ""), meta)
    except Exception as exc:
        _logger().warning({"event": "gma_kho_luu_loi", "error": str(exc)[:120]})


def _xoa_tiep_noi(khop) -> None:
    try:
        from services.gma_conversation_store import kho_gma
        kho_gma().xoa(khop["strict_hash"])
    except Exception:
        pass


def _co_anh(messages: list[dict[str, Any]]) -> bool:
    """Lịch sử có ảnh không — dùng xếp hạng account, KHÔNG tải ảnh về."""
    for msg in messages or []:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for p in content:
            if isinstance(p, dict) and p.get("type") == "image_url":
                return True
    return False


def _tu_chua_phien_nen(profile: str, exc: Exception) -> None:
    """Tự chữa phiên Google chết ở nền — chỉ profile thật (google-*) mới có
    creds đã lưu; placeholder/static-config gọi recover chỉ tổ spam ❌."""
    if not profile or not profile.startswith("google-"):
        return
    try:
        import threading as _t
        from services.account_recovery import gma_recover_and_notify
        _t.Thread(target=gma_recover_and_notify,
                  args=(profile, str(exc)[:60]), daemon=True).start()
    except Exception:
        pass


def _bo_qua_guest(psid: str, profile: str) -> RuntimeError:
    """Guest không upload/vision được (Google 1100) — bỏ nhanh + hẹn relogin.
    Trả sẵn RuntimeError để caller giữ làm last_exc (đường stream trước đây
    `continue` tay không: cả pool toàn guest là stream kết thúc RỖNG im lặng)."""
    _logger().info({"event": "gma_skip_guest", "profile": profile})
    _drop_client(psid, profile)
    try:
        from services.solver_selfheal import try_relogin, GEMINI
        sc = _solver_cfg()
        try_relogin(sc.get("url", ""), sc.get("api_key", ""), GEMINI, profile)
    except Exception:
        pass
    return RuntimeError("guest account cannot do vision/upload")

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
    """Provider handler cho router chính (gma/* models).

    Hai chế độ gửi (học từ Gemini-FastAPI):
      - TIẾP NỐI: lịch sử khớp kho hội thoại native → start_chat(metadata) và
        chỉ gửi phần tin nhắn MỚI. Payload nhỏ, ngữ cảnh server-side còn nguyên.
      - PHÁT LẠI: không khớp (hoặc tiếp nối hỏng) → flatten cả transcript như cũ.
    Trả lời xong luôn lưu (lịch sử + câu trả lời) → metadata để lượt sau tiếp nối.
    """
    from services.account_service import account_service

    # Lấy tools từ request body
    tools = body.get("tools") if body else None
    prompt = _flatten_messages_with_tools(messages, tools)
    # KHÔNG tiêm instruction "ép sinh nhạc" nữa. Đo thật 31/07: câu ép (mượn từ
    # repo Gemini-FastAPI vốn dùng cho ẢNH) KHÔNG gọi được Lyria qua HTTP — nó chỉ
    # khiến model BỊA một link .mp3 giả trong chữ (log không hề có gma_media_saved,
    # chunk.media rỗng). Ảnh sinh được qua HTTP vì đó là năng lực GỐC của model;
    # nhạc (Lyria) là công cụ RIÊNG chỉ giao diện web kích hoạt được. Ép chỉ tổ
    # khiến bot nói dối "đã tạo nhạc" kèm link chết — tệ hơn thoái thác thật thà.
    # Nhạc thật cần đường điều khiển trình duyệt (như video Flow) — chưa làm.
    model_enum = _resolve_model(model, prompt)

    ten_kho = _ten_model_cho_kho(model)
    khop = _tim_tiep_noi(messages, ten_kho)
    con_lai = messages[khop["so_tin"]:] if khop else messages

    _logger().info({"event": "gma_request", "model": str(model_enum or "auto"),
                    "msg_count": len(messages or []), "tiep_noi": bool(khop),
                    "gui_moi": len(con_lai)})

    req_features = ["file_upload"] if _co_anh(messages) else ["text"]
    available_creds = _get_cookies_ranked(required_features=req_features)
    if not available_creds:
        raise RuntimeError(
            "Gemini web-api not configured or all accounts exhausted: set providers.gemini_web_api.psid "
            "(cookie __Secure-1PSID) or onboard a gemini_web profile")

    # Cuộc chat native sống trong TÀI KHOẢN đã tạo nó — tiếp nối phải đi đúng
    # profile chủ. Chủ không còn cookie trong pool thì đành phát lại.
    cred_chu = None
    if khop:
        cred_chu = next((c for c in available_creds if c[2] == khop["profile"]), None)
        if cred_chu is None:
            khop = None
            con_lai = messages

    # Danh sách lượt thử: tiếp nối (nếu có) trước, rồi phát lại qua từng account.
    luot_thu: list[tuple[bool, tuple[str, str, str]]] = []
    if khop and cred_chu:
        luot_thu.append((True, cred_chu))
    luot_thu.extend((False, c) for c in available_creds)

    # (prompt, files) dựng MỘT LẦN cho mỗi chế độ và dùng lại qua các lượt thử —
    # khỏi tải lại ảnh/ghi lại message.txt mỗi lần đổi account. Dọn ở _don_goi().
    goi_san: dict[bool, tuple[str, list[str]]] = {}

    def _goi_cho(tiep_noi: bool) -> tuple[str, list[str]]:
        if tiep_noi not in goi_san:
            nguon = con_lai if tiep_noi else messages
            p = _flatten_messages_with_tools(nguon, tools) if tiep_noi else prompt
            files = _prepare_files(nguon)
            # Prompt vượt trần ký tự → đính nguyên văn vào message.txt (không nén mất chữ).
            goi_san[tiep_noi] = _dong_goi_prompt_dai(p, files)
        return goi_san[tiep_noi]

    def _don_goi() -> None:
        for _p, fs in goi_san.values():
            _cleanup(fs)
        goi_san.clear()

    # Dựng sẵn gói cho lượt thử ĐẦU TIÊN ngay tại đây: ảnh data: hỏng phải nổi
    # thành HTTP 400 TRƯỚC khi mở stream SSE (hành vi cũ), không phải giữa chừng.
    try:
        _goi_cho(luot_thu[0][0])
    except Exception:
        _don_goi()
        raise

    def _call_with_retry() -> tuple[str, Any, str]:
        """Trả (text, chat_session, profile) — chat_session để lưu metadata vào kho."""
        last_exc = None
        for tiep_noi, (psid, psidts, profile) in luot_thu:
            co_files = False
            try:
                client = _get_client(psid, psidts)
                p, files = _goi_cho(tiep_noi)
                co_files = bool(files)
                chat = (client.start_chat(metadata=list(khop["metadata"]))
                        if tiep_noi else client.start_chat())
                # Vision/upload (kể cả message.txt) chỉ chạy trên account đã
                # đăng nhập — guest bị Google chặn 1100, bỏ nhanh khỏi tốn lượt.
                if files:
                    st = getattr(client, "account_status", None)
                    if st is not None and getattr(st, "name", "") != "AVAILABLE":
                        last_exc = last_exc or _bo_qua_guest(psid, profile)
                        continue
                # Build Google session cookies for CDN download (ảnh/nhạc)
                _cookies = {"__Secure-1PSID": psid}
                if psidts:
                    _cookies["__Secure-1PSIDTS"] = psidts
                text = _generate_text(client, p, files, model_enum,
                                      base_url=base_url, cookies=_cookies,
                                      chat_session=chat)

                # Detect REAL quota limits (not Flash fake "limit resets" declines)
                if _looks_like_real_gma_quota(str(text), has_files=bool(files)):
                    raise RuntimeError(f"QUOTA_EXHAUSTED: {text[:100]}")

                try:
                    from services.request_context import note_provider_account
                    note_provider_account(
                        "gma",
                        account=str(profile or "")[:120],
                        model=str(model_enum or model or "gma/auto")[:80],
                    )
                except Exception:
                    pass
                return text, chat, profile
            except HTTPException:
                raise          # lỗi của REQUEST (vd ảnh hỏng) — không phải account
            except Exception as exc:
                if tiep_noi:
                    # Metadata có thể đã chết (Google quên/đóng cuộc chat) — xoá
                    # bản ghi rồi rơi về PHÁT LẠI; account này vẫn được thử tiếp
                    # ở các lượt phát lại phía sau nên không mất gì.
                    _logger().info({"event": "gma_tiep_noi_hong",
                                    "profile": profile, "error": str(exc)[:120]})
                    _xoa_tiep_noi(khop)
                    last_exc = exc
                    continue
                err = str(exc).lower()

                # Quota exhaustion
                if "quota_exhausted" in err:
                    _logger().warning({"event": "gma_quota_hit", "profile": profile})
                    if profile and profile != "static-config":
                        account_service.record_profile_quota_failure(
                            profile=profile,
                            quota_type="file_upload" if co_files else "text_limit",
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
                    _drop_client(psid, profile)
                    _tu_chua_phien_nen(profile, exc)
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
            last_exc = None
            role_da_gui = False
            try:
                for tiep_noi, (psid, psidts, profile) in luot_thu:
                    co_files = False
                    try:
                        client = _get_client(psid, psidts)
                        p, files = _goi_cho(tiep_noi)
                        co_files = bool(files)
                        if files:
                            st = getattr(client, "account_status", None)
                            if st is not None and getattr(st, "name", "") != "AVAILABLE":
                                # Trước đây chỗ này `continue` tay không: pool toàn
                                # guest là stream kết thúc RỖNG với finish=stop,
                                # không ai biết lỗi. Giữ last_exc để cuối vòng báo.
                                last_exc = last_exc or _bo_qua_guest(psid, profile)
                                continue
                        chat = (client.start_chat(metadata=list(khop["metadata"]))
                                if tiep_noi else client.start_chat())
                        _cookies = {"__Secure-1PSID": psid}
                        if psidts: _cookies["__Secure-1PSIDTS"] = psidts

                        if not role_da_gui:
                            yield _openai_chunk(model, cid, created, {"role": "assistant", "content": ""})
                            role_da_gui = True

                        # Có tools → lọc khối [ToolCalls] khỏi content (trước đây
                        # stream phát nguyên văn protocol cho client thấy).
                        loc = _LocToolCallStream() if tools else None
                        full_text = ""
                        da_phat = ""
                        if getattr(model_enum, "name", "") == "BASIC_PRO":
                            initial_msg = "⏳ Hệ thống đang xử lý tạo media/nhạc (quá trình này mất khoảng 60-90 giây), vui lòng đợi...\n\n"
                            full_text += initial_msg
                            da_phat += initial_msg
                            yield _openai_chunk(model, cid, created, {"content": initial_msg})
                        for chunk in _generate_stream(client, p, files, model_enum,
                                                      base_url=base_url, cookies=_cookies,
                                                      chat_session=chat):
                            full_text += chunk
                            phat = loc.feed(chunk) if loc else chunk
                            if phat:
                                da_phat += phat
                                yield _openai_chunk(model, cid, created, {"content": phat})
                        if loc:
                            duoi = loc.flush()
                            if duoi:
                                da_phat += duoi
                                yield _openai_chunk(model, cid, created, {"content": duoi})

                        if _looks_like_real_gma_quota(full_text, has_files=co_files):
                            raise RuntimeError("QUOTA_EXHAUSTED")

                        tool_calls: list[dict[str, Any]] = []
                        if tools:
                            _, tool_calls = _extract_tool_calls(full_text)
                            if tool_calls:
                                yield _openai_chunk(model, cid, created, {"tool_calls": [
                                    {"index": i, **tc} for i, tc in enumerate(tool_calls)
                                ]})

                        tin_luu: dict[str, Any] = {"role": "assistant", "content": da_phat}
                        if tool_calls:
                            tin_luu["tool_calls"] = tool_calls
                        _luu_tiep_noi(messages, ten_kho, profile, chat, tin_luu)
                        try:
                            from services.request_context import note_provider_account
                            note_provider_account(
                                "gma",
                                account=str(profile or "")[:120],
                                model=str(model_enum or model or "gma/auto")[:80],
                            )
                        except Exception:
                            pass

                        yield _openai_chunk(model, cid, created, {},
                                            finish="tool_calls" if tool_calls else "stop")
                        return
                    except HTTPException:
                        raise
                    except Exception as exc:
                        if tiep_noi:
                            _logger().info({"event": "gma_tiep_noi_hong",
                                            "profile": profile, "error": str(exc)[:120]})
                            _xoa_tiep_noi(khop)
                            last_exc = exc
                            continue
                        err = str(exc).lower()
                        if "quota_exhausted" in err or "quota" in err:
                            if "quota_exhausted" in err and profile and profile != "static-config":
                                try:
                                    account_service.record_profile_quota_failure(
                                        profile=profile,
                                        quota_type="file_upload" if co_files else "text_limit",
                                        account_type="gemini_web_api",
                                    )
                                except Exception:
                                    pass
                            last_exc = exc
                            continue
                        if any(k in err for k in ("auth", "cookie", "1psid", "401", "403",
                                                  "1100", "unauthenticated", "failed to generate")):
                            _drop_client(psid, profile)
                            _tu_chua_phien_nen(profile, exc)
                            last_exc = exc
                            continue
                        raise

                raise (last_exc or RuntimeError("No available accounts to fulfill request"))
            finally:
                _don_goi()
        return sse()

    try:
        text, chat, profile = _call_with_retry()
    finally:
        _don_goi()
    clean_text, tool_calls = _extract_tool_calls(text)

    # content giữ cả khi có tool_calls (trước đây bị VỨT: model vừa nói vừa gọi
    # tool là mất phần nói; OpenAI cho phép content đi kèm tool_calls).
    msg: dict[str, Any] = {"role": "assistant", "content": clean_text or None}
    if tool_calls:
        msg["tool_calls"] = tool_calls

    tin_luu: dict[str, Any] = {"role": "assistant", "content": clean_text}
    if tool_calls:
        tin_luu["tool_calls"] = tool_calls
    _luu_tiep_noi(messages, ten_kho, profile, chat, tin_luu)

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
                text = str(getattr(resp, "text", "") or "")
                if _looks_like_real_gma_quota(text, has_files=True):
                    _logger().warning({"event": "gma_quota_hit_detail", "profile": profile, "response": text[:250]})
                    # Image-only: mark image fail, don't brick whole text profile
                    try:
                        account_service.record_profile_quota_failure(
                            profile=profile,
                            quota_type="file_upload",
                            account_type="gemini_web_api",
                        )
                    except Exception:
                        pass
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
                _drop_client(psid, profile)
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








