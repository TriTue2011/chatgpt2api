"""Bot tự học VÙNG KHOẢNG CÁCH của từng khu — radar báo có người mà người đứng ở khu thông bên cạnh.

Chủ máy 01/10/2026: "tắt thì cũng dựa vào khoảng cách để tắt, chứ không phải chỉ là trống ở cảm biến phòng
khách". Radar phòng khách nhà chủ máy nhìn thẳng ra bếp (bếp mở): người đứng bếp nó vẫn báo có người. Đo 10
ngày dữ liệu thô của HA: lúc camera phòng khách thấy người và radar bếp trống, khoảng cách giữa 2,57 m
(p25–p75 2,34–2,93); lúc camera phòng khách không thấy ai mà radar bếp có người, giữa 4,44 m (3,92–4,98) —
một ngưỡng tách đúng 92%, đoán theo nhóm đông 68%.

Bot tự rút ngưỡng mỗi lượt học, không ai đặt số: NHÃN lấy từ camera của chính khu (Frigate thấy người) và
radar các khu bên cạnh — nhà nào có radar đo khoảng cách + camera cũng học được. Tách không đủ tốt thì không
dùng (``dat`` = False) và điều kiện khoảng cách luôn đúng — chưa học được không bao giờ gây tắt nhầm.

Số 0 / không phải số = radar KHÔNG đo được khoảng cách (đo: số 0 giữ trung vị 13 giây, có lúc 5 phút, trong
lúc radar vẫn báo có người), không phải "không có người" — cũng tính là đúng.

Dữ liệu thô lấy từ /api/history của HA (giữ ~10 ngày): kho `lich_su_nha` chỉ giữ khoảng cách gộp 5 phút.
Hệ quả: cảm biến ghép dựng lại lịch sử từ kho (`cam_bien_ghep.chuoi`) không thấy khoảng cách — nút khoảng
cách ở quá khứ tính là đúng, như trước khi có nó.
"""

from __future__ import annotations

import bisect
import json
import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

_PATH = Path(DATA_DIR) / "agent" / "vung_khoang_cach.json"
_khoa = threading.RLock()
_dl: dict[str, Any] | None = None
#: HA giữ dữ liệu thô khoảng ngần này ngày.
NGAY = 10
#: Mỗi nhãn (trong khu / khu bên cạnh) cần ít nhất ngần này số đo.
MAU_TOI_THIEU = 100
#: Độ đúng cân bằng (trung bình đúng của hai nhãn) tối thiểu mới dùng — đoán mò là 0,5.
CONG = 0.8
_LOP_HIEN_DIEN = ("occupancy", "presence", "motion")
#: Radar khu bên cạnh báo có người quá ngần này phần thời gian là KẸT — bỏ khỏi nhãn (cùng số `so_do_nha._KET`).
#: Đo 01/10/2026: radar phòng học kẹt «có người» từ 29/09 làm nhãn «trong khu» của phòng khách còn 114 mẫu
#: thay vì ~3.000 — "không radar khu bên cạnh nào báo" gần như không bao giờ đúng.
KET = 0.98
#: Khu bên cạnh chỉ là NGUỒN BÁO LÂY khi radar của nó báo có người ít nhất ngần này phần số đo lúc radar khu này
#: báo mà camera khu này không thấy ai (cùng mức «cùng báo» 40% của `so_do_nha`). Đo 01/10/2026: lấy radar MỌI khu
#: khác làm khu bên cạnh thì nhà 4 người lúc nào cũng có ai ở phòng ngủ / ban công → nhãn «trong khu» còn 114.
LAY = 0.4
#: …VÀ cao hơn lúc camera khu này THẤY người ít nhất ngần này — cảm biến kẹt / hay báo ảo báo nhiều bất kể người ở
#: đâu. Đo 01/10/2026 (radar phòng khách có số đo, lúc camera phòng khách không thấy / có thấy người): bếp 74% / 51%
#: (nguồn lây thật — radar nhìn thẳng ra bếp), phòng học (kẹt) 95% / 96%, ban công (báo ảo) 43% / 36%, phòng ngủ
#: 39% / 23%.
LAY_CHENH = 0.2
#: Tích hợp Frigate đặt tên cảm biến người của camera là ``binary_sensor.<camera>_person_occupancy``.
_DUOI_NGUOI_FRIGATE = "_person_occupancy"


def _nap() -> dict[str, Any]:
    global _dl
    if _dl is None:
        try:
            _dl = json.loads(_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _dl = {}
    return _dl


def _luu() -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_nap(), ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_PATH)


def ds() -> dict[str, dict[str, Any]]:
    with _khoa:
        return {k: dict(v) for k, v in _nap().items()}


def vung_dang_dung(m: dict[str, Any] | None) -> tuple[str, float] | None:
    """(hướng, ngưỡng) đang dùng: số chủ máy đặt (`dat_nguong`) thắng số bot học; chưa học đạt mà chủ máy chưa đặt
    thì None."""
    if not m:
        return None
    if m.get("nguong_chu") is not None:
        return str(m.get("huong") or "duoi"), float(m["nguong_chu"])
    return (str(m["huong"]), float(m["nguong"])) if m.get("dat") else None


def dat_nguong(ma: str, nguong: float | None) -> dict[str, Any]:
    """Chủ máy đặt ngưỡng vùng trên web (None = trả về số bot học). Giữ qua mọi lần `hoc()`."""
    with _khoa:
        m = _nap().get(str(ma))
        if m is None:
            raise ValueError(f"{ma} không phải khoảng cách của radar nào bot biết.")
        if nguong is None:
            m.pop("nguong_chu", None)
        else:
            if not 0 < float(nguong) <= 50:
                raise ValueError("Ngưỡng khoảng cách: 0–50.")
            m["nguong_chu"] = round(float(nguong), 2)
        _luu()
        return dict(m)


def trong_vung(ma: str, gia_tri: Any) -> bool:
    """Khoảng cách ``gia_tri`` của cảm biến ``ma`` có thể là người trong khu của radar không. Chưa học đạt,
    số 0, không phải số → True (không bao giờ vì thiếu hiểu biết mà nói «khu trống»)."""
    vg = vung_dang_dung(_nap().get(str(ma)))
    if vg is None:
        return True
    try:
        v = float(gia_tri)
    except (TypeError, ValueError):
        return True
    if v <= 0:
        return True
    return v < vg[1] if vg[0] == "duoi" else v >= vg[1]


def vi_tri(ma: str, gia_tri: Any) -> bool | None:
    """Ba trạng thái cho việc XÁC MINH (`xac_minh_nha`): True = radar đang đo một người trong vùng khu, False = đo
    được nhưng ở ngoài vùng (khu bên cạnh), None = không biết (chưa học đạt, số 0, không phải số)."""
    vg = vung_dang_dung(_nap().get(str(ma)))
    if vg is None:
        return None
    try:
        v = float(gia_tri)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return v < vg[1] if vg[0] == "duoi" else v >= vg[1]


def nguong(trong: list[float], ngoai: list[float]) -> dict[str, Any]:
    """Ngưỡng tách số đo lúc người TRONG khu với lúc người ở khu bên cạnh, theo độ đúng CÂN BẰNG (hai nhãn
    nặng như nhau — nhãn đông không được lấn)."""
    if not trong or not ngoai:
        return {"dung": 0.0}
    st, sn = sorted(trong), sorted(ngoai)
    tot = {"dung": 0.0}
    for t in sorted(set(st) | set(sn))[1:]:
        a = bisect.bisect_left(st, t) / len(st)
        b = (len(sn) - bisect.bisect_left(sn, t)) / len(sn)
        for huong, d in (("duoi", (a + b) / 2), ("tren", (2 - a - b) / 2)):
            if d > tot["dung"]:
                tot = {"dung": round(d, 3), "huong": huong, "nguong": round(t, 2)}
    return tot


def _luc(ts: list[float], chuoi: list[tuple[float, str]], t: float) -> str:
    i = bisect.bisect_right(ts, t) - 1
    return chuoi[i][1] if i >= 0 else ""


def ti_le_bat(chuoi: list[tuple[float, str]], tu: float, den: float) -> float:
    """Phần thời gian trong [tu, den) chuỗi trạng thái ở «on» (giá trị trước ``tu`` kéo dài tới mốc đầu)."""
    if den <= tu:
        return 0.0
    bat, cu, t0 = 0.0, "", tu
    for t, g in chuoi:
        t = min(max(t, tu), den)
        if cu == "on":
            bat += t - t0
        cu, t0 = g, t
    if cu == "on":
        bat += den - t0
    return bat / (den - tu)


def nguon_lay(kc: list[tuple[float, str]], radar: list[tuple[float, str]], cam: list[list[tuple[float, str]]],
              ke: dict[str, list[tuple[float, str]]]) -> list[str]:
    """Khu bên cạnh nào radar khu này hay báo LÂY: lúc radar khu này báo (có số đo) mà camera khu không thấy ai,
    radar khu kia báo có người ít nhất LAY phần số lần, và hơn lúc camera thấy người ít nhất LAY_CHENH."""
    moc = {id(c): [x[0] for x in c] for c in [radar, *cam, *ke.values()]}
    n = {False: 0, True: 0}
    dem = {k: {False: 0, True: 0} for k in ke}
    for t, g in kc:
        try:
            if float(g) <= 0:
                continue
        except ValueError:
            continue
        if _luc(moc[id(radar)], radar, t) != "on":
            continue
        thay = any(_luc(moc[id(c)], c, t) == "on" for c in cam)
        n[thay] += 1
        for k, c in ke.items():
            dem[k][thay] += _luc(moc[id(c)], c, t) == "on"
    if not n[False]:
        return []
    ra = []
    for k, v in dem.items():
        khong = v[False] / n[False]
        co = v[True] / n[True] if n[True] else 0.0
        if khong >= LAY and khong - co >= LAY_CHENH:
            ra.append(k)
    return ra


def gan_nhan(kc: list[tuple[float, str]], radar: list[tuple[float, str]], cam: list[list[tuple[float, str]]],
             ke: list[list[tuple[float, str]]]) -> tuple[list[float], list[float]]:
    """(số đo lúc người TRONG khu, số đo lúc người ở KHU BÊN CẠNH). Chỉ xét lúc radar khu báo có người và số
    đo khác 0. Trong khu: camera khu thấy người VÀ không radar khu bên cạnh nào báo. Khu bên cạnh: camera khu
    KHÔNG thấy ai VÀ có radar khu bên cạnh báo."""
    trong, ngoai = [], []
    moc = {id(c): [x[0] for x in c] for c in [radar, *cam, *ke]}

    def luc(c: list[tuple[float, str]], t: float) -> str:
        return _luc(moc[id(c)], c, t)
    for t, g in kc:
        try:
            v = float(g)
        except ValueError:
            continue
        if v <= 0 or luc(radar, t) != "on":
            continue
        thay = any(luc(c, t) == "on" for c in cam)
        ben = any(luc(k, t) == "on" for k in ke)
        if thay and not ben:
            trong.append(v)
        elif not thay and ben:
            ngoai.append(v)
    return trong, ngoai


def cap_radar() -> list[dict[str, Any]]:
    """Radar có số khoảng cách: cảm biến ĐỘ DÀI (device_class distance hoặc đơn vị m/cm/mm) cùng THIẾT BỊ với
    một cảm biến hiện diện — nhận theo sổ thiết bị HA, không theo tên. Kèm camera và radar khu bên cạnh."""
    from services import boi_canh_nha, cam_bien_ghep, ha_client, so_do_nha

    st = ha_client.get_states() or []
    idx = ha_client.get_ha_area_index() or {}
    nen = idx.get("entity_platform") or {}
    tb = {m: tuple(v) for m, v in (idx.get("entity_device_ids") or {}).items() if v}
    radar = {}
    for s in st:
        ma, a = str(s["entity_id"]), s.get("attributes") or {}
        if (ma.startswith("binary_sensor.") and a.get("device_class") in _LOP_HIEN_DIEN and nen.get(ma) != "frigate"
                and not cam_bien_ghep.la_ghep(ma) and ma in tb):
            radar[tb[ma]] = ma
    khu_radar = {m: boi_canh_nha.phong_cua(m) for m in radar.values()}
    cam = {}
    for s in st:
        ma = str(s["entity_id"])
        if nen.get(ma) == "frigate" and ma.startswith("binary_sensor.") and ma.endswith(_DUOI_NGUOI_FRIGATE):
            cam.setdefault(boi_canh_nha.phong_cua(ma), []).append(ma)
    so_do = so_do_nha.ap() or {}
    ra = []
    for s in st:
        ma, a = str(s["entity_id"]), s.get("attributes") or {}
        if not ma.startswith("sensor.") or not (a.get("device_class") == "distance"
                                                or a.get("unit_of_measurement") in ("m", "cm", "mm")):
            continue
        r = radar.get(tb.get(ma, ()))
        khu = khu_radar.get(r) if r else None
        if not khu:
            continue
        p = next((x for x in so_do.get("phong") or [] if x.get("ten") == khu), None)
        noi = set((p or {}).get("thong_voi") or []) | set((p or {}).get("cua_sang") or []) if p else None
        ke = [m for m, k in khu_radar.items() if k and k != khu and (noi is None or k in noi)]
        ra.append({"ma": ma, "radar": r, "khu": khu, "cam": cam.get(khu, []), "ke": ke,
                   "don_vi": a.get("unit_of_measurement") or "m"})
    return ra


def hoc(so_ngay: int = NGAY) -> dict[str, Any]:
    """Học lại vùng của mọi radar có số khoảng cách. Gọi trong lượt học hằng ngày, TRƯỚC bài «có người thật»
    (đề bài đó bày vùng vừa học)."""
    from services.canh_bao_nha import _lich_su_ha

    ket: dict[str, Any] = {}
    for x in cap_radar():
        if not x["cam"] or not x["ke"]:
            ket[x["ma"]] = {"khu": x["khu"], "radar": x["radar"], "dat": False,
                            "ly_do": "khu không có camera Frigate để gắn nhãn" if not x["cam"]
                            else "không có radar khu bên cạnh"}
            continue
        try:
            ls = _lich_su_ha([x["ma"], x["radar"], *x["cam"], *x["ke"]], time.time() - so_ngay * 86400)
        except Exception as exc:  # noqa: BLE001 — HA không trả lịch sử thì giữ vùng cũ
            logger.warning({"event": "vung_khoang_cach_loi", "ma": x["ma"], "loi": str(exc)[:120]})
            continue
        tu = time.time() - so_ngay * 86400
        ke = [k for k in x["ke"] if ti_le_bat(ls.get(k, []), tu, time.time()) <= KET]
        ke = nguon_lay(ls.get(x["ma"], []), ls.get(x["radar"], []), [ls.get(c, []) for c in x["cam"]],
                       {k: ls.get(k, []) for k in ke})
        trong, ngoai = gan_nhan(ls.get(x["ma"], []), ls.get(x["radar"], []),
                                [ls.get(c, []) for c in x["cam"]], [ls.get(k, []) for k in ke])
        t = nguong(trong, ngoai)
        dat = len(trong) >= MAU_TOI_THIEU and len(ngoai) >= MAU_TOI_THIEU and t["dung"] >= CONG
        ket[x["ma"]] = {"khu": x["khu"], "radar": x["radar"], "don_vi": x["don_vi"], "nhan": x["cam"],
                        "ke": ke, "n_trong": len(trong), "n_ngoai": len(ngoai), "dat": dat, "luc": time.time(),
                        **{k: t[k] for k in ("dung", "huong", "nguong") if k in t}}
    with _khoa:
        for m, v in _nap().items():          # số chủ máy đặt sống qua lần học lại
            if v.get("nguong_chu") is not None and m in ket:
                ket[m]["nguong_chu"] = v["nguong_chu"]
        _nap().clear()
        _nap().update(ket)
        _luu()
    logger.info({"event": "vung_khoang_cach_hoc", "dat": [m for m, v in ket.items() if v.get("dat")],
                 "so": len(ket)})
    return ket


def cho_de(khu: str) -> list[dict[str, Any]]:
    """Vùng đang dùng của radar trong ``khu`` (học đạt, hoặc chủ máy đặt) — bày trong đề bài «có người thật»."""
    ra = []
    for m, v in ds().items():
        vg = vung_dang_dung(v)
        if v.get("khu") == khu and vg:
            ra.append({"ma": m, **v, "huong": vg[0], "nguong": vg[1]})
    return ra


def _reset_for_tests(duong: Path) -> None:
    global _dl, _PATH
    _dl, _PATH = None, duong
