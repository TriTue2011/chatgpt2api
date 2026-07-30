"""Router kênh Zalo Bot (Zalo Bot API chính thức — xác thực bằng bot token).

- POST /api/zalo-bot/webhook        : Zalo POST tin vào (public, verify header
  `X-Bot-Api-Secret-Token`), trả 200 ngay và xử lý ở luồng nền.
- GET  /api/zalo-bot/status         : (admin) trạng thái + getWebhookInfo từng bot.
- POST /api/zalo-bot/webhook-config : (admin) công tắc bật/tắt webhook.
- POST /api/zalo-bot/apply-mode     : (admin) áp lại đúng chế độ đang cấu hình.

KHÔNG dính gì kênh **Zalo Cá Nhân** (`api/zalo_personal.py` + `zalo-server/`,
zca-js): kênh đó điều khiển tài khoản Zalo của NGƯỜI THẬT qua bot server Node,
kênh này là bot chính thức trên Zalo Bot Platform. Hai kênh chạy song song, khác
token, khác endpoint, không chia sẻ trạng thái nào.

Đường cũ `POST /zalo/webhook` (api/system.py) vẫn giữ để không phá webhook đã
đăng ký ngoài thực địa; nó gọi cùng `services.zalo_bot.process_update` nên tin
đi vào đúng một đường xử lý.
"""
from __future__ import annotations

import asyncio
import logging
import threading

from fastapi import APIRouter, Header, HTTPException, Request

from api.support import require_admin
from services import zalo_bot as zb

logger = logging.getLogger(__name__)


def create_router() -> APIRouter:
    router = APIRouter()

    # ── Webhook receiver (public — Zalo Bot Platform gọi vào) ────────────────
    @router.post("/api/zalo-bot/webhook")
    async def zalo_bot_webhook(request: Request):
        """Docs /docs/webhook/: Zalo POST JSON kèm header X-Bot-Api-Secret-Token
        và ví dụ chính thức trả 403 khi secret lệch → làm đúng vậy.

        Trả 200 NGAY, xử lý ở luồng nền: docs không nói rõ timeout/số lần retry
        của Zalo, nên không được đánh cược rằng nền tảng chờ hết một lượt gọi AI
        (thường vài giây). Chậm mà bị coi là thất bại thì Zalo gửi lại → người
        dùng nhận trả lời trùng.
        """
        # Starlette headers không phân biệt hoa/thường (docs viết
        # `X-Bot-Api-Secret-Token`, SDK zalo-bot-js viết `x-bot-api-secret-token`
        # — cùng một header theo HTTP).
        hdr = request.headers.get("x-bot-api-secret-token", "")
        bot = zb.verify_webhook_secret(hdr)
        if bot is None:
            # Không log giá trị header: nó CHÍNH LÀ secret, vào log là rò.
            logger.warning("Zalo Bot webhook: secret sai → 403")
            raise HTTPException(status_code=403, detail="Bad secret token")
        try:
            body = await request.json()
        except Exception:
            # Body không phải JSON → nhận 200 rồi bỏ qua, đừng để Zalo retry mãi
            # một payload vốn không đọc được.
            return {"ok": True}
        threading.Thread(target=zb.process_update, args=(body, bot), daemon=True).start()
        return {"ok": True}

    # ── Quản trị ─────────────────────────────────────────────────────────────
    @router.get("/api/zalo-bot/status")
    async def status(authorization: str | None = Header(default=None)):
        """Có gọi mạng (getWebhookInfo mỗi bot) → chạy ngoài event loop."""
        require_admin(authorization)
        return await asyncio.to_thread(zb.get_webhook_status)

    @router.post("/api/zalo-bot/webhook-config")
    async def webhook_config(body: dict | None = None,
                             authorization: str | None = Header(default=None)):
        """Công tắc: {"enabled": true} → setWebhook + dừng long-poll;
        {"enabled": false} → deleteWebhook + bật long-poll."""
        require_admin(authorization)
        b = body or {}
        if "enabled" not in b:
            raise HTTPException(status_code=400, detail="Thiếu trường 'enabled'")
        return await asyncio.to_thread(zb.set_webhook_enabled, bool(b.get("enabled")))

    @router.post("/api/zalo-bot/apply-mode")
    async def apply_mode(authorization: str | None = Header(default=None)):
        """Áp lại chế độ đang cấu hình — dùng khi base_url/domain đổi mà webhook
        trên Zalo vẫn trỏ URL cũ (getWebhookInfo lệch expected_webhook_url)."""
        require_admin(authorization)
        return await asyncio.to_thread(zb.apply_mode)

    return router
