"""Bot tự XÁC MINH trước khi bật/tắt và tự CHẤM sau khi làm — hỏi người dùng ít dần.

Chủ máy 01/10/2026: "Việc xác nhận đúng hay không nên dùng qua các ngoại vi như cảm biến, camera, bếp,
yolo, vision vào những khung giờ lệch sinh hoạt"; "việc bật hay tắt nên giảm dần phụ thuộc vào người dùng
vì có rất nhiều cảm biến, cam để check"; "với nhà tôi thì thế nhưng nhà khác thì chỉ có mỗi cảm biến
chuyển động hoặc hiện diện"; "dạy cho bot phải đúng, đủ các trường hợp".

Đo 14 ngày trước đó (`du_doan_nha`, đèn trần / quạt phòng khách / đèn phòng ngủ — 66 lượt): bot tự tắt
bị bật lại 11/31 lần (vắng 3–9 phút trong khi người ngồi yên, radar mất dấu); bot HỎI 11 lần thì 7 lần
không ai trả lời. Hỏi người không phải đường xác minh dùng được.

Mỗi thiết bị một bài: bot đọc những NGUỒN nhà đó có (camera + YOLO, radar, cảm biến chuyển động, khoảng
cách radar, máy theo người, đọc ảnh) cùng lịch sinh hoạt, rồi chọn nguồn nào xác minh trước khi bật, trước
khi tắt, thêm gì lúc giờ lệch lịch, khi nào mới hỏi người, và nguồn nào tự chấm đúng/sai sau khi làm. Code
chỉ bày đủ dữ kiện và kiểm biên (mã có thật trong đề); chọn gì là việc của bot theo hướng dẫn
`huong_dan_hoc/chon_xac_minh.md`.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

#: Loại nguồn — tên bày trong đề, cùng điều nó CHỨNG MINH được (bot đọc ở hướng dẫn).
LOAI = {
    "camera": "camera — YOLO đếm người trong vùng của khu",
    "camera_nguoi": "cảm biến người của camera (Frigate)",
    "hien_dien": "cảm biến hiện diện / radar",
    "chuyen_dong": "cảm biến chuyển động",
    "khoang_cach": "khoảng cách người tới radar",
    "mang": "máy theo người (điện thoại, laptop)",
    "anh": "đọc ảnh camera bằng model (chậm)",
}
HOI = ("khong", "khi_khong_ro", "luon")
HUONG = ("bat", "tat")
#: Tối đa ngần này nguồn mỗi danh sách — xác minh bằng cả chục nguồn là chưa chọn.
TOI_DA = 6
#: Bật NGAY rồi KIỂM LẠI (`bat.kiem_lai`) mỗi ngần này giây khi cảm biến khu hay báo ảo — số của chủ máy
#: 01/10/2026: "kiểm tra theo chu kỳ 2p 1 lần nếu gặp tình trạng nhiễu của cảm biến".
KIEM_LAI_GIAY = 120


def de(uv: dict[str, Any], ten_tb: str, dan: list[str]) -> str:
    """Đề cho MỘT thiết bị. ``uv``: tb, khu, loai_tb, nguy_hiem, noi, so_do (dòng), nguon (danh sách
    {ma, ten, loai, khu, ghi_chu}), camera (danh sách {ten, thay, ghi_chu}), lich (dòng), ket_qua (dòng)."""
    dong = [f"A. THIẾT BỊ: {ten_tb} ({uv['tb']}) — {uv.get('loai_tb') or 'thiết bị'} ở khu {uv['khu']}"
            + (f", nơi: {uv['noi']}" if uv.get("noi") else "")
            + (" — NGUY HIỂM nếu bật/tắt nhầm (nhiệt, lửa, nước nóng, khoá)" if uv.get("nguy_hiem") else "")]
    dong += ["\nB. NGUỒN BOT ĐỌC ĐƯỢC (mã | loại | khu | ghi chú):"]
    dong += [f"- {x['ma']} | {LOAI.get(x['loai'], x['loai'])} | {x.get('khu') or '—'} | {x.get('ghi_chu') or '—'}"
             for x in uv.get("nguon") or []] or ["(không có)"]
    dong += ["\nC. CAMERA (tên | thấy khu nào — theo sơ đồ đã chấm | ghi chú):"]
    dong += [f"- {c['ten']} | {', '.join(c.get('thay') or []) or 'không thấy khu nào trong nhà'} | "
             f"{c.get('ghi_chu') or '—'}" for c in uv.get("camera") or []] or ["(không có camera)"]
    dong += ["\nD. LỊCH SINH HOẠT:"] + ([f"- {x}" for x in uv.get("lich") or []] or ["(chưa khai)"])
    dong += ["\nE. KẾT QUẢ GẦN ĐÂY của thiết bị này:"] + ([f"- {x}" for x in uv.get("ket_qua") or []]
                                                       or ["(chưa có)"])
    dong += ["\nF. SƠ ĐỒ NHÀ:"] + ([f"- {x}" for x in uv.get("so_do") or []] or ["(chưa có)"])
    if dan:
        dong += ["\nCHỦ NHÀ DẶN:"] + [f"- {x}" for x in dan]
    return "\n".join(dong)


def _ds(x: Any, co: set[str], ten: str) -> list[str] | str:
    if x is None:
        return []
    if not isinstance(x, list):
        return f"{ten} phải là danh sách mã"
    la = [m for m in x if str(m) not in co]
    if la:
        return f"{ten} có mã không có trong đề: {la!r}"
    if len(x) > TOI_DA:
        return f"{ten} quá {TOI_DA} nguồn"
    return [str(m) for m in x]


def kiem(data: Any, uv: dict[str, Any]) -> dict[str, Any] | str:
    """Loại bài sai khuôn hoặc nhắc mã không có trong đề; đúng/sai về nội dung là việc người chấm."""
    if not isinstance(data, dict):
        return "không phải JSON object"
    co = {str(x["ma"]) for x in uv.get("nguon") or []} | {str(c["ten"]) for c in uv.get("camera") or []}
    ra: dict[str, Any] = {}
    for h in HUONG:
        x = data.get(h)
        if not isinstance(x, dict):
            return f"{h} phải là object"
        if x.get("hoi") not in HOI:
            return f"{h}.hoi phải là một trong {HOI}"
        y: dict[str, Any] = {"hoi": x["hoi"]}
        for k in ("xac_minh", "lech_lich") + (("nha_vang",) if h == "tat" else ("kiem_lai",)):
            v = _ds(x.get(k), co, f"{h}.{k}")
            if isinstance(v, str):
                return v
            y[k] = v
        ra[h] = y
    tc = data.get("tu_cham")
    if not isinstance(tc, dict):
        return "tu_cham phải là object {bat, tat}"
    ra["tu_cham"] = {}
    for h in HUONG:
        v = _ds(tc.get(h), co, f"tu_cham.{h}")
        if isinstance(v, str):
            return v
        ra["tu_cham"][h] = v
    try:
        chac = min(1.0, max(0.0, float(data.get("chac"))))
    except (TypeError, ValueError):
        chac = 0.0
    ra.update(chac=round(chac, 2), vi_sao=str(data.get("vi_sao") or "")[:500])
    return ra


# ── Chạy thật (B3): đề nhà thật, giải, chấm, áp, xác minh lúc sống ─────────
_PATH = Path(DATA_DIR) / "agent" / "xac_minh_nha.json"
_khoa = threading.RLock()
_dl: dict[str, Any] | None = None
#: Cảm biến báo có người quá ngần này phần 3 ngày qua là KẸT (ghi chú cho bot, cùng số `so_do_nha._KET`).
_KET = 0.98
_DUOI_NGUOI_FRIGATE = "_person_occupancy"


def _nap() -> dict[str, Any]:
    global _dl
    if _dl is None:
        try:
            _dl = json.loads(_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _dl = {}
        _dl.setdefault("bai", {})
    return _dl


def _luu() -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_nap(), ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_PATH)


def so() -> dict[str, Any]:
    with _khoa:
        return json.loads(json.dumps(_nap()))


def ap(tb: str) -> dict[str, Any] | None:
    """Bài ĐANG ÁP của thiết bị = bài mới nhất đã chấm ĐÚNG (chưa chấm thì không áp — giáo viên / chủ máy chấm)."""
    with _khoa:
        return next((b["gia_tri"] for b in reversed(_nap()["bai"].get(tb) or []) if b.get("ket_qua") == "dung"), None)


def _camera_thay() -> dict[str, list[str]]:
    """Camera → khu nó thấy: chủ nhà khoanh trên ảnh trước, không có thì bài sơ đồ gần nhất của bot (chưa chấm)."""
    from services import camera_nha, so_do_nha
    k = so_do_nha.khoanh()
    moi = next((b["gia_tri"] for b in reversed(so_do_nha.so().get("bai") or []) if b.get("ket_qua") != "sai"), {})
    ve = {c.get("ten"): list((c.get("thay") or {}).keys()) for c in (moi or {}).get("camera") or []}
    return {str(c["name"]): list(((k.get(str(c["name"])) or {}).get("phong") or {}).keys()) or ve.get(str(c["name"])) or []
            for c in camera_nha.danh_sach()}


def do(tb: str) -> dict[str, Any]:
    """Đề NHÀ THẬT cho một thiết bị — cùng khuôn `de` của bộ đề luyện."""
    import sqlite3
    from services import (boi_canh_nha, cam_bien_ghep, du_doan_nha as dd, ha_client, kich_hoat_nha as kh,
                          lich_sinh_hoat, lich_su_nha, so_do_nha, vung_khoang_cach)
    st = ha_client.get_states() or []
    nen = (ha_client.get_ha_area_index() or {}).get("entity_platform") or {}
    ten = {str(s["entity_id"]): str((s.get("attributes") or {}).get("friendly_name") or s["entity_id"]) for s in st}
    khu = boi_canh_nha.phong_cua(tb) or "chưa xếp khu"
    bao_ao = {m for cd in (kh._nap().get("mo_hinh") or {}).values() for m in ((cd.get("nhieu") or {}).get("song") or [])}
    den = time.time()
    ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    nguon: list[dict[str, str]] = []
    try:
        from services.co_nguoi_nha import _dong
        for s in st:
            ma, a = str(s["entity_id"]), s.get("attributes") or {}
            mien, lop = ma.split(".")[0], a.get("device_class")
            if mien == "binary_sensor" and lop in kh._LOP_HIEN_DIEN and not cam_bien_ghep.la_ghep(ma):
                fr = nen.get(ma) == "frigate"
                loai = ("camera_nguoi" if ma.endswith(_DUOI_NGUOI_FRIGATE) else "chuyen_dong") if fr else \
                       ("chuyen_dong" if lop == "motion" else "hien_dien")
                ghi = [ten.get(ma, ma)] + (["của camera Frigate — chuyển động khung hình, không phải người"]
                                           if fr and loai == "chuyen_dong" else [])
                ts, gt = _dong(ro, ma, den - 3 * 86400, den)
                if ts and _ti_le(ts, gt, den - 3 * 86400, den) > _KET:
                    ghi.append("KẸT «có người» 3 ngày nay")
                if ma in bao_ao:
                    ghi.append("hay báo ẢO (báo có người mà camera không thấy ai)")
                nguon.append({"ma": ma, "loai": loai, "khu": boi_canh_nha.phong_cua(ma) or "", "ghi_chu": "; ".join(ghi)})
            elif mien in ("device_tracker", "person"):
                nguon.append({"ma": ma, "loai": "mang", "khu": "", "ghi_chu": ten.get(ma, ma)})
    finally:
        ro.close()
    vung = vung_khoang_cach.ds()
    for x in vung_khoang_cach.cap_radar():
        v = vung.get(x["ma"]) or {}
        vg = vung_khoang_cach.vung_dang_dung(v)
        nguon.append({"ma": x["ma"], "loai": "khoang_cach", "khu": x["khu"],
                      "ghi_chu": (f"cùng radar {ten.get(x['radar'], x['radar'])}; vùng khu "
                                  f"{'chủ nhà đặt' if v.get('nguong_chu') is not None else 'đã học'}: "
                                  f"{'dưới' if vg[0] == 'duoi' else 'từ'} {vg[1]:g} m"
                                  + ("" if v.get("nguong_chu") is not None
                                     else f", tách đúng {round(100 * float(v.get('dung') or 0))}%")) if vg
                                 else f"cùng radar {ten.get(x['radar'], x['radar'])}; CHƯA học được vùng"})
    camera = [{"ten": c, "thay": t, "ghi_chu": "theo vùng chủ nhà khoanh / sơ đồ bot vẽ"}
              for c, t in _camera_thay().items()]
    ket_qua = []
    for hd, ten_hd in (("on", "bật"), ("off", "tắt")):
        r = [x for x in kh._nhan_da_cham(tb, hd) if x[0] > den - 14 * 86400]
        lam = [x for x in r if x[1].endswith(":tu_lam")]
        hoi = [x for x in r if x[1].endswith(":hoi")]
        if lam:
            ket_qua.append(f"14 ngày: tự {ten_hd} {len(lam)} lần, sai {sum(x[1].startswith('sai') for x in lam)}")
        if hoi:
            ket_qua.append(f"14 ngày: hỏi {ten_hd} {len(hoi)} lần, không ai trả lời "
                           f"{sum(x[1].startswith('lo') for x in hoi)}")
    return {"tb": tb, "khu": khu, "loai_tb": tb.split(".")[0], "noi": "",
            # ĐÚNG đầu vào chốt lúc chạy dùng (`kich_hoat_nha._ten_tt`): đưa cả tên thân thiện vào thì «Đèn CỬA sổ»
            # khớp «cua» (khoá cửa) — đo 01/10/2026, bài đèn cửa sổ thành «luôn hỏi» vì đề ghi NGUY HIỂM.
            "nguy_hiem": dd._cam_tu_lam(kh._ten_tt(tb, "on")), "nguon": nguon, "camera": camera,
            "lich": lich_sinh_hoat.doc_cho_bot(), "ket_qua": ket_qua, "so_do": so_do_nha.doan_de(khu),
            "ten_tb": ten.get(tb, tb)}


def _ti_le(ts: list[float], gt: list[str], tu: float, den: float) -> float:
    bat, a = 0.0, None
    for t, g in zip(ts, gt):
        if g == "on" and a is None:
            a = max(t, tu)
        elif g != "on" and a is not None:
            bat += max(0.0, t - a)
            a = None
    if a is not None:
        bat += den - a
    return bat / max(1.0, den - tu)


def _dan(tb: str) -> list[str]:
    with _khoa:
        return [f"({'giáo viên ' if b.get('cham_boi') == 'claude' else ''}chấm "
                f"{'đúng' if b['ket_qua'] == 'dung' else 'sai'}) {b['ghi_chu']}"
                for b in (_nap()["bai"].get(tb) or []) if b.get("ghi_chu") and b.get("ket_qua") in ("dung", "sai")][-5:]


def giai(chi: list[str]) -> dict[str, Any]:
    """Bot giải bài xác minh cho từng thiết bị trong ``chi``; ghi sổ ở trạng thái chờ chấm."""
    from services import hieu_thiet_bi_nha as ht
    from services.thoi_quen_nha import _hoi_bot
    huong, ban = ht.huong_dan("chon_xac_minh")
    model = ht._model()
    ra, loi = [], []
    for tb in chi:
        uv = do(tb)
        b = _hoi_bot(ht, model, huong, de(uv, uv["ten_tb"], _dan(tb)))
        k = kiem(b, uv) if not isinstance(b, str) else b
        if isinstance(k, str):
            loi.append({"thiet_bi": tb, "loi": k})
            continue
        with _khoa:
            ds = _nap()["bai"].setdefault(tb, [])
            id_ = max((x["id"] for v in _nap()["bai"].values() for x in v), default=0) + 1
            ds.append({"id": id_, "luc": time.time(), "huong_dan": ban, "gia_tri": k, "ket_qua": "cho"})
            del ds[:-10]
            _luu()
        ra.append({"thiet_bi": tb, "id": id_, "gia_tri": k})
    return {"ok": True, "bai": ra, "loi": loi}


def lua_chon(tb: str) -> dict[str, Any]:
    """Cho trang web: bài đang áp và mọi nguồn chủ máy chọn được (đúng những mã bài bot được phép dùng)."""
    uv = do(tb)
    nguon = [{"ma": x["ma"], "loai": LOAI.get(x["loai"], x["loai"]), "khu": x.get("khu") or "",
              "ten": str(x.get("ghi_chu") or x["ma"]).split(";")[0]} for x in uv["nguon"]]
    nguon += [{"ma": c["ten"], "loai": LOAI["camera"], "khu": ", ".join(c.get("thay") or []), "ten": c["ten"]}
              for c in uv["camera"]]
    return {"ap": ap(tb), "nguon": nguon, "hoi": list(HOI), "nguy_hiem": bool(uv["nguy_hiem"])}


def sua(tb: str, gia_tri: Any) -> dict[str, Any]:
    """Chủ máy sửa bài trên web (01/10/2026: "các trạng thái, thông số kích hoạt tôi muốn chỉnh trên webui được"):
    kiểm như bài bot giải (mã phải có trong đề của thiết bị), lưu thành bài chủ máy chấm ĐÚNG nên áp ngay; lần bot
    giải sau đọc nó trong «chủ nhà dặn»."""
    k = kiem(gia_tri, do(tb))
    if isinstance(k, str):
        raise ValueError(k)
    with _khoa:
        ds = _nap()["bai"].setdefault(tb, [])
        id_ = max((x["id"] for v in _nap()["bai"].values() for x in v), default=0) + 1
        ds.append({"id": id_, "luc": time.time(), "huong_dan": "chu_may", "gia_tri": k, "ket_qua": "dung",
                   "cham_boi": "chu_may", "ghi_chu": "anh sửa trên web", "cham_luc": time.time()})
        del ds[:-10]
        _luu()
    logger.info({"event": "xac_minh_chu_sua", "thiet_bi": tb, "id": id_})
    return {"id": id_, "gia_tri": k}


def cham(tb: str, id_: int, dung: bool, *, cham_boi: str, ghi_chu: str = "") -> bool:
    with _khoa:
        b = next((x for x in _nap()["bai"].get(tb) or [] if x["id"] == int(id_)), None)
        if b is None:
            return False
        b.update(ket_qua="dung" if dung else "sai", cham_boi=cham_boi, ghi_chu=str(ghi_chu or "")[:300],
                 cham_luc=time.time())
        _luu()
    logger.info({"event": "xac_minh_cham", "thiet_bi": tb, "id": id_, "dung": dung, "cham_boi": cham_boi})
    return True


def xac_minh(nguon: list[str], khu: str) -> tuple[bool | None, str]:
    """Lúc sống: có người trong ``khu`` không, theo các nguồn bài đã chọn. True = có nguồn THẤY người; False = nguồn
    nhìn được và không thấy ai; None = không nguồn nào trả lời được (camera lỗi, khoảng cách chưa học…)."""
    from services import camera_nha, ha_client, kich_hoat_nha as kh, vung_khoang_cach
    cam = {str(c["name"]) for c in camera_nha.danh_sach()}
    tt = {str(s["entity_id"]): str(s.get("state") or "").lower() for s in kh._trang_thai_ha()}
    da_xem: list[str] = []
    for m in nguon:
        if m in cam:
            thay = kh._nhin_lai([m], khu)
            if thay:
                return True, f"{m}: {thay}"
            if thay == "":
                da_xem.append(m)
        elif m.startswith("sensor."):
            v = vung_khoang_cach.vi_tri(m, (ha_client.get_state(m) or {}).get("state"))
            if v:
                return True, f"khoảng cách radar trong vùng {khu}"
            if v is False:
                da_xem.append(m)
        elif m.startswith("binary_sensor."):
            # Radar đã học vùng khoảng cách: «có người» chỉ tính khi khoảng cách của CHÍNH nó không cho thấy người
            # đứng ngoài vùng — không thì người ở bếp làm radar phòng khách giữ đèn (đúng thứ khoảng cách để loại).
            ngoai = any(vung_khoang_cach.vi_tri(d, (ha_client.get_state(d) or {}).get("state")) is False
                        for d, v in vung_khoang_cach.ds().items() if v.get("radar") == m)
            if tt.get(m) == "on" and not ngoai:
                return True, f"{m} báo có người"
            if tt.get(m) == "off" or ngoai:
                da_xem.append(m)
    return (False, "không nguồn nào thấy người: " + ", ".join(da_xem)) if da_xem else (None, "không nguồn nào nhìn được")


def nguon_luc(huong: dict[str, Any], luc: float) -> list[str]:
    """Nguồn xác minh của một chiều lúc ``luc``: `xac_minh`, cộng `lech_lich` khi lịch nói cả nhà VẮNG hay NGỦ mà
    vẫn có chuyện cần bật/tắt — giờ lệch lịch (chủ máy: "vợ tôi đôi khi làm buổi chiều, sáng có ở nhà")."""
    from services import lich_sinh_hoat
    ds = list(huong.get("xac_minh") or [])
    if huong.get("lech_lich") and (lich_sinh_hoat.ca_nha("vang", luc) or lich_sinh_hoat.ca_nha("ngu", luc)):
        ds += [m for m in huong["lech_lich"] if m not in ds]
    return ds


def _reset_for_tests(duong: Path) -> None:
    global _dl, _PATH
    _dl, _PATH = None, duong
