"""Lịch nghỉ lễ – Tết chính thức của Việt Nam (dùng cho nhắc hẹn bỏ ngày nghỉ).

Nguồn quy tắc: Bộ luật Lao động 2019, Điều 112 — 11 ngày nghỉ lễ hưởng lương:
  * Tết Dương lịch: 1/1 (1 ngày)
  * Tết Âm lịch: 5 ngày (quanh mùng 1 tháng Giêng)
  * Giỗ Tổ Hùng Vương: 10/3 âm lịch (1 ngày)
  * Ngày Giải phóng miền Nam: 30/4 (1 ngày)
  * Quốc tế Lao động: 1/5 (1 ngày)
  * Quốc khánh: 2/9 và một ngày liền kề (2 ngày, từ 2021)

NGHỈ BÙ: khi một ngày lễ rơi vào Thứ Bảy/Chủ Nhật thì được nghỉ bù vào ngày làm
việc kế tiếp (Điều 111 Bộ luật Lao động). Đây cũng là NGÀY NGHỈ — nên với một
nhắc hẹn kiểu chấm công, bỏ luôn ngày nghỉ bù là đúng ý.

GIỚI HẠN cố ý nói rõ, không giấu:
  * Khoảng nghỉ Tết 5 ngày ở đây tính theo QUY TẮC (30/29 Chạp → mùng 4 Giêng).
    Chính phủ ra quyết định hoán đổi RIÊNG mỗi năm (có năm nghỉ 7–9 ngày do ghép
    cuối tuần), nên vài ngày rìa có thể lệch quyết định năm đó. Lõi mùng 1–3 luôn
    đúng.
  * KHÔNG mô hình "làm bù" (đi làm Thứ Bảy để nghỉ dài) — cái đó do quyết định
    từng năm, không suy ra được bằng thuật toán. Ai cần chính xác 100% phải nạp
    lịch quyết định của năm.

Chỉ dùng `services.lunar_vn` (thuật toán Hồ Ngọc Đức) để đổi âm→dương, không thêm
phụ thuộc ngoài.
"""
from __future__ import annotations

import datetime as _dt
from functools import lru_cache

from services import lunar_vn

# Nhãn danh mục để lời dặn "trừ lễ / trừ tết / trừ nghỉ bù" ánh xạ vào.
LE = "le"        # lễ dương lịch cố định + Giỗ Tổ
TET = "tet"      # Tết Âm lịch
BU = "bu"        # nghỉ bù (lễ rơi vào cuối tuần)


def _le_duong(year: int) -> list[tuple[_dt.date, str]]:
    """Ngày lễ theo DƯƠNG lịch cố định (chưa tính nghỉ bù)."""
    d = _dt.date
    return [
        (d(year, 1, 1), "Tết Dương lịch"),
        (d(year, 4, 30), "Giải phóng miền Nam"),
        (d(year, 5, 1), "Quốc tế Lao động"),
        (d(year, 9, 2), "Quốc khánh"),
        (d(year, 9, 1), "Quốc khánh (nghỉ liền kề)"),
    ]


def _tet_am(year: int) -> list[tuple[_dt.date, str]]:
    """5 ngày Tết Âm lịch của NĂM DƯƠNG `year`: Giao thừa (30/29 Chạp) → mùng 4.

    Mùng 1 tháng Giêng của năm âm rơi trong `year` dương — đổi lunar (1,1,year)
    sang dương rồi lấy từ hôm trước (giao thừa) tới +3 (mùng 4). Tổng 5 ngày,
    đúng số ngày luật định.
    """
    dd, mm, yy = lunar_vn.lunar_to_solar(1, 1, year)
    if (dd, mm, yy) == (0, 0, 0):
        return []
    mung1 = _dt.date(yy, mm, dd)
    ra: list[tuple[_dt.date, str]] = []
    for off in range(-1, 4):            # -1 = giao thừa … +3 = mùng 4
        ngay = mung1 + _dt.timedelta(days=off)
        ten = "Giao thừa" if off == -1 else f"Mùng {off + 1} Tết"
        ra.append((ngay, ten))
    return ra


def _gio_to(year: int) -> list[tuple[_dt.date, str]]:
    """Giỗ Tổ Hùng Vương — 10/3 âm lịch, đổi sang dương của `year`."""
    dd, mm, yy = lunar_vn.lunar_to_solar(10, 3, year)
    if (dd, mm, yy) == (0, 0, 0) or yy != year:
        return []
    return [(_dt.date(yy, mm, dd), "Giỗ Tổ Hùng Vương")]


@lru_cache(maxsize=64)
def _nghi_theo_nam(year: int) -> dict[_dt.date, tuple[str, str]]:
    """{ngày: (danh_mục, tên)} cho một năm dương, ĐÃ tính nghỉ bù.

    Nghỉ bù: mỗi ngày lễ rơi vào T7/CN đẩy sang ngày làm việc kế chưa bị chiếm.
    Tết đã gồm cả cuối tuần trong 5 ngày nên KHÔNG cộng bù cho Tết (đúng thực tế:
    Tết nghỉ trọn khối, không nghỉ bù thêm từng ngày).
    """
    goc: list[tuple[_dt.date, str, str]] = []
    for ngay, ten in _le_duong(year) + _gio_to(year):
        goc.append((ngay, LE, ten))
    for ngay, ten in _tet_am(year):
        goc.append((ngay, TET, ten))

    ra: dict[_dt.date, tuple[str, str]] = {}
    for ngay, dm, ten in goc:
        ra[ngay] = (dm, ten)

    # Nghỉ bù CHỈ cho lễ dương/Giỗ Tổ rơi vào cuối tuần.
    for ngay, dm, ten in goc:
        if dm != LE or ngay.weekday() < 5:
            continue
        bu = ngay + _dt.timedelta(days=1)
        while bu.weekday() >= 5 or bu in ra:   # nhảy qua cuối tuần / ngày đã nghỉ
            bu += _dt.timedelta(days=1)
        ra[bu] = (BU, f"Nghỉ bù {ten}")
    return ra


def la_ngay_nghi(ngay: _dt.date, cac_loai: frozenset[str] | set[str] | None = None) -> bool:
    """Ngày này có phải ngày nghỉ thuộc các danh mục yêu cầu không.

    `cac_loai` = tập con của {LE, TET, BU}. None/rỗng = xét cả ba.
    """
    thong_tin = _nghi_theo_nam(ngay.year).get(ngay)
    if not thong_tin:
        return False
    if not cac_loai:
        return True
    return thong_tin[0] in cac_loai


def ten_ngay_nghi(ngay: _dt.date) -> str:
    """Tên ngày nghỉ (rỗng nếu không phải ngày nghỉ)."""
    tt = _nghi_theo_nam(ngay.year).get(ngay)
    return tt[1] if tt else ""


def cac_ngay_nghi(year: int) -> list[tuple[_dt.date, str, str]]:
    """Danh sách (ngày, danh_mục, tên) trong năm — đã sắp theo ngày."""
    return sorted((d, dm, ten) for d, (dm, ten) in _nghi_theo_nam(year).items())
