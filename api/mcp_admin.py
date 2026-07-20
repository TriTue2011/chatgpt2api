"""MCP Hub admin proxy.

The vn-mcp-hub now runs as an internal process inside the same container
(127.0.0.1:8005) instead of a separate Docker service. Its admin/studio API
(`/api/studio/*`, `/api/rag/*`, `/api/telegram/*`) used to be reached through
the standalone Studio page at :8005/studio.

This router exposes a single authenticated passthrough so the web MCP tab can
drive all of those endpoints on the same origin — no separate Studio, no logic
duplicated here. Frontend calls e.g. `/api/mcp/hub/api/studio/sources`.
"""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Header, Request
from fastapi.responses import Response

from api.support import require_admin

HUB_URL = os.getenv("MCP_HUB_INTERNAL_URL", "http://127.0.0.1:8005").rstrip("/")

# RAG ingest / AI source-analysis can legitimately take a minute or two.
_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=180.0, pool=5.0)

# Hop-by-hop / length headers we must not copy verbatim across the proxy.
_DROP_REQ = {"host", "content-length", "connection", "accept-encoding"}
_DROP_RESP = {"content-encoding", "transfer-encoding", "content-length", "connection"}


def create_router() -> APIRouter:
    router = APIRouter()

    @router.api_route(
        "/api/mcp/hub/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )
    async def proxy(path: str, request: Request, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        url = f"{HUB_URL}/{path}"
        body = await request.body()
        fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQ}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            upstream = await client.request(
                request.method,
                url,
                params=request.query_params,
                content=body,
                headers=fwd_headers,
            )
        resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _DROP_RESP}
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=resp_headers,
            media_type=upstream.headers.get("content-type"),
        )

    return router
