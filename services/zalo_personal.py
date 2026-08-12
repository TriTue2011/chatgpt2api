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
    # Ưu tiên env dùng CHUNG với zalo-server (ZALO_SERVER_ADMIN_USERNAME/PASSWORD):
    # đặt env một chỗ thì cả server seed lẫn bot login đều khớp, gỡ được mặc
    # định admin/admin. Không có env → config → admin/admin (giữ tương thích).
    import os as _os
    c = _cfg()
    env_u = str(_os.environ.get("ZALO_SERVER_ADMIN_USERNAME") or "").strip()
    env_p = str(_os.environ.get("ZALO_SERVER_ADMIN_PASSWORD") or "").strip()
    user = env_u or str(c.get("zalo_personal_username") or "admin").strip()
    pw = env_p or str(c.get("zalo_personal_password") or "admin").strip()
    return (user, pw)


def _default_account() -> str:
    return str(_cfg().get("zalo_personal_account_id") or "").strip()


def _ai_model(account_id: str = "", thread_id: str = "") -> str:
    """Model: «Lọc thread» → admin_entries.ai_model → acc.ai_model → kênh →
    global → AI text. Model cài ở Lọc thread thắng (admin = một thread bình thường)."""
    c = _cfg()
    acc = str(account_id or "").strip()
    tid = str(thread_id or "").strip()
    # 0) Model riêng cài ở tab «Lọc thread» cho chính thread này
    if tid:
        try:
            from services.admin_workspace import thread_model_for
            m = thread_model_for("zalop", acc, tid)
            if m:
                return m
        except Exception:
            pass
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
             timeout: float | None = None, headers: dict | None = None,
             max_retries: int = 2) -> dict:
    """Gọi bot server; response chuẩn hóa {ok, data|error}. 401 → login lại 1 lần.

    429/flood (bot server dồn qua zca-js) → retry có giới hạn, giống
    services.telegram.client.TelegramClient.call — trước đây gọi 1 lần rồi bỏ
    cuộc ngay, không thử lại.
    """
    client = _get_client()
    if client is None:
        return {"ok": False, "error": "Chưa cấu hình zalo_personal_server_url"}
    kw: dict[str, Any] = {}
    if body is not None:
        kw["json"] = body
    if timeout is not None:
        kw["timeout"] = timeout
    if headers:
        kw["headers"] = headers
    for attempt in range(max_retries + 1):
        try:
            if time.time() - _logged_in_at > _SESSION_TTL:
                _login(client)
            r = client.request(method, path, **kw)
            if r.status_code == 401:
                if not _login(client):
                    return {"ok": False, "error": "Đăng nhập bot server thất bại"}
                r = client.request(method, path, **kw)
            if r.status_code == 429 and attempt < max_retries:
                retry_after = 1.0
                try:
                    retry_after = min(float(r.headers.get("Retry-After") or 1.0), 30.0)
                except (TypeError, ValueError):
                    pass
                time.sleep(retry_after)
                continue
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
            if attempt < max_retries:
                time.sleep(0.4 * (attempt + 1))
                continue
            return {"ok": False, "error": f"Lỗi kết nối bot server: {exc}"}
    return {"ok": False, "error": "Lỗi kết nối bot server"}


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


def suggested_webhook_urls() -> dict:
    """URL webhook gợi ý cho UI: NỘI BỘ (zca-js nhúng gọi ngược) + CÔNG KHAI
    (domain, chỉ khi đã cấu hình).

    Gateway nhận webhook ở CÙNG một endpoint nên gọi bằng IP nội bộ hay domain
    đều vào chung một chỗ — dùng song song được. Chỉ khác: zca-js nhúng cùng
    container nên nên dùng URL nội bộ (nhanh, không vòng ra Internet)."""
    c = _cfg()
    sec = webhook_secret()
    events = ("message", "group_event", "reaction")

    def _mk(base: str) -> dict:
        b = str(base or "").rstrip("/")
        return {e: f"{b}/zalo-personal/webhook?secret={sec}&event={e}" for e in events}

    internal_base = _webhook_base()
    public_base = (str(c.get("base_url") or "").strip()
                   or str(c.get("telegram_webhook_url") or "").strip()).rstrip("/")
    out: dict = {
        "auto": _bool(c, "zalo_personal_auto_webhook", True),
        "internal_base": internal_base,
        "internal": _mk(internal_base),
        "secret": sec,
        "events": list(events),
    }
    # Chỉ trả URL domain khi CÓ domain thật (không phải localhost nội bộ)
    if public_base and "127.0.0.1" not in public_base and "localhost" not in public_base:
        out["public_base"] = public_base
        out["public"] = _mk(public_base)
    return out


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
    """Thread này CÓ PHẢI nơi nhận thông báo admin — thuộc tính của THREAD.

    Không phải câu hỏi về quyền: nó quyết định thread được im lặng / khỏi bị báo
    "thread lạ", những thứ áp cho cả nhóm. Quyền admin dùng `_la_admin_nguoi_gui`.
    """
    tid = str(thread_id or "").strip()
    if not tid:
        return False
    return tid in _admin_thread_ids_for_account(account_id)


def _la_admin_nguoi_gui(account_id: str, thread_id: str, sender_id: str = "",
                        *, is_group: bool = False) -> bool:
    """True nếu NGƯỜI GỬI lượt này thật sự là admin của account này.

    Bản cũ chỉ so thread_id, nên khai một NHÓM làm admin thread là cấp quyền
    admin cho MỌI THÀNH VIÊN nhóm đó. Quyền này mở ra chụp webcam, chụp màn
    hình, tắt máy từ xa, xem cả kho media và xoá tài khoản Codex.

    Thread 1-1: thread_id CHÍNH LÀ uid người đối diện nên so thread_id là đủ.
    Nhóm: chỉ nhận khi sender_id cũng nằm trong danh sách admin; thiếu
    sender_id thì từ chối (fail-closed).
    """
    if not _is_admin_thread(account_id, thread_id):
        return False
    if not is_group:
        return True
    sid = str(sender_id or "").strip()
    return bool(sid) and sid in _admin_thread_ids_for_account(account_id)


_NHAN_ALL = "@All"      # Zalo hiển thị tag cả nhóm là '@All' (ảnh người dùng 01/08)


def send_message(thread_id: str, text: str, thread_type: int = 0, account: str = "",
                 *, rich: bool = True, mention_all: bool = False,
                 co_nut_chon: bool = False) -> dict:
    """Gửi text (tự cắt khúc ~2000). Styles RTF zca-js (giống Zalo Bot: đậm+màu+cỡ).

    thread_type: 0=user, 1=group.
    rich=True: emphasis + markdown_color/size (per admin_entries acc nếu match).
    co_nut_chon=True: tin này là MENU đánh số → không đổi "1." thành danh sách
        native của Zalo, giữ con số trong phần chữ.
    mention_all=True: tag CẢ NHÓM. Chèn '@All ' đầu tin rồi gắn mention
        {pos:0, uid:'-1', len:4} — uid '-1' là mã Zalo hiểu là 'nhắc mọi người'
        (đã xác minh trong zca-js: type = uid=='-1' ? 1 : 0). Chỉ áp cho NHÓM
        (thread_type=1) và chỉ khúc ĐẦU; chat 1-1 thì bỏ qua, gửi chữ thường.
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

    # Gạch chân / danh sách / thụt lề — bot TỰ áp theo văn bản (mặc định bật).
    rtf = {"gach_chan": True, "danh_sach": True, "thut_le": True}
    if rich:
        try:
            from services.telegram.emphasis import emphasize_text
            raw = emphasize_text(raw, bot=bot_like if bot_like else None, chat_id=thread_id)
        except Exception:
            pass
        try:
            from services.zalo_bot_format import (
                resolve_zalo_bot_color, resolve_zalo_bot_size, resolve_zalo_rtf,
            )
            color = resolve_zalo_bot_color(bot_like or None, str(thread_id)) or "orange"
            size = resolve_zalo_bot_size(bot_like or None, str(thread_id))
            rtf = resolve_zalo_rtf(bot_like or None, str(thread_id))
        except Exception:
            try:
                from services.zalo_markdown import config_markdown_color
                color = config_markdown_color()
            except Exception:
                color = "orange"

    # Cắt theo ranh giới đoạn/dòng/khoảng trắng (giống Telegram split_message) —
    # cắt cứng theo offset ký tự cũ có thể chẻ đôi 1 span **đậm**/styles khiến
    # marker mồ côi lộ ra ở đầu/cuối chunk.
    from services.telegram.format import split_message
    chunks = split_message(raw, limit=_MAX_LEN, prefer=_MAX_LEN) or ["..."]
    last: dict = {"ok": False}
    try:
        from services.zalo_markdown import config_markdown_enabled, markdown_to_zalo_message
        md_on = rich and config_markdown_enabled()
    except Exception:
        md_on = rich
        markdown_to_zalo_message = None  # type: ignore

    # Tag cả nhóm CHỈ ở khúc đầu, và chỉ khi là NHÓM. Chat 1-1 thì Zalo bỏ
    # mention nên không chèn (khỏi lòi chữ '@All' vô nghĩa vào tin riêng).
    con_tag = bool(mention_all) and int(thread_type or 0) == 1
    for ch in chunks[:_MAX_CHUNKS]:
        msg_obj: dict = {"msg": ch, "ttl": 0, "quote": None}
        if md_on and markdown_to_zalo_message is not None:
            try:
                parsed = markdown_to_zalo_message(
                    ch, color=color, size=size,
                    gach_chan=rtf["gach_chan"],
                    # Menu chọn giữ "1." DẠNG CHỮ: để Zalo tự đánh số thì con số
                    # rời khỏi phần chữ, mà cả `ask_choices.format_numbered` lẫn
                    # thói quen gõ "1" của người dùng đều bám vào con số đó.
                    danh_sach=rtf["danh_sach"] and not co_nut_chon,
                    thut_le=rtf["thut_le"])
                msg_obj["msg"] = parsed.get("msg") or ch
                styles = parsed.get("styles") or []
                if styles:
                    msg_obj["styles"] = styles
            except Exception as exc:
                logger.warning("zalo markdown convert fail: %s", exc)
        if con_tag:
            # Chèn '@All ' đầu tin. Vùng đậm lưu vị trí theo JS/UTF-16 (khoá
            # 'start'); '@All ' là 5 ký tự ASCII = 5 đơn vị JS nên DỜI mọi style
            # đi 5, không thì chữ đậm tô lệch. mention len=4 ('@All'), pos=0.
            _tien = _NHAN_ALL + " "
            msg_obj["msg"] = _tien + str(msg_obj.get("msg") or "")
            for s in (msg_obj.get("styles") or []):
                s["start"] = int(s.get("start") or 0) + len(_tien)
            msg_obj["mentions"] = [{"pos": 0, "uid": "-1", "len": len(_NHAN_ALL)}]
            con_tag = False
        last = _request("POST", "/api/sendMessageByAccount", {
            "message": msg_obj,
            "threadId": str(thread_id),
            "accountSelection": acc,
            "type": int(thread_type),
        })
        if not last.get("ok"):
            if msg_obj.get("styles"):
                # Bản dự phòng phải dùng CHUỖI ĐÃ BÓC MARKDOWN, không phải `ch`
                # thô. Dùng `ch` thì gửi-có-định-dạng thất bại là người dùng nhận
                # nguyên `**Tiêu đề**` — họ thấy đúng hai dấu sao và tưởng bot
                # trình bày xấu. Đo thật 01/08: bản tin 32 vùng đậm bị Zalo từ
                # chối, hai lệnh gửi cách nhau 1 giây, và người dùng nhắn lại
                # "Trình bày xấu quá, bỏ ** đi".
                plain = {"msg": msg_obj.get("msg") or ch, "ttl": 0, "quote": None}
                if msg_obj.get("mentions"):
                    plain["mentions"] = msg_obj["mentions"]   # '@All' đã ở trong msg
                last = _request("POST", "/api/sendMessageByAccount", {
                    "message": plain,
                    "threadId": str(thread_id),
                    "accountSelection": acc,
                    "type": int(thread_type),
                })
            if not last.get("ok"):
                break
    return last


def gui_chu_dong(thread_id: str, text: str, *, account: str = "") -> dict:
    """Gửi tới một thread KHÁC thread đang xử lý — tự dò chat riêng hay nhóm.

    Cấu hình chỉ ghi id thread, không ghi loại; gửi sai loại thì zca-js báo lỗi
    và tin không tới nơi. Nên thử loại đoán được trước, hỏng thì thử chiều còn
    lại — thà tốn một lời gọi còn hơn câu hỏi xác nhận rơi vào hư không.
    """
    from services.admin_workspace import guess_chat_kind
    thu = [1, 0] if guess_chat_kind(thread_id) == "group" else [0, 1]
    kq: dict = {"ok": False}
    for tt in thu:
        kq = send_message(thread_id, text, tt, account=account,
                          rich=False, co_nut_chon=True)
        if kq.get("ok"):
            return kq
    return kq


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


def _cong_khai_media(src: str) -> str:
    """Đưa một file media về URL /images/… mà zalo-server FETCH ĐƯỢC.

    URL http(s) → giữ nguyên (đã công khai). File dưới images_dir → giữ nguyên
    (_media_fetch_candidates tự đổi). File local NGOÀI images_dir (vd video lưu ở
    /app/data/agent/media) → COPY vào images_dir/media rồi trả /images/media/…;
    nếu không thì zalo-server dựng URL trỏ path gốc, nhận 404 và gửi trang lỗi
    ~14KB thay cho video."""
    s = str(src or "").strip()
    if not s or s.startswith("http://") or s.startswith("https://"):
        return s
    try:
        from pathlib import Path
        p = Path(s)
        if not p.is_file():
            return s
        img_root = Path(config.images_dir).resolve()
        try:
            p.resolve().relative_to(img_root)
            return s  # đã nằm dưới images_dir → khỏi copy
        except Exception:
            pass
        import uuid as _uuid
        out_dir = config.images_dir / "media"
        out_dir.mkdir(parents=True, exist_ok=True)
        pub = out_dir / f"{_uuid.uuid4().hex[:8]}-{p.name}"
        pub.write_bytes(p.read_bytes())
        return f"/images/media/{pub.name}"
    except Exception as exc:
        logger.warning("zalop cong_khai_media: %s", exc)
        return s


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


def _gui_nhieu_anh(thread_id: str, urls: list[str], caption: str = "",
                   thread_type: int = 0, account: str = "") -> bool:
    """Gửi NHIỀU ảnh trong MỘT tin (album) qua sendImages*ByAccount.

    Đi endpoint mảng chứ không gọi sendImage nhiều lần: bot server chia lô theo
    `max_file` THẬT của phiên (đo 30/07: 50 ảnh/tin) và nghỉ giữa các lô, nên
    3–50 ảnh vẫn gọn một tin. Gọi từng tấm thì thành N tin rời và dễ ăn lỗi
    "vượt quá số request cho phép, code 221" — ngưỡng mà chính người bảo trì
    zca-js nói họ không biết.

    Mỗi URL vẫn qua `_media_fetch_candidates` như đường một ảnh, vì URL nội bộ
    (127.0.0.1) cần đổi sang dạng bot server tải được.
    """
    acc = _account_for_send(account)
    if not acc or not urls:
        return False
    ds: list[str] = []
    for u in urls:
        for c in _media_fetch_candidates(u):
            try:
                from services import net_guard as _ng
                if (c.startswith("http") and not c.startswith("http://127.0.0.1")
                        and not _ng.is_allowed_egress_url(c)):
                    continue
            except Exception:
                pass
            ds.append(c)
            break   # mỗi ảnh lấy ứng viên ĐẦU dùng được, không nhân bản ảnh
    if len(ds) < 2:
        return False
    path = ("/api/sendImagesToGroupByAccount" if int(thread_type or 0) == 1
            else "/api/sendImagesToUserByAccount")
    r = _request("POST", path, {
        "imagePaths": ds,
        "threadId": str(thread_id),
        "accountSelection": acc,
        **({"caption": caption} if caption else {}),
    }, timeout=180.0)
    d = r.get("data") or {}
    ok = bool(r.get("ok")) and bool(d.get("success"))
    if ok:
        logger.info({"event": "zalop_gui_nhieu_anh", "so_anh": d.get("soAnh"),
                     "so_lo": d.get("soLo"), "max_file": d.get("maxFilePerMessage")})
    else:
        logger.warning({"event": "zalop_gui_nhieu_anh_loi", "so_anh": len(ds),
                        "loi": str(d.get("error") or r.get("error") or "")[:200]})
    return ok


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


def _try_fallback(entry: dict, own_id: str, text: str) -> None:
    """Fallback CHÍNH kênh Zalo Cá Nhân — KHÔNG mượn
    services.telegram_bot._try_bot_fallback: dict truyền vào trước đây KHÔNG có
    key "token" Telegram nên TelegramClient.call trả thẳng {"ok": False,
    "description": "empty token"} MÀ KHÔNG HỀ gọi mạng — cảnh báo lặng lẽ biến
    mất. `entry` (1 account trong zalo_personal_account_admins) đã có sẵn
    admin_entries/fallback_thread cùng cấu trúc "bot" của Telegram/Zalo Bot
    (xem _normalize_zalo_personal_account_admins) nên dùng chung
    admin_workspace.admin_entries rồi gửi qua send_message() của CHÍNH module
    này bằng tài khoản sở hữu (own_id)."""
    try:
        from services.admin_workspace import admin_entries
        rows = [e for e in admin_entries(entry) if e.get("fallback_enabled")]
    except Exception:
        rows = []
    threads: list[tuple[str, int]] = [
        (str(e["chat_id"]), 1 if e.get("kind") == "group" else 0) for e in rows
    ]
    legacy = str(entry.get("fallback_thread") or "").strip()
    if legacy and legacy not in {t for t, _ in threads}:
        threads.append((legacy, 0))
    if not threads and entry.get("fallback_enabled"):
        try:
            from services.admin_workspace import admin_entries as _admin_entries2
            for e in _admin_entries2(entry):
                if e.get("notify_enabled", True) and e.get("chat_id"):
                    threads.append((str(e["chat_id"]), 1 if e.get("kind") == "group" else 0))
                    break
        except Exception:
            pass
    if not threads:
        return
    for thread, ttype in threads:
        try:
            send_message(
                thread, text[:_MAX_LEN] + "\n(Fallback admin thread)",
                ttype, account=own_id, rich=False,
            )
        except Exception as exc:
            logger.warning("zalo personal fallback failed (%s): %s", thread, exc)


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
    is_account_update = cat == "account_update"
    is_newchat = cat == "newchat"
    seen: set[str] = set()
    raw = c.get("zalo_personal_account_admins")
    if not isinstance(raw, dict) or not raw:
        # Legacy: 1 admin_thread kênh — luôn gửi nếu còn cấu hình (không gate cờ kênh)
        if is_account_update:
            return
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
        # 🔔 / 📋 / 🔄 / 💬 độc lập
        if is_newchat:
            if entry.get("newchat_alert_enabled") is False:
                continue
        elif is_account_update:
            entries_list = entry.get("admin_entries") if isinstance(entry.get("admin_entries"), list) else []
            any_admin_update = any(isinstance(x, dict) and x.get("account_update_log_enabled") for x in entries_list)
            if not (entry.get("account_update_log_enabled") or any_admin_update):
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
                        "account_update_log_enabled": False,
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
                    "account_update_log_enabled": False,
                    "newchat_alert_enabled": True,
                })
        sent = 0
        for row in rows:
            if is_newchat:
                if row.get("newchat_alert_enabled") is False:
                    continue
            elif is_account_update:
                if not row.get("account_update_log_enabled"):
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
                _try_fallback(entry, str(own_id), text)
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
        for a in get_accounts():
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
        from services.net_guard import is_http_url
        if not is_http_url(url):
            logger.warning("Zalo personal webhook bỏ qua URL scheme lạ: %s", str(url)[:80])
            return
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


def _ten_tep_phuc_vu(ten_goc: str, duoi: str) -> str:
    """'<tên PDF gốc>' + đuôi mới → tên file NGƯỜI NHẬN nhìn thấy.

    Đo thật 05/08 13:22 — chuyển "HTT - Phướng án CHCN cơ sở.pdf" sang Word thì
    file tới tay là "1785910932720-d5cc523b18004c3d9e6841938369d7e7.docx": tên
    cũ là chuỗi uuid thuần, mở ra mới biết là tài liệu gì.

    Bỏ dấu về ASCII: tên này nằm trong URL mà máy chủ Zalo phải tự tải về, chữ
    có dấu chưa chắc qua được mọi tầng mã hoá. Ký tự lạ → '_', gộp '_' liên
    tiếp, cắt 60 ký tự cho gọn.
    """
    import re as _re
    import unicodedata as _ud

    goc = str(ten_goc or "").strip()
    if goc.lower().endswith(".pdf"):
        goc = goc[:-4]
    goc = "".join(c for c in _ud.normalize("NFD", goc)
                  if _ud.category(c) != "Mn").replace("đ", "d").replace("Đ", "D")
    goc = _re.sub(r"[^A-Za-z0-9._-]+", "_", goc).strip("._-")
    goc = _re.sub(r"_{2,}", "_", goc)[:60]
    return f"{goc or 'tai-lieu'}{duoi}"


def _serve_docx(thread_id: str, thread_type: int, docx_path: str, how: str,
                ten_goc: str = "") -> None:
    """Gửi file Word: ưu tiên gửi FILE THẬT qua bot server (sendFileByAccount cần
    URL công khai) — fallback nhắn link tải.

    `ten_goc` = tên file PDF người dùng gửi vào, để bản Word GIỮ ĐÚNG tên đó.
    Thư mục con uuid lo phần chống trùng, nên tên file không cần uuid nữa."""
    import uuid
    out_dir = config.images_dir / "docs" / uuid.uuid4().hex[:12]
    out_dir.mkdir(parents=True, exist_ok=True)
    fn = _ten_tep_phuc_vu(ten_goc, ".docx")
    with open(docx_path, "rb") as f:
        (out_dir / fn).write_bytes(f.read())
    # Gửi FILE .docx thật (sendFile); không dán link trừ khi mọi URL fail.
    rel = f"/images/docs/{out_dir.name}/{fn}"
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


def _moi_luu_online(ev: dict, thread_id: str, ten_tep: str, du_lieu: bytes,
                    *, menu_dang_mo: bool = False) -> None:
    """Tệp/ảnh vừa nhận → hỏi admin có lưu lên kho đám mây không.

    Mặc định phạm vi nào cũng TẮT nên hàm này thường thoát ngay, và mọi lỗi đều
    chặn tại đây: nhận tệp là việc chính, lưu đám mây là việc phụ đi kèm.

    `menu_dang_mo` — vừa gửi menu ý định (Nạp RAG / Chuyển Word / Tóm tắt / Lưu
    kho) cho tệp này. Khi đó KHÔNG hỏi lưu, theo đúng luật chủ máy chốt 07/08:
    **chỉ hỏi lưu sau khi đã xong việc**.

    Hai lý do, và lý do đầu là hỏng thật chứ không phải bất tiện:

      · Hai menu cùng sống thì menu kho KHÔNG BAO GIỜ bấm số được — bản chờ pdf
        được xét TRƯỚC (`zalo_personal` ~2393) rồi return. Đo thật 07/08 08:36:
        chủ máy gõ "4" định trả lời menu kho, bot hiểu là "4. Chuyển Excel" của
        menu ý định và chạy OCR một PDF scan 4 trang.
      · Hỏi lúc vừa nhận là hỏi SỚM: chưa biết sẽ chuyển hay tóm tắt thì chưa
        trả lời được "lưu bản nào". Hỏi sau mới có mục «Cả tệp gốc và bản đã
        chuyển».

    Không mất đường nào: menu ý định đã có sẵn mục «☁️ Lưu lên kho đám mây» cho
    ai chỉ muốn lưu, còn vừa chuyển vừa lưu thì sau khi chuyển xong bot hỏi tiếp
    với đủ bốn lựa chọn (bản đã chuyển / cả hai / bản gốc / không lưu).
    """
    try:
        from services.agent import luu_tru_day as _ltd
        if menu_dang_mo:
            logger.info({"event": "bo_hoi_luu_vi_menu_dang_mo",
                         "thread": str(thread_id), "tep": ten_tep[:60]})
            return
        _ltd.moi_luu(
            "zalop", str(thread_id),
            user=str(ev.get("sender_id") or ""),
            ten_tep=ten_tep, du_lieu=du_lieu,
            ten_nhom=str(ev.get("chat_name") or ""),
            dinh_danh=str(ev.get("account_id") or ""),
        )
    except Exception as exc:
        logger.warning("zalop luu_tru_online: %s", str(exc)[:150])


def _nhan_tep_ngam(ev: dict, thread_id: str) -> None:
    """Thread bot NGỒI IM nhận được tệp/ảnh → vẫn hỏi admin để lưu lên kho.

    Chủ máy 07/08: "nếu kiểu ghi nhận ngầm để tải lên thì sao". Làm được, vì
    câu hỏi duyệt KHÔNG gửi vào thread nhận tệp mà sang **thread admin** — nên
    bot không phải nói câu nào ở đây, sự im lặng của nhóm không bị phá.

    Cùng nếp với nhật ký: khối ghi nhật ký cũng đặt trước cổng im lặng, vì
    "chỉ không phản hồi, nhưng nhật ký vẫn phải có".

    Ba điều bắt buộc, đừng nới:
      · KHÔNG gửi gì vào `thread_id`. Nhánh này chỉ tải tệp về rồi giao cho
        `moi_luu`; mọi phản hồi đi đường admin. Thêm một `send_message` vào đây
        là thread im lặng bỗng lên tiếng — đúng thứ chủ máy tắt đi.
      · Phạm vi chưa khai kho hoặc chưa chọn thread admin thì `moi_luu` tự
        thoát; không tự đoán thay.
      · Mọi lỗi chặn tại đây — thread này vốn không được phục vụ, hỏng gì cũng
        không được làm rơi lượt xử lý của thread khác.
    """
    try:
        if not ev.get("attachment_url"):
            return
        loai = str(ev.get("msg_type") or "")
        if loai == "share.file":
            ten = (ev.get("file_name") or "").strip() or "document"
        elif loai == "chat.photo":
            ten = ""            # đặt tên theo đuôi ảnh ở dưới
        else:
            return
        data = _download(ev["attachment_url"])
        if not data:
            return
        if not ten:
            from services.agent.luu_tru_day import ten_anh as _ten_anh
            ten = _ten_anh(data)
        logger.info("zalop nhan tep ngam: thread=%s ten=%s bytes=%d"
                    % (thread_id, ten, len(data)))
        _moi_luu_online(ev, thread_id, ten, data)
    except Exception as exc:
        logger.warning("zalop nhan_tep_ngam: %s", str(exc)[:150])


def _moi_luu_tom_tat(thread_id: str, account: str, user_id: str, ten_goc: str,
                     tom_tat: str) -> None:
    """Vừa gửi bản tóm tắt → hỏi admin có lưu nó lên kho đám mây không."""
    try:
        from services.agent import luu_tru_day as _ltd
        _ltd.moi_luu_tom_tat("zalop", str(thread_id), ten_goc=ten_goc,
                             tom_tat=tom_tat, user=str(user_id or ""),
                             dinh_danh=str(account or ""))
    except Exception as exc:
        logger.warning("zalop luu_tru_online sau tom tat: %s", str(exc)[:150])


def _moi_luu_sau_chuyen_doi(*, ev_user_id: str, thread_id: str, account: str,
                            tep_goc: str, ten_goc: str, tep_moi: str,
                            duoi: str) -> None:
    """Vừa gửi bản đã chuyển → hỏi admin lưu bản nào lên kho đám mây.

    `account` là định danh tài khoản Zalo cá nhân — bản chờ khoá theo nó, phải
    khớp với khoá lúc đọc trả lời (`khoa_cho_thread`).
    """
    try:
        from pathlib import Path as _P
        from services.agent import luu_tru_day as _ltd
        _ltd.moi_luu_sau_chuyen_doi(
            "zalop", str(thread_id), tep_goc=tep_goc, ten_goc=ten_goc,
            du_lieu_moi=_P(tep_moi).read_bytes(),
            ten_moi=_ten_tep_phuc_vu(ten_goc, duoi),
            user=str(ev_user_id or ""), dinh_danh=str(account or ""))
    except Exception as exc:
        logger.warning("zalop luu_tru_online sau chuyen doi: %s", str(exc)[:150])


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
    loai_sach: str = "sgk",
    chu_thich: str = "",
) -> None:
    # `loai_sach` tên KHÁC biến `kind` bên trong (kind là loại việc cho telemetry).
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
        if intent == _pi.LUU_ONLINE:
            kind = "pdf_luu_online"
            from services.agent import luu_tru_day as _ltd
            reply = _ltd.luu_ngay("zalop", str(thread_id), tep=path, ten_tep=name,
                                  user=str(user_id or ""))
            send_message(thread_id, reply, thread_type)
        elif intent == _pi.WORD:
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
            _serve_docx(thread_id, thread_type, docx_tmp, how, name)
            _moi_luu_sau_chuyen_doi(ev_user_id=user_id, thread_id=thread_id,
                                    account=account, tep_goc=path, ten_goc=name,
                                    tep_moi=docx_tmp, duoi=".docx")
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
            # Giữ TÊN GỐC như bản Word (xem `_ten_tep_phuc_vu`); thư mục con
            # uuid lo chống trùng.
            out_dir = config.images_dir / "docs" / uuid.uuid4().hex[:12]
            out_dir.mkdir(parents=True, exist_ok=True)
            fn = _ten_tep_phuc_vu(name, ".xlsx")
            dest = out_dir / fn
            shutil.copy2(xlsx_tmp, dest)
            rel = f"/images/docs/{out_dir.name}/{fn}"
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
            _moi_luu_sau_chuyen_doi(ev_user_id=user_id, thread_id=thread_id,
                                    account=account, tep_goc=path, ten_goc=name,
                                    tep_moi=xlsx_tmp, duoi=".xlsx")
        elif intent == _pi.DICH:
            # Dịch tài liệu bằng máy chủ dịch tự dựng. docx/pptx/odt/txt/epub/
            # html quay lại ĐÚNG định dạng gốc; PDF/Excel thì Argos không dựng
            # lại được nên trả về chữ.
            kind = "pdf_dich"
            from services import translate_service as _ts
            r = _ts.dich_tep(path, name)
            reply = _ts.bao_cao_dich(r, name)
            if not r.get("ok"):
                status = "error"
                err = str(r.get("error") or "")[:200]
                send_message(thread_id, reply, thread_type)
            elif r.get("kieu") == "tep":
                import uuid
                ten_moi = str(r.get("ten") or name)
                duoi_moi = ten_moi[ten_moi.rfind("."):] if "." in ten_moi else ""
                stem = ten_moi[:-len(duoi_moi)] if duoi_moi else ten_moi
                out_dir = config.images_dir / "docs" / uuid.uuid4().hex[:12]
                out_dir.mkdir(parents=True, exist_ok=True)
                fn = _ten_tep_phuc_vu(stem, duoi_moi)
                (out_dir / fn).write_bytes(r["data"])
                rel = f"/images/docs/{out_dir.name}/{fn}"
                if not _send_file_robust(thread_id, rel, reply, thread_type,
                                         account=account):
                    reply = "🌐 Em đã dịch xong nhưng gửi file chưa được ạ."
                    send_message(thread_id, reply, thread_type)
            else:
                send_message(thread_id, reply, thread_type)
        elif intent == _pi.TOM_TAT:
            # Tóm tắt THUẦN: đọc file, trả bản tóm tắt, KHÔNG nạp vào kho nào.
            # Khác `RAG_KNOWLEDGE` ở chỗ đó — mục cũ vừa tóm tắt vừa ghi wiki,
            # nên ai chỉ muốn đọc nhanh một tài liệu thì không có lựa chọn nào.
            kind = "pdf_tom_tat"
            _tt = _pi.summarize_pdf(path, _ai_model(account, thread_id))
            if not (_tt or "").strip():
                status = "error"
                err = "khong doc duoc noi dung"
                reply = "⚠️ Em không đọc được nội dung file này để tóm tắt ạ."
            else:
                from services import pdf_images as _pimg
                reply = f"✍️ Tóm tắt **{name}**\n\n" + _pimg.humanize_markers(_tt)
            send_message(thread_id, reply, thread_type)
            if (_tt or "").strip():
                _moi_luu_tom_tat(thread_id, account, user_id, name, _tt)
        elif intent == _pi.RAG_TEACHER:
            kind = "pdf_teacher"
            if not grade or not subject:
                reply = "⚠️ Thiếu lớp/môn cho RAG teacher."
                status = "error"
                err = "missing grade/subject"
                send_message(thread_id, reply, thread_type)
                return
            r = _pi.ingest_teacher(path, grade=int(grade), subject=str(subject),
                                   name=name, kind=loai_sach, caption=chu_thich)
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


def _fb_gui_orchestrate(thread_id: str, thread_type: int, account: str,
                        user_id: str, allow: set | None, inject: str) -> None:
    """Bơm một câu vào orchestrator rồi trả lời — cho luồng Facebook.

    Telegram có đường replay (_process_message như nút ask:<n>); Zalo không có
    nên gọi thẳng orchestrate rồi tự format (đánh số lựa chọn) như nhánh
    orchestrate chính. Khoá phiên PHẢI trùng _skey của _process_ai, không thì
    câu này rơi vào lịch sử khác với hội thoại đang diễn ra.
    """
    from services.agent.orchestrator import orchestrate
    _skey = f"zalop_{thread_id}"
    try:
        from services.agent.scope import tach_phien_theo_nguoi as _tach
        if int(thread_type or 0) == 1 and user_id and _tach():
            _skey = f"zalop_{thread_id}:u{user_id}"
    except Exception:
        pass
    out = orchestrate(inject, _skey, allow=allow)
    reply = str((out or {}).get("text") or "")
    choices = (out or {}).get("choices") or []
    if choices:
        from services.agent import ask_choices as _ask
        reply = _ask.format_numbered(reply, choices)
    # Cùng hook với nhánh orchestrate chính: bot trả lời kiểu "gửi thêm ảnh đi"
    # thì mở cửa sổ chờ ảnh cho ĐÚNG người này — thiếu nó thì trong nhóm bắt
    # tag, tấm ảnh thứ hai gửi không tag bị cổng loại im lặng.
    try:
        from services import photo_intent as _phi_xin
        _phi_xin.danh_dau_neu_xin_anh(
            f"zalop:{account}:{thread_id}:{user_id or ''}", reply)
    except Exception:
        pass
    if reply:
        send_message(thread_id, reply, thread_type,
                     account=account or "", co_nut_chon=bool(choices))


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
        allowed = _phi.them_dang_facebook(_phi.allowed_intents(allow), allow)
        if it not in allowed and allow is not None:
            status = "blocked"
            err = f"intent {it} not allowed"
            return

        if it == _phi.FACEBOOK:
            # Ảnh → URL công khai của chính bot, rồi bơm lại orchestrator như
            # một lượt chat: URL vào lịch sử phiên để người dùng gửi thêm ảnh /
            # chốt caption, model gom mọi URL đã nhận vào MỘT lời gọi
            # `dang_facebook`. Telegram đi đường _process_message; Zalo không
            # có đường replay nên gọi thẳng orchestrate rồi tự trả lời (cùng
            # cách format với nhánh orchestrate chính: đánh số lựa chọn).
            kind = "photo_facebook"
            from services.protocol.conversation import save_image_bytes
            url = save_image_bytes(file_data)
            inject = f"thêm ảnh vào bài đăng facebook: {url}"
            if request_text:
                inject += f" — {request_text}"
            _fb_gui_orchestrate(thread_id, thread_type, account or "",
                                user_id, allow, inject)
            return

        if it == _phi.LUU_ONLINE:
            # Ảnh đi thẳng lên kho, không phân tích không tạo. Cùng đường với
            # `pdf_intent.LUU_ONLINE`: `luu_ngay` lưu luôn, KHÔNG hỏi lại lần
            # nữa — luật của chủ máy là chỉ hỏi lưu sau khi xong việc, mà đây
            # chính là việc đã xong.
            kind = "photo_luu_online"
            from services.agent import luu_tru_day as _ltd
            _ten = _ltd.ten_anh(file_data)
            _tam = _ltd.luu_vao_thu_muc_lam_viec(_ten, file_data)
            reply = _ltd.luu_ngay("zalop", str(thread_id), tep=_tam, ten_tep=_ten,
                                  user=str(user_id or ""))
            send_message(thread_id, reply, thread_type)
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

        if it == _phi.DICH:
            kind = "photo_dich"
            from services import translate_service as _ts
            r = _ts.dich_anh(file_data, channel="zalop")
            reply = _ts.bao_cao_dich(r, "chữ trong ảnh")
            if r.get("ok") and r.get("kieu") == "tep":
                # Bản dịch dài → .docx (xem translate_service._dong_goi_chu).
                import uuid
                out_dir = config.images_dir / "docs" / uuid.uuid4().hex[:12]
                out_dir.mkdir(parents=True, exist_ok=True)
                fn = _ten_tep_phuc_vu("chu-trong-anh", ".docx")
                (out_dir / fn).write_bytes(r["data"])
                if not _send_file_robust(
                        thread_id, f"/images/docs/{out_dir.name}/{fn}", reply,
                        thread_type, account=account):
                    send_message(thread_id, r.get("text") or reply, thread_type)
                return
            if not r.get("ok"):
                status = "error"
                err = str(r.get("error") or "")[:200]
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
    # NHẬT KÝ NHÓM: ghi MỌI tin nhận được (nếu phạm vi BẬT) — TRƯỚC mọi cổng
    # lọc/tag, tách hẳn với việc trả lời. Mặc định TẮT nên không bật thì không ghi.
    try:
        from services.agent import chatlog as _chatlog
        _skey_log = f"zalop_{thread_id}"
        if int(thread_type or 0) == 1 and _sender:
            _skey_log = f"{_skey_log}:u{_sender}"
        # `tagged` cho luật «Tag bot» của «Lọc nhật ký» (mặc định TẮT nên phần
        # lớn phạm vi không dùng tới). Tra từ khoá tag của chính thread này chứ
        # không truyền chuỗi rỗng: chủ máy đặt từ khoá riêng thì tin tag bằng từ
        # khoá đó vẫn phải tính là CÓ tag, không thì bật `tag_only` xong nhật ký
        # rỗng mà không hiểu vì sao.
        try:
            _, _kw_log = _caps.mention_required_for(
                "zalop", str(ev.get("account_id") or ""), thread_id)
        except Exception:
            _kw_log = ""
        _chatlog.ghi(_skey_log, sender_id=_sender,
                     sender_name=str(ev.get("display_name") or "").strip(),
                     text=text, mentions=[str(m) for m in (ev.get("mentions") or [])],
                     tagged=is_bot_tagged(ev, _kw_log))
    except Exception:
        pass
    _allow = _caps.allowed_groups_for_member("zalop", acc_id, thread_id, _sender)
    allowed_ids = list(_chat_ids())
    # HAI câu hỏi khác nhau, đừng trộn:
    #   _thread_admin — thread này có phải NƠI NHẬN thông báo admin (của THREAD)
    #   _is_admin     — NGƯỜI GỬI lượt này có quyền admin (của NGƯỜI)
    _thread_admin = _is_admin_thread(acc_id, thread_id)
    _is_admin = _la_admin_nguoi_gui(acc_id, thread_id, _sender,
                                    is_group=int(thread_type or 0) == 1)
    # Admin = NƠI NHẬN THÔNG BÁO. Chức năng chat/AI của thread do LỌC THREAD quyết định:
    # admin KHÔNG thêm trong lọc (thread_filters) và không trong whitelist → im lặng,
    # chỉ nhận log. (Trước đây admin auto-permit — nay bỏ.)
    # Chỉ người trong danh sách mới được giao tiếp (công tắc theo thread). Câu
    # hỏi này KHÁC câu "được dùng chức năng nào": người bị lọc mà không tick
    # nhóm nào thì quyền là tập RỖNG — vẫn khác None nên bot vẫn tán gẫu.
    #
    # ĐẶT SAU khối nhật ký nhóm ở trên là CỐ Ý: yêu cầu là "chỉ không phản hồi,
    # nhưng nhật ký vẫn phải có". Ghi ≠ trả lời, cùng lý lẽ với cổng tag.
    if not _caps.duoc_giao_tiep("zalop", acc_id, thread_id, _sender):
        _nhan_tep_ngam(ev, thread_id)
        return  # im lặng, đúng như thread chưa được thêm vào Lọc thread
    permitted = (_allow is not None) or (thread_id in allowed_ids)
    if not permitted:
        if not _thread_admin:
            _alert_new_thread(ev)  # admin đã biết — không cảnh báo "thread lạ"
        return  # im lặng — chưa thêm thread vào Lọc thread

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

    # Lệnh /facebook — menu đăng bài Page, do CODE dựng (không qua LLM), cùng
    # nếp /id. Nhóm chức năng 'facebook' phải bật; tắt thì nói rõ thay vì im
    # lặng — người gõ ĐÍCH DANH lệnh này xứng đáng biết vì sao không có gì xảy ra.
    # Bóc tag bot trước khi so ("@TênBot /facebook" là cách gọi thường gặp
    # trong nhóm Zalo — không bóc thì lệnh mở đầu bằng '@' và không bao giờ khớp).
    from services import photo_intent as _phi_fb
    if _phi_fb.bo_tag(text).lower() in {"/facebook", "/fb"}:
        _acc_fb = str(ev.get("account_id") or "").strip()
        if _allow is not None and "facebook" not in _allow:
            send_message(thread_id, "📘 Chức năng Facebook đang tắt cho chỗ này — "
                                    "bật nhóm «📘 Facebook» trong Cài đặt ▸ Lọc thread.",
                         thread_type, account=_acc_fb)
            return
        # Khoá phiên PHẢI trùng với _skey của orchestrate bên dưới, không thì
        # người dùng trả "1/2/3" mà resolve_reply không thấy bản chờ nào.
        _fbkey = f"zalop_{thread_id}"
        try:
            from services.agent.scope import tach_phien_theo_nguoi as _tach_fb
            _snd_fb = str(ev.get("sender_id") or "")
            if int(thread_type or 0) == 1 and _snd_fb and _tach_fb():
                _fbkey = f"zalop_{thread_id}:u{_snd_fb}"
        except Exception:
            pass
        from services import facebook_page as _fbp
        from services.agent import ask_choices as _ask_fb
        _out_fb = _ask_fb.apply_to_result({"text": _fbp.menu_ask(_fbkey)}, _fbkey)
        _reply_fb = _ask_fb.format_numbered(
            str(_out_fb.get("text") or ""), _out_fb.get("choices") or [])
        send_message(thread_id, _reply_fb, thread_type, account=_acc_fb,
                     co_nut_chon=bool(_out_fb.get("choices")))
        return

    # Khoá chờ — tính SỚM vì cổng tag bên dưới cần tra nó.
    pkey = f"zalop:{ev.get('account_id')}:{thread_id}:{ev.get('sender_id') or ''}"

    # Bộ lọc TAG (nhóm): native mention / keyword / @alias — chung tag_gate_allows.
    if thread_type == 1 and thread_id:
        # NGOẠI LỆ: bot vừa xin ảnh của chính người này, hoặc đang giữ bản chờ
        # của họ → cho câu/ảnh tiếp theo đi qua dù không tag. Không có ngoại lệ
        # này thì bot hỏi "gửi ảnh đi" rồi tự bịt tai: ảnh tới máy chủ nhưng bị
        # cổng loại ngay, không lời gọi vision nào (đo thật 06/08 lúc 07:07).
        from services import photo_intent as _phi_cho
        from services import pdf_intent as _pi_cho
        # Bản chờ «lưu tệp lên kho đám mây?» khoá theo THREAD (nhóm admin thì ai
        # trả lời cũng được), khác ba bản chờ trên khoá theo từng người. Chỉ mở
        # cổng cho ĐÚNG câu trả lời "1/2/3", không mở cho mọi tin trong 30 phút
        # chờ — mở rộng thế là tắt luôn yêu cầu tag của nhóm đó.
        from services.agent import luu_tru_day as _ltd_cho
        from services import cho_sau_tag as _cst
        _dang_cho = (_phi_cho.dang_cho_anh(pkey) or _phi_cho.has_pending(pkey)
                     or _pi_cho.has_pending(pkey)
                     or bool(_ltd_cho.chon_tu_tra_loi(_ltd_cho.khoa_cho_thread(
                         "zalop", str(ev.get("account_id") or ""),
                         str(thread_id)), text or ""))
                     # Vừa tag bot xong → chờ họ gửi tiếp (ảnh/tệp/chữ). Zalo
                     # không cho vừa tag vừa đính ảnh nên đây là đường DUY NHẤT
                     # để tấm ảnh gửi ngay sau đó tới được phần xử lý.
                     or _cst.dang_cho(pkey))
        _req, _kw = _caps.mention_required_for("zalop", ev.get("account_id") or "", thread_id)
        if _dang_cho:
            _req = False
            _phi_cho.het_cho_anh(pkey)   # dùng một lần, tránh mở cổng mãi
        _native = is_bot_tagged(ev, "")
        if _native:
            # TAG là mở cửa sổ chờ — bất kể tin này có kèm yêu cầu hay không.
            # Chủ máy chốt 06/08: "tag tên bot rồi chờ đợi thông tin từ user".
            _cst.mo(pkey)
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

    # Khoá chờ phải kèm NGƯỜI GỬI. Bản cũ chỉ tới thread nên trong nhóm, A gửi
    # ảnh rồi bot hỏi "muốn làm gì", B nói câu bất kỳ là câu đó bị nhận làm trả
    # lời của A — B cướp mất lượt mà không ai biết, và A trả lời sau thì bản chờ
    # đã bị lấy đi rồi. Chờ là chờ theo từng người (chủ máy chốt 05/08).
    # `pkey` đã tính ở trên, ngay trước cổng tag — cổng đó cần tra bản chờ.

    # PDF chờ: 1 kiến thức / 2 teacher / 3 Word / 4 Excel
    from services import pdf_intent as _pi
    from services.yeu_cau_moi import la_yeu_cau_moi as _la_moi_pdf
    if text and _pi.has_pending(pkey) and _la_moi_pdf(text):
        _pi.pop_pending(pkey)   # yêu cầu mới → đóng bản chờ, đi tiếp bình thường
    elif text and _pi.has_pending(pkey):
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
                loai_sach=meta.get("kind") or "sgk", chu_thich=text,
            )
            return
        # Bộ ý định phải là bộ ĐÃ HIỆN trong menu, không phải bộ suy lại từ
        # `_allow`: tệp Office hiện 3 mục mà giải số theo 5 mục thì gõ "3" ra
        # WORD trong khi màn hình ghi "3. Tóm tắt".
        _allowed_i = _pi.y_dinh_da_moi(_pend, _pi.allowed_intents(_allow))
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
    from services.yeu_cau_moi import la_yeu_cau_moi as _la_moi
    if text and _phi.has_pending(pkey) and _la_moi(text):
        # Yêu cầu MỚI thì đóng bản chờ cũ rồi để câu này đi tiếp như bình thường.
        # Không đóng thì: đang chờ mô tả ảnh mà nói "gửi file cho nhóm A" là câu
        # đó bị lấy làm mô tả ảnh; đang chờ lớp+môn thì bị hỏi lại mãi, khoá chặt
        # 10 phút. Quy tắc chủ máy chốt 05/08.
        _phi.pop_pending_full(pkey)
    elif text and _phi.has_pending(pkey):
        _pend = _phi.get_pending(pkey) or {}
        _allowed_ph = _phi.them_dang_facebook(_phi.them_luu_online(
            _phi.allowed_intents(_allow), "zalop", str(thread_id),
            user=str(ev.get("sender_id") or "")), _allow)
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
                    channel="zalop", kind=meta.get("kind") or "sgk", caption=text,
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

    # Lưu trữ online: admin trả lời "1/2/3" cho tệp đang chờ. Khoá theo THREAD
    # (không kèm người) vì nhóm admin thì ai trả lời cũng được. Đặt SAU các bản
    # chờ pdf/ảnh: những bản chờ đó theo TỪNG NGƯỜI nên là việc riêng của họ,
    # phải được ưu tiên trước câu hỏi chung của cả thread.
    if text and ev.get("msg_type") not in {"share.file", "chat.photo"}:
        from services.agent import luu_tru_day as _ltd
        _khoa_kho = _ltd.khoa_cho_thread("zalop", str(ev.get("account_id") or ""),
                                         str(thread_id))
        _chon_kho = _ltd.chon_tu_tra_loi(_khoa_kho, text)
        if _chon_kho:
            send_message(thread_id, _ltd.tra_loi(_khoa_kho, _chon_kho)["text"],
                         thread_type)
            return

    # File đính kèm
    if ev.get("msg_type") == "share.file" and ev.get("attachment_url"):
        name = (ev.get("file_name") or "").strip()
        _la_pdf = (name.lower().endswith(".pdf")
                   or ".pdf" in str(ev["attachment_url"]).lower())
        # File Office đi CHUNG đường với PDF — cùng menu ý định, cùng đường nạp
        # RAG. Yêu cầu 05/08: "nạp rag kiến thức, nạp rag teacher như pdf cho
        # word và excel". Khác đúng hai chỗ: menu không có mục chuyển Word/Excel
        # (đổi .docx sang .docx thì vô nghĩa), và file tạm phải giữ ĐÚNG đuôi
        # thật vì markitdown nhận dạng theo đuôi.
        _la_office = _pi.la_office(name)
        if _la_pdf or _la_office:
            intents = (_pi.y_dinh_cho_office(_allow) if _la_office
                       else _pi.allowed_intents(_allow))
            intents = _pi.them_luu_online(
                intents, "zalop", str(thread_id),
                user=str(ev.get("sender_id") or ""))
            if not intents:
                return
            send_typing(thread_id, thread_type)
            data = _download(ev["attachment_url"])
            if not data:
                send_message(thread_id, "📄 Không tải được file.", thread_type)
                return
            _duoi = ("." + name.rsplit(".", 1)[-1].lower()) if _la_office else ".pdf"
            info = _pi.set_pending(pkey, data, name or "document.pdf", _duoi,
                                   intents=intents)
            send_message(thread_id,
                         _pi.ask_text(name or ("Office" if _la_office else "PDF"),
                                      intents, info),
                         thread_type)
            _moi_luu_online(ev, thread_id, name or "document.pdf", data,
                            menu_dang_mo=True)
            return
        send_message(thread_id,
                     f"📎 Em nhận PDF, Word, Excel và PowerPoint thôi ạ. "
                     f"File: {name or 'không rõ'}", thread_type)
        return

    # Ảnh: không caption → menu; có caption → parse intent / hỏi prompt nếu cần.
    if ev.get("msg_type") == "chat.photo" and ev.get("attachment_url"):
        send_typing(thread_id, thread_type)
        data = _download(ev["attachment_url"])
        if not data:
            send_message(thread_id, "📷 Không tải được ảnh.", thread_type)
            return
        # Zalo cá nhân chuyển ảnh GỐC (iPhone → HEIC, CDN đôi khi trả .jxl):
        # chuẩn hoá ngay, ảnh không đọc được thì báo liền.
        data, _img_err = _phi.prepare_incoming(data)
        if not data:
            send_message(thread_id, _img_err, thread_type)
            return
        # Ảnh cũng có thư mục riêng và hạn giữ riêng trên đám mây (mục «Ảnh»).
        from services.agent.luu_tru_day import ten_anh as _ten_anh
        # Menu ảnh NAY đã có mục «☁️ Lưu lên kho đám mây» (photo_intent 07/08),
        # nên ảnh theo cùng luật với tệp: không hỏi chồng lúc vừa nhận.
        _moi_luu_online(ev, thread_id, _ten_anh(data), data, menu_dang_mo=True)
        # Bóc phần tag bot ra trước khi xét "có nói gì không". Trong nhóm phải
        # tag mới gọi được bot, nên lời kèm ảnh gần như luôn mở đầu bằng
        # '@TenBot' — không bóc thì nó không bao giờ rỗng và nhánh hiện menu bên
        # dưới không bao giờ chạy, tag bot rồi gửi ảnh suông là bị đoán bừa
        # thành «phân tích ảnh» (chủ máy báo 05/08, 20:55).
        caption = _phi.bo_tag(text)
        _allowed_ph = _phi.them_dang_facebook(_phi.them_luu_online(
            _phi.allowed_intents(_allow), "zalop", str(thread_id),
            user=str(ev.get("sender_id") or "")), _allow)
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

    # Video: CHỈ phục vụ luồng Facebook (nhóm 'facebook' bật + đã nối Page) —
    # ngoài điều kiện đó rơi tiếp xuống dưới, giữ nguyên hành vi cũ (trước giờ
    # chat.video không có handler nào).
    if (ev.get("msg_type") in {"chat.video", "chat.video.msg"}
            and ev.get("attachment_url")
            and _phi.FACEBOOK in _phi.them_dang_facebook(set(), _allow)):
        send_typing(thread_id, thread_type)
        data = _download(ev["attachment_url"])
        if not data:
            send_message(thread_id, "🎬 Em không tải được video — anh/chị gửi "
                                    "em link mp4 công khai cũng được ạ.",
                         thread_type)
            return
        from services import facebook_page as _fbp_v
        _vurl = _fbp_v.luu_media_cong_khai(data, "mp4")
        _vinject = f"thêm video vào bài đăng facebook: {_vurl}"
        _vcap = _phi.bo_tag(text)
        if _vcap:
            _vinject += f" — {_vcap}"
        _fb_gui_orchestrate(thread_id, thread_type, _acc, _uid, _allow, _vinject)
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
            # session_id → STT chọn ngôn ngữ theo phạm vi (vi mặc định / en)
            _sid = f"zalop:{_acc}:{thread_id}:{_uid}"
            text = _voice.listen(data, "m4a", session_id=_sid)
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
        # HA: «Lọc thread» (nếu cài riêng) → admin entry (nếu match) → acc → True
        _fp = True
        if isinstance(_fp_entry, dict):
            _fp = bool(_fp_entry.get("ha_fastpath", True))
            for e in (_fp_entry.get("admin_entries") or []):
                if isinstance(e, dict) and str(e.get("chat_id") or "").strip() == thread_id:
                    _fp = bool(e.get("ha_fastpath", _fp))
                    break
        try:
            from services.admin_workspace import thread_fastpath_for as _tfp
            _t = _tfp("zalop", _acc, thread_id)
            if _t is not None:
                _fp = _t
        except Exception:
            pass
        _model = _ai_model(_acc, thread_id)
        # Nhóm (thread_type=1): mỗi USER một phiên riêng; 1-1 giữ key cũ.
        # CHỈ hội thoại live tách theo người — bộ nhớ và nhật ký vẫn dùng chung
        # cả nhóm (`scope.khoa_du_lieu` / `khoa_nhat_ky` tự bỏ người ra).
        _skey = f"zalop_{thread_id}"
        try:
            from services.agent.scope import tach_phien_theo_nguoi as _tach
            _snd = str(ev.get("sender_id") or "")
            if int(thread_type) == 1 and _snd and _tach():
                _skey = f"zalop_{thread_id}:u{_snd}"
        except Exception:
            pass
        out = orchestrate(
            text, _skey,
            allow=_allow, ha_fastpath=_fp, model=_model,
            # Quyền admin quyết định phạm vi thư viện media: admin xem cả kho,
            # người thường chỉ media chính họ tạo (đặc tả 31/07).
            is_admin=_is_admin,
        )
        try:
            from services import net_guard
            out = net_guard.filter_agent_output(out if isinstance(out, dict) else {})
        except Exception:
            pass
        if out.get("silent"):
            return
        # Trống + có nút chọn → `format_numbered` điền danh sách, đừng chèn "..."
        # (câu duyệt gửi tin nay CHỈ có ba lựa chọn).
        reply = (out.get("text") or "").strip()
        if not reply and not out.get("choices"):
            reply = "..."
        # Bot vừa nói câu xin ảnh → ghi nhận đang chờ ảnh của ĐÚNG người này, để
        # tấm ảnh gửi sau đó đi qua được cổng chặn-nếu-không-tag trong nhóm.
        try:
            from services import photo_intent as _phi_xin
            _phi_xin.danh_dau_neu_xin_anh(pkey, reply)
        except Exception:
            pass
        image_url = out.get("image_url")
        image_urls = out.get("image_urls")
        sent_media = False
        if isinstance(image_urls, list) and len(image_urls) > 1:
            # Nhiều ảnh → MỘT tin (album). Đây là lợi thế riêng của Zalo Cá Nhân:
            # giới hạn thật đọc từ phiên là 50 ảnh/tin (đo 30/07), nên 3–50 ảnh
            # vẫn gọn một tin. Zalo Bot không có album, phải gửi lần lượt.
            if _gui_nhieu_anh(thread_id, [str(u) for u in image_urls],
                              reply[:1000], thread_type, account=_acc):
                sent_media = True
            else:
                # Rơi về gửi từng tấm: thà chậm và tới đủ, hơn là mất cả loạt.
                da = sum(1 for u in image_urls
                         if _send_photo_robust(thread_id, str(u), "", thread_type,
                                               account=_acc))
                sent_media = da > 0
                if da < len(image_urls):
                    reply = (reply + f"\n(gửi được {da}/{len(image_urls)} ảnh)").strip()
        elif image_url:
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
            # best-effort file; không dán link. Tạo nhiều video (Flow x2/x3/x4)
            # thì gửi HẾT — người dùng đã trả tín dụng cho từng cái.
            vsrcs = [str(v) for v in (out.get("video_paths") or out.get("video_urls") or [])
                     if v] or [str(out.get("video_path") or out.get("video_url") or "")]
            vsrcs = [v for v in vsrcs if v]
            da_gui = 0
            for i, vsrc in enumerate(vsrcs):
                cap = reply[:200] if i == 0 else ""
                # video_path lưu ở /app/data/agent/media (NGOÀI images_dir) → không
                # được serve → zalo-server fetch phải 404 rồi gửi trang lỗi ~14KB
                # thay cho video. Copy vào images_dir/media để có URL /images/media/…
                # công khai (đúng cách doc_path đã xử). URL http thì để nguyên.
                gui = _cong_khai_media(vsrc)
                if _send_file_robust(thread_id, gui, cap, thread_type, account=_acc):
                    da_gui += 1
            if da_gui:
                sent_media = True
                if da_gui < len(vsrcs):
                    reply = (reply + f"\n(gửi được {da_gui}/{len(vsrcs)} video)").strip()
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
        has_choices = bool(choices and not any(out.get(k) for k in ("image_url", "video_url", "audio_url")))
        if has_choices:
            try:
                from services.agent import ask_choices as _ask
                reply = _ask.format_numbered(reply, choices)
            except Exception:
                pass
        # «Trả lời bằng giọng nói» = chỉ âm thanh; có nút chọn số thì vẫn gửi chữ
        # (kèm voice). Ngược lại: gửi được voice → bỏ chữ; không → gửi chữ.
        _sender = str(ev.get("sender_id") or "")
        if has_choices:
            send_message(thread_id, reply, thread_type, co_nut_chon=True)
            _maybe_voice_reply(thread_id, thread_type, _acc, _sender, reply)
        elif not _maybe_voice_reply(thread_id, thread_type, _acc, _sender, reply):
            send_message(thread_id, reply, thread_type)
    except Exception as exc:
        logger.warning("Zalo personal orchestrator lỗi %s: %s", thread_id, exc)
        send_message(thread_id, "⏳ Hệ thống bận, thử lại sau ạ.", thread_type)


def _maybe_voice_reply(thread_id: str, thread_type: int, account: str,
                       user_id: str, reply: str) -> bool:
    """Gửi file âm thanh nếu thread (hoặc riêng user này) bật `tts_reply`.

    Lưu WAV vào ``/images/voice/`` rồi ``sendFile`` qua URL nội bộ
    ``http://127.0.0.1/images/voice/…`` (zalo-server trong cùng container).
    Trả True nếu ĐÃ gửi voice → caller BỎ gửi chữ («Trả lời bằng giọng nói» =
    chỉ âm thanh). False (chưa bật / TTS chưa sẵn / lỗi) → caller gửi chữ.
    """
    text = (reply or "").strip()
    if not text or not thread_id:
        return False
    try:
        import uuid
        from pathlib import Path

        from services import voice as _voice
        from services.voice import permissions as _vperm
        if not _vperm.wants_voice_reply("zalop", account, thread_id, user_id):
            return False
        if not _voice.tts_ready():
            return False
        from services.voice import session_voice as _sv
        _sid = f"zalop:{account}:{thread_id}:{user_id}"
        if not _sv.is_tts_enabled_for_session(_sid):
            return False  # TTS bị tắt cho kênh/acc/nhóm/user này
        _pk = f"zalop_{thread_id}:u{user_id}" if user_id else f"zalop_{thread_id}"
        wav = _voice.speak_reply(text[:1000], _pk, session_id=_sid)
        out_dir = Path(config.images_dir) / "voice"
        out_dir.mkdir(parents=True, exist_ok=True)
        fn = f"tts_{uuid.uuid4().hex[:10]}.wav"
        (out_dir / fn).write_bytes(wav)
        # Ưu tiên URL local — đã test sendFile nhóm/1-1 thành công
        local = f"http://127.0.0.1/images/voice/{fn}"
        sent = _send_file_robust(thread_id, local, "", thread_type, account=account)
        if not sent:
            # fallback public / media_url cũ
            try:
                url = _voice.media_url(_voice.save_media(wav))
                send_file(thread_id, url, "", thread_type, account=account)
                sent = True
            except Exception:
                sent = False
        _voice.cleanup_media()
        return bool(sent)
    except Exception as exc:
        logger.warning("zalop voice reply loi: %s", str(exc)[:160])
    return False


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
