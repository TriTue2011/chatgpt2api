"""SƠ ĐỒ NHÀ — bot tự hiểu nhà mình: kiểu nhà, phòng, phòng nào thông / có vách với phòng nào, cửa
chính mở vào đâu, và phần nào của khung hình mỗi camera là phòng nào.

Chủ máy 29/09/2026: "Việc train này có 1 điều đang bỏ sót đó chính là sơ đồ nhà tôi. Đó mới là
điều để bot đánh giá thiết bị nào phù hợp cho điều khiển và ngoại vi … nhà chung cư hay nhà mặt đất
… bố trí … có thể lấy qua bản vẽ, qua lời mô tả, qua cam, thiết bị. Nhưng hiện nay có yolo thì việc
xác định tọa độ là tốt nhất. Ví dụ danh giới phòng khách và bếp, vị trí của cửa phòng A."

Cùng khung các tầng học khác: CODE đo và bày bằng chứng, BOT (hướng dẫn `hieu_so_do_nha.md`) viết
sơ đồ, người chấm (chủ nhà / giáo viên) rồi mới ÁP. Bằng chứng code đo:

* Phòng và thiết bị theo khu vực của Home Assistant.
* CÙNG BÁO: hai phòng hay có người cùng lúc — sóng radar xuyên vách, hoặc hai phòng thông nhau.
* LƯỚI CAMERA: 30 ngày sự kiện người của Frigate (hộp toạ độ) → điểm CHÂN người rơi vào ô nào của
  lưới 8×6 (A–H × 1–6), lúc đó radar của phòng nào báo có người MỘT MÌNH. Đo 29/09/2026: camera
  phòng khách cột A–B phần lớn trùng lúc chỉ radar bếp báo — góc bếp trong khung hình.
* CỬA: cửa chính mở rồi phòng nào có người đầu tiên.
* Lời chủ nhà mô tả (và bản vẽ, qua lời mô tả của model thị giác).
"""

from __future__ import annotations

import bisect
import json
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

_PATH = Path(DATA_DIR) / "agent" / "so_do_nha.json"
_khoa = threading.RLock()
NGAY = 30
#: Lưới trên khung hình camera: cột A–H, hàng 1–6 (1 = mép trên).
COT, HANG = 8, 6
#: Ô có ít hơn ngần này mẫu thì không bày — một hai lần trùng không nói lên phòng nào.
O_TOI_THIEU = 20
#: Cửa mở rồi trong ngần này giây phòng nào có người đầu tiên.
CUA_GIAY = 60
#: Cảm biến báo có người quá ngần này thời gian là KẸT (cùng số `co_nguoi_nha._KET`).
_KET = 0.98
_LOP_HIEN_DIEN = ("occupancy", "presence", "motion")
_LOP_CUA = ("door", "garage_door", "opening")


# ── Sổ ──────────────────────────────────────────────────────────────────────
def _nap() -> dict[str, Any]:
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("mo_ta", [])
    d.setdefault("bai", [])
    d.setdefault("ap", None)
    return d


def _luu(d: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_PATH)


def so() -> dict[str, Any]:
    with _khoa:
        return _nap()


def them_mo_ta(noi_dung: str, nguon: str = "chu_may") -> int:
    """Lời chủ nhà mô tả nhà (hoặc bản mô tả bản vẽ của model thị giác). Trả số thứ tự."""
    noi_dung = str(noi_dung or "").strip()
    if not noi_dung:
        raise ValueError("Mô tả rỗng.")
    with _khoa:
        d = _nap()
        d["mo_ta"].append({"luc": time.time(), "nguon": nguon, "noi_dung": noi_dung[:4000]})
        _luu(d)
        return len(d["mo_ta"])


def ap() -> dict[str, Any] | None:
    """Sơ đồ đang dùng (đã chấm đúng), hoặc None."""
    with _khoa:
        return _nap().get("ap")


# ── Đo ──────────────────────────────────────────────────────────────────────
def o_cua(x: float, y: float) -> str:
    """Điểm (0–1) → tên ô "A1".."H6"."""
    c = min(COT - 1, max(0, int(x * COT)))
    h = min(HANG - 1, max(0, int(y * HANG)))
    return f"{chr(ord('A') + c)}{h + 1}"


def frigate_url() -> str:
    from services import nhin_nha
    return str(nhin_nha._muc("frigate").get("url") or "").rstrip("/")


def _frigate(duong: str, timeout: float = 60.0) -> Any:
    goc = frigate_url()
    if not goc:
        raise RuntimeError("chưa khai địa chỉ Frigate (nhin_nha.frigate.url)")
    with urllib.request.urlopen(goc + duong, timeout=timeout) as r:  # noqa: S310 — địa chỉ nội bộ chủ máy khai
        return json.loads(r.read())


def diem_chan(hop: list[float]) -> tuple[float, float]:
    """Hộp REST của Frigate ``(x, y, w, h)`` TỈ LỆ 0–1 → điểm chân người (giữa đáy hộp).
    ⚠️ Bản tin MQTT dùng PIXEL ``(x1, y1, x2, y2)`` — đừng lẫn (xem `canh_camera_nha._hop_tu_frigate`)."""
    x, y, w, h = (float(v) for v in hop[:4])
    return x + w / 2, min(1.0, y + h)


def _dong(ro: sqlite3.Connection, ma: str, tu: float, den: float) -> tuple[list[float], list[str]]:
    from services.co_nguoi_nha import _dong as dong
    return dong(ro, ma, tu, den)


def _luc(ts: list[float], gt: list[str], t: float) -> str:
    i = bisect.bisect_right(ts, t) - 1
    return gt[i] if i >= 0 else ""


def do(den: float | None = None) -> dict[str, Any]:
    """Mọi bằng chứng cho đề. Không gọi được Frigate thì bỏ phần lưới camera (ghi lý do)."""
    from services import boi_canh_nha, cam_bien_ghep, camera_nha, ha_client, lich_su_nha

    den = den or time.time()
    tu = den - NGAY * 86400
    st = ha_client.get_states() or []
    idx = ha_client.get_ha_area_index() or {}
    nen = idx.get("entity_platform") or {}
    ten = {str(s["entity_id"]): str((s.get("attributes") or {}).get("friendly_name") or s["entity_id"]) for s in st}
    phong: dict[str, dict[str, list[str]]] = {}
    hien, cua = [], []
    for s in st:
        ma = str(s["entity_id"])
        khu = boi_canh_nha.phong_cua(ma)
        lop = (s.get("attributes") or {}).get("device_class")
        if ma.startswith("binary_sensor.") and lop in _LOP_CUA:
            cua.append(ma)
        if not khu:
            continue
        p = phong.setdefault(khu, {"hien_dien": [], "thiet_bi": []})
        if ma.startswith("binary_sensor.") and lop in _LOP_HIEN_DIEN and not cam_bien_ghep.la_ghep(ma):
            p["hien_dien"].append(ma)
            # Cảm biến sinh từ CHÍNH camera (tích hợp Frigate) không dùng để gắn nhãn phòng cho điểm
            # trên camera — tự khẳng định vòng quanh.
            if nen.get(ma) != "frigate":
                hien.append((ma, khu))
        elif ma.split(".")[0] in ("light", "switch", "fan", "climate", "media_player", "cover"):
            p["thiet_bi"].append(ma)

    ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    try:
        dong = {m: _dong(ro, m, tu, den) for m, _ in hien}
        dong_cua = {m: _dong(ro, m, tu, den) for m in cua}
    finally:
        ro.close()

    def ty_le_bat(m: str) -> float:
        ts, gt = dong[m]
        bat, a = 0.0, None
        for t, g in zip(ts, gt):
            if g == "on" and a is None:
                a = max(t, tu)
            elif g != "on" and a is not None:
                bat += max(0.0, t - a)
                a = None
        if a is not None:
            bat += den - a
        return bat / (den - tu)

    ket = {m for m, _ in hien if dong[m][0] and ty_le_bat(m) > _KET}
    radar = [(m, k) for m, k in hien if m not in ket and dong[m][0]]
    khu_ds = sorted({k for _, k in radar})

    def khu_co_nguoi(t: float) -> set[str]:
        return {k for m, k in radar if _luc(*dong[m], t) == "on"}

    # 1. Cùng báo giữa hai phòng: lấy mẫu mỗi phút.
    dem: Counter = Counter()
    rieng: Counter = Counter()
    t = tu
    while t < den:
        co = khu_co_nguoi(t)
        for k in co:
            rieng[k] += 1
            for k2 in co:
                if k2 != k:
                    dem[(k, k2)] += 1
        t += 60
    cung_bao = sorted(({"a": a, "b": b, "ty_le": round(n / rieng[a], 2)} for (a, b), n in dem.items()
                       if rieng[a] and n / rieng[a] >= 0.1), key=lambda d: -d["ty_le"])

    # 2. Lưới camera từ sự kiện người của Frigate.
    camera: dict[str, Any] = {}
    loi_camera = ""
    try:
        for c in camera_nha.danh_sach():
            src = str(c.get("src") or "")
            if not src:
                continue
            ev = _frigate(f"/api/events?camera={urllib.parse.quote(src)}&label=person&limit=100000&after={int(tu)}")
            luoi: dict[str, Counter] = {}
            for e in ev:
                hop = (e.get("data") or {}).get("box")
                if not hop:
                    continue
                co = khu_co_nguoi(float(e["start_time"]) + 1)
                if len(co) != 1:
                    continue
                luoi.setdefault(o_cua(*diem_chan(hop)), Counter())[next(iter(co))] += 1
            camera[str(c["name"])] = {o: dict(cnt) for o, cnt in luoi.items() if sum(cnt.values()) >= O_TOI_THIEU}
    except Exception as exc:  # noqa: BLE001 — không có Frigate thì vẫn đo phần khác
        loi_camera = str(exc)[:160]

    # 3. Cửa mở rồi phòng nào có người đầu tiên.
    cua_ra: dict[str, Counter] = {}
    for m in cua:
        ts, gt = dong_cua[m]
        for i, (t0, g) in enumerate(zip(ts, gt)):
            if g != "on" or t0 < tu or (i and gt[i - 1] == "on"):
                continue
            dau: tuple[float, str] | None = None
            for mm, k in radar:
                rts, rgt = dong[mm]
                j = bisect.bisect_right(rts, t0)
                while j < len(rts) and rts[j] <= t0 + CUA_GIAY:
                    if rgt[j] == "on":
                        if dau is None or rts[j] < dau[0]:
                            dau = (rts[j], k)
                        break
                    j += 1
            cua_ra.setdefault(m, Counter())[dau[1] if dau else "(không phòng nào)"] += 1

    return {"phong": phong, "khu_radar": khu_ds, "ket": sorted(ket), "cung_bao": cung_bao, "camera": camera,
            "loi_camera": loi_camera, "cua": {m: dict(c) for m, c in cua_ra.items()}, "ten": ten}


# ── Đề ──────────────────────────────────────────────────────────────────────
def de(uv: dict[str, Any], mo_ta: list[str], dan: list[str]) -> str:
    ten = uv.get("ten") or {}
    dong = ["A. PHÒNG theo khu vực Home Assistant (cảm biến có người | thiết bị):"]
    for k, p in sorted(uv["phong"].items()):
        dong.append(f"- {k}: " + (", ".join(ten.get(m, m) for m in p["hien_dien"][:6]) or "—")
                    + " | " + (", ".join(ten.get(m, m) for m in p["thiet_bi"][:8]) or "—"))
    if uv.get("ket"):
        dong.append("(cảm biến kẹt, bỏ: " + ", ".join(ten.get(m, m) for m in uv["ket"]) + ")")
    dong += ["\nB. CÙNG BÁO — phòng A có người thì phòng B cũng có người bao nhiêu phần thời gian:",
             "phòng A | phòng B | cùng báo"]
    dong += [f"{d['a']} | {d['b']} | {round(100 * d['ty_le'])}%" for d in uv["cung_bao"][:20]] or ["(không)"]
    dong += [f"\nC. CAMERA — lưới {COT}×{HANG} trên khung hình (cột A–H trái→phải, hàng 1–6 trên→dưới); mỗi ô là "
             "chỗ CHÂN người đứng, kèm phòng nào có radar báo MỘT MÌNH lúc đó (tỉ lệ, số lần):"]
    if uv.get("loi_camera"):
        dong.append(f"(không đo được: {uv['loi_camera']})")
    for c, luoi in sorted(uv["camera"].items()):
        dong.append(f"- {c}:")
        for o in sorted(luoi, key=lambda o: (o[1], o[0])):
            n = sum(luoi[o].values())
            dong.append(f"  {o}: " + ", ".join(f"{k} {round(100 * v / n)}%" for k, v in
                                                sorted(luoi[o].items(), key=lambda i: -i[1])) + f" ({n})")
    dong += ["\nD. CỬA — mở ra rồi trong 60 giây phòng nào có người đầu tiên:"]
    dong += [f"- {ten.get(m, m)}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items(), key=lambda i: -i[1]))
             for m, c in uv["cua"].items()] or ["(không có cảm biến cửa)"]
    dong += ["\nE. CHỦ NHÀ MÔ TẢ:"] + ([f"- {x}" for x in mo_ta] or ["(chưa có)"])
    if dan:
        dong += ["\nCHỦ NHÀ DẶN (khi chấm các lần trước):"] + [f"- {x}" for x in dan]
    return "\n".join(dong)


# ── Kiểm bài ở biên ─────────────────────────────────────────────────────────
KIEU = ("chung_cu", "nha_dat", "khong_ro")


def kiem(data: Any, uv: dict[str, Any]) -> dict[str, Any] | str:
    """Loại bài sai khuôn; đúng/sai về nội dung là việc người chấm."""
    if not isinstance(data, dict):
        return "không phải JSON object"
    if data.get("kieu") not in KIEU:
        return f"kieu phải là một trong {KIEU}"
    phong = data.get("phong")
    if not isinstance(phong, list) or not phong:
        return "phong phải là danh sách phòng"
    ten_p = set()
    for p in phong:
        if not isinstance(p, dict) or not str(p.get("ten") or "").strip():
            return "mỗi phòng phải có «ten»"
        ten_p.add(str(p["ten"]))
    for p in phong:
        for k in ("thong_voi", "vach_voi"):
            la = [x for x in p.get(k) or [] if x not in ten_p]
            if la:
                return f"{p['ten']}.{k} nhắc phòng không có trong danh sách: {la!r}"
    cam = data.get("camera") or []
    if not isinstance(cam, list):
        return "camera phải là danh sách"
    for c in cam:
        if c.get("ten") not in uv["camera"]:
            return f"camera không có trong đề: {c.get('ten')!r}"
        for k, o in (c.get("thay") or {}).items():
            if k not in ten_p:
                return f"camera {c['ten']} nhắc phòng không có: {k!r}"
            if not all(isinstance(x, str) and len(x) == 2 and "A" <= x[0] <= chr(ord("A") + COT - 1)
                       and "1" <= x[1] <= str(HANG) for x in o):
                return f"camera {c['ten']}: ô phải dạng A1–{chr(ord('A') + COT - 1)}{HANG}"
    try:
        chac = min(1.0, max(0.0, float(data.get("chac"))))
    except (TypeError, ValueError):
        chac = 0.0
    return {"kieu": data["kieu"], "so_tang": data.get("so_tang"), "phong": phong, "cua_chinh": data.get("cua_chinh"),
            "camera": cam, "hoi_chu_nha": [str(x) for x in data.get("hoi_chu_nha") or []][:5],
            "chac": round(chac, 2), "vi_sao": str(data.get("vi_sao") or "")[:500]}


# ── Giải, chấm, áp ──────────────────────────────────────────────────────────
def giai() -> dict[str, Any]:
    """Bot đọc bằng chứng + lời chủ nhà → sơ đồ. Ghi vào sổ ở trạng thái chờ chấm."""
    from services import hieu_thiet_bi_nha as ht
    from services.thoi_quen_nha import _hoi_bot

    uv = do()
    d = so()
    huong, ban = ht.huong_dan("hieu_so_do_nha")
    dan = [f"({'đúng' if b['ket_qua'] == 'dung' else 'sai'}) {b['ghi_chu']}" for b in d["bai"]
           if b.get("ghi_chu") and b.get("ket_qua") in ("dung", "sai")][-5:]
    b = _hoi_bot(ht, ht._model(), huong, de(uv, [x["noi_dung"] for x in d["mo_ta"]], dan))
    k = kiem(b, uv) if not isinstance(b, str) else b
    if isinstance(k, str):
        logger.warning({"event": "so_do_nha_loai", "loi": k})
        return {"ok": False, "loi": k}
    with _khoa:
        d = _nap()
        id_ = (max((x["id"] for x in d["bai"]), default=0) + 1)
        d["bai"].append({"id": id_, "luc": time.time(), "huong_dan": ban, "gia_tri": k, "ket_qua": "cho"})
        d["bai"] = d["bai"][-20:]
        _luu(d)
    return {"ok": True, "id": id_, "gia_tri": k}


def cham(id_: int, dung: bool, *, cham_boi: str, ghi_chu: str = "") -> bool:
    """Chấm một bài; đúng thì ÁP làm sơ đồ đang dùng."""
    with _khoa:
        d = _nap()
        b = next((x for x in d["bai"] if x["id"] == int(id_)), None)
        if b is None:
            return False
        b.update(ket_qua="dung" if dung else "sai", cham_boi=cham_boi, ghi_chu=str(ghi_chu or "")[:300],
                 cham_luc=time.time())
        if dung:
            d["ap"] = {**b["gia_tri"], "id": b["id"]}
        _luu(d)
    return True


def doc(g: dict[str, Any]) -> str:
    """Sơ đồ → mấy dòng tiếng Việt cho chủ nhà đọc và chấm."""
    ten_kieu = {"chung_cu": "chung cư", "nha_dat": "nhà đất", "khong_ro": "chưa rõ kiểu nhà"}
    dong = [ten_kieu.get(g.get("kieu"), str(g.get("kieu"))) + (f", {g['so_tang']} tầng" if g.get("so_tang") else "")]
    for p in g.get("phong") or []:
        x = p["ten"]
        if p.get("thong_voi"):
            x += f" — thông {', '.join(p['thong_voi'])}"
        if p.get("vach_voi"):
            x += f" — có vách với {', '.join(p['vach_voi'])}"
        dong.append(f"• {x}")
    if (g.get("cua_chinh") or {}).get("vao"):
        dong.append(f"• Cửa chính mở vào {g['cua_chinh']['vao']}")
    for c in g.get("camera") or []:
        thay = ", ".join(f"{k} ({len(v)} ô)" for k, v in (c.get("thay") or {}).items())
        if thay:
            dong.append(f"• {c['ten']} thấy: {thay}")
    return "\n".join(dong)


def giai_va_bao() -> dict[str, Any]:
    """Vẽ lại rồi báo nhóm học hỏi: sơ đồ bot hiểu + câu hỏi xác nhận."""
    from services import hieu_thiet_bi_nha as ht

    kq = giai()
    if kq.get("ok"):
        g = kq["gia_tri"]
        tin = (f"🏠 #{kq['id']} Em hiểu sơ đồ nhà thế này (chắc {round(100 * g['chac'])}%):\n{doc(g)}"
               + ("\n\nEm cần anh xác nhận:\n" + "\n".join(f"{i + 1}. {q}" for i, q in enumerate(g["hoi_chu_nha"]))
                  if g.get("hoi_chu_nha") else "")
               + "\nAnh trả lời hoặc mô tả thêm, em vẽ lại; đúng thì anh nói «sơ đồ đúng rồi».")
        ht.bao_nhom(tin)
    return kq


# ── Dùng sơ đồ ──────────────────────────────────────────────────────────────
def o_cua_phong(camera: str, phong: str) -> set[str]:
    """Ô trên khung hình ``camera`` thuộc ``phong`` theo sơ đồ đang dùng (rỗng = không biết)."""
    s = ap() or {}
    for c in s.get("camera") or []:
        if c.get("ten") == camera:
            return set((c.get("thay") or {}).get(phong) or [])
    return set()


def doan_de(khu: str) -> list[str]:
    """Mấy dòng «SƠ ĐỒ NHÀ» cho đề của một thiết bị ở ``khu`` (rỗng khi chưa có sơ đồ)."""
    s = ap()
    if not s:
        return []
    p = next((x for x in s.get("phong") or [] if x.get("ten") == khu), None)
    dong = [f"SƠ ĐỒ NHÀ (đã chấm): {s.get('kieu')}" + (f", {s['so_tang']} tầng" if s.get("so_tang") else "")]
    if p:
        if p.get("thong_voi"):
            dong.append(f"- {khu} THÔNG với: {', '.join(p['thong_voi'])}")
        if p.get("vach_voi"):
            dong.append(f"- {khu} có VÁCH với: {', '.join(p['vach_voi'])}")
    for c in s.get("camera") or []:
        o = (c.get("thay") or {}).get(khu)
        if o:
            khac = [k for k in (c.get("thay") or {}) if k != khu]
            dong.append(f"- camera {c['ten']} thấy {khu}" + (f" (và cả {', '.join(khac)})" if khac else ""))
    return dong
