"""Subconscious-lite heartbeat — background skip / act / escalate loop.

Periodic tick (default 5 min) evaluates system + user tasks:

- **skip** — nothing to do
- **act** — run a deterministic handler (e.g. write wiki daily digest)
- **escalate** — notify configured admin user_ids (or log only)

User tasks live in ``DATA_DIR/agent/HEARTBEAT.md`` (one per line)::

    # comments ignored
    [read] Kiểm tra thiết bị offline
    [write] Gửi tóm tắt nếu có tin lạ
    wiki_daily_digest          # bare id = system task name override

Config (``agent_heartbeat``)::

    enabled: bool (default True)
    tick_seconds: int (default 300, min 60)
    admin_user_ids: list[str]  — orchestrator user_ids to notify on escalate
    max_acts_per_tick: int (default 3)
    activity_log: bool (default True)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from services.config import DATA_DIR, config

logger = logging.getLogger(__name__)

_AGENT_DIR = Path(DATA_DIR) / "agent"
_HEARTBEAT_MD = _AGENT_DIR / "HEARTBEAT.md"
_STATE_FILE = _AGENT_DIR / "heartbeat_state.json"
_ACTIVITY_FILE = _AGENT_DIR / "heartbeat_activity.jsonl"
_DEFAULT_HEARTBEAT = """# Heartbeat — một dòng / task (Phase B)
# [read] = chỉ quan sát; [write] = có thể gửi tin / side-effect khi escalate
# Hệ thống luôn chạy: wiki_daily_digest

[read] Rà pending approvals nếu có
"""

_lock = threading.RLock()
_started = False
_stop = threading.Event()
# last run bookkeeping: task_id -> ts
_state: dict[str, Any] = {}


def _cfg() -> dict[str, Any]:
    raw = config.get().get("agent_heartbeat")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def tick_seconds() -> float:
    try:
        return max(60.0, float(_cfg().get("tick_seconds") or 300))
    except (TypeError, ValueError):
        return 300.0


def max_acts_per_tick() -> int:
    try:
        return max(1, int(_cfg().get("max_acts_per_tick") or 3))
    except (TypeError, ValueError):
        return 3


def admin_user_ids() -> list[str]:
    raw = _cfg().get("admin_user_ids")
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def activity_log_enabled() -> bool:
    return bool(_cfg().get("activity_log", True))


def _load_state() -> dict[str, Any]:
    global _state
    try:
        if _STATE_FILE.exists():
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _state = data
                return _state
    except Exception as exc:
        logger.warning("heartbeat: load state failed: %s", exc)
    _state = {}
    return _state


def _save_state() -> None:
    try:
        _AGENT_DIR.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps(_state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("heartbeat: save state failed: %s", exc)


def _log_activity(kind: str, task_id: str, detail: str = "") -> None:
    if not activity_log_enabled():
        return
    row = {
        "ts": time.time(),
        "kind": kind,
        "task": task_id,
        "detail": (detail or "")[:500],
    }
    try:
        _AGENT_DIR.mkdir(parents=True, exist_ok=True)
        with _ACTIVITY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _ensure_heartbeat_md() -> None:
    try:
        _AGENT_DIR.mkdir(parents=True, exist_ok=True)
        if not _HEARTBEAT_MD.exists():
            _HEARTBEAT_MD.write_text(_DEFAULT_HEARTBEAT, encoding="utf-8")
    except OSError as exc:
        logger.warning("heartbeat: seed HEARTBEAT.md failed: %s", exc)


def _parse_tasks() -> list[dict[str, Any]]:
    """Return task dicts: id, intent (read|write), text, system?."""
    tasks: list[dict[str, Any]] = []
    # Always include system digest task first
    tasks.append({
        "id": "wiki_daily_digest",
        "intent": "read",
        "text": "Viết wiki daily digest nếu đến giờ và chưa có file hôm nay",
        "system": True,
    })
    tasks.append({
        "id": "open_goals_nudge",
        "intent": "read",
        "text": "Nhắc admin nếu có goal doing quá 24h (khi có admin_user_ids)",
        "system": True,
    })

    _ensure_heartbeat_md()
    try:
        text = _HEARTBEAT_MD.read_text(encoding="utf-8")
    except OSError:
        return tasks

    seen = {t["id"] for t in tasks}
    for i, line in enumerate(text.splitlines()):
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        intent = "read"
        body = raw
        if raw.lower().startswith("[write]"):
            intent = "write"
            body = raw[7:].strip()
        elif raw.lower().startswith("[read]"):
            intent = "read"
            body = raw[6:].strip()
        if not body:
            continue
        # bare known system id
        tid = body.split()[0].lower() if body.split()[0].isidentifier() and " " not in body else f"user_{i}"
        if body in ("wiki_daily_digest", "open_goals_nudge"):
            continue  # already seeded
        if tid in seen and body in seen:
            continue
        uid = f"user_{i}_{abs(hash(body)) % 10000}"
        if body.isidentifier():
            uid = body
        if uid in seen:
            continue
        seen.add(uid)
        tasks.append({
            "id": uid,
            "intent": intent,
            "text": body,
            "system": False,
        })
    return tasks


# ── Task handlers ────────────────────────────────────────────────────────────


def _eval_wiki_digest() -> tuple[str, str]:
    """Return (decision, detail) for wiki_daily_digest."""
    try:
        from services.agent import wiki as w
        if not w.digest_due_now():
            return "skip", "chưa đến giờ hoặc đã có digest"
        out = w.build_daily_digest(force=False)
        if not out.get("ok"):
            return "skip", str(out.get("text") or "digest fail")
        if out.get("skipped"):
            return "skip", f"đã có digest {out.get('day')}"
        detail = f"digest {out.get('day')}: {out.get('note_count', 0)} notes"
        # escalate = notify admins of digest summary
        admins = admin_user_ids()
        if admins and out.get("text"):
            snippet = str(out["text"])[:800]
            for uid in admins:
                _notify_user(uid, f"📰 Wiki digest hôm nay:\n{snippet}")
            return "act", detail + f" · gửi {len(admins)} admin"
        return "act", detail
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_open_goals() -> tuple[str, str]:
    admins = admin_user_ids()
    if not admins:
        return "skip", "không cấu hình admin_user_ids"
    try:
        from services.agent import goals as g
        if not g.is_enabled():
            return "skip", "goals tắt"
        now = time.time()
        stale: list[str] = []
        for uid in admins:
            for row in g.list_for(uid, status="doing", limit=20):
                age = now - float(row.get("updated_at") or 0)
                if age >= 86400:
                    stale.append(f"{uid}: {row.get('title')} (`{row.get('id')}`)")
        if not stale:
            return "skip", "không có goal doing >24h"
        msg = "🎯 Goal đang `doing` quá 24h:\n" + "\n".join(f"• {s}" for s in stale[:8])
        for uid in admins:
            _notify_user(uid, msg)
        return "escalate", f"{len(stale)} goal stale"
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_user_task(task: dict[str, Any]) -> tuple[str, str]:
    """User HEARTBEAT lines: escalate write intents to admin; skip read unless interval."""
    tid = task["id"]
    st = _load_state()
    last = float((st.get("tasks") or {}).get(tid) or 0)
    # User tasks at most once per 6 hours
    if last and time.time() - last < 6 * 3600:
        return "skip", "chưa đủ 6h từ lần trước"
    intent = task.get("intent") or "read"
    text = task.get("text") or tid
    admins = admin_user_ids()
    if not admins:
        return "skip", "không có admin để escalate"
    if intent == "write":
        for uid in admins:
            _notify_user(
                uid,
                f"💓 Heartbeat gợi ý việc (write):\n{text}\n"
                f"Anh/chị muốn em làm thì nhắn lại (hoặc đặt schedule).",
            )
        return "escalate", text[:120]
    # read: gentle nudge less often
    for uid in admins:
        _notify_user(
            uid,
            f"💓 Heartbeat nhắc kiểm tra (read):\n{text}",
        )
    return "escalate", text[:120]


def _notify_user(user_id: str, text: str) -> None:
    """Best-effort send via reminders channel mapping."""
    try:
        from services.agent import reminders as rem
        channel, chat_id = rem.channel_of(user_id)
        rem._send(channel, chat_id, text, {})
    except Exception as exc:
        logger.info("heartbeat: notify %s failed: %s", user_id, exc)


_HANDLERS: dict[str, Callable[[], tuple[str, str]]] = {
    "wiki_daily_digest": _eval_wiki_digest,
    "open_goals_nudge": _eval_open_goals,
}


def evaluate_task(task: dict[str, Any]) -> dict[str, Any]:
    tid = str(task.get("id") or "")
    if tid in _HANDLERS:
        decision, detail = _HANDLERS[tid]()
    elif task.get("system"):
        decision, detail = "skip", "no handler"
    else:
        decision, detail = _eval_user_task(task)
    return {
        "id": tid,
        "decision": decision,
        "detail": detail,
        "intent": task.get("intent"),
        "text": task.get("text"),
    }


def tick_once() -> list[dict[str, Any]]:
    """Run one heartbeat evaluation. Returns list of outcomes."""
    if not is_enabled():
        return []
    _load_state()
    tasks = _parse_tasks()
    results: list[dict[str, Any]] = []
    acts = 0
    for task in tasks:
        try:
            out = evaluate_task(task)
        except Exception as exc:
            out = {
                "id": task.get("id"),
                "decision": "skip",
                "detail": f"error: {exc}",
            }
        results.append(out)
        dec = out.get("decision") or "skip"
        _log_activity(dec, str(out.get("id")), str(out.get("detail") or ""))
        if dec in ("act", "escalate"):
            acts += 1
            # mark last run
            _state.setdefault("tasks", {})[str(out.get("id"))] = time.time()
            if acts >= max_acts_per_tick():
                # still mark remaining as skipped this tick
                break
    _state["last_tick"] = time.time()
    _save_state()
    logger.info(
        "heartbeat: tick done acts=%s results=%s",
        acts,
        [(r.get("id"), r.get("decision")) for r in results],
    )
    return results


def _loop() -> None:
    # slight delay so app finishes startup
    _stop.wait(15)
    while not _stop.is_set():
        try:
            tick_once()
        except Exception as exc:
            logger.warning("heartbeat: tick error: %s", exc)
        _stop.wait(tick_seconds())


def start() -> None:
    global _started
    if _started or not is_enabled():
        return
    _started = True
    _stop.clear()
    _ensure_heartbeat_md()
    _load_state()
    t = threading.Thread(target=_loop, name="agent-heartbeat", daemon=True)
    t.start()
    logger.info("heartbeat: started (tick=%ss)", tick_seconds())


def stop() -> None:
    global _started
    _stop.set()
    _started = False


def _reset_for_tests(
    agent_dir: Path | None = None,
    *,
    clear_state: bool = True,
) -> None:
    global _AGENT_DIR, _HEARTBEAT_MD, _STATE_FILE, _ACTIVITY_FILE, _state, _started
    stop()
    with _lock:
        if agent_dir is not None:
            _AGENT_DIR = Path(agent_dir)
            _HEARTBEAT_MD = _AGENT_DIR / "HEARTBEAT.md"
            _STATE_FILE = _AGENT_DIR / "heartbeat_state.json"
            _ACTIVITY_FILE = _AGENT_DIR / "heartbeat_activity.jsonl"
        if clear_state:
            _state = {}
            try:
                if _STATE_FILE.exists():
                    _STATE_FILE.unlink()
            except OSError:
                pass
    _started = False
