"""Router kênh Zalo Bot (Zalo Bot API chính thức — xác thực bằng bot token).

- POST /api/zalo-bot/webhook        : Zalo POST tin vào (public, verify header
  `X-Bot-Api-Secret-Token`), trả 200 ngay và xử lý ở luồng nền.
- POST /api/zalo-bot/webhook/{bot_id} : cùng việc, mỗi bot MỘT URL riêng — đây là
  đường `setWebhook` đăng ký. Đường không có bot_id vẫn nhận (webhook cũ ngoài
  thực địa không bị phá). bot_id chỉ để ĐỐI CHIẾU, quyền vẫn do secret quyết định.
- GET  /api/zalo-bot/status         : (admin) trạng thái + getWebhookInfo từng bot.
- POST /api/zalo-bot/webhook-config : (admin) công tắc bật/tắt webhook.
- POST /api/zalo-bot/apply-mode     : (admin) áp lại đúng chế độ đang cấu hình.
- POST /api/zalo-bot/send           : (admin) GỬI RA — cảnh báo + ảnh cục bộ.
  Dành cho Home Assistant: HA POST thẳng tệp ảnh lên, không cần mở HA ra
  Internet và không cần tự dựng URL công khai.

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

from fastapi import (APIRouter, File, Form, Header, HTTPException, Request,
                     UploadFile)

from api.support import require_admin
from services import zalo_bot as zb

logger = logging.getLogger(__name__)

# Bound worker + body cap nay ở tầng CHUNG: process_update (services.zalo_bot)
# tự bound qua _zalo_worker khi spawn _process_message, và read_json_limited
# chặn body vô hạn (kể cả chunked). api chỉ cần: xác thực → đọc body giới hạn →
# process_update (non-blocking, tự spawn worker có bound). Bỏ semaphore ở đây
# vì nó nhả trước khi worker thật chạy (process_update trả về ngay) — vô tác dụng.
from services.ingress_guard import read_json_limited, BodyTooLarge


async def _read_body_or_413(request: Request) -> dict:
    try:
        return await read_json_limited(request)
    except BodyTooLarge:
        raise HTTPException(status_code=413, detail="Payload quá lớn")
    except HTTPException:
        raise
    except Exception:
        return {}


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
        # XÁC THỰC secret TRƯỚC khi đọc body (không tốn RAM cho req chưa xác thực).
        hdr = request.headers.get("x-bot-api-secret-token", "")
        bot = zb.verify_webhook_secret(hdr)
        if bot is None:
            # Không log giá trị header: nó CHÍNH LÀ secret, vào log là rò.
            logger.warning("Zalo Bot webhook: secret sai → 403")
            raise HTTPException(status_code=403, detail="Bad secret token")
        body = await _read_body_or_413(request)   # stream cap 2MB (cả chunked)
        if not body:
            return {"ok": True}
        zb.process_update(body, bot)   # non-blocking; worker AI đã bound trong đó
        return {"ok": True}

    @router.post("/api/zalo-bot/webhook/{bot_id}")
    async def zalo_bot_webhook_theo_bot(bot_id: str, request: Request):
        """Cùng việc như trên, nhưng mỗi bot MỘT URL: `…/webhook/<bot_id>`.

        Vì sao cần dù secret trong header đã phân biệt được bot: nhiều bot dùng
        chung một URL thì người vận hành không nhìn ra URL nào của bot nào, và
        getWebhookInfo của mọi bot trả về cùng một chuỗi nên không soi được cái
        nào lệch. Có `<bot_id>` trên URL thì đọc là thấy.

        `bot_id` KHÔNG phải thứ để xác thực — nó chỉ dùng để đối chiếu. Quyền vẫn
        do secret trong header quyết định, y như đường không có bot_id: bot_id là
        phần công khai của token, ai cũng đoán được.
        """
        hdr = request.headers.get("x-bot-api-secret-token", "")
        bot = zb.verify_webhook_secret(hdr)
        if bot is None:
            logger.warning("Zalo Bot webhook[%s]: secret sai → 403", bot_id[:16])
            raise HTTPException(status_code=403, detail="Bad secret token")
        # Lệch thì CHỈ ghi log rồi xử lý tiếp: secret đã đúng nên tin là thật;
        # từ chối ở đây chỉ làm mất tin khi ai đó vừa đổi token/đường dẫn.
        that = zb._bot_public_id(bot)
        if bot_id and that and bot_id != that:
            logger.warning("Zalo Bot webhook: URL ghi bot_id=%s nhưng secret là của %s",
                           bot_id[:16], that[:16])
        body = await _read_body_or_413(request)
        if not body:
            return {"ok": True}
        zb.process_update(body, bot)
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

    # ── Gửi RA: cảnh báo + ảnh, cho Home Assistant ───────────────────────────

    @router.post("/api/zalo-bot/send")
    async def send_out(
        chat_id: str = Form(default=""),
        text: str = Form(default=""),
        photo_url: str = Form(default=""),
        photo: UploadFile | None = File(default=None),
        authorization: str | None = Header(default=None),
    ):
        """Gửi cảnh báo (và ảnh) ra Zalo Bot. Nhận multipart để HA POST thẳng tệp.

        Vì sao cần endpoint này thay vì để HA gọi thẳng Zalo Bot API: `sendPhoto`
        đòi ảnh là URL http(s) CÔNG KHAI — Zalo tự đi tải về. Ảnh camera của HA
        nằm ở `/config/www/...` trong mạng LAN, Zalo ngoài Internet không tải
        được. Server này đã phục vụ `/images/` công khai không cần token, nên chỗ
        hợp lý để nối là ở đây; HA chỉ cần một lời gọi và không phải mở ra ngoài.

        `chat_id` để trống → gửi cho admin của bot đang hoạt động.
        """
        require_admin(authorization)
        # Đọc ảnh có TRẦN (chống upload khổng lồ làm cạn RAM) thay vì read() trần.
        from api.support import read_upload_limited
        raw = await read_upload_limited(photo) if photo is not None else b""
        if not raw and not photo_url and not text.strip():
            raise HTTPException(status_code=400,
                                detail="Cần ít nhất một trong: text, photo, photo_url")

        def _gui() -> dict:
            cid = (chat_id or "").strip() or zb._resolve_admin_delivery()[0]
            if not cid:
                raise HTTPException(
                    status_code=400,
                    detail="Chưa có chat_id: truyền chat_id, hoặc nhắn cho bot một "
                           "lần để nó biết admin là ai")
            anh = photo_url.strip()
            if raw:
                anh = _luu_anh_lay_duong_dan(raw)
            if anh:
                # send_photo tự ghép base_url CÔNG KHAI khi nhận đường dẫn tương
                # đối. PHẢI đưa đường dẫn, KHÔNG đưa URL đầy đủ của
                # save_image_bytes: URL đó dựng từ `config.base_url` =
                # http://172.16.10.38:3030 (địa chỉ LAN), và _ensure_public_photo_url
                # chỉ viết lại localhost/127.0.0.1 — LAN thì nó giữ nguyên rồi
                # Zalo im lặng không tải được ảnh.
                r = zb.send_photo(cid, anh, caption=text.strip())
                return {"ok": bool(r.get("ok")), "kieu": "photo",
                        "chat_id": cid, "ket_qua": r}
            r = zb.send_message(cid, text.strip(), rich=False)
            return {"ok": bool(r.get("ok")), "kieu": "text",
                    "chat_id": cid, "ket_qua": r}

        return await asyncio.to_thread(_gui)

    return router


def _luu_anh_lay_duong_dan(raw: bytes) -> str:
    """Lưu ảnh vào kho công khai, trả ĐƯỜNG DẪN tương đối `/images/...`.

    `save_image_bytes` luôn đặt tên `.png` bất kể nội dung. Gửi JPEG vào đó là
    tệp `.png` chứa byte JPEG: StaticFiles đoán content-type theo phần mở rộng
    nên trả `image/png` cho một ảnh JPEG, và Zalo có thể từ chối. Nên ảnh không
    phải PNG thì chuyển thật sang PNG, để tên tệp khớp nội dung.
    """
    from urllib.parse import urlparse

    from services.protocol.conversation import save_image_bytes

    # Kiểm TRƯỚC khi mở: `Image.open(...).convert()` giải nén thật, nên ảnh bom
    # nén sẽ nổ ở đúng dòng đó nếu không chặn từ đây.
    from services.image_guard import ImageRejected, kiem_anh
    try:
        kiem_anh(raw, ten="ảnh gửi Zalo")
    except ImageRejected as exc:
        raise HTTPException(status_code=400, detail=exc.ly_do) from exc

    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        try:
            import io

            from PIL import Image
            buf = io.BytesIO()
            Image.open(io.BytesIO(raw)).convert("RGB").save(buf, format="PNG")
            raw = buf.getvalue()
        except Exception as exc:
            raise HTTPException(status_code=400,
                                detail=f"Không đọc được ảnh: {exc}") from exc
    return urlparse(save_image_bytes(raw)).path
