"""Deterministic Zalo Personal admin commands that target another thread.

The normal ``schedule`` capability creates a reminder for the conversation
currently speaking to the bot.  An admin command such as ``nhắc ... thread ID
123`` has a different, explicit destination.  Letting a language model infer
that destination made the command susceptible to unrelated Home Assistant
context (for example, an electricity-meter status) and it could answer a daily
summary instead of scheduling anything.

Only the Zalo Personal ingress calls this module *after* authenticating the
sender as an admin.  It deliberately handles a narrow, unambiguous grammar;
anything without ``thread ID`` remains normal conversation.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from services.agent import reminders as rem
from services.agent.vi_text import fold


_RE_THREAD_ID = re.compile(r"\bthread\s*id\s*[:#-]?\s*(\d{6,})\b", re.IGNORECASE)
_RE_MONTHLY_DAY = re.compile(r"\b(?:mung|ngay)\s*(\d{1,2})\s+hang\s+thang\b")
_RE_CONTENT = re.compile(r"\b(?:nội\s+dung|noi\s+dung)\s*[:=-]?\s*(.+)$", re.IGNORECASE)
_RE_CONTENT_HEAD = re.compile(r"\b(?:nội\s+dung|noi\s+dung)\b", re.IGNORECASE)
_RE_TIME = re.compile(
    r"(?<!\d)([01]?\d|2[0-3])\s*(?:"
    r":\s*(\d{1,2})|h(?![a-z])\s*(\d{1,2})?|gio\s*(\d{1,2})?"
    r")",
)


def _times_in(text: str) -> list[str]:
    """Return canonical, sorted clock times explicitly written in ``text``."""
    found: list[tuple[int, int]] = []
    for match in _RE_TIME.finditer(fold(text)):
        hour = int(match.group(1))
        minute = int(next((g for g in match.groups()[1:] if g is not None), "0"))
        if 0 <= hour <= 23 and 0 <= minute <= 59 and (hour, minute) not in found:
            found.append((hour, minute))
    return [f"{hour:02d}:{minute:02d}" for hour, minute in sorted(found)]


def _content_in(text: str) -> str:
    match = _RE_CONTENT.search(text)
    return (match.group(1).strip(" \t:;,-") if match else "")


def _thread_type_of(account_id: str, thread_id: str) -> tuple[int, str]:
    """(thread_type, nhãn) của thread ĐÍCH, tra trong danh bạ kênh.

    Tới giờ nhắc, `_send` gửi bằng đúng `meta['thread_type']` này. Đóng đinh 0
    như bản đầu thì mọi lịch đặt cho một NHÓM đều gửi sai loại thread — mà hỏng
    kiểu đó chỉ lộ ra vào mùng 1 tháng sau, lúc không ai còn nhớ câu lệnh.

    Thread chưa có trong danh bạ thì vẫn đặt lịch (coi là chat cá nhân) nhưng
    NÓI RÕ trong câu xác nhận, để admin sửa ngay thay vì chờ tới lúc nó bắn.
    """
    try:
        from services import channel_contacts as cc
        rec = cc.get(cc.contact_key("zalop", str(account_id or ""),
                                    str(thread_id or ""))) or {}
    except Exception:
        rec = {}
    kind = str(rec.get("kind") or "")
    if kind == "group":
        return 1, "nhóm"
    if kind:
        return 0, "chat cá nhân"
    return 0, "chat cá nhân — thread này chưa có trong danh bạ, nếu là NHÓM thì báo em đặt lại"


def _target_name(text: str, thread_match: re.Match[str]) -> str:
    before = text[:thread_match.start()]
    name = re.sub(r"^\s*nh[ắa]c\s+", "", before, flags=re.IGNORECASE).strip()
    return name or "thread đích"


def _rrule_of(row: dict[str, Any]) -> dict[str, Any] | None:
    try:
        parsed = json.loads(str(row.get("rrule") or ""))
        return parsed if isinstance(parsed, dict) else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _same_text(left: str, right: str) -> bool:
    return " ".join(fold(left).split()) == " ".join(fold(right).split())


def _matching_monthly_rows(user_id: str, text: str, day: int,
                           times: list[str]) -> tuple[list[dict[str, Any]],
                                                        list[dict[str, Any]]]:
    """Return (identical, stale-one-slot) existing schedules for replacement."""
    expected = [(int(t[:2]), int(t[3:])) for t in times]
    identical: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    for row in rem.list_for(user_id):
        if not _same_text(str(row.get("text") or ""), text):
            continue
        spec = _rrule_of(row)
        if not spec or str(spec.get("unit") or "") != "month":
            continue
        if int(spec.get("day") or 0) != day:
            continue
        slots = rem.lich_lap.cac_moc_gio(spec)
        if slots == expected:
            identical.append(row)
        elif len(slots) == 1:
            stale.append(row)
    return identical, stale


def handle_zalop_admin_reminder(text: str, *, account_id: str,
                                 now: dt.datetime | None = None) -> str | None:
    """Create a monthly multi-time reminder for the explicit Zalo thread.

    Return ``None`` when the message is not this command form, so normal agent
    conversation retains ownership.  A recognized but incomplete command gets
    a precise question rather than a guessed schedule.
    """
    raw = str(text or "").strip()
    folded = fold(raw)
    if not re.search(r"\bnhac\b", folded):
        return None
    # Câu HỎI về lịch ("xem lịch nhắc của thread ID …", "huỷ lịch nhắc thread
    # ID …") cũng có đủ chữ «nhắc» và «thread ID», nhưng nhánh này chỉ biết TẠO.
    # Không nhường lại thì admin hỏi xem lịch sẽ nhận câu "cần nói rõ ngày lặp
    # hàng tháng" — vô nghĩa, mà lại chặn mất đường xem/huỷ đang chạy được.
    if re.search(r"\b(xem|liet ke|danh sach|huy|bo|xoa|con lich nao)\b", folded):
        return None
    thread_match = _RE_THREAD_ID.search(raw)
    if not thread_match:
        return None

    target_thread_id = thread_match.group(1)
    monthly = _RE_MONTHLY_DAY.search(folded)
    content = _content_in(raw)
    # Giờ đọc từ phần TRƯỚC cụm «nội dung», kẻo giờ nằm trong chính nội dung
    # ("nội dung: gọi khách lúc 8h") bị đếm thành một mốc nhắc. Không thấy mốc
    # nào ở đó thì mới quét cả câu — người dùng có thể viết ngược thứ tự.
    head = _RE_CONTENT_HEAD.split(raw, maxsplit=1)[0]
    times = _times_in(head) or _times_in(raw)
    target_name = _target_name(raw, thread_match)
    if not monthly:
        return (f"Em đã nhận thread ID {target_thread_id} ({target_name}), nhưng cần "
                "nói rõ ngày lặp hàng tháng, ví dụ: mùng 1 hàng tháng.")
    day = int(monthly.group(1))
    if not 1 <= day <= 31:
        return f"Ngày {day} không hợp lệ; ngày trong tháng phải từ 1 đến 31 ạ."
    if not times:
        return (f"Em đã nhận thread ID {target_thread_id} ({target_name}), nhưng thiếu "
                "giờ nhắc. Ví dụ: vào 10h, 15h và 21h.")
    if not content:
        return (f"Em đã nhận thread ID {target_thread_id} ({target_name}), nhưng thiếu "
                "nội dung sau cụm «nội dung …» ạ.")

    now = now or rem._now_vn()
    schedule = rem.parse_when(
        "", unit="month", day_of_month=day, at_times=times, now=now,
    )
    if not schedule or schedule.get("kind") != "recur":
        return "Em chưa tạo được lịch do thời điểm chưa hợp lệ; anh/chị kiểm tra lại giờ ạ."

    user_id = f"zalop_{target_thread_id}"
    identical, stale = _matching_monthly_rows(user_id, content, day, times)
    if identical:
        row = identical[0]
        return (f"Lịch cho {target_name} (thread ID {target_thread_id}) đã đúng rồi: "
                f"ngày {day} hằng tháng lúc {', '.join(times)} — mã {row['id']}. "
                "Em không tạo thêm lịch trùng.")

    thread_type, thread_label = _thread_type_of(account_id, target_thread_id)
    try:
        row = rem.create(
            user_id, content, schedule,
            meta_extra={"account": str(account_id or ""),
                        "thread_type": thread_type},
        )
    except Exception as exc:
        return f"Không đặt được lịch cho thread ID {target_thread_id}: {str(exc)[:150]}"

    # The new schedule exists before disabling the known incomplete one.  This
    # makes a transient database failure prefer a duplicate over losing a
    # reminder altogether.
    replaced = [old["id"] for old in stale if rem.cancel(user_id, str(old["id"]))]
    suffix = (f" Đã thay lịch một-mốc cũ: {', '.join(replaced)}."
              if replaced else "")
    return (f"Đã đặt nhắc cho {target_name} (thread ID {target_thread_id}, "
            f"{thread_label}): ngày {day} hằng tháng lúc {', '.join(times)}, "
            f"nội dung «{content}» — mã {row['id']}.{suffix}")
