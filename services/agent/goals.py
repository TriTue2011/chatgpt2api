"""Per-thread (user) goals / mini kanban for the agent.

Durable SQLite under ``DATA_DIR/agent/goals.sqlite``. Injected into the
system prompt so multi-turn work stays aligned.

Config (``agent_goals``)::

    enabled: bool (default True)
    max_open: int (default 12)
    prompt_max: int (default 6) — how many open goals appear in system prompt
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR, config

_DB_PATH = Path(DATA_DIR) / "agent" / "goals.sqlite"
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

_STATUSES = frozenset({"open", "doing", "done", "cancelled"})


def _cfg() -> dict[str, Any]:
    raw = config.get().get("agent_goals")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def max_open() -> int:
    try:
        return max(1, int(_cfg().get("max_open") or 12))
    except (TypeError, ValueError):
        return 12


def prompt_max() -> int:
    try:
        return max(1, int(_cfg().get("prompt_max") or 6))
    except (TypeError, ValueError):
        return 6


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS goals ("
            " id TEXT PRIMARY KEY,"
            " user_id TEXT NOT NULL,"
            " title TEXT NOT NULL,"
            " status TEXT NOT NULL DEFAULT 'open',"
            " notes TEXT NOT NULL DEFAULT '',"
            " priority INTEGER NOT NULL DEFAULT 0,"
            " created_at REAL,"
            " updated_at REAL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_goals_user "
            "ON goals(user_id, status, priority DESC, updated_at DESC)"
        )
        conn.commit()
        _conn = conn
    return _conn


def add(
    user_id: str,
    title: str,
    *,
    notes: str = "",
    priority: int = 0,
    status: str = "open",
) -> dict[str, Any]:
    if not is_enabled():
        raise RuntimeError("Goals đang tắt (agent_goals.enabled=false).")
    title = (title or "").strip()
    if not title:
        raise ValueError("Thiếu tiêu đề goal.")
    status = (status or "open").strip().lower()
    if status not in _STATUSES:
        status = "open"
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("Thiếu user_id.")
    open_n = len(list_for(uid, status="open")) + len(list_for(uid, status="doing"))
    if status in ("open", "doing") and open_n >= max_open():
        raise ValueError(f"Đã đủ {max_open()} goal đang mở — hoàn thành bớt trước ạ.")
    rid = uuid.uuid4().hex[:10]
    now = time.time()
    try:
        pri = int(priority)
    except (TypeError, ValueError):
        pri = 0
    row = {
        "id": rid,
        "user_id": uid,
        "title": title[:300],
        "status": status,
        "notes": (notes or "")[:2000],
        "priority": pri,
        "created_at": now,
        "updated_at": now,
    }
    with _lock:
        _db().execute(
            "INSERT INTO goals "
            "(id,user_id,title,status,notes,priority,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                row["id"], row["user_id"], row["title"], row["status"],
                row["notes"], row["priority"], now, now,
            ),
        )
        _db().commit()
    return row


def list_for(
    user_id: str,
    *,
    status: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    if not user_id:
        return []
    limit = max(1, min(int(limit or 30), 100))
    with _lock:
        if status and status in _STATUSES:
            rows = _db().execute(
                "SELECT * FROM goals WHERE user_id=? AND status=? "
                "ORDER BY priority DESC, updated_at DESC LIMIT ?",
                (str(user_id), status, limit),
            ).fetchall()
        else:
            rows = _db().execute(
                "SELECT * FROM goals WHERE user_id=? "
                "ORDER BY CASE status "
                " WHEN 'doing' THEN 0 WHEN 'open' THEN 1 "
                " WHEN 'done' THEN 2 ELSE 3 END, "
                "priority DESC, updated_at DESC LIMIT ?",
                (str(user_id), limit),
            ).fetchall()
    return [dict(r) for r in rows]


def get(user_id: str, goal_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        row = _db().execute(
            "SELECT * FROM goals WHERE id=? AND user_id=?",
            (str(goal_id), str(user_id)),
        ).fetchone()
    return dict(row) if row else None


def update(
    user_id: str,
    goal_id: str,
    *,
    title: str | None = None,
    status: str | None = None,
    notes: str | None = None,
    priority: int | None = None,
) -> Optional[dict[str, Any]]:
    cur = get(user_id, goal_id)
    if not cur:
        return None
    if title is not None and str(title).strip():
        cur["title"] = str(title).strip()[:300]
    if status is not None:
        st = str(status).strip().lower()
        if st in _STATUSES:
            cur["status"] = st
    if notes is not None:
        cur["notes"] = str(notes)[:2000]
    if priority is not None:
        try:
            cur["priority"] = int(priority)
        except (TypeError, ValueError):
            pass
    cur["updated_at"] = time.time()
    with _lock:
        _db().execute(
            "UPDATE goals SET title=?, status=?, notes=?, priority=?, updated_at=? "
            "WHERE id=? AND user_id=?",
            (
                cur["title"], cur["status"], cur["notes"], cur["priority"],
                cur["updated_at"], goal_id, str(user_id),
            ),
        )
        _db().commit()
    return cur


def set_status(user_id: str, goal_id: str, status: str) -> Optional[dict[str, Any]]:
    return update(user_id, goal_id, status=status)


def describe(row: dict[str, Any]) -> str:
    st = row.get("status") or "open"
    icon = {"open": "○", "doing": "◐", "done": "●", "cancelled": "✕"}.get(st, "·")
    pri = int(row.get("priority") or 0)
    p = f" P{pri}" if pri else ""
    return f"• `{row['id']}` {icon} [{st}]{p} {row.get('title', '')}"


def prompt_block(user_id: str) -> str:
    """Short block for system prompt (open + doing only)."""
    if not is_enabled() or not user_id:
        return ""
    rows = list_for(user_id, limit=prompt_max() * 2)
    active = [r for r in rows if r.get("status") in ("open", "doing")][: prompt_max()]
    if not active:
        return ""
    lines = ["## Mục tiêu đang theo dõi (thread goals)"]
    for r in active:
        lines.append(describe(r))
    lines.append(
        "Cập nhật qua tool `goals` (op=add|list|done|doing|cancel|update). "
        "Ưu tiên goal `doing` / priority cao."
    )
    return "\n".join(lines)


def _reset_for_tests(db_path: Path | None = None) -> None:
    global _conn, _DB_PATH
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None
        if db_path is not None:
            _DB_PATH = Path(db_path)
