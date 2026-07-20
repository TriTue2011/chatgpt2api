"""Lightweight calendar connector — fetch a public/private ICS URL.

Not a full CalDAV client. Useful for morning brief / super_context:
pull next N events from an ICS feed (Google calendar secret URL, etc.).

Config (``calendar_connector``)::

    enabled: bool (default False)
    ics_url: str
    max_events: int (default 8)
    days_ahead: int (default 7)
    cache_seconds: int (default 900)
"""

from __future__ import annotations

import logging
import re
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.config import config

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_cache: dict[str, Any] = {"ts": 0.0, "text": "", "events": []}

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:
    _TZ = timezone(timedelta(hours=7))


def _cfg() -> dict[str, Any]:
    raw = config.get().get("calendar_connector")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    c = _cfg()
    return bool(c.get("enabled")) and bool(str(c.get("ics_url") or "").strip())


def _unfold(ics: str) -> str:
    # RFC 5545 line folding: CRLF + space/tab
    return re.sub(r"\r?\n[ \t]", "", ics or "")


def _parse_dt(val: str) -> Optional[datetime]:
    val = (val or "").strip()
    if ":" in val and not re.match(r"^\d", val):
        val = val.split(":", 1)[-1]
    val = val.replace("Z", "").strip()
    dt: Optional[datetime] = None
    try:
        if "T" in val:
            core = re.sub(r"[^0-9T]", "", val)[:15]
            if len(core) >= 15:
                dt = datetime.strptime(core[:15], "%Y%m%dT%H%M%S")
            elif len(core) >= 13:
                dt = datetime.strptime(core[:13], "%Y%m%dT%H%M")
        else:
            core = re.sub(r"\D", "", val)[:8]
            if len(core) == 8:
                dt = datetime.strptime(core, "%Y%m%d")
    except Exception:
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ)
    return dt


def _parse_events(ics: str) -> list[dict[str, Any]]:
    ics = _unfold(ics)
    events: list[dict[str, Any]] = []
    blocks = re.split(r"BEGIN:VEVENT", ics, flags=re.I)[1:]
    for block in blocks:
        end = re.split(r"END:VEVENT", block, flags=re.I)[0]
        fields: dict[str, str] = {}
        for line in end.splitlines():
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.split(";")[0].strip().upper()
            fields[key] = val.strip()
        summary = fields.get("SUMMARY") or "(không tiêu đề)"
        # unescape common ICS escapes
        summary = summary.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";")
        dtstart = _parse_dt(fields.get("DTSTART") or "")
        dtend = _parse_dt(fields.get("DTEND") or "")
        if not dtstart:
            continue
        events.append({
            "summary": summary[:200],
            "start": dtstart,
            "end": dtend,
            "location": (fields.get("LOCATION") or "").replace("\\,", ",")[:120],
        })
    events.sort(key=lambda e: e["start"])
    return events


def fetch_events(*, force: bool = False) -> list[dict[str, Any]]:
    if not is_enabled():
        return []
    c = _cfg()
    url = str(c.get("ics_url") or "").strip()
    try:
        cache_s = max(60, int(c.get("cache_seconds") or 900))
    except (TypeError, ValueError):
        cache_s = 900
    try:
        days = max(1, int(c.get("days_ahead") or 7))
    except (TypeError, ValueError):
        days = 7
    try:
        max_n = max(1, min(30, int(c.get("max_events") or 8)))
    except (TypeError, ValueError):
        max_n = 8

    with _lock:
        if not force and _cache.get("events") and time.time() - float(_cache.get("ts") or 0) < cache_s:
            return list(_cache["events"])

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "chatgpt2api-calendar/1.0"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("calendar: fetch failed: %s", exc)
        with _lock:
            return list(_cache.get("events") or [])

    now = datetime.now(_TZ)
    horizon = now + timedelta(days=days)
    events = []
    for ev in _parse_events(raw):
        if ev["start"] < now - timedelta(hours=2):
            continue
        if ev["start"] > horizon:
            continue
        events.append(ev)
        if len(events) >= max_n:
            break

    with _lock:
        _cache["ts"] = time.time()
        _cache["events"] = events
        _cache["text"] = format_events(events)
    return events


def format_events(events: list[dict[str, Any]] | None = None) -> str:
    if events is None:
        events = fetch_events()
    if not events:
        return ""
    lines = ["### Lịch sắp tới"]
    for ev in events:
        st: datetime = ev["start"]
        when = st.astimezone(_TZ).strftime("%a %d/%m %H:%M")
        loc = f" @ {ev['location']}" if ev.get("location") else ""
        lines.append(f"- {when}: {ev['summary']}{loc}")
    return "\n".join(lines)


def prompt_block() -> str:
    """For super_context / system prompt."""
    if not is_enabled():
        return ""
    try:
        return format_events()
    except Exception:
        return ""


def _reset_for_tests() -> None:
    with _lock:
        _cache.clear()
        _cache.update({"ts": 0.0, "text": "", "events": []})
