"""Cảnh báo thời tiết xấu 12h tới cho VỊ TRÍ NHÀ — tham khảo tính năng storm
của sunshineplan/weather nhưng viết native Python (không sidecar Go, không cần
API key): Open-Meteo forecast, lat/lon lấy từ HA /api/config.

Dùng bởi fast-path thời tiết (_ha_local_weather): thêm 1 câu cảnh báo dông /
mưa rất to / gió giật vào cuối bản tin chung; không có gì đáng báo → chuỗi rỗng.
"""
from __future__ import annotations

import json
import time
import urllib.request

from utils.log import logger

_cache: tuple[float, str] | None = None
_TTL = 900.0  # 15 phút — cảnh báo không cần tươi hơn


def _home_latlon() -> tuple[float, float] | None:
    from services.ha_client import _api_request
    code, body = _api_request("GET", "/api/config")
    if code != 200:
        return None
    try:
        d = json.loads(body)
        lat, lon = d.get("latitude"), d.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return float(lat), float(lon)
    except Exception:
        pass
    return None


_MA_THOI_TIET = {
    0: "trời quang", 1: "ít mây", 2: "có mây", 3: "nhiều mây",
    45: "sương mù", 48: "sương mù đóng băng",
    51: "mưa phùn nhẹ", 53: "mưa phùn", 55: "mưa phùn nặng hạt",
    61: "mưa nhẹ", 63: "mưa", 65: "mưa to",
    71: "tuyết nhẹ", 73: "tuyết", 75: "tuyết dày",
    80: "mưa rào nhẹ", 81: "mưa rào", 82: "mưa rào rất to",
    95: "dông", 96: "dông kèm mưa đá", 99: "dông mạnh kèm mưa đá",
}
_cache_hien_tai: tuple[float, str] | None = None
_TTL_HIEN_TAI = 600.0     # 10 phút — thời tiết hiện tại không cần tươi hơn


def thoi_tiet_hien_tai(keep_units: bool = True) -> str:
    """Thời tiết HIỆN TẠI từ Open-Meteo cho vị trí nhà — DỰ PHÒNG khi cảm biến
    Home Assistant trả 'unavailable'.

    Vì sao cần: đo thật 31/07, entity thời tiết của HA chết thì bot trả nguyên
    câu "thời tiết Hoàng Mai hiện đang không có dữ liệu (unavailable)" — người
    dùng chẳng nhận được gì dù Open-Meteo (đã dùng cho cảnh báo dông) trả lời
    được ngay và không cần khoá API.

    Trả "" nếu cũng không lấy được (bên gọi tự rơi tiếp sang tra mạng).
    """
    global _cache_hien_tai
    now = time.time()
    if _cache_hien_tai and now - _cache_hien_tai[0] < _TTL_HIEN_TAI:
        return _cache_hien_tai[1]
    out = ""
    try:
        ll = _home_latlon()
        if ll:
            url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
                   "&current=temperature_2m,relative_humidity_2m,weather_code"
                   "&timezone=auto" % ll)
            with urllib.request.urlopen(url, timeout=8) as r:
                cur = (json.loads(r.read().decode()) or {}).get("current") or {}
            nhiet = cur.get("temperature_2m")
            am = cur.get("relative_humidity_2m")
            ma = cur.get("weather_code")
            mo_ta = _MA_THOI_TIET.get(int(ma), "") if ma is not None else ""
            phan = []
            if mo_ta:
                phan.append(mo_ta)
            if nhiet is not None:
                phan.append(f"khoảng {round(float(nhiet))}°C" if keep_units
                            else f"khoảng {round(float(nhiet))} độ")
            if am is not None:
                phan.append(f"độ ẩm {round(float(am))}%" if keep_units
                            else f"độ ẩm {round(float(am))} phần trăm")
            if phan:
                out = "Thời tiết hiện tại: " + ", ".join(phan) + "."
    except Exception as exc:
        logger.warning({"event": "thoi_tiet_hien_tai_failed", "error": str(exc)[:120]})
    _cache_hien_tai = (now, out)
    return out


def storm_warning() -> str:
    """Câu cảnh báo tiếng Việt nếu 12h tới có dông (weather_code>=95), mưa rất
    to (>=10mm/h) hoặc gió giật >=60km/h; '' nếu trời yên. Best-effort."""
    global _cache
    now = time.time()
    if _cache and now - _cache[0] < _TTL:
        return _cache[1]
    out = ""
    try:
        ll = _home_latlon()
        if ll:
            url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
                   "&hourly=weather_code,precipitation,wind_gusts_10m"
                   "&forecast_hours=12&timezone=auto" % ll)
            with urllib.request.urlopen(url, timeout=8) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            h = d.get("hourly") or {}
            times = h.get("time") or []
            codes = h.get("weather_code") or []
            rain = h.get("precipitation") or []
            gust = h.get("wind_gusts_10m") or []

            def _first(vals, pred, fmt):
                for i, t in enumerate(times):
                    v = vals[i] if i < len(vals) else None
                    try:
                        if v is not None and pred(float(v)):
                            return fmt(float(v), str(t)[11:16])
                    except (TypeError, ValueError):
                        continue
                return ""

            warns = [w for w in (
                _first(codes, lambda v: v >= 95, lambda v, hh: f"dông khoảng {hh}"),
                _first(rain, lambda v: v >= 10, lambda v, hh: f"mưa rất to (~{round(v)}mm) khoảng {hh}"),
                _first(gust, lambda v: v >= 60, lambda v, hh: f"gió giật mạnh (~{round(v)} km/h) khoảng {hh}"),
            ) if w]
            if warns:
                out = "⛈️ Cảnh báo 12 giờ tới: " + "; ".join(warns) + "."
    except Exception as exc:
        logger.warning({"event": "weather_extras_failed", "error": str(exc)[:120]})
    _cache = (now, out)
    return out
