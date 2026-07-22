"""
MemoryService — ký ức dài hạn TÍCH HỢP SẴN trong chatgpt2api (không cần
container/dịch vụ ngoài).

Mục đích: giữ "dòng suy nghĩ" giữa các phiên và khi xoay account — trước khi
dispatch, recall top-K ký ức liên quan từ SQLite và inject làm system message;
sau khi trả lời xong, lưu cặp user/assistant (thread nền, không chặn response).

Kho chứa: DATA_DIR/memory.sqlite (cùng volume với config.json → sống qua các
lần deploy/restart container). Tìm kiếm: SQLite FTS5 (bm25) + boost theo độ
mới — thuần Python, 0 dependency, 0 API call ngoài, recall <10ms.

An toàn flow: mọi lỗi đều nuốt — chat hoạt động y như khi không có memory.
Không áp dụng cho HA query, vision và image-generation. Tắt được qua config.

Config (top-level "memory", mọi field đều optional):
    enabled: bool (default TRUE — tắt bằng {"memory": {"enabled": false}})
    k: số ký ức inject (default 5)
    max_items: trần số ký ức mỗi user, vượt thì xoá cũ nhất (default 5000)
    user_id: default "chatgpt2api" (override per-request bằng field chuẩn
             OpenAI `user` trong body)
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
import time
from typing import Any, Iterator

from services.config import DATA_DIR, config
from utils.helper import IMAGE_MODELS
from utils.log import logger

_INJECT_HEADER = (
    "Ký ức liên quan từ các phiên làm việc trước (long-term memory — dùng để "
    "tiếp nối mạch công việc, KHÔNG cần nhắc lại với người dùng):"
)

_STORE_USER_MAX = 2000
_STORE_ASSISTANT_MAX = 3000
_INJECT_TOTAL_MAX = 2400
_MIN_QUERY_CHARS = 8
_PRUNE_EVERY = 50

_WORD_RE = re.compile(r"[\wÀ-ỹ]{2,}", re.UNICODE)


def _messages_have_images(messages: list[dict[str, Any]] | None) -> bool:
    for msg in messages or []:
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") in ("image", "image_url", "input_image"):
                    return True
    return False


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages or []):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [str(p.get("text") or "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
            return "\n".join(parts).strip()
    return ""


def _fts_query(text: str) -> str:
    """Build FTS5 OR-query từ keywords (quote từng từ để né syntax FTS)."""
    words: list[str] = []
    seen: set[str] = set()
    for w in _WORD_RE.findall(text.lower()):
        if w not in seen:
            seen.add(w)
            words.append(w)
        if len(words) >= 16:
            break
    return " OR ".join(f'"{w}"' for w in words)


class _MemoryCapture:
    """Giữ context 1 lượt chat để lưu ký ức sau khi có response."""

    def __init__(self, service: "MemoryService", user_id: str, user_text: str, model: str):
        self.service = service
        self.user_id = user_id
        self.user_text = user_text
        self.model = model

    def _store_turn(self, assistant_text: str) -> None:
        assistant_text = (assistant_text or "").strip()
        if not assistant_text:
            return
        user_part = self.user_text[:_STORE_USER_MAX]
        asst_part = assistant_text[:_STORE_ASSISTANT_MAX]
        # P1: never store raw MK/PII in long-term memory
        try:
            from services.privacy_gate import scrub_for_log, redact_memory_enabled
            if redact_memory_enabled():
                user_part = scrub_for_log(user_part, session_id=f"mem:{self.user_id}")
                asst_part = scrub_for_log(asst_part, session_id=f"mem:{self.user_id}")
        except Exception:
            pass
        content = (
            f"USER: {user_part}\n"
            f"ASSISTANT: {asst_part}"
        )
        self.service.store_async(content, self.user_id, model=self.model)

    def capture(self, result: Any) -> Any:
        # Non-stream: đọc content từ dict, trả nguyên vẹn
        if isinstance(result, dict):
            try:
                choices = result.get("choices") or []
                msg = choices[0].get("message") or {}
                self._store_turn(str(msg.get("content") or ""))
            except Exception:
                pass
            return result
        # Stream: tee — yield nguyên chunk, gom content, lưu khi stream xong
        return self._tee(result)

    def _tee(self, gen: Iterator[dict[str, Any]]) -> Iterator[dict[str, Any]]:
        parts: list[str] = []
        try:
            for chunk in gen:
                try:
                    choices = chunk.get("choices") or []
                    first = choices[0] if choices and isinstance(choices[0], dict) else {}
                    delta = first.get("delta") if isinstance(first.get("delta"), dict) else {}
                    text = str(delta.get("content") or "")
                    if text:
                        parts.append(text)
                except Exception:
                    pass
                yield chunk
        finally:
            try:
                self._store_turn("".join(parts))
            except Exception:
                pass


class MemoryService:
    def __init__(self) -> None:
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._store_count = 0

    # ------------------------------------------------------------------ cfg
    @property
    def _cfg(self) -> dict[str, Any]:
        cfg = config.data.get("memory")
        return cfg if isinstance(cfg, dict) else {}

    @property
    def is_enabled(self) -> bool:
        return bool(self._cfg.get("enabled", True))

    # ------------------------------------------------------------------- db
    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(DATA_DIR / "memory.sqlite"), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS memories ("
                " id INTEGER PRIMARY KEY,"
                " user_id TEXT NOT NULL,"
                " content TEXT NOT NULL,"
                " model TEXT DEFAULT '',"
                " hash TEXT UNIQUE,"
                " created_at REAL,"
                " last_seen_at REAL,"
                " uses INTEGER DEFAULT 0)"
            )
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5("
                "content, content='memories', content_rowid='id', tokenize='unicode61')"
            )
            conn.commit()
            self._conn = conn
        return self._conn

    # ---------------------------------------------------------------- store
    def store_async(self, content: str, user_id: str, model: str = "") -> None:
        def _worker():
            try:
                self._store(content, user_id, model)
            except Exception as exc:
                logger.warning({"event": "memory_store_fail", "error": str(exc)[:200]})

        threading.Thread(target=_worker, daemon=True).start()

    def _store(self, content: str, user_id: str, model: str = "") -> None:
        content = (content or "").strip()
        if not content:
            return
        h = hashlib.sha1((user_id + "\x00" + content).encode("utf-8")).hexdigest()
        now = time.time()
        with self._lock:
            db = self._db()
            cur = db.execute(
                "INSERT OR IGNORE INTO memories (user_id, content, model, hash, created_at, last_seen_at)"
                " VALUES (?,?,?,?,?,?)",
                (user_id, content, model, h, now, now),
            )
            if cur.rowcount:
                db.execute(
                    "INSERT INTO memories_fts (rowid, content) VALUES (?,?)",
                    (cur.lastrowid, content),
                )
            db.commit()
            self._store_count += 1
            if self._store_count % _PRUNE_EVERY == 0:
                self._prune(db, user_id)

    def _prune(self, db: sqlite3.Connection, user_id: str) -> None:
        max_items = int(self._cfg.get("max_items") or 5000)
        rows = db.execute(
            "SELECT id FROM memories WHERE user_id=? ORDER BY last_seen_at DESC LIMIT -1 OFFSET ?",
            (user_id, max_items),
        ).fetchall()
        if rows:
            ids = [r[0] for r in rows]
            qs = ",".join("?" * len(ids))
            db.execute(f"DELETE FROM memories_fts WHERE rowid IN ({qs})", ids)
            db.execute(f"DELETE FROM memories WHERE id IN ({qs})", ids)
            db.commit()

    # --------------------------------------------------------------- recall
    def recall(self, query: str, user_id: str) -> list[str]:
        fts = _fts_query(query)
        if not fts:
            return []
        k = int(self._cfg.get("k") or 5)
        now = time.time()
        try:
            with self._lock:
                db = self._db()
                rows = db.execute(
                    "SELECT m.id, m.content, bm25(memories_fts) AS rank, m.last_seen_at"
                    " FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid"
                    " WHERE memories_fts MATCH ? AND m.user_id = ?"
                    " ORDER BY rank LIMIT ?",
                    (fts, user_id, k * 3),
                ).fetchall()
                if not rows:
                    return []
                # bm25 càng âm càng khớp; cộng boost độ mới (half-life ~7 ngày)
                scored = []
                for mid, content, rank, last_seen in rows:
                    age_days = max(0.0, (now - float(last_seen or 0)) / 86400.0)
                    recency = 0.5 ** (age_days / 7.0)
                    scored.append((float(rank) - 2.0 * recency, mid, content))
                scored.sort(key=lambda t: t[0])
                top = scored[:k]
                # reinforce: ký ức được dùng thì tươi lại, prune sau cùng
                ids = [t[1] for t in top]
                qs = ",".join("?" * len(ids))
                db.execute(
                    f"UPDATE memories SET uses = uses + 1, last_seen_at = ? WHERE id IN ({qs})",
                    [now, *ids],
                )
                db.commit()
                return [t[2] for t in top]
        except Exception as exc:
            logger.warning({"event": "memory_recall_fail", "error": str(exc)[:200]})
            return []

    # ------------------------------------------------------------ chat hook
    def prepare(self, body: dict[str, Any]) -> _MemoryCapture | None:
        """Recall + inject ký ức vào body['messages']. Trả capture-context để
        lưu lượt chat sau khi có response; None nếu memory không áp dụng."""
        if not self.is_enabled:
            return None
        if bool(body.get("_is_ha_request")):
            return None
        model = str(body.get("model") or "").strip()
        if model in IMAGE_MODELS:
            return None
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return None
        if _messages_have_images(messages):
            return None
        user_text = _last_user_text(messages)
        if len(user_text) < _MIN_QUERY_CHARS:
            return None
        try:
            from services.ha_client import is_ha_query
            if is_ha_query(messages):
                return None
        except Exception:
            pass

        user_id = str(body.get("user") or self._cfg.get("user_id") or "chatgpt2api").strip()

        matches = self.recall(user_text, user_id)
        if matches:
            lines: list[str] = []
            total = 0
            for content in matches:
                line = "- " + content.strip().replace("\n", " ")[:600]
                if total + len(line) > _INJECT_TOTAL_MAX:
                    break
                lines.append(line)
                total += len(line)
            if lines:
                messages.append({"role": "system", "content": _INJECT_HEADER + "\n" + "\n".join(lines)})
                logger.info({"event": "memory_injected", "count": len(lines), "user_id": user_id})

        return _MemoryCapture(self, user_id, user_text, model)


# Singleton
memory_service = MemoryService()
