"""API tài khoản Grok cho web — Cài đặt › Grok và nhánh Grok ở trang Tài khoản (`api/grok_firefox.py`)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Header

from api.support import require_admin


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/grok-web/tai-khoan")
    async def ds(authorization: str | None = Header(default=None)):
        """Tài khoản theo thứ tự ưu tiên, kèm phiên còn sống không / Firefox đang mở không."""
        require_admin(authorization)
        from api import grok_firefox as gf
        from services.config import config
        bat = ((config.data.get("providers") or {}).get("grok_web") or {}).get("enabled") is not False
        return {"ok": True, "enabled": bat, "tai_khoan": await asyncio.to_thread(gf.trang_thai)}

    @router.post("/api/grok-web/tai-khoan")
    async def sua(body: dict, authorization: str | None = Header(default=None)):
        """body: {viec: them|bat|tat|xoa|dang_nhap|tat_firefox|thu_tu|bat_provider|tat_provider, profile?, label?,
        thu_tu?: [profile]}."""
        require_admin(authorization)
        from api import grok_firefox as gf
        viec, p = str(body.get("viec") or ""), str(body.get("profile") or "")
        try:
            if viec == "them":
                return {"ok": True, "tai_khoan": gf.them(str(body.get("label") or ""))}
            if viec in ("bat", "tat"):
                gf.bat_tat(p, viec == "bat")
            elif viec == "xoa":
                await asyncio.to_thread(gf.xoa, p)
            elif viec == "dang_nhap":
                return {"ok": True, **await asyncio.to_thread(gf.dang_nhap, p)}
            elif viec == "tat_firefox":
                gf._kiem_ten(p)
                await asyncio.to_thread(gf.tat, p)
            elif viec == "thu_tu":
                gf.doi_thu_tu([str(x) for x in body.get("thu_tu") or []])
            elif viec in ("bat_provider", "tat_provider"):
                from services.config import config
                providers = dict(config.data.get("providers") or {})
                providers["grok_web"] = {**(providers.get("grok_web") or {}), "enabled": viec == "bat_provider"}
                config.update({"providers": providers})
            else:
                return {"ok": False, "error": f"Việc lạ: {viec!r}"}
        except (ValueError, RuntimeError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    return router
