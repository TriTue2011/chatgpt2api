"""Telegram Bot — 2-way AI chat channel through chatgpt2api.

Each Telegram chat = a chat session with full AI + MCP tool support.

Transport / format / Bot API surface live in ``services.telegram`` (client,
format, updates, rich). This module keeps webhook routing + agent wiring.
"""

from __future__ import annotations

import logging
import json
import threading
import time
import urllib.request
from typing import Any

from services.config import config
from services.telegram import (
    DEFAULT_API_BASE,
    detect_bot_mention,
    get_client,
    is_duplicate_update,
    llm_to_legacy_markdown,
    match_bot_by_secret,
    webhook_secret_for,
)
from services.telegram.client import TelegramClient

logger = logging.getLogger(__name__)

TELEGRAM_API = DEFAULT_API_BASE


def _to_telegram_markdown(text: str) -> str:
    """Convert LLM markdown to Telegram legacy Markdown (*bold*)."""
    return llm_to_legacy_markdown(text)


def _cli(token: str | None = None) -> TelegramClient:
    """Active-bot client (or explicit token)."""
    tok = (token or _bot_token()).strip()
    return get_client(tok)
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


def _tg_model(chat_id: str | None = None) -> str:
    """Model: admin.ai_model (nếu chat admin) → bot.ai_model → telegram_ai_model → AI text."""
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
        g = str(config.get().get("telegram_ai_model") or "").strip()
        if g:
            return g
    except Exception:
        pass
    return "AI text"


def _chat_ids() -> list:
    return list(_active_bot().get("chat_ids") or [])


def _webhook_secret_for(token: str) -> str:
    """Secret ổn định sinh từ token — xem services.telegram.updates.webhook_secret_for."""
    return webhook_secret_for(token)


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
    """Báo chat/nhóm mới (💬) — chỉ admin bật newchat_alert; không dùng 🔔/📋."""
    c = config.get()
    if not bool(c.get("telegram_newchat_alert_enabled", True)):
        return
    bot = _active_bot() or {}
    if not bool(bot.get("newchat_alert_enabled", True)):
        return
    try:
        from services import channel_contacts as _cc
        from services import admin_workspace as _aw
        from services.admin_workspace import admin_entries
        ok, rec = _cc.should_alert_new(
            "tg", _bot_id(), chat_id,
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
                bl = _aw.bot_display_name("tg", _bot_id(), aid)
                msg = base.replace(
                    f"bot **{_cc.bot_label('tg', _bot_id())}**",
                    f"bot **{bl}**",
                    1,
                )
                msg += _aw.start_save_prompt("tg", aid, rec)
                # newchat: dùng notify path có emphasize (HTML bold)
                try:
                    from services.telegram.emphasis import emphasize_text
                    from services.telegram.format import llm_to_html
                    body = emphasize_text(msg, bot=bot, chat_id=aid)
                    html_body = llm_to_html(body)
                    r = _api_call("sendMessage", {
                        "chat_id": str(aid), "text": html_body[:4000],
                        "parse_mode": "HTML",
                        "link_preview_options": {"is_disabled": True},
                    })
                    if not r.get("ok"):
                        r = _api_call("sendMessage", {
                            "chat_id": str(aid), "text": msg[:4000],
                            "link_preview_options": {"is_disabled": True},
                        })
                    if r.get("ok"):
                        sent += 1
                except Exception:
                    if _send_admin_thread(aid, msg):
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
        logger.warning("telegram new-contact alert failed: %s", exc)


def notify_admin(text: str, category: str = "") -> None:
    """Gửi admin theo category:

    - account_log (📋): notify_enabled + account_log_enabled
    - system / \"\" (🔔): notify_enabled — lỗi & cảnh báo
    - newchat (💬): newchat_alert_enabled — chat/nhóm mới (thread ID)
    """
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
            if is_account_update and not bot.get("account_update_log_enabled", False):
                continue
            if is_account_log and not bot.get("account_log_enabled", True):
                continue
            _current.bot = bot
            targets: list[str] = []
            for e in admin_entries(bot):
                if is_newchat:
                    if e.get("newchat_alert_enabled") is False:
                        continue
                    # newchat: không yêu cầu 🔔 (tách hẳn)
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
            for cid in targets:
                try:
                    body = text[:4000]
                    try:
                        from services.telegram.emphasis import emphasize_text
                        body = emphasize_text(body, bot=bot, chat_id=cid)
                    except Exception:
                        pass
                    # Tele: đậm/code (HTML); không có màu
                    try:
                        from services.telegram.format import llm_to_html
                        html_body = llm_to_html(body)
                        r = _api_call("sendMessage", {
                            "chat_id": str(cid), "text": html_body[:4000],
                            "parse_mode": "HTML",
                            "link_preview_options": {"is_disabled": True},
                        })
                        if not r.get("ok"):
                            r = _api_call("sendMessage", {
                                "chat_id": str(cid), "text": body[:4000],
                                "link_preview_options": {"is_disabled": True},
                            })
                    except Exception:
                        r = _api_call("sendMessage", {
                            "chat_id": str(cid), "text": body[:4000],
                            "link_preview_options": {"is_disabled": True},
                        })
                    if r.get("ok"):
                        sent += 1
                except Exception:
                    pass
            if sent == 0 and (
                bot.get("fallback_enabled")
                or any(e.get("fallback_enabled") for e in admin_entries(bot))
            ):
                _try_bot_fallback(bot, text)
    finally:
        _current.bot = None


def _try_bot_fallback(bot: dict, text: str) -> None:
    """Fallback: gửi tới admin có fallback_enabled (mỗi admin bật/tắt riêng)."""
    threads: list[str] = []
    try:
        from services.admin_workspace import fallback_admin_threads
        threads = list(fallback_admin_threads(bot))
    except Exception:
        threads = []
    # Legacy bot-level fallback_thread
    legacy = str(bot.get("fallback_thread") or "").strip()
    if legacy and legacy not in threads:
        threads.append(legacy)
    if not threads and bot.get("fallback_enabled"):
        try:
            from services.admin_workspace import admin_entries
            for e in admin_entries(bot):
                if e.get("notify_enabled", True) and e.get("chat_id"):
                    threads.append(str(e["chat_id"]).strip())
                    break
        except Exception:
            pass
    if not threads:
        return
    prev = _cur_bot()
    try:
        _current.bot = bot
        for thread in threads:
            try:
                _api_call("sendMessage", {
                    "chat_id": thread,
                    "text": (text[:3900] + "\n(Fallback admin thread)"),
                    "link_preview_options": {"is_disabled": True},
                })
            except Exception as exc:
                logger.warning("tg bot fallback failed (%s): %s", thread, exc)
    finally:
        _current.bot = prev


def _api_call(method: str, data: dict | None = None) -> dict:
    """JSON Bot API call via services.telegram.TelegramClient (429 retry)."""
    return _cli().call(method, data, timeout=15)


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
                "allowed_updates": [
                    "message", "edited_message", "callback_query", "my_chat_member",
                ],
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
    """Send text with **auto** format: rich → HTML → plain (content-aware).

    Emphasis (bold numbers / key info) respects per-admin-thread toggle on the
    active bot config. See ``services.telegram.emphasis.resolve_emphasis_settings``.
    """
    results = _cli().send_message_safe(
        chat_id, text or "",
        parse_mode="auto",
        convert_llm_md=True,
        split=True,
        link_preview_disabled=True,
        reply_markup=reply_markup,
        plain_fallback=True,
        allow_rich=True,
        bot=_active_bot(),
    )
    if not results:
        return {"ok": False}
    last = results[-1]
    fmt = last.get("_c2a_format")
    if fmt:
        logger.debug(
            "tg send auto format=%s reason=%s chat=%s",
            fmt, last.get("_c2a_format_reason"), chat_id,
        )
    for r in results:
        if not r.get("ok"):
            return r
    return last


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
    return _cli().send_photo(chat_id, photo_bytes, caption=caption or "")


def send_video(chat_id: int | str, video_bytes: bytes, caption: str = "") -> dict:
    """Gửi video qua Telegram."""
    return _cli().send_video(chat_id, video_bytes, caption=caption or "")


def send_audio(chat_id: int | str, audio_bytes: bytes, caption: str = "") -> dict:
    """Gửi file nhạc/audio qua Telegram (hiện player bấm nghe)."""
    return _cli().send_audio(chat_id, audio_bytes, caption=caption or "")


def send_document(chat_id: int | str, doc_bytes: bytes, filename: str, caption: str = "") -> dict:
    """Gửi file/document qua Telegram."""
    return _cli().send_document(
        chat_id, doc_bytes, filename=filename or "file.bin", caption=caption or "",
    )


async def handle_webhook(request) -> dict:
    """Handle incoming Telegram webhook POST. Returns immediately, processes AI in background."""
    try:
        hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        body = await request.json()
    except Exception:
        return {"ok": False}
    bot = match_bot_by_secret(_bots(), hdr, secret_fn=_webhook_secret_for)
    if bot is None:
        logger.warning("Telegram webhook bad/ambiguous secret")
        return {"ok": False}

    # De-dupe Telegram webhook retries
    bid_pub = _bot_public_id(bot)
    if is_duplicate_update(bid_pub, body.get("update_id")):
        return {"ok": True}

    # Inline keyboard callbacks (ask-with-choices)
    cq = body.get("callback_query")
    if cq:
        _current.bot = bot
        t = threading.Thread(target=_handle_callback_query, args=(cq, bot), daemon=True)
        t.start()
        return {"ok": True}

    # my_chat_member: user block/unblock — ghi log nhẹ, không agent
    mcm = body.get("my_chat_member")
    if isinstance(mcm, dict):
        try:
            st = ((mcm.get("new_chat_member") or {}).get("status") or "")
            chat = (mcm.get("chat") or {}).get("id")
            logger.info("tg my_chat_member bot=%s chat=%s status=%s", bid_pub, chat, st)
        except Exception:
            pass
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
    _fn = str(frm.get("first_name") or "").strip()
    _ln = str(frm.get("last_name") or "").strip()
    sender = (" ".join(x for x in (_fn, _ln) if x).strip()
              or str(frm.get("username") or "").strip())
    user_id = str(frm.get("id") or "").strip()
    is_group = str(chat.get("type") or "") in {"group", "supergroup"}
    chat_name = str(chat.get("title") or "").strip()
    if not chat_name and not is_group:
        chat_name = str(chat.get("first_name") or chat.get("username") or "").strip()

    _current.bot = bot
    try:
        native_mention = detect_bot_mention(
            msg, bot_username=_bot_username(), bot_id=_bot_id(),
        )
    except Exception:
        native_mention = False

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
    return _cli().download_file(file_id)


def _do_pdf_intent(
    chat_id: str,
    pending: dict | None,
    intent: str,
    *,
    grade: int | None = None,
    subject: str | None = None,
    user_id: str = "",
) -> None:
    """PDF chờ: rag_knowledge | rag_teacher | word | excel."""
    if not pending:
        return
    import os
    import time as _time
    from services import pdf_intent as _pi
    path, name = pending["path"], pending["name"]
    t0 = _time.time()
    kind = "pdf_rag"
    reply = ""
    status = "ok"
    err = ""
    _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    try:
        if intent == _pi.WORD:
            kind = "pdf_word"
            from services.pdf_to_word import convert_pdf_to_docx
            docx_path = (path[:-4] if path.endswith(".pdf") else path) + ".docx"
            r = convert_pdf_to_docx(path, docx_path)
            if r.get("ok"):
                with open(docx_path, "rb") as f:
                    data = f.read()
                base = name[:-4] if name.lower().endswith(".pdf") else name
                how = {"layout": "giữ layout", "scan": "AI OCR scan — giữ bảng + hình"} \
                    .get(r.get("method"), "OCR (PDF scan)")
                reply = f"📝 Bản Word ({how})"
                send_document(chat_id, data, f"{base}.docx", caption=reply)
                try:
                    os.unlink(docx_path)
                except Exception:
                    pass
            else:
                status = "error"
                err = str(r.get("error") or "")[:150]
                reply = f"⚠️ Không chuyển được sang Word: {err}"
                send_message(chat_id, reply)
        elif intent == _pi.EXCEL:
            kind = "pdf_excel"
            from services.pdf_to_excel import convert_pdf_to_xlsx
            xlsx_path = (path[:-4] if path.endswith(".pdf") else path) + ".xlsx"
            r = convert_pdf_to_xlsx(path, xlsx_path)
            if r.get("ok"):
                with open(xlsx_path, "rb") as f:
                    data = f.read()
                base = name[:-4] if name.lower().endswith(".pdf") else name
                reply = (
                    f"📊 Bản Excel ({r.get('method')}, {r.get('sheets')} sheet"
                    f"{', ' + str(r.get('pages_extracted')) + ' trang' if r.get('pages_extracted') else ''})"
                )
                send_document(
                    chat_id, data, f"{base}.xlsx",
                    caption=reply,
                )
                try:
                    os.unlink(xlsx_path)
                except Exception:
                    pass
            else:
                status = "error"
                err = str(r.get("error") or "")[:150]
                reply = f"⚠️ Không chuyển được sang Excel: {err}"
                send_message(chat_id, reply)
        elif intent == _pi.RAG_TEACHER:
            kind = "pdf_teacher"
            if not grade or not subject:
                reply = "⚠️ Thiếu lớp/môn cho RAG teacher."
                status = "error"
                err = "missing grade/subject"
                send_message(chat_id, reply)
            else:
                r = _pi.ingest_teacher(path, grade=int(grade), subject=str(subject), name=name)
                reply = r.get("text") or r.get("error") or "Xong."
                if r.get("error") and not r.get("ok", True):
                    status = "error"
                    err = str(r.get("error") or "")[:200]
                send_message(chat_id, reply)
        else:
            # rag_knowledge (default / legacy rag)
            kind = "pdf_rag"
            r = _pi.ingest_knowledge(
                path, name=name, model=_tg_model(chat_id),
                who=str(user_id or chat_id), platform="tg", chat_id=str(chat_id),
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
            else:
                reply = "\n\n".join(parts)
                send_message(chat_id, reply)
                try:
                    from services import pdf_images as _pimg
                    for cap, iid in _pimg.find_markers(r.get("summary") or "")[:4]:
                        p = _pimg.image_path(iid)
                        if p:
                            send_photo(chat_id, p.read_bytes(),
                                       caption=(cap or "Hình trong tài liệu")[:200])
                except Exception as exc:
                    logger.warning("gửi ảnh marker PDF lỗi: %s", exc)
    except Exception as e:
        status = "error"
        err = str(e)[:200]
        reply = f"❌ Lỗi xử lý PDF: {e}"
        logger.warning("pdf intent %s error: %s", intent, e)
        send_message(chat_id, reply)
    finally:
        try:
            from services.agent import run_journal as _rj
            _rj.log_channel_event(
                channel="tg",
                kind=kind,
                user_text=f"PDF:{name} → {intent}",
                reply_text=str(reply or "")[:800],
                user_id=str(user_id or chat_id),
                source_account=_bot_id(),
                source_peer=str(chat_id),
                model=_tg_model(chat_id) if intent not in ("word", "excel") else "",
                status=status,
                error=err,
                duration_ms=int((_time.time() - t0) * 1000),
                meta={"file": name, "intent": intent},
            )
        except Exception:
            pass
        try:
            os.unlink(path)
        except Exception:
            pass


def _fetch_image_bytes(url: str) -> bytes | None:
    """Tải bytes ảnh. Self ``/images/`` → loopback; URL ngoài → net_guard (SSRF)."""
    try:
        from services import net_guard
        return net_guard.fetch_media(url, timeout=60, max_bytes=25 * 1024 * 1024)
    except Exception as e:
        logger.warning("fetch image blocked/failed: %s", e)
        return None


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
        # Resolve intent: explicit > classify caption
        it = intent or (
            _phi.GENERATE if _phi.classify(request) == _phi.GENERATE else _phi.ANALYZE
        )
        allowed = _phi.allowed_intents(allow)
        if it not in allowed and allow is not None:
            # generate blocked without image group
            status = "blocked"
            err = f"intent {it} not allowed"
            return

        if it == _phi.GENERATE:
            kind = "photo_generate"
            out = _phi.generate_from_photo(file_data, request, channel="tg")
            try:
                from services import net_guard
                out = net_guard.filter_agent_output(out if isinstance(out, dict) else {})
            except Exception:
                pass
            url = out.get("image_url")
            cap = (out.get("text") or "Đây ạ 🎨")[:1000]
            reply = cap
            img = out.get("image_bytes") or (_fetch_image_bytes(url) if url else None)
            if img and send_photo(chat_id, img, caption=cap).get("ok"):
                return
            if url:
                from services import net_guard as _ng
                if _ng.is_allowed_egress_url(str(url)) and not str(url).startswith("data:"):
                    if _api_call("sendPhoto", {"chat_id": chat_id, "photo": url, "caption": cap}).get("ok"):
                        return
            reply = out.get("text") or "Em chưa tạo được ảnh ạ."
            send_message(chat_id, reply)
            return

        if it == _phi.RAG_KNOWLEDGE:
            kind = "photo_rag"
            r = _phi.ingest_knowledge_from_photo(
                file_data, prompt=request, who=user_id or chat_id,
                platform="tg", chat_id=str(chat_id), channel="tg",
            )
            reply = r.get("text") or r.get("error") or "Xong."
            if r.get("error") and not r.get("ok", True):
                status = "error"
                err = str(r.get("error") or "")[:200]
            send_message(chat_id, reply)
            return

        if it == _phi.RAG_TEACHER:
            kind = "photo_rag"
            reply = "⚠️ RAG teacher ảnh cần lớp + môn (vd: `5 toán`)."
            send_message(chat_id, reply)
            return

        # analyze
        kind = "photo_analyze"
        answer = _phi.analyze_photo(file_data, request, channel="tg")
        reply = answer or ""
        send_message(chat_id, answer)
    except Exception as exc:
        status = "error"
        err = str(exc)[:200]
        raise
    finally:
        try:
            from services.agent import run_journal as _rj
            _rj.log_channel_event(
                channel="tg",
                kind=kind,
                user_text=(request or "[ảnh]")[:500],
                reply_text=str(reply or "")[:800],
                user_id=str(user_id or chat_id),
                source_account=_bot_id(),
                source_peer=str(chat_id),
                status=status,
                error=err,
                duration_ms=int((_time.time() - t0) * 1000),
            )
        except Exception:
            pass


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
    # chat_ids đã bỏ trên UI — AI thường qua bộ lọc thread; admin luôn được phép
    allowed = [str(c) for c in _chat_ids()]
    _is_admin = bool(chat_id and _is_admin_chat(chat_id))
    if _is_admin and chat_id and chat_id not in allowed:
        allowed.append(str(chat_id))
    _low = (text or "").strip().lower()
    # So khớp substring (như Zalo Bot) — tag bot kèm /id ("@Bot /id", "/id@Bot")
    # vẫn phải nhận ra lệnh /id để gửi về thread admin.
    _is_id = _low in {"/id", "id", "chatid"} or "/id" in _low or "chatid" in _low \
        or ("chat id" in _low and len(_low) <= 40)
    # Admin thread → workspace độc lập (đặt tên bot / lưu người lạ / pending)
    if chat_id and text and _is_admin:
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

    # Bộ lọc TAG: required → native @mention HOẶC keyword (keyword rỗng không
    # chặn native — tag_gate_allows). /id đã return ở trên.
    if is_group and chat_id:
        _req, _kw = _caps.mention_required_for("tg", _bot_id(), chat_id)
        if _req and not _caps.tag_gate_allows(
            required=True,
            keyword=_kw,
            text=text or "",
            native_tagged=bool(native_mention),
            platform_group_delivery=False,
        ):
            return

    # Trả lời ý định PDF: 1 kiến thức / 2 teacher / 3 Word / 4 Excel
    from services import pdf_intent as _pi
    _pkey = f"tg:{_bot_id()}:{chat_id}"
    if text and chat_id and _pi.has_pending(_pkey):
        _pend = _pi.get_pending(_pkey) or {}
        # Bước 2: đang chờ lớp + môn cho RAG teacher
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
        _allowed_i = _pi.allowed_intents(_allow)
        _intent = _pi.parse_intent(text, _allowed_i)
        if _intent:
            if _intent == "rag":
                _intent = _pi.RAG_KNOWLEDGE
            if _intent not in _allowed_i:
                return  # ý định PDF bị lọc → im lặng
            if _intent == _pi.RAG_TEACHER:
                _pi.update_pending(_pkey, stage="teacher_meta", intent=_pi.RAG_TEACHER)
                send_message(chat_id, _pi.ASK_TEACHER)
                return
            _do_pdf_intent(chat_id, _pi.pop_pending(_pkey), _intent, user_id=user_id)
            return

    # Ảnh chờ: menu 1–4 / hỏi prompt / teacher meta
    from services import photo_intent as _phi
    _phkey = f"tg:{_bot_id()}:{chat_id}"
    if text and chat_id and _phi.has_pending(_phkey):
        _pend = _phi.get_pending(_phkey) or {}
        _allowed_ph = _phi.allowed_intents(_allow)
        stage = str(_pend.get("stage") or "choose")
        if stage == "teacher_meta":
            from services import pdf_intent as _pi
            meta = _pi.parse_teacher_meta(text)
            if not meta:
                send_message(chat_id, _phi.ASK_TEACHER)
                return
            full = _phi.pop_pending_full(_phkey)
            if full and full.get("data"):
                r = _phi.ingest_teacher_from_photo(
                    full["data"], grade=meta["grade"], subject=meta["subject"],
                    channel="tg",
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
            # Caption-style: text is already the prompt (or knowledge free-text)
            full = _phi.pop_pending_full(_phkey)
            if full and full.get("data"):
                _do_photo_request(
                    chat_id, full["data"], text.strip(), _allow,
                    intent=intent, user_id=user_id,
                )
            return

    # Handle photo — có caption: thử parse menu/intent; không caption: menu
    if photo:
        _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        largest = max(photo, key=lambda p: p.get("file_size", 0))
        file_data = _download_file(largest["file_id"])
        if not file_data:
            send_message(chat_id, "📷 Không thể tải ảnh.")
            return
        caption = (text or "").strip()
        _allowed_ph = _phi.allowed_intents(_allow)
        if not caption:
            _phi.set_pending(_phkey, file_data)
            send_message(chat_id, _phi.ask_text(_allowed_ph))
            return
        # Caption có sẵn: nếu là prompt analyze/generate → làm luôn; else menu+prompt
        intent = _phi.parse_intent(caption, _allowed_ph) or (
            _phi.GENERATE if _phi.classify(caption) == _phi.GENERATE else _phi.ANALYZE
        )
        if intent not in _allowed_ph and _allow is not None:
            if intent == _phi.GENERATE:
                return
        if intent == _phi.RAG_TEACHER:
            _phi.set_pending(_phkey, file_data, stage="teacher_meta", intent=intent)
            send_message(chat_id, _phi.ASK_TEACHER)
            return
        if intent in {_phi.ANALYZE, _phi.GENERATE} and _phi.needs_prompt(intent, caption):
            _phi.set_pending(_phkey, file_data, stage="need_prompt", intent=intent)
            send_message(
                chat_id,
                _phi.ASK_PROMPT_GENERATE if intent == _phi.GENERATE else _phi.ASK_PROMPT_ANALYZE,
            )
            return
        _do_photo_request(chat_id, file_data, caption, _allow, intent=intent, user_id=user_id)
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
        try:
            from services.admin_workspace import ha_fastpath_for_chat as _ha_fp
            _fp = _ha_fp(_active_bot(), chat_id)
        except Exception:
            _fp = bool(_active_bot().get("ha_fastpath", True))
        _model = _tg_model(chat_id)
        # Nhóm: mỗi USER một phiên riêng (lịch sử/persona/approval độc lập).
        # Chat 1-1 giữ key cũ (chat_id) để không mất lịch sử hiện có.
        _skey = str(chat_id)
        try:
            from services.config import config as _c2
            if (str(chat_id).startswith("-") and user_id
                    and getattr(_c2, "group_user_isolation", True)):
                _skey = f"{chat_id}:u{user_id}"
        except Exception:
            pass
        out = orchestrate(text, _skey, allow=_allow, ha_fastpath=_fp, model=_model)
        # P0#5 defense-in-depth: lọc lại media URL/path (orchestrator đã lọc).
        try:
            from services import net_guard
            out = net_guard.filter_agent_output(out if isinstance(out, dict) else {})
        except Exception:
            pass
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
            # Chỉ nhờ Telegram server-side fetch khi URL public đã qua guard.
            from services import net_guard as _ng
            if _ng.is_allowed_egress_url(str(image_url)) and not str(image_url).startswith("data:"):
                if _api_call("sendPhoto", {"chat_id": chat_id, "photo": image_url,
                                           "caption": reply[:1000]}).get("ok"):
                    return
            logger.warning("send image failed for %s", str(image_url)[:120])
            reply = f"{reply}\n{image_url}"
        video_path = out.get("video_path")
        video_url = out.get("video_url")
        if video_path or video_url:
            try:
                if video_path:
                    with open(video_path, "rb") as f:
                        vid = f.read()
                else:
                    from services import net_guard
                    vid = net_guard.fetch_media(str(video_url), timeout=120)
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
                    from services import net_guard
                    aud = net_guard.fetch_media(str(audio_url), timeout=120)
                send_audio(chat_id, aud, caption=reply[:1000])
                return
            except Exception as exc:
                logger.warning("send audio failed: %s", exc)
                if audio_url:
                    reply = f"{reply}\n{audio_url}"
        doc_path = out.get("doc_path")
        if doc_path:
            try:
                from pathlib import Path as _P
                _p = _P(str(doc_path))
                send_document(chat_id, _p.read_bytes(), _p.name,
                              caption=reply[:1000])
                return
            except Exception as exc:
                logger.warning("send doc failed: %s", exc)
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
    payload = {"model": _tg_model(chat_id), "messages": _conversations[key], "stream": False,
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
        return f"👋 **chatgpt2api Bot**\nModel: `{_tg_model(chat_id)}`\n/help /clear /model"
    elif cmd == "/help":
        return "📌 Hỗ trợ: chat AI, MCP tools, tra cứu.\nLệnh: /clear /model"
    elif cmd == "/clear":
        _conversations.pop(key, None)
        return "✅ Đã xóa lịch sử."
    elif cmd == "/model":
        return f"🤖 `{_tg_model(chat_id)}`"
    return None


def get_status() -> dict:
    bots = _bots()
    return {
        "configured": bool(bots),
        "webhook_url": str(config.get().get("telegram_webhook_url", "")).strip(),
        "bots_count": len(bots),
        "bots_enabled": sum(1 for b in bots if b.get("enabled", True)),
    }
