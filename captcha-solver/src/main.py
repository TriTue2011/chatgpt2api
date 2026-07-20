"""Captcha solver HTTP API.

Endpoints (all require Authorization: Bearer <CAPTCHA_SOLVER_API_KEY>):

    POST /v1/solve/turnstile          → solve Cloudflare Turnstile
    POST /v1/solve/recaptcha2         → solve reCAPTCHA v2 (checkbox/audio)
    POST /v1/solve/recaptcha3         → solve reCAPTCHA v3 (invisible)
    POST /v1/browser/run              → open URL, run JS, return DOM
    POST /v1/session/manual-login     → open URL in headful mode for VNC
    POST /v1/session/{profile}/close  → close a persistent profile's context
    GET  /v1/session/{profile}/status → quick health check on a profile
    GET  /health                      → unauthenticated liveness probe
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .accounts_db import (
    delete_account,
    get_account,
    list_accounts,
    resolve_account,
    save_account,
)
from .auto_login import (
    get_session as get_login_session,
    list_sessions as list_login_sessions,
    start_auto_login,
    submit_2fa_code,
)
from .chatgpt_login import (
    get_session as get_chatgpt_session,
    start_chatgpt_onboard,
)
from .chatgpt_login import _sessions as chatgpt_sessions
from .gemini_web_login import (
    get_session as get_gemini_web_session,
    start_gemini_web_login,
    submit_2fa_code as submit_gemini_web_2fa_code,
)
from .claude_web_login import (
    get_session as get_claude_web_session,
    start_claude_web_login,
    submit_2fa_code as submit_claude_web_2fa_code,
)
from .solvers.gemini_web import (
    analyze_image as gemini_web_analyze_image,
    chat as gemini_web_chat,
    generate_image as gemini_web_generate_image,
    list_models as gemini_web_list_models,
    get_plan as gemini_web_get_plan,
)
from .browser_pool import pool
from .settings import settings
from .solvers.browser_run import browser_run
from .solvers.flow_google import (
    generate_image as flow_generate_image,
    get_or_create_project as flow_get_or_create_project,
)
from .solvers.chatgpt_web import (
    analyze_image as chatgpt_web_analyze_image,
    chat as chatgpt_web_chat,
    generate_image as chatgpt_web_generate_image,
    list_models as chatgpt_web_list_models,
)
from .solvers.recaptcha import solve_recaptcha_v2, solve_recaptcha_v3
from .solvers.turnstile import solve_turnstile
from .codex_google_onboard import run_codex_google_onboard, CodexGoogleOnboardReq
from .github_codex_onboard import run_codex_onboard, CodexOnboardReq

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("captcha-solver")


def require_api_key(authorization: str | None = Header(default=None)) -> None:
    expected = settings.api_key or ""
    if not expected:
        return  # auth disabled (dev only)
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="invalid api key")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await pool.start()
    yield
    await pool.stop()


app = FastAPI(title="captcha-solver", version="0.1.0", lifespan=lifespan)

# Allow cross-origin POST from chatgpt2api's Settings UI (Flow tab) so the
# "Open noVNC + start Google login" button can call /v1/session/manual-login
# directly from the browser. Auth still required (Bearer header forwarded).
# allow_origins=["*"] is OK here because every protected endpoint
# enforces require_api_key — the Origin header alone never authenticates.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-flow-image-id", "x-flow-model", "x-flow-seed", "x-flow-elapsed-ms"],
)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "novnc": settings.novnc_external_url}


class TurnstileReq(BaseModel):
    url: str
    sitekey: str | None = None
    profile: str = "default"
    headless: bool = True
    timeout: int | None = Field(default=None, ge=5, le=300)


class Recaptcha3Req(BaseModel):
    url: str
    sitekey: str
    action: str = "submit"
    profile: str = "default"
    headless: bool = True
    timeout: int | None = Field(default=None, ge=5, le=300)


class Recaptcha2Req(BaseModel):
    url: str
    profile: str = "default"
    headless: bool = True
    timeout: int | None = Field(default=None, ge=5, le=300)


class BrowserRunReq(BaseModel):
    url: str
    script: str | None = None
    wait_for: str | None = None
    profile: str = "default"
    headless: bool = True
    timeout: int = Field(default=30, ge=5, le=300)


class ManualLoginReq(BaseModel):
    url: str
    profile: str = "default"
    # When true, kill any cached context for this profile and launch a
    # fresh Chrome. Use this from the "Mở lại noVNC" button when the
    # previous window died or noVNC shows a blank desktop.
    force: bool = False


class AutoLoginReq(BaseModel):
    profile: str = "google-fx"
    email: str
    password: str
    totp_secret: str = ""
    # "auth" → click Authenticator on the 2FA picker (state advances to
    # need_code). "tap" → skip the picker so Google falls through to the
    # tap-on-device prompt (state advances to need_tap).
    prefer_method: str = "auth"


class AutoLoginSavedReq(BaseModel):
    """Freshen Google session using password/TOTP already in accounts_db."""
    profile: str


class MultiOnboardReq(BaseModel):
    profile: str = "google-multi"
    email: str
    password: str
    # Same as AutoLoginReq.prefer_method but applied across all services.
    prefer_method: str = "auth"
    # Subset of {"gemini_web", "flow", "chatgpt"}. Order matters — we
    # trigger them sequentially after the shared Google login succeeds.
    # chatgpt rides the shared Google session (reuse_session=True) so it
    # never re-nukes the profile or asks for a second 2FA.
    services: list[str] = Field(default_factory=lambda: ["gemini_web", "flow", "chatgpt"])


class TwoFactorCodeReq(BaseModel):
    code: str


class GetOrCreateProjectReq(BaseModel):
    profile: str = "google-fx"
    headless: bool = False
    timeout: int = Field(default=90, ge=20, le=300)


class GeminiWebOnboardReq(BaseModel):
    profile: str = "gemini-web-default"
    email: str
    password: str
    totp_secret: str = ""


class GeminiWebChatReq(BaseModel):
    profile: str = "gemini-web-default"
    prompt: str
    timeout: int = Field(default=90, ge=20, le=300)
    headless: bool = False


class ClaudeWebOnboardReq(BaseModel):
    profile: str = "claude-web-default"
    email: str = ""
    password: str = ""
    totp_secret: str = ""




class GeminiWebImageReq(BaseModel):
    profile: str = "gemini-web-default"
    prompt: str
    count: int = Field(default=1, ge=1, le=4)
    timeout: int = Field(default=120, ge=30, le=300)
    headless: bool = False


class GeminiWebVisionReq(BaseModel):
    profile: str = "gemini-web-default"
    image: str  # data:image/...;base64,... OR https URL
    prompt: str = "Phân tích nội dung ảnh này một cách chi tiết."
    timeout: int = Field(default=120, ge=30, le=300)
    headless: bool = False


class FlowImageReq(BaseModel):
    project_id: str
    prompt: str
    # Default 16:9 landscape. Other supported values matching Flow's pill
    # buttons: IMAGE_ASPECT_RATIO_LANDSCAPE_4_3, _SQUARE, _PORTRAIT_3_4,
    # _PORTRAIT (9:16).
    aspect_ratio: str = "IMAGE_ASPECT_RATIO_LANDSCAPE"
    # Strongest model by default. NARWHAL = Nano Banana 2, IMAGEN_4 = Imagen 4.
    model: str = "NANO_BANANA_PRO"
    # 1-4 images per request. Best-effort — Flow uses project default if
    # the dropdown click misses.
    count: int = Field(default=1, ge=1, le=4)
    tool: str = "PINHOLE"
    profile: str = "google-fx"
    # Flow's React app doesn't hydrate in true headless mode, so we default
    # to headful on Xvfb. Leave as-is unless you really know why.
    headless: bool = False
    timeout: int = Field(default=120, ge=15, le=300)
    # When true, the response is a single image/png body (the first image
    # downloaded from the Google CDN). Use this from Home Assistant or n8n
    # binary-handling nodes so you don't need a second HTTP call.
    return_binary: bool = False


class FlowVideoReq(BaseModel):
    prompt: str
    project_id: str = ""
    model: str = "flow/veo-3.1-lite"
    aspect_ratio: str = "16:9"
    duration: str | None = None
    count: int = 1
    image: str | None = None
    last_frame: str | None = None
    profile: str = "google-fx"
    headless: bool = True
    timeout: int = Field(default=300, ge=60, le=600)
    return_binary: bool = False


@app.post("/v1/solve/turnstile", dependencies=[Depends(require_api_key)])
async def api_solve_turnstile(req: TurnstileReq) -> dict[str, Any]:
    try:
        return await solve_turnstile(
            url=req.url,
            sitekey=req.sitekey,
            profile=req.profile,
            headless=req.headless,
            timeout=req.timeout,
        )
    except HTTPException:
        raise
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("turnstile solve failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/solve/recaptcha3", dependencies=[Depends(require_api_key)])
async def api_solve_recaptcha3(req: Recaptcha3Req) -> dict[str, Any]:
    try:
        return await solve_recaptcha_v3(
            url=req.url,
            sitekey=req.sitekey,
            action=req.action,
            profile=req.profile,
            headless=req.headless,
            timeout=req.timeout,
        )
    except HTTPException:
        raise
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("recaptcha3 solve failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/solve/recaptcha2", dependencies=[Depends(require_api_key)])
async def api_solve_recaptcha2(req: Recaptcha2Req) -> dict[str, Any]:
    try:
        return await solve_recaptcha_v2(
            url=req.url,
            profile=req.profile,
            headless=req.headless,
            timeout=req.timeout,
        )
    except HTTPException:
        raise
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("recaptcha2 solve failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/google/flow/generate-image", dependencies=[Depends(require_api_key)])
async def api_flow_generate(req: FlowImageReq):
    """End-to-end Google Labs Flow image gen. Requires the `google-fx`
    profile to be logged in first via /v1/session/manual-login.

    Returns JSON by default. With `return_binary: true`, downloads the
    first generated image and returns it as `image/png` (handy for Home
    Assistant `rest_command`, n8n HTTP Request → Binary Data, etc).

    For `count > 1` we fan out N parallel calls to Flow (the API itself
    only generates 1 image per request — there's no batch field — so we
    parallelise the requests instead). Each call uses the same profile
    + project; the BrowserPool will serialise them if the profile only
    has one Chromium context, which keeps the same upper bound on
    parallelism as the user has logged-in accounts.
    """
    import asyncio

    async def _one() -> dict:
        return await flow_generate_image(
            project_id=req.project_id,
            prompt=req.prompt,
            aspect_ratio=req.aspect_ratio,
            model=req.model,
            count=1,  # always 1 per call — count handled at this layer
            tool=req.tool,
            profile=req.profile,
            headless=req.headless,
            timeout=req.timeout,
        )

    try:
        n = max(1, min(4, int(req.count or 1)))
        if n == 1:
            result = await _one()
        else:
            # Fan-out, gather all (and surface the first exception if any).
            results = await asyncio.gather(*[_one() for _ in range(n)], return_exceptions=True)
            ok_results = [r for r in results if isinstance(r, dict)]
            failures = [r for r in results if not isinstance(r, dict)]
            if not ok_results:
                raise RuntimeError(f"all {n} parallel calls failed: {failures[0]}")
            # Merge: keep first result's metadata, concatenate `images`.
            result = dict(ok_results[0])
            merged_images = []
            for r in ok_results:
                merged_images.extend(r.get("images") or [])
            result["images"] = merged_images
            if failures:
                logger.warning("flow_partial_failure ok=%d failed=%d first_error=%s",
                                len(ok_results), len(failures), failures[0])
    except HTTPException:
        raise
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("flow generate failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not req.return_binary:
        return result

    images = result.get("images") or []
    if not images:
        raise HTTPException(status_code=502, detail="flow returned no images")
    first = images[0]
    url = first.get("url")
    if not url:
        raise HTTPException(status_code=502, detail="first image has no URL")
    if url.startswith("data:"):
        import base64
        header, b64data = url.split(",", 1)
        content = base64.b64decode(b64data)
        cdn_ct = header.split(";", 1)[0].split(":")[1]
        r_headers = {}
    else:
        try:
            cookies = {c["name"]: c["value"] for c in result.get("cookies", [])}
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, cookies=cookies) as client:
                r = await client.get(url)
                r.raise_for_status()
                content = r.content
                cdn_ct = (r.headers.get("content-type") or "").split(";")[0].strip()
                r_headers = r.headers
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("download flow image failed")
            raise HTTPException(status_code=502, detail=f"download failed: {exc}") from exc

    return Response(
        content=content,
        media_type=cdn_ct or first.get("mime") or "image/png",
        headers={
            "x-flow-image-id": str(first.get("id") or ""),
            "x-flow-model": str(first.get("model") or ""),
            "x-flow-seed": str(first.get("seed") or ""),
            "x-flow-elapsed-ms": str(result.get("elapsed_ms") or ""),
            "content-disposition": f'inline; filename="flow_{first.get("id","image")}.png"',
        },
    )


@app.post("/v1/google/flow/generate-video", dependencies=[Depends(require_api_key)])
async def api_flow_generate_video(req: FlowVideoReq):
    """End-to-end Google Labs Flow Video generation."""
    try:
        from src.solvers.flow_google import flow_generate_video
        
        # We handle project_id exactly like the image route:
        # if project_id is empty, it needs get_or_create_project first.
        # But for now, assume the caller passed it or we wrap it in a helper.
        result = await flow_generate_video(
            project_id=req.project_id or "placeholder", # The UI usually sends it
            prompt=req.prompt,
            aspect_ratio=req.aspect_ratio,
            model=req.model,
            duration=req.duration,
            count=req.count,
            image_b64=req.image,
            last_frame_b64=req.last_frame,
            profile=req.profile,
            headless=req.headless,
            timeout=req.timeout,
        )
        return result
    except Exception as exc:
        logger.exception("flow generate video failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not req.return_binary:
        return result
        
    try:
        import httpx
        url = result["data"][0]["url"]
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
            r.raise_for_status()
            return Response(content=r.content, media_type="video/mp4")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Download video failed: {exc}")


@app.post(
    "/v1/google/flow/get-or-create-project",
    dependencies=[Depends(require_api_key)],
)
async def api_flow_get_or_create_project(req: GetOrCreateProjectReq) -> dict[str, Any]:
    """List Flow projects the logged-in account already owns and return
    the first one's UUID, or click "Dự án mới" to create a fresh one
    and return its UUID. The profile MUST already be logged in.

    Used by the chatgpt2api UI's "1-click add account" flow:
      1. POST /v1/session/auto-login {profile, email, password}
      2. Poll /v1/session/{profile}/auto-login-status until success
      3. POST /v1/google/flow/get-or-create-project {profile}
      4. PATCH /api/settings to add the {profile, project_id, label}
         to flow.accounts
    """
    try:
        return await flow_get_or_create_project(
            profile=req.profile,
            headless=req.headless,
            timeout=req.timeout,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("flow get_or_create_project failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/browser/run", dependencies=[Depends(require_api_key)])
async def api_browser_run(req: BrowserRunReq) -> dict[str, Any]:
    try:
        return await browser_run(
            url=req.url,
            script=req.script,
            wait_for=req.wait_for,
            profile=req.profile,
            headless=req.headless,
            timeout=req.timeout,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("browser run failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc



@app.post("/v1/session/manual-login", dependencies=[Depends(require_api_key)])
async def api_manual_login(req: ManualLoginReq) -> dict[str, Any]:
    """Open `url` in a headful browser on the noVNC display so the user can
    sign in manually. The profile's user-data-dir persists, so the next
    automated call with the same `profile` is already logged in.

    Reuses the first existing page in the context (so the user sees ONE
    Chrome window in noVNC, not a new tab on every click). If `force=True`,
    any cached context for this profile is killed and a fresh Chrome is
    launched — use this when noVNC shows "Connected... :99" but the
    desktop is blank (Chrome died between calls).

    """
    ctx = await pool.get(
        profile=req.profile,
        headless=False,
        force_recreate=req.force,
    )
    # Reuse first non-closed page so noVNC user keeps ONE window.
    page = None
    for p in list(ctx.pages):
        try:
            if not p.is_closed():
                page = p
                break
        except Exception:
            continue
    if page is None:
        page = await ctx.new_page()
    try:
        await page.bring_to_front()
    except Exception:
        pass
    await page.goto(req.url, wait_until="domcontentloaded", timeout=30_000)

    return {
        "profile": req.profile,
        "url": req.url,
        "open_in_browser": settings.novnc_external_url,
        "force": req.force,
        "message": (
            "Mở noVNC URL ở trên, đăng nhập tài khoản trong cửa sổ Chromium. "
            "Cookies sẽ được lưu vào profile '{}' để các lần gọi sau dùng headless. "
            "Nếu desktop trống → gọi lại endpoint này với force=true.".format(req.profile)
        ),
    }


@app.post("/v1/session/auto-login", dependencies=[Depends(require_api_key)])
async def api_auto_login(req: AutoLoginReq) -> dict[str, Any]:
    """Start a CLI-driven Google login. Returns immediately with the
    initial session state — UI polls /v1/session/{profile}/auto-login-status
    to track progress and feeds 2FA codes via /auto-login-2fa-code.

    Anti-bot reality: Google often blocks automation in container/VPS
    setups. If state stalls or fails, the noVNC window is still open
    — the user can finish the remaining steps manually and the saved
    cookies persist either way.
    """
    session = await start_auto_login(
        profile=req.profile,
        email=req.email,
        password=req.password,
        prefer_method=req.prefer_method,
        totp_secret=req.totp_secret,
    )
    # Auto-save credentials to shared accounts DB
    try: save_account(req.email, req.password, req.totp_secret, "")
    except Exception: pass
    return {
        **session.to_dict(),
        "novnc": settings.novnc_external_url,
        "note": "Theo dõi tiến trình ở /v1/session/{profile}/auto-login-status. "
                "Mở noVNC để giám sát/can thiệp khi cần.",
    }


# ── Multi-service onboard ────────────────────────────────────────────────
# One Google login → trigger Gemini Web + Flow + ChatGPT onboards in
# sequence on the same persistent profile so the user only goes through
# the 2FA prompt once. ChatGPT may still fail at the chatgpt.com Cloudflare
# wall but Gemini/Flow inherit the Google session and succeed silently.

_MULTI_STATES: dict[str, dict[str, Any]] = {}


def _multi_state(profile: str) -> dict[str, Any]:
    return _MULTI_STATES.setdefault(profile, {
        "profile": profile,
        "stage": "idle",
        "results": {},   # service → {"state": ..., "token": ..., "error": ...}
        "started_at": None,
        "completed_at": None,
        "error": None,
    })


async def _run_multi(req: MultiOnboardReq) -> None:
    """Background runner for /v1/multi-onboard. State is exposed via
    /v1/multi-onboard/{profile}/status; the UI polls it and feeds the
    auth code (if any) via the existing /auto-login-2fa-code endpoint
    on the SAME profile."""
    import asyncio as _asyncio
    state = _multi_state(req.profile)
    state["stage"] = "google_login"
    state["started_at"] = time.time()
    state["error"] = None
    try:
        # Step 1 — Google login (shared session for every service below).
        await start_auto_login(
            profile=req.profile,
            email=req.email,
            password=req.password,
            prefer_method=req.prefer_method,
        )
        deadline = time.time() + 360
        while time.time() < deadline:
            await _asyncio.sleep(2)
            sess = get_login_session(req.profile)
            if sess is None:
                continue
            if sess.state == "success":
                break
            if sess.state in ("failed", "error"):
                state["stage"] = "failed"
                state["error"] = f"google_login: {sess.error or sess.message}"
                state["completed_at"] = time.time()
                return
        else:
            state["stage"] = "failed"
            state["error"] = "google_login: timeout"
            state["completed_at"] = time.time()
            return

        # Step 2 — Per-service onboard. Each service reuses the same
        # persistent Chrome profile so Google cookies are already there.
        for svc in req.services:
            state["stage"] = svc
            state["results"][svc] = {"state": "running"}
            try:
                if svc == "gemini_web":
                    s = await start_gemini_web_login(
                        profile=req.profile, email=req.email, password=req.password,
                    )
                elif svc == "flow":
                    # Flow login = Google session + open labs.google. The
                    # existing Google session is enough; we just record success.
                    state["results"][svc] = {"state": "success", "note": "uses shared Google session"}
                    continue
                elif svc == "chatgpt":
                    # ChatGPT rides the shared Google session via reuse_session
                    # (no profile nuke, no 2nd 2FA) — just SSO + scrape JWT.
                    await start_chatgpt_onboard(
                        profile=req.profile, email=req.email, password=req.password,
                        reuse_session=True,
                    )
                    cgpt_deadline = time.time() + 240
                    while time.time() < cgpt_deadline:
                        await _asyncio.sleep(2)
                        cur = get_chatgpt_session(req.profile)
                        if cur is None:
                            continue
                        if cur.state == "success":
                            state["results"][svc] = {
                                "state": "success",
                                "token": getattr(cur, "access_token", None),
                                "email": getattr(cur, "captured_email", None) or req.email,
                            }
                            break
                        if cur.state in ("failed", "error"):
                            state["results"][svc] = {
                                "state": "failed",
                                "error": cur.error or cur.message,
                            }
                            break
                    else:
                        state["results"][svc] = {"state": "failed", "error": "timeout"}
                    continue
                elif svc in ("claude_web", "claude"):
                    # Claude rides the shared Google session — scrape sessionKey.
                    await start_claude_web_login(
                        profile=req.profile, email=req.email, password=req.password,
                    )
                    cl_deadline = time.time() + 240
                    while time.time() < cl_deadline:
                        await _asyncio.sleep(2)
                        cur = get_claude_web_session(req.profile)
                        if cur is None:
                            continue
                        if cur.state == "success":
                            state["results"][svc] = {
                                "state": "success",
                                "session_key": getattr(cur, "session_key", None),
                                "email": req.email,
                            }
                            break
                        if cur.state in ("failed", "error"):
                            state["results"][svc] = {"state": "failed", "error": cur.error or cur.message}
                            break
                    else:
                        state["results"][svc] = {"state": "failed", "error": "timeout"}
                    continue

                else:
                    state["results"][svc] = {"state": "skipped", "error": "unknown service"}
                    continue
                # Poll the service-specific session until terminal.
                svc_deadline = time.time() + 240
                while time.time() < svc_deadline:
                    await _asyncio.sleep(2)
                    cur = get_gemini_web_session(req.profile)
                    if cur is None:
                        continue
                    if cur.state == "success":
                        token = getattr(cur, "access_token", None)
                        state["results"][svc] = {
                            "state": "success",
                            "token": token,
                            "email": getattr(cur, "captured_email", None) or req.email,
                        }
                        break
                    if cur.state in ("failed", "error"):
                        state["results"][svc] = {
                            "state": "failed",
                            "error": cur.error or cur.message,
                        }
                        break
                else:
                    state["results"][svc] = {"state": "failed", "error": "timeout"}
            except Exception as exc:
                state["results"][svc] = {"state": "failed", "error": str(exc)[:200]}

        state["stage"] = "done"
        state["completed_at"] = time.time()
    except Exception as exc:
        state["stage"] = "failed"
        state["error"] = str(exc)[:300]
        state["completed_at"] = time.time()


@app.post("/v1/codex-google-onboard", dependencies=[Depends(require_api_key)])
async def api_codex_google_onboard(req: CodexGoogleOnboardReq) -> dict[str, Any]:
    """Ride the existing Google session in a google-* profile to complete a
    Codex OAuth authorize; returns the localhost callback URL (?code=...)."""
    return await run_codex_google_onboard(req)


@app.post("/v1/codex-onboard", dependencies=[Depends(require_api_key)])
async def api_codex_onboard(req: CodexOnboardReq) -> dict[str, Any]:
    """Codex auto-login qua GITHUB (hàng loạt): mở auth_url trong browser pool
    (hiện trên VNC :99), đăng nhập Github + lấy mã IMAP, trả callback URL."""
    return await run_codex_onboard(req)










@app.post("/v1/session/auto-login-saved", dependencies=[Depends(require_api_key)])
async def api_auto_login_saved(req: AutoLoginSavedReq) -> dict[str, Any]:
    """Freshen Google login KHÔNG cần truyền password — tự tra credentials đã
    lưu (accounts_db) theo profile/email. Dùng cho auto-recovery: caller chỉ
    biết profile, mật khẩu Google nằm trong solver (không lộ ra ngoài)."""
    acct = resolve_account(req.profile)
    if not acct or not acct.get("password"):
        return {"state": "failed", "error": "no saved Google credentials for this profile"}
    totp = str(acct.get("totp_secret") or "").strip()
    session = await start_auto_login(
        profile=req.profile,
        email=str(acct.get("email") or ""),
        password=str(acct.get("password") or ""),
        prefer_method="auth" if totp else "tap",
        totp_secret=totp,
    )
    return {**session.to_dict(), "novnc": settings.novnc_external_url}


@app.post("/v1/multi-onboard", dependencies=[Depends(require_api_key)])
async def api_multi_onboard(req: MultiOnboardReq) -> dict[str, Any]:
    """Kick off one Google login + fan out to multiple service onboards.

    UI flow:
      1. POST /v1/multi-onboard {email, password, prefer_method, services}
      2. Poll /v1/multi-onboard/{profile}/status to track progress
      3. When the embedded Google session reports state=need_code, POST
         the 6-digit Authenticator code to
         /v1/session/{profile}/auto-login-2fa-code (existing endpoint —
         same profile shared between the multi-flow and the embedded
         auto-login session).
      4. When stage=done, response.results[service].token is the JWT to
         feed into chatgpt2api's account pool.
    """
    import asyncio as _asyncio
    state = _multi_state(req.profile)
    state.update({
        "profile": req.profile,
        "stage": "starting",
        "results": {},
        "started_at": time.time(),
        "completed_at": None,
        "error": None,
        "prefer_method": req.prefer_method,
        "services": list(req.services),
    })
    _asyncio.create_task(_run_multi(req))
    return {
        "profile": req.profile,
        "stage": state["stage"],
        "services": req.services,
        "prefer_method": req.prefer_method,
        "novnc": settings.novnc_external_url,
        "note": "Poll /v1/multi-onboard/{profile}/status. Khi state Google "
                "ở need_code, POST mã vào /v1/session/{profile}/auto-login-2fa-code.",
    }


@app.get("/v1/multi-onboard/{profile}/status", dependencies=[Depends(require_api_key)])
async def api_multi_onboard_status(profile: str) -> dict[str, Any]:
    state = dict(_multi_state(profile))
    # Surface the embedded Google login state so the UI can detect
    # need_code / need_tap without polling a second endpoint.
    g = get_login_session(profile)
    if g is not None:
        state["google"] = {
            "state": g.state,
            "message": g.message,
            "tap_number": g.tap_number,
            "error": g.error,
        }
    return state


@app.get(
    "/v1/session/{profile}/auto-login-status",
    dependencies=[Depends(require_api_key)],
)
async def api_auto_login_status(profile: str) -> dict[str, Any]:
    session = get_login_session(profile)
    if session is None:
        return {"profile": profile, "state": "none", "message": "Chưa có phiên auto-login"}
    return session.to_dict()


@app.post(
    "/v1/session/{profile}/auto-login-2fa-code",
    dependencies=[Depends(require_api_key)],
)
async def api_auto_login_2fa_code(profile: str, req: TwoFactorCodeReq) -> dict[str, Any]:
    """Feed an SMS / TOTP / backup code to a session currently in
    state=need_code. Returns 409 if the session isn't asking for one."""
    ok = submit_2fa_code(profile, req.code)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Phiên không ở trạng thái cần mã (chỉ submit được khi state=need_code)",
        )
    return {"profile": profile, "submitted": True}


@app.get("/v1/session/auto-login-sessions", dependencies=[Depends(require_api_key)])
async def api_auto_login_sessions() -> dict[str, Any]:
    """Snapshot of every auto-login session (running + recently finished)."""
    return {"sessions": list_login_sessions()}


@app.get("/v1/session/{profile}/warmup", dependencies=[Depends(require_api_key)])
async def api_session_warmup(profile: str, provider: str = "gemini_web") -> dict[str, Any]:
    """Khởi động ngầm trình duyệt (warm up) để giảm độ trễ cho câu hỏi đầu tiên."""
    # Đã vô hiệu hoá logic giữ Chrome chạy ngầm (warmup) để tiết kiệm 100% CPU.
    # Trình duyệt giờ đây sẽ CHỈ được bật lên khi có request chat thực tế từ người dùng.
    return {"profile": profile, "status": "warmed_up_bypassed_to_save_cpu"}


@app.get("/v1/profiles", dependencies=[Depends(require_api_key)])
async def api_list_profiles(prefix: str = "") -> dict[str, Any]:
    """List all available browser profiles matching a prefix."""
    try:
        from src.settings import settings
        import os
        profiles_dir = settings.data_dir / "profiles"
        if not profiles_dir.exists():
            return {"profiles": []}
        profiles = []
        for d in profiles_dir.iterdir():
            if d.is_dir() and d.name.startswith(prefix):
                profiles.append(d.name)
        return {"profiles": sorted(profiles)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to list profiles")
        raise HTTPException(status_code=500, detail=str(exc)) from exc



# ── Gemini Web (gemini.google.com) ──────────────────────────────────────

@app.get("/v1/gemini-web/{profile}/plan", dependencies=[Depends(require_api_key)])
async def api_gemini_web_plan(profile: str, headless: bool = True, timeout: int = 30) -> dict[str, Any]:
    """Detected subscription tier of a Gemini Web profile.

    Wraps `solvers.gemini_web.get_plan` so the chatgpt2api provider-tree
    can show a free/plus/pro/ultra badge next to each onboarded
    profile. Plan classification is text-pattern based — there's no
    public API for it on Google's side.
    """
    try:
        return await gemini_web_get_plan(profile=profile, headless=headless, timeout=timeout)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("gemini_web get_plan failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/v1/gemini-web/{profile}/models", dependencies=[Depends(require_api_key)])
async def api_gemini_web_models(profile: str, headless: bool = True, timeout: int = 30) -> dict[str, Any]:
    """Live model list scraped from gemini.google.com's model picker.

    Returns `{"models": [...]}` shaped like the catalogue chatgpt2api
    exposes elsewhere — each item carries `id: "gmw/<slug>"` so the
    aggregator in /v1/models can drop them straight into the response.
    """
    try:
        models = await gemini_web_list_models(profile=profile, headless=headless, timeout=timeout)
        return {"profile": profile, "count": len(models), "models": models}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("gemini_web list_models failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/gemini-web/onboard", dependencies=[Depends(require_api_key)])
async def api_gemini_web_onboard(req: GeminiWebOnboardReq) -> dict[str, Any]:
    prefer = getattr(req, "prefer_method", "auth" if req.totp_secret else "tap")
    session = await start_gemini_web_login(
        profile=req.profile, email=req.email, password=req.password,
        totp_secret=req.totp_secret, prefer_method=prefer,
    )
    try: save_account(req.email, req.password, req.totp_secret, "")
    except Exception: pass
    return {
        **session.to_dict(),
        "novnc": settings.novnc_external_url,
        "note": "Theo dõi tiến trình ở /v1/gemini-web/{profile}/onboard-status. "
                "Khi state=success, gọi /v1/gemini-web/chat để chat.",
    }


@app.get("/v1/gemini-web/{profile}/onboard-status", dependencies=[Depends(require_api_key)])
async def api_gemini_web_onboard_status(profile: str) -> dict[str, Any]:
    session = get_gemini_web_session(profile)
    if session is None:
        return {"profile": profile, "state": "none", "message": "Chưa có phiên onboard"}
    return session.to_dict()


@app.post("/v1/gemini-web/{profile}/onboard-2fa-code", dependencies=[Depends(require_api_key)])
async def api_gemini_web_onboard_2fa_code(profile: str, req: TwoFactorCodeReq) -> dict[str, Any]:
    ok = submit_gemini_web_2fa_code(profile, req.code)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Phiên không ở state=need_code",
        )
    return {"profile": profile, "submitted": True}


@app.post("/v1/gemini-web/{profile}/relogin-via-google", dependencies=[Depends(require_api_key)])
async def api_gemini_web_relogin_via_google(profile: str) -> dict[str, Any]:
    """Re-login gemini.google.com bằng credential đã lưu (resolve theo profile).
    Profile còn phiên Google → ride SSO (không nhập tay); mất phiên → tự
    email/password/2FA. Dùng cho self-heal khi 1PSID hết hạn."""
    acct = resolve_account(profile)
    if not acct:
        raise HTTPException(404, f"No saved credentials for profile '{profile}'")
    await pool.close_profile(profile)
    session = await start_gemini_web_login(
        profile=profile, email=acct["email"], password=acct["password"],
        totp_secret=acct.get("totp_secret", ""),
    )
    return {**session.to_dict(), "note": "Poll /v1/gemini-web/{profile}/onboard-status."}


# ── Claude Web (claude.ai) ──────────────────────────────────────────────

@app.post("/v1/claude-web/onboard", dependencies=[Depends(require_api_key)])
async def api_claude_web_onboard(req: ClaudeWebOnboardReq) -> dict[str, Any]:
    prefer = getattr(req, "prefer_method", "auth" if req.totp_secret else "tap")
    session = await start_claude_web_login(
        profile=req.profile, email=req.email, password=req.password,
        totp_secret=req.totp_secret, prefer_method=prefer,
    )
    # Chỉ lưu credential khi có email thực, tránh ghi đè rác vào DB
    if req.email.strip() and req.password.strip():
        try: save_account(req.email, req.password, req.totp_secret, "")
        except Exception: pass
    return {
        **session.to_dict(),
        "novnc": settings.novnc_external_url,
        "note": "Theo dõi /v1/claude-web/{profile}/onboard-status. Khi state=success, "
                "lấy sessionKey ở /v1/claude-web/{profile}/session.",
    }


@app.get("/v1/claude-web/{profile}/onboard-status", dependencies=[Depends(require_api_key)])
async def api_claude_web_onboard_status(profile: str) -> dict[str, Any]:
    session = get_claude_web_session(profile)
    if session is None:
        return {"profile": profile, "state": "none", "message": "Chưa có phiên onboard"}
    return session.to_dict()


@app.post("/v1/claude-web/{profile}/onboard-2fa-code", dependencies=[Depends(require_api_key)])
async def api_claude_web_onboard_2fa_code(profile: str, req: TwoFactorCodeReq) -> dict[str, Any]:
    ok = submit_claude_web_2fa_code(profile, req.code)
    if not ok:
        raise HTTPException(status_code=409, detail="Phiên không ở state=need_code")
    return {"profile": profile, "submitted": True}


@app.get("/v1/claude-web/{profile}/session", dependencies=[Depends(require_api_key)])
async def api_claude_web_session(profile: str) -> dict[str, Any]:
    """Return the scraped claude.ai sessionKey for a logged-in profile.

    chatgpt2api's api/claude.py calls this to obtain the cookie instead of
    storing a static session_key in config.
    """
    session = get_claude_web_session(profile)
    if session is None or not session.session_key:
        raise HTTPException(status_code=404, detail="Chưa có sessionKey (onboard Claude Web trước)")
    return {"profile": profile, "session_key": session.session_key, "email": session.email}


@app.post("/v1/claude-web/{profile}/relogin-via-google", dependencies=[Depends(require_api_key)])
async def api_claude_web_relogin_via_google(profile: str) -> dict[str, Any]:
    """Re-login claude.ai bằng credential đã lưu (resolve theo profile→email). Nếu
    profile đã có phiên Google → claude ride SSO, KHÔNG cần nhập tay (reuse)."""
    acct = resolve_account(profile)
    if not acct:
        raise HTTPException(404, f"No saved credentials for profile '{profile}'")
    session = await start_claude_web_login(
        profile=profile,
        email=acct["email"],
        password=acct["password"],
        totp_secret=acct.get("totp_secret", ""),
    )
    return {**session.to_dict(), "note": "Poll /v1/claude-web/{profile}/onboard-status de theo doi."}


@app.post("/v1/gemini-web/chat", dependencies=[Depends(require_api_key)])
async def api_gemini_web_chat(req: GeminiWebChatReq) -> dict[str, Any]:
    """Send a prompt to gemini.google.com (DOM-scrape approach).

    Profile must already be logged in via /v1/gemini-web/onboard.
    Returns the assistant's text response + elapsed_ms.
    """
    try:
        return await gemini_web_chat(
            profile=req.profile, prompt=req.prompt,
            timeout=req.timeout, headless=req.headless,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("gemini_web chat failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/gemini-web/generate-image", dependencies=[Depends(require_api_key)])
async def api_gemini_web_generate_image(req: GeminiWebImageReq) -> dict[str, Any]:
    """Generate image(s) via Imagen — activates the 'Tạo hình ảnh' tool
    in Gemini's + menu, types the prompt, scrapes <img> from response."""
    try:
        return await gemini_web_generate_image(
            profile=req.profile, prompt=req.prompt, count=req.count,
            timeout=req.timeout, headless=req.headless,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("gemini_web generate_image failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/gemini-web/analyze-image", dependencies=[Depends(require_api_key)])
async def api_gemini_web_analyze_image(req: GeminiWebVisionReq) -> dict[str, Any]:
    """Upload an image to Gemini Web and ask a question about it.
    Accepts `image` as either a data:image/...;base64 URL or an https URL."""
    try:
        return await gemini_web_analyze_image(
            profile=req.profile, image=req.image, prompt=req.prompt,
            timeout=req.timeout, headless=req.headless,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("gemini_web analyze_image failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/v1/session/list", dependencies=[Depends(require_api_key)])
async def api_session_list() -> dict[str, Any]:
    """List all known profiles (each is a chromium user-data-dir) along
    with whether they're currently held open in the pool."""
    root = settings.data_dir / "profiles"
    profiles: list[dict[str, Any]] = []
    if root.exists():
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            size = 0
            try:
                size = sum(p.stat().st_size for p in child.rglob("*") if p.is_file())
            except Exception:
                pass
            profiles.append({
                "name": child.name,
                "loaded": pool.is_loaded(child.name),
                "size_bytes": size,
                "path": str(child),
            })
    return {"profiles": profiles, "count": len(profiles)}


@app.get("/v1/session/{profile}/status", dependencies=[Depends(require_api_key)])
async def api_session_status(profile: str) -> dict[str, Any]:
    ctx = pool.get_cached(profile)
    if ctx is None:
        return {"profile": profile, "loaded": False, "pages": 0, "cookies": 0}
    try:
        cookies = await ctx.cookies()
    except Exception:
        # Context exists in cache but is dead — return zeroes; next /get
        # call will evict it.
        return {"profile": profile, "loaded": False, "pages": 0, "cookies": 0, "stale": True}
    return {
        "profile": profile,
        "loaded": True,
        "pages": len(ctx.pages),
        "cookies": len(cookies),
    }


@app.post("/v1/session/{profile}/close", dependencies=[Depends(require_api_key)])
async def api_session_close(profile: str) -> dict[str, Any]:
    closed = await pool.close_profile(profile)
    return {"profile": profile, "closed": closed}


@app.get("/v1/gemini-web/{profile}/cookies", dependencies=[Depends(require_api_key)])
async def api_gemini_web_cookies(profile: str) -> dict[str, Any]:
    """Export Google session cookies từ profile đã login.

    Trả __Secure-1PSID / __Secure-1PSIDTS để chatgpt2api (gma/ provider,
    lib gemini_webapi) gọi thẳng HTTP API gemini.google.com — không cần DOM.
    Pattern y hệt /v1/claude-web/{profile}/session của Claude.
    """
    ctx = pool.get_cached(profile)
    if ctx is None:
        try:
            ctx = await pool.get(profile)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"cannot load profile: {exc}") from exc
    try:
        cookies = await ctx.cookies("https://gemini.google.com")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"profile context dead: {exc}") from exc
    wanted = {"__Secure-1PSID", "__Secure-1PSIDTS"}
    out = {c["name"]: c["value"] for c in cookies
           if c.get("name") in wanted and c.get("value")}
    if "__Secure-1PSID" not in out:
        raise HTTPException(
            status_code=404,
            detail="profile has no Google session (__Secure-1PSID missing) — onboard first",
        )
    return {"profile": profile, "cookies": out}


# ── ChatGPT onboard ──────────────────────────────────────────────────────

class ChatGPTOnboardReq(BaseModel):
    profile: str = "chatgpt-default"
    email: str = ""
    password: str = ""
    totp_secret: str = ""
    reuse_session: bool = False


class ChatGPT2FACodeReq(BaseModel):
    code: str


@app.post("/v1/chatgpt/onboard", dependencies=[Depends(require_api_key)])
async def api_chatgpt_onboard(req: ChatGPTOnboardReq) -> dict[str, Any]:
    """Onboard ChatGPT via Google. If totp_secret provided, 2FA is automatic."""
    prefer = getattr(req, "prefer_method", "auth" if req.totp_secret else "tap")
    session = await start_chatgpt_onboard(
        profile=req.profile,
        email=req.email,
        password=req.password,
        totp_secret=req.totp_secret,
        prefer_method=prefer,
        reuse_session=req.reuse_session,
    )
    # Auto-save credentials to shared accounts DB
    try: save_account(req.email, req.password, req.totp_secret, "")
    except Exception: pass
    return {
        **session.to_dict(),
        "note": "Poll /v1/chatgpt/{profile}/onboard-status. "
                "Mo noVNC de giam sat/can thiep khi can.",
    }


@app.get("/v1/chatgpt/{profile}/onboard-status", dependencies=[Depends(require_api_key)])
async def api_chatgpt_onboard_status(profile: str) -> dict[str, Any]:
    session = get_chatgpt_session(profile)
    if not session:
        return {"profile": profile, "state": "none", "message": "Chua co phien onboard"}
    return session.to_dict()


@app.post("/v1/chatgpt/{profile}/onboard-2fa-code", dependencies=[Depends(require_api_key)])
async def api_chatgpt_onboard_2fa_code(profile: str, req: ChatGPT2FACodeReq) -> dict[str, Any]:
    session = get_chatgpt_session(profile)
    if not session or session.state != "need_code":
        raise HTTPException(400, "Session khong o state need_code")
    session.pending_code = req.code.strip()
    return {"profile": profile, "state": session.state, "message": "Da nhan ma"}


@app.get("/v1/chatgpt/{profile}/refresh-jwt", dependencies=[Depends(require_api_key)])
async def api_chatgpt_refresh_jwt(profile: str) -> dict[str, Any]:
    """Re-scrape JWT from session, or full re-login if expired.

    Strategy:
    1. Try scraping JWT from existing browser session (fast)
    2. If JWT missing/expired, look up saved credentials from accounts_db
    3. Run full ChatGPT onboard with saved email/password/totp_secret
    4. Return fresh JWT
    """
    # Step 1: Try quick scrape from existing session
    try:
        async with pool.page(profile=profile, headless=True) as page:
            if "chatgpt.com" not in (page.url or ""):
                await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=20_000)
                await asyncio.sleep(3.0)
            from .chatgpt_login import _scrape_chatgpt_token
            token, email, preview = await _scrape_chatgpt_token(page)
            if token:
                logger.info("refresh_jwt: quick scrape OK for %s", profile)
                await _update_chatgpt2api_token(token)   # đẩy JWT mới vào pool chatgpt2api
                return {
                    "profile": profile,
                    "ok": True,
                    "method": "scrape",
                    "access_token": token,
                    "access_token_preview": preview,
                    "captured_email": email,
                }
    except Exception:
        pass

    # Step 2: Quick scrape failed — try full re-login with saved credentials
    acct = resolve_account(profile)
    if not acct:
        return {"profile": profile, "ok": False, "error": "Session expired + no saved credentials found for this profile"}

    logger.info("refresh_jwt: session expired for %s, re-logging in with saved credentials", profile)
    try:
        from .chatgpt_login import start_chatgpt_onboard, get_session as get_chatgpt_session

        # Kill old session
        await pool.close_profile(profile)

        # Start re-login
        session = await start_chatgpt_onboard(
            profile=profile,
            email=acct["email"],
            password=acct["password"],
            totp_secret=acct.get("totp_secret", ""),
        )

        # Wait for completion (poll up to 5 minutes)
        deadline = time.time() + 300
        while time.time() < deadline:
            await asyncio.sleep(2.0)
            s = get_chatgpt_session(profile)
            if not s:
                continue
            if s.state == "success":
                if s.access_token:
                    # Update chatgpt2api accounts pool
                    await _update_chatgpt2api_token(s.access_token)
                    return {
                        "profile": profile,
                        "ok": True,
                        "method": "relogin",
                        "access_token": s.access_token,
                        "access_token_preview": s.access_token_preview,
                        "captured_email": s.captured_email,
                    }
                return {"profile": profile, "ok": False, "error": "Re-login OK but no token scraped"}
            if s.state == "failed":
                return {"profile": profile, "ok": False, "error": s.error or "Re-login failed"}

        return {"profile": profile, "ok": False, "error": "Re-login timed out after 5 min"}
    except Exception as exc:
        logger.exception("refresh_jwt: re-login error for %s", profile)
        return {"profile": profile, "ok": False, "error": str(exc)[:200]}


def _chatgpt2api_auth_key() -> str:
    """Admin key của chatgpt2api (= config.auth_key) để POST /api/accounts. Đọc env
    CHATGPT2API_AUTH_KEY, fallback file /data/chatgpt2api_auth_key (persist qua mount)."""
    k = os.environ.get("CHATGPT2API_AUTH_KEY", "").strip()
    if k:
        return k
    try:
        import pathlib
        f = pathlib.Path("/data/chatgpt2api_auth_key")
        if f.exists():
            return f.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


async def _update_chatgpt2api_token(access_token: str) -> None:
    """POST fresh token to chatgpt2api's accounts pool (kèm admin auth)."""
    try:
        chatgpt2api_url = os.environ.get("CHATGPT2API_URL", "http://chatgpt2api:8100")
        headers = {"Content-Type": "application/json"}
        _ak = _chatgpt2api_auth_key()
        if _ak:
            headers["Authorization"] = f"Bearer {_ak}"
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{chatgpt2api_url}/api/accounts",
                json={"tokens": [access_token]},
                headers=headers,
            )
            if r.status_code < 400:
                logger.info("refresh_jwt: updated chatgpt2api pool OK")
            else:
                logger.warning("refresh_jwt: chatgpt2api returned %s: %s", r.status_code, r.text[:200])
    except Exception as exc:
        logger.warning("refresh_jwt: failed to update chatgpt2api: %s", str(exc)[:120])


@app.post("/v1/chatgpt/{profile}/relogin-via-google", dependencies=[Depends(require_api_key)])
async def api_chatgpt_relogin_via_google(profile: str) -> dict[str, Any]:
    """Force re-login via Google OAuth for an existing ChatGPT profile using saved credentials."""
    acct = resolve_account(profile)
    if not acct:
        raise HTTPException(404, f"No saved credentials for profile '{profile}'")

    await pool.close_profile(profile)
    from .chatgpt_login import start_chatgpt_onboard
    session = await start_chatgpt_onboard(
        profile=profile,
        email=acct["email"],
        password=acct["password"],
        totp_secret=acct.get("totp_secret", ""),
    )
    return {
        **session.to_dict(),
        "note": "Poll /v1/chatgpt/{profile}/onboard-status de theo doi.",
    }


# ── Background token auto-refresh scheduler ──────────────────────────────

_refresh_task: Optional[asyncio.Task] = None
_refresh_running = False


async def _auto_refresh_loop(interval_minutes: int = 30):
    """Background loop that refreshes all saved accounts' tokens periodically."""
    global _refresh_running
    _refresh_running = True
    logger.info("auto_refresh: started (interval=%d min)", interval_minutes)

    while _refresh_running:
        try:
            from .accounts_db import list_accounts as db_list

            accounts = db_list()
            for acct in accounts:
                if not _refresh_running:
                    break
                email = acct["email"]
                profile = "chatgpt-" + email.split("@")[0].replace(".", "-")

                try:
                    try:
                        logger.info("auto_refresh: refreshing %s (profile=%s)", email, profile)
                        # Quick scrape first
                        scrape_ok = False
                        async with pool.page(profile=profile, headless=True) as page:
                            if "chatgpt.com" not in (page.url or ""):
                                await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=20_000)
                                await asyncio.sleep(3.0)
                            from .chatgpt_login import _scrape_chatgpt_token
                            token, _, preview = await _scrape_chatgpt_token(page)
                            if token:
                                await _update_chatgpt2api_token(token)
                                logger.info("auto_refresh: %s OK (scrape)", email)
                                scrape_ok = True
                        if scrape_ok:
                            continue
                    except Exception as exc:
                        logger.warning("auto_refresh: scrape failed for %s: %s", email, str(exc)[:100])

                    # Scrape failed — full re-login
                    try:
                        full = get_account(email)
                        if not full:
                            continue

                        await pool.close_profile(profile)
                        await asyncio.sleep(1.0)

                        session = await start_chatgpt_onboard(
                            profile=profile,
                            email=full["email"],
                            password=full["password"],
                            totp_secret=full.get("totp_secret", ""),
                        )

                        deadline = time.time() + 300
                        while time.time() < deadline and _refresh_running:
                            await asyncio.sleep(2.0)
                            s = get_chatgpt_session(profile)
                            if not s:
                                continue
                            if s.state == "success" and s.access_token:
                                await _update_chatgpt2api_token(s.access_token)
                                logger.info("auto_refresh: %s OK (relogin)", email)
                                break
                            if s.state == "failed":
                                logger.warning("auto_refresh: %s re-login failed: %s", email, s.error)
                                break
                    except Exception as exc:
                        logger.warning("auto_refresh: %s error: %s", email, str(exc)[:100])
                finally:
                    # Đảm bảo tắt ngay trình duyệt sau khi xử lý xong tài khoản này
                    await pool.close_profile(profile)

        except Exception as exc:
            logger.warning("auto_refresh: loop error: %s", str(exc)[:120])

        # Sleep between refresh cycles
        for _ in range(interval_minutes * 60):
            if not _refresh_running:
                break
            await asyncio.sleep(1.0)

    logger.info("auto_refresh: stopped")


@app.post("/v1/chatgpt/auto-refresh/start", dependencies=[Depends(require_api_key)])
async def api_auto_refresh_start(interval_minutes: int = 30) -> dict[str, Any]:
    """Start background auto-refresh for all saved accounts."""
    global _refresh_task, _refresh_running
    if _refresh_running:
        return {"ok": True, "message": "Auto-refresh da chay san", "interval_minutes": interval_minutes}
    _refresh_task = asyncio.create_task(_auto_refresh_loop(interval_minutes))
    return {"ok": True, "message": f"Auto-refresh started (interval={interval_minutes} min)"}


@app.post("/v1/chatgpt/auto-refresh/stop", dependencies=[Depends(require_api_key)])
async def api_auto_refresh_stop() -> dict[str, Any]:
    """Stop background auto-refresh."""
    global _refresh_running, _refresh_task
    _refresh_running = False
    if _refresh_task:
        _refresh_task.cancel()
        _refresh_task = None
    return {"ok": True, "message": "Auto-refresh stopped"}


@app.get("/v1/chatgpt/auto-refresh/status", dependencies=[Depends(require_api_key)])
async def api_auto_refresh_status() -> dict[str, Any]:
    """Check auto-refresh status."""
    return {"running": _refresh_running}


# ── ChatGPT Web (chatgpt.com direct) ─────────────────────────────────────

class ChatGPTWebChatReq(BaseModel):
    profile: str = "chatgpt-default"
    prompt: str
    timeout: int = 90
    headless: bool = True


class ChatGPTWebImageReq(BaseModel):
    profile: str = "chatgpt-default"
    image: str  # data: URL or https URL
    prompt: str = "Phan tich noi dung anh nay mot cach chi tiet."
    timeout: int = 120
    headless: bool = True


@app.get("/v1/chatgpt-web/{profile}/models", dependencies=[Depends(require_api_key)])
async def api_chatgpt_web_models(profile: str) -> dict[str, Any]:
    return await chatgpt_web_list_models(profile=profile, headless=True, timeout=30)


@app.post("/v1/chatgpt-web/chat", dependencies=[Depends(require_api_key)])
async def api_chatgpt_web_chat(req: ChatGPTWebChatReq) -> dict[str, Any]:
    return await chatgpt_web_chat(
        profile=req.profile,
        prompt=req.prompt,
        timeout=req.timeout,
        headless=req.headless,
    )


@app.post("/v1/chatgpt-web/generate-image", dependencies=[Depends(require_api_key)])
async def api_chatgpt_web_generate_image(req: ChatGPTWebChatReq) -> dict[str, Any]:
    return await chatgpt_web_generate_image(
        profile=req.profile,
        prompt=req.prompt,
        timeout=req.timeout,
        headless=req.headless,
    )


@app.post("/v1/chatgpt-web/analyze-image", dependencies=[Depends(require_api_key)])
async def api_chatgpt_web_analyze_image(req: ChatGPTWebImageReq) -> dict[str, Any]:
    return await chatgpt_web_analyze_image(
        profile=req.profile,
        image=req.image,
        prompt=req.prompt,
        timeout=req.timeout,
        headless=req.headless,
    )


# ── Saved Accounts (SQLite) ──────────────────────────────────────────────

class SaveAccountReq(BaseModel):
    email: str
    password: str
    totp_secret: str = ""
    label: str = ""


@app.get("/v1/accounts/saved", dependencies=[Depends(require_api_key)])
async def api_accounts_list() -> list[dict]:
    """List saved accounts (no passwords exposed)."""
    return list_accounts()


@app.get("/v1/accounts/saved/{email}", dependencies=[Depends(require_api_key)])
async def api_accounts_get(email: str) -> dict[str, Any]:
    """Get full account details including password (for auto-login)."""
    acct = get_account(email)
    if not acct:
        raise HTTPException(404, "Account not found")
    return dict(acct)


@app.post("/v1/accounts/saved", dependencies=[Depends(require_api_key)])
async def api_accounts_save(req: SaveAccountReq) -> dict[str, Any]:
    """Save or update a saved account."""
    email = req.email.strip()
    name_lower = email.lower()
    if name_lower.startswith(("google-", "chatgpt-", "claude-", "gemini-", "flow-")):
        raise HTTPException(
            status_code=400,
            detail="Vui lòng nhập địa chỉ email Google hợp lệ (chứa @), không nhập tên Profile (bắt đầu bằng google-, chatgpt-,...)"
        )
    if "@" not in email:
        email = f"{email}@gmail.com"
        
    return save_account(email, req.password, req.totp_secret, req.label)


@app.delete("/v1/accounts/saved/{email}", dependencies=[Depends(require_api_key)])
async def api_accounts_delete(email: str) -> dict[str, Any]:
    """Delete a saved account."""
    ok = delete_account(email)
    if not ok:
        raise HTTPException(404, "Account not found")
    return {"ok": True, "email": email}


@app.delete("/v1/profiles/{profile}", dependencies=[Depends(require_api_key)])
async def api_delete_profile(profile: str) -> dict[str, Any]:
    """Close (if open) then PERMANENTLY delete a profile's user-data-dir.

    chatgpt2api calls this when an account is removed so the on-disk browser
    profile doesn't linger after a UI delete (the orphaned-profile desync).
    Irreversible — the login session for that profile is lost.
    """
    import shutil
    if not profile or "/" in profile or "\\" in profile or profile in (".", ".."):
        raise HTTPException(status_code=400, detail="invalid profile name")
    try:
        await pool.close_profile(profile)
    except Exception:
        logger.warning("close before delete failed for profile=%s", profile)
    profile_dir = settings.data_dir / "profiles" / profile
    if not profile_dir.exists():
        return {"profile": profile, "deleted": False, "reason": "not_found"}
    try:
        shutil.rmtree(profile_dir)
    except Exception as exc:
        logger.exception("Failed to delete profile dir")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    logger.info("deleted profile dir profile=%s", profile)
    return {"profile": profile, "deleted": True}
