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
* ẢNH CAMERA: chủ máy 29/09/2026 "chụp ảnh cam phòng khách phân tích, dùng yolo phân tích cho chính
  xác", "bếp tính từ chiếc thùng gỗ màu xanh trong ảnh chụp ra đến cửa ban công". Lưới thống kê chỉ
  có ô nào chân người từng đứng và nhãn radar hay báo lây (bài #4–#11: camera phòng khách chỉ ra 1–2
  ô). Code chụp khung, kẻ đúng lưới 8×6, cho YOLO khoanh đồ vật (tủ lạnh, tivi, bàn ăn…); BOT (model
  thị giác, hướng dẫn `doc_anh_camera.md`) nhìn ảnh + mốc chủ nhà tả rồi chia ô theo phòng. Kết quả
  vào sổ như một lời mô tả nguồn «anh:<camera>» — lượt vẽ sơ đồ đọc nó như mọi bằng chứng khác.
"""

from __future__ import annotations

import base64
import bisect
import json
import re
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
#: Chủ máy 30/09/2026: "chia ô dày hơn hôm qua thì mới chính xác, càng dày càng tốt nhưng trong giới hạn cho
#: phép". Đo trên ảnh thật (Cam bếp, ban ngày): 16×12 bot tách được ban công / bếp / phòng khách; 24×18 chữ tên ô
#: chìm trên nền sáng và bot gộp thành khối chữ nhật lớn — quá giới hạn đọc của model thị giác.
COT, HANG = 16, 12
#: Ô có ít hơn ngần này mẫu thì không bày — một hai lần trùng không nói lên phòng nào.
O_TOI_THIEU = 20
#: Mỗi camera bày tối đa ngần này cặp đường đi (ô đầu → ô cuối) hay gặp nhất.
DUONG_TOI_DA = 8
#: Cửa mở rồi trong ngần này giây phòng nào có người đầu tiên.
CUA_GIAY = 60
#: LỐI VÀO (mục D2): khu trống ít nhất ngần này giây rồi có người mới tính là một lần «vào».
VAO_SAU_TRONG = 60
#: «Khu khác báo có người trước»: trong ngần này giây trước lúc vào.
TRUOC_GIAY = 30
#: «Khu khác hết người ngay sau»: radar tắt TRỄ — giữ vài chục giây tới vài phút sau khi người đi.
ROI_GIAY = 180
#: Khu KHÔNG có cảm biến hiện diện (nhà tắm, kho): người tắt thiết bị trong ngần này giây trước lúc vào.
TAT_GIAY = 120
#: Mốc nền: lấy mẫu mỗi ngần này giây lúc khu VẪN TRỐNG — dấu hiệu nào cũng có lúc trùng ngẫu nhiên
#: (radar nhà bên nháy liên tục), chỉ so với nền mới biết nó có đi kèm lúc vào thật không.
NEN_BUOC = 300
#: Khu có ít hơn ngần này lần vào thì không bày.
VAO_TOI_THIEU = 20
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


def them_mo_ta(noi_dung: str, nguon: str = "chu_may", *, thay_cu: bool = False) -> int:
    """Lời chủ nhà mô tả nhà (hoặc bản mô tả bản vẽ / ảnh camera của model thị giác). Trả số thứ tự.
    ``thay_cu``: bỏ các mô tả cũ CÙNG nguồn (đọc lại ảnh một camera thì bản mới thay bản cũ)."""
    noi_dung = str(noi_dung or "").strip()
    if not noi_dung:
        raise ValueError("Mô tả rỗng.")
    with _khoa:
        d = _nap()
        if thay_cu:
            d["mo_ta"] = [x for x in d["mo_ta"] if x.get("nguon") != nguon]
        d["mo_ta"].append({"luc": time.time(), "nguon": nguon, "noi_dung": noi_dung[:4000]})
        _luu(d)
        return len(d["mo_ta"])


def sua_mo_ta(luc: float, noi_dung: str | None) -> bool:
    """Sửa (``noi_dung``) hoặc xoá (``None``) một dòng mô tả, nhận ra bằng ``luc`` lúc ghi. Chủ máy 30/09/2026:
    "có thêm có xoá, có chỉnh sửa" — lời tả sai nằm lại trong sổ thì mọi lần vẽ sau bot đọc lại cái sai."""
    if noi_dung is not None and not str(noi_dung).strip():
        raise ValueError("Mô tả rỗng — muốn bỏ thì bấm xoá.")
    with _khoa:
        d = _nap()
        x = next((m for m in d["mo_ta"] if abs(float(m.get("luc") or 0) - float(luc)) < 1e-6), None)
        if x is None:
            return False
        if noi_dung is None:
            d["mo_ta"].remove(x)
        else:
            x["noi_dung"] = str(noi_dung).strip()[:4000]
        _luu(d)
        return True


def ap() -> dict[str, Any] | None:
    """Sơ đồ đang dùng (đã chấm đúng), hoặc None."""
    with _khoa:
        return _nap().get("ap")


# ── Đo ──────────────────────────────────────────────────────────────────────
def la_o(x: Any) -> bool:
    """Tên ô hợp lệ của lưới hiện tại: chữ cột A.. + số hàng 1..HANG (vd "C4", "P12")."""
    m = re.fullmatch(r"([A-Z])(\d{1,2})", str(x)) if isinstance(x, str) else None
    return bool(m) and ord(m.group(1)) - ord("A") < COT and 1 <= int(m.group(2)) <= HANG


def mau_o() -> str:
    """Câu mô tả cách gọi tên ô cho đề và lời báo lỗi."""
    return f"A1–{chr(ord('A') + COT - 1)}{HANG} (cột A–{chr(ord('A') + COT - 1)} trái→phải, hàng 1–{HANG} trên→dưới)"


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


def _doi(ts: list[float], gt: list[str], tu_gt: str, sang_gt: str) -> list[tuple[float, float]]:
    """Các lần đổi ``tu_gt`` → ``sang_gt``: (lúc đổi, đã ở ``tu_gt`` bao lâu)."""
    return [(ts[i], ts[i] - ts[i - 1]) for i in range(1, len(ts)) if gt[i] == sang_gt and gt[i - 1] == tu_gt]


def _co_trong(ds: list[float], a: float, b: float) -> bool:
    i = bisect.bisect_left(ds, a)
    return i < len(ds) and ds[i] <= b


def _nguoi_tat(ro: sqlite3.Connection, may: list[str], tu: float, den: float) -> list[float]:
    """Lúc NGƯỜI tắt một thiết bị trong nhóm (bỏ lần bot tự tắt — `do_ai`); đèn và công tắc gương của
    nó tắt cùng lúc nên các lần cách nhau dưới 20 giây gộp làm một."""
    ts = sorted(float(t) for m in may for (t,) in ro.execute(
        "SELECT ts FROM su_kien WHERE thiet_bi=? AND truong='state' AND gia_tri='off' AND do_ai=0"
        " AND ts>=? AND ts<?", (m, tu, den)))
    gop: list[float] = []
    for t in ts:
        if not gop or t - gop[-1] > 20:
            gop.append(t)
    return gop


def _loi_vao(radar: list[tuple[str, str]], dong: dict[str, tuple[list[float], list[str]]],
             tat_khu: dict[str, list[float]], mo_cua: dict[str, list[float]], ten: dict[str, str],
             tu: float, den: float) -> tuple[dict[str, Any], dict[str, Any]]:
    """Mục D2 (lối vào từng khu có radar) và D3 (khu không có cảm biến thông ra đâu).

    Chỉ ĐẾM dấu hiệu, không kết luận: khu nào nối khu nào là việc của bot đọc đề. Đo 01/10/2026 trên nhà thật
    (30 ngày): vào phòng khách thì «bếp báo có người trước» 8% so với nền 0,3%, «người vừa tắt đèn nhà tắm» 5%
    so với 0,4% — đúng lời chủ nhà "bếp đang trống mà báo trước phòng khách là người từ nhà tắm ra"."""
    bat = {m: [t for t, _ in _doi(*dong[m], "off", "on")] for m, _ in radar}
    het = {m: [t for t, _ in _doi(*dong[m], "on", "off")] for m, _ in radar}

    def dau_hieu(khu: str, t: float) -> set[str]:
        ra = set()
        for m, k in radar:
            if k == khu:
                continue
            if _co_trong(bat[m], t - TRUOC_GIAY, t - 0.001):
                ra.add(f"{k} báo có người trước")
            if _co_trong(het[m], t - TRUOC_GIAY, t + ROI_GIAY):
                ra.add(f"{k} hết người ngay sau")
        ra |= {f"{k}: người vừa tắt thiết bị" for k, ds in tat_khu.items() if _co_trong(ds, t - TAT_GIAY, t + 10)}
        ra |= {f"{ten.get(m, m)} vừa mở" for m, ds in mo_cua.items() if _co_trong(ds, t - CUA_GIAY, t)}
        return ra

    vao: dict[str, Any] = {}
    for m, khu in radar:
        lan = [t for t, lau in _doi(*dong[m], "off", "on") if lau >= VAO_SAU_TRONG and t >= tu]
        if len(lan) < VAO_TOI_THIEU:
            continue
        dem = Counter(x for t in lan for x in dau_hieu(khu, t))
        nen, n_nen, t = Counter(), 0, tu
        ts, gt = dong[m]
        while t < den - TRUOC_GIAY:
            i = bisect.bisect_right(ts, t) - 1
            if i >= 0 and gt[i] == "off" and t - ts[i] >= VAO_SAU_TRONG and (i + 1 >= len(ts) or ts[i + 1] > t + TRUOC_GIAY):
                n_nen += 1
                nen.update(dau_hieu(khu, t))
            t += NEN_BUOC
        if n_nen:
            vao[khu] = {"n": len(lan), "dau_hieu": [[x, round(v / len(lan), 3), round(nen[x] / n_nen, 3)]
                                                    for x, v in sorted(dem.items(), key=lambda i: (-i[1], i[0]))[:8]
                                                    if v / len(lan) >= 0.03]}

    # D3 — như mục D (cửa mở rồi phòng nào có người đầu tiên), cho khu không có cảm biến.
    ra_dau: dict[str, Any] = {}
    for khu, ds in tat_khu.items():
        dem = Counter()
        for t in ds:
            dau: tuple[float, str] | None = None
            for m, k in radar:
                j = bisect.bisect_right(bat[m], t)
                if j < len(bat[m]) and bat[m][j] <= t + CUA_GIAY and (dau is None or bat[m][j] < dau[0]):
                    dau = (bat[m][j], k)
            dem[dau[1] if dau else "(không khu nào — khu bên cạnh có thể đã có người sẵn)"] += 1
        if sum(dem.values()) >= VAO_TOI_THIEU:
            ra_dau[khu] = dict(dem)
    return vao, ra_dau


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
        co_radar = {k for _, k in hien}
        tat_khu = {k: _nguoi_tat(ro, p["thiet_bi"], tu, den) for k, p in phong.items()
                   if k not in co_radar and p["thiet_bi"]}
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
    duong: dict[str, list] = {}
    loi_camera = ""
    try:
        for c in camera_nha.danh_sach():
            src = str(c.get("src") or "")
            if not src:
                continue
            ev = _frigate(f"/api/events?camera={urllib.parse.quote(src)}&label=person&limit=100000&after={int(tu)}")
            luoi: dict[str, Counter] = {}
            di: Counter = Counter()
            for e in ev:
                # Đường đi Frigate lưu sẵn (`path_data`: điểm tỉ lệ 0–1 kèm giờ): ô ĐẦU → ô CUỐI của người —
                # đường cắt qua ranh giới ở đâu là chỗ cửa / khoảng thông; ô người hay hiện ra / biến mất ở mép
                # khung là lối vào phòng.
                pd = (e.get("data") or {}).get("path_data") or []
                if len(pd) >= 2:
                    try:
                        dau, cuoi = o_cua(*pd[0][0][:2]), o_cua(*pd[-1][0][:2])
                    except (TypeError, ValueError, IndexError):
                        dau = cuoi = ""
                    if dau and cuoi and dau != cuoi:
                        di[(dau, cuoi)] += 1
                hop = (e.get("data") or {}).get("box")
                if not hop:
                    continue
                co = khu_co_nguoi(float(e["start_time"]) + 1)
                if len(co) != 1:
                    continue
                luoi.setdefault(o_cua(*diem_chan(hop)), Counter())[next(iter(co))] += 1
            camera[str(c["name"])] = {o: dict(cnt) for o, cnt in luoi.items() if sum(cnt.values()) >= O_TOI_THIEU}
            duong[str(c["name"])] = [[a, b, n] for (a, b), n in di.most_common(DUONG_TOI_DA) if n >= O_TOI_THIEU]
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

    # 4. Lối vào từng khu, và khu không có cảm biến thông ra đâu.
    loi_vao, khong_cb = _loi_vao(radar, dong, tat_khu,
                                 {m: [t for t, _ in _doi(*dong_cua[m], "off", "on")] for m in cua}, ten, tu, den)

    from services import kich_hoat_nha
    dinh_vi_sai = [f"{ten.get(x['thiet_bi'], x['thiet_bi'])} (khu {boi_canh_nha.phong_cua(x['thiet_bi'])}), nguồn "
                   f"{ten.get(x['nguon'].split(' ')[0], x['nguon'])}, lúc "
                   f"{time.strftime('%d/%m %H:%M', time.localtime(float(x['luc'])))}"
                   for x in kich_hoat_nha._nap().get("dinh_vi") or [] if x.get("ket_qua") == "sai"]
    return {"phong": phong, "khu_radar": khu_ds, "ket": sorted(ket), "cung_bao": cung_bao, "camera": camera,
            "loi_camera": loi_camera, "cua": {m: dict(c) for m, c in cua_ra.items()}, "ten": ten, "duong": duong,
            "dinh_vi_sai": dinh_vi_sai, "loi_vao": loi_vao, "khong_cb": khong_cb}


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
    dong += [f"\nC. CAMERA — lưới {COT}×{HANG} trên khung hình, ô {mau_o()}; mỗi ô là "
             "chỗ CHÂN người đứng, kèm phòng nào có radar báo MỘT MÌNH lúc đó (tỉ lệ, số lần):"]
    if uv.get("loi_camera"):
        dong.append(f"(không đo được: {uv['loi_camera']})")
    for c, luoi in sorted(uv["camera"].items()):
        dong.append(f"- {c}:")
        for o in sorted(luoi, key=lambda o: (int(o[1:]), o[0])):
            n = sum(luoi[o].values())
            dong.append(f"  {o}: " + ", ".join(f"{k} {round(100 * v / n)}%" for k, v in
                                                sorted(luoi[o].items(), key=lambda i: -i[1])) + f" ({n})")
    if any(uv.get("duong") or {}):
        dong += ["\nC2. ĐƯỜNG ĐI trên camera — người xuất hiện ở ô ĐẦU, đi tới ô CUỐI (số lần, 30 ngày):"]
        for c, ds in sorted((uv.get("duong") or {}).items()):
            if ds:
                dong.append(f"- {c}: " + ", ".join(f"{a}→{b} ({n})" for a, b, n in ds))
    dong += ["\nD. CỬA — mở ra rồi trong 60 giây phòng nào có người đầu tiên:"]
    dong += [f"- {ten.get(m, m)}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items(), key=lambda i: -i[1]))
             for m, c in uv["cua"].items()] or ["(không có cảm biến cửa)"]

    def pt(x: float) -> str:
        return f"{100 * x:.1f}".replace(".", ",") if x < 0.1 else str(round(100 * x))
    if uv.get("loi_vao"):
        dong += [f"\nD2. LỐI VÀO — khu đang trống ≥{VAO_SAU_TRONG} giây rồi có người: dấu hiệu nào đi kèm "
                 f"(% số lần vào) so với MỐC NỀN (% lúc khu đó vẫn trống, lấy mẫu {NEN_BUOC // 60} phút một lần). "
                 f"«báo có người trước» = trong {TRUOC_GIAY} giây trước; «hết người ngay sau» = radar khu đó tắt trong "
                 f"{ROI_GIAY // 60} phút quanh lúc vào; «người vừa tắt thiết bị» = khu không có cảm biến, trong "
                 f"{TAT_GIAY // 60} phút trước:"]
        for k, v in sorted(uv["loi_vao"].items()):
            dong.append(f"- vào {k} ({v['n']} lần): " + "; ".join(
                f"{x} {pt(p)}% | nền {pt(q)}%" for x, p, q in v["dau_hieu"]))
    if uv.get("khong_cb"):
        dong += [f"\nD3. KHU KHÔNG CÓ CẢM BIẾN — người tắt thiết bị trong khu rồi trong {CUA_GIAY} giây khu nào báo "
                 "có người đầu tiên (số lần):"]
        dong += [f"- {k}: " + ", ".join(f"{x} {n}" for x, n in sorted(c.items(), key=lambda i: -i[1]))
                 for k, c in sorted(uv["khong_cb"].items())]
    dong += ["\nE. CHỦ NHÀ MÔ TẢ:"] + ([f"- {x}" for x in mo_ta] or ["(chưa có)"])
    sai = uv.get("dinh_vi_sai") or []
    if sai:
        # Bot chặn bật vì camera thấy người ở ngoài ô của khu, mà người tự bật ngay: ô của khu trên camera
        # đó đang THIẾU (hoặc ranh giới lệch) — sửa `camera.thay`.
        dong += ["\nG. ĐỊNH VỊ CHẶN NHẦM (theo sơ đồ đang dùng, camera không thấy ai trong ô của khu mà người "
                 "vẫn tự bật thiết bị ngay sau đó — ô của khu đang thiếu hoặc lệch):"]
        dong += [f"- {x}" for x in sai[-10:]]
    if dan:
        dong += ["\nCHỦ NHÀ DẶN (khi chấm các lần trước):"] + [f"- {x}" for x in dan]
    return "\n".join(dong)


# ── Kiểm bài ở biên ─────────────────────────────────────────────────────────
#: Kiểu nơi — cũng quyết định phần hướng dẫn RIÊNG khi dựng tình huống (`kich_ban_nha.noi_cua`). "nha_dat" là
#: tên cũ (trước 30/09/2026), giữ để bài cũ còn đọc được — coi như nhà phố.
KIEU = ("chung_cu", "nha_pho", "biet_thu", "van_phong", "xuong", "nha_dat", "khong_ro")


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
        for k in ("thong_voi", "vach_voi", "cua_sang"):
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
            if not all(la_o(x) for x in o):
                return f"camera {c['ten']}: ô phải dạng {mau_o()}"
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
    ten_kieu = {"chung_cu": "chung cư", "nha_pho": "nhà phố", "biet_thu": "nhà vườn / biệt thự",
                "van_phong": "văn phòng", "xuong": "xưởng", "nha_dat": "nhà đất", "khong_ro": "chưa rõ kiểu nhà"}
    dong = [ten_kieu.get(g.get("kieu"), str(g.get("kieu"))) + (f", {g['so_tang']} tầng" if g.get("so_tang") else "")]
    for p in g.get("phong") or []:
        x = p["ten"]
        if p.get("thong_voi"):
            x += f" — thông {', '.join(p['thong_voi'])}"
        if p.get("vach_voi"):
            x += f" — có vách với {', '.join(p['vach_voi'])}"
        if p.get("cua_sang"):
            x += f" — có cửa đi sang {', '.join(p['cua_sang'])}"
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


# ── Đọc ẢNH camera ─────────────────────────────────────────────────────────
_ANH_DIR = Path(DATA_DIR) / "agent" / "so_do_nha"


def ten_o(c: int, h: int) -> str:
    return f"{chr(ord('A') + c)}{h + 1}"


def ve_luoi(anh: Any, vat: list[Any]) -> bytes:
    """Ảnh BGR → JPEG có lưới COT×HANG ghi tên ô và hộp đồ vật YOLO (nhãn tiếng Anh; tên tiếng Việt nằm
    trong đề chữ)."""
    import io

    from PIL import Image, ImageDraw, ImageFont

    ra = Image.fromarray(anh[:, :, ::-1].copy())
    rong, cao = ra.size
    ve = ImageDraw.Draw(ra)
    try:
        # Chữ theo cỡ Ô (không theo cỡ ảnh): lưới dày thì chữ nhỏ lại cho khỏi che ảnh, nhưng không dưới 11 px.
        chu = ImageFont.load_default(size=max(11, min(cao // HANG, rong // COT) // 4))
    except TypeError:          # Pillow cũ: không có cỡ chữ
        chu = ImageFont.load_default()
    vang, do_ = (255, 255, 0), (255, 0, 0)
    for c in range(1, COT):
        ve.line([(int(c * rong / COT), 0), (int(c * rong / COT), cao)], fill=vang, width=1)
    for h in range(1, HANG):
        ve.line([(0, int(h * cao / HANG)), (rong, int(h * cao / HANG))], fill=vang, width=1)
    for c in range(COT):
        for h in range(HANG):
            # Viền đen: chữ vàng đọc được cả trên sàn gỗ sáng, cửa sổ chói (đo 30/09 — lưới dày chữ nhỏ bị chìm).
            ve.text((int(c * rong / COT) + 3, int(h * cao / HANG) + 2), ten_o(c, h), fill=vang, font=chu,
                    stroke_width=2, stroke_fill=(0, 0, 0))
    for v in vat:
        x1, y1, x2, y2 = (int(t) for t in v.hop)
        ve.rectangle([x1, y1, x2, y2], outline=do_, width=2)
        ve.text((x1 + 2, max(0, y1 - cao // 40)), v.nhan, fill=do_, font=chu)
    buf = io.BytesIO()
    ra.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def la_anh_dem(anh: Any) -> bool:
    """Camera chuyển hồng ngoại ban đêm cho ảnh xám: ba kênh màu gần như trùng nhau."""
    import numpy as np

    m = anh[::8, ::8].astype(np.int16)
    return float(np.abs(m[..., 0] - m[..., 1]).mean() + np.abs(m[..., 1] - m[..., 2]).mean()) < 3.0


def mo_ta_vat(v: Any, rong: int, cao: int) -> str:
    """Một đồ vật YOLO → «tên (nhãn) — chân ô X, trải A1–C3» (chân = giữa đáy hộp, chỗ nó đứng trên sàn)."""
    x1, y1, x2, y2 = (float(t) for t in v.hop)
    chan = o_cua((x1 + x2) / 2 / rong, min(y2 / cao, 0.999))
    return (f"{v.ten} ({v.nhan}, {v.diem:.0%}) — chân ô {chan}, trải "
            f"{o_cua(x1 / rong, y1 / cao)}–{o_cua(min(x2 / rong, 0.999), min(y2 / cao, 0.999))}")


#: Model đọc ảnh sơ đồ nhà khi chủ máy chưa đặt `nhin_nha.so_do.model_anh`. Chủ máy chọn 30/09/2026 sau khi đo
#: trên ảnh thật: ChatGPT miễn phí (đầu combo «AI vision») bịa phòng không có trong khung (gán «bếp» cho tủ giày,
#: bàn ăn phòng khách); Claude và Gemini thì không, Claude bám hình dạng sàn sát nhất.
#: Đổi lại 30/09/2026 chiều theo bộ đề ảnh thật (`de_luyen/doc_anh_camera`, đáp án = vùng chủ máy khoanh): Gemini
#: 3.6 flash đạt 4/4 camera cả hai lượt (tìm đúng mốc «thùng gỗ xanh» mà Claude không thấy), Claude đạt 2/4 và
#: hay 429. Chủ máy chọn đổi.
#: Nhiều model (phân cách dấu phẩy): model ĐẦU đọc mọi lần và bỏ phiếu, model sau chỉ vào THAY khi model trước
#: hỏng (lỗi gọi, 429). Chủ máy 30/09/2026 muốn "kết hợp và bù trừ"; đo trên bộ đề ảnh thật: trộn phiếu
#: Gemini–Claude–Gemini đạt 11/16 camera (Claude không mạnh hơn ở mặt nào, chỉ thêm phiếu sai và cầm đa số mỗi
#: lần Gemini lỡ), chỉ Gemini đạt 8/8. Nên Claude bù khi Gemini HỎNG, không bù bằng phiếu.
MODEL_ANH_MAC_DINH = "gemini_free/gemini-3.6-flash,claude/auto"


def model_anh() -> str:
    from services import nhin_nha
    return str(nhin_nha._muc("so_do").get("model_anh") or "").strip() or MODEL_ANH_MAC_DINH


def cac_model_anh() -> list[str]:
    """Danh sách model đọc ảnh theo thứ tự ưu tiên (cài đặt `model_anh`, phân cách dấu phẩy)."""
    return [m.strip() for m in model_anh().split(",") if m.strip()]


def _goi_thi_giac(noi: str, jpeg: bytes, max_tokens: int = 4000, model: str | None = None) -> str:
    """Một lượt gọi model đọc ảnh sơ đồ (`model_anh`) với một ảnh. Lỗi thì ném RuntimeError.

    ``max_tokens`` 4000: lưới 16×12 = 192 ô, bài chia hai phòng dài gần 1000 token; đo 30/09/2026 mức 1500 làm
    gemini-3.6-flash (model có suy nghĩ) trả «{}» ở Cam bếp, Cam phòng khách — nới ra thì đọc đúng mốc ngay."""
    from services.agent.runtime import call_model, content_of

    url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
    r = call_model(model or cac_model_anh()[0], [{"role": "user", "content": [
        {"type": "text", "text": noi}, {"type": "image_url", "image_url": {"url": url}}]}],
        timeout=180, max_tokens=max_tokens,
        # Cùng khuôn lời gọi học của bot (`hieu_thiet_bi_nha._goi_model`): xin JSON, tắt mọi tích hợp.
        # Đo 30/09/2026: thiếu ba tham số này thì cả ba model thị giác trả «json\nmo ta…» — mất sạch
        # ngoặc, nháy, gạch dưới — không đọc được.
        response_format={"type": "json_object"}, no_smart_home=True, allowed_groups=set())
    if r.get("error"):
        raise RuntimeError(f"model thị giác lỗi: {str(r['error'])[:160]}")
    return str(content_of(r) or "")


def _ten_phong() -> list[str]:
    from services import boi_canh_nha, ha_client
    return sorted({boi_canh_nha.phong_cua(str(s["entity_id"])) for s in ha_client.get_states() or []} - {"", None})


def kiem_anh(data: Any, phong: list[str]) -> dict[str, Any] | str:
    """Loại bài đọc ảnh sai khuôn: ô phải A1–H6, phòng phải có trong nhà."""
    if not isinstance(data, dict) or not isinstance(data.get("thay"), dict):
        return "phải là JSON có «thay»: {phòng: [ô]}"
    thay: dict[str, list[str]] = {}
    for k, o in data["thay"].items():
        if k not in phong:
            return f"phòng không có trong nhà: {k!r}"
        if not isinstance(o, list) or not all(la_o(x) for x in o):
            return f"{k}: ô phải dạng {mau_o()}"
        if o:
            thay[k] = sorted(set(o), key=lambda x: (int(x[1:]), x[0]))
    try:
        chac = min(1.0, max(0.0, float(data.get("chac"))))
    except (TypeError, ValueError):
        chac = 0.0
    return {"thay": thay, "moc": str(data.get("moc") or "")[:400], "chac": round(chac, 2),
            "vi_sao": str(data.get("vi_sao") or "")[:500]}


def lenh_doc_anh(ten: str, jpeg: bytes, mo_ta: list[str]) -> tuple[str, bytes, bool, list[Any], tuple[int, int], str]:
    """Lệnh cho model đọc ảnh một camera: kẻ lưới + YOLO khoanh đồ vật + lời chủ nhà ``mo_ta``.
    Trả (lệnh, ảnh lưới, ảnh đêm?, đồ vật, (rộng, cao), phiên bản hướng dẫn). Dùng chung cho đường chạy thật
    và bộ đề luyện đọc ảnh (`services/de_luyen/doc_anh_camera.py`) để hai bên không lệch nhau."""
    from services import hieu_thiet_bi_nha as ht, nhin_nha, yolo_nha

    anh = yolo_nha.doc_anh(jpeg)
    cao, rong = anh.shape[:2]
    vat = nhin_nha.vat_the(anh)
    dem = la_anh_dem(anh)
    luoi = ve_luoi(anh, vat)
    huong, ban = ht.huong_dan("doc_anh_camera")
    de = "\n".join([f"CAMERA: {ten}",
                    f"PHÒNG trong nhà (chỉ dùng đúng các tên này): {', '.join(_ten_phong())}",
                    f"ẢNH: khung hình đã kẻ lưới {COT}×{HANG} — ô {mau_o()}, tên ô ghi ở góc trên-trái mỗi ô; "
                    "hộp đỏ là đồ vật YOLO thấy."
                    + (" ẢNH ĐÊM (hồng ngoại, đen trắng — không thấy màu)." if dem else ""),
                    "YOLO thấy:"] + [f"- {mo_ta_vat(v, rong, cao)}" for v in vat[:25]] + (["- (không thấy gì)"] if not vat else [])
                   + ["CHỦ NHÀ MÔ TẢ:"] + ([f"- {x}" for x in mo_ta] or ["- (chưa có)"]))
    return huong + "\n\n---\n\n" + de, luoi, dem, vat, (rong, cao), ban


#: Mỗi camera đọc bấy nhiêu lần rồi lấy ĐA SỐ theo từng ô. Đo 30/09/2026 trên bộ đề ảnh thật: cùng ảnh, cùng
#: hướng dẫn mà claude/auto mỗi lần chia một kiểu (Cam phòng khách lần đạt, lần bịa «khu bếp» ở tủ giày) — một
#: lần đọc không tin được, sửa chữ trong hướng dẫn không chữa được độ dao động.
LAN_DOC = 3


def gop_phieu(bai: list[dict[str, Any]]) -> dict[str, Any]:
    """Gộp nhiều lần đọc: ô nào QUÁ NỬA số lần gán cùng một phòng thì nhận phòng đó, còn lại bỏ.
    Mốc / lời giải lấy của lần đọc khớp kết quả gộp nhất; `chac` = trung bình × tỉ lệ ô được đa số đồng ý."""
    can = len(bai) // 2 + 1
    phieu: dict[tuple[str, str], int] = {}
    for b in bai:
        for p, ds in b["thay"].items():
            for o in ds:
                phieu[(o, p)] = phieu.get((o, p), 0) + 1
    thay: dict[str, list[str]] = {}
    for (o, p), n in phieu.items():
        if n >= can:
            thay.setdefault(p, []).append(o)
    thay = {p: sorted(ds, key=lambda x: (int(x[1:]), x[0])) for p, ds in thay.items()}
    nhan = {(o, p) for p, ds in thay.items() for o in ds}
    gan_nhat = max(bai, key=lambda b: len(nhan & {(o, p) for p, ds in b["thay"].items() for o in ds}))
    moi_o = {o for o, _ in phieu}
    dong_y = len(nhan) / len(moi_o) if moi_o else 1.0
    chac = sum(b["chac"] for b in bai) / len(bai) * dong_y
    return {**gan_nhat, "thay": thay, "chac": round(chac, 2), "so_lan": len(bai)}


def doc_nhieu_lan(lenh: str, luoi: bytes, phong: list[str]) -> tuple[dict[str, Any] | str | None, str]:
    """Đọc ảnh ``LAN_DOC`` lần rồi gộp theo đa số. Model đầu (`cac_model_anh`) đọc mọi lần; nó lỗi (429, không
    gọi được) thì rút khỏi lượt và model kế đọc thay. Chỉ còn một model mà nó lỗi sau khi đã đọc được: nghỉ rồi
    đọc tiếp. Sai khuôn thì chính model đó đọc lại. Trả (kết quả | lỗi khuôn | None khi không đọc được lần nào,
    lỗi model cuối). Dùng chung cho đường chạy thật và bộ đề `de_luyen/doc_anh_camera`."""
    from services import hieu_thiet_bi_nha as ht

    con = cac_model_anh()
    hop_le: list[dict[str, Any]] = []
    loi_khuon, loi_model = "", ""
    for _ in range(2 * LAN_DOC + len(con)):
        if len(hop_le) >= LAN_DOC or not con:
            break
        m = con[0]
        try:
            tho = _goi_thi_giac(lenh, luoi, model=m)
        except RuntimeError as exc:
            loi_model = str(exc)[:160]
            if len(con) > 1:
                con.pop(0)
                continue
            if not hop_le:
                break
            time.sleep(NGHI_THU_LAI_S)
            continue
        data = ht._doc_json(tho)
        k = kiem_anh(data, phong) if data is not None else "không đọc được JSON"
        if isinstance(k, str):
            loi_khuon = k
        else:
            hop_le.append({**k, "model": m})
    if hop_le:
        return {**gop_phieu(hop_le), "model": ", ".join(x["model"] for x in hop_le)}, loi_model
    return (loi_khuon or None) if not loi_model else None, loi_model


def doc_anh_camera(ten: str) -> dict[str, Any]:
    """Chụp ``ten``, kẻ lưới + YOLO khoanh đồ vật, bot (model thị giác) chia ô theo phòng; kết quả vào sổ
    thành lời mô tả nguồn «anh:<camera>» (thay bản đọc cũ của camera đó)."""
    from services import camera_nha, ha_client

    ten_that, jpeg = camera_nha.chup(ten, timeout=20.0)
    mo_ta = [x["noi_dung"] for x in so()["mo_ta"] if not str(x.get("nguon") or "").startswith("anh:")]
    lenh, luoi, dem, vat, (rong, cao), ban = lenh_doc_anh(ten_that, jpeg, mo_ta)
    _ANH_DIR.mkdir(parents=True, exist_ok=True)
    (_ANH_DIR / f"{ten_that}.jpg").write_bytes(luoi)
    phong = _ten_phong()
    if ha_client._URL_CO_MAT_KHAU.search(lenh):
        return {"ok": False, "loi": "đề có chuỗi dạng tài khoản:mật khẩu — bỏ lượt"}
    if model_anh() == THU_CONG:
        k, loi_model = None, ""
    else:
        k, loi_model = doc_nhieu_lan(lenh, luoi, phong)
        if k is None and loi_model and so().get("model_doc_duoc") == model_anh():
            # Model này ĐÃ từng đọc được ảnh ở nhà này → lần này là lỗi TẠM (bận, quá giới hạn…), không phải nhà
            # thiếu model. Đo 30/09/2026 07:57: Claude đọc xong 2 camera rồi trả 429 ở 2 camera sau — bản cũ
            # gửi vào nhóm "em chưa có model đọc ảnh, anh tự làm giúp em". Chỉ việc người mới làm được mới
            # được đẩy sang người.
            return {"ok": False, "tam": True, "camera": ten_that,
                    "loi": f"model đọc ảnh lỗi tạm, lượt sau em đọc lại ({loi_model})"}
    if k is None:
        # Không có model đọc ảnh (nhà không có Claude…) hoặc chủ nhà chọn tự làm: xuất ẢNH + LỆNH để người dùng
        # dán vào app của họ, thấy đúng thì gửi đáp án lại (chủ máy 30/09/2026).
        return {"ok": False, "thu_cong": True, "camera": ten_that, "luoi": luoi, "loi": loi_model,
                **_cho_dap_an(ten_that, lenh, luoi, dem, ban)}
    if isinstance(k, str):
        logger.warning({"event": "so_do_nha_anh_loai", "camera": ten_that, "loi": k})
        return {"ok": False, "camera": ten_that, "loi": k}
    _ghi_bai_anh(ten_that, k, dem, f"bot đọc, hướng dẫn {ban}")
    with _khoa:
        d = _nap()
        d["model_doc_duoc"] = model_anh()
        (d.get("cho_anh") or {}).pop(ten_that, None)   # bot đọc được rồi thì phiếu nhờ người làm tay hết việc
        _luu(d)
    logger.info({"event": "so_do_nha_anh", "camera": ten_that, "thay": k["thay"], "vat": len(vat)})
    return {"ok": True, "camera": ten_that, **k, "dem": dem, "luoi": luoi,
            "vat": [mo_ta_vat(v, rong, cao) for v in vat[:25]]}


#: Lỗi tạm của model đọc ảnh: nghỉ bấy nhiêu giây rồi thử lại một lần trong cùng lượt đọc.
NGHI_THU_LAI_S = 60.0

#: Đặt `nhin_nha.so_do.model_anh` = giá trị này: không gọi model — luôn xuất ảnh + lệnh cho người dùng tự làm.
THU_CONG = "thu_cong"


def _ghi_bai_anh(ten: str, k: dict[str, Any], dem: bool, ai_doc: str) -> None:
    noi = (f"Ảnh {ten} ({ai_doc}; ảnh chụp{' ĐÊM đen trắng' if dem else ''} kẻ lưới {COT}×{HANG}, YOLO khoanh đồ vật, "
           f"chắc {round(100 * k['chac'])}%): "
           + ("; ".join(f"{p}: ô {', '.join(o)}" for p, o in k["thay"].items()) or "không thấy phòng nào trong nhà")
           + (f". Mốc: {k['moc']}" if k["moc"] else ""))
    them_mo_ta(noi, nguon=f"anh:{ten}", thay_cu=True)


def _cho_dap_an(ten: str, lenh: str, luoi: bytes, dem: bool, ban: str) -> dict[str, Any]:
    """Lưu phiếu CHỜ ĐÁP ÁN của một camera: ảnh lưới (đường tải) + lệnh đầy đủ. Trả {anh_url, lenh}."""
    try:
        from services.protocol.conversation import save_image_bytes
        url = save_image_bytes(luoi)
    except Exception:  # noqa: BLE001 — không lưu được vào thư viện ảnh thì vẫn còn tệp trong _ANH_DIR
        url = ""
    lenh_du = (lenh + "\n\n(Ảnh đính kèm là khung hình camera đã kẻ lưới. CHỈ trả JSON đúng khuôn ở trên.)")
    with _khoa:
        d = _nap()
        d.setdefault("cho_anh", {})[ten] = {"luc": time.time(), "anh_url": url, "lenh": lenh_du, "dem": dem,
                                            "huong_dan": ban}
        _luu(d)
    return {"anh_url": url, "lenh": lenh_du}


def cho_dap_an() -> dict[str, dict[str, Any]]:
    """Các camera đang chờ người dùng gửi đáp án (tự đọc ảnh bằng app khác). Phiếu của camera đã có bản đọc
    MỚI HƠN phiếu thì không còn việc: 30/09/2026 hai phiếu lúc 08:1x nằm lại trên web cả ngày dù bot đã đọc
    xong hai camera đó ngay sau (bản cũ chỉ bỏ phiếu ở lần đọc kế tiếp)."""
    d = so()
    doc_luc = {str(x["nguon"])[4:]: float(x.get("luc") or 0) for x in d["mo_ta"]
               if str(x.get("nguon") or "").startswith("anh:")}
    return {k: v for k, v in (d.get("cho_anh") or {}).items() if float(v.get("luc") or 0) > doc_luc.get(k, 0)}


def anh_luoi(ten: str) -> Path | None:
    """Ảnh lưới mới nhất bot đã đọc của camera ``ten`` (None nếu chưa có). Chỉ nhận tên khớp đúng một tệp
    trong thư mục ảnh — tên lạ (``../``) không bao giờ thành đường dẫn."""
    if not _ANH_DIR.is_dir():
        return None
    return next((f for f in _ANH_DIR.glob("*.jpg") if f.stem == ten), None)


def nhan_dap_an_anh(ten: str, dap_an: str) -> dict[str, Any]:
    """Người dùng tự đọc ảnh (ChatGPT / Gemini / Claude của họ) rồi dán đáp án: kiểm khuôn GIỐNG HỆT lúc bot tự
    đọc, ghi vào sổ như một bài đọc ảnh, bỏ phiếu chờ. Sai khuôn thì trả lỗi để họ sửa, phiếu vẫn giữ."""
    from services import hieu_thiet_bi_nha as ht
    cho = cho_dap_an()
    if ten not in cho:
        return {"ok": False, "loi": f"không có ảnh nào của «{ten}» đang chờ đáp án"}
    data = ht._doc_json(str(dap_an or ""))
    k = kiem_anh(data, _ten_phong()) if data is not None else "không đọc được JSON (dán nguyên phần {…} app trả)"
    if isinstance(k, str):
        return {"ok": False, "loi": k}
    _ghi_bai_anh(ten, k, bool(cho[ten].get("dem")), "người dùng tự đọc bằng app khác, gửi lại")
    with _khoa:
        d = _nap()
        (d.get("cho_anh") or {}).pop(ten, None)
        _luu(d)
    logger.info({"event": "so_do_nha_anh_thu_cong", "camera": ten, "thay": k["thay"]})
    return {"ok": True, "camera": ten, **k, "con_cho": sorted(cho_dap_an())}


def doc_anh_va_ve(cameras: list[str] | None = None) -> dict[str, Any]:
    """Đọc ảnh từng camera (mặc định mọi camera) rồi vẽ lại sơ đồ và báo nhóm học hỏi."""
    from services import camera_nha, hieu_thiet_bi_nha as ht

    ds = cameras or [str(c["name"]) for c in camera_nha.danh_sach()]
    ra = []
    for c in ds:
        try:
            ra.append(doc_anh_camera(c))
        except Exception as exc:  # noqa: BLE001 — một camera hỏng không bỏ cả lượt
            ra.append({"ok": False, "camera": c, "loi": str(exc)[:160]})
    lai = [i for i, x in enumerate(ra) if x.get("tam")]
    if lai:
        # Lỗi tạm (thường là quá giới hạn sau vài ảnh liền): nghỉ một quãng rồi thử lại MỘT lần trong lượt này.
        time.sleep(NGHI_THU_LAI_S)
        for i in lai:
            try:
                ra[i] = doc_anh_camera(ds[i])
            except Exception as exc:  # noqa: BLE001
                ra[i] = {"ok": False, "camera": ds[i], "loi": str(exc)[:160]}
    from services import thong_bao
    from services.protocol.conversation import save_image_bytes

    loi = []
    for x in ra:
        if x.get("thu_cong"):
            # Không model nào đọc được: gửi ẢNH LƯỚI + cách tự làm; lệnh đầy đủ dài nên để trên web / API.
            tin = (f"📷 {x['camera']} — em chưa có model đọc ảnh"
                   + (f" ({x['loi']})" if x.get("loi") else "") + ".\nAnh tự làm giúp em: mở trang Học hỏi → «Sơ đồ nhà — "
                   "ảnh chờ đáp án», chép LỆNH + ảnh này vào ChatGPT / Gemini / Claude của anh; thấy chia ô đúng thì dán "
                   f"đáp án (phần {{…}}) vào ô ở đó, hoặc nhắn cho em «đáp án ảnh {x['camera']}: {{…}}».")
            x.pop("luoi", None)
            thong_bao.gui("hoc_hoi.hieu_thiet_bi", tin, anh_url=x.get("anh_url") or "")
            continue
        if not x.get("ok"):
            loi.append(f"• {x['camera']}: chưa đọc được — {x.get('loi')}")
            continue
        # Gửi kèm ẢNH LƯỚI em đã nhìn: chủ nhà chấm được từng ô, lời chấm vào sổ mô tả và lần đọc sau đọc cả nó.
        tin = (f"📷 {x['camera']} — em chia ô (ô ghi ở góc mỗi ô trong ảnh), chắc {round(100 * x['chac'])}%:\n"
               + ("\n".join(f"• {p}: {', '.join(o)}" for p, o in x["thay"].items()) or "• không thấy phòng nào trong nhà")
               + (f"\nMốc em dùng: {x['moc'][:200]}" if x.get("moc") else "")
               + ("\n(Ảnh ĐÊM đen trắng — mốc theo màu em chưa thấy; anh bảo em chụp lại ban ngày.)" if x.get("dem") else "")
               + "\nSai ô nào anh nói, vd «ô E4, F4 là phòng khách», em đọc lại.")
        try:
            url = save_image_bytes(x.pop("luoi"))
        except Exception:  # noqa: BLE001 — không lưu được ảnh thì vẫn gửi chữ
            url = ""
        thong_bao.gui("hoc_hoi.hieu_thiet_bi", tin, anh_url=url)
    if loi:
        ht.bao_nhom("📷 Camera em chưa nhìn được:\n" + "\n".join(loi))
    for x in ra:
        x.pop("luoi", None)
    return {"anh": ra, "so_do": giai_va_bao()}


# ── Chủ nhà KHOANH trên ảnh ─────────────────────────────────────────────────
# Chủ máy 30/09/2026 tối: "sao không tích được trên ảnh nhỉ, mấy chỗ sai, rõ ràng sáng tôi đã gửi chi tiết cho bạn
# rồi". Vùng chủ nhà khoanh là ĐÁP ÁN, thắng bài bot tự đọc: sơ đồ trên web, bộ đếm người theo phòng
# (``o_cua_phong``) và đề cho bot vẽ lại đều dùng nó.
def khoanh(camera: str | None = None) -> dict[str, Any]:
    """{camera: {"phong": {phòng: [ô]}, "do": [ô đồ đạc], "luc"}} (hoặc của một camera)."""
    d = so().get("chu_khoanh") or {}
    return dict(d.get(camera) or {}) if camera is not None else dict(d)


def dat_khoanh(camera: str, phong: Any, do: Any = None) -> dict[str, Any]:
    """Lưu vùng chủ nhà khoanh cho một camera (thay bản cũ). ``phong`` rỗng và ``do`` rỗng = bỏ khoanh, quay về
    bài bot đọc. Ô sai dạng, một ô hai phòng → ValueError."""
    camera = str(camera or "").strip()
    if not camera:
        raise ValueError("Thiếu tên camera.")
    if not isinstance(phong, dict):
        raise ValueError("«phong» phải là {phòng: [ô]}.")
    sach: dict[str, list[str]] = {}
    da: dict[str, str] = {}
    for ten, o in phong.items():
        ten = str(ten or "").strip()
        if not ten or len(ten) > 40 or not isinstance(o, list) or not all(la_o(x) for x in o):
            raise ValueError(f"«{ten}»: ô phải dạng {mau_o()}")
        for x in o:
            if da.get(x, ten) != ten:
                raise ValueError(f"ô {x} vừa thuộc «{da[x]}» vừa thuộc «{ten}»")
            da[x] = ten
        if o:
            sach[ten] = sorted(set(o), key=lambda x: (int(x[1:]), x[0]))
    do_ = [x for x in (do or []) if la_o(x) and x not in da]
    if do is not None and not isinstance(do, list):
        raise ValueError("«do» phải là danh sách ô.")
    with _khoa:
        d = _nap()
        ck = d.setdefault("chu_khoanh", {})
        if not sach and not do_:
            ck.pop(camera, None)
        else:
            ck[camera] = {"phong": sach, "do": sorted(set(do_), key=lambda x: (int(x[1:]), x[0])),
                          "luc": time.time()}
        d["mo_ta"] = [x for x in d["mo_ta"] if x.get("nguon") != f"khoanh:{camera}"]
        if sach or do_:
            d["mo_ta"].append({"luc": time.time(), "nguon": f"khoanh:{camera}", "noi_dung": (
                f"Chủ nhà khoanh trên ảnh {camera} (ĐÁP ÁN, thắng mọi lần bot đọc): "
                + "; ".join(f"{k}: ô {', '.join(v)}" for k, v in sach.items())
                + (f"; ĐỒ ĐẠC (không ai đứng, không thuộc phòng nào): ô {', '.join(do_)}" if do_ else ""))[:4000]})
        _luu(d)
    return khoanh(camera)


def thay_cua(camera: str) -> dict[str, list[str]]:
    """Ô theo phòng của ``camera``: vùng chủ nhà khoanh nếu có, không thì theo sơ đồ đang dùng."""
    k = khoanh(camera)
    if k.get("phong"):
        return dict(k["phong"])
    for c in (ap() or {}).get("camera") or []:
        if c.get("ten") == camera:
            return dict(c.get("thay") or {})
    return {}


# ── Dùng sơ đồ ──────────────────────────────────────────────────────────────
def o_cua_phong(camera: str, phong: str) -> set[str]:
    """Ô trên khung hình ``camera`` thuộc ``phong`` — vùng chủ nhà khoanh trước, không thì theo sơ đồ đang dùng
    (rỗng = không biết)."""
    k = khoanh(camera)
    if k.get("phong"):
        return set(k["phong"].get(phong) or [])
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
        if p.get("cua_sang"):
            dong.append(f"- {khu} có CỬA đi thẳng sang: {', '.join(p['cua_sang'])}")
    for c in s.get("camera") or []:
        o = (c.get("thay") or {}).get(khu)
        if o:
            khac = [k for k in (c.get("thay") or {}) if k != khu]
            dong.append(f"- camera {c['ten']} thấy {khu}" + (f" (và cả {', '.join(khac)})" if khac else ""))
    return dong
