"""Captcha-solver same-origin proxy.

The captcha-solver runs inside this same container on 127.0.0.1:8010 (not
published). The web onboarding / reuse-profile UI used to call it directly from
the browser with a configurable URL + API key. Now it calls this same-origin
proxy instead — no URL/key needed in the UI; the captcha key is injected
server-side from the env.

Frontend: fetch("/api/captcha/v1/...") with the dashboard auth key.
"""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response

from api.support import extract_bearer_token
from services.config import config

CAPTCHA_URL = os.getenv("CAPTCHA_SOLVER_URL_INTERNAL", "http://127.0.0.1:8010").rstrip("/")

# Onboarding can take a while; status polls are quick.
_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=180.0, pool=5.0)
_DROP_REQ = {"host", "content-length", "connection", "accept-encoding", "authorization"}
_DROP_RESP = {"content-encoding", "transfer-encoding", "content-length", "connection"}


def _captcha_key() -> str:
    return str(os.getenv("CAPTCHA_SOLVER_API_KEY") or "").strip()


def _authorized(authorization: str | None) -> bool:
    """Allow the dashboard auth key OR the captcha key (cards may send either)."""
    token = extract_bearer_token(authorization)
    if not token:
        return False
    auth_key = str(config.auth_key or "").strip()
    return token == auth_key or (bool(_captcha_key()) and token == _captcha_key())


def create_router() -> APIRouter:
    router = APIRouter()

    @router.api_route("/api/captcha/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def proxy(path: str, request: Request, authorization: str | None = Header(default=None)):
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail={"error": "Unauthorized"})
        url = f"{CAPTCHA_URL}/{path}"
        body = await request.body()
        fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQ}
        key = _captcha_key()
        if key:
            fwd_headers["Authorization"] = f"Bearer {key}"  # inject real captcha key
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            upstream = await client.request(
                request.method, url, params=request.query_params, content=body, headers=fwd_headers,
            )
        resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _DROP_RESP}
        return Response(
            content=upstream.content, status_code=upstream.status_code,
            headers=resp_headers, media_type=upstream.headers.get("content-type"),
        )

    return router
