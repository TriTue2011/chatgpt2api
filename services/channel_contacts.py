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
    # Zalo Cá Nhân: SĐT / displayName (không hiện bare ownId nếu có phone)
    if plat in {"zalop", "zalo_personal"}:
        try:
            from services.zalo_personal import get_accounts
            for a in (get_accounts().get("accounts") or []):
                if str(a.get("ownId") or "").strip() != bid:
                    continue
                phone = str(a.get("phoneNumber") or "").strip()
                name = str(a.get("displayName") or "").strip()
                # Bỏ "(ownId)" trong displayName zca
                if name:
                    name = re.sub(r"\s*\(\d{8,}\)\s*$", "", name).strip()
                if phone and name and name != phone and phone not in name:
                    return f"{name} · {phone}"
                return phone or name or bid
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
    """Tin 💬 chat/nhóm/user mới — luôn cố gắng đầy đủ tên bot/SĐT/nhóm/user."""
    is_group = rec.get("kind") == "group"
    kind = "Nhóm" if is_group else "Chat cá nhân"
    plat = str(rec.get("platform") or "").strip()
    bid = str(rec.get("bot_id") or "").strip()
    bl = str(rec.get("bot_label") or "").strip() or bot_label(plat, bid)
    if bl == bid:
        bl = bot_label(plat, bid) or bid
    # Zalo CN: bổ sung SĐT nếu label chưa có
    phone = str(rec.get("bot_phone") or rec.get("phone") or "").strip()
    if plat in {"zalop", "zalo_personal"} and not phone and bid:
        try:
            from services.zalo_personal import get_accounts
            for a in (get_accounts().get("accounts") or []):
                if str(a.get("ownId") or "").strip() == bid:
                    phone = str(a.get("phoneNumber") or "").strip()
                    if not bl or bl == bid:
                        dn = str(a.get("displayName") or "").strip()
                        dn = re.sub(r"\s*\(\d{8,}\)\s*$", "", dn).strip()
                        bl = phone or dn or bl
                    break
        except Exception:
            pass
    status = (
        "chưa cấp phép (bot im / chặn nếu đã bật Chat IDs)"
        if not served
        else "chưa có trong danh bạ — bot vẫn có thể trả lời nếu chưa khoá Chat IDs"
    )
    chat_name = str(rec.get("chat_name") or "").strip()
    user_name = str(rec.get("display_name") or "").strip()
    user_id = str(rec.get("user_id") or "").strip()
    chat_id = str(rec.get("chat_id") or "").strip()

    bot_line = f"🆕 {kind} mới → bot **{bl}**"
    if phone and phone not in bot_line:
        bot_line += f" · SĐT `{phone}`"
    if bid and bid != bl and bid != phone:
        bot_line += f" · id `{bid}`" if plat not in {"zalop", "zalo_personal"} else f" · ownId `{bid}`"

    lines = [
        bot_line,
        f"• Thread / Chat ID: `{chat_id}`" if chat_id else None,
    ]
    if is_group:
        lines.append(
            f"• Tên nhóm: **{chat_name}**" if chat_name else "• Tên nhóm: *(chưa nhận diện)*"
        )
        if user_id:
            lines.append(f"• User ID người gửi: `{user_id}`")
        lines.append(
            f"• Tên user: **{user_name}**" if user_name else "• Tên user: *(chưa nhận diện)*"
        )
    else:
        lines.append(
            f"• Tên user: **{user_name or chat_name}**"
            if (user_name or chat_name)
            else "• Tên user: *(chưa nhận diện)*"
        )
        if user_id and user_id != chat_id:
            lines.append(f"• User ID: `{user_id}`")
    lines.append(f"• Trạng thái: {status}")
    snippet = (text or rec.get("last_text") or "")[:120]
    if snippet:
        lines.append(f"• Tin: {snippet}")
    lines.append(
        "→ Trả lời: `có` / `lưu` để đưa vào danh bạ, hoặc `không` / `bỏ`. "
        "Cũng có thể thêm bằng Admin #N / Lọc thread."
    )
    return "\n".join(x for x in lines if x)


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


def list_directory(platform: str, *, limit: int = 300) -> list[dict[str, Any]]:
    """Danh bạ thread theo kênh — CHỈ mục đã đồng ý hoặc cấu hình Settings.

    Nguồn:
      - ``approved``: channel_contacts với known=True (admin trả lời `có` / lưu)
      - ``admin``: Admin #N trong Settings
      - ``filter``: Lọc thread trong Settings

    Không gộp tin gần đây / auto chưa đồng ý.
    Mỗi dòng: bot_id, bot_label, thread_id, kind, name, sources[].
    """
    plat = str(platform or "").strip()
    if plat == "zalo_personal":
        plat = "zalop"
    if plat not in {"tg", "zalo", "zalop"}:
        return []

    # key = bot_id|thread_id
    by: dict[str, dict[str, Any]] = {}

    def _put(
        bot_id: str,
        thread_id: str,
        *,
        kind: str = "user",
        name: str = "",
        source: str = "",
        bot_lab: str = "",
    ) -> None:
        bid = str(bot_id or "").strip()
        tid = str(thread_id or "").strip()
        if not bid or not tid:
            return
        k = f"{bid}|{tid}"
        kind_n = "group" if str(kind or "").lower() in {
            "group", "1", "nhóm", "nhom", "supergroup", "channel",
        } else "user"
        name_n = str(name or "").strip()
        src = str(source or "").strip()
        prev = by.get(k)
        if not prev:
            by[k] = {
                "bot_id": bid,
                "bot_label": (bot_lab or bot_label(plat, bid)).strip() or bid,
                "thread_id": tid,
                "kind": kind_n,
                "name": name_n,
                "sources": [src] if src else [],
            }
            return
        # kind: group thắng user nếu mâu thuẫn
        if kind_n == "group":
            prev["kind"] = "group"
        # Tên: không ghi đè tên nhóm đã có bằng chuỗi rỗng; admin/filter ưu tiên hơn activity
        if name_n:
            prev_name = str(prev.get("name") or "").strip()
            src_rank = {"admin": 3, "filter": 2, "auto": 1, "activity": 0}
            if not prev_name:
                prev["name"] = name_n
            elif src_rank.get(src, 0) >= src_rank.get(
                (prev.get("sources") or ["activity"])[0], 0
            ):
                # Nguồn đáng tin hơn (admin/filter) → cập nhật tên
                if src in {"admin", "filter"}:
                    prev["name"] = name_n
        if src and src not in prev["sources"]:
            prev["sources"].append(src)
        # bot_label: luôn ưu tiên tên thật (label), không để bare id
        bl = (bot_lab or bot_label(plat, bid)).strip()
        if bl and (not prev.get("bot_label") or prev["bot_label"] == bid):
            prev["bot_label"] = bl

    # 1) Đã đồng ý lưu (known=True) — không lấy tin gần đây / stranger chưa duyệt
    for r in list_contacts(plat, limit=200):
        if not r.get("known"):
            continue
        key = str(r.get("key") or "")
        parts = key.split(":")
        # platform:bot:chat[:user] — 4+ phần = member
        if len(parts) >= 4:
            continue
        is_g = str(r.get("kind") or "") == "group"
        # Nhóm: chỉ alias / chat_name — KHÔNG dùng display_name (tên người gửi)
        if is_g:
            nm = (
                str(r.get("alias") or "").strip()
                or str(r.get("chat_name") or "").strip()
            )
        else:
            nm = (
                str(r.get("alias") or "").strip()
                or str(r.get("display_name") or "").strip()
                or str(r.get("chat_name") or "").strip()
            )
        _put(
            str(r.get("bot_id") or ""),
            str(r.get("chat_id") or ""),
            kind=str(r.get("kind") or "user"),
            name=nm,
            source="approved",
            bot_lab=str(r.get("bot_label") or ""),
        )

    # 2) Setting — Admin #N
    try:
        cfg = config.get() or {}
        if plat in {"tg", "zalo"}:
            bots_key = "telegram_bots" if plat == "tg" else "zalo_bots"
            from services.admin_workspace import admin_entries
            for b in (cfg.get(bots_key) or []):
                if not isinstance(b, dict):
                    continue
                tok = str(b.get("token") or "").strip()
                bid = tok.split(":", 1)[0].strip() if tok else ""
                if not bid:
                    continue
                bl = str(b.get("label") or "").strip() or bot_label(plat, bid)
                for e in admin_entries(b):
                    _put(
                        bid,
                        str(e.get("chat_id") or ""),
                        kind=str(e.get("kind") or "private"),
                        name=str(e.get("name") or ""),
                        source="admin",
                        bot_lab=bl,
                    )
        elif plat == "zalop":
            raw = cfg.get("zalo_personal_account_admins") or {}
            if isinstance(raw, dict):
                for own_id, entry in raw.items():
                    if not isinstance(entry, dict):
                        continue
                    bid = str(own_id or "").strip()
                    bl = bot_label("zalop", bid)
                    entries = entry.get("admin_entries")
                    if isinstance(entries, list) and entries:
                        for e in entries:
                            if not isinstance(e, dict):
                                continue
                            _put(
                                bid,
                                str(e.get("chat_id") or ""),
                                kind=str(e.get("kind") or "private"),
                                name=str(e.get("name") or ""),
                                source="admin",
                                bot_lab=bl,
                            )
                    else:
                        th = str(entry.get("admin_thread") or "").strip()
                        if th:
                            knd = (
                                "group"
                                if str(entry.get("admin_thread_type") or "0") in {"1", "group"}
                                else "user"
                            )
                            _put(
                                bid, th, kind=knd,
                                name=str(entry.get("admin_name") or ""),
                                source="admin", bot_lab=bl,
                            )
    except Exception:
        pass

    # 3) Setting — Lọc thread (meta name/kind)
    try:
        cfg = config.get() or {}
        tf = cfg.get("thread_filters") or {}
        meta = cfg.get("thread_filter_meta") or {}
        if isinstance(tf, dict):
            for key, _groups in tf.items():
                ks = str(key or "")
                # tg:BOT:CHAT | zalo:BOT:CHAT | zalop:OWN:CHAT | tg:CHAT
                if not (ks == plat or ks.startswith(f"{plat}:")):
                    continue
                parts = ks.split(":")
                if len(parts) >= 3:
                    bid, tid = parts[1], ":".join(parts[2:])
                elif len(parts) == 2:
                    bid, tid = "", parts[1]
                else:
                    continue
                if not bid:
                    # "mọi bot" — gán bot_id = "*" để vẫn hiện
                    bid = "*"
                m = meta.get(ks) if isinstance(meta, dict) else None
                m = m if isinstance(m, dict) else {}
                _put(
                    bid, tid,
                    kind=str(m.get("kind") or "group"),
                    name=str(m.get("name") or ""),
                    source="filter",
                    bot_lab="Mọi bot" if bid == "*" else bot_label(plat, bid),
                )
    except Exception:
        pass

    rows = list(by.values())

    # Zalo Cá Nhân: thiếu tên trên mục Settings/đã duyệt → resolve để HIỂN THỊ
    # (không tự thêm mục lạ vào danh bạ — chỉ làm giàu tên dòng đã có).
    if plat == "zalop":
        try:
            from services.zalo_personal import resolve_thread as _zalop_resolve
            for row in rows:
                if str(row.get("name") or "").strip():
                    continue
                bid = str(row.get("bot_id") or "").strip()
                tid = str(row.get("thread_id") or "").strip()
                if not bid or not tid or bid == "*":
                    continue
                prefer = "group" if row.get("kind") == "group" else "private"
                try:
                    info = _zalop_resolve(bid, tid, prefer)
                except Exception:
                    continue
                n = str((info or {}).get("name") or "").strip()
                if not n:
                    continue
                row["name"] = n
                if (info or {}).get("kind") == "group":
                    row["kind"] = "group"
        except Exception:
            pass

    rows.sort(key=lambda x: (
        str(x.get("bot_label") or "").lower(),
        str(x.get("name") or "").lower(),
        str(x.get("thread_id") or ""),
    ))
    return rows[: max(1, min(int(limit or 300), 500))]


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
