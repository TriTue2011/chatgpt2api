"""Sổ danh bạ kênh (Telegram / Zalo Bot) — multi-bot, multi-admin.

Mục tiêu:
  - Lưu thread/user kể cả khi CHƯA cấu hình trong Settings (Chat IDs / lọc).
  - Đặt alias (tên dễ nhớ) + gắn bot nhận tin.
  - Báo admin CHỈ LẦN ĐẦU khi người lạ nhắn; sau khi known thì im.
  - Admin hỏi "ai vừa nhắn" / "danh bạ" → trả thông tin đầy đủ.
  - Nhắc / gửi tin sau: resolve alias → hỏi bot nào gửi.

Key contact: ``{platform}:{bot_id}:{chat_id}`` (cá nhân hoặc nhóm).
Member key (optional): ``{platform}:{bot_id}:{chat_id}:{user_id}`` trong nhóm.

Known (không báo nữa) khi:
  - admin đã lưu alias / mark known, hoặc
  - chat_id nằm trong bot.chat_ids, hoặc
  - có thread_filter cho bot+chat (đã cấp phép trong Settings).

Lưu: ``DATA_DIR/channel_contacts.json`` (sống qua restart).
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR, config

_lock = threading.RLock()
_PATH = Path(DATA_DIR) / "channel_contacts.json"
_data: dict[str, dict[str, Any]] = {}
_loaded = False


def _ensure() -> None:
    global _loaded, _data
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        try:
            if _PATH.is_file():
                raw = json.loads(_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    _data = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
        except Exception:
            _data = {}
        _loaded = True


def _save() -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_PATH)
    except Exception:
        pass


def contact_key(platform: str, bot_id: str, chat_id: str, user_id: str = "") -> str:
    """Primary key for DM/group thread. user_id only if you want member-level."""
    p = str(platform or "").strip()
    b = str(bot_id or "").strip()
    c = str(chat_id or "").strip()
    u = str(user_id or "").strip()
    if u and u != c:
        return f"{p}:{b}:{c}:{u}"
    return f"{p}:{b}:{c}"


def bot_label(platform: str, bot_id: str) -> str:
    """Human label for a bot: config label → getMe name → bot_id."""
    bid = str(bot_id or "").strip()
    plat = str(platform or "").strip()
    if not bid:
        return "?"
    # Per-bot label in bots list
    bots_key = "telegram_bots" if plat == "tg" else "zalo_bots" if plat == "zalo" else ""
    if bots_key:
        try:
            for b in (config.get().get(bots_key) or []):
                if not isinstance(b, dict):
                    continue
                tok = str(b.get("token") or "").strip()
                id_ = tok.split(":", 1)[0].strip() if tok else ""
                if id_ == bid:
                    lab = str(b.get("label") or "").strip()
                    if lab:
                        return lab
                    break
        except Exception:
            pass
    # Runtime names
    try:
        if plat == "tg":
            from services.telegram_bot import get_bot_names
            n = (get_bot_names() or {}).get(bid)
            if n:
                return n
        elif plat == "zalo":
            from services.zalo_bot import get_bot_names
            n = (get_bot_names() or {}).get(bid)
            if n:
                return n
    except Exception:
        pass
    return bid


def is_configured(platform: str, bot_id: str, chat_id: str, user_id: str = "") -> bool:
    """True nếu đã cấp phép trong Settings (chat_ids hoặc thread filter)."""
    plat = str(platform or "").strip()
    bid = str(bot_id or "").strip()
    cid = str(chat_id or "").strip()
    if not (plat and bid and cid):
        return False
    # Chat IDs trên bot
    bots_key = "telegram_bots" if plat == "tg" else "zalo_bots" if plat == "zalo" else ""
    if bots_key:
        try:
            for b in (config.get().get(bots_key) or []):
                if not isinstance(b, dict):
                    continue
                tok = str(b.get("token") or "").strip()
                id_ = tok.split(":", 1)[0].strip() if tok else ""
                if id_ != bid:
                    continue
                cids = [str(x).strip() for x in (b.get("chat_ids") or [])]
                if cid in cids:
                    return True
        except Exception:
            pass
    # Thread filter exists for this bot+chat (any groups list means "known/managed")
    try:
        from services.agent import capabilities as caps
        if caps.allowed_groups_for_bot(plat, bid, cid) is not None:
            return True
        # Also member-level filter implies known group
        if user_id and caps.allowed_groups_for_member(plat, bid, cid, user_id) is not None:
            # only if parent filter exists
            if caps.allowed_groups_for_bot(plat, bid, cid) is not None:
                return True
    except Exception:
        pass
    return False


def get(key: str) -> Optional[dict[str, Any]]:
    _ensure()
    with _lock:
        c = _data.get(key)
        return dict(c) if c else None


def upsert(
    platform: str,
    bot_id: str,
    chat_id: str,
    *,
    user_id: str = "",
    display_name: str = "",
    chat_name: str = "",
    is_group: bool = False,
    text: str = "",
    member_level: bool = False,
) -> dict[str, Any]:
    """Create/update contact from inbound message. Returns contact dict.

    display_name = tên người gửi (nền tảng).
    chat_name    = tên nhóm/chat (title) khi là nhóm.
    """
    _ensure()
    uid = str(user_id or "").strip() if member_level else ""
    key = contact_key(platform, bot_id, chat_id, uid if member_level else "")
    now = int(time.time())
    with _lock:
        prev = _data.get(key) or {}
        known = bool(prev.get("known")) or is_configured(platform, bot_id, chat_id, user_id)
        rec = {
            **prev,
            "key": key,
            "platform": str(platform or "").strip(),
            "bot_id": str(bot_id or "").strip(),
            "bot_label": bot_label(platform, bot_id),
            "chat_id": str(chat_id or "").strip(),
            "user_id": str(user_id or "").strip(),
            "kind": "group" if is_group else "user",
            "display_name": (display_name or prev.get("display_name") or "").strip(),
            "chat_name": (chat_name or prev.get("chat_name") or "").strip(),
            "alias": str(prev.get("alias") or "").strip(),
            "known": known,
            "notified": bool(prev.get("notified")),
            "first_seen": int(prev.get("first_seen") or now),
            "last_seen": now,
            "last_text": (text or prev.get("last_text") or "")[:200],
            "msg_count": int(prev.get("msg_count") or 0) + 1,
        }
        # Re-check known after config may have changed
        if not rec["known"] and is_configured(platform, bot_id, chat_id, user_id):
            rec["known"] = True
        _data[key] = rec
        _save()
        return dict(rec)


def set_alias(key: str, alias: str, *, mark_known: bool = True) -> Optional[dict[str, Any]]:
    _ensure()
    alias = (alias or "").strip()
    with _lock:
        rec = _data.get(key)
        if not rec:
            return None
        rec = dict(rec)
        rec["alias"] = alias
        if mark_known:
            rec["known"] = True
        rec["notified"] = True  # stop future new-contact spam
        _data[key] = rec
        _save()
        return dict(rec)


def mark_known(key: str) -> Optional[dict[str, Any]]:
    _ensure()  # đọc alias SAU khi nạp file + trong lock — kẻo xoá alias sẵn có
    with _lock:
        alias = str((_data.get(key) or {}).get("alias") or "")
    return set_alias(key, alias, mark_known=True)


def mark_notified(key: str) -> None:
    _ensure()
    with _lock:
        rec = _data.get(key)
        if not rec:
            return
        rec = dict(rec)
        rec["notified"] = True
        _data[key] = rec
        _save()


def should_alert_new(
    platform: str,
    bot_id: str,
    chat_id: str,
    *,
    user_id: str = "",
    is_group: bool = False,
    tagged: bool = False,
    display_name: str = "",
    chat_name: str = "",
    text: str = "",
) -> tuple[bool, dict[str, Any]]:
    """Decide whether to push a NEW-CONTACT admin alert for this inbound message.

    Rules (multi-bot):
      - Only the bot that received the message calls this (caller responsibility).
      - If contact already known OR already notified → False.
      - Group + mention filter active + not tagged → False (silent; other bots same).
      - Group + no mention required → True for every bot that receives the event
        (platform may deliver to all bots; each bot alerts its own admin once).
      - Group + tagged this bot → True for this bot only (others won't get tagged).

    Returns (should_alert, contact_snapshot).
    """
    rec = upsert(
        platform, bot_id, chat_id,
        user_id=user_id, display_name=display_name, chat_name=chat_name,
        is_group=is_group, text=text, member_level=False,
    )
    # Also track member in groups for "who messaged"
    if is_group and user_id:
        upsert(
            platform, bot_id, chat_id,
            user_id=user_id, display_name=display_name, chat_name=chat_name,
            is_group=True, text=text, member_level=True,
        )

    if rec.get("known") or rec.get("notified"):
        return False, rec

    # Group tag gate for ALERTS (AI reply uses separate filter)
    if is_group:
        try:
            from services.agent import capabilities as caps
            req, _kw = caps.mention_required_for(platform, bot_id, chat_id)
            if req and not tagged:
                return False, rec
        except Exception:
            pass

    return True, rec


def format_alert(rec: dict[str, Any], *, served: bool, text: str = "") -> str:
    kind = "Nhóm" if rec.get("kind") == "group" else "Chat cá nhân"
    bl = rec.get("bot_label") or bot_label(rec.get("platform", ""), rec.get("bot_id", ""))
    status = (
        "chưa cấp phép (bot im / chặn nếu đã bật Chat IDs)"
        if not served
        else "chưa có trong danh bạ — bot vẫn có thể trả lời nếu chưa khoá Chat IDs"
    )
    lines = [
        f"🆕 {kind} mới → bot **{bl}** (`{rec.get('bot_id')}`)",
        f"• Chat ID: `{rec.get('chat_id')}`",
    ]
    if rec.get("kind") == "group" and rec.get("chat_name"):
        lines.append(f"• Tên nhóm: **{rec.get('chat_name')}**")
    if rec.get("user_id"):
        lines.append(f"• User ID người gửi: `{rec.get('user_id')}`")
    if rec.get("display_name"):
        lines.append(f"• Tên người (nền tảng): **{rec.get('display_name')}**")
    lines.append(f"• Trạng thái: {status}")
    snippet = (text or rec.get("last_text") or "")[:120]
    if snippet:
        lines.append(f"• Tin: {snippet}")
    lines.append(f"• Mã danh bạ: `{rec.get('key')}`")
    lines.append(
        "→ Trả lời admin: `có` để lưu (chọn tên người / tên nhóm / tự đặt) "
        "hoặc Settings → Lọc thread. Sau khi lưu sẽ không báo lại."
    )
    return "\n".join(lines)


def list_contacts(
    platform: str = "",
    bot_id: str = "",
    *,
    q: str = "",
    limit: int = 40,
) -> list[dict[str, Any]]:
    _ensure()
    plat = str(platform or "").strip()
    bid = str(bot_id or "").strip()
    query = (q or "").strip().lower()
    with _lock:
        rows = list(_data.values())
    out: list[dict[str, Any]] = []
    for r in rows:
        if plat and r.get("platform") != plat:
            continue
        if bid and r.get("bot_id") != bid:
            continue
        if query:
            blob = " ".join([
                str(r.get("alias") or ""),
                str(r.get("display_name") or ""),
                str(r.get("chat_id") or ""),
                str(r.get("user_id") or ""),
                str(r.get("bot_label") or ""),
                str(r.get("key") or ""),
            ]).lower()
            if query not in blob and not all(w in blob for w in query.split()):
                continue
        out.append(dict(r))
    out.sort(key=lambda x: -int(x.get("last_seen") or 0))
    return out[: max(1, min(limit, 100))]


def resolve_alias(name: str, *, platform: str = "", bot_id: str = "") -> list[dict[str, Any]]:
    """Find contacts by alias / display_name (case-insensitive, substring)."""
    name = (name or "").strip()
    if not name:
        return []
    return list_contacts(platform, bot_id, q=name, limit=10)


def describe(rec: dict[str, Any]) -> str:
    alias = rec.get("alias") or ""
    name = rec.get("display_name") or ""
    gname = rec.get("chat_name") or ""
    title = alias or name or gname or rec.get("chat_id")
    bl = rec.get("bot_label") or rec.get("bot_id")
    kind = "nhóm" if rec.get("kind") == "group" else "cá nhân"
    return (
        f"• **{title}** ({kind})\n"
        f"  bot={bl} (`{rec.get('bot_id')}`) chat=`{rec.get('chat_id')}`"
        + (f" nhóm=`{gname}`" if gname else "")
        + (f" user=`{rec.get('user_id')}`" if rec.get("user_id") else "")
        + (f" người=`{name}`" if name and name != title else "")
        + (f" alias=`{alias}`" if alias else "")
        + f"\n  last: {(rec.get('last_text') or '')[:80]}"
        + f"\n  key=`{rec.get('key')}` known={bool(rec.get('known'))}"
    )


def parse_admin_rename(text: str) -> Optional[tuple[str, str]]:
    """Parse 'đặt tên KEY = Alias' or 'đặt tên 123456 = Anh A'."""
    t = (text or "").strip()
    m = re.match(
        r"^(?:đặt\s*tên|dat\s*ten|rename|alias)\s+(.+?)\s*[=:]\s*(.+)$",
        t,
        re.I,
    )
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip()


def find_by_ref(ref: str) -> Optional[dict[str, Any]]:
    """Lookup by full key, chat_id, or alias."""
    ref = (ref or "").strip()
    if not ref:
        return None
    _ensure()
    with _lock:
        if ref in _data:
            return dict(_data[ref])
        # chat_id exact
        for r in _data.values():
            if str(r.get("chat_id")) == ref or str(r.get("key")) == ref:
                return dict(r)
        low = ref.lower()
        for r in _data.values():
            if str(r.get("alias") or "").lower() == low:
                return dict(r)
    return None


def _reset_for_tests(path: Path | None = None) -> None:
    global _PATH, _data, _loaded
    with _lock:
        if path is not None:
            _PATH = Path(path)
        _data = {}
        _loaded = False
