"""Zalo Cá Nhân (zalo custom) — kênh AI 2 chiều qua BOT SERVER zca-js.

Khác `zalo_bot.py` (Zalo Bot API chính thức, clone Telegram), kênh này điều khiển
TÀI KHOẢN ZALO CÁ NHÂN thông qua bot server Node.js (image
`ghcr.io/smarthomeblack/zalobot-*`, fork multizlogin dùng thư viện zca-js):
- Đăng nhập bằng quét QR (như Zalo Web), đa tài khoản, cookie tự relogin.
- REST API `/api/*ByAccount` (100+ endpoint) — Home Assistant có thể cài custom
  integration https://github.com/smarthomeblack/zalo_bot trỏ THẲNG vào bot
  server này để gửi tin/thông báo độc lập với chatgpt2api.
- Webhook theo TÀI KHOẢN: messageWebhookUrl / groupEventWebhookUrl /
  reactionWebhookUrl → gateway tự đăng ký về `/zalo-personal/webhook`.

Luồng tin nhắn đến:  Zalo ⇄ bot server ─POST─▶ gateway
  1. Dedup msgId, bỏ tin isSelf.
  2. CHUYỂN TIẾP sang webhook Home Assistant (LAN hoặc domain) nếu bật —
     tham khảo luuquangvu/tutorials zalo_custom_bot_handle_tool.py: HA tạo
     webhook id rồi automation xử lý payload đã chuẩn hóa.
  3. AI trả lời (nếu bật): CHUNG orchestrator với Telegram/Zalo Bot — cùng
     persona/memory/bộ lọc thread (khóa `zalop:<threadId>`).

AN TOÀN tài khoản cá nhân: KHÔNG trả lời AI cho thread lạ — chỉ thread nằm
trong `zalo_personal_chat_ids` hoặc có bản ghi 'Lọc chức năng theo thread'
(khóa `zalop:`). Thread mới nhắn tới sẽ báo admin kèm thread ID để cấp phép.

Payload webhook = event zca-js nguyên bản + `_accountId`:
  {type: 0|1, threadId, isSelf, data: {msgId, cliMsgId, msgType, uidFrom,
   idTo, dName, ts, content: str|{href,thumb,title,...}, ttl}, _accountId}
msgType: webchat | chat.photo | share.file | chat.voice | chat.video | chat.sticker
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import time
import urllib.request
from typing import Any

import httpx

from services.config import config

logger = logging.getLogger(__name__)

_MAX_LEN = 1990          # Zalo giới hạn 2000 ký tự / tin
_MAX_CHUNKS = 6

# Ngữ cảnh tin nhắn ĐANG xử lý trên thread này (account nhận + loại thread) —
# reminders đọc lúc tạo nhắc hẹn để về sau gửi đúng account, đúng nhóm/cá nhân.
_msg_ctx = threading.local()


def current_msg_ctx() -> tuple[str, int]:
    """(account_id, thread_type) của tin đang xử lý; ngoài luồng tin → ('', 0)."""
    return (str(getattr(_msg_ctx, "account", "") or ""),
            int(getattr(_msg_ctx, "thread_type", 0) or 0))

# ── Cấu hình ──────────────────────────────────────────────────────────────────

def _cfg() -> dict:
    try:
        return config.get()
    except Exception:
        return {}


def _bool(c: dict, key: str, default: bool = False) -> bool:
    v = c.get(key, default)
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "on"}
    return bool(v)


# zalo-server nay nhúng trong image (supervisord, 127.0.0.1:3001) → mặc định
# TRỎ NỘI BỘ, kênh bật sẵn. Vẫn cho ghi đè để trỏ bot server ngoài nếu cần.
_DEFAULT_SERVER_URL = "http://127.0.0.1:3001"


def enabled() -> bool:
    return _bool(_cfg(), "zalo_personal_enabled", True)


def _server_url() -> str:
    return (str(_cfg().get("zalo_personal_server_url") or "").strip().rstrip("/")
            or _DEFAULT_SERVER_URL)


def _credentials() -> tuple[str, str]:
    c = _cfg()
    return (str(c.get("zalo_personal_username") or "admin").strip(),
            str(c.get("zalo_personal_password") or "admin").strip())


def _default_account() -> str:
    return str(_cfg().get("zalo_personal_account_id") or "").strip()


def _ai_model(account_id: str = "", thread_id: str = "") -> str:
    """Model: admin_entries.ai_model → acc.ai_model → kênh → global → AI text."""
    c = _cfg()
    acc = str(account_id or "").strip()
    tid = str(thread_id or "").strip()
    raw = c.get("zalo_personal_account_admins")
    if isinstance(raw, dict) and acc:
        entry = raw.get(acc)
        if isinstance(entry, dict):
            # 1) Model riêng Admin #N (nếu tin từ đúng thread admin)
            if tid:
                for e in (entry.get("admin_entries") or []):
                    if not isinstance(e, dict):
                        continue
                    if str(e.get("chat_id") or "").strip() == tid:
                        m = str(e.get("ai_model") or "").strip()
                        if m:
                            return m
            # 2) Model mặc định acc
            m = str(entry.get("ai_model") or "").strip()
            if m:
                return m
    # 3) Model kênh Zalo Cá Nhân
    m = str(c.get("zalo_personal_ai_model") or "").strip()
    if m:
        return m
    # 4) Global / fallback
    return (str(c.get("telegram_ai_model") or "").strip()
            or str(c.get("zalo_ai_model") or "").strip()
            or "AI text")


def _chat_ids() -> list[str]:
    v = _cfg().get("zalo_personal_chat_ids")
    if isinstance(v, str):
        v = [s.strip() for s in re.split(r"[,\n]+", v) if s.strip()]
    return [str(x).strip() for x in (v or []) if str(x).strip()]


def webhook_secret() -> str:
    """Secret cho webhook receiver — tự sinh 1 lần rồi lưu vào config."""
    c = _cfg()
    s = str(c.get("zalo_personal_webhook_secret") or "").strip()
    if not s:
        s = secrets.token_urlsafe(24)
        try:
            config.update({"zalo_personal_webhook_secret": s})
        except Exception:
            pass
    return s


def _webhook_base() -> str:
    """Base URL mà BOT SERVER gọi ngược về gateway. zalo-server nhúng cùng
    container nên mặc định 127.0.0.1:80 (cổng nội bộ của gateway). Ưu tiên cấu
    hình riêng, rồi base_url chung, cuối cùng localhost nội bộ."""
    c = _cfg()
    return (str(c.get("zalo_personal_webhook_base") or "").strip()
            or str(c.get("base_url") or "").strip()
            or "http://127.0.0.1:80").rstrip("/")


def _public_base() -> str:
    """Base URL công khai để phục vụ link file (docx, ảnh)."""
    c = _cfg()
    return (str(c.get("base_url") or "").strip()
            or _webhook_base()).rstrip("/")


# ── HTTP client tới bot server (cookie session, tự re-login khi 401) ──────────

_http_lock = threading.Lock()
_client: httpx.Client | None = None
_client_server = ""
_logged_in_at = 0.0
_SESSION_TTL = 25 * 60  # bot server session 30 ngày nhưng re-login nhẹ mỗi 25'


def _get_client() -> httpx.Client | None:
    global _client, _client_server
    url = _server_url()
    if not url:
        return None
    with _http_lock:
        if _client is None or _client_server != url:
            try:
                if _client is not None:
                    _client.close()
            except Exception:
                pass
            _client = httpx.Client(base_url=url, timeout=httpx.Timeout(
                connect=5.0, read=30.0, write=30.0, pool=5.0))
            _client_server = url
        return _client


def _login(client: httpx.Client) -> bool:
    global _logged_in_at
    user, pw = _credentials()
    try:
        r = client.post("/api/login", json={"username": user, "password": pw})
        ok = r.status_code == 200 and bool((r.json() or {}).get("success"))
        if ok:
            _logged_in_at = time.time()
        else:
            logger.warning("Zalo personal: đăng nhập bot server thất bại (%s)", r.status_code)
        return ok
    except Exception as exc:
        logger.warning("Zalo personal: không kết nối được bot server: %s", exc)
        return False


def _request(method: str, path: str, body: dict | None = None,
             timeout: float | None = None, headers: dict | None = None) -> dict:
    """Gọi bot server; response chuẩn hóa {ok, data|error}. 401 → login lại 1 lần."""
    client = _get_client()
    if client is None:
        return {"ok": False, "error": "Chưa cấu hình zalo_personal_server_url"}
    try:
        if time.time() - _logged_in_at > _SESSION_TTL:
            _login(client)
        kw: dict[str, Any] = {}
        if body is not None:
            kw["json"] = body
        if timeout is not None:
            kw["timeout"] = timeout
        if headers:
            kw["headers"] = headers
        r = client.request(method, path, **kw)
        if r.status_code == 401:
            if not _login(client):
                return {"ok": False, "error": "Đăng nhập bot server thất bại"}
            r = client.request(method, path, **kw)
        if r.status_code >= 400:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        try:
            data = r.json()
        except Exception:
            data = r.text
        if isinstance(data, dict) and (data.get("success") is False or data.get("ok") is False):
            return {"ok": False, "error": str(data.get("error") or data.get("message") or "Bot server báo lỗi")}
        return {"ok": True, "data": data}
    except Exception as exc:
        return {"ok": False, "error": f"Lỗi kết nối bot server: {exc}"}


# ── API bot server: tài khoản / QR / webhook / proxy ─────────────────────────

def get_accounts() -> dict:
    """GET /api/accounts → {ok, accounts:[{ownId, phoneNumber, displayName, isOnline, proxy}]}"""
    r = _request("GET", "/api/accounts")
    if not r.get("ok"):
        return {"ok": False, "accounts": [], "error": r.get("error")}
    d = r.get("data")
    accounts = d if isinstance(d, list) else ((d or {}).get("data") or (d or {}).get("accounts") or [])
    return {"ok": True, "accounts": accounts}


def login_qr(proxy: str = "") -> dict:
    """POST /zalo-login → {ok, qr: dataURI}. Chờ tới 70s (server đợi tạo QR)."""
    body = {"proxy": proxy} if proxy else {}
    r = _request("POST", "/zalo-login", body, timeout=70.0)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    d = r.get("data") or {}
    qr = d.get("qrCodeImage") or d.get("qrCode") or d.get("image") or ""
    if isinstance(d.get("data"), dict):
        qr = qr or d["data"].get("qrCodeImage") or d["data"].get("image") or ""
    if not qr:
        return {"ok": False, "error": "Bot server không trả về mã QR"}
    if not str(qr).startswith("data:image"):
        qr = "data:image/png;base64," + str(qr)
    return {"ok": True, "qr": qr}


def get_webhooks() -> dict:
    return _request("GET", "/api/account-webhooks")


def set_account_webhook(own_id: str, message_url: str, group_url: str = "",
                        reaction_url: str = "") -> dict:
    return _request("POST", "/api/account-webhook", {
        "ownId": own_id,
        "messageWebhookUrl": message_url,
        "groupEventWebhookUrl": group_url or message_url,
        "reactionWebhookUrl": reaction_url or message_url,
    })


def delete_account_webhook(own_id: str) -> dict:
    return _request("DELETE", f"/api/account-webhook/{own_id}")


# Proxy nằm ở /proxies (router ui, KHÔNG có /api/); GET phải kèm
# Accept: application/json kẻo server render trang HTML.
def get_proxies() -> dict:
    return _request("GET", "/proxies", headers={"Accept": "application/json"})


def add_proxy(proxy_url: str) -> dict:
    return _request("POST", "/proxies", {"proxyUrl": proxy_url},
                    headers={"Accept": "application/json"})


def remove_proxy(proxy_url: str) -> dict:
    return _request("DELETE", "/proxies", {"proxyUrl": proxy_url},
                    headers={"Accept": "application/json"})


def proxy_raw(method: str, path: str, body: dict | None = None, timeout: float = 30.0) -> dict:
    """Passthrough cho trang quản lý web — gọi endpoint bất kỳ của bot server
    (vd getAllFriendsByAccount) mà không phải viết lại từng hàm."""
    if not path.startswith("/"):
        path = "/" + path
    return _request(method.upper(), path, body, timeout=timeout)


def _receiver_url(event: str) -> str:
    base = _webhook_base()
    if not base:
        return ""
    return f"{base}/zalo-personal/webhook?secret={webhook_secret()}&event={event}"


def ensure_webhooks(force: bool = False) -> dict:
    """Tự đăng ký webhook của MỌI tài khoản đã login về gateway (idempotent).
    Chỉ chạy khi bật kênh + bật auto (mặc định). Trả {ok, updated:[ownId]}."""
    c = _cfg()
    if not enabled():
        return {"ok": False, "error": "Kênh Zalo Cá Nhân đang tắt"}
    if not force and not _bool(c, "zalo_personal_auto_webhook", True):
        return {"ok": True, "updated": [], "skipped": "auto_webhook tắt"}
    msg_url = _receiver_url("message")
    if not msg_url:
        return {"ok": False, "error": "Chưa cấu hình zalo_personal_webhook_base/base_url"}
    grp_url = _receiver_url("group_event")
    react_url = _receiver_url("reaction")
    acc = get_accounts()
    if not acc.get("ok"):
        return {"ok": False, "error": acc.get("error")}
    current = get_webhooks()
    cur_map: dict = {}
    if current.get("ok"):
        d = current.get("data") or {}
        cur_map = d.get("accounts") if isinstance(d, dict) and isinstance(d.get("accounts"), dict) else (d if isinstance(d, dict) else {})
    updated = []
    for a in acc.get("accounts") or []:
        own_id = str(a.get("ownId") or "").strip()
        if not own_id:
            continue
        cur = cur_map.get(own_id) or {}
        if (str(cur.get("messageWebhookUrl") or "") == msg_url
                and str(cur.get("groupEventWebhookUrl") or "") == grp_url
                and str(cur.get("reactionWebhookUrl") or "") == react_url):
            continue
        r = set_account_webhook(own_id, msg_url, grp_url, react_url)
        if r.get("ok"):
            updated.append(own_id)
        else:
            logger.warning("Zalo personal: đặt webhook cho %s lỗi: %s", own_id, r.get("error"))
    if updated:
        logger.info("Zalo personal: đã đăng ký webhook cho %s", updated)
    return {"ok": True, "updated": updated}


def get_status() -> dict:
    c = _cfg()
    st: dict[str, Any] = {
        "enabled": enabled(),
        "server_url": _server_url(),
        "reachable": False,
        "accounts": [],
        "ai_enabled": _bool(c, "zalo_personal_ai_enabled", True),
        "ai_model": _ai_model(),
        "chat_ids": _chat_ids(),
        "auto_webhook": _bool(c, "zalo_personal_auto_webhook", True),
        "webhook_receiver": _receiver_url("message"),
        "ha_enabled": _bool(c, "zalo_personal_ha_enabled", False),
        "ha_url": str(c.get("zalo_personal_ha_url") or "").strip(),
        "forward_webhooks": _forward_destinations(),
        # 🔔/📋/💬 theo từng Admin #N — không còn cờ kênh zalo_personal_notify_enabled
        "admin_thread": str(c.get("zalo_personal_admin_thread") or "").strip(),
    }
    if not st["server_url"]:
        return st
    acc = get_accounts()
    st["reachable"] = bool(acc.get("ok"))
    st["accounts"] = acc.get("accounts") or []
    if not acc.get("ok"):
        st["error"] = acc.get("error")
    return st


# ── Gửi tin ───────────────────────────────────────────────────────────────────

def _account_for_send(account: str = "") -> str:
    acc = (account or _default_account()).strip()
    if acc:
        return acc
    accounts = get_accounts().get("accounts") or []
    return str(accounts[0].get("ownId")) if accounts else ""


def _profile_display_name(p: dict) -> str:
    """Tên hiển thị khi nhận diện thread.

    zca-js:
      - zaloName  = tên Zalo thật (vd ``Nguyễn Việt``)
      - displayName = biệt danh local trong danh bạ acc (vd ``BotNhatoi``)
    Ưu tiên tên Zalo thật — biệt danh local dễ gây hiểu nhầm khi Nhận diện.
    """
    if not isinstance(p, dict):
        return ""
    return str(
        p.get("zaloName") or p.get("zalo_name")
        or p.get("displayName") or p.get("display_name")
        or p.get("username") or p.get("name") or ""
    ).strip()


def _extract_user_name(info: dict, want_id: str, *, skip_ids: set[str] | None = None) -> str:
    """Lấy tên ĐÚNG user want_id từ response getUserInfo.

    zca-js hay trả changed_profiles gồm cả bạn bè + chính acc đăng nhập.
    Bug cũ: lấy profile đầu tiên → nhầm tên bot (vd BotNhatoi) thay vì
    người gửi (vd Nguyễn Việt).
    """
    if not isinstance(info, dict):
        return ""
    want = str(want_id or "").strip()
    skip = {str(x).strip() for x in (skip_ids or set()) if str(x).strip()}

    profiles: dict = {}
    for key in ("changed_profiles", "unchanged_profiles", "profiles"):
        raw = info.get(key)
        if isinstance(raw, dict):
            profiles.update(raw)
    nested = info.get("data")
    if isinstance(nested, dict):
        for key in ("changed_profiles", "unchanged_profiles", "profiles"):
            raw = nested.get(key)
            if isinstance(raw, dict):
                profiles.update(raw)

    def _pid_match(pid: str) -> bool:
        p = str(pid or "").strip()
        return bool(want) and (p == want or want in p or p in want)

    # 1) Ưu tiên profile khớp Thread/User ID
    if want and profiles:
        for pid, p in profiles.items():
            if _pid_match(str(pid)):
                n = _profile_display_name(p if isinstance(p, dict) else {})
                if n:
                    return n

    # 2) Chỉ 1 profile và không phải acc của mình
    others = [
        (str(pid), p) for pid, p in profiles.items()
        if str(pid).strip() not in skip
    ]
    if len(others) == 1:
        n = _profile_display_name(others[0][1] if isinstance(others[0][1], dict) else {})
        if n:
            return n

    # 3) Flat fields — chỉ khi không có map (tránh nhặt tên acc)
    if not profiles:
        return str(
            info.get("displayName") or info.get("zaloName")
            or info.get("name") or ""
        ).strip()
    return ""


def _extract_group_name(info: dict, want_id: str = "") -> str:
    if not isinstance(info, dict):
        return ""
    want = str(want_id or "").strip()
    gmap = info.get("gridInfoMap")
    if not isinstance(gmap, dict) and isinstance(info.get("data"), dict):
        gmap = info["data"].get("gridInfoMap")
    if isinstance(gmap, dict):
        if want:
            for gid, g in gmap.items():
                if str(gid) == want or want in str(gid):
                    if isinstance(g, dict):
                        n = str(g.get("name") or g.get("groupName") or g.get("title") or "").strip()
                        if n:
                            return n
        for _gid, g in gmap.items():
            if isinstance(g, dict):
                n = str(g.get("name") or g.get("groupName") or g.get("title") or "").strip()
                if n:
                    return n
    return str(info.get("name") or "").strip()


def resolve_thread(
    account: str = "",
    thread_id: str = "",
    prefer_kind: str = "",
) -> dict:
    """Nhận diện thread qua zca-js getUserInfo / getGroupInfo.

    Trả {ok, chat_id, name, kind: private|group}.
    """
    from services.admin_workspace import guess_chat_kind
    tid = str(thread_id or "").strip()
    acc = _account_for_send(account)
    kind = "group" if prefer_kind in {"group", "1"} else (
        "private" if prefer_kind in {"private", "0", "user"} else guess_chat_kind(tid)
    )
    name = ""
    ok = False
    if not tid or not acc:
        return {"ok": False, "chat_id": tid, "name": name, "kind": kind}

    # Thử theo prefer_kind; nếu fail thử chiều kia (zca-js phân user/group)
    order = ["group", "user"] if kind == "group" else ["user", "group"]
    for attempt in order:
        try:
            if attempt == "user":
                r = _request("POST", "/api/getUserInfoByAccount", {
                    "userId": tid, "accountSelection": acc,
                }, timeout=15.0)
                if not r.get("ok"):
                    continue
                # _request bọc: {ok, data: {success, data: zcaResponse}}
                outer = r.get("data") if isinstance(r.get("data"), dict) else {}
                data = outer.get("data") if isinstance(outer.get("data"), dict) else outer
                if not isinstance(data, dict):
                    data = outer if isinstance(outer, dict) else {}
                n = _extract_user_name(data, tid, skip_ids={acc})
                profiles = data.get("changed_profiles") if isinstance(data, dict) else None
                if not isinstance(profiles, dict):
                    profiles = data.get("unchanged_profiles") if isinstance(data, dict) else None
                # Có profile khớp ID, hoặc tên đúng ID → user
                matched = False
                if isinstance(profiles, dict):
                    matched = any(
                        str(pid) == tid or tid in str(pid)
                        for pid in profiles
                    )
                if n or matched:
                    ok = True
                    kind = "private"
                    name = n
                    break
            else:
                r = _request("POST", "/api/getGroupInfoByAccount", {
                    "groupId": tid, "accountSelection": acc,
                }, timeout=15.0)
                if not r.get("ok"):
                    continue
                outer = r.get("data") if isinstance(r.get("data"), dict) else {}
                data = outer.get("data") if isinstance(outer.get("data"), dict) else outer
                if not isinstance(data, dict):
                    continue
                removed = data.get("removedsGroup") or []
                if tid in (removed if isinstance(removed, list) else []):
                    continue
                n = _extract_group_name(data, tid)
                if n or data.get("gridInfoMap"):
                    ok = True
                    kind = "group"
                    name = n
                    break
        except Exception as exc:
            logger.info("zalop resolve %s %s: %s", attempt, tid[:16], exc)
    return {"ok": ok, "chat_id": tid, "name": name, "kind": kind}


def _admin_thread_ids_for_account(account_id: str = "") -> set[str]:
    """Tập Thread ID admin của 1 acc (admin_entries + legacy admin_thread)."""
    c = _cfg()
    acc = str(account_id or "").strip()
    out: set[str] = set()
    raw = c.get("zalo_personal_account_admins")
    if isinstance(raw, dict) and acc:
        entry = raw.get(acc)
        if isinstance(entry, dict):
            entries = entry.get("admin_entries")
            if isinstance(entries, list):
                for e in entries:
                    if isinstance(e, dict):
                        cid = str(e.get("chat_id") or "").strip()
                        if cid:
                            out.add(cid)
                    elif isinstance(e, str) and e.strip():
                        out.add(e.strip())
            th = str(entry.get("admin_thread") or "").strip()
            if th:
                out.add(th)
    # Legacy global
    th = str(c.get("zalo_personal_admin_thread") or "").strip()
    if th:
        out.add(th)
    return out


def _is_admin_thread(account_id: str, thread_id: str) -> bool:
    tid = str(thread_id or "").strip()
    if not tid:
        return False
    return tid in _admin_thread_ids_for_account(account_id)


def send_message(thread_id: str, text: str, thread_type: int = 0, account: str = "",
                 *, rich: bool = True) -> dict:
    """Gửi text (tự cắt khúc ~2000). Styles RTF zca-js (giống Zalo Bot: đậm+màu+cỡ).

    thread_type: 0=user, 1=group.
    rich=True: emphasis + markdown_color/size (per admin_entries acc nếu match).
    """
    acc = _account_for_send(account)
    if not acc:
        return {"ok": False, "error": "Chưa có tài khoản Zalo nào đăng nhập"}
    raw = text or "..."
    # Per-admin color/size từ zalo_personal_account_admins[acc]
    color = "orange"
    size = "normal"
    bot_like: dict = {}
    try:
        from services.config import config as _cfg_mod
        adm_map = (_cfg_mod.get() or {}).get("zalo_personal_account_admins") or {}
        entry = adm_map.get(acc) if isinstance(adm_map, dict) else None
        if isinstance(entry, dict):
            bot_like = entry
            for e in (entry.get("admin_entries") or []):
                if isinstance(e, dict) and str(e.get("chat_id") or "").strip() == str(thread_id):
                    bot_like = {**entry, **e}
                    break
    except Exception:
        pass

    if rich:
        try:
            from services.telegram.emphasis import emphasize_text
            raw = emphasize_text(raw, bot=bot_like if bot_like else None, chat_id=thread_id)
        except Exception:
            pass
        try:
            from services.zalo_bot_format import resolve_zalo_bot_color, resolve_zalo_bot_size
            color = resolve_zalo_bot_color(bot_like or None, str(thread_id)) or "orange"
            size = resolve_zalo_bot_size(bot_like or None, str(thread_id))
        except Exception:
            try:
                from services.zalo_markdown import config_markdown_color
                color = config_markdown_color()
            except Exception:
                color = "orange"

    chunks = [raw[i:i + _MAX_LEN] for i in range(0, len(raw), _MAX_LEN)] or ["..."]
    last: dict = {"ok": False}
    try:
        from services.zalo_markdown import config_markdown_enabled, markdown_to_zalo_message
        md_on = rich and config_markdown_enabled()
    except Exception:
        md_on = rich
        markdown_to_zalo_message = None  # type: ignore

    for ch in chunks[:_MAX_CHUNKS]:
        msg_obj: dict = {"msg": ch, "ttl": 0, "quote": None}
        if md_on and markdown_to_zalo_message is not None:
            try:
                parsed = markdown_to_zalo_message(ch, color=color, size=size)
                msg_obj["msg"] = parsed.get("msg") or ch
                styles = parsed.get("styles") or []
                if styles:
                    msg_obj["styles"] = styles
            except Exception as exc:
                logger.warning("zalo markdown convert fail: %s", exc)
        last = _request("POST", "/api/sendMessageByAccount", {
            "message": msg_obj,
            "threadId": str(thread_id),
            "accountSelection": acc,
            "type": int(thread_type),
        })
        if not last.get("ok"):
            if msg_obj.get("styles"):
                plain = {"msg": ch, "ttl": 0, "quote": None}
                last = _request("POST", "/api/sendMessageByAccount", {
                    "message": plain,
                    "threadId": str(thread_id),
                    "accountSelection": acc,
                    "type": int(thread_type),
                })
            if not last.get("ok"):
                break
    return last


def send_photo(thread_id: str, image_url: str, caption: str = "",
               thread_type: int = 0, account: str = "") -> dict:
    acc = _account_for_send(account)
    if not acc:
        return {"ok": False, "error": "Chưa có tài khoản Zalo nào đăng nhập"}
    return _request("POST", "/api/sendImageByAccount", {
        "imagePath": image_url,
        "threadId": str(thread_id),
        "accountSelection": acc,
        "type": "group" if int(thread_type) == 1 else "user",
        "message": (caption or "")[:1000],
        "ttl": 0,
    }, timeout=60.0)


def send_file(thread_id: str, file_url: str, caption: str = "",
              thread_type: int = 0, account: str = "") -> dict:
    acc = _account_for_send(account)
    if not acc:
        return {"ok": False, "error": "Chưa có tài khoản Zalo nào đăng nhập"}
    return _request("POST", "/api/sendFileByAccount", {
        "fileUrl": file_url,
        "message": (caption or "")[:1000],
        "threadId": str(thread_id),
        "accountSelection": acc,
        "type": "group" if int(thread_type) == 1 else "user",
        "ttl": 0,
    }, timeout=90.0)


def _public_base() -> str:
    c = _cfg()
    return (str(c.get("base_url") or "").strip()
            or str(c.get("telegram_webhook_url") or "").strip()).rstrip("/")


def _media_fetch_candidates(url_or_path: str) -> list[str]:
    """URL zalo-server có thể fetch — ưu tiên http://127.0.0.1/images/… (trong Docker).

    Test thực tế: HTTPS CF đôi khi ``fetch failed``; ``http://127.0.0.1/images/…`` OK.
    """
    u = str(url_or_path or "").strip()
    if not u:
        return []
    out: list[str] = []
    # Absolute filesystem path under images_dir → /images/ relative
    try:
        from pathlib import Path
        p = Path(u)
        if p.is_file():
            img_root = Path(config.images_dir).resolve()
            try:
                rel = p.resolve().relative_to(img_root)
                u = "/images/" + str(rel).replace("\\", "/")
            except Exception:
                pass
    except Exception:
        pass
    path_part = ""
    if "/images/" in u:
        path_part = "/images/" + u.split("/images/", 1)[1].split("?", 1)[0]
    elif u.startswith("/media/voice/"):
        # voice.save_media → /media/voice/… may not be on images static; skip prefer images
        path_part = u.split("?", 1)[0]
    elif u.startswith("/"):
        path_part = u.split("?", 1)[0]

    if path_part:
        out.append("http://127.0.0.1" + path_part)
        out.append("http://127.0.0.1:3030" + path_part)
        base = _public_base()
        if base:
            out.append(base.rstrip("/") + path_part)
    if u.startswith("http://") or u.startswith("https://"):
        if u not in out:
            out.append(u)
    # de-dupe
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _send_photo_robust(thread_id: str, image_url: str, caption: str = "",
                       thread_type: int = 0, account: str = "") -> bool:
    """Gửi ẢNH thật (sendImage) — thử nhiều URL; không dán link text."""
    for u in _media_fetch_candidates(image_url):
        try:
            from services import net_guard as _ng
            if u.startswith("http") and not u.startswith("http://127.0.0.1") and not _ng.is_allowed_egress_url(u):
                continue
        except Exception:
            pass
        r = send_photo(thread_id, u, caption, thread_type, account=account)
        if r.get("ok"):
            return True
    return False


def _send_file_robust(thread_id: str, file_url: str, caption: str = "",
                      thread_type: int = 0, account: str = "") -> bool:
    """Gửi FILE thật (sendFile) — PDF/DOCX/audio; không dán link text."""
    for u in _media_fetch_candidates(file_url):
        r = send_file(thread_id, u, caption, thread_type, account=account)
        if r.get("ok"):
            return True
    return False


def send_typing(thread_id: str, thread_type: int = 0, account: str = "") -> None:
    acc = _account_for_send(account)
    if not acc:
        return
    try:
        _request("POST", "/api/sendTypingEventByAccount", {
            "threadId": str(thread_id), "accountSelection": acc,
            "type": int(thread_type),
        }, timeout=8.0)
    except Exception:
        pass


def _admin_for_account(account_id: str = "") -> tuple[str, int, str]:
    """(thread, type 0|1, account_to_send).

    1) Map zalo_personal_account_admins[ownId] → gửi bằng CHÍNH acc đó.
    2) Admin CHUNG zalo_personal_admin_thread → gửi bằng acc chỉ định
       zalo_personal_admin_send_account (vd acc A). Trống → acc mặc định /
       acc đầu tiên (không dùng acc nhận tin nếu khác acc sở hữu thread admin).
    """
    c = _cfg()
    acc = str(account_id or "").strip()
    raw = c.get("zalo_personal_account_admins")
    if isinstance(raw, dict) and acc:
        entry = raw.get(acc)
        if isinstance(entry, dict):
            th = str(entry.get("admin_thread") or "").strip()
            if th:
                ttype = 1 if str(entry.get("admin_thread_type") or "0").strip() in {
                    "1", "group",
                } else 0
                return th, ttype, acc
    th = str(c.get("zalo_personal_admin_thread") or "").strip()
    ttype = 1 if str(c.get("zalo_personal_admin_thread_type") or "0").strip() in {
        "1", "group",
    } else 0
    send_acc = str(c.get("zalo_personal_admin_send_account") or "").strip()
    if not send_acc:
        send_acc = str(c.get("zalo_personal_account_id") or "").strip() or _default_account()
    return th, ttype, send_acc


def notify_admin(text: str, category: str = "") -> None:
    """account_log 📋 / system 🔔 / newchat 💬 — theo toggle từng Admin #N (zca-js).

    Không còn cờ kênh ``zalo_personal_notify_enabled`` — chỉ Admin #N 🔔/📋/💬.
    """
    c = _cfg()
    if not enabled():
        return
    try:
        from services.notifier import classify_notify_category
        cat = classify_notify_category(text, category)
    except Exception:
        cat = str(category or "system").strip().lower() or "system"
    is_account_log = cat == "account_log"
    is_newchat = cat == "newchat"
    seen: set[str] = set()
    raw = c.get("zalo_personal_account_admins")
    if not isinstance(raw, dict) or not raw:
        # Legacy: 1 admin_thread kênh — luôn gửi nếu còn cấu hình (không gate cờ kênh)
        th, ttype, send_acc = _admin_for_account("")
        if th:
            try:
                send_message(th, text[:_MAX_LEN], ttype, account=send_acc, rich=True)
            except Exception:
                pass
        return
    for own_id, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled") is False:
            continue
        # 🔔 / 📋 / 💬 độc lập — tắt 📋 không còn dính 🔔 và ngược lại
        if is_newchat:
            if entry.get("newchat_alert_enabled") is False:
                continue
        elif is_account_log:
            if entry.get("account_log_enabled") is False:
                continue
        else:
            if entry.get("notify_admin_enabled") is False:
                continue
        entries = entry.get("admin_entries")
        rows: list[dict] = []
        if isinstance(entries, list) and entries:
            for x in entries:
                if isinstance(x, dict) and x.get("chat_id"):
                    rows.append(x)
                elif isinstance(x, str) and x.strip():
                    rows.append({
                        "chat_id": x.strip(), "kind": "private",
                        "notify_enabled": True,
                        "account_log_enabled": True,
                        "newchat_alert_enabled": True,
                    })
        else:
            th = str(entry.get("admin_thread") or "").strip()
            if th:
                rows.append({
                    "chat_id": th,
                    "kind": "group" if str(entry.get("admin_thread_type") or "0") in {"1", "group"} else "private",
                    "notify_enabled": True,
                    "account_log_enabled": True,
                    "newchat_alert_enabled": True,
                })
        sent = 0
        for row in rows:
            if is_newchat:
                if row.get("newchat_alert_enabled") is False:
                    continue
            elif is_account_log:
                # 📋: chỉ gửi khi Admin #N bật — False tuyệt đối không gửi
                if row.get("account_log_enabled") is False:
                    continue
            else:
                if row.get("notify_enabled") is False:
                    continue
            th = str(row.get("chat_id") or "").strip()
            if not th or th in seen:
                continue
            ttype = 1 if str(row.get("kind") or "") in {"group", "1"} else 0
            seen.add(th)
            try:
                r = send_message(
                    th, text[:_MAX_LEN], ttype, account=str(own_id), rich=True,
                )
                if r.get("ok"):
                    sent += 1
            except Exception:
                pass
        if sent == 0 and entry.get("fallback_enabled"):
            try:
                from services.telegram_bot import _try_bot_fallback
                _try_bot_fallback({
                    "fallback_enabled": True,
                    "fallback_channel": entry.get("fallback_channel"),
                    "fallback_bot_name": entry.get("fallback_bot_name"),
                    "fallback_thread": entry.get("fallback_thread"),
                }, text)
            except Exception:
                pass


# ── Nhận webhook: parse payload zca-js ────────────────────────────────────────

_seen_lock = threading.Lock()
_seen_ids: set[str] = set()


def _dedup(msg_id: str) -> bool:
    """True nếu đã thấy msg_id này (bỏ qua)."""
    if not msg_id:
        return False
    with _seen_lock:
        if msg_id in _seen_ids:
            return True
        _seen_ids.add(msg_id)
        if len(_seen_ids) > 4000:
            _seen_ids.clear()
            _seen_ids.add(msg_id)
    return False


def _parse_event(body: dict) -> dict:
    """Chuẩn hóa event zca-js → dict phẳng dùng chung cho AI + HA forward."""
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    is_group = str(body.get("type") or data.get("type") or "0").strip() == "1"
    thread_id = str(body.get("threadId") or data.get("idTo") or data.get("uidFrom") or "").strip()
    sender_id = str(data.get("uidFrom") or "").strip()
    display_name = str(data.get("dName") or data.get("fromD") or "").strip()
    msg_type = str(data.get("msgType") or "webchat").strip()
    content = data.get("content")

    text, attachment_url, file_name = "", "", ""
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, dict):
        href = str(content.get("href") or "").strip()
        thumb = str(content.get("thumb") or "").strip()
        title = str(content.get("title") or "").strip()
        desc = str(content.get("description") or "").strip()
        if msg_type == "chat.photo":
            attachment_url = href or thumb
            text = desc or title
        elif msg_type == "share.file":
            attachment_url = href
            file_name = title or "file"
        elif msg_type in {"chat.video", "chat.video.msg", "chat.voice", "chat.sticker"}:
            attachment_url = href
            text = title or desc
        else:
            text = str(content.get("msg") or title or desc or "").strip()
            attachment_url = href

    # Mentions native zca-js: [{uid, pos, len, ...}] — tag @tên bot trong nhóm
    mentions_raw = data.get("mentions") if data.get("mentions") is not None else body.get("mentions")
    mentions: list = []
    if isinstance(mentions_raw, str):
        try:
            mentions_raw = json.loads(mentions_raw)
        except Exception:
            mentions_raw = []
    if isinstance(mentions_raw, list):
        mentions = [x for x in mentions_raw if isinstance(x, dict)]

    return {
        "account_id": str(body.get("_accountId") or "").strip(),
        "thread_id": thread_id,
        "thread_type": 1 if is_group else 0,
        "is_self": bool(body.get("isSelf")),
        "sender_id": sender_id,
        "display_name": display_name,
        "msg_id": str(data.get("msgId") or data.get("cliMsgId") or "").strip(),
        "msg_type": msg_type,
        "text": text,
        "attachment_url": attachment_url,
        "file_name": file_name,
        "ts": str(data.get("ts") or "").strip(),
        "ttl": data.get("ttl"),
        "mentions": mentions,
    }


def _bot_account_aliases(account_id: str) -> list[str]:
    """Tên/SĐT có thể xuất hiện khi user gõ @bot trong text (không chỉ native mention)."""
    acc = str(account_id or "").strip()
    out: list[str] = []
    if not acc:
        return out
    try:
        for a in list_accounts():
            if str(a.get("ownId") or "").strip() != acc:
                continue
            for k in ("displayName", "display_name", "phoneNumber", "phone", "name"):
                v = str(a.get(k) or "").strip()
                if v and v not in out:
                    out.append(v)
            break
    except Exception:
        pass
    # ownId luôn so được trong mentions; thêm vào text match hiếm khi
    if acc not in out:
        out.append(acc)
    return out


def is_bot_tagged(ev: dict, keyword: str = "") -> bool:
    """Tin có tag bot không? (nhóm + bắt buộc tag)

    Đủ 1 trong các điều kiện:
      1. Từ khóa tag (settings) xuất hiện trong text
      2. Mention native zca-js: mentions[].uid == ownId tài khoản nhận tin
      3. Text chứa @alias bot (displayName / SĐT) — fallback khi platform
         không gửi mảng mentions

    Trước đây: required=True + keyword rỗng → LUÔN im lặng (bug).
    """
    text = str((ev or {}).get("text") or "")
    text_l = text.lower()
    kw = str(keyword or "").strip()
    if kw and kw.lower() in text_l:
        return True

    own = str((ev or {}).get("account_id") or "").strip()
    mts = (ev or {}).get("mentions")
    if own and isinstance(mts, list):
        for x in mts:
            if isinstance(x, dict) and str(x.get("uid") or "").strip() == own:
                return True

    # Fallback text: @Botmitbap / @Ben Bắp …
    if "@" in text:
        for alias in _bot_account_aliases(own):
            al = alias.strip()
            if not al:
                continue
            # so khớp không dấu cách / không phân biệt hoa thường
            compact_al = re.sub(r"\s+", "", al).lower()
            compact_tx = re.sub(r"\s+", "", text).lower()
            if compact_al and (f"@{compact_al}" in compact_tx or compact_al in compact_tx):
                # chỉ tin khi có @ gần alias (tránh match số phone trôi nổi)
                if f"@{compact_al}" in compact_tx or f"@{al.lower()}" in text_l:
                    return True
    return False


# ── Chuyển tiếp webhook (HA / n8n / bất kỳ URL) ────────────────────────────────
#
# Config mới: zalo_personal_forward_webhooks = [
#   { id, enabled, url, label, filters: [{thread_id, kind, user_ids}] }
# ]
# filters rỗng = chuyển TẤT CẢ thread.
# Thread nhóm (kind=group): user_ids rỗng = mọi người; có list = chỉ user đó.
#
# Legacy (vẫn đọc):
#   zalo_personal_ha_enabled + zalo_personal_ha_url + zalo_personal_ha_filters
#   / zalo_personal_ha_threads

def _ha_threads() -> list[str]:
    v = _cfg().get("zalo_personal_ha_threads")
    if isinstance(v, str):
        v = [s.strip() for s in re.split(r"[,\n]+", v) if s.strip()]
    return [str(x).strip() for x in (v or []) if str(x).strip()]


def _normalize_filters(raw: object) -> list[dict]:
    """Chuẩn hóa list filter → [{thread_id, kind, user_ids}]."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        tid = str(it.get("thread_id") or "").strip()
        if not tid:
            continue
        kind = "user" if str(it.get("kind") or "").strip().lower() == "user" else "group"
        uids = [
            str(u).strip()
            for u in (it.get("user_ids") or [])
            if str(u).strip()
        ]
        out.append({"thread_id": tid, "kind": kind, "user_ids": uids if kind == "group" else []})
    return out


def _ha_filters() -> list[dict] | None:
    """Legacy: None = chưa có khóa filters (fallback ha_threads); list (kể cả []) = dùng filters."""
    v = _cfg().get("zalo_personal_ha_filters")
    if not isinstance(v, list):
        return None
    return _normalize_filters(v)


def _forward_destinations() -> list[dict]:
    """Danh sách đích chuyển tiếp (webhook URL bất kỳ).

    Ưu tiên `zalo_personal_forward_webhooks`. Nếu trống, migrate legacy HA
    (ha_enabled + ha_url + filters/threads) thành 1 đích ảo.
    """
    c = _cfg()
    raw = c.get("zalo_personal_forward_webhooks")
    dests: list[dict] = []
    if isinstance(raw, list):
        for i, it in enumerate(raw):
            if not isinstance(it, dict):
                continue
            url = str(it.get("url") or "").strip()
            if not url:
                continue
            dests.append({
                "id": str(it.get("id") or f"wh-{i}"),
                "enabled": bool(it.get("enabled", True)),
                "url": url,
                "label": str(it.get("label") or "").strip(),
                "filters": _normalize_filters(it.get("filters")),
            })
    if dests:
        return dests

    # Legacy single HA webhook
    url = str(c.get("zalo_personal_ha_url") or "").strip()
    if not url:
        return []
    flt = _ha_filters()
    if flt is None:
        # Fallback ha_threads → filters group không user limit
        flt = [{"thread_id": t, "kind": "group", "user_ids": []} for t in _ha_threads()]
    return [{
        "id": "legacy-ha",
        "enabled": _bool(c, "zalo_personal_ha_enabled", False),
        "url": url,
        "label": "Home Assistant (legacy)",
        "filters": flt,
    }]


def _event_matches_filters(ev: dict, filters: list[dict]) -> bool:
    """filters rỗng = ALL. Có list = thread phải khớp; nhóm + user_ids → lọc sender."""
    if not filters:
        return True
    tid = str(ev.get("thread_id") or "")
    entry = next((f for f in filters if f.get("thread_id") == tid), None)
    if entry is None:
        return False
    # Cá nhân: chỉ cần khớp thread. Nhóm: user_ids rỗng = mọi người.
    if entry.get("kind") == "user":
        return True
    uids = entry.get("user_ids") or []
    if not uids:
        return True
    return str(ev.get("sender_id") or "") in uids


def _zca_js_payload(body: dict, ev: dict) -> dict:
    """Payload zca-js gốc (+ bổ sung field thiếu) cho blueprint HA / consumer khác."""
    payload = dict(body) if isinstance(body, dict) else {}
    if not payload.get("threadId") and ev.get("thread_id"):
        payload["threadId"] = ev.get("thread_id")
    if payload.get("type") is None and ev.get("thread_type") is not None:
        payload["type"] = str(ev.get("thread_type"))
    data = payload.get("data") if isinstance(payload.get("data"), dict) else None
    if data is not None and not data.get("uidFrom") and ev.get("sender_id"):
        data = dict(data)
        data["uidFrom"] = ev.get("sender_id")
        payload["data"] = data
    return payload


def _post_webhook(url: str, payload: dict, label: str, ev: dict, event_name: str) -> None:
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            logger.info(
                "Zalo personal → webhook OK label=%s status=%s thread=%s sender=%s event=%s",
                label or url[:48],
                getattr(resp, "status", "?"),
                ev.get("thread_id"),
                ev.get("sender_id"),
                event_name,
            )
    except Exception as exc:
        logger.warning(
            "Zalo personal → webhook lỗi label=%s: %s",
            label or url[:48], exc,
        )


def forward_to_ha(body: dict, ev: dict, event_name: str) -> None:
    """POST event Zalo tới MỌI webhook đã bật (HA / n8n / URL bất kỳ) — fire-and-forget.

    Blueprint `luuquangvu/zalo_custom_bot_webhook` đọc payload **zca-js gốc**
    (threadId, data.uidFrom, data.content, …).
    """
    dests = [d for d in _forward_destinations() if d.get("enabled") and d.get("url")]
    if not dests:
        return

    payload = _zca_js_payload(body, ev)
    for dest in dests:
        if not _event_matches_filters(ev, dest.get("filters") or []):
            logger.debug(
                "Zalo personal → webhook skip label=%s thread=%s sender=%s",
                dest.get("label") or dest.get("id"),
                ev.get("thread_id"),
                ev.get("sender_id"),
            )
            continue
        url = str(dest["url"])
        label = str(dest.get("label") or dest.get("id") or "")
        threading.Thread(
            target=_post_webhook,
            args=(url, payload, label, ev, event_name),
            daemon=True,
        ).start()


def test_ha_forward(url: str = "", filters: list | None = None) -> dict:
    """Gửi payload test tới 1 webhook (nút Test trên UI).

    url trống → lấy webhook enabled đầu tiên. filters (nếu truyền) hoặc filters
    của đích đó dùng để chọn threadId/uidFrom mẫu cho blueprint HA.
    """
    c = _cfg()
    dests = _forward_destinations()
    target = (url or "").strip()
    flt: list[dict] = _normalize_filters(filters) if filters is not None else []
    if not target:
        for d in dests:
            if d.get("enabled") and d.get("url"):
                target = str(d["url"])
                if not flt:
                    flt = list(d.get("filters") or [])
                break
    if not target:
        return {"ok": False, "error": "Chưa cấu hình URL webhook"}

    thread_id = ""
    sender_id = ""
    if flt:
        thread_id = str(flt[0].get("thread_id") or "").strip()
        uids = flt[0].get("user_ids") or []
        sender_id = str(uids[0]).strip() if uids else ""
    if not thread_id:
        threads = _ha_threads()
        thread_id = threads[0] if threads else str(c.get("zalo_personal_admin_thread") or "0")
    if not sender_id:
        sender_id = str(c.get("zalo_personal_admin_thread") or "0")

    payload = {
        "threadId": thread_id,
        "type": "1",
        "isSelf": False,
        "_accountId": str(c.get("zalo_personal_account_id") or "test"),
        "data": {
            "uidFrom": sender_id,
            "dName": "chatgpt2api-test",
            "msgType": "webchat",
            "content": "Test chuyển tiếp Zalo Cá Nhân → webhook",
            "msgId": f"test-{int(time.time())}",
            "cliMsgId": f"test-{int(time.time())}",
        },
    }
    try:
        req = urllib.request.Request(
            target,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=8)
        return {
            "ok": True,
            "status": resp.status,
            "url": target,
            "note": "Đã POST payload zca-js. Kiểm tra consumer (vd automation HA last_triggered).",
            "threadId": thread_id,
            "uidFrom": sender_id,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "url": target}


# ── Báo admin thread MỚI (để lấy thread ID cấp phép) ──────────────────────────

_new_thread_seen: set[str] = set()


def _account_phone_name(acc_id: str) -> tuple[str, str, str]:
    """(label, phone, ownId) cho acc Zalo CN — label ưu tiên SĐT/tên, không bare id."""
    acc = str(acc_id or "").strip()
    phone = ""
    dname = ""
    try:
        for a in (get_accounts().get("accounts") or []):
            if str(a.get("ownId") or "").strip() != acc:
                continue
            phone = str(a.get("phoneNumber") or "").strip()
            dname = str(a.get("displayName") or "").strip()
            dname = re.sub(r"\s*\(\d{8,}\)\s*$", "", dname).strip()
            break
    except Exception:
        pass
    try:
        from services.channel_contacts import bot_label as _bl
        label = _bl("zalop", acc) if acc else ""
    except Exception:
        label = ""
    if not label or label == acc:
        label = phone or dname or acc
    return label, phone, acc


def _alert_new_thread(ev: dict) -> None:
    """Báo thread lạ + hỏi admin có lưu danh bạ không (consent)."""
    acc_id = str(ev.get("account_id") or "").strip()
    src_thread = str(ev.get("thread_id") or "").strip()
    # Đã là Admin #N của acc → không báo "thread mới"
    if src_thread and _is_admin_thread(acc_id, src_thread):
        return
    key = f"{acc_id}:{src_thread}"
    if key in _new_thread_seen:
        return
    _new_thread_seen.add(key)
    if len(_new_thread_seen) > 500:
        _new_thread_seen.clear()
    c = _cfg()
    if not _bool(c, "zalo_personal_newchat_alert_enabled", True):
        return
    is_group = int(ev.get("thread_type") or 0) == 1
    user_id = str(ev.get("sender_id") or "").strip()
    user_name = str(ev.get("display_name") or "").strip()
    group_name = str(ev.get("chat_name") or ev.get("group_name") or "").strip()

    # Bổ sung tên nhóm / user qua zca-js
    if acc_id and src_thread:
        try:
            if is_group and not group_name:
                info = resolve_thread(acc_id, src_thread, "group")
                if info.get("ok") and info.get("name"):
                    group_name = str(info.get("name") or "").strip()
            if not is_group and not user_name:
                info = resolve_thread(acc_id, src_thread, "private")
                if info.get("ok") and info.get("name"):
                    user_name = str(info.get("name") or "").strip()
            elif is_group and user_id and not user_name:
                info = resolve_thread(acc_id, user_id, "private")
                if info.get("ok") and info.get("name"):
                    user_name = str(info.get("name") or "").strip()
        except Exception:
            pass

    acc_label, acc_phone, _ = _account_phone_name(acc_id)
    text_snip = str(ev.get("text") or ev.get("msg_type") or "")[:120]

    try:
        from services import channel_contacts as _cc
        from services.admin_workspace import start_save_prompt
        ok, rec = _cc.should_alert_new(
            "zalop", acc_id, src_thread,
            user_id=user_id, is_group=is_group, tagged=False,
            display_name=user_name, chat_name=group_name, text=text_snip,
        )
        if not ok:
            return
        # Làm giàu rec trước khi format
        rec = dict(rec)
        rec["bot_label"] = acc_label
        if group_name:
            rec["chat_name"] = group_name
        if user_name:
            rec["display_name"] = user_name
        if acc_phone and not rec.get("bot_label"):
            rec["bot_label"] = acc_phone
        base = _cc.format_alert(rec, served=False, text=text_snip)
        if acc_phone and acc_phone not in base:
            base = base.replace(
                f"bot **{acc_label}**",
                f"bot **{acc_label}** · SĐT `{acc_phone}`",
                1,
            )

        # Gửi từng Admin #N (💬) kèm hỏi lưu danh bạ
        raw = c.get("zalo_personal_account_admins")
        sent = 0
        if isinstance(raw, dict):
            for own_id, entry in raw.items():
                if not isinstance(entry, dict) or entry.get("enabled") is False:
                    continue
                if entry.get("newchat_alert_enabled") is False:
                    continue
                rows: list[dict] = []
                entries = entry.get("admin_entries")
                if isinstance(entries, list) and entries:
                    for x in entries:
                        if isinstance(x, dict) and x.get("chat_id"):
                            rows.append(x)
                else:
                    th = str(entry.get("admin_thread") or "").strip()
                    if th:
                        rows.append({
                            "chat_id": th,
                            "kind": "group" if str(entry.get("admin_thread_type") or "0")
                            in {"1", "group"} else "private",
                            "newchat_alert_enabled": True,
                        })
                for row in rows:
                    if row.get("newchat_alert_enabled") is False:
                        continue
                    aid = str(row.get("chat_id") or "").strip()
                    if not aid or aid == src_thread:
                        continue
                    ttype = 1 if str(row.get("kind") or "") in {"group", "1"} else 0
                    prompt = start_save_prompt("zalop", aid, rec)
                    msg = base + prompt
                    try:
                        r = send_message(aid, msg[:_MAX_LEN], ttype, account=str(own_id), rich=True)
                        if r.get("ok"):
                            sent += 1
                    except Exception:
                        pass
        if sent:
            _cc.mark_notified(str(rec.get("key") or ""))
        else:
            # Không gửi được admin thread → fallback đa kênh (không auto-lưu)
            try:
                notify_admin(
                    base + "\n→ Trả lời admin trên kênh khác hoặc thêm Admin #N / Lọc thread.",
                    category="newchat",
                )
            except Exception:
                pass
    except Exception as exc:
        logger.warning("zalop new-thread alert: %s", exc)


# ── Xử lý AI (chung orchestrator với Telegram/Zalo Bot) ───────────────────────

def _download(url: str) -> bytes | None:
    # attachment_url đến TỪ webhook (không tin cậy) → chặn SSRF: cấm IP nội bộ,
    # chỉ http/https, có trần dung lượng. Xem services/net_guard.
    try:
        from services import net_guard
        return net_guard.safe_fetch(url, timeout=30)
    except Exception as exc:
        logger.warning("Zalo personal download lỗi: %s", exc)
        return None


def _serve_docx(thread_id: str, thread_type: int, docx_path: str, how: str) -> None:
    """Gửi file Word: ưu tiên gửi FILE THẬT qua bot server (sendFileByAccount cần
    URL công khai) — fallback nhắn link tải."""
    import uuid
    out_dir = config.images_dir / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    fn = f"{uuid.uuid4().hex}.docx"
    with open(docx_path, "rb") as f:
        (out_dir / fn).write_bytes(f.read())
    # Gửi FILE .docx thật (sendFile); không dán link trừ khi mọi URL fail.
    rel = f"/images/docs/{fn}"
    if _send_file_robust(thread_id, rel, f"Bản Word ({how})", thread_type):
        return
    base = _public_base()
    link = f"{base}{rel}" if base else rel
    send_message(
        thread_id,
        f"📝 Em đã chuyển Word nhưng gửi file chưa được. Thử lại giúp em nhé.",
        thread_type,
    )
    logger.warning("zalop Word sendFile fail path=%s", link)


def _do_pdf_intent(
    thread_id: str,
    thread_type: int,
    pending: dict | None,
    intent: str,
    *,
    grade: int | None = None,
    subject: str | None = None,
    account: str = "",
    user_id: str = "",
) -> None:
    if not pending:
        return
    import os
    import time as _time
    from services import pdf_intent as _pi
    path = pending["path"]
    name = pending.get("name") or "document.pdf"
    t0 = _time.time()
    kind = "pdf_rag"
    reply = ""
    status = "ok"
    err = ""
    send_typing(thread_id, thread_type)
    temps: list[str] = [path]
    try:
        if intent == _pi.WORD:
            kind = "pdf_word"
            docx_tmp = (path[:-4] if path.endswith(".pdf") else path) + ".docx"
            temps.append(docx_tmp)
            from services.pdf_to_word import convert_pdf_to_docx
            r = convert_pdf_to_docx(path, docx_tmp)
            if not r.get("ok"):
                status = "error"
                err = str(r.get("error") or "")[:150]
                reply = f"⚠️ Không chuyển được sang Word: {err}"
                send_message(thread_id, reply, thread_type)
                return
            how = "giữ layout" if r.get("method") == "layout" else "OCR (PDF scan)"
            reply = f"📝 Bản Word ({how})"
            _serve_docx(thread_id, thread_type, docx_tmp, how)
        elif intent == _pi.EXCEL:
            kind = "pdf_excel"
            xlsx_tmp = (path[:-4] if path.endswith(".pdf") else path) + ".xlsx"
            temps.append(xlsx_tmp)
            from services.pdf_to_excel import convert_pdf_to_xlsx
            r = convert_pdf_to_xlsx(path, xlsx_tmp)
            if not r.get("ok"):
                status = "error"
                err = str(r.get("error") or "")[:150]
                reply = f"⚠️ Không chuyển được sang Excel: {err}"
                send_message(thread_id, reply, thread_type)
                return
            # serve via images/docs like word
            import shutil
            import uuid
            out_dir = config.images_dir / "docs"
            out_dir.mkdir(parents=True, exist_ok=True)
            fn = f"{uuid.uuid4().hex}.xlsx"
            dest = out_dir / fn
            shutil.copy2(xlsx_tmp, dest)
            rel = f"/images/docs/{fn}"
            pages = r.get("pages_extracted")
            reply = (
                f"📊 Bản Excel ({r.get('method')}, {r.get('sheets')} sheet"
                f"{', ' + str(pages) + ' trang' if pages else ''})"
            )
            if not _send_file_robust(
                thread_id, rel, reply, thread_type, account=account,
            ):
                reply = "📊 Em đã tạo Excel nhưng gửi file chưa được."
                send_message(thread_id, reply, thread_type)
        elif intent == _pi.RAG_TEACHER:
            kind = "pdf_teacher"
            if not grade or not subject:
                reply = "⚠️ Thiếu lớp/môn cho RAG teacher."
                status = "error"
                err = "missing grade/subject"
                send_message(thread_id, reply, thread_type)
                return
            r = _pi.ingest_teacher(path, grade=int(grade), subject=str(subject), name=name)
            reply = r.get("text") or r.get("error") or "Xong."
            send_message(thread_id, reply, thread_type)
        else:
            kind = "pdf_rag"
            r = _pi.ingest_knowledge(
                path, name=name, model=_ai_model(account, thread_id),
                who=user_id or f"zalop_{thread_id}", platform="zalop", chat_id=thread_id,
            )
            parts = []
            if r.get("summary"):
                from services import pdf_images as _pimg
                parts.append(_pimg.humanize_markers(r["summary"]))
            if r.get("text"):
                parts.append(r["text"])
            if not r.get("ok") and r.get("error"):
                parts.append(f"⚠️ {r['error']}")
            if not parts:
                reply = "❌ Không đọc được nội dung PDF (có thể là ảnh chụp)."
                send_message(thread_id, reply, thread_type)
            else:
                reply = "\n\n".join(parts)
                if not r.get("ok") and r.get("error"):
                    status = "error"
                    err = str(r.get("error") or "")[:200]
                send_message(thread_id, reply, thread_type)
                try:
                    from services import pdf_images as _pimg
                    for cap, iid in _pimg.find_markers(r.get("summary") or "")[:4]:
                        p = _pimg.image_path(iid)
                        if p:
                            _send_photo_robust(
                                thread_id, str(p),
                                (cap or "Hình trong tài liệu")[:200],
                                thread_type, account=account,
                            )
                except Exception as exc:
                    logger.warning("zalop gửi ảnh marker PDF lỗi: %s", exc)
    except Exception as e:
        status = "error"
        err = str(e)[:200]
        reply = f"❌ Lỗi xử lý PDF: {e}"
        logger.warning("Zalo personal pdf intent %s lỗi: %s", intent, e)
        send_message(thread_id, reply, thread_type)
    finally:
        _zalop_journal(
            kind=kind, thread_id=thread_id, account=account, user_id=user_id,
            user_text=f"PDF:{name} → {intent}", reply=reply,
            status=status, error=err, t0=t0,
            meta={"file": name, "intent": intent},
        )
        for p in temps:
            try:
                os.unlink(p)
            except Exception:
                pass


def _zalop_journal(
    *,
    kind: str,
    thread_id: str,
    account: str = "",
    user_id: str = "",
    user_text: str = "",
    reply: str = "",
    status: str = "ok",
    error: str = "",
    t0: float = 0,
    meta: dict | None = None,
) -> None:
    try:
        import time as _time
        from services.agent import run_journal as _rj
        _rj.log_channel_event(
            channel="zalop",
            kind=kind,
            user_text=user_text,
            reply_text=str(reply or "")[:800],
            user_id=str(user_id or f"zalop_{account}_{thread_id}"),
            source_account=str(account or ""),
            source_peer=str(thread_id),
            status=status,
            error=error,
            duration_ms=int((_time.time() - t0) * 1000) if t0 else 0,
            meta=meta,
        )
    except Exception:
        pass


def _do_photo_request(
    thread_id: str,
    thread_type: int,
    file_data: bytes,
    request_text: str,
    allow: set | None = None,
    *,
    intent: str | None = None,
    user_id: str = "",
    account: str = "",
) -> None:
    """Xử lý ảnh: rag_knowledge | rag_teacher | analyze | generate (img2img)."""
    import time as _time
    from services import photo_intent as _phi
    t0 = _time.time()
    kind = "photo_analyze"
    reply = ""
    status = "ok"
    err = ""
    send_typing(thread_id, thread_type)
    try:
        it = intent or (
            _phi.GENERATE if _phi.classify(request_text) == _phi.GENERATE else _phi.ANALYZE
        )
        allowed = _phi.allowed_intents(allow)
        if it not in allowed and allow is not None:
            status = "blocked"
            err = f"intent {it} not allowed"
            return

        if it == _phi.GENERATE:
            kind = "photo_generate"
            out = _phi.generate_from_photo(file_data, request_text, channel="zalop")
            try:
                from services import net_guard
                out = net_guard.filter_agent_output(out if isinstance(out, dict) else {})
            except Exception:
                pass
            url = out.get("image_url")
            reply = (out.get("text") or "Đây ạ 🎨")[:1000]
            if url:
                if _send_photo_robust(
                    thread_id, str(url), reply, thread_type,
                    account=account or "",
                ):
                    return
                reply = out.get("text") or "Em tạo được ảnh nhưng gửi chưa được ạ."
                send_message(thread_id, reply, thread_type)
                return
            reply = out.get("text") or "Em chưa tạo được ảnh ạ."
            send_message(thread_id, reply, thread_type)
            return

        if it == _phi.RAG_KNOWLEDGE:
            kind = "photo_rag"
            r = _phi.ingest_knowledge_from_photo(
                file_data, prompt=request_text, who=user_id or thread_id,
                platform="zalop", chat_id=str(thread_id), channel="zalop",
            )
            reply = r.get("text") or r.get("error") or "Xong."
            send_message(thread_id, reply, thread_type)
            return

        if it == _phi.RAG_TEACHER:
            kind = "photo_rag"
            reply = "⚠️ RAG teacher ảnh cần lớp + môn (vd: `5 toán`)."
            send_message(thread_id, reply, thread_type)
            return

        kind = "photo_analyze"
        answer = _phi.analyze_photo(file_data, request_text, channel="zalop")
        reply = answer or ""
        send_message(thread_id, answer, thread_type)
    except Exception as exc:
        status = "error"
        err = str(exc)[:200]
        raise
    finally:
        _zalop_journal(
            kind=kind, thread_id=thread_id, account=account, user_id=user_id,
            user_text=(request_text or "[ảnh]")[:500], reply=reply,
            status=status, error=err, t0=t0,
        )


def _process_ai(ev: dict) -> None:
    """Trả lời AI cho 1 tin — CHỈ thread được cấp phép (an toàn tài khoản cá nhân)."""
    thread_id = str(ev.get("thread_id") or "").strip()
    thread_type = ev["thread_type"]
    text = (ev.get("text") or "").strip()
    acc_id = str(ev.get("account_id") or "").strip()

    from services.agent import capabilities as _caps
    # Tầng lọc: nhóm (thread_id) ∩ user (sender_id) — User ID theo từng nhóm.
    _sender = str(ev.get("sender_id") or "")
    _allow = _caps.allowed_groups_for_member("zalop", acc_id, thread_id, _sender)
    allowed_ids = list(_chat_ids())
    # Admin #N của acc = luôn được phép (giống Telegram / Zalo Bot)
    _is_admin = _is_admin_thread(acc_id, thread_id)
    if _is_admin and thread_id and thread_id not in allowed_ids:
        allowed_ids.append(thread_id)
    permitted = _is_admin or (_allow is not None) or (thread_id in allowed_ids)
    if not permitted:
        _alert_new_thread(ev)
        return  # im lặng — tài khoản cá nhân không tự trả lời người lạ

    # Admin workspace: trả lời `có`/`không` lưu danh bạ, đặt tên…
    if _is_admin and text:
        try:
            from services.admin_workspace import handle_admin_text
            _ar = handle_admin_text("zalop", thread_id, text)
            if _ar:
                send_message(thread_id, _ar, int(thread_type or 0), account=acc_id, rich=True)
                return
        except Exception as exc:
            logger.warning("zalop admin workspace: %s", exc)

    _low = text.lower()
    # Substring như Zalo Bot — tag bot kèm /id ("@Tên bot /id") vẫn nhận ra lệnh.
    if _low in {"/id", "id", "chatid"} or "/id" in _low or "chatid" in _low \
            or ("thread id" in _low and len(_low) <= 40):
        kind = "nhóm" if thread_type == 1 else "cá nhân"
        is_g = int(thread_type or 0) == 1
        acc_id = str(ev.get("account_id") or "").strip()
        acc_label, acc_phone, acc_own = _account_phone_name(acc_id)
        # Tên thread (nhóm / user)
        thread_name = ""
        try:
            info = resolve_thread(acc_id, thread_id, "group" if is_g else "private")
            if info.get("ok") and info.get("name"):
                thread_name = str(info.get("name") or "").strip()
        except Exception:
            pass
        sender_name = str(ev.get("display_name") or "").strip()
        if is_g and _sender and not sender_name:
            try:
                info = resolve_thread(acc_id, _sender, "private")
                if info.get("ok") and info.get("name"):
                    sender_name = str(info.get("name") or "").strip()
            except Exception:
                pass
        lines = [
            f"🆔 Thread ID: `{thread_id}` ({kind})",
            f"📛 Tên {'nhóm' if is_g else 'user'}: **{thread_name}**" if thread_name else None,
            f"👤 User ID người gửi: `{_sender}`" if _sender else None,
            f"👤 Tên người gửi: **{sender_name}**" if sender_name else None,
            f"🤖 Tài khoản Zalo CN: **{acc_label}**" if acc_label else None,
            f"📞 SĐT: `{acc_phone}`" if acc_phone else None,
            f"🔑 ownId: `{acc_own}`" if acc_own else None,
        ]
        _id_info = "\n".join(x for x in lines if x)
        _admin, _attype, _send_acc = _admin_for_account(acc_id)
        if _admin:
            send_message(
                _admin,
                f"🆔 Yêu cầu /id từ thread {kind}:\n{_id_info}",
                _attype,
                account=_send_acc,
                rich=True,
            )
        else:
            send_message(thread_id, _id_info, thread_type, account=acc_id, rich=True)
        return

    # Bộ lọc TAG (nhóm): native mention / keyword / @alias — chung tag_gate_allows.
    if thread_type == 1 and thread_id:
        _req, _kw = _caps.mention_required_for("zalop", ev.get("account_id") or "", thread_id)
        _native = is_bot_tagged(ev, "")  # mention / @alias (không cần keyword)
        if _req and not _caps.tag_gate_allows(
            required=True,
            keyword=_kw,
            text=text or "",
            native_tagged=_native,
            platform_group_delivery=False,
        ):
            logger.info(
                "zalop skip (cần tag bot): thread=%s acc=%s text=%.80s mentions=%s kw=%r",
                thread_id, ev.get("account_id"), text,
                len(ev.get("mentions") or []), _kw,
            )
            return

    pkey = f"zalop:{ev.get('account_id')}:{thread_id}"

    # PDF chờ: 1 kiến thức / 2 teacher / 3 Word / 4 Excel
    from services import pdf_intent as _pi
    if text and _pi.has_pending(pkey):
        _pend = _pi.get_pending(pkey) or {}
        _acc = str(ev.get("account_id") or "")
        _uid = str(ev.get("sender_id") or "")
        if _pend.get("stage") == "teacher_meta":
            meta = _pi.parse_teacher_meta(text)
            if not meta:
                send_message(thread_id, _pi.ASK_TEACHER, thread_type)
                return
            _do_pdf_intent(
                thread_id, thread_type, _pi.pop_pending(pkey), _pi.RAG_TEACHER,
                grade=meta["grade"], subject=meta["subject"],
                account=_acc, user_id=_uid,
            )
            return
        _allowed_i = _pi.allowed_intents(_allow)
        _intent = _pi.parse_intent(text, _allowed_i)
        if _intent:
            if _intent == "rag":
                _intent = _pi.RAG_KNOWLEDGE
            if _intent not in _allowed_i:
                return
            if _intent == _pi.RAG_TEACHER:
                _pi.update_pending(pkey, stage="teacher_meta", intent=_pi.RAG_TEACHER)
                send_message(thread_id, _pi.ASK_TEACHER, thread_type)
                return
            _do_pdf_intent(
                thread_id, thread_type, _pi.pop_pending(pkey), _intent,
                account=_acc, user_id=_uid,
            )
            return

    # Ảnh chờ: menu 1–4 / hỏi prompt / teacher meta (giống Telegram / Zalo Bot)
    from services import photo_intent as _phi
    _acc = str(ev.get("account_id") or "")
    _uid = str(ev.get("sender_id") or "")
    if text and _phi.has_pending(pkey):
        _pend = _phi.get_pending(pkey) or {}
        _allowed_ph = _phi.allowed_intents(_allow)
        stage = str(_pend.get("stage") or "choose")
        if stage == "teacher_meta":
            meta = _pi.parse_teacher_meta(text)
            if not meta:
                send_message(thread_id, _phi.ASK_TEACHER, thread_type)
                return
            full = _phi.pop_pending_full(pkey)
            if full and full.get("data"):
                r = _phi.ingest_teacher_from_photo(
                    full["data"], grade=meta["grade"], subject=meta["subject"],
                    channel="zalop",
                )
                send_message(
                    thread_id, r.get("text") or r.get("error") or "Xong.", thread_type,
                )
            return
        if stage == "need_prompt":
            intent = str(_pend.get("intent") or _phi.ANALYZE)
            full = _phi.pop_pending_full(pkey)
            if full and full.get("data"):
                _do_photo_request(
                    thread_id, thread_type, full["data"], text.strip(), _allow,
                    intent=intent, user_id=_uid, account=_acc,
                )
            return
        # stage=choose
        intent = _phi.parse_intent(text, _allowed_ph)
        if intent:
            if intent not in _allowed_ph:
                return
            if intent == _phi.RAG_TEACHER:
                _phi.update_pending(pkey, stage="teacher_meta", intent=intent)
                send_message(thread_id, _phi.ASK_TEACHER, thread_type)
                return
            if _phi.needs_prompt(intent, text):
                _phi.update_pending(pkey, stage="need_prompt", intent=intent)
                send_message(
                    thread_id,
                    _phi.ASK_PROMPT_GENERATE if intent == _phi.GENERATE else _phi.ASK_PROMPT_ANALYZE,
                    thread_type,
                )
                return
            full = _phi.pop_pending_full(pkey)
            if full and full.get("data"):
                _do_photo_request(
                    thread_id, thread_type, full["data"], text.strip(), _allow,
                    intent=intent, user_id=_uid, account=_acc,
                )
            return

    # File đính kèm
    if ev.get("msg_type") == "share.file" and ev.get("attachment_url"):
        name = (ev.get("file_name") or "").strip()
        if name.lower().endswith(".pdf") or ".pdf" in str(ev["attachment_url"]).lower():
            intents = _pi.allowed_intents(_allow)
            if not intents:
                return
            send_typing(thread_id, thread_type)
            data = _download(ev["attachment_url"])
            if not data:
                send_message(thread_id, "📄 Không tải được file PDF.", thread_type)
                return
            info = _pi.set_pending(pkey, data, name or "document.pdf")
            send_message(thread_id, _pi.ask_text(name or "PDF", intents, info), thread_type)
            return
        send_message(thread_id, f"📎 Hiện em chỉ hỗ trợ chuyển PDF → Word. File: {name or 'không rõ'}", thread_type)
        return

    # Ảnh: không caption → menu; có caption → parse intent / hỏi prompt nếu cần.
    if ev.get("msg_type") == "chat.photo" and ev.get("attachment_url"):
        send_typing(thread_id, thread_type)
        data = _download(ev["attachment_url"])
        if not data:
            send_message(thread_id, "📷 Không tải được ảnh.", thread_type)
            return
        caption = (text or "").strip()
        _allowed_ph = _phi.allowed_intents(_allow)
        if not caption:
            _phi.set_pending(pkey, data)
            send_message(thread_id, _phi.ask_text(_allowed_ph), thread_type)
            return
        intent = _phi.parse_intent(caption, _allowed_ph) or (
            _phi.GENERATE if _phi.classify(caption) == _phi.GENERATE else _phi.ANALYZE
        )
        if intent not in _allowed_ph and _allow is not None:
            if intent == _phi.GENERATE:
                return
        if intent == _phi.RAG_TEACHER:
            _phi.set_pending(pkey, data, stage="teacher_meta", intent=intent)
            send_message(thread_id, _phi.ASK_TEACHER, thread_type)
            return
        if intent in {_phi.ANALYZE, _phi.GENERATE} and _phi.needs_prompt(intent, caption):
            _phi.set_pending(pkey, data, stage="need_prompt", intent=intent)
            send_message(
                thread_id,
                _phi.ASK_PROMPT_GENERATE if intent == _phi.GENERATE else _phi.ASK_PROMPT_ANALYZE,
                thread_type,
            )
            return
        _do_photo_request(
            thread_id, thread_type, data, caption, _allow,
            intent=intent, user_id=_uid, account=_acc,
        )
        return

    # Tin GHI ÂM → STT → coi như tin nhắn chữ (đường đi chỉ thêm bước chuyển
    # đổi, các bước sau giữ nguyên như chat thường).
    if not text and ev.get("msg_type") == "chat.voice" and ev.get("attachment_url"):
        send_typing(thread_id, thread_type)
        data = _download(ev["attachment_url"])
        if not data:
            send_message(thread_id, "🎤 Em không tải được đoạn ghi âm ạ.", thread_type)
            return
        try:
            from services import voice as _voice
            text = _voice.listen(data, "m4a")
            logger.info("zalop voice->text (%d bytes): %.60s", len(data), text)
        except Exception as exc:
            logger.warning("zalop STT loi: %s", str(exc)[:160])
            send_message(thread_id, f"🎤 Em nghe không rõ ạ 😥 ({str(exc)[:120]})",
                         thread_type)
            return
        if not text:
            send_message(thread_id, "🎤 Em không nghe ra chữ nào trong đoạn ghi âm ạ.",
                         thread_type)
            return

    # Video/sticker — chưa hỗ trợ AI, bỏ qua im lặng.
    if not text:
        return

    send_typing(thread_id, thread_type)
    try:
        from services.agent import orchestrate
        # Cài đặt RIÊNG từng tài khoản (ownId): fast-path HA + model.
        _acc = str(ev.get("account_id") or "").strip()
        # Ngữ cảnh cho reminders (tạo nhắc hẹn trong lượt orchestrate này).
        _msg_ctx.account = _acc
        _msg_ctx.thread_type = int(thread_type or 0)
        _fp_map = config.get().get("zalo_personal_account_admins")
        _fp_entry = _fp_map.get(_acc) if isinstance(_fp_map, dict) else None
        # HA: admin entry (nếu match) → acc → True
        _fp = True
        if isinstance(_fp_entry, dict):
            _fp = bool(_fp_entry.get("ha_fastpath", True))
            for e in (_fp_entry.get("admin_entries") or []):
                if isinstance(e, dict) and str(e.get("chat_id") or "").strip() == thread_id:
                    _fp = bool(e.get("ha_fastpath", _fp))
                    break
        _model = _ai_model(_acc, thread_id)
        out = orchestrate(
            text, f"zalop_{thread_id}",
            allow=_allow, ha_fastpath=_fp, model=_model,
        )
        try:
            from services import net_guard
            out = net_guard.filter_agent_output(out if isinstance(out, dict) else {})
        except Exception:
            pass
        if out.get("silent"):
            return
        reply = (out.get("text") or "").strip() or "..."
        image_url = out.get("image_url")
        sent_media = False
        if image_url:
            if _send_photo_robust(
                thread_id, str(image_url), reply[:1000], thread_type, account=_acc,
            ):
                sent_media = True
            else:
                reply = (reply + "\n(em tạo ảnh xong nhưng gửi ảnh chưa được)").strip()
        # Audio agent → file đính kèm (không dán URL)
        audio_url = out.get("audio_url") or ""
        audio_path = out.get("audio_path") or ""
        if not sent_media and (audio_url or audio_path):
            src = audio_path or audio_url
            if _send_file_robust(
                thread_id, str(src), reply[:200], thread_type, account=_acc,
            ):
                sent_media = True
            else:
                reply = (reply + "\n(em có audio nhưng gửi file chưa được)").strip()
        if out.get("video_url") or out.get("video_path"):
            # best-effort file; không dán link
            vsrc = out.get("video_path") or out.get("video_url")
            if vsrc and _send_file_robust(
                thread_id, str(vsrc), reply[:200], thread_type, account=_acc,
            ):
                sent_media = True
            elif not sent_media:
                reply = (reply + "\n(em có video nhưng gửi file chưa được)").strip()
        # File Office từ agent (office_send) → gửi FILE THẬT như luồng Word:
        # sendFileByAccount cần URL công khai — copy vào images_dir/docs rồi
        # gửi /images/docs/… (path gốc /app/data/office KHÔNG được serve → 404
        # bị zalo-server tải về thành file hỏng).
        doc_path = out.get("doc_path") or ""
        if not sent_media and doc_path:
            sent_doc = False
            try:
                import uuid as _uuid
                from pathlib import Path as _P
                _src = _P(str(doc_path))
                _out_dir = config.images_dir / "docs"
                _out_dir.mkdir(parents=True, exist_ok=True)
                _pub = _out_dir / f"{_uuid.uuid4().hex[:8]}-{_src.name}"
                _pub.write_bytes(_src.read_bytes())
                sent_doc = _send_file_robust(
                    thread_id, f"/images/docs/{_pub.name}", reply[:200],
                    thread_type, account=_acc,
                )
            except Exception as exc:
                logger.warning("zalop doc_path: %s", exc)
            if sent_doc:
                sent_media = True
            else:
                reply = (reply + "\n(em có file nhưng gửi chưa được)").strip()
        if sent_media:
            if image_url and not (audio_url or audio_path):
                _maybe_voice_reply(
                    thread_id, thread_type, _acc,
                    str(ev.get("sender_id") or ""), reply,
                )
            return
        choices = out.get("choices") or []
        if choices and not any(out.get(k) for k in ("image_url", "video_url", "audio_url")):
            try:
                from services.agent import ask_choices as _ask
                reply = _ask.format_numbered(reply, choices)
            except Exception:
                pass
        send_message(thread_id, reply, thread_type)
        _maybe_voice_reply(thread_id, thread_type, _acc,
                           str(ev.get("sender_id") or ""), reply)
    except Exception as exc:
        logger.warning("Zalo personal orchestrator lỗi %s: %s", thread_id, exc)
        send_message(thread_id, "⏳ Hệ thống bận, thử lại sau ạ.", thread_type)


def _maybe_voice_reply(thread_id: str, thread_type: int, account: str,
                       user_id: str, reply: str) -> None:
    """Gửi KÈM file âm thanh nếu thread (hoặc riêng user này) bật `tts_reply`.

    Lưu WAV vào ``/images/voice/`` rồi ``sendFile`` qua URL nội bộ
    ``http://127.0.0.1/images/voice/…`` (zalo-server trong cùng container).
    Không dán link; lỗi TTS không làm hỏng câu chữ đã gửi.
    """
    text = (reply or "").strip()
    if not text or not thread_id:
        return
    try:
        import uuid
        from pathlib import Path

        from services import voice as _voice
        from services.voice import permissions as _vperm
        if not _vperm.wants_voice_reply("zalop", account, thread_id, user_id):
            return
        if not _voice.tts_ready():
            return
        wav = _voice.speak(text[:1000])
        out_dir = Path(config.images_dir) / "voice"
        out_dir.mkdir(parents=True, exist_ok=True)
        fn = f"tts_{uuid.uuid4().hex[:10]}.wav"
        (out_dir / fn).write_bytes(wav)
        # Ưu tiên URL local — đã test sendFile nhóm/1-1 thành công
        local = f"http://127.0.0.1/images/voice/{fn}"
        if not _send_file_robust(thread_id, local, "", thread_type, account=account):
            # fallback public / media_url cũ
            try:
                url = _voice.media_url(_voice.save_media(wav))
                send_file(thread_id, url, "", thread_type, account=account)
            except Exception:
                pass
        _voice.cleanup_media()
    except Exception as exc:
        logger.warning("zalop voice reply loi: %s", str(exc)[:160])


def handle_event(body: dict, event_name: str = "message") -> None:
    """Điểm vào từ webhook receiver (đã verify secret) — chạy trong thread nền."""
    try:
        ev = _parse_event(body if isinstance(body, dict) else {})
        if event_name == "message" and _dedup(ev.get("msg_id") or ""):
            return
        # Blacklist THEO TÀI KHOẢN (ownId): chặn nhóm/user trên acc này.
        from services import channel_activity as _ca
        if _ca.is_blacklisted(
            "zalop",
            ev.get("thread_id") or "",
            ev.get("sender_id") or "",
            account=str(ev.get("account_id") or ""),
        ):
            return
        # 1) Chuyển tiếp HA (mọi event, kể cả group_event/reaction/tin tự gửi).
        forward_to_ha(body, ev, event_name)
        # 1b) Chuyển tiếp theo 'Lọc chức năng theo thread' (khóa zalop:...) —
        # cùng cơ chế thread/user như Telegram + Zalo Bot, payload zca-js gốc.
        # User bật tag_mode: tin chứa TỪ KHÓA TAG của thread → CHỈ chuyển
        # webhook (AI im lặng); không tag → ChatGPT trả lời như thường.
        _fw_consumed = False
        try:
            # Lệnh /id ƯU TIÊN trước chuyển tiếp webhook (kể cả tag_mode) — để
            # "tag bot kèm /id" luôn gửi info về thread admin, không bị webhook nuốt.
            _txt_low = str(ev.get("text") or "").strip().lower()
            _is_id_req = _txt_low in {"/id", "id", "chatid"} or "/id" in _txt_low \
                or "chatid" in _txt_low or ("thread id" in _txt_low and len(_txt_low) <= 40)
            if not _is_id_req:
                from services.agent import capabilities as _fw_caps
                _req_fw, _kw_fw = _fw_caps.mention_required_for(
                    "zalop", str(ev.get("account_id") or ""),
                    str(ev.get("thread_id") or ""))
                # Chung logic với cổng AI: keyword + mention native + @alias
                _tagged = is_bot_tagged(ev, _kw_fw)
                _fw_payload = _zca_js_payload(body, ev)
                _fw_payload["tagged"] = _tagged
                _fw_consumed = _fw_caps.forward_event(
                    "zalop", str(ev.get("account_id") or ""),
                    str(ev.get("thread_id") or ""), str(ev.get("sender_id") or ""),
                    _fw_payload, tagged=_tagged,
                )
        except Exception:
            pass
        # 2) AI chỉ xử lý tin nhắn thường, không phải tin tự gửi.
        if event_name != "message" or ev.get("is_self") or not ev.get("thread_id"):
            return
        # Tên nhóm (zca-js getGroupInfo) — webhook thường không kèm title
        _is_g = bool(ev.get("thread_type") == 1)
        _acc = str(ev.get("account_id") or "")
        _tid = str(ev.get("thread_id") or "")
        _chat_name = str(ev.get("chat_name") or ev.get("group_name") or "").strip()
        if _is_g and _acc and _tid and not _chat_name:
            try:
                _info = resolve_thread(_acc, _tid, "group")
                if _info.get("ok") and _info.get("name"):
                    _chat_name = str(_info.get("name") or "").strip()
            except Exception:
                pass
        # Ghi LẦN GẦN NHẤT (tài khoản/Chat ID/User ID) để trang quản lý hiển thị.
        _ca.record("zalop", account=_acc,
                   chat_id=_tid, user_id=ev.get("sender_id") or "",
                   user_name=ev.get("display_name") or "",
                   chat_name=_chat_name,
                   is_group=_is_g,
                   text=ev.get("text") or ev.get("msg_type") or "")
        # Danh bạ bền (channel_contacts) — giống Telegram / Zalo Bot
        try:
            from services import channel_contacts as _cc
            _cc.upsert(
                "zalop",
                _acc,
                _tid,
                user_id=str(ev.get("sender_id") or ""),
                display_name=str(ev.get("display_name") or ""),
                chat_name=_chat_name,
                is_group=_is_g,
                text=str(ev.get("text") or ev.get("msg_type") or ""),
            )
        except Exception:
            pass
        if _fw_consumed:
            return  # tin tag đã chuyển webhook — không đưa vào AI
        if not _bool(_cfg(), "zalo_personal_ai_enabled", True):
            return
        _process_ai(ev)
    except Exception as exc:
        logger.warning("Zalo personal handle_event lỗi: %s", exc)


# ── Khởi động / đổi cấu hình ──────────────────────────────────────────────────

def startup() -> None:
    """Gọi từ app.py lifespan — login + tự đăng ký webhook ở NỀN (không block)."""
    if not enabled() or not _server_url():
        return

    def _run() -> None:
        for attempt in range(3):
            try:
                r = ensure_webhooks()
                if r.get("ok"):
                    logger.info("Zalo personal sẵn sàng (webhook: %s)", r.get("updated") or "đã đúng")
                    return
                logger.warning("Zalo personal startup: %s", r.get("error"))
            except Exception as exc:
                logger.warning("Zalo personal startup lỗi: %s", exc)
            time.sleep(15 * (attempt + 1))

    threading.Thread(target=_run, daemon=True, name="zalo-personal-startup").start()


def on_settings_changed() -> None:
    """Gọi khi settings zalo_personal_* thay đổi — reset client + re-đăng ký webhook."""
    global _client, _client_server, _logged_in_at
    with _http_lock:
        try:
            if _client is not None:
                _client.close()
        except Exception:
            pass
        _client = None
        _client_server = ""
        _logged_in_at = 0.0
    startup()
