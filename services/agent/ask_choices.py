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

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

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

# Pending choices ĐƯỢC LƯU RA SQLITE (không chỉ RAM). Vì sao: trước đây `_pending`
# chỉ nằm trong bộ nhớ tiến trình, nên MỖI LẦN app khởi động lại (deploy, crash,
# health-restart, Portainer update) là mất sạch — người dùng vừa được hỏi
# "chọn 1/2/3", trả "1" sau khi app restart thì bot "chưa rõ ý" (không còn nhớ
# đang hỏi gì). Đo thật 31/07: nhắc-lịch hỏi kênh → "1" → "chưa rõ ý" đúng vào
# lúc app vừa restart. Lưu ra đĩa (cùng chỗ sessions/reminders) thì câu hỏi số
# sống qua restart. RAM vẫn là cache nhanh; SQLite là nguồn bền.
_conn = None


def _db():
    global _conn
    if _conn is not None:
        return _conn
    try:
        import sqlite3
        from services.config import DATA_DIR
        p = Path(DATA_DIR) / "agent" / "ask_pending.sqlite"
        p.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(p), check_same_thread=False)
        c.execute("CREATE TABLE IF NOT EXISTS ask_pending ("
                  " user_id TEXT PRIMARY KEY, choices TEXT NOT NULL, ts REAL)")
        c.commit()
        _conn = c
    except Exception as exc:
        logger.warning("ask_choices: mở SQLite lỗi (chỉ dùng RAM): %s", exc)
        _conn = None
    return _conn


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
    now = time.time()
    with _lock:
        _pending[str(user_id)] = {"choices": list(choices), "ts": now}
    # Ghi ra đĩa để sống qua restart (best-effort — hỏng thì RAM vẫn chạy).
    try:
        import json
        c = _db()
        if c is not None:
            c.execute("INSERT OR REPLACE INTO ask_pending(user_id, choices, ts) "
                      "VALUES (?,?,?)",
                      (str(user_id), json.dumps(list(choices), ensure_ascii=False), now))
            c.commit()
    except Exception as exc:
        logger.warning("ask_choices: lưu pending lỗi: %s", exc)


def get_pending(user_id: str) -> Optional[list[dict[str, str]]]:
    uid = str(user_id)
    with _lock:
        p = _pending.get(uid)
    if p:
        if time.time() - float(p.get("ts") or 0) > _TTL:
            clear_pending(uid)
            return None
        return list(p.get("choices") or [])
    # RAM miss (vd app vừa restart) → đọc lại từ SQLite.
    try:
        import json
        c = _db()
        if c is None:
            return None
        row = c.execute("SELECT choices, ts FROM ask_pending WHERE user_id=?",
                        (uid,)).fetchone()
        if not row:
            return None
        if time.time() - float(row[1] or 0) > _TTL:
            clear_pending(uid)
            return None
        choices = json.loads(row[0] or "[]")
        with _lock:                       # nạp lại vào cache RAM
            _pending[uid] = {"choices": choices, "ts": row[1]}
        return list(choices)
    except Exception as exc:
        logger.warning("ask_choices: đọc pending lỗi: %s", exc)
        return None


def clear_pending(user_id: str) -> None:
    uid = str(user_id)
    with _lock:
        _pending.pop(uid, None)
    try:
        c = _db()
        if c is not None:
            c.execute("DELETE FROM ask_pending WHERE user_id=?", (uid,))
            c.commit()
    except Exception:
        pass


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
