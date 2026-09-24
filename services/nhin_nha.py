"""Mắt của nhà — cấu hình và bộ máy dùng chung cho YOLO + nhận khuôn mặt.

Hai bộ máy nặng (``yolo_nha.BoPhatHien``, ``khuon_mat_nha.BoNhanMat``) nạp MỘT
lần rồi ở lại trong tiến trình, như model TTS. Mọi nơi cần nhìn — tool camera,
menu ảnh, luồng canh camera, trang web — lấy qua ``yolo()`` / ``mat()`` ở đây,
không tự nạp phiên ONNX riêng (mỗi phiên buffalo_l giữ vài trăm MB).

Cấu hình nằm ở ``config['nhin_nha']``, cùng lối ``cameras`` và ``mqtt``:

    {"yolo": {"model": "yolo26n", "nguong": 0.35, "luong": 2},
     "khuon_mat": {"bo": "buffalo_s", "nguong_co_the": 40, "nguong_chac": 55,
                   "luong": 2}}

Model tải bằng ``scripts/download_nhin_nha.py`` về ``data/nhin-nha/``. Chưa tải
thì ``ChuaCoModel`` mang sẵn câu chỉ cách tải — đọc thẳng cho người dùng được.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from services import khuon_mat_nha, yolo_nha
from services.config import DATA_DIR, config

THU_MUC = Path(DATA_DIR) / "nhin-nha"
LENH_TAI = "docker exec c2a /app/.venv/bin/python scripts/download_nhin_nha.py"

#: Ngưỡng của IRIS (`db.py`: match 40, auto_accept 55): từ 40 là «có thể là»,
#: từ 55 là chắc. Chỉnh cho buffalo_s; IRIS dặn phải hiệu chỉnh trên camera thật.
NGUONG_CO_THE = 40.0
NGUONG_CHAC = 55.0


class ChuaCoModel(RuntimeError):
    """Model chưa tải — thông điệp đã kèm lệnh tải."""


def _muc(ten: str) -> dict[str, Any]:
    goc = config.data.get("nhin_nha")
    raw = goc.get(ten) if isinstance(goc, dict) else None
    return raw if isinstance(raw, dict) else {}


def _so(raw: Any, mac_dinh: float, thap: float, cao: float) -> float:
    try:
        return max(thap, min(cao, float(raw)))
    except (TypeError, ValueError):
        return mac_dinh


def model_yolo() -> yolo_nha.ModelYolo:
    return yolo_nha.get(str(_muc("yolo").get("model") or "")) or yolo_nha.get(yolo_nha.MAC_DINH)


def bo_mat() -> khuon_mat_nha.BoMat:
    return (khuon_mat_nha.get(str(_muc("khuon_mat").get("bo") or ""))
            or khuon_mat_nha.get(khuon_mat_nha.MAC_DINH))


def nguong_yolo() -> float:
    return _so(_muc("yolo").get("nguong"), 0.35, 0.05, 0.95)


def nguong_mat() -> tuple[float, float]:
    """``(có thể là, chắc chắn)`` trên thang 0–100."""
    co_the = _so(_muc("khuon_mat").get("nguong_co_the"), NGUONG_CO_THE, 10, 95)
    chac = _so(_muc("khuon_mat").get("nguong_chac"), NGUONG_CHAC, 10, 99)
    return co_the, max(co_the, chac)


def _luong(ten: str) -> int:
    return int(_so(_muc(ten).get("luong"), 2, 1, 8))


def duong_yolo(m: yolo_nha.ModelYolo | None = None) -> Path:
    return THU_MUC / (m or model_yolo()).tep


def thu_muc_mat(b: khuon_mat_nha.BoMat | None = None) -> Path:
    return THU_MUC / (b or bo_mat()).ma


def co_yolo() -> bool:
    return duong_yolo().is_file()


def co_mat() -> bool:
    b = bo_mat()
    d = thu_muc_mat(b)
    return (d / b.tep_do).is_file() and (d / b.tep_vector).is_file()


_khoa = threading.Lock()
_yolo: tuple[tuple, yolo_nha.BoPhatHien] | None = None
_mat: tuple[tuple, khuon_mat_nha.BoNhanMat] | None = None


def yolo() -> yolo_nha.BoPhatHien:
    """Bộ nhận vật thể theo cấu hình hiện tại. Đổi model/luồng thì nạp lại."""
    global _yolo
    m = model_yolo()
    khoa = (m.ma, _luong("yolo"))
    with _khoa:
        if _yolo is None or _yolo[0] != khoa:
            if not duong_yolo(m).is_file():
                raise ChuaCoModel(f"Chưa tải model nhận vật thể {m.ma}. Chạy: "
                                  f"{LENH_TAI} --yolo {m.ma}")
            _yolo = (khoa, yolo_nha.BoPhatHien(duong_yolo(m), luong=khoa[1]))
        return _yolo[1]


def mat() -> khuon_mat_nha.BoNhanMat:
    """Bộ nhận khuôn mặt theo cấu hình hiện tại. Đổi bộ/luồng thì nạp lại."""
    global _mat
    b = bo_mat()
    khoa = (b.ma, _luong("khuon_mat"))
    with _khoa:
        if _mat is None or _mat[0] != khoa:
            if not co_mat():
                raise ChuaCoModel(f"Chưa tải model nhận khuôn mặt {b.ma}. Chạy: "
                                  f"{LENH_TAI} --mat {b.ma}")
            _mat = (khoa, khuon_mat_nha.BoNhanMat(thu_muc_mat(b), b, luong=khoa[1]))
        return _mat[1]


def vat_the(anh, *, chi_nhan: set[str] | None = None,
            nguong: float | None = None) -> list[yolo_nha.VatThe]:
    """Vật thể trong ảnh BGR, theo ngưỡng cấu hình."""
    return yolo().phat_hien(anh, nguong_yolo() if nguong is None else nguong, chi_nhan)


# ── Phân tích một khung camera ──────────────────────────────────────────────

#: Lề quanh hộp NGƯỜI trước khi dò mặt — YOLO hay cắt sát đỉnh đầu.
_LE_NGUOI = 0.15


@dataclass
class KhungDaXem:
    rong: int
    cao: int
    vat_the: list = field(default_factory=list)   # [yolo_nha.VatThe], điểm cao trước
    mat: list = field(default_factory=list)       # [dict của so_mat_nha.nhan_dien_anh + "nguoi_so"]


def _iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    giao = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    hop = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - giao
    return giao / hop if hop > 0 else 0.0


def phan_tich_khung(anh, *, nhan_mat: bool = True,
                    hop_nguoi: list | None = None) -> KhungDaXem:
    """Vật thể + khuôn mặt trong một khung ảnh BGR.

    Chỉ dò mặt TRONG hộp người mà YOLO tìm được, không dò cả khung: khung luồng
    chính 2688×1664 thu về 640 thì mặt người đứng xa còn vài pixel, SCRFD bỏ
    sót; cắt vùng người rồi mới thu thì mặt đủ to. Chưa tải model mặt thì chỉ
    trả vật thể (``mat`` rỗng) — không làm hỏng câu hỏi «trong bếp có gì».

    ``hop_nguoi`` — danh sách ``yolo_nha.VatThe`` dựng sẵn (Frigate đã dò giúp)
    thì DÙNG LUÔN thay vì chạy YOLO, tiết kiệm một lượt suy luận mỗi khung.
    Hộp ấy chụp tại thời điểm Frigate báo, còn khung này lấy sau đó một hai
    giây — người đã dịch chỗ — nên nếu KHÔNG ra mặt nào thì tự chạy lại bằng
    YOLO trên đúng khung này. Đường dự phòng đó là điều kiện để dùng hộp sẵn
    không bao giờ tệ hơn cách cũ.
    """
    from services import so_mat_nha

    cao, rong = anh.shape[:2]
    ra = KhungDaXem(rong, cao, list(hop_nguoi) if hop_nguoi else vat_the(anh))
    if not nhan_mat or not co_mat():
        return ra
    may = mat()
    for i, v in enumerate(ra.vat_the):
        if v.nhan != "person":
            continue
        x1, y1, x2, y2 = v.hop
        le_x, le_y = (x2 - x1) * _LE_NGUOI, (y2 - y1) * _LE_NGUOI
        a, b = int(max(0, x1 - le_x)), int(max(0, y1 - le_y))
        c, d = int(min(rong, x2 + le_x)), int(min(cao, y2 + le_y))
        for m in so_mat_nha.nhan_dien_anh(anh[b:d, a:c], may)["mat"]:
            # Mọi toạ độ của mặt về hệ của CẢ khung — hộp lẫn năm điểm mốc. Từ
            # 6042b0a (22/09/2026) ảnh lưu được căn theo mốc trên cả khung; mốc
            # còn theo vùng cắt thì ảnh ra góc trên-trái khung: tường, song cửa
            # (chủ máy 24/09/2026: "toàn thấy tường nhà, cửa nhà").
            m["hop"] = [m["hop"][0] + a, m["hop"][1] + b, m["hop"][2] + a, m["hop"][3] + b]
            if m.get("moc"):
                m["moc"] = [[x + a, y + b] for x, y in m["moc"]]
            m["nguoi_so"] = i
            # Hai hộp người chồng nhau thì một mặt bị dò hai lần — giữ lần rõ hơn.
            trung = next((x for x in ra.mat if _iou(x["hop"], m["hop"]) > 0.5), None)
            if trung is None:
                ra.mat.append(m)
            elif m["diem_do"] > trung["diem_do"]:
                ra.mat[ra.mat.index(trung)] = m
    # Dùng hộp sẵn mà không ra mặt nào: người đã dịch khỏi chỗ Frigate thấy.
    # Chạy lại bằng YOLO trên đúng khung này — chậm hơn, nhưng không bỏ sót.
    if hop_nguoi and not ra.mat and nhan_mat and co_mat():
        return phan_tich_khung(anh, nhan_mat=nhan_mat)
    return ra


def ten_mat(m: dict[str, Any]) -> str:
    if m.get("loai") == "quen":
        return str(m["ten"])
    if m.get("loai") == "co_the":
        return f"có thể là {m['ten']}"
    return "người lạ"


def mo_ta(k: KhungDaXem) -> str:
    """Kết quả bằng lời: đếm theo loại, rồi từng vật (số khớp số vẽ trên ảnh)."""
    from collections import Counter

    if not k.vat_the:
        return "Em không thấy vật thể nào em nhận ra được trong khung hình."
    dem = Counter(v.ten for v in k.vat_the)
    dong = ["Thấy: " + ", ".join(f"{n} {t}" for t, n in dem.most_common()) + "."]
    mat_theo_nguoi: dict[int, dict] = {}
    for m in k.mat:
        cu = mat_theo_nguoi.get(m["nguoi_so"])
        if cu is None or m["diem_do"] > cu["diem_do"]:
            mat_theo_nguoi[m["nguoi_so"]] = m
    for i, v in enumerate(k.vat_the, 1):
        x1, y1, x2, y2 = v.hop
        dong.append(f"{i}. {v.ten} — {yolo_nha.vi_tri(v.hop, k.rong, k.cao)}, "
                    f"khung ({x1},{y1})–({x2},{y2}), {v.diem * 100:.0f}%")
        m = mat_theo_nguoi.get(i - 1)
        if m is not None:
            dong[-1] += (f" · mặt: {ten_mat(m)}"
                         + (f" ({m['do_giong']:.0f}/100)" if m.get("loai") != "la" else "")
                         + (" — mặt nhỏ, kém chắc" if m.get("nho") else ""))
    return "\n".join(dong)


def ve_khung(anh, k: KhungDaXem) -> bytes:
    """Ảnh JPEG có khung đánh số (người xanh lá, vật khác cam, mặt quen xanh dương)."""
    import cv2

    ve = anh.copy()
    day = max(2, round(max(k.rong, k.cao) / 600))
    for i, v in enumerate(k.vat_the, 1):
        mau = (60, 200, 60) if v.nhan == "person" else (0, 150, 255)
        x1, y1, x2, y2 = v.hop
        cv2.rectangle(ve, (x1, y1), (x2, y2), mau, day)
        cv2.putText(ve, str(i), (x1 + day, max(y1 - day * 2, day * 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, day * 0.6, mau, day)
    for m in k.mat:
        mau = {"quen": (255, 120, 0), "co_the": (0, 220, 255)}.get(m.get("loai"), (0, 0, 255))
        x1, y1, x2, y2 = (int(x) for x in m["hop"])
        cv2.rectangle(ve, (x1, y1), (x2, y2), mau, max(1, day - 1))
    ok, buf = cv2.imencode(".jpg", ve, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise ValueError("không mã hoá được ảnh đã vẽ khung")
    return buf.tobytes()


def trang_thai() -> dict[str, Any]:
    """Cho web và tool: đã tải model nào, đang dùng model nào."""
    m, b = model_yolo(), bo_mat()
    co_the, chac = nguong_mat()
    return {
        "thu_muc": str(THU_MUC),
        "yolo": {"model": m.ma, "da_tai": co_yolo(), "nguong": nguong_yolo(),
                 "cac_model": [{"ma": x.ma, "mb": x.mb, "mo_ta": x.mo_ta,
                                "da_tai": duong_yolo(x).is_file()} for x in yolo_nha.MODELS]},
        "khuon_mat": {"bo": b.ma, "da_tai": co_mat(),
                      "nguong_co_the": co_the, "nguong_chac": chac,
                      "cac_bo": [{"ma": x.ma, "mb": x.zip_mb, "mo_ta": x.mo_ta,
                                  "da_tai": (thu_muc_mat(x) / x.tep_do).is_file()
                                  and (thu_muc_mat(x) / x.tep_vector).is_file()}
                                 for x in khuon_mat_nha.BO]},
        "lenh_tai": LENH_TAI,
    }
