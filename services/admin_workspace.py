"""Workspace độc lập cho MỖI admin thread (multi-admin, multi-bot).

Mỗi admin_chat_id có:
  - bot_names: {bot_id → tên do admin này đặt} (gợi ý / hiển thị riêng)
  - contact_aliases: {contact_key → alias riêng của admin này}
  - pending: hội thoại đang dở (lưu người lạ, đặt tên bot…)

Bot độc lập: cảnh báo/gửi admin chỉ qua token bot nhận tin, fan-out TỚI MỌI
admin_thread của CHÍNH bot đó — không “admin chung” chéo bot.

Lưu: DATA_DIR/admin_workspaces.json
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
_PATH = Path(DATA_DIR) / "admin_workspaces.json"
_data: dict[str, dict[str, Any]] = {}
_loaded = False

_PENDING_TTL = 600  # 10 phút


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


def ws_key(platform: str, admin_chat_id: str) -> str:
    return f"{str(platform or '').strip()}:{str(admin_chat_id or '').strip()}"


def get_ws(platform: str, admin_chat_id: str) -> dict[str, Any]:
    _ensure()
    k = ws_key(platform, admin_chat_id)
    with _lock:
        rec = _data.get(k)
        if not rec:
            rec = {
                "platform": str(platform or "").strip(),
                "admin_chat_id": str(admin_chat_id or "").strip(),
                "bot_names": {},
                "contact_aliases": {},
                "pending": None,
            }
            _data[k] = rec
            _save()
        return dict(rec)


def _put_ws(ws: dict[str, Any]) -> None:
    k = ws_key(ws.get("platform", ""), ws.get("admin_chat_id", ""))
    with _lock:
        _data[k] = ws
        _save()


def bot_display_name(platform: str, bot_id: str, admin_chat_id: str = "") -> str:
    """Tên bot theo góc nhìn admin: workspace → label config → getMe → id."""
    bid = str(bot_id or "").strip()
    if not bid:
        return "?"
    if admin_chat_id:
        ws = get_ws(platform, admin_chat_id)
        n = str((ws.get("bot_names") or {}).get(bid) or "").strip()
        if n:
            return n
    # global label + getMe via channel_contacts.bot_label
    try:
        from services.channel_contacts import bot_label
        return bot_label(platform, bid)
    except Exception:
        return bid


def set_bot_name(platform: str, admin_chat_id: str, bot_id: str, name: str) -> dict[str, Any]:
    ws = get_ws(platform, admin_chat_id)
    names = dict(ws.get("bot_names") or {})
    bid = str(bot_id or "").strip()
    name = (name or "").strip()[:64]
    if bid and name:
        names[bid] = name
    elif bid and not name:
        names.pop(bid, None)
    ws["bot_names"] = names
    _put_ws(ws)
    return ws


def set_contact_alias(platform: str, admin_chat_id: str, contact_key: str, alias: str) -> dict[str, Any]:
    ws = get_ws(platform, admin_chat_id)
    aliases = dict(ws.get("contact_aliases") or {})
    ck = str(contact_key or "").strip()
    alias = (alias or "").strip()[:64]
    if ck and alias:
        aliases[ck] = alias
    elif ck:
        aliases.pop(ck, None)
    ws["contact_aliases"] = aliases
    _put_ws(ws)
    # Also mark global contact known so re-alerts stop for everyone
    try:
        from services import channel_contacts as cc
        cc.set_alias(ck, alias, mark_known=True)
    except Exception:
        pass
    return ws


def contact_alias_for(platform: str, admin_chat_id: str, contact_key: str, fallback: str = "") -> str:
    ws = get_ws(platform, admin_chat_id)
    a = str((ws.get("contact_aliases") or {}).get(contact_key) or "").strip()
    return a or fallback


def set_pending(platform: str, admin_chat_id: str, pending: dict[str, Any] | None) -> None:
    ws = get_ws(platform, admin_chat_id)
    if pending is None:
        ws["pending"] = None
    else:
        pending = dict(pending)
        pending["ts"] = int(time.time())
        ws["pending"] = pending
    _put_ws(ws)


def get_pending(platform: str, admin_chat_id: str) -> Optional[dict[str, Any]]:
    ws = get_ws(platform, admin_chat_id)
    p = ws.get("pending")
    if not isinstance(p, dict):
        return None
    if int(time.time()) - int(p.get("ts") or 0) > _PENDING_TTL:
        set_pending(platform, admin_chat_id, None)
        return None
    return dict(p)


def clear_pending(platform: str, admin_chat_id: str) -> None:
    set_pending(platform, admin_chat_id, None)


def list_bots_for_admin(platform: str, admin_chat_id: str) -> list[dict[str, str]]:
    """Bots this admin is attached to (appears in admin_threads) + all enabled for naming."""
    plat = str(platform or "").strip()
    aid = str(admin_chat_id or "").strip()
    bots_key = "telegram_bots" if plat == "tg" else "zalo_bots" if plat == "zalo" else ""
    out: list[dict[str, str]] = []
    if not bots_key:
        return out
    try:
        for b in (config.get().get(bots_key) or []):
            if not isinstance(b, dict) or not b.get("enabled", True):
                continue
            tok = str(b.get("token") or "").strip()
            bid = tok.split(":", 1)[0].strip() if tok else ""
            if not bid:
                continue
            admins = admin_thread_ids(b)
            # List all enabled bots; mark if this admin receives alerts from them
            out.append({
                "bot_id": bid,
                "platform_name": str(b.get("label") or "").strip(),
                "my_name": bot_display_name(plat, bid, aid),
                "is_my_bot": aid in admins or not admins,  # no admins = legacy global
            })
    except Exception:
        pass
    return out


def admin_thread_ids(bot: dict | None) -> list[str]:
    """All admin chat IDs for a bot entry (multi-admin)."""
    if not isinstance(bot, dict):
        return []
    ids: list[str] = []
    # New: admin_threads list
    raw = bot.get("admin_threads")
    if isinstance(raw, list):
        for x in raw:
            s = str(x).strip()
            if s and s not in ids:
                ids.append(s)
    # Legacy single field
    one = str(bot.get("admin_thread") or "").strip()
    if one and one not in ids:
        ids.append(one)
    return ids


def global_fallback_admins(platform: str) -> list[str]:
    """Legacy single global admin only if bot has no per-bot admins."""
    c = config.get()
    if platform == "tg":
        a = str(c.get("telegram_admin_thread") or "").strip()
        return [a] if a else []
    if platform == "zalo":
        a = str(c.get("zalo_admin_thread") or "").strip()
        return [a] if a else []
    return []


def resolve_admins_for_bot(platform: str, bot: dict | None) -> list[str]:
    """Admin threads to notify for this bot — multi, independent."""
    ids = admin_thread_ids(bot)
    if ids:
        return ids
    return global_fallback_admins(platform)


def format_bot_list(platform: str, admin_chat_id: str) -> str:
    rows = list_bots_for_admin(platform, admin_chat_id)
    if not rows:
        return "Chưa có bot nào bật."
    lines = ["🤖 Danh sách bot (tên **bạn** đặt / mặc định):"]
    for r in rows:
        mine = "★ nhận alert" if r.get("is_my_bot") else "·"
        lines.append(
            f"{mine} `{r['bot_id']}` → **{r['my_name']}**"
            + (f" (label hệ thống: {r['platform_name']})" if r.get("platform_name") else "")
        )
    lines.append(
        "\nĐặt tên (chỉ trong thread admin của bạn):\n"
        "`đặt tên bot <id> = Tên dễ nhớ`\n"
        "VD: `đặt tên bot 123456789 = Bot Nhà`"
    )
    return "\n".join(lines)


def parse_set_bot_name(text: str) -> Optional[tuple[str, str]]:
    t = (text or "").strip()
    m = re.match(
        r"^(?:đặt\s*tên\s*bot|dat\s*ten\s*bot|name\s*bot)\s+(\S+)\s*[=:]\s*(.+)$",
        t,
        re.I,
    )
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip()


def parse_list_bots(text: str) -> bool:
    t = (text or "").strip().lower()
    return t in {
        "đặt tên bot", "dat ten bot", "liệt kê bot", "liet ke bot",
        "danh sách bot", "danh sach bot", "list bots", "list bot",
        "tôi muốn đặt tên bot", "toi muon dat ten bot",
    }


# ── Pending: save stranger ───────────────────────────────────────────────────


def start_save_prompt(platform: str, admin_chat_id: str, contact: dict[str, Any]) -> str:
    """After new-contact alert: ask this admin whether to save (independent pending)."""
    key = str(contact.get("key") or "")
    bl = bot_display_name(platform, str(contact.get("bot_id") or ""), admin_chat_id)
    set_pending(platform, admin_chat_id, {
        "type": "save_contact",
        "step": "ask_yes",
        "contact_key": key,
        "bot_id": contact.get("bot_id"),
        "chat_id": contact.get("chat_id"),
        "user_id": contact.get("user_id"),
        "display_name": contact.get("display_name") or "",
        "chat_name": contact.get("chat_name") or "",
        "kind": contact.get("kind") or "user",
    })
    dn = str(contact.get("display_name") or "").strip()
    gn = str(contact.get("chat_name") or "").strip()
    is_group = str(contact.get("kind") or "") == "group"
    lines_info = []
    if dn:
        lines_info.append(f"• Tên người (nền tảng): **{dn}**")
    else:
        lines_info.append("• Tên người (nền tảng): *(trống)*")
    if is_group:
        if gn:
            lines_info.append(f"• Tên nhóm: **{gn}**")
        else:
            lines_info.append("• Tên nhóm: *(trống)*")
    return (
        f"\n\n💾 **Lưu vào danh bạ của bạn?** (bot **{bl}**)\n"
        f"Trả lời: `có` / `lưu` hoặc `không` / `bỏ`\n"
        f"(Chỉ thread admin này — admin khác tự quyết riêng.)\n"
        + "\n".join(lines_info)
    )


def handle_admin_text(platform: str, admin_chat_id: str, text: str) -> Optional[str]:
    """If this message is from an admin thread, handle workspace commands / pending.

    Returns reply text if handled, else None (fall through to normal agent).
    """
    text = (text or "").strip()
    if not text or not admin_chat_id:
        return None

    # List / name bots
    if parse_list_bots(text):
        return format_bot_list(platform, admin_chat_id)

    parsed = parse_set_bot_name(text)
    if parsed:
        bid, name = parsed
        # resolve bid by current display name match
        for row in list_bots_for_admin(platform, admin_chat_id):
            if row["bot_id"] == bid or row["my_name"].lower() == bid.lower():
                bid = row["bot_id"]
                break
        set_bot_name(platform, admin_chat_id, bid, name)
        return f"Đã lưu tên bot `{bid}` = **{name}** (chỉ thread admin này)."

    # Pending save flow
    pending = get_pending(platform, admin_chat_id)
    if not pending or pending.get("type") != "save_contact":
        # free-form rename contact: đặt tên <ref> = Alias
        try:
            from services.channel_contacts import parse_admin_rename, find_by_ref
            ren = parse_admin_rename(text)
            if ren:
                ref, alias = ren
                rec = find_by_ref(ref)
                if not rec:
                    return f"Không thấy contact `{ref}`."
                set_contact_alias(platform, admin_chat_id, str(rec["key"]), alias)
                return f"Đã lưu **{alias}** cho `{rec.get('key')}` (danh bạ của bạn)."
        except Exception:
            pass
        return None

    step = pending.get("step") or "ask_yes"
    low = text.lower()

    if step == "ask_yes":
        if low in {"không", "khong", "no", "bỏ", "bo", "skip", "0"}:
            clear_pending(platform, admin_chat_id)
            return "Ok, không lưu. (Vẫn có thể hỏi 'ai vừa nhắn' sau.)"
        if low in {"có", "co", "yes", "lưu", "luu", "1", "ok", "oke"}:
            dn = str(pending.get("display_name") or "").strip()
            gn = str(pending.get("chat_name") or "").strip()
            is_group = str(pending.get("kind") or "") == "group"
            set_pending(platform, admin_chat_id, {**pending, "step": "ask_name"})
            if is_group:
                return (
                    "Lưu tên nào?\n"
                    f"1. Tên **người** (nền tảng bot nhận được)\n"
                    f"   → **{dn or '(trống)'}**\n"
                    f"2. Tên **nhóm** (title nhóm bot nhận được)\n"
                    f"   → **{gn or '(trống)'}**\n"
                    "3. Tự đặt — gõ thẳng (VD: `Nhóm A - Anh B`)\n"
                    "4. `bỏ` — không lưu\n"
                    "Trả lời `1` / `2` / gõ tên / `bỏ`."
                )
            return (
                "Lưu tên nào?\n"
                f"1. Tên **người** (nền tảng bot nhận được)\n"
                f"   → **{dn or '(trống)'}**\n"
                "2. Tự đặt — gõ thẳng (VD: `Anh A`)\n"
                "3. `bỏ` — không lưu\n"
                "Trả lời `1` / gõ tên / `bỏ`."
            )
        # Câu KHÁC (hỏi việc, chat thường…) → nhả xuống agent trả lời bình
        # thường; pending vẫn chờ trong TTL — admin trả lời `có`/`không` sau.
        return None

    if step == "ask_name":
        is_group = str(pending.get("kind") or "") == "group"
        skip_set = {"bỏ", "bo", "không", "khong", "skip"}
        if is_group:
            skip_set |= {"4"}
        else:
            skip_set |= {"3"}
        if low in skip_set:
            clear_pending(platform, admin_chat_id)
            return "Đã huỷ lưu."
        if low in {"1", "người", "nguoi", "tên người", "ten nguoi",
                   "tên nền tảng", "ten nen tang"}:
            alias = str(pending.get("display_name") or "").strip()
            source_note = "tên người (nền tảng)"
            if not alias:
                return "Tên người trống. Chọn `2` (nhóm) nếu có, hoặc gõ tên tự đặt / `bỏ`."
        elif is_group and low in {"2", "nhóm", "nhom", "tên nhóm", "ten nhom", "group"}:
            alias = str(pending.get("chat_name") or "").strip()
            source_note = "tên nhóm"
            if not alias:
                return "Tên nhóm trống. Chọn `1` (người) hoặc gõ tên tự đặt / `bỏ`."
        else:
            # custom: strip "2." or "3." prefix
            alias = re.sub(r"^[23][\.\)\-\s]+", "", text).strip()
            source_note = "tên bạn tự đặt"
        if not alias:
            return "Tên trống — gõ `1` / `2` (nhóm) hoặc gõ tên / `bỏ`."
        ck = str(pending.get("contact_key") or "")
        set_contact_alias(platform, admin_chat_id, ck, alias)
        clear_pending(platform, admin_chat_id)
        bid = pending.get("bot_id")
        bl = bot_display_name(platform, str(bid or ""), admin_chat_id)
        gn = str(pending.get("chat_name") or "").strip()
        dn = str(pending.get("display_name") or "").strip()
        extra = ""
        if is_group and (gn or dn):
            extra = f"\n• (tham chiếu) người=`{dn or '—'}` · nhóm=`{gn or '—'}`"
        return (
            f"Đã lưu **{alias}** ({source_note})\n"
            f"• key `{ck}` · bot **{bl}**{extra}\n"
            f"Lần sau họ nhắn sẽ không báo lạ. Gửi tin: "
            f"`gửi cho {alias} bằng bot {bl}: ...`"
        )

    return None


def _reset_for_tests(path: Path | None = None) -> None:
    global _PATH, _data, _loaded
    with _lock:
        if path is not None:
            _PATH = Path(path)
        _data = {}
        _loaded = False
