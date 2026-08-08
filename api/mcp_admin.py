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
from services.ingress_guard import read_body_limited, read_upstream_limited, BodyTooLarge

HUB_URL = os.getenv("MCP_HUB_INTERNAL_URL", "http://127.0.0.1:8005").rstrip("/")

# Trần body cho proxy admin → hub (Studio ingest tài liệu có thể lớn, nhưng
# không vô hạn). 100MB đủ cho tài liệu thực tế, chặn nạp RAM vô tội vạ.
_MAX_PROXY_BODY = 100 * 1024 * 1024

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
        try:
            body = await read_body_limited(request, _MAX_PROXY_BODY)
        except BodyTooLarge:
            return Response(content=b"Payload qua lon (>100MB)", status_code=413)
        fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQ}
        # Đọc response CÓ TRẦN: cap request mà để `upstream.content` nạp không
        # giới hạn thì vẫn còn nguyên đường làm cạn RAM gateway.
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream(
                request.method,
                url,
                params=request.query_params,
                content=body,
                headers=fwd_headers,
            ) as upstream:
                try:
                    payload = await read_upstream_limited(upstream, _MAX_PROXY_BODY)
                except BodyTooLarge:
                    return Response(content=b"Hub tra ve qua lon (>100MB)", status_code=502)
                status = upstream.status_code
                resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _DROP_RESP}
                ctype = upstream.headers.get("content-type")
        return Response(
            content=payload,
            status_code=status,
            headers=resp_headers,
            media_type=ctype,
        )

    return router
