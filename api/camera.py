"""API cho Camera nhà — tab Cài đặt → Home Assistant.

Sổ camera nằm trong ``config`` (khoá ``cameras``), nên web lưu nó qua đúng đường
lưu cấu hình chung như mọi card khác — ở đây KHÔNG có endpoint CRUD nào cho nó.
Ai được xem camera thì hỏi bộ lọc chức năng của từng kênh (ô tích «📷 Camera
nhà»), không phải một danh sách riêng của camera.

Chỉ một việc web không tự làm được:

``POST /api/camera/test``        chụp thử một camera, trả ảnh xem trước
"""

from __future__ import annotations

import asyncio
import base64
import logging

from fastapi import APIRouter, Header

from api.support import require_admin

logger = logging.getLogger(__name__)


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/camera/test")
    async def test(body: dict, authorization: str | None = Header(default=None)):
        """Chụp thử một camera đã lưu và trả về ảnh xem trước.

        Bấm Lưu xong mới test được: hàm chụp đọc sổ trong config, không nhận
        tham số rời. Nói rõ trong UI để người dùng không tưởng nút hỏng.
        """
        require_admin(authorization)

        from services import camera_nha

        ten = str(body.get("ten") or "").strip()
        if not ten:
            return {"ok": False, "error": "Chưa chọn camera nào để thử."}
        try:
            ten_that, jpeg = await asyncio.to_thread(camera_nha.chup, ten)
        except camera_nha.LoiCamera as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            logger.warning("test camera '%s' lỗi: %s", ten, exc)
            return {"ok": False, "error": str(exc)[:200]}
        return {
            "ok": True,
            "ten": ten_that,
            "bytes": len(jpeg),
            "anh": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii"),
        }

    return router
