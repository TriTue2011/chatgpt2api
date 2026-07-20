"""Ask-with-choices — structured follow-up questions for multi-channel bots.

The model may end a reply with a control block (stripped before the user
sees raw markup)::

    <<<ASK>>>
    Flow miễn phí
    ChatGPT (đẹp hơn)
    Gemini
    <<<END>>>

Or with optional send-values::

    <<<ASK>>>
    Flow | flow
    ChatGPT | chatgpt
    <<<END>>>

Orchestrator returns ``{"text": clean, "choices": [{"label","send"}, ...]}``.

Channel adapters:
  - Telegram → InlineKeyboard (callback ``ask:<n>``) when possible; also
    append numbered list as fallback text.
  - Zalo / Zalo Personal → numbered list in the message body.
  - When the user replies with ``1`` / ``2`` / ``a``, ``resolve_reply`` maps
    that to the chosen ``send`` string for the next orchestrate turn.

Pending choices are kept in-memory per user_id (10 min TTL).
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Optional

_ASK_RE = re.compile(
    r"<<<ASK>>>\s*(.*?)\s*<<<END>>>",
    re.IGNORECASE | re.DOTALL,
)
# Also accept JAVIS_ASK style fenced JSON array of strings (best-effort)
_JAVIS_RE = re.compile(
    r"JAVIS_ASK\s*[\[:]?\s*(\[[^\]]+\])",
    re.IGNORECASE | re.DOTALL,
)

_lock = threading.RLock()
# user_id -> {"choices": [...], "ts": float}
_pending: dict[str, dict[str, Any]] = {}
_TTL = 600.0
_LABEL_MAX = 40


def extract(text: str) -> tuple[str, list[dict[str, str]]]:
    """Strip ask blocks from text; return (clean_text, choices).

    Each choice: ``{"label": str, "send": str}`` (send is what gets injected
    as the next user message when picked).
    """
    raw = text or ""
    choices: list[dict[str, str]] = []

    def _parse_lines(block: str) -> None:
        for line in (block or "").splitlines():
            line = line.strip()
            if not line:
                continue
            # strip leading list markers / numbers
            line = re.sub(r"^[-*•]\s+", "", line)
            line = re.sub(r"^\d+[\.\)\-:\s]+", "", line).strip()
            if not line:
                continue
            if "|" in line:
                label, send = line.split("|", 1)
                label, send = label.strip(), send.strip()
            else:
                label = send = line
            if not label:
                continue
            if len(label) > _LABEL_MAX:
                label = label[: _LABEL_MAX - 1] + "…"
            # send side also capped so user never "sends" text they didn't see
            if len(send) > 200:
                send = send[:200]
            choices.append({"label": label, "send": send or label})

    def _sub_ask(m: re.Match) -> str:
        _parse_lines(m.group(1))
        return ""

    clean = _ASK_RE.sub(_sub_ask, raw)

    if not choices:
        m = _JAVIS_RE.search(raw)
        if m:
            try:
                import json
                arr = json.loads(m.group(1))
                if isinstance(arr, list):
                    for item in arr:
                        if isinstance(item, str) and item.strip():
                            lab = item.strip()
                            if len(lab) > _LABEL_MAX:
                                lab = lab[: _LABEL_MAX - 1] + "…"
                            choices.append({"label": lab, "send": item.strip()[:200]})
                        elif isinstance(item, dict):
                            lab = str(item.get("label") or item.get("text") or "").strip()
                            send = str(item.get("send") or item.get("value") or lab).strip()
                            if lab:
                                if len(lab) > _LABEL_MAX:
                                    lab = lab[: _LABEL_MAX - 1] + "…"
                                choices.append({"label": lab, "send": (send or lab)[:200]})
                clean = _JAVIS_RE.sub("", clean)
            except Exception:
                pass

    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    # max 8 choices (Telegram row comfort)
    return clean, choices[:8]


def set_pending(user_id: str, choices: list[dict[str, str]]) -> None:
    if not user_id or not choices:
        return
    with _lock:
        _pending[str(user_id)] = {"choices": list(choices), "ts": time.time()}


def get_pending(user_id: str) -> Optional[list[dict[str, str]]]:
    with _lock:
        p = _pending.get(str(user_id))
        if not p:
            return None
        if time.time() - float(p.get("ts") or 0) > _TTL:
            _pending.pop(str(user_id), None)
            return None
        return list(p.get("choices") or [])


def clear_pending(user_id: str) -> None:
    with _lock:
        _pending.pop(str(user_id), None)


def resolve_reply(user_id: str, user_text: str) -> Optional[str]:
    """If user_text picks a pending choice (1/2/a or exact label), return send text."""
    t = (user_text or "").strip()
    if not t:
        return None
    choices = get_pending(user_id)
    if not choices:
        return None

    # pure number 1..n
    if re.fullmatch(r"\d{1,2}", t):
        idx = int(t) - 1
        if 0 <= idx < len(choices):
            clear_pending(user_id)
            return choices[idx]["send"]

    # a/b/c
    if re.fullmatch(r"[a-zA-Z]", t):
        idx = ord(t.lower()) - ord("a")
        if 0 <= idx < len(choices):
            clear_pending(user_id)
            return choices[idx]["send"]

    # exact label or send match (case-insensitive)
    low = t.lower()
    for c in choices:
        if low == c["label"].lower() or low == c["send"].lower():
            clear_pending(user_id)
            return c["send"]

    # not a pick — leave pending (user asked something else)
    return None


def format_numbered(text: str, choices: list[dict[str, str]]) -> str:
    """Append a numbered list for channels without buttons (Zalo, plain text)."""
    if not choices:
        return text
    lines = [text.rstrip(), "", "Chọn bằng cách trả lời số:"]
    for i, c in enumerate(choices, 1):
        lines.append(f"{i}. {c['label']}")
    return "\n".join(lines).strip()


def telegram_inline_keyboard(choices: list[dict[str, str]]) -> dict[str, Any]:
    """Build Telegram InlineKeyboardMarkup (callback_data = ask:0, ask:1, …)."""
    rows: list[list[dict[str, str]]] = []
    row: list[dict[str, str]] = []
    for i, c in enumerate(choices):
        row.append({
            "text": c["label"][:64],
            "callback_data": f"ask:{i}",
        })
        # 2 buttons per row
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return {"inline_keyboard": rows}


def apply_to_result(result: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Mutate orchestrator result: strip ask block, attach choices, set pending."""
    if not isinstance(result, dict):
        return result
    text = str(result.get("text") or "")
    if result.get("silent") or not text:
        return result
    clean, choices = extract(text)
    result["text"] = clean
    if choices:
        result["choices"] = choices
        set_pending(user_id, choices)
    return result


def _reset_for_tests() -> None:
    with _lock:
        _pending.clear()
