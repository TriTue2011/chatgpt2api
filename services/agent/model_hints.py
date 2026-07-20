"""Model hint routing — pick the right LLM tier per workload.

Hints (OpenHuman-style burst / reason / code)::

    chat     — default conversational agent (telegram_ai_model)
    burst    — cheap/fast: super_context, compaction, phrasing, digest polish
    reason   — deeper multi-step agent loop (default = chat)
    code     — code write/review (agent_branches.code)
    vision   — image analysis (agent_branches.vision)

Config (``agent_model_hints``)::

    enabled: bool (default True)
    chat: str    — override main chat model
    burst: str   — e.g. gma/flash or cx/auto
    reason: str  — e.g. claude/sonnet
    code: str    — optional; falls back to agent_branches.code
    vision: str

Empty string → fall through to defaults below.
"""

from __future__ import annotations

from typing import Any

from services.config import config
from services.agent.branches import branch_model

HINTS = ("chat", "burst", "reason", "code", "vision")

_DEFAULTS = {
    "chat": "",      # → telegram_ai_model
    "burst": "",     # → chat (cheap path uses same unless set)
    "reason": "",    # → chat
    "code": "",      # → branch_model("code")
    "vision": "",    # → branch_model("vision")
}


def _cfg() -> dict[str, Any]:
    raw = config.get().get("agent_model_hints")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def main_chat_model() -> str:
    c = _cfg()
    override = str(c.get("chat") or "").strip()
    if override:
        return override
    return str(config.get().get("telegram_ai_model") or "").strip() or "cx/auto"


def resolve(hint: str, *, channel: str = "") -> str:
    """Resolve a workload hint to a concrete model id."""
    h = (hint or "chat").strip().lower()
    if h not in HINTS:
        h = "chat"
    if not is_enabled():
        if h == "code":
            return branch_model("code", channel) or main_chat_model()
        if h == "vision":
            return branch_model("vision", channel) or main_chat_model()
        return main_chat_model()

    c = _cfg()
    explicit = str(c.get(h) or "").strip()
    if explicit:
        return explicit

    if h == "code":
        return branch_model("code", channel) or main_chat_model()
    if h == "vision":
        return branch_model("vision", channel) or main_chat_model()
    if h in ("burst", "reason", "chat"):
        # burst/reason fall back to chat unless configured
        chat = str(c.get("chat") or "").strip()
        return chat or main_chat_model()
    return main_chat_model()


def describe() -> dict[str, str]:
    """Resolved map for UI / debug."""
    return {h: resolve(h) for h in HINTS}
