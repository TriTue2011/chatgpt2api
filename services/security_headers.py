"""Security response headers middleware (OWASP A05 misconfiguration)."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "SAMEORIGIN")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Studio chat cần micro (STT) + camera/gallery (đính kèm ảnh).
        # camera=()/microphone=() = CẤM hoàn toàn getUserMedia — trình duyệt
        # báo "Không truy cập được micro" dù user đã bật quyền app/OS.
        h.setdefault(
            "Permissions-Policy",
            "camera=(self), microphone=(self), geolocation=(), payment=()",
        )
        # HSTS only when request is HTTPS (direct or behind TLS-terminating proxy)
        try:
            proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
            if proto == "https":
                h.setdefault(
                    "Strict-Transport-Security",
                    "max-age=31536000; includeSubDomains",
                )
        except Exception:
            pass
        return response
