"""User-defined reminders & recurring agent tasks.

Stores jobs in SQLite under ``DATA_DIR/agent/reminders.sqlite``. A background
thread ticks every ~20s, delivers due items to Telegram / Zalo / Zalo Personal.

Modes:
  - notify — send the text as-is to the user's chat
  - task   — run the agent orchestrator on the prompt, then send the reply

Schedule kinds:
  - once       — fire at due_at, then disable
  - interval   — every interval_min minutes
  - daily      — every day at hour:minute (Asia/Ho_Chi_Minh)

Config (top-level ``agent_reminders``)::

    enabled: bool (default True)
    tick_seconds: int (default 20)
    max_task_seconds: int (default 120)  — wall clock budget for task mode
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from services import lich_lap
from services.config import DATA_DIR, config

logger = logging.getLogger(__name__)

# Bản đồ thứ tiếng Việt → số của Python (0 = Thứ Hai … 6 = Chủ Nhật).
_THU_VN = {
    "t2": 0, "thứ 2": 0, "thu 2": 0, "thứ hai": 0, "thu hai": 0, "monday": 0, "mon": 0,
    "t3": 1, "thứ 3": 1, "thu 3": 1, "thứ ba": 1, "thu ba": 1, "tuesday": 1, "tue": 1,
    "t4": 2, "thứ 4": 2, "thu 4": 2, "thứ tư": 2, "thu tu": 2, "wednesday": 2, "wed": 2,
    "t5": 3, "thứ 5": 3, "thu 5": 3, "thứ năm": 3, "thu nam": 3, "thursday": 3, "thu": 3,
    "t6": 4, "thứ 6": 4, "thu 6": 4, "thứ sáu": 4, "thu sau": 4, "friday": 4, "fri": 4,
    "t7": 5, "thứ 7": 5, "thu 7": 5, "thứ bảy": 5, "thu bay": 5, "saturday": 5, "sat": 5,
    "cn": 6, "chủ nhật": 6, "chu nhat": 6, "sunday": 6, "sun": 6,
}
_SKIP_VN = {
    "lễ": "le", "le": "le", "ngày lễ": "le", "nghỉ lễ": "le", "holiday": "le",
    "tết": "tet", "tet": "tet", "tết âm": "tet", "lunar": "tet",
    "bù": "bu", "bu": "bu", "nghỉ bù": "bu",
}


def _chuan_weekdays(weekdays: list | None) -> list[int] | None:
    """Chuẩn hoá danh sách thứ: nhận số (0–6) hoặc chữ ('T2','thứ hai','mon')."""
    if not weekdays:
        return None
    ra: list[int] = []
    for w in weekdays:
        if isinstance(w, bool):
            continue
        if isinstance(w, (int, float)):
            v = int(w)
            if 0 <= v <= 6:
                ra.append(v)
        else:
            key = str(w).strip().lower()
            if key in _THU_VN:
                ra.append(_THU_VN[key])
    # loại trùng, giữ thứ tự
    seen: set[int] = set()
    out = [x for x in ra if not (x in seen or seen.add(x))]
    return out or None


def _chuan_skip(skip: list | None) -> list[str] | None:
    if not skip:
        return None
    ra: list[str] = []
    for s in skip:
        key = str(s).strip().lower()
        val = _SKIP_VN.get(key, key if key in ("le", "tet", "bu") else "")
        if val and val not in ra:
            ra.append(val)
    return ra or None


def _build_rrule(unit: str | None, every_n: int | None, at_hm: str | None,
                 weekdays: list | None, day_of_month: int | None,
                 month: int | None, skip: list | None,
                 now: datetime) -> dict[str, Any] | None:
    """Dựng spec cho lich_lap từ tham số công cụ. None nếu không phải lịch lặp.

    Kích hoạt khi có `unit`, hoặc khi có `weekdays` (người dùng chỉ nói thứ mà
    không nói đơn vị → hiểu là lặp theo tuần)."""
    wds = _chuan_weekdays(weekdays)
    u = (unit or "").strip().lower() if unit else ""
    if not u and wds:
        u = "week"
    if u not in lich_lap.UNITS:
        return None
    spec: dict[str, Any] = {"unit": u, "n": max(1, int(every_n or 1)),
                            "anchor": now.date().isoformat()}
    if u not in ("second", "minute", "hour"):
        hm = _parse_hm(at_hm or "") if at_hm else None
        spec["hour"], spec["minute"] = (hm or (int(now.hour), int(now.minute)))
    if wds:
        spec["weekdays"] = wds
    if day_of_month and 1 <= int(day_of_month) <= 31:
        spec["day"] = int(day_of_month)
    if month and 1 <= int(month) <= 12:
        spec["month"] = int(month)
    sk = _chuan_skip(skip)
    if sk:
        spec["skip"] = sk
    return spec


def _parse_on_date(on_date: str, at_hm: str | None,
                   now: datetime) -> dict[str, Any] | None:
    """'20/8', '20/08/2026', '2026-08-20' + giờ tuỳ chọn → nhắc MỘT lần."""
    s = str(on_date or "").strip()
    d = mo = yy = None
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        yy, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?$", s)
        if m:
            d, mo = int(m.group(1)), int(m.group(2))
            yy = int(m.group(3)) if m.group(3) else now.year
            if yy < 100:
                yy += 2000
    if not (d and mo and yy):
        return None
    hm = _parse_hm(at_hm or "") if at_hm else None
    h, mi = hm or (8, 0)
    try:
        dt = datetime(yy, mo, d, h, mi, tzinfo=_TZ)
    except ValueError:
        return None
    if dt <= now:
        # Đã qua: nếu người dùng KHÔNG ghi năm rõ (chỉ '20/8') thì hiểu là năm
        # sau; nếu ghi năm rõ mà vẫn quá khứ thì từ chối (không đoán bừa).
        if re.search(r"\d{4}", s):
            return None
        try:
            dt = dt.replace(year=dt.year + 1)
        except ValueError:
            return None
    return {"kind": "once", "due_at": dt.timestamp(), "next_run_at": dt.timestamp()}

_DB_PATH = Path(DATA_DIR) / "agent" / "reminders.sqlite"
try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:
    # Windows without tzdata package — fixed UTC+7 is correct for Vietnam.
    _TZ = timezone(timedelta(hours=7))
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_started = False
_stop = threading.Event()

# Vietnamese relative patterns
_RE_IN = re.compile(
    r"(?:sau|trong)\s+(\d+)\s*(phút|phut|p|giờ|gio|h|tiếng|tieng|ngày|ngay|d)",
    re.IGNORECASE,
)
_RE_AT_HM = re.compile(
    r"(?:lúc|luc|vào|vao|at)?\s*(\d{1,2})\s*[:hH]\s*(\d{0,2})\s*"
    r"(sáng|sang|chiều|chieu|tối|toi|trưa|trua)?",
    re.IGNORECASE,
)
_RE_EVERY_MIN = re.compile(
    r"mỗi\s+(\d+)\s*(phút|phut|p|giờ|gio|h|tiếng|tieng)",
    re.IGNORECASE,
)
_RE_EVERY_DAY = re.compile(
    r"mỗi\s*(?:ngày|ngay|sáng|sang|chiều|chieu|tối|toi)?\s*"
    r"(?:lúc|luc)?\s*(\d{1,2})\s*[:hH]\s*(\d{0,2})?",
    re.IGNORECASE,
)
_RE_BARE_MIN = re.compile(r"^(\d+)\s*(phút|phut|p|m|min|minutes?)?$", re.IGNORECASE)


def _cfg() -> dict[str, Any]:
    raw = config.get().get("agent_reminders")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def _tick_seconds() -> float:
    try:
        return max(5.0, float(_cfg().get("tick_seconds") or 20))
    except (TypeError, ValueError):
        return 20.0


def _now_vn() -> datetime:
    return datetime.now(_TZ)


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS reminders ("
            " id TEXT PRIMARY KEY,"
            " user_id TEXT NOT NULL,"
            " channel TEXT NOT NULL,"
            " chat_id TEXT NOT NULL,"
            " mode TEXT NOT NULL DEFAULT 'notify',"
            " text TEXT NOT NULL,"
            " kind TEXT NOT NULL DEFAULT 'once',"
            " due_at REAL,"
            " interval_min INTEGER,"
            " hour INTEGER,"
            " minute INTEGER,"
            " next_run_at REAL,"
            " enabled INTEGER NOT NULL DEFAULT 1,"
            " created_at REAL,"
            " last_run_at REAL,"
            " runs INTEGER NOT NULL DEFAULT 0,"
            " meta TEXT DEFAULT '{}',"
            # rrule: JSON của lịch lặp linh hoạt (kind='recur'). Xem services.lich_lap.
            " rrule TEXT)"
        )
        # Migration cho DB cũ (tạo trước khi có cột rrule): thêm nếu thiếu.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(reminders)").fetchall()}
        if "rrule" not in cols:
            conn.execute("ALTER TABLE reminders ADD COLUMN rrule TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rem_due "
            "ON reminders(enabled, next_run_at)"
        )
        conn.commit()
        _conn = conn
    return _conn


def channel_of(user_id: str) -> tuple[str, str]:
    """Return (channel, chat_id) from orchestrator user_id conventions."""
    uid = str(user_id or "")
    if uid.startswith("zalop_"):
        return "zalop", uid[6:]
    if uid.startswith("zalo_"):
        return "zalo", uid[5:]
    return "tg", uid


# ── When parser ──────────────────────────────────────────────────────────────


def parse_when(
    when: str,
    *,
    in_minutes: int | None = None,
    every_minutes: int | None = None,
    every_day_at: str | None = None,
    at: str | None = None,
    now: datetime | None = None,
    unit: str | None = None,
    every_n: int | None = None,
    weekdays: list | None = None,
    day_of_month: int | None = None,
    month: int | None = None,
    skip: list | None = None,
    on_date: str | None = None,
) -> dict[str, Any] | None:
    """Resolve schedule from structured args and/or free-text ``when``.

    Returns dict with keys: kind, next_run_at, and optional interval_min/hour/minute/due_at.
    kind='recur' còn kèm 'rrule' (dict spec cho services.lich_lap).
    """
    now = now or _now_vn()

    # ── LỊCH LẶP LINH HOẠT (giây→năm, thứ trong tuần, trừ lễ/tết/bù) ──────────
    # Ưu tiên cao nhất khi model truyền `unit`: đây là đường có kiểm soát, thay
    # cho việc đoán từ chữ. Cũng nhận `weekdays`/`skip` mà không cần `unit` (khi
    # người dùng chỉ nói "T2–T6 lúc 17:30 trừ lễ").
    _spec = _build_rrule(unit, every_n, every_day_at or at, weekdays,
                         day_of_month, month, skip, now)
    if _spec is not None:
        nxt = lich_lap.next_run(_spec, now, _TZ)
        if nxt:
            return {"kind": "recur", "rrule": _spec,
                    "hour": _spec.get("hour"), "minute": _spec.get("minute"),
                    "next_run_at": nxt.timestamp()}

    # Hẹn MỘT ngày cụ thể (dd/mm[/yyyy] [giờ]) → once.
    if on_date:
        _once = _parse_on_date(on_date, every_day_at or at, now)
        if _once:
            return _once

    if in_minutes is not None:
        try:
            mins = max(1, int(in_minutes))
        except (TypeError, ValueError):
            mins = 0
        if mins > 0:
            due = now + timedelta(minutes=mins)
            return {
                "kind": "once",
                "due_at": due.timestamp(),
                "next_run_at": due.timestamp(),
            }

    if every_minutes is not None:
        try:
            mins = max(5, int(every_minutes))  # floor 5 min
        except (TypeError, ValueError):
            mins = 0
        if mins > 0:
            nxt = now + timedelta(minutes=mins)
            return {
                "kind": "interval",
                "interval_min": mins,
                "next_run_at": nxt.timestamp(),
            }

    if every_day_at:
        hm = _parse_hm(every_day_at)
        if hm:
            h, m = hm
            nxt = _next_daily(now, h, m)
            return {
                "kind": "daily",
                "hour": h,
                "minute": m,
                "next_run_at": nxt.timestamp(),
            }

    if at:
        # ISO-ish or HH:MM today/tomorrow
        parsed = _parse_absolute(at, now)
        if parsed:
            return parsed

    text = (when or "").strip().lower()
    if not text:
        return None

    # interval: mỗi N phút/giờ
    m = _RE_EVERY_MIN.search(text)
    if m and ("mỗi" in text or "moi" in text):
        n = int(m.group(1))
        unit = m.group(2).lower()
        mins = n * (60 if unit in ("giờ", "gio", "h", "tiếng", "tieng") else 1)
        mins = max(5, mins)
        nxt = now + timedelta(minutes=mins)
        return {
            "kind": "interval",
            "interval_min": mins,
            "next_run_at": nxt.timestamp(),
        }

    # daily: mỗi ngày 7h / mỗi sáng 7:00
    if "mỗi ngày" in text or "moi ngay" in text or "hằng ngày" in text or "hang ngay" in text:
        hm = _extract_hm(text)
        if hm:
            h, mi = hm
            nxt = _next_daily(now, h, mi)
            return {
                "kind": "daily",
                "hour": h,
                "minute": mi,
                "next_run_at": nxt.timestamp(),
            }

    m = _RE_EVERY_DAY.search(text)
    if m and "mỗi" in text:
        h = int(m.group(1))
        mi = int(m.group(2) or 0)
        h, mi = _apply_period(h, mi, text)
        if 0 <= h <= 23 and 0 <= mi <= 59:
            nxt = _next_daily(now, h, mi)
            return {
                "kind": "daily",
                "hour": h,
                "minute": mi,
                "next_run_at": nxt.timestamp(),
            }

    # relative: sau 30 phút
    m = _RE_IN.search(text)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit in ("giờ", "gio", "h", "tiếng", "tieng"):
            delta = timedelta(hours=n)
        elif unit in ("ngày", "ngay", "d"):
            delta = timedelta(days=n)
        else:
            delta = timedelta(minutes=n)
        due = now + delta
        return {
            "kind": "once",
            "due_at": due.timestamp(),
            "next_run_at": due.timestamp(),
        }

    # bare "30" / "30 phút"
    m = _RE_BARE_MIN.match(text.strip())
    if m:
        n = int(m.group(1))
        due = now + timedelta(minutes=max(1, n))
        return {
            "kind": "once",
            "due_at": due.timestamp(),
            "next_run_at": due.timestamp(),
        }

    # absolute "lúc 7h sáng" / "19:30"
    parsed = _parse_absolute(text, now)
    if parsed:
        return parsed

    return None


def _parse_hm(s: str) -> tuple[int, int] | None:
    s = (s or "").strip()
    m = re.match(r"^(\d{1,2})[:hH](\d{0,2})$", s)
    if not m:
        m = re.match(r"^(\d{1,2})$", s)
        if m:
            h = int(m.group(1))
            return (h, 0) if 0 <= h <= 23 else None
        return None
    h = int(m.group(1))
    mi = int(m.group(2) or 0)
    if 0 <= h <= 23 and 0 <= mi <= 59:
        return h, mi
    return None


def _extract_hm(text: str) -> tuple[int, int] | None:
    m = _RE_AT_HM.search(text)
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2) or 0)
    period = (m.group(3) or "").lower()
    h, mi = _apply_period(h, mi, period or text)
    if 0 <= h <= 23 and 0 <= mi <= 59:
        return h, mi
    return None


def _apply_period(h: int, mi: int, text: str) -> tuple[int, int]:
    t = (text or "").lower()
    if any(x in t for x in ("chiều", "chieu", "tối", "toi")) and h < 12:
        h += 12
    elif any(x in t for x in ("sáng", "sang", "trưa", "trua")) and h == 12:
        h = 12
    return h, mi


def _next_daily(now: datetime, hour: int, minute: int) -> datetime:
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    return candidate


def _parse_absolute(text: str, now: datetime) -> dict[str, Any] | None:
    text = (text or "").strip()
    # ISO date-time
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(text[:19], fmt).replace(tzinfo=_TZ)
            if dt > now:
                return {
                    "kind": "once",
                    "due_at": dt.timestamp(),
                    "next_run_at": dt.timestamp(),
                }
        except ValueError:
            pass

    hm = _extract_hm(text) or _parse_hm(text)
    if not hm:
        return None
    h, mi = hm
    candidate = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    # "mai"
    if "mai" in text.lower() and "mãi" not in text.lower():
        candidate = candidate + timedelta(days=1)
        # if we already advanced via "mai", don't double-shift if time was past
    elif candidate <= now:
        candidate = candidate + timedelta(days=1)
    return {
        "kind": "once",
        "due_at": candidate.timestamp(),
        "next_run_at": candidate.timestamp(),
    }


def _load_rrule(row: dict[str, Any]) -> dict[str, Any] | None:
    raw = row.get("rrule")
    if not raw:
        return None
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
        return d if isinstance(d, dict) else None
    except Exception:
        return None


_UNIT_VN = {"second": "giây", "minute": "phút", "hour": "giờ", "day": "ngày",
            "week": "tuần", "month": "tháng", "year": "năm"}
_THU_NHAN = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
_SKIP_NHAN = {"le": "lễ", "tet": "Tết", "bu": "nghỉ bù"}


def _fmt_rrule(spec: dict[str, Any]) -> str:
    unit = str(spec.get("unit") or "day")
    n = int(spec.get("n") or 1)
    don_vi = _UNIT_VN.get(unit, unit)
    if unit in ("second", "minute", "hour"):
        return f"mỗi {n} {don_vi}" if n > 1 else f"mỗi {don_vi}"
    gio = f"{int(spec.get('hour') or 0):02d}:{int(spec.get('minute') or 0):02d}"
    dau = f"mỗi {n} {don_vi}" if n > 1 else f"mỗi {don_vi}"
    wds = spec.get("weekdays")
    if wds:
        cac_thu = " ".join(_THU_NHAN[w] for w in wds if 0 <= w <= 6)
        dau = f"{cac_thu} hằng tuần" if unit == "week" else cac_thu
    elif unit == "month":
        dau = f"ngày {int(spec.get('day') or 1)} hằng tháng"
    elif unit == "year":
        dau = f"{int(spec.get('day') or 1)}/{int(spec.get('month') or 1)} hằng năm"
    kem = ""
    sk = spec.get("skip")
    if sk:
        kem = " (trừ " + ", ".join(_SKIP_NHAN.get(x, x) for x in sk) + ")"
    return f"{dau} lúc {gio}{kem}"


def _fmt_when(row: dict[str, Any]) -> str:
    kind = row.get("kind") or "once"
    try:
        nxt = float(row.get("next_run_at") or 0)
        dt = datetime.fromtimestamp(nxt, _TZ)
        when_s = dt.strftime("%H:%M %d/%m/%Y")
    except Exception:
        when_s = "?"
    if kind == "recur":
        spec = _load_rrule(row)
        if spec:
            return f"{_fmt_rrule(spec)} (kế: {when_s})"
        return f"lặp (kế: {when_s})"
    if kind == "interval":
        return f"mỗi {row.get('interval_min')} phút (kế: {when_s})"
    if kind == "daily":
        return f"mỗi ngày {int(row.get('hour') or 0):02d}:{int(row.get('minute') or 0):02d} (kế: {when_s})"
    return f"một lần lúc {when_s}"


# ── CRUD ─────────────────────────────────────────────────────────────────────


def _capture_delivery_ctx(channel: str) -> dict[str, Any]:
    """Bối cảnh GỬI tại thời điểm tạo reminder (đang ở thread xử lý tin của
    kênh): bot nào nhận tin thì đúng bot đó gửi nhắc (đa-bot); Zalo Cá Nhân
    thêm account nhận + loại thread (nhóm/cá nhân) — kẻo nhắc trong NHÓM bị
    gửi sai loại. Best-effort: ngoài ngữ cảnh kênh → {} (giữ hành vi cũ)."""
    ctx: dict[str, Any] = {}
    try:
        if channel == "tg":
            from services.telegram_bot import _bot_id
            if _bot_id():
                ctx["bot_id"] = _bot_id()
        elif channel == "zalo":
            from services.zalo_bot import _bot_id
            if _bot_id():
                ctx["bot_id"] = _bot_id()
        elif channel == "zalop":
            from services.zalo_personal import current_msg_ctx
            acc, ttype = current_msg_ctx()
            if acc:
                ctx["account"] = acc
            ctx["thread_type"] = int(ttype)
    except Exception:
        pass
    return ctx


_MODES = ("notify", "task", "loa")


def create(
    user_id: str,
    text: str,
    schedule: dict[str, Any],
    *,
    mode: str = "notify",
    meta_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a reminder. ``schedule`` from parse_when().

    `mode`:
      notify — gửi tin nhắc vào chat
      task   — chạy một việc rồi báo kết quả
      loa    — ĐỌC RA LOA. `meta_extra` mang {speaker_id, audio_path, volume,
               voice}: âm thanh đã được tổng hợp SẴN lúc đặt lịch và ghi ra file
               (tiền tố `lich_` nên `cleanup_media` không dọn). Tới giờ chỉ việc
               phát file đó — không cần TTS lại, nên lịch vẫn chạy đúng dù lúc đó
               engine giọng đang lỗi hoặc model chưa nạp.

    `meta_extra` gộp vào cột `meta` sẵn có, không thêm cột mới.
    """
    if not is_enabled():
        raise RuntimeError("Nhắc hẹn đang tắt (agent_reminders.enabled=false).")
    text = (text or "").strip()
    if not text:
        raise ValueError("Thiếu nội dung nhắc / nhiệm vụ.")
    if not schedule or not schedule.get("next_run_at"):
        raise ValueError("Không hiểu thời điểm. VD: 'sau 30 phút', 'mỗi ngày 7h', '19:30'.")
    mode = str(mode).lower() if str(mode).lower() in _MODES else "notify"
    channel, chat_id = channel_of(user_id)
    _meta = _capture_delivery_ctx(channel)
    if isinstance(meta_extra, dict):
        _meta.update(meta_extra)
    meta_json = json.dumps(_meta, ensure_ascii=False)
    rid = uuid.uuid4().hex[:12]
    now = time.time()
    row = {
        "id": rid,
        "user_id": str(user_id),
        "channel": channel,
        "chat_id": str(chat_id),
        "mode": mode,
        "text": text[:2000],
        "kind": schedule.get("kind") or "once",
        "due_at": schedule.get("due_at"),
        "interval_min": schedule.get("interval_min"),
        "hour": schedule.get("hour"),
        "minute": schedule.get("minute"),
        "next_run_at": float(schedule["next_run_at"]),
        "enabled": 1,
        "created_at": now,
        "last_run_at": None,
        "runs": 0,
        "meta": meta_json,
        "rrule": json.dumps(schedule["rrule"], ensure_ascii=False)
        if schedule.get("rrule") else None,
    }
    with _lock:
        _db().execute(
            "INSERT INTO reminders "
            "(id,user_id,channel,chat_id,mode,text,kind,due_at,interval_min,"
            "hour,minute,next_run_at,enabled,created_at,last_run_at,runs,meta,rrule) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["id"], row["user_id"], row["channel"], row["chat_id"],
                row["mode"], row["text"], row["kind"], row["due_at"],
                row["interval_min"], row["hour"], row["minute"],
                row["next_run_at"], 1, now, None, 0, meta_json, row["rrule"],
            ),
        )
        _db().commit()
    return row


def list_for(user_id: str, *, include_disabled: bool = False) -> list[dict[str, Any]]:
    with _lock:
        if include_disabled:
            rows = _db().execute(
                "SELECT * FROM reminders WHERE user_id=? ORDER BY next_run_at",
                (str(user_id),),
            ).fetchall()
        else:
            rows = _db().execute(
                "SELECT * FROM reminders WHERE user_id=? AND enabled=1 "
                "ORDER BY next_run_at",
                (str(user_id),),
            ).fetchall()
    return [dict(r) for r in rows]


def _xoa_audio_cua_lich(rows: list[dict[str, Any]]) -> None:
    """Xoá file âm thanh của lịch đọc ra loa khi lịch bị huỷ.

    File này có tiền tố `lich_` nên `cleanup_media` CỐ Ý không dọn theo tuổi (lịch
    tuần sau vẫn phải còn tiếng). Nên nó chỉ có đúng một đường ra: huỷ lịch.
    """
    from pathlib import Path
    for r in rows:
        if (r.get("mode") or "") != "loa":
            continue
        try:
            meta = json.loads(str(r.get("meta") or "{}"))
            duong = str((meta or {}).get("audio_path") or "").strip()
            if duong:
                p = Path(duong)
                if p.is_file():
                    p.unlink()
        except Exception as exc:
            logger.info("agent.reminders: chưa xoá được audio lịch %s (%s)",
                        r.get("id"), str(exc)[:80])


def cancel(user_id: str, reminder_id: str) -> bool:
    rid = (reminder_id or "").strip()
    if not rid:
        return False
    with _lock:
        rows = [dict(r) for r in _db().execute(
            "SELECT * FROM reminders WHERE id=? AND user_id=?", (rid, str(user_id)),
        ).fetchall()]
        cur = _db().execute(
            "UPDATE reminders SET enabled=0 WHERE id=? AND user_id=?",
            (rid, str(user_id)),
        )
        _db().commit()
        ok = cur.rowcount > 0
    if ok:
        _xoa_audio_cua_lich(rows)
    return ok


def cancel_all(user_id: str) -> int:
    with _lock:
        rows = [dict(r) for r in _db().execute(
            "SELECT * FROM reminders WHERE user_id=? AND enabled=1", (str(user_id),),
        ).fetchall()]
        cur = _db().execute(
            "UPDATE reminders SET enabled=0 WHERE user_id=? AND enabled=1",
            (str(user_id),),
        )
        _db().commit()
        n = cur.rowcount
    _xoa_audio_cua_lich(rows)
    return n


_MODE_NHAN = {"notify": "nhắc", "task": "việc", "loa": "loa"}


def describe(row: dict[str, Any]) -> str:
    mode_s = _MODE_NHAN.get(str(row.get("mode") or ""), "việc")
    return f"• `{row['id']}` [{mode_s}] {_fmt_when(row)} — {row.get('text', '')[:80]}"


# ── Delivery ─────────────────────────────────────────────────────────────────


def _send(channel: str, chat_id: str, text: str,
          meta: dict[str, Any] | None = None) -> None:
    text = (text or "").strip()
    if not text:
        return
    # Telegram hard limit ~4096; keep safe
    if len(text) > 3500:
        text = text[:3500] + "…"
    meta = meta or {}
    if channel == "tg":
        # Gửi bằng ĐÚNG bot đã nhận tin lúc tạo (đa-bot) — thiếu meta thì như cũ.
        from services import telegram_bot as _tg
        bot = _tg._find_bot_by_id(str(meta.get("bot_id") or ""))
        prev = _tg._cur_bot()
        try:
            if bot is not None:
                _tg._current.bot = bot
            _tg.send_message(chat_id, text)
        finally:
            _tg._current.bot = prev
    elif channel == "zalo":
        from services import zalo_bot as _zb
        bot = _zb._find_bot_by_id(str(meta.get("bot_id") or ""))
        prev = _zb._cur_bot()
        try:
            if bot is not None:
                _zb._current.bot = bot
            _zb.send_message(chat_id, text)
        finally:
            _zb._current.bot = prev
    elif channel == "zalop":
        from services.zalo_personal import send_message
        send_message(chat_id, text, int(meta.get("thread_type") or 0),
                     account=str(meta.get("account") or ""))
    else:
        logger.warning("agent.reminders: unknown channel %s", channel)


def _task_model(channel: str, chat_id: str, meta: dict) -> str:
    """Model ĐÚNG kênh gốc của nhắc nhở (như lúc user chat) — tránh dùng
    model mặc định (_main_model) vốn có thể là provider web cookie hết hạn."""
    try:
        if channel == "tg":
            from services.telegram_bot import _tg_model
            return _tg_model(chat_id) or ""
        if channel == "zalo":
            from services.zalo_bot import _zalo_model
            return _zalo_model(chat_id) or ""
        if channel == "zalop":
            from services.zalo_personal import _ai_model
            return _ai_model(str(meta.get("account") or ""), chat_id) or ""
    except Exception as exc:
        logger.warning("reminders: _task_model %s: %s", channel, exc)
    return ""


def _run_task(user_id: str, prompt: str, *, channel: str = "",
              chat_id: str = "", meta: dict | None = None) -> str:
    """Run a one-shot agent turn for a scheduled task (no nested scheduling loop)."""
    from services.agent.orchestrator import orchestrate
    model = _task_model(channel, chat_id, meta or {}) if channel else ""
    # auto_approve=True: user ĐÃ đồng ý khi tạo nhắc nhở → tới giờ TỰ chạy,
    # KHÔNG hỏi duyệt lại (nếu không sẽ mâu thuẫn 'em sẽ tự gửi' rồi lại hỏi).
    out = orchestrate(
        f"[Nhắc việc theo lịch — làm ngay và trả lời ngắn gọn, KHÔNG hỏi lại]\n{prompt}",
        user_id,
        ha_fastpath=True,
        auto_approve=True,
        model=model or None,
    )
    if out.get("silent"):
        return ""
    return str(out.get("text") or "").strip()


def _advance(row: dict[str, Any], now_ts: float) -> None:
    """After fire: disable once, or compute next_run for recurring."""
    rid = row["id"]
    kind = row.get("kind") or "once"
    with _lock:
        if kind == "once":
            _db().execute(
                "UPDATE reminders SET enabled=0, last_run_at=?, runs=runs+1 WHERE id=?",
                (now_ts, rid),
            )
        elif kind == "interval":
            mins = max(5, int(row.get("interval_min") or 60))
            nxt = now_ts + mins * 60
            _db().execute(
                "UPDATE reminders SET next_run_at=?, last_run_at=?, runs=runs+1 WHERE id=?",
                (nxt, now_ts, rid),
            )
        elif kind == "daily":
            h = int(row.get("hour") or 0)
            mi = int(row.get("minute") or 0)
            now = datetime.fromtimestamp(now_ts, _TZ)
            # next day same time (skip if still same slot)
            nxt_dt = _next_daily(now + timedelta(seconds=1), h, mi)
            _db().execute(
                "UPDATE reminders SET next_run_at=?, last_run_at=?, runs=runs+1 WHERE id=?",
                (nxt_dt.timestamp(), now_ts, rid),
            )
        elif kind == "recur":
            spec = _load_rrule(row)
            now_dt = datetime.fromtimestamp(now_ts, _TZ)
            nxt = lich_lap.next_run(spec, now_dt, _TZ) if spec else None
            if nxt:
                _db().execute(
                    "UPDATE reminders SET next_run_at=?, last_run_at=?, runs=runs+1 WHERE id=?",
                    (nxt.timestamp(), now_ts, rid),
                )
            else:
                # rrule hỏng hoặc không còn mốc kế → tắt, không treo mãi.
                _db().execute(
                    "UPDATE reminders SET enabled=0, last_run_at=?, runs=runs+1 WHERE id=?",
                    (now_ts, rid),
                )
        else:
            _db().execute(
                "UPDATE reminders SET enabled=0, last_run_at=?, runs=runs+1 WHERE id=?",
                (now_ts, rid),
            )
        _db().commit()


def _due_rows(now_ts: float) -> list[dict[str, Any]]:
    with _lock:
        rows = _db().execute(
            "SELECT * FROM reminders WHERE enabled=1 AND next_run_at IS NOT NULL "
            "AND next_run_at <= ? "
            # FIX6 (audit 2026-07): last_run_at cũng là marker "đã thử gửi"
            # (ghi TRƯỚC _send trong _fire) — nếu nó >= next_run_at của chính
            # dòng này tức là lần bắn gần nhất đã attempt cho ĐÚNG cữ hẹn này
            # rồi (đang chờ _advance hoàn tất hoặc crash giữa chừng), KHÔNG
            # chọn lại để tránh gửi trùng; qua chu kỳ sau _advance() đã đẩy
            # next_run_at vượt qua last_run_at nên lại due bình thường.
            "AND (last_run_at IS NULL OR last_run_at < next_run_at) "
            "ORDER BY next_run_at LIMIT 20",
            (now_ts,),
        ).fetchall()
    return [dict(r) for r in rows]


def tick_once() -> int:
    """Process due reminders. Returns number fired. Safe to call from tests."""
    if not is_enabled():
        return 0
    now_ts = time.time()
    due = _due_rows(now_ts)
    fired = 0
    for row in due:
        try:
            _fire(row, now_ts)
            fired += 1
        except Exception as exc:
            logger.warning(
                "agent.reminders: fire %s failed: %s", row.get("id"), exc,
            )
            # still advance so a broken item doesn't block forever
            try:
                _advance(row, now_ts)
            except Exception:
                pass
    return fired


def _phat_ra_loa(meta: dict[str, Any], text: str) -> tuple[bool, str]:
    """Phát âm thanh của lịch ra loa. Trả (xong chưa, tên loa / lý do hỏng).

    Âm thanh đã tổng hợp SẴN lúc đặt lịch (`meta['audio_path']`), nên tới giờ chỉ
    việc đẩy URL cho loa kéo về — lịch vẫn chạy đúng dù engine giọng đang lỗi.
    File mất (bị dọn tay, đổi volume) thì TTS lại tại chỗ để lịch không im lặng
    trôi qua.

    Âm lượng: đặt mức của lịch rồi TRẢ VỀ mức cũ sau khi đọc xong — giống đường
    phát ngay (xem `announce._run`).
    """
    from pathlib import Path

    from services import voice
    from services.voice import announce as vann
    from services.voice import speakers as vspk

    sid = str(meta.get("speaker_id") or "").strip()
    rec = vspk.get(sid) if sid else None
    if not rec:
        return False, f"không còn loa nào có id «{sid}»"

    muc_cu: float | None = None
    vol = meta.get("volume")
    try:
        if vol not in (None, ""):
            try:
                muc_cu = vspk.get_volume(rec)
            except Exception:
                muc_cu = None
            try:
                vspk.set_volume(rec, float(vol))
            except Exception as exc:
                muc_cu = None
                logger.info("reminders: bỏ qua đặt âm lượng (%s)", str(exc)[:80])

        # Lịch có mức riêng thì phát bằng bản ghi KHÔNG mang âm lượng mặc định
        # của sổ loa — để nguyên thì `_play_cast` vặn đè lên mức của lịch.
        rec_phat = vspk.bo_am_luong_mac_dinh(rec) if vol not in (None, "") else rec
        duong = str(meta.get("audio_path") or "").strip()
        p = Path(duong) if duong else None
        if p is not None and p.is_file():
            url = voice.media_url(p)
            voice.play_on(rec_phat, url)
        else:
            # File đã mất → đọc lại tại chỗ, giữ đúng giọng đã chọn lúc đặt lịch.
            logger.warning("reminders: mất file âm thanh của lịch (%s) — TTS lại", duong)
            url = voice.play_text_on(text, rec_phat, str(meta.get("voice") or ""))
        if muc_cu is not None:
            vann._tra_am_luong_sau_khi_phat(rec, muc_cu, str(url or ""))
        return True, str(rec.get("name") or sid)
    except Exception as exc:
        if muc_cu is not None:
            try:
                vspk.set_volume(rec, float(muc_cu))
            except Exception:
                pass
        return False, str(exc)[:200]


def _fire(row: dict[str, Any], now_ts: float) -> None:
    mode = row.get("mode") or "notify"
    channel = row.get("channel") or "tg"
    chat_id = str(row.get("chat_id") or "")
    text = str(row.get("text") or "")
    user_id = str(row.get("user_id") or "")
    try:
        meta = json.loads(str(row.get("meta") or "{}"))
        if not isinstance(meta, dict):
            meta = {}
    except Exception:
        meta = {}

    # FIX6 (audit 2026-07): đánh dấu "đã thử gửi" TRƯỚC khi gọi _send — nếu
    # tiến trình crash NGAY SAU khi gửi xong nhưng TRƯỚC khi _advance() cập
    # nhật lịch, tick sau (~20s) sẽ KHÔNG chọn lại dòng này nữa (xem guard
    # last_run_at < next_run_at trong _due_rows) nên không gửi trùng. Tái
    # dùng cột last_run_at có sẵn — không cần ALTER TABLE thêm cột mới.
    rid = row.get("id")
    with _lock:
        try:
            _db().execute(
                "UPDATE reminders SET last_run_at=? WHERE id=?", (now_ts, rid),
            )
            _db().commit()
        except Exception as exc:
            logger.warning("agent.reminders: mark attempted %s failed: %s", rid, exc)

    if mode == "task":
        try:
            result = _run_task(user_id, text, channel=channel,
                               chat_id=chat_id, meta=meta)
        except Exception as exc:
            result = f"(lỗi khi chạy việc: {str(exc)[:120]})"
        body = result or f"Đã xử lý: {text}"
        _send(channel, chat_id, f"⏰ Việc theo lịch:\n{body}", meta)
    elif mode == "loa":
        ok, chi_tiet = _phat_ra_loa(meta, text)
        _send(channel, chat_id,
              f"🔊 Đã đọc ra {chi_tiet}:\n{text}" if ok
              else f"🔊 Lịch đọc ra loa không chạy được ạ: {chi_tiet}", meta)
    else:
        _send(channel, chat_id, f"⏰ Nhắc anh/chị: {text}", meta)

    # FIX6 (audit 2026-07): cô lập _advance khỏi lỗi gửi — trước đây lỗi
    # UPDATE của _advance() lẫn vào cùng khối với _send(), khiến tick_once()
    # log nhầm "fire failed" dù tin đã gửi xong, và (trước khi có marker ở
    # trên) tick sau còn gửi lặp lại. Giờ lỗi advance chỉ log riêng, không
    # ném ngược lên tick_once().
    try:
        _advance(row, now_ts)
    except Exception as exc:
        logger.warning(
            "agent.reminders: advance %s failed (đã gửi rồi, marker last_run_at "
            "chặn gửi lặp): %s", row.get("id"), exc,
        )
    logger.info(
        "agent.reminders: fired id=%s mode=%s channel=%s",
        row.get("id"), mode, channel,
    )


def _loop() -> None:
    while not _stop.is_set():
        try:
            tick_once()
        except Exception as exc:
            logger.warning("agent.reminders: tick error: %s", exc)
        _stop.wait(_tick_seconds())


def start() -> None:
    """Start the background tick thread (idempotent)."""
    global _started
    if _started or not is_enabled():
        return
    _started = True
    _stop.clear()
    t = threading.Thread(target=_loop, name="agent-reminders", daemon=True)
    t.start()
    logger.info("agent.reminders: scheduler started")


def stop() -> None:
    global _started
    _stop.set()
    _started = False


def _reset_for_tests(db_path: Path | None = None) -> None:
    global _conn, _DB_PATH, _started
    stop()
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None
        if db_path is not None:
            _DB_PATH = Path(db_path)
    _started = False
