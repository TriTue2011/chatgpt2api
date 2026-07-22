"""Router DÙNG CHUNG cho hoạt động gần đây + blacklist + danh bạ các kênh chat.

Phục vụ trang quản lý Zalo Cá Nhân (/zalo) và card Zalo / Telegram / Cloudflare
(Settings) — cùng đọc/ghi `services.channel_activity` / `channel_contacts`:
- GET  /api/channels/recent?platform=zalop|zalo|tg  : ai vừa nhắn (tài khoản,
  Chat ID, User ID, tên, tin gần nhất).
- GET  /api/channels/directory?platform=... : danh bạ thread (setting ∪ auto bot).
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

    @router.get("/api/channels/directory")
    async def directory(platform: str = "", limit: int = 300,
                        authorization: str | None = Header(default=None)):
        """Danh bạ thread: bot · Thread ID · loại · tên (admin/lọc + auto bot)."""
        require_admin(authorization)
        platform = platform if platform in _PLATFORMS else ""
        if not platform:
            return {"ok": False, "error": "Cần platform=tg|zalo|zalop", "rows": []}
        from services import channel_contacts as cc
        rows = await asyncio.to_thread(
            cc.list_directory, platform, limit=max(1, min(int(limit or 300), 500)),
        )
        return {"ok": True, "platform": platform, "rows": rows}

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

    # ── Speech Persona theo phiên — 4 phạm vi độc lập (giống webhook forward):
    # admin (= user 1-1), user 1-1, cả NHÓM (fallback), từng USER TRONG NHÓM.
    def _persona_key(platform: str, group_id: str, user_id: str) -> str:
        gid = str(group_id or "").strip()
        uid = str(user_id or "").strip()
        if platform == "ha":  # Home Assistant — một phiên chung, key cố định
            return "ha"
        if platform == "tg":
            return f"{gid}:u{uid}" if (gid and uid) else (gid or uid)
        pre = "zalo_" if platform == "zalo" else "zalop_"
        if gid and uid:
            return f"{pre}{gid}:u{uid}"
        return f"{pre}{gid or uid}" if (gid or uid) else ""

    @router.get("/api/personas")
    async def personas_list(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.agent import persona as P
        rows = await asyncio.to_thread(P.list_all)
        return {"ok": True, "rows": rows,
                "presets": [{"name": n, "desc": d} for n, d in P.PRESETS],
                "options": P.ui_options()}

    @router.post("/api/personas")
    async def personas_set(body: dict,
                           authorization: str | None = Header(default=None)):
        require_admin(authorization)
        platform = str(body.get("platform") or "").strip()
        key = str(body.get("key") or "").strip()
        if not key:
            if platform not in _PLATFORMS and platform != "ha":
                return {"ok": False, "error": "Cần platform tg|zalo|zalop|ha"}
            key = _persona_key(platform, str(body.get("group_id") or ""),
                               str(body.get("user_id") or ""))
        if not key:
            return {"ok": False, "error": "Cần group_id hoặc user_id"}
        from services.agent import persona as P
        sel = body.get("sel") if isinstance(body.get("sel"), dict) else None
        return await asyncio.to_thread(
            lambda: P.set_for(key, preset=str(body.get("preset") or ""),
                              prompt=str(body.get("prompt") or ""), sel=sel))

    @router.post("/api/personas/preview")
    async def personas_preview(body: dict,
                               authorization: str | None = Header(default=None)):
        """Sinh khối persona từ sel KHÔNG lưu — tab Chat gửi per-request."""
        require_admin(authorization)
        from services.agent import persona as P
        sel = body.get("sel") if isinstance(body.get("sel"), dict) else {}
        return {"ok": True, "prompt": await asyncio.to_thread(P.preview, sel)}

    @router.delete("/api/personas")
    async def personas_del(body: dict,
                           authorization: str | None = Header(default=None)):
        require_admin(authorization)
        key = str(body.get("key") or "").strip()
        if not key:
            return {"ok": False, "error": "Thiếu key"}
        from services.agent import persona as P
        return await asyncio.to_thread(P.clear_key, key)

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
