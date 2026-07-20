# -*- coding: utf-8 -*-
"""Vietnamese lunar calendar — Hồ Ngọc Đức algorithm (public domain), ported
local so the gateway answers âm/dương-lịch questions accurately & instantly
without an MCP round-trip or the model guessing. Timezone fixed to +7 (VN).

Core: solar↔lunar conversion (any date) + can chi (day/month/year) + giờ
hoàng đạo (auspicious hours).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta

TZ = 7.0
CAN = ["Giáp", "Ất", "Bính", "Đinh", "Mậu", "Kỷ", "Canh", "Tân", "Nhâm", "Quý"]
CHI = ["Tý", "Sửu", "Dần", "Mão", "Thìn", "Tỵ", "Ngọ", "Mùi", "Thân", "Dậu", "Tuất", "Hợi"]
# Auspicious-hour bitmask (index = hour chi 0..11, 1 = hoàng đạo), keyed by dayChi % 6
# (pairs: Tý/Ngọ, Sửu/Mùi, Dần/Thân, Mão/Dậu, Thìn/Tuất, Tỵ/Hợi).
_HOANG_DAO = {
    0: "110100101100",  # Tý, Ngọ
    1: "001101001011",  # Sửu, Mùi
    2: "110011010010",  # Dần, Thân
    3: "101100110100",  # Mão, Dậu
    4: "001011001101",  # Thìn, Tuất
    5: "010010110011",  # Tỵ, Hợi
}


def _jd_from_date(dd: int, mm: int, yy: int) -> int:
    a = (14 - mm) // 12
    y = yy + 4800 - a
    m = mm + 12 * a - 3
    jd = dd + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    if jd < 2299161:
        jd = dd + (153 * m + 2) // 5 + 365 * y + y // 4 - 32083
    return jd


def _jd_to_date(jd: int) -> tuple[int, int, int]:
    if jd > 2299160:
        a = jd + 32044
        b = (4 * a + 3) // 146097
        c = a - (b * 146097) // 4
    else:
        b = 0
        c = jd + 32082
    d = (4 * c + 3) // 1461
    e = c - (1461 * d) // 4
    m = (5 * e + 2) // 153
    day = e - (153 * m + 2) // 5 + 1
    month = m + 3 - 12 * (m // 10)
    year = b * 100 + d - 4800 + m // 10
    return (day, month, year)


def _new_moon(k: int) -> float:
    T = k / 1236.85
    T2 = T * T
    T3 = T2 * T
    dr = math.pi / 180
    Jd1 = 2415020.75933 + 29.53058868 * k + 0.0001178 * T2 - 0.000000155 * T3
    Jd1 += 0.00033 * math.sin((166.56 + 132.87 * T - 0.009173 * T2) * dr)
    M = 359.2242 + 29.10535608 * k - 0.0000333 * T2 - 0.00000347 * T3
    Mpr = 306.0253 + 385.81691806 * k + 0.0107306 * T2 + 0.00001236 * T3
    F = 21.2964 + 390.67050646 * k - 0.0016528 * T2 - 0.00000239 * T3
    C1 = (0.1734 - 0.000393 * T) * math.sin(M * dr) + 0.0021 * math.sin(2 * dr * M)
    C1 = C1 - 0.4068 * math.sin(Mpr * dr) + 0.0161 * math.sin(dr * 2 * Mpr)
    C1 = C1 - 0.0004 * math.sin(dr * 3 * Mpr)
    C1 = C1 + 0.0104 * math.sin(dr * 2 * F) - 0.0051 * math.sin(dr * (M + Mpr))
    C1 = C1 - 0.0074 * math.sin(dr * (M - Mpr)) + 0.0004 * math.sin(dr * (2 * F + M))
    C1 = C1 - 0.0004 * math.sin(dr * (2 * F - M)) - 0.0006 * math.sin(dr * (2 * F + Mpr))
    C1 = C1 + 0.0010 * math.sin(dr * (2 * F - Mpr)) + 0.0005 * math.sin(dr * (2 * Mpr + M))
    if T < -11:
        deltat = 0.001 + 0.000839 * T + 0.0002261 * T2 - 0.00000845 * T3 - 0.000000081 * T * T3
    else:
        deltat = -0.000278 + 0.000265 * T + 0.000262 * T2
    return Jd1 + C1 - deltat


def _sun_longitude(jdn: float) -> float:
    T = (jdn - 2451545.0) / 36525
    T2 = T * T
    dr = math.pi / 180
    M = 357.52910 + 35999.05030 * T - 0.0001559 * T2 - 0.00000048 * T * T2
    L0 = 280.46645 + 36000.76983 * T + 0.0003032 * T2
    DL = (1.914600 - 0.004817 * T - 0.000014 * T2) * math.sin(dr * M)
    DL += (0.019993 - 0.000101 * T) * math.sin(dr * 2 * M) + 0.000290 * math.sin(dr * 3 * M)
    L = (L0 + DL) * dr
    L = L - math.pi * 2 * int(L / (math.pi * 2))
    return L


def _get_sun_longitude(day_number: float, tz: float) -> int:
    return int(_sun_longitude(day_number - 0.5 - tz / 24) / math.pi * 6)


def _get_new_moon_day(k: int, tz: float) -> int:
    return int(_new_moon(k) + 0.5 + tz / 24)


def _get_lunar_month_11(yy: int, tz: float) -> int:
    off = _jd_from_date(31, 12, yy) - 2415021
    k = int(off / 29.530588853)
    nm = _get_new_moon_day(k, tz)
    if _get_sun_longitude(nm, tz) >= 9:
        nm = _get_new_moon_day(k - 1, tz)
    return nm


def _get_leap_month_offset(a11: int, tz: float) -> int:
    k = int((a11 - 2415021.076998695) / 29.530588853 + 0.5)
    i = 1
    arc = _get_sun_longitude(_get_new_moon_day(k + i, tz), tz)
    while True:
        last = arc
        i += 1
        arc = _get_sun_longitude(_get_new_moon_day(k + i, tz), tz)
        if not (arc != last and i < 14):
            break
    return i - 1


def solar_to_lunar(dd: int, mm: int, yy: int, tz: float = TZ) -> tuple[int, int, int, int]:
    """(lunarDay, lunarMonth, lunarYear, isLeapMonth)."""
    day_number = _jd_from_date(dd, mm, yy)
    k = int((day_number - 2415021.076998695) / 29.530588853)
    month_start = _get_new_moon_day(k + 1, tz)
    if month_start > day_number:
        month_start = _get_new_moon_day(k, tz)
    a11 = _get_lunar_month_11(yy, tz)
    b11 = a11
    if a11 >= month_start:
        lunar_year = yy
        a11 = _get_lunar_month_11(yy - 1, tz)
    else:
        lunar_year = yy + 1
        b11 = _get_lunar_month_11(yy + 1, tz)
    lunar_day = day_number - month_start + 1
    diff = int((month_start - a11) / 29)
    lunar_leap = 0
    lunar_month = diff + 11
    if b11 - a11 > 365:
        leap_diff = _get_leap_month_offset(a11, tz)
        if diff >= leap_diff:
            lunar_month = diff + 10
            if diff == leap_diff:
                lunar_leap = 1
    if lunar_month > 12:
        lunar_month -= 12
    if lunar_month >= 11 and diff < 4:
        lunar_year -= 1
    return (lunar_day, lunar_month, lunar_year, lunar_leap)


def lunar_to_solar(lunar_day: int, lunar_month: int, lunar_year: int,
                   lunar_leap: int = 0, tz: float = TZ) -> tuple[int, int, int]:
    """(dd, mm, yy) — (0,0,0) if the lunar date is invalid."""
    if lunar_month < 11:
        a11 = _get_lunar_month_11(lunar_year - 1, tz)
        b11 = _get_lunar_month_11(lunar_year, tz)
    else:
        a11 = _get_lunar_month_11(lunar_year, tz)
        b11 = _get_lunar_month_11(lunar_year + 1, tz)
    k = int(0.5 + (a11 - 2415021.076998695) / 29.530588853)
    off = lunar_month - 11
    if off < 0:
        off += 12
    if b11 - a11 > 365:
        leap_off = _get_leap_month_offset(a11, tz)
        leap_month = leap_off - 2
        if leap_month < 0:
            leap_month += 12
        if lunar_leap != 0 and lunar_month != leap_month:
            return (0, 0, 0)
        elif lunar_leap != 0 or off >= leap_off:
            off += 1
    month_start = _get_new_moon_day(k + off, tz)
    return _jd_to_date(month_start + lunar_day - 1)


def _can_chi_day(dd: int, mm: int, yy: int) -> str:
    jd = _jd_from_date(dd, mm, yy)
    return f"{CAN[(jd + 9) % 10]} {CHI[(jd + 1) % 12]}"


def _can_chi_year(lunar_year: int) -> str:
    return f"{CAN[(lunar_year + 6) % 10]} {CHI[(lunar_year + 8) % 12]}"


def _can_chi_month(lunar_month: int, lunar_year: int) -> str:
    return f"{CAN[(lunar_year * 12 + lunar_month + 3) % 10]} {CHI[(lunar_month + 1) % 12]}"


def hoang_dao_hours(dd: int, mm: int, yy: int) -> list[str]:
    jd = _jd_from_date(dd, mm, yy)
    mask = _HOANG_DAO[(jd + 1) % 12 % 6]
    out = []
    for i, c in enumerate(mask):
        if c == "1":
            start = (23 + 2 * i) % 24
            end = (start + 2) % 24
            out.append(f"{CHI[i]} ({start:02d}h-{end:02d}h)")
    return out


# Thập nhị trực (12 Directs) + standard việc nên làm / nên tránh.
_TRUC = ["Kiến", "Trừ", "Mãn", "Bình", "Định", "Chấp",
         "Phá", "Nguy", "Thành", "Thu", "Khai", "Bế"]
_TRUC_VIEC = {
    "Kiến":  ("xuất hành, nhậm chức, cưới hỏi, khai trương", "động thổ, đào giếng, an táng"),
    "Trừ":   ("chữa bệnh, cúng tế, dọn dẹp, trừ tà", "cưới hỏi, xuất hành xa, khai trương"),
    "Mãn":   ("cầu tài, khai trương, tế tự, mở kho", "nhậm chức, kiện tụng, an táng, uống thuốc"),
    "Bình":  ("cưới hỏi, làm đường, san nền, lợp nhà", "động thổ, đào ao, kiện tụng"),
    "Định":  ("cưới hỏi, nhập học, khai trương, ký kết", "kiện tụng, xuất hành, tranh chấp"),
    "Chấp":  ("tạo tác, cưới hỏi, xây dựng", "xuất hành, di dời, mở kho"),
    "Phá":   ("chữa bệnh, phá dỡ nhà cũ", "cưới hỏi, khai trương, ký kết, việc lớn"),
    "Nguy":  ("tế tự, cầu an", "leo cao, đi xa, lên thuyền, mạo hiểm"),
    "Thành": ("khai trương, cưới hỏi, nhập học, xuất hành (đa số việc tốt)", "kiện tụng, tranh chấp"),
    "Thu":   ("thu hoạch, cầu tài, nhập kho, mua sắm", "an táng, xuất hành xa, khởi sự lớn"),
    "Khai":  ("khai trương, cưới hỏi, nhập học, động thổ, xuất hành", "an táng, đào huyệt"),
    "Bế":    ("đắp đê, lấp hố, an táng, củng cố", "khai trương, xuất hành, chữa mắt, khởi sự"),
}


def truc_of_day(dd: int, mm: int, yy: int) -> str:
    """Thập nhị trực of a day = (dayChi − tiết-khí-month branch) mod 12, Kiến=0.
    The month branch comes from the sun's longitude (Lập Xuân 315° = Dần)."""
    jd = _jd_from_date(dd, mm, yy)
    day_chi = (jd + 1) % 12
    deg = _sun_longitude(jd - 0.5 - TZ / 24) * 180.0 / math.pi
    month_branch = (2 + int(((deg - 315) % 360) / 30)) % 12  # 315°=Dần(2)
    return _TRUC[(day_chi - month_branch + 12) % 12]


# 24 tiết khí theo kinh độ mặt trời (0° = Xuân phân, mỗi tiết 15°).
_TIETKHI = ["Xuân phân", "Thanh minh", "Cốc vũ", "Lập hạ", "Tiểu mãn", "Mang chủng",
            "Hạ chí", "Tiểu thử", "Đại thử", "Lập thu", "Xử thử", "Bạch lộ",
            "Thu phân", "Hàn lộ", "Sương giáng", "Lập đông", "Tiểu tuyết", "Đại tuyết",
            "Đông chí", "Tiểu hàn", "Đại hàn", "Lập xuân", "Vũ thủy", "Kinh trập"]


def tiet_khi(dd: int, mm: int, yy: int) -> str:
    """Tiết khí hiện hành của ngày (theo kinh độ mặt trời)."""
    jd = _jd_from_date(dd, mm, yy)
    deg = _sun_longitude(jd - 0.5 - TZ / 24) * 180.0 / math.pi
    return _TIETKHI[int(deg / 15) % 24]


def _hd_chi(dd: int, mm: int, yy: int) -> str:
    """Giờ hoàng đạo đọc xuôi kèm KHUNG GIỜ: 'giờ Dần từ 3 đến 5 giờ, ... và ...'."""
    jd = _jd_from_date(dd, mm, yy)
    mask = _HOANG_DAO[(jd + 1) % 12 % 6]
    parts = []
    for i, c in enumerate(mask):
        if c == "1":
            start = (23 + 2 * i) % 24
            end = (start + 2) % 24
            parts.append(f"giờ {CHI[i]} từ {start} đến {end} giờ")
    if len(parts) > 1:
        return ", ".join(parts[:-1]) + " và " + parts[-1]
    return ", ".join(parts)


def describe_activities(dd: int, mm: int, yy: int) -> str:
    """Việc nên làm / nên tránh (theo thập nhị trực) + giờ hoàng đạo — đọc xuôi."""
    truc = truc_of_day(dd, mm, yy)
    nen, ky = _TRUC_VIEC.get(truc, ("", ""))
    s = f"Ngày {_can_chi_day(dd, mm, yy)}, trực {truc}."
    if nen and ky:
        s += f" Nên {nen}; nên tránh {ky}."
    return s + " Giờ hoàng đạo trong ngày gồm " + _hd_chi(dd, mm, yy) + "."


def _today_vn() -> tuple[int, int, int]:
    now = datetime.now(timezone(timedelta(hours=TZ)))
    return (now.day, now.month, now.year)


def _lunar_str(ld: int, lm: int, ly: int, leap: int) -> str:
    leap_s = " (nhuận)" if leap else ""
    return f"ngày {ld} tháng {lm}{leap_s} năm {_can_chi_year(ly)}"


def _day_detail(dd: int, mm: int, yy: int, with_hours: bool = True) -> str:
    """Chi tiết 1 ngày dạng ĐỌC XUÔI (không ký tự lạ): can chi, tiết khí, trực +
    nên/kỵ, giờ hoàng đạo."""
    ld, lm, ly, leap = solar_to_lunar(dd, mm, yy)
    truc = truc_of_day(dd, mm, yy)
    nen, ky = _TRUC_VIEC.get(truc, ("", ""))
    s = (f"Ngày {_can_chi_day(dd, mm, yy)}, tháng {_can_chi_month(lm, ly)}, "
         f"năm {_can_chi_year(ly)}, đang tiết {tiet_khi(dd, mm, yy)}, trực {truc}.")
    if nen and ky:
        s += f" Nên {nen}; nên tránh {ky}."
    if with_hours:
        s += " Giờ hoàng đạo trong ngày gồm " + _hd_chi(dd, mm, yy) + "."
    return s


def _weekday_vn(dd: int, mm: int, yy: int) -> str:
    """Thứ trong tuần (tiếng Việt) của một ngày dương lịch."""
    import datetime
    wd = datetime.date(yy, mm, dd).weekday()  # 0 = Thứ Hai
    return ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"][wd]


def describe_solar(dd: int, mm: int, yy: int, with_hours: bool = True) -> str:
    """Mô tả âm lịch của một ngày dương — đọc xuôi cho giọng nói."""
    ld, lm, ly, leap = solar_to_lunar(dd, mm, yy)
    leap_s = " nhuận" if leap else ""
    return (f"{_weekday_vn(dd, mm, yy)}, ngày {dd} tháng {mm} năm {yy} dương lịch, "
            f"nhằm ngày {ld} tháng {lm}{leap_s} năm {_can_chi_year(ly)} âm lịch. "
            + _day_detail(dd, mm, yy, with_hours))


def describe_today() -> str:
    dd, mm, yy = _today_vn()
    return "Hôm nay là " + describe_solar(dd, mm, yy)


def describe_lunar(ld: int, lm: int, ly: int, leap: int = 0) -> str:
    """Mô tả ngày âm lịch → dương lịch (kèm chi tiết) — đọc xuôi."""
    dd, mm, yy = lunar_to_solar(ld, lm, ly, leap)
    if (dd, mm, yy) == (0, 0, 0):
        return f"Âm lịch ngày {ld} tháng {lm} năm {_can_chi_year(ly)} không hợp lệ."
    leap_s = " nhuận" if leap else ""
    return (f"Âm lịch ngày {ld} tháng {lm}{leap_s} năm {_can_chi_year(ly)} nhằm "
            f"ngày {dd} tháng {mm} năm {yy} dương lịch. " + _day_detail(dd, mm, yy))
