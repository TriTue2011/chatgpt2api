"""Danh mục model cần tải — thẻ «Model cần tải» ở trang Cài đặt (xem `services.danh_muc_model`)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Header, HTTPException

from api.support import require_admin


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/models/danh-muc")
    async def danh_muc(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import danh_muc_model
        return {"ok": True, "items": danh_muc_model.danh_muc()}

    @router.get("/api/models/tai")
    async def viec_tai(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import tai_model
        return {"ok": True, "items": tai_model.ds()}

    @router.post("/api/models/tai")
    async def tai(body: dict = Body(...), authorization: str | None = Header(default=None)):
        """Nút «Tải xuống»: chạy script tải của ĐÚNG một mục trong danh mục, ở nền."""
        require_admin(authorization)
        from services import tai_model
        try:
            return {"ok": True, "viec": tai_model.bat_dau(str(body.get("lenh") or ""))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
