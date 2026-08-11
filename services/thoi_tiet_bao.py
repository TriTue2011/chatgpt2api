"""Theo dõi bão nhiệt đới + cảnh báo thời tiết chính thức (CAP) cho Việt Nam.

Nguồn: endpoint công khai của Windy (`node.windy.com`) — KHÔNG cần khoá API. Feed
này gộp sẵn các trung tâm chính thức (JMA cho tây bắc Thái Bình Dương, NOAA NHC,
UKMO, BoM, IMD) cùng các mô hình Windy tự dò trên ECMWF/GFS/ICON, nên áp thấp
hiện ra trước cả khi được đặt tên.

Port native Python từ `custom_components/accuweather/windy.py` (kho
TriTue2011/accuweather) để bot trả lời được "có bão không", "bão vào đâu" mà
KHÔNG cần Home Assistant đã cài component đó. Bỏ mọi phụ thuộc `homeassistant`,
dùng `urllib` đồng bộ giống `services/weather_extras.py`.

Khác bản gốc ở chỗ thước đo "cơn nào đáng quan tâm". Bản gốc xếp mọi thứ theo
khoảng cách tới NHÀ, nên nhà ở Hà Nội thì cơn sắp đổ bộ Cà Mau bị coi là xa và
thậm chí không được tải đường đi. Ở đây dùng:

    cach_min_km = min(khoảng cách tới người hỏi,
                      khoảng cách tới khúc bờ Việt Nam bão sẽ đổ bộ)

Khi đã có dự báo đổ bộ thì vế thứ hai lấy đúng điểm đổ bộ (nên xấp xỉ 0 và cơn đó
lên đầu); chưa có dự báo thì lấy khoảng cách từ vị trí HIỆN TẠI của bão tới tỉnh
ven biển gần nhất. Thước này quyết định cả thứ tự danh sách, cơn được tải chi
tiết, và cơn được đem ra cảnh báo — xem `muc_quan_tam_km()`.

`available=False` phân biệt "không gọi được Windy" với "trời yên thật": đang bão
mà báo hết bão là kiểu sai tệ nhất, nên bên gọi phải im lặng chứ đừng nói không
có bão.
"""
from __future__ import annotations

import json
import math
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from utils.log import logger

WINDY_STORMS_URL = "https://node.windy.com/tc/v2/storms"
WINDY_ALERTS_URL = ("https://node.windy.com/capalerts/{lat}/{lon}"
                    "?source=hp&lang=vi&maxCount=6")

# Điểm dự báo cách bờ dưới ngưỡng này thì coi như bão vào đất liền.
NGUONG_VAO_BO_KM = 80.0
# Xa hơn mức này thì chỉ liệt kê tên, không tải đường đi (mỗi cơn 1 request).
BAN_KINH_QUAN_TAM_KM = 2500.0
# Số cơn được tải chi tiết mỗi lượt.
SO_BAO_CHI_TIET = 3
# Ngưỡng để chèn câu cảnh báo vào bản tin thời tiết chung.
BAN_KINH_CANH_BAO_KM = 1000.0

_TIMEOUT = 8.0
# Hạn tổng cho một lượt `danh_sach_bao`. Hàm này nằm trên đường trả lời thời tiết
# của MỖI lượt chat, mà một lượt có thể là 1 + 3 request tuần tự — không chặn thì
# lúc Windy chậm người dùng ngồi đợi hơn nửa phút cho một câu hỏi thời tiết. Quá
# hạn thì bỏ phần tải quỹ đạo còn lại: mất dự báo đổ bộ của mấy cơn cuối (im lặng)
# chứ không bao giờ biến thành "không có bão".
_HAN_GIAY = 10.0
# Windy tự cache 60 giây, bão thì di chuyển theo giờ — 4 phút là đủ tươi.
_CACHE_TTL = 240.0
_CACHE: dict[str, tuple[float, Any]] = {}

# Việt Nam không có giờ mùa hè nên +7 cố định luôn đúng, không phụ thuộc TZ của
# container. Windy đóng dấu mọi mốc thời gian theo UTC; in thẳng ra là sớm 7
# tiếng, thường lệch sang ngày khác.
_TZ_VN = timezone(timedelta(hours=7))

# Điểm tham chiếu ven biển, xấp xỉ trên bờ của từng tỉnh giáp biển, dùng để gọi
# tên khúc bờ mà bão đang hướng tới. Xếp từ Bắc xuống Nam.
BO_BIEN_VN: tuple[tuple[str, float, float], ...] = (
    ("Quảng Ninh", 21.05, 107.35),
    ("Hải Phòng", 20.75, 106.75),
    ("Thái Bình", 20.45, 106.55),
    ("Nam Định", 20.15, 106.35),
    ("Ninh Bình", 20.05, 106.10),
    ("Thanh Hóa", 19.70, 105.95),
    ("Nghệ An", 18.80, 105.80),
    ("Hà Tĩnh", 18.30, 106.05),
    ("Quảng Bình", 17.50, 106.65),
    ("Quảng Trị", 16.85, 107.15),
    ("Huế", 16.50, 107.65),
    ("Đà Nẵng", 16.05, 108.25),
    ("Quảng Nam", 15.60, 108.55),
    ("Quảng Ngãi", 15.10, 108.90),
    ("Bình Định", 14.00, 109.25),
    ("Phú Yên", 13.15, 109.30),
    ("Khánh Hòa", 12.25, 109.20),
    ("Ninh Thuận", 11.60, 109.00),
    ("Bình Thuận", 10.90, 108.10),
    ("Bà Rịa - Vũng Tàu", 10.35, 107.10),
    ("TP. Hồ Chí Minh", 10.40, 106.90),
    ("Tiền Giang", 10.30, 106.70),
    ("Bến Tre", 9.90, 106.60),
    ("Trà Vinh", 9.70, 106.50),
    ("Sóc Trăng", 9.40, 106.10),
    ("Bạc Liêu", 9.10, 105.70),
    ("Cà Mau", 8.70, 105.10),
    ("Kiên Giang", 10.00, 104.80),
)

# Thứ tự tin cậy khi ước lượng nơi vào bờ: JMA là trung tâm WMO chỉ định cho khu
# vực này, rồi ECMWF, rồi phần còn lại.
UU_TIEN_MO_HINH: tuple[str, ...] = (
    "jma", "ecmwf", "ukm", "noaa-at", "imd",
    "detected(ecmwf-hres)", "detected(gfs)",
)

# Phương chính (tiếng Anh) → độ.
_PHUONG_DO: dict[str, float] = {
    "N": 0.0, "NNE": 22.5, "NE": 45.0, "ENE": 67.5,
    "E": 90.0, "ESE": 112.5, "SE": 135.0, "SSE": 157.5,
    "S": 180.0, "SSW": 202.5, "SW": 225.0, "WSW": 247.5,
    "W": 270.0, "WNW": 292.5, "NW": 315.0, "NNW": 337.5,
}

# Phương chính → tên tiếng Việt đầy đủ, để nói hướng bằng chữ.
_PHUONG_VI: dict[str, str] = {
    "N": "Bắc", "NNE": "Bắc Đông Bắc", "NE": "Đông Bắc", "ENE": "Đông Đông Bắc",
    "E": "Đông", "ESE": "Đông Đông Nam", "SE": "Đông Nam", "SSE": "Nam Đông Nam",
    "S": "Nam", "SSW": "Nam Tây Nam", "SW": "Tây Nam", "WSW": "Tây Tây Nam",
    "W": "Tây", "WNW": "Tây Tây Bắc", "NW": "Tây Bắc", "NNW": "Bắc Tây Bắc",
}

# Cấp Beaufort → ngưỡng dưới, m/s. Bản tin Việt Nam đọc bão theo thang này nên nó
# hữu ích hơn thang Saffir-Simpson của Mỹ.
_BEAUFORT_TOI_THIEU: tuple[tuple[int, float], ...] = (
    (17, 56.1), (16, 51.0), (15, 46.2), (14, 41.5), (13, 37.0), (12, 32.7),
    (11, 28.5), (10, 24.5), (9, 20.8), (8, 17.2), (7, 13.9), (6, 10.8),
    (5, 8.0), (4, 5.5), (3, 3.4), (2, 1.6), (1, 0.3),
)


# ── Toán học và phân cấp ──────────────────────────────────────────────────

def cap_beaufort(gio_ms: float | None) -> int | None:
    """Cấp Beaufort của một tốc độ gió tính bằng m/s."""
    if gio_ms is None:
        return None
    for cap, nguong in _BEAUFORT_TOI_THIEU:
        if gio_ms >= nguong:
            return cap
    return 0


def phan_cap_bao(gio_ms: float | None) -> str | None:
    """Gọi tên cường độ bão theo cách bản tin Việt Nam vẫn dùng."""
    cap = cap_beaufort(gio_ms)
    if cap is None:
        return None
    if cap >= 16:
        return "Siêu bão"
    if cap >= 12:
        return "Bão rất mạnh"
    if cap >= 10:
        return "Bão mạnh"
    if cap >= 8:
        return "Bão"
    if cap >= 6:
        return "Áp thấp nhiệt đới"
    return "Vùng áp thấp"


def khoang_cach_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Khoảng cách vòng tròn lớn giữa hai điểm, tính bằng km."""
    ban_kinh = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = (math.sin(d_phi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2)
    return round(2 * ban_kinh * math.asin(math.sqrt(a)), 1)


def huong_toi(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, str]:
    """Phương vị từ điểm 1 tới điểm 2, trả (độ, phương chính tiếng Anh)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = (math.cos(phi1) * math.sin(phi2)
         - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda))
    do = (math.degrees(math.atan2(y, x)) + 360) % 360
    phuong = min(
        _PHUONG_DO.items(),
        key=lambda muc: min(abs(do - muc[1]), 360 - abs(do - muc[1])),
    )[0]
    return round(do, 1), phuong


def bo_gan_nhat(lat: float, lon: float) -> tuple[str, float]:
    """Tỉnh ven biển Việt Nam gần điểm này nhất, kèm khoảng cách km.

    KHÔNG phụ thuộc vị trí người dùng — đây là lý do một cơn sắp vào Cà Mau vẫn
    được nhận ra dù chủ nhà ở Hà Nội.
    """
    ten, gan = min(
        ((tinh, khoang_cach_km(lat, lon, la, lo)) for tinh, la, lo in BO_BIEN_VN),
        key=lambda muc: muc[1],
    )
    return ten, gan


def gio_dia_phuong(moc: str | None) -> str | None:
    """Đổi mốc thời gian của Windy (UTC) sang giờ Việt Nam, dạng 'HH:MM dd/mm'."""
    if not moc:
        return None
    try:
        t = datetime.fromisoformat(str(moc))
    except (TypeError, ValueError):
        return str(moc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(_TZ_VN).strftime("%H:%M %d/%m")


def du_doan_vao_bo(
    du_bao: dict[str, dict[str, Any]],
    nguong_km: float = NGUONG_VAO_BO_KM,
) -> dict[str, Any] | None:
    """Ước lượng bão vào bờ Việt Nam ở đâu và lúc nào.

    Duyệt các đường dự báo theo thứ tự tin cậy của cơ quan khí tượng, báo điểm
    ĐẦU TIÊN lọt vào `nguong_km` của một tỉnh ven biển. Đây là ước lượng từ điểm
    quỹ đạo so với điểm tham chiếu ven biển — nó gọi tên khúc bờ bão đang hướng
    tới, KHÔNG phải bản tin chính thức.
    """
    thu_tu = [m for m in UU_TIEN_MO_HINH if m in du_bao]
    thu_tu += [m for m in sorted(du_bao) if m not in thu_tu]

    for mo_hinh in thu_tu:
        for diem in du_bao[mo_hinh].get("track") or []:
            lat, lon = diem.get("latitude"), diem.get("longitude")
            if lat is None or lon is None:
                continue
            tinh, cach = bo_gan_nhat(lat, lon)
            if cach <= nguong_km:
                return {
                    "model": mo_hinh,
                    "tinh": tinh,
                    "cach_bo_km": cach,
                    "time": diem.get("time"),
                    "time_text": gio_dia_phuong(diem.get("time")),
                    "latitude": lat,
                    "longitude": lon,
                    "ap_suat_hpa": diem.get("ap_suat_hpa"),
                    "gio_kmh": diem.get("gio_kmh"),
                }
    return None


def mo_ta_vao_bo(
    vao_bo: dict[str, Any] | None,
    tinh_gan_bo: str | None = None,
    cach_bo_km: float | None = None,
    cach_diem_do_bo_km: float | None = None,
    do_bo_cach_nha_km: float | None = None,
) -> str:
    """Một câu tiếng Việt thường về việc bão đi đâu.

    Khi có dự báo đổ bộ thì nói kèm hai khoảng cách, vì chúng trả lời hai câu hỏi
    khác nhau: bão còn phải đi bao xa nữa (`cach_diem_do_bo_km`), và chỗ đổ bộ
    cách người hỏi bao xa (`do_bo_cach_nha_km`).
    """
    if vao_bo:
        khi = vao_bo.get("time_text")
        cau = (f"Dự kiến đổ bộ khu vực {vao_bo['tinh']}"
               + (f" khoảng {khi}" if khi else "")
               + f" (theo {str(vao_bo['model']).upper()})")
        them = []
        if cach_diem_do_bo_km is not None:
            them.append(f"bão còn cách chỗ đổ bộ {round(cach_diem_do_bo_km)} km")
        if do_bo_cach_nha_km is not None:
            them.append(f"chỗ đổ bộ cách anh {round(do_bo_cach_nha_km)} km")
        if them:
            cau += " — " + ", ".join(them)
        return cau
    if tinh_gan_bo and cach_bo_km is not None:
        return (f"Chưa có dấu hiệu đổ bộ Việt Nam; gần bờ {tinh_gan_bo} nhất "
                f"khoảng {round(cach_bo_km)} km")
    return "Chưa có dấu hiệu đổ bộ Việt Nam"


# ── Lấy dữ liệu ───────────────────────────────────────────────────────────

def _get_json(url: str) -> Any | None:
    """GET một endpoint JSON của Windy, có cache dùng chung trong tiến trình.

    Cache cả lần thất bại (ngắn hạn) để endpoint hỏng không bị gọi lại mỗi lượt
    chat. HTTP 204 (Windy trả khi không có gì để báo) rơi vào nhánh thân rỗng.
    """
    da_cache = _CACHE.get(url)
    if da_cache and (time.time() - da_cache[0]) < _CACHE_TTL:
        return da_cache[1]
    du_lieu = None
    try:
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        })
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            than = r.read().decode("utf-8", "replace")
        if than.strip():
            du_lieu = json.loads(than)
    except Exception as exc:
        logger.warning({"event": "windy_fetch_failed", "url": url[:90],
                        "error": str(exc)[:120]})
    _CACHE[url] = (time.time(), du_lieu)
    return du_lieu


def _so(gia_tri: Any) -> float | None:
    """Đổi một giá trị của feed sang float, None nếu thiếu hoặc không phải số.

    Feed không có tài liệu chính thức; một toạ độ null từng làm phép tính khoảng
    cách nổ TypeError và kéo theo toàn bộ cảm biến mất dữ liệu.
    """
    if gia_tri is None:
        return None
    try:
        return float(gia_tri)
    except (TypeError, ValueError):
        return None


def _tom_tat(bao: dict[str, Any], lat: float | None, lon: float | None) -> dict[str, Any]:
    """Chuẩn hoá một cơn bão: m/s → km/h, Pascal → hPa, kèm khoảng cách."""
    gio_ms = _so(bao.get("windSpeed"))
    lat_b, lon_b = _so(bao.get("lat")), _so(bao.get("lon"))
    ket: dict[str, Any] = {
        "id": bao.get("id"),
        "ten": bao.get("name"),
        "latitude": lat_b,
        "longitude": lon_b,
        "strength": bao.get("strength"),
        "gio_ms": gio_ms,
        "gio_kmh": round(gio_ms * 3.6, 1) if gio_ms is not None else None,
        "beaufort": cap_beaufort(gio_ms),
        "phan_cap": phan_cap_bao(gio_ms),
    }

    if lat_b is not None and lon_b is not None:
        # Khoảng cách tới BỜ VIỆT NAM — tính từ toạ độ bão, không liên quan vị
        # trí người hỏi, nên cơn ở miền nào cũng được nhận ra như nhau.
        tinh, cach_bo = bo_gan_nhat(lat_b, lon_b)
        ket["tinh_gan_bo"] = tinh
        ket["cach_bo_km"] = cach_bo
        if lat is not None and lon is not None:
            ket["cach_nha_km"] = khoang_cach_km(lat, lon, lat_b, lon_b)
            # Bão đang ở phía nào so với người hỏi — KHÁC hướng nó đang đi.
            do, phuong = huong_toi(lat, lon, lat_b, lon_b)
            ket["phia_do"] = do
            ket["phia_en"] = phuong
            ket["phia"] = _PHUONG_VI.get(phuong, phuong)
    return ket


def _diem_quy_dao(diem: dict[str, Any]) -> dict[str, Any]:
    """Chuẩn hoá một điểm quỹ đạo (feed để gió m/s, áp suất Pascal)."""
    gio_ms = _so(diem.get("windSpeed"))
    ap_suat = _so(diem.get("pressure"))
    return {
        "time": diem.get("time"),
        "latitude": _so(diem.get("lat")),
        "longitude": _so(diem.get("lon")),
        "gio_kmh": round(gio_ms * 3.6, 1) if gio_ms is not None else None,
        "ap_suat_hpa": round(ap_suat / 100, 1) if ap_suat is not None else None,
    }


def _di_chuyen(lich_su: list[dict[str, Any]]) -> dict[str, Any]:
    """Bão đang đi hướng nào, nhanh bao nhiêu.

    Feed không có trường hướng đi, nên suy từ hai điểm quỹ đạo mới nhất (feed xếp
    mới nhất trước). Phương vị ở đây là nơi bão ĐI TỚI — ngược quy ước của hướng
    gió, thứ gọi tên nơi gió thổi ĐẾN TỪ.
    """
    diem = [p for p in lich_su
            if p.get("latitude") is not None and p.get("longitude") is not None]
    if len(diem) < 2:
        return {}

    moi, truoc = diem[0], diem[1]
    do, phuong = huong_toi(truoc["latitude"], truoc["longitude"],
                           moi["latitude"], moi["longitude"])
    huong_vi = _PHUONG_VI.get(phuong, phuong)
    da_di = khoang_cach_km(truoc["latitude"], truoc["longitude"],
                           moi["latitude"], moi["longitude"])

    toc_do = None
    try:
        t_moi = datetime.fromisoformat(str(moi.get("time")))
        t_truoc = datetime.fromisoformat(str(truoc.get("time")))
        gio = (t_moi - t_truoc).total_seconds() / 3600
        if gio > 0:
            toc_do = round(da_di / gio, 1)
    except (TypeError, ValueError):
        logger.warning({"event": "windy_history_bad_time"})

    return {
        "huong_di": huong_vi,
        "huong_di_en": phuong,
        "huong_di_do": do,
        "toc_do_kmh": toc_do,
        "di_chuyen_text": (f"Di chuyển hướng {huong_vi}"
                           + (f", {toc_do} km/h" if toc_do is not None else "")),
    }


def _them_chi_tiet(
    bao: dict[str, Any],
    lat: float | None = None,
    lon: float | None = None,
) -> None:
    """Gắn quỹ đạo, hướng di chuyển và dự kiến đổ bộ vào một cơn bão, tại chỗ.

    `lat/lon` là vị trí người hỏi, dùng để tính điểm đổ bộ cách họ bao xa.
    """
    chi_tiet = _get_json(f"{WINDY_STORMS_URL}/{bao['id']}")
    if not isinstance(chi_tiet, dict):
        return

    lich_su = [_diem_quy_dao(p) for p in chi_tiet.get("history") or []
               if isinstance(p, dict)]
    du_bao: dict[str, dict[str, Any]] = {}
    for muc in chi_tiet.get("forecast") or []:
        if not isinstance(muc, dict):
            continue
        mo_hinh = muc.get("modelIdentifier")
        if not mo_hinh:
            continue
        du_bao[mo_hinh] = {
            "reference_time": muc.get("reftime"),
            # Windy xếp bản ghi dự báo TƯƠNG LAI XA TRƯỚC. Phải xếp lại theo thời
            # gian tăng dần: du_doan_vao_bo báo điểm đầu tiên chạm bờ, để nguyên
            # thứ tự feed thì nó báo lần áp bờ CUỐI — sai tỉnh và trễ cả ngày.
            "track": sorted(
                (_diem_quy_dao(p) for p in muc.get("records") or []
                 if isinstance(p, dict)),
                key=lambda p: p.get("time") or "",
            ),
        }

    bao["lich_su"] = lich_su
    bao["mo_hinh_du_bao"] = sorted(du_bao)
    bao["du_bao"] = du_bao
    bao.update(_di_chuyen(lich_su))
    if lich_su:
        bao["ap_suat_hpa"] = lich_su[0].get("ap_suat_hpa")
        bao["quan_trac_luc"] = lich_su[0].get("time")
        bao["quan_trac_luc_text"] = gio_dia_phuong(lich_su[0].get("time"))

    vao_bo = du_doan_vao_bo(du_bao)
    bao["vao_bo"] = vao_bo
    if vao_bo and bao.get("latitude") is not None and bao.get("longitude") is not None:
        # Bão còn phải đi bao xa nữa mới tới chỗ đổ bộ.
        bao["cach_diem_do_bo_km"] = khoang_cach_km(
            bao["latitude"], bao["longitude"],
            vao_bo["latitude"], vao_bo["longitude"])
    if vao_bo and lat is not None and lon is not None:
        # Chỗ đổ bộ cách NGƯỜI HỎI bao xa — con số quyết định "có ảnh hưởng tới
        # mình không", khác hẳn khoảng cách tới cơn bão lúc này.
        bao["do_bo_cach_nha_km"] = khoang_cach_km(
            lat, lon, vao_bo["latitude"], vao_bo["longitude"])
    bao["vao_bo_text"] = mo_ta_vao_bo(
        vao_bo, bao.get("tinh_gan_bo"), bao.get("cach_bo_km"),
        bao.get("cach_diem_do_bo_km"), bao.get("do_bo_cach_nha_km"))
    bao["co_chi_tiet"] = True


# Ba khoảng cách được đem so, và nhãn để nói lại cho người đọc biết số nào đang
# hiện. Không dùng "khoảng cách tới bờ Việt Nam nói chung": một cơn tình cờ trôi
# ngang gần bờ nhưng đang đi ra biển thì con số đó nhỏ một cách vô nghĩa.
_KHOANG_CACH_SO_SANH: tuple[tuple[str, str], ...] = (
    # (khoá trên dict bão, nhãn co_so_min)
    ("cach_nha_km", "nha"),                  # bão → người hỏi
    ("cach_diem_do_bo_km", "do_bo"),         # bão → điểm đổ bộ (còn phải đi bao xa)
    ("do_bo_cach_nha_km", "do_bo_toi_nha"),  # điểm đổ bộ → người hỏi
)


def muc_quan_tam_km(bao: dict[str, Any]) -> float:
    """Thước đo "cơn này đáng quan tâm tới đâu", càng nhỏ càng đáng — km.

    Lấy min của ba khoảng cách trong `_KHOANG_CACH_SO_SANH`: bão cách người hỏi,
    bão cách điểm đổ bộ, và điểm đổ bộ cách người hỏi. Nói cách khác cơn được coi
    là đáng quan tâm khi bão đang ở gần mình, HOẶC nó sắp đổ bộ, HOẶC nó sẽ đổ bộ
    gần mình — cả ba đều là lý do chính đáng để bản tin nhắc tới nó.

    Điểm đổ bộ là nơi đường đi dự báo thật sự chạm đất liền Việt Nam, dò trên toàn
    bộ 28 điểm ven biển, nên bão đổ bộ miền nào cũng vào diện này.

    Chưa tải được đường đi và không có toạ độ người hỏi thì trả `inf`; thứ tự cho
    những cơn như vậy do `danh_sach_bao()` lo bằng khoá phụ.
    """
    return min((bao[k] for k, _ in _KHOANG_CACH_SO_SANH
                if bao.get(k) is not None), default=math.inf)


def co_so_gan_nhat(bao: dict[str, Any]) -> str:
    """Nhãn cho biết `cach_min_km` của cơn này là khoảng cách nào trong ba cái."""
    muc = muc_quan_tam_km(bao)
    for khoa, nhan in _KHOANG_CACH_SO_SANH:
        if bao.get(khoa) is not None and bao[khoa] <= muc:
            return nhan
    return ""


def _uu_tien_tai(bao: dict[str, Any]) -> float:
    """Cơn nào đáng tải đường đi trước — HEURISTIC nội bộ, không phải số đem báo.

    Trước khi tải track thì chưa biết bão có đổ bộ hay không, nên phải đoán bằng
    thứ có sẵn: min(cách người hỏi, cách bờ Việt Nam theo vị trí hiện tại). Thiếu
    vế thứ hai thì cơn sắp vào Cà Mau không bao giờ được tải khi chủ nhà ở Hà Nội,
    và khi đó chẳng có dự báo đổ bộ nào để hiện.
    """
    cach_nha = bao.get("cach_nha_km")
    cach_bo = bao.get("cach_bo_km")
    return min(cach_nha if cach_nha is not None else math.inf,
               cach_bo if cach_bo is not None else math.inf)


def danh_sach_bao(
    lat: float | None = None,
    lon: float | None = None,
    so_chi_tiet: int = SO_BAO_CHI_TIET,
    ban_kinh_km: float = BAN_KINH_QUAN_TAM_KM,
    han_giay: float = _HAN_GIAY,
) -> dict[str, Any]:
    """Các cơn bão nhiệt đới đang hoạt động, cơn đáng quan tâm nhất trước.

    `lat/lon` là vị trí người hỏi, dùng để tính khoảng cách và phía (bỏ trống thì
    bỏ luôn hai thông tin đó, phần dự báo đổ bộ vẫn đủ). Chỉ những cơn đáng nhất
    theo `_uu_tien_tai()` và nằm trong `ban_kinh_km` mới được tải quỹ đạo, tối đa
    `so_chi_tiet` cơn, mỗi cơn thêm 1 request. Quá `han_giay` giây thì dừng tải
    thêm — cơn đáng nhất đã tải trước nên phần bỏ dở là phần ít đáng nhất.

    Trả về dict với:
      available    — gọi được Windy hay không. False thì ĐỪNG nói "không có bão".
      count        — số cơn đang hoạt động trên toàn cầu
      storms       — danh sách đã chuẩn hoá, cơn đáng quan tâm nhất trước. Mỗi cơn
                     có `cach_min_km` (xem `muc_quan_tam_km`) và `co_so_min`:
                     'nha' = số đó là khoảng cách tới người hỏi, 'do_bo' = khoảng
                     cách từ bão tới điểm đổ bộ.
      dang_lo_nhat — cơn `cach_min_km` nhỏ nhất (ưu tiên cơn có dự báo đổ bộ)
      gan_nha      — cơn gần ĐÚNG người hỏi nhất, None nếu không truyền lat/lon.
                     Thường KHÁC `dang_lo_nhat`: một áp thấp yếu ở gần vẫn có thể
                     gần hơn cơn siêu bão đang hướng vào Quảng Bình.
    """
    ket: dict[str, Any] = {
        "available": False, "count": 0, "storms": [],
        "dang_lo_nhat": None, "gan_nha": None,
    }

    du_lieu = _get_json(WINDY_STORMS_URL)
    if not isinstance(du_lieu, dict):
        return ket
    ket["available"] = True

    storms = [_tom_tat(s, lat, lon) for s in du_lieu.get("storms") or []
              if isinstance(s, dict)]
    if not storms:
        # Câu trả lời thật: hiện không có cơn nào.
        return ket

    # Vòng 1 — chọn cơn đáng tải quỹ đạo bằng heuristic vị trí hiện tại, vì lúc
    # này chưa cơn nào có dự báo đổ bộ để mà so. Cơn đáng nhất đứng đầu nên nếu hết
    # hạn giờ, thứ bị bỏ là cơn ít đáng nhất.
    bat_dau = time.time()
    for bao in sorted(storms, key=_uu_tien_tai)[:max(0, so_chi_tiet)]:
        if not bao.get("id") or _uu_tien_tai(bao) > ban_kinh_km:
            continue
        if time.time() - bat_dau > han_giay:
            logger.warning({"event": "windy_qua_han", "bo_qua": bao.get("ten")})
            break
        _them_chi_tiet(bao, lat, lon)

    # Vòng 2 — giờ đã biết cơn nào đổ bộ ở đâu, mới tính thước đo thật và xếp chốt.
    for bao in storms:
        bao["cach_min_km"] = muc_quan_tam_km(bao)
        bao["co_so_min"] = co_so_gan_nhat(bao)
    # Khoá phụ: cơn có dự báo đổ bộ đứng trước, rồi cơn đổ bộ sớm hơn, cuối cùng
    # mới tới khoảng cách tới bờ — khoá cuối chỉ để những cơn cùng `inf` (không có
    # toạ độ người hỏi, không dự báo đổ bộ) vẫn ra thứ tự có nghĩa.
    storms.sort(key=lambda b: (b["cach_min_km"],
                               0 if b.get("vao_bo") else 1,
                               str((b.get("vao_bo") or {}).get("time") or ""),
                               b.get("cach_bo_km") if b.get("cach_bo_km") is not None
                               else math.inf))

    ket["count"] = len(storms)
    ket["storms"] = storms
    ket["dang_lo_nhat"] = storms[0]
    if lat is not None and lon is not None:
        co_toa_do = [b for b in storms if b.get("cach_nha_km") is not None]
        if co_toa_do:
            ket["gan_nha"] = min(co_toa_do, key=lambda b: b["cach_nha_km"])
    ket["uncertainty_circles_m"] = du_lieu.get("defaultCircles")
    return ket


def canh_bao_cap(lat: float, lon: float) -> list[dict[str, Any]]:
    """Cảnh báo thời tiết chính thức (CAP) cho một điểm; rỗng khi không có."""
    du_lieu = _get_json(WINDY_ALERTS_URL.format(lat=lat, lon=lon))
    if not isinstance(du_lieu, list):
        return []
    ra = []
    for muc in du_lieu:
        if not isinstance(muc, dict):
            continue
        ra.append({
            "id": muc.get("id"),
            "tieu_de": muc.get("headline"),
            "hien_tuong": muc.get("event"),
            "muc_do": muc.get("severity"),
            "loai": muc.get("type"),
            "bat_dau": muc.get("start"),
            "ket_thuc": muc.get("end"),
        })
    return ra


# ── Toạ độ nhà ────────────────────────────────────────────────────────────

_cache_nha: tuple[float, tuple[float, float] | None] | None = None
_TTL_NHA = 3600.0  # nhà không di chuyển


def toa_do_nha() -> tuple[float, float] | None:
    """Toạ độ vị trí nhà, lấy từ Home Assistant. None khi không có HA.

    Dùng bởi các đường tắt trong gateway. `vn-mcp-hub` không import được
    `services.ha_client` nên hàm này trả None ở đó — các tool MCP tự truyền
    toạ độ theo tên địa danh.
    """
    global _cache_nha
    if _cache_nha and time.time() - _cache_nha[0] < _TTL_NHA:
        return _cache_nha[1]
    ll = None
    try:
        from services.weather_extras import _home_latlon
        ll = _home_latlon()
    except Exception as exc:
        logger.warning({"event": "toa_do_nha_failed", "error": str(exc)[:120]})
    _cache_nha = (time.time(), ll)
    return ll


# ── Bản tin tiếng Việt ────────────────────────────────────────────────────

def _cum_mo_ta(bao: dict[str, Any], noi: str = "") -> str:
    """Mô tả một cơn bão thành cụm chữ: tên, cấp, gió, áp suất, khoảng cách."""
    phan = []
    ten = bao.get("ten") or "Không tên"
    cap = bao.get("phan_cap")
    beaufort = bao.get("beaufort")
    dau = f"Bão {ten}" if cap and cap.startswith("Bão") else ten
    if cap:
        dau += f" — {cap}"
        if beaufort:
            dau += f" (cấp {beaufort})"
    phan.append(dau)
    if bao.get("gio_kmh") is not None:
        phan.append(f"gió {round(bao['gio_kmh'])} km/h")
    if bao.get("ap_suat_hpa") is not None:
        phan.append(f"áp suất {round(bao['ap_suat_hpa'])} hPa")
    if bao.get("cach_nha_km") is not None:
        cach = f"cách {noi or 'vị trí của anh'} {round(bao['cach_nha_km'])} km"
        if bao.get("phia"):
            cach += f" về phía {bao['phia']}"
        phan.append(cach)
    elif bao.get("cach_bo_km") is not None:
        phan.append(f"cách bờ {bao.get('tinh_gan_bo')} khoảng "
                    f"{round(bao['cach_bo_km'])} km")
    return ", ".join(phan)


def _tong_quan(dl: dict[str, Any], noi: str = "") -> str:
    """Bản tin bão đầy đủ: cơn ĐỔ BỘ trước, rồi cơn gần người hỏi nhất nếu đó là
    cơn khác — hai thứ này thường khác nhau và người đọc cần cả hai.

    Dẫn bằng cơn đổ bộ chứ không bằng `dang_lo_nhat`: thước `cach_min_km` đo "cơn
    nào tới gần mình nhất", nên một áp thấp yếu cách 220 km vẫn xếp trên cơn cấp
    12 sẽ đổ bộ Quảng Bình sau hai ngày. Xếp hạng như vậy thì đúng theo định
    nghĩa, nhưng mở đầu bản tin bằng cái áp thấp rồi gọi cơn cấp 12 là "cơn khác ở
    xa" thì đọc lên là sai.
    """
    dong: list[str] = []
    chinh = bao_sap_do_bo(dl) or dl.get("dang_lo_nhat") or dl["storms"][0]
    gan = dl.get("gan_nha")

    dong.append("🌀 " + _cum_mo_ta(chinh, noi) + ".")
    if chinh.get("di_chuyen_text"):
        dong.append(chinh["di_chuyen_text"] + ".")
    if chinh.get("vao_bo_text"):
        dong.append(chinh["vao_bo_text"] + ".")

    # So bằng identity: cùng một dict trong `storms`, không dựa vào id của feed.
    if gan is not None and gan is not chinh:
        dong.append("Cơn gần anh nhất: " + _cum_mo_ta(gan, noi) + ".")
        if gan.get("di_chuyen_text"):
            dong.append(gan["di_chuyen_text"] + ".")

    con_lai = [b.get("ten") or "không tên" for b in dl["storms"]
               if b is not chinh and b is not gan]
    if con_lai:
        # Không nói "ở xa": phần còn lại chưa được tải đường đi nên không có cơ sở
        # nào để khẳng định chúng xa hay gần.
        dong.append(f"Còn {len(con_lai)} cơn khác đang hoạt động "
                    f"({', '.join(con_lai[:4])}).")
    return " ".join(d for d in dong if d.strip(" ."))


# ── Chọn cơn theo từng kiểu câu hỏi ───────────────────────────────────────
#
# Ba câu hỏi dưới đây thường cho ra BA cơn khác nhau, nên mỗi câu một hàm chọn
# riêng chứ không dùng chung "cơn gần nhất":
#   "bão gần tôi nhất"            → dl['gan_nha']
#   "bão đổ bộ gần tôi nhất"      → bao_do_bo_gan_nguoi_hoi()
#   "bão nào sắp vào Việt Nam"    → bao_sap_do_bo()

def bao_do_bo_gan_nguoi_hoi(dl: dict[str, Any]) -> dict[str, Any] | None:
    """Cơn có ĐIỂM ĐỔ BỘ gần người hỏi nhất. None nếu chưa cơn nào dự báo đổ bộ."""
    co = [b for b in dl.get("storms") or []
          if b.get("do_bo_cach_nha_km") is not None]
    return min(co, key=lambda b: b["do_bo_cach_nha_km"]) if co else None


def bao_sap_do_bo(dl: dict[str, Any]) -> dict[str, Any] | None:
    """Cơn dự báo đổ bộ Việt Nam SỚM NHẤT, bất kể gần ai. None nếu không có cơn nào."""
    co = [b for b in dl.get("storms") or [] if b.get("vao_bo")]
    if not co:
        return None
    return min(co, key=lambda b: str(b["vao_bo"].get("time") or ""))


Y_DINH_BAO: tuple[str, ...] = (
    "tong_quan",       # bản tin đầy đủ
    "gan_toi",         # "bão gần tôi nhất", "bão cách đây bao xa"
    "do_bo_gan_toi",   # "bão đổ bộ gần tôi nhất vào đâu"
    "sap_do_bo",       # "bão nào sắp vào Việt Nam", "khi nào bão vào bờ"
    "con_cach_bao_xa", # "còn cách bao xa nữa thì vào đất liền"
    "so_luong",        # "đang có mấy cơn bão"
)

# Người gõ KHÔNG DẤU thì "bao" là bãi mìn của tiếng Việt: bao nhiêu, bao giờ,
# thông báo, báo cáo, bảo vệ, báo thức, còn bao lâu — không cái nào nói về bão.
# Cắt hết các cụm này trước khi tìm dấu hiệu bão.
_CUM_KHONG_PHAI_BAO: tuple[str, ...] = (
    "bao nhieu", "bao gio", "thong bao", "bao cao", "bao ve", "bao mat",
    "bao hiem", "bao tri", "bao dam", "bao lanh", "bao quan", "bao ton",
    "bao chi", "bao gom", "bao lau", "bao thuc", "bao loi", "bao tin",
    "bao danh", "bao gia", "dong bao", "bao boc", "bao ham", "bao kim",
)

# Cụm nhận ra câu đang nói về bão khi người dùng gõ không dấu.
_CUM_LA_BAO: tuple[str, ...] = (
    "con bao", "may con bao", "bao so", "sieu bao", "bao nhiet doi",
    "ap thap nhiet doi", "tin bao", "duong di cua bao", "bao do bo",
    "do bo dat lien", "vao dat lien", "tinh hinh bao", "theo doi bao",
    "bao vao viet nam", "bao huong vao", "bao dang o dau", "bao dang di",
    # Dạng câu hỏi 3 từ hay gặp nhất. An toàn vì các cụm nhiễu cùng hình dạng
    # ("có báo về không", "có báo lỗi không") đã bị cắt ở bước trước.
    "co bao khong", "co bao nao", "co bao gan",
)

# Cụm → ý định, xét theo thứ tự từ cụ thể nhất xuống chung nhất.
_LUAT_Y_DINH: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("con_cach_bao_xa", ("cach bao xa", "bao xa nua", "con bao xa",
                         "bao xa thi vao", "cach bao lau nua thi vao",
                         "cach cho do bo")),
    ("do_bo_gan_toi", ("do bo gan", "do bo o dau", "do bo vao dau", "vao dau",
                       "vao tinh nao", "vao khu vuc nao", "vao mien nao",
                       "vao noi nao", "vao cho nao", "do bo tinh nao")),
    ("sap_do_bo", ("sap vao", "sap do bo", "vao viet nam", "vao dat lien",
                   "vao bo", "khi nao", "luc nao", "ngay nao", "may gio",
                   "do bo khi nao", "do bo luc nao", "co do bo", "do bo chua",
                   "do bo")),
    # "ở đâu" = bão đang ở đâu (vị trí hiện tại). Câu "vào đâu" là hỏi nơi đổ bộ
    # nên đã bị luật trên bắt trước.
    ("gan_toi", ("gan toi", "gan day", "gan nha", "gan minh", "cach toi",
                 "cach day", "cach nha", "gan nhat", "gan em", "gan cho toi",
                 "o dau", "dang o dau", "vi tri")),
    ("so_luong", ("may con", "bao nhieu con", "so luong", "dang co may",
                  "co nhung con nao", "liet ke")),
)


def y_dinh_cau_hoi(raw: str, fd: str) -> str | None:
    """Câu này hỏi gì về BÃO? Trả một tên trong `Y_DINH_BAO`, hoặc None nếu câu
    không nói về bão.

    `raw` là câu gốc còn dấu, `fd` là bản đã bỏ dấu và đổi đ→d (bên gọi dùng
    `services.ha_client._fold_diacritics`).

    Nhận theo chữ CÓ DẤU trước: "bão" là chữ không lẫn được với gì, còn bỏ dấu thì
    bao/báo/bảo đều thành "bao" và "còn bao lâu nữa" sẽ bị bắt thành câu hỏi bão.
    Chỉ khi câu không có dấu mới phải đoán, và lúc đó cắt cụm nhiễu rồi mới tìm.

    Các ý định tách riêng vì chúng cho ra những cơn KHÁC nhau — cơn gần người hỏi
    nhất thường không phải cơn sắp đổ bộ.
    """
    low = (raw or "").lower()
    la_bao = "bão" in low or "áp thấp nhiệt đới" in low
    if not la_bao:
        sach = fd or ""
        for xau in _CUM_KHONG_PHAI_BAO:
            sach = sach.replace(xau, " ")
        la_bao = any(k in sach for k in _CUM_LA_BAO)
    if not la_bao:
        return None
    for y_dinh, cum in _LUAT_Y_DINH:
        if any(k in fd for k in cum):
            return y_dinh
    return "tong_quan"


def tra_loi_bao(
    y_dinh: str = "tong_quan",
    lat: float | None = None,
    lon: float | None = None,
    noi: str = "",
) -> str:
    """Trả lời một câu hỏi về bão theo `y_dinh` (xem `Y_DINH_BAO`).

    Chuỗi rỗng nghĩa là KHÔNG gọi được Windy — bên gọi phải im lặng và nhả cho
    đường khác, đừng suy ra là trời yên.
    """
    dl = danh_sach_bao(lat, lon)
    if not dl["available"]:
        return ""
    if not dl["count"]:
        return "Hiện không có cơn bão nhiệt đới nào đang hoạt động."

    if y_dinh == "so_luong":
        # "cơn" chứ không "cơn bão": feed đếm cả áp thấp nhiệt đới và vùng áp thấp.
        cau = f"Hiện có {dl['count']} cơn bão / áp thấp nhiệt đới đang hoạt động"
        sap = bao_sap_do_bo(dl)
        if sap:
            cau += (f", trong đó bão {sap.get('ten')} "
                    f"{sap['vao_bo_text'][0].lower()}{sap['vao_bo_text'][1:]}")
        else:
            cau += ", chưa cơn nào có dấu hiệu đổ bộ Việt Nam"
        return cau + "."

    if y_dinh == "gan_toi":
        bao = dl.get("gan_nha")
        if not bao:
            return _tong_quan(dl, noi)
        cau = "Cơn gần anh nhất: " + _cum_mo_ta(bao, noi) + "."
        if bao.get("di_chuyen_text"):
            cau += " " + bao["di_chuyen_text"] + "."
        if bao.get("vao_bo_text"):
            cau += " " + bao["vao_bo_text"] + "."
        return cau

    if y_dinh in ("do_bo_gan_toi", "sap_do_bo", "con_cach_bao_xa"):
        bao = (bao_do_bo_gan_nguoi_hoi(dl) if y_dinh == "do_bo_gan_toi"
               else bao_sap_do_bo(dl))
        if not bao:
            # Có bão thật, nhưng không cơn nào có đường đi chạm đất liền VN. Nói
            # rõ chuyện đó rồi mới kể cơn gần nhất, đừng để người đọc tự suy.
            cau = "Chưa cơn nào có dự báo đổ bộ Việt Nam."
            gan = dl.get("gan_nha") or dl["storms"][0]
            return cau + " Cơn đáng theo dõi nhất: " + _cum_mo_ta(gan, noi) + "."
        vao_bo = bao["vao_bo"]
        if y_dinh == "con_cach_bao_xa":
            cach = bao.get("cach_diem_do_bo_km")
            cau = f"Bão {bao.get('ten')} "
            cau += (f"còn cách chỗ đổ bộ ({vao_bo['tinh']}) khoảng "
                    f"{round(cach)} km" if cach is not None
                    else f"dự kiến đổ bộ khu vực {vao_bo['tinh']}")
            khi = vao_bo.get("time_text")
            if khi:
                cau += f", dự kiến {khi}"
            if bao.get("toc_do_kmh"):
                cau += f", đang đi {bao['toc_do_kmh']} km/h"
            return cau + "."
        cau = "🌀 " + _cum_mo_ta(bao, noi) + ". " + bao["vao_bo_text"] + "."
        if bao.get("di_chuyen_text"):
            cau += " " + bao["di_chuyen_text"] + "."
        return cau

    return _tong_quan(dl, noi)


def cau_canh_bao_bao(lat: float | None = None, lon: float | None = None) -> str:
    """MỘT câu cảnh báo bão để ghép vào cuối bản tin thời tiết chung.

    Ưu tiên cơn CÓ dự báo đổ bộ Việt Nam, kể cả khi nó không phải cơn gần người
    hỏi nhất: đổ bộ là việc có hậu quả, một áp thấp yếu ở gần thì không. Không có
    cơn nào đổ bộ thì mới xét cơn đáng quan tâm nhất, và chỉ nói nếu nó nằm trong
    `BAN_KINH_CANH_BAO_KM`. Trời yên hoặc không gọi được Windy → chuỗi rỗng, bên
    gọi không phải kiểm gì thêm.

    Câu này cố tình chỉ chứa hai con số: bão cách người hỏi bao xa, và chỗ đổ bộ
    cách người hỏi bao xa — đủ để quyết định có phải lo hay không.
    """
    try:
        dl = danh_sach_bao(lat, lon)
    except Exception as exc:
        logger.warning({"event": "cau_canh_bao_bao_failed", "error": str(exc)[:120]})
        return ""
    if not dl["available"] or not dl["count"]:
        return ""

    bao = bao_sap_do_bo(dl)
    if bao is None:
        bao = dl.get("dang_lo_nhat")
        if not bao or bao.get("cach_min_km", math.inf) > BAN_KINH_CANH_BAO_KM:
            return ""

    phan = [f"🌀 Bão {bao.get('ten') or 'không tên'}"]
    if bao.get("phan_cap"):
        cap = f" ({bao['phan_cap']}"
        if bao.get("beaufort"):
            cap += f", cấp {bao['beaufort']}"
        phan.append(cap + ")")
    if bao.get("cach_nha_km") is not None:
        phan.append(f" cách đây {round(bao['cach_nha_km'])} km")
    vao_bo = bao.get("vao_bo")
    if vao_bo:
        khi = vao_bo.get("time_text")
        phan.append(f", dự kiến đổ bộ khu vực {vao_bo['tinh']}"
                    + (f" khoảng {khi}" if khi else ""))
        if bao.get("do_bo_cach_nha_km") is not None:
            phan.append(f" — chỗ đổ bộ cách anh "
                        f"{round(bao['do_bo_cach_nha_km'])} km")
    elif bao.get("di_chuyen_text"):
        phan.append(", " + bao["di_chuyen_text"].lower())
    return "".join(phan) + "."


def ban_tin_canh_bao_cap(lat: float, lon: float) -> str:
    """Cảnh báo chính thức (CAP) cho một điểm, thành câu tiếng Việt."""
    ds = canh_bao_cap(lat, lon)
    if not ds:
        return "Hiện không có cảnh báo thời tiết chính thức nào cho khu vực này."
    dong = []
    for c in ds[:4]:
        mo = c.get("tieu_de") or c.get("hien_tuong") or "Cảnh báo"
        khi = gio_dia_phuong(c.get("bat_dau"))
        het = gio_dia_phuong(c.get("ket_thuc"))
        hieu_luc = ""
        if khi and het:
            hieu_luc = f" (từ {khi} đến {het})"
        elif khi:
            hieu_luc = f" (từ {khi})"
        muc = f" — mức {c['muc_do']}" if c.get("muc_do") else ""
        dong.append(f"⚠️ {mo}{muc}{hieu_luc}.")
    return " ".join(dong)
