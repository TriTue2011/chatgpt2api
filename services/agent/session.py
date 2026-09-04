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
import uuid
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


def soft_idle_s() -> float:
    """Nghỉ quá mốc này → CẤP PHIÊN MỚI, nhưng KHÔNG xoá đuôi, KHÔNG nén.

    Mốc "mềm": chỉ để gom lượt thành phiên (nén/tra theo phiên, trả lời được
    "hôm qua mình bàn gì"). Nối lại trong mốc cứng thì hội thoại vẫn liền mạch.
    """
    try:
        return max(60.0, float(_cfg().get("soft_idle_s") or 1800))
    except (TypeError, ValueError):
        return 1800.0


def hard_idle_s() -> float:
    """Nghỉ quá mốc này → hội thoại coi như ĐÓNG: xoá đuôi + nén vào tóm tắt.

    Mốc "cứng". Trước đây chỉ có MỘT mốc 10 phút làm luôn việc này, nên nghỉ ăn
    trưa xong hỏi tiếp là mất mạch. Để cấu hình được vì đánh đổi hai chiều: dài
    quá thì chủ đề nguội bám dai — đúng lỗi mốc 10 phút sinh ra để chặn.
    """
    try:
        return max(soft_idle_s(), float(_cfg().get("hard_idle_s") or 7200))
    except (TypeError, ValueError):
        return 7200.0


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
        # Cột thêm sau. `CREATE TABLE IF NOT EXISTS` KHÔNG thêm cột vào bảng đã
        # nằm sẵn trên máy chủ (đúng cái bẫy `muc_luc.py` đã ghi lại), nên phải
        # ALTER riêng. Chạy lại lần hai thì SQLite báo "duplicate column" — nuốt
        # đúng lỗi đó, lỗi khác vẫn để nổi.
        for bang, cot in (("turns", "message_id"), ("turns", "session_id"),
                          ("sessions", "session_id")):
            try:
                conn.execute(f"ALTER TABLE {bang} ADD COLUMN {cot} TEXT")
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_turns_msgid ON turns(user_id, message_id)"
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


def last_activity(user_id: str) -> float:
    """Thời điểm (epoch giây) phiên này được ghi gần nhất; 0.0 nếu chưa có.

    Dùng để ĐÓNG hội thoại đã nghỉ lâu: `updated_at` được cập nhật mỗi lần
    `save_history`/`set_summary`, nên khoảng cách tới `time.time()` là thời gian
    im lặng của người này.
    """
    if not is_enabled() or not user_id:
        return 0.0
    with _lock:
        row = _db().execute(
            "SELECT updated_at FROM sessions WHERE user_id=?", (str(user_id),)
        ).fetchone()
    try:
        return float(row[0]) if row and row[0] is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


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


def append_turn(user_id: str, role: str, content: str, *,
                message_id: str = "", session_id: str = "") -> int | None:
    """Append one turn to the searchable turns log (best-effort, never raises).

    ``message_id`` là mã tin của NỀN TẢNG (Zalo Bot gửi kèm mỗi tin) — có nó thì
    tra lại tin được TRÍCH DẪN là khớp chính xác, thay cho đoán theo mốc thời
    gian ±900 giây (trong nhóm đông, 15 phút có hàng chục tin → khớp nhầm).

    Trả `rowid` của lượt vừa ghi (hoặc None) để bên gọi còn vá `message_id` vào
    sau — lượt `assistant` được ghi TRƯỚC khi tin thật sự gửi đi, nên lúc ghi
    chưa biết mã tin đầu ra.
    """
    if not is_enabled() or not user_id:
        return None
    role = str(role or "").strip()
    content = (content or "").strip()
    if role not in ("user", "assistant") or not content:
        return None
    now = time.time()
    try:
        with _lock:
            db = _db()
            cur = db.execute(
                "INSERT INTO turns (user_id, role, content, created_at,"
                " message_id, session_id) VALUES (?,?,?,?,?,?)",
                (str(user_id), role, content[:8000], now,
                 str(message_id or ""), str(session_id or "")),
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
        return rid
    except Exception:
        return None  # never break the chat path


def set_message_id(rowid: int | None, message_id: str) -> None:
    """Vá mã tin vào một lượt đã ghi (best-effort).

    Cần vì lượt `assistant` được ghi TRƯỚC lúc gửi: mã tin đầu ra chỉ có sau khi
    nền tảng nhận. Nền tảng không trả mã thì bỏ qua, không phải lỗi.
    """
    if not is_enabled() or not rowid or not str(message_id or "").strip():
        return
    try:
        with _lock:
            db = _db()
            db.execute("UPDATE turns SET message_id=? WHERE id=?",
                       (str(message_id).strip(), int(rowid)))
            db.commit()
    except Exception:
        pass


def turn_by_message_id(user_id: str, message_id: str) -> dict[str, Any] | None:
    """Lượt mang đúng mã tin này → dict, hoặc None.

    Đường tra CHÍNH XÁC cho tin được trích dẫn, thay cho `turn_gan_ts` (khớp mốc
    thời gian ±900 giây, dễ vớ nhầm tin khác trong nhóm đông).
    """
    if not is_enabled() or not user_id or not str(message_id or "").strip():
        return None
    try:
        with _lock:
            row = _db().execute(
                "SELECT role, content, created_at FROM turns "
                "WHERE user_id=? AND message_id=? ORDER BY created_at DESC LIMIT 1",
                (str(user_id), str(message_id).strip()),
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return {"role": row[0], "content": row[1], "created_at": row[2]}


def current_session_id(user_id: str) -> str:
    """Mã phiên đang mở của người này ("" nếu chưa có)."""
    if not is_enabled() or not user_id:
        return ""
    try:
        with _lock:
            row = _db().execute(
                "SELECT session_id FROM sessions WHERE user_id=?", (str(user_id),)
            ).fetchone()
    except Exception:
        return ""
    return str(row[0] or "") if row else ""


def moi_phien(user_id: str) -> str:
    """Cấp mã phiên MỚI cho người này rồi trả về nó.

    Gọi khi im lặng vượt mốc MỀM. Chỉ đổi mã gom nhóm — không đụng tới đuôi hội
    thoại hay tóm tắt (việc đó là của mốc CỨNG).
    """
    if not is_enabled() or not user_id:
        return ""
    sid = uuid.uuid4().hex[:12]
    try:
        with _lock:
            db = _db()
            row = db.execute("SELECT user_id FROM sessions WHERE user_id=?",
                             (str(user_id),)).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO sessions (user_id, messages, summary, updated_at,"
                    " session_id) VALUES (?,?,?,?,?)",
                    (str(user_id), "[]", "", time.time(), sid),
                )
            else:
                db.execute("UPDATE sessions SET session_id=? WHERE user_id=?",
                           (sid, str(user_id)))
            db.commit()
    except Exception:
        return ""
    return sid


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


def turn_gan_ts(user_id: str, ts: float, *, cua_bot: bool | None = None,
                window_s: float = 600.0) -> dict[str, Any] | None:
    """Lượt chat GẦN mốc `ts` nhất của người này, trong cửa sổ ±`window_s`.

    Dùng cho dự phòng trích dẫn: nền tảng cho biết người dùng đang trả lời một
    tin CŨ và mốc thời gian của nó, nhưng KHÔNG kèm nội dung. `created_at` của
    turn xấp xỉ lúc tin đó được xử lý, nên khớp theo mốc gần nhất là lấy lại
    được nội dung.

    `cua_bot`: True chỉ xét lượt của bot (role=assistant), False chỉ xét lượt
    người dùng, None xét cả hai. Trả None nếu không có lượt nào đủ gần.
    """
    if not is_enabled() or not user_id or not ts:
        return None
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return None
    dieu_kien = "user_id=? AND ABS(created_at - ?) <= ?"
    tham_so: list[Any] = [str(user_id), ts, float(window_s)]
    if cua_bot is True:
        dieu_kien += " AND role='assistant'"
    elif cua_bot is False:
        dieu_kien += " AND role='user'"
    try:
        with _lock:
            row = _db().execute(
                "SELECT role, content, created_at FROM turns "
                f"WHERE {dieu_kien} ORDER BY ABS(created_at - ?) ASC LIMIT 1",
                (*tham_so, ts),
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return {"role": row[0], "content": row[1], "created_at": row[2]}


def users_active_since(ts: float) -> list[tuple[str, int]]:
    """user_id + số turn ghi được kể từ ``ts``, nhiều nhất trước — nguồn ứng
    viên cho pipeline chưng cất hồ sơ (services.agent.distill)."""
    if not is_enabled():
        return []
    try:
        with _lock:
            rows = _db().execute(
                "SELECT user_id, COUNT(*) AS n FROM turns WHERE created_at > ? "
                "GROUP BY user_id ORDER BY n DESC",
                (float(ts),),
            ).fetchall()
    except Exception:
        return []
    return [(str(r[0]), int(r[1])) for r in rows]


def count_turns_since(user_id: str, ts: float) -> int:
    """Số turn của một user kể từ ``ts`` — distill dùng để bỏ qua user chưa
    có đủ chất liệu mới."""
    if not is_enabled() or not user_id:
        return 0
    try:
        with _lock:
            row = _db().execute(
                "SELECT COUNT(*) FROM turns WHERE user_id=? AND created_at > ?",
                (str(user_id), float(ts)),
            ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


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
