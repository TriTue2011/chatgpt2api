"""Agent run journal — per-turn audit of tools, latency, model, status.

Stored in ``DATA_DIR/agent/runs.sqlite``. Orchestrator logs each completed
turn for the Runs UI and debugging multi-bot behaviour.

Config (``agent_run_journal``)::

    enabled: bool (default True)
    max_rows: int (default 2000) — prune oldest beyond this
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR, config

_DB_PATH = Path(DATA_DIR) / "agent" / "runs.sqlite"
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def _cfg() -> dict[str, Any]:
    raw = config.get().get("agent_run_journal")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def max_rows() -> int:
    try:
        return max(100, int(_cfg().get("max_rows") or 2000))
    except (TypeError, ValueError):
        return 2000


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS runs ("
            " id TEXT PRIMARY KEY,"
            " user_id TEXT NOT NULL,"
            " channel TEXT NOT NULL DEFAULT '',"
            " model TEXT NOT NULL DEFAULT '',"
            " hint TEXT NOT NULL DEFAULT '',"
            " status TEXT NOT NULL DEFAULT 'ok',"
            " user_text TEXT NOT NULL DEFAULT '',"
            " reply_text TEXT NOT NULL DEFAULT '',"
            " tools TEXT NOT NULL DEFAULT '[]',"
            " steps INTEGER NOT NULL DEFAULT 0,"
            " duration_ms INTEGER NOT NULL DEFAULT 0,"
            " error TEXT NOT NULL DEFAULT '',"
            " meta TEXT NOT NULL DEFAULT '{}',"
            " created_at REAL NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_user ON runs(user_id, created_at DESC)"
        )
        conn.commit()
        _conn = conn
    return _conn


def _channel_of(user_id: str) -> str:
    uid = str(user_id or "")
    if uid.startswith("zalop_"):
        return "zalop"
    if uid.startswith("zalo_"):
        return "zalo"
    if uid.startswith("email_"):
        return "email"
    return "tg" if uid else ""


def log_run(
    *,
    user_id: str,
    user_text: str = "",
    reply_text: str = "",
    model: str = "",
    hint: str = "",
    tools: list[str] | None = None,
    steps: int = 0,
    duration_ms: int = 0,
    status: str = "ok",
    error: str = "",
    meta: dict[str, Any] | None = None,
) -> Optional[str]:
    """Insert one run row. Returns run id or None if disabled."""
    if not is_enabled():
        return None
    rid = uuid.uuid4().hex[:12]
    now = time.time()
    tools = tools or []
    try:
        tools_json = json.dumps(list(tools)[:40], ensure_ascii=False)
    except Exception:
        tools_json = "[]"
    try:
        meta_json = json.dumps(meta or {}, ensure_ascii=False)
    except Exception:
        meta_json = "{}"
    with _lock:
        db = _db()
        db.execute(
            "INSERT INTO runs "
            "(id,user_id,channel,model,hint,status,user_text,reply_text,"
            "tools,steps,duration_ms,error,meta,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rid,
                str(user_id or ""),
                _channel_of(user_id),
                str(model or "")[:120],
                str(hint or "")[:40],
                str(status or "ok")[:32],
                str(user_text or "")[:1500],
                str(reply_text or "")[:2000],
                tools_json,
                int(steps or 0),
                int(duration_ms or 0),
                str(error or "")[:500],
                meta_json[:2000],
                now,
            ),
        )
        # prune
        try:
            cap = max_rows()
            db.execute(
                "DELETE FROM runs WHERE id IN ("
                " SELECT id FROM runs ORDER BY created_at DESC LIMIT -1 OFFSET ?"
                ")",
                (cap,),
            )
        except Exception:
            pass
        db.commit()
    return rid


def list_runs(
    *,
    limit: int = 50,
    user_id: str = "",
    channel: str = "",
    status: str = "",
) -> list[dict[str, Any]]:
    if not is_enabled():
        return []
    limit = max(1, min(int(limit or 50), 200))
    clauses = ["1=1"]
    params: list[Any] = []
    if user_id:
        clauses.append("user_id=?")
        params.append(str(user_id))
    if channel:
        clauses.append("channel=?")
        params.append(str(channel))
    if status:
        clauses.append("status=?")
        params.append(str(status))
    where = " AND ".join(clauses)
    params.append(limit)
    with _lock:
        rows = _db().execute(
            f"SELECT * FROM runs WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        try:
            d["tools"] = json.loads(d.get("tools") or "[]")
        except Exception:
            d["tools"] = []
        try:
            d["meta"] = json.loads(d.get("meta") or "{}")
        except Exception:
            d["meta"] = {}
        out.append(d)
    return out


def get_run(run_id: str) -> Optional[dict[str, Any]]:
    if not run_id:
        return None
    with _lock:
        row = _db().execute(
            "SELECT * FROM runs WHERE id=?", (str(run_id),)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["tools"] = json.loads(d.get("tools") or "[]")
    except Exception:
        d["tools"] = []
    try:
        d["meta"] = json.loads(d.get("meta") or "{}")
    except Exception:
        d["meta"] = {}
    return d


def stats(hours: int = 24) -> dict[str, Any]:
    if not is_enabled():
        return {"total": 0, "by_status": {}, "by_channel": {}}
    since = time.time() - max(1, int(hours)) * 3600
    with _lock:
        total = _db().execute(
            "SELECT COUNT(*) FROM runs WHERE created_at>=?", (since,),
        ).fetchone()[0]
        by_st = _db().execute(
            "SELECT status, COUNT(*) c FROM runs WHERE created_at>=? "
            "GROUP BY status",
            (since,),
        ).fetchall()
        by_ch = _db().execute(
            "SELECT channel, COUNT(*) c FROM runs WHERE created_at>=? "
            "GROUP BY channel",
            (since,),
        ).fetchall()
        avg_ms = _db().execute(
            "SELECT AVG(duration_ms) FROM runs WHERE created_at>=? AND duration_ms>0",
            (since,),
        ).fetchone()[0]
    return {
        "total": int(total or 0),
        "avg_duration_ms": int(avg_ms or 0),
        "by_status": {str(r[0]): int(r[1]) for r in by_st},
        "by_channel": {str(r[0] or "?"): int(r[1]) for r in by_ch},
        "hours": hours,
    }


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
