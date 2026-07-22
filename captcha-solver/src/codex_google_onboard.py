"""Codex OAuth onboard bằng cách RIDE session Google có sẵn trong profile
`google-<name>` của captcha-solver — không cần password/2FA/nuke profile.

Dùng khi token Codex của một tài khoản Google chết (OpenAI revoke) và cần lấy
token mới tự động. Mở auth_url (do chatgpt2api sinh, PKCE), bấm "Continue with
Google", để `click_google_oauth_consent` xử lý account chooser + consent, rồi
bắt URL callback localhost chứa ?code=... trả về cho phía chatgpt2api exchange.
"""
import asyncio
import logging
import time
from typing import Any

from pydantic import BaseModel

from .browser_pool import pool
from .auto_login import click_google_oauth_consent
from .chatgpt_login import _GOOGLE_BTN_SELECTORS
from .claude_web_login import _pick_google_account

logger = logging.getLogger(__name__)


class CodexGoogleOnboardReq(BaseModel):
    profile: str            # vd: google-smarthomebanbap2011
    auth_url: str           # URL OAuth Codex do chatgpt2api sinh (có state+PKCE)
    email: str = ""         # để bấm đúng tile ở màn account chooser
    headless: bool = True


async def _click_google_btn(page) -> bool:
    """Click "Tiếp tục với Google" / Continue with Google on OpenAI login."""
    # Playwright role/name (VN + EN) — OpenAI welcome-back page uses this label.
    for name in (
        "Tiếp tục với Google",
        "Continue with Google",
        "Continue with google",
        "Google",
    ):
        try:
            loc = page.get_by_role("button", name=name)
            if await loc.count() > 0:
                btn = loc.first
                if await btn.is_visible():
                    await btn.click(timeout=5000, force=True)
                    logger.info("codex-g: clicked Google btn via role name=%r", name)
                    return True
        except Exception:
            continue
    selectors = list(_GOOGLE_BTN_SELECTORS) + [
        'button:has-text("Tiếp tục với Google")',
        'a:has-text("Tiếp tục với Google")',
        'button:has-text("Continue with Google")',
        'div[role="button"]:has-text("Tiếp tục với Google")',
        'div[role="button"]:has-text("Google")',
        # OpenAI sometimes wraps icon+text
        'button:has-text("Google")',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.click(timeout=5000, force=True)
                logger.info("codex-g: clicked Google btn via %s", sel)
                return True
        except Exception:
            continue
    # JS: exact-ish match (avoid Apple/Microsoft)
    try:
        ok = await page.evaluate(
            """() => {
              const re = /tiếp\\s*tục\\s*với\\s*google|continue\\s*with\\s*google/i;
              const bad = /apple|microsoft|github|microsoft|đăng ký|sign up/i;
              const nodes = document.querySelectorAll(
                'button,a,[role="button"],div[role="button"]'
              );
              for (const n of nodes) {
                const t = (n.innerText || n.textContent || '').trim().replace(/\\s+/g, ' ');
                if (!t || t.length > 60) continue;
                if (bad.test(t) && !/google/i.test(t)) continue;
                if (re.test(t) || (/google/i.test(t) && /tiếp|continue/i.test(t))) {
                  n.scrollIntoView({block:'center'});
                  n.click();
                  return t;
                }
              }
              return null;
            }"""
        )
        if ok:
            logger.info("codex-g: JS-clicked Google btn %r", ok)
            return True
    except Exception as exc:
        logger.warning("codex-g: JS Google click failed: %s", exc)
    return False


# Shared rule (OpenAI welcome-back + Google accountchooser):
#   if target email appears in the list → click that tile (refresh that account)
#   else → click "use another account" / "đăng nhập vào tài khoản khác"
_PICK_OR_OTHER_JS = """
(email) => {
  const want = (email || '').toLowerCase().replace(/\\s+/g, '');
  const norm = (s) => (s || '').toLowerCase().replace(/\\s+/g, '');
  const nodes = Array.from(
    document.querySelectorAll(
      'button, a, [role="button"], [role="link"], div[data-identifier], li[data-identifier], div[data-email]'
    )
  );

  if (want) {
    // Prefer data-identifier / data-email exact match (Google)
    for (const n of nodes) {
      const id = norm(n.getAttribute('data-identifier') || n.getAttribute('data-email') || '');
      if (id === want) { n.click(); return { action: 'tile', via: 'data-id', email: want }; }
    }
    // Text match (OpenAI tiles may wrap email across lines — strip whitespace)
    for (const n of nodes) {
      const t = norm(n.innerText || n.textContent || '');
      if (!t || t.length > 200) continue;
      if (t.includes(want)) { n.click(); return { action: 'tile', via: 'text', email: want }; }
    }
  }

  // No matching tile → use another account (same wording on both screens)
  const reOther = /sử dụng một tài khoản khác|use another account|đăng nhập vào tài khoản khác|log in to another account|sign in to another account/i;
  for (const n of nodes) {
    const t = (n.innerText || n.textContent || '').trim().replace(/\\s+/g, ' ');
    if (reOther.test(t) && t.length < 80) {
      n.click();
      return { action: 'other', text: t };
    }
  }
  // Broaden: some Google rows are plain divs without role
  for (const n of document.querySelectorAll('div, li, span')) {
    const t = (n.innerText || '').trim().replace(/\\s+/g, ' ');
    if (reOther.test(t) && t.length < 60 && n.children.length < 4) {
      n.click();
      return { action: 'other', text: t, via: 'broad' };
    }
  }
  return { action: 'none' };
}
"""


async def _pick_account_or_other(page, email: str, *, where: str) -> bool:
    """If `email` is on the chooser list, click it; otherwise click 'another account'."""
    try:
        result = await page.evaluate(_PICK_OR_OTHER_JS, (email or "").strip())
    except Exception as exc:
        logger.warning("codex-g: %s pick-or-other failed: %s", where, exc)
        return False
    if not result or result.get("action") == "none":
        logger.info("codex-g: %s no tile for %r and no other-account btn", where, email)
        return False
    if result.get("action") == "tile":
        logger.info("codex-g: %s clicked tile %s (via %s)", where, email, result.get("via"))
    else:
        logger.info(
            "codex-g: %s target %r not in list → another account (%r)",
            where,
            email,
            result.get("text"),
        )
    await asyncio.sleep(2.0)
    return True


async def _google_chooser_pick(page, email: str) -> bool:
    """Google accountchooser: pick target email, else 'Sử dụng một tài khoản khác'."""
    if await _pick_account_or_other(page, email, where="google-chooser"):
        return True
    # Fallback to existing helper for Google-specific data-identifier quirks
    if email:
        try:
            if await _pick_google_account(page, email):
                logger.info("codex-g: _pick_google_account ok %s", email)
                await asyncio.sleep(2.0)
                return True
        except Exception:
            pass
    return False


async def run_codex_google_onboard(req: CodexGoogleOnboardReq) -> dict[str, Any]:
    ctx = await pool.get(profile=req.profile, headless=req.headless)
    pages = ctx.pages
    page = pages[0] if pages else await ctx.new_page()

    captured: list[str] = []

    def on_request(request):
        u = request.url
        if "localhost" in u and "code=" in u:
            captured.append(u)

    page.on("request", on_request)

    try:
        await page.goto(req.auth_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2.5)

        # Loop until OAuth callback — handle OpenAI login screens + Google chooser
        deadline = time.time() + 120
        google_btn_clicked = False
        while time.time() < deadline and not captured:
            url = ""
            content = ""
            try:
                url = page.url or ""
                content = await page.content()
            except Exception:
                await asyncio.sleep(1.0)
                continue

            # ── Google accountchooser / consent ──
            if "accounts.google.com" in url:
                if "accountchooser" in url or "Chọn tài khoản" in content or "Choose an account" in content:
                    await _google_chooser_pick(page, req.email or "")
                else:
                    if req.email:
                        await _pick_google_account(page, req.email)
                    await click_google_oauth_consent(page, timeout=6.0)
                await asyncio.sleep(1.5)
                continue

            # ── OpenAI ──
            if "auth.openai.com" in url or "chatgpt.com" in url:
                # PRIORITY: always click "Tiếp tục với Google" when visible.
                # Bug trước: trang "Chào mừng trở lại" (/log-in) bị nhầm là
                # account-chooser → chỉ tìm tile email, KHÔNG bao giờ bấm Google.
                has_google_btn = (
                    "Tiếp tục với Google" in content
                    or "Continue with Google" in content
                    or "log-in" in url
                    or "log-in-or-create" in url
                )
                if has_google_btn:
                    try:
                        n_btn = await page.locator(
                            'button:has-text("Tiếp tục với Google"), '
                            'button:has-text("Continue with Google"), '
                            'button:has-text("Google")'
                        ).count()
                    except Exception:
                        n_btn = 0
                    if n_btn > 0 or "Tiếp tục với Google" in content or "Continue with Google" in content:
                        if await _click_google_btn(page):
                            google_btn_clicked = True
                            logger.info(
                                "codex-g: clicked Tiếp tục với Google url=%s",
                                url[:120],
                            )
                            await asyncio.sleep(3.0)
                            continue

                # Welcome back account tiles / choose-an-account (no Google btn path)
                if (
                    "choose-an-account" in url
                    or "Chọn một tài khoản" in content
                    or (
                        ("Chào mừng trở lại" in content or "Welcome back" in content)
                        and "Tiếp tục với Google" not in content
                        and "Continue with Google" not in content
                    )
                ):
                    await _pick_account_or_other(
                        page, req.email or "", where="openai-chooser"
                    )
                    await asyncio.sleep(2.0)
                    continue

                # Codex consent after existing-account tile OR after Google login:
                # /sign-in-with-chatgpt/codex/consent → email pill + Hủy + Tiếp tục
                # → click Tiếp tục → localhost:1455/auth/callback?code=... (same capture)
                try:
                    is_codex_consent = (
                        "/codex/consent" in url
                        or "sign-in-with-chatgpt" in url
                        or (
                            ("ChatGPT" in content or "Codex" in content)
                            and ("Hủy" in content or "Cancel" in content)
                        )
                    )
                    has_google = await page.locator(
                        'button:has-text("Google"), button:has-text("Tiếp tục với Google")'
                    ).count() > 0
                    has_email = await page.locator(
                        'input[type="email"], input[name="email"]'
                    ).count() > 0
                    if has_google and not google_btn_clicked and not is_codex_consent:
                        if await _click_google_btn(page):
                            google_btn_clicked = True
                            await asyncio.sleep(3.0)
                            continue
                    cont = page.locator(
                        'button:has-text("Tiếp tục"), button:has-text("Continue"), '
                        'button[value="accept"], button:has-text("Allow"), '
                        'button:has-text("Authorize"), button:has-text("Đồng ý")'
                    )
                    if (
                        await cont.count() > 0
                        and not has_email
                        and "choose-an-account" not in url
                        and "log-in-or-create" not in url
                        and (is_codex_consent or not has_google)
                    ):
                        # Prefer black primary "Tiếp tục" (not Hủy)
                        primary = page.locator(
                            'button:has-text("Tiếp tục"), button:has-text("Continue")'
                        )
                        btn = primary.last if await primary.count() > 0 else cont.last
                        label = ""
                        try:
                            label = (await btn.inner_text()).strip()
                        except Exception:
                            pass
                        if "Tạo tài khoản" in label or "Google" in label:
                            pass
                        else:
                            logger.info(
                                "codex-g: consent Tiếp tục (%r) url=%s",
                                label or "primary",
                                url[:100],
                            )
                            await btn.click(force=True, timeout=3000)
                            await asyncio.sleep(2.5)
                            for _ in range(15):
                                if captured:
                                    break
                                await asyncio.sleep(0.4)
                except Exception:
                    pass

            await asyncio.sleep(1.2)

        # 3) Chờ callback localhost (ERR_CONNECTION_REFUSED nên bắt ở request)
        deadline = time.time() + 15
        while time.time() < deadline and not captured:
            await asyncio.sleep(0.5)

        if not captured:
            cur = ""
            try:
                cur = page.url
            except Exception:
                pass
            return {"state": "failed", "error": f"no callback; stuck at {cur[:120]}"}

        return {"state": "success", "redirect_url": captured[0]}
    except Exception as e:
        logger.exception("codex google onboard error")
        return {"state": "failed", "error": str(e)[:200]}
