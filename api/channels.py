"""Router DÙNG CHUNG cho hoạt động gần đây + blacklist các kênh chat.

Phục vụ trang quản lý Zalo Cá Nhân (/zalo) và card Zalo / Telegram / Cloudflare
(Settings) — cùng đọc/ghi `services.channel_activity`:
- GET  /api/channels/recent?platform=zalop|zalo|tg  : ai vừa nhắn (tài khoản,
  Chat ID, User ID, tên, tin gần nhất).
- GET  /api/channels/blacklist?platform=...&account=... : danh sách bị loại
  (account = bot_id/ownId; trống = tất cả mục kênh).
- POST /api/channels/blacklist {platform,id,kind,name,account}: thêm.
- DELETE /api/channels/blacklist {platform,id,account}: gỡ.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Header

from api.support import require_admin
from services import channel_activity as ca

_PLATFORMS = {"zalop", "zalo", "tg"}


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/channels/recent")
    async def recent(platform: str = "", limit: int = 100,
                     authorization: str | None = Header(default=None)):
        require_admin(authorization)
        platform = platform if platform in _PLATFORMS else ""
        rows = await asyncio.to_thread(ca.recent, platform, max(1, min(int(limit or 100), 300)))
        return {"ok": True, "rows": rows}

    @router.get("/api/channels/blacklist")
    async def get_blacklist(platform: str = "", account: str = "",
                            authorization: str | None = Header(default=None)):
        require_admin(authorization)
        platform = platform if platform in _PLATFORMS else ""
        items = await asyncio.to_thread(
            ca.get_blacklist, platform, str(account or "").strip(),
        )
        return {"ok": True, "items": items}

    @router.post("/api/channels/blacklist")
    async def add_blacklist(body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        platform = str(body.get("platform") or "").strip()
        entry_id = str(body.get("id") or "").strip()
        if platform not in _PLATFORMS or not entry_id:
            return {"ok": False, "error": "Thiếu/không hợp lệ platform hoặc id"}
        return await asyncio.to_thread(
            ca.add_blacklist, platform, entry_id,
            str(body.get("kind") or "").strip(),
            str(body.get("name") or "").strip(),
            True,
            str(body.get("account") or "").strip(),
        )

    @router.delete("/api/channels/blacklist")
    async def del_blacklist(body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        platform = str(body.get("platform") or "").strip()
        entry_id = str(body.get("id") or "").strip()
        if platform not in _PLATFORMS or not entry_id:
            return {"ok": False, "error": "Thiếu/không hợp lệ platform hoặc id"}
        return await asyncio.to_thread(
            ca.remove_blacklist, platform, entry_id,
            str(body.get("account") or "").strip(),
        )

    return router
