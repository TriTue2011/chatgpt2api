"""Cảm biến KẸT theo từng NGÀY — tầng học bỏ những ngày đó (coi là «không biết», không phải «có người»).

Chủ máy 02/10/2026: "tầng học tự bỏ những quãng cảm biến kẹt (giá trị đứng im hàng giờ mà vẫn báo có người), rồi
cho bot học lại". Đo cùng ngày qua lịch sử thô HA: radar phòng học báo «có người» 99–100% mỗi ngày từ 22/09 tới
29/09, khoảng cách đứng im 126 cm — kể cả 2–5 giờ sáng và giờ cả nhà vắng; từ 01/10 về 14–18%. Kho lịch sử của
bot: cảm biến chuyển động ban công kẹt 6 ngày, phòng khách 1 ngày trong 30.

Ngưỡng là ngưỡng «kẹt» SẴN CÓ (`co_nguoi_nha._KET`, `vung_khoang_cach.KET` = 0,98) — trước đây chỉ xét trên CẢ
cửa sổ học, nên cảm biến kẹt 8 ngày trong 30 vẫn lọt. Nay xét từng ngày (giờ địa phương). Chỉ áp cho chuỗi
bật/tắt (on/off); số đo không đụng.
"""

from __future__ import annotations

from datetime import datetime, timedelta

KET = 0.98
_BAT_TAT = frozenset({"on", "off"})


def _dau_ngay(t: float) -> float:
    d = datetime.fromtimestamp(t)
    return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _ngay_sau(t: float) -> float:
    return (datetime.fromtimestamp(t) + timedelta(days=1, hours=2)).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp()


def ngay_ket(ts: list[float], gt: list[str | None], tu: float, den: float) -> list[tuple[float, float]]:
    """[(đầu ngày, cuối ngày)] những ngày TRỌN trong [tu, den] mà chuỗi báo «on» ≥ KET thời gian."""
    if not ts or not any(str(g).lower() in _BAT_TAT for g in gt):
        return []
    ra: list[tuple[float, float]] = []
    a = _ngay_sau(tu - 1) if _dau_ngay(tu) < tu else _dau_ngay(tu)
    i = 0
    cur: str | None = None
    while i < len(ts) and ts[i] <= a:
        cur = str(gt[i]).lower() if gt[i] is not None else None
        i += 1
    while True:
        b = _ngay_sau(a)
        if b > den:
            return ra
        on, last = 0.0, a
        while i < len(ts) and ts[i] < b:
            if cur == "on":
                on += ts[i] - last
            last, cur = ts[i], (str(gt[i]).lower() if gt[i] is not None else None)
            i += 1
        if cur == "on":
            on += b - last
        if on >= KET * (b - a):
            ra.append((a, b))
        a = b


def bo_ket(ts: list[float], gt: list[str | None], tu: float, den: float) -> tuple[list[float], list[str | None]]:
    """Trong quãng kẹt (các ngày kẹt liền nhau gộp lại): một mốc ``None`` ở đầu quãng, bỏ mọi mốc trong quãng, rồi trả
    giá trị THẬT gần nhất ở cuối quãng — sau quãng kẹt chuỗi lại như cũ."""
    quang: list[list[float]] = []
    for a, b in ngay_ket(ts, gt, tu, den):
        if quang and quang[-1][1] == a:
            quang[-1][1] = b
        else:
            quang.append([a, b])
    if not quang:
        return ts, gt
    ra: list[tuple[float, str | None]] = []
    j, cuoi = 0, None
    for t, g in zip(ts, gt):
        while j < len(quang) and t >= quang[j][1]:
            ra += [(quang[j][0], None), (quang[j][1], cuoi)]
            j += 1
        cuoi = g
        if j < len(quang) and quang[j][0] <= t < quang[j][1]:
            continue
        ra.append((t, g))
    for a, b in quang[j:]:
        ra += [(a, None), (b, cuoi)]
    ra.sort(key=lambda x: x[0])
    return [t for t, _ in ra], [g for _, g in ra]
