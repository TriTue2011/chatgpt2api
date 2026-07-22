"""Rate-limit + audit cho POST /auth/login — chặn brute-force AUTH_KEY.

In-memory, per-process (đủ cho 1 container c2a). Config optional
``security.login_max_failures`` (default 10), ``security.login_window_sec``
(default 900), ``security.login_lockout_sec`` (default 900).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import HTTPException

logger = logging.getLogger(__name__)

_lock = threading.Lock()
# ip -> deque of failure timestamps
_failures: dict[str, Deque[float]] = defaultdict(deque)
# ip -> lockout_until epoch
_lockouts: dict[str, float] = {}


def _cfg_int(key: str, default: int) -> int:
    try:
        from services.config import config
        sec = config.get().get("security")
        if isinstance(sec, dict) and sec.get(key) is not None:
            return int(sec[key])
    except Exception:
        pass
    return default


def max_failures() -> int:
    return max(3, _cfg_int("login_max_failures", 10))


def window_sec() -> float:
    return float(max(60, _cfg_int("login_window_sec", 900)))


def lockout_sec() -> float:
    return float(max(60, _cfg_int("login_lockout_sec", 900)))


def client_ip_from_request(request) -> str:  # noqa: ANN001 — FastAPI Request
    """Ưu tiên X-Forwarded-For (sau reverse proxy), fallback client.host."""
    try:
        xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if xff:
            return xff[:128]
    except Exception:
        pass
    try:
        if request.client and request.client.host:
            return str(request.client.host)[:128]
    except Exception:
        pass
    return "unknown"


def check_allowed(ip: str) -> None:
    """Ném HTTP 429 nếu IP đang bị lockout."""
    now = time.time()
    with _lock:
        until = _lockouts.get(ip) or 0.0
        if until > now:
            remain = int(until - now)
            logger.warning("login_guard lockout ip=%s remain=%ss", ip, remain)
            raise HTTPException(
                status_code=429,
                detail={"error": f"Quá nhiều lần đăng nhập sai. Thử lại sau {remain}s."},
            )
        if until and until <= now:
            _lockouts.pop(ip, None)


def record_failure(ip: str) -> None:
    now = time.time()
    win = window_sec()
    with _lock:
        q = _failures[ip]
        q.append(now)
        while q and q[0] < now - win:
            q.popleft()
        n = len(q)
        logger.warning("login_guard fail ip=%s count=%s/%s", ip, n, max_failures())
        if n >= max_failures():
            _lockouts[ip] = now + lockout_sec()
            q.clear()
            logger.warning(
                "login_guard LOCKOUT ip=%s for %ss", ip, int(lockout_sec())
            )


def record_success(ip: str) -> None:
    with _lock:
        _failures.pop(ip, None)
        _lockouts.pop(ip, None)


def reset_for_tests() -> None:
    """Chỉ dùng trong unit test."""
    with _lock:
        _failures.clear()
        _lockouts.clear()
