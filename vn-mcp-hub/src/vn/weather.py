"""vn_weather — thời tiết Việt Nam qua wttr.in.

Wraps the free wttr.in API and ships with a curated list of Vietnamese
city/province names. wttr.in handles the geolocation by name internally,
so we just pass the city name through (with a couple of common alias
fixes for cities that wttr.in doesn't resolve well).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("vn_weather")

# wttr.in returns JSON when format=j1.
WTTR_URL = "https://wttr.in/{location}"

# Some VN cities benefit from explicit english names for wttr.
ALIAS = {
    "hà nội": "Hanoi",
    "ha noi": "Hanoi",
    "hn": "Hanoi",
    "sài gòn": "Ho Chi Minh City",
    "sai gon": "Ho Chi Minh City",
    "hcm": "Ho Chi Minh City",
    "tp hcm": "Ho Chi Minh City",
    "tp.hcm": "Ho Chi Minh City",
    "đà nẵng": "Da Nang",
    "da nang": "Da Nang",
    "huế": "Hue",
    "hue": "Hue",
    "hải phòng": "Hai Phong",
    "hai phong": "Hai Phong",
    "cần thơ": "Can Tho",
    "can tho": "Can Tho",
    "nha trang": "Nha Trang",
    "đà lạt": "Da Lat",
    "da lat": "Da Lat",
    "vũng tàu": "Vung Tau",
    "vung tau": "Vung Tau",
    "phú quốc": "Phu Quoc",
    "phu quoc": "Phu Quoc",
}


def _normalise(city: str) -> str:
    key = city.strip().lower()
    return ALIAS.get(key, city.strip())


def _fmt_current(data: dict[str, Any]) -> str:
    """Pull a few useful fields from wttr's current_condition section."""
    cur = (data.get("current_condition") or [{}])[0]
    nearest = (data.get("nearest_area") or [{}])[0]
    name = ((nearest.get("areaName") or [{}])[0]).get("value", "")
    country = ((nearest.get("country") or [{}])[0]).get("value", "")
    desc = ((cur.get("lang_vi") or [{}])[0]).get("value") or \
           ((cur.get("weatherDesc") or [{}])[0]).get("value", "")
    temp_c = cur.get("temp_C")
    feels_c = cur.get("FeelsLikeC")
    humidity = cur.get("humidity")
    wind_kph = cur.get("windspeedKmph")
    wind_dir = cur.get("winddir16Point")
    cloud = cur.get("cloudcover")
    visibility = cur.get("visibility")
    uv = cur.get("uvIndex")
    return (
        f"**Thời tiết {name}, {country} hiện tại:** {desc}\n"
        f"- Nhiệt độ: {temp_c}°C (cảm giác {feels_c}°C)\n"
        f"- Độ ẩm: {humidity}%\n"
        f"- Gió: {wind_kph} km/h hướng {wind_dir}\n"
        f"- Mây: {cloud}%\n"
        f"- Tầm nhìn: {visibility} km\n"
        f"- Chỉ số UV: {uv}"
    )


def _fmt_forecast_day(day: dict[str, Any]) -> str:
    date = day.get("date")
    avg = day.get("avgtempC")
    mn = day.get("mintempC")
    mx = day.get("maxtempC")
    rain = day.get("totalSnow_cm") or "0"
    hourly = day.get("hourly") or []
    midday = hourly[len(hourly) // 2] if hourly else {}
    desc = ((midday.get("lang_vi") or [{}])[0]).get("value") or \
           ((midday.get("weatherDesc") or [{}])[0]).get("value", "")
    return f"- {date}: {mn}–{mx}°C (TB {avg}°C), {desc}"


@mcp.tool()
def get_current_weather(city: str) -> str:
    """Lấy thời tiết hiện tại cho thành phố/tỉnh tại Việt Nam.

    Args:
        city: Tên thành phố hoặc tỉnh (vd: "Hà Nội", "TP HCM", "Đà Nẵng").
              Cũng nhận tên tiếng Anh hoặc không dấu.

    Returns:
        Mô tả thời tiết hiện tại bằng tiếng Việt: nhiệt độ, độ ẩm, gió, UV.
    """
    location = _normalise(city)
    url = WTTR_URL.format(location=location.replace(" ", "+"))
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url, params={"format": "j1", "lang": "vi"})
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.warning("wttr fetch failed for %s: %s", location, exc)
        return f"Không lấy được thời tiết cho '{city}': {exc}"
    return _fmt_current(data)


@mcp.tool()
def get_forecast(city: str, days: int = 3) -> str:
    """Lấy dự báo thời tiết 1-3 ngày cho thành phố tại Việt Nam.

    Args:
        city: Tên thành phố (vd: "Hà Nội", "Đà Nẵng").
        days: Số ngày dự báo (1-3, mặc định 3).

    Returns:
        Tóm tắt dự báo từng ngày: nhiệt độ min-max, mô tả thời tiết.
    """
    days = max(1, min(3, days))
    location = _normalise(city)
    url = WTTR_URL.format(location=location.replace(" ", "+"))
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url, params={"format": "j1", "lang": "vi"})
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        return f"Không lấy được dự báo cho '{city}': {exc}"

    forecasts = (data.get("weather") or [])[:days]
    if not forecasts:
        return f"Không có dữ liệu dự báo cho '{city}'."
    lines = [f"**Dự báo {location} {days} ngày tới:**"]
    lines.extend(_fmt_forecast_day(d) for d in forecasts)
    return "\n".join(lines)
