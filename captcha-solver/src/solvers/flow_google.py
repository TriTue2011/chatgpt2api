"""Google Labs Flow image generator.

End-to-end: open https://labs.google/fx/vi/tools/flow/project/<id> with the
persistent "google-fx" profile (must be logged in to a Google account), let
the React app initialise, harvest the ya29 OAuth bearer token from the
first outbound googleapis.com request, ask the page's own grecaptcha
runtime for a fresh reCAPTCHA Enterprise token, then POST to
aisandbox-pa.googleapis.com from INSIDE the browser context so Chrome
attaches its proprietary x-browser-validation / x-client-data headers.

Setup is a one-time noVNC login:
  POST /v1/session/manual-login {"profile":"google-fx","url":"https://labs.google/fx/vi/tools/flow"}
After that this function works headlessly until the Google session cookie
naturally expires (typically months).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from ..browser_pool import pool

logger = logging.getLogger(__name__)


# Defaults — strongest model (Nano Banana Pro), 16:9 landscape, 1 image per
# request. Override per-call by passing model / aspect_ratio / count.
DEFAULT_MODEL = "NANO_BANANA_PRO"
DEFAULT_TOOL = "PINHOLE"
DEFAULT_ASPECT = "IMAGE_ASPECT_RATIO_LANDSCAPE"
DEFAULT_COUNT = 1
API_HOST = "https://aisandbox-pa.googleapis.com"

# Aspect ratio labels in the Flow UI dropdown (Vietnamese locale).
_ASPECT_LABELS = {
    "IMAGE_ASPECT_RATIO_LANDSCAPE":      "16:9",
    "IMAGE_ASPECT_RATIO_LANDSCAPE_4_3":  "4:3",
    "IMAGE_ASPECT_RATIO_SQUARE":         "1:1",
    "IMAGE_ASPECT_RATIO_PORTRAIT_3_4":   "3:4",
    "IMAGE_ASPECT_RATIO_PORTRAIT":       "9:16",
}

# Flow UI model labels (matches the dropdown text in the screenshot).
# IMPORTANT: Flow's API uses IMAGEN_3_5 internally even though the UI
# shows "Imagen 4" — the user's captured request body confirmed this.
_MODEL_LABELS = {
    "NANO_BANANA_PRO": "Nano Banana Pro",
    "NARWHAL":         "Nano Banana 2",
    "IMAGEN_3_5":      "Imagen 4",
    "IMAGEN_4":        "Imagen 4",  # back-compat alias
}

# When the request interceptor overrides imageModelName, map our friendly
# constants to the actual Flow API enum values. IMAGEN_4 isn't recognized
# by the Flow API — it must be IMAGEN_3_5.
_MODEL_API_VALUE = {
    "NANO_BANANA_PRO": "NANO_BANANA_PRO",
    "NARWHAL":         "NARWHAL",
    "IMAGEN_4":        "IMAGEN_3_5",   # UI alias → real API value
    "IMAGEN_3_5":      "IMAGEN_3_5",
}


def _fingerprint(image_url_obj: dict) -> str:
    """Stable identifier for a returned image so callers can dedupe."""
    for key in ("imageId", "mediaId", "id"):
        v = image_url_obj.get(key)
        if isinstance(v, str) and v:
            return v
    return str(image_url_obj)[:80]


def _extract_image_refs(payload: Any) -> list[dict]:
    """Walk the Flow API response and pull out every "image-like" record.

    Flow's batchGenerateImages response shape (Dec 2026):
        {"media": [
            {"name": "<media-id>", "image": {"generatedImage": {
                "fifeUrl": "https://flow-content.google/image/...",
                "mediaGenerationId": "...", "seed": 12345,
                "aspectRatio": "...", "modelNameType": "NARWHAL", ...
            }}}
        ]}
    We accept any dict that exposes one of the known URL fields or raw bytes.
    """
    out: list[dict] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            url = (
                node.get("fifeUrl")        # primary CDN URL for Flow images
                or node.get("mediaUrl")
                or node.get("imageUrl")
                or node.get("gcsUri")
                or node.get("publicUrl")
                or node.get("url")
            )
            data = node.get("encodedImage") or node.get("imageBytes") or node.get("bytes")
            if url or data:
                out.append({
                    "url": url,
                    "data": data,
                    "mime": node.get("mimeType") or node.get("contentType") or "image/png",
                    "id": node.get("mediaGenerationId") or _fingerprint(node),
                    "seed": node.get("seed"),
                    "model": node.get("modelNameType"),
                    "aspect": node.get("aspectRatio"),
                    "prompt": node.get("prompt"),
                })
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(payload)
    return out


async def _capture_bearer(page, timeout_s: float = 25.0) -> str:
    """Observe outgoing requests and grab the first ya29 OAuth bearer."""
    captured: dict[str, str] = {}

    def _on_request(request) -> None:
        if captured.get("token"):
            return
        try:
            auth = (request.headers.get("authorization") or "").strip()
        except Exception:
            return
        if auth.startswith("Bearer ya29."):
            captured["token"] = auth[len("Bearer "):]
            logger.info(
                "captured ya29 bearer len=%d via %s",
                len(captured["token"]),
                request.url[:80],
            )

    page.on("request", _on_request)

    deadline = time.time() + timeout_s
    # Nudge the page to issue auth-bearing calls if it hasn't already.
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    while time.time() < deadline:
        if captured.get("token"):
            return captured["token"]
        await asyncio.sleep(0.4)

    raise RuntimeError(
        "Could not capture ya29 token. Profile likely not logged in. "
        "Run POST /v1/session/manual-login with profile='google-fx' and "
        "sign in via the noVNC URL, then retry."
    )


async def _get_recaptcha_token(page, action: str = "flow_generate") -> tuple[str, str]:
    """Call grecaptcha.enterprise.execute() on the page; return (token, sitekey).

    The Flow app loads grecaptcha lazily via a script tag with
    ?render=<sitekey>. If the script hasn't auto-loaded yet, we inject the
    script ourselves so we don't have to wait for the React app to trigger
    the load on its own.
    """
    info = await page.evaluate(
        """async (action) => {
            // Locate sitekey from any of the standard places.
            const findSitekey = () => {
                const el = document.querySelector('[data-sitekey]');
                if (el) return el.getAttribute('data-sitekey');
                for (const s of document.querySelectorAll('script[src*="recaptcha"]')) {
                    const m = s.src.match(/render=([^&]+)/);
                    if (m) return m[1];
                }
                if (window.___grecaptcha_cfg?.clients?.[0]?.K?.K?.sitekey) {
                    return window.___grecaptcha_cfg.clients[0].K.K.sitekey;
                }
                return null;
            };
            const sitekey = findSitekey();
            if (!sitekey) return {error: "sitekey not on page"};

            // If grecaptcha isn't loaded yet, inject the script explicitly.
            if (!window.grecaptcha?.enterprise?.execute) {
                if (!document.querySelector('script[data-cs-injected]')) {
                    const sc = document.createElement('script');
                    sc.src = 'https://www.google.com/recaptcha/enterprise.js?render=' + sitekey;
                    sc.async = true;
                    sc.defer = true;
                    sc.dataset.csInjected = '1';
                    document.head.appendChild(sc);
                }
                // Wait up to 30 s for the runtime to register.
                for (let i = 0; i < 150; i++) {
                    if (window.grecaptcha?.enterprise?.execute) break;
                    await new Promise(r => setTimeout(r, 200));
                }
            }
            if (!window.grecaptcha?.enterprise?.execute) {
                return {error: "grecaptcha.enterprise.execute never registered", sitekey};
            }

            // grecaptcha.enterprise has its own ready() callback that must
            // resolve before execute() will work. Promisify it.
            await new Promise(r => grecaptcha.enterprise.ready(r));

            try {
                const token = await grecaptcha.enterprise.execute(sitekey, { action });
                return {token, sitekey};
            } catch (e) {
                return {error: String(e?.message || e), sitekey};
            }
        }""",
        action,
    )
    if not isinstance(info, dict) or info.get("error"):
        raise RuntimeError(f"reCAPTCHA execute failed: {info}")
    token = info.get("token")
    sitekey = info.get("sitekey", "")
    if not token:
        raise RuntimeError(f"reCAPTCHA returned empty token: {info}")
    return token, sitekey


async def _set_dropdown(page, label_text: str, log_what: str) -> bool:
    """Robust selection for Google Flow UI (Tablist or Dropdown Menu)."""
    if not label_text:
        return False
        
    try:
        # 1. Thử tìm và click trực tiếp nếu element đã hiển thị sẵn (ví dụ: nút aspect ratio hoặc menu đã mở)
        locs = page.locator(f"text='{label_text}'")
        count = await locs.count()
        
        clicked = False
        for i in range(count - 1, -1, -1):
            el = locs.nth(i)
            if await el.is_visible():
                box = await el.bounding_box()
                if box:
                    await page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                    clicked = True
                    await asyncio.sleep(0.5)
                    break
                    
        # Nếu không thấy (vì menu đang đóng), tìm nút Trigger để mở menu
        if not clicked:
            trigger_box = await page.evaluate("""([txt, lbl]) => {
                const btns = Array.from(document.querySelectorAll('button, div[role="button"]'));
                let keywords = [];
                if (lbl === 'model') keywords = ['nano', 'banana', 'imagen', 'pro'];
                else if (lbl === 'aspect') keywords = ['16:9', '9:16', '1:1', 'portrait', 'landscape', 'square', '4:3', '3:4'];
                else if (lbl === 'count') keywords = ['1x', 'x1', '2x', 'x2', '3x', '4x'];
                else keywords = [txt];
                
                let trigger = btns.find(b => {
                    const bt = (b.textContent || '').toLowerCase().trim();
                    return keywords.some(k => bt.includes(k));
                });
                if (trigger) {
                    const r = trigger.getBoundingClientRect();
                    return {x: r.x + r.width/2, y: r.y + r.height/2};
                }
                return null;
            }""", [label_text.lower(), log_what])
            
            if trigger_box:
                await page.mouse.click(trigger_box['x'], trigger_box['y'])
                await asyncio.sleep(1.5) # Đợi React render xong menu
            else:
                logger.warning("flow_dropdown_skip %s=%s (Trigger not found)", log_what, label_text)
                return False
        
        # Sau khi click trigger (hoặc click lần 1), kiểm tra xem nó có mở ra một dropdown list không
        await asyncio.sleep(0.5)
        locs = page.locator(f"text='{label_text}'")
        count = await locs.count()
        
        # Thường option trong menu sẽ là phần tử cuối cùng hiển thị trên màn hình
        for i in range(count - 1, -1, -1):
            el = locs.nth(i)
            if await el.is_visible():
                # Kiểm tra xem đây có phải trigger không
                is_trigger = await el.evaluate("(node) => { return node.hasAttribute('aria-haspopup') || node.hasAttribute('aria-expanded'); }")
                if not is_trigger:
                    box = await el.bounding_box()
                    if box:
                        await page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                        logger.info("flow_dropdown_set %s=%s (Physical Option Click)", log_what, label_text)
                        await asyncio.sleep(0.5)
                        return True
                        
        logger.info("flow_dropdown_set %s=%s (Physical Trigger Click/Direct Toggle)", log_what, label_text)
        return True

    except Exception as e:
        logger.warning("flow_dropdown error: %s", e)

    return False


async def _humanize(page, moves: int = 7) -> None:
    """Emit human-like mouse movement + scroll + dwell so reCAPTCHA Enterprise
    v3 sees genuine interaction signals before grecaptcha.execute().

    Synthetic/no cursor movement (overly fast, perfectly straight, or absent)
    is a known score-lowering signal; real curved movement at human pace with
    pauses and a little scrolling raises the score. Best-effort, never raises.
    """
    import random as _r
    try:
        w, h = 1366, 768
        try:
            vp = page.viewport_size or {}
            w, h = vp.get("width", w), vp.get("height", h)
        except Exception:
            pass
        x, y = _r.randint(60, w - 60), _r.randint(90, h - 90)
        for _ in range(moves):
            nx = max(5, min(w - 5, x + _r.randint(-260, 260)))
            ny = max(5, min(h - 5, y + _r.randint(-190, 190)))
            # steps>1 makes Playwright interpolate → smooth, curved-ish path
            await page.mouse.move(nx, ny, steps=_r.randint(10, 28))
            x, y = nx, ny
            await asyncio.sleep(_r.uniform(0.15, 0.55))
            if _r.random() < 0.45:
                try:
                    await page.mouse.wheel(0, _r.randint(-280, 420))
                except Exception:
                    pass
                await asyncio.sleep(_r.uniform(0.2, 0.5))
        # final "reading" dwell — reCAPTCHA scores time-on-page positively
        await asyncio.sleep(_r.uniform(1.8, 3.2))
    except Exception as _exc:
        logger.warning("flow_humanize_failed: %s", _exc)


async def generate_image(
    project_id: str,
    prompt: str,
    aspect_ratio: str = DEFAULT_ASPECT,
    model: str = DEFAULT_MODEL,
    count: int = DEFAULT_COUNT,
    tool: str = DEFAULT_TOOL,
    profile: str = "google-fx",
    headless: bool = True,
    timeout: int = 90,
) -> dict:
    """Run the full Flow batchGenerateImages flow and return image refs.

    Args:
        count: 1-4. Flow's UI supports 1x/2x/3x/4x. We best-effort drive
            the dropdown; if Flow stored a different default on the project
            you may get a different number back.

    Returns:
        {
          "images": [{"url"|"data": ..., "mime": ..., "id": ...}, ...],
          "raw":    <full API response>,
          "elapsed_ms": int,
          "model": str,
        }
    """
    count = max(1, min(4, int(count or 1)))
    started = time.time()
    flow_url = f"https://labs.google/fx/vi/tools/flow/project/{project_id}"
    api_url = f"{API_HOST}/v1/projects/{project_id}/flowMedia:batchGenerateImages"

    async with pool.page(profile=profile, headless=headless) as page:
        # TRICK 1: Tẩy sạch cookie & storage đánh dấu Bot của reCAPTCHA (Surgical remove để giữ login)
        try:
            await page.goto("https://labs.google/fx", wait_until="domcontentloaded", timeout=15000)
            await page.evaluate("""() => {
                const keys = [];
                for (let i = 0; i < window.localStorage.length; i++) {
                    const k = window.localStorage.key(i);
                    if (k && (k.includes('recaptcha') || k.includes('grecaptcha') || k.startsWith('rc::'))) keys.push(k);
                }
                keys.forEach(k => window.localStorage.removeItem(k));
                
                const sk = [];
                for (let i = 0; i < window.sessionStorage.length; i++) {
                    const k = window.sessionStorage.key(i);
                    if (k && (k.includes('recaptcha') || k.includes('grecaptcha') || k.startsWith('rc::'))) sk.push(k);
                }
                sk.forEach(k => window.sessionStorage.removeItem(k));
                
                document.cookie.split(';').forEach(c => {
                    let name = c.split('=')[0].trim();
                    if(name.includes('grecaptcha') || name.startsWith('_ga') || name.includes('recaptcha')) {
                        document.cookie = name + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/';
                        document.cookie = name + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=.google.com';
                        document.cookie = name + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=.labs.google';
                    }
                });
            }""")
            logger.info("flow_stealth: surgically cleared reCAPTCHA cache")
        except Exception as exc:
            logger.debug("flow_stealth_clear_failed: %s", exc)

        await _prime_flow_session(page)
        await page.goto(flow_url, wait_until="domcontentloaded", timeout=30_000)

        # Flow renders the prompt input as a contenteditable DIV (not a
        # textarea — the only textarea on the page is the hidden
        # g-recaptcha-response shadow input). Wait for a sizeable
        # contenteditable to appear.
        try:
            await page.wait_for_function(
                """() => {
                    const ces = Array.from(document.querySelectorAll('[contenteditable=\"true\"]'));
                    return ces.some(e => e.offsetWidth > 200 && e.offsetHeight > 0);
                }""",
                timeout=60_000,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Flow UI never hydrated (timeout). Profile may be logged out. "
                f"Re-run /v1/session/manual-login with profile='{profile}'. ({exc})"
            ) from exc

        # ── Step 0: Remove the welcome dialog OVERLAY layer FIRST.
        # On freshly-created projects, Flow renders a Radix dialog with:
        #   • An overlay <div data-state="open"> (no role, viewport-sized)
        #     that intercepts ALL mouse events.
        #   • A dialog <div role="dialog"> with the actual content.
        # Removing just the overlay (not the dialog) lets mouse events
        # reach the workspace BELOW (where the prompt input lives at
        # y≈658, well below the dialog box).
        #
        # Why remove overlay early (not just before submit click):
        # Slate.js (the prompt editor) requires a REAL mouse click to
        # activate before keyboard events register in its React state.
        # JS .focus() + page.keyboard.type fires DOM key events, but
        # Slate ignores them — the submit button stays aria-disabled=true
        # because Slate state shows empty prompt. We confirmed this via
        # probe: after JS focus + execCommand insertText, ce_text had
        # our text in DOM but submit_aria_disabled was still 'true'.
        await page.evaluate("""
            () => {
                document.querySelectorAll('[data-state="open"]').forEach(el => {
                    if (el.getAttribute('role')) return;  // keep dialog content
                    const r = el.getBoundingClientRect();
                    if (r.width >= window.innerWidth * 0.8 && r.height >= window.innerHeight * 0.8) {
                        el.remove();
                    }
                });
            }
        """)
        await asyncio.sleep(0.3)

        # ── Step 1: Real mouse click on the prompt input to activate
        # Slate. Now that overlay is gone, the click reaches the editor.
        focused = await page.evaluate("""
            () => {
                const ces = Array.from(document.querySelectorAll('[contenteditable=true]'));
                // pick the largest visible contenteditable (the prompt input)
                const target = ces
                    .map(e => ({e, w: e.offsetWidth, h: e.offsetHeight}))
                    .filter(x => x.w > 200 && x.h > 0)
                    .sort((a, b) => (b.w * b.h) - (a.w * a.h))[0];
                if (!target) {
                    return {
                        found: false,
                        debug_ce_count: ces.length,
                        debug_dims: ces.map(e => ({w: e.offsetWidth, h: e.offsetHeight, role: e.getAttribute('role')})),
                    };
                }
                target.e.focus();
                // Place caret at end (so subsequent keys append)
                const sel = window.getSelection();
                const range = document.createRange();
                range.selectNodeContents(target.e);
                range.collapse(false);
                sel.removeAllRanges();
                sel.addRange(range);
                return {found: true, w: target.w, h: target.h};
            }
        """)
        if not focused.get("found"):
            raise RuntimeError(
                f"Could not find/focus prompt contenteditable. "
                f"ce_count={focused.get('debug_ce_count')} "
                f"dims={focused.get('debug_dims')}"
            )
        logger.info("flow_prompt_focused w=%d h=%d", focused.get("w", 0), focused.get("h", 0))

        # Real mouse click on the prompt — Slate needs this to activate
        # its React event handlers. After this, keyboard.type populates
        # Slate's state correctly and the submit button un-disables.
        try:
            prompt_locator = page.locator("[contenteditable='true']").first
            await prompt_locator.click(timeout=5000)
            logger.info("flow_prompt_mouse_clicked")
        except Exception as exc:
            logger.warning("flow_prompt mouse click failed: %s — keys may go to wrong target", str(exc)[:100])

        # Inject the prompt via InputEvent('beforeinput'). Slate.js (the
        # editor Flow uses) listens for beforeinput specifically —
        # page.keyboard.type fires raw keydown/keypress/keyup which the
        # browser CDP delivers, but Slate's React handlers don't pick
        # those up. So the typed text appeared in the DOM but Slate's
        # internal state stayed empty and the submit button stayed
        # aria-disabled="true". Confirmed by v13 probe.
        await page.evaluate(
            """
            (text) => {
                const ce = document.querySelector('[contenteditable=true]');
                if (!ce) return false;
                ce.focus();
                const e1 = new InputEvent('beforeinput', {
                    inputType: 'insertText',
                    data: text,
                    bubbles: true,
                    cancelable: true,
                });
                ce.dispatchEvent(e1);
                // If beforeinput wasn't preventDefault'd, fire input too.
                const e2 = new InputEvent('input', {
                    inputType: 'insertText',
                    data: text,
                    bubbles: true,
                    cancelable: true,
                });
                ce.dispatchEvent(e2);
                return true;
            }
            """,
            prompt,
        )
        await asyncio.sleep(0.5)

        # Verify Slate accepted the prompt (submit un-disables when the
        # editor has non-empty content).
        submit_state = await page.evaluate("""
            () => {
                const buttons = Array.from(document.querySelectorAll('button'));
                const submit = buttons.find(b => /arrow_forward[\\s\\n]+(Tạo|Generate|Create|Send|Submit)/i.test(b.innerText||''));
                if (submit && submit.getAttribute('aria-disabled') !== 'true') submit.click(); return submit ? submit.getAttribute('aria-disabled') : 'no-submit';
            }
        """)
        logger.info("flow_prompt_injected submit_aria_disabled=%s", submit_state)
        if submit_state == "true":
            raise RuntimeError(
                "Slate did not accept the prompt — submit button stayed "
                "aria-disabled=true after InputEvent dispatch"
            )

        # 2) Set model / aspect / count via Flow's UI pill buttons BEFORE
        # clicking submit. This replaces the old request-interception path
        # because page.route() hangs in CloakBrowser (CDP Fetch.enable
        # never returns). DOM-driven settings are less robust against Flow
        # UI reskins, but they avoid the CDP hang entirely.
        api_patterns = ["flowMedia:batchGenerateImages", "flowCreationAgent:streamChat"]

        _ASPECT_LABEL = {
            "IMAGE_ASPECT_RATIO_LANDSCAPE": "16:9",
            "IMAGE_ASPECT_RATIO_LANDSCAPE_4_3": "4:3",
            "IMAGE_ASPECT_RATIO_SQUARE": "1:1",
            "IMAGE_ASPECT_RATIO_PORTRAIT_3_4": "3:4",
            "IMAGE_ASPECT_RATIO_PORTRAIT": "9:16",
        }
        _MODEL_LABEL = {
            "NANO_BANANA_PRO": "Nano Banana Pro",
            "NANO_BANANA_2": "Nano Banana 2",
            "IMAGEN_4": "Imagen 4",
        }
        aspect_label = _ASPECT_LABEL.get(aspect_ratio, aspect_ratio)
        model_label = _MODEL_LABEL.get(model, model)
        
        # Open the settings menu if it's closed
        try:
            menu_btn = page.locator("button[aria-haspopup='menu']").first
            if await menu_btn.count() > 0 and await menu_btn.get_attribute("aria-expanded") == "false":
                await menu_btn.click(timeout=1500)
                await page.wait_for_timeout(500)
        except Exception as e:
            logger.debug("flow_menu_open skipped: %s", e)

        await _set_dropdown(page, aspect_label, "aspect")
        await _set_dropdown(page, model_label, "model")
        
        # New Google Flow UI count labels: 1x, x2, x3, x4
        count_label = "1x" if count == 1 else f"x{count}"
        await _set_dropdown(page, count_label, "count")
        
        # Close the settings menu to avoid intercepting other clicks
        try:
            if await menu_btn.count() > 0 and await menu_btn.get_attribute("aria-expanded") == "true":
                await menu_btn.click(timeout=1500)
        except Exception:
            pass

        logger.info("flow_dropdowns_done aspect=%s model=%s count=%d", aspect_label, model_label, count)

        # 2.5) reCAPTCHA token helper — re-fetched FRESH on every submit attempt.
        # Enterprise score is borderline on a GPU-less server, and each token
        # rolls a new score, so the retry loop below calls this each try.
        async def _refresh_recaptcha() -> None:
            try:
                tok, sitekey = await _get_recaptcha_token(page, action="flow_generate")
                await page.evaluate(
                    """(token) => {
                        const ta = document.querySelector('textarea[name="g-recaptcha-response"]');
                        if (ta) { ta.value = token; return true; }
                        const ta2 = document.querySelector('textarea[id*="recaptcha" i]');
                        if (ta2) { ta2.value = token; return true; }
                        const ta3 = document.querySelector('#g-recaptcha-response');
                        if (ta3) { ta3.value = token; return true; }
                        return false;
                    }""",
                    tok,
                )
                logger.info("flow_recaptcha_ok token_preview=%s", tok[:25])
            except Exception as _exc:
                logger.warning("flow_recaptcha_failed: %s", _exc)

        # 3) Click the "Tạo" submit button. On fresh projects the welcome
        # dialog overlay intercepts mouse clicks, so JS .click() is more
        # reliable — it dispatches the synthetic event directly to the
        # element and bypasses the overlay entirely.
        async def _click_generate() -> None:
            logger.info("flow_click_generate_enter")
            # Overlay was already removed at the start, but re-do it in
            # case React re-rendered the welcome dialog overlay.
            try:
                await page.evaluate("""
                    () => {
                        document.querySelectorAll('[data-state="open"]').forEach(el => {
                            if (el.getAttribute('role')) return;
                            const r = el.getBoundingClientRect();
                            if (r.width >= window.innerWidth * 0.8 && r.height >= window.innerHeight * 0.8) {
                                el.remove();
                            }
                        });
                    }
                """)
            except Exception as _exc:
                logger.warning("flow_click_overlay_remove_failed: %s", _exc)
            await asyncio.sleep(0.2)
            logger.info("flow_click_overlay_done")

            # Step 2: Find the submit button — text "arrow_forward\\nTạo"
            # (Material icon name + label as two lines).
            submit_btn = page.locator(
                "button:has-text('arrow_forward'):has-text('Tạo'), "
                "button:has-text('arrow_forward'):has-text('Generate'), "
                "button:has-text('arrow_forward'):has-text('Create')"
            ).last
            logger.info("flow_click_submit_btn_count=%d", await submit_btn.count())
            try:
                await submit_btn.click(timeout=8000)
                logger.info("flow_submit_clicked via_locator")
                return
            except Exception as exc:
                logger.warning("flow_submit locator click failed: %s — trying JS dispatch", str(exc)[:120])

            # Step 3: Fallback — full PointerEvent + MouseEvent sequence via
            # JS. React's onClick handler needs pointerdown→pointerup→click
            # to fire reliably; a bare .click() sometimes doesn't trigger
            # the synthetic event.
            dispatched = await page.evaluate("""
                () => {
                    const buttons = Array.from(document.querySelectorAll('button'));
                    let btn = buttons.find(b => /arrow_forward[\\s\\n]+(Tạo|Generate|Create|Send|Submit)/i.test(b.innerText || ''));
                    if (!btn) btn = buttons.find(b => /arrow_(forward|upward)/i.test(b.innerText || ''));
                    if (!btn) {
                        const taoes = buttons.filter(b => /Tạo/.test(b.innerText||'') && !/add_2/.test(b.innerText||''));
                        btn = taoes[taoes.length - 1];
                    }
                    if (!btn) return {clicked: false};
                    const r = btn.getBoundingClientRect();
                    const x = r.left + r.width/2, y = r.top + r.height/2;
                    const opts = {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, view: window};
                    btn.dispatchEvent(new PointerEvent('pointerdown', opts));
                    btn.dispatchEvent(new MouseEvent('mousedown', opts));
                    btn.dispatchEvent(new PointerEvent('pointerup', opts));
                    btn.dispatchEvent(new MouseEvent('mouseup', opts));
                    btn.dispatchEvent(new MouseEvent('click', opts));
                    btn.click();
                    return {clicked: true, text: (btn.innerText || '').slice(0, 50).replace(/\\n/g, '|')};
                }
            """)
            if dispatched.get("clicked"):
                logger.info("flow_submit_clicked via_dispatch text=%s", dispatched.get("text"))
                return
            logger.warning("flow_submit: no button found, trying Ctrl+Enter")
            await page.keyboard.press("Control+Enter")

        async def _reprep() -> bool:
            """For a RETRY: re-navigate to the project + re-enter the prompt so a
            subsequent submit click fires a genuinely NEW flowMedia POST. A bare
            re-click after a rejected submit fires nothing (Slate is cleared /
            the button re-disables), so a fresh page load is required. Returns
            True if the prompt was accepted (submit enabled)."""
            try:
                await page.goto(flow_url, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_function(
                    "() => { const c = Array.from(document.querySelectorAll('[contenteditable=true]')); return c.some(e => e.offsetWidth > 200 && e.offsetHeight > 0); }",
                    timeout=45_000,
                )
            except Exception as exc:
                logger.warning("flow_prime: no /project/ redirect: %s", str(exc)[:120])
                if "accounts.google.com" in page.url:
                    raise RuntimeError(f"Flow UI never hydrated. Profile is logged out. URL: {page.url[:100]}") from exc
                return False
            try:
                await page.evaluate("""() => {
                    document.querySelectorAll('[data-state="open"]').forEach(el => {
                        if (el.getAttribute('role')) return;
                        const r = el.getBoundingClientRect();
                        if (r.width >= window.innerWidth * 0.8 && r.height >= window.innerHeight * 0.8) { el.remove(); }
                    });
                }""")
            except Exception:
                pass
            await asyncio.sleep(0.3)
            try:
                await page.evaluate("""
                    () => {
                        const ces = Array.from(document.querySelectorAll('[contenteditable=true]'));
                        const target = ces
                            .map(e => ({e, w: e.offsetWidth, h: e.offsetHeight}))
                            .filter(x => x.w > 200 && x.h > 0)
                            .sort((a, b) => (b.w * b.h) - (a.w * a.h))[0];
                        if (target) {
                            target.e.focus();
                            const sel = window.getSelection();
                            const range = document.createRange();
                            range.selectNodeContents(target.e);
                            range.collapse(false);
                            sel.removeAllRanges();
                            sel.addRange(range);
                        }
                    }
                """)
                await page.locator("[contenteditable='true']").first.click(timeout=5000)
            except Exception:
                pass
            await page.evaluate(
                """(text) => {
                    const ce = document.querySelector('[contenteditable=true]');
                    if (!ce) return false;
                    ce.focus();
                    const sel = window.getSelection();
                    const rng = document.createRange();
                    rng.selectNodeContents(ce);
                    sel.removeAllRanges();
                    sel.addRange(rng);
                    // clear any leftover text first so we don't append on retry
                    ce.dispatchEvent(new InputEvent('beforeinput', {inputType: 'deleteContentBackward', bubbles: true, cancelable: true}));
                    ce.dispatchEvent(new InputEvent('input', {inputType: 'deleteContentBackward', bubbles: true, cancelable: true}));
                    ce.dispatchEvent(new InputEvent('beforeinput', {inputType: 'insertText', data: text, bubbles: true, cancelable: true}));
                    ce.dispatchEvent(new InputEvent('input', {inputType: 'insertText', data: text, bubbles: true, cancelable: true}));
                    return true;
                }""",
                prompt,
            )
            await asyncio.sleep(0.5)
            state = await page.evaluate(
                """() => {
                    const b = Array.from(document.querySelectorAll('button')).find(b => /arrow_forward[\\s\\n]+(Tạo|Generate|Create|Send|Submit)/i.test(b.innerText || ''));
                    return b ? b.getAttribute('aria-disabled') : 'no-submit';
                }"""
            )
            logger.info("flow_reprep submit_aria_disabled=%s", state)
            return state != "true"

        # 4) Submit with reCAPTCHA retry, bounded by a WALL-CLOCK budget so the
        # call always returns before the caller's HTTP timeout (no hangs). The
        # score is borderline on a GPU-less server, so: humanize ONCE up front
        # (the interaction history persists for the page session and benefits
        # every subsequent execute()), then retry cheaply with a fresh token
        # until one passes or the budget runs out. We stop launching new
        # attempts once too little time remains for a winning attempt (~45s to
        # generate) so a success is never cut off mid-flight.
        _budget = max(90, timeout - 15)   # seconds for the whole retry phase
        _deadline = started + _budget
        _GEN_RESERVE = 85                 # retry re-nav (~15s) + a successful POST (~60s)
        _per_try = 80
        response = None
        last_err = ""
        _attempt = 0
        images = []
        logger.info("flow_waiting_for_post budget_s=%d", _budget)
        # Heavy humanize once — the biggest controllable score signal.
        await _humanize(page, moves=8)
        while time.time() < _deadline:
            remaining = _deadline - time.time()
            if remaining < _GEN_RESERVE:
                logger.info("flow_budget_low remaining=%.0fs — stop (no room for a win)", remaining)
                break
            _attempt += 1
            if _attempt > 1:
                # A bare re-click after a reject fires NO new POST (Slate
                # cleared / submit re-disabled). Re-navigate + re-enter the
                # prompt to arm a genuinely fresh submit, then a light humanize.
                if not await _reprep():
                    last_err = "re-prep failed (prompt not accepted / nav failed)"
                    logger.warning("flow_reprep failed attempt=%d", _attempt)
                    await asyncio.sleep(1.0)
                    continue
                await _humanize(page, moves=4)
            await _refresh_recaptcha()
            try:
                logger.info("flow_submit attempt=%d budget_left=%.0fs", _attempt, _deadline - time.time())
                
                # Get baseline images to know when new ones arrive
                old_imgs = await page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('img')).map(img => img.src);
                }''')
                
                await _click_generate()
                
                # Wait for images to appear in the DOM
                logger.info("flow_waiting_for_dom_images")
                
                new_imgs = []
                wait_time = int(_deadline - time.time())
                for _ in range(max(1, wait_time // 2)):
                    await page.wait_for_timeout(2000)
                    curr_imgs = await page.evaluate('''() => {
                        return Array.from(document.querySelectorAll('img')).map(img => img.src);
                    }''')
                    diff = set(curr_imgs) - set(old_imgs)
                    # Ignore avatars, google icons, and svgs
                    diff = {src for src in diff if '/a/' not in src and 'avatar' not in src and not src.endswith('.svg') and 'gstatic.com' not in src}
                    if diff:
                        new_imgs = list(diff)
                        break
                    # Upstream error toast (daily limit / policy / generic fail)
                    # → no image will ever come; bail with the real reason
                    # instead of burning the rest of the budget in silence.
                    try:
                        toast = await page.evaluate('''() => {
                            const sel = '[role="alert"], [class*="toast"], [class*="Toast"], [class*="snackbar"]';
                            return Array.from(document.querySelectorAll(sel))
                                .map(e => (e.innerText || "").trim()).filter(Boolean).join(" | ");
                        }''')
                    except Exception:
                        toast = ""
                    if toast:
                        low_t = toast.lower()
                        if any(k in low_t for k in ("limit", "quota", "error", "fail", "can't", "cannot", "unable", "wrong")):
                            last_err = f"Flow UI error: {toast[:250]}"
                            logger.warning("flow_error_toast attempt=%d: %s", _attempt, toast[:200])
                            break
                
                if new_imgs:
                    images = []
                    for src in new_imgs:
                        # Convert both blob: and normal URLs to base64 within the browser context
                        # to avoid httpx 400 Bad Request errors for protected internal URLs
                        b64 = await page.evaluate('''async (url) => {
                            const response = await fetch(url);
                            const blob = await response.blob();
                            return new Promise((resolve, reject) => {
                                const reader = new FileReader();
                                reader.onloadend = () => resolve(reader.result);
                                reader.onerror = reject;
                                reader.readAsDataURL(blob);
                            });
                        }''', src)
                        images.append({"url": b64, "mime": "image/jpeg"})
                    logger.info("flow_extracted_images count=%d", len(images))
                    break
                    
            except Exception as exc:
                last_err = f"DOM extraction failed: {exc}"
                logger.warning("flow_dom_extract attempt=%d failed: %s", _attempt, str(exc)[:120])
                
                # Check if it was a reCAPTCHA error or daily limit
                body_text = await page.content()
                low = body_text.lower()
                is_recaptcha = "recaptcha" in low or "unusual" in low or "permission" in low
                if is_recaptcha:
                    logger.warning("flow_recaptcha_reject attempt=%d — retry fresh token", _attempt)
                    await asyncio.sleep(1.2)
                    continue
                    
                await asyncio.sleep(1.0)
                continue

    if not images:
        if not last_err:
            # No exception and no error toast — capture what the page actually
            # shows so the failure is diagnosable instead of an empty reason.
            try:
                snippet = await page.evaluate(
                    "() => (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 300)")
                last_err = f"no new images in DOM; page says: {snippet}"
            except Exception:
                last_err = "no new images in DOM (page text unavailable)"
        raise RuntimeError(
            f"Flow generate failed after {_attempt} attempts within {_budget}s budget: {last_err}"
        )

    return {
        "images": images,
        "raw": {"extracted_from_dom": True},
        "elapsed_ms": int((time.time() - started) * 1000),
        "model": model,
        "cookies": await page.context.cookies(),
    }


async def _prime_flow_session(page) -> None:
    """Prime the Flow session so subsequent project URLs render the app
    (not the marketing landing page).

    Without this, navigating straight to /tools/flow/project/<id> on a
    just-launched Chrome — even with valid Google login cookies — shows
    Google's marketing CTA page. The session has to be "warmed" by
    visiting /tools/flow root AND clicking through it.

    Empirically verified: passive wait on /tools/flow (even 100s+)
    NEVER converts the marketing landing to the app. The user MUST click
    "Create with Google Flow" to fire Google's entitlement check, which
    then redirects to /project/<auto-uuid> and primes the session for
    all subsequent /project/<id> navigations on the same context.
    """
    async def _auto_handle_google_oauth(pg):
        if "accounts.google.com" not in pg.url:
            return
        logger.info("flow_prime: on Google OAuth (%s), attempting auto select/consent...", pg.url[:80])
        try:
            clicked = await pg.evaluate("""() => {
                const acc = document.querySelector('[data-identifier], [data-email], ul li[data-item-index], div[role="link"]');
                if (acc) {
                    acc.click();
                    return 'account_tile';
                }
                const btns = Array.from(document.querySelectorAll('button'));
                const cont = btns.find(b => /continue|tiếp tục|cho phép|allow|agree|đồng ý/i.test(b.innerText || ''));
                if (cont) {
                    cont.click();
                    return 'consent_button';
                }
                return null;
            }""")
            if clicked:
                logger.info("flow_prime: auto oauth handled via %s", clicked)
                await asyncio.sleep(3.0)
        except Exception as exc:
            logger.warning("flow_prime: auto oauth failed: %s", exc)

    try:
        await page.goto(
            "https://labs.google/fx/vi/tools/flow",
            wait_until="domcontentloaded",
            timeout=20_000,
        )
        await asyncio.sleep(1.0)
        await _auto_handle_google_oauth(page)
    except Exception as exc:
        logger.warning("flow_prime: goto root failed: %s", exc)
        return

    # Did the actual app load? (PRO badge, Dự án mới, edit project buttons)
    try:
        await page.wait_for_function(
            """() => {
                const els = Array.from(document.querySelectorAll('button,a'));
                return els.some(e => {
                    const t = (e.innerText || e.getAttribute('aria-label') || '').trim();
                    return /^pro$|dự án mới|new project|add_2|chỉnh sửa dự án/i.test(t);
                });
            }""",
            timeout=10_000,
        )
        logger.info("flow_prime: already primed (app shell visible)")
        return
    except Exception:
        pass  # marketing landing — force entitlement check

    # Click "Create with Google Flow" via Playwright locator
    try:
        btn = page.locator(
            'button:has-text("Create with Google Flow"), '
            'button:has-text("Tạo bằng Google Flow")'
        ).first
        if await btn.count() == 0:
            logger.warning("flow_prime: marketing button not found")
            return
        await btn.scroll_into_view_if_needed(timeout=3_000)
        await btn.click(timeout=5_000)
        logger.info("flow_prime: clicked 'Create with Google Flow'")
    except Exception as exc:
        logger.warning("flow_prime: click failed: %s", exc)
        return

    # Wait for redirect to /project/<uuid>
    try:
        await page.wait_for_url("**/project/*", timeout=6_000)
        logger.info("flow_prime: redirected to %s", page.url)
    except Exception as exc:
        logger.info("flow_prime: no immediate /project/ redirect after 6s")
        await _auto_handle_google_oauth(page)


async def get_or_create_project(
    profile: str,
    headless: bool = False,
    timeout: int = 90,
) -> dict[str, Any]:
    """Return the UUID of a Flow project the logged-in account owns,
    creating a fresh one if none exist. The profile MUST already be
    logged in (typically via /v1/session/auto-login or manual noVNC).

    Returns:
        {
          "project_id": "<uuid>",
          "action": "use_existing" | "created",
          "project_count": int,
          "elapsed_ms": int,
        }
    """
    started = time.time()
    async with pool.page(profile=profile, headless=headless) as page:
        # Prime session — handles the marketing-landing detour itself.
        await _prime_flow_session(page)

        # If priming clicked "Create with Google Flow", we may already be
        # on /project/<auto-uuid>. Grab that UUID — it's a perfectly
        # usable existing project.
        import re
        cur = page.url
        m = re.search(r"/project/([0-9a-f-]+)", cur, re.I)
        if m:
            return {
                "project_id": m.group(1),
                "action": "created",  # via warmup click
                "project_count": 0,
                "elapsed_ms": int((time.time() - started) * 1000),
            }

        # Otherwise look for existing project links on /tools/flow root.
        result = await page.evaluate(
            """() => {
                const links = Array.from(document.querySelectorAll('a[href*="/project/"]'))
                    .map(a => (a.href.match(/\\/project\\/([0-9a-f-]+)/i) || [])[1])
                    .filter(Boolean);
                return {existing: links};
            }"""
        )
        existing = result.get("existing", [])
        if existing:
            return {
                "project_id": existing[0],
                "action": "use_existing",
                "project_count": len(existing),
                "elapsed_ms": int((time.time() - started) * 1000),
            }

        # No projects — click "Dự án mới" / "New project" button.
        clicked = await page.evaluate(
            """() => {
                const btn = Array.from(document.querySelectorAll('button')).find(
                    b => /add_2|dự án mới|new project/i.test(
                      b.innerText || b.getAttribute('aria-label') || ''
                    )
                );
                if (!btn) return false;
                btn.click();
                return true;
            }"""
        )
        if not clicked:
            # Fallback 1: wait 5s and retry (page may still be hydrating)
            logger.warning("get_or_create_project: 'New project' button not found, waiting 5s and retrying...")
            await asyncio.sleep(5)
            clicked = await page.evaluate(
                """() => {
                    const btn = Array.from(document.querySelectorAll('button')).find(
                        b => /add_2|dự án mới|new project|create|tạo/i.test(
                          b.innerText || b.getAttribute('aria-label') || ''
                        )
                    );
                    if (!btn) return false;
                    btn.click();
                    return true;
                }"""
            )
        if not clicked:
            # Fallback 2: re-prime session (clears marketing landing) then retry
            logger.warning("get_or_create_project: still not found, re-priming session...")
            await _prime_flow_session(page)
            cur2 = page.url
            m2 = re.search(r"/project/([0-9a-f-]+)", cur2, re.I)
            if m2:
                return {
                    "project_id": m2.group(1),
                    "action": "created",
                    "project_count": 0,
                    "elapsed_ms": int((time.time() - started) * 1000),
                }
            clicked = await page.evaluate(
                """() => {
                    const btn = Array.from(document.querySelectorAll('button')).find(
                        b => /add_2|dự án mới|new project/i.test(
                          b.innerText || b.getAttribute('aria-label') || ''
                        )
                    );
                    if (!btn) return false;
                    btn.click();
                    return true;
                }"""
            )
        if not clicked:
            raise RuntimeError(
                f"Could not find 'Dự án mới' / 'New project' button (page: {page.url[:120]}). "
                "Account may not have Flow access or session is expired."
            )



        try:
            await page.wait_for_url("**/project/*", timeout=20_000)
        except Exception as exc:
            raise RuntimeError(
                f"New-project click did not redirect to /project/<uuid> ({exc})"
            ) from exc

        import re
        m = re.search(r"/project/([0-9a-f-]+)", page.url, re.I)
        if not m:
            raise RuntimeError(f"Could not extract UUID from URL: {page.url}")
        return {
            "project_id": m.group(1),
            "action": "created",
            "project_count": 0,
            "elapsed_ms": int((time.time() - started) * 1000),
        }

async def flow_generate_video(
    project_id: str,
    prompt: str,
    aspect_ratio: str = "16:9",
    model: str = "flow/veo-3.1-lite",
    duration: str | None = None,
    count: int = 1,
    image_b64: str | None = None,
    last_frame_b64: str | None = None,
    profile: str = "google-fx",
    headless: bool = True,
    timeout: int = 300,
) -> dict:
    """Tạo video qua Google Flow:
    1. Đăng ký network interceptor TRƯỚC khi navigate (không miss response).
    2. Click UI "Tạo" để Google's own JS xử lý reCAPTCHA (bypass 403).
    3. Interceptor bắt op_name + bearer từ batchAsyncGenerateVideoText response.
    4. Poll batchCheckAsyncVideoGenerationStatus cho đến SUCCESSFUL.
    5. Lấy fifeUrl từ operations[0].operation.metadata.video.fifeUrl.
    """
    import json as _json, time, asyncio, re as _re
    started = time.time()

    model_name_map = {
        "flow/veo-3.1-lite":    "veo_3_1_t2v_lite",
        "veo-3.1-lite":         "veo_3_1_t2v_lite",
        "flow/veo-3.1-fast":    "veo_3_1_t2v_fast",
        "veo-3.1-fast":         "veo_3_1_t2v_fast",
        "flow/veo-3.1-quality": "veo_3_1_t2v_quality",
        "veo-3.1-quality":      "veo_3_1_t2v_quality",
        "flow/omni-flash":      "abra_t2v_10s",
        "omni-flash":           "abra_t2v_10s",
        "veo/veo-3.1-generate-preview": "veo_3_1_t2v_lite",
        "veo-3.1-generate-preview": "veo_3_1_t2v_lite",
    }
    is_portrait = aspect_ratio == "9:16"
    model_key = model_name_map.get(model, "veo_3_1_t2v_lite")
    if is_portrait and not model_key.endswith("_portrait"):
        model_key += "_portrait"
    aspect_label = "9:16" if is_portrait else "16:9"
    aspect_enum = "VIDEO_ASPECT_RATIO_PORTRAIT" if is_portrait else "VIDEO_ASPECT_RATIO_LANDSCAPE"

    async with pool.page(profile=profile, headless=headless) as page:
        # ── Interceptor đăng ký TRƯỚC mọi navigation ─────────────────────
        _cap: dict = {
            "bearer":    None,
            "op_name":   None,
            "op_scene":  None,
            "op_status": None,
            "media_name": None,
            "video_url": None,
        }

        async def _on_resp(resp):
            try:
                url = resp.url
                # Bắt bearer từ request header
                if "aisandbox-pa.googleapis.com" in url and not _cap["bearer"]:
                    ah = resp.request.headers.get("authorization", "")
                    if ah.startswith("Bearer "):
                        _cap["bearer"] = ah[7:]
                        logger.info("flow_video: bearer captured len=%d", len(_cap["bearer"]))

                # Bắt thông tin gen từ batchAsyncGenerateVideoText response
                if "batchAsyncGenerateVideoText" in url and resp.request.method == "POST":
                    try:
                        body = await resp.json()
                        if "remainingCredits" in body:
                            _cap["remaining_credits"] = body["remainingCredits"]
                            
                        # N8N format: operations[]
                        ops = body.get("operations", [])
                        if ops:
                            op = ops[0]
                            _cap["op_name"]   = op.get("operation", {}).get("name") or op.get("name")
                            _cap["op_scene"]  = op.get("sceneId", "")
                            _cap["op_status"] = op.get("status", "")
                            logger.info("flow_video: op_name=%s status=%s", _cap["op_name"], _cap["op_status"])
                        
                        # UI Web format: media[]
                        media_arr = body.get("media", [])
                        if media_arr:
                            _cap["media_name"] = media_arr[0].get("name")
                            logger.info("flow_video: media_name=%s", _cap["media_name"])
                    except Exception as e:
                        logger.warning("flow_video: parse gen response failed: %s", e)
                        
                # UI Load profile
                if "getUserProfile" in url:
                    try:
                        body = await resp.json()
                        if "remainingCredits" in body:
                            _cap["remaining_credits"] = body["remainingCredits"]
                    except Exception:
                        pass

                # Bắt fifeUrl nếu có sẵn
                if "batchCheckAsyncVideoGenerationStatus" in url or "aisandbox" in url or "media.poll" in url:
                    try:
                        text = await resp.text()
                        if "aisandbox" in url:
                            logger.info("--- FLOW API RESPONSE CAPTURE ---")
                            logger.info("URL: %s", url)
                            if len(text) < 2000:
                                logger.info("RESP: %s", text)
                            else:
                                logger.info("RESP (truncated): %s", text[:2000])
                            logger.info("-------------------------------------")

                        if "media.poll" in url and "MEDIA_URL_TYPE_MP4" in text or "gcsUri" in text or "fifeUrl" in text or "storage.googleapis.com" in text:
                            logger.info("flow_video: media.poll returned: %s", text[:800])
                            
                        m = _re.search(r'"fifeUrl"\s*:\s*"([^"]+)"', text)
                        if not m:
                            m = _re.search(r'"gcsUri"\s*:\s*"([^"]+)"', text)
                        if not m:
                            m = _re.search(r'"url"\s*:\s*"([^"]+\.mp4[^"]*)"', text)
                            
                        if m and not _cap["video_url"]:
                            _cap["video_url"] = m.group(1)
                            logger.info("flow_video: fifeUrl intercepted from %s", url)
                    except Exception:
                        pass
            except Exception:
                pass

        async def _on_req(req: Request):
            try:
                url = req.url
                if "aisandbox-pa.googleapis.com/v1/video" in url:
                    logger.info("--- FLOW API RAW REQUEST CAPTURE ---")
                    logger.info("METHOD: %s", req.method)
                    logger.info("URL: %s", url)
                    try:
                        body = req.post_data_json if req.method == "POST" else None
                        if body:
                            logger.info("POST_DATA: %s", json.dumps(body, ensure_ascii=False, separators=(',', ':')))
                            if "generateVideoText" in url:
                                media_arr = body.get("media", [])
                                if media_arr:
                                    _cap["media_name"] = media_arr[0].get("name")
                    except:
                        pass
                    logger.info("------------------------------------")
            except Exception:
                pass

        page.on("request", _on_req)
        page.on("response", _on_resp)

        # ── Warm up + navigate ────────────────────────────────────────────
        await _prime_flow_session(page)
        nav_url = f"https://labs.google/fx/vi/tools/flow/project/{project_id}"
        await page.goto(nav_url, wait_until="domcontentloaded", timeout=30_000)

        try:
            await page.wait_for_function(
                "() => document.querySelector('[contenteditable=true]') !== null",
                timeout=45_000,
            )
        except Exception as exc:
            raise RuntimeError(f"Flow UI never hydrated: {exc}") from exc

        # ── Xóa overlay ───────────────────────────────────────────────────
        await page.evaluate("""() => {
            document.querySelectorAll('[data-state="open"]').forEach(el => {
                if (!el.getAttribute('role')) el.remove();
            });
        }""")

        # ── Switch sang tab Video ─────────────────────────────────────────
        await page.evaluate("""() => {
            const tabs = Array.from(document.querySelectorAll('button, [role=tab]'));
            const vt = tabs.find(b => /^video$/i.test((b.innerText || b.textContent || '').trim()));
            if (vt) vt.click();
        }""")
        await asyncio.sleep(1.5)
        # Fallback bằng locator
        try:
            loc = page.locator("button", has_text="Video").first
            if await loc.count():
                await loc.click(timeout=3000)
                await asyncio.sleep(1)
        except Exception:
            pass
        # ── Tắt chế độ "Tác nhân" (Agent) nếu đang bật ────────────────────
        try:
            # Nếu bật Tác nhân, Google sẽ khóa/ẩn menu chọn Model
            agent_btn = page.locator("button[aria-pressed='true']:has-text('Tác nhân'), button[aria-pressed='true']:has-text('Agent')").first
            # count() không wait, nên ta dùng try/except click trực tiếp với timeout ngắn
            await agent_btn.click(timeout=1500)
            logger.info("flow_video: Disabled 'Tác nhân' (Agent) mode to unlock model selection")
            await asyncio.sleep(0.5)
        except Exception:
            pass

        # ── Hàm chọn giá trị trong giao diện ──────────────────────────────
        async def _set_dropdown(pg: Page, target_text: str, label: str):
            try:
                # 1. Thử tìm và click trực tiếp nếu element đã hiển thị sẵn (ví dụ: nút aspect ratio hoặc menu đã mở)
                locs = pg.locator(f"text='{target_text}'")
                count = await locs.count()
                
                clicked = False
                for i in range(count - 1, -1, -1):
                    el = locs.nth(i)
                    if await el.is_visible():
                        box = await el.bounding_box()
                        if box:
                            await pg.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                            clicked = True
                            await asyncio.sleep(0.5)
                            break
                            
                # Nếu không thấy (vì menu đang đóng), tìm nút Trigger để mở menu
                if not clicked:
                    trigger_box = await pg.evaluate("""([txt, lbl]) => {
                        const btns = Array.from(document.querySelectorAll('button, div[role="button"]'));
                        let keywords = [];
                        if (lbl === 'model') keywords = ['veo', 'omni', 'flash'];
                        else if (lbl === 'aspect') keywords = ['16:9', '9:16', '1:1', 'portrait', 'landscape', 'square'];
                        else if (lbl === 'duration') keywords = ['4s', '8s', '5s', '10s'];
                        else if (lbl === 'count') keywords = ['1x', 'x1', '2x', 'x2', '3x', '4x'];
                        else keywords = [txt];
                        
                        let trigger = btns.find(b => {
                            const bt = (b.textContent || '').toLowerCase().trim();
                            return keywords.some(k => bt.includes(k));
                        });
                        if (trigger) {
                            const r = trigger.getBoundingClientRect();
                            return {x: r.x + r.width/2, y: r.y + r.height/2};
                        }
                        return null;
                    }""", [target_text, label])
                    
                    if trigger_box:
                        await pg.mouse.click(trigger_box['x'], trigger_box['y'])
                        await asyncio.sleep(1.5) # Đợi React render xong menu
                    else:
                        logger.warning("flow_dropdown_skip %s=%s (Trigger not found)", label, target_text)
                        return
                
                # Sau khi click trigger (hoặc click lần 1), kiểm tra xem nó có mở ra một dropdown list không
                # Bằng cách tìm lại đúng text đó, nếu có nhiều hơn 1 element visible -> có dropdown
                await asyncio.sleep(0.5)
                locs = pg.locator(f"text='{target_text}'")
                count = await locs.count()
                
                # Thường option trong menu sẽ là phần tử cuối cùng hiển thị trên màn hình
                for i in range(count - 1, -1, -1):
                    el = locs.nth(i)
                    if await el.is_visible():
                        # Kiểm tra xem đây có phải trigger không (trigger thường có aria-haspopup hoặc aria-expanded)
                        is_trigger = await el.evaluate("(node) => { return node.hasAttribute('aria-haspopup') || node.hasAttribute('aria-expanded'); }")
                        if not is_trigger:
                            box = await el.bounding_box()
                            if box:
                                await pg.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                                logger.info("flow_dropdown_set %s=%s (Physical Option Click)", label, target_text)
                                await asyncio.sleep(0.5)
                                return
                                
                logger.info("flow_dropdown_set %s=%s (Physical Trigger Click/Direct Toggle)", label, target_text)

            except Exception as e:
                logger.warning("flow_dropdown_error %s=%s: %s", label, target_text, e)
            
            await asyncio.sleep(0.5)

        # ── Set model/aspect/duration/count dropdowns ─────────────────────
        
        # 1. Aspect Ratio
        if aspect_ratio == "16:9":
            await _set_dropdown(page, "16:9", "aspect")
        elif aspect_ratio == "9:16":
            await _set_dropdown(page, "9:16", "aspect")
        elif aspect_ratio == "1:1":
            await _set_dropdown(page, "1:1", "aspect")

        # 2. Count (luôn = 1)
        await _set_dropdown(page, "1x", "count")
        
        # 3. Model
        _MODEL_LABEL = {
            "veo_3_1_t2v":         "Veo 3.1",
            "veo_3_1_t2v_lite":    "Veo 3.1 - Lite",
            "veo_3_1_t2v_fast":    "Veo 3.1 - Fast",
            "veo_3_1_t2v_quality": "Veo 3.1 - Quality",
            "abra_t2v_8s":         "Omni Flash",
            "abra_t2v_10s":        "Omni Flash",
        }
        model_lbl = _MODEL_LABEL.get(model_key.replace("_portrait", ""), "Veo 3.1 - Lite")
        await _set_dropdown(page, model_lbl, "model")
        
        if duration:
            # duration is usually "10s", "4s", etc.
            dur_str = str(duration)
            if not dur_str.endswith("s"):
                dur_str += "s"
            await _set_dropdown(page, dur_str, "duration")

        # ── Humanize ──────────────────────────────────────────────────────
        await _humanize(page, moves=8)

        # ── Nhập prompt ───────────────────────────────────────────────────
        async def _type_prompt():
            try:
                box = page.locator("[contenteditable='true']").first
                # Click vật lý để tạo event isTrusted=true, qua mặt ReCAPTCHA
                await box.click(force=True)
                await asyncio.sleep(0.2)
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await asyncio.sleep(0.2)
                
                # Dùng insert_text (tương đương với hành động Paste/Ctrl+V của người thật)
                await page.keyboard.insert_text(prompt)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning("flow_video: type prompt error: %s", e)
            await asyncio.sleep(1.0)
            
            # Secondary check: if still disabled, type another char natively
            disabled = await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button'));
                let btn = btns.find(b => {
                    const txt = (b.textContent || '');
                    return /arrow_forward/i.test(txt) && /(Tạo|Generate|Create|Send)/i.test(txt);
                });
                if (!btn) btn = btns.find(b => /^(Tạo|Generate|Create)$/i.test((b.textContent||'').trim()));
                return btn ? btn.getAttribute('aria-disabled') === 'true' : true;
            }""")
            if disabled:
                try:
                    await page.keyboard.type(" ")
                    await asyncio.sleep(0.5)
                except Exception:
                    pass

        await _type_prompt()

        # Lấy danh sách các video cũ trên DOM trước khi click
        old_vids = await page.evaluate("() => Array.from(document.querySelectorAll('video')).map(v => v.src)")

        # ── Click nút "Tạo" - retry tối đa 3 lần ────────────────────────
        _budget = max(300, timeout)
        _deadline = started + _budget
        _attempt = 0

        while time.time() < _deadline:
            _attempt += 1
            logger.info("flow_video_submit attempt=%d", _attempt)

            await _humanize(page, moves=3)

            clicked = await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button'));
                let btn = btns.find(b => {
                    const txt = (b.textContent || '');
                    return /arrow_forward/i.test(txt) && /(Tạo|Generate|Create|Send)/i.test(txt);
                });
                if (!btn) btn = btns.find(b => /^(Tạo|Generate|Create)$/i.test((b.textContent||'').trim()) && b.getAttribute('aria-disabled') !== 'true');
                if (!btn) return {ok: false, reason: 'not_found'};
                if (btn.getAttribute('aria-disabled') === 'true') return {ok: false, reason: 'disabled'};
                btn.click();
                return {ok: true};
            }""")
            logger.info("flow_video_click=%s", clicked)

            if not clicked.get("ok"):
                if _attempt >= 3:
                    raise RuntimeError(f"Không click được nút Tạo sau {_attempt} lần: {clicked.get('reason')}")
                await _type_prompt()
                await asyncio.sleep(1.5)
                continue

            # ── Chờ video render trên DOM (không phụ thuộc cấu trúc API) ──
            wait_start = time.time()
            nav_detected = False
            video_url = None
            remaining_credits = None
            
            while time.time() - wait_start < 300:
                # Phát hiện UI navigate sang gallery
                if not nav_detected:
                    nav = await page.evaluate("""() =>
                        Array.from(document.querySelectorAll('button')).some(b => /arrow_back/i.test(b.innerText||''))
                    """)
                    if nav:
                        nav_detected = True
                        logger.info("flow_video: UI navigated (submit OK) - waiting for video DOM")
                
                if nav_detected:
                    # Kiểm tra xem có video nào MỚI load xong chưa
                    vid_src = await page.evaluate("""(old_vids) => {
                        const progress = document.querySelector('div[role="progressbar"]');
                        if (progress) return null; // Vẫn đang gen
                        
                        let vids = Array.from(document.querySelectorAll('video')).map(v => v.src);
                        let new_vid = vids.find(src => !old_vids.includes(src));
                        if (new_vid) return new_vid;

                        // Chưa có thẻ video, thử click vào thumbnail đầu tiên
                        // Trong Google Labs, gallery có các ảnh img hoặc div
                        const firstThumb = document.querySelector('img[alt*="Hiện tượng"], img[src*="blob:"], main img, [data-slate-editor] ~ div img');
                        if (firstThumb) {
                            firstThumb.click();
                            console.log("Clicked thumbnail to open video modal");
                        }
                        
                        return null;
                    }""", old_vids)
                    
                    if vid_src:
                        video_url = vid_src
                        logger.info("flow_video: Found NEW video in DOM: %s", video_url[:100])
                        break
                        
                await asyncio.sleep(4)

            if video_url:
                break

            # Miss response - reload + retry
            logger.warning("flow_video: no video_url after 300s, retrying (attempt %d)", _attempt)
            if _attempt >= 3:
                raise RuntimeError("Không lấy được video từ DOM sau 3 lần click Tạo (quá timeout)")
            await page.goto(nav_url, wait_until="domcontentloaded", timeout=30_000)
            try:
                await page.wait_for_function(
                    "() => document.querySelector('[contenteditable=true]') !== null",
                    timeout=20_000,
                )
            except Exception:
                pass
            await _type_prompt()
            await asyncio.sleep(0.5)

        if not video_url:
            raise RuntimeError(f"Timeout {int(time.time()-started)}s waiting for video DOM.")
            
        logger.info("flow_video: got video_url %s", video_url[:100])

        # ── Download bytes trong browser (có session cookies) ─────────────
        b64_data = ""
        try:
            b64_data = await page.evaluate("""async (src) => {
                const r = await fetch(src);
                const blob = await r.blob();
                return new Promise((res, rej) => {
                    const reader = new FileReader();
                    reader.onloadend = () => res(reader.result);
                    reader.onerror = rej;
                    reader.readAsDataURL(blob);
                });
            }""", video_url)
            logger.info("flow_video: b64 len=%d", len(b64_data))
        except Exception as exc:
            logger.warning("flow_video: download failed: %s", exc)

        # ── Lấy số dư tín dụng ────────────────────────────────────────────
        remaining_credits = _cap.get("remaining_credits")
        if remaining_credits is None:
            try:
                credits_str = await page.evaluate("""async () => {
                    const r = await fetch('https://labs.google/fx/api/trpc/user.getUserProfile?batch=1', {
                        headers: {'x-trpc-source': 'nextjs-react'}
                    });
                    const data = await r.json();
                    return data[0].result.data.json.remainingCredits;
                }""")
                if credits_str is None:
                    # Fallback text extract from UI
                    credits_str = await page.evaluate("""() => {
                        const el = document.querySelector('[class*="TokenIndicator"]');
                        return el ? parseInt((el.innerText || '0').replace(/\\D/g, ''), 10) : null;
                    }""")
                if credits_str is not None:
                    remaining_credits = int(credits_str)
                    logger.info("flow_video: active poll remaining_credits=%s", remaining_credits)
            except Exception as e:
                logger.warning("flow_video: fetch credits failed: %s", e)

        return {
            "created": int(time.time()),
            "data": [{
                "url": video_url,
                "b64_json": b64_data,
                "metadata": {
                    "source":           "flow_ui_intercept",
                    "elapsed_s":        int(time.time() - started),
                    "model":            model_key,
                    "remainingCredits": remaining_credits,
                    "operation_name":   _cap.get("op_name"),
                }
            }]
        }

