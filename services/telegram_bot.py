"""Telegram Bot — 2-way AI chat channel through chatgpt2api.

Each Telegram chat = a chat session with full AI + MCP tool support.
"""

from __future__ import annotations

import hashlib
import logging
import json
import re
import threading
import time
import urllib.request
from typing import Any

from services.config import config


_MD_BOLD_DOUBLE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MD_BOLD_UNDER_DOUBLE = re.compile(r"__(.+?)__", re.DOTALL)
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_MD_STRIKE = re.compile(r"~~(.+?)~~", re.DOTALL)
_MD_TABLE_PIPE = re.compile(r"^\s*\|.+\|\s*$", re.MULTILINE)
_MD_TABLE_SEP = re.compile(r"^\s*\|?[\s:-]+\|[\s:|\-]+\s*$", re.MULTILINE)


def _to_telegram_markdown(text: str) -> str:
    """Convert LLM markdown to Telegram MarkdownV1 syntax.

    Telegram MarkdownV1 uses *single-asterisk* for bold (not **double**),
    has no headings, and breaks on stray unbalanced markers. Convert the
    common cases so messages render with bold/italic/code instead of
    failing or showing literal asterisks.
    """
    if not text:
        return text
    out = _MD_BOLD_DOUBLE.sub(r"*\1*", text)
    out = _MD_BOLD_UNDER_DOUBLE.sub(r"*\1*", out)
    out = _MD_HEADING.sub("", out)
    out = _MD_STRIKE.sub(r"\1", out)
    return out

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
_conversations: dict[str, list[dict]] = {}
MAX_HISTORY = 20


# Ngữ cảnh bot hiện hành (đa-token). Luồng xử lý tin set _current.bot; getter đọc
# từ đây, fallback bot[0]. Cần để gửi trả đúng token khi chạy nhiều bot Telegram.
_current = threading.local()


def _cur_bot() -> dict | None:
    return getattr(_current, "bot", None)


def _bots() -> list[dict]:
    return config.telegram_bots()


def _active_bot() -> dict:
    b = _cur_bot()
    if b is None:
        bots = _bots()
        b = bots[0] if bots else {}
    return b


def _bot_token() -> str:
    return str(_active_bot().get("token", "")).strip()


def _bot_id() -> str:
    """ID bot công khai = phần trước ':' của token (Telegram bot id, không phải
    secret). Dùng làm khóa lọc theo-bot 'tg:<bot_id>:<chat_id>'."""
    return _bot_token().split(":", 1)[0].strip()


_bot_name_cache: dict[str, str] = {}  # token -> tên bot (getMe first_name); "" = lỗi


def _fetch_bot_name(token: str) -> str:
    """Tên hiển thị bot (getMe → first_name, fallback username) — cache theo
    token; lỗi cũng cache '' để không gọi lặp (restart thử lại)."""
    token = str(token or "").strip()
    if not token:
        return ""
    if token in _bot_name_cache:
        return _bot_name_cache[token]
    name = ""
    try:
        req = urllib.request.Request(f"{TELEGRAM_API}/bot{token}/getMe")
        r = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
        res = r.get("result") or {}
        name = str(res.get("first_name") or res.get("username") or "").strip()
    except Exception as exc:
        logger.warning("Telegram getMe (tên bot) lỗi: %s", exc)
    _bot_name_cache[token] = name
    return name


def get_bot_names() -> dict[str, str]:
    """Map bot_id → tên bot cho MỌI bot đã cấu hình — UI hiển thị tên thay mã số."""
    out: dict[str, str] = {}
    for b in _bots():
        token = str(b.get("token", "")).strip()
        if not token:
            continue
        name = _fetch_bot_name(token)
        if name:
            out[token.split(":", 1)[0].strip()] = name
    return out


_bot_username_cache: dict[str, str] = {}  # token -> @username (lower), cho @mention


def _bot_username() -> str:
    """Username bot (không '@', lowercase) — getMe 1 lần, cache theo token.
    Dùng để nhận diện @mention native trong nhóm."""
    token = _bot_token()
    if not token:
        return ""
    if token in _bot_username_cache:
        return _bot_username_cache[token]
    name = ""
    try:
        r = _api_call("getMe")
        if r.get("ok"):
            name = str((r.get("result") or {}).get("username") or "").strip().lower()
    except Exception:
        pass
    _bot_username_cache[token] = name
    return name


def _tg_model() -> str:
    return str(_active_bot().get("ai_model", "")).strip() or "cx/auto"


def _chat_ids() -> list:
    return list(_active_bot().get("chat_ids") or [])


def _webhook_secret_for(token: str) -> str:
    """Secret ổn định sinh từ token (A-Za-z0-9), cho setWebhook.secret_token + verify
    header X-Telegram-Bot-Api-Secret-Token khi nhiều bot chung 1 URL webhook."""
    return ("t" + hashlib.sha256(token.encode()).hexdigest()[:40]) if token else ""


def _bot_public_id(bot: dict | None) -> str:
    tok = str((bot or {}).get("token") or "").strip()
    return tok.split(":", 1)[0].strip() if tok else ""


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
    """Mọi admin thread của bot (độc lập). Không dùng 'admin chung' chéo bot."""
    from services.admin_workspace import resolve_admins_for_bot
    return resolve_admins_for_bot("tg", bot or _active_bot())


def _resolve_admin_delivery() -> tuple[str, dict | None]:
    """Legacy: (first_admin, current_bot). Prefer _notify_all_admins / _admin_ids_for_bot."""
    cur = _active_bot()
    ids = _admin_ids_for_bot(cur)
    if ids:
        return ids[0], cur
    return "", cur


def _send_admin_thread(admin: str, text: str, *, bot_only: bool = False) -> bool:
    """Gửi 1 admin chat bằng bot hiện tại (token bot nhận tin)."""
    if not admin:
        return False
    try:
        return bool(send_message(admin, text).get("ok"))
    except Exception:
        return False


def _notify_all_admins(text: str, *, bot: dict | None = None) -> int:
    """Gửi CÙNG nội dung tới MỌI admin_thread của bot này (multi-admin)."""
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
    """True nếu chat_id là admin thread của bot hiện tại."""
    return str(chat_id or "").strip() in set(_admin_ids_for_bot())


def _alert_new_chat(chat_id: str, sender: str, text: str, served: bool,
                    user_id: str = "", is_group: bool = False,
                    tagged: bool = False, chat_name: str = "") -> None:
    """Báo MỌI admin của bot nhận tin — 1 lần/(bot,chat); hỏi lưu riêng từng admin."""
    c = config.get()
    if not bool(c.get("telegram_newchat_alert_enabled", True)):
        return
    # Toggle RIÊNG bot này (áp cho cả admin_threads của nó) — tắt là im.
    if not bool((_active_bot() or {}).get("newchat_alert_enabled", True)):
        return
    try:
        from services import channel_contacts as _cc
        from services import admin_workspace as _aw
        ok, rec = _cc.should_alert_new(
            "tg", _bot_id(), chat_id,
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
                    # Tên bot theo GÓC NHÌN từng admin
                    bl = _aw.bot_display_name("tg", _bot_id(), aid)
                    msg = base.replace(
                        f"bot **{_cc.bot_label('tg', _bot_id())}**",
                        f"bot **{bl}**",
                        1,
                    )
                    msg += _aw.start_save_prompt("tg", aid, rec)
                    if _send_admin_thread(aid, msg):
                        sent += 1
            finally:
                _current.bot = prev
        if not sent:
            # Không có admin / gửi fail hết (vd admin chưa /start bot này) →
            # fallback notifier đa kênh như trước, kẻo alert rơi lặng lẽ.
            try:
                from services.notifier import notify_admin as _notify
                _notify(base + "\n(Fallback đa kênh — bot này chưa gửi được admin thread nào.)")
            except Exception:
                pass
        _cc.mark_notified(str(rec.get("key") or ""))
    except Exception as exc:
        logger.warning("telegram new-contact alert failed: %s", exc)


def notify_admin(text: str, category: str = "") -> None:
    """Send a system/admin notification to every configured Telegram chat of EVERY
    enabled bot (đa-token). Best-effort — never raises.

    Mỗi bot có toggle RIÊNG (độc lập giữa các tài khoản): `notify_admin_enabled`
    tắt là bot đó im hẳn; `category="account_log"` xét thêm `account_log_enabled`.

    Sent as PLAIN text (no Markdown) — alert text carries emails/reasons with
    `_` and `.` that break Telegram's legacy Markdown, which then showed the
    literal `*`/`` ` `` symbols ("lỗi phông chữ"). Plain text is always clean."""
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
                if _caps.allowed_groups_for_bot("tg", bid, str(cid)) is not None:
                    continue
                try:
                    _api_call("sendMessage", {
                        "chat_id": str(cid), "text": text[:4000],
                        "link_preview_options": {"is_disabled": True},
                    })
                except Exception:
                    pass
    finally:
        _current.bot = None


def _api_call(method: str, data: dict | None = None) -> dict:
    token = _bot_token()
    if not token:
        return {"ok": False}
    url = f"{TELEGRAM_API}/bot{token}/{method}"
    try:
        if data:
            req = urllib.request.Request(url, data=json.dumps(data).encode(),
                headers={"Content-Type": "application/json"})
        else:
            req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode())
    except Exception as exc:
        logger.warning("Telegram API %s: %s", method, exc)
        return {"ok": False}


def register_webhook() -> bool:
    """Đăng ký webhook cho MỌI bot Telegram đang bật (đa-token). Tất cả trỏ về CÙNG
    URL /telegram/webhook, phân biệt bằng secret_token → handle_webhook định tuyến
    theo header X-Telegram-Bot-Api-Secret-Token."""
    webhook_url = str(config.get().get("telegram_webhook_url", "")).strip()
    if not webhook_url:
        return False
    url = f"{webhook_url.rstrip('/')}/telegram/webhook"
    ok_any = False
    try:
        for bot in _bots():
            if not bot.get("enabled", True):
                continue
            token = str(bot.get("token", "")).strip()
            if not token:
                continue
            _current.bot = bot
            r = _api_call("setWebhook", {
                "url": url,
                "allowed_updates": ["message", "edited_message", "callback_query"],
                "secret_token": _webhook_secret_for(token),
            })
            if r.get("ok"):
                logger.info("Telegram webhook OK bot %s…: %s", token[:8], url)
                ok_any = True
            else:
                logger.warning("Telegram webhook failed bot %s…: %s", token[:8], r)
    finally:
        _current.bot = None
    return ok_any


def send_message(chat_id: int | str, text: str,
                 reply_markup: dict | None = None) -> dict:
    if len(text) > 4000:
        text = text[:3900] + "..."
    converted = _to_telegram_markdown(text)
    payload: dict = {
        "chat_id": str(chat_id), "text": converted, "parse_mode": "Markdown",
        "link_preview_options": {"is_disabled": True},
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    r = _api_call("sendMessage", payload)
    if r.get("ok"):
        return r
    # Telegram rejected the markdown (often unbalanced markers from the LLM).
    # Retry as plain text so the user at least sees the answer.
    plain: dict = {
        "chat_id": str(chat_id), "text": text,
        "link_preview_options": {"is_disabled": True},
    }
    if reply_markup:
        plain["reply_markup"] = reply_markup
    return _api_call("sendMessage", plain)


def _send_agent_reply(chat_id: str, out: dict) -> None:
    """Send orchestrator text (+ optional ask-choice inline keyboard)."""
    from services.agent import ask_choices as _ask
    reply = (out.get("text") or "").strip() or "..."
    choices = out.get("choices") or []
    markup = None
    if choices:
        try:
            markup = _ask.telegram_inline_keyboard(choices)
            # Numbered fallback in text for users who type instead of tapping
            reply = _ask.format_numbered(reply, choices)
        except Exception:
            markup = None
    send_message(chat_id, reply, reply_markup=markup)

def send_photo(chat_id: int | str, photo_bytes: bytes, caption: str = "") -> dict:
    """Gửi ảnh qua Telegram."""
    import io, uuid
    token = _bot_token()
    if not token:
        return {"ok": False}
    try:
        boundary = f"bot{token[:8]}{uuid.uuid4().hex[:8]}"
        body = io.BytesIO()
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode())
        body.write(f"--{boundary}\r\n".encode())
        if caption:
            body.write(f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode())
            body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="photo"; filename="image.png"\r\n'.encode())
        body.write(f'Content-Type: image/png\r\n\r\n'.encode())
        body.write(photo_bytes)
        body.write(f"\r\n--{boundary}--\r\n".encode())
        body.seek(0)

        url = f"{TELEGRAM_API}/bot{token}/sendPhoto"
        req = urllib.request.Request(url, data=body.getvalue(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read().decode())
    except Exception as e:
        logger.warning("sendPhoto failed: %s", e)
        return {"ok": False}

def send_video(chat_id: int | str, video_bytes: bytes, caption: str = "") -> dict:
    """Gửi video qua Telegram."""
    import io, uuid
    token = _bot_token()
    if not token:
        return {"ok": False}
    try:
        boundary = f"bot{token[:8]}{uuid.uuid4().hex[:8]}"
        body = io.BytesIO()
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode())
        body.write(f"--{boundary}\r\n".encode())
        if caption:
            body.write(f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode())
            body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="video"; filename="video.mp4"\r\n'.encode())
        body.write(f'Content-Type: video/mp4\r\n\r\n'.encode())
        body.write(video_bytes)
        body.write(f"\r\n--{boundary}--\r\n".encode())
        body.seek(0)

        url = f"{TELEGRAM_API}/bot{token}/sendVideo"
        req = urllib.request.Request(url, data=body.getvalue(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        resp = urllib.request.urlopen(req, timeout=120)
        return json.loads(resp.read().decode())
    except Exception as e:
        logger.warning("sendVideo failed: %s", e)
        return {"ok": False}

def send_audio(chat_id: int | str, audio_bytes: bytes, caption: str = "") -> dict:
    """Gửi file nhạc/audio qua Telegram (hiện player bấm nghe)."""
    import io, uuid
    token = _bot_token()
    if not token:
        return {"ok": False}
    try:
        boundary = f"bot{token[:8]}{uuid.uuid4().hex[:8]}"
        body = io.BytesIO()
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode())
        body.write(f"--{boundary}\r\n".encode())
        if caption:
            body.write(f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode())
            body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="audio"; filename="music.mp3"\r\n'.encode())
        body.write(f'Content-Type: audio/mpeg\r\n\r\n'.encode())
        body.write(audio_bytes)
        body.write(f"\r\n--{boundary}--\r\n".encode())
        body.seek(0)

        url = f"{TELEGRAM_API}/bot{token}/sendAudio"
        req = urllib.request.Request(url, data=body.getvalue(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        resp = urllib.request.urlopen(req, timeout=120)
        return json.loads(resp.read().decode())
    except Exception as e:
        logger.warning("sendAudio failed: %s", e)
        return {"ok": False}

def send_document(chat_id: int | str, doc_bytes: bytes, filename: str, caption: str = "") -> dict:
    """Gửi file/document qua Telegram."""
    import io, uuid
    token = _bot_token()
    if not token:
        return {"ok": False}
    try:
        boundary = f"bot{token[:8]}{uuid.uuid4().hex[:8]}"
        body = io.BytesIO()
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode())
        body.write(f"--{boundary}\r\n".encode())
        if caption:
            body.write(f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode())
            body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode())
        body.write(f'Content-Type: application/octet-stream\r\n\r\n'.encode())
        body.write(doc_bytes)
        body.write(f"\r\n--{boundary}--\r\n".encode())
        body.seek(0)

        url = f"{TELEGRAM_API}/bot{token}/sendDocument"
        req = urllib.request.Request(url, data=body.getvalue(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read().decode())
    except Exception as e:
        logger.warning("sendDocument failed: %s", e)
        return {"ok": False}


async def handle_webhook(request) -> dict:
    """Handle incoming Telegram webhook POST. Returns immediately, processes AI in background."""
    try:
        hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
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
            logger.warning("Telegram webhook bad/ambiguous secret")
            return {"ok": False}
    # Inline keyboard callbacks (ask-with-choices)
    cq = body.get("callback_query")
    if cq:
        _current.bot = bot
        t = threading.Thread(target=_handle_callback_query, args=(cq, bot), daemon=True)
        t.start()
        return {"ok": True}

    msg = body.get("message") or body.get("edited_message")
    if not msg:
        return {"ok": True}
    chat = msg.get("chat", {}) or {}
    chat_id = str(chat.get("id", ""))
    text = (msg.get("text") or "").strip()
    photo = msg.get("photo")
    document = msg.get("document")
    # Voice note / file ghi âm → STT ở luồng nền rồi đi tiếp như tin nhắn chữ.
    _vo = msg.get("voice") or msg.get("audio") or {}
    voice_file_id = str(_vo.get("file_id") or "") if isinstance(_vo, dict) else ""
    frm = msg.get("from") or {}
    # Tên người: first_name + last_name, fallback @username
    _fn = str(frm.get("first_name") or "").strip()
    _ln = str(frm.get("last_name") or "").strip()
    sender = (" ".join(x for x in (_fn, _ln) if x).strip()
              or str(frm.get("username") or "").strip())
    user_id = str(frm.get("id") or "").strip()
    is_group = str(chat.get("type") or "") in {"group", "supergroup"}
    # Tên nhóm / title chat (cá nhân có thể có first_name của chat)
    chat_name = str(chat.get("title") or "").strip()
    if not chat_name and not is_group:
        chat_name = str(chat.get("first_name") or chat.get("username") or "").strip()

    # Nhận diện @mention NATIVE (cho bộ lọc 'bắt buộc tag'): reply vào tin của bot,
    # entity 'mention' == @username bot, hoặc 'text_mention' trỏ đúng user bot.
    native_mention = False
    _current.bot = bot  # để _bot_username()/_bot_id() dùng đúng token trong luồng này
    try:
        buser = _bot_username()
        bid = _bot_id()
        rtm = (msg.get("reply_to_message") or {}).get("from") or {}
        if rtm.get("is_bot") and (str(rtm.get("id") or "") == bid
                                  or str(rtm.get("username") or "").lower() == buser):
            native_mention = True
        ents = (msg.get("entities") or []) + (msg.get("caption_entities") or [])
        body_txt = text or (msg.get("caption") or "")
        for e in ents:
            et = e.get("type")
            if et == "mention" and buser:
                seg = body_txt[e.get("offset", 0): e.get("offset", 0) + e.get("length", 0)]
                if seg.lower().lstrip("@") == buser:
                    native_mention = True
                    break
            if et == "text_mention" and str((e.get("user") or {}).get("id") or "") == bid:
                native_mention = True
                break
    except Exception:
        pass

    # Process in background thread so webhook returns immediately
    t = threading.Thread(target=_process_message,
                         args=(text, chat_id, photo, document, bot, sender,
                               user_id, is_group, native_mention, chat_name,
                               voice_file_id),
                         daemon=True)
    t.start()
    return {"ok": True}


def _handle_callback_query(cq: dict, bot: dict) -> None:
    """Inline button press → treat as the chosen option text for the agent."""
    try:
        _current.bot = bot
        cq_id = str(cq.get("id") or "")
        if cq_id:
            _api_call("answerCallbackQuery", {"callback_query_id": cq_id})
        data = str(cq.get("data") or "")
        msg = cq.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id") or "")
        frm = cq.get("from") or {}
        sender = str(frm.get("username") or frm.get("first_name") or "").strip()
        user_id = str(frm.get("id") or "").strip()
        is_group = str(chat.get("type") or "") in {"group", "supergroup"}
        if not chat_id or not data.startswith("ask:"):
            return
        try:
            idx = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            return
        from services.agent import ask_choices as _ask
        choices = _ask.get_pending(chat_id)
        if not choices or idx < 0 or idx >= len(choices):
            return
        _ask.clear_pending(chat_id)
        chosen = choices[idx].get("send") or choices[idx].get("label") or ""
        if not chosen:
            return
        _process_message(chosen, chat_id, None, None, bot, sender,
                         user_id, is_group, native_mention=True)
    except Exception as exc:
        logger.warning("Telegram callback_query failed: %s", exc)
    finally:
        _current.bot = None


def _maybe_voice_reply(chat_id: str, user_id: str, reply: str) -> None:
    """Gửi KÈM file âm thanh nếu thread (hoặc riêng user này) bật `tts_reply`.

    Quy tắc user thắng nhóm: nhóm không bật nhưng user bật → chỉ người đó nghe.
    Lỗi TTS không được làm hỏng câu trả lời chữ đã gửi.
    """
    text = (reply or "").strip()
    if not text or not chat_id:
        return
    try:
        from services import voice as _voice
        from services.voice import permissions as _vperm
        if not _vperm.wants_voice_reply("tg", _bot_id(), chat_id, user_id):
            return
        if not _voice.tts_ready():
            return
        wav = _voice.speak(text[:1000])
        send_audio(chat_id, wav, caption="")
    except Exception as exc:
        logger.warning("tg voice reply loi: %s", str(exc)[:160])


def _download_file(file_id: str) -> bytes | None:
    """Download a file from Telegram by file_id."""
    token = _bot_token()
    if not token:
        return None
    try:
        # Get file path
        r = _api_call("getFile", {"file_id": file_id})
        if not r.get("ok") or not r.get("result", {}).get("file_path"):
            return None
        file_path = r["result"]["file_path"]
        url = f"{TELEGRAM_API}/file/bot{token}/{file_path}"
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=30)
        return resp.read()
    except Exception as e:
        logger.warning("File download failed: %s", e)
        return None


def _do_pdf_intent(chat_id: str, pending: dict | None, intent: str) -> None:
    """Xử lý PDF đang chờ theo ý định người dùng: 'word' (pdf2docx) / 'rag' (tóm tắt)."""
    if not pending:
        return
    import os
    path, name = pending["path"], pending["name"]
    _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    try:
        if intent == "word":
            from services.pdf_to_word import convert_pdf_to_docx
            docx_path = (path[:-4] if path.endswith(".pdf") else path) + ".docx"
            r = convert_pdf_to_docx(path, docx_path)
            if r.get("ok"):
                with open(docx_path, "rb") as f:
                    data = f.read()
                base = name[:-4] if name.lower().endswith(".pdf") else name
                how = {"layout": "giữ layout", "scan": "AI OCR scan — giữ bảng + hình"} \
                    .get(r.get("method"), "OCR (PDF scan)")
                send_document(chat_id, data, f"{base}.docx", caption=f"📝 Bản Word ({how})")
                try:
                    os.unlink(docx_path)
                except Exception:
                    pass
            else:
                send_message(chat_id, f"⚠️ Không chuyển được sang Word: {str(r.get('error', ''))[:150]}")
        else:
            from services.pdf_intent import summarize_pdf
            s = summarize_pdf(path, _tg_model())
            if not s:
                send_message(chat_id, "❌ Không đọc được nội dung PDF (có thể là ảnh chụp).")
            else:
                from services import pdf_images as _pimg
                send_message(chat_id, _pimg.humanize_markers(s))
                # Gửi kèm ảnh THẬT cho marker image:// (hình trích từ PDF số).
                try:
                    for cap, iid in _pimg.find_markers(s)[:4]:
                        p = _pimg.image_path(iid)
                        if p:
                            send_photo(chat_id, p.read_bytes(),
                                       caption=(cap or "Hình trong tài liệu")[:200])
                except Exception as exc:
                    logger.warning("gửi ảnh marker PDF lỗi: %s", exc)
    except Exception as e:
        logger.warning("pdf intent %s error: %s", intent, e)
        send_message(chat_id, f"❌ Lỗi xử lý PDF: {e}")
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def _fetch_image_bytes(url: str) -> bytes | None:
    """Tải bytes ảnh. URL /images/ của CHÍNH mình đi qua localhost trước —
    container tự gọi ngược domain public qua Cloudflare bị 403 (hairpin)."""
    candidates = []
    if "/images/" in url:
        candidates.append("http://127.0.0.1:80/images/" + url.split("/images/", 1)[1])
    candidates.append(url)
    for u in candidates:
        try:
            return urllib.request.urlopen(u, timeout=60).read()
        except Exception:
            continue
    return None


def _do_photo_request(chat_id: str, file_data: bytes, request: str, allow: set | None = None) -> None:
    """Xử lý ảnh + yêu cầu đi kèm: 'generate' = tạo/chỉnh ảnh mới TỪ ảnh gửi
    (img2img, thuộc nhóm lọc 'image' — thread bị cấm thì bỏ qua im lặng);
    'analyze' = phân tích/mô tả bằng nhánh vision, OCR fallback."""
    from services import photo_intent as _phi
    _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    if _phi.classify(request) == "generate":
        if allow is not None and "image" not in allow:
            return  # thread lọc không có nhóm 'image' → bỏ qua, không nhắn gì
        out = _phi.generate_from_photo(file_data, request)
        url = out.get("image_url")
        cap = (out.get("text") or "Đây ạ 🎨")[:1000]
        # Ưu tiên upload BYTES multipart — luôn ra ẢNH thật, không phải link.
        img = out.get("image_bytes") or (_fetch_image_bytes(url) if url else None)
        if img:
            if send_photo(chat_id, img, caption=cap).get("ok"):
                return
        if url:
            # Cứu cánh: đưa URL public cho server Telegram tự fetch (vẫn hiển
            # thị là ảnh); bí lắm mới gửi link chữ.
            if _api_call("sendPhoto", {"chat_id": chat_id, "photo": url, "caption": cap}).get("ok"):
                return
            send_message(chat_id, f"{cap}\n{url}".strip())
            return
        send_message(chat_id, out.get("text") or "Em chưa tạo được ảnh ạ.")
        return
    # analyze — vision là chính, OCR chỉ còn là fallback khi vision lỗi.
    answer = ""
    try:
        import base64
        from services.agent.branches import branch_model
        from services.agent.runtime import call_model, content_of
        data_url = "data:image/jpeg;base64," + base64.b64encode(file_data).decode()
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": request},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}]
        # Model DUY NHẤT từ Nhánh Agent 'Phân tích ảnh' — lỗi báo admin debug.
        _vm = branch_model("vision", "tg")
        resp = call_model(_vm, msgs, timeout=180, max_tokens=900)
        if resp.get("error"):
            try:
                from services.notifier import notify_admin
                notify_admin(f"⚠️ Vision (Telegram photo) lỗi — model '{_vm}': {str(resp['error'])[:200]}")
            except Exception:
                pass
        else:
            answer = content_of(resp).strip()
    except Exception as exc:
        logger.warning("vision branch failed: %s", exc)
        answer = ""
    if answer:
        send_message(chat_id, answer)
        return
    # Fallback: OCR như cũ
    ocr = ""
    try:
        import pytesseract
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(file_data))
        ocr = pytesseract.image_to_string(img, lang="vie+eng").strip()
    except Exception:
        pass
    if ocr:
        send_message(chat_id, f"📷 OCR:\n{ocr[:2000]}")
    else:
        send_message(chat_id, f"📷 Đã nhận ảnh ({len(file_data)//1024}KB) nhưng em chưa phân tích được ạ.")


def _process_message(text: str, chat_id: str, photo: list | None = None, document: dict | None = None, bot: dict | None = None, sender: str = "", user_id: str = "", is_group: bool = False, native_mention: bool = False, chat_name: str = "", voice_file_id: str = "") -> None:
    """Process a Telegram message in background thread."""
    if bot is not None:
        _current.bot = bot  # luồng mới → gắn lại ngữ cảnh bot để gửi đúng token

    # Voice note → STT → coi như tin nhắn CHỮ: đường đi chỉ thêm bước chuyển
    # đổi, phần sau (lọc quyền, agent, trả lời) giữ nguyên như chat thường.
    if voice_file_id and not text:
        try:
            from services import voice as _voice
            raw = _download_file(voice_file_id)
            if raw:
                text = _voice.listen(raw, "ogg")
                logger.info("tg voice->text (%d bytes): %.60s", len(raw), text)
        except Exception as exc:
            logger.warning("tg STT loi: %s", str(exc)[:160])
            if chat_id:
                send_message(chat_id, f"🎤 Em nghe không rõ ạ 😥 ({str(exc)[:120]})")
            return
        if not text:
            if chat_id:
                send_message(chat_id, "🎤 Em không nghe ra chữ nào trong đoạn ghi âm ạ.")
            return

    # Blacklist THEO BOT: nhóm/cá nhân bị loại trên bot này → bỏ qua hoàn toàn.
    from services import channel_activity as _ca
    if chat_id and _ca.is_blacklisted("tg", chat_id, user_id, account=_bot_id()):
        return
    if chat_id:
        _ca.record(
            "tg", account=_bot_id(), chat_id=chat_id, user_id=user_id,
            user_name=sender, chat_name=chat_name, is_group=is_group,
            text=text or ("[ảnh]" if photo else "") or str((document or {}).get("file_name") or ""),
        )

    # Kiểm soát truy cập NGAY TỪ ĐẦU (áp cho cả ảnh/PDF, không chỉ text):
    # - chat có bản ghi lọc = đã cấp phép (không cần nằm trong Chat IDs);
    # - người lạ → báo admin + chặn (trừ lệnh /id để họ lấy ID gửi admin).
    # - trong NHÓM: quyền = giao(nhóm, user) — tầng lọc User ID theo từng nhóm.
    from services.agent import capabilities as _caps
    _allow = _caps.allowed_groups_for_member("tg", _bot_id(), chat_id, user_id) if chat_id else None
    allowed = [str(c) for c in _chat_ids()]
    _low = (text or "").strip().lower()
    # So khớp substring (như Zalo Bot) — tag bot kèm /id ("@Bot /id", "/id@Bot")
    # vẫn phải nhận ra lệnh /id để gửi về thread admin.
    _is_id = _low in {"/id", "id", "chatid"} or "/id" in _low or "chatid" in _low \
        or ("chat id" in _low and len(_low) <= 40)
    # Admin thread → workspace độc lập (đặt tên bot / lưu người lạ / pending)
    if chat_id and text and _is_admin_chat(chat_id):
        try:
            from services.admin_workspace import handle_admin_text
            _ar = handle_admin_text("tg", chat_id, text)
            if _ar:
                send_message(chat_id, _ar)
                return
        except Exception as exc:
            logger.warning("admin workspace handle: %s", exc)

    # Tag / @mention sớm (cần cho alert nhóm multi-bot + filter phản hồi)
    _req_early, _kw_early = (
        _caps.mention_required_for("tg", _bot_id(), chat_id) if chat_id else (False, "")
    )
    _tagged_early = bool(native_mention) or (
        bool(_kw_early) and str(_kw_early).lower() in (text or "").lower()
    )
    # Người lạ: ghi danh bạ + báo admin 1 lần (không spam khi known / đã notified)
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
        # Đã known/cấu hình: vẫn cập nhật last_seen, không alert
        try:
            from services import channel_contacts as _cc
            _cc.upsert(
                "tg", _bot_id(), chat_id, user_id=user_id,
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
                    + f"Bot: Telegram {_bot_id()}")
        # Gửi MỌI admin của bot này; không có admin → trả /id cho người gửi.
        if not _notify_all_admins(
                f"🆔 Yêu cầu /id từ {'nhóm' if is_group else 'chat'}:\n{_id_info}"):
            send_message(chat_id, _id_info)
        return

    # Chuyển tiếp webhook (HA / n8n / URL bất kỳ) theo 'Lọc chức năng theo
    # thread' — TRƯỚC bộ lọc tag (tin nhóm không tag vẫn chuyển được).
    # Thread bật → mọi user (trừ user tắt riêng); thread không bật → user nào
    # bật + có URL riêng thì chuyển tới đó. User bật tag_mode: tin TAG bot →
    # CHỈ chuyển webhook (AI im lặng); không tag → ChatGPT trả lời như thường.
    _req_fw, _kw_fw = _caps.mention_required_for("tg", _bot_id(), chat_id)
    _tagged = bool(native_mention) or (
        bool(_kw_fw) and _kw_fw.lower() in (text or "").lower()
    )
    if _caps.forward_event("tg", _bot_id(), chat_id, user_id, {
        "platform": "telegram", "bot": _bot_id(), "chat_id": chat_id,
        "user_id": user_id, "sender": sender, "is_group": is_group,
        "text": text or "", "tagged": _tagged,
        "has_photo": bool(photo),
        "document": str((document or {}).get("file_name") or ""),
    }, tagged=_tagged):
        return

    # Bộ lọc TAG: nếu thread bật 'bắt buộc tag' và đây là NHÓM → chỉ trả lời khi
    # bot được @mention (native) hoặc tin chứa từ khóa tag đã cấu hình. Không đạt
    # → im lặng (để không spam nhóm). Lệnh /id ở trên vẫn qua được.
    if is_group and chat_id:
        _req, _kw = _caps.mention_required_for("tg", _bot_id(), chat_id)
        if _req:
            _kw_l = (_kw or "").strip().lower()
            _mentioned = native_mention or (bool(_kw_l) and _kw_l in (text or "").lower())
            if not _mentioned:
                return

    # Trả lời ý định cho PDF đang chờ (1=RAG / 2=Word)?
    from services import pdf_intent as _pi
    _pkey = f"tg:{_bot_id()}:{chat_id}"
    if text and chat_id and _pi.has_pending(_pkey):
        _intent = _pi.parse_intent(text)
        if _intent:
            if _intent not in _pi.allowed_intents(_allow):
                return  # ý định PDF bị lọc → bỏ qua, không nhắn gì
            _do_pdf_intent(chat_id, _pi.pop_pending(_pkey), _intent)
            return

    # Trả lời yêu cầu cho ẢNH đang chờ (đã gửi ảnh không kèm caption)?
    from services import photo_intent as _phi
    if text and chat_id and _phi.has_pending(f"tg:{_bot_id()}:{chat_id}"):
        _pdata = _phi.pop_pending(f"tg:{_bot_id()}:{chat_id}")
        if _pdata:
            _do_photo_request(chat_id, _pdata, text.strip(), _allow)
            return

    # Handle photo — CÓ caption thì làm luôn (phân tích HAY tạo ảnh từ ảnh tùy
    # yêu cầu); KHÔNG caption thì hỏi lại muốn làm gì rồi chờ tin nhắn kế tiếp.
    if photo:
        _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        largest = max(photo, key=lambda p: p.get("file_size", 0))
        file_data = _download_file(largest["file_id"])
        if not file_data:
            send_message(chat_id, "📷 Không thể tải ảnh.")
            return
        caption = (text or "").strip()
        if not caption:
            from services import photo_intent as _phi
            _phi.set_pending(f"tg:{_bot_id()}:{chat_id}", file_data)
            send_message(chat_id, _phi.ASK)
            return
        _do_photo_request(chat_id, file_data, caption, _allow)
        return

    # Handle document (PDF) — HỎI ý định trước (1=RAG / 2=Word), không tự quyết.
    if document:
        doc_name = document.get("file_name", "document.pdf")
        if not str(doc_name).lower().endswith(".pdf"):
            send_message(chat_id, f"📎 Hiện chỉ hỗ trợ PDF. File: {doc_name}")
            return
        _pdf_intents = _pi.allowed_intents(_allow)
        if not _pdf_intents:
            return  # thread lọc không có nhóm tài liệu → bỏ qua PDF, không nhắn gì
        _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        file_data = _download_file(document.get("file_id", ""))
        if not file_data:
            send_message(chat_id, "❌ Không thể tải file PDF.")
            return
        _pdf_info = _pi.set_pending(f"tg:{_bot_id()}:{chat_id}", file_data, doc_name)
        send_message(chat_id, _pi.ask_text(doc_name, _pdf_intents, _pdf_info))
        return

    if not text or not chat_id:
        return

    _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})

    # Tiểu Vy orchestrator — supervised, capability-aware agent (persona +
    # memory + approval). Falls back to a plain model call if it errors so the
    # bot still answers.
    try:
        from services.agent import orchestrate
        out = orchestrate(text, chat_id, allow=_allow,
                          ha_fastpath=bool(_active_bot().get("ha_fastpath", True)))
        if out.get("silent"):
            return  # thread lọc yêu cầu chức năng bị tắt → bỏ qua, không nhắn gì
        reply = (out.get("text") or "").strip() or "..."
        image_url = out.get("image_url")
        if image_url:
            # _fetch_image_bytes né 403 hairpin (URL /images/ của chính mình
            # → tải qua localhost) để LUÔN gửi được ảnh thật thay vì link.
            img = _fetch_image_bytes(image_url)
            if img and send_photo(chat_id, img, caption=reply[:1000]).get("ok"):
                return
            if _api_call("sendPhoto", {"chat_id": chat_id, "photo": image_url,
                                       "caption": reply[:1000]}).get("ok"):
                return
            logger.warning("send image failed for %s", image_url[:120])
            reply = f"{reply}\n{image_url}"
        video_path = out.get("video_path")
        video_url = out.get("video_url")
        if video_path or video_url:
            try:
                if video_path:
                    with open(video_path, "rb") as f:
                        vid = f.read()
                else:
                    vid = urllib.request.urlopen(video_url, timeout=120).read()
                send_video(chat_id, vid, caption=reply[:1000])
                return
            except Exception as exc:
                logger.warning("send video failed: %s", exc)
                if video_url:
                    reply = f"{reply}\n{video_url}"
        audio_path = out.get("audio_path")
        audio_url = out.get("audio_url")
        if audio_path or audio_url:
            try:
                if audio_path:
                    with open(audio_path, "rb") as f:
                        aud = f.read()
                else:
                    aud = urllib.request.urlopen(audio_url, timeout=120).read()
                send_audio(chat_id, aud, caption=reply[:1000])
                return
            except Exception as exc:
                logger.warning("send audio failed: %s", exc)
                if audio_url:
                    reply = f"{reply}\n{audio_url}"
        # Text path: preserve choices from orchestrator for inline keyboard
        if out.get("choices") and not any(
            out.get(k) for k in ("image_url", "video_path", "video_url", "audio_path", "audio_url")
        ):
            _send_agent_reply(chat_id, out)
        else:
            send_message(chat_id, reply)
        _maybe_voice_reply(chat_id, user_id, reply)
        return
    except Exception as exc:
        logger.warning("orchestrator error for %s: %s", chat_id, exc)

    # Fallback: plain model call
    key = f"tg_{chat_id}"
    if key not in _conversations:
        _conversations[key] = [{
            "role": "system",
            "content": "Bạn là trợ lý AI qua Telegram. Trả lời ngắn gọn, chính xác bằng tiếng Việt."
        }]
    _conversations[key].append({"role": "user", "content": text})
    if len(_conversations[key]) > MAX_HISTORY:
        _conversations[key] = [_conversations[key][0]] + _conversations[key][-(MAX_HISTORY - 1):]

    base_url = str(config.get().get("api_base_url", "")).strip().rstrip("/") or "http://127.0.0.1/v1"
    auth_header = config.auth_key
    payload = {"model": _tg_model(), "messages": _conversations[key], "stream": False,
               "x_channel": "tg"}
    if _allow is not None:
        # Fallback cũng phải mang bộ lọc — kẻo orchestrator lỗi là gateway
        # tự bật HA/ssh/search cho thread bị cấm.
        payload["x_allowed_groups"] = sorted(_allow)
        payload["x_no_smart_home"] = "homeassistant" not in _allow
    try:
        req = urllib.request.Request(f"{base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {auth_header}", "Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=300)
        reply = json.loads(resp.read().decode()).get("choices", [{}])[0].get("message", {}).get("content", "")
        reply = reply.strip() or "..."
    except Exception as exc:
        logger.warning("AI error for %s: %s", chat_id, exc)
        reply = "⏳ Hệ thống bận, thử lại."

    _conversations[key].append({"role": "assistant", "content": reply})
    if len(_conversations[key]) > MAX_HISTORY:
        _conversations[key] = [_conversations[key][0]] + _conversations[key][-(MAX_HISTORY - 1):]

    send_message(chat_id, reply)


def _cmd(text: str, chat_id: str) -> str | None:
    cmd = text.lower().split()[0]
    key = f"tg_{chat_id}"
    if cmd == "/start":
        return f"👋 **chatgpt2api Bot**\nModel: `{_tg_model()}`\n/help /clear /model"
    elif cmd == "/help":
        return "📌 Hỗ trợ: chat AI, MCP tools, tra cứu.\nLệnh: /clear /model"
    elif cmd == "/clear":
        _conversations.pop(key, None)
        return "✅ Đã xóa lịch sử."
    elif cmd == "/model":
        return f"🤖 `{_tg_model()}`"
    return None


def get_status() -> dict:
    bots = _bots()
    return {
        "configured": bool(bots),
        "webhook_url": str(config.get().get("telegram_webhook_url", "")).strip(),
        "bots_count": len(bots),
        "bots_enabled": sum(1 for b in bots if b.get("enabled", True)),
    }
