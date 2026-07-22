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

from services.config import DATA_DIR, config

logger = logging.getLogger(__name__)

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
            " meta TEXT DEFAULT '{}')"
        )
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
) -> dict[str, Any] | None:
    """Resolve schedule from structured args and/or free-text ``when``.

    Returns dict with keys: kind, next_run_at, and optional interval_min/hour/minute/due_at.
    """
    now = now or _now_vn()

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


def _fmt_when(row: dict[str, Any]) -> str:
    kind = row.get("kind") or "once"
    try:
        nxt = float(row.get("next_run_at") or 0)
        dt = datetime.fromtimestamp(nxt, _TZ)
        when_s = dt.strftime("%H:%M %d/%m/%Y")
    except Exception:
        when_s = "?"
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


def create(
    user_id: str,
    text: str,
    schedule: dict[str, Any],
    *,
    mode: str = "notify",
) -> dict[str, Any]:
    """Insert a reminder. ``schedule`` from parse_when()."""
    if not is_enabled():
        raise RuntimeError("Nhắc hẹn đang tắt (agent_reminders.enabled=false).")
    text = (text or "").strip()
    if not text:
        raise ValueError("Thiếu nội dung nhắc / nhiệm vụ.")
    if not schedule or not schedule.get("next_run_at"):
        raise ValueError("Không hiểu thời điểm. VD: 'sau 30 phút', 'mỗi ngày 7h', '19:30'.")
    mode = "task" if str(mode).lower() == "task" else "notify"
    channel, chat_id = channel_of(user_id)
    meta_json = json.dumps(_capture_delivery_ctx(channel), ensure_ascii=False)
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
    }
    with _lock:
        _db().execute(
            "INSERT INTO reminders "
            "(id,user_id,channel,chat_id,mode,text,kind,due_at,interval_min,"
            "hour,minute,next_run_at,enabled,created_at,last_run_at,runs,meta) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["id"], row["user_id"], row["channel"], row["chat_id"],
                row["mode"], row["text"], row["kind"], row["due_at"],
                row["interval_min"], row["hour"], row["minute"],
                row["next_run_at"], 1, now, None, 0, meta_json,
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


def cancel(user_id: str, reminder_id: str) -> bool:
    rid = (reminder_id or "").strip()
    if not rid:
        return False
    with _lock:
        cur = _db().execute(
            "UPDATE reminders SET enabled=0 WHERE id=? AND user_id=?",
            (rid, str(user_id)),
        )
        _db().commit()
        return cur.rowcount > 0


def cancel_all(user_id: str) -> int:
    with _lock:
        cur = _db().execute(
            "UPDATE reminders SET enabled=0 WHERE user_id=? AND enabled=1",
            (str(user_id),),
        )
        _db().commit()
        return cur.rowcount


def describe(row: dict[str, Any]) -> str:
    mode_s = "nhắc" if row.get("mode") == "notify" else "việc"
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


def _run_task(user_id: str, prompt: str) -> str:
    """Run a one-shot agent turn for a scheduled task (no nested scheduling loop)."""
    from services.agent.orchestrator import orchestrate
    # auto_approve=True: user ĐÃ đồng ý khi tạo nhắc nhở → tới giờ TỰ chạy,
    # KHÔNG hỏi duyệt lại (nếu không sẽ mâu thuẫn 'em sẽ tự gửi' rồi lại hỏi).
    out = orchestrate(
        f"[Nhắc việc theo lịch — làm ngay và trả lời ngắn gọn, KHÔNG hỏi lại]\n{prompt}",
        user_id,
        ha_fastpath=True,
        auto_approve=True,
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
            "AND next_run_at <= ? ORDER BY next_run_at LIMIT 20",
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

    if mode == "task":
        try:
            result = _run_task(user_id, text)
        except Exception as exc:
            result = f"(lỗi khi chạy việc: {str(exc)[:120]})"
        body = result or f"Đã xử lý: {text}"
        _send(channel, chat_id, f"⏰ Việc theo lịch:\n{body}", meta)
    else:
        _send(channel, chat_id, f"⏰ Nhắc anh/chị: {text}", meta)

    _advance(row, now_ts)
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
