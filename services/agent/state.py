"""Agent state — persona, memory, user profiles, approval allowlist.

The "who am I / what can I do / what am I allowed / what do I remember" state
that shapes every conversation (mirrors OpenClaw/Hermes SOUL.md + MEMORY.md +
USER.md + command allowlist). Everything persists under ``DATA_DIR/agent`` so it
survives restarts and image rebuilds (the dir is on the bind mount).

Files:
    agent/soul.md            — persona + capability list (seeded from package)
    agent/MEMORY.md          — durable family facts
    agent/users/<uid>.md     — per-user profile
    agent/approvals.json     — {user_id: {capability: "always"}} remembered grants

Pending approvals (a change action proposed but not yet confirmed) are kept
in-memory per user — they are ephemeral by nature (the next message resolves
them), so they are NOT persisted.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR

logger = logging.getLogger(__name__)

_AGENT_DIR = Path(DATA_DIR) / "agent"
_USERS_DIR = _AGENT_DIR / "users"
_SOUL_FILE = _AGENT_DIR / "soul.md"
_MEMORY_FILE = _AGENT_DIR / "MEMORY.md"
_ENVIRONMENT_FILE = _AGENT_DIR / "ENVIRONMENT.md"
_APPROVALS_FILE = _AGENT_DIR / "approvals.json"

# Package-shipped default persona used to seed soul.md on first run.
_DEFAULT_SOUL = Path(__file__).with_name("soul.md")

_lock = threading.RLock()

# user_id -> {"capability": str, "args": dict, "summary": str, "ts": float}
# A change action the model proposed; resolved when the user confirms/denies.
_pending: dict[str, dict[str, Any]] = {}


def _ensure_dirs() -> None:
    try:
        _AGENT_DIR.mkdir(parents=True, exist_ok=True)
        _USERS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # never let a state hiccup break the agent
        logger.warning("agent.state: mkdir failed: %s", exc)


# ── Persona ────────────────────────────────────────────────────────────────

def load_soul() -> str:
    """Return the persona text, seeding soul.md from the package on first use."""
    _ensure_dirs()
    try:
        if _SOUL_FILE.exists():
            return _SOUL_FILE.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("agent.state: read soul failed: %s", exc)
    # Seed from the packaged default.
    try:
        text = _DEFAULT_SOUL.read_text(encoding="utf-8")
        _SOUL_FILE.write_text(text, encoding="utf-8")
        return text
    except Exception as exc:
        logger.warning("agent.state: seed soul failed: %s", exc)
        return "Em là Tiểu Vy, trợ lý gia đình. Trả lời tiếng Việt, ngắn gọn, ấm áp."


# ── Environment map (servers/containers/services — read-only for the agent) ──

def load_environment(limit_chars: int = 2500) -> str:
    """Return the environment map (ENVIRONMENT.md). The agent only reads it;
    the owner (or a maintenance session) edits the file on the bind mount."""
    try:
        if _ENVIRONMENT_FILE.exists():
            return _ENVIRONMENT_FILE.read_text(encoding="utf-8")[:limit_chars]
    except Exception as exc:
        logger.warning("agent.state: read environment failed: %s", exc)
    return ""


# ── Memory (durable family facts) ────────────────────────────────────────────

def load_memory(limit_chars: int = 4000) -> str:
    """Return recent durable memory (tail of MEMORY.md)."""
    try:
        if _MEMORY_FILE.exists():
            text = _MEMORY_FILE.read_text(encoding="utf-8")
            return text[-limit_chars:]
    except Exception as exc:
        logger.warning("agent.state: read memory failed: %s", exc)
    return ""


def append_memory(fact: str, who: str = "") -> None:
    """Append a durable fact (a change action — call only after approval)."""
    fact = (fact or "").strip()
    if not fact:
        return
    _ensure_dirs()
    stamp = time.strftime("%Y-%m-%d %H:%M")
    line = f"- [{stamp}]{f' ({who})' if who else ''} {fact}\n"
    with _lock:
        try:
            with _MEMORY_FILE.open("a", encoding="utf-8") as f:
                f.write(line)
        except Exception as exc:
            logger.warning("agent.state: append memory failed: %s", exc)


# ── Per-user profile ─────────────────────────────────────────────────────────

def load_user_profile(user_id: str) -> str:
    try:
        p = _USERS_DIR / f"{_safe(user_id)}.md"
        if p.exists():
            return p.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("agent.state: read user %s failed: %s", user_id, exc)
    return ""


def _safe(name: str) -> str:
    return "".join(c for c in str(name) if c.isalnum() or c in ("-", "_")) or "unknown"


# ── Approval allowlist (remembered "always allow") ───────────────────────────

def _load_approvals() -> dict[str, dict[str, str]]:
    try:
        if _APPROVALS_FILE.exists():
            data = json.loads(_APPROVALS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.warning("agent.state: read approvals failed: %s", exc)
    return {}


def is_approved(user_id: str, capability: str) -> bool:
    """True when the user has granted "always" for this capability."""
    with _lock:
        return _load_approvals().get(str(user_id), {}).get(capability) == "always"


def grant_always(user_id: str, capability: str) -> None:
    """Persist an "always allow" grant for (user, capability)."""
    _ensure_dirs()
    with _lock:
        data = _load_approvals()
        data.setdefault(str(user_id), {})[capability] = "always"
        try:
            _APPROVALS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
        except Exception as exc:
            logger.warning("agent.state: write approvals failed: %s", exc)


def revoke(user_id: str, capability: str) -> None:
    with _lock:
        data = _load_approvals()
        if str(user_id) in data:
            data[str(user_id)].pop(capability, None)
            try:
                _APPROVALS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
            except Exception:
                pass


# ── Pending approval (ephemeral) ─────────────────────────────────────────────

def set_pending(user_id: str, capability: str, args: dict, summary: str) -> None:
    with _lock:
        _pending[str(user_id)] = {"capability": capability, "args": args,
                                  "summary": summary, "ts": time.time()}


def get_pending(user_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        p = _pending.get(str(user_id))
        # Expire stale proposals after 10 minutes.
        if p and time.time() - p.get("ts", 0) > 600:
            _pending.pop(str(user_id), None)
            return None
        return p


def clear_pending(user_id: str) -> None:
    with _lock:
        _pending.pop(str(user_id), None)
