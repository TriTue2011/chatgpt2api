"""Agent / API run journal — audit of tools, latency, model, source & dest account.

Stored in ``DATA_DIR/agent/runs.sqlite``. Logged from:
  - agent orchestrator (Telegram / Zalo / email bot turns)
  - gateway LoggedCall for external HA / OpenAPI / web chat completions

Config (``agent_run_journal``)::

    enabled: bool (default True)
    max_rows: int (default 2000) — prune oldest beyond this
    log_api: bool (default True) — also journal /v1/chat/completions etc.
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

# Columns added after initial schema — migrated via ALTER TABLE.
_EXTRA_COLS: tuple[tuple[str, str], ...] = (
    ("source_kind", "TEXT NOT NULL DEFAULT ''"),
    ("source_account", "TEXT NOT NULL DEFAULT ''"),
    ("source_peer", "TEXT NOT NULL DEFAULT ''"),
    ("dest_provider", "TEXT NOT NULL DEFAULT ''"),
    ("dest_account", "TEXT NOT NULL DEFAULT ''"),
    ("dest_model", "TEXT NOT NULL DEFAULT ''"),
    ("request_id", "TEXT NOT NULL DEFAULT ''"),
)


def _cfg() -> dict[str, Any]:
    raw = config.get().get("agent_run_journal")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def log_api_enabled() -> bool:
    return bool(_cfg().get("log_api", True))


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
        # migrate extra columns
        existing = {
            str(r[1]) for r in conn.execute("PRAGMA table_info(runs)").fetchall()
        }
        for col, decl in _EXTRA_COLS:
            if col not in existing:
                try:
                    conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {decl}")
                except Exception:
                    pass
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_source ON runs(source_kind, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_channel ON runs(channel, created_at DESC)"
        )
        conn.commit()
        _conn = conn
    return _conn


def _channel_of(user_id: str, source_kind: str = "") -> str:
    uid = str(user_id or "")
    sk = str(source_kind or "").lower()
    if sk in {"ha", "openapi", "web", "api", "tg", "zalo", "zalop", "email", "agent"}:
        if sk == "api":
            return "openapi"
        return sk
    if uid.startswith("zalop_"):
        return "zalop"
    if uid.startswith("zalo_"):
        return "zalo"
    if uid.startswith("email_"):
        return "email"
    if uid.startswith("ha_") or uid.startswith("ha:"):
        return "ha"
    if uid.startswith("api_") or uid.startswith("key_"):
        return "openapi"
    return "tg" if uid else (sk or "")


def log_run(
    *,
    user_id: str = "",
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
    source_kind: str = "",
    source_account: str = "",
    source_peer: str = "",
    dest_provider: str = "",
    dest_account: str = "",
    dest_model: str = "",
    request_id: str = "",
    channel: str = "",
) -> Optional[str]:
    """Insert one run row. Returns run id or None if disabled."""
    if not is_enabled():
        return None
    rid = uuid.uuid4().hex[:12]
    now = time.time()
    tools = tools or []

    # Auto-fill dest from request_context when not provided
    if not dest_provider and not dest_account:
        try:
            from services import request_context as rc

            d = rc.get_dest()
            if d:
                dest_provider = dest_provider or str(d.get("provider") or "")
                dest_account = dest_account or str(d.get("account") or "")
                dest_model = dest_model or str(d.get("model") or "")
            trail = rc.get_dest_trail()
            if trail and meta is not None:
                meta = {**(meta or {}), "dest_trail": trail}
            elif trail:
                meta = {"dest_trail": trail}
        except Exception:
            pass

    # Auto-fill source from request_context
    if not source_kind and not source_account:
        try:
            from services import request_context as rc

            s = rc.get_source()
            if s:
                source_kind = source_kind or str(s.get("kind") or "")
                source_account = source_account or str(s.get("account") or "")
                source_peer = source_peer or str(s.get("peer") or "")
                if not user_id:
                    user_id = str(s.get("user_id") or "")
        except Exception:
            pass

    ch = channel or _channel_of(user_id, source_kind)

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
            "tools,steps,duration_ms,error,meta,created_at,"
            "source_kind,source_account,source_peer,"
            "dest_provider,dest_account,dest_model,request_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rid,
                str(user_id or "")[:200],
                str(ch or "")[:32],
                str(model or "")[:120],
                str(hint or "")[:40],
                str(status or "ok")[:32],
                str(user_text or "")[:1500],
                str(reply_text or "")[:2000],
                tools_json,
                int(steps or 0),
                int(duration_ms or 0),
                str(error or "")[:500],
                meta_json[:4000],
                now,
                str(source_kind or "")[:40],
                str(source_account or "")[:120],
                str(source_peer or "")[:200],
                str(dest_provider or "")[:80],
                str(dest_account or "")[:120],
                str(dest_model or "")[:120],
                str(request_id or "")[:64],
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
    source_kind: str = "",
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
    if source_kind:
        clauses.append("source_kind=?")
        params.append(str(source_kind))
    where = " AND ".join(clauses)
    params.append(limit)
    with _lock:
        rows = _db().execute(
            f"SELECT * FROM runs WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(_row_to_dict(r))
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
    return _row_to_dict(row)


def _row_to_dict(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    try:
        d["tools"] = json.loads(d.get("tools") or "[]")
    except Exception:
        d["tools"] = []
    try:
        d["meta"] = json.loads(d.get("meta") or "{}")
    except Exception:
        d["meta"] = {}
    # Convenience display fields
    d["from_label"] = _from_label(d)
    d["to_label"] = _to_label(d)
    return d


def _from_label(d: dict[str, Any]) -> str:
    kind = str(d.get("source_kind") or d.get("channel") or "").strip()
    acc = str(d.get("source_account") or "").strip()
    peer = str(d.get("source_peer") or "").strip()
    parts = [p for p in (kind, acc, peer) if p]
    if parts:
        return " · ".join(parts)
    uid = str(d.get("user_id") or "").strip()
    return uid or "—"


def _to_label(d: dict[str, Any]) -> str:
    prov = str(d.get("dest_provider") or "").strip()
    acc = str(d.get("dest_account") or "").strip()
    model = str(d.get("dest_model") or d.get("model") or "").strip()
    parts = [p for p in (prov, acc) if p]
    if parts:
        base = " · ".join(parts)
        return f"{base} ({model})" if model and model not in base else base
    return model or "—"


def stats(hours: int = 24) -> dict[str, Any]:
    if not is_enabled():
        return {
            "total": 0, "by_status": {}, "by_channel": {}, "by_source": {},
            "by_kind": {},
        }
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
        try:
            by_src = _db().execute(
                "SELECT source_kind, COUNT(*) c FROM runs WHERE created_at>=? "
                "GROUP BY source_kind",
                (since,),
            ).fetchall()
        except Exception:
            by_src = []
        try:
            # hint stores run kind: chat | vision | image_gen | video_gen | agent
            by_kind = _db().execute(
                "SELECT hint, COUNT(*) c FROM runs WHERE created_at>=? "
                "GROUP BY hint",
                (since,),
            ).fetchall()
        except Exception:
            by_kind = []
        avg_ms = _db().execute(
            "SELECT AVG(duration_ms) FROM runs WHERE created_at>=? AND duration_ms>0",
            (since,),
        ).fetchone()[0]
    return {
        "total": int(total or 0),
        "avg_duration_ms": int(avg_ms or 0),
        "by_status": {str(r[0]): int(r[1]) for r in by_st},
        "by_channel": {str(r[0] or "?"): int(r[1]) for r in by_ch},
        "by_source": {str(r[0] or "?"): int(r[1]) for r in by_src},
        "by_kind": {str(r[0] or "?"): int(r[1]) for r in by_kind if r[0]},
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
