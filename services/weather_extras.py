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
