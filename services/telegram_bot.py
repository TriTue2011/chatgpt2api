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
from services.telegram.constants import MAX_UPLOAD_FILE_BYTES
from services.ingress_guard import make_worker_pool, read_json_limited, BodyTooLarge


def _doc_media_co_tran(kieu: str, src: str, max_bytes: int, nhan: str) -> bytes:
    """Đọc media để GỬI đi, có trần dung lượng. Vượt trần → ValueError.

    Vì sao cần: bản cũ `open(src).read()` / `Path.read_bytes()` nạp cả tệp vào
    RAM rồi `call_multipart` dựng thêm một bản sao nữa trong bộ đệm multipart —
    một video 2GB do provider trả về là 4GB RAM. Telegram cũng từ chối tệp quá
    50MB, nên đọc hết rồi mới biết là phí hoàn toàn.

    Với tệp trên đĩa: hỏi `stat()` TRƯỚC khi đọc, nên tệp quá lớn không tốn một
    byte RAM nào. Với URL: `fetch_media` đã có sẵn tham số `max_bytes` (đi kèm
    kiểm SSRF và redirect) — trước đây gọi mà không truyền nên nó dùng mặc định
    rộng hơn trần thật của Telegram.
    """
    if kieu == "path":
        from pathlib import Path as _P
        p = _P(src)
        co = p.stat().st_size
        if co > max_bytes:
            raise ValueError(
                f"{nhan} quá lớn: {co // (1024 * 1024)}MB, trần {max_bytes // (1024 * 1024)}MB"
            )
        return p.read_bytes()
    from services import net_guard
    return net_guard.fetch_media(src, timeout=120, max_bytes=max_bytes)

logger = logging.getLogger(__name__)

TELEGRAM_API = DEFAULT_API_BASE

# Bound worker AI Telegram (webhook): giữ slot tới khi _process_message /
# _handle_callback_query xong. Trước đây webhook spawn thread không giới hạn.
_tg_worker = make_worker_pool("telegram", 24)


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


def _cur_topic() -> int | None:
    """Topic (forum) của tin đang xử lý — để TRẢ LỜI ĐÚNG TOPIC.

    Nhóm bật Topics: mỗi tin có `message_thread_id`. Không truyền lại khi gửi thì
    câu trả lời rơi vào topic General thay vì chỗ người ta hỏi. Topic General
    không có id → None (gửi như nhóm thường)."""
    t = getattr(_current, "topic", None)
    try:
        return int(t) if t else None
    except (TypeError, ValueError):
        return None


def _split_chat_topic(chat_id: int | str) -> tuple[str, int | None]:
    """Tách đích dạng ``'<chat_id>:<topic_id>'`` → (chat_id, message_thread_id).

    Nhóm forum Telegram: mỗi topic có ``message_thread_id`` riêng. Cho phép ghi
    đích admin/nhóm là ``'-1003837425521:5'`` để bot gửi THẲNG vào topic 5 thay
    vì General. Không có ':<số>' → topic None (General / nhóm thường). Chỉ tách
    khi cả hai vế là SỐ (chat có thể âm '-100…'), tránh nhầm URL/username."""
    s = str(chat_id).strip()
    head, sep, tail = s.rpartition(":")
    if sep and tail.isdigit() and head.lstrip("-").isdigit():
        return head, int(tail)
    return s, None


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


def _bot_username(no_block: bool = False) -> str:
    """Username bot (không '@', lowercase) — getMe 1 lần, cache theo token.
    Dùng để nhận diện @mention native trong nhóm.

    no_block=True: CHỈ đọc cache, KHÔNG gọi getMe — dùng trên event loop
    (handle_webhook) để không chặn webhook bằng 1 cuộc gọi mạng đồng bộ khi
    cache miss (vd ngay sau restart). Cache miss → trả "" (mention qua
    @username tạm thời không nhận ra tới khi cache ấm; reply/text_mention vẫn
    hoạt động vì không cần username). register_webhook() đã làm ấm cache lúc
    khởi động nên cửa sổ cache-miss trên đường webhook gần như không xảy ra."""
    token = _bot_token()
    if not token:
        return ""
    if token in _bot_username_cache:
        return _bot_username_cache[token]
    if no_block:
        return ""
    name = ""
    try:
        r = _api_call("getMe")
        if r.get("ok"):
            name = str((r.get("result") or {}).get("username") or "").strip().lower()
    except Exception:
        pass
    _bot_username_cache[token] = name
    return name


def _tg_model(chat_id: str | None = None, user_id: str | None = None) -> str:
    """Model: «Lọc thread» (thread/user) → admin.ai_model → bot.ai_model →
    telegram_ai_model → AI text. Model cài ở Lọc thread thắng, nhờ vậy admin chỉ
    là một thread bình thường (thêm vào Lọc thread rồi cài model là xong)."""
    bot = _active_bot()
    m = ""
    if chat_id:
        try:
            from services.admin_workspace import thread_model_for
            bid = str((bot or {}).get("token") or "").split(":")[0].strip()
            m = thread_model_for("tg", bid, chat_id, user_id, _cur_topic())
        except Exception:
            m = ""
    if not m and chat_id:
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


def khoa_phien(chat_id: str, topic_id: str = "", user_id: str = "") -> str:
    """Khoá phiên orchestrator của một lượt Telegram.

    Nhóm: mỗi USER một phiên riêng (lịch sử/persona/approval độc lập). Chat 1-1
    giữ key cũ (chat_id) để không mất lịch sử hiện có. Nhóm bật Topics: mỗi
    TOPIC một phiên riêng ('chat#topic') — lịch sử không trộn giữa các topic, và
    persona cài riêng topic có hiệu lực (persona.prompt_for fallback: user-topic
    → user-nhóm → topic → nhóm).

    PHẢI là chỗ DUY NHẤT tính khoá này. Trước đây khoá được dựng tại chỗ ở
    đường tin nhắn, còn đường bấm NÚT (_handle_callback_query) lại tra
    ask_choices bằng chat_id trần — trong nhóm hai khoá khác nhau nên nút bấm
    không tìm thấy lựa chọn nào và IM LẶNG không làm gì.

    Công tắc `group_user_isolation` đọc từ CONFIG (config.get()), không phải
    thuộc tính Python của đối tượng config. Bản cũ dùng
    `getattr(config, "group_user_isolation", True)` — `config` không có thuộc
    tính đó nên nó LUÔN trả về mặc định, tức công tắc không bao giờ có tác dụng.
    Mặc định vẫn là TÁCH (chủ máy chốt 06/08: "tách ở hội thoại live với bot").
    """
    base = f"{chat_id}#{topic_id}" if topic_id else str(chat_id)
    try:
        from services.agent.scope import tach_phien_theo_nguoi as _tach
        if str(chat_id).startswith("-") and user_id and _tach():
            return f"{base}:u{user_id}"
    except Exception:
        pass
    return base


def _la_thread_admin(chat_id: str) -> bool:
    """Chat này CÓ PHẢI nơi nhận thông báo admin — thuộc tính của CHAT.

    Khác `_is_admin_chat`: đây không phải câu hỏi về quyền. Nó quyết định thread
    có được im lặng / được whitelist / khỏi bị báo "chat lạ" — những thứ áp cho
    cả nhóm, kể cả thành viên thường trong nhóm admin.
    """
    return str(chat_id or "").strip() in set(_admin_ids_for_bot())


def _is_admin_chat(chat_id: str, user_id: str = "") -> bool:
    """True nếu lượt này thật sự là ADMIN của bot hiện tại.

    NHÓM thì phải xét NGƯỜI GỬI, không chỉ chat_id. Bản cũ chỉ so chat_id, nên
    khai một NHÓM làm admin thread là cấp quyền admin cho MỌI THÀNH VIÊN nhóm
    đó — kể cả người chỉ được thêm vào. Quyền admin ở đây mở ra chụp webcam,
    chụp màn hình, tắt máy từ xa, xem cả kho media và xoá tài khoản Codex.

    Chat 1-1: chat_id CHÍNH LÀ người dùng, nên so chat_id là đủ và đúng.
    Nhóm (id âm): chỉ nhận khi người gửi tự nó cũng nằm trong danh sách admin.
    """
    if not _la_thread_admin(chat_id):
        return False
    if not str(chat_id or "").strip().startswith("-"):
        return True
    uid = str(user_id or "").strip()
    return bool(uid) and uid in set(_admin_ids_for_bot())


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
            if is_account_update and not (
                bot.get("account_update_log_enabled", False)
                or any(e.get("account_update_log_enabled") for e in admin_entries(bot))
            ):
                continue
            if is_account_log and not bot.get("account_log_enabled", True):
                continue
            _current.bot = bot
            # Admin dạng CHUỖI ('-100…:975') không mang cờ per-entry được — khi
            # entry không nêu account_update_log_enabled thì KẾ THỪA cờ bot-level
            # (bật lên khi người dùng tick 🔄). Không kế thừa thì tick xong vẫn
            # bị bỏ qua vì mặc định False.
            _bot_au = bool(bot.get("account_update_log_enabled", False))
            targets: list[str] = []
            for e in admin_entries(bot):
                if is_newchat:
                    if e.get("newchat_alert_enabled") is False:
                        continue
                    # newchat: không yêu cầu 🔔 (tách hẳn)
                else:
                    if not e.get("notify_enabled", True):
                        continue
                    if is_account_update and not e.get("account_update_log_enabled", _bot_au):
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
                    # Đích admin có thể ghi '<chat>:<topic>' để log vào ĐÚNG topic
                    # của nhóm forum, thay vì rơi vào General.
                    _achat, _atopic = _split_chat_topic(cid)
                    _base = {"chat_id": str(_achat),
                             "link_preview_options": {"is_disabled": True}}
                    if _atopic is not None:
                        _base["message_thread_id"] = _atopic
                    # Tele: đậm/code (HTML); không có màu
                    try:
                        from services.telegram.format import llm_to_html
                        html_body = llm_to_html(body)
                        r = _api_call("sendMessage", {
                            **_base, "text": html_body[:4000], "parse_mode": "HTML"})
                        if not r.get("ok"):
                            r = _api_call("sendMessage", {**_base, "text": body[:4000]})
                    except Exception:
                        r = _api_call("sendMessage", {**_base, "text": body[:4000]})
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
            # Làm ấm cache username TRƯỚC khi có traffic webhook — tránh
            # handle_webhook phải gọi getMe (blocking) ngay trên event loop
            # lúc cache miss (mỗi lần restart process).
            _bot_username()
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
    _chat, _topic_dest = _split_chat_topic(chat_id)
    results = _cli().send_message_safe(
        _chat, text or "",
        # Ưu tiên topic của TIN ĐANG XỬ LÝ (trả lời đúng chỗ hỏi); gửi chủ động
        # (không có tin đến) thì lấy topic mã hoá trong đích '<chat>:<topic>'.
        # None = nhóm thường / General.
        message_thread_id=_cur_topic() if _cur_topic() is not None else _topic_dest,
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


def gui_chu_dong(dich: str, text: str) -> bool:
    """Gửi tới một thread KHÁC thread đang xử lý. `dich` dạng '<chat>[:<topic>]'.

    Phải xoá topic thread-local trước khi gửi: `send_message` ưu tiên topic của
    TIN ĐANG XỬ LÝ để trả lời đúng chỗ người ta hỏi, nhưng ở đây đích là chỗ
    khác — giữ topic cũ là gửi vào một topic không tồn tại bên chat đích.
    """
    truoc = getattr(_current, "topic", None)
    _current.topic = ""
    try:
        return bool(send_message(dich, text).get("ok"))
    except Exception as exc:
        logger.warning("tg gửi chủ động tới %s lỗi: %s", dich, str(exc)[:150])
        return False
    finally:
        _current.topic = truoc


def _send_agent_reply(chat_id: str, out: dict, user_id: str = "") -> None:
    """Send orchestrator text (+ optional ask-choice inline keyboard).

    `user_id`: để ghi nhận "bot vừa xin ảnh của người này" — tấm ảnh gửi sau đó
    mới đi qua được cổng chặn-nếu-không-tag trong nhóm.
    """
    if user_id:
        try:
            from services import photo_intent as _phi_xin
            _phi_xin.danh_dau_neu_xin_anh(
                f"tg:{_bot_id()}:{chat_id}:{user_id}", str(out.get("text") or ""))
        except Exception:
            pass
    from services.agent import ask_choices as _ask
    # Trống + có nút chọn → `format_numbered` điền danh sách, đừng chèn "..."
    # (câu duyệt gửi tin nay CHỈ có ba lựa chọn). Trống mà không nút thì vẫn cần
    # "..." vì Telegram không nhận tin rỗng.
    reply = (out.get("text") or "").strip()
    choices = out.get("choices") or []
    if not reply and not choices:
        reply = "..."
    markup = None
    if choices:
        try:
            markup = _ask.telegram_inline_keyboard(choices)
            # Numbered fallback in text for users who type instead of tapping
            reply = _ask.format_numbered(reply, choices)
        except Exception:
            markup = None
    send_message(chat_id, reply, reply_markup=markup)

def _telegram_tai_duoc(url: str) -> bool:
    """MÁY CHỦ TELEGRAM có tải được URL này không?

    Khác hẳn `net_guard.is_allowed_egress_url` — cái đó trả lời "CHÚNG TA có được
    phép gọi ra địa chỉ này không". Hai câu hỏi khác nhau, và bản cũ dùng lẫn:
    `is_allowed_egress_url("http://127.0.0.1:80/images/a.png")` là True (đúng, ta
    tự tải được), nên album vẫn được gửi đi rồi Telegram trả:

        400 Bad Request: failed to send message #3 with the error message
        "WEBPAGE_MEDIA_EMPTY"

    Tức mỗi lần gửi ảnh thư viện là một lượt gọi API chắc chắn thất bại, cộng một
    dòng log trông như lỗi Telegram. Ảnh thư viện luôn ở `http://127.0.0.1:80/…`
    nên đó là MỌI lần, không phải ca lạ.
    """
    from urllib.parse import urlparse
    try:
        h = (urlparse(str(url)).hostname or "").lower()
    except Exception:
        return False
    if not h or h in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False
    try:
        import ipaddress
        return not ipaddress.ip_address(h).is_private
    except ValueError:
        return True          # tên miền — coi như công khai
    except Exception:
        return False


def _gui_album(chat_id: int | str, urls: list[str], caption: str = "") -> bool:
    """Gửi nhiều ảnh thành MỘT album qua sendMediaGroup (tối đa 10 ảnh/lô).

    Hai đường, chọn theo việc Telegram có tải được URL hay không:

    · URL công khai → gửi thẳng URL, Telegram tự tải (rẻ nhất).
    · URL nội bộ (`http://127.0.0.1:80/images/…` — mọi ảnh thư viện của máy này)
      → TẢI BYTES rồi đính kèm multipart `attach://`. Vẫn là MỘT album.

    Bản cũ chỉ có đường một và trả False cho URL nội bộ, nên người gọi rơi về gửi
    TỪNG TẤM: 3 ảnh thành 3 tin nhắn rời. Người dùng xin "gửi 3 ảnh một lúc" mà
    nhận 3 tin — đúng việc album sinh ra để tránh, và trên Zalo thì đã gộp được.
    """
    if len(urls) < 2:
        return False
    sach = [str(u) for u in urls[:10] if not str(u).startswith("data:")]
    if len(sach) < 2:
        return False

    if all(_telegram_tai_duoc(u) for u in sach):
        media = [{"type": "photo", "media": u} for u in sach]
        if caption:
            media[0]["caption"] = caption
        r = _api_call("sendMediaGroup", {"chat_id": chat_id, "media": media})
        if not r.get("ok"):
            logger.warning("sendMediaGroup (URL) thất bại (%d ảnh): %s",
                           len(media), str(r)[:200])
        return bool(r.get("ok"))

    # Đường bytes: tải về rồi đính kèm. `_fetch_image_bytes` đã né được hairpin
    # 403 của chính máy mình nên URL /images/ nội bộ tải được.
    files: dict[str, tuple[str, bytes, str]] = {}
    media = []
    for i, u in enumerate(sach):
        img = _fetch_image_bytes(u)
        if not img:
            logger.warning("_gui_album: không tải được %s", u[:120])
            continue
        ten = f"anh{i}"
        files[ten] = (f"{ten}.png", img, "image/png")
        m: dict = {"type": "photo", "media": f"attach://{ten}"}
        if not media and caption:
            m["caption"] = caption
        media.append(m)
    if len(media) < 2:
        return False        # dưới 2 tấm thì không phải album — để caller gửi lẻ
    r = _cli().call_multipart(
        "sendMediaGroup",
        {"chat_id": chat_id, "media": json.dumps(media, ensure_ascii=False)},
        files, timeout=120,
    )
    if not r.get("ok"):
        logger.warning("sendMediaGroup (bytes) thất bại (%d ảnh): %s",
                       len(media), str(r)[:200])
        return False
    # Gửi được ÍT hơn số xin → trả False để caller báo thiếu, chứ không im lặng.
    return len(media) >= len(sach)


def send_photo(chat_id: int | str, photo_bytes: bytes, caption: str = "") -> dict:
    """Gửi ảnh qua Telegram (đúng topic đã nhận — xem send_message)."""
    return _cli().send_photo(chat_id, photo_bytes, caption=caption or "",
                             message_thread_id=_cur_topic())


def send_video(chat_id: int | str, video_bytes: bytes, caption: str = "") -> dict:
    """Gửi video qua Telegram (đúng topic đã nhận)."""
    return _cli().send_video(chat_id, video_bytes, caption=caption or "",
                             message_thread_id=_cur_topic())


def send_audio(chat_id: int | str, audio_bytes: bytes, caption: str = "") -> dict:
    """Gửi file nhạc/audio qua Telegram (hiện player bấm nghe) — đúng topic."""
    return _cli().send_audio(chat_id, audio_bytes, caption=caption or "",
                             message_thread_id=_cur_topic())


def send_document(chat_id: int | str, doc_bytes: bytes, filename: str, caption: str = "") -> dict:
    """Gửi file/document qua Telegram (đúng topic đã nhận)."""
    return _cli().send_document(
        chat_id, doc_bytes, filename=filename or "file.bin", caption=caption or "",
        message_thread_id=_cur_topic(),
    )


async def handle_webhook(request) -> dict:
    """Handle incoming Telegram webhook POST. Returns immediately, processes AI in background."""
    # XÁC THỰC secret TRƯỚC khi đọc body (đừng nạp RAM cho request chưa xác thực).
    hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    bot = match_bot_by_secret(_bots(), hdr, secret_fn=_webhook_secret_for)
    if bot is None:
        logger.warning("Telegram webhook bad/ambiguous secret")
        return {"ok": False}
    # Body cap qua stream — chặn chunked (không Content-Length) nạp vô hạn RAM.
    try:
        body = await read_json_limited(request)
    except BodyTooLarge:
        logger.warning("Telegram webhook: body quá lớn → bỏ")
        return {"ok": False}
    except Exception:
        return {"ok": False}
    # JSON hợp lệ nhưng không phải object (vd [] / null) → body.get() sẽ 500.
    if not isinstance(body, dict):
        return {"ok": False}

    # De-dupe Telegram webhook retries
    bid_pub = _bot_public_id(bot)
    if is_duplicate_update(bid_pub, body.get("update_id")):
        return {"ok": True}

    # Inline keyboard callbacks (ask-with-choices)
    cq = body.get("callback_query")
    if cq:
        _current.bot = bot
        _tg_worker(_handle_callback_query, cq, bot)   # bound: hết slot thì bỏ
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
    # Nhóm bật Topics (forum): mỗi tin thuộc 1 topic. Giữ lại để (a) trả lời đúng
    # topic, (b) lọc chức năng theo topic. Topic General không có id → "".
    topic_id = str(msg.get("message_thread_id") or "").strip()
    # KHÔNG gán _current.topic ở đây: luồng xử lý là thread khác (thread-local
    # không nhìn thấy) nên topic được TRUYỀN qua args của _process_message. Gán ở
    # luồng event-loop chỉ để lại giá trị cũ, dễ khiến lần gửi sau (API khác,
    # chat khác) dính topic lạ → Telegram trả "message thread not found".
    # Ảnh/video Telegram mang lời kèm trong `caption`, không phải `text` —
    # không đọc thì "gửi ảnh kèm chú thích" luôn rơi vào nhánh menu như thể
    # người dùng chưa nói gì (nhánh caption phía dưới thành mã chết).
    text = (msg.get("text") or msg.get("caption") or "").strip()
    photo = msg.get("photo")
    document = msg.get("document")
    # Video: chỉ luồng Facebook dùng (xem _process_message_inner) — ngoài luồng
    # đó hành vi giữ nguyên như trước: bỏ qua.
    video = msg.get("video")
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
            msg, bot_username=_bot_username(no_block=True), bot_id=_bot_id(),
        )
    except Exception:
        native_mention = False

    _tg_worker(_process_message, text, chat_id, photo, document, bot, sender,
               user_id, is_group, native_mention, chat_name,
               voice_file_id, topic_id, video)   # bound: hết slot thì bỏ tin
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
        topic_id = str(msg.get("message_thread_id") or "").strip()
        # Tra bằng ĐÚNG khoá phiên orchestrator đã lưu, không phải chat_id trần:
        # trong nhóm khoá có kèm ':u<uid>' nên tra theo chat_id không thấy gì và
        # nút bấm im lặng. Kèm luôn người bấm → người này không tiêu được lựa
        # chọn đang chờ của người khác trong cùng nhóm.
        skey = khoa_phien(chat_id, topic_id, user_id)
        choices = _ask.get_pending(skey)
        if not choices or idx < 0 or idx >= len(choices):
            return
        _ask.clear_pending(skey)
        chosen = choices[idx].get("send") or choices[idx].get("label") or ""
        if not chosen:
            return
        _process_message(chosen, chat_id, None, None, bot, sender,
                         user_id, is_group, native_mention=True,
                         topic_id=topic_id)
    except Exception as exc:
        logger.warning("Telegram callback_query failed: %s", exc)
    finally:
        _current.bot = None


def _maybe_voice_reply(chat_id: str, user_id: str, reply: str) -> bool:
    """Gửi âm thanh nếu thread (hoặc riêng user này) bật `tts_reply`.

    Quy tắc user thắng nhóm: nhóm không bật nhưng user bật → chỉ người đó nghe.
    Trả True nếu ĐÃ gửi voice → caller BỎ gửi chữ («Trả lời bằng giọng nói» =
    chỉ âm thanh, không kèm chữ). Trả False (chưa bật / TTS chưa sẵn / lỗi) →
    caller gửi chữ như thường (không để người dùng mất câu trả lời).
    """
    text = (reply or "").strip()
    if not text or not chat_id:
        return False
    try:
        from services import voice as _voice
        from services.voice import permissions as _vperm
        if not _vperm.wants_voice_reply("tg", _bot_id(), chat_id, user_id,
                                        _cur_topic()):
            return False
        if not _voice.tts_ready():
            return False
        from services.voice import session_voice as _sv
        # Nhóm bật Topics: khóa mang '#topic' → giọng/tắt TTS cài riêng cho topic
        # thắng cài đặt cả nhóm (session_voice._candidate_keys tự fallback).
        _tp = _cur_topic()
        _cid = f"{chat_id}#{_tp}" if _tp else str(chat_id)
        _sid = f"tg:{_bot_id()}:{_cid}:{user_id}"
        if not _sv.is_tts_enabled_for_session(_sid):
            return False  # TTS bị tắt cho kênh/bot/nhóm/topic/user này
        _pk = f"{_cid}:u{user_id}" if user_id else _cid
        wav = _voice.speak_reply(text[:1000], _pk, session_id=_sid)
        send_audio(chat_id, wav, caption="")
        return True
    except Exception as exc:
        logger.warning("tg voice reply loi: %s", str(exc)[:160])
    return False


def _download_file(file_id: str) -> bytes | None:
    """Download a file from Telegram by file_id."""
    return _cli().download_file(file_id)


def _moi_luu_online(chat_id: str, user_id: str, chat_name: str,
                    ten_tep: str, du_lieu: bytes, *,
                    menu_dang_mo: bool = False) -> None:
    """Tệp/ảnh vừa nhận → hỏi admin có lưu lên kho đám mây không.

    Mặc định phạm vi nào cũng TẮT nên hàm này thường thoát ngay, và mọi lỗi đều
    chặn tại đây: nhận tệp là việc chính, lưu đám mây là việc phụ đi kèm.
    
    `menu_dang_mo` — vừa gửi menu ý định cho tệp này. Khi đó KHÔNG hỏi lưu, theo
    luật chủ máy chốt 07/08: **chỉ hỏi lưu sau khi đã xong việc**. Hai menu cùng
    sống thì menu kho không bấm số được (bản chờ pdf được xét trước rồi return),
    và hỏi lúc vừa nhận là hỏi sớm — chưa biết sẽ chuyển hay không thì chưa trả
    lời được "lưu bản nào".

    Không mất đường nào: menu ý định đã có sẵn mục «☁️ Lưu lên kho đám mây», còn
    vừa chuyển vừa lưu thì sau khi chuyển xong bot hỏi tiếp đủ bốn lựa chọn.
    """
    if menu_dang_mo:
        logger.info({"event": "bo_hoi_luu_vi_menu_dang_mo",
                     "tep": str(ten_tep)[:60]})
        return
    try:
        from services.agent import luu_tru_day as _ltd
        _ltd.moi_luu("tg", str(chat_id), user=str(user_id or ""),
                     topic=str(_cur_topic() or ""),
                     ten_tep=ten_tep, du_lieu=du_lieu,
                     ten_nhom=str(chat_name or ""), dinh_danh=str(_bot_id() or ""))
    except Exception as exc:
        logger.warning("tg luu_tru_online: %s", str(exc)[:150])


def _moi_luu_sau_chuyen_doi(chat_id: str, user_id: str, tep_goc: str,
                            ten_goc: str, du_lieu_moi: bytes,
                            ten_moi: str) -> None:
    """Vừa gửi bản đã chuyển → hỏi admin lưu bản nào lên kho đám mây."""
    try:
        from services.agent import luu_tru_day as _ltd
        _ltd.moi_luu_sau_chuyen_doi(
            "tg", str(chat_id), tep_goc=tep_goc, ten_goc=ten_goc,
            du_lieu_moi=du_lieu_moi, ten_moi=ten_moi,
            topic=str(_cur_topic() or ""), user=str(user_id or ""),
            dinh_danh=str(_bot_id() or ""))
    except Exception as exc:
        logger.warning("tg luu_tru_online sau chuyen doi: %s", str(exc)[:150])


def _moi_luu_tom_tat(chat_id: str, user_id: str, ten_goc: str,
                     tom_tat: str) -> None:
    """Vừa gửi bản tóm tắt → hỏi admin có lưu nó lên kho đám mây không."""
    try:
        from services.agent import luu_tru_day as _ltd
        _ltd.moi_luu_tom_tat("tg", str(chat_id), ten_goc=ten_goc, tom_tat=tom_tat,
                             topic=str(_cur_topic() or ""),
                             user=str(user_id or ""),
                             dinh_danh=str(_bot_id() or ""))
    except Exception as exc:
        logger.warning("tg luu_tru_online sau tom tat: %s", str(exc)[:150])


def _do_pdf_intent(
    chat_id: str,
    pending: dict | None,
    intent: str,
    *,
    grade: int | None = None,
    subject: str | None = None,
    user_id: str = "",
    loai_sach: str = "sgk",
    chu_thich: str = "",
) -> None:
    """PDF chờ: rag_knowledge | rag_teacher | word | excel.

    `loai_sach` (sgk/sgv/vbt/tap_huan) tên KHÁC biến `kind` bên trong hàm — biến
    đó là loại việc cho telemetry ("pdf_word"/"pdf_rag"), trùng tên là ghi đè
    tham số ngay dòng đầu.
    """
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
        if intent == _pi.LUU_ONLINE:
            kind = "pdf_luu_online"
            from services.agent import luu_tru_day as _ltd
            reply = _ltd.luu_ngay("tg", str(chat_id), tep=path, ten_tep=name,
                                  topic=str(_cur_topic() or ""),
                                  user=str(user_id or ""))
            send_message(chat_id, reply)
        elif intent == _pi.WORD:
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
                _moi_luu_sau_chuyen_doi(chat_id, user_id, path, name,
                                        data, f"{base}.docx")
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
                _moi_luu_sau_chuyen_doi(chat_id, user_id, path, name,
                                        data, f"{base}.xlsx")
                try:
                    os.unlink(xlsx_path)
                except Exception:
                    pass
            else:
                status = "error"
                err = str(r.get("error") or "")[:150]
                reply = f"⚠️ Không chuyển được sang Excel: {err}"
                send_message(chat_id, reply)
        elif intent == _pi.DICH:
            # Dịch tài liệu bằng máy chủ dịch tự dựng. docx/pptx/odt/txt/epub/
            # html quay lại ĐÚNG định dạng gốc (LibreTranslate dựng lại tệp);
            # PDF và Excel thì Argos không dựng lại được nên trả về chữ.
            kind = "pdf_dich"
            from services import translate_service as _ts
            r = _ts.dich_tep(path, name)
            reply = _ts.bao_cao_dich(r, name)
            if r.get("ok") and r.get("kieu") == "tep":
                send_document(chat_id, r["data"], r["ten"], caption=reply)
                _moi_luu_sau_chuyen_doi(chat_id, user_id, path, name,
                                        r["data"], r["ten"])
            else:
                if not r.get("ok"):
                    status = "error"
                    err = str(r.get("error") or "")[:150]
                send_message(chat_id, reply)
        elif intent == _pi.TOM_TAT:
            # Tóm tắt THUẦN: đọc file, trả bản tóm, KHÔNG nạp vào kho nào.
            kind = "pdf_tom_tat"
            _tt = _pi.summarize_pdf(path, _tg_model(chat_id, user_id))
            if not (_tt or "").strip():
                status = "error"
                err = "khong doc duoc noi dung"
                reply = "⚠️ Không đọc được nội dung file này để tóm tắt."
            else:
                from services import pdf_images as _pimg
                reply = f"✍️ Tóm tắt **{name}**\n\n" + _pimg.humanize_markers(_tt)
            send_message(chat_id, reply)
            if (_tt or "").strip():
                _moi_luu_tom_tat(chat_id, user_id, name, _tt)
        elif intent == _pi.RAG_TEACHER:
            kind = "pdf_teacher"
            if not grade or not subject:
                reply = "⚠️ Thiếu lớp/môn cho RAG teacher."
                status = "error"
                err = "missing grade/subject"
                send_message(chat_id, reply)
            else:
                r = _pi.ingest_teacher(path, grade=int(grade), subject=str(subject),
                                       name=name, kind=loai_sach, caption=chu_thich)
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
        allowed = _phi.them_dang_facebook(_phi.allowed_intents(allow), allow)
        if it not in allowed and allow is not None:
            # generate blocked without image group
            status = "blocked"
            err = f"intent {it} not allowed"
            return

        if it == _phi.FACEBOOK:
            # Ảnh → URL công khai của chính bot, rồi BƠM LẠI pipeline như một
            # tin nhắn (cùng đường với nút bấm ask:<n>): URL vào lịch sử phiên
            # để lượt sau người dùng chốt caption, model gom mọi URL đã nhận
            # vào MỘT lời gọi `dang_facebook` (bài nhiều ảnh).
            kind = "photo_facebook"
            from services.protocol.conversation import save_image_bytes
            url = save_image_bytes(file_data)
            inject = f"thêm ảnh vào bài đăng facebook: {url}"
            if request:
                inject += f" — {request}"
            _process_message(inject, chat_id, None, None, None, "", user_id,
                             str(chat_id).startswith("-"), True, "", "",
                             _cur_topic() or "")
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

        if it == _phi.DICH:
            # Đọc chữ trong ảnh (vision) rồi dịch bằng máy chủ dịch tự dựng.
            # Ảnh chụp cả trang tài liệu ra bản dịch dài hơn trần 4096 ký tự của
            # một tin Telegram → dich_anh tự đóng thành .docx (kieu="tep").
            kind = "photo_dich"
            from services import translate_service as _ts
            r = _ts.dich_anh(file_data, channel="tg")
            reply = _ts.bao_cao_dich(r, "chữ trong ảnh")
            if not r.get("ok"):
                status = "error"
                err = str(r.get("error") or "")[:200]
                send_message(chat_id, reply)
            elif r.get("kieu") == "tep":
                send_document(chat_id, r["data"], r["ten"], caption=reply)
            else:
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


def _process_message(text: str, chat_id: str, photo: list | None = None, document: dict | None = None, bot: dict | None = None, sender: str = "", user_id: str = "", is_group: bool = False, native_mention: bool = False, chat_name: str = "", voice_file_id: str = "", topic_id: str = "", video: dict | None = None) -> None:
    """Process a Telegram message in background thread.

    Lưới AN TOÀN NGOÀI CÙNG quanh TOÀN BỘ pipeline (_process_message_inner):
    dedup update_id đã tiêu thụ ở handle_webhook TRƯỚC khi thread nền này
    chạy, nên một lỗi ở blacklist / lọc quyền / admin-workspace / state-machine
    PDF-ảnh (mọi thứ TRƯỚC orchestrate()) mà không bắt thì tin MẤT VĨNH VIỄN —
    không trả lời, không cảnh báo admin, không ai retry. orchestrate() đã có
    try/except + fallback riêng bên trong _process_message_inner — lưới này
    KHÔNG thay thế, chỉ bọc thêm bên ngoài."""
    try:
        _process_message_inner(
            text, chat_id, photo, document, bot, sender, user_id, is_group,
            native_mention, chat_name, voice_file_id, topic_id, video,
        )
    except Exception as exc:
        logger.warning("tg _process_message lỗi (chat=%s user=%s): %s", chat_id, user_id, exc)
        try:
            _notify_all_admins(
                f"⚠️ Lỗi xử lý tin Telegram (chat {chat_id}): {str(exc)[:300]}",
                bot=bot,
            )
        except Exception:
            pass


def _process_message_inner(text: str, chat_id: str, photo: list | None = None, document: dict | None = None, bot: dict | None = None, sender: str = "", user_id: str = "", is_group: bool = False, native_mention: bool = False, chat_name: str = "", voice_file_id: str = "", topic_id: str = "", video: dict | None = None) -> None:
    """Nội dung xử lý thật (bọc lưới an toàn ở _process_message phía trên)."""
    if bot is not None:
        _current.bot = bot  # luồng mới → gắn lại ngữ cảnh bot để gửi đúng token
    # `_current` là thread-local: topic gán ở handle_webhook KHÔNG nhìn thấy được
    # trong luồng này → phải gắn lại, y như _current.bot ở trên. Thiếu dòng này
    # thì mọi câu trả lời rơi về topic General dù đã đọc đúng message_thread_id.
    _current.topic = str(topic_id or "")

    # NHẬT KÝ NHÓM: ghi tin CHỮ nhận được (nếu phạm vi BẬT) — TRƯỚC cổng tag,
    # tách hẳn với việc trả lời. Mặc định TẮT. (Voice log sau khi có STT — v1 bỏ.)
    if text and is_group:
        try:
            from services.agent import chatlog as _chatlog
            # `tagged` cho luật «Tag bot» của «Lọc nhật ký». Dựng lại y công
            # thức `_tagged` dùng ở đoạn webhook bên dưới (mention native HOẶC
            # từ khoá tag của thread) — ở đây chưa chạy tới đoạn đó.
            try:
                from services.agent import capabilities as _caps_log
                _, _kw_log = _caps_log.mention_required_for(
                    "tg", _bot_id(), chat_id, str(topic_id or ""))
            except Exception:
                _kw_log = ""
            _tag_log = bool(native_mention) or (
                bool(_kw_log) and _kw_log.lower() in (text or "").lower())
            _chatlog.ghi(khoa_phien(chat_id, str(topic_id or ""), user_id),
                         sender_id=user_id, sender_name=sender, text=text,
                         mentions=["@all"] if native_mention else None,
                         tagged=_tag_log)
        except Exception:
            pass

    # Voice note → STT → coi như tin nhắn CHỮ: đường đi chỉ thêm bước chuyển
    # đổi, phần sau (lọc quyền, agent, trả lời) giữ nguyên như chat thường.
    if voice_file_id and not text:
        try:
            from services import voice as _voice
            raw = _download_file(voice_file_id)
            if raw:
                # session_id → STT chọn ngôn ngữ theo phạm vi (vi mặc định / en);
                # topic có '#' → cài đặt STT riêng topic thắng cả nhóm.
                _cid_stt = f"{chat_id}#{_cur_topic()}" if _cur_topic() else str(chat_id)
                _sid = f"tg:{_bot_id()}:{_cid_stt}:{user_id}"
                text = _voice.listen(raw, "ogg", session_id=_sid)
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
    # 3 cấp trong nhóm: Nhóm → Topic → User (topic ⊆ nhóm, user ⊆ topic).
    # Nhóm KHÔNG bật Topics → _cur_topic() = None → đúng 2 cấp như trước.
    _allow = _caps.allowed_groups_for_member(
        "tg", _bot_id(), chat_id, user_id, _cur_topic()) if chat_id else None
    # Chỉ người trong danh sách mới được giao tiếp (công tắc theo thread/topic) —
    # xem `capabilities.duoc_giao_tiep`. Khác câu "được dùng chức năng nào".
    # ĐẶT SAU khối nhật ký nhóm ở trên là CỐ Ý: chỉ không phản hồi, nhật ký vẫn ghi.
    if chat_id and not _caps.duoc_giao_tiep(
            "tg", _bot_id(), chat_id, user_id, _cur_topic()):
        return
    # chat_ids đã bỏ trên UI — AI thường qua bộ lọc thread; admin luôn được phép
    allowed = [str(c) for c in _chat_ids()]
    # HAI câu hỏi khác nhau, đừng trộn:
    #   _thread_admin — chat này có phải NƠI NHẬN thông báo admin (của CHAT)
    #   _is_admin     — NGƯỜI GỬI lượt này có quyền admin (của NGƯỜI)
    # Trong nhóm admin, mọi thành viên đều thuộc _thread_admin (nên nhóm vẫn im
    # lặng / vẫn được whitelist như trước) nhưng chỉ admin thật có _is_admin.
    _thread_admin = bool(chat_id and _la_thread_admin(chat_id))
    _is_admin = bool(chat_id and _is_admin_chat(chat_id, user_id))
    # Admin = NƠI NHẬN THÔNG BÁO. Chức năng chat/AI của thread do LỌC THREAD quyết định:
    # admin KHÔNG thêm trong lọc (thread_filters) và không nằm trong whitelist chat_ids
    # → im lặng hoàn toàn (chỉ nhận log). Muốn admin chat / ra lệnh: thêm thread admin
    # vào Lọc thread. (Trước đây admin được auto-permit vô điều kiện — nay chỉ khi có trong lọc.)
    if _thread_admin and _allow is None and chat_id and str(chat_id) not in allowed:
        return
    if _thread_admin and chat_id and str(chat_id) not in allowed:
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
        _caps.mention_required_for("tg", _bot_id(), chat_id, _cur_topic())
        if chat_id else (False, "")
    )
    _tagged_early = bool(native_mention) or (
        bool(_kw_early) and str(_kw_early).lower() in (text or "").lower()
    )
    # Người lạ: ghi danh bạ + báo admin 1 lần (không spam khi known / đã notified)
    # Dùng _thread_admin: thành viên thường trong nhóm admin KHÔNG phải "chat lạ",
    # nếu xét theo _is_admin thì mỗi tin của họ lại nhả "⛔ Không được phép." vào
    # đúng nhóm admin đang dùng để nhận thông báo.
    if chat_id and _allow is None and chat_id not in allowed and not _thread_admin:
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
                    # Topic ID — cần để cài «Lọc theo Topic» ở Lọc thread. Chỉ có
                    # khi gõ /id NGAY TRONG topic (topic General không có id).
                    + (f"🧵 Topic ID: {_cur_topic()}\n" if _cur_topic() else "")
                    + f"👤 User ID người gửi: {user_id or '(không rõ)'}\n"
                    + (f"👤 Tên người: {sender}\n" if sender else "")
                    + f"Bot: Telegram {_bot_id()}")
        # Gửi MỌI admin của bot này; không có admin → trả /id cho người gửi.
        if not _notify_all_admins(
                f"🆔 Yêu cầu /id từ {'nhóm' if is_group else 'chat'}:\n{_id_info}"):
            send_message(chat_id, _id_info)
        return

    # Lệnh /facebook — menu đăng bài Page, do CODE dựng (không qua LLM), cùng
    # nếp /id. Nhận cả "/facebook@TênBot" và "/fb". Nhóm chức năng 'facebook'
    # phải bật cho thread; tắt thì nói rõ thay vì im lặng — người gõ ĐÍCH DANH
    # lệnh này xứng đáng biết vì sao không có gì xảy ra.
    # Nhận "/facebook", "/fb", "/facebook@TênBot" và cả "@TênBot /facebook"
    # (bóc tag như photo_intent.bo_tag để lệnh trong nhóm không trượt).
    from services.photo_intent import bo_tag as _bo_tag_fb
    if chat_id and _bo_tag_fb(_low).split("@", 1)[0].strip() in {"/facebook", "/fb"}:
        if _allow is not None and "facebook" not in _allow:
            send_message(chat_id, "📘 Chức năng Facebook đang tắt cho chỗ này — "
                                  "bật nhóm «📘 Facebook» trong Cài đặt ▸ Lọc thread.")
            return
        from services import facebook_page as _fbp
        from services.agent import ask_choices as _ask_fb
        _fbkey = khoa_phien(chat_id, _cur_topic(), user_id)
        _out_fb = _ask_fb.apply_to_result({"text": _fbp.menu_ask(_fbkey)}, _fbkey)
        _send_agent_reply(chat_id, _out_fb, user_id)
        return

    # Lệnh /dich — dịch máy tự dựng (LibreTranslate trong stack), do CODE làm,
    # KHÔNG qua LLM: hỏi model dịch thì tốn hạn mức và trả về lời rào đón. Cùng
    # nếp /id, /facebook. Nhận "/dich@TênBot" và "@TênBot /dich ..." (bóc tag).
    # Trả lời trên CHỮ GỐC (không dùng _low) — dịch phải giữ nguyên chữ hoa.
    # `not video`: "/dich" làm CHÚ THÍCH của video là lệnh cho nhánh video ở
    # dưới, nuốt ở đây thì video không bao giờ được xử lý.
    if chat_id and text and not video:
        from services import translate_service as _ts
        if _ts.la_lenh_dich(text):
            # Link video thì đi đường phụ đề: trả .srt nạp được vào trình phát,
            # thay vì trả lại chính cái link (URL nằm trong _KHONG_DICH).
            from services import video_dich as _vd
            _noi_dung = _ts._bo_tag_dau(text)
            if _vd.la_link_video(_noi_dung):
                _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
                send_message(chat_id, "🎬 Đang lấy phụ đề và dịch, chờ em chút ạ…")
                _rv = _vd.dich_video(_noi_dung)
                if _rv.get("ok"):
                    send_document(chat_id, _rv["srt"], _rv["ten"],
                                  caption=_vd.bao_cao(_rv))
                    # Video ngắn thì gửi kèm bản chữ để đọc luôn trong chat,
                    # khỏi phải mở tệp. Dài thì .srt là đủ.
                    if len(_rv["chu"]) <= 1500:
                        send_message(chat_id, _rv["chu"])
                else:
                    send_message(chat_id, _vd.bao_cao(_rv))
                return
            send_message(chat_id, _ts.lenh_dich(text))
            return

    # Chuyển tiếp webhook (HA / n8n / URL bất kỳ) theo 'Lọc chức năng theo
    # thread' — TRƯỚC bộ lọc tag (tin nhóm không tag vẫn chuyển được).
    # Thread bật → mọi user (trừ user tắt riêng); thread không bật → user nào
    # bật + có URL riêng thì chuyển tới đó. User bật tag_mode: tin TAG bot →
    # CHỈ chuyển webhook (AI im lặng); không tag → ChatGPT trả lời như thường.
    _req_fw, _kw_fw = _caps.mention_required_for(
        "tg", _bot_id(), chat_id, _cur_topic())
    _tagged = bool(native_mention) or (
        bool(_kw_fw) and _kw_fw.lower() in (text or "").lower()
    )
    if _caps.forward_event("tg", _bot_id(), chat_id, user_id, {
        "platform": "telegram", "bot": _bot_id(), "chat_id": chat_id,
        "topic_id": _cur_topic(), "user_id": user_id, "sender": sender,
        "is_group": is_group,
        "text": text or "", "tagged": _tagged,
        "has_photo": bool(photo),
        "document": str((document or {}).get("file_name") or ""),
    }, tagged=_tagged, topic_id=_cur_topic()):
        return

    # Bộ lọc TAG: required → native @mention HOẶC keyword (keyword rỗng không
    # chặn native — tag_gate_allows). /id đã return ở trên.
    if is_group and chat_id:
        _req, _kw = _caps.mention_required_for(
            "tg", _bot_id(), chat_id, _cur_topic())
        # NGOẠI LỆ: nhóm này đang được hỏi "lưu tệp lên kho đám mây?" thì câu
        # trả lời "1/2/3" không tag vẫn phải qua cổng. Không có ngoại lệ này là
        # bot tự hỏi rồi tự bịt tai — đúng cái đã xảy ra với ảnh hôm 06/08.
        # Chỉ mở cho ĐÚNG câu trả lời, không mở cho mọi tin trong 30 phút chờ:
        # mở rộng thế là tắt luôn yêu cầu tag của nhóm đó.
        if _req and text:
            from services.agent import luu_tru_day as _ltd_cho
            if _ltd_cho.chon_tu_tra_loi(_ltd_cho.khoa_cho_thread(
                    "tg", str(_bot_id() or ""), str(chat_id)), text):
                _req = False
        # Tag bot = mở cửa sổ chờ cho ĐÚNG người đó; tin tiếp theo của họ (ảnh,
        # tệp, chữ) đi qua mà không cần tag lại. Trên điện thoại không đính được
        # ảnh vào cùng tin có tag, nên không có cửa sổ này thì ảnh gửi ngay sau
        # đó bị loại.
        from services import cho_sau_tag as _cst
        _ckey = f"tg:{_bot_id()}:{chat_id}:{user_id or ''}"
        if native_mention:
            _cst.mo(_ckey)
        elif _req and _cst.dang_cho(_ckey):
            _req = False
        # NGOẠI LỆ như Zalo cá nhân: bot vừa xin ảnh của chính người này, hoặc
        # đang giữ bản chờ "chọn 1/2/3" của họ → câu/ảnh tiếp theo đi qua dù
        # không tag. Cửa sổ sau-tag sống 5 phút còn bản chờ sống 10 — thiếu
        # ngoại lệ này thì đúng 5 phút giữa hai mốc đó, người dùng bấm số mà
        # không có gì xảy ra.
        if _req:
            from services import photo_intent as _phi_cho
            from services import pdf_intent as _pi_cho
            if (_phi_cho.dang_cho_anh(_ckey) or _phi_cho.has_pending(_ckey)
                    or _pi_cho.has_pending(_ckey)):
                _req = False
                _phi_cho.het_cho_anh(_ckey)   # dùng một lần, tránh mở cổng mãi
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
    # Kèm NGƯỜI GỬI: bản cũ chỉ tới chat nên trong nhóm, A gửi tệp rồi bot hỏi
    # muốn làm gì, B nói câu bất kỳ là câu đó bị nhận làm trả lời của A. Chờ là
    # chờ theo từng người (chủ máy chốt 05/08).
    _pkey = f"tg:{_bot_id()}:{chat_id}:{user_id or ''}"
    from services.yeu_cau_moi import la_yeu_cau_moi as _la_moi
    if text and chat_id and _pi.has_pending(_pkey) and _la_moi(text):
        # Yêu cầu MỚI thì đóng bản chờ cũ rồi để câu này đi tiếp bình
        # thường — không nuốt câu của người dùng làm câu trả lời.
        _pi.pop_pending(_pkey)
    elif text and chat_id and _pi.has_pending(_pkey):
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
                return  # ý định PDF bị lọc → im lặng
            if _intent == _pi.RAG_TEACHER:
                _pi.update_pending(_pkey, stage="teacher_meta", intent=_pi.RAG_TEACHER)
                send_message(chat_id, _pi.ASK_TEACHER)
                return
            _do_pdf_intent(chat_id, _pi.pop_pending(_pkey), _intent, user_id=user_id)
            return

    # Ảnh chờ: menu 1–4 / hỏi prompt / teacher meta
    from services import photo_intent as _phi
    _phkey = f"tg:{_bot_id()}:{chat_id}:{user_id or ''}"
    if text and chat_id and _phi.has_pending(_phkey) and _la_moi(text):
        _phi.pop_pending_full(_phkey)   # yêu cầu mới → đóng bản chờ
    elif text and chat_id and _phi.has_pending(_phkey):
        _pend = _phi.get_pending(_phkey) or {}
        _allowed_ph = _phi.them_dang_facebook(_phi.allowed_intents(_allow), _allow)
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
                    channel="tg", kind=meta.get("kind") or "sgk", caption=text,
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

    # Lưu trữ online: admin trả lời "1/2/3" cho tệp đang chờ. Khoá theo THREAD
    # (không kèm người) vì nhóm admin thì ai trả lời cũng được. Đặt SAU các bản
    # chờ pdf/ảnh: những bản chờ đó theo TỪNG NGƯỜI nên là việc riêng của họ,
    # phải được ưu tiên trước câu hỏi chung của cả thread.
    if text and not photo and not document:
        from services.agent import luu_tru_day as _ltd
        _khoa_kho = _ltd.khoa_cho_thread("tg", str(_bot_id() or ""), str(chat_id))
        _chon_kho = _ltd.chon_tu_tra_loi(_khoa_kho, text)
        if _chon_kho:
            send_message(chat_id, _ltd.tra_loi(_khoa_kho, _chon_kho)["text"])
            return

    # Handle photo — có caption: thử parse menu/intent; không caption: menu
    if photo:
        _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        largest = max(photo, key=lambda p: p.get("file_size", 0))
        file_data = _download_file(largest["file_id"])
        if not file_data:
            send_message(chat_id, "📷 Không thể tải ảnh.")
            return
        # Chuẩn hoá ngay (HEIC→JPEG) và báo liền nếu ảnh không đọc được, thay vì
        # để người dùng chọn menu → chờ vision → mới nhận lỗi.
        file_data, _img_err = _phi.prepare_incoming(file_data)
        if not file_data:
            send_message(chat_id, _img_err)
            return
        # Ảnh cũng có thư mục riêng và hạn giữ riêng trên đám mây (mục «Ảnh»).
        from services.agent.luu_tru_day import ten_anh as _ten_anh
        _moi_luu_online(chat_id, user_id, chat_name, _ten_anh(file_data), file_data)
        caption = (text or "").strip()
        _allowed_ph = _phi.them_dang_facebook(_phi.allowed_intents(_allow), _allow)
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

    # Handle video — CHỈ phục vụ luồng Facebook (nhóm 'facebook' bật + đã nối
    # Page); ngoài luồng đó giữ nguyên hành vi cũ: bỏ qua im lặng. Bot API chỉ
    # cho tải file ≤ 20MB (MAX_DOWNLOAD_BYTES) nên video lớn phải đi đường link.
    if video and isinstance(video, dict):
        # Hai việc làm được với video: DỊCH thành phụ đề, hoặc ĐĂNG Facebook.
        # Chú thích có /dich → dịch. Không thì giữ nếp cũ (Facebook); nhóm
        # không bật Facebook thì dịch thay vì im lặng như trước.
        from services import translate_service as _ts_v
        _muon_dich_v = bool(text) and _ts_v.la_lenh_dich(text)
        _fb_duoc = _phi.FACEBOOK in _phi.them_dang_facebook(set(), _allow)
        if _muon_dich_v or not _fb_duoc:
            from services import video_dich as _vd_v
            _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
            _vdata = _download_file(str(video.get("file_id") or ""))
            if not _vdata:
                send_message(chat_id, "🎬 Video này em không tải được (Telegram "
                                      "chỉ cho bot lấy tệp tới 20MB) — video "
                                      "YouTube thì gửi em link nhé.")
                return
            send_message(chat_id, "🎬 Em đang nghe và dịch, video dài có thể "
                                  "mất vài phút ạ…")
            import os as _os_v
            import tempfile as _tmp_v
            with _tmp_v.NamedTemporaryFile(suffix=".mp4", delete=False) as _fv:
                _fv.write(_vdata)
                _vpath_v = _fv.name
            try:
                _rv_v = _vd_v.dich_tep_video(_vpath_v, str(video.get("file_name") or "video.mp4"))
            finally:
                try:
                    _os_v.unlink(_vpath_v)
                except OSError:
                    pass
            if _rv_v.get("ok"):
                send_document(chat_id, _rv_v["srt"], _rv_v["ten"],
                              caption=_vd_v.bao_cao(_rv_v))
                if len(_rv_v["chu"]) <= 1500:
                    send_message(chat_id, _rv_v["chu"])
            else:
                send_message(chat_id, _vd_v.bao_cao(_rv_v))
            return
        _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        _vdata = _download_file(str(video.get("file_id") or ""))
        if not _vdata:
            send_message(chat_id, "🎬 Video này em không tải được (Telegram chỉ "
                                  "cho bot lấy file tới 20MB) — anh/chị gửi em "
                                  "link mp4 công khai nhé.")
            return
        from services import facebook_page as _fbp_v
        _vurl = _fbp_v.luu_media_cong_khai(_vdata, "mp4")
        _vinject = f"thêm video vào bài đăng facebook: {_vurl}"
        _vcap = (text or "").strip()
        if _vcap:
            _vinject += f" — {_vcap}"
        _process_message(_vinject, chat_id, None, None, None, "", user_id,
                         str(chat_id).startswith("-"), True, "", "",
                         _cur_topic() or "")
        return

    # Handle document (PDF) — HỎI ý định trước (1=RAG / 2=Word), không tự quyết.
    if document:
        doc_name = document.get("file_name", "document.pdf")
        # Word/Excel đi CHUNG đường với PDF — cùng menu ý định, cùng đường nạp
        # RAG, y như bên Zalo cá nhân. Khác hai chỗ: menu bỏ mục chuyển
        # Word/Excel, và file tạm giữ ĐÚNG đuôi thật cho markitdown nhận dạng.
        _la_office = _pi.la_office(doc_name)
        # Video/âm thanh gửi dạng TỆP → nghe ra chữ rồi dịch thành phụ đề.
        from services import video_asr as _va_d
        if _va_d.la_tep_nghe_duoc(doc_name):
            from services import video_dich as _vd_d
            _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
            _ddata = _download_file(document.get("file_id", ""))
            if not _ddata:
                send_message(chat_id, "🎬 Không tải được tệp — Telegram chỉ cho "
                                      "bot lấy tệp tới 20MB. Video YouTube thì "
                                      "gửi em link nhé.")
                return
            send_message(chat_id, "🎬 Em đang nghe và dịch, video dài có thể "
                                  "mất vài phút ạ…")
            import os as _os_d
            import tempfile as _tmp_d
            _suf_d = ("." + str(doc_name).rsplit(".", 1)[-1].lower()
                      if "." in str(doc_name) else ".mp4")
            with _tmp_d.NamedTemporaryFile(suffix=_suf_d, delete=False) as _fd:
                _fd.write(_ddata)
                _dpath = _fd.name
            try:
                _rd = _vd_d.dich_tep_video(_dpath, str(doc_name))
            finally:
                try:
                    _os_d.unlink(_dpath)
                except OSError:
                    pass
            if _rd.get("ok"):
                send_document(chat_id, _rd["srt"], _rd["ten"],
                              caption=_vd_d.bao_cao(_rd))
                if len(_rd["chu"]) <= 1500:
                    send_message(chat_id, _rd["chu"])
            else:
                send_message(chat_id, _vd_d.bao_cao(_rd))
            return
        if not str(doc_name).lower().endswith(".pdf") and not _la_office:
            send_message(chat_id, "📎 Hiện chỉ hỗ trợ PDF, Word, Excel và "
                                  f"PowerPoint. File: {doc_name}")
            return
        _pdf_intents = (_pi.y_dinh_cho_office(_allow) if _la_office
                        else _pi.allowed_intents(_allow))
        _pdf_intents = _pi.them_luu_online(
            _pdf_intents, "tg", str(chat_id), topic=str(_cur_topic() or ""),
            user=str(user_id or ""))
        if not _pdf_intents:
            return  # thread lọc không có nhóm tài liệu → bỏ qua, không nhắn gì
        _api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        file_data = _download_file(document.get("file_id", ""))
        if not file_data:
            send_message(chat_id, "❌ Không thể tải file.")
            return
        _duoi = ("." + str(doc_name).rsplit(".", 1)[-1].lower()) if _la_office else ".pdf"
        # Khoá phải khớp TỪNG CHỮ với `_pkey` chỗ đọc bản chờ — tạo một đằng tra
        # một nẻo thì người dùng chọn số mãi không ra gì.
        _pdf_info = _pi.set_pending(f"tg:{_bot_id()}:{chat_id}:{user_id or ''}",
                                    file_data, doc_name, _duoi,
                                    intents=_pdf_intents)
        send_message(chat_id, _pi.ask_text(doc_name, _pdf_intents, _pdf_info))
        _moi_luu_online(chat_id, user_id, chat_name, doc_name, file_data,
                        menu_dang_mo=True)
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
            from services.admin_workspace import (ha_fastpath_for_chat as _ha_fp,
                                                  thread_fastpath_for as _tfp)
            _b = _active_bot()
            _bid = str((_b or {}).get("token") or "").split(":")[0].strip()
            # «Lọc thread» cài riêng cho thread này thì THẮNG; không cài → chuỗi cũ.
            _t = _tfp("tg", _bid, chat_id, user_id, _cur_topic())
            _fp = _t if _t is not None else _ha_fp(_b, chat_id)
        except Exception:
            _fp = bool(_active_bot().get("ha_fastpath", True))
        _model = _tg_model(chat_id, user_id)
        # Nhóm: mỗi USER một phiên riêng (lịch sử/persona/approval độc lập).
        # Chat 1-1 giữ key cũ (chat_id) để không mất lịch sử hiện có.
        # Nhóm bật Topics: mỗi TOPIC một phiên riêng ('chat#topic') — lịch sử
        # không trộn giữa các topic, và persona cài riêng topic có hiệu lực
        # (persona.prompt_for fallback: user-topic → user-nhóm → topic → nhóm).
        _skey = khoa_phien(chat_id, _cur_topic(), user_id)
        out = orchestrate(text, _skey, allow=_allow, ha_fastpath=_fp, model=_model,
                          is_admin=_is_admin_chat(chat_id, user_id))
        # P0#5 defense-in-depth: lọc lại media URL/path (orchestrator đã lọc).
        try:
            from services import net_guard
            out = net_guard.filter_agent_output(out if isinstance(out, dict) else {})
        except Exception:
            pass
        if out.get("silent"):
            return  # thread lọc yêu cầu chức năng bị tắt → bỏ qua, không nhắn gì
        # Trống + có nút chọn → `format_numbered` điền danh sách, đừng chèn "..."
        reply = (out.get("text") or "").strip()
        if not reply and not out.get("choices"):
            reply = "..."
        image_url = out.get("image_url")
        image_urls = out.get("image_urls")
        if isinstance(image_urls, list) and len(image_urls) > 1:
            # Telegram gộp tối đa 10 ảnh mỗi album (giới hạn sendMediaGroup của
            # Bot API), khác Zalo Cá Nhân 50 — nên chia lô 10, không dùng chung
            # con số của kênh khác.
            gui = 0
            for i in range(0, len(image_urls), 10):
                lo = [u for u in image_urls[i:i + 10]]
                if _gui_album(chat_id, lo, caption=reply[:1000] if i == 0 else ""):
                    gui += len(lo)
            if gui:
                if gui < len(image_urls):
                    send_message(chat_id, f"(gửi được {gui}/{len(image_urls)} ảnh)")
                return
            # Album thất bại → rơi về gửi từng tấm, thà chậm hơn là mất cả loạt.
            da = 0
            for u in image_urls:
                img = _fetch_image_bytes(u)
                if img and send_photo(chat_id, img, caption="").get("ok"):
                    da += 1
            if da:
                send_message(chat_id, reply[:1000] if da == len(image_urls)
                             else f"{reply[:900]}\n(gửi được {da}/{len(image_urls)} ảnh)")
                return
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
            # Flow x2/x3/x4 trả về nhiều video và đã trừ tín dụng cho từng cái —
            # gửi hết, không chỉ cái đầu.
            paths = [str(p) for p in (out.get("video_paths") or []) if p] \
                or ([str(video_path)] if video_path else [])
            urls = [str(u) for u in (out.get("video_urls") or []) if u] \
                or ([str(video_url)] if video_url else [])
            nguon: list[tuple[str, str]] = [("path", p) for p in paths] or \
                                           [("url", u) for u in urls]
            da_gui = 0
            for i, (kieu, src) in enumerate(nguon):
                try:
                    vid = _doc_media_co_tran(kieu, src, MAX_UPLOAD_FILE_BYTES, "video")
                    send_video(chat_id, vid, caption=reply[:1000] if i == 0 else "")
                    da_gui += 1
                except Exception as exc:
                    logger.warning("send video failed: %s", exc)
            if da_gui:
                if da_gui < len(nguon):
                    send_message(chat_id, f"(gửi được {da_gui}/{len(nguon)} video)")
                return
            if video_url:
                reply = f"{reply}\n{video_url}"
        audio_path = out.get("audio_path")
        audio_url = out.get("audio_url")
        if audio_path or audio_url:
            try:
                aud = _doc_media_co_tran(
                    "path" if audio_path else "url",
                    str(audio_path or audio_url), MAX_UPLOAD_FILE_BYTES, "audio")
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
                send_document(chat_id,
                              _doc_media_co_tran("path", str(_p), MAX_UPLOAD_FILE_BYTES, "tài liệu"),
                              _p.name, caption=reply[:1000])
                return
            except Exception as exc:
                logger.warning("send doc failed: %s", exc)
        # Text path: preserve choices from orchestrator for inline keyboard
        if out.get("choices") and not any(
            out.get(k) for k in ("image_url", "video_path", "video_url", "audio_path", "audio_url")
        ):
            # Có nút chọn số → giữ chữ (không voice-only), voice kèm nếu bật.
            _send_agent_reply(chat_id, out, user_id=user_id)
            _maybe_voice_reply(chat_id, user_id, reply)
        elif not _maybe_voice_reply(chat_id, user_id, reply):
            # tts_reply tắt / TTS lỗi → gửi chữ; bật + gửi được voice → chỉ voice.
            send_message(chat_id, reply)
        return
    except Exception as exc:
        logger.warning("orchestrator error for %s: %s", chat_id, exc)

    # Fallback: plain model call
    # Khoá theo PHIÊN, không theo chat: trong nhóm, khoá theo chat_id là mọi
    # thành viên chung một bộ đệm hội thoại — tin của người này thành ngữ cảnh
    # của người kia. Đường này chỉ chạy khi orchestrator lỗi, nhưng lúc đó bộ
    # lọc trộn ngữ cảnh vẫn phải giữ.
    key = f"tg_{khoa_phien(chat_id, _cur_topic(), user_id)}"
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
