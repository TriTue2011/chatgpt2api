"""API cho Camera nhà — tab Cài đặt → Home Assistant.

Sổ camera nằm trong ``config`` (khoá ``cameras``), nên web lưu nó qua đúng đường
lưu cấu hình chung như mọi card khác — ở đây KHÔNG có endpoint CRUD nào cho nó.
Ai được xem camera thì hỏi bộ lọc chức năng của từng kênh (ô tích «📷 Camera
nhà»), không phải một danh sách riêng của camera.

Hai việc web không tự làm được:

``POST /api/camera/test``        chụp thử một camera, trả ảnh xem trước
``POST /api/camera/noi``         đọc một câu ra loa camera (Dahua/Imou, cổng 37777)
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

    @router.post("/api/camera/noi")
    async def noi(body: dict, authorization: str | None = Header(default=None)):
        """Đọc ``cau`` ra loa camera ``ten`` bằng giọng ``giong`` (rỗng = mặc định)."""
        require_admin(authorization)

        from services import loa_camera

        try:
            kq = await asyncio.to_thread(loa_camera.noi, str(body.get("ten") or ""),
                                         str(body.get("cau") or ""), str(body.get("giong") or ""))
        except loa_camera.LoiLoa as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **kq}

    return router
