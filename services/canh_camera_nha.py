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
    "camera": [],          # rỗng = KHÔNG canh camera nào
    "camera_ve": [],       # camera tính là «về nhà» — rỗng = không báo người quen về
    "nhan": ["person"],    # nhãn YOLO cần tìm; nhãn KHÁC người chỉ để báo tin
    "so_khung_luot": 5,    # nhìn mấy khung trong MỘT lượt rồi mới quyết
    "khoang_khung_giay": 0.5,   # cách nhau bao lâu giữa hai khung trong lượt
    "dong_thuan": 2,       # phải ngần này lần nhìn cùng chỉ một người mới dám gọi tên
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
#: camera → (lúc nhận, hộp người Frigate vừa báo). ĐỂ NGOÀI hàng đợi có chủ ý:
#: hình dạng bản ghi trong ``_hang`` là hợp đồng đã có test canh
#: (``test_canh_camera_nha`` khẳng định ``("Cam cửa", "frigate")``), nên nhét
#: thêm dữ liệu vào đó là phá thứ đang được bảo vệ. Sổ tạm theo camera đi đúng
#: lối của ``_dang_cho`` / ``_lan_mat`` / ``_phien`` ngay trên.
_goi_y: dict[str, tuple[float, list]] = {}

#: Cỡ luồng DÒ của Frigate. Hộp trong bản tin MQTT tính bằng PIXEL của luồng
#: này — đo bản tin thật 18/09/2026: ``after.box = [188, 266, 244, 381]``, tức
#: (x1, y1, x2, y2). Khác hẳn API REST (``data.box`` là tỉ lệ 0–1); lấy nhầm
#: đơn vị là cắt ra vùng nằm ngoài ảnh mà không có lỗi nào báo.
_FRIGATE_RONG, _FRIGATE_CAO = 640, 480


_stats: dict[str, Any] = {"quet": 0, "co_nguoi": 0, "thay_vat": 0, "nhan_mat": 0,
                          "su_kien": 0, "frigate": 0, "ben_bi": 0,
                          "khung_trong_luot": 0, "ha_vi_thieu_dong_thuan": 0,
                          "loi": 0, "loi_cuoi": ""}


def _hop_tu_frigate(hop, rong: int, cao: int, diem: float) -> list:
    """Hộp Frigate (pixel luồng dò) → ``VatThe`` theo pixel ảnh luồng chính.

    Trả danh sách rỗng khi hộp vô lý. Kiểm tra ấy là phần QUAN TRỌNG: nếu cỡ
    luồng dò đổi mà hằng số ``_FRIGATE_RONG``/``_FRIGATE_CAO`` chưa đổi theo,
    hộp sẽ lệch — thà bỏ hộp và để YOLO tự dò còn hơn cắt nhầm vùng rồi lặng
    lẽ mất mặt.
    """
    from services import yolo_nha

    try:
        x1, y1, x2, y2 = (float(v) for v in hop)
    except (TypeError, ValueError):
        return []
    if x2 <= x1 or y2 <= y1:
        return []
    if max(x2, x1) > _FRIGATE_RONG * 1.02 or max(y2, y1) > _FRIGATE_CAO * 1.02:
        return []
    tx, ty = rong / _FRIGATE_RONG, cao / _FRIGATE_CAO
    a, b = int(max(0, x1 * tx)), int(max(0, y1 * ty))
    c, d = int(min(rong, x2 * tx)), int(min(cao, y2 * ty))
    if c - a < 8 or d - b < 8:
        return []
    return [yolo_nha.VatThe("person", float(diem or 0.5), (a, b, c, d))]


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
    """Camera đang được canh. KHÔNG tích camera nào ⇒ KHÔNG canh gì cả.

    Chủ máy chốt 16/09/2026: *"khi không tích cam nào là không dùng yolo"*.
    Trước đây danh sách rỗng nghĩa là MỌI camera, nên bỏ tích hết vẫn quét đủ
    bốn camera — ngược hẳn ý người dùng, và là cách đốt CPU không ai xin.
    """
    from services import camera_nha

    chon = {str(x).strip() for x in (c.get("camera") or []) if str(x).strip()}
    if not chon:
        return []
    return [x["name"] for x in camera_nha.danh_sach() if x["name"] in chon]


def _nhan_canh(c: dict[str, Any]) -> set[str]:
    """Nhãn YOLO cần tìm khi quét. Không khai gì thì chỉ tìm «person».

    Nhãn KHÁC người chỉ dùng để BÁO TIN, không kéo theo nhận khuôn mặt: chạy
    nhận mặt lên một con chó là đốt 300 ms cho không có gì.
    """
    ds = {str(x).strip() for x in (c.get("nhan") or []) if str(x).strip()}
    return ds or {"person"}


def _bao_vat(camera: str, nhan: set[str], ts: float, c: dict[str, Any]) -> None:
    """Báo «thấy <vật>» cho nhãn khác người, gộp theo cửa sổ ``phien_phut``.

    Không gộp thì một con mèo nằm trong khung sẽ sinh một tin mỗi vòng quét.
    """
    from services import thong_bao
    from services.yolo_nha import TEN_VIET

    phien = _so(c["phien_phut"], 10.0, 0.5, 24 * 60) * 60
    moi = []
    with _khoa:
        for n in sorted(nhan):
            khoa = (camera, f"vat:{n}")
            if ts - _phien.get(khoa, 0.0) >= phien:
                moi.append(n)
            _phien[khoa] = ts
    if not moi:
        return
    ten = ", ".join(TEN_VIET.get(n, n) for n in moi)
    thong_bao.gui("camera.thay_vat", f"👁️ Thấy {ten} ở {camera} lúc {_gio(ts)}.")


# ── Nguồn: Frigate ──────────────────────────────────────────────────────────

def camera_tu_frigate(ma: str, c: dict[str, Any]) -> str:
    """Mã camera Frigate (``cua``, ``phong-khach``) → tên camera đã khai. Không chắc → ``""``.

    KHÔNG dùng ``camera_nha.tim``: hàm đó khớp CÂU NGƯỜI NÓI nên bỏ «từ chung»
    trước khi chấm — mà «cua» (của) nằm trong danh sách đó, nên mã ``cua`` của
    camera cửa không khớp «Cam cửa». Đo 15/09/2026: bốn camera Frigate thì
    đúng camera cửa rơi mất. Mã máy không có từ thừa, nên luật ở đây là: MỌI
    từ của mã phải có trong tên camera, và chỉ đúng MỘT camera thoả.
    """
    from services import camera_nha

    ban_do = c.get("frigate_ban_do") if isinstance(c.get("frigate_ban_do"), dict) else {}
    if ban_do.get(ma):
        return str(ban_do[ma])
    tu = camera_nha._tu(ma)
    if not tu:
        return ""
    khop = [x["name"] for x in camera_nha.danh_sach()
            if tu <= camera_nha._tu(x["name"]) | camera_nha._tu(str(x.get("note") or ""))]
    return khop[0] if len(khop) == 1 else ""


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
        ten = camera_tu_frigate(str(sau.get("camera") or ""), c)
        if not ten:
            return
        _stats["frigate"] += 1
        # Giữ lại hộp người Frigate vừa dò: `xu_ly` dùng nó cho khung ĐẦU TIÊN
        # để khỏi chạy lại YOLO. Ghi đè bản cũ là đúng — tin mới luôn sát thực
        # tế hơn tin cũ vài giây.
        hop = sau.get("box")
        if isinstance(hop, (list, tuple)) and len(hop) == 4:
            with _khoa:
                _goi_y[ten] = (time.time(), list(hop))
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
                # Kết nối giữ mở trả khung trong 0–4 ms; `chup_tho` tốn ~1 giây
                # mỗi lần vì go2rtc phải chờ khung khoá (đo 16/09/2026, 20 lần).
                # Không dùng được thì rơi về cách cũ — chậm chứ không mất ảnh.
                anh = camera_nha.khung_ben_bi(ten)
                if anh is None:
                    _, tho = camera_nha.chup_tho(ten, phu=True, timeout=10)
                    anh = yolo_nha.doc_anh(tho)
                else:
                    _stats["ben_bi"] += 1
                thay = nhin_nha.vat_the(anh, chi_nhan=_nhan_canh(c))
                _stats["quet"] += 1
            except Exception as exc:
                # Camera chết thì nghỉ nó 60 giây — không để một camera hỏng
                # làm chậm cả vòng, cũng không dội log mỗi 2 giây.
                _hong_toi[ten] = time.time() + 60
                _stats["loi"] += 1
                _stats["loi_cuoi"] = f"quét {ten}: {str(exc)[:120]}"
                continue
            if not thay:
                continue
            khac = {v.nhan for v in thay if v.nhan != "person"}
            if khac:
                _stats["thay_vat"] += 1
                _bao_vat(ten, khac, time.time(), c)
            if any(v.nhan == "person" for v in thay):
                # CHỈ người mới kéo theo nhận mặt — và `xu_ly` lấy LUỒNG CHÍNH
                # nguyên cỡ, không phải khung luồng phụ vừa quét: mặt ở luồng
                # phụ 640×480 chỉ còn vài pixel, không nhận ra ai.
                _stats["co_nguoi"] += 1
                yeu_cau(ten, "yolo")
        _stop.wait(nghi)


# ── Nhận mặt, ghi, báo ──────────────────────────────────────────────────────

def _gio(ts: float) -> str:
    return datetime.fromtimestamp(ts, _TZ).strftime("%H:%M")


def _vung_mat(anh, hop, moc=None):
    """Ảnh chỉ còn khuôn mặt, để xem và để dạy lại.

    Ảnh báo trước nới hộp 1,2 lần mỗi cạnh rồi cộng thêm hai lần chiều cao
    xuống dưới — ra cả người, mặt nhỏ ở phía trên. Bộ dò thu ảnh ấy về 640
    thì mất mặt, nên bấm «thêm vào nguồn» không học được.

    Có năm điểm mốc thì căn thẳng mặt cho đầy khung. Không có thì cắt sát hộp
    với một ít lề, cùng cách sổ mặt lưu ảnh nguồn.
    """
    import cv2
    import numpy as np

    from services.khuon_mat_nha import can_mat
    from services.so_mat_nha import _LE

    if moc is not None:
        diem = np.asarray(moc, np.float32)
        if diem.shape == (5, 2) and np.isfinite(diem).all():
            return can_mat(anh, diem, canh=256)
    # `_cat_mat` trả JPEG. Ở đây cần mảng để người gọi nén một lần.
    cao, rong = anh.shape[:2]
    x1, y1, x2, y2 = (float(v) for v in hop)
    le_x, le_y = (x2 - x1) * _LE, (y2 - y1) * _LE
    a, b = int(max(0, x1 - le_x)), int(max(0, y1 - le_y))
    c, d = int(min(rong, x2 + le_x)), int(min(cao, y2 + le_y))
    if c <= a or d <= b:
        return anh
    return anh[b:d, a:c]


def _luu_anh_bao(anh, hop, moc=None) -> str:
    """Ảnh mặt cho tin báo → URL /images/ (cùng thư viện ảnh camera)."""
    import cv2

    from services.local_gateway import gateway_base_url

    mat = _vung_mat(anh, hop, moc)
    ok, buf = cv2.imencode(".jpg", mat, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        return ""
    thu_muc = config.images_dir / time.strftime("%Y") / time.strftime("%m") / time.strftime("%d")
    thu_muc.mkdir(parents=True, exist_ok=True)
    tep = f"camera_mat_{int(time.time() * 1000)}.jpg"
    (thu_muc / tep).write_bytes(buf.tobytes())
    return f"{gateway_base_url()}/images/{time.strftime('%Y/%m/%d')}/{tep}"


def _diem_chat_luong(anh, m: dict[str, Any]) -> float:
    """Chấm 0–1 cho một khuôn mặt bắt được: dò chắc tới đâu, to tới đâu, nét tới đâu.

    Vì sao cần: đo 17/09/2026 trên camera bếp, CÙNG một người lúc 09:26 cúi đầu
    thì không model nào dò ra mặt (thử cả `buffalo_l`), lúc 09:27 ngẩng lên thì
    ra ngay. Nhìn đúng một khung rồi quyết là phó mặc cho may rủi.

    KHÔNG dùng 5 điểm mốc dù bộ dò có sinh ra: `so_mat_nha.nhan_dien_anh` không
    mang `moc` ra ngoài, và fixture test cũng không có — bộ chấm phải chạy được
    khi thiếu, nếu không là vỡ mọi test cũ.
    """
    import cv2

    diem_do = float(m.get("diem_do") or 0.0)
    try:
        x1, y1, x2, y2 = (int(v) for v in m["hop"])
        canh = max(1, min(x2 - x1, y2 - y1))
    except Exception:  # noqa: BLE001 — hộp lạ thì chấm theo mỗi điểm dò
        return round(diem_do, 4)
    # 40 px là sàn cho phép dạy (`MAT_NHO_NHAT`); từ 160 px trở lên coi như đủ to.
    co = min(1.0, max(0.0, (canh - 40) / 120.0))
    net = 0.0
    try:
        o = anh[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
        if getattr(o, "size", 0):
            xam = cv2.cvtColor(o, cv2.COLOR_BGR2GRAY)
            # Phương sai Laplace: ảnh mờ thì cạnh ít biến thiên.
            net = min(1.0, float(cv2.Laplacian(xam, cv2.CV_64F).var()) / 200.0)
    except Exception:  # noqa: BLE001 — chấm điểm hỏng KHÔNG được làm hỏng cả lượt
        net = 0.0
    return round(0.5 * diem_do + 0.3 * co + 0.2 * net, 4)


def _chon_dai_dien(ung_vien: list[tuple[float, dict[str, Any], Any]],
                   dong_thuan: int) -> list[tuple[dict[str, Any], Any]]:
    """Nhiều lần nhìn trong một lượt → mỗi danh tính một khuôn mặt đại diện.

    Hai việc, và việc thứ hai mới là thứ giảm nhận sai:

    1. Chọn khung CHẤT LƯỢNG CAO NHẤT cho mỗi danh tính, thay vì khung đầu tiên.
    2. **Đòi đồng thuận**: chưa đủ ``dong_thuan`` lần nhìn cùng chỉ vào một người
       thì hạ từ «quen» xuống «có thể là» — vẫn ghi, vẫn hiện, nhưng không dám
       khẳng định tên. Tài liệu và cộng đồng đều nói đồng thuận nhiều lần đáng
       tin hơn là chỉnh ngưỡng điểm, vì một khung xấu có thể ăn may vượt ngưỡng.
    """
    import numpy as np

    from services import nhin_nha

    co_the, _chac = nhin_nha.nguong_mat()
    # Người đã biết (kể cả «có thể là») gom theo danh tính. Mặt LẠ chưa có danh
    # tính nên gom theo ĐỘ GIỐNG giữa chính các vector — cùng luật mà
    # `so_mat_nha.gom_mat_la` dùng. Gom chung hết thành một là gộp nhầm hai khách
    # cùng đứng; mỗi khung một cụm thì một người đi qua đẻ ra năm cụm.
    theo_ai: dict[str, list[tuple[float, dict[str, Any], Any]]] = {}
    cum_la: list[tuple[str, Any]] = []
    for d, m, anh in ung_vien:
        if m.get("nguoi_id"):
            khoa = f"nguoi:{m['nguoi_id']}"
        else:
            khoa = ""
            v = np.asarray(m["vector"], np.float32)
            for ten_cum, vc in cum_la:
                if float(np.dot(vc, v)) * 100.0 >= co_the:
                    khoa = ten_cum
                    break
            if not khoa:
                khoa = "la:%d" % len(cum_la)
                cum_la.append((khoa, v))
        theo_ai.setdefault(khoa, []).append((d, m, anh))
    ra = []
    for khoa, ds in theo_ai.items():
        ds.sort(key=lambda z: -z[0])
        _d, m, anh = ds[0]
        if khoa.startswith("nguoi:") and m.get("loai") == "quen" and len(ds) < dong_thuan:
            m = {**m, "loai": "co_the"}
            _stats["ha_vi_thieu_dong_thuan"] += 1
        ra.append((m, anh))
    return ra


def xu_ly(camera: str, nguon: str) -> dict[str, Any]:
    """Một lượt nhận mặt ở ``camera``. Trả tóm tắt để test và web xem.

    NHÌN NHIỀU KHUNG rồi mới quyết, không quyết ngay khung đầu — xem
    `_diem_chat_luong` để biết vì sao. Khung lấy từ LUỒNG CHÍNH nguyên cỡ, vì
    mặt ở luồng phụ 640×480 chỉ còn vài pixel.
    """
    from services import camera_nha, nhin_nha, so_mat_nha, yolo_nha
    from services.khuon_mat_nha import moc_la_mat

    c = cfg()
    if not nhin_nha.co_mat():
        return {"bo_qua": "chưa tải model mặt"}
    so_khung = int(_so(c["so_khung_luot"], 5, 1, 30))
    cach = _so(c["khoang_khung_giay"], 0.5, 0.0, 10.0)
    ung_vien: list[tuple[float, dict[str, Any], Any]] = []
    anh = None
    k = None
    # Hộp người Frigate vừa báo, nếu còn mới. Lấy RA LUÔN (pop) để lượt sau
    # không dùng lại hộp cũ. Hạn 5 giây: quá đó thì người đã đi khỏi chỗ ấy,
    # hộp thành vô dụng — thà để YOLO tự dò trên đúng khung vừa chụp.
    goi_y = None
    with _khoa:
        cu = _goi_y.pop(camera, None)
    if cu and time.time() - cu[0] <= 5.0:
        goi_y = cu[1]
    for i in range(so_khung):
        if i and cach:
            _stop.wait(cach)
        if _stop.is_set():
            break
        try:
            _, tho = camera_nha.chup_tho(camera, timeout=15)
            anh_i = yolo_nha.doc_anh(tho)
        except Exception as exc:
            # Một khung hỏng KHÔNG được làm hỏng cả lượt: go2rtc thỉnh thoảng
            # trả mã 500 (đo được 2/12 lần ở Cam cửa ngày 17/09).
            logger.info({"event": "canh_camera_khung_hong", "camera": camera,
                         "loi": str(exc)[:120]})
            continue
        # CHỈ khung đầu tiên lấy được mới dùng hộp của Frigate: các khung sau
        # cách nhau nửa giây, người đã dịch chỗ nên hộp cũ càng lúc càng sai.
        hop_nguoi = None
        if goi_y:
            hop_nguoi = _hop_tu_frigate(goi_y, anh_i.shape[1], anh_i.shape[0],
                                        0.9) or None
            goi_y = None
        k_i = nhin_nha.phan_tich_khung(anh_i, hop_nguoi=hop_nguoi)
        _stats["khung_trong_luot"] += 1
        if anh is None:
            anh, k = anh_i, k_i
        for m in k_i.mat:
            if m["nho"] or m["diem_do"] < DIEM_DO_TOI_THIEU:
                continue
            # Tường và cạnh cửa vẫn có điểm dò cao. Năm mốc không thành mặt thì bỏ.
            if not moc_la_mat(m["hop"], m.get("moc")):
                continue
            ung_vien.append((_diem_chat_luong(anh_i, m), m, anh_i))
    if anh is None:
        return {"bo_qua": "không lấy được khung nào"}
    _stats["nhan_mat"] += 1
    now = time.time()
    phien = _so(c["phien_phut"], 10.0, 0.5, 24 * 60) * 60
    dai_dien = _chon_dai_dien(ung_vien, int(_so(c["dong_thuan"], 2, 1, 10)))
    ra: dict[str, Any] = {"nguoi": sum(v.nhan == "person" for v in k.vat_the),
                          "mat": len(dai_dien), "su_kien": []}
    for m, anh in dai_dien:
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
            anh_url = _luu_anh_bao(anh, m["hop"], m.get("moc"))
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


#: Trần số người đưa lên nút bấm — danh sách dài quá thì tin nhắn thành một
#: bức tường số, bấm nhầm nhiều hơn bấm đúng.
_TOI_DA_NGUOI_CHON = 8


def _lua_chon_mat_la(mat_la_id: str) -> list[str]:
    """Nút bấm kèm tin «người lạ»: chọn người đã biết, thêm mới, hoặc bỏ qua.

    Chủ máy chốt 16/09/2026: *"người lạ thì bỏ qua, người quen thì đưa danh
    sách đã có để chọn và thêm 1 lựa chọn thêm mới"*. Trước đây tin chỉ dạy
    cú pháp «mặt lạ <mã> là <tên>» — đúng nhưng bắt người dùng gõ đúng mã,
    mà mã là sáu ký tự băm chẳng ai nhớ nổi.

    Nhãn nút bị cắt còn 40 ký tự ở `ask_choices`, nên tên dài phải rút ở đây
    chứ không để nó cắt ngang chừng.
    """
    from services import so_mat_nha

    dong = ["<<<ASK>>>"]
    for n in so_mat_nha.danh_sach_nguoi()[:_TOI_DA_NGUOI_CHON]:
        ten = str(n.get("ten") or "").strip()
        if ten:
            dong.append(f"Là {ten[:30]} | mặt lạ {mat_la_id} là {ten}")
    dong.append(f"Thêm người mới | tôi muốn đặt tên mới cho mặt lạ {mat_la_id}")
    dong.append(f"Người lạ, đừng hỏi nữa | thôi hỏi về mặt lạ {mat_la_id}")
    dong.append(f"Để sau | để sau hỏi lại về mặt lạ {mat_la_id}")
    dong.append("<<<END>>>")
    return dong


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
                  "\n".join([
                      f"👤 Người lạ ở {camera} lúc {_gio(ts)}"
                      + (f" — đã gặp {so_lan} lượt." if so_lan > 1 else "."),
                      "Đây là ai ạ?",
                      *_lua_chon_mat_la(mat_la_id),
                  ]),
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
