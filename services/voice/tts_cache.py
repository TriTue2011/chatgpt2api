"""Cache LRU có hạn mức cho audio TTS — câu lặp lại không phải tổng hợp lần nữa.

Trợ lý nhà đọc đi đọc lại một nhúm câu: "Đã bật đèn phòng khách", "Đã tắt điều
hoà", "Vâng ạ". Tổng hợp lại mỗi lần tốn từ nửa giây tới vài giây CPU trong khi
kết quả y hệt — cùng chữ, cùng giọng, cùng cấu hình engine thì ra cùng byte
audio. Cache biến lần đọc thứ hai trở đi thành gần như tức thì.

Bốn hạn mức chặn phình RAM: số mục, tổng byte, byte mỗi mục, và tuổi nhàn rỗi
(mục lâu không đụng tới thì bỏ). Đặt ``voice.tts.cache_mb: 0`` để tắt hẳn.

Khoá băm CẢ cấu hình engine (backend, precision, length_scale) chứ không chỉ
chữ + giọng: đổi precision int8 ↔ fp32 là audio khác, khoá phải khác theo.

Ý tưởng hạn mức lấy từ luuquangvu/wyoming-vietnamese (``wyoming_vietnamese/
cache.py``); bản này thêm khoá threading vì engine ở đây bị gọi từ nhiều luồng
(worker Wyoming, bot Telegram, bot Zalo) chứ không chỉ một event loop.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic
from typing import Any

# Hạn mức cố định — chỉ tổng dung lượng mới cần chỉnh (voice.tts.cache_mb).
_MAX_ENTRIES = 256
_MAX_ITEM_BYTES = 4 * 1024 * 1024      # 4 MB ≈ 40 giây audio 48 kHz mono 16-bit
_IDLE_SECONDS = 24 * 3600.0


@dataclass
class _Entry:
    value: Any
    size_bytes: int
    expires_at: float


class BoundedLruCache:
    """Giữ giá trị dùng gần đây trong hạn mức số mục / tổng byte / byte mỗi mục."""

    def __init__(self, *, max_entries: int, max_bytes: int,
                 max_item_bytes: int, max_idle_seconds: float) -> None:
        self.max_entries = max(0, int(max_entries))
        self.max_bytes = max(0, int(max_bytes))
        self.max_item_bytes = max(0, int(max_item_bytes))
        self.max_idle_seconds = max(0.0, float(max_idle_seconds))
        self._entries: OrderedDict[bytes, _Entry] = OrderedDict()
        self._total_bytes = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @property
    def enabled(self) -> bool:
        return bool(self.max_entries and self.max_bytes and self.max_item_bytes)

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    def __len__(self) -> int:
        with self._lock:
            self._prune(monotonic())
            return len(self._entries)

    def get(self, key: bytes) -> Any | None:
        if not self.enabled:
            return None
        now = monotonic()
        with self._lock:
            self._prune(now)
            entry = self._entries.pop(key, None)
            if entry is None:
                self.misses += 1
                return None
            entry.expires_at = self._deadline(now)
            self._entries[key] = entry      # đẩy về cuối = vừa dùng
            self.hits += 1
            return entry.value

    def put(self, key: bytes, value: Any, *, size_bytes: int) -> bool:
        if not self.enabled or size_bytes <= 0:
            return False
        if size_bytes > self.max_item_bytes or size_bytes > self.max_bytes:
            return False
        now = monotonic()
        with self._lock:
            self._prune(now)
            old = self._entries.pop(key, None)
            if old is not None:
                self._total_bytes -= old.size_bytes
            self._entries[key] = _Entry(value, size_bytes, self._deadline(now))
            self._total_bytes += size_bytes
            while (len(self._entries) > self.max_entries
                   or self._total_bytes > self.max_bytes):
                _, evicted = self._entries.popitem(last=False)
                self._total_bytes -= evicted.size_bytes
            return True

    def clear(self) -> tuple[int, int]:
        """Bỏ hết, trả (số mục, số byte) vừa giải phóng."""
        with self._lock:
            freed = (len(self._entries), self._total_bytes)
            self._entries.clear()
            self._total_bytes = 0
            return freed

    def _prune(self, now: float) -> None:
        """Bỏ các mục quá hạn nhàn rỗi. Gọi khi ĐANG giữ khoá."""
        if not self._entries or not self.max_idle_seconds:
            return
        while self._entries:
            first = next(iter(self._entries))
            if self._entries[first].expires_at > now:
                break
            self._total_bytes -= self._entries.pop(first).size_bytes

    def _deadline(self, now: float) -> float:
        return now + self.max_idle_seconds if self.max_idle_seconds else float("inf")


# ── Thể hiện dùng chung ──────────────────────────────────────────────────────

_instance_lock = threading.Lock()
_instance: BoundedLruCache | None = None
_instance_mb: int = -1      # MB lúc dựng cache hiện tại — đổi cấu hình thì dựng lại


def _cache() -> BoundedLruCache | None:
    """Cache hiện hành, hoặc None khi ``voice.tts.cache_mb`` = 0 (tắt)."""
    from services.voice import config as vcfg

    mb = vcfg.tts_cache_mb()
    global _instance, _instance_mb
    with _instance_lock:
        if mb <= 0:
            _instance = None
            _instance_mb = 0
            return None
        if _instance is None or _instance_mb != mb:
            _instance = BoundedLruCache(
                max_entries=_MAX_ENTRIES,
                max_bytes=mb * 1024 * 1024,
                max_item_bytes=_MAX_ITEM_BYTES,
                max_idle_seconds=_IDLE_SECONDS,
            )
            _instance_mb = mb
        return _instance


def key(kind: str, text: str, voice: str, style: str) -> bytes:
    """Khoá cho một lần đọc. ``kind`` tách audio nguyên khối với audio theo mẩu.

    Băm luôn cấu hình engine: đổi precision hay length_scale là audio đổi, khoá
    phải đổi theo kẻo phát lại bản cũ. Khoảng lặng cũng nằm trong khoá — vừa
    chỉnh nhịp nghỉ trong Cài đặt mà nghe thử lại ra bản cũ thì tưởng là hỏng.
    """
    from services.voice import config as vcfg

    try:
        engine_cfg = "|".join((
            vcfg.tts_backend(),
            vcfg.vieneu_precision(),
            str(vcfg.tts_length_scale()),
            str(vcfg.tts_sentence_silence_ms()),
            str(vcfg.tts_clause_silence_ms()),
            str(vcfg.tts_silence_jitter_percent()),
        ))
    except Exception:
        engine_cfg = ""
    raw = "\x00".join((kind, text, voice, style, engine_cfg))
    return hashlib.sha256(raw.encode("utf-8")).digest()


def get(k: bytes) -> Any | None:
    c = _cache()
    return None if c is None else c.get(k)


def put(k: bytes, value: Any, *, size_bytes: int) -> bool:
    c = _cache()
    return False if c is None else c.put(k, value, size_bytes=size_bytes)


def max_item_bytes() -> int:
    """Trần byte mỗi mục — caller dừng gom audio khi vượt, khỏi phí RAM."""
    c = _cache()
    return 0 if c is None else c.max_item_bytes


def stats() -> dict[str, Any]:
    """Số liệu cho trang trạng thái Giọng nói."""
    c = _cache()
    if c is None:
        return {"enabled": False}
    return {
        "enabled": True,
        "entries": len(c),
        "bytes": c.total_bytes,
        "max_bytes": c.max_bytes,
        "hits": c.hits,
        "misses": c.misses,
    }


def clear() -> tuple[int, int]:
    c = _cache()
    return (0, 0) if c is None else c.clear()
