"""Zalo Bot — kênh chat AI 2 chiều qua chatgpt2api.

Zalo Bot API: base `https://bot-api.zaloplatforms.com/bot<token>/<method>`,
token nằm trong path, response {ok, result, description, error_code}.

Media HỖ TRỢ (docs bot-api.zaloplatforms.com):
- sendPhoto  — tin NHẢN ẢNH (photo = URL http công khai; optional caption ≤2000)
- sendVoice  — tin THOẠI 1-1 (voice_url = URL .aac; KHÔNG hỗ trợ nhóm)
- sendMessage — text

KHÔNG hỗ trợ gửi file (Word/docx/video/document). PDF nhận vào chỉ tóm tắt/RAG;
không chuyển Word. Không dán link file thay cho media.

Điểm khác Telegram:
- Webhook payload bọc trong `result`: {ok, result:{event_name, message:{…}}}.
- Xác thực webhook: header `X-Bot-Api-Secret-Token`.
- NHÓM: nền tảng chỉ giao tin khi @tag bot.

Dùng CHUNG orchestrator + Cloudflare webhook như Telegram.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import urllib.request
from typing import Any

from services.config import config

logger = logging.getLogger(__name__)
# uvicorn không gắn handler cho root logger → INFO của module này ("Zalo IN",
# "long-polling started") không ra docker logs, chẩn đoán mù. Gắn handler riêng.
if not logging.getLogger().handlers and not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)
    logger.propagate = False

ZALO_API = "https://bot-api.zaloplatforms.com"
_MAX_LEN = 1990  # sendMessage giới hạn 2000


# Ngữ cảnh bot hiện hành (đa-token). Mỗi luồng poll / xử lý tin set _current.bot =
# {token, chat_ids, ai_model, enabled}; getter đọc từ đây, fallback bot[0] nếu chưa set.
_current = threading.local()


def _cur_bot() -> dict | None:
    return getattr(_current, "bot", None)


def _bots() -> list[dict]:
    return config.zalo_bots()


def _active_bot() -> dict:
    b = _cur_bot()
    if b is None:
        bots = _bots()
        b = bots[0] if bots else {}
    return b


def _bot_token() -> str:
    return str(_active_bot().get("token", "")).strip()


def _zalo_model(chat_id: str | None = None) -> str:
    """Model: admin.ai_model → bot.ai_model → global → AI text."""
    bot = _active_bot()
    m = ""
    if chat_id:
        try:
            from services.admin_workspace import ai_model_for_chat
            m = ai_model_for_chat(bot, chat_id)
        except Exception:
            m = ""
    if not m:
        m = str((bot or {}).get("ai_model", "")).strip()
    if m:
        return m
    try:
        g = str(config.get().get("telegram_ai_model")
                or config.get().get("zalo_ai_model") or "").strip()
        if g:
            return g
    except Exception:
        pass
    return "AI text"


def _chat_ids() -> list:
    return list(_active_bot().get("chat_ids") or [])


def _webhook_secret_for(token: str) -> str:
    """Secret ổn định sinh từ token (cho X-Bot-Api-Secret-Token, verify webhook)."""
    return ("z" + hashlib.sha256(token.encode()).hexdigest()[:40]) if token else ""


def _bot_id() -> str:
    """ID bot công khai = phần trước ':' của token. Dùng làm khóa lọc theo-bot
    'zalo:<bot_id>:<chat_id>'."""
    return _bot_token().split(":", 1)[0].strip()


def _bot_public_id(bot: dict | None) -> str:
    tok = str((bot or {}).get("token") or "").strip()
    return tok.split(":", 1)[0].strip() if tok else ""


_bot_name_cache: dict[str, str] = {}  # token -> tên bot (getMe); "" = đã thử, lỗi


def _fetch_bot_name(token: str) -> str:
    """Tên hiển thị qua getMe (fallback). Ưu tiên tên người, tránh username mã hóa
    kiểu ``bot.dEnBZJeC`` — UI nên dùng config ``label`` trước hàm này."""
    token = str(token or "").strip()
    if not token:
        return ""
    if token in _bot_name_cache:
        return _bot_name_cache[token]
    name = ""
    try:
        req = urllib.request.Request(f"{ZALO_API}/bot{token}/getMe")
        r = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
        res = r.get("result") or {}
        # Live Zalo getMe: display_name="Bot Ben Bắp", account_name="bot.LgDbinZQ"
        # → luôn ưu tiên display_name / first_name; account_name/username mã hóa chỉ fallback.
        human = str(
            res.get("display_name") or res.get("first_name")
            or res.get("name") or res.get("title") or ""
        ).strip()
        coded = str(
            res.get("account_name") or res.get("username") or ""
        ).strip()
        if human:
            name = human
        elif coded and not coded.lower().startswith("bot."):
            name = coded
        else:
            name = coded
    except Exception as exc:
        logger.warning("Zalo getMe lỗi: %s", exc)
    _bot_name_cache[token] = name
    return name


def get_bot_names() -> dict[str, str]:
    """Map bot_id → tên bot cho UI.

    Ưu tiên ``label`` trong Settings (vd Bot Ben Bắp) — KHÔNG lấy username mã hóa
    getMe (bot.dEnBZJeC) khi đã có label.
    """
    out: dict[str, str] = {}
    for b in _bots():
        token = str(b.get("token", "")).strip()
        if not token:
            continue
        bid = token.split(":", 1)[0].strip()
        if not bid:
            continue
        label = str(b.get("label") or "").strip()
        if label:
            out[bid] = label
            continue
        name = _fetch_bot_name(token)
        if name:
            out[bid] = name
    return out


def resolve_chat(token: str, chat_id: str) -> dict:
    """Nhận diện thread admin: getChat (Zalo Bot API ≈ Telegram) + heuristic.

    Trả {ok, chat_id, name, kind: private|group}.
    """
    from services.admin_workspace import guess_chat_kind
    token = str(token or "").strip()
    chat_id = str(chat_id or "").strip()
    kind = guess_chat_kind(chat_id)
    # Zalo group id thường dạng zgr-… / g…
    cl = chat_id.lower()
    if cl.startswith("zgr-") or cl.startswith("g") or chat_id.startswith("-"):
        kind = "group"
    # Zalo thread id opaque: heuristic thường private; API mới tin cậy
    name = ""
    ok = False
    if not token or not chat_id:
        return {"ok": False, "chat_id": chat_id, "name": name, "kind": kind}
    url = f"{ZALO_API}/bot{token}/getChat"
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps({"chat_id": chat_id}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        r = json.loads(urllib.request.urlopen(req, timeout=12).read().decode("utf-8", "replace"))
        if r.get("ok") and isinstance(r.get("result"), dict):
            res = r["result"]
            ok = True
            ctype = str(
                res.get("type") or res.get("chat_type") or res.get("chatType") or ""
            ).strip().upper()
            if ctype in {"GROUP", "SUPERGROUP", "CHANNEL", "1"} or ctype.lower() in {
                "group", "supergroup", "channel",
            }:
                kind = "group"
            elif ctype in {"PRIVATE", "USER", "0"} or ctype.lower() in {
                "private", "user",
            }:
                kind = "private"
            name = (
                str(res.get("title") or res.get("name") or res.get("display_name")
                    or res.get("account_name") or "").strip()
                or " ".join(
                    x for x in (
                        str(res.get("first_name") or "").strip(),
                        str(res.get("last_name") or "").strip(),
                    ) if x
                ).strip()
                or str(res.get("username") or "").strip()
            )
    except Exception as exc:
        logger.info("Zalo getChat fail %s: %s", chat_id[:24], exc)
    # Fallback: getChatAdministrators / heuristic
    if not ok:
        # Một số bản API trả chat qua getUpdates history — kind heuristic
        if re.fullmatch(r"-?\d{10,}", chat_id) or chat_id.startswith("g"):
            # id số dài / prefix g → thường nhóm (best-effort)
            pass
    return {"ok": ok, "chat_id": chat_id, "name": name, "kind": kind}


def _bot_label() -> str:
    """Nhãn bot hiện hành cho tin nhắn admin: 'Tên (id)' — có tên thì kèm, không
    thì chỉ id."""
    name = _fetch_bot_name(_bot_token())
    return f"{name} ({_bot_id()})" if name else _bot_id()


def _find_bot_by_id(bot_id: str) -> dict | None:
    want = str(bot_id or "").strip()
    if not want:
        return None
    for b in _bots():
        if not b.get("enabled", True):
            continue
        if _bot_public_id(b) == want:
            return b
    return None


def _admin_ids_for_bot(bot: dict | None = None) -> list[str]:
    from services.admin_workspace import resolve_admins_for_bot
    return resolve_admins_for_bot("zalo", bot or _active_bot())


def _resolve_admin_delivery() -> tuple[str, dict | None]:
    cur = _active_bot()
    ids = _admin_ids_for_bot(cur)
    return (ids[0], cur) if ids else ("", cur)


def _send_admin_thread(admin: str, text: str, *, bot_only: bool = False) -> bool:
    if not admin:
        return False
    try:
        return bool(send_message(admin, text, rich=False).get("ok"))
    except Exception:
        return False


def _notify_all_admins(text: str, *, bot: dict | None = None) -> int:
    b = bot or _active_bot()
    ids = _admin_ids_for_bot(b)
    if not ids:
        return 0
    prev = _cur_bot()
    n = 0
    try:
        _current.bot = b
        for aid in ids:
            if _send_admin_thread(aid, text):
                n += 1
    finally:
        _current.bot = prev
    return n


def _is_admin_chat(chat_id: str) -> bool:
    return str(chat_id or "").strip() in set(_admin_ids_for_bot())


def _alert_new_chat(chat_id: str, sender: str, text: str, served: bool,
                    user_id: str = "", is_group: bool = False,
                    tagged: bool = False, chat_name: str = "") -> None:
    """Báo chat/nhóm mới (💬) — chỉ admin bật newchat_alert."""
    c = config.get()
    if not bool(c.get("zalo_newchat_alert_enabled", True)):
        return
    bot = _active_bot() or {}
    if not bool(bot.get("newchat_alert_enabled", True)):
        return
    try:
        from services import channel_contacts as _cc
        from services import admin_workspace as _aw
        from services.admin_workspace import admin_entries
        ok, rec = _cc.should_alert_new(
            "zalo", _bot_id(), chat_id,
            user_id=user_id, is_group=is_group, tagged=tagged,
            display_name=sender, chat_name=chat_name, text=text or "",
        )
        if not ok:
            return
        base = _cc.format_alert(rec, served=served, text=text or "")
        sent = 0
        prev = _cur_bot()
        try:
            for e in admin_entries(bot):
                if e.get("newchat_alert_enabled") is False:
                    continue
                aid = str(e.get("chat_id") or "").strip()
                if not aid:
                    continue
                bl = _aw.bot_display_name("zalo", _bot_id(), aid)
                msg = base.replace(
                    f"bot **{_cc.bot_label('zalo', _bot_id())}**",
                    f"bot **{bl}**",
                    1,
                )
                msg += _aw.start_save_prompt("zalo", aid, rec)
                # rich theo admin (màu/cỡ) — send_message(..., rich=True) mặc định
                if send_message(aid, msg, rich=True, bot=bot).get("ok"):
                    sent += 1
        finally:
            _current.bot = prev
        if not sent:
            try:
                from services.notifier import notify_admin as _notify
                _notify(
                    base + "\n(Fallback đa kênh — bot này chưa gửi được admin thread nào.)",
                    category="newchat",
                )
            except Exception:
                pass
        _cc.mark_notified(str(rec.get("key") or ""))
    except Exception as exc:
        logger.warning("zalo new-contact alert failed: %s", exc)


def _api_call(method: str, data: dict | None = None, timeout: int = 20) -> dict:
    token = _bot_token()
    if not token:
        return {"ok": False}
    url = f"{ZALO_API}/bot{token}/{method}"
    try:
        if data is not None:
            req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                         headers={"Content-Type": "application/json"})
        else:
            req = urllib.request.Request(url, method="POST")
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        logger.warning("Zalo API %s: %s", method, exc)
        return {"ok": False}


# ── Long-polling (giống openclaw zaloclawbot) ────────────────────────────────
# Cloudflare chặn /zalo/webhook (403) → KHÔNG dùng webhook. Thay vào đó gateway
# tự POST getUpdates liên tục (outbound, không cần public endpoint). Zalo, như
# Telegram, chỉ cho getUpdates khi webhook TẮT → deleteWebhook trước khi poll.
_poll_threads: dict[str, threading.Thread] = {}
_poll_lock = threading.Lock()
_seen_ids: dict[str, set[str]] = {}  # dedup message_id theo TỪNG token


def register_webhook() -> bool:
    """Giữ TÊN cũ (app.py/system.py gọi) nhưng KHỞI ĐỘNG LONG-POLLING cho MỌI bot
    Zalo đang bật (đa-token). Idempotent — mỗi token 1 thread poll."""
    return start_polling()


def start_polling() -> bool:
    """Bật polling cho tất cả bot enabled; bỏ qua bot đã có thread sống."""
    started = False
    with _poll_lock:
        for bot in _bots():
            if not bot.get("enabled", True):
                continue
            token = str(bot.get("token", "")).strip()
            if not token:
                continue
            th = _poll_threads.get(token)
            if th and th.is_alive():
                started = True
                continue
            th = threading.Thread(target=_poll_loop, args=(dict(bot),), daemon=True,
                                  name=f"zalo-poll-{token[:6]}")
            _poll_threads[token] = th
            th.start()
            logger.info("Zalo long-polling started for bot %s…", token[:6])
            started = True
    return started


def _poll_loop(bot: dict) -> None:
    _current.bot = bot  # thread-local: mọi _api_call trong luồng này dùng token bot
    token = str(bot.get("token", "")).strip()
    _api_call("deleteWebhook")  # tắt webhook để getUpdates hoạt động
    seen = _seen_ids.setdefault(token, set())
    fails = 0
    while True:
        # Bot bị tắt / xóa khỏi config → tự dừng luồng.
        if not any(str(b.get("token", "")).strip() == token and b.get("enabled", True)
                   for b in _bots()):
            _poll_threads.pop(token, None)
            logger.info("Zalo poll stop for bot %s (disabled/removed)", token[:6])
            return
        try:
            # Socket timeout PHẢI dài hơn poll timeout kẻo mất tin đến ở giây cuối.
            r = _api_call("getUpdates", {"timeout": 25}, timeout=35)
        except Exception:
            r = {"ok": False}
        if not r.get("ok"):
            # 408 timeout = không có tin mới (bình thường). Lỗi khác → backoff nhẹ;
            # log lần đầu của chuỗi lỗi kẻo poll chết âm thầm không ai biết.
            code = r.get("error_code")
            if code != 408 and fails == 0:
                logger.warning("Zalo getUpdates lỗi (bot %s…): %s", token[:6], str(r)[:200])
            time.sleep(1 if code == 408 else min(2 + fails, 15))
            fails = 0 if code == 408 else fails + 1
            continue
        fails = 0
        res = r.get("result")
        updates = res if isinstance(res, list) else ([res] if isinstance(res, dict) else [])
        for upd in updates:
            try:
                _handle_update(upd, bot, seen)
            except Exception as exc:
                logger.warning("Zalo update error: %s", exc)


def _handle_update(upd: dict, bot: dict, seen: set[str]) -> None:
    # getUpdates trả cùng khối như webhook: có thể {message:{...}} hoặc
    # {result:{message:{...}}} hoặc {event_name, message:{...}}.
    if not isinstance(upd, dict):
        return
    msg = upd.get("message") or (upd.get("result") or {}).get("message") or {}
    # LOG THÔ mọi tin Zalo (chẩn đoán nhận diện file) — keys + raw cắt ngắn.
    try:
        logger.info("Zalo IN keys=%s raw=%s", list(msg.keys()),
                    json.dumps(msg, ensure_ascii=False)[:600])
    except Exception:
        pass
    mid = str(msg.get("message_id") or "")
    if not mid or mid in seen:
        return
    seen.add(mid)
    if len(seen) > 2000:
        seen.clear()
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id", "")).strip()
    text = (msg.get("text") or "").strip()
    photo_url = msg.get("photo") or msg.get("photo_url") or msg.get("url") or ""
    sender = str((msg.get("from") or {}).get("display_name")
                 or (msg.get("from") or {}).get("name") or "").strip()
    user_id, is_group = _extract_meta(msg)
    # Tên nhóm / chat title (Zalo API: name / display_name / title / …)
    chat_name = str(
        chat.get("name") or chat.get("display_name") or chat.get("title")
        or chat.get("group_name") or chat.get("groupName")
        or chat.get("chat_name") or chat.get("chatName") or ""
    ).strip()
    # Nhóm mà webhook không kèm title → getChat lấy tên thật (không dùng tên người gửi)
    if is_group and not chat_name and chat_id:
        try:
            tok = str((bot or {}).get("token") or "").strip()
            if tok:
                info = resolve_chat(tok, chat_id)
                if info.get("ok") and info.get("name"):
                    chat_name = str(info.get("name") or "").strip()
        except Exception:
            pass
    f_url, f_name, f_id = _extract_file_fields(msg)
    voice_url = _extract_voice_url(msg)
    if not text and not photo_url and not f_url and not f_name and not f_id and not voice_url:
        # Payload lạ (file kiểu mới?) → log thô để chẩn đoán lần sau.
        logger.info("Zalo msg unhandled keys=%s raw=%s", list(msg.keys()),
                    json.dumps(msg, ensure_ascii=False)[:400])
    if chat_id:
        threading.Thread(target=_process_message,
                         args=(text, chat_id, photo_url, bot, sender, f_url, f_name, f_id,
                               user_id, is_group, chat_name, voice_url),
                         daemon=True).start()


def send_message(chat_id: str, text: str, *, rich: bool = True,
                 bot: dict | None = None) -> dict:
    """Gửi text qua Zalo Bot sendMessage (docs bot.zapps.me).

    rich=True (mặc định, trả lời AI):
      - emphasis số/đơn vị (``**…**``) như Telegram
      - **có màu** (Zalo hỗ trợ; Tele không): ``{orange}**29°C**{/orange}``
      - ``parse_mode=markdown``; lỗi → plain

    rich=False: plain (notify hệ thống / account_log — tránh vỡ email/URL).

    Docs: parse_mode markdown hỗ trợ **đậm**, *nghiêng*, {red|orange|yellow|green},
    {big}, {underline}, list…  hoặc text_styles (b/i/c_hex).
    """
    from services.zalo_bot_format import build_send_message_payload
    active = bot if isinstance(bot, dict) else _active_bot()
    payloads = build_send_message_payload(
        str(chat_id), text or "...", bot=active, rich=rich, max_len=_MAX_LEN,
    )
    last: dict = {"ok": False}
    for p in payloads:
        last = _api_call("sendMessage", p)
        if last.get("ok"):
            continue
        # Fallback plain: bỏ parse_mode + strip tag màu / ** nếu server từ chối markup
        plain = str(p.get("text") or "")
        plain = re.sub(r"\{/?\w+\}", "", plain)
        plain = plain.replace("**", "").replace("__", "")
        last = _api_call("sendMessage", {
            "chat_id": str(chat_id), "text": plain[:_MAX_LEN] or "...",
        })
    return last


def _ensure_public_photo_url(photo_url: str) -> str | None:
    """Zalo sendPhoto cần URL http(s) CÔNG KHAI — platform tự fetch ra ẢNH thật.

    - data:image → lưu /images/ + base_url
    - /images/... tương đối → base_url + path
    - http(s) → giữ (sau net_guard)
    Trả None nếu không tạo được URL public (thiếu base_url / bị chặn).
    """
    u = str(photo_url or "").strip()
    if not u:
        return None
    base = _public_base()
    try:
        if u.startswith("data:image"):
            import base64
            import re as _re
            from services.protocol.conversation import save_image_bytes
            m = _re.match(r"data:image/[^;]+;base64,(.+)", u, _re.DOTALL)
            if not m:
                return None
            raw = base64.b64decode(m.group(1))
            rel = save_image_bytes(raw)
            u = str(rel or "")
        if u.startswith("/") and base:
            u = base + u
        elif u.startswith("/") and not base:
            logger.warning("zalo sendPhoto: thiếu base_url cho path %s", u[:80])
            return None
        # Rewrite localhost → public base (Zalo cloud không fetch được LAN)
        if base and ("127.0.0.1" in u or "localhost" in u):
            from urllib.parse import urlparse
            path = urlparse(u).path or ""
            if path:
                u = base.rstrip("/") + path
        if not u.startswith(("http://", "https://")):
            if base and u:
                u = base.rstrip("/") + "/" + u.lstrip("/")
            else:
                return None
        from services import net_guard as _ng
        if not _ng.is_allowed_egress_url(u):
            logger.warning("zalo sendPhoto: URL bị chặn %s", u[:120])
            return None
        return u
    except Exception as exc:
        logger.warning("zalo ensure photo url: %s", exc)
        return None


def send_photo(chat_id: str, photo_url: str, caption: str = "") -> dict:
    """sendPhoto — tin nhắn HÌNH ẢNH thật (photo = URL http công khai).

    Docs: POST /bot{token}/sendPhoto  {chat_id, photo, caption?}
    Platform tải URL → hiển thị ảnh trong chat (không phải tin text link).
    """
    url = _ensure_public_photo_url(photo_url)
    if not url:
        return {"ok": False, "error": "no public photo url (set base_url)"}
    data: dict[str, Any] = {"chat_id": str(chat_id), "photo": url}
    cap = (caption or "").strip()
    if cap:
        data["caption"] = cap[:2000]
    r = _api_call("sendPhoto", data)
    if not r.get("ok"):
        logger.warning("zalo sendPhoto fail chat=%s url=%s resp=%s",
                       chat_id, url[:100], str(r)[:200])
    return r


def send_voice(chat_id: str, voice_url: str) -> dict:
    """sendVoice — tin nhắn THOẠI 1-1 (voice_url phải là URL .aac).

    Docs: POST /bot{token}/sendVoice  {chat_id, voice_url}
    - Chỉ 1-1; truyền chat_id nhóm có thể ok=true nhưng tin không tới nhóm.
    - Không caption; chỉ file âm thanh.
    """
    url = str(voice_url or "").strip()
    if not url:
        return {"ok": False, "error": "empty voice_url"}
    # Platform yêu cầu đuôi .aac
    if not url.lower().split("?", 1)[0].endswith(".aac"):
        logger.warning("sendVoice url không .aac: %s", url[:120])
    return _api_call("sendVoice", {
        "chat_id": str(chat_id),
        "voice_url": url,
    })


def notify_admin(text: str, category: str = "") -> None:
    """account_log 📋 / system 🔔 / newchat 💬 — per-admin toggles."""
    try:
        from services.notifier import classify_notify_category
        cat = classify_notify_category(text, category)
    except Exception:
        cat = str(category or "system").strip().lower() or "system"
    is_account_log = cat == "account_log"
    is_account_update = cat == "account_update"
    is_newchat = cat == "newchat"
    try:
        from services.admin_workspace import admin_entries
        for bot in _bots():
            if not bot.get("enabled", True):
                continue
            if is_newchat:
                if not bot.get("newchat_alert_enabled", True):
                    continue
            else:
                if not bot.get("notify_admin_enabled", True):
                    continue
            if is_account_update and not (
                bot.get("account_update_log_enabled", False)
                or any(e.get("account_update_log_enabled") for e in admin_entries(bot))
            ):
                continue
            if is_account_log and not bot.get("account_log_enabled", True):
                continue
            _current.bot = bot
            targets: list[str] = []
            for e in admin_entries(bot):
                if is_newchat:
                    if e.get("newchat_alert_enabled") is False:
                        continue
                else:
                    if not e.get("notify_enabled", True):
                        continue
                    if is_account_update and not e.get("account_update_log_enabled", False):
                        continue
                    if is_account_log and not e.get("account_log_enabled", True):
                        continue
                cid = str(e.get("chat_id") or "").strip()
                if cid and cid not in targets:
                    targets.append(cid)
            sent = 0
            # Provider / lỗi / chat mới: cùng đậm + màu + cỡ theo admin nhận tin
            for e in admin_entries(bot):
                cid = str(e.get("chat_id") or "").strip()
                if cid not in targets:
                    continue
                try:
                    # rich=True: markdown_color / markdown_size / emphasis của admin
                    if send_message(
                        str(cid), text[:_MAX_LEN], rich=True, bot=bot,
                    ).get("ok"):
                        sent += 1
                except Exception:
                    pass
            if sent == 0 and (
                bot.get("fallback_enabled")
                or any(e.get("fallback_enabled") for e in admin_entries(bot))
            ):
                try:
                    from services.telegram_bot import _try_bot_fallback
                    _try_bot_fallback(bot, text)
                except Exception:
                    pass
    finally:
        _current.bot = None


def _download(url: str) -> bytes | None:
    # URL đến từ webhook/tin nhắn (không tin cậy) → chặn SSRF (net_guard).
    try:
        from services import net_guard
        return net_guard.safe_fetch(url, timeout=30)
    except Exception as exc:
        logger.warning("Zalo download failed: %s", exc)
        return None


def _public_base() -> str:
    """Base URL công khai — Zalo platform fetch photo/voice từ URL này (sendPhoto/sendVoice)."""
    c = config.get()
    return (str(c.get("base_url") or "").strip()
            or str(c.get("telegram_webhook_url") or "").strip()).rstrip("/")


def _wav_to_aac_public_url(wav: bytes) -> str | None:
    """WAV bytes → file .aac công khai (Zalo sendVoice bắt buộc đuôi .aac)."""
    import subprocess
    import tempfile
    import uuid
    from pathlib import Path

    base = _public_base()
    if not base or not wav:
        return None
    out_dir = config.images_dir / "voice"
    out_dir.mkdir(parents=True, exist_ok=True)
    fn = f"{uuid.uuid4().hex}.aac"
    dst = out_dir / fn
    src_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as src:
            src.write(wav)
            src_path = src.name
        proc = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", src_path, "-c:a", "aac", "-b:a", "64k", str(dst),
            ],
            capture_output=True, timeout=90,
        )
        if proc.returncode != 0 or not dst.is_file() or dst.stat().st_size < 32:
            err = (proc.stderr or b"").decode("utf-8", "ignore")[:160]
            logger.warning("zalo wav→aac failed: %s", err)
            try:
                dst.unlink(missing_ok=True)
            except Exception:
                pass
            return None
        return f"{base}/images/voice/{fn}"
    except FileNotFoundError:
        logger.warning("zalo sendVoice: thiếu ffmpeg trong image")
        return None
    except Exception as exc:
        logger.warning("zalo wav→aac lỗi: %s", exc)
        return None
    finally:
        if src_path:
            try:
                Path(src_path).unlink(missing_ok=True)
            except Exception:
                pass


def _audio_url_to_aac_public(url: str) -> str | None:
    """URL audio bất kỳ → .aac public (tải an toàn + ffmpeg). Đã .aac http → dùng luôn."""
    u = str(url or "").strip()
    if not u:
        return None
    path_part = u.lower().split("?", 1)[0]
    if path_part.startswith("http") and path_part.endswith(".aac"):
        return u
    try:
        from services import net_guard
        raw = net_guard.fetch_media(u, timeout=90, max_bytes=15 * 1024 * 1024)
    except Exception as exc:
        logger.warning("zalo fetch audio: %s", exc)
        return None
    if not raw:
        return None
    # speak() trả WAV; audio khác cũng cố convert qua ffmpeg (input sniff)
    return _wav_to_aac_public_url(raw) if raw[:4] == b"RIFF" else _bytes_to_aac_public(raw)


def _bytes_to_aac_public(audio: bytes, suffix: str = ".bin") -> str | None:
    """Audio bytes bất kỳ → .aac public URL."""
    import subprocess
    import tempfile
    import uuid
    from pathlib import Path

    base = _public_base()
    if not base or not audio:
        return None
    out_dir = config.images_dir / "voice"
    out_dir.mkdir(parents=True, exist_ok=True)
    fn = f"{uuid.uuid4().hex}.aac"
    dst = out_dir / fn
    src_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as src:
            src.write(audio)
            src_path = src.name
        proc = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", src_path, "-c:a", "aac", "-b:a", "64k", str(dst),
            ],
            capture_output=True, timeout=90,
        )
        if proc.returncode != 0 or not dst.is_file():
            return None
        return f"{base}/images/voice/{fn}"
    except Exception as exc:
        logger.warning("zalo bytes→aac: %s", exc)
        return None
    finally:
        if src_path:
            try:
                Path(src_path).unlink(missing_ok=True)
            except Exception:
                pass


def _maybe_voice_reply(chat_id: str, user_id: str, reply: str, *, is_group: bool) -> None:
    """TTS → sendVoice (.aac) nếu thread bật tts_reply.

    sendVoice CHỈ 1-1 — nhóm bỏ qua (API không hỗ trợ).
    """
    text = (reply or "").strip()
    if not text or not chat_id or is_group:
        return
    try:
        from services import voice as _voice
        from services.voice import permissions as _vperm
        if not _vperm.wants_voice_reply("zalo", _bot_id(), chat_id, user_id):
            return
        if not _voice.tts_ready():
            return
        from services.voice import session_voice as _sv
        _sid = f"zalo:{_bot_id()}:{chat_id}:{user_id}"
        if not _sv.is_tts_enabled_for_session(_sid):
            return  # TTS bị tắt cho kênh/bot/nhóm/user này
        _pk = f"zalo_{chat_id}:u{user_id}" if user_id else f"zalo_{chat_id}"
        wav = _voice.speak_reply(text[:1000], _pk, session_id=_sid)
        aac_url = _wav_to_aac_public_url(wav)
        if not aac_url:
            logger.warning("zalo voice reply: không tạo được URL .aac (base_url?)")
            return
        r = send_voice(chat_id, aac_url)
        if not r.get("ok"):
            logger.warning("zalo sendVoice fail: %s", str(r)[:200])
    except Exception as exc:
        logger.warning("zalo voice reply loi: %s", str(exc)[:160])


def _handle_pdf(chat_id: str, url: str, name: str = "",
                allow: set[str] | None = None) -> None:
    """Nhận PDF → RAG kiến thức / teacher (Zalo Bot KHÔNG gửi Word/Excel)."""
    from services import pdf_intent as _pi
    # Bỏ word/excel — API không sendDocument
    intents = _pi.allowed_intents(allow) - {_pi.WORD, _pi.EXCEL}
    if not intents:
        full = _pi.allowed_intents(allow) or set()
        if full & {_pi.WORD, _pi.EXCEL}:
            send_message(
                chat_id,
                "📎 Zalo Bot không gửi file Word/Excel (chỉ ảnh + thoại 1-1). "
                "Bật «RAG / tài liệu» hoặc «Giáo viên» để nạp PDF, "
                "hoặc dùng Telegram / Zalo Cá nhân để nhận .docx/.xlsx.",
            )
        return
    _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    data = _download(url)
    if not data:
        send_message(chat_id, "📄 Không tải được file PDF.")
        return
    info = _pi.set_pending(f"zalo:{_bot_id()}:{chat_id}", data, name or "document.pdf")
    send_message(chat_id, _pi.ask_text(name or "PDF", intents, info))


def _zalo_journal(
    *,
    kind: str,
    chat_id: str,
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
            channel="zalo",
            kind=kind,
            user_text=user_text,
            reply_text=str(reply or "")[:800],
            user_id=str(user_id or chat_id),
            source_account=_bot_id(),
            source_peer=str(chat_id),
            status=status,
            error=error,
            duration_ms=int((_time.time() - t0) * 1000) if t0 else 0,
            meta=meta,
        )
    except Exception:
        pass


def _do_pdf_intent(
    chat_id: str,
    pending: dict | None,
    intent: str,
    *,
    grade: int | None = None,
    subject: str | None = None,
    user_id: str = "",
) -> None:
    """PDF: rag_knowledge / rag_teacher. word/excel → báo không hỗ trợ file."""
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
    _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    try:
        if intent in {_pi.WORD, _pi.EXCEL, "word", "excel"}:
            kind = "pdf_excel" if intent in {_pi.EXCEL, "excel"} else "pdf_word"
            reply = (
                "📎 Zalo Bot không gửi file Word/Excel. "
                "Chọn nạp RAG kiến thức / teacher, hoặc dùng Telegram / Zalo Cá nhân."
            )
            status = "blocked"
            err = "zalo_bot_no_file"
            send_message(chat_id, reply)
            return
        if intent == _pi.RAG_TEACHER:
            kind = "pdf_teacher"
            if not grade or not subject:
                reply = "⚠️ Thiếu lớp/môn cho RAG teacher."
                status = "error"
                err = "missing grade/subject"
                send_message(chat_id, reply)
                return
            r = _pi.ingest_teacher(path, grade=int(grade), subject=str(subject), name=name)
            reply = r.get("text") or r.get("error") or "Xong."
            send_message(chat_id, reply)
            return
        # rag_knowledge
        kind = "pdf_rag"
        r = _pi.ingest_knowledge(
            path, name=name, model=_zalo_model(chat_id),
            who=user_id or chat_id, platform="zalo", chat_id=str(chat_id),
        )
        parts = []
        if r.get("summary"):
            from services import pdf_images as _pimg
            parts.append(_pimg.humanize_markers(r["summary"]))
        if r.get("text"):
            parts.append(r["text"])
        if not r.get("ok") and r.get("error"):
            parts.append(f"⚠️ {r['error']}")
            status = "error"
            err = str(r.get("error") or "")[:200]
        if not parts:
            reply = "❌ Không đọc được nội dung PDF (có thể là ảnh chụp)."
            send_message(chat_id, reply)
            return
        reply = "\n\n".join(parts)
        send_message(chat_id, reply)
        try:
            from services import pdf_images as _pimg
            base = _public_base()
            for cap, iid in _pimg.find_markers(r.get("summary") or "")[:4]:
                rel = _pimg.serve_rel(iid)
                if rel and base:
                    send_photo(
                        chat_id, f"{base}{rel}",
                        caption=(cap or "Hình trong tài liệu")[:200],
                    )
        except Exception as exc:
            logger.warning("zalo gửi ảnh marker PDF lỗi: %s", exc)
    except Exception as e:
        status = "error"
        err = str(e)[:200]
        reply = f"❌ Lỗi xử lý PDF: {e}"
        logger.warning("zalo pdf intent %s error: %s", intent, e)
        send_message(chat_id, reply)
    finally:
        _zalo_journal(
            kind=kind, chat_id=chat_id, user_id=user_id,
            user_text=f"PDF:{name} → {intent}", reply=reply,
            status=status, error=err, t0=t0, meta={"file": name, "intent": intent},
        )
        try:
            os.unlink(path)
        except Exception:
            pass


def _do_photo_request(
    chat_id: str,
    file_data: bytes,
    request: str,
    allow: set | None = None,
    *,
    intent: str | None = None,
    user_id: str = "",
) -> None:
    """Xử lý ảnh: rag_knowledge | rag_teacher | analyze | generate (img2img)."""
    import time as _time
    from services import photo_intent as _phi
    t0 = _time.time()
    kind = "photo_analyze"
    reply = ""
    status = "ok"
    err = ""
    _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    try:
        it = intent or (
            _phi.GENERATE if _phi.classify(request) == _phi.GENERATE else _phi.ANALYZE
        )
        allowed = _phi.allowed_intents(allow)
        if it not in allowed and allow is not None:
            status = "blocked"
            err = f"intent {it} not allowed"
            return

        if it == _phi.GENERATE:
            kind = "photo_generate"
            out = _phi.generate_from_photo(file_data, request, channel="zalo")
            try:
                from services import net_guard
                out = net_guard.filter_agent_output(out if isinstance(out, dict) else {})
            except Exception:
                pass
            url = out.get("image_url")
            reply = (out.get("text") or "Đây ạ 🎨")[:1000]
            if url:
                if send_photo(chat_id, str(url), caption=reply).get("ok"):
                    return
                reply = out.get("text") or (
                    "Em tạo được ảnh nhưng sendPhoto chưa được (cần base_url công khai)."
                )
                send_message(chat_id, reply)
                return
            reply = out.get("text") or "Em chưa tạo được ảnh ạ."
            send_message(chat_id, reply)
            return

        if it == _phi.RAG_KNOWLEDGE:
            kind = "photo_rag"
            r = _phi.ingest_knowledge_from_photo(
                file_data, prompt=request, who=user_id or chat_id,
                platform="zalo", chat_id=str(chat_id), channel="zalo",
            )
            reply = r.get("text") or r.get("error") or "Xong."
            send_message(chat_id, reply)
            return

        if it == _phi.RAG_TEACHER:
            kind = "photo_rag"
            reply = "⚠️ RAG teacher ảnh cần lớp + môn (vd: `5 toán`)."
            send_message(chat_id, reply)
            return

        # analyze — nhánh vision
        kind = "photo_analyze"
        answer = _phi.analyze_photo(file_data, request, channel="zalo")
        reply = answer or ""
        send_message(chat_id, answer)
    except Exception as exc:
        status = "error"
        err = str(exc)[:200]
        raise
    finally:
        _zalo_journal(
            kind=kind, chat_id=chat_id, user_id=user_id,
            user_text=(request or "[ảnh]")[:500], reply=reply,
            status=status, error=err, t0=t0,
        )


async def handle_webhook(request) -> dict:
    """Nhận webhook Zalo (POST). Verify secret header, tách message, xử lý AI ở
    background rồi trả ngay {ok:true}."""
    try:
        hdr = request.headers.get("X-Bot-Api-Secret-Token", "")
        body = await request.json()
    except Exception:
        return {"ok": False}
    # Xác định bot theo secret (đa-token); chỉ 1 bot thì fallback lenient.
    bots = [b for b in _bots() if b.get("enabled", True)]
    bot = next((b for b in bots if _webhook_secret_for(str(b.get("token", "")).strip()) == hdr), None)
    if bot is None:
        if len(bots) == 1:
            bot = bots[0]
        else:
            logger.warning("Zalo webhook bad/ambiguous secret")
            return {"ok": False}
    result = (body or {}).get("result") or {}
    msg = result.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id", "")).strip()
    text = (msg.get("text") or "").strip()
    photo_url = msg.get("photo") or msg.get("photo_url") or msg.get("url") or ""
    sender = str((msg.get("from") or {}).get("display_name")
                 or (msg.get("from") or {}).get("name") or "").strip()
    user_id, is_group = _extract_meta(msg)
    chat_name = str(
        chat.get("name") or chat.get("display_name") or chat.get("title")
        or chat.get("group_name") or ""
    ).strip()
    f_url, f_name, f_id = _extract_file_fields(msg)
    voice_url = _extract_voice_url(msg)
    if not chat_id:
        return {"ok": True}
    threading.Thread(target=_process_message,
                     args=(text, chat_id, photo_url, bot, sender, f_url, f_name, f_id,
                           user_id, is_group, chat_name, voice_url),
                     daemon=True).start()
    return {"ok": True}


def _extract_meta(msg: dict) -> tuple[str, bool]:
    """Lấy (user_id người gửi, có phải NHÓM) từ message Zalo Bot. Nhóm nhận biết
    qua chat.chat_type ('group'/1) — dùng cho tầng lọc User ID + bộ lọc tag."""
    frm = msg.get("from") if isinstance(msg.get("from"), dict) else {}
    user_id = str(frm.get("id") or "").strip()
    chat = msg.get("chat") if isinstance(msg.get("chat"), dict) else {}
    ctype = str(chat.get("chat_type") or chat.get("type") or msg.get("type") or "").strip().lower()
    is_group = ctype in {"group", "grouptype", "1"} or str(msg.get("type") or "") == "1"
    return user_id, is_group


def _extract_file_fields(msg: dict) -> tuple[str, str, str]:
    """Tìm (url, tên, file_id) file đính kèm — Zalo có nhiều biến thể payload:
    document{url|file_url|file_name|file_id}, hoặc file_url/file_name/file_id
    nằm phẳng trong message."""
    doc = msg.get("document")
    doc = doc if isinstance(doc, dict) else {}
    url = str(doc.get("url") or doc.get("file_url") or msg.get("file_url") or "").strip()
    name = str(doc.get("file_name") or doc.get("filename") or msg.get("file_name") or "").strip()
    fid = str(doc.get("file_id") or msg.get("file_id") or "").strip()
    return url, name, fid


def _extract_voice_url(msg: dict) -> str:
    """URL voice note inbound (nếu platform gửi)."""
    if not isinstance(msg, dict):
        return ""
    v = msg.get("voice_url") or msg.get("voice")
    if isinstance(v, dict):
        return str(v.get("url") or v.get("voice_url") or v.get("file_url") or "").strip()
    if isinstance(v, str):
        return v.strip()
    return ""


def _process_message(text: str, chat_id: str, photo_url: str = "", bot: dict | None = None,
                     sender: str = "", file_url: str = "", file_name: str = "",
                     file_id: str = "", user_id: str = "", is_group: bool = False,
                     chat_name: str = "", voice_url: str = "") -> None:
    if bot is not None:
        _current.bot = bot  # luồng mới → gắn lại ngữ cảnh bot để gửi đúng token

    # Voice note → STT → coi như tin chữ (giống Telegram).
    if voice_url and not (text or "").strip():
        try:
            from services import voice as _voice
            raw = _download(voice_url)
            if raw:
                text = _voice.listen(raw, "aac" if voice_url.lower().endswith(".aac") else "m4a")
                logger.info("zalo voice->text (%d bytes): %.60s", len(raw or b""), text)
        except Exception as exc:
            logger.warning("zalo STT loi: %s", str(exc)[:160])
            if chat_id:
                send_message(chat_id, f"🎤 Em nghe không rõ ạ 😥 ({str(exc)[:120]})")
            return
        if not text:
            if chat_id:
                send_message(chat_id, "🎤 Em không nghe ra chữ nào trong đoạn ghi âm ạ.")
            return

    # Blacklist THEO BOT: nhóm/cá nhân bị loại trên bot này → bỏ qua hoàn toàn.
    from services import channel_activity as _ca
    if chat_id and _ca.is_blacklisted("zalo", chat_id, user_id, account=_bot_id()):
        return
    # Ghi LẦN GẦN NHẤT (bot/Chat ID/User ID) để trang quản lý hiển thị.
    if chat_id:
        _ca.record("zalo", account=_bot_id(), chat_id=chat_id, user_id=user_id,
                   user_name=sender, chat_name=chat_name, is_group=is_group,
                   text=text or ("[ảnh]" if photo_url else "") or ("[voice]" if voice_url else "") or (file_name or ""))

    # Admin workspace (đặt tên bot / lưu người lạ) — độc lập từng admin thread
    if chat_id and text and _is_admin_chat(chat_id):
        try:
            from services.admin_workspace import handle_admin_text
            _ar = handle_admin_text("zalo", chat_id, text)
            if _ar:
                send_message(chat_id, _ar)
                return
        except Exception as exc:
            logger.warning("zalo admin workspace: %s", exc)

    # Kiểm soát truy cập NGAY TỪ ĐẦU (áp cho cả ảnh, không chỉ text):
    # - chat có bản ghi lọc = đã cấp phép (không cần nằm trong Chat IDs);
    # - người lạ → báo admin + chặn (trừ lệnh /id để họ lấy ID gửi admin).
    # - trong NHÓM: quyền = giao(nhóm, user) — tầng lọc User ID theo từng nhóm.
    from services.agent import capabilities as _caps
    _allow = _caps.allowed_groups_for_member("zalo", _bot_id(), chat_id, user_id) if chat_id else None
    allowed = [str(c) for c in _chat_ids()]
    _is_admin = bool(chat_id and _is_admin_chat(chat_id))
    if _is_admin and chat_id and chat_id not in allowed:
        allowed.append(str(chat_id))
    _low = (text or "").strip().lower()
    # Trong NHÓM tin luôn kèm prefix @tag bot (nền tảng bắt buộc tag mới giao tin)
    # → so khớp substring chứ không chỉ equality, kẻo "/id" trong nhóm bị trượt.
    _is_id = _low in {"/id", "id", "chatid"} or "/id" in _low or "chatid" in _low \
        or ("chat id" in _low and len(_low) <= 60)
    # Zalo OA nhóm: nền tảng CHỈ đẩy tin khi đã @tag bot → tin tới = đã tag.
    # 1-1: luôn coi là tagged (không cần @). Keyword settings = lớp phụ.
    _req_m, _kw_m = (False, "")
    try:
        if chat_id:
            _req_m, _kw_m = _caps.mention_required_for("zalo", _bot_id(), chat_id)
    except Exception:
        pass
    _native_txt = bool(
        is_group and (
            str(_bot_id()) in (text or "")
            or (_bot_label() and _bot_label().lower() in (text or "").lower())
            or "@" in (text or "")
        )
    )
    _tagged_early = _caps.tag_gate_allows(
        required=_req_m,
        keyword=_kw_m,
        text=text or "",
        native_tagged=_native_txt or (not is_group),
        platform_group_delivery=bool(is_group),
    )
    if not _req_m:
        _tagged_early = True
    if chat_id and _allow is None and chat_id not in allowed and not _is_admin:
        _alert_new_chat(
            chat_id, sender, text, served=not allowed,
            user_id=user_id, is_group=is_group, tagged=_tagged_early,
            chat_name=chat_name,
        )
        if allowed and not _is_id:
            send_message(chat_id, "⛔ Không được phép.")
            return
    elif chat_id:
        try:
            from services import channel_contacts as _cc
            _cc.upsert(
                "zalo", _bot_id(), chat_id, user_id=user_id,
                display_name=sender, chat_name=chat_name,
                is_group=is_group, text=text or "",
            )
        except Exception:
            pass
    if _is_id and chat_id:
        _id_info = (f"🆔 Chat ID: {chat_id} ({'nhóm' if is_group else 'cá nhân'})\n"
                    + (f"📛 Tên nhóm: {chat_name}\n" if is_group and chat_name else "")
                    + f"👤 User ID người gửi: {user_id or '(không rõ)'}\n"
                    + (f"👤 Tên người: {sender}\n" if sender else "")
                    + f"Bot: Zalo {_bot_label()}")
        if not _notify_all_admins(
                f"🆔 Yêu cầu /id từ {'nhóm' if is_group else 'chat'}:\n{_id_info}"):
            send_message(chat_id, _id_info)
        return

    # Chuyển tiếp webhook — tagged = keyword / text @bot / platform group delivery
    _req_fw, _kw_fw = _caps.mention_required_for("zalo", _bot_id(), chat_id)
    _tagged = _caps.tag_gate_allows(
        required=True,  # chỉ tính cờ tagged, không chặn ở đây
        keyword=_kw_fw,
        text=text or "",
        native_tagged=_native_txt or (not is_group),
        platform_group_delivery=bool(is_group),
    )
    if _caps.forward_event("zalo", _bot_id(), chat_id, user_id, {
        "platform": "zalo", "bot": _bot_id(), "chat_id": chat_id,
        "user_id": user_id, "sender": sender, "is_group": is_group,
        "text": text or "", "tagged": _tagged, "photo_url": photo_url or "",
        "file_url": file_url or "", "file_name": file_name or "",
    }, tagged=_tagged):
        return

    # Bộ lọc TAG (nhóm): required + keyword rỗng → tin OA đã tới = đã tag (không im).
    # Keyword có → phải khớp (hoặc text chứa id/label bot).
    if is_group and chat_id:
        _req, _kw = _caps.mention_required_for("zalo", _bot_id(), chat_id)
        if _req and not _caps.tag_gate_allows(
            required=True,
            keyword=_kw,
            text=text or "",
            native_tagged=_native_txt,
            platform_group_delivery=True,
        ):
            logger.info(
                "zalo skip (cần tag): chat=%s kw=%r text=%.80s",
                chat_id, _kw, text or "",
            )
            return

    # PDF chờ: RAG kiến thức / teacher (word/excel → báo không hỗ trợ file)
    from services import pdf_intent as _pi
    _pkey = f"zalo:{_bot_id()}:{chat_id}"
    if text and chat_id and _pi.has_pending(_pkey):
        _pend = _pi.get_pending(_pkey) or {}
        _full_allow = _pi.allowed_intents(_allow)
        if _pend.get("stage") == "teacher_meta":
            meta = _pi.parse_teacher_meta(text)
            if not meta:
                send_message(chat_id, _pi.ASK_TEACHER)
                return
            _do_pdf_intent(
                chat_id, _pi.pop_pending(_pkey), _pi.RAG_TEACHER,
                grade=meta["grade"], subject=meta["subject"], user_id=user_id,
            )
            return
        # parse theo intents bot có thể làm (RAG); word/excel vẫn parse được bằng keyword
        _parse_allow = _full_allow | {_pi.WORD, _pi.EXCEL}
        _intent = _pi.parse_intent(text, _parse_allow if _parse_allow else None)
        if _intent:
            if _intent == "rag":
                _intent = _pi.RAG_KNOWLEDGE
            # Word/Excel: handler báo không hỗ trợ file
            if _intent in {_pi.WORD, _pi.EXCEL}:
                _do_pdf_intent(chat_id, _pi.pop_pending(_pkey), _intent, user_id=user_id)
                return
            if _intent not in _full_allow:
                return
            if _intent == _pi.RAG_TEACHER:
                _pi.update_pending(_pkey, stage="teacher_meta", intent=_pi.RAG_TEACHER)
                send_message(chat_id, _pi.ASK_TEACHER)
                return
            _do_pdf_intent(chat_id, _pi.pop_pending(_pkey), _intent, user_id=user_id)
            return

    # Ảnh chờ: menu 1–4 / hỏi prompt / teacher meta (giống Telegram)
    from services import photo_intent as _phi
    _phkey = f"zalo:{_bot_id()}:{chat_id}"
    if text and chat_id and _phi.has_pending(_phkey):
        _pend = _phi.get_pending(_phkey) or {}
        _allowed_ph = _phi.allowed_intents(_allow)
        stage = str(_pend.get("stage") or "choose")
        if stage == "teacher_meta":
            meta = _pi.parse_teacher_meta(text)
            if not meta:
                send_message(chat_id, _phi.ASK_TEACHER)
                return
            full = _phi.pop_pending_full(_phkey)
            if full and full.get("data"):
                r = _phi.ingest_teacher_from_photo(
                    full["data"], grade=meta["grade"], subject=meta["subject"],
                    channel="zalo",
                )
                send_message(chat_id, r.get("text") or r.get("error") or "Xong.")
            return
        if stage == "need_prompt":
            intent = str(_pend.get("intent") or _phi.ANALYZE)
            full = _phi.pop_pending_full(_phkey)
            if full and full.get("data"):
                _do_photo_request(
                    chat_id, full["data"], text.strip(), _allow,
                    intent=intent, user_id=user_id,
                )
            return
        # stage=choose
        intent = _phi.parse_intent(text, _allowed_ph)
        if intent:
            if intent not in _allowed_ph:
                return
            if intent == _phi.RAG_TEACHER:
                _phi.update_pending(_phkey, stage="teacher_meta", intent=intent)
                send_message(chat_id, _phi.ASK_TEACHER)
                return
            if _phi.needs_prompt(intent, text):
                _phi.update_pending(_phkey, stage="need_prompt", intent=intent)
                send_message(
                    chat_id,
                    _phi.ASK_PROMPT_GENERATE if intent == _phi.GENERATE else _phi.ASK_PROMPT_ANALYZE,
                )
                return
            full = _phi.pop_pending_full(_phkey)
            if full and full.get("data"):
                _do_photo_request(
                    chat_id, full["data"], text.strip(), _allow,
                    intent=intent, user_id=user_id,
                )
            return

    # File đính kèm → chỉ PDF tóm tắt (RAG). Không Word / không file khác.
    from urllib.parse import urlparse
    _pdf_name = (file_name or "").lower().endswith(".pdf") or \
        (text or "").strip().lower().endswith(".pdf")
    _url_pdf = ""
    for _u in (file_url, photo_url):
        if _u and urlparse(str(_u)).path.lower().endswith(".pdf"):
            _url_pdf = str(_u)
            break
    if _url_pdf or (_pdf_name and (file_url or file_id or photo_url)):
        u = _url_pdf or file_url or photo_url
        if not u and file_id:
            r = _api_call("getFile", {"file_id": file_id})
            fp = ((r.get("result") or {}).get("file_path") or "") if r.get("ok") else ""
            if fp:
                u = fp if str(fp).startswith("http") else f"{ZALO_API}/file/bot{_bot_token()}/{fp}"
        if u:
            _handle_pdf(chat_id, str(u), file_name or "", _allow)
            return
        send_message(chat_id, "📄 Em thấy file PDF nhưng không lấy được đường tải, anh/chị gửi lại giúp em nhé.")
        return
    if (file_url or file_name or file_id) and not photo_url:
        send_message(
            chat_id,
            "📎 Zalo Bot không nhận/gửi file (API chỉ hỗ trợ ảnh + thoại 1-1). "
            f"File: {file_name or 'không rõ'}. Gửi ảnh hoặc PDF để tóm tắt nhé.",
        )
        return

    # Ảnh: không caption → menu 1–4; có caption → parse intent / hỏi prompt nếu cần.
    if photo_url:
        _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        data = _download(photo_url)
        if not data:
            send_message(chat_id, "📷 Không tải được ảnh.")
            return
        caption = (text or "").strip()
        _allowed_ph = _phi.allowed_intents(_allow)
        if not caption:
            _phi.set_pending(_phkey, data)
            send_message(chat_id, _phi.ask_text(_allowed_ph))
            return
        intent = _phi.parse_intent(caption, _allowed_ph) or (
            _phi.GENERATE if _phi.classify(caption) == _phi.GENERATE else _phi.ANALYZE
        )
        if intent not in _allowed_ph and _allow is not None:
            if intent == _phi.GENERATE:
                return
        if intent == _phi.RAG_TEACHER:
            _phi.set_pending(_phkey, data, stage="teacher_meta", intent=intent)
            send_message(chat_id, _phi.ASK_TEACHER)
            return
        if intent in {_phi.ANALYZE, _phi.GENERATE} and _phi.needs_prompt(intent, caption):
            _phi.set_pending(_phkey, data, stage="need_prompt", intent=intent)
            send_message(
                chat_id,
                _phi.ASK_PROMPT_GENERATE if intent == _phi.GENERATE else _phi.ASK_PROMPT_ANALYZE,
            )
            return
        _do_photo_request(chat_id, data, caption, _allow, intent=intent, user_id=user_id)
        return

    if not text:
        return

    _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    # CHUNG orchestrator với Telegram — cùng persona/memory/capability/setting.
    try:
        from services.agent import orchestrate
        try:
            from services.admin_workspace import ha_fastpath_for_chat as _ha_fp
            _fp = _ha_fp(_active_bot(), chat_id)
        except Exception:
            _fp = bool(_active_bot().get("ha_fastpath", True))
        _model = _zalo_model(chat_id)
        # Nhóm: mỗi USER một phiên riêng; 1-1 giữ key cũ (không mất lịch sử).
        _skey = f"zalo_{chat_id}"
        try:
            from services.config import config as _c2
            if is_group and user_id and getattr(_c2, "group_user_isolation", True):
                _skey = f"zalo_{chat_id}:u{user_id}"
        except Exception:
            pass
        out = orchestrate(text, _skey, allow=_allow, ha_fastpath=_fp, model=_model)
        try:
            from services import net_guard
            out = net_guard.filter_agent_output(out if isinstance(out, dict) else {})
        except Exception:
            pass
        if out.get("silent"):
            return  # thread lọc yêu cầu chức năng bị tắt → bỏ qua, không nhắn gì
        reply = (out.get("text") or "").strip() or "..."
        image_url = out.get("image_url")
        sent_photo = False
        sent_voice = False
        if image_url:
            if send_photo(chat_id, str(image_url), caption=reply[:1000]).get("ok"):
                sent_photo = True
            else:
                reply = (reply + "\n(em tạo ảnh xong nhưng sendPhoto lỗi — kiểm tra base_url)").strip()
        # Thoại outbound: chỉ sendVoice .aac 1-1 (không dán URL)
        audio_url = out.get("audio_url") or ""
        audio_path = out.get("audio_path") or ""
        if (audio_url or audio_path) and not is_group:
            aac = None
            if audio_path:
                try:
                    from pathlib import Path
                    raw = Path(str(audio_path)).read_bytes()
                    aac = _wav_to_aac_public_url(raw) if raw[:4] == b"RIFF" else _bytes_to_aac_public(raw)
                except Exception as exc:
                    logger.warning("zalo audio_path: %s", exc)
            elif audio_url:
                aac = _audio_url_to_aac_public(str(audio_url))
            if aac and send_voice(chat_id, aac).get("ok"):
                sent_voice = True
            elif audio_url or audio_path:
                reply = (reply + "\n(em có audio nhưng chỉ gửi thoại .aac 1-1)").strip()
        if out.get("video_url") or out.get("video_path"):
            if not sent_photo and not sent_voice:
                reply = (reply + "\n(Zalo Bot không gửi video — chỉ ảnh + thoại 1-1)").strip()
        if out.get("doc_path"):
            # Zalo Bot API không hỗ trợ gửi file — hướng người dùng sang kênh khác
            from pathlib import Path as _P
            _fn = _P(str(out["doc_path"])).name
            reply = (reply + f"\n(File {_fn} đã lưu — Zalo Bot không gửi được file; "
                     "anh/chị nhận qua Telegram hoặc Zalo Cá nhân giúp em ạ)").strip()
        if sent_photo or sent_voice:
            # Ảnh đã gửi: TTS thêm nếu bật tts_reply (1-1) và chưa gửi voice agent
            if sent_photo and not sent_voice:
                _maybe_voice_reply(chat_id, user_id, reply, is_group=is_group)
            return
        choices = out.get("choices") or []
        if choices and not any(out.get(k) for k in ("image_url", "video_url", "audio_url")):
            try:
                from services.agent import ask_choices as _ask
                reply = _ask.format_numbered(reply, choices)
            except Exception:
                pass
        send_message(chat_id, reply)
        # Text → TTS sendVoice (.aac) 1-1 nếu bật «Trả lời bằng giọng nói»
        _maybe_voice_reply(chat_id, user_id, reply, is_group=is_group)
        return
    except Exception as exc:
        logger.warning("Zalo orchestrator error %s: %s", chat_id, exc)

    # Fallback: gọi thẳng gateway.
    base_url = str(config.get().get("api_base_url", "")).strip().rstrip("/") or "http://127.0.0.1/v1"
    try:
        payload = {"model": _zalo_model(chat_id),
                   "messages": [{"role": "user", "content": text}], "stream": False,
                   "x_channel": "zalo"}
        if _allow is not None:
            # Fallback cũng phải mang bộ lọc — kẻo orchestrator lỗi là gateway
            # tự bật HA/ssh/search cho thread bị cấm.
            payload["x_allowed_groups"] = sorted(_allow)
            payload["x_no_smart_home"] = "homeassistant" not in _allow
        req = urllib.request.Request(f"{base_url}/chat/completions",
                                     data=json.dumps(payload).encode(),
                                     headers={"Authorization": f"Bearer {config.auth_key}",
                                              "Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=300)
        reply = json.loads(resp.read().decode()).get("choices", [{}])[0].get("message", {}).get("content", "")
        reply = (reply or "").strip() or "⏳ Hệ thống bận, thử lại."
        send_message(chat_id, reply)
        _maybe_voice_reply(chat_id, user_id, reply, is_group=is_group)
    except Exception as exc:
        logger.warning("Zalo AI error %s: %s", chat_id, exc)
        send_message(chat_id, "⏳ Hệ thống bận, thử lại.")


def get_status() -> dict:
    bots = _bots()
    alive = sum(1 for th in _poll_threads.values() if th.is_alive())
    return {
        "configured": bool(bots),
        "mode": "long-polling",
        "polling": alive > 0,
        "bots_count": len(bots),
        "bots_polling": alive,
    }
