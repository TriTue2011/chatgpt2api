"""Lịch ICS — NHIỀU lịch: đọc feed, phát hiện sự kiện mới, tóm tắt gửi kênh.

Không phải CalDAV đầy đủ: đọc một URL ICS (link bí mật của Google Calendar,
Outlook, Nextcloud…) rồi lấy N sự kiện sắp tới.

Config ``calendars`` (list — mỗi phần tử một lịch)::

    id: str                  — khóa ổn định (tự sinh nếu thiếu)
    label: str               — tên hiển thị ("Lịch gia đình")
    enabled: bool
    ics_url: str             — link .ics
    days_ahead: int (7)      — nhìn trước bao nhiêu ngày
    max_events: int (8)
    cache_seconds: int (900)
    notify_on_new: bool      — có sự kiện MỚI là gửi ngay
    notify_times: list[str]  — ["07:00"] gom lại gửi định kỳ
    notify_targets: list[str]— kênh nhận, khóa 'plat:bot:chat' như «Lọc thread»
    remind_before: list[str] — NHIỀU MỐC nhắc trước sự kiện: ["7d","1d","2h","30m"]
                               (d=ngày, h=giờ, m=phút; số trần = ngày). Mỗi sự
                               kiện nhắc một lần ở từng mốc; cửa sổ nhìn trước
                               tự nới theo mốc lớn nhất.

Tương thích ngược: ``calendars`` rỗng thì đọc ``calendar_connector`` (cấu hình
một-lịch cũ) thành lịch #1 — không ghi đè, không cần migrate.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.config import config

logger = logging.getLogger(__name__)

_lock = threading.RLock()
#: cache theo TỪNG lịch: {source_key: {"ts": float, "events": [...]}}
_cache: dict[str, dict[str, Any]] = {}

_started = False
_stop = threading.Event()

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:  # pragma: no cover
    _TZ = timezone(timedelta(hours=7))


# ── Danh sách lịch ───────────────────────────────────────────────────────────
def parse_lead(v: Any) -> int:
    """Mốc nhắc trước → GIÂY: '7d'=7 ngày, '2h'=2 giờ, '30m'=30 phút, '7'=7 ngày.
    Không hợp lệ → 0 (mốc bị bỏ qua)."""
    s = str(v or "").strip().lower()
    if not s:
        return 0
    unit = 86400  # số trần = ngày
    if s[-1] in ("d", "h", "m"):
        unit = {"d": 86400, "h": 3600, "m": 60}[s[-1]]
        s = s[:-1]
    try:
        n = float(s)
    except ValueError:
        return 0
    return int(n * unit) if n > 0 else 0


def _legacy() -> dict[str, Any]:
    raw = config.get().get("calendar_connector")
    return raw if isinstance(raw, dict) else {}


def _norm_cal(raw: Any, idx: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    url = str(raw.get("ics_url") or "").strip()
    cal_id = str(raw.get("id") or "").strip()
    if not cal_id:
        # id ổn định theo URL → state 'seen' không mất khi đổi thứ tự danh sách
        cal_id = hashlib.sha256(url.encode()).hexdigest()[:8] if url else f"c{idx + 1}"

    def _int(key: str, default: int, lo: int = 1) -> int:
        try:
            return max(lo, int(raw.get(key) or default))
        except (TypeError, ValueError):
            return default

    times = raw.get("notify_times")
    if isinstance(times, str):
        times = [s.strip() for s in times.split(",") if s.strip()]
    targets = raw.get("notify_targets")
    if isinstance(targets, str):
        targets = [s.strip() for s in targets.split(",") if s.strip()]
    remind = raw.get("remind_before")
    if isinstance(remind, str):
        remind = [s.strip() for s in remind.split(",") if s.strip()]
    remind = [str(x).strip() for x in (remind or []) if parse_lead(x) > 0]
    days = _int("days_ahead", 7)
    if remind:
        # Cửa sổ nhìn trước phải PHỦ mốc nhắc xa nhất, không thì sự kiện chưa
        # vào cache đã tới giờ nhắc.
        max_days = max(parse_lead(x) for x in remind) / 86400.0
        days = max(days, int(max_days) + 1)
    return {
        "id": cal_id,
        "label": str(raw.get("label") or f"Lịch {idx + 1}").strip(),
        "enabled": bool(raw.get("enabled")),
        "ics_url": url,
        "days_ahead": days,
        "max_events": min(30, _int("max_events", 8)),
        "cache_seconds": _int("cache_seconds", 900, lo=60),
        "notify_on_new": bool(raw.get("notify_on_new", True)),
        "notify_times": [str(t) for t in (times or []) if str(t).strip()],
        "notify_targets": [str(t) for t in (targets or []) if str(t).strip()],
        "remind_before": remind,
    }


def calendars() -> list[dict[str, Any]]:
    """Mọi lịch đã cấu hình (đã chuẩn hóa); rỗng thì lấy cấu hình một-lịch cũ."""
    raw = config.get().get("calendars")
    out: list[dict[str, Any]] = []
    if isinstance(raw, list) and raw:
        for i, item in enumerate(raw):
            cal = _norm_cal(item, i)
            if cal and cal.get("ics_url"):
                out.append(cal)
        if out:
            return out
    legacy = _legacy()
    if str(legacy.get("ics_url") or "").strip():
        cal = _norm_cal({**legacy, "label": legacy.get("label") or "Lịch chính"}, 0)
        if cal:
            out.append(cal)
    return out


def source_key(cal: dict[str, Any]) -> str:
    return f"cal:{str(cal.get('id') or '').strip() or 'c1'}"


def calendar_by_id(calendar_id: str) -> dict[str, Any] | None:
    cid = str(calendar_id or "").strip()
    cals = calendars()
    if not cid:
        return cals[0] if cals else None
    for c in cals:
        if c.get("id") == cid:
            return c
    return None


def is_enabled() -> bool:
    """Có ít nhất một lịch đang bật."""
    return any(c.get("enabled") for c in calendars())


# ── Phân tích ICS ────────────────────────────────────────────────────────────
def _unfold(ics: str) -> str:
    # RFC 5545: dòng gấp = CRLF + space/tab
    return re.sub(r"\r?\n[ \t]", "", ics or "")


def _parse_dt(val: str) -> Optional[datetime]:
    val = (val or "").strip()
    if ":" in val and not re.match(r"^\d", val):
        val = val.split(":", 1)[-1]
    val = val.replace("Z", "").strip()
    dt: Optional[datetime] = None
    try:
        if "T" in val:
            core = re.sub(r"[^0-9T]", "", val)[:15]
            if len(core) >= 15:
                dt = datetime.strptime(core[:15], "%Y%m%dT%H%M%S")
            elif len(core) >= 13:
                dt = datetime.strptime(core[:13], "%Y%m%dT%H%M")
        else:
            core = re.sub(r"\D", "", val)[:8]
            if len(core) == 8:
                dt = datetime.strptime(core, "%Y%m%d")
    except Exception:
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ)
    return dt


def _parse_events(ics: str) -> list[dict[str, Any]]:
    ics = _unfold(ics)
    events: list[dict[str, Any]] = []
    blocks = re.split(r"BEGIN:VEVENT", ics, flags=re.I)[1:]
    for block in blocks:
        end = re.split(r"END:VEVENT", block, flags=re.I)[0]
        fields: dict[str, str] = {}
        for line in end.splitlines():
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.split(";")[0].strip().upper()
            fields[key] = val.strip()
        summary = fields.get("SUMMARY") or "(không tiêu đề)"
        summary = summary.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";")
        dtstart = _parse_dt(fields.get("DTSTART") or "")
        if not dtstart:
            continue
        events.append({
            "uid": str(fields.get("UID") or "").strip(),
            "summary": summary[:200],
            "start": dtstart,
            "end": _parse_dt(fields.get("DTEND") or ""),
            "location": (fields.get("LOCATION") or "").replace("\\,", ",")[:120],
            "description": (fields.get("DESCRIPTION") or "")
            .replace("\\n", " ").replace("\\,", ",")[:500],
        })
    events.sort(key=lambda e: e["start"])
    return events


def _fetch_ics(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "chatgpt2api-calendar/1.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_events(cal: dict[str, Any] | None = None, *,
                 force: bool = False) -> list[dict[str, Any]]:
    """Sự kiện sắp tới của MỘT lịch (None = lịch đầu tiên đang bật).

    Lỗi mạng → trả cache cũ (không làm rỗng lịch trong prompt)."""
    if cal is None:
        cals = [c for c in calendars() if c.get("enabled")]
        if not cals:
            return []
        cal = cals[0]
    url = str(cal.get("ics_url") or "").strip()
    if not url:
        return []
    key = source_key(cal)
    cache_s = int(cal.get("cache_seconds") or 900)
    with _lock:
        c = _cache.get(key) or {}
        if not force and c.get("events") and time.time() - float(c.get("ts") or 0) < cache_s:
            return list(c["events"])

    try:
        raw = _fetch_ics(url)
    except Exception as exc:
        logger.warning("calendar %s: tải lỗi: %s", cal.get("label"), exc)
        with _lock:
            return list((_cache.get(key) or {}).get("events") or [])

    now = datetime.now(_TZ)
    horizon = now + timedelta(days=int(cal.get("days_ahead") or 7))
    max_n = int(cal.get("max_events") or 8)
    events: list[dict[str, Any]] = []
    for ev in _parse_events(raw):
        if ev["start"] < now - timedelta(hours=2) or ev["start"] > horizon:
            continue
        events.append(ev)
        if len(events) >= max_n:
            break

    with _lock:
        _cache[key] = {"ts": time.time(), "events": events}
    return events


def format_events(events: list[dict[str, Any]] | None = None, *,
                  title: str = "### Lịch sắp tới") -> str:
    if events is None:
        events = fetch_events()
    if not events:
        return ""
    lines = [title]
    for ev in events:
        st: datetime = ev["start"]
        when = st.astimezone(_TZ).strftime("%a %d/%m %H:%M")
        loc = f" @ {ev['location']}" if ev.get("location") else ""
        lines.append(f"- {when}: {ev['summary']}{loc}")
    return "\n".join(lines)


def khop_muc_tieu(target: str, sc: Any) -> bool:
    """Khoá kênh nhận `plat[:bot]:chat[#topic]` có trỏ đúng lượt này không?

    Khoá giống hệt tab «Lọc thread». Ở đây chỉ so kênh + chat (+ topic) nên khoá
    có hay không có phần `bot` đều khớp — super_context không biết bot nào đang
    chạy, mà chat id thì đã đủ phân biệt.

    Mục tiêu trỏ MỘT topic → chỉ lượt trong đúng topic đó nhận. Mục tiêu trỏ cả
    nhóm → mọi topic trong nhóm nhận.
    """
    phan = str(target or "").strip().split(":")
    if len(phan) < 2 or not phan[0]:
        return False
    if phan[0] != getattr(sc, "kenh", ""):
        return False
    chat, _, topic = phan[-1].partition("#")
    if chat != getattr(sc, "chat", ""):
        return False
    return not topic or topic == getattr(sc, "topic", "")


def _lich_cho_luot(cal: dict[str, Any], sc: Any) -> bool:
    """Lịch này có dành cho lượt đang chạy?

    `notify_targets` là chính lời khai của chủ máy về việc lịch này thuộc về
    thread nào — dùng lại nó, không thêm cài đặt thứ hai để chủ máy phải nhớ.

    Lịch CHƯA khai kênh nhận thì không giới hạn (giữ hành vi cũ): nó là lịch một
    mình dùng, tắt đi là lấy mất thứ đang chạy mà không ai yêu cầu.
    """
    if sc is None:
        return True
    targets = cal.get("notify_targets") or []
    if not targets:
        return True
    return any(khop_muc_tieu(t, sc) for t in targets)


def prompt_block(user_id: str = "") -> str:
    """Cho super_context / system prompt — gộp mọi lịch đang bật DÀNH CHO lượt này.

    Trước đây gộp MỌI lịch đang bật, bất kể ai đang nhắn: sự kiện lịch gia đình
    đi vào system prompt của mọi thread, kể cả nhóm người ngoài. `user_id` là
    khoá phiên orchestrator; rỗng = đường nội bộ, giữ nguyên hành vi cũ.
    """
    sc = None
    if str(user_id or "").strip():
        try:
            from services.agent.scope import tach_khoa_phien
            sc = tach_khoa_phien(user_id)
        except Exception:
            sc = None
    parts: list[str] = []
    try:
        for cal in calendars():
            if not cal.get("enabled"):
                continue
            if not _lich_cho_luot(cal, sc):
                continue
            evs = fetch_events(cal)
            if evs:
                parts.append(format_events(
                    evs, title=f"### Lịch sắp tới — {cal.get('label')}"))
    except Exception:
        return ""
    return "\n\n".join(parts)


# ── Kiểm tra lịch (nút «Kiểm tra» trong UI) ──────────────────────────────────
def test_calendar(calendar_id: str = "") -> dict[str, Any]:
    """Tải thật ICS rồi báo: đọc được không, bao nhiêu sự kiện, 3 sự kiện gần nhất.

    Đây là cách «kiểm tra lịch» — không phải đợi tới giờ thông báo mới biết."""
    cal = calendar_by_id(calendar_id)
    if not cal:
        return {"ok": False, "error": "Chưa cấu hình lịch nào"}
    url = str(cal.get("ics_url") or "").strip()
    if not url:
        return {"ok": False, "error": "❌ Chưa nhập link ICS"}
    if not url.lower().startswith(("http://", "https://")):
        return {"ok": False, "error": "❌ Link ICS phải bắt đầu bằng http:// hoặc https://"}
    try:
        raw = _fetch_ics(url)
    except Exception as exc:
        low = str(exc).lower()
        if "404" in low:
            hint = "❌ Link không tồn tại (404) — lấy lại link ICS bí mật."
        elif "401" in low or "403" in low:
            hint = ("❌ Link bị từ chối (401/403) — lịch chưa chia sẻ / sai link bí mật.")
        elif "timed out" in low or "timeout" in low:
            hint = "❌ Hết thời gian tải — kiểm tra mạng rồi thử lại."
        else:
            hint = f"❌ Không tải được link ICS: {str(exc)[:160]}"
        return {"ok": False, "error": hint, "id": cal.get("id")}
    if "BEGIN:VCALENDAR" not in raw.upper():
        return {"ok": False, "id": cal.get("id"),
                "error": "❌ Tải được nhưng nội dung KHÔNG phải file ICS "
                         "(link có thể trả về trang HTML đăng nhập)."}
    all_events = _parse_events(raw)
    upcoming = fetch_events(cal, force=True)
    preview = [
        f"{e['start'].astimezone(_TZ).strftime('%d/%m %H:%M')} — {e['summary']}"
        for e in upcoming[:3]
    ]
    return {
        "ok": True,
        "id": cal.get("id"),
        "label": cal.get("label"),
        "total": len(all_events),
        "upcoming": len(upcoming),
        "preview": preview,
        "message": (f"✅ Đọc được lịch: {len(all_events)} sự kiện trong file, "
                    f"{len(upcoming)} sự kiện trong {cal.get('days_ahead')} ngày tới"
                    + (f" · gần nhất: {preview[0]}" if preview
                       else " · (không có sự kiện nào sắp tới)")),
    }


# ── Sự kiện mới → thông báo ──────────────────────────────────────────────────
def _ev_uid(ev: dict[str, Any]) -> str:
    """UID chống trùng — ICS UID nếu có, không thì băm (giờ bắt đầu + tiêu đề).
    Kèm giờ bắt đầu để sự kiện BỊ ĐỔI GIỜ cũng được coi là mục mới.
    Không cần trộn id lịch: state đã tách theo source_key của từng lịch."""
    base = f"{ev.get('uid') or ''}|{ev['start'].isoformat()}|{ev.get('summary')}"
    return hashlib.sha256(base.encode()).hexdigest()[:20]


def check_new(cal: dict[str, Any]) -> int:
    """Tìm sự kiện MỚI của một lịch rồi thông báo theo cấu hình. Trả số mục mới."""
    from services import digest
    src = source_key(cal)
    try:
        events = fetch_events(cal, force=True)
    except Exception as exc:
        logger.warning("calendar %s: check_new lỗi: %s", cal.get("label"), exc)
        return 0
    if not cal.get("notify_targets"):
        # Chưa chọn kênh: vẫn ghi 'seen' để lúc chọn kênh không đổ dồn lịch cũ
        for ev in events:
            digest.mark_seen(src, _ev_uid(ev))
        return 0
    new_n = 0
    for ev in events:
        uid = _ev_uid(ev)
        if digest.seen(src, uid):
            continue
        digest.mark_seen(src, uid)
        new_n += 1
        when = ev["start"].astimezone(_TZ).strftime("%a %d/%m %H:%M")
        loc = f"\n📍 {ev['location']}" if ev.get("location") else ""
        desc = f"\n{ev['description']}" if ev.get("description") else ""
        text = (f"📅 {cal.get('label')} — sự kiện mới\n"
                f"🗓️ {when}: {ev['summary']}{loc}{desc}").strip()
        try:
            digest.notify(src, cal, text)
        except Exception as exc:
            logger.warning("calendar: thông báo lỗi: %s", str(exc)[:160])
    return new_n


def check_reminders(cal: dict[str, Any]) -> int:
    """NHIỀU MỐC nhắc trước sự kiện (remind_before) — trả số tin đã gửi.

    Mỗi (sự kiện, mốc) chỉ nhắc MỘT lần (state 'rem:<uid>:<mốc>'). Sự kiện phát
    hiện muộn khi nhiều mốc đã trôi qua → chỉ nhắc MỐC GẦN NHẤT, các mốc trễ hơn
    đánh dấu đã qua (không dội 3-4 tin một lúc). Sự kiện đã bắt đầu → thôi."""
    from services import digest
    leads = sorted(
        {(parse_lead(x), str(x).strip()) for x in (cal.get("remind_before") or [])
         if parse_lead(x) > 0})
    if not leads or not cal.get("notify_targets"):
        return 0
    src = source_key(cal)
    now = datetime.now(_TZ)
    sent = 0
    for ev in fetch_events(cal):        # dùng cache — không đập feed mỗi tick
        if ev["start"] <= now:
            continue
        # Mốc đang "tới giờ": start - lead <= now < start
        active = [(secs, lbl) for secs, lbl in leads
                  if ev["start"] - timedelta(seconds=secs) <= now]
        if not active:
            continue
        fresh = [(s, l) for s, l in active
                 if not digest.seen(src, f"rem:{_ev_uid(ev)}:{l}")]
        if not fresh:
            continue
        for _s, lbl in fresh:           # mọi mốc active đều coi như đã xử lý
            digest.mark_seen(src, f"rem:{_ev_uid(ev)}:{lbl}")
        secs, lbl = fresh[0]            # nhỏ nhất = sát sự kiện nhất
        left = ev["start"] - now
        mins = int(left.total_seconds() // 60)
        left_txt = (f"{mins // 1440} ngày {mins % 1440 // 60} giờ" if mins >= 1440
                    else f"{mins // 60} giờ {mins % 60} phút" if mins >= 60
                    else f"{max(1, mins)} phút")
        when = ev["start"].astimezone(_TZ).strftime("%a %d/%m %H:%M")
        loc = f"\n📍 {ev['location']}" if ev.get("location") else ""
        if digest.send_targets(
                cal["notify_targets"],
                f"⏰ {cal.get('label')} — còn {left_txt} (mốc {lbl})\n"
                f"🗓️ {when}: {ev['summary']}{loc}"):
            sent += 1
    return sent


def send_digest_now(calendar_id: str = "") -> dict[str, Any]:
    """Gửi NGAY bản lịch sắp tới tới các kênh đã chọn (nút «Gửi thử»)."""
    cal = calendar_by_id(calendar_id)
    if not cal:
        return {"ok": False, "error": "Chưa cấu hình lịch nào"}
    if not cal.get("notify_targets"):
        return {"ok": False, "error": "Lịch này chưa chọn kênh nhận"}
    from services import digest
    events = fetch_events(cal, force=True)
    body = format_events(events, title=f"📅 Lịch sắp tới — {cal.get('label')}")
    if not body:
        body = (f"📅 {cal.get('label')} — kiểm tra kênh nhận: OK "
                f"(không có sự kiện nào trong {cal.get('days_ahead')} ngày tới).")
    n = digest.send_targets(cal["notify_targets"], body)
    return {"ok": n > 0, "sent": n, "events": len(events),
            "message": f"Đã gửi {len(events)} sự kiện tới {n} kênh"}


# ── Vòng lặp ─────────────────────────────────────────────────────────────────
_CHECK_EVERY = 300.0   # 5 phút/lịch: đủ nhạy, không hại quota feed
_last_check: dict[str, float] = {}


def _loop() -> None:
    _stop.wait(25)
    while not _stop.is_set():
        try:
            for cal in calendars():
                if not cal.get("enabled"):
                    continue
                key = source_key(cal)
                if time.time() - _last_check.get(key, 0.0) >= _CHECK_EVERY:
                    _last_check[key] = time.time()
                    # Sự kiện mới gửi ngay (notify_on_new) hoặc xếp chờ tới giờ
                    # (notify_times) — digest.notify quyết định.
                    check_new(cal)
                # Mốc nhắc trước sự kiện: kiểm tra MỖI tick (60s) từ cache —
                # rẻ, và mốc phút ('30m') không bị lệch 5 phút như check_new.
                check_reminders(cal)
        except Exception as exc:
            logger.warning("calendar: loop lỗi: %s", exc)
        _stop.wait(60)


def start() -> None:
    """Supervisor luôn chạy: thêm/bật lịch trong Settings có hiệu lực ngay."""
    global _started
    if _started:
        return
    _started = True
    _stop.clear()
    threading.Thread(target=_loop, name="calendar-watch", daemon=True).start()
    logger.info("calendar: started (%d lịch)", len(calendars()))


def stop() -> None:
    global _started
    _stop.set()
    _started = False


def status() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for c in calendars():
        key = source_key(c)
        with _lock:
            cached = (_cache.get(key) or {}).get("events") or []
        rows.append({
            "id": c.get("id"), "label": c.get("label"),
            "enabled": bool(c.get("enabled")),
            "ics_url": str(c.get("ics_url") or "")[:80],
            "upcoming": len(cached),
            "notify_targets": c.get("notify_targets") or [],
            "notify_times": c.get("notify_times") or [],
            "notify_on_new": bool(c.get("notify_on_new")),
            "remind_before": c.get("remind_before") or [],
        })
    return {"running": _started, "enabled": is_enabled(),
            "calendars": rows, "count": len(rows)}


def _reset_for_tests() -> None:
    stop()
    with _lock:
        _cache.clear()
        _last_check.clear()
