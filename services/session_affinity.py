"""Session Affinity (sticky) — giữ 1 hội thoại trên CÙNG account khi có thể.

API stateless (không conversation_id), nên khóa phiên lấy theo thứ tự:
1. `body["user"]` — field OpenAI chuẩn, client nào set thì chính xác nhất.
2. Fallback: SHA1(model + nội dung user message ĐẦU TIÊN) — hội thoại nhiều
   lượt luôn gửi lại prefix cũ nên message đầu ổn định suốt phiên.

Map pool→key→access_token trong RAM (TTL smart_pool.sticky_ttl_seconds, mặc
định 900s; LRU tối đa 2000 mục). Account bị demote/rotate → evict_token() gỡ
mọi phiên đang dính vào token đó. Tắt: smart_pool.enabled=false hoặc
sticky_ttl_seconds=0 → mọi hàm no-op.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any

from services.config import config

_MAX_ENTRIES = 2000


def _sticky_ttl() -> int:
    sp = config.data.get("smart_pool")
    if not isinstance(sp, dict):
        return 900
    if not sp.get("enabled", True):
        return 0
    try:
        return max(0, int(sp.get("sticky_ttl_seconds", 900)))
    except Exception:
        return 900


class SessionAffinity:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key = f"{pool}|{session_key}" -> (access_token, expires_at)
        self._map: "OrderedDict[str, tuple[str, float]]" = OrderedDict()

    @staticmethod
    def session_key(body: dict | None, messages: list[dict] | None) -> str | None:
        """Rút khóa phiên từ request; None = không sticky được."""
        body = body if isinstance(body, dict) else {}
        user = str(body.get("user") or "").strip()
        if user:
            return "u:" + user
        model = str(body.get("model") or "")
        first_user = ""
        for m in messages or []:
            if isinstance(m, dict) and m.get("role") == "user":
                c = m.get("content")
                if isinstance(c, list):  # multimodal → ghép text part
                    c = " ".join(str(p.get("text") or "") for p in c if isinstance(p, dict))
                first_user = str(c or "")[:2000]
                break
        if not first_user:
            return None
        return "h:" + hashlib.sha1((model + "\n" + first_user).encode("utf-8"), usedforsecurity=False).hexdigest()

    def get(self, pool: str, key: str | None) -> str | None:
        """access_token đang dính với phiên này (còn TTL), hoặc None."""
        ttl = _sticky_ttl()
        if not ttl or not key:
            return None
        mk = f"{pool}|{key}"
        with self._lock:
            item = self._map.get(mk)
            if item is None:
                return None
            token, expires_at = item
            if time.time() > expires_at:
                del self._map[mk]
                return None
            self._map.move_to_end(mk)  # LRU refresh
            return token

    def bind(self, pool: str, key: str | None, access_token: str) -> None:
        ttl = _sticky_ttl()
        if not ttl or not key or not access_token:
            return
        mk = f"{pool}|{key}"
        with self._lock:
            if mk in self._map:
                del self._map[mk]
            self._map[mk] = (access_token, time.time() + ttl)
            while len(self._map) > _MAX_ENTRIES:
                self._map.popitem(last=False)

    def evict_token(self, access_token: str) -> None:
        """Gỡ mọi phiên đang dính token này (account hỏng/rotate/demote)."""
        if not access_token:
            return
        with self._lock:
            dead = [k for k, (tok, _) in self._map.items() if tok == access_token]
            for k in dead:
                del self._map[k]

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {"entries": len(self._map), "ttl_seconds": _sticky_ttl()}


# Singleton
session_affinity = SessionAffinity()
