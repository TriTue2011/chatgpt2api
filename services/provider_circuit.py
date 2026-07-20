"""Provider Circuit-Breaker — chặn sớm provider đang chết hàng loạt.

Mẫu theo model_cooldown (in-memory, singleton, threading.Lock) nhưng ở TẦNG
PROVIDER (key = BackendRoute.provider: 'openai_oauth', 'chatgpt_free',
'custom:<id>'...): provider fail LIÊN TIẾP >= ngưỡng → mạch MỞ (open) trong
`open_seconds`; hết hạn → half_open cho 1 request thăm dò; thành công → đóng.

Khác model_cooldown (theo account+model, biết retry-after), circuit-breaker trả
lời câu "provider này còn sống không?" để combo bỏ qua NHANH thay vì đốt timeout
mỗi request. Quy tắc an toàn:
- 413 (payload size) KHÔNG tính fail — lỗi request, không phải sức khỏe provider.
- Caller KHÔNG bao giờ chặn lựa chọn cuối cùng còn lại (tránh chết cứng).
- Tắt bằng config smart_pool.enabled=false → allow() luôn True.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from services.config import config
from utils.log import logger


def _cfg_int(key: str, default: int) -> int:
    try:
        sp = config.data.get("smart_pool") or {}
        return int(sp.get(key, default)) if isinstance(sp, dict) else default
    except Exception:
        return default


def _enabled() -> bool:
    sp = config.data.get("smart_pool")
    if isinstance(sp, dict):
        return bool(sp.get("enabled", True))
    return True


@dataclass
class CircuitState:
    provider: str
    state: str = "closed"            # closed | open | half_open
    consecutive_failures: int = 0
    opened_at: float = 0.0
    last_error: str = ""
    total_opens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "opened_seconds_ago": round(time.time() - self.opened_at) if self.opened_at else 0,
            "last_error": self.last_error[:120],
            "total_opens": self.total_opens,
        }


class ProviderCircuit:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, CircuitState] = {}

    def _get(self, provider: str) -> CircuitState:
        st = self._states.get(provider)
        if st is None:
            st = CircuitState(provider=provider)
            self._states[provider] = st
        return st

    def allow(self, provider: str) -> bool:
        """True = được thử provider này. Mạch mở quá open_seconds → half_open
        (cho đúng 1 request thăm dò đi qua)."""
        if not _enabled():
            return True
        provider = str(provider or "").strip()
        if not provider:
            return True
        open_seconds = _cfg_int("circuit_open_seconds", 60)
        with self._lock:
            st = self._states.get(provider)
            if st is None or st.state == "closed":
                return True
            if st.state == "open":
                if time.time() - st.opened_at >= open_seconds:
                    st.state = "half_open"
                    logger.info({"event": "circuit_half_open", "provider": provider})
                    return True
                return False
            # half_open: đã có 1 request thăm dò đang chạy → chặn request khác
            return False

    def record_success(self, provider: str) -> None:
        if not _enabled():
            return
        provider = str(provider or "").strip()
        if not provider:
            return
        with self._lock:
            st = self._states.get(provider)
            if st and (st.consecutive_failures or st.state != "closed"):
                logger.info({"event": "circuit_closed", "provider": provider})
                st.state = "closed"
                st.consecutive_failures = 0
                st.opened_at = 0.0
                st.last_error = ""

    def record_failure(self, provider: str, status_code: int = 0, error: str = "") -> None:
        if not _enabled():
            return
        provider = str(provider or "").strip()
        if not provider:
            return
        if status_code == 413:
            return  # request-size, không phải sức khỏe provider (như model_cooldown)
        threshold = max(1, _cfg_int("circuit_threshold", 3))
        with self._lock:
            st = self._get(provider)
            st.consecutive_failures += 1
            st.last_error = str(error or "")[:200]
            # half_open thăm dò fail → mở lại ngay; closed đạt ngưỡng → mở.
            if st.state == "half_open" or st.consecutive_failures >= threshold:
                if st.state != "open":
                    st.total_opens += 1
                    logger.warning({
                        "event": "circuit_open", "provider": provider,
                        "failures": st.consecutive_failures,
                        "error": st.last_error[:120],
                    })
                st.state = "open"
                st.opened_at = time.time()

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            active = {p: st.to_dict() for p, st in self._states.items()
                      if st.state != "closed" or st.consecutive_failures}
            return {
                "enabled": _enabled(),
                "open_count": sum(1 for st in self._states.values() if st.state == "open"),
                "providers": active,
            }


# Singleton
provider_circuit = ProviderCircuit()
