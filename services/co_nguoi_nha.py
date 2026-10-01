"""Tầng CÓ NGƯỜI THẬT — bot tự chọn "khu này có người" cho việc TẮT KHI VẮNG của từng thiết bị,
và ngoại vi GIỮ khỏi tắt nhầm.

Chủ máy 29/09/2026, quạt và đèn phòng khách: radar phòng khách báo lây khi người đứng ở bếp; radar
mất người ngồi yên trong khi camera vẫn thấy ("Vợ tôi đang làm việc sao lại tắt đèn"); laptop của
vợ là NGOẠI VI chống tắt nhầm — "không phải cứ có máy tính là không tắt, quan trọng phải có người
ở đó". Claude cài tay cho phòng khách, rồi chủ máy: "phải tạo hướng dẫn cho bot sau này cho các
thiết bị khác, chứ không phải bạn làm tất cả"; kết luận của bot HỎI RỒI MỚI ÁP; đề cho bot "kèm
hướng dẫn … đưa thông tin thiết bị" nhưng "gói gọn trong việc học, không lẫn cái khác".

Ai làm gì (cùng khung `thoi_quen_nha`):

* CODE đo và bày số đo của MỘT thiết bị: cảm biến hiện diện (theo device_class, không theo tên)
  xếp theo khu, cặp báo lây, những lần mất dấu và ngoại vi lúc đó. Code không chọn hộ.
* BOT viết hai biểu thức theo `huong_dan_hoc/chon_co_nguoi.md`: `co_nguoi` và `giu`.
* NGƯỜI CHẤM: câu `co_nguoi` trong sổ `hieu_thiet_bi_nha`. Chấm đúng thì áp (`ap_dung`); loại câu
  này đủ thang lên cấp thì tự áp — nhưng không đè cài đặt tay (cảm biến ghép tầng này không tạo).
  Chấm sai sau khi đã áp thì trả lại danh sách cảm biến cũ.

Thời gian chờ KHÔNG ở tầng này: bot tự học từ thời gian mất dấu (`kich_hoat_nha._hoc_cho_vang`).
"""

from __future__ import annotations

import bisect
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

#: Quãng mọi cảm biến trong khu cùng vắng rồi có người lại trong ngần này = MẤT DẤU (cùng cửa sổ
#: `kich_hoat_nha.MAT_DAU_GIAY`); dài hơn là người đi thật.
MAT_DAU_GIAY = 600
#: Nhịp quan sát "người đi đâu" ngay sau lúc khu vắng — cùng số `kich_hoat_nha.ROI_GIAY`.
ROI_GIAY = 60
#: Có người lại trong ngần này giây sau lúc tắt = tắt nhầm (5 phút — "bật lại ngay").
ROI_NHAM = 300
#: ĐI NGANG hay Ở LẠI: lượt có người trước lúc khu vắng dài không quá ngần này phút (chủ máy 29/09/2026:
#: "đi đến đâu sáng đến đó, nếu lưu trú thì giữ trạng thái"). Đo 29/09/2026 phòng ngủ: người ghé dưới
#: 1 phút rồi sang khu khác, tắt nhanh nhầm 5/31; đã ở trên 10 phút thì nhầm 9/17.
O_MOC_PHUT = (1, 3, 10)
#: Khung giờ để bot thấy CÙNG một việc có giá trị khác nhau theo lúc (chủ máy 29/09/2026: "bật lại
#: thiết bị vào các thời điểm khác nhau thì cũng có giá trị khác nhau").
KHUNG_GIO = (("đêm", 0, 5), ("sáng", 5, 11), ("trưa", 11, 14), ("chiều", 14, 18), ("tối", 18, 24))


def _khung(t: float) -> str:
    from datetime import datetime, timedelta, timezone
    h = datetime.fromtimestamp(t, timezone(timedelta(hours=7))).hour
    return next(ten for ten, a, b in KHUNG_GIO if a <= h < b)
#: Kết luận còn mới thì không giải lại — trừ khi chủ nhà vừa dặn thêm dữ kiện.
_GIAI_LAI_SAU_GIAY = 7 * 86400
_SO_NGAY = 30
#: Giới hạn dòng của đề — đề ngắn để bot khỏi nghĩ lan man (chủ máy 13/09/2026).
_TOI_DA_LAY = 6
_LAY_MOI_CAM_BIEN = 3
#: Cảm biến khu khác báo "có người" quá ngần này thời gian là KẸT (đo 29/09/2026: hiện diện
#: phòng học báo có người 100%, 0 lần đổi/ngày) — không mang thông tin, chỉ chiếm chỗ trong đề.
_KET = 0.98
_TOI_DA_NGOAI_VI = 10
#: Ngoại vi người CẦM hoặc DÙNG: máy theo dõi thiết bị (điện thoại, laptop, máy tính bảng qua
#: router) và máy phát (tivi, loa). Theo MIỀN của HA — nghĩa của miền, không phải khớp tên.
_MIEN_NGOAI_VI = ("device_tracker", "media_player")
_KHONG_RO = {"unavailable", "unknown", "none", ""}

_PATH = Path(DATA_DIR) / "agent" / "co_nguoi_nha.json"
_khoa = threading.RLock()
_dang_chay = threading.Lock()


# ── Khoảng thời gian ────────────────────────────────────────────────────────
Khoang = list[tuple[float, float]]


def _dong(ro: sqlite3.Connection, ma: str, tu: float, den: float) -> tuple[list[float], list[str]]:
    """Trạng thái một mã theo thời gian (chữ thường), kể cả giá trị đang có lúc ``tu`` — HA chỉ
    báo khi ĐỔI, máy theo dõi thiết bị có khi cả tuần mới đổi một lần."""
    ra = [(float(t), str(g).strip().lower()) for t, g in ro.execute(
        "SELECT ts, gia_tri FROM (SELECT ts, gia_tri FROM su_kien WHERE thiet_bi=? AND truong='state'"
        " AND ts<? ORDER BY ts DESC LIMIT 1) UNION ALL SELECT ts, gia_tri FROM su_kien"
        " WHERE thiet_bi=? AND truong='state' AND ts>=? AND ts<? ORDER BY ts", (ma, tu, ma, tu, den))]
    if ra and ra[0][0] >= tu:
        # Không có bản ghi nào trước ``tu``: kho chỉ ghi khi ĐỔI, nhưng lần đổi đầu tiên mang giá trị
        # CŨ. Bỏ nó thì máy ít đổi (laptop, điện thoại) "không rõ" gần hết tháng — đo 29/09/2026 đề
        # đèn trần: mọi ngoại vi "không rõ" 77–98% số lần vắng.
        r = ro.execute("SELECT gia_tri_cu FROM su_kien WHERE thiet_bi=? AND truong='state' AND ts>=?"
                       " ORDER BY ts LIMIT 1", (ma, tu)).fetchone()
        cu = str((r or [""])[0] or "").strip().lower()
        if cu:
            ra.insert(0, (tu, cu))
    return [t for t, _ in ra], [g for _, g in ra]


def _luc(ts: list[float], gt: list[str], t: float) -> str:
    i = bisect.bisect_right(ts, t) - 1
    return gt[i] if i >= 0 else ""


def _khoang(ts: list[float], gt: list[str], tu: float, den: float, dk: Any) -> Khoang:
    """Những khoảng trong [tu, den) mà ``dk(trạng thái)`` đúng."""
    ra: Khoang = []
    a = tu if dk(_luc(ts, gt, tu)) else None
    for t, g in zip(ts[bisect.bisect_right(ts, tu):], gt[bisect.bisect_right(ts, tu):]):
        if t >= den:
            break
        if dk(g) and a is None:
            a = t
        elif not dk(g) and a is not None:
            ra.append((a, t))
            a = None
    if a is not None:
        ra.append((a, den))
    return ra


def _giao(x: Khoang, y: Khoang) -> Khoang:
    ra: Khoang = []
    i = j = 0
    while i < len(x) and j < len(y):
        a, b = max(x[i][0], y[j][0]), min(x[i][1], y[j][1])
        if a < b:
            ra.append((a, b))
        if x[i][1] < y[j][1]:
            i += 1
        else:
            j += 1
    return ra


def _hop(ds: list[Khoang]) -> Khoang:
    ra: Khoang = []
    for a, b in sorted(k for x in ds for k in x):
        if ra and a <= ra[-1][1]:
            ra[-1] = (ra[-1][0], max(ra[-1][1], b))
        else:
            ra.append((a, b))
    return ra


def _bu(x: Khoang, tu: float, den: float) -> Khoang:
    ra: Khoang = []
    t = tu
    for a, b in x:
        if a > t:
            ra.append((t, a))
        t = max(t, b)
    if t < den:
        ra.append((t, den))
    return ra


def _dai(x: Khoang) -> float:
    return sum(b - a for a, b in x)


def _ti_le(tu_so: float, mau_so: float) -> str:
    return f"{round(100 * tu_so / mau_so)}%" if mau_so > 0 else "—"


# ── Đo ──────────────────────────────────────────────────────────────────────
def _la_bat(g: str) -> bool:
    from services.du_doan_nha import _la_bat as la_bat
    return la_bat(g)


def ung_vien(tb: str, ro: sqlite3.Connection, tu: float, den: float, *,
             trang_thai: list[dict[str, Any]], khu_tb: str) -> dict[str, Any] | str:
    """Số đo của MỘT thiết bị cho đề. Trả chuỗi lý do khi không có gì để bot chọn."""
    from services import boi_canh_nha, cam_bien_ghep, kich_hoat_nha

    so_ngay = max(1.0, (den - tu) / 86400)
    ts_tb, gt_tb = _dong(ro, tb, tu, den)
    bat_tb = _khoang(ts_tb, gt_tb, tu, den, _la_bat)
    if _dai(bat_tb) < 3600:
        return "thiết bị bật chưa tới 1 giờ trong cửa sổ đo"

    hien_dien: dict[str, dict[str, Any]] = {}
    ngoai_vi: dict[str, dict[str, Any]] = {}
    for s in trang_thai:
        ma = str(s.get("entity_id") or "")
        attr = s.get("attributes") or {}
        mien = ma.split(".")[0]
        la_hd = (mien == "binary_sensor" and attr.get("device_class") in kich_hoat_nha._LOP_HIEN_DIEN
                 and not ma.startswith(cam_bien_ghep.TIEN_TO))
        if not la_hd and mien not in _MIEN_NGOAI_VI:
            continue
        ts, gt = _dong(ro, ma, tu, den)
        n = sum(1 for t in ts if t >= tu)
        # Cảm biến không đổi lần nào không nói được gì; ngoại vi đứng yên cả tháng (laptop bật
        # suốt) vẫn phải có trong đề — chủ nhà có thể dặn đúng tên nó.
        if not (n if la_hd else ts):
            continue
        x = {"ten": str(attr.get("friendly_name") or ma), "ts": ts, "gt": gt,
             "doi_ngay": n / so_ngay, "khu": boi_canh_nha.phong_cua(ma) or "chưa xếp khu"}
        if la_hd:
            x["bat"] = _khoang(ts, gt, tu, den, lambda g: g == "on")
            hien_dien[ma] = x
        else:
            ngoai_vi[ma] = x

    trong = [m for m, x in hien_dien.items() if x["khu"] == khu_tb]
    if not trong:
        return f"khu {khu_tb or '(chưa rõ)'} không có cảm biến hiện diện nào có lịch sử"
    ket = [m for m in hien_dien if m not in trong and _dai(hien_dien[m]["bat"]) > _KET * (den - tu)]
    khac = [m for m in hien_dien if m not in trong and m not in ket]
    dai_bat = _dai(bat_tb)

    # 1. Cảm biến trong khu: báo có người bao nhiêu phần lúc thiết bị bật, và phần CHỈ nó báo.
    for m in trong:
        con_lai = _hop([hien_dien[k]["bat"] for k in trong if k != m])
        rieng = _giao(_giao(hien_dien[m]["bat"], bat_tb), _bu(con_lai, tu, den))
        hien_dien[m]["khi_bat"] = _ti_le(_dai(_giao(hien_dien[m]["bat"], bat_tb)), dai_bat)
        hien_dien[m]["rieng"] = _ti_le(_dai(rieng), dai_bat)

    # 2. Báo lây: cảm biến trong khu báo có người thì cảm biến khu khác cũng báo bao nhiêu phần;
    #    trong lúc cả hai cùng báo, từng cảm biến còn lại trong khu báo bao nhiêu phần.
    cap = []
    for r in trong:
        on_r = hien_dien[r]["bat"]
        cua_r = []
        for x in khac:
            ca_hai = _giao(on_r, hien_dien[x]["bat"])
            p = _dai(ca_hai) / _dai(on_r) if _dai(on_r) else 0.0
            if p <= 0:
                continue
            xac = {c: _ti_le(_dai(_giao(ca_hai, hien_dien[c]["bat"])), _dai(ca_hai))
                   for c in trong if c != r}
            cua_r.append({"r": r, "x": x, "p": p, "xac": xac})
        cap += sorted(cua_r, key=lambda c: -c["p"])[:_LAY_MOI_CAM_BIEN]

    # 3. Mất dấu: mọi cảm biến trong khu cùng vắng lúc thiết bị đang bật, rồi có người lại.
    hop_trong = _hop([hien_dien[m]["bat"] for m in trong])
    quang = [(a, b) for a, b in _bu(hop_trong, tu, den) if b < den and _la_bat(_luc(ts_tb, gt_tb, a))]
    ngan = [(a, b) for a, b in quang if b - a <= MAT_DAU_GIAY]
    dai = [(a, b) for a, b in quang if b - a > MAT_DAU_GIAY]

    def co_trong(x: str, ds: Khoang) -> int:
        return sum(1 for q in ds if _giao([q], hien_dien[x]["bat"]))

    sang_khac = sorted(({"x": x, "ngan": co_trong(x, ngan), "dai": co_trong(x, dai)} for x in khac),
                       key=lambda d: -d["ngan"])
    for d in sang_khac:
        d["ngan"], d["dai"] = _ti_le(d["ngan"], len(ngan)), _ti_le(d["dai"], len(dai))

    def phan_bo(x: dict[str, Any], ds: Khoang) -> str:
        dem: dict[str, int] = {}
        for a, _ in ds:
            g = _luc(x["ts"], x["gt"], a) or "không rõ"
            dem[g] = dem.get(g, 0) + 1
        return ", ".join(f"{g} {_ti_le(n, len(ds))}" for g, n in
                         sorted(dem.items(), key=lambda i: -i[1])[:2]) if ds else "—"

    def lech(x: dict[str, Any]) -> float:
        """Một trạng thái xuất hiện ở lần mất dấu nhiều hơn ở lần đi thật bao nhiêu — đúng tiêu chí
        hướng dẫn cho bot dùng để chọn ngoại vi."""
        def phan(ds: Khoang) -> dict[str, float]:
            dem: dict[str, float] = {}
            for a, _ in ds:
                g = _luc(x["ts"], x["gt"], a)
                if g not in _KHONG_RO:
                    dem[g] = dem.get(g, 0) + 1 / len(ds)
            return dem
        pn, pd = phan(ngan) if ngan else {}, phan(dai) if dai else {}
        return max((v - pd.get(g, 0.0) for g, v in pn.items()), default=0.0)

    # 4. Rời khu: trong ROI_GIAY đầu sau lúc khu này vắng, cảm biến khu khác báo có người (người đi
    #    sang đó?) — khu này có người lại nhanh hay không, so với lúc không khu nào báo.
    def bat_trong(x: str, a: float, b: float) -> bool:
        ts, gt = hien_dien[x]["ts"], hien_dien[x]["gt"]
        i = bisect.bisect_right(ts, a)
        while i < len(ts) and ts[i] <= b:
            if gt[i] == "on":
                return True
            i += 1
        return False

    # Lượt có người trong khu (khe vắng ngắn hơn VANG gộp lại — cùng nghĩa "vắng" lúc sống): mỗi
    # quãng vắng biết người đã ở bao lâu trước đó — đi ngang hay ở lại.
    bd_luot: list[float] = []
    cuoi = -1e18
    for a, b in hop_trong:
        if a - cuoi >= kich_hoat_nha.VANG:
            bd_luot.append(a)
        cuoi = max(cuoi, b)

    def da_o(a: float) -> float:
        i = bisect.bisect_right(bd_luot, a - 1e-6) - 1
        return (a - bd_luot[i]) / 60 if i >= 0 else 1e9

    def ty(ds: Khoang) -> dict[str, Any]:
        """Chỉ những lần CÒN vắng lúc đường tắt nhanh kịp tắt (2 nhịp quan sát); "nhầm" = có người
        lại trong ROI_NHAM giây sau đó — đúng tỉ lệ tắt nhầm nếu tắt nhanh. Mất dấu vài giây thì
        chưa kịp tắt nên không tính (đo 29/09/2026: tính cả chúng làm phòng ngủ trông như 40% nhầm)."""
        con = [(a, b) for a, b in ds if b - a > 2 * ROI_GIAY]
        def nham(q: Khoang) -> str:
            return _ti_le(sum(1 for a, b in q if b - a <= 2 * ROI_GIAY + ROI_NHAM), len(q))
        theo = {ten: [q for q in con if _khung(q[0]) == ten] for ten, _a, _b in KHUNG_GIO}
        theo_o = {p: [q for q in con if da_o(q[0]) <= p] for p in O_MOC_PHUT}
        return {"n": len(con), "nham": nham(con),
                "khung": " ".join(f"{ten} {nham(q)}/{len(q)}" for ten, q in theo.items() if q),
                "o": " ".join(f"≤{p}' {nham(q)}/{len(q)}" for p, q in theo_o.items() if q)}

    theo_x = {x: [q for q in quang if bat_trong(x, q[0], q[0] + ROI_GIAY)] for x in khac}
    co_x = {q for ds in theo_x.values() for q in ds}
    roi = sorted(({"x": x, **ty(ds)} for x, ds in theo_x.items() if ds), key=lambda d: -d["n"])
    roi = [d for d in roi if d["n"]]
    roi_nen = ty([q for q in quang if q not in co_x])
    # Những lần bot ĐÃ tắt theo «rời khu» và bị bật lại ngay (sai) — theo khung giờ.
    from services import du_doan_nha, kich_hoat_nha
    roi_da: dict[str, list[int]] = {}
    with du_doan_nha._khoa:
        for ts, kq in du_doan_nha._db().execute(
                "SELECT ts, ket_qua FROM du_doan WHERE ten=? AND ts>=?"
                " AND COALESCE(json_extract(boi_canh, '$.roi'), 0)=1", (kich_hoat_nha._ten_tt(tb, "off"), tu)):
            x = roi_da.setdefault(_khung(float(ts)), [0, 0])
            x[0] += kq == "sai"
            x[1] += 1

    nv = []
    for m, x in ngoai_vi.items():
        if all(_luc(x["ts"], x["gt"], a) in _KHONG_RO for a, _ in quang):
            continue
        nv.append({"ma": m, "ten": x["ten"], "ngan": phan_bo(x, ngan), "dai": phan_bo(x, dai),
                   "doi_ngay": x["doi_ngay"], "lech": lech(x),
                   "gia_tri": sorted({g for g in x["gt"] if g not in _KHONG_RO})})
    # Bảng cắt ở _TOI_DA_NGOAI_VI dòng: xếp theo tiêu chí chọn, không theo độ hay đổi — đo 29/09/2026
    # laptop của vợ (đổi 2 lần/14 ngày) rơi khỏi đề đèn trần dù chủ nhà nêu đích danh nó.
    nv.sort(key=lambda d: (-d["lech"], -d["doi_ngay"]))
    try:
        from services import camera_nha, mqtt_nha
        ds_cam = camera_nha.danh_sach()
        dem = mqtt_nha.dem_nguoi()
        camera = [str(c["name"]) for c in ds_cam]
        # Camera Frigate đếm sẵn người (trùng ĐÚNG tên luồng) — nhìn lại khỏi phải chụp.
        frigate = [str(c["name"]) for c in ds_cam if not dem.get("_cu") and str(c.get("src") or "") in dem]
    except Exception:  # noqa: BLE001 — không đọc được sổ camera thì bot không có camera để nhìn lại
        camera, frigate = [], []
    try:
        from services import so_do_nha
        so_do = so_do_nha.doan_de(khu_tb)
    except Exception:  # noqa: BLE001 — chưa có sơ đồ thì thôi
        so_do = []
    from services import vung_khoang_cach
    return {"ma": tb, "khoang_cach": vung_khoang_cach.cho_de(khu_tb), "camera": camera, "camera_frigate": frigate, "so_do": so_do, "khu": khu_tb, "so_ngay": so_ngay, "gio_bat": dai_bat / 3600,
            "hien_dien": {m: {k: v for k, v in x.items() if k not in ("ts", "gt", "bat")}
                          for m, x in hien_dien.items()},
            "trong": trong, "ket": ket, "cap": cap, "sang_khac": sang_khac[:_TOI_DA_LAY],
            "roi": roi[:_TOI_DA_LAY], "roi_nen": roi_nen,
            "roi_da": {k: {"sai": v[0], "n": v[1]} for k, v in roi_da.items()},
            "ngan": len(ngan), "dai": len(dai), "ngoai_vi": nv[:_TOI_DA_NGOAI_VI]}


def de(uv: dict[str, Any], ten_tb: str, dan: list[str]) -> str:
    """Đề cho bot: CHỈ thiết bị này, lời chủ nhà dặn khi chấm câu của chính nó, và số đo.

    Không bày cả sổ dữ kiện chung: chủ máy 29/09/2026 "gói gọn trong việc học, không nên thêm
    các promt khác không thuộc phạm vi" — sổ đó có cả vân tay, aptomat, "Em bật đúng rồi"."""
    hd = uv["hien_dien"]
    dong = [f"THIẾT BỊ: {uv['ma']} | {ten_tb} | khu: {uv['khu']} | "
            f"bật {uv['gio_bat']:.0f} giờ trong {uv['so_ngay']:.0f} ngày"]
    if uv.get("so_do"):
        dong += [""] + list(uv["so_do"])
    if dan:
        dong.append("\nCHỦ NHÀ / GIÁO VIÊN DẶN (khi chấm các lần chọn trước của thiết bị này):")
        dong += [f"- {x}" for x in dan]
    dong += ["\nA. CẢM BIẾN HIỆN DIỆN TRONG KHU (lúc thiết bị bật):",
             "mã | tên | đổi/ngày | báo có người | CHỈ mình nó báo"]
    dong += [f"{m} | {hd[m]['ten']} | {hd[m]['doi_ngay']:.0f} | {hd[m]['khi_bat']} | {hd[m]['rieng']}"
             for m in uv["trong"]]
    if uv["ket"]:
        dong.append("\n(Bỏ khỏi B, C vì luôn báo có người — kẹt: " + ", ".join(uv["ket"]) + ")")
    dong += ["\nB. BÁO LÂY — cảm biến trong khu báo có người thì cảm biến khu khác cũng báo:",
             "trong khu | khu khác (khu, đổi/ngày) | cùng báo | trong lúc cùng báo, cảm biến khác trong khu báo"]
    dong += [f"{c['r']} | {_khac(hd, c['x'])} | {round(100 * c['p'])}% | "
             + (", ".join(f"{k} {v}" for k, v in c["xac"].items()) or "—") for c in uv["cap"]]
    if not uv["cap"]:
        dong.append("(không có cặp nào cùng báo)")
    dong += [f"\nC. MẤT DẤU — mọi cảm biến mục A cùng vắng lúc thiết bị bật: {uv['ngan']} lần có "
             f"người lại trong {MAT_DAU_GIAY // 60} phút (mất dấu), {uv['dai']} lần lâu hơn (đi thật).",
             "Cảm biến khu khác báo có người trong quãng đó:",
             "mã (khu, đổi/ngày) | trong lần mất dấu | trong lần đi thật"]
    dong += [f"{_khac(hd, d['x'])} | {d['ngan']} | {d['dai']}" for d in uv["sang_khac"]]
    dong += ["\nD. NGOẠI VI — trạng thái lúc bắt đầu quãng vắng:",
             "mã | tên | các trạng thái | lúc mất dấu | lúc đi thật"]
    dong += [f"{x['ma']} | {x['ten']} | {', '.join(x['gia_tri'][:6])} | {x['ngan']} | {x['dai']}"
             for x in uv["ngoai_vi"]]
    if not uv["ngoai_vi"]:
        dong.append("(không có)")
    dong += [f"\nF. RỜI KHU — trong {ROI_GIAY} giây đầu sau lúc mục A vắng, cảm biến khu khác báo có người."
             f" Chỉ tính lần khu này còn vắng sau {2 * ROI_GIAY // 60} phút (lúc tắt nhanh sẽ tắt);"
             f" TẮT NHẦM = có người lại trong {ROI_NHAM // 60} phút sau đó. Cột cuối: chỉ tính lần người"
             f" mới Ở trong khu không quá N phút trước lúc vắng (≤1' là đi ngang):",
             "mã (khu, đổi/ngày) | số lần | tắt nhầm | tắt nhầm theo khung giờ (tỉ lệ/số lần) | "
             "tắt nhầm theo lúc trước đã ở (tỉ lệ/số lần)"]
    dong += [f"{_khac(hd, d['x'])} | {d['n']} | {d['nham']} | {d['khung']} | {d.get('o') or '—'}"
             for d in uv.get("roi") or []]
    nen = uv.get("roi_nen") or {}
    dong.append(f"(không cảm biến khu khác nào báo) | {nen.get('n', 0)} | {nen.get('nham', '—')} | "
                f"{nen.get('khung', '')} | {nen.get('o') or '—'}")
    if uv.get("roi_da"):
        dong.append("Bot đã tắt theo «rời khu» rồi bị bật lại ngay (sai/số lần): "
                    + ", ".join(f"{k} {v['sai']}/{v['n']}" for k, v in uv["roi_da"].items()))
    if uv.get("khoang_cach"):
        dong += ["\nG. KHOẢNG CÁCH — radar trong khu đo được người đứng cách nó bao xa; bot đã tự học vùng của khu "
                 "(nhãn: camera khu thấy người / radar khu bên cạnh báo). Nút {\"khoang_cach\": \"<mã>\"} đúng khi "
                 "radar KHÔNG thấy người ở ngoài vùng (không đo được cũng tính là đúng):",
                 "mã | radar | vùng của khu | tách đúng (đoán mò 50%) | số đo trong khu / khu bên cạnh"]
        dong += [f"{x['ma']} | {x['radar']} | {'dưới' if x['huong'] == 'duoi' else 'từ'} {x['nguong']} "
                 f"{x.get('don_vi') or 'm'} | {round(100 * x['dung'])}% | {x['n_trong']} / {x['n_ngoai']}"
                 for x in uv["khoang_cach"]]
    dong += ["\nE. CAMERA — c2a nhìn lại được (tên | cách đếm người):"]
    dong += [f"{c} | " + ("Frigate đếm sẵn, khỏi chụp" if c in (uv.get("camera_frigate") or []) else "chụp rồi đếm")
             for c in uv.get("camera") or []] or ["(không có)"]
    return "\n".join(dong)


def _khac(hd: dict[str, Any], ma: str) -> str:
    return f"{ma} ({hd[ma]['khu']}, {hd[ma]['doi_ngay']:.0f})"


# ── Kiểm bài ở biên ─────────────────────────────────────────────────────────
def _ma_trong(bt: Any) -> set[str]:
    from services import cam_bien_ghep
    return cam_bien_ghep.thanh_phan(bt)


def kiem(data: Any, uv: dict[str, Any]) -> dict[str, Any] | str:
    """Loại hẳn bài sai khuôn thay vì sửa hộ (cùng lẽ `thoi_quen_nha.kiem`). Code chỉ kiểm mã và
    trạng thái CÓ trong đề; chọn đúng hay sai là việc người chấm."""
    from services import cam_bien_ghep

    if not isinstance(data, dict):
        return "không phải JSON object"
    co, giu = data.get("co_nguoi"), data.get("giu")
    hien_dien = set(uv["hien_dien"])
    gia_tri = {x["ma"]: set(x["gia_tri"]) for x in uv["ngoai_vi"]}
    kc = {x["ma"] for x in uv.get("khoang_cach") or []}
    for ten, bt, duoc in (("co_nguoi", co, hien_dien | kc), ("giu", giu, hien_dien | set(gia_tri))):
        if bt is None and ten == "giu":
            continue
        try:
            cam_bien_ghep._kiem(bt)
        except ValueError as exc:
            return f"{ten}: {exc}"
        la = _la_cua(bt)
        for ma in _ma_trong(bt):
            if ma not in duoc:
                return f"{ten}: mã không có trong đề hoặc không dùng được ở đây: {ma!r}"
            cho_phep = gia_tri.get(ma, {"on", "off"})
            if not la.get(ma, {"on"}) <= cho_phep:
                return f"{ten}: trạng thái {sorted(la[ma])} không có ở {ma}"
    if not set(uv["trong"]) & _ma_trong(co):
        return "co_nguoi phải dùng ít nhất một cảm biến trong khu"
    try:
        chac = min(1.0, max(0.0, float(data.get("chac"))))
    except (TypeError, ValueError):
        chac = 0.0
    roi_di = data.get("roi_di")
    if roi_di is not None:
        try:
            cam_bien_ghep._kiem(roi_di)
        except ValueError as exc:
            return f"roi_di: {exc}"
        la_ = _ma_trong(roi_di) - (hien_dien - set(uv["trong"]) - set(uv["ket"]))
        if la_:
            return f"roi_di chỉ dùng cảm biến KHU KHÁC có trong đề (không trong khu, không kẹt): {sorted(la_)!r}"
    roi_phut = data.get("roi_khi_o_duoi")
    if roi_di is None or roi_phut in (None, "", 0):
        roi_phut = None
    elif roi_phut not in O_MOC_PHUT:
        return f"roi_khi_o_duoi phải là một trong {O_MOC_PHUT} (phút, như cột cuối mục F) hoặc null"
    nhin = data.get("nhin")
    if nhin is not None:
        if not isinstance(nhin, list) or not all(isinstance(x, str) for x in nhin):
            return "nhin phải là danh sách tên camera hoặc null"
        la = [x for x in nhin if x not in (uv.get("camera") or [])]
        if la:
            return f"nhin: camera không có trong đề: {la!r}"
        nhin = nhin or None
    if giu is not None and not nhin:
        return "giu phải đi cùng nhin — ngoại vi chỉ để NHÌN LẠI, không giữ một mình"
    return {"co_nguoi": co, "giu": giu, "nhin": nhin, "roi_di": roi_di, "roi_khi_o_duoi": roi_phut,
            "chac": round(chac, 2),
            "vi_sao": str(data.get("vi_sao") or "")[:300]}


def _la_cua(bt: Any, ra: dict[str, set[str]] | None = None) -> dict[str, set[str]]:
    ra = {} if ra is None else ra
    if "ma" in bt:
        ra.setdefault(str(bt["ma"]), set()).update(str(x).lower() for x in bt.get("la", ["on"]))
    elif "khoang_cach" in bt:
        pass
    elif "khong" in bt:
        _la_cua(bt["khong"], ra)
    else:
        for x in next(iter(bt.values())):
            _la_cua(x, ra)
    return ra


# ── Giải ────────────────────────────────────────────────────────────────────
def _thiet_bi() -> dict[str, dict[str, Any]]:
    """Thiết bị đang cho bot tắt khi vắng — tầng này chỉ chọn cảm biến cho việc đó."""
    from services import kich_hoat_nha

    with kich_hoat_nha._khoa:
        return {tb: json.loads(json.dumps(cd)) for tb, cd in kich_hoat_nha._nap()["thiet_bi"].items()
                if cd.get("bat") and (cd.get("tat_khi_vang") or {}).get("bat")}


def _khu(tb: str) -> str:
    """Khu thiết bị thật sự nằm: kết luận chặng 1 (`ngoai_vi`) nếu có — tên thiết bị thắng khu
    của công tắc — không thì sổ khu vực HA."""
    from services import boi_canh_nha, ha_client, hieu_thiet_bi_nha as ht

    nvh = ht.ngoai_vi_hoc()
    for m in (tb, ha_client.thuc_the_guong(tb)):
        if m and (nvh.get(m) or {}).get("khu_vuc"):
            return str(nvh[m]["khu_vuc"])
    return boi_canh_nha.phong_cua(tb) or ""


def _can_giai(cu: dict[str, Any] | None, now: float) -> bool:
    """Chưa có kết luận; chủ nhà vừa chấm SAI (giải lại ngay, kèm lời dặn); hoặc đã cũ. Bot lặp
    lại đúng câu từng bị chấm sai (`lap_lai`) thì chờ tới hạn cũ — hỏi lại mỗi lượt chỉ tốn lượt gọi."""
    if not cu:
        return True
    giai_luc = float(cu["nhom"].get("giai_luc") or 0)
    if (cu["ket_qua"] == "sai" and cu.get("cham_boi") in ("chu_may", "claude")
            and float(cu.get("cham_luc") or 0) > giai_luc):
        return True
    return now - giai_luc >= _GIAI_LAI_SAU_GIAY


def giai(chi: list[str] | None = None, *, tat_ca: bool = False) -> dict[str, Any]:
    """Bot chọn `co_nguoi` / `giu` cho từng thiết bị. KHÔNG ghi sổ — `chay_mot_lan` ghi; tách ra để
    giáo viên thử hướng dẫn trên đề thật."""
    from services import ha_client, hieu_thiet_bi_nha as ht, lich_su_nha
    from services.thoi_quen_nha import _hoi_bot

    tbs = _thiet_bi()
    trang_thai = ha_client.get_states() or []
    if not tbs or not trang_thai:
        return {"ket_luan": [], "loi": [], "bo_qua": "chưa có thiết bị tắt khi vắng hoặc HA chưa trả trạng thái"}
    now = time.time()
    cu = {d["khoa"]: d for d in ht.dang_hieu_luc() if d["loai_cau_hoi"] == "co_nguoi"}
    ds = [tb for tb in tbs if (not chi or tb in chi) and (chi or tat_ca or _can_giai(cu.get(tb), now))]
    if not ds:
        return {"ket_luan": [], "loi": [], "bo_qua": "kết luận còn mới"}
    huong, ban = ht.huong_dan("chon_co_nguoi")
    model = ht._model()
    ten_ha = ht._ten_ha()
    den = now
    tu = den - _SO_NGAY * 86400
    ket_luan: list[dict[str, Any]] = []
    loi: list[dict[str, str]] = []
    ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    try:
        for tb in ds:
            uv = ung_vien(tb, ro, tu, den, trang_thai=trang_thai, khu_tb=_khu(tb))
            if isinstance(uv, str):
                loi.append({"ma": tb, "buoc": "đo", "loi": uv})
                continue
            b = _hoi_bot(ht, model, huong, de(uv, ten_ha.get(tb, ""), ht.ghi_chu_cham("co_nguoi", tb)))
            k = kiem(b, uv) if not isinstance(b, str) else b
            if isinstance(k, str):
                loi.append({"ma": tb, "buoc": "chọn", "loi": k})
                continue
            ket_luan.append({"ma_hoc": tb, "khu_vuc": uv["khu"], **k,
                             "ten": {m: x["ten"] for m, x in uv["hien_dien"].items()}
                             | {x["ma"]: x["ten"] for x in uv["ngoai_vi"]}})
    finally:
        ro.close()
    return {"phien_ban": ban, "model": model, "so_thiet_bi": len(ds), "ket_luan": ket_luan, "loi": loi}


# ── Áp vào bộ kích hoạt ─────────────────────────────────────────────────────
def ma_ghep(tb: str, phan: str) -> str:
    """Mã cảm biến ghép tầng này tạo: ``binary_sensor.c2a_vang_<miền>_<tên>`` / ``…_giu_…``."""
    from services import cam_bien_ghep
    return f"{cam_bien_ghep.TIEN_TO}{phan}_{tb.replace('.', '_')}"


def _nap_so() -> dict[str, Any]:
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _luu_so(so: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(so, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_PATH)


def _cai_tay(tb: str, cam_bien: list[str]) -> bool:
    """Danh sách cảm biến có cảm biến ghép KHÔNG do tầng này tạo = chủ máy (hoặc giáo viên) cài
    tay — tự áp không được đè."""
    from services import cam_bien_ghep
    cua_tang = {ma_ghep(tb, "vang"), ma_ghep(tb, "giu"), ma_ghep(tb, "roi")}
    return any(m.startswith(cam_bien_ghep.TIEN_TO) and m not in cua_tang for m in cam_bien)


def ap_dung() -> list[dict[str, Any]]:
    """Đưa kết luận `co_nguoi` vào bộ kích hoạt. Gọi sau mỗi lượt giải và sau mỗi lần chấm.

    * chấm ĐÚNG → áp;
    * chưa chấm mà loại câu đã đủ thang lên cấp → tự áp, trừ khi đang cài tay;
    * chấm SAI mà đang áp chính câu đó → trả lại danh sách cảm biến trước khi áp.
    """
    from services import cam_bien_ghep, hieu_thiet_bi_nha as ht, kich_hoat_nha

    tu_quyet = not ht.can_hoi("co_nguoi")
    tbs = _thiet_bi()
    ten_ha = ht._ten_ha()
    lam: list[dict[str, Any]] = []
    with _khoa:
        so = _nap_so()
        for d in ht.dang_hieu_luc():
            tb = d["khoa"]
            if d["loai_cau_hoi"] != "co_nguoi" or tb not in tbs:
                continue
            tv = tbs[tb]["tat_khi_vang"]
            da = so.get(tb) or {}
            if d["ket_qua"] == "sai":
                if da.get("id") == d["id"]:
                    kich_hoat_nha.dat_thiet_bi(tb, tat_khi_vang={**tv, "cam_bien": da["truoc"],
                                                                 "giu": "", "nhin": [], "roi": "",
                                                                 "roi_phut": None})
                    cam_bien_ghep.xoa(ma_ghep(tb, "vang"))
                    cam_bien_ghep.xoa(ma_ghep(tb, "giu"))
                    cam_bien_ghep.xoa(ma_ghep(tb, "roi"))
                    so.pop(tb, None)
                    lam.append({"thiet_bi": tb, "tra_lai": da["truoc"]})
                continue
            if da.get("id") == d["id"]:
                continue
            if not (d["ket_qua"] == "dung" or (tu_quyet and not _cai_tay(tb, tv["cam_bien"]))):
                continue
            ten = ten_ha.get(tb) or tb
            ds = [ma_ghep(tb, "vang")]
            cam_bien_ghep.dat(ds[0], f"Có người — {ten}"[:60], d["gia_tri"]["co_nguoi"])
            # Ngoại vi KHÔNG nằm trong danh sách vắng: nó không giữ thiết bị, chỉ khiến bot nhìn
            # lại bằng camera trước khi tắt (`kich_hoat_nha._tat_vi_vang`).
            giu = ""
            if d["gia_tri"].get("giu") and d["gia_tri"].get("nhin"):
                giu = ma_ghep(tb, "giu")
                cam_bien_ghep.dat(giu, f"Nên nhìn lại — {ten}"[:60], d["gia_tri"]["giu"])
            else:
                cam_bien_ghep.xoa(ma_ghep(tb, "giu"))
            roi = ""
            if d["gia_tri"].get("roi_di"):
                roi = ma_ghep(tb, "roi")
                cam_bien_ghep.dat(roi, f"Đã rời khu — {ten}"[:60], d["gia_tri"]["roi_di"])
            else:
                cam_bien_ghep.xoa(ma_ghep(tb, "roi"))
            truoc = da.get("truoc") if da else tv["cam_bien"]
            kich_hoat_nha.dat_thiet_bi(tb, tat_khi_vang={**tv, "cam_bien": ds, "giu": giu, "roi": roi,
                                                         "roi_phut": d["gia_tri"].get("roi_khi_o_duoi") if roi else None,
                                                         "nhin": list(d["gia_tri"].get("nhin") or [])})
            so[tb] = {"id": d["id"], "truoc": truoc, "luc": time.time()}
            lam.append({"thiet_bi": tb, "cam_bien": ds, "id": d["id"]})
        if lam:
            _luu_so(so)
    for x in lam:
        logger.info({"event": "co_nguoi_ap_dung", **x})
    return lam


def chay(ht: Any) -> tuple[dict[str, Any], str]:
    """Một lượt trong heartbeat của tầng thói quen: giải → lưu sổ → áp. Trả (kết quả, đoạn báo)."""
    from services.thoi_quen_nha import _bao_so, _ghi_luot

    if not _dang_chay.acquire(blocking=False):
        return {"bo_qua": "lượt trước chưa xong"}, ""
    try:
        kq = giai()
        if kq.get("bo_qua"):
            return kq, ""
        lan = _ghi_luot(ht, kq, "co_nguoi")
        ghi = ht.ghi_co_nguoi(lan, kq["ket_luan"])
        if kq["loi"]:
            logger.warning({"event": "co_nguoi_loai", "loi": kq["loi"][:5]})
        ap = ap_dung()
        ra = {"lan_giai": lan, "moi": len(ghi["moi"]), "lap_lai": len(ghi["lap_lai"]),
              "loai": len(kq["loi"]), "ap": len(ap)}
        bao = (_bao_so("chọn cảm biến «có người» cho việc tắt khi vắng", kq, ghi)
               if ghi["moi"] or ghi["lap_lai"] or kq["loi"] else "")
        return ra, bao
    finally:
        _dang_chay.release()
