"""Tool-result compression (TokenJuice-inspired, pure Python).

Large tool outputs (HA dumps, logs, HTML) are compacted before they enter
the model context. The full original is cached (memory + optional disk) and
recoverable via ``expand_tool_result`` using a ``⟦tc:<hash>⟧`` marker.

Config (``agent_tool_compress``)::

    enabled: bool (default True)
    min_bytes: int — only compress above this size (default 2048)
    max_chars: int — target max chars kept for the model (default 4000)
    disk_cache: bool (default True)
    max_cache_entries: int (default 256)
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR, config

logger = logging.getLogger(__name__)

_MARKER_RE = re.compile(r"⟦tc:([0-9a-f]{12,64})⟧")
_lock = threading.RLock()
# hash12 -> {"text": str, "tool": str, "ts": float, "chars": int}
_cache: dict[str, dict[str, Any]] = {}
_CACHE_DIR = Path(DATA_DIR) / "agent" / "tool_cache"


def _cfg() -> dict[str, Any]:
    raw = config.get().get("agent_tool_compress")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def min_bytes() -> int:
    try:
        return max(256, int(_cfg().get("min_bytes") or 2048))
    except (TypeError, ValueError):
        return 2048


def max_chars() -> int:
    try:
        return max(500, int(_cfg().get("max_chars") or 4000))
    except (TypeError, ValueError):
        return 4000


def disk_cache_enabled() -> bool:
    return bool(_cfg().get("disk_cache", True))


def max_cache_entries() -> int:
    try:
        return max(16, int(_cfg().get("max_cache_entries") or 256))
    except (TypeError, ValueError):
        return 256


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _detect_kind(text: str, tool_name: str = "") -> str:
    name = (tool_name or "").lower()
    if name in (
        "home_status", "system_status", "remote_system_status",
        "web_search", "read_webpage", "youtube_transcript",
        "run_workflow", "search_history", "contacts", "wiki_search",
    ):
        if name == "read_webpage":
            return "html"
        if name in ("web_search", "wiki_search", "search_history", "contacts"):
            return "search"
        return "log"
    t = (text or "").lstrip()
    if t.startswith("{") or t.startswith("["):
        return "json"
    if "<html" in t[:500].lower() or "<!doctype" in t[:200].lower():
        return "html"
    if re.search(r"(?m)^(?:diff --git|@@ |\+\+\+ |\-\-\- )", t[:2000]):
        return "diff"
    # log-ish: many short lines with timestamps or levels
    lines = t.splitlines()
    if len(lines) > 40:
        return "log"
    return "plain"


def _compress_body(text: str, kind: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    if kind == "html":
        # strip tags lightly
        plain = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
        plain = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", plain)
        plain = re.sub(r"(?s)<[^>]+>", " ", plain)
        plain = re.sub(r"\s+", " ", plain).strip()
        if len(plain) > limit:
            half = limit // 2 - 20
            plain = plain[:half] + " … " + plain[-half:]
        return plain
    if kind == "json":
        # keep start + end; useful for large HA dumps
        half = limit // 2 - 30
        return text[:half] + "\n… [json rút gọn] …\n" + text[-half:]
    if kind in ("log", "search", "diff", "plain"):
        lines = text.splitlines()
        signal_re = re.compile(
            r"(error|err|warn|warning|fail|exception|traceback|critical|"
            r"panic|timeout|denied|offline|unavailable|lỗi|thất bại)",
            re.I,
        )
        signals = [ln for ln in lines if signal_re.search(ln)][:24]
        # Reserve room for signal block first, then head/tail.
        sig_block = ""
        if signals:
            sig_block = "… [dòng quan trọng] …\n" + "\n".join(signals) + "\n"
        remain = max(120, limit - len(sig_block) - 40)
        head_budget = remain // 2
        tail_budget = remain - head_budget
        head_parts: list[str] = []
        n = 0
        for ln in lines:
            if n + len(ln) + 1 > head_budget:
                break
            head_parts.append(ln)
            n += len(ln) + 1
        tail_parts: list[str] = []
        n = 0
        for ln in reversed(lines):
            if n + len(ln) + 1 > tail_budget:
                break
            tail_parts.append(ln)
            n += len(ln) + 1
        tail_parts.reverse()
        skipped = max(0, len(lines) - len(head_parts) - len(tail_parts))
        parts = head_parts
        if sig_block:
            parts = parts + [sig_block.rstrip()]
        if skipped > 0:
            parts = parts + [f"… [đã bỏ ~{skipped} dòng] …"]
        parts = parts + tail_parts
        body = "\n".join(parts)
        if len(body) > limit:
            # Last resort: signals + truncated head
            body = (sig_block + "\n".join(head_parts))[:limit]
        return body
    half = limit // 2 - 20
    return text[:half] + " … " + text[-half:]

def _evict_if_needed() -> None:
    cap = max_cache_entries()
    if len(_cache) <= cap:
        return
    # FIFO by ts
    ordered = sorted(_cache.items(), key=lambda kv: kv[1].get("ts") or 0)
    for key, _ in ordered[: max(1, len(_cache) - cap)]:
        _cache.pop(key, None)
        if disk_cache_enabled():
            p = _CACHE_DIR / f"{key}.txt"
            try:
                if p.is_file():
                    p.unlink()
            except OSError:
                pass


def store_full(text: str, *, tool_name: str = "") -> str:
    """Cache full text; return 16-char hash token."""
    token = _hash(text)
    with _lock:
        _cache[token] = {
            "text": text,
            "tool": tool_name or "",
            "ts": time.time(),
            "chars": len(text),
        }
        _evict_if_needed()
        if disk_cache_enabled():
            try:
                _CACHE_DIR.mkdir(parents=True, exist_ok=True)
                (_CACHE_DIR / f"{token}.txt").write_text(text, encoding="utf-8")
            except OSError as exc:
                logger.warning("tool_compress: disk cache write failed: %s", exc)
    return token


def retrieve(token: str, *, max_out: int = 50000) -> Optional[str]:
    """Return full original by token (hash or marker)."""
    if not token:
        return None
    m = _MARKER_RE.search(token)
    if m:
        token = m.group(1)
    token = re.sub(r"[^0-9a-f]", "", token.lower())
    if len(token) < 12:
        return None
    # allow prefix match on 12+ chars
    with _lock:
        if token in _cache:
            return str(_cache[token].get("text") or "")[:max_out]
        for k, v in _cache.items():
            if k.startswith(token) or token.startswith(k):
                return str(v.get("text") or "")[:max_out]
    if disk_cache_enabled():
        try:
            for p in _CACHE_DIR.glob(f"{token}*.txt"):
                return p.read_text(encoding="utf-8", errors="replace")[:max_out]
            # prefix files
            for p in _CACHE_DIR.glob("*.txt"):
                if p.stem.startswith(token) or token.startswith(p.stem):
                    return p.read_text(encoding="utf-8", errors="replace")[:max_out]
        except OSError:
            return None
    return None


def compress(
    text: str,
    *,
    tool_name: str = "",
) -> str:
    """Return text for the model; may append ``⟦tc:hash⟧`` recovery marker."""
    if not is_enabled():
        return text or ""
    raw = text or ""
    if len(raw.encode("utf-8", errors="replace")) < min_bytes():
        return raw
    if len(raw) <= max_chars():
        return raw
    kind = _detect_kind(raw, tool_name)
    body = _compress_body(raw, kind, max_chars())
    token = store_full(raw, tool_name=tool_name)
    saved = max(0, len(raw) - len(body))
    footer = (
        f"\n\n[tool output đã nén ~{saved} ký tự; bản đầy đủ: "
        f"expand_tool_result token=`{token}` hoặc marker ⟦tc:{token}⟧]"
    )
    return body + footer


def maybe_compress_result(result: dict[str, Any], *, tool_name: str = "") -> dict[str, Any]:
    """Compress ``result['text']`` in-place copy; leave media keys alone."""
    if not isinstance(result, dict):
        return {"text": str(result)}
    out = dict(result)
    txt = out.get("text")
    if isinstance(txt, str) and txt:
        out["text"] = compress(txt, tool_name=tool_name)
    return out


def _reset_for_tests(cache_dir: Path | None = None) -> None:
    global _CACHE_DIR, _cache
    with _lock:
        _cache = {}
        if cache_dir is not None:
            _CACHE_DIR = Path(cache_dir)
