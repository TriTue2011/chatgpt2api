"""Định kỳ tự tìm & nạp SGK cho toàn bộ lớp × môn.

Cùng khuôn với ``codex_refresh_scheduler``: một thread nền, ngủ theo chu kỳ,
khởi động từ ``api/app.py``. Khác ở chỗ việc này NẶNG (tìm web + tải PDF cả
trăm MB) nên:

- **Mặc định TẮT** (``sgk_autofill_enabled``) — bật ở Cài đặt, hoặc bấm nút
  chạy ngay ở trang Giáo viên.
- Chu kỳ tính bằng NGÀY (``sgk_autofill_interval_days``, mặc định 7), không
  phải giờ — sách giáo khoa không đổi hằng ngày.
- Mỗi vòng chỉ nạp tổ hợp CHƯA có (``skip_done=True``), nên chạy định kỳ chỉ
  vá dần chỗ trống chứ không tải lại thứ đã có.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_started = False
_stop = threading.Event()

_DEFAULT_INTERVAL_DAYS = 7
# Chờ server lên hẳn rồi mới đụng tới mạng.
_BOOT_DELAY_SECONDS = 120


def _cfg() -> dict[str, Any]:
    try:
        from services.config import config
        return config.data or {}
    except Exception:
        return {}


def is_enabled() -> bool:
    return bool(_cfg().get("sgk_autofill_enabled", False))


def interval_seconds() -> float:
    try:
        days = float(_cfg().get("sgk_autofill_interval_days", _DEFAULT_INTERVAL_DAYS) or 0)
    except (TypeError, ValueError):
        days = _DEFAULT_INTERVAL_DAYS
    if days <= 0:
        days = _DEFAULT_INTERVAL_DAYS
    return days * 86400.0


def _run_once() -> None:
    from services.agent import sgk_autofill as af
    if af.is_running():
        logger.info({"event": "sgk_autofill_skip", "reason": "đang chạy"})
        return
    kinds = _cfg().get("sgk_autofill_kinds") or ["sgk"]
    for kind in kinds:
        if _stop.is_set():
            return
        st = af.run(kind=str(kind), skip_done=True)
        c = st.get("counts") or {}
        logger.info({"event": "sgk_autofill_round_done", "kind": kind,
                     "ok": c.get("ok"), "no_source": c.get("no_source"),
                     "failed": c.get("failed"), "skipped": c.get("skipped")})
        if c.get("ok"):
            try:
                from services.notifier import notify_admin
                notify_admin(af.summary(st))
            except Exception:
                pass


def _loop() -> None:
    _stop.wait(_BOOT_DELAY_SECONDS)
    while not _stop.is_set():
        # Đọc cờ MỖI vòng: bật/tắt ở Cài đặt có hiệu lực ngay vòng kế,
        # không cần khởi động lại container.
        if is_enabled():
            try:
                _run_once()
            except Exception as exc:
                logger.warning({"event": "sgk_autofill_round_error", "error": str(exc)[:200]})
        _stop.wait(interval_seconds())


def start() -> None:
    """Bật thread nền (idempotent — gọi nhiều lần chỉ chạy một cái)."""
    global _started
    if _started:
        return
    _started = True
    _stop.clear()
    threading.Thread(target=_loop, name="sgk-autofill-scheduler", daemon=True).start()
    logger.info({"event": "sgk_autofill_scheduler_started",
                 "enabled": is_enabled(),
                 "interval_days": interval_seconds() / 86400.0})


def stop() -> None:
    _stop.set()


def status() -> dict[str, Any]:
    from services.agent import sgk_autofill as af
    return {
        "scheduler_started": _started,
        "enabled": is_enabled(),
        "interval_days": interval_seconds() / 86400.0,
        "running_now": af.is_running(),
        "last": af.read_state(),
    }


__all__ = ["start", "stop", "status", "is_enabled", "interval_seconds"]
