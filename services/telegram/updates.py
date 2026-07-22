"""Webhook / Update helpers for Telegram Bot API."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any, Callable

from services.telegram.constants import DEFAULT_ALLOWED_UPDATES


def webhook_secret_for(token: str, *, prefix: str = "t") -> str:
    """Stable secret_token from bot token (A-Za-z0-9 only after prefix).

    Used with setWebhook(secret_token=…) and verified against
    X-Telegram-Bot-Api-Secret-Token.
    """
    tok = (token or "").strip()
    if not tok:
        return ""
    digest = hashlib.sha256(tok.encode("utf-8")).hexdigest()[:40]
    return f"{prefix}{digest}"


def match_bot_by_secret(
    bots: list[dict],
    header_secret: str,
    *,
    secret_fn: Callable[[str], str] | None = None,
) -> dict | None:
    """Pick bot whose derived secret matches header. Single-bot: lenient fallback."""
    fn = secret_fn or webhook_secret_for
    enabled = [b for b in bots if b.get("enabled", True)]
    hdr = (header_secret or "").strip()
    for b in enabled:
        tok = str(b.get("token") or "").strip()
        if tok and fn(tok) == hdr:
            return b
    if len(enabled) == 1:
        return enabled[0]
    return None


# ── Update id de-dupe (webhook retries) ───────────────────────────────────────

class UpdateDedupe:
    """Remember recent update_ids per bot to ignore Telegram retries."""

    def __init__(self, max_size: int = 2000, ttl_sec: float = 3600.0) -> None:
        self.max_size = max_size
        self.ttl_sec = ttl_sec
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def _key(self, bot_id: str, update_id: int | str) -> str:
        return f"{bot_id}:{update_id}"

    def _purge(self, now: float) -> None:
        if len(self._seen) < self.max_size:
            # still drop expired
            expired = [k for k, t in self._seen.items() if now - t > self.ttl_sec]
            for k in expired:
                self._seen.pop(k, None)
            return
        # Drop oldest half
        items = sorted(self._seen.items(), key=lambda x: x[1])
        for k, _ in items[: len(items) // 2]:
            self._seen.pop(k, None)

    def is_duplicate(self, bot_id: str, update_id: int | str | None) -> bool:
        if update_id is None or update_id == "":
            return False
        key = self._key(str(bot_id or ""), update_id)
        now = time.time()
        with self._lock:
            self._purge(now)
            if key in self._seen:
                return True
            self._seen[key] = now
            return False


_default_dedupe = UpdateDedupe()


def is_duplicate_update(
    bot_id: str, update_id: int | str | None, *, store: UpdateDedupe | None = None
) -> bool:
    return (store or _default_dedupe).is_duplicate(bot_id, update_id)


# ── Update parsing ────────────────────────────────────────────────────────────

def update_kind(update: dict) -> str | None:
    """Return the single optional field name present on Update (message, …)."""
    if not isinstance(update, dict):
        return None
    for k in (
        "message", "edited_message", "channel_post", "edited_channel_post",
        "business_connection", "business_message", "edited_business_message",
        "deleted_business_messages", "guest_message",
        "message_reaction", "message_reaction_count",
        "inline_query", "chosen_inline_result", "callback_query",
        "shipping_query", "pre_checkout_query", "purchased_paid_media",
        "poll", "poll_answer",
        "my_chat_member", "chat_member", "chat_join_request",
        "chat_boost", "removed_chat_boost", "managed_bot", "subscription",
    ):
        if update.get(k) is not None:
            return k
    return None


def extract_message(update: dict) -> dict | None:
    """Message-like payload from common update types."""
    if not isinstance(update, dict):
        return None
    for k in (
        "message", "edited_message", "channel_post", "edited_channel_post",
        "business_message", "edited_business_message", "guest_message",
    ):
        m = update.get(k)
        if isinstance(m, dict):
            return m
    cq = update.get("callback_query")
    if isinstance(cq, dict) and isinstance(cq.get("message"), dict):
        return cq["message"]
    return None


def message_context(msg: dict) -> dict[str, Any]:
    """Normalize Message fields used by the AI gateway."""
    msg = msg or {}
    chat = msg.get("chat") or {}
    frm = msg.get("from") or {}
    chat_type = str(chat.get("type") or "")
    is_group = chat_type in {"group", "supergroup"}
    fn = str(frm.get("first_name") or "").strip()
    ln = str(frm.get("last_name") or "").strip()
    sender = (" ".join(x for x in (fn, ln) if x).strip()
              or str(frm.get("username") or "").strip())
    chat_name = str(chat.get("title") or "").strip()
    if not chat_name and not is_group:
        chat_name = str(chat.get("first_name") or chat.get("username") or "").strip()
    voice = msg.get("voice") or msg.get("audio") or {}
    voice_file_id = ""
    if isinstance(voice, dict):
        voice_file_id = str(voice.get("file_id") or "")
    return {
        "chat_id": str(chat.get("id") or ""),
        "chat_type": chat_type,
        "is_group": is_group,
        "chat_name": chat_name,
        "user_id": str(frm.get("id") or "").strip(),
        "sender": sender,
        "username": str(frm.get("username") or "").strip(),
        "language_code": str(frm.get("language_code") or "").strip(),
        "text": (msg.get("text") or "").strip(),
        "caption": (msg.get("caption") or "").strip(),
        "message_id": msg.get("message_id"),
        "message_thread_id": msg.get("message_thread_id"),
        "photo": msg.get("photo"),
        "document": msg.get("document"),
        "voice_file_id": voice_file_id,
        "sticker": msg.get("sticker"),
        "video": msg.get("video"),
        "animation": msg.get("animation"),
        "location": msg.get("location"),
        "contact": msg.get("contact"),
        "entities": msg.get("entities") or [],
        "caption_entities": msg.get("caption_entities") or [],
        "reply_to_message": msg.get("reply_to_message"),
        "date": msg.get("date"),
        "edit_date": msg.get("edit_date"),
        "guest_query_id": msg.get("guest_query_id"),
        "business_connection_id": msg.get("business_connection_id"),
    }


def detect_bot_mention(
    msg: dict,
    *,
    bot_username: str,
    bot_id: str,
) -> bool:
    """True if user @mentioned bot, text_mentioned, or replied to bot message."""
    msg = msg or {}
    buser = (bot_username or "").strip().lower().lstrip("@")
    bid = str(bot_id or "").strip()
    rtm = (msg.get("reply_to_message") or {}).get("from") or {}
    if rtm.get("is_bot") and (
        str(rtm.get("id") or "") == bid
        or str(rtm.get("username") or "").lower() == buser
    ):
        return True
    body = (msg.get("text") or msg.get("caption") or "")
    ents = list(msg.get("entities") or []) + list(msg.get("caption_entities") or [])
    for e in ents:
        et = e.get("type")
        if et == "mention" and buser:
            off = int(e.get("offset") or 0)
            ln = int(e.get("length") or 0)
            seg = body[off: off + ln]
            if seg.lower().lstrip("@") == buser:
                return True
        if et == "text_mention" and str((e.get("user") or {}).get("id") or "") == bid:
            return True
    return False


def default_webhook_payload(
    url: str,
    *,
    secret_token: str,
    allowed_updates: list[str] | None = None,
    drop_pending_updates: bool | None = None,
) -> dict[str, Any]:
    return {
        "url": url,
        "secret_token": secret_token,
        "allowed_updates": allowed_updates or list(DEFAULT_ALLOWED_UPDATES),
        "drop_pending_updates": drop_pending_updates,
    }
