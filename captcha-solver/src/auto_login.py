"""Google account auto-login orchestration with 2FA support.

Three states the user cares about:
  • running  — Playwright is busy on Chrome (typing email/password,
               waiting for Google's UI). UI shows "Đang chạy: <step>".
  • need_code — Google asked for an SMS/authenticator code. UI shows
                a code-entry input that POSTs to /2fa-code.
  • need_tap — Google sent a "tap this number" notification to the
               user's phone. UI shows the number to tap.
  • success / failed — terminal.

Anti-bot reality: Google often blocks headless-detected Chrome in a
container, especially from a VPS IP without a real device history.
If auto-login stalls, the noVNC window is still open and the user can
finish manually — the saved cookies still persist in user-data-dir.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from .browser_pool import pool

try:
    import pyotp
    _HAS_PYOTP = True
except ImportError:
    pyotp = None  # type: ignore
    _HAS_PYOTP = False

logger = logging.getLogger(__name__)


_GOOGLE_SIGNIN_URL = (
    "https://accounts.google.com/signin/v2/identifier"
    "?hl=vi&service=accountsettings"
)

# Cookies that prove a Google login completed.
_GOOGLE_LOGIN_COOKIES = ("__Secure-1PSID", "__Secure-3PSID", "SID")

async def _type_human_like(locator, text: str) -> None:
    """Type text character-by-character with randomized delays to evade bot detection."""
    # Random pause before starting (human looks at phone, then starts typing)
    await asyncio.sleep(random.uniform(0.4, 1.2))
    for i, ch in enumerate(text):
        await locator.press(ch, delay=random.randint(80, 350))
        # Occasionally pause mid-code (human glances at phone between digits)
        if i == 2 and random.random() < 0.6:
            await asyncio.sleep(random.uniform(0.2, 0.6))


# Selectors Google uses for the 2FA code input (varies by challenge type).
_2FA_CODE_SELECTORS = (
    'input[type="tel"][autocomplete="one-time-code"]',
    'input[name="totpPin"]',
    'input[id="totpPin"]',
    'input[autocomplete="one-time-code"]',
    'input[type="tel"]:not([disabled])',
)

# Selectors for the tap-match number Google displays. They change often;
# we look for any short numeric digit in a heading-like element. Best-
# effort — if we can't extract it, we still report state="need_tap" so
# the user knows to look at noVNC.
_TAP_MATCH_SELECTORS = (
    'samp',
    'div[role="heading"] >> visible=true',
    '.eFajbf',
    '.NQ5OL',
)

# Selectors for the "Choose how you'll sign in" page. When Google shows
# a list of 2FA methods (tap-on-device / Authenticator / SMS / recovery
# email), this page sits between password and the actual challenge.
# `_detect_state` would otherwise treat it as "working" and the 4-minute
# deadline expires before any code field shows up. We pick the TOTP /
# Authenticator option automatically because it's the fastest fully-
# automatable path — user only has to read the 6-digit Authenticator
# code and POST it to /v1/session/{profile}/auto-login-2fa-code.
# IMPORTANT: text-based selectors MUST come before data-challengetype
# because when "Tap Yes" is disabled, data-challengetype="9" can match
# the wrong element (the disabled tap option instead of Authenticator).
_AUTHENTICATOR_OPTION_SELECTORS = (
    'li:has-text("Google Authenticator")',
    'li:has-text("ứng dụng xác thực")',
    'div[role="link"]:has-text("Google Authenticator")',
    'div[role="link"]:has-text("authenticator")',
    'div:has-text("Google Authenticator"):not(:has(div))',
    'li[data-challengetype="9"]:has-text("Authenticator")',
    'li[data-challengetype="9"]:has-text("xác thực")',
    'div[data-challengetype="9"]:has-text("Authenticator")',
    'div[data-challengetype="9"]:has-text("xác thực")',
    'li[data-challengetype="9"]',          # last resort
    'div[data-challengetype="9"]',          # last resort
)

# Selectors for phone-call / SMS challenge when Google offers the method
# picker. After clicking, Google calls or texts the enrolled number and
# then shows a code input — same need_code state as Authenticator.
_PHONE_OPTION_SELECTORS = (
    'li:has-text("cuộc gọi đến số")',
    'li:has-text("nhận cuộc gọi")',
    'li:has-text("nhận mã qua")',
    'div[role="link"]:has-text("cuộc gọi đến số")',
    'div[role="link"]:has-text("nhận cuộc gọi")',
    'div[role="link"]:has-text("nhận mã qua")',
    'li:has-text("số điện thoại"):not(:has-text("sử dụng"))',
    'div[role="link"]:has-text("số điện thoại"):not(:has-text("sử dụng"))',
)

_METHOD_SELECTOR_HINTS = (
    "choose how you", "chọn cách",
    "try another way", "thử cách khác",
    "google authenticator",
    "nhận mã xác minh", "ứng dụng xác thực",
)


async def _pick_authenticator_method(page) -> bool:
    """When Google shows the method picker, click the Authenticator entry."""
    for sel in _AUTHENTICATOR_OPTION_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            await loc.click(timeout=2500)
            logger.info("auto_login: picked Authenticator method via selector=%s", sel)
            return True
        except Exception:
            continue
            
    for t in ("authenticator", "ứng dụng xác thực"):
        try:
            loc = page.locator(f'text=/{t}/i').last
            if await loc.count() > 0:
                await loc.click(timeout=2500)
                logger.info("auto_login: picked Authenticator method via text=/%s/i", t)
                return True
        except Exception:
            pass

    logger.info("auto_login: method-picker visible but no Authenticator selector matched")
    return False


async def _pick_phone_method(page) -> bool:
    """When Google shows the method picker, click the phone-call / SMS entry."""
    for sel in _PHONE_OPTION_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            await loc.click(timeout=2500)
            logger.info("auto_login: picked phone method via selector=%s", sel)
            return True
        except Exception:
            continue
            
    for t in ("cuộc gọi", "nhận cuộc gọi", "số điện thoại", "nhận mã qua", "gọi đến số"):
        try:
            loc = page.locator(f'text=/{t}/i').last
            if await loc.count() > 0:
                await loc.click(timeout=2500)
                logger.info("auto_login: picked phone method via text=/%s/i", t)
                return True
        except Exception:
            pass

    logger.info("auto_login: method-picker visible but no phone selector matched")
    return False


async def _pick_tap_method(page) -> bool:
    """When Google shows the method picker, click the 'Tap Yes on your phone' entry."""
    
    _TAP_OPTION_SELECTORS = (
        'li:has-text("Nhấn vào Có trên điện thoại")',
        'li:has-text("Nhấn Có trên điện thoại")',
        'li:has-text("Tap Yes on your phone")',
        'li:has-text("Tap Yes on your phone or tablet")',
        'div[role="link"]:has-text("Nhấn vào Có")',
        'div[role="link"]:has-text("Tap Yes")',
        'div[data-challengetype="12"]',
        'li[data-challengetype="12"]',
    )
    for sel in _TAP_OPTION_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                await loc.click(timeout=2500)
                logger.info("auto_login: picked Tap method via selector=%s", sel)
                return True
        except Exception:
            continue
            
    for t in ("nhấn có", "tap yes", "nhấn vào có"):
        try:
            loc = page.locator(f'text=/{t}/i').last
            if await loc.count() > 0:
                await loc.click(timeout=2500)
                logger.info("auto_login: picked Tap method via text=/%s/i", t)
                return True
        except Exception:
            pass

    logger.info("auto_login: method-picker visible but no Tap selector matched")
    return False


# Phrases that mark a Google OAuth consent / account-confirm page.
# Match against the body text (lowercased). Any one of these means we
# should look for an affirmative button to click.
_CONSENT_SCREEN_HINTS = (
    "continue as", "tiếp tục với tư cách", "tiep tuc voi tu cach",
    "wants access", "muốn truy cập", "muon truy cap",
    "to continue to", "để tiếp tục với", "de tiep tuc voi",
    "by continuing, google will share", "khi tiếp tục, google sẽ chia sẻ",
    "review the permissions", "xem lại quyền", "xem lai quyen",
    "google sẽ chia sẻ", "google se chia se",
    # Granular-consent screen (enable_granular_consent=true) — checkbox list
    "select what", "chọn nội dung", "chon noi dung",
    "what * can access", "can access", "có thể truy cập", "co the truy cap",
    "share some", "chia sẻ một số", "chia se mot so",
    "allow this app", "cho phép ứng dụng này", "cho phep ung dung nay",
    "confirm your identity", "xác nhận danh tính", "xac nhan danh tinh",
    "verify it's you", "xác minh là bạn", "xac minh la ban",
    "choose an account", "chọn một tài khoản", "chon mot tai khoan",
    "sign in to", "đăng nhập vào", "dang nhap vao",
    "đăng nhập lại vào", "dang nhap lai vao",
    "bạn đang đăng nhập", "ban dang dang nhap",
    "đăng nhập bằng google", "dang nhap bang google",
)

# Affirmative button text — matched against innerText / aria-label
# (lowercased, trimmed). Includes both EN and VI variants. We match by
# equality OR startswith because Google often nests extra spans inside
# the button (e.g. "Continue\n>").
_CONSENT_AFFIRMATIVE_VOCAB = (
    "continue",
    "tiếp tục", "tiep tuc",
    "allow", "allow access",
    "cho phép", "cho phep",
    "confirm", "xác nhận", "xac nhan",
    "i agree", "đồng ý", "dong y",
    "next", "tiếp theo", "tiep theo",
    "yes, continue", "có, tiếp tục",
    "accept", "chấp nhận", "chap nhan",
)


async def click_google_oauth_consent(page, timeout: float = 8.0) -> bool:
    """Auto-click Google's OAuth consent / "Continue as <email>" / "Allow"
    pages that appear after a service (ChatGPT, Gemini, ...) redirects to
    accounts.google.com and the user has cookies for the Google account
    but the target app needs explicit consent.

    Safe to call multiple times — it no-ops unless body text contains
    one of `_CONSENT_SCREEN_HINTS`, so it won't fire on the email or
    password steps (which have their own dedicated handlers).

    Returns True if a click was performed.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            url = page.url
        except Exception:
            url = ""
        if "accounts.google.com" not in url:
            return False
        try:
            body_text = (await page.locator("body").inner_text(timeout=800)).lower()
        except Exception:
            await asyncio.sleep(0.5)
            continue
        if not any(h in body_text for h in _CONSENT_SCREEN_HINTS):
            await asyncio.sleep(0.7)
            continue
        try:
            clicked_label = await page.evaluate(
                """
                (vocab) => {
                    // Granular consent: tick any unchecked permission boxes
                    // (native + Material role=checkbox) before hitting Continue.
                    document.querySelectorAll('input[type="checkbox"], [role="checkbox"]').forEach(cb => {
                        if (!cb.offsetParent) return;
                        const checked = cb.checked || cb.getAttribute('aria-checked') === 'true';
                        if (!checked && !cb.disabled) { try { cb.click(); } catch (e) {} }
                    });
                    const sel = 'button, a, div[role="button"], input[type="submit"]';
                    const btns = Array.from(document.querySelectorAll(sel));
                    for (const b of btns) {
                        if (!b.offsetParent) continue;
                        let text = (b.innerText || b.getAttribute('aria-label') || b.value || '').trim().toLowerCase();
                        if (!text) continue;
                        // Strip surrounding whitespace and trailing punctuation.
                        text = text.replace(/\\s+/g, ' ');
                        for (const v of vocab) {
                            if (text === v || text.startsWith(v + ' ') || text.startsWith(v + ',') || text.startsWith(v + '.')) {
                                b.click();
                                return text;
                            }
                        }
                    }
                    return null;
                }
                """,
                list(_CONSENT_AFFIRMATIVE_VOCAB),
            )
            if clicked_label:
                logger.info("auto_login: clicked OAuth consent button text=%r url=%s",
                            clicked_label[:60], url)
                await asyncio.sleep(1.5)
                return True
        except Exception as exc:
            logger.debug("auto_login: consent click eval failed: %s", str(exc)[:120])
        await asyncio.sleep(0.7)
    return False


@dataclass
class LoginSession:
    profile: str
    email: str
    state: str = "pending"
    message: str = ""
    tap_number: Optional[str] = None
    pending_code: Optional[str] = None
    totp_secret: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    error: Optional[str] = None
    # Selects how to satisfy a 2FA challenge when Google offers a picker.
    # "auth" → click Authenticator → state=need_code, user POSTs 6-digit.
    # "tap"  → skip picker, fall through to tap-on-phone (state=need_tap).
    prefer_method: str = "auth"

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "email": self.email,
            "state": self.state,
            "message": self.message,
            "tap_number": self.tap_number,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed_sec": int((self.completed_at or time.time()) - self.started_at),
            "error": self.error,
        }


_sessions: dict[str, LoginSession] = {}
_tasks: dict[str, asyncio.Task] = {}


def get_session(profile: str) -> Optional[LoginSession]:
    return _sessions.get(profile)


def list_sessions() -> list[dict]:
    return [s.to_dict() for s in _sessions.values()]


def submit_2fa_code(profile: str, code: str) -> bool:
    """Feed an SMS / TOTP / backup code to a waiting auto-login.
    Returns False if there's no session waiting for a code."""
    session = _sessions.get(profile)
    if not session or session.state != "need_code":
        return False
    session.pending_code = code.strip()
    session.message = "Đã nhận mã, đang submit..."
    return True


async def _nuke_profile(profile: str, max_wait: float = 10.0) -> None:
    """Delete browser profile directory, retrying until files are unlocked.

    SAFETY: if another session (gemini_web, flow, etc.) is currently using
    this profile through the browser pool, we skip deletion entirely.
    Only nuke profiles that are NOT actively in use by another component.
    """
    if pool.is_loaded(profile):
        logger.info("auto_login: profile %s is loaded in pool, skipping nuke", profile)
        return

    import shutil
    from .settings import settings as _settings
    _profile_dir = _settings.data_dir / "profiles" / profile
    if not _profile_dir.exists():
        return
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            shutil.rmtree(str(_profile_dir), ignore_errors=False)
            logger.info("auto_login: nuked profile %s", profile)
            return
        except PermissionError:
            logger.warning("auto_login: profile %s locked, retrying in 1s...", profile)
            await asyncio.sleep(1.0)
        except Exception as exc:
            logger.warning("auto_login: rmtree attempt failed: %s, retrying...", exc)
            await asyncio.sleep(1.0)
    # Last resort: rename out of the way
    try:
        backup = _profile_dir.with_name(_profile_dir.name + f".old-{int(time.time())}")
        shutil.move(str(_profile_dir), str(backup))
        logger.warning("auto_login: could not delete, renamed to %s", backup.name)
    except Exception as exc:
        logger.error("auto_login: profile cleanup failed completely: %s", exc)


async def start_auto_login(
    profile: str,
    email: str,
    password: str,
    prefer_method: str = "auth",
    totp_secret: Optional[str] = None,
) -> LoginSession:
    """Kick off background auto-login. Returns the LoginSession immediately
    so the UI can start polling /auto-login-status.

    `prefer_method` selects the 2FA path when Google offers a picker:
    "auth" = click Authenticator (need_code), "tap" = wait for the
    tap-on-device prompt (need_tap), "phone" = click phone call / SMS
    option (need_code after Google calls/texts).

    If `totp_secret` is provided and pyotp is installed, 2FA codes are
    auto-generated instead of waiting for manual input.
    """
    old_task = _tasks.pop(profile, None)
    if old_task and not old_task.done():
        old_task.cancel()

    session = LoginSession(
        profile=profile,
        email=email,
        state="starting",
        message="Khởi tạo Chrome",
        prefer_method=prefer_method if prefer_method in ("auth", "tap", "phone") else "auth",
        totp_secret=totp_secret,
    )
    _sessions[profile] = session

    # Always close old context before reusing it
    await pool.close_profile(profile)
    # await _nuke_profile(profile)  # REMOVED to preserve ChatGPT/Codex cache

    task = asyncio.create_task(_run(session, password))
    _tasks[profile] = task
    return session


async def _already_logged_in(ctx) -> bool:
    try:
        cookies = await ctx.cookies()
        return any(c["name"] in _GOOGLE_LOGIN_COOKIES for c in cookies)
    except Exception:
        return False


async def _detect_state(page) -> tuple[str, Optional[str]]:
    """Inspect the current Google sign-in page and classify it.

    Returns (state, extra_info) where state is one of:
      success, need_code, need_tap, error, working
    extra_info is the tap number when state=="need_tap"."""
    try:
        url = page.url
    except Exception:
        return "working", None

    # Success heuristic — Google redirects away from accounts.google.com
    # after sign-in, typically to myaccount.google.com or service URL.
    if "myaccount.google.com" in url or "google.com/accounts/Logout" in url:
        return "success", None
    if "accounts.google.com" not in url and "ServiceLogin" not in url:
        return "success", None

    # Generic error banner
    try:
        err_count = await page.locator(
            'div[jsname="B34EJ"], .Ekjuhf, .dEOOab'
        ).first.count()
        if err_count > 0:
            try:
                err_text = await page.locator(
                    'div[jsname="B34EJ"], .Ekjuhf, .dEOOab'
                ).first.inner_text(timeout=600)
                if err_text and len(err_text) < 220:
                    return "error", err_text.strip()
            except Exception:
                pass
    except Exception:
        pass

    # Code input visible?
    for sel in _2FA_CODE_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible(timeout=400):
                return "need_code", None
        except Exception:
            continue

    # Tap-match: page typically says "Check your phone" or has a samp
    # element with a number 0-99.
    try:
        body_text = (await page.locator("body").inner_text(timeout=600)).lower()
    except Exception:
        body_text = ""
    if any(k in body_text for k in (
        "check your phone", "kiểm tra điện thoại",
        "tap yes", "nhấn có", "trên thiết bị của bạn",
    )):
        # Try extracting the number
        for sel in _TAP_MATCH_SELECTORS:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    txt = (await loc.inner_text(timeout=400)).strip()
                    if txt.isdigit() and 1 <= len(txt) <= 3:
                        return "need_tap", txt
            except Exception:
                continue
        return "need_tap", None

    return "working", None


async def _safe_click(page, *selectors, timeout: int = 2500) -> bool:
    for sel in selectors:
        try:
            await page.locator(sel).first.click(timeout=timeout)
            return True
        except Exception:
            continue
    return False


async def do_google_login_steps(
    session: LoginSession,
    page,
    ctx,
    password: str,
    prefer_method: str = "auth",
) -> bool:
    """Shared Google login email/password/2FA dance.

    Assumes `page` is already navigated to an accounts.google.com page
    (signin form OR an OAuth redirect target). Drives the form forward
    and handles 2FA prompts.

    `prefer_method` selects how to satisfy a 2FA challenge when Google
    offers a method picker:
      "auth"  — click the Authenticator option; flow advances to need_code
                and the user POSTs the 6-digit code via the existing
                /auto-login-2fa-code endpoint.
      "tap"   — skip the picker; let Google fall through to the
                tap-on-device prompt (need_tap). The user opens Gmail/
                Google app on their phone and taps "Yes, it's me".
      "phone" — click the phone-call / SMS option; Google calls or texts
                the enrolled number, then shows a code input (need_code).

    Updates `session.state` / `.message` / `.error` in-place. Returns
    True on success, False on failure. Caller decides what to do next
    (e.g. scrape session cookies, navigate elsewhere, etc).
    """
    if not password:
        session.state = "failed"
        session.error = "Không có mật khẩu để tự động đăng nhập (reuse_only=True hoặc thiếu dữ liệu)."
        session.completed_at = time.time()
        return False
    
    async def _click_try_again() -> bool:
        # 1. Attribute-based reliable locators
        for _sel in (
            'a[href*="/restart"]',
            '[aria-label="Thử lại"]',
            '[aria-label="Try again"]',
            'div[jsname="LgbsSe"]:has-text("Thử lại")',
            'div[jsname="LgbsSe"]:has-text("Try again")',
            'button:has-text("Thử lại")',
            'button:has-text("Try again")'
        ):
            try:
                _loc = page.locator(_sel).first
                if await _loc.is_visible(timeout=500):
                    await _loc.click()
                    return True
            except Exception:
                continue
                
        # 2. Text-based exact matches (Playwright native)
        for _t in ("Thử lại", "Try again", "Thử đăng nhập lại"):
            try:
                _loc = page.locator(f'text="{_t}"').last
                if await _loc.is_visible(timeout=500):
                    await _loc.click()
                    return True
            except Exception:
                pass

        # 3. Fallback generic JS clicker that ignores empty text
        try:
            if await page.evaluate("""() => { 
                const a=document.querySelectorAll('*'); 
                for(const el of a){ 
                    if(!el.offsetParent) continue; 
                    if(el.tagName !== 'BUTTON' && el.tagName !== 'A' && el.tagName !== 'SPAN' && el.tagName !== 'DIV' && el.tagName !== 'INPUT') continue;
                    const t=(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '').normalize('NFC').trim().toLowerCase(); 
                    if(t.includes('thử lại') || t.includes('try again') || t.includes('thử đăng nhập lại')){
                        el.click();return true;
                    } 
                } 
                return false; 
            }"""):
                return True
        except Exception:
            pass
        return False

    # ── Google block detection: check if Google served an error page ──
    # Wait out the transient "Đang tải" (loading) spinner first — checking too
    # early matches hidden/placeholder text and yields a false "blocked".
    _BLOCK_TEXTS = (
        "browser or app may not be secure",
        "trình duyệt hoặc ứng dụng này có thể không an toàn",
        "couldn't sign you in",
        "không thể đăng nhập",
    )
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        pass
    for _ in range(8):
        try:
            body = (await page.locator("body").inner_text(timeout=2000)).strip().lower()
        except Exception:
            body = ""
        if not body or body in ("đang tải", "đang tải...", "loading", "loading…", "loading..."):
            await asyncio.sleep(1.0)
            continue
        matched = next((k for k in _BLOCK_TEXTS if k in body), None)
        if matched:
            # KHÔNG fail ngay — BotGuard chập chờn. Vòng lặp email bên dưới sẽ
            # bấm 'Thử lại' + nhập lại mail liên tục đến khi lọt ô mật khẩu.
            logger.info("auto_login: BotGuard block at start (matched=%r) — will retry", matched)
        break

    # ── Handle Account Chooser ──
    # Google often shows the "Choose an account" screen instead of an email input
    # if the profile already has history.
    try:
        clicked_tile = await page.evaluate(
            """(em) => {
                const els = Array.from(document.querySelectorAll('div[data-identifier],li,div[role=link],div[role=button],a,div[jsname]'));
                for (const e of els) {
                    const id = (e.getAttribute('data-identifier')||'').toLowerCase();
                    if (id && id === em) { e.click(); return true; }
                }
                for (const e of els) {
                    if ((e.innerText||'').toLowerCase().includes(em)) { e.click(); return true; }
                }
                return false;
            }""", session.email.lower()
        )
        if clicked_tile:
            logger.info("auto_login: clicked account tile for %s on chooser screen", session.email)
            await asyncio.sleep(2.0)
    except Exception:
        pass

    # After an account-chooser SSO pick, Google lands directly on the password
    # challenge (no email field). Detect that and skip straight to password so
    # we don't fail on the missing email input.
    pwd_already = clicked_tile
    if not pwd_already:
        for _sel in ('input[type="password"]', 'input[name="Passwd"]',
                     'input[autocomplete="current-password"]', 'input[name="password"]'):
            try:
                if await page.locator(_sel).first.is_visible(timeout=2500):
                    pwd_already = True
                    break
            except Exception:
                continue

    if pwd_already:
        logger.info("auto_login: password field assumed/present — skipping email step (SSO pick)")
    else:
        session.message = "Điền email..."
        try:
            email_success = False
            for _retry in range(6):
                # 1. Check for BotGuard block and click "Thử lại"
                try:
                    body = (await page.locator("body").inner_text(timeout=1000)).strip().lower()
                    if any(b in body for b in _BLOCK_TEXTS):
                        session.message = f"Google chặn (BotGuard) — bấm Thử lại lần {_retry + 1}..."
                        await _click_try_again()
                        await asyncio.sleep(2.5)
                except Exception:
                    pass

                # 2. Try to find the email input
                email_input = None
                for _sel in ('input[type="email"]', 'input#identifierId',
                             'input[name="identifier"]', 'input[autocomplete="username"]',
                             'input[autocomplete="email"]'):
                    try:
                        _loc = page.locator(_sel).first
                        if await _loc.is_visible(timeout=2000):
                            email_input = _loc
                            break
                    except Exception:
                        continue
                
                # 3. If found, fill and click next
                if email_input is not None:
                    await email_input.fill("")
                    await email_input.press_sequentially(session.email, delay=50)
                    await asyncio.sleep(0.8)
                    clicked = await _safe_click(
                        page,
                        '#identifierNext button', '#identifierNext',
                        'button:has-text("Next")', 'button:has-text("Tiếp theo")',
                        'span[jsname="V67aGc"]', 'button[jsname="LgbsSe"]:visible',
                        'div[role="button"]:has-text("Next")', 'div[role="button"]:has-text("Tiếp theo")',
                    )
                    if not clicked:
                        await page.evaluate("""() => {
                            const all = document.querySelectorAll('button, div[role="button"], span[role="button"]');
                            for (const el of all) {
                                if (!el.offsetParent) continue;
                                const t = (el.innerText || '').trim().toLowerCase();
                                if (t === 'next' || t === 'tiếp theo' || t === 'tiep theo') {
                                    el.click();
                                    return;
                                }
                            }
                        }""")
                    email_success = True
                    break
                await asyncio.sleep(1.0)
            
            if not email_success:
                raise RuntimeError("email field not found (BotGuard chặn gắt hoặc đổi UI)")
        except Exception as exc:
            session.state = "failed"
            session.error = f"Không tìm thấy ô email: {exc}"
            session.completed_at = time.time()
            return False

    await asyncio.sleep(2.0)

    # Debug: log what page Google shows after email
    try:
        url = page.url or "?"
        title = await page.title() or ""
        body = (await page.locator("body").inner_text(timeout=2000))[:500]
        logger.info("auto_login: after email, url=%s title=%r body=%s", url[:120], title[:80], body[:300])
    except Exception:
        pass

    # ── Password step + né BotGuard (retry email) ──
    # Chiến lược: nếu Google chặn ("trình duyệt không an toàn"/"không thể đăng
    # nhập") thì BẤM 'Thử lại' + NHẬP LẠI email, LẶP LIÊN TỤC đến khi hiện ô
    # MẬT KHẨU (BotGuard chập chờn, thử đủ nhiều sẽ lọt). Captcha vẫn chờ tay.
    session.message = "Điền mật khẩu..."
    _PWD_SELECTORS = ('input[type="password"]', 'input[name="Passwd"]',
                      'input[autocomplete="current-password"]', 'input[name="password"]')
    _CAPTCHA_SELECTORS = ('img#captchaimg', 'img[src*="Captcha"]', 'input[name="ca"]',
                          'input[aria-label*="văn bản" i]', 'input[aria-label*="hear" i]')

    async def _pwd_visible():
        for _sel in _PWD_SELECTORS:
            try:
                _loc = page.locator(_sel).first
                if await _loc.is_visible(timeout=1000):
                    return _loc
            except Exception:
                continue
        return None

    async def _reenter_email() -> None:
        try:
            # First try to see if it's the account chooser screen
            clicked_tile = await page.evaluate(
                """(em) => {
                    const els = Array.from(document.querySelectorAll('div[data-identifier],li,div[role=link],div[role=button],a,div[jsname]'));
                    for (const e of els) {
                        const id = (e.getAttribute('data-identifier')||'').toLowerCase();
                        if (id && id === em) { e.click(); return true; }
                    }
                    for (const e of els) {
                        if ((e.innerText||'').toLowerCase().includes(em)) { e.click(); return true; }
                    }
                    return false;
                }""", session.email.lower()
            )
            if clicked_tile:
                logger.info("auto_login: clicked account tile for %s in _reenter_email", session.email)
                return

            for _sel in ('input[type="email"]', 'input#identifierId',
                         'input[name="identifier"]', 'input[autocomplete="username"]',
                         'input[autocomplete="email"]'):
                try:
                    el = page.locator(_sel).first
                    if await el.is_visible(timeout=500):
                        await el.fill("")
                        await el.press_sequentially(session.email, delay=50)
                        await asyncio.sleep(0.5)
                        await _safe_click(
                            page, '#identifierNext button', '#identifierNext',
                            'button:has-text("Next")', 'button:has-text("Tiếp theo")',
                        )
                        break
                except Exception:
                    continue
        except Exception:
            pass

    pwd_input = None
    captcha_flagged = False
    block_retries = 0
    pwd_deadline = time.time() + 300  # tối đa 5 phút (gồm cả retry BotGuard)
    while time.time() < pwd_deadline:
        # ĐÃ đăng nhập sẵn (SSO pick trúng acc còn phiên): Google nhảy thẳng
        # myaccount.google.com / trang dịch vụ nên ô mật khẩu KHÔNG BAO GIỜ hiện.
        # Không thoát sớm ở đây thì quay vòng đủ 300s rồi báo "failed" OAN dù
        # session Google vẫn sống → recover Codex trượt vô cớ (bug 2026-07-24).
        if await _already_logged_in(ctx):
            session.state = "success"
            session.message = "Google login OK (đã đăng nhập sẵn)"
            session.completed_at = time.time()
            logger.info("auto_login: already signed in for %s — bỏ qua bước mật khẩu",
                        session.profile)
            return True
        pwd_input = await _pwd_visible()
        if pwd_input is not None:
            break
        try:
            body = (await page.locator("body").inner_text(timeout=1500)).strip().lower()
        except Exception:
            body = ""
        if body in ("", "đang tải", "đang tải...", "loading", "loading…", "loading..."):
            await asyncio.sleep(1.5)
            continue
        # BotGuard chặn → bấm 'Thử lại' + nhập lại email, lặp tới khi có password
        if any(b in body for b in _BLOCK_TEXTS):
            block_retries += 1
            session.state = "running"
            session.message = f"Google chặn (BotGuard) — thử lại lần {block_retries}..."
            logger.info("auto_login: BotGuard block, retry #%d for %s", block_retries, session.profile)
            await _click_try_again()
            await asyncio.sleep(2.0)
            await _reenter_email()
            await asyncio.sleep(2.5)
            continue
        # captcha? flag để user giải trên noVNC
        if not captcha_flagged:
            for _csel in _CAPTCHA_SELECTORS:
                try:
                    if await page.locator(_csel).first.is_visible(timeout=800):
                        session.state = "need_captcha"
                        session.message = "Google yêu cầu captcha — gõ captcha trên noVNC, hệ thống sẽ TỰ tiếp tục password+2FA"
                        logger.info("auto_login: captcha detected for %s, waiting manual solve", session.profile)
                        captcha_flagged = True
                        break
                except Exception:
                    continue
        await asyncio.sleep(2.0)
    if pwd_input is None:
        session.state = "failed"
        session.error = f"Không lọt được ô mật khẩu (BotGuard chặn sau {block_retries} lần thử / captcha chưa giải)"
        session.completed_at = time.time()
        return False
    try:
        session.state = "running"
        session.message = "Điền mật khẩu..."
        await asyncio.sleep(0.6)
        await pwd_input.fill("")
        await pwd_input.press_sequentially(password, delay=40)
        await asyncio.sleep(0.6)
        clicked = await _safe_click(
            page, 
            '#passwordNext button', 
            '#passwordNext',
            'button:has-text("Next")',
            'button:has-text("Tiếp theo")',
            'span[jsname="V67aGc"]', 
            'button[jsname="LgbsSe"]:visible',
            'div[role="button"]:has-text("Next")',
            'div[role="button"]:has-text("Tiếp theo")'
        )
        if not clicked:
            await page.evaluate("""() => {
                const all = document.querySelectorAll('button, div[role="button"], span[role="button"]');
                for (const el of all) {
                    if (!el.offsetParent) continue;
                    const t = (el.innerText || '').trim().toLowerCase();
                    if (t === 'next' || t === 'tiếp theo' || t === 'tiep theo') {
                        el.click();
                        return;
                    }
                }
            }""")
    except Exception as exc:
        session.state = "failed"
        session.error = f"Không điền được mật khẩu: {exc}"
        session.completed_at = time.time()
        return False

    # ── 2FA poll loop ──
    deadline = time.time() + 240
    picker_clicked = False
    while time.time() < deadline:
        await asyncio.sleep(2.0)

        # 1. If Google shows the method picker, pick the method automatically
        if not picker_clicked:
            try:
                if session.totp_secret and _HAS_PYOTP:
                    if await _pick_authenticator_method(page):
                        picker_clicked = True
                        session.message = "Phát hiện mã TOTP tự động, đã chọn Google Authenticator..."
                        await asyncio.sleep(1.5)
                        continue
                
                if session.prefer_method == "phone":
                    if await _pick_phone_method(page):
                        picker_clicked = True
                        session.message = "Đã chọn xác minh qua số điện thoại, đang chờ code..."
                        await asyncio.sleep(1.5)
                        continue
                elif session.prefer_method == "tap":
                    if await _pick_tap_method(page):
                        picker_clicked = True
                        session.message = "Đã chọn Nhấn Có trên điện thoại..."
                        await asyncio.sleep(1.5)
                        continue
                else: # default to auth
                    if await _pick_authenticator_method(page):
                        picker_clicked = True
                        session.message = "Đã chọn Google Authenticator, đang chờ code..."
                        await asyncio.sleep(1.5)
                        continue
                    elif await _pick_tap_method(page):
                        picker_clicked = True
                        session.message = "Không có Authenticator, đã chọn Nhấn Có trên điện thoại..."
                        await asyncio.sleep(1.5)
                        continue
            except Exception:
                pass

        # 2. Expand "Try another way" if needed
        if not picker_clicked:
            clicked_other = await _safe_click(
                page,
                'button:has-text("Thử cách khác")', 'button:has-text("Try another way")',
                'div[role="button"]:has-text("Thử cách khác")', 'div[role="button"]:has-text("Try another way")',
                'span[jsname="V67aGc"]:has-text("Thử cách khác")', 'span[jsname="V67aGc"]:has-text("Try another way")'
            )
            if not clicked_other:
                try:
                    clicked_other = await page.evaluate("""() => {
                        const all = document.querySelectorAll('*');
                        for (const el of all) {
                            let t = (el.innerText || el.textContent || '').normalize('NFC').trim().toLowerCase();
                            t = t.replace(/\s+/g, ' ');
                            if (t.includes('thử cách khác') || t.includes('try another way') || t.includes('chọn cách khác') || t.includes('tùy chọn khác')) {
                                const target = el.closest('button, a, div[role="button"]') || el;
                                target.click();
                                return true;
                            }
                        }
                        return false;
                    }""")
                except Exception:
                    pass
            
            if clicked_other:
                logger.info("auto_login: clicked 'Try another way' button to open method picker")
                await asyncio.sleep(2.0)
                continue

        state, info = await _detect_state(page)

        if state == "success":
            if await _already_logged_in(ctx):
                session.message = "Google login OK"
                return True
            continue

        if state == "error":
            session.state = "failed"
            session.error = info or "Google báo lỗi"
            session.completed_at = time.time()
            return False

        if state == "need_tap":
            session.state = "need_tap"
            session.tap_number = info
            session.message = (
                f"Bấm số {info} trên điện thoại"
                if info else
                "Mở app Gmail/Google trên điện thoại và bấm 'Có' để xác minh"
            )
            continue

        if state == "need_code":
            session.state = "need_code"
            if not picker_clicked:
                has_other = False
                for _sel in (
                    'button:has-text("Thử cách khác")', 'button:has-text("Try another way")',
                    'div[role="button"]:has-text("Thử cách khác")', 'div[role="button"]:has-text("Try another way")',
                    'span[jsname="V67aGc"]:has-text("Thử cách khác")', 'span[jsname="V67aGc"]:has-text("Try another way")'
                ):
                    try:
                        _loc = page.locator(_sel).first
                        if await _loc.is_visible(timeout=500):
                            has_other = True
                            break
                    except Exception:
                        pass
                if not has_other:
                    try:
                        has_other = await page.evaluate("""() => {
                            const all = document.querySelectorAll('*');
                            for (const el of all) {
                                let t = (el.innerText || el.textContent || '').normalize('NFC').trim().toLowerCase();
                                t = t.replace(/\s+/g, ' ');
                                if (t.includes('thử cách khác') || t.includes('try another way') || t.includes('chọn cách khác') || t.includes('tùy chọn khác')) return true;
                            }
                            return false;
                        }""")
                    except Exception:
                        pass
                
                if not has_other:
                    try:
                        body_text = await page.evaluate("() => document.body.innerText")
                        logger.error("auto_login: 'Thử cách khác' NOT FOUND in need_code! Body text: %r", (body_text or "")[:1000].replace('\n', ' '))
                    except Exception:
                        pass
                
                if has_other:
                    session.message = "Google yêu cầu Security Code, bỏ qua để bấm Thử cách khác..."
                    await asyncio.sleep(1.0)
                    continue

            if session.totp_secret and _HAS_PYOTP:
                secret = session.totp_secret.replace(' ', '')
                code = pyotp.TOTP(secret).now()
                session.message = "Da tu sinh ma 2FA"
                logger.info("auto_login: TOTP auto for %s code=%s", session.profile, code)
                await asyncio.sleep(1.0)
            else:
                session.message = "Can ma 2FA"
                code_deadline = time.time() + 180
                while time.time() < code_deadline and not session.pending_code:
                    await asyncio.sleep(1.0)
                    if await _already_logged_in(ctx):
                        session.state = "success"
                        session.message = "Google login OK"
                        return True
                    if not picker_clicked:
                        try:
                            has_other = await page.evaluate("""() => {
                                const btns = Array.from(document.querySelectorAll('button, div[role="button"], span[role="button"], a, li'));
                                for (const b of btns) {
                                    if (!b.offsetParent) continue;
                                    const t = (b.innerText || '').trim().toLowerCase();
                                    if (t.includes('thử cách khác') || t.includes('try another way')) return true;
                                }
                                return false;
                            }""")
                            if has_other:
                                break
                        except Exception:
                            pass
                if not session.pending_code:
                    if await _already_logged_in(ctx):
                        session.state = "success"
                        session.message = "Google login OK"
                        return True
                    session.state = "failed"
                    session.error = "Khong nhan duoc ma 2FA trong 3 phut"
                    session.completed_at = time.time()
                    return False
                code = session.pending_code
                session.pending_code = None
            # Fill code with fill() for reliability on input[type=tel]
            filled = False
            for sel in _2FA_CODE_SELECTORS:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        await loc.click(timeout=2000)
                        await loc.fill('')
                        await asyncio.sleep(random.uniform(0.3, 0.6))
                        await loc.fill(code)
                        await asyncio.sleep(0.3)
                        await loc.press("Enter")
                        try:
                            actual = await loc.input_value()
                            logger.info("auto_login: typed=%s actual=%s via selector=%s", code, actual, sel)
                        except Exception:
                            logger.info("auto_login: filled 2FA code via selector=%s", sel)
                        filled = True
                        break
                except Exception:
                    continue
            if not filled:
                logger.warning("auto_login: could not fill 2FA code with any selector")
            await asyncio.sleep(0.5)
            clicked = await _safe_click(
                page,
                'button:has-text("Next")', 'button:has-text("Tiếp theo")',
                'span[jsname="V67aGc"]',
                '#totpNext button', '#submit',
                'button[jsname="LgbsSe"]:visible',
            )
            if not clicked:
                await page.evaluate("""() => {
                    const all = document.querySelectorAll('button, div[role="button"], span[role="button"]');
                    for (const el of all) {
                        if (!el.offsetParent) continue;
                        const t = (el.innerText || '').trim().toLowerCase();
                        if (t.includes('tiếp theo') || t.includes('next')) { el.click(); return true; }
                    }
                    return false;
                }""")
            session.state = "running"
            session.message = "Đã gửi mã, đang xác minh..."
            await asyncio.sleep(5.0)
            continue

    session.state = "failed"
    session.error = "Hết 4 phút mà chưa hoàn tất 2FA"
    session.completed_at = time.time()
    return False


async def _run(session: LoginSession, password: str) -> None:
    # Onboard FAIL or SUCCESS -> dong browser ngay de khoi dot CPU tren Xvfb, luu cache.
    # CancelledError (login moi chiem profile) propagate -> KHONG close (ne race).
    await _run_inner(session, password)
    if session.state in ("failed", "success"):
        try:
            await pool.close_profile(session.profile)
            logger.info("closed browser after onboard profile=%s state=%s", session.profile, session.state)
        except Exception:
            logger.debug("close_profile after onboard skipped", exc_info=True)

async def _run_inner(session: LoginSession, password: str) -> None:
    """Playwright orchestration for accounts.google.com direct login.
    Updates session.state in-place; UI polls /v1/session/{profile}/
    auto-login-status to see progress."""
    try:
        session.state = "starting"
        session.message = "Đang mở Chrome (headful → noVNC)"
        # KHÔNG force_recreate để giữ lại cache/cookie của các dịch vụ khác (ChatGPT, Codex)
        ctx = await pool.get(profile=session.profile, headless=False, force_recreate=False)

        pages = ctx.pages
        page = pages[0] if pages else await ctx.new_page()
        try:
            await page.bring_to_front()
        except Exception:
            pass

        session.state = "running"
        session.message = "Mở trang accounts.google.com (qua trang chủ Google)..."
        navigated = False
        try:
            await page.goto("https://www.google.com/", wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(2.0)
            
            clicked = await page.evaluate("""() => {
                const links = document.querySelectorAll('a');
                for (const a of links) {
                    if (a.href && a.href.includes('accounts.google.com/ServiceLogin')) {
                        a.click();
                        return true;
                    }
                }
                return false;
            }""")
            
            if clicked:
                try:
                    await page.wait_for_url("**/accounts.google.com/**", timeout=10000)
                    navigated = True
                except Exception:
                    pass
        except Exception:
            pass
            
        if not navigated:
            await page.goto(_GOOGLE_SIGNIN_URL, wait_until="domcontentloaded", timeout=30_000)

        ok = await do_google_login_steps(session, page, ctx, password)
        if ok:
            session.state = "success"
            session.message = "Đăng nhập thành công"
            session.completed_at = time.time()

    except asyncio.CancelledError:
        session.state = "failed"
        session.error = "Bị huỷ (có yêu cầu auto-login mới)"
        session.completed_at = time.time()
        raise
    except Exception as exc:
        logger.exception("auto-login crashed profile=%s", session.profile)
        session.state = "failed"
        session.error = str(exc)
        session.completed_at = time.time()
