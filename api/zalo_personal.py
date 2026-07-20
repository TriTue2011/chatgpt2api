"""Router kênh Zalo Cá Nhân (bot server zca-js) — webhook receiver + API quản lý.

- POST /zalo-personal/webhook  : bot server gọi (verify ?secret=), trả ngay 200.
- /api/zalo-personal/*         : trang quản lý web (require_admin) — trạng thái,
  QR đăng nhập, webhook per-account, proxy, danh bạ, test gửi/HA, passthrough.

HA muốn dùng custom integration smarthomeblack/zalo_bot thì trỏ THẲNG vào bot
server (http://<ip>:3001) — các endpoint ở đây chỉ phục vụ web UI chatgpt2api.
"""
from __future__ import annotations

import asyncio
import logging
import threading

from fastapi import APIRouter, Header, HTTPException, Request

from api.support import require_admin
from services import zalo_personal as zp

logger = logging.getLogger(__name__)


def create_router() -> APIRouter:
    router = APIRouter()

    # ── Webhook receiver (public — bot server gọi qua LAN) ──────────────────
    @router.post("/zalo-personal/webhook")
    async def zalo_personal_webhook(request: Request):
        secret = request.query_params.get("secret", "")
        event = request.query_params.get("event", "message")
        if secret != zp.webhook_secret():
            logger.warning("Zalo personal webhook: secret sai")
            raise HTTPException(status_code=403, detail="Bad secret")
        try:
            body = await request.json()
        except Exception:
            return {"ok": False}
        threading.Thread(target=zp.handle_event, args=(body, event), daemon=True).start()
        return {"ok": True}

    # ── Quản trị (web UI) ────────────────────────────────────────────────────
    @router.get("/api/zalo-personal/status")
    async def status(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return await asyncio.to_thread(zp.get_status)

    @router.post("/api/zalo-personal/login-qr")
    async def login_qr(body: dict | None = None, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        proxy = str((body or {}).get("proxy") or "").strip()
        return await asyncio.to_thread(zp.login_qr, proxy)

    @router.get("/api/zalo-personal/accounts")
    async def accounts(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return await asyncio.to_thread(zp.get_accounts)

    @router.get("/api/zalo-personal/webhooks")
    async def webhooks(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return await asyncio.to_thread(zp.get_webhooks)

    @router.post("/api/zalo-personal/webhook-config")
    async def set_webhook(body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        own_id = str(body.get("ownId") or "").strip()
        if not own_id:
            raise HTTPException(status_code=400, detail="Thiếu ownId")
        return await asyncio.to_thread(
            zp.set_account_webhook, own_id,
            str(body.get("messageWebhookUrl") or "").strip(),
            str(body.get("groupEventWebhookUrl") or "").strip(),
            str(body.get("reactionWebhookUrl") or "").strip())

    @router.delete("/api/zalo-personal/webhook-config/{own_id}")
    async def del_webhook(own_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return await asyncio.to_thread(zp.delete_account_webhook, own_id)

    @router.post("/api/zalo-personal/webhook-config/auto")
    async def auto_webhook(authorization: str | None = Header(default=None)):
        """Đăng ký lại webhook mọi tài khoản về gateway (nút 'Dùng chatgpt2api')."""
        require_admin(authorization)
        return await asyncio.to_thread(zp.ensure_webhooks, True)

    @router.get("/api/zalo-personal/proxies")
    async def proxies(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return await asyncio.to_thread(zp.get_proxies)

    @router.post("/api/zalo-personal/proxies")
    async def add_proxy(body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return await asyncio.to_thread(zp.add_proxy, str(body.get("proxyUrl") or "").strip())

    @router.delete("/api/zalo-personal/proxies")
    async def del_proxy(body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return await asyncio.to_thread(zp.remove_proxy, str(body.get("proxyUrl") or "").strip())

    @router.post("/api/zalo-personal/test-send")
    async def test_send(body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        thread_id = str(body.get("thread_id") or "").strip()
        if not thread_id:
            raise HTTPException(status_code=400, detail="Thiếu thread_id")
        return await asyncio.to_thread(
            zp.send_message, thread_id,
            str(body.get("text") or "Test từ chatgpt2api 🤖"),
            int(body.get("type") or 0), str(body.get("account") or "").strip())

    @router.post("/api/zalo-personal/test-ha")
    async def test_ha(body: dict | None = None, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        b = body or {}
        return await asyncio.to_thread(
            zp.test_ha_forward,
            str(b.get("url") or "").strip(),
            b.get("filters") if isinstance(b.get("filters"), list) else None,
        )

    @router.post("/api/zalo-personal/friends")
    async def friends(body: dict | None = None, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        acc = str((body or {}).get("account") or "").strip() or zp._account_for_send()
        if not acc:
            return {"ok": False, "error": "Chưa có tài khoản Zalo nào đăng nhập"}
        return await asyncio.to_thread(
            zp.proxy_raw, "POST", "/api/getAllFriendsByAccount", {"accountSelection": acc}, 30.0)

    @router.post("/api/zalo-personal/groups")
    async def groups(body: dict | None = None, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        acc = str((body or {}).get("account") or "").strip() or zp._account_for_send()
        if not acc:
            return {"ok": False, "error": "Chưa có tài khoản Zalo nào đăng nhập"}
        return await asyncio.to_thread(
            zp.proxy_raw, "POST", "/api/getAllGroupsByAccount", {"accountSelection": acc}, 30.0)

    # ── Passthrough: gọi endpoint bất kỳ của bot server (trang quản lý nâng cao)
    @router.api_route("/api/zalo-personal/proxy/{path:path}",
                      methods=["GET", "POST", "PUT", "DELETE"])
    async def passthrough(path: str, request: Request,
                          authorization: str | None = Header(default=None)):
        require_admin(authorization)
        body = None
        if request.method in {"POST", "PUT", "DELETE"}:
            try:
                body = await request.json()
            except Exception:
                body = None
        return await asyncio.to_thread(zp.proxy_raw, request.method, "/" + path, body, 60.0)

    return router
