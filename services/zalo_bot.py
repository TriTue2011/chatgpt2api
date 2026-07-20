"""Zalo Bot — kênh chat AI 2 chiều qua chatgpt2api, GIỐNG Telegram.

Zalo Bot API là bản clone Telegram Bot API: base
`https://bot-api.zaloplatforms.com/bot<token>/<method>`, token nằm trong path,
response {ok, result, description, error_code}. Điểm khác:
- Webhook payload bọc trong `result`: {ok, result:{event_name, message:{from,chat,
  text,photo,caption,url,voice_url,sticker,message_id,date}}}. chat.id là chuỗi.
- Xác thực webhook bằng header `X-Bot-Api-Secret-Token` (secret đã đăng ký).
- sendMessage.text tối đa 2000 ký tự; sendPhoto.photo là URL ảnh.
- NHÓM (chat_type GROUP): nền tảng CHỈ giao tin cho bot khi tin @tag bot —
  tin nhóm không tag KHÔNG BAO GIỜ tới getUpdates/webhook (không cấu hình được).
  Muốn lấy Chat ID nhóm: vào nhóm @tag bot rồi nhắn "/id".

Dùng CHUNG orchestrator (services.agent.orchestrate) + CHUNG Cloudflare
(telegram_webhook_url) như Telegram → cùng "tab" cài đặt, cùng agent/setting.
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

_MD_BOLD_DOUBLE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)


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


def _zalo_model() -> str:
    return str(_active_bot().get("ai_model", "")).strip() or "cx/auto"


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
    """Tên hiển thị của bot qua getMe — cache theo token (lỗi cũng cache '' để
    không gọi lại liên tục; restart sẽ thử lại). Zalo Bot API là Telegram-clone
    nên thử lần lượt các field tên có thể gặp."""
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
        name = str(res.get("account_name") or res.get("display_name")
                   or res.get("first_name") or res.get("name")
                   or res.get("username") or "").strip()
    except Exception as exc:
        logger.warning("Zalo getMe lỗi: %s", exc)
    _bot_name_cache[token] = name
    return name


def get_bot_names() -> dict[str, str]:
    """Map bot_id → tên bot cho MỌI bot đã cấu hình (kể cả đang tắt) — UI dùng
    hiển thị TÊN thay mã số. Bot getMe lỗi → bỏ qua (UI fallback mã số)."""
    out: dict[str, str] = {}
    for b in _bots():
        token = str(b.get("token", "")).strip()
        if not token:
            continue
        name = _fetch_bot_name(token)
        if name:
            out[token.split(":", 1)[0].strip()] = name
    return out


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
        return bool(send_message(admin, text).get("ok"))
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
    """Báo MỌI admin của bot nhận tin; hỏi lưu riêng từng admin."""
    c = config.get()
    if not bool(c.get("zalo_newchat_alert_enabled", True)):
        return
    # Toggle RIÊNG bot này (áp cho cả admin_threads của nó) — tắt là im.
    if not bool((_active_bot() or {}).get("newchat_alert_enabled", True)):
        return
    try:
        from services import channel_contacts as _cc
        from services import admin_workspace as _aw
        ok, rec = _cc.should_alert_new(
            "zalo", _bot_id(), chat_id,
            user_id=user_id, is_group=is_group, tagged=tagged,
            display_name=sender, chat_name=chat_name, text=text or "",
        )
        if not ok:
            return
        base = _cc.format_alert(rec, served=served, text=text or "")
        admins = _admin_ids_for_bot()
        sent = 0
        if admins:
            prev = _cur_bot()
            try:
                for aid in admins:
                    bl = _aw.bot_display_name("zalo", _bot_id(), aid)
                    msg = base.replace(
                        f"bot **{_cc.bot_label('zalo', _bot_id())}**",
                        f"bot **{bl}**",
                        1,
                    )
                    msg += _aw.start_save_prompt("zalo", aid, rec)
                    if _send_admin_thread(aid, msg):
                        sent += 1
            finally:
                _current.bot = prev
        if not sent:
            # Không có admin / gửi fail hết (Chat ID Zalo theo từng bot) →
            # fallback notifier đa kênh, kẻo alert rơi lặng lẽ.
            try:
                from services.notifier import notify_admin as _notify
                _notify(base + "\n(Fallback đa kênh — bot này chưa gửi được admin thread nào.)")
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
    # Tên nhóm / chat title (Zalo API: name / display_name / title)
    chat_name = str(
        chat.get("name") or chat.get("display_name") or chat.get("title")
        or chat.get("group_name") or ""
    ).strip()
    f_url, f_name, f_id = _extract_file_fields(msg)
    if not text and not photo_url and not f_url and not f_name and not f_id:
        # Payload lạ (file kiểu mới?) → log thô để chẩn đoán lần sau.
        logger.info("Zalo msg unhandled keys=%s raw=%s", list(msg.keys()),
                    json.dumps(msg, ensure_ascii=False)[:400])
    if chat_id:
        threading.Thread(target=_process_message,
                         args=(text, chat_id, photo_url, bot, sender, f_url, f_name, f_id,
                               user_id, is_group, chat_name),
                         daemon=True).start()


def _to_zalo_markdown(text: str) -> str:
    out = _MD_BOLD_DOUBLE.sub(r"*\1*", text or "")
    out = _MD_HEADING.sub("", out)
    return out


def send_message(chat_id: str, text: str) -> dict:
    text = text or "..."
    # Zalo giới hạn 2000 ký tự/tin → cắt khúc, gửi nhiều tin.
    chunks = [text[i:i + _MAX_LEN] for i in range(0, len(text), _MAX_LEN)] or ["..."]
    last = {"ok": False}
    for ch in chunks[:6]:
        last = _api_call("sendMessage", {
            "chat_id": str(chat_id), "text": _to_zalo_markdown(ch), "parse_mode": "markdown",
        })
        if not last.get("ok"):
            last = _api_call("sendMessage", {"chat_id": str(chat_id), "text": ch})
    return last


def send_photo(chat_id: str, photo_url: str, caption: str = "") -> dict:
    """Zalo sendPhoto nhận URL ảnh (không upload multipart như Telegram)."""
    data = {"chat_id": str(chat_id), "photo": photo_url}
    if caption:
        data["caption"] = caption[:2000]
    return _api_call("sendPhoto", data)


def notify_admin(text: str, category: str = "") -> None:
    """Báo tới admin qua MỌI bot Zalo đang bật, mỗi bot gửi tới chat_ids của nó
    (song song notify Telegram). Best-effort — không raise.

    Mỗi bot có toggle RIÊNG (độc lập giữa các tài khoản): `notify_admin_enabled`
    tắt là bot đó im hẳn; `category="account_log"` xét thêm `account_log_enabled`."""
    try:
        from services.agent import capabilities as _caps
        for bot in _bots():
            if not bot.get("enabled", True):
                continue
            if not bot.get("notify_admin_enabled", True):
                continue
            if category == "account_log" and not bot.get("account_log_enabled", True):
                continue
            _current.bot = bot
            bid = _bot_id()
            for cid in (bot.get("chat_ids") or []):
                # Chat có bộ lọc chức năng = thread hạn chế → KHÔNG gửi cảnh báo hệ thống.
                if _caps.allowed_groups_for_bot("zalo", bid, str(cid)) is not None:
                    continue
                try:
                    send_message(str(cid), text[:_MAX_LEN])
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
    """Base URL công khai để tạo link tải file (Zalo không upload multipart được)."""
    c = config.get()
    return (str(c.get("base_url") or "").strip()
            or str(c.get("telegram_webhook_url") or "").strip()).rstrip("/")


def _handle_pdf(chat_id: str, url: str, name: str = "",
                allow: set[str] | None = None) -> None:
    """Nhận PDF (Zalo cấp url) → lưu hàng đợi + HỎI ý định (1=RAG / 2=Word).
    `allow` = bộ lọc chức năng của thread — chỉ chào các lựa chọn được phép."""
    from services import pdf_intent as _pi
    intents = _pi.allowed_intents(allow)
    if not intents:
        return  # thread lọc không có nhóm tài liệu → bỏ qua PDF, không nhắn gì
    _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    data = _download(url)
    if not data:
        send_message(chat_id, "📄 Không tải được file PDF.")
        return
    info = _pi.set_pending(f"zalo:{_bot_id()}:{chat_id}", data, name or "document.pdf")
    send_message(chat_id, _pi.ask_text(name or "PDF", intents, info))


def _serve_docx_link(chat_id: str, docx_path: str, how: str) -> None:
    """Zalo Bot API không upload file trực tiếp → phục vụ .docx qua /images/docs/."""
    import uuid
    out_dir = config.images_dir / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    fn = f"{uuid.uuid4().hex}.docx"
    with open(docx_path, "rb") as f:
        (out_dir / fn).write_bytes(f.read())
    base = _public_base()
    link = f"{base}/images/docs/{fn}" if base else f"/images/docs/{fn}"
    send_message(chat_id, f"📝 Bản Word ({how}) — bấm để tải về:\n{link}")


def _do_pdf_intent(chat_id: str, pending: dict | None, intent: str) -> None:
    """Xử lý PDF chờ theo ý định: 'word' (pdf2docx→link) / 'rag' (markitdown+AI tóm tắt)."""
    if not pending:
        return
    import os
    path = pending["path"]
    _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    docx_tmp = (path[:-4] if path.endswith(".pdf") else path) + ".docx"
    try:
        if intent == "word":
            from services.pdf_to_word import convert_pdf_to_docx
            r = convert_pdf_to_docx(path, docx_tmp)
            if not r.get("ok"):
                send_message(chat_id, f"⚠️ Không chuyển được sang Word: {str(r.get('error', ''))[:150]}")
                return
            how = "giữ layout" if r.get("method") == "layout" else "OCR (PDF scan)"
            _serve_docx_link(chat_id, docx_tmp, how)
        else:
            from services.pdf_intent import summarize_pdf
            s = summarize_pdf(path, _zalo_model())
            if not s:
                send_message(chat_id, "❌ Không đọc được nội dung PDF (có thể là ảnh chụp).")
            else:
                from services import pdf_images as _pimg
                send_message(chat_id, _pimg.humanize_markers(s))
                # Ảnh THẬT cho marker image:// — Zalo Bot API cần URL công khai
                # (nền tảng tự fetch), phục vụ qua /images/pdf/ như _serve_docx_link.
                try:
                    base = _public_base()
                    for cap, iid in _pimg.find_markers(s)[:4]:
                        rel = _pimg.serve_rel(iid)
                        if rel and base:
                            send_photo(chat_id, f"{base}{rel}",
                                       caption=(cap or "Hình trong tài liệu")[:200])
                except Exception as exc:
                    logger.warning("zalo gửi ảnh marker PDF lỗi: %s", exc)
    except Exception as e:
        logger.warning("zalo pdf intent %s error: %s", intent, e)
        send_message(chat_id, f"❌ Lỗi xử lý PDF: {e}")
    finally:
        for p in (path, docx_tmp):
            try:
                os.unlink(p)
            except Exception:
                pass


def _do_photo_request(chat_id: str, file_data: bytes, request: str, allow: set | None = None) -> None:
    """Xử lý ảnh + yêu cầu đi kèm: 'generate' = tạo/chỉnh ảnh mới TỪ ảnh gửi
    (img2img, nhóm lọc 'image' — thread bị cấm thì bỏ qua im lặng);
    'analyze' = phân tích/mô tả bằng nhánh vision (giống Telegram)."""
    from services import photo_intent as _phi
    _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    if _phi.classify(request) == "generate":
        if allow is not None and "image" not in allow:
            return  # thread lọc không có nhóm 'image' → bỏ qua, không nhắn gì
        out = _phi.generate_from_photo(file_data, request)
        url = out.get("image_url")
        if url:
            if send_photo(chat_id, url, caption=(out.get("text") or "Đây ạ 🎨")[:1000]).get("ok"):
                return
            send_message(chat_id, f"{out.get('text') or ''}\n{url}".strip())
            return
        send_message(chat_id, out.get("text") or "Em chưa tạo được ảnh ạ.")
        return
    # analyze — nhánh vision.
    ans = ""
    try:
        import base64
        from services.agent.branches import branch_model
        from services.agent.runtime import call_model, content_of
        durl = "data:image/jpeg;base64," + base64.b64encode(file_data).decode()
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": request},
            {"type": "image_url", "image_url": {"url": durl}},
        ]}]
        # Model DUY NHẤT từ Nhánh Agent 'Phân tích ảnh' — lỗi báo admin debug.
        _vm = branch_model("vision", "zalo")
        resp = call_model(_vm, msgs, timeout=180, max_tokens=900)
        if resp.get("error"):
            try:
                from services.notifier import notify_admin
                notify_admin(f"⚠️ Vision (Zalo photo) lỗi — model '{_vm}': {str(resp['error'])[:200]}")
            except Exception:
                pass
        else:
            ans = content_of(resp).strip()
    except Exception as exc:
        logger.warning("Zalo vision failed: %s", exc)
        ans = ""
    send_message(chat_id, ans or "📷 Đã nhận ảnh nhưng chưa phân tích được ạ.")


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
    if not chat_id:
        return {"ok": True}
    threading.Thread(target=_process_message,
                     args=(text, chat_id, photo_url, bot, sender, f_url, f_name, f_id,
                           user_id, is_group, chat_name),
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


def _process_message(text: str, chat_id: str, photo_url: str = "", bot: dict | None = None,
                     sender: str = "", file_url: str = "", file_name: str = "",
                     file_id: str = "", user_id: str = "", is_group: bool = False,
                     chat_name: str = "") -> None:
    if bot is not None:
        _current.bot = bot  # luồng mới → gắn lại ngữ cảnh bot để gửi đúng token

    # Blacklist THEO BOT: nhóm/cá nhân bị loại trên bot này → bỏ qua hoàn toàn.
    from services import channel_activity as _ca
    if chat_id and _ca.is_blacklisted("zalo", chat_id, user_id, account=_bot_id()):
        return
    # Ghi LẦN GẦN NHẤT (bot/Chat ID/User ID) để trang quản lý hiển thị.
    if chat_id:
        _ca.record("zalo", account=_bot_id(), chat_id=chat_id, user_id=user_id,
                   user_name=sender, chat_name=chat_name, is_group=is_group,
                   text=text or ("[ảnh]" if photo_url else "") or (file_name or ""))

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
    _low = (text or "").strip().lower()
    # Trong NHÓM tin luôn kèm prefix @tag bot (nền tảng bắt buộc tag mới giao tin)
    # → so khớp substring chứ không chỉ equality, kẻo "/id" trong nhóm bị trượt.
    _is_id = _low in {"/id", "id", "chatid"} or "/id" in _low or "chatid" in _low \
        or ("chat id" in _low and len(_low) <= 60)
    # Zalo nhóm: nền tảng thường chỉ đẩy tin khi đã tag bot → coi tagged=True
    # nếu is_group (hoặc keyword filter). Multi-bot: bot không nhận event thì
    # không alert; bot nhận event thì alert 1 lần nếu stranger.
    _tagged_early = bool(is_group)
    if chat_id and not is_group:
        _tagged_early = True
    if chat_id:
        try:
            _req_m, _kw_m = _caps.mention_required_for("zalo", _bot_id(), chat_id)
            if _req_m:
                _kw_l = (_kw_m or "").strip().lower()
                _tagged_early = bool(_kw_l) and _kw_l in (text or "").lower()
                # Zalo group messages often include @Bot — treat as tagged if bot id in text
                if is_group and (str(_bot_id()) in (text or "") or _bot_label().lower() in (text or "").lower()):
                    _tagged_early = True
        except Exception:
            pass
    if chat_id and _allow is None and chat_id not in allowed:
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

    # Chuyển tiếp webhook (HA / n8n / URL bất kỳ) theo 'Lọc chức năng theo
    # thread'. Thread bật → mọi user (trừ user tắt riêng); thread không bật →
    # user nào bật + có URL riêng thì chuyển tới đó. User bật tag_mode: tin
    # TAG bot → CHỈ chuyển webhook (AI im lặng); không tag → ChatGPT trả lời.
    # Nhận diện tag Zalo: từ khóa tag của thread nếu có; KHÔNG có từ khóa thì
    # NHÓM = tagged (nền tảng Zalo bắt buộc @tag mới giao tin nhóm cho bot).
    _req_fw, _kw_fw = _caps.mention_required_for("zalo", _bot_id(), chat_id)
    if _kw_fw:
        _tagged = _kw_fw.lower() in (text or "").lower()
    else:
        _tagged = bool(is_group)
    if _caps.forward_event("zalo", _bot_id(), chat_id, user_id, {
        "platform": "zalo", "bot": _bot_id(), "chat_id": chat_id,
        "user_id": user_id, "sender": sender, "is_group": is_group,
        "text": text or "", "tagged": _tagged, "photo_url": photo_url or "",
        "file_url": file_url or "", "file_name": file_name or "",
    }, tagged=_tagged):
        return

    # Bộ lọc TAG (nhóm): bật 'bắt buộc tag' → chỉ trả lời khi tin chứa từ khóa tag
    # đã cấu hình. LƯU Ý: nền tảng Zalo ĐÃ bắt buộc @tag bot mới giao tin nhóm cho
    # bot — bộ lọc từ khóa này là LỚP PHỤ (thường không cần bật). /id vẫn qua.
    if is_group and chat_id:
        _req, _kw = _caps.mention_required_for("zalo", _bot_id(), chat_id)
        if _req:
            _kw_l = (_kw or "").strip().lower()
            if not (_kw_l and _kw_l in (text or "").lower()):
                return

    # Trả lời ý định cho PDF đang chờ (1=RAG / 2=Word)?
    from services import pdf_intent as _pi
    _pkey = f"zalo:{_bot_id()}:{chat_id}"
    if text and chat_id and _pi.has_pending(_pkey):
        _intent = _pi.parse_intent(text)
        if _intent:
            if _intent not in _pi.allowed_intents(_allow):
                return  # ý định PDF bị lọc → bỏ qua, không nhắn gì
            _do_pdf_intent(chat_id, _pi.pop_pending(_pkey), _intent)
            return

    # Trả lời yêu cầu cho ẢNH đang chờ (gửi ảnh không kèm caption)?
    from services import photo_intent as _phi
    if text and chat_id and _phi.has_pending(_pkey):
        _pdata = _phi.pop_pending(_pkey)
        if _pdata:
            _do_photo_request(chat_id, _pdata, text.strip(), _allow)
            return

    # File đính kèm → PDF thì HỎI ý định (RAG/Word). Bắt đủ biến thể:
    # url/.pdf, document{...}, file_url, file_name, file_id (getFile).
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
        send_message(chat_id, f"📎 Hiện em chỉ hỗ trợ chuyển PDF → Word. File: {file_name or 'không rõ'}")
        return

    # Ảnh → CÓ caption thì làm luôn (phân tích HAY tạo ảnh từ ảnh tùy yêu cầu);
    # KHÔNG caption thì hỏi lại muốn làm gì rồi chờ tin nhắn kế tiếp.
    if photo_url:
        _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        data = _download(photo_url)
        if not data:
            send_message(chat_id, "📷 Không tải được ảnh.")
            return
        caption = (text or "").strip()
        if not caption:
            from services import photo_intent as _phi
            _phi.set_pending(f"zalo:{_bot_id()}:{chat_id}", data)
            send_message(chat_id, _phi.ASK)
            return
        _do_photo_request(chat_id, data, caption, _allow)
        return

    if not text:
        return

    _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    # CHUNG orchestrator với Telegram — cùng persona/memory/capability/setting.
    try:
        from services.agent import orchestrate
        out = orchestrate(text, f"zalo_{chat_id}", allow=_allow,
                          ha_fastpath=bool(_active_bot().get("ha_fastpath", True)))
        if out.get("silent"):
            return  # thread lọc yêu cầu chức năng bị tắt → bỏ qua, không nhắn gì
        reply = (out.get("text") or "").strip() or "..."
        image_url = out.get("image_url")
        if image_url:
            if send_photo(chat_id, image_url, caption=reply[:1000]).get("ok"):
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
        send_message(chat_id, reply)
        return
    except Exception as exc:
        logger.warning("Zalo orchestrator error %s: %s", chat_id, exc)

    # Fallback: gọi thẳng gateway.
    base_url = str(config.get().get("api_base_url", "")).strip().rstrip("/") or "http://127.0.0.1/v1"
    try:
        payload = {"model": _zalo_model(),
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
        send_message(chat_id, (reply or "").strip() or "⏳ Hệ thống bận, thử lại.")
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
