#!/usr/bin/env python3
"""Đo trên DỮ LIỆU THẬT xem tầng học nhà có đủ dữ liệu để học không.

Vì sao có tệp này: một bộ dò lỗi của dự án từng đạt 13/13 test mà bắt 0 ca
thật. Test chỉ chứng minh code chạy đúng như mình nghĩ, không chứng minh mình
nghĩ đúng. Bốn phép đo dưới đây chạy trên kho thật, chạy lại được bất cứ lúc
nào, và mỗi phép trả về một con số so được với lần trước.

Chạy trên máy chủ:
    python3 scripts/do_hoc_nha.py /opt/c2a/data/agent/lich_su_nha.sqlite
"""

from __future__ import annotations

import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=7))


def _mo(ts: float) -> str:
    return datetime.fromtimestamp(ts, TZ).strftime("%d/%m %H:%M")


def do_1_tran_cat_dung_dau(c: sqlite3.Connection) -> None:
    """Trần có cắt mất phần MỚI NHẤT không.

    Trước sửa: xin 14 ngày chỉ nhận về 13,9 giờ của ngày đầu tiên (mất 96,6%).
    """
    now = time.time()
    tu = now - 14 * 86400
    tong = c.execute("SELECT COUNT(*) FROM su_kien WHERE ts>=?", (tu,)).fetchone()[0]
    moi = c.execute("SELECT MAX(ts) FROM su_kien WHERE ts>=?", (tu,)).fetchone()[0]
    print(f"1. TRẦN CẮT ĐÚNG ĐẦU CHƯA")
    print(f"   14 ngày có {tong:,} sự kiện")
    if moi:
        print(f"   bản ghi mới nhất trong kho: {_mo(moi)}"
              f"  (cách bây giờ {(now - moi) / 60:.1f} phút)")
    print("   → đạt khi hàm đọc trả về đúng mốc này, lệch < 1 phút")


def do_2_dieu_kien_co_duoc_ghi(c: sqlite3.Connection) -> None:
    """Lux, nhiệt độ, độ ẩm có vào kho không — sơ đồ chủ máy cần chúng."""
    print("\n2. ĐIỀU KIỆN TRONG SƠ ĐỒ CÓ ĐƯỢC GHI KHÔNG")
    for ten, mau in (("lux", "%illuminance%"), ("nhiệt độ", "%temperature%"),
                     ("độ ẩm", "%humidity%")):
        r = c.execute(
            "SELECT COUNT(*) n, COUNT(DISTINCT thiet_bi) tb,"
            " MIN(o_5p)*300 a, MAX(o_5p)*300 b FROM so_do WHERE truong LIKE ?",
            (mau,)).fetchone()
        if r["n"]:
            ngay = (r["b"] - r["a"]) / 86400
            print(f"   {ten:9s} {r['n']:6,} bản ghi / {r['tb']} thiết bị"
                  f" / {ngay:.1f} ngày")
        else:
            print(f"   {ten:9s} KHÔNG CÓ — bộ lọc đang chặn")


def do_3_tra_nguoc_boi_canh(c: sqlite3.Connection, mau: int = 400) -> None:
    """Phép đo quyết định: lúc bật đèn thì có biết bối cảnh không.

    Hôm 10/09/2026 trước khi sửa: 0/400. Sau khi tích đủ dữ liệu phải > 60%,
    nếu không thì tầng xác suất chưa được bật.
    """
    now = time.time()
    tu = now - 7 * 86400
    bat = c.execute(
        "SELECT ts FROM su_kien WHERE ts>=? AND thiet_bi LIKE 'light.%'"
        " AND gia_tri IN ('on','ON','True') ORDER BY ts DESC LIMIT ?",
        (tu, mau)).fetchall()
    print(f"\n3. LÚC BẬT ĐÈN CÓ BIẾT BỐI CẢNH KHÔNG ({len(bat)} lần)")
    if not bat:
        print("   chưa có lần bật đèn nào trong 7 ngày")
        return
    co = {"lux": 0, "nhiệt độ": 0, "có người": 0}
    for r in bat:
        o = int(r["ts"] // 300)
        for ten, sql, tham in (
            ("lux", "SELECT 1 FROM so_do WHERE truong LIKE '%illuminance%'"
                    " AND o_5p<=? AND o_5p>=? LIMIT 1", (o, o - 6)),
            ("nhiệt độ", "SELECT 1 FROM so_do WHERE truong LIKE '%temperature%'"
                         " AND o_5p<=? AND o_5p>=? LIMIT 1", (o, o - 6)),
            ("có người", "SELECT 1 FROM su_kien WHERE ts<=? AND ts>=?"
                         " AND (truong LIKE '%occupancy%' OR truong='presence')"
                         " LIMIT 1", (r["ts"], r["ts"] - 900)),
        ):
            if c.execute(sql, tham).fetchone():
                co[ten] += 1
    for ten, n in co.items():
        print(f"   {ten:9s} {n:4d}/{len(bat)}  ({n / len(bat) * 100:5.1f}%)")
    print("   → cổng chặn: phải > 60% mới bật tầng xác suất")


def do_4_rac_cau_hinh(c: sqlite3.Connection) -> None:
    """Hằng số cấu hình có còn chiếm chỗ trong `so_do` không."""
    print("\n4. RÁC CẤU HÌNH TRONG KHO SỐ ĐO")
    try:
        r = c.execute(
            "SELECT loai, COUNT(*) n FROM nhip GROUP BY loai").fetchall()
        if not r:
            print("   bảng `nhip` rỗng — bản mới chưa chạy đủ lâu")
            return
        for x in r:
            print(f"   {str(x['loai']):9s} {x['n']:5d} trường")
    except sqlite3.OperationalError:
        print("   chưa có bảng `nhip` — máy chủ còn chạy bản cũ")
        return
    dung = c.execute(
        "SELECT COUNT(*) FROM so_do WHERE (thiet_bi, truong) IN"
        " (SELECT thiet_bi, truong FROM nhip WHERE loai='hang_so')").fetchone()[0]
    print(f"   còn {dung:,} dòng số đo thuộc về hằng số — nên tiến về 0")


def main() -> int:
    duong = sys.argv[1] if len(sys.argv) > 1 else "data/agent/lich_su_nha.sqlite"
    c = sqlite3.connect(f"file:{duong}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    print(f"Kho: {duong}")
    print(f"Lúc: {_mo(time.time())}\n")
    do_1_tran_cat_dung_dau(c)
    do_2_dieu_kien_co_duoc_ghi(c)
    do_3_tra_nguoc_boi_canh(c)
    do_4_rac_cau_hinh(c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
