from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.support import require_admin
from services.register_service import register_service

logger = logging.getLogger(__name__)


class RegisterConfigRequest(BaseModel):
    mail: dict | None = None
    proxy: str | None = None
    total: int | None = None
    threads: int | None = None
    mode: str | None = None
    target_quota: int | None = None
    target_available: int | None = None
    check_interval: int | None = None


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/register")
    async def get_register_config(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.get()}

    @router.post("/api/register")
    async def update_register_config(body: RegisterConfigRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.update(body.model_dump(exclude_none=True))}

    @router.post("/api/register/start")
    async def start_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.start()}

    @router.post("/api/register/stop")
    async def stop_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.stop()}

    @router.post("/api/register/reset")
    async def reset_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.reset()}

    def _phien_bam(request: Request) -> str:
        """Hash của session-id trong cookie, hoặc "" nếu đi bằng Bearer.

        Vé được RÀNG vào phiên đã xin nó: ai đọc được vé trong 60 giây (log
        proxy, lịch sử trình duyệt) cũng không mở được stream từ máy khác.
        """
        try:
            from services.browser_session import COOKIE_NAME, _bam
            sid = request.cookies.get(COOKIE_NAME, "")
            return _bam(sid) if sid else ""
        except Exception:
            return ""

    @router.post("/api/register/events-ticket")
    async def register_events_ticket(request: Request,
                                     authorization: str | None = Header(default=None)):
        """Xin vé mở SSE. Xác thực bằng header như mọi endpoint khác."""
        identity = require_admin(authorization)
        from services.sse_ticket import kho_ve
        ve, ttl = kho_ve.cap(identity, _phien_bam(request))
        return {"ok": True, "ticket": ve, "expires_in": ttl}

    @router.get("/api/register/events")
    async def register_events(request: Request, token: str = "", ticket: str = ""):
        """SSE. Ưu tiên vé; `token=` giữ lại để không cắt client cũ.

        `EventSource` không gửi được header tuỳ ý nên đường này buộc phải nhận
        xác thực qua query string — mà query string thì vào access log, lịch sử
        trình duyệt và header Referer. Vé sống 60 giây và dùng một lần, nên lộ
        cũng gần như vô hại; còn `token=` chính là KHOÁ ADMIN, lộ là mất tất cả.
        """
        if ticket:
            from services.sse_ticket import kho_ve
            if kho_ve.dung(ticket, _phien_bam(request)) is None:
                raise HTTPException(
                    status_code=401,
                    detail={"error": "Vé không hợp lệ, đã dùng hoặc đã hết hạn",
                            "code": "sse_ticket_invalid"})
        else:
            # Đường cũ — còn để client chưa cập nhật vẫn chạy. Tắt hẳn được
            # bằng `security.sse_legacy_token_disabled` khi đã chắc không còn
            # ai dùng; không có công tắc thì "tạm thời" sẽ thành vĩnh viễn.
            from services.config import config as _cfg
            _sec = _cfg.get().get("security")
            if isinstance(_sec, dict) and _sec.get("sse_legacy_token_disabled"):
                raise HTTPException(
                    status_code=401,
                    detail={"error": "Đường ?token= đã tắt — hãy xin vé ở "
                                     "/api/register/events-ticket",
                            "code": "sse_legacy_token_disabled"})
            logger.warning({"event": "sse_token_trong_url",
                            "msg": "client còn dùng ?token= (khoá admin trong URL); "
                                   "hãy chuyển sang /api/register/events-ticket"})
            require_admin(f"Bearer {token}")

        async def stream():
            last = ""
            while True:
                payload = json.dumps(register_service.get(), ensure_ascii=False)
                if payload != last:
                    last = payload
                    yield f"data: {payload}\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return router
