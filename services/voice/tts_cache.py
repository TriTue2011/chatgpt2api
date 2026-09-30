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

TẦNG ĐĨA (chủ máy 30/09/2026: "làm nốt tích hợp ý tưởng từ wyoming-vietnamese", bản #23 của họ):
cache RAM mất sạch mỗi lần container khởi động lại — mà c2a khởi động lại ở MỖI lần
triển khai, nên "Đã bật đèn phòng khách" lại phải tổng hợp từ đầu. Nay mục vừa tổng
hợp còn được ghi xuống ``DATA_DIR/voice/tts_cache/`` (ghi nguyên tử), đọc lại khi RAM
trượt. Hạn mức riêng: tổng MB (``voice.tts.cache_disk_mb``, mặc định theo hạng máy —
``config.hang_may``), số tệp, byte mỗi tệp, 30 ngày không dùng thì bỏ.

Khoá có thêm PHIÊN BẢN CÁCH ĐỌC = băm toàn bộ mã + dữ liệu ``services/voice/``: c2a sửa
luật đọc tiếng Việt thường xuyên; không có nó thì đĩa phát bản đọc CŨ suốt 30 ngày.
"""

from __future__ import annotations

import hashlib
import os
import struct
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, time as _bay_gio
from typing import Any

from utils.log import logger

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


# ── Tầng ĐĨA ────────────────────────────────────────────────────────────────
_DIA_MAX_ENTRIES = 4096
_DIA_IDLE_SECONDS = 30 * 86400.0
_MAGIC = b"C2TTS1"


def _ma_hoa(value: Any) -> bytes | None:
    """Giá trị cache → byte trên đĩa: audio nguyên khối (bytes) hoặc theo mẩu ([(tần số, PCM)])."""
    if isinstance(value, (bytes, bytearray)):
        return _MAGIC + b"w" + bytes(value)
    if isinstance(value, list) and all(isinstance(x, tuple) and len(x) == 2 and isinstance(x[0], int)
                                       and isinstance(x[1], (bytes, bytearray)) for x in value):
        return _MAGIC + b"s" + b"".join(struct.pack("<II", sr, len(pcm)) + bytes(pcm) for sr, pcm in value)
    return None


def _giai_ma(raw: bytes) -> Any | None:
    if not raw.startswith(_MAGIC) or len(raw) < len(_MAGIC) + 1:
        return None
    kieu, than = raw[len(_MAGIC):len(_MAGIC) + 1], raw[len(_MAGIC) + 1:]
    if kieu == b"w":
        return than
    if kieu != b"s":
        return None
    ra, i = [], 0
    while i < len(than):
        if i + 8 > len(than):
            return None
        sr, n = struct.unpack_from("<II", than, i)
        i += 8
        if i + n > len(than):
            return None
        ra.append((sr, than[i:i + n]))
        i += n
    return ra


class DiskAudioCache:
    """Cache audio trên đĩa: một tệp mỗi khoá, LRU theo lúc dùng (mtime), hạn mức tổng byte / số tệp / byte mỗi tệp
    / ngày nhàn rỗi. Lỗi đọc ghi chỉ làm trượt cache — không bao giờ làm hỏng lượt đọc."""

    def __init__(self, thu_muc: Path, *, max_bytes: int, max_entries: int = _DIA_MAX_ENTRIES,
                 max_item_bytes: int = 8 * 1024 * 1024, max_idle_seconds: float = _DIA_IDLE_SECONDS) -> None:
        self.dir = Path(thu_muc)
        self.max_bytes, self.max_entries = max(0, int(max_bytes)), max(0, int(max_entries))
        self.max_item_bytes, self.max_idle_seconds = max(0, int(max_item_bytes)), float(max_idle_seconds)
        self._lock = threading.Lock()
        self._chi_muc: dict[str, tuple[int, float]] | None = None     # tên tệp → (byte, lúc dùng)
        self.hits = 0
        self.misses = 0

    @property
    def enabled(self) -> bool:
        return bool(self.max_bytes and self.max_entries and self.max_item_bytes)

    def _nap_chi_muc(self) -> dict[str, tuple[int, float]]:
        if self._chi_muc is None:
            self._chi_muc = {}
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                for f in self.dir.glob("*.bin"):
                    st = f.stat()
                    self._chi_muc[f.name] = (st.st_size, st.st_mtime)
            except OSError as exc:
                logger.warning({"event": "tts_cache_dia_loi", "viec": "doc_thu_muc", "error": str(exc)[:160]})
            self._don(_bay_gio())
        return self._chi_muc

    def _bo(self, ten: str) -> None:
        self._chi_muc.pop(ten, None)
        try:
            (self.dir / ten).unlink()
        except OSError:
            pass

    def _don(self, bay_gio: float, them_byte: int = 0) -> None:
        """Bỏ tệp quá hạn nhàn rỗi, rồi tệp dùng lâu nhất cho tới khi còn chỗ cho ``them_byte``."""
        cm = self._chi_muc
        for ten, (_n, luc) in list(cm.items()):
            if bay_gio - luc > self.max_idle_seconds:
                self._bo(ten)
        tong = sum(n for n, _ in cm.values())
        for ten, (n, _luc) in sorted(cm.items(), key=lambda x: x[1][1]):
            if tong + them_byte <= self.max_bytes and len(cm) + (1 if them_byte else 0) <= self.max_entries:
                break
            self._bo(ten)
            tong -= n

    def get(self, key: bytes) -> Any | None:
        if not self.enabled:
            return None
        ten = key.hex() + ".bin"
        with self._lock:
            cm = self._nap_chi_muc()
            if ten not in cm:
                self.misses += 1
                return None
            try:
                v = _giai_ma((self.dir / ten).read_bytes())
            except OSError:
                v = None
            if v is None:
                self._bo(ten)
                self.misses += 1
                return None
            bay_gio = _bay_gio()
            cm[ten] = (cm[ten][0], bay_gio)
            try:
                os.utime(self.dir / ten, (bay_gio, bay_gio))
            except OSError:
                pass
            self.hits += 1
            return v

    def put(self, key: bytes, value: Any) -> bool:
        if not self.enabled:
            return False
        raw = _ma_hoa(value)
        if raw is None or len(raw) > self.max_item_bytes or len(raw) > self.max_bytes:
            return False
        ten = key.hex() + ".bin"
        with self._lock:
            cm = self._nap_chi_muc()
            if ten in cm:
                self._bo(ten)
            self._don(_bay_gio(), len(raw))
            tam = self.dir / (ten + ".tmp")
            try:
                tam.write_bytes(raw)
                os.replace(tam, self.dir / ten)
            except OSError as exc:
                logger.warning({"event": "tts_cache_dia_loi", "viec": "ghi", "error": str(exc)[:160]})
                try:
                    tam.unlink()
                except OSError:
                    pass
                return False
            cm[ten] = (len(raw), _bay_gio())
            return True

    def clear(self) -> tuple[int, int]:
        with self._lock:
            cm = self._nap_chi_muc()
            freed = (len(cm), sum(n for n, _ in cm.values()))
            for ten in list(cm):
                self._bo(ten)
            return freed

    def stats(self) -> tuple[int, int]:
        with self._lock:
            cm = self._nap_chi_muc()
            return len(cm), sum(n for n, _ in cm.values())


_phien_ban: str | None = None


def phien_ban_cach_doc() -> str:
    """Băm mọi tệp mã + dữ liệu của ``services/voice`` — đổi cách đọc là khoá đổi, bản cũ trên đĩa hết hiệu lực."""
    global _phien_ban
    if _phien_ban is None:
        goc = Path(__file__).resolve().parent
        h = hashlib.sha256()
        for f in sorted(goc.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                h.update(str(f.relative_to(goc)).encode())
                try:
                    h.update(f.read_bytes())
                except OSError:
                    pass
        _phien_ban = h.hexdigest()[:16]
    return _phien_ban


# ── Thể hiện dùng chung ──────────────────────────────────────────────────────

_instance_lock = threading.Lock()
_instance: BoundedLruCache | None = None
_instance_mb: int = -1      # MB lúc dựng cache hiện tại — đổi cấu hình thì dựng lại


_dia: DiskAudioCache | None = None
_dia_mb: int = -1


def _cache_dia() -> DiskAudioCache | None:
    """Tầng đĩa hiện hành, hoặc None khi ``voice.tts.cache_disk_mb`` = 0."""
    from services.config import DATA_DIR
    from services.voice import config as vcfg

    # ``cache_mb: 0`` là TẮT HẲN cache (như tài liệu vẫn nói) — tắt luôn tầng đĩa.
    mb = vcfg.tts_cache_disk_mb() if vcfg.tts_cache_mb() > 0 else 0
    global _dia, _dia_mb
    with _instance_lock:
        if mb <= 0:
            _dia, _dia_mb = None, 0
            return None
        if _dia is None or _dia_mb != mb:
            _dia = DiskAudioCache(Path(DATA_DIR) / "voice" / "tts_cache", max_bytes=mb * 1024 * 1024)
            _dia_mb = mb
        return _dia


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
            str(vcfg.tts_paragraph_silence_ms()),
            str(vcfg.tts_sentence_silence_ms()),
            str(vcfg.tts_clause_silence_ms()),
            str(vcfg.tts_silence_jitter_percent()),
        ))
    except Exception:
        engine_cfg = ""
    raw = "\x00".join((kind, text, voice, style, engine_cfg, phien_ban_cach_doc()))
    return hashlib.sha256(raw.encode("utf-8")).digest()


def get(k: bytes) -> Any | None:
    """RAM trước; trượt thì đĩa — thấy ở đĩa thì đưa lại lên RAM cho lần sau."""
    c = _cache()
    v = None if c is None else c.get(k)
    if v is not None:
        return v
    d = _cache_dia()
    v = None if d is None else d.get(k)
    if v is not None and c is not None:
        c.put(k, v, size_bytes=_co_byte(v))
    return v


def put(k: bytes, value: Any, *, size_bytes: int) -> bool:
    c = _cache()
    o_ram = False if c is None else c.put(k, value, size_bytes=size_bytes)
    d = _cache_dia()
    o_dia = False if d is None else d.put(k, value)
    return o_ram or o_dia


def _co_byte(value: Any) -> int:
    if isinstance(value, (bytes, bytearray)):
        return len(value)
    return sum(len(x[1]) for x in value) if isinstance(value, list) else 0


def max_item_bytes() -> int:
    """Trần byte mỗi mục — caller dừng gom audio khi vượt, khỏi phí RAM."""
    c = _cache()
    d = _cache_dia()
    return max(0 if c is None else c.max_item_bytes, 0 if d is None else d.max_item_bytes)


def stats() -> dict[str, Any]:
    """Số liệu cho trang trạng thái Giọng nói."""
    c = _cache()
    d = _cache_dia()
    ra: dict[str, Any] = {"enabled": c is not None or d is not None}
    if c is not None:
        ra.update(entries=len(c), bytes=c.total_bytes, max_bytes=c.max_bytes, hits=c.hits, misses=c.misses)
    if d is not None:
        n, b = d.stats()
        ra["disk"] = {"entries": n, "bytes": b, "max_bytes": d.max_bytes, "hits": d.hits, "misses": d.misses}
    return ra


def clear() -> tuple[int, int]:
    c = _cache()
    d = _cache_dia()
    a = (0, 0) if c is None else c.clear()
    b = (0, 0) if d is None else d.clear()
    return a[0] + b[0], a[1] + b[1]
