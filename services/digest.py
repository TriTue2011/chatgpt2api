"""Tóm tắt & gửi thông báo từ NHIỀU nguồn (email, lịch) tới NHIỀU kênh.

Mỗi nguồn (một hộp mail / một lịch) tự cấu hình:
  - ``notify_targets``: danh sách kênh nhận — khóa GIỐNG HỆT tab «Lọc thread»
    ``plat:bot:chat`` (kèm ``#topic`` được), nhờ vậy UI dùng lại danh sách thread
    người dùng đã đặt tên sẵn.
  - ``notify_on_new``: hễ có mục mới là tóm tắt và gửi NGAY.
  - ``notify_times``: danh sách ``HH:MM`` — gom các mục mới lại, tới giờ mới gửi
    một bản tổng hợp (định kỳ). Bật cả hai cùng lúc cũng được.

State: ``DATA_DIR/digest_state.json``::

    {"email:a1": {"seen": ["<uid>"],
                  "pending": [{"ts": 1769000000, "text": "..."}],
                  "fired": {"07:00": "2026-07-26"}}}

``seen`` chống gửi trùng (UID mail / UID sự kiện lịch), ``pending`` là bộ đệm chờ
tới giờ, ``fired`` ghi ngày đã bắn từng mốc giờ để một mốc chỉ bắn 1 lần/ngày.

Không bao giờ raise ra ngoài: nguồn tin lỗi thì bỏ qua, không được làm chết luồng
poll của email/lịch.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.config import DATA_DIR

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:  # pragma: no cover - môi trường thiếu tzdata
    _TZ = timezone(timedelta(hours=7))

_PATH = Path(DATA_DIR) / "digest_state.json"
_lock = threading.RLock()
_state: dict[str, dict[str, Any]] = {}
_loaded = False

_SEEN_CAP = 400      # UID giữ lại mỗi nguồn (đủ chống trùng, không phình file)
_PENDING_CAP = 60    # mục chờ tối đa mỗi nguồn
_MAX_MSG = 3500      # Telegram ~4096; chừa chỗ tiêu đề

_started = False
_stop = threading.Event()


# ── State ────────────────────────────────────────────────────────────────────
def _ensure() -> None:
    global _loaded, _state
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        try:
            if _PATH.is_file():
                raw = json.loads(_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    _state = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
        except Exception:
            _state = {}
        _loaded = True


def _save() -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_state, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(_PATH)
    except Exception as exc:
        logger.warning("digest: save state lỗi: %s", exc)


def _rec(source: str) -> dict[str, Any]:
    _ensure()
    r = _state.get(source)
    if not isinstance(r, dict):
        r = {"seen": [], "pending": [], "fired": {}}
        _state[source] = r
    r.setdefault("seen", [])
    r.setdefault("pending", [])
    r.setdefault("fired", {})
    return r


def seen(source: str, uid: str) -> bool:
    """UID này đã xử lý chưa (chống gửi trùng khi poll lại)."""
    uid = str(uid or "").strip()
    if not uid:
        return False
    with _lock:
        return uid in (_rec(source).get("seen") or [])


def mark_seen(source: str, uid: str) -> None:
    uid = str(uid or "").strip()
    if not uid:
        return
    with _lock:
        r = _rec(source)
        lst = [x for x in (r.get("seen") or []) if x != uid]
        lst.append(uid)
        r["seen"] = lst[-_SEEN_CAP:]
        _save()


def queue(source: str, text: str) -> None:
    """Gom một mục vào bộ đệm chờ tới giờ định kỳ."""
    text = str(text or "").strip()
    if not text:
        return
    with _lock:
        r = _rec(source)
        pend = list(r.get("pending") or [])
        pend.append({"ts": time.time(), "text": text[:2000]})
        r["pending"] = pend[-_PENDING_CAP:]
        _save()


def pending_count(source: str) -> int:
    with _lock:
        return len(_rec(source).get("pending") or [])


def _take_pending(source: str) -> list[dict[str, Any]]:
    with _lock:
        r = _rec(source)
        pend = list(r.get("pending") or [])
        r["pending"] = []
        _save()
        return pend


def forget(source: str) -> None:
    """Xóa state của một nguồn (khi người dùng xóa hộp mail / lịch)."""
    with _lock:
        _ensure()
        if source in _state:
            _state.pop(source, None)
            _save()


# ── Gửi tới kênh ─────────────────────────────────────────────────────────────
def _zalop_thread_type(account: str, thread_id: str) -> int:
    """Zalo Cá Nhân cần biết thread là nhóm (1) hay cá nhân (0). Tra danh bạ kênh;
    không thấy thì đoán cá nhân (0) — an toàn hơn gửi sai vào nhóm."""
    try:
        from services import channel_contacts as cc
        rec = cc.get(cc.contact_key("zalop", account, thread_id))
        if rec and rec.get("is_group"):
            return 1
    except Exception:
        pass
    return 0


def parse_target(target: str) -> tuple[str, str, str, str] | None:
    """'plat:bot:chat[#topic]' → (plat, bot_id, chat_id, topic).

    Cho phép dạng ngắn 'plat:chat' (không chỉ bot → dùng bot đầu tiên của kênh).
    Trả None nếu khóa không dùng được."""
    t = str(target or "").strip()
    if not t or ":" not in t:
        return None
    parts = t.split(":")
    plat = parts[0].strip()
    if plat not in {"tg", "zalo", "zalop"}:
        return None
    if len(parts) >= 3:
        bot_id, chat = parts[1].strip(), ":".join(parts[2:]).strip()
    else:
        bot_id, chat = "", parts[1].strip()
    topic = ""
    if plat == "tg" and "#" in chat:
        chat, topic = chat.split("#", 1)
        chat, topic = chat.strip(), topic.strip()
    if not chat:
        return None
    return (plat, bot_id, chat, topic)


def send_target(target: str, text: str) -> bool:
    """Gửi text tới MỘT kênh. Không raise; trả False nếu không gửi được."""
    parsed = parse_target(target)
    if not parsed:
        logger.warning("digest: kênh nhận không hợp lệ: %r", target)
        return False
    plat, bot_id, chat, topic = parsed
    body = str(text or "").strip()
    if not body:
        return False
    if len(body) > _MAX_MSG:
        body = body[:_MAX_MSG] + "…"
    try:
        if plat == "tg":
            from services import telegram_bot as tg
            bot = tg._find_bot_by_id(bot_id) if bot_id else None
            prev_bot = tg._cur_bot()
            prev_topic = getattr(tg._current, "topic", None)
            try:
                if bot is not None:
                    tg._current.bot = bot
                # Gửi đúng TOPIC nếu khóa kênh có '#<topic>'
                tg._current.topic = topic
                return bool(tg.send_message(chat, body).get("ok"))
            finally:
                tg._current.bot = prev_bot
                tg._current.topic = prev_topic
        if plat == "zalo":
            from services import zalo_bot as zb
            bot = zb._find_bot_by_id(bot_id) if bot_id else None
            prev = zb._cur_bot()
            try:
                if bot is not None:
                    zb._current.bot = bot
                return bool(zb.send_message(chat, body))
            finally:
                zb._current.bot = prev
        if plat == "zalop":
            from services.zalo_personal import send_message as zp_send
            return bool(zp_send(chat, body, _zalop_thread_type(bot_id, chat),
                                account=bot_id))
    except Exception as exc:
        logger.warning("digest: gửi %s lỗi: %s", target, str(exc)[:160])
    return False


def send_targets(targets: Any, text: str) -> int:
    """Gửi tới MỌI kênh đã chọn — trả số kênh gửi thành công."""
    if not isinstance(targets, (list, tuple)):
        return 0
    n = 0
    for t in targets:
        if send_target(str(t), text):
            n += 1
    return n


# ── Tóm tắt ──────────────────────────────────────────────────────────────────
def summarize(text: str, *, what: str = "email", max_chars: int = 900) -> str:
    """Tóm tắt bằng model 'burst' (rẻ/nhanh). Lỗi/không có model → cắt gọn thô,
    KHÔNG bao giờ trả rỗng để thông báo không bị mất nội dung."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    if len(raw) <= 240:
        return raw
    try:
        from services.agent.orchestrator import _main_model
        from services.agent.runtime import call_model
        model = _main_model("burst") or _main_model("chat")
        if model:
            out = call_model(
                model,
                [
                    {"role": "system", "content":
                        "Bạn tóm tắt tiếng Việt, ngắn gọn, đúng sự thật. Không thêm "
                        "thông tin không có trong nội dung. Trả tối đa 6 gạch đầu dòng."},
                    {"role": "user", "content":
                        f"Tóm tắt {what} sau (nêu ai gửi/việc gì/mốc thời gian/việc cần làm):"
                        f"\n\n{raw[:12000]}"},
                ],
                max_tokens=420, timeout=90,
                # Tóm tắt là việc ĐỌC NỘI DUNG CÓ SẴN — không được đi tra web.
                # Bản cũ để trống nên gateway bật web search tự động và lấy
                # NGUYÊN prompt tóm tắt làm câu truy vấn: log đầy
                # "Federated search: 0 results for 'Tóm tắt email sau (nêu ai
                # gửi/việc gì...'" kèm 414 Request-URI Too Long từ PubMed/
                # CrossRef/Archive. Vô ích, và cộng hàng chục giây cho MỖI thư
                # trong khi vòng poll mail chạy tuần tự.
                allowed_groups={"summary"},
            )
            msg = (((out.get("choices") or [{}])[0]).get("message") or {})
            s = str(msg.get("content") or "").strip()
            if s:
                return s[:max_chars]
    except Exception as exc:
        logger.warning("digest: tóm tắt lỗi (dùng bản cắt gọn): %s", str(exc)[:160])
    return raw[:max_chars] + ("…" if len(raw) > max_chars else "")


# ── Thông báo ────────────────────────────────────────────────────────────────
def notify(source: str, cfg: dict[str, Any], text: str) -> dict[str, Any]:
    """Xử lý một mục mới theo cấu hình thông báo của nguồn.

    - ``notify_on_new`` → gửi ngay tới mọi kênh.
    - ``notify_times``  → xếp vào bộ đệm, tick() gửi khi tới giờ.
    Trả {sent_now: int, queued: bool}."""
    targets = cfg.get("notify_targets") or []
    on_new = bool(cfg.get("notify_on_new"))
    times = [t for t in (cfg.get("notify_times") or []) if str(t).strip()]
    out: dict[str, Any] = {"sent_now": 0, "queued": False}
    body = str(text or "").strip()
    if not body:
        return out
    if on_new and targets:
        out["sent_now"] = send_targets(targets, body)
    if times:
        queue(source, body)
        out["queued"] = True
    return out


def _hm_now() -> str:
    return datetime.now(_TZ).strftime("%H:%M")


def _today() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d")


def _norm_hm(v: Any) -> str:
    """'7:5' / '07:05' / '0705' → '07:05'; không hợp lệ → ''."""
    s = str(v or "").strip()
    if not s:
        return ""
    if ":" not in s and s.isdigit() and len(s) in (3, 4):
        s = s[:-2].rjust(2, "0") + ":" + s[-2:]
    parts = s.split(":")
    if len(parts) != 2:
        return ""
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return ""
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return ""
    return f"{h:02d}:{m:02d}"


def flush(source: str, cfg: dict[str, Any], *, title: str = "") -> int:
    """Gộp bộ đệm của nguồn thành MỘT bản tổng hợp rồi gửi. Trả số kênh đã gửi.
    Bộ đệm rỗng → không gửi gì (không spam 'không có gì mới')."""
    targets = cfg.get("notify_targets") or []
    if not targets:
        return 0
    pend = _take_pending(source)
    if not pend:
        return 0
    head = (title or f"📬 Tổng hợp ({len(pend)} mục)").strip()
    lines = [f"{head} — {len(pend)} mục", ""]
    for i, item in enumerate(pend, 1):
        when = datetime.fromtimestamp(float(item.get("ts") or 0), _TZ).strftime("%H:%M")
        lines.append(f"{i}. [{when}] {str(item.get('text') or '').strip()}")
    return send_targets(targets, "\n".join(lines))


def tick(sources: list[tuple[str, dict[str, Any], str]] | None = None) -> int:
    """Kiểm tra mốc giờ định kỳ của mọi nguồn, gửi bản tổng hợp nếu tới giờ.

    `sources` = [(source_key, cfg, title)]; None = tự đọc từ email + lịch.
    Mỗi mốc giờ chỉ bắn 1 lần/ngày (state 'fired'). Trả số nguồn đã gửi."""
    if sources is None:
        sources = _all_sources()
    now_hm = _hm_now()
    today = _today()
    fired_n = 0
    for source, cfg, title in sources:
        times = {_norm_hm(t) for t in (cfg.get("notify_times") or [])}
        times.discard("")
        if now_hm not in times:
            continue
        with _lock:
            r = _rec(source)
            if str((r.get("fired") or {}).get(now_hm) or "") == today:
                continue  # mốc này hôm nay đã bắn
            r.setdefault("fired", {})[now_hm] = today
            _save()
        try:
            if flush(source, cfg, title=title):
                fired_n += 1
        except Exception as exc:
            logger.warning("digest: flush %s lỗi: %s", source, str(exc)[:160])
    return fired_n


def _all_sources() -> list[tuple[str, dict[str, Any], str]]:
    """Mọi nguồn đang bật — email trước, lịch sau. Lỗi một bên không chặn bên kia."""
    out: list[tuple[str, dict[str, Any], str]] = []
    try:
        from services.email_channel import accounts, source_key
        for acc in accounts():
            if acc.get("enabled"):
                label = str(acc.get("label") or acc.get("user") or "email")
                out.append((source_key(acc), acc, f"📬 Tổng hợp email · {label}"))
    except Exception as exc:
        logger.warning("digest: đọc email accounts lỗi: %s", str(exc)[:160])
    try:
        from services.calendar_connector import calendars, source_key as cal_key
        for cal in calendars():
            if cal.get("enabled"):
                label = str(cal.get("label") or "lịch")
                out.append((cal_key(cal), cal, f"📅 Tổng hợp lịch · {label}"))
    except Exception as exc:
        logger.warning("digest: đọc calendars lỗi: %s", str(exc)[:160])
    return out


# ── Vòng lặp ─────────────────────────────────────────────────────────────────
def _loop() -> None:
    _stop.wait(20)
    while not _stop.is_set():
        try:
            tick()
        except Exception as exc:
            logger.warning("digest: tick lỗi: %s", str(exc)[:160])
        # 30s: mốc 'HH:MM' luôn được kiểm tra ít nhất 2 lần trong phút của nó
        _stop.wait(30)


def start() -> None:
    """Chạy nền vĩnh viễn — tick() tự đọc cấu hình mỗi vòng nên thêm/sửa hộp mail
    hay lịch trong Settings có hiệu lực ngay, KHÔNG cần restart container."""
    global _started
    if _started:
        return
    _started = True
    _stop.clear()
    threading.Thread(target=_loop, name="digest-scheduler", daemon=True).start()
    logger.info("digest: scheduler started")


def stop() -> None:
    global _started
    _stop.set()
    _started = False


def _reset_for_tests(path: Path | None = None) -> None:
    global _PATH, _state, _loaded
    stop()
    with _lock:
        if path is not None:
            _PATH = path
        _state = {}
        _loaded = False
