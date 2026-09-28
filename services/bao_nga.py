"""Báo ngã — ĐỢT THU DỮ LIỆU: thấy người chuyển sang nằm thì lưu ảnh + hỏi model nhìn ảnh, KHÔNG báo.

Chủ máy 28/09/2026: báo ngã cho cả nhà, thử trước ở Cam bếp, "Chạy im trước, rồi bật loa", không
ngã thử. Đo cùng ngày (không dùng được để báo thẳng):

* Dáng người + học máy trên bộ GMDCSA24 (79 ngã / 81 sinh hoạt): bắt 90–97% cú ngã nhưng báo
  nhầm 20–37% cảnh cố ý nằm (nằm giường, ngồi bệt, chống đẩy). Tốc độ đổ thẳng→nằm của ngã
  (trung vị 0,30 s) và cố ý nằm (0,40 s) KHÔNG tách được.
* Chạy qua một ngày Cam bếp: 129–267 đoạn 10 giây bị nghi — nhà này NẰM DƯỚI SÀN BẾP thường
  xuyên (47/525 đoạn có người lộ trọn thân nằm), camera quay góc cao nên người sát mép chỉ lộ vai.
* Hỏi model nhìn ảnh (6 khung ghép): «AI vision» bắt 7/20 ngã, Gemini 3.5 Flash 13/18.

Nên đợt này chỉ GOM MẪU của chính nhà: mỗi lần một người đang thẳng chuyển sang nằm, theo dõi thêm
`THEO_GIAY` xem có dậy không, ghép 6 khung (trước → sau) và hỏi model — rồi ghi sổ
``agent/bao_nga/nhat_ky.jsonl`` kèm ảnh. Không Zalo, không loa. Có sổ thì mới đo được mỗi ngày
bao nhiêu lần nằm, model nói gì, nằm bao lâu — trước khi bật báo thật.

Giờ canh (`dang_canh`): chủ máy đặt 24/24 hoặc khung giờ thì theo đó; không thì theo nếp sinh hoạt
(`lich_sinh_hoat`) — bỏ lúc cả nhà vắng.
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

_TZ = timezone(timedelta(hours=7))
THU_MUC = Path(DATA_DIR) / "agent" / "bao_nga"
LUONG = ("phu", "chinh", "khoa")
CHE_DO = ("nep", "24", "khung")
#: Hỏi lần lượt, model đầu lỗi/trả rỗng thì sang model sau. Đo 28/09/2026: Gemini 3.5 Flash bắt
#: ngã khá hơn (13/18) nhưng bản miễn phí hay trả 503 "high demand" hoặc chuỗi rỗng; «AI vision»
#: trả lời đủ 40/40 lần (bắt 7/20) — để gom mẫu thì thà có câu trả lời kém hơn còn hơn lỗ trống.
MODEL_HOI = ("gemini_free/gemini-3.5-flash", "AI vision")

#: Thân lệch khỏi phương đứng: ≤ THANG là đứng/ngồi thẳng, ≥ NAM là nằm (độ).
THANG, NAM = 35.0, 60.0
#: Thẳng → nằm trong ngần này giây mới tính là một lần CHUYỂN sang nằm.
CHUYEN_GIAY = 4.0
#: Sau lúc chuyển, theo dõi thêm ngần này giây: nằm bao lâu, có dậy không.
THEO_GIAY = 20.0
#: Một camera: hai lần ghi cách nhau ít nhất ngần này (một người nằm lăn qua lại = một lần).
NGHI_GIAY = 30.0
TIN_KHOP = 0.5
TIN_NGUOI = 0.4
GIU_NGAY = 14

_khoa = threading.RLock()
_luong: tuple[threading.Thread, threading.Event] | None = None
_phien: Any = None
_stats: dict[str, Any] = {"khung": 0, "nguoi": 0, "nghi": 0, "loi": 0, "loi_cuoi": "", "dang_canh": False}


# ── Cài đặt ─────────────────────────────────────────────────────────────────

def cai_dat() -> dict[str, Any]:
    """``nhin_nha.nga`` — chủ máy chỉnh trên web (thẻ Nhìn nhà)."""
    from services.config import config
    c = (config.data.get("nhin_nha") or {}).get("nga")
    c = c if isinstance(c, dict) else {}
    luong = str(c.get("luong") or "phu")
    che_do = str(c.get("che_do") or "nep")
    cam = c.get("camera")
    return {"bat": bool(c.get("bat")),
            "camera": [str(x) for x in cam] if isinstance(cam, list) else ["Cam bếp"],
            "luong": luong if luong in LUONG else "phu",
            "che_do": che_do if che_do in CHE_DO else "nep",
            "khung": [x for x in (c.get("khung") or []) if isinstance(x, dict)],
            "moi_giay": _so(c.get("moi_giay"), 2.0, 0.5, 5.0),
            "model": _ds_model(c.get("model"))}


def _ds_model(v: Any) -> list[str]:
    if v is None:
        return list(MODEL_HOI)
    if isinstance(v, str):
        return [v] if v.strip() else []
    return [str(x) for x in v if str(x).strip()] if isinstance(v, list) else list(MODEL_HOI)


def _so(v: Any, mac_dinh: float, thap: float, cao: float) -> float:
    try:
        return max(thap, min(cao, float(v)))
    except (TypeError, ValueError):
        return mac_dinh


def dang_canh(c: dict[str, Any], luc: float | None = None) -> bool:
    """Chủ máy đặt 24/24 hoặc khung giờ thì THẮNG nếp sinh hoạt (chủ máy 28/09/2026)."""
    from services import lich_sinh_hoat as lsh
    luc = time.time() if luc is None else luc
    if c["che_do"] == "24":
        return True
    if c["che_do"] == "khung":
        return any(lsh.trong({"tu": x.get("tu", ""), "den": x.get("den", ""),
                              "thu": x.get("thu") if x.get("thu") is not None else range(7)}, luc)
                   for x in c["khung"] if x.get("tu") and x.get("den") and x["tu"] != x["den"])
    # nếp sinh hoạt: cả nhà vắng thì không ai ngã ở nhà
    return not any(m.get("loai") == "vang" for m in lsh.dang(luc))


# ── Dáng người ──────────────────────────────────────────────────────────────

def _phien_dang():
    global _phien
    with _khoa:
        if _phien is None:
            import onnxruntime as ort

            from services import nhin_nha, yolo_nha
            tc = ort.SessionOptions()
            tc.intra_op_num_threads = 2
            tc.inter_op_num_threads = 1
            _phien = ort.InferenceSession(str(nhin_nha.THU_MUC / yolo_nha.MODEL_DANG.tep), tc,
                                          providers=["CPUExecutionProvider"])
        return _phien


def giai_ma_dang(dau_ra, ti_le: float, le_trai: float, le_tren: float, nguong: float = TIN_NGUOI):
    """Đầu ra end-to-end ``(300, 57)`` = hộp, điểm, lớp, 17×(x, y, tin) → [(hộp, điểm, kp (17,3))]
    theo toạ độ ảnh gốc."""
    import numpy as np
    ra = []
    for d in dau_ra:
        if d[4] < nguong:
            continue
        hop = ((d[0] - le_trai) / ti_le, (d[1] - le_tren) / ti_le,
               (d[2] - le_trai) / ti_le, (d[3] - le_tren) / ti_le)
        kp = np.asarray(d[6:57], np.float32).reshape(17, 3).copy()
        kp[:, 0] = (kp[:, 0] - le_trai) / ti_le
        kp[:, 1] = (kp[:, 1] - le_tren) / ti_le
        ra.append((hop, float(d[4]), kp))
    return ra


def dang(anh) -> list:
    from services import yolo_nha
    s = _phien_dang()
    blob, tl, lt, lr = yolo_nha.letterbox(anh)
    return giai_ma_dang(s.run(None, {s.get_inputs()[0].name: blob})[0][0], tl, lt, lr)


def goc_than(kp, hop, cao_anh: int) -> float | None:
    """Thân lệch khỏi phương đứng (0 đứng, 90 nằm) — chỉ khi đo TIN được.

    Không tin khi thiếu vai hoặc hông, hoặc người chạm mép dưới ảnh: đo 28/09/2026 Cam bếp, người
    ngồi sát mép chỉ lộ vai mà vẫn ra góc 79–93° như đang nằm."""
    import numpy as np
    if hop[3] >= 0.98 * cao_anh:
        return None
    vai = [kp[i, :2] for i in (5, 6) if kp[i, 2] >= TIN_KHOP]
    hong = [kp[i, :2] for i in (11, 12) if kp[i, 2] >= TIN_KHOP]
    if not vai or not hong:
        return None
    v = np.mean(vai, 0) - np.mean(hong, 0)
    return float(np.degrees(np.arctan2(abs(v[0]), -v[1])))


# ── Theo vết, phát hiện lần chuyển sang nằm ─────────────────────────────────

class Vet:
    def __init__(self, t: float, hop, goc: float | None) -> None:
        self.t, self.hop = t, hop
        self.lich_su: deque[tuple[float, float]] = deque(maxlen=64)
        self.da_ghi = False          # đã ghi lần nằm này — chờ dậy (≤ THANG) mới xét lần sau
        if goc is not None:
            self.lich_su.append((t, goc))

    def tam(self):
        return (self.hop[0] + self.hop[2]) / 2, (self.hop[1] + self.hop[3]) / 2

    def co(self) -> float:
        return max(self.hop[2] - self.hop[0], self.hop[3] - self.hop[1], 1.0)


def ghep_vet(vets: list[Vet], t: float, nguoi: list, cao_anh: int) -> list[tuple[Vet, float | None]]:
    """Gán từng người trong khung vào vết gần nhất (tâm cách ≤ 0,6 cỡ người, thấy trong 1,5 s)."""
    import math
    ra, dung = [], set()
    for hop, _d, kp in nguoi:
        goc = goc_than(kp, hop, cao_anh)
        cx, cy = (hop[0] + hop[2]) / 2, (hop[1] + hop[3]) / 2
        tot, kc = None, None
        for v in vets:
            if id(v) in dung or t - v.t > 1.5:
                continue
            vx, vy = v.tam()
            k = math.hypot(cx - vx, cy - vy)
            if k <= 0.6 * v.co() and (kc is None or k < kc):
                tot, kc = v, k
        if tot is None:
            tot = Vet(t, hop, goc)
            vets.append(tot)
        else:
            tot.t, tot.hop = t, hop
            if goc is not None:
                tot.lich_su.append((t, goc))
        dung.add(id(tot))
        ra.append((tot, goc))
    vets[:] = [v for v in vets if t - v.t <= 5.0]
    return ra


def vua_nam(v: Vet, t: float, goc: float | None) -> bool:
    """Vết vừa chuyển từ thẳng sang nằm trong `CHUYEN_GIAY`, lần đầu kể từ khi đứng dậy."""
    if goc is None:
        return False
    if goc <= THANG:
        v.da_ghi = False
        return False
    if goc < NAM or v.da_ghi:
        return False
    if any(t - t0 <= CHUYEN_GIAY and g0 <= THANG for t0, g0 in v.lich_su if t0 < t):
        v.da_ghi = True
        return True
    return False


# ── Ghép ảnh, hỏi model, ghi sổ ─────────────────────────────────────────────

def ghep_anh(khung: list) -> bytes:
    """6 khung (trái→phải, trên→dưới) thành một JPEG, mỗi ô rộng 640."""
    import cv2
    import numpy as np
    o = [cv2.resize(a, (640, max(1, int(640 * a.shape[0] / a.shape[1])))) for a in khung[:6]]
    while len(o) < 6:
        o.append(np.zeros_like(o[-1]))
    h = max(x.shape[0] for x in o)
    o = [cv2.copyMakeBorder(x, 0, h - x.shape[0], 0, 0, cv2.BORDER_CONSTANT) for x in o]
    return cv2.imencode(".jpg", np.vstack([np.hstack(o[:3]), np.hstack(o[3:])]),
                        [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()


HOI = ("6 khung hình liên tiếp từ camera trong nhà (trái→phải, trên→dưới; 3 khung đầu là TRƯỚC lúc "
       "một người chuyển sang nằm, 3 khung sau là SAU đó tới ~20 giây). Có người NGÃ THẬT (té, trượt, "
       "mất thăng bằng, đổ xuống ngoài ý muốn) không? Phân biệt với cố ý nằm xuống, ngồi xuống sàn, nằm "
       "lên giường/sofa, tập thể dục, trẻ con chơi đùa lăn ra sàn. Chỉ trả lời JSON một dòng: "
       '{"nga": true|false, "chac": 0-100, "ly_do": "<ngắn, tiếng Việt>"}')


def doc_tra_loi(s: str) -> dict[str, Any]:
    """Cổng chat của c2a lọc mất ngoặc và nháy (bộ lọc cho loa) — đọc theo tên trường."""
    m1 = re.search(r"nga\W*(true|false)", s, re.I)
    m2 = re.search(r"chac\W*(\d+)", s, re.I)
    m3 = re.search(r"ly[ _]?do\W*(.*)", s, re.I | re.S)
    return {"nga": (m1.group(1).lower() == "true") if m1 else None,
            "chac": int(m2.group(1)) if m2 else None,
            "ly_do": (m3.group(1).strip() if m3 else s.strip())[:200]}


def hoi_model(models: list[str], anh: bytes) -> dict[str, Any]:
    """Hỏi lần lượt từng model; model lỗi hoặc trả rỗng thì sang model sau. Ghi cả lỗi đã gặp."""
    import base64

    from services.agent.runtime import call_model, content_of
    msg = [{"role": "user", "content": [
        {"type": "text", "text": HOI},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(anh).decode()}}]}]
    loi = []
    for model in models:
        t = time.time()
        # 1.500 token: Gemini tiêu phần lớn vào bước nghĩ — 300 thì câu trả lời cụt (đo 28/09/2026)
        r = call_model(model, msg, timeout=120, max_tokens=1500)
        noi_dung = "" if r.get("error") else (content_of(r) or "").strip()
        if noi_dung:
            kq = doc_tra_loi(noi_dung)
            if kq["nga"] is not None:
                return {**kq, "model": model, "giay": round(time.time() - t, 1), **({"loi_truoc": loi} if loi else {})}
        loi.append(f"{model}: {str(r.get('error') or 'trả rỗng/không đọc được')[:120]}")
    return {"loi": loi}


def _ghi(muc: dict[str, Any]) -> None:
    THU_MUC.mkdir(parents=True, exist_ok=True)
    with open(THU_MUC / "nhat_ky.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(muc, ensure_ascii=False) + "\n")


def _don_cu() -> None:
    han = time.time() - GIU_NGAY * 86400
    for p in THU_MUC.glob("*.jpg"):
        try:
            if p.stat().st_mtime < han:
                p.unlink()
        except OSError:
            pass


def chot(camera: str, lan: dict[str, Any], model: list[str]) -> dict[str, Any]:
    """Lần nằm đã theo dõi đủ: lưu ảnh ghép, hỏi model, ghi sổ. Trả mục vừa ghi."""
    anh = ghep_anh(lan["khung"])
    ten = datetime.fromtimestamp(lan["t"], _TZ).strftime("%Y%m%d_%H%M%S") + "_" + re.sub(r"\W+", "_", camera) + ".jpg"
    THU_MUC.mkdir(parents=True, exist_ok=True)
    (THU_MUC / ten).write_bytes(anh)
    muc = {"ts": round(lan["t"], 1), "gio": datetime.fromtimestamp(lan["t"], _TZ).strftime("%d/%m %H:%M:%S"),
           "camera": camera, "nam_giay": round(lan["nam_giay"], 1), "dung_day_sau": lan["dung_day_sau"],
           "goc": round(lan["goc"], 0), "anh": ten}
    if model:
        try:
            muc["model"] = hoi_model(model, anh)
        except Exception as exc:  # noqa: BLE001 — model lỗi vẫn giữ mẫu
            muc["model"] = {"loi": [str(exc)[:200]]}
    _ghi(muc)
    _stats["nghi"] += 1
    logger.info({"event": "bao_nga_nghi", **{k: v for k, v in muc.items() if k != "model"},
                 "model": muc.get("model")})
    _don_cu()
    return muc


# ── Vòng chạy ───────────────────────────────────────────────────────────────

class _Camera:
    """Trạng thái một camera: đầu đọc giữ mở, vết người, khung gần đây, các lần nằm đang theo dõi."""

    def __init__(self, ten: str, luong: str) -> None:
        self.ten, self.luong = ten, luong
        self.doc: Any = None
        self.vets: list[Vet] = []
        self.gan: deque[tuple[float, Any]] = deque()
        self.dang_theo: list[dict[str, Any]] = []
        self.lan_cuoi = float("-inf")

    def khung(self):
        from services import camera_nha
        if self.doc is None:
            self.doc = camera_nha.mo_video(self.ten, self.luong)
        kq = self.doc.khung_moi(time.time(), cho=4.0)
        return kq

    def dong(self) -> None:
        if self.doc is not None:
            try:
                self.doc.dong()
            except Exception:  # noqa: BLE001
                pass
            self.doc = None


def _khung_gan(cam: _Camera, t: float):
    """Khung trong bộ nhớ gần mốc ``t`` nhất."""
    return min(cam.gan, key=lambda x: abs(x[0] - t))[1] if cam.gan else None


def xet_khung(cam: _Camera, t: float, anh, nguoi: list, model: list[str], chot_fn=chot) -> None:
    """Một khung: cập nhật vết, mở lần theo dõi mới, cập nhật/chốt các lần đang theo dõi."""
    import cv2
    nho = cv2.resize(anh, (640, max(1, int(640 * anh.shape[0] / anh.shape[1]))))
    cam.gan.append((t, nho))
    while cam.gan and t - cam.gan[0][0] > 8.0:
        cam.gan.popleft()
    for v, goc in ghep_vet(cam.vets, t, nguoi, anh.shape[0]):
        if vua_nam(v, t, goc) and t - cam.lan_cuoi >= NGHI_GIAY:
            cam.lan_cuoi = t
            truoc = [_khung_gan(cam, t - s) for s in (3.0, 1.5, 0.0)]
            cam.dang_theo.append({"t": t, "vet": v, "goc": goc, "nam_giay": 0.0, "t_nam": t,
                                  "dung_day_sau": None, "khung": truoc})
    for lan in list(cam.dang_theo):
        g = lan["vet"].lich_su[-1][1] if lan["vet"].lich_su else None
        if lan["dung_day_sau"] is None and lan["vet"].lich_su and lan["vet"].lich_su[-1][0] == t and g is not None:
            if g >= NAM:
                lan["nam_giay"] = t - lan["t"]
            elif g <= THANG:
                lan["dung_day_sau"] = round(t - lan["t"], 1)
        # khung SAU: +4 s, +10 s, và lúc chốt
        if len(lan["khung"]) == 3 and t - lan["t"] >= 4.0:
            lan["khung"].append(nho)
        elif len(lan["khung"]) == 4 and t - lan["t"] >= 10.0:
            lan["khung"].append(nho)
        if t - lan["t"] >= THEO_GIAY or t - lan["vet"].t > 5.0:
            while len(lan["khung"]) < 6:
                lan["khung"].append(nho)
            cam.dang_theo.remove(lan)
            lan["khung"] = [k for k in lan["khung"] if k is not None] or [nho]
            threading.Thread(target=chot_fn, args=(cam.ten, lan, model), name="bao-nga-chot",
                             daemon=True).start()


def _vong(dung_ev: threading.Event) -> None:
    cams: dict[str, _Camera] = {}
    while not dung_ev.is_set():
        c = cai_dat()
        canh = c["bat"] and dang_canh(c)
        _stats["dang_canh"] = canh
        if not canh:
            for x in cams.values():
                x.dong()
            cams.clear()
            dung_ev.wait(30.0)
            continue
        bat_dau = time.time()
        for ten in c["camera"]:
            cam = cams.get(ten)
            if cam is None or cam.luong != c["luong"]:
                if cam is not None:
                    cam.dong()
                cam = cams[ten] = _Camera(ten, c["luong"])
            try:
                kq = cam.khung()
                if kq is None:
                    continue
                t, anh = kq
                nguoi = dang(anh)
                _stats["khung"] += 1
                _stats["nguoi"] += len(nguoi)
                xet_khung(cam, t, anh, nguoi, c["model"])
            except Exception as exc:  # noqa: BLE001 — một camera hỏng không dừng cả vòng
                _stats["loi"] += 1
                _stats["loi_cuoi"] = str(exc)[:160]
                cam.dong()
                dung_ev.wait(5.0)
        for ten in [k for k in cams if k not in c["camera"]]:
            cams.pop(ten).dong()
        dung_ev.wait(max(0.0, 1.0 / c["moi_giay"] - (time.time() - bat_dau)))
    for x in cams.values():
        x.dong()


def start() -> None:
    """Luôn chạy nền; nằm im (30 giây một lần xem cài đặt) khi tắt hoặc ngoài giờ canh."""
    global _luong
    with _khoa:
        if _luong is not None and _luong[0].is_alive():
            return
        ev = threading.Event()
        t = threading.Thread(target=_vong, args=(ev,), name="bao-nga", daemon=True)
        _luong = (t, ev)
        t.start()


def stop() -> None:
    with _khoa:
        if _luong is not None:
            _luong[1].set()


def trang_thai() -> dict[str, Any]:
    return dict(_stats)


def nhat_ky(toi_da: int = 50) -> list[dict[str, Any]]:
    p = THU_MUC / "nhat_ky.jsonl"
    if not p.is_file():
        return []
    ra = []
    for dong in p.read_text(encoding="utf-8").splitlines()[-toi_da:]:
        try:
            ra.append(json.loads(dong))
        except ValueError:
            pass
    return ra
