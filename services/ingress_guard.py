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
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Trần body webhook mặc định (JSON điều khiển, không phải upload media).
DEFAULT_MAX_BODY = 2 * 1024 * 1024


class BodyTooLarge(Exception):
    """Body vượt trần khi đọc stream — caller trả 413 / {ok:false}."""


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
