"""Agent session store — durable conversation history per user_id.

History survives process restart / container rebuild (SQLite under
``DATA_DIR/agent/sessions.sqlite``). The orchestrator loads the recent tail
into the model; older turns stay on disk for search and compaction.

Config (top-level ``agent_session``, all optional)::

    enabled: bool (default True)
    max_history: int — messages loaded into the model (default 16)
    max_stored: int — hard cap of turns kept on disk per user (default 200)
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR, config

_DB_PATH = Path(DATA_DIR) / "agent" / "sessions.sqlite"
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

_WORD_RE = re.compile(r"[\wÀ-ỹ]{2,}", re.UNICODE)


def _cfg() -> dict[str, Any]:
    raw = config.get().get("agent_session")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def max_history() -> int:
    try:
        return max(4, int(_cfg().get("max_history") or 16))
    except (TypeError, ValueError):
        return 16


def max_stored() -> int:
    try:
        return max(20, int(_cfg().get("max_stored") or 200))
    except (TypeError, ValueError):
        return 200


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            " user_id TEXT PRIMARY KEY,"
            " messages TEXT NOT NULL DEFAULT '[]',"
            " summary TEXT NOT NULL DEFAULT '',"
            " updated_at REAL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS turns ("
            " id INTEGER PRIMARY KEY,"
            " user_id TEXT NOT NULL,"
            " role TEXT NOT NULL,"
            " content TEXT NOT NULL,"
            " created_at REAL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_turns_user ON turns(user_id, created_at)"
        )
        # FTS for full-text search over historical turns
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5("
            "content, content='turns', content_rowid='id', tokenize='unicode61')"
        )
        conn.commit()
        _conn = conn
    return _conn


def load_summary(user_id: str) -> str:
    """Return the compacted summary for this user (may be empty)."""
    if not is_enabled() or not user_id:
        return ""
    with _lock:
        row = _db().execute(
            "SELECT summary FROM sessions WHERE user_id=?", (str(user_id),)
        ).fetchone()
    return (row[0] if row else "") or ""


def set_summary(user_id: str, summary: str) -> None:
    if not is_enabled() or not user_id:
        return
    summary = (summary or "").strip()
    with _lock:
        db = _db()
        row = db.execute(
            "SELECT messages FROM sessions WHERE user_id=?", (str(user_id),)
        ).fetchone()
        if row is None:
            db.execute(
                "INSERT INTO sessions (user_id, messages, summary, updated_at) "
                "VALUES (?,?,?,?)",
                (str(user_id), "[]", summary, time.time()),
            )
        else:
            db.execute(
                "UPDATE sessions SET summary=?, updated_at=? WHERE user_id=?",
                (summary, time.time(), str(user_id)),
            )
        db.commit()


def load_history(user_id: str) -> list[dict[str, Any]]:
    """Load recent user/assistant messages for the model (tail of max_history)."""
    if not is_enabled() or not user_id:
        return []
    with _lock:
        row = _db().execute(
            "SELECT messages FROM sessions WHERE user_id=?", (str(user_id),)
        ).fetchone()
    if not row:
        return []
    try:
        msgs = json.loads(row[0] or "[]")
    except Exception:
        return []
    if not isinstance(msgs, list):
        return []
    clean: list[dict[str, Any]] = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        content = m.get("content")
        if role not in ("user", "assistant") or content is None:
            continue
        clean.append({"role": role, "content": str(content)})
    return clean[-max_history():]


def save_history(user_id: str, messages: list[dict[str, Any]]) -> None:
    """Persist the in-memory history tail (user/assistant only)."""
    if not is_enabled() or not user_id:
        return
    clean: list[dict[str, str]] = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        content = m.get("content")
        if role not in ("user", "assistant") or content is None:
            continue
        text = str(content)
        if not text.strip():
            continue
        clean.append({"role": role, "content": text})
    # Cap stored size
    clean = clean[-max_stored():]
    with _lock:
        db = _db()
        existing = db.execute(
            "SELECT summary FROM sessions WHERE user_id=?", (str(user_id),)
        ).fetchone()
        summary = existing[0] if existing else ""
        db.execute(
            "INSERT INTO sessions (user_id, messages, summary, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "messages=excluded.messages, updated_at=excluded.updated_at",
            (str(user_id), json.dumps(clean, ensure_ascii=False), summary or "", time.time()),
        )
        db.commit()


def append_turn(user_id: str, role: str, content: str) -> None:
    """Append one turn to the searchable turns log (best-effort, never raises)."""
    if not is_enabled() or not user_id:
        return
    role = str(role or "").strip()
    content = (content or "").strip()
    if role not in ("user", "assistant") or not content:
        return
    now = time.time()
    try:
        with _lock:
            db = _db()
            cur = db.execute(
                "INSERT INTO turns (user_id, role, content, created_at) VALUES (?,?,?,?)",
                (str(user_id), role, content[:8000], now),
            )
            rid = cur.lastrowid
            if rid:
                db.execute(
                    "INSERT INTO turns_fts (rowid, content) VALUES (?,?)",
                    (rid, content[:8000]),
                )
            # Prune old turns for this user
            max_t = max_stored() * 2
            old = db.execute(
                "SELECT id FROM turns WHERE user_id=? ORDER BY created_at DESC "
                "LIMIT -1 OFFSET ?",
                (str(user_id), max_t),
            ).fetchall()
            if old:
                ids = [r[0] for r in old]
                qs = ",".join("?" * len(ids))
                db.execute(f"DELETE FROM turns_fts WHERE rowid IN ({qs})", ids)
                db.execute(f"DELETE FROM turns WHERE id IN ({qs})", ids)
            db.commit()
    except Exception:
        pass  # never break the chat path


def search(user_id: str, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Full-text search past turns for this user. Returns newest-first matches."""
    if not is_enabled() or not user_id:
        return []
    words: list[str] = []
    seen: set[str] = set()
    for w in _WORD_RE.findall((query or "").lower()):
        if w not in seen:
            seen.add(w)
            words.append(w)
        if len(words) >= 12:
            break
    if not words:
        return []
    fts = " OR ".join(f'"{w}"' for w in words)
    limit = max(1, min(int(limit or 20), 50))
    try:
        with _lock:
            rows = _db().execute(
                "SELECT t.role, t.content, t.created_at "
                "FROM turns_fts JOIN turns t ON t.id = turns_fts.rowid "
                "WHERE turns_fts MATCH ? AND t.user_id=? "
                "ORDER BY t.created_at DESC LIMIT ?",
                (fts, str(user_id), limit),
            ).fetchall()
    except Exception:
        return []
    return [
        {"role": r[0], "content": r[1], "created_at": r[2]}
        for r in rows
    ]


def clear_history(user_id: str) -> None:
    """Wipe session messages + summary (turns log kept for audit/search)."""
    if not user_id:
        return
    with _lock:
        _db().execute("DELETE FROM sessions WHERE user_id=?", (str(user_id),))
        _db().commit()


def _reset_for_tests(db_path: Path | None = None) -> None:
    """Test helper: close and optionally repoint the DB."""
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
