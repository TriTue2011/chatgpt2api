"""Đăng nhập cho trình duyệt: đổi khoá API lấy cookie phiên.

Đường vào của bản di trú: web admin hiện giữ khoá trong localStorage. Nó gọi
``POST /auth/browser-login`` một lần với khoá đang có, nhận cookie ``HttpOnly``
cùng một CSRF token, rồi XOÁ khoá khỏi localStorage. Từ đó JavaScript không
còn giữ thứ gì mở được API.

Khoá API vẫn sống nguyên — HA, Zalo và script không liên quan gì tới đây.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.support import _legacy_admin_identity, extract_bearer_token, require_identity
from services.auth_service import auth_service
from services.browser_session import COOKIE_NAME, THOI_HAN_GIAY, kho_phien
from services.browser_session_middleware import bat_phien_trinh_duyet

logger = logging.getLogger(__name__)


class DangNhapRequest(BaseModel):
    key: str = ""


def _la_https(request: Request) -> bool:
    fwd = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return (fwd or request.url.scheme or "").lower() == "https"


def create_router() -> APIRouter:
    router = APIRouter(tags=["browser-auth"])

    @router.post("/auth/browser-login")
    async def browser_login(body: DangNhapRequest, request: Request,
                            authorization: str | None = Header(default=None)):
        """Đổi khoá API lấy cookie phiên.

        Nhận khoá ở body hoặc ở header ``Authorization`` — frontend đang gửi
        Bearer sẵn nên không phải sửa chỗ gọi trước khi di trú.
        """
        if not bat_phien_trinh_duyet():
            return JSONResponse(
                {"detail": {"error": "Phiên trình duyệt chưa được bật "
                                     "(security.browser_sessions_enabled)",
                            "code": "browser_sessions_disabled"}},
                status_code=404)

        khoa = str(body.key or "").strip() or extract_bearer_token(authorization)
        identity = None
        if khoa:
            identity = _legacy_admin_identity(khoa) or auth_service.authenticate(khoa)
        if identity is None:
            return JSONResponse(
                {"detail": {"error": "Khóa không hợp lệ hoặc đã hết hạn",
                            "code": "invalid_key"}},
                status_code=401)

        sid, csrf = kho_phien.tao(identity)
        secure = _la_https(request)
        resp = JSONResponse({
            "ok": True,
            "role": identity.get("role"),
            "name": identity.get("name"),
            # CSRF token KHÔNG phải bí mật kiểu cookie: frontend phải đọc được
            # để gắn vào header. Giá trị nó bảo vệ nằm ở chỗ trang khác không
            # đọc được phản hồi này (same-origin policy).
            "csrf_token": csrf,
            "expires_in": THOI_HAN_GIAY,
            "secure_cookie": secure,
        })
        resp.set_cookie(
            COOKIE_NAME, sid,
            max_age=THOI_HAN_GIAY,
            httponly=True,      # JavaScript không đọc được → XSS không lấy được phiên
            samesite="lax",
            # `Secure` CHỈ khi request thật sự là HTTPS. Đặt cứng Secure sẽ làm
            # trình duyệt vứt cookie trên mọi triển khai LAN chạy HTTP thuần —
            # đăng nhập "thành công" mà vào lại vẫn trắng, không dấu vết. Sau
            # tunnel HTTPS thì cờ này tự bật.
            secure=secure,
            path="/",
        )
        if not secure:
            logger.warning({"event": "phien_trinh_duyet_cookie_khong_secure",
                            "msg": "request không phải HTTPS nên cookie không có cờ Secure"})
        logger.info({"event": "phien_trinh_duyet_tao",
                     "role": identity.get("role"), "secure": secure})
        return resp

    @router.post("/auth/browser-logout")
    async def browser_logout(request: Request):
        sid = request.cookies.get(COOKIE_NAME, "")
        da_thu_hoi = kho_phien.thu_hoi(sid) if sid else False
        resp = JSONResponse({"ok": True, "revoked": da_thu_hoi})
        resp.delete_cookie(COOKIE_NAME, path="/")
        return resp

    @router.get("/auth/browser-session")
    async def browser_session(authorization: str | None = Header(default=None)):
        """Ai đang đăng nhập. Dùng lúc tải trang để biết còn phiên hay không."""
        identity = require_identity(authorization)
        return {"ok": True, "id": identity.get("id"), "name": identity.get("name"),
                "role": identity.get("role"),
                "nguon": identity.get("nguon") or "bearer"}

    return router
