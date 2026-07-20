"""Hoạt động gần đây + blacklist DÙNG CHUNG cho các kênh chat (Zalo Cá Nhân
`zalop`, Zalo Bot `zalo`, Telegram `tg`).

- `record(...)`  : ghi lại LẦN GẦN NHẤT mỗi (tài khoản, chat, người gửi) — bộ đệm
  RAM, giới hạn 300 mục/kênh, tự xoá cũ; LƯU BỀN ra data/channel_activity.json
  (best-effort) để không mất khi restart container. Trang quản lý đọc để hiện
  "ai vừa nhắn, Chat ID / User ID bao nhiêu, qua tài khoản nào".
- Blacklist    : lưu bền vào config `channel_blacklist` (dict platform -> list
  {id, kind, name, account}). `account` = bot_id / ownId (trống = chung cả kênh).
  `is_blacklisted(platform, chat, user, account=...)` chặn theo đúng bot/acc.
  Khi thêm, `add_blacklist()` báo admin qua notifier.

Các kênh gọi `record()` + `is_blacklisted()` ngay khi nhận tin (trước khi vào AI /
chuyển tiếp HA). Blacklist khớp id với CẢ chat_id lẫn user_id (kind chỉ để hiển thị).
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

from services.config import config

_MAX_PER_PLATFORM = 300

_lock = threading.Lock()
# platform -> OrderedDict[key -> record]; key = "chat|user" để giữ mục mới nhất.
_recent: dict[str, "OrderedDict[str, dict]"] = {}
_loaded = False  # đã nạp file bền chưa (nạp lười, 1 lần)


def _store_path():
    from services.config import DATA_DIR
    return DATA_DIR / "channel_activity.json"


def _load_locked() -> None:
    """Nạp bộ đệm từ đĩa (gọi khi ĐANG giữ _lock). Best-effort, hỏng file = bỏ qua."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        import json
        raw = json.loads(_store_path().read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        for plat, rows in raw.items():
            if not isinstance(rows, list):
                continue
            bucket = _recent.setdefault(str(plat), OrderedDict())
            for rec in rows:
                if not isinstance(rec, dict) or not rec.get("chat_id"):
                    continue
                key = f"{rec.get('chat_id')}|{rec.get('user_id') or ''}"
                if key not in bucket:  # RAM (mới hơn) thắng file
                    bucket[key] = rec
    except Exception:
        pass


def _save_locked() -> None:
    """Ghi bộ đệm ra đĩa atomic (gọi khi ĐANG giữ _lock). Best-effort."""
    try:
        import json
        data = {plat: list(bucket.values()) for plat, bucket in _recent.items()}
        path = _store_path()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def _cfg() -> dict:
    try:
        return config.get()
    except Exception:
        return {}


# ── Ghi nhận hoạt động ────────────────────────────────────────────────────────

def record(platform: str, *, account: str = "", chat_id: str = "",
           chat_name: str = "", user_id: str = "", user_name: str = "",
           is_group: bool = False, text: str = "") -> None:
    """Cập nhật LẦN GẦN NHẤT cho (chat, user). Best-effort, không raise.

    chat_name = title nhóm / tên chat (nếu có).
    """
    platform = str(platform or "").strip()
    chat_id = str(chat_id or "").strip()
    if not platform or not chat_id:
        return
    user_id = str(user_id or "").strip()
    key = f"{chat_id}|{user_id}"
    rec = {
        "platform": platform,
        "account": str(account or "").strip(),
        "chat_id": chat_id,
        "chat_name": str(chat_name or "").strip(),
        "user_id": user_id,
        "user_name": str(user_name or "").strip(),
        "is_group": bool(is_group),
        "text": (str(text or "").strip())[:160],
        "ts": int(time.time()),
    }
    with _lock:
        _load_locked()
        bucket = _recent.setdefault(platform, OrderedDict())
        if key in bucket:
            del bucket[key]
        bucket[key] = rec
        while len(bucket) > _MAX_PER_PLATFORM:
            bucket.popitem(last=False)
        _save_locked()


def recent(platform: str = "", limit: int = 100) -> list[dict]:
    """Danh sách hoạt động gần đây (mới nhất trước). platform rỗng = mọi kênh."""
    platform = str(platform or "").strip()
    with _lock:
        _load_locked()
        rows: list[dict] = []
        for plat, bucket in _recent.items():
            if platform and plat != platform:
                continue
            rows.extend(bucket.values())
    rows.sort(key=lambda r: r.get("ts", 0), reverse=True)
    return rows[: max(1, int(limit or 100))]


# ── Blacklist (bền, trong config) — theo từng bot/account ─────────────────────

def get_blacklist(platform: str = "", account: str = "") -> list[dict]:
    """Danh sách blacklist. account set → chỉ mục của bot đó + mục chung (account='').
    account rỗng → mọi mục của platform (dùng UI 'tất cả')."""
    raw = _cfg().get("channel_blacklist")
    raw = raw if isinstance(raw, dict) else {}
    platform = str(platform or "").strip()
    account = str(account or "").strip()
    if platform:
        v = raw.get(platform)
        items = list(v) if isinstance(v, list) else []
    else:
        items = []
        for plat, v in raw.items():
            if isinstance(v, list):
                for it in v:
                    if isinstance(it, dict):
                        items.append({**it, "platform": plat})
    if not account:
        return [it for it in items if isinstance(it, dict)]
    # Filter: chung (không account) + đúng bot
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        acc = str(it.get("account") or "").strip()
        if not acc or acc == account:
            out.append(it)
    return out


def is_blacklisted(platform: str, chat_id: str = "", user_id: str = "",
                   account: str = "") -> bool:
    """True nếu chat HOẶC người gửi bị chặn trên bot/acc này.

    Mục blacklist:
      - account rỗng = CHUNG cả platform (áp mọi bot)
      - account = bot_id/ownId = chỉ chặn trên bot/acc đó
    """
    platform = str(platform or "").strip()
    account = str(account or "").strip()
    chat_id = str(chat_id or "").strip()
    user_id = str(user_id or "").strip()
    if not platform or (not chat_id and not user_id):
        return False
    for it in get_blacklist(platform):
        if not isinstance(it, dict):
            continue
        entry_acc = str(it.get("account") or "").strip()
        # Per-bot entry chỉ áp khi account khớp
        if entry_acc and entry_acc != account:
            continue
        eid = str(it.get("id") or "").strip()
        if not eid:
            continue
        if (chat_id and eid == chat_id) or (user_id and eid == user_id):
            return True
    return False


def add_blacklist(platform: str, entry_id: str, kind: str = "",
                  name: str = "", notify: bool = True,
                  account: str = "") -> dict:
    """Thêm id vào blacklist của kênh (+ account = bot/ownId). Báo admin nếu notify."""
    platform = str(platform or "").strip()
    entry_id = str(entry_id or "").strip()
    account = str(account or "").strip()
    if not platform or not entry_id:
        return {"ok": False, "error": "Thiếu platform/id"}
    raw = _cfg().get("channel_blacklist")
    raw = dict(raw) if isinstance(raw, dict) else {}
    items = [it for it in (raw.get(platform) or []) if isinstance(it, dict)]
    for it in items:
        if (str(it.get("id") or "").strip() == entry_id
                and str(it.get("account") or "").strip() == account):
            return {"ok": True, "already": True}
    items.append({
        "id": entry_id,
        "kind": str(kind or "").strip(),
        "name": str(name or "").strip(),
        "account": account,
    })
    raw[platform] = items
    try:
        config.update({"channel_blacklist": raw})
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if notify:
        _notify_blacklist("thêm", platform, entry_id, kind, name, account)
    return {"ok": True}


def remove_blacklist(platform: str, entry_id: str, account: str = "") -> dict:
    """Gỡ blacklist. account set → chỉ gỡ mục của bot đó; account rỗng → gỡ mọi
    mục cùng id (hoặc chỉ mục chung nếu chỉ có chung)."""
    platform = str(platform or "").strip()
    entry_id = str(entry_id or "").strip()
    account = str(account or "").strip()
    raw = _cfg().get("channel_blacklist")
    raw = dict(raw) if isinstance(raw, dict) else {}
    items_in = [it for it in (raw.get(platform) or []) if isinstance(it, dict)]
    items: list[dict] = []
    for it in items_in:
        eid = str(it.get("id") or "").strip()
        eacc = str(it.get("account") or "").strip()
        if eid != entry_id:
            items.append(it)
            continue
        # id khớp: gỡ nếu account filter rỗng (gỡ hết cùng id) hoặc đúng account
        if account and eacc != account:
            items.append(it)
            continue
        # drop this entry
    raw[platform] = items
    try:
        config.update({"channel_blacklist": raw})
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


_PLAT_LABEL = {"zalop": "Zalo Cá Nhân", "zalo": "Zalo Bot", "tg": "Telegram"}


def _notify_blacklist(action: str, platform: str, entry_id: str,
                      kind: str, name: str, account: str = "") -> None:
    label = _PLAT_LABEL.get(platform, platform)
    what = "nhóm" if str(kind).strip() == "chat" else ("cá nhân" if str(kind).strip() == "user" else "mục")
    scope = f"bot/acc `{account}`" if account else "cả kênh"
    try:
        from services.notifier import notify_admin as _notify
        _notify(
            f"🚫 Đã {action} blacklist {label} ({what}, {scope})\n"
            f"• ID: {entry_id}\n"
            + (f"• Tên: {name}\n" if name else "")
            + "→ Bot/tài khoản này sẽ KHÔNG nhận/hiển thị tin từ mục trên nữa."
        )
    except Exception:
        pass
