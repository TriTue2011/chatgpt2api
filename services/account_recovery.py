"""Account auto-recovery + Telegram notification.

When an account fails during use (token expired / 401 on the web flow), try to
recover it automatically by REUSING its refresh_token to mint a fresh OAuth
token, and notify the admin Telegram chat of: the error, the action taken, and
the result. Accounts without a refresh_token can't be auto-refreshed — we
notify that a manual re-login (noVNC / onboard) is required.

Debounced per account so a burst of failures doesn't spam Telegram.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from utils.log import logger

_last_attempt: dict[str, float] = {}
_lock = threading.Lock()
_COOLDOWN_S = 600.0  # one recovery attempt / notification per account per 10 min


def _notify(text: str, detail: dict[str, Any] | None = None) -> None:
    """Push recovery status to admin bots + account log file.

    Bot fan-out dùng category="account_log" → mỗi kênh (Telegram / Zalo bot /
    Zalo cá nhân) bật/tắt riêng bằng account_log_notify_* (fallback key cũ).
    Also append LOG_TYPE_ACCOUNT so UI Logs shows them; detail mang
    provider/email/profile/step để log đầy đủ tài khoản nào, provider nào,
    đến bước khôi phục nào.
    """
    try:
        from services.notifier import notify_admin
        notify_admin(text, category="account_log")
    except Exception as exc:
        logger.warning({"event": "recovery_notify_failed", "error": str(exc)[:120]})
    try:
        from services.log_service import LOG_TYPE_ACCOUNT, log_service
        # Skip bot fan-out from log_service to avoid double Telegram messages:
        # notify_admin above already delivered to the enabled channels.
        summary = (text or "").replace("\n", " · ")[:240]
        det: dict[str, Any] = {"source": "account_recovery", "notify_bots": False}
        if detail:
            det.update({k: v for k, v in detail.items() if v not in (None, "")})
        log_service.add(LOG_TYPE_ACCOUNT, summary, det)
    except Exception:
        pass


def _acct_label(account: dict[str, Any]) -> str:
    return str(account.get("email") or (account.get("access_token") or "")[:12] or "?")


_GRELOGIN_COOLDOWN_S = 1800.0  # browser login đắt → 1 lần / account / 30 phút
_RECOVER_BUDGET_S = 300.0      # trần thời gian 1 lượt khôi phục (bail nếu quá)
_CAPTCHA_PROFILES = "/app/data/captcha/profiles"


def _solver_cfg() -> tuple[str, str]:
    """(url, api_key) của captcha-solver — lấy từ config như flow/gemini_web."""
    from services.config import config
    prov = config.data.get("providers") or {}
    for n in ("flow", "gemini_web_api", "gemini_web"):
        c = prov.get(n) or {}
        raw = str(c.get("captcha_solver_url") or "").strip()
        if raw:
            from services.captcha import captcha_base
            return captcha_base(raw), str(c.get("captcha_solver_api_key") or "")
    return "http://127.0.0.1:8010", ""


def _profile_for(email: str) -> str:
    localpart = email.split("@")[0] if "@" in email else email
    return f"google-{localpart}"


def _is_google_email(email: str) -> bool:
    """Gmail/Googlemail only — Outlook/Microsoft go bulk (T3), not Google ride."""
    e = (email or "").strip().lower()
    return e.endswith("@gmail.com") or e.endswith("@googlemail.com")


def _has_profile(profile: str) -> bool:
    import os
    return os.path.isdir(os.path.join(_CAPTCHA_PROFILES, profile))


def _has_google_creds(profile: str, email: str = "") -> bool:
    """True if captcha accounts_db has password for this profile/email."""
    try:
        import os
        import sqlite3

        db = "/app/data/captcha/accounts.db"
        if not os.path.isfile(db):
            return False
        con = sqlite3.connect(db)
        try:
            # By email first
            if email:
                row = con.execute(
                    "SELECT password FROM accounts WHERE lower(email)=lower(?) LIMIT 1",
                    (email,),
                ).fetchone()
                if row and row[0]:
                    return True
            # By profile localpart (same rules as resolve_account)
            local = profile
            for pfx in ("google-", "chatgpt-", "codex-", "claude-", "gemini-"):
                if local.startswith(pfx):
                    local = local[len(pfx):]
                    break
            local = local.replace("-", "").replace(".", "").lower()
            rows = con.execute("SELECT email, password FROM accounts").fetchall()
            for em, pw in rows:
                if not pw:
                    continue
                lp = str(em or "").split("@")[0].lower().replace(".", "").replace("-", "")
                if lp == local:
                    return True
        finally:
            con.close()
        return False
    except Exception:
        return False


def _freshen_google(profile: str) -> bool:
    """Tầng 2 — 'Đăng nhập tài khoản Google': làm tươi session Google bằng
    credentials đã lưu trong solver (accounts_db, có totp → tự chạy). Trả True
    nếu login thành công. Password KHÔNG rời khỏi solver."""
    import requests
    url, api_key = _solver_cfg()
    base = url.rstrip("/")
    H = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        r = requests.post(f"{base}/v1/session/auto-login-saved", headers=H,
                          json={"profile": profile}, timeout=30)
        st = (r.json() or {}).get("state", "")
        if st in ("failed", "blocked", "error"):
            return False
        # Poll tối đa ~310s — KHỚP ngân sách BotGuard-retry (auto_login lặp bấm
        # 'Thử lại' + nhập lại mail tới 5 phút). Chờ ngắn hơn sẽ bỏ cuộc oan khi
        # retry vẫn đang chạy. 'running' = đang retry → cứ chờ tiếp.
        for _ in range(62):
            time.sleep(5)
            try:
                s = requests.get(f"{base}/v1/session/{profile}/auto-login-status",
                                 headers=H, timeout=15).json()
            except Exception:
                continue
            state = str(s.get("state") or "")
            if state in ("success", "done", "logged_in"):
                return True
            if state in ("failed", "blocked", "error", "need_code", "need_tap"):
                # need_code/need_tap = cần người (không có totp) → coi như fail auto
                return False
        return False
    except Exception:
        return False


# ── Steps riêng theo provider ────────────────────────────────────────────────

def _codex_pick_working(email: str) -> str:
    """Quét pool tìm token codex CÒN SỐNG của email; dọn token chết cùng email."""
    from services.account_service import account_service, account_group
    from services.openai_backend_api import OpenAIBackendAPI
    good = ""
    with account_service._lock:
        for k, a in list(account_service._accounts.items()):
            if not isinstance(a, dict) or account_group(a) != "codex":
                continue
            if str(a.get("email") or "").lower() != email.lower() or not str(k).startswith("eyJ"):
                continue
            try:
                OpenAIBackendAPI(access_token=k).list_models()
                good = k
                a["status"] = "active"
            except Exception:
                a["status"] = "disabled"
        account_service._save_accounts()
    return good


def _codex_exchange_from_redirect(redirect_url: str, state: str) -> None:
    from urllib.parse import urlparse, parse_qs
    from services.oauth_service import exchange_codex_code
    q = parse_qs(urlparse(redirect_url or "").query)
    code = (q.get("code") or [""])[0]
    st = (q.get("state") or [state])[0]
    exchange_codex_code(code, st)


def _codex_reuse(profile: str, email: str) -> str:
    """Tầng 1/2-retry — ride session Google, authorize Codex → token. '' nếu fail."""
    import requests
    from services.oauth_service import get_codex_auth_url
    url, api_key = _solver_cfg()
    auth = get_codex_auth_url("http://localhost:1455")
    try:
        r = requests.post(f"{url.rstrip('/')}/v1/codex-google-onboard",
                          headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                          json={"profile": profile, "auth_url": auth["auth_url"],
                                "email": email, "headless": True}, timeout=180)
        data = r.json()
    except Exception:
        return ""
    if data.get("state") != "success":
        return ""
    _codex_exchange_from_redirect(data.get("redirect_url") or "", auth["state"])
    return _codex_pick_working(email)


def _codex_batch(email: str) -> str:
    """Tầng 3 — 'Danh sách Tài khoản Codex' (config.codex_auto_list).

    Cùng endpoint/code Playwright với nút "Đăng nhập hàng loạt":
      POST captcha-solver /v1/codex-onboard → run_codex_onboard
      (Microsoft OTC + IMAP + Tiếp tục + bắt OAuth callback).

    IMAP: ưu tiên cột 3–4 trên dòng; nếu trống → IMAP Gmail dùng chung
    (config.codex_imap_gmail_email / codex_imap_gmail_app_password).
    """
    import requests
    from services.config import config
    from services.oauth_service import get_codex_auth_url
    cfg = config.data if isinstance(config.data, dict) else {}
    raw = str(cfg.get("codex_auto_list") or "")
    line = None
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split("|") if "|" in ln else ln.split(":")
        if parts and parts[0].strip().lower() == email.lower():
            line = parts
            break
    if not line or len(line) < 2:
        return ""
    g_email, g_pass = line[0].strip(), line[1].strip()
    # Per-line IMAP optional; shared IMAP from settings (same as UI batch)
    shared_imap = str(cfg.get("codex_imap_gmail_email") or "").strip()
    shared_pass = str(cfg.get("codex_imap_gmail_app_password") or "").strip()
    imap_email = (line[2].strip() if len(line) > 2 and line[2].strip() else shared_imap)
    imap_pass = (line[3].strip() if len(line) > 3 and line[3].strip() else shared_pass)
    if not imap_email or not imap_pass:
        logger.warning({
            "event": "codex_batch_missing_imap",
            "email": email,
            "hint": "Điền IMAP Gmail dùng chung trong Settings Codex hoặc thêm |imap|pass trên dòng",
        })
        return ""
    url, api_key = _solver_cfg()
    auth = get_codex_auth_url("http://localhost:1455")
    try:
        # 420s: OTC + IMAP poll + consent can exceed 4 min
        r = requests.post(
            f"{url.rstrip('/')}/v1/codex-onboard",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "auth_url": auth["auth_url"],
                "github_email": g_email,
                "github_password": g_pass,
                "gmail_email": imap_email,
                "gmail_app_password": imap_pass,
            },
            timeout=420,
        )
        data = r.json()
    except Exception as exc:
        logger.warning({"event": "codex_batch_request_failed", "email": email, "error": str(exc)[:160]})
        return ""
    if data.get("state") != "success" or not data.get("redirect_url"):
        logger.warning({
            "event": "codex_batch_onboard_failed",
            "email": email,
            "error": str(data.get("error") or data.get("state") or "")[:200],
        })
        return ""
    _codex_exchange_from_redirect(data.get("redirect_url"), auth["state"])
    return _codex_pick_working(email)


def _cgf_onboard_once(profile: str, *, reuse_session: bool, timeout_polls: int = 36) -> str:
    """One ChatGPT onboard attempt. Returns JWT or ''."""
    import requests
    url, api_key = _solver_cfg()
    base = url.rstrip("/")
    H = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        r = requests.post(
            f"{base}/v1/chatgpt/onboard",
            headers=H,
            json={
                "profile": profile,
                "email": "",
                "password": "",
                "reuse_session": reuse_session,
            },
            timeout=180,
        )
        init = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except Exception as exc:
        logger.warning({
            "event": "cgf_onboard_request_failed",
            "profile": profile,
            "reuse": reuse_session,
            "error": str(exc)[:160],
        })
        return ""
    token = str(init.get("access_token") or "")
    state = str(init.get("state") or "")
    if state == "success" and token.startswith("eyJ"):
        return token
    if state != "success" or not token.startswith("eyJ"):
        for i in range(timeout_polls):  # default ~180s
            time.sleep(5)
            try:
                s = requests.get(
                    f"{base}/v1/chatgpt/{profile}/onboard-status",
                    headers=H,
                    timeout=15,
                ).json()
            except Exception:
                continue
            st = str(s.get("state") or "")
            tok = str(s.get("access_token") or "")
            if st == "success" and tok.startswith("eyJ"):
                return tok
            if st in ("failed", "error"):
                logger.warning({
                    "event": "cgf_onboard_failed",
                    "profile": profile,
                    "reuse": reuse_session,
                    "error": str(s.get("error") or s.get("message") or "")[:200],
                    "poll": i,
                })
                return ""
    if token.startswith("eyJ"):
        return token
    return ""


def _cgf_reuse(profile: str, email: str) -> str:
    """ChatGPT-free (web JWT): ride Google/ChatGPT session → scrape JWT →
    upsert free pool (chỉ email đã có). '' nếu fail.

    Thử 2 lần:
      1) reuse_session=True  (nhanh nếu cookie Google/ChatGPT còn)
      2) reuse_session=False (SSO đầy đủ hơn khi cookie ChatGPT chết
         nhưng profile Google vẫn còn — tránh kẹt cookie NextAuth rác)
    """
    for reuse in (True, False):
        token = _cgf_onboard_once(profile, reuse_session=reuse)
        if not token or not token.startswith("eyJ"):
            continue
        try:
            from services.account_service import account_service
            # Chỉ refresh/cập nhật tài khoản free ĐÃ có trong pool (cùng email).
            # Không tự thêm email mới từ profile captcha / saved accounts.
            existing = account_service.find_free_by_email(email)
            if not existing:
                logger.info({
                    "event": "cgf_reuse_skip_not_in_pool",
                    "email": email,
                    "hint": "Chỉ refresh account free user đã thêm tay — không auto-add",
                })
                return ""
            account_service.upsert_free_token(token, {
                "status": "active",
                "email": email,
            })
            logger.info({
                "event": "cgf_reuse_ok",
                "email": email,
                "profile": profile,
                "reuse_session": reuse,
            })
            return token
        except Exception as exc:
            logger.warning({
                "event": "cgf_reuse_upsert_failed",
                "email": email,
                "error": str(exc)[:160],
            })
            return ""
    return ""


# ── gma (Gemini web) — theo PROFILE (không có token pool, cookie fetch live) ──

def _gma_authenticated(profile: str) -> bool:
    """Session gma của profile có AUTHENTICATED không (account_status AVAILABLE).
    Đây là tín hiệu THẬT của gma (không dựa state string của onboard)."""
    try:
        import api.gemini_web as gw
        ck = gw._fetch_cookies_from_solver(profile)
        psid = ck.get("__Secure-1PSID", "")
        if not psid:
            return False
        cli = gw._get_client(psid, ck.get("__Secure-1PSIDTS", ""))
        st = getattr(cli, "account_status", None)
        return st is not None and getattr(st, "name", "") == "AVAILABLE"
    except Exception:
        return False


def _gma_has_session(profile: str) -> bool:
    """Profile có cookie session Google (__Secure-1PSID) không. Sau relogin,
    gma kích hoạt AVAILABLE ở lượt dùng kế — nên cookie-có-mặt là đủ để coi
    session đã khôi phục."""
    try:
        import api.gemini_web as gw
        return bool(gw._fetch_cookies_from_solver(profile).get("__Secure-1PSID"))
    except Exception:
        return False


def _gma_reuse(profile: str) -> bool:
    """Khôi phục session Gemini web cho profile. Nếu đang AUTHENTICATED thật
    (account_status AVAILABLE) → xong ngay. Nếu không → relogin-via-google
    (solver tự tra creds, ride SSO hoặc full login) → chờ session cookie xuất
    hiện lại (activation AVAILABLE diễn ra ở lượt dùng kế)."""
    if _gma_authenticated(profile):
        return True
    import requests
    url, api_key = _solver_cfg()
    H = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        requests.post(f"{url.rstrip('/')}/v1/gemini-web/{profile}/relogin-via-google",
                      headers=H, timeout=150)
    except Exception:
        pass
    for _ in range(18):  # chờ ~90s: session cookie khôi phục hoặc auth AVAILABLE
        time.sleep(5)
        if _gma_authenticated(profile) or _gma_has_session(profile):
            return True
    return False


def gma_recover_and_notify(profile: str, reason: str = "mất session") -> None:
    """Khôi phục 1 profile Gemini web (thread nền) + Telegram. Thang:
    T1 tái dùng (gemini-web onboard, ride Google) → T2 'Đăng nhập tài khoản
    Google' làm tươi rồi tái dùng lại → hết thì báo tay. Debounce 30ph/profile."""
    key = f"recover:gma:{profile}"
    with _lock:
        if time.time() - _last_attempt.get(key, 0.0) < _GRELOGIN_COOLDOWN_S:
            return
        _last_attempt[key] = time.time()

    started = time.time()
    det = {"provider": "gemini_web_api", "profile": profile}
    _notify(f"⚠️ Gemini web — {profile}\nLỗi: {reason}\n→ Đang tự khôi phục…",
            {**det, "step": "start", "reason": reason})
    if _gma_reuse(profile):
        _notify(f"✅ Gemini web — {profile}\nKhôi phục xong ([T1] tái dùng session Google).",
                {**det, "step": "T1-reuse-ok"})
        logger.info({"event": "recover_ok", "provider": "gemini_web_api", "tier": "reuse", "profile": profile})
        return
    if time.time() - started < _RECOVER_BUDGET_S:
        _notify(f"🔧 Gemini web — {profile}\n[T1] tái dùng lỗi → [T2] đang đăng nhập lại tài khoản Google…",
                {**det, "step": "T2-freshen"})
        if _freshen_google(profile) and _gma_reuse(profile):
            _notify(f"✅ Gemini web — {profile}\nKhôi phục xong ([T2] đăng nhập Google + tái dùng).",
                    {**det, "step": "T2-freshen-ok"})
            logger.info({"event": "recover_ok", "provider": "gemini_web_api", "tier": "freshen", "profile": profile})
            return
    _notify(f"❌ Gemini web — {profile}\nKHÔNG tự khôi phục được. Cần xử lý tay (noVNC cổng 6080).",
            {**det, "step": "failed"})
    logger.warning({"event": "recover_failed", "provider": "gemini_web_api", "profile": profile})


# ── flow (Google Labs Flow / Veo) — theo PROFILE, session labs.google ─────────

def _flow_session_ok(profile: str) -> bool:
    """Session Flow của profile còn sống không: get-or-create-project trả
    project_id nghĩa là labs.google đã hydrate + đăng nhập OK."""
    import requests
    url, api_key = _solver_cfg()
    H = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        r = requests.post(f"{url.rstrip('/')}/v1/google/flow/get-or-create-project",
                          headers=H, json={"profile": profile, "headless": True,
                                           "timeout": 150}, timeout=170)
        return bool((r.json() or {}).get("project_id"))
    except Exception:
        return False


def flow_recover_and_notify(profile: str, reason: str = "mất phiên") -> None:
    """Khôi phục 1 profile Flow (thread nền) + Telegram. T1 kiểm/tái lập phiên
    labs.google → T2 'Đăng nhập tài khoản Google' rồi thử lại. Debounce 30ph."""
    key = f"recover:flow:{profile}"
    with _lock:
        if time.time() - _last_attempt.get(key, 0.0) < _GRELOGIN_COOLDOWN_S:
            return
        _last_attempt[key] = time.time()

    started = time.time()
    det = {"provider": "flow", "profile": profile}
    _notify(f"⚠️ Flow — {profile}\nLỗi: {reason}\n→ Đang tự khôi phục…",
            {**det, "step": "start", "reason": reason})
    if _flow_session_ok(profile):
        _notify(f"✅ Flow — {profile}\nKhôi phục xong ([T1] phiên labs.google còn sống).",
                {**det, "step": "T1-reuse-ok"})
        logger.info({"event": "recover_ok", "provider": "flow", "tier": "reuse", "profile": profile})
        return
    if time.time() - started < _RECOVER_BUDGET_S:
        _notify(f"🔧 Flow — {profile}\n[T1] mất phiên → [T2] đang đăng nhập lại tài khoản Google…",
                {**det, "step": "T2-freshen"})
        if _freshen_google(profile) and _flow_session_ok(profile):
            _notify(f"✅ Flow — {profile}\nKhôi phục xong ([T2] đăng nhập Google + tái lập phiên).",
                    {**det, "step": "T2-freshen-ok"})
            logger.info({"event": "recover_ok", "provider": "flow", "tier": "freshen", "profile": profile})
            return
    _notify(f"❌ Flow — {profile}\nKHÔNG tự khôi phục được. Cần đăng nhập lại tay (noVNC cổng 6080).",
            {**det, "step": "failed"})
    logger.warning({"event": "recover_failed", "provider": "flow", "profile": profile})


# ── Registry provider (bật dần) ──────────────────────────────────────────────

_PROVIDERS: dict[str, dict[str, Any]] = {
    "codex": {"enabled": True, "label": "Codex",
              "reuse": _codex_reuse, "batch": _codex_batch},
    # Label dùng trong tin nhắn bot admin (log ChatGPT free / Codex)
    "free": {"enabled": True, "label": "ChatGPT free",
             "reuse": _cgf_reuse, "batch": None},
    # Bật dần tiếp:
    "gemini_web_api": {"enabled": False, "label": "Gemini web"},
    "claude": {"enabled": False, "label": "Claude"},
    "flow": {"enabled": False, "label": "Flow"},
}


def recover_provider_account(account: dict[str, Any], provider: str, reason: str) -> None:
    """Thang khôi phục SAU KHI refresh_token (T0) đã fail (chạy thread nền).

    Phân nhánh theo loại email:

    **Google (gmail/googlemail)** — multi-tier browser:
      T1  Tái dùng session Google profile (`codex-google-onboard`) nếu đã có profile
      T2  'Đăng nhập tài khoản Google' (`auto-login-saved` pass+TOTP) rồi lại T1
      T3  Đăng nhập hàng loạt (`codex-onboard` = cùng code UI bulk) nếu có dòng
          trong `codex_auto_list` + IMAP

    **Không phải Google** (Outlook/Microsoft/…):
      BỎ T1/T2 (không ride Google) → **chỉ T3** giống nút "Đăng nhập hàng loạt"
      (`/v1/codex-onboard`: email+pass, MS OTC, IMAP shared, consent, callback).

    Mỗi bước báo Telegram; debounce 30ph/account."""
    prov = _PROVIDERS.get(provider) or {}
    if not prov.get("enabled"):
        return  # provider chưa bật auto-recovery → giữ hành vi cũ
    if not isinstance(account, dict):
        return
    label = prov.get("label", provider)
    email = _acct_label(account)
    profile = _profile_for(email)
    key = f"recover:{provider}:{email}"

    with _lock:
        if time.time() - _last_attempt.get(key, 0.0) < _GRELOGIN_COOLDOWN_S:
            return
        _last_attempt[key] = time.time()

    reuse = prov.get("reuse")
    batch = prov.get("batch")
    is_google = _is_google_email(email)
    has_profile = _has_profile(profile)
    has_creds = _has_google_creds(profile, email) if is_google else False
    # Ngân sách thời gian tổng — ca vô vọng (account bị ban) sẽ bail sớm thay vì
    # treo nhiều phút qua từng tầng browser. Ca hợp lệ (session còn sống) T1 xong
    # trong ~40s nên không đụng trần.
    started = time.time()
    budget = _RECOVER_BUDGET_S
    tried: list[str] = []

    kind = "Google" if is_google else "non-Google (bulk/onboard)"
    det = {"provider": provider, "email": email}
    _notify(f"⚠️ {label} — {email}\nLỗi: {reason}\n→ Đang tự khôi phục ({kind})…",
            {**det, "step": "start", "reason": reason})
    logger.info({
        "event": "recover_start",
        "provider": provider,
        "email": email,
        "is_google": is_google,
        "has_profile": has_profile,
        "has_google_creds": has_creds,
        "reason": reason[:120],
    })

    # ── Google only: T1 ride → T2 freshen+ride ─────────────────────────────
    if is_google and reuse:
        # T1: profile cookies còn → ride OAuth Codex
        if has_profile and time.time() - started < budget:
            tried.append("T1-reuse")
            tok = reuse(profile, email)
            if tok:
                _notify(f"✅ {label} — {email}\nKhôi phục xong ([T1] tái dùng session Google).",
                        {**det, "step": "T1-reuse-ok"})
                logger.info({"event": "recover_ok", "provider": provider, "tier": "reuse", "email": email})
                return

        # T2: login Google only (pass+TOTP đã lưu) rồi ride lại — kể cả chưa có
        # profile folder (auto-login sẽ tạo user-data-dir).
        if has_creds and time.time() - started < budget:
            tried.append("T2-freshen")
            _notify(f"🔧 {label} — {email}\n[T2] Đang đăng nhập lại tài khoản Google…",
                    {**det, "step": "T2-freshen"})
            if _freshen_google(profile):
                tried.append("T1-after-freshen")
                tok = reuse(profile, email)
                if tok:
                    _notify(f"✅ {label} — {email}\nKhôi phục xong ([T2] đăng nhập Google + tái dùng).",
                            {**det, "step": "T2-freshen-ok"})
                    logger.info({"event": "recover_ok", "provider": provider, "tier": "freshen", "email": email})
                    return
            else:
                logger.warning({
                    "event": "recover_freshen_failed",
                    "provider": provider,
                    "email": email,
                })

    # ── T3: bulk login (Google fallback + BẮT BUỘC cho non-Google) ──────────
    # Cùng endpoint/code với UI "Đăng nhập hàng loạt" → /v1/codex-onboard.
    if batch and time.time() - started < budget:
        tried.append("T3-batch")
        if is_google:
            _notify(
                f"🔧 {label} — {email}\n"
                f"Google tiers lỗi → [T3] thử đăng nhập hàng loạt (codex_auto_list + IMAP)…",
                {**det, "step": "T3-batch"},
            )
        else:
            _notify(
                f"🔧 {label} — {email}\n"
                f"Acc không phải Gmail → [T3] đăng nhập giống hàng loạt "
                f"(email|pass + IMAP OTC)…",
                {**det, "step": "T3-batch"},
            )
        tok = batch(email)
        if tok:
            _notify(f"✅ {label} — {email}\nKhôi phục xong ([T3] đăng nhập hàng loạt / codex-onboard).",
                    {**det, "step": "T3-batch-ok"})
            logger.info({"event": "recover_ok", "provider": provider, "tier": "batch", "email": email})
            return

    tried_s = " → ".join(tried) if tried else "none"
    hint = (
        "Thêm dòng email|pass vào Settings Codex (codex_auto_list) + IMAP Gmail dùng chung"
        if not is_google
        else "Kiểm tra profile Google / pass+TOTP / codex_auto_list + IMAP"
    )
    _notify(
        f"❌ {label} — {email}\n"
        f"KHÔNG tự khôi phục được (đã thử: {tried_s}).\n"
        f"→ {hint}\n"
        f"→ Hoặc xử lý tay noVNC cổng 6080.",
        {**det, "step": "failed", "reason": f"tried: {tried_s}"},
    )
    logger.warning({
        "event": "recover_failed",
        "provider": provider,
        "email": email,
        "is_google": is_google,
        "tried": tried,
    })


def codex_google_relogin_and_notify(account: dict[str, Any], reason: str) -> None:
    """Wrapper tương thích call-site cũ → orchestrator chung cho codex."""
    recover_provider_account(account, "codex", reason)


def recover_and_notify(account: dict[str, Any], reason: str) -> str | None:
    """Recover a failing account (reuse refresh_token) and notify admin of the
    error → action → result. Returns the NEW access_token on success, else None.
    Best-effort; never raises. Debounced per account."""
    if not isinstance(account, dict):
        return None
    email = _acct_label(account)
    key = str(account.get("access_token") or email)
    # Nhãn provider để log đủ "tài khoản nào, provider nào" (codex/free/…)
    try:
        from services.account_service import account_group
        group = account_group(account)
    except Exception:
        group = ""
    label = _PROVIDERS.get(group, {}).get("label") or {
        "openai": "OpenAI", "antigravity": "Antigravity",
    }.get(group, group or "ChatGPT")
    det = {"provider": group or "chatgpt", "email": email}

    with _lock:
        if time.time() - _last_attempt.get(key, 0.0) < _COOLDOWN_S:
            return None  # attempted recently — skip to avoid spam
        _last_attempt[key] = time.time()

    if not str(account.get("refresh_token") or "").strip():
        _notify(f"⚠️ {label} — {email}\nLỗi: {reason}\n"
                f"→ [T0] Không có refresh_token nên không tự khôi phục được.\n"
                f"❌ Cần đăng nhập lại thủ công qua noVNC (cổng 6080).",
                {**det, "step": "T0-no-refresh-token", "reason": reason})
        logger.warning({"event": "recovery_no_refresh", "email": email, "reason": reason})
        return None

    _notify(f"⚠️ {label} — {email}\nLỗi: {reason}\n→ [T0] Đang tự làm mới token (refresh)…",
            {**det, "step": "T0-refresh", "reason": reason})
    try:
        from services.codex_refresh_scheduler import _refresh_one
        from services.account_service import account_service
        updated = _refresh_one(account)
        if updated:
            new_token = str(updated.get("access_token") or "")
            old_token = str(account.get("access_token") or "")
            if new_token and new_token != old_token:
                # update_account forces the old key, so re-key manually.
                with account_service._lock:
                    account_service._accounts.pop(old_token, None)
                    normalized = account_service._normalize_account(updated)
                    if normalized:
                        account_service._accounts[new_token] = normalized
                    account_service._save_accounts()
                _notify(f"✅ {label} — {email}\nKhôi phục xong ([T0] refresh token mới). Dùng lại bình thường.",
                        {**det, "step": "T0-refresh-ok"})
                logger.info({"event": "recovery_ok", "email": email})
                return new_token
    except Exception as exc:
        logger.warning({"event": "recovery_error", "email": email, "error": str(exc)[:150]})

    _notify(f"❌ {label} — {email}\n[T0] Refresh THẤT BẠI ({reason}).\n"
            f"→ refresh_token có thể đã hết hạn. Cần đăng nhập lại qua noVNC (`:6080`).",
            {**det, "step": "T0-refresh-failed", "reason": reason})
    return None
