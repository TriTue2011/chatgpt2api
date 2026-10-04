"""ĐỘ TIN của cảm biến — đo trên lịch sử THẬT để biết cảm biến nào đáng tin cho việc học và điều khiển.

Chủ máy 04/10/2026: "giữ 1 trạng thái mà tự dưng thay đổi … lịch sử có thay đổi mà tự dưng giữ 1 trạng thái là lỗi …
nhiều cảm biến thay đổi liên tục cũng có thể là lỗi setting … căn cứ thời gian thay đổi liên tục và thời gian ở lâu
nhất khi có người để đánh giá bật/tắt thật". Tầng 1 của việc đó: ĐO và DÁN NHÃN; lọc mềm (tầng 2) và báo lỗi
(`canh_bao_nha`, tầng 3) dùng lại số ở đây.

Đo 04/10/2026 trên dữ liệu thật: cảm biến phòng khách/bếp đổi 600–950 lần/ngày, 42–57% lần ở dưới 10 giây (nhiễu);
phòng ngủ 40 lần/ngày, 3% — lành. Khoảng cách phòng khách chạm 0 ở 81% ô 5 phút. Nên ngưỡng dưới đây bắt được cả hai
thái cực mà không dán nhầm cảm biến lành.

Nhãn: ``lanh`` (dùng thẳng), ``nhieu`` (đặt quá nhạy — lọc mềm + báo), ``ket`` (đứng im bất thường — báo),
``it_du_lieu`` (chưa đủ để nói).
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any

from utils.log import logger

#: Một lần ở dưới ngần này giây coi là NHIỄU (người thật không ra-vào trong 10 giây).
NGAN_GIAY = 10.0
#: «Nhiễu»: phần lớn lần đổi là chớp nhoáng. Phòng ngủ lành = 3%; phòng khách nhiễu = 42–57%.
NHIEU_TL = 0.25
#: … và đổi đủ dày (cảm biến cửa đổi 29 lần/ngày, 16% ngắn — không phải nhiễu, chỉ là bản chất đóng/mở).
NHIEU_DOI_NGAY = 150.0
#: «Kẹt»: 7 ngày từng đổi ngần này lần nhưng 24 giờ qua đứng im. 24h là góc nhìn chủ máy chốt.
KET_DOI_7NGAY = 50
KET_IM_GIAY = 86400.0
#: Khoảng cách radar: chạm 0 (mất mục tiêu) quá nhiều ô = tín hiệu giật, ngưỡng khoảng cách kém tin.
KC_0_TL = 0.6


def _db() -> sqlite3.Connection | None:
    from services import lich_su_nha
    try:
        return sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    except sqlite3.Error:
        return None


def _chuoi(ro: sqlite3.Connection, ma: str, tu: float) -> list[tuple[float, str]]:
    return [(float(t), str(g)) for t, g in ro.execute(
        "SELECT ts, gia_tri FROM su_kien WHERE thiet_bi=? AND truong='state' AND ts>? ORDER BY ts", (ma, tu))]


def _dwell(ev: list[tuple[float, str]]) -> dict[str, list[float]]:
    d: dict[str, list[float]] = {}
    for i in range(len(ev) - 1):
        d.setdefault(ev[i][1], []).append(ev[i + 1][0] - ev[i][0])
    return d


def do(ma: str, so_ngay: float = 3.0, now: float | None = None,
       ro: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Độ tin của MỘT cảm biến. ``ro`` cho phép dùng chung kết nối khi đo cả loạt."""
    now = float(now or time.time())
    dong = ro is None
    if ro is None:
        ro = _db()
        if ro is None:
            return {"ma": ma, "nhan": "it_du_lieu"}
    try:
        ev = _chuoi(ro, ma, now - so_ngay * 86400)
        ev7 = _chuoi(ro, ma, now - 7 * 86400) if so_ngay < 7 else ev
    finally:
        if dong:
            ro.close()
    if len(ev) < 4:
        # Có thể là cảm biến SỐ (vào bảng so_do, không vào su_kien) hoặc chưa đủ dữ liệu.
        return {"ma": ma, "so_doi": len(ev), "nhan": "it_du_lieu"}

    d = _dwell(ev)
    moi = [v for ds in d.values() for v in ds]
    doi_ngay = len(ev) / so_ngay
    ngan_tl = sum(1 for v in moi if v < NGAN_GIAY) / len(moi) if moi else 0.0
    dwell_dai = max(moi) if moi else 0.0

    # Kẹt: từng đổi nhiều trong 7 ngày nhưng mốc cuối đã lâu.
    moc_cuoi = ev7[-1][0] if ev7 else 0.0
    ket = len(ev7) >= KET_DOI_7NGAY and (now - moc_cuoi) >= KET_IM_GIAY

    if ket:
        nhan = "ket"
    elif ngan_tl >= NHIEU_TL and doi_ngay >= NHIEU_DOI_NGAY:
        nhan = "nhieu"
    else:
        nhan = "lanh"
    return {"ma": ma, "so_doi": len(ev), "doi_ngay": round(doi_ngay, 1), "ngan_tl": round(ngan_tl, 3),
            "dwell_dai_gio": round(dwell_dai / 3600, 2), "nhieu_giay": _nguong_giu(moi),
            "moc_cuoi": moc_cuoi, "im_gio": round((now - moc_cuoi) / 3600, 1), "nhan": nhan}


def _nguong_giu(dwell: list[float]) -> float:
    """Ngưỡng GIỮ: một đổi trạng thái chỉ đáng tin khi trạng thái mới giữ ≥ ngần này giây. Lấy p40 của các lần ở —
    thấp hơn là nhiễu chớp, cao hơn là lần ở thật. Chặn trong [NGAN_GIAY, 120] để không quá nhạy/quá chậm."""
    if not dwell:
        return NGAN_GIAY
    s = sorted(dwell)
    p40 = s[int(len(s) * 0.4)]
    return round(max(NGAN_GIAY, min(120.0, p40)), 1)


def do_so(ma: str, so_ngay: float = 2.0, now: float | None = None,
          ro: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Độ tin của cảm biến SỐ (khoảng cách radar) — đọc bảng ``so_do`` (gộp 5 phút). Nhãn ``nhieu`` khi chạm 0 nhiều
    ô (radar hay mất mục tiêu) hoặc biên độ trong 5 phút lớn liên tục."""
    now = float(now or time.time())
    dong = ro is None
    if ro is None:
        ro = _db()
        if ro is None:
            return {"ma": ma, "nhan": "it_du_lieu"}
    try:
        o_tu = int((now - so_ngay * 86400) // 300)
        rows = [(float(nho), float(lon)) for nho, lon in ro.execute(
            "SELECT nho, lon FROM so_do WHERE thiet_bi=? AND o_5p>? ORDER BY o_5p", (ma, o_tu))]
    finally:
        if dong:
            ro.close()
    if len(rows) < 20:
        return {"ma": ma, "nhan": "it_du_lieu"}
    cham0 = sum(1 for nho, _ in rows if nho == 0) / len(rows)
    bien = sum(1 for nho, lon in rows if lon - nho > 3) / len(rows)
    nhan = "nhieu" if cham0 >= KC_0_TL else "lanh"
    return {"ma": ma, "so_o": len(rows), "cham0_tl": round(cham0, 3), "bien_rong_tl": round(bien, 3), "nhan": nhan}


def tat_ca(so_ngay: float = 3.0, now: float | None = None) -> dict[str, Any]:
    """Độ tin mọi cảm biến hiện diện/cửa/đếm + cảm biến khoảng cách, cho tab Học hỏi và các tầng dùng lại."""
    from services import kich_hoat_nha as kh
    now = float(now or time.time())
    ro = _db()
    if ro is None:
        return {"nhi_phan": [], "so": [], "luc": now}
    try:
        from services.luat_duyet import cam_bien as _cb
        cbs = _cb()
    except Exception as exc:  # noqa: BLE001
        logger.warning({"event": "do_tin_cam_bien_loi", "error": str(exc)[:160]})
        cbs = []
    nhi: list[dict[str, Any]] = []
    so: list[dict[str, Any]] = []
    try:
        for c in cbs:
            ma = c["ma"]
            if ma.startswith("binary_sensor."):
                r = do(ma, so_ngay, now, ro)
                if r.get("nhan") != "it_du_lieu":
                    nhi.append({**r, "ten": c.get("ten"), "khu": c.get("khu")})
            elif "khoảng cách" in str(c.get("loai", "")) or (c.get("don_vi") in ("m", "cm", "mm")):
                r = do_so(ma, min(so_ngay, 2.0), now, ro)
                if r.get("nhan") != "it_du_lieu":
                    so.append({**r, "ten": c.get("ten"), "khu": c.get("khu")})
    finally:
        ro.close()
    _ = kh  # giữ import rõ ý: cùng họ cảm biến mà kích hoạt dùng
    thu_tu = {"ket": 0, "nhieu": 1, "lanh": 2}
    nhi.sort(key=lambda x: (thu_tu.get(x["nhan"], 3), -x.get("doi_ngay", 0)))
    so.sort(key=lambda x: (thu_tu.get(x["nhan"], 3), -x.get("cham0_tl", 0)))
    return {"nhi_phan": nhi, "so": so, "luc": now, "so_ngay": so_ngay}


def nguong_giu(ma: str, so_ngay: float = 3.0, now: float | None = None) -> float | None:
    """Ngưỡng giữ của một cảm biến (giây) nếu nó NHIỄU; None nếu lành/không đủ dữ liệu (không cần lọc)."""
    r = do(ma, so_ngay, now)
    return r.get("nhieu_giay") if r.get("nhan") == "nhieu" else None


#: Bộ nhớ đệm ngưỡng giữ: đo flap tốn một truy vấn lịch sử, mà `kiem_dieu_kien` gọi mỗi lượt sự kiện (hàng trăm
#: lần/ngày). Tính lại mỗi `_CACHE_GIAY`; độ nhiễu của cảm biến đổi theo ngày chứ không theo giây.
_cache: dict[str, tuple[float, float | None]] = {}
_CACHE_GIAY = 1800.0


def nguong_giu_nhanh(ma: str, now: float | None = None) -> float | None:
    """Như `nguong_giu` nhưng có đệm — dùng trong đường nóng (lọc mềm điều kiện). Chỉ cảm biến nhị phân."""
    if not str(ma).startswith("binary_sensor."):
        return None
    now = float(now or time.time())
    c = _cache.get(ma)
    if c and now - c[0] < _CACHE_GIAY:
        return c[1]
    v = nguong_giu(ma, 3.0, now)
    _cache[ma] = (now, v)
    return v


def _reset_cache_for_tests() -> None:
    _cache.clear()


#: Báo lỗi setting ở BAR cao hơn nhãn: nhãn «nhiễu» để lọc mềm (nhạy), còn báo anh đi chỉnh độ nhạy thì chỉ ca RÕ
#: (đổi rất dày + phần lớn chớp nhoáng), tránh làm phiền vì cảm biến hơi nhiễu.
BAO_DOI_NGAY = 300.0
BAO_NGAN_TL = 0.4


def loi_can_bao(so_ngay: float = 3.0, now: float | None = None) -> list[dict[str, Any]]:
    """Lỗi SETTING đáng báo chủ máy (dạng bản ghi của `canh_bao_nha`): cảm biến đổi quá dày (đặt quá nhạy) hoặc kẹt.
    Đi qua cùng cơ chế im lặng / nâng bậc của `canh_bao_nha`, nên anh tắt được cái nào chấp nhận."""
    d = tat_ca(so_ngay, now)
    ra: list[dict[str, Any]] = []
    for x in d.get("nhi_phan") or []:
        ten = x.get("ten") or x["ma"]
        if x["nhan"] == "ket":
            ra.append({"thiet_bi": x["ma"], "truong": "state", "loai": "cam_bien_ket",
                       "chi_tiet": f"«{ten}» đứng im {x.get('im_gio')} giờ dù trước đó đổi thường xuyên — "
                                   "có thể cảm biến kẹt hoặc mất nguồn, anh kiểm giúp."})
        elif x["nhan"] == "nhieu" and x.get("doi_ngay", 0) >= BAO_DOI_NGAY and x.get("ngan_tl", 0) >= BAO_NGAN_TL:
            ra.append({"thiet_bi": x["ma"], "truong": "state", "loai": "cam_bien_nhieu",
                       "chi_tiet": f"«{ten}» đổi {x.get('doi_ngay'):.0f} lần/ngày, {x.get('ngan_tl', 0) * 100:.0f}% chỉ "
                                   "ở dưới 10 giây — có thể đặt quá nhạy. Chỉnh bớt độ nhạy giúp bot học chính xác hơn; "
                                   "trong lúc đó em tự lọc nhiễu."})
    for x in d.get("so") or []:
        if x["nhan"] == "nhieu" and x.get("cham0_tl", 0) >= 0.7:
            ten = x.get("ten") or x["ma"]
            ra.append({"thiet_bi": x["ma"], "truong": "state", "loai": "cam_bien_nhieu",
                       "chi_tiet": f"Radar «{ten}» mất mục tiêu ở {x.get('cham0_tl', 0) * 100:.0f}% thời gian "
                                   "(khoảng cách hay về 0) — ngưỡng khoảng cách kém tin, anh kiểm vị trí/độ nhạy radar."})
    return ra
