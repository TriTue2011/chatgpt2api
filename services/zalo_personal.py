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

_MD_BOLD_DOUBLE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)


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


def _ai_model() -> str:
    return str(_cfg().get("zalo_personal_ai_model") or "").strip() or "cx/auto"


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
        "notify_enabled": _bool(c, "zalo_personal_notify_enabled", False),
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

def _to_zalo_text(text: str) -> str:
    out = _MD_BOLD_DOUBLE.sub(r"\1", text or "")
    return _MD_HEADING.sub("", out)


def _account_for_send(account: str = "") -> str:
    acc = (account or _default_account()).strip()
    if acc:
        return acc
    accounts = get_accounts().get("accounts") or []
    return str(accounts[0].get("ownId")) if accounts else ""


def send_message(thread_id: str, text: str, thread_type: int = 0, account: str = "") -> dict:
    """Gửi text (tự cắt khúc 2000). thread_type: 0=user, 1=group."""
    acc = _account_for_send(account)
    if not acc:
        return {"ok": False, "error": "Chưa có tài khoản Zalo nào đăng nhập"}
    text = _to_zalo_text(text or "...")
    chunks = [text[i:i + _MAX_LEN] for i in range(0, len(text), _MAX_LEN)] or ["..."]
    last: dict = {"ok": False}
    for ch in chunks[:_MAX_CHUNKS]:
        last = _request("POST", "/api/sendMessageByAccount", {
            "message": {"msg": ch, "ttl": 0, "quote": None},
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


def notify_admin(text: str) -> None:
    """Gửi thông báo hệ thống tới thread admin (global + từng acc nếu có). Best-effort."""
    c = _cfg()
    if not enabled() or not _bool(c, "zalo_personal_notify_enabled", False):
        return
    seen: set[str] = set()
    # Per-account admin threads
    raw = c.get("zalo_personal_account_admins")
    if isinstance(raw, dict):
        for own_id, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            th = str(entry.get("admin_thread") or "").strip()
            if not th or th in seen:
                continue
            ttype = 1 if str(entry.get("admin_thread_type") or "0").strip() in {
                "1", "group",
            } else 0
            seen.add(th)
            try:
                send_message(th, text[:_MAX_LEN], ttype, account=str(own_id))
            except Exception:
                pass
    # Global fallback (nếu chưa gửi cùng thread)
    th = str(c.get("zalo_personal_admin_thread") or "").strip()
    if th and th not in seen:
        ttype = 1 if str(c.get("zalo_personal_admin_thread_type") or "0").strip() in {
            "1", "group",
        } else 0
        try:
            send_message(th, text[:_MAX_LEN], ttype)
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
    }


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


def _alert_new_thread(ev: dict) -> None:
    key = f"{ev.get('account_id')}:{ev.get('thread_id')}"
    if key in _new_thread_seen:
        return
    _new_thread_seen.add(key)
    if len(_new_thread_seen) > 500:
        _new_thread_seen.clear()
    c = _cfg()
    if not _bool(c, "zalo_personal_newchat_alert_enabled", True):
        return  # đã tắt chức năng báo thread mới cho kênh Zalo Cá Nhân
    kind = "nhóm" if ev.get("thread_type") == 1 else "cá nhân"
    msg = (
        f"🆕 Thread Zalo Cá Nhân mới nhắn tới ({kind})\n"
        f"• Thread ID: {ev.get('thread_id')}\n"
        + (f"• User ID người gửi: {ev.get('sender_id')}\n" if ev.get("sender_id") else "")
        + (f"• Người gửi: {ev.get('display_name')}\n" if ev.get("display_name") else "")
        + (f"• Tài khoản nhận: {ev.get('account_id')}\n" if ev.get("account_id") else "")
        + f"• Tin: {(ev.get('text') or ev.get('msg_type') or '')[:120]}\n"
        f"→ Trang Zalo Cá Nhân: thêm Thread ID vào danh sách cho phép, hoặc "
        f"'Lọc chức năng theo thread' (khóa zalop:{ev.get('account_id')}:{ev.get('thread_id')})."
    )
    # Ưu tiên Thread ID admin CỦA TÀI KHOẢN nhận tin; fallback global.
    # Có admin → gửi bằng chính acc đó. Trống → notifier đa kênh.
    acc_id = str(ev.get("account_id") or "").strip()
    thread, ttype, send_acc = _admin_for_account(acc_id)
    if thread:
        try:
            send_message(thread, msg[:_MAX_LEN], ttype, account=send_acc)
        except Exception:
            pass
        return
    try:
        from services.notifier import notify_admin as _notify
        _notify(msg)
    except Exception:
        pass


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
    base = _public_base()
    link = f"{base}/images/docs/{fn}" if base else f"/images/docs/{fn}"
    if base and send_file(thread_id, link, f"Bản Word ({how})", thread_type).get("ok"):
        return
    send_message(thread_id, f"📝 Bản Word ({how}) — bấm để tải về:\n{link}", thread_type)


def _do_pdf_intent(thread_id: str, thread_type: int, pending: dict | None, intent: str) -> None:
    if not pending:
        return
    import os
    path = pending["path"]
    send_typing(thread_id, thread_type)
    docx_tmp = (path[:-4] if path.endswith(".pdf") else path) + ".docx"
    try:
        if intent == "word":
            from services.pdf_to_word import convert_pdf_to_docx
            r = convert_pdf_to_docx(path, docx_tmp)
            if not r.get("ok"):
                send_message(thread_id, f"⚠️ Không chuyển được sang Word: {str(r.get('error', ''))[:150]}", thread_type)
                return
            how = "giữ layout" if r.get("method") == "layout" else "OCR (PDF scan)"
            _serve_docx(thread_id, thread_type, docx_tmp, how)
        else:
            from services.pdf_intent import summarize_pdf
            s = summarize_pdf(path, _ai_model())
            if not s:
                send_message(thread_id, "❌ Không đọc được nội dung PDF (có thể là ảnh chụp).", thread_type)
            else:
                from services import pdf_images as _pimg
                send_message(thread_id, _pimg.humanize_markers(s), thread_type)
                # Ảnh THẬT cho marker image:// — zalo-server chạy chung container
                # nên đưa thẳng đường dẫn file cục bộ làm imagePath.
                try:
                    for cap, iid in _pimg.find_markers(s)[:4]:
                        p = _pimg.image_path(iid)
                        if p:
                            send_photo(thread_id, str(p),
                                       caption=(cap or "Hình trong tài liệu")[:200],
                                       thread_type=thread_type)
                except Exception as exc:
                    logger.warning("zalop gửi ảnh marker PDF lỗi: %s", exc)
    except Exception as e:
        logger.warning("Zalo personal pdf intent %s lỗi: %s", intent, e)
        send_message(thread_id, f"❌ Lỗi xử lý PDF: {e}", thread_type)
    finally:
        for p in (path, docx_tmp):
            try:
                os.unlink(p)
            except Exception:
                pass


def _do_photo_request(thread_id: str, thread_type: int, file_data: bytes,
                      request_text: str, allow: set | None = None) -> None:
    """Ảnh + yêu cầu: 'generate' = tạo/chỉnh ảnh (nhóm lọc 'image');
    'analyze' = phân tích bằng nhánh vision — GIỐNG kênh Zalo Bot."""
    from services import photo_intent as _phi
    send_typing(thread_id, thread_type)
    if _phi.classify(request_text) == "generate":
        if allow is not None and "image" not in allow:
            return
        out = _phi.generate_from_photo(file_data, request_text)
        url = out.get("image_url")
        if url:
            if send_photo(thread_id, url, (out.get("text") or "Đây ạ 🎨")[:1000], thread_type).get("ok"):
                return
            send_message(thread_id, f"{out.get('text') or ''}\n{url}".strip(), thread_type)
            return
        send_message(thread_id, out.get("text") or "Em chưa tạo được ảnh ạ.", thread_type)
        return
    ans = ""
    try:
        import base64
        from services.agent.branches import branch_model
        from services.agent.runtime import call_model, content_of
        durl = "data:image/jpeg;base64," + base64.b64encode(file_data).decode()
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": request_text},
            {"type": "image_url", "image_url": {"url": durl}},
        ]}]
        _vm = branch_model("vision", "zalop")
        resp = call_model(_vm, msgs, timeout=180, max_tokens=900)
        if resp.get("error"):
            try:
                from services.notifier import notify_admin as _notify
                _notify(f"⚠️ Vision (Zalo Cá Nhân) lỗi — model '{_vm}': {str(resp['error'])[:200]}")
            except Exception:
                pass
        else:
            ans = content_of(resp).strip()
    except Exception as exc:
        logger.warning("Zalo personal vision lỗi: %s", exc)
    send_message(thread_id, ans or "📷 Đã nhận ảnh nhưng chưa phân tích được ạ.", thread_type)


def _process_ai(ev: dict) -> None:
    """Trả lời AI cho 1 tin — CHỈ thread được cấp phép (an toàn tài khoản cá nhân)."""
    thread_id = ev["thread_id"]
    thread_type = ev["thread_type"]
    text = (ev.get("text") or "").strip()

    from services.agent import capabilities as _caps
    # Tầng lọc: nhóm (thread_id) ∩ user (sender_id) — User ID theo từng nhóm.
    _sender = str(ev.get("sender_id") or "")
    _allow = _caps.allowed_groups_for_member("zalop", ev.get("account_id") or "", thread_id, _sender)
    allowed_ids = _chat_ids()
    permitted = (_allow is not None) or (thread_id in allowed_ids)
    if not permitted:
        _alert_new_thread(ev)
        return  # im lặng — tài khoản cá nhân không tự trả lời người lạ

    _low = text.lower()
    # Substring như Zalo Bot — tag bot kèm /id ("@Tên bot /id") vẫn nhận ra lệnh.
    if _low in {"/id", "id", "chatid"} or "/id" in _low or "chatid" in _low \
            or ("thread id" in _low and len(_low) <= 40):
        kind = "nhóm" if thread_type == 1 else "cá nhân"
        _id_info = (f"🆔 Thread ID: {thread_id} ({kind})\n"
                    f"👤 User ID người gửi: {_sender or '(không rõ)'}\n"
                    f"Tài khoản bot: {ev.get('account_id')}")
        # Ưu tiên Thread ID admin CỦA TÀI KHOẢN nhận tin; fallback global.
        acc_id = str(ev.get("account_id") or "").strip()
        _admin, _attype, _send_acc = _admin_for_account(acc_id)
        if _admin:
            send_message(
                _admin,
                f"🆔 Yêu cầu /id từ thread {kind}:\n{_id_info}",
                _attype,
                account=_send_acc,
            )
        else:
            send_message(thread_id, _id_info, thread_type)
        return

    # Bộ lọc TAG (nhóm): bật 'bắt buộc tag' → chỉ trả lời khi tin chứa từ khóa tag.
    if thread_type == 1 and thread_id:
        _req, _kw = _caps.mention_required_for("zalop", ev.get("account_id") or "", thread_id)
        if _req:
            _kw_l = (_kw or "").strip().lower()
            if not (_kw_l and _kw_l in (text or "").lower()):
                return

    pkey = f"zalop:{ev.get('account_id')}:{thread_id}"

    # PDF đang chờ ý định (1=RAG / 2=Word)?
    from services import pdf_intent as _pi
    if text and _pi.has_pending(pkey):
        _intent = _pi.parse_intent(text)
        if _intent:
            if _intent not in _pi.allowed_intents(_allow):
                return
            _do_pdf_intent(thread_id, thread_type, _pi.pop_pending(pkey), _intent)
            return

    # Ảnh đang chờ yêu cầu?
    from services import photo_intent as _phi
    if text and _phi.has_pending(pkey):
        pdata = _phi.pop_pending(pkey)
        if pdata:
            _do_photo_request(thread_id, thread_type, pdata, text, _allow)
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

    # Ảnh: có caption → xử lý ngay; không caption → hỏi rồi chờ tin kế tiếp.
    if ev.get("msg_type") == "chat.photo" and ev.get("attachment_url"):
        send_typing(thread_id, thread_type)
        data = _download(ev["attachment_url"])
        if not data:
            send_message(thread_id, "📷 Không tải được ảnh.", thread_type)
            return
        if not text:
            _phi.set_pending(pkey, data)
            send_message(thread_id, _phi.ASK, thread_type)
            return
        _do_photo_request(thread_id, thread_type, data, text, _allow)
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
        # Cài đặt RIÊNG từng tài khoản (ownId): fast-path HA cục bộ.
        _acc = str(ev.get("account_id") or "").strip()
        # Ngữ cảnh cho reminders (tạo nhắc hẹn trong lượt orchestrate này).
        _msg_ctx.account = _acc
        _msg_ctx.thread_type = int(thread_type or 0)
        _fp_map = config.get().get("zalo_personal_account_admins")
        _fp_entry = _fp_map.get(_acc) if isinstance(_fp_map, dict) else None
        _fp = bool(_fp_entry.get("ha_fastpath", True)) if isinstance(_fp_entry, dict) else True
        out = orchestrate(text, f"zalop_{thread_id}", allow=_allow, ha_fastpath=_fp)
        if out.get("silent"):
            return
        reply = (out.get("text") or "").strip() or "..."
        image_url = out.get("image_url")
        if image_url:
            if send_photo(thread_id, image_url, reply[:1000], thread_type).get("ok"):
                return
            reply = f"{reply}\n{image_url}"
        for k in ("video_url", "audio_url"):
            u = out.get(k)
            if u:
                reply = f"{reply}\n{u}"
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

    Zalo cá nhân gửi file qua URL nên cần voice.public_base_url trỏ đúng địa
    chỉ gateway. Lỗi TTS không làm hỏng câu trả lời chữ đã gửi.
    """
    text = (reply or "").strip()
    if not text or not thread_id:
        return
    try:
        from services import voice as _voice
        from services.voice import permissions as _vperm
        if not _vperm.wants_voice_reply("zalop", account, thread_id, user_id):
            return
        if not _voice.tts_ready():
            return
        wav = _voice.speak(text[:1000])
        url = _voice.media_url(_voice.save_media(wav))
        send_file(thread_id, url, "", thread_type, account=account)
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
                _tagged = bool(_kw_fw) and _kw_fw.lower() in str(ev.get("text") or "").lower()
                # Mention NATIVE zca-js: data.mentions = [{uid,pos,len,...}] — tag
                # tên tài khoản bot (uid == ownId nhận tin) là "tag", không cần đặt
                # từ khóa ở bộ lọc tag.
                if not _tagged:
                    try:
                        _mts = (body.get("data") or {}).get("mentions") if isinstance(body, dict) else None
                        if isinstance(_mts, str):
                            _mts = json.loads(_mts)
                        _own = str(ev.get("account_id") or "")
                        if _own and isinstance(_mts, list):
                            _tagged = any(
                                isinstance(x, dict) and str(x.get("uid") or "") == _own
                                for x in _mts
                            )
                    except Exception:
                        pass
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
        # Ghi LẦN GẦN NHẤT (tài khoản/Chat ID/User ID) để trang quản lý hiển thị.
        _ca.record("zalop", account=ev.get("account_id") or "",
                   chat_id=ev.get("thread_id") or "", user_id=ev.get("sender_id") or "",
                   user_name=ev.get("display_name") or "",
                   is_group=ev.get("thread_type") == 1,
                   text=ev.get("text") or ev.get("msg_type") or "")
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
