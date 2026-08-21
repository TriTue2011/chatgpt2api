"""Bảo vệ chung cho các webhook ingress (Telegram / Zalo Bot / Zalo Personal).

Hai lỗ DoS lặp ở mọi kênh (báo cáo bảo mật 07/08):
1. `await request.json()` nạp TOÀN BỘ body vào RAM không giới hạn (kiểm
   Content-Length không đủ: request chunked không có header đó vẫn lọt).
2. Mỗi webhook hợp lệ spawn một thread xử lý AI KHÔNG giới hạn → nhiều tin là
   cạn thread/RAM và bung hàng loạt lượt gọi model.

Module này cung cấp:
- `read_json_limited(request, max_bytes)`: đọc stream theo chunk, DỪNG khi vượt
  trần (ném BodyTooLarge) trước khi parse — chặn cả chunked.
- `make_worker_pool(name, max_inflight)`: trả một hàm spawn có SEMAPHORE, giữ
  slot tới khi worker THỰC SỰ chạy xong (release trong finally), vượt trần thì
  bỏ tin (shed-load) thay vì tạo vô hạn thread.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Callable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Trần body webhook mặc định (JSON điều khiển, không phải upload media).
DEFAULT_MAX_BODY = 2 * 1024 * 1024
# Trần cho TOÀN BỘ HTTP app. Cao hơn trần webhook/upload riêng vì
# request chat có thể mang nhiều ảnh base64. Admin có thể hạ qua
# `security.max_request_body_bytes` hoặc env; 0 = tắt có chủ ý.
DEFAULT_MAX_REQUEST_BODY = 256 * 1024 * 1024


class BodyTooLarge(Exception):
    """Body vượt trần khi đọc stream — caller trả 413 / {ok:false}."""


class _RequestBodyOverflow(Exception):
    """Tín hiệu nội bộ: ASGI receive đã vượt trần."""


def max_request_body_bytes() -> int:
    """Trần body HTTP toàn app; env thắng config, giá trị sai dùng mặc định."""
    raw = os.environ.get("CHATGPT2API_MAX_REQUEST_BODY_BYTES")
    if raw in (None, ""):
        try:
            from services.config import config

            security = config.data.get("security") or {}
            raw = security.get("max_request_body_bytes")
        except Exception:
            raw = None
    if raw in (None, ""):
        return DEFAULT_MAX_REQUEST_BODY
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        logger.warning("max_request_body_bytes khong hop le: %r; dung mac dinh", raw)
        return DEFAULT_MAX_REQUEST_BODY


class RequestBodyLimitMiddleware:
    """Chặn body quá trần trước khi FastAPI/route nạp nó vào RAM.

    `Content-Length` chỉ là đường từ chối sớm. Dòng `receive` vẫn được
    đếm thật để chặn request chunked hoặc header khai nhỏ hơn thực tế.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max(0, int(max_body_bytes))

    def _detail(self) -> dict[str, Any]:
        return {
            "error": "Nội dung yêu cầu vượt giới hạn an toàn của máy chủ.",
            "code": "request_body_too_large",
            "max_bytes": self.max_body_bytes,
        }

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(status_code=413, content={"detail": self._detail()})
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.max_body_bytes == 0:
            await self.app(scope, receive, send)
            return

        declared: int | None = None
        for name, value in scope.get("headers", []):
            if name.lower() != b"content-length":
                continue
            try:
                declared = int(value)
            except (TypeError, ValueError):
                declared = None
            break
        if declared is not None and declared > self.max_body_bytes:
            await self._reject(scope, receive, send)
            return

        received = 0
        overflowed = False

        async def limited_receive() -> Message:
            nonlocal overflowed, received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    overflowed = True
                    raise _RequestBodyOverflow
            return message

        async def limited_send(message: Message) -> None:
            # Route có thể biến exception từ receive thành response riêng. Bỏ response
            # đó để client luôn nhận một envelope 413 nhất quán.
            if not overflowed:
                await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except _RequestBodyOverflow:
            pass
        if overflowed:
            await self._reject(scope, receive, send)


async def read_json_limited(request, max_bytes: int = DEFAULT_MAX_BODY) -> Any:
    """Đọc body theo chunk, dừng khi vượt max_bytes, rồi mới JSON parse.

    Ném BodyTooLarge nếu vượt trần; ValueError nếu JSON hỏng. Body rỗng → {}.
    Dùng request.stream() nên chặn được cả chunked transfer (không Content-Length).
    """
    total = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise BodyTooLarge(f"body > {max_bytes} bytes")
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw:
        return {}
    return json.loads(raw)


async def read_body_limited(request, max_bytes: int) -> bytes:
    """Đọc RAW body theo chunk, dừng khi vượt max_bytes (ném BodyTooLarge).

    Cho proxy/upload cần bytes thô (không JSON). Chống body vô hạn nạp RAM kể
    cả chunked (không Content-Length)."""
    total = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise BodyTooLarge(f"body > {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


async def read_upload_limited(upload, max_bytes: int) -> bytes:
    """Đọc một UploadFile theo khối, ném BodyTooLarge khi vượt trần.

    `await upload.read()` không tham số nạp cả file vào RAM — với multipart thì
    Content-Length của request cũng không cho biết từng phần to bao nhiêu.
    """
    total = 0
    chunks: list[bytes] = []
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise BodyTooLarge(f"file > {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


async def read_upstream_limited(resp, max_bytes: int) -> bytes:
    """Đọc response upstream (httpx streaming) theo khối, cắt khi vượt trần.

    Proxy nào cũng phải có: cap request mà không cap response thì upstream độc
    (hoặc bị chiếm) vẫn kéo được RAM của gateway xuống đất.
    """
    total = 0
    chunks: list[bytes] = []
    async for chunk in resp.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise BodyTooLarge(f"upstream response > {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def make_worker_pool(name: str, max_inflight: int) -> Callable[..., bool]:
    """Trả hàm `spawn(fn, *args, **kwargs) -> bool`: chạy fn ở thread nền NHƯNG
    giữ một slot semaphore tới khi fn KẾT THÚC. Hết slot → bỏ (trả False), log.

    Đặt bound ở ĐÚNG điểm spawn worker nặng (không phải quanh hàm điều phối trả
    về ngay), nếu không semaphore nhả trước khi việc thật chạy — vô tác dụng.
    """
    sem = threading.BoundedSemaphore(max_inflight)

    def spawn(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> bool:
        if not sem.acquire(blocking=False):
            logger.warning("%s: quá %d worker đồng thời → bỏ tin (shed-load)",
                           name, max_inflight)
            return False

        def _run() -> None:
            try:
                fn(*args, **kwargs)
            finally:
                sem.release()

        threading.Thread(target=_run, daemon=True).start()
        return True

    return spawn
