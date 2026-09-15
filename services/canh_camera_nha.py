"""Canh camera — tự nhìn, nhận ai tới, ghi lại, và báo tin theo cài đặt.

Chủ máy chốt 15/09/2026 ba điều: nguồn phát hiện người «kết hợp cả 2» (Frigate
và YOLO chạy trên máy), dạy mặt qua chat lẫn web, và bật đủ các kiểu báo tin
(người lạ, người quen về, hỏi tên mặt lạ hay gặp) — mỗi kiểu bật/tắt riêng ở
Cài đặt → Thông báo, mặc định TẮT như mọi thông báo khác (`thong_bao`).

HAI NGUỒN, MỘT ĐƯỜNG XỬ LÝ

``frigate``
    Sự kiện ``frigate/events`` nhãn ``person`` (mqtt_nha gọi ``su_kien_frigate``).
    Frigate đã chạy YOLO trên Coral nên c2a không phải quét — rẻ nhất.
``yolo``
    Luồng nền quét luồng PHỤ từng camera khai trong ``camera_nha`` rồi chạy
    YOLO26 tìm người. Dùng khi nhà không có Frigate, hoặc bổ sung khi Frigate
    im (Frigate chỉ theo dõi những camera nó được cấu hình).

Cả hai chỉ đẩy «camera X có người» vào CÙNG một hàng đợi. Luồng xử lý bóc khung
luồng CHÍNH (đủ nét để nhận mặt), chạy ``nhin_nha.phan_tich_khung``, rồi ghi sự
kiện vào ``so_mat_nha``. Hai nguồn cùng báo một lúc thì khoảng nghỉ theo camera
(`cach_giay`) gộp lại — không nhận mặt hai lần cho một khoảnh khắc.

MỘT LƯỢT, KHÔNG PHẢI MỘT KHUNG

Người ngồi xem tivi hai tiếng là hàng trăm khung có mặt. Cùng người + cùng
camera trong ``phien_phut`` phút là MỘT lượt: chỉ ghi và báo ở khung đầu. Mặt
lạ cũng vậy, theo cụm mặt lạ (``so_mat_nha.gom_mat_la``).

Cấu hình ``config['nhin_nha']['canh']`` — đọc lại mỗi vòng nên bật/tắt trên web
có hiệu lực ngay, không cần khởi động lại.
"""
from __future__ import annotations

import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from services.config import config
from utils.log import logger

_TZ = timezone(timedelta(hours=7))

#: Mặt dò được dưới điểm này thường là bóng, tranh, mặt nghiêng quá — không đưa
#: vào cụm mặt lạ (một cụm rác là một tin «người lạ» sai).
DIEM_DO_TOI_THIEU = 0.6

_MAC_DINH: dict[str, Any] = {
    "bat": False,
    "frigate": True,
    "yolo_quet": True,
    "chu_ky_giay": 2.0,
    "cach_giay": 8.0,
    "phien_phut": 10.0,
    "camera": [],          # rỗng = mọi camera đã khai
    "camera_ve": [],       # camera tính là «về nhà» — rỗng = không báo người quen về
    "hoi_ten_sau": 3,      # mặt lạ gặp ngần này lượt thì hỏi tên
    "frigate_ban_do": {},  # {"cua": "Cam cửa"} khi tên Frigate không khớp tên camera
}

_hang: "queue.Queue[tuple[str, str]]" = queue.Queue(maxsize=32)
_dang_cho: set[str] = set()
_khoa = threading.Lock()
_stop = threading.Event()
_luong: list[threading.Thread] = []
_lan_mat: dict[str, float] = {}             # camera → lúc nhận mặt gần nhất
_phien: dict[tuple[str, str], float] = {}   # (camera, người/cụm) → lúc thấy gần nhất
_hong_toi: dict[str, float] = {}            # camera → bỏ qua tới lúc (vừa lỗi)
_stats: dict[str, Any] = {"quet": 0, "co_nguoi": 0, "nhan_mat": 0, "su_kien": 0,
                          "frigate": 0, "loi": 0, "loi_cuoi": ""}


def cfg() -> dict[str, Any]:
    goc = config.data.get("nhin_nha")
    raw = goc.get("canh") if isinstance(goc, dict) else None
    ra = dict(_MAC_DINH)
    if isinstance(raw, dict):
        ra.update({k: v for k, v in raw.items() if k in _MAC_DINH})
    return ra


def _so(v: Any, mac_dinh: float, thap: float, cao: float) -> float:
    try:
        return max(thap, min(cao, float(v)))
    except (TypeError, ValueError):
        return mac_dinh


def _camera_duoc_canh(c: dict[str, Any]) -> list[str]:
    from services import camera_nha

    ten = [x["name"] for x in camera_nha.danh_sach()]
    chon = [str(x) for x in (c.get("camera") or []) if str(x).strip()]
    return [t for t in ten if not chon or t in chon]


# ── Nguồn: Frigate ──────────────────────────────────────────────────────────

def su_kien_frigate(su_kien: Any) -> None:
    """mqtt_nha gọi cho mỗi tin ``frigate/events``. KHÔNG chặn, KHÔNG raise."""
    try:
        c = cfg()
        if not c["bat"] or not c["frigate"] or not isinstance(su_kien, dict):
            return
        if str(su_kien.get("type") or "") not in ("new", "update"):
            return
        sau = su_kien.get("after") or {}
        if not isinstance(sau, dict) or str(sau.get("label") or "") != "person":
            return
        cam_frigate = str(sau.get("camera") or "")
        ban_do = c["frigate_ban_do"] if isinstance(c["frigate_ban_do"], dict) else {}
        ten = str(ban_do.get(cam_frigate) or "")
        if not ten:
            from services import camera_nha
            ten, ban_ghi, _ = camera_nha.tim(cam_frigate)
            if ban_ghi is None:
                return
        _stats["frigate"] += 1
        yeu_cau(ten, "frigate")
    except Exception as exc:
        _stats["loi"] += 1
        _stats["loi_cuoi"] = f"frigate: {str(exc)[:120]}"


# ── Hàng đợi ────────────────────────────────────────────────────────────────

def yeu_cau(camera: str, nguon: str) -> bool:
    """Xin nhận mặt ở ``camera``. Đang chờ sẵn hoặc vừa nhận xong thì bỏ qua."""
    now = time.time()
    c = cfg()
    with _khoa:
        if camera in _dang_cho:
            return False
        if now - _lan_mat.get(camera, 0.0) < _so(c["cach_giay"], 8.0, 1.0, 600.0):
            return False
        if camera not in _camera_duoc_canh(c):
            return False
        try:
            _hang.put_nowait((camera, nguon))
        except queue.Full:
            return False
        _dang_cho.add(camera)
    return True


def _vong_xu_ly() -> None:
    while not _stop.is_set():
        try:
            camera, nguon = _hang.get(timeout=1.0)
        except queue.Empty:
            continue
        with _khoa:
            _dang_cho.discard(camera)
            _lan_mat[camera] = time.time()
        try:
            if cfg()["bat"]:
                xu_ly(camera, nguon)
        except Exception as exc:
            _stats["loi"] += 1
            _stats["loi_cuoi"] = f"{camera}: {str(exc)[:160]}"
            logger.warning({"event": "canh_camera_loi", "camera": camera, "loi": str(exc)[:200]})


# ── Nguồn: YOLO tự quét ─────────────────────────────────────────────────────

def _vong_quet() -> None:
    from services import camera_nha, nhin_nha, yolo_nha

    while not _stop.is_set():
        c = cfg()
        nghi = _so(c["chu_ky_giay"], 2.0, 0.5, 600.0)
        if not c["bat"] or not c["yolo_quet"] or not nhin_nha.co_yolo():
            _stop.wait(5.0)
            continue
        for ten in _camera_duoc_canh(c):
            if _stop.is_set():
                return
            if time.time() < _hong_toi.get(ten, 0.0):
                continue
            try:
                _, tho = camera_nha.chup_tho(ten, phu=True, timeout=10)
                nguoi = nhin_nha.vat_the(yolo_nha.doc_anh(tho), chi_nhan={"person"})
                _stats["quet"] += 1
            except Exception as exc:
                # Camera chết thì nghỉ nó 60 giây — không để một camera hỏng
                # làm chậm cả vòng, cũng không dội log mỗi 2 giây.
                _hong_toi[ten] = time.time() + 60
                _stats["loi"] += 1
                _stats["loi_cuoi"] = f"quét {ten}: {str(exc)[:120]}"
                continue
            if nguoi:
                _stats["co_nguoi"] += 1
                yeu_cau(ten, "yolo")
        _stop.wait(nghi)


# ── Nhận mặt, ghi, báo ──────────────────────────────────────────────────────

def _gio(ts: float) -> str:
    return datetime.fromtimestamp(ts, _TZ).strftime("%H:%M")


def _luu_anh_bao(anh, hop) -> str:
    """Ảnh vùng người/mặt cho tin báo → URL /images/ (cùng thư viện ảnh camera)."""
    import cv2

    from services.local_gateway import gateway_base_url

    cao, rong = anh.shape[:2]
    x1, y1, x2, y2 = hop
    le_x, le_y = (x2 - x1) * 1.2, (y2 - y1) * 1.2
    a, b = int(max(0, x1 - le_x)), int(max(0, y1 - le_y))
    c, d = int(min(rong, x2 + le_x)), int(min(cao, y2 + le_y * 2))
    ok, buf = cv2.imencode(".jpg", anh[b:d, a:c], [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        return ""
    thu_muc = config.images_dir / time.strftime("%Y") / time.strftime("%m") / time.strftime("%d")
    thu_muc.mkdir(parents=True, exist_ok=True)
    tep = f"camera_mat_{int(time.time() * 1000)}.jpg"
    (thu_muc / tep).write_bytes(buf.tobytes())
    return f"{gateway_base_url()}/images/{time.strftime('%Y/%m/%d')}/{tep}"


def xu_ly(camera: str, nguon: str) -> dict[str, Any]:
    """Một lượt nhận mặt ở ``camera``. Trả tóm tắt để test và web xem."""
    from services import camera_nha, nhin_nha, so_mat_nha, yolo_nha

    c = cfg()
    if not nhin_nha.co_mat():
        return {"bo_qua": "chưa tải model mặt"}
    _, tho = camera_nha.chup_tho(camera, timeout=15)
    anh = yolo_nha.doc_anh(tho)
    k = nhin_nha.phan_tich_khung(anh)
    _stats["nhan_mat"] += 1
    now = time.time()
    phien = _so(c["phien_phut"], 10.0, 0.5, 24 * 60) * 60
    ra: dict[str, Any] = {"nguoi": sum(v.nhan == "person" for v in k.vat_the),
                          "mat": len(k.mat), "su_kien": []}
    for m in k.mat:
        if m["nho"] or m["diem_do"] < DIEM_DO_TOI_THIEU:
            continue
        mat_la_id = None
        if m["loai"] == "la":
            mat_la_id, _moi = so_mat_nha.gom_mat_la(m["vector"], anh, m["hop"], camera)
            khoa_luot = f"la:{mat_la_id}"
        else:
            khoa_luot = f"nguoi:{m['nguoi_id']}"
        with _khoa:
            truoc = _phien.get((camera, khoa_luot), 0.0)
            _phien[(camera, khoa_luot)] = now
        if now - truoc < phien:
            continue                     # vẫn lượt cũ — không ghi, không báo lại
        anh_url = ""
        try:
            anh_url = _luu_anh_bao(anh, m["hop"])
        except Exception as exc:
            logger.info({"event": "canh_camera_luu_anh_loi", "loi": str(exc)[:120]})
        sk = so_mat_nha.ghi_su_kien(camera, nguon, m["loai"], nguoi_id=m["nguoi_id"],
                                    mat_la_id=mat_la_id, do_giong=m["do_giong"],
                                    hop=m["hop"], anh=anh_url, ts=now)
        _stats["su_kien"] += 1
        ra["su_kien"].append(sk)
        _bao(camera, m, mat_la_id, anh_url, now, c)
    _don_phien(now, phien)
    return ra


def _don_phien(now: float, phien: float) -> None:
    with _khoa:
        for k in [k for k, t in _phien.items() if now - t > phien * 2]:
            del _phien[k]


def _bao(camera: str, m: dict[str, Any], mat_la_id: str | None, anh_url: str,
         ts: float, c: dict[str, Any]) -> None:
    """Gửi qua sổ đăng ký thông báo — chưa bật/chưa chọn kênh thì `thong_bao` tự im."""
    from services import so_mat_nha, thong_bao

    if m["loai"] == "quen":
        if camera in [str(x) for x in (c.get("camera_ve") or [])]:
            thong_bao.gui("camera.nguoi_quen",
                          f"🏠 {m['ten']} vừa về — {camera} lúc {_gio(ts)}.", anh_url)
        return
    if m["loai"] != "la" or not mat_la_id:
        return
    la = so_mat_nha.mat_la(mat_la_id) or {}
    so_lan = int(la.get("so_lan") or 1)
    thong_bao.gui("camera.nguoi_la",
                  f"👤 Người lạ ở {camera} lúc {_gio(ts)}"
                  + (f" — đã gặp {so_lan} lượt." if so_lan > 1 else ".")
                  + f"\nNếu là người quen, nhắn «mặt lạ {mat_la_id} là <tên>» để em nhớ.",
                  anh_url)
    if so_mat_nha.nen_hoi_mat_la(mat_la_id, int(_so(c["hoi_ten_sau"], 3, 1, 100))):
        gui = thong_bao.gui(
            "camera.hoi_ten",
            "\n".join([
                f"👤 Mặt này em gặp {so_lan} lượt rồi (gần nhất ở {camera} lúc {_gio(ts)}).",
                "Đây là ai ạ? Nhắn tên để em nhớ mặt, vd "
                f"«mặt lạ {mat_la_id} là bà ngoại».",
                "<<<ASK>>>",
                f"Để sau | để sau hỏi lại về mặt lạ {mat_la_id}",
                f"Người lạ, đừng hỏi nữa | thôi hỏi về mặt lạ {mat_la_id}",
                "<<<END>>>",
            ]), anh_url)
        if gui:
            so_mat_nha.danh_dau_da_hoi(mat_la_id)


# ── Vòng đời ────────────────────────────────────────────────────────────────

def start() -> bool:
    """Bật hai luồng nền (một lần). Luồng tự nằm im khi ``bat`` tắt."""
    with _khoa:
        if any(t.is_alive() for t in _luong):
            return False
        _stop.clear()
        _luong.clear()
        for ten, ham in (("canh-camera-xu-ly", _vong_xu_ly), ("canh-camera-quet", _vong_quet)):
            t = threading.Thread(target=ham, name=ten, daemon=True)
            t.start()
            _luong.append(t)
    return True


def stop() -> None:
    _stop.set()


def trang_thai() -> dict[str, Any]:
    c = cfg()
    return {"cau_hinh": c, "dang_chay": any(t.is_alive() for t in _luong),
            "hang_doi": _hang.qsize(), **_stats}
