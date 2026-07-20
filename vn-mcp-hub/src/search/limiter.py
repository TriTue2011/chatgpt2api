"""Rate-limit aware fallback for search backends.

Khi một API/tài khoản (key) dính rate-limit (429) hoặc hết quota, ta:
- đánh dấu KEY đó nghỉ một lúc → backend xoay sang key/account khác (fallback account);
- nếu cả backend hết đường (không key dùng được, hoặc API không-key bị 429) →
  đánh dấu BACKEND nghỉ → orchestrator bỏ qua nó, các API khác gánh tiếp
  (fallback API). Né ngay nên không phí thời gian gọi lại nguồn đã limit.

Trạng thái giữ trong RAM, an toàn đa luồng (orchestrator chạy ThreadPool).
"""

from __future__ import annotations

import threading
import time

# Cooldown mặc định (giây).
BACKEND_COOLDOWN = 600.0   # 10 phút: API/nguồn dính 429 → nghỉ rồi thử lại
KEY_COOLDOWN = 1800.0      # 30 phút: 1 key/account hết quota → nghỉ, xoay key khác

_lock = threading.Lock()
_backend_until: dict[str, float] = {}   # backend id -> thời điểm hết cooldown
_key_until: dict[str, float] = {}       # f"{source}#{key[:10]}" -> hết cooldown


class RateLimited(Exception):
    """Backend báo đã hết đường (mọi key/account đều limit hoặc 429 không-key)."""


def is_rate_limited(exc: Exception) -> bool:
    """Đoán một exception HTTP có phải do rate-limit/quota không."""
    s = str(exc).lower()
    return any(k in s for k in ("429", "too many requests", "rate limit",
                                "quota", "402", "payment required"))


# ── Backend-level (fallback sang API khác) ───────────────────────────────────

def backend_cooling(backend: str) -> bool:
    with _lock:
        return _backend_until.get(backend, 0.0) > time.time()


def mark_backend_limited(backend: str, seconds: float = BACKEND_COOLDOWN) -> None:
    with _lock:
        _backend_until[backend] = time.time() + seconds


def mark_backend_ok(backend: str) -> None:
    with _lock:
        _backend_until.pop(backend, None)


# ── Key-level (fallback sang account/key khác cùng API) ──────────────────────

def _kid(source: str, key: str) -> str:
    return f"{source}#{(key or '')[:10]}"


def key_cooling(source: str, key: str) -> bool:
    with _lock:
        return _key_until.get(_kid(source, key), 0.0) > time.time()


def mark_key_limited(source: str, key: str, seconds: float = KEY_COOLDOWN) -> None:
    with _lock:
        _key_until[_kid(source, key)] = time.time() + seconds


def usable_keys(source: str, keys: list[str]) -> list[str]:
    """Lọc bỏ key đang cooldown, giữ thứ tự ưu tiên."""
    return [k for k in keys if k and not key_cooling(source, k)]


def status() -> dict:
    """Ảnh chụp trạng thái cooldown (debug / Studio)."""
    now = time.time()
    with _lock:
        return {
            "backends_cooling": {b: round(t - now, 1) for b, t in _backend_until.items() if t > now},
            "keys_cooling": {k: round(t - now, 1) for k, t in _key_until.items() if t > now},
        }
