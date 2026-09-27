"""Danh mục model cần tải — thẻ «Model cần tải» ở trang Cài đặt (xem `services.danh_muc_model`)."""
from __future__ import annotations

from fastapi import APIRouter, Header

from api.support import require_admin


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/models/danh-muc")
    async def danh_muc(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import danh_muc_model
        return {"ok": True, "items": danh_muc_model.danh_muc()}

    return router
