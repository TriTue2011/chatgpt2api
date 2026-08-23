"""API cho Camera nhà — tab Cài đặt → Home Assistant.

Sổ camera và cài đặt quyền nằm trong ``config`` (khoá ``cameras`` và
``camera_quyen``), nên web lưu chúng qua đúng đường lưu cấu hình chung như mọi
card khác — ở đây KHÔNG có endpoint CRUD nào cho chúng.

Chỉ hai việc web không tự làm được:

``GET  /api/camera/nguoi-dung``  ai có thể tích cho xem camera, kèm sẵn khoá phiên
``POST /api/camera/test``        chụp thử một camera, trả ảnh xem trước
"""

from __future__ import annotations

import asyncio
import base64
import logging

from fastapi import APIRouter, Header

from api.support import require_admin

logger = logging.getLogger(__name__)

_KENH = (("tg", "Telegram"), ("zalo", "Zalo Bot"), ("zalop", "Zalo Cá Nhân"))


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/camera/nguoi-dung")
    async def nguoi_dung(authorization: str | None = Header(default=None)):
        """Những người có thể được tích cho xem camera.

        CHỈ liệt kê hội thoại 1-1. Nhóm không vào danh sách vì mỗi người trong
        nhóm có khoá phiên riêng, tích cả nhóm sẽ không khớp với ai — và mở
        camera nhà cho cả một nhóm chat cũng không phải thứ nên bấm nhầm một cái
        là xong.
        """
        require_admin(authorization)

        from services.channel_contacts import list_directory, session_key

        def _quet() -> list[dict[str, str]]:
            ra: list[dict[str, str]] = [
                {"key": "ha", "kenh": "Home Assistant", "ten": "Trợ lý trong nhà (Assist / loa)"},
            ]
            for plat, nhan in _KENH:
                for r in list_directory(plat, limit=300):
                    if str(r.get("kind") or "") != "user":
                        continue
                    khoa = session_key(plat, str(r.get("thread_id") or ""))
                    if not khoa:
                        continue
                    ten = str(r.get("name") or "").strip() or str(r.get("thread_id") or "")
                    bot = str(r.get("bot_label") or "").strip()
                    ra.append({"key": khoa, "kenh": nhan,
                               "ten": f"{ten} · bot {bot}" if bot else ten})
            return ra

        try:
            return {"ok": True, "rows": await asyncio.to_thread(_quet)}
        except Exception as exc:
            logger.warning("liệt kê người dùng camera lỗi: %s", exc)
            return {"ok": False, "error": str(exc)[:200], "rows": []}

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
