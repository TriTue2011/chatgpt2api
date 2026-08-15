"""Hàng đợi GPU dùng chung cho các lời gọi LAN từ gateway.

Một RTX 2060 Super 8 GB không chịu được Whisper, Qwen-VL và CTranslate2 cùng
lúc. Khoá phải nằm ở gateway (nơi phát sinh cả ba loại request), không phải
trong từng HTTP client riêng lẻ. ``flock`` còn giữ được khi gateway có nhiều
process; tiến trình chết thì kernel tự nhả khoá.
"""
from __future__ import annotations

import fcntl
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


class QuaTaiGpu(TimeoutError):
    """Chờ quá lâu để dùng GPU chung; caller chọn đường CPU hoặc degradation."""


def _so(name: str, mac_dinh: float, nho_nhat: float = 0.0) -> float:
    try:
        return max(nho_nhat, float(os.getenv(name, str(mac_dinh))))
    except (TypeError, ValueError):
        return mac_dinh


@contextmanager
def giu(nguon: str, *, timeout: float | None = None) -> Iterator[None]:
    """Lấy độc quyền GPU từ gateway đến khi request LAN hoàn tất.

    Không giữ khoá cho xử lý CPU như tách cảnh/cắt SRT. Chỉ giữ lúc remote GPU
    đang nạp hoặc chạy model, nhờ đó việc nhỏ không bị chặn không cần thiết.
    """
    duong = Path(os.getenv("GPU_QUEUE_LOCK", "/tmp/chatgpt2api-gpu.lock"))
    duong.parent.mkdir(parents=True, exist_ok=True)
    cho = _so("GPU_QUEUE_TIMEOUT", 900.0, 1.0) if timeout is None else timeout
    fd = os.open(str(duong), os.O_CREAT | os.O_RDWR, 0o600)
    bat_dau = time.monotonic()
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() - bat_dau >= cho:
                    raise QuaTaiGpu(f"GPU đang bận quá {cho:.0f}s ({nguon})")
                time.sleep(0.1)
        logger.info("GPU queue: %s bắt đầu sau %.1fs", nguon,
                    time.monotonic() - bat_dau)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
            logger.info("GPU queue: %s nhả", nguon)
