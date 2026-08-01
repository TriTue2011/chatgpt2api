"""Tính LẦN KẾ TIẾP của một lịch lặp — thuần datetime, không đụng DB.

Tách riêng khỏi `reminders.py` để kiểm được độc lập (không cần SQLite/config), và
để một chỗ duy nhất định nghĩa ngữ nghĩa lặp.

Đơn vị hỗ trợ: second, minute, hour, day, week, month, year.
  * Dưới một ngày (second/minute/hour): cộng khoảng đều, KHÔNG xét thứ/ngày nghỉ
    (nhắc mỗi 30 giây mà né lễ thì vô nghĩa).
  * day/week: bắn lúc hh:mm vào các ngày khớp bộ lọc thứ (`weekdays`) — hoặc mọi
    ngày nếu không lọc — với chu kỳ `n`. Bỏ ngày nghỉ nếu `skip` yêu cầu.
  * month/year: bắn lúc hh:mm vào đúng ngày trong tháng / tháng-ngày trong năm,
    chu kỳ `n`; ngày rơi vào lễ thì đẩy sang ngày kế không nghỉ.

`spec` (dict):
  n:int=1, unit:str, hour:int, minute:int,
  weekdays:list[int]|None  (0=Thứ Hai … 6=Chủ Nhật),
  day:int|None             (ngày trong tháng, cho month/year),
  month:int|None           (tháng, cho year),
  skip:list[str]|None      ("le"/"tet"/"bu"),
  anchor:str|None          ("YYYY-MM-DD" — mốc tính chu kỳ n; mặc định hôm tạo).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from services import le_tet_vn as _le

_GIAY = {"second": 1, "minute": 60, "hour": 3600}
UNITS = ("second", "minute", "hour", "day", "week", "month", "year")
_MAX_NGAY = 366 * 5      # trần dò tới, chống lặp vô hạn khi bộ lọc quá hẹp


def _anchor(spec: dict[str, Any], mac_dinh: _dt.date) -> _dt.date:
    s = str(spec.get("anchor") or "").strip()
    if s:
        try:
            return _dt.date.fromisoformat(s[:10])
        except ValueError:
            pass
    return mac_dinh


def _skip_set(spec: dict[str, Any]) -> frozenset[str]:
    return frozenset(str(x) for x in (spec.get("skip") or []))


def _add_months(d: _dt.date, months: int) -> _dt.date:
    """Cộng tháng, kẹp ngày về cuối tháng nếu tràn (31/1 + 1 tháng → 28/2)."""
    thang0 = d.month - 1 + months
    nam = d.year + thang0 // 12
    thang = thang0 % 12 + 1
    # ngày cuối của tháng đích
    if thang == 12:
        cuoi = 31
    else:
        cuoi = (_dt.date(nam, thang + 1, 1) - _dt.timedelta(days=1)).day
    return _dt.date(nam, thang, min(d.day, cuoi))


def next_run(spec: dict[str, Any], after: _dt.datetime,
             tz: Optional[_dt.tzinfo] = None) -> Optional[_dt.datetime]:
    """Lần bắn kế tiếp SAU `after` (đúng nghiêm ngặt). None nếu không tính được."""
    tz = tz or after.tzinfo
    unit = str(spec.get("unit") or "day").lower()
    if unit not in UNITS:
        return None
    n = max(1, int(spec.get("n") or 1))

    if unit in _GIAY:
        return after + _dt.timedelta(seconds=n * _GIAY[unit])

    hour = int(spec.get("hour") or 0)
    minute = int(spec.get("minute") or 0)
    skip = _skip_set(spec)
    wds = spec.get("weekdays")
    wdset = {int(w) for w in wds} if wds else None
    anchor = _anchor(spec, after.date())

    def tao(d: _dt.date) -> _dt.datetime:
        return _dt.datetime(d.year, d.month, d.day, hour, minute, tzinfo=tz)

    def bi_nghi(d: _dt.date) -> bool:
        return bool(skip) and _le.la_ngay_nghi(d, skip)

    if unit in ("day", "week"):
        # Ngày đầu tiên có thể xét: hôm nay nếu giờ chưa qua, không thì mai.
        d = after.date()
        if tao(d) <= after:
            d = d + _dt.timedelta(days=1)
        for _ in range(_MAX_NGAY):
            hop = True
            if wdset is not None and d.weekday() not in wdset:
                hop = False
            elif unit == "week" and wdset is None and d.weekday() != anchor.weekday():
                hop = False           # tuần: không lọc thứ → theo thứ của mốc
            if hop and unit == "day" and (d - anchor).days % n != 0:
                hop = False
            if hop and unit == "week":
                tuan = ((d - anchor).days - (d.weekday() - anchor.weekday())) // 7
                if tuan % n != 0:
                    hop = False
            if hop and bi_nghi(d):
                hop = False
            if hop:
                return tao(d)
            d = d + _dt.timedelta(days=1)
        return None

    if unit in ("month", "year"):
        dom = int(spec.get("day") or anchor.day)
        thang_moc = int(spec.get("month") or anchor.month) if unit == "year" else None
        # điểm xuất phát: mốc, rồi nhảy theo chu kỳ tới khi vượt `after`
        if unit == "month":
            base = _dt.date(anchor.year, anchor.month, 1)
            buoc = lambda k: _add_months(base, k).replace(day=1)  # noqa: E731
        else:
            base = _dt.date(anchor.year, thang_moc or anchor.month, 1)
            buoc = lambda k: _dt.date(anchor.year + k * n, thang_moc or anchor.month, 1)  # noqa: E731
        k = 0
        for _ in range(_MAX_NGAY):
            if unit == "month":
                thang_dau = _add_months(base, k * n)
                cuoi = _add_months(thang_dau, 1) - _dt.timedelta(days=1)
                d = thang_dau.replace(day=min(dom, cuoi.day))
            else:
                thang_dau = buoc(k)
                cuoi = _add_months(thang_dau, 1) - _dt.timedelta(days=1)
                d = thang_dau.replace(day=min(dom, cuoi.day))
            # đẩy qua ngày nghỉ (giữ trong cùng tháng slot)
            dd = d
            for _ in range(15):
                if not bi_nghi(dd):
                    break
                dd = dd + _dt.timedelta(days=1)
            cand = tao(dd)
            if cand > after:
                return cand
            k += 1
        return None
    return None
