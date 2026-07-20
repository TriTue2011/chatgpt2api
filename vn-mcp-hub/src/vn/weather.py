"""vn_weather — multi-source weather for Vietnam and worldwide.

Sources (togglable in Studio UI):
- Open-Meteo: global, free, no API key — primary
- wttr.in: free, no key — fallback
- NWS (US National Weather Service): free, US-only
- AccuWeather: free tier 50/day, needs ACCUWEATHER_API_KEY env var
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("vn_weather")

WTTR_URL = "https://wttr.in/{location}"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEO = "https://geocoding-api.open-meteo.com/v1/search"
NWS_URL = "https://api.weather.gov/points/{lat},{lon}"
# AccuWeather web-api (giong repo smarthomeblack): MIEN PHI, KHONG key, KHONG
# quota, phu toi cap phuong va tra thang toa do (lat/lon) -> geocoder VN chinh.
ACCU_WEBAPI = "https://www.accuweather.com/web-api/autocomplete"
_ACCU_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json"}

ALIAS = {
    "ha noi": "Hanoi", "hn": "Hanoi",
    "sai gon": "Ho Chi Minh City", "hcm": "Ho Chi Minh City",
    "tp hcm": "Ho Chi Minh City", "tp.hcm": "Ho Chi Minh City",
    "da nang": "Da Nang",
    "hue": "Hue",
    "hai phong": "Hai Phong",
    "can tho": "Can Tho",
}


def _is_enabled(source: str) -> bool:
    try:
        from src.sources_config import is_enabled as _chk
        return _chk("vn_weather", source)
    except Exception:
        return True


# ── Open-Meteo (primary, free global) ─────────────────────────────────────

_WMO = {0: "trời quang", 1: "ít mây", 2: "có mây", 3: "nhiều mây",
        45: "sương mù", 48: "sương mù băng giá", 51: "mưa phùn nhẹ",
        53: "mưa phùn", 55: "mưa phùn dày", 56: "mưa phùn băng giá",
        57: "mưa phùn băng giá", 61: "mưa nhỏ", 63: "mưa vừa", 65: "mưa to",
        66: "mưa băng giá", 67: "mưa băng giá", 71: "tuyết nhẹ", 73: "tuyết vừa",
        75: "tuyết to", 77: "hạt tuyết", 80: "mưa rào", 81: "mưa rào vừa",
        82: "mưa rào to", 85: "tuyết rào", 86: "tuyết rào to", 95: "dông",
        96: "dông kèm mưa đá", 99: "dông mạnh kèm mưa đá"}


def _vn_num(x) -> str:
    """So thap phan kieu Viet Nam: dung dau PHAY (32.2 -> '32,2')."""
    return str(x).replace(".", ",")


def _titlecase_vn(s: str) -> str:
    """Hoa chu cai dau moi tu, giu nguyen phan con lai ('hà nội' -> 'Hà Nội')."""
    return " ".join(w[:1].upper() + w[1:] if w else w for w in s.split(" "))


def _aqi_cat(aqi: float) -> str:
    if aqi <= 50:
        return "tốt"
    if aqi <= 100:
        return "trung bình"
    if aqi <= 150:
        return "kém"
    if aqi <= 200:
        return "xấu"
    if aqi <= 300:
        return "rất xấu"
    return "nguy hại"


def _uv_cat(uv: float) -> str:
    if uv < 3:
        return "thấp"
    if uv < 6:
        return "trung bình"
    if uv < 8:
        return "cao"
    if uv < 11:
        return "rất cao"
    return "cực kỳ cao"


def _wind_cat(kmh: float) -> str:
    if kmh < 12:
        return "gió nhẹ"
    if kmh < 30:
        return "gió vừa"
    return "gió mạnh"


def _air_quality(lat: float, lon: float) -> str:
    """Chat luong khong khi (Open-Meteo Air Quality API, free) -> mo ta NGAN, doc
    xuoi (chi muc do, khong so/don vi cho do ngang tai khi TTS doc)."""
    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get("https://air-quality-api.open-meteo.com/v1/air-quality",
                      params={"latitude": lat, "longitude": lon,
                              "current": "us_aqi", "timezone": "auto"})
            r.raise_for_status()
        aqi = (r.json().get("current", {}) or {}).get("us_aqi")
        if aqi is None:
            return ""
        return f"Chất lượng không khí ở mức {_aqi_cat(aqi)}."
    except Exception:
        return ""


def _om_fetch(lat: float, lon: float, name: str) -> str | None:
    """Thoi tiet hien tai tu Open-Meteo theo TOA DO -> CAU VAN XUOI cho giong noi:
    bo ky tu/don vi gay ngang tai (°C, %, km/h), dung 'do' va cap do."""
    if not _is_enabled("open_meteo"):
        return None
    try:
        with httpx.Client(timeout=8.0) as c:
            wr = c.get(OPEN_METEO_URL, params={
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,uv_index",
                "timezone": "auto",
            })
            wr.raise_for_status()
        w = wr.json().get("current", {})
        desc = _WMO.get(w.get("weather_code", 0), "")
        s = f"Thời tiết {_titlecase_vn(name)}"
        if desc:
            s += f" hiện {desc}"
        temp, feels = w.get("temperature_2m"), w.get("apparent_temperature")
        if temp is not None:
            s += f", khoảng {round(temp)} độ"
            if feels is not None and abs(feels - temp) >= 3:
                s += f", cảm giác như {round(feels)} độ"
        hum, wind = w.get("relative_humidity_2m"), w.get("wind_speed_10m")
        if hum is not None:
            s += f", độ ẩm {round(hum)} phần trăm"
        if wind is not None:
            s += f", {_wind_cat(wind)}"
        s += "."
        uv = w.get("uv_index")
        if uv is not None:
            s += f" Chỉ số tia cực tím ở mức {_uv_cat(uv)}."
        aq = _air_quality(lat, lon)
        if aq:
            s += f" {aq}"
        return s
    except Exception as exc:
        logger.warning("Open-Meteo fetch failed: %s", exc)
        return None


def _open_meteo_current(query: str, require_match: str = "") -> str | None:
    if not _is_enabled("open_meteo"):
        return None
    try:
        with httpx.Client(timeout=10.0) as c:
            gr = c.get(OPEN_METEO_GEO, params={"name": query, "count": 5, "language": "vi"})
            gr.raise_for_status()
        results = (gr.json().get("results") or [])
        if not results:
            return None
        # Mac dinh Viet Nam: tro ly huong VN nen uu tien ket qua VN neu co. Dia
        # danh nuoc ngoai (London, Tokyo...) khong co ban trung VN -> roi ve #1.
        vn = [r for r in results if r.get("country_code") == "VN"]
        loc = (vn or results)[0]
        # Chong khop-mo rac: neu doi hoi ten khop (tra huyen) ma ten geocode khong
        # chua DU token cua ten huyen -> tu choi (vd "Kim Thanh" -> "Thon Tam").
        if require_match:
            ntok = set(_wfold(loc.get("name", "")).split())
            qtok = [t for t in _wfold(require_match).split() if len(t) >= 2]
            if qtok and not all(t in ntok for t in qtok):
                return None
        return _om_fetch(loc["latitude"], loc["longitude"], loc.get("name", query))
    except Exception as exc:
        logger.warning("Open-Meteo geocode failed: %s", exc)
        return None


# ── NWS (US National Weather Service, free) ───────────────────────────────

def _nws_current(query: str) -> str | None:
    if not _is_enabled("nws"):
        return None
    try:
        with httpx.Client(timeout=10.0) as c:
            gr = c.get(OPEN_METEO_GEO, params={"name": query, "count": 1})
            gr.raise_for_status()
        results = (gr.json().get("results") or [])
        if not results:
            return None
        loc = results[0]
        if loc.get("country_code", "").upper() != "US":
            return None
        lat, lon = loc["latitude"], loc["longitude"]

        with httpx.Client(timeout=10.0) as c:
            pr = c.get(NWS_URL.format(lat=lat, lon=lon),
                       headers={"User-Agent": "vn-mcp-hub/0.1", "Accept": "application/json"})
            pr.raise_for_status()
        forecast_url = pr.json().get("properties", {}).get("forecast")
        if not forecast_url:
            return None
        with httpx.Client(timeout=10.0) as c:
            fr = c.get(forecast_url, headers={"User-Agent": "vn-mcp-hub/0.1", "Accept": "application/json"})
            fr.raise_for_status()
        period = (fr.json().get("properties", {}).get("periods") or [])[0]
        return (
            f"**Thoi tiet {loc.get('name', query)}, US (NWS):** {period.get('shortForecast','')}\n"
            f"- Nhiet do: {period.get('temperature')}F ({period.get('temperatureUnit','F')})\n"
            f"- Gio: {period.get('windSpeed','')} {period.get('windDirection','')}\n"
            f"- {period.get('detailedForecast','')}"
        )
    except Exception as exc:
        logger.warning("NWS failed: %s", exc)
        return None


# ── AccuWeather web-api geocoder (free, no key, phu toi phuong) ────────────
# (Da bo nhanh AccuWeather API chinh thuc dataservice.accuweather.com + key —
#  chi dung web-api mien phi ben duoi.)

_WARD_PRE = ("phường ", "xã ", "thị trấn ", "phuong ", "xa ", "thi tran ")


def _strip_ward(nm: str) -> str:
    low = nm.lower()
    for p in _WARD_PRE:
        if low.startswith(p):
            return nm[len(p):].strip()
    return nm.strip()


def _prov_of(ln: str) -> str:
    """Tach tinh tu longName: 'Tan Binh, Tuyen Quang Province VN' -> 'Tuyen Quang'."""
    parts = ln.split(",")
    tail = parts[-1].strip() if len(parts) >= 2 else ln.strip()
    if tail.endswith(" VN"):
        tail = tail[:-3].strip()
    if tail.endswith(" Province"):
        tail = tail[:-9].strip()
    return tail or "Việt Nam"


def _has_diac(s: str) -> bool:
    import unicodedata
    return any(unicodedata.category(c) == "Mn" for c in unicodedata.normalize("NFD", s)) \
        or "đ" in s.lower()


_PROVS_FOLDED: set[str] | None = None


def _province_set() -> set[str]:
    """Tap ten tinh/thanh (folded) lay tu gazetteer — de nhan dien truy van la
    TINH (Ha Noi, Da Nang) -> resolve thang, khong hoi nham."""
    global _PROVS_FOLDED
    if _PROVS_FOLDED is None:
        _PROVS_FOLDED = {_wfold(v) for v in _district_map().values()}
    return _PROVS_FOLDED


def _accuweather_resolve(query: str, prefer_prov: str = "") -> dict:
    """Geocode VN bang AccuWeather web-api (free, khong key). Tra:
      {'status':'ok','lat','lon','name'}          - tim duoc 1 noi ro rang
      {'status':'ask','provs':[...],'name':query} - trung ten >=2 tinh / lech dau
      {'status':'none'}                           - khong co ung vien VN
    prefer_prov (huyen gazetteer da biet) -> chi lay ung vien dung tinh, khong hoi."""
    if not query.strip():
        return {"status": "none"}
    try:
        with httpx.Client(timeout=12.0, follow_redirects=True, headers=_ACCU_UA) as c:
            r = c.get(ACCU_WEBAPI, params={"query": query, "language": "en-us"})
        if r.status_code != 200:
            return {"status": "none"}
        items = r.json() or []
    except Exception as exc:
        logger.warning("AccuWeather web-api failed: %s", exc)
        return {"status": "none"}
    qf = _wfold(query)
    pf = _wfold(prefer_prov).replace(" ", "") if prefer_prov else ""
    # Giu ung vien VN la LOCALITY khop AM (ten bo tien to phuong/xa fold == truy
    # van) -> loai POI ('My Dinh Stadium') va ten dai ('Tan Binh (Huyen X)').
    locs = []  # (lat, lon, name, prov, diac_exact)
    for it in items:
        ln = it.get("longName") or ""
        key = it.get("key") or ""
        if not (ln.rstrip().endswith(" VN") or "country=VN" in key):
            continue
        lat, lon = it.get("lat"), it.get("lon")
        if lat is None or lon is None:
            continue
        nm = it.get("name") or ""
        bare = _strip_ward(nm)
        if _wfold(bare) != qf:
            continue
        locs.append((float(lat), float(lon), nm, _prov_of(ln),
                     bare.strip().lower() == query.strip().lower()))
    if not locs:
        return {"status": "none"}
    if pf:  # huyen gazetteer da biet -> ep dung tinh, khong hoi
        inprov = [l for l in locs if pf in _wfold(l[3]).replace(" ", "")]
        if inprov:
            l = inprov[0]
            return {"status": "ok", "lat": l[0], "lon": l[1], "name": l[2]}
        return {"status": "none"}
    # Truy van CHINH la ten tinh/thanh (Ha Noi, Da Nang...) -> resolve thang.
    if qf in _province_set():
        l = next((x for x in locs if x[4]), locs[0])
        return {"status": "ok", "lat": l[0], "lon": l[1], "name": l[2]}
    # Khong rang buoc tinh -> kiem nhap nhang
    seen, provs = set(), []
    for l in locs:
        pk = _wfold(l[3]).replace(" ", "")
        if pk not in seen:
            seen.add(pk); provs.append(l[3])
    if len(provs) >= 2:
        return {"status": "ask", "provs": provs, "name": query}
    # 1 tinh nhung truy van CO dau ma khong ung vien nao khop dau (My Dinh vs My
    # Dinh) -> coi nhu chua tim thay dung -> hoi.
    if _has_diac(query) and not any(l[4] for l in locs):
        return {"status": "ask", "provs": [], "name": query}
    l = locs[0]
    return {"status": "ok", "lat": l[0], "lon": l[1], "name": l[2]}


def _ask_text(res: dict) -> str:
    """Cau hoi lai user khi dia danh trung ten / lech dau."""
    nm = res.get("name", "")
    provs = res.get("provs") or []
    if provs:
        lst = ", ".join(provs[:5])
        return f"\"{nm}\" có ở nhiều tỉnh ({lst}). Bạn muốn hỏi thời tiết tỉnh/thành nào ạ?"
    return f"Mình chưa tìm thấy chính xác \"{nm}\". Bạn cho biết thuộc tỉnh/thành nào để mình tra đúng nhé?"


def _geocode_coords(query: str) -> tuple[float, float] | None:
    """Geocode tho (Open-Meteo, uu tien VN) -> (lat, lon). Dung cho minutecast khi
    web-api truot (vd quy ve ten tinh)."""
    if not query.strip():
        return None
    try:
        with httpx.Client(timeout=10.0) as c:
            gr = c.get(OPEN_METEO_GEO, params={"name": query, "count": 5, "language": "vi"})
            gr.raise_for_status()
        results = (gr.json().get("results") or [])
        if not results:
            return None
        vn = [r for r in results if r.get("country_code") == "VN"]
        loc = (vn or results)[0]
        return float(loc["latitude"]), float(loc["longitude"])
    except Exception:
        return None


# ── wttr.in (fallback, free) ──────────────────────────────────────────────

def _normalise(city: str) -> str:
    key = city.strip().lower()
    return ALIAS.get(key, city.strip())


def _wttr_current(city: str) -> str | None:
    if not _is_enabled("wttr"):
        return None
    location = _normalise(city)
    url = WTTR_URL.format(location=location.replace(" ", "+"))
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url, params={"format": "j1", "lang": "vi"})
            r.raise_for_status()
        data = r.json()
        cur = (data.get("current_condition") or [{}])[0]
        nearest = (data.get("nearest_area") or [{}])[0]
        name = ((nearest.get("areaName") or [{}])[0]).get("value", "")
        desc = ((cur.get("lang_vi") or [{}])[0]).get("value") or \
               ((cur.get("weatherDesc") or [{}])[0]).get("value", "")
        s = f"Thời tiết {name}"
        if desc:
            s += f" hiện {desc.strip().lower()}"
        if cur.get("temp_C") is not None:
            s += f", {cur.get('temp_C')}°C"
            if cur.get("FeelsLikeC"):
                s += f" (cảm giác {cur.get('FeelsLikeC')}°C)"
        if cur.get("humidity"):
            s += f", độ ẩm {cur.get('humidity')}%"
        if cur.get("windspeedKmph"):
            s += f", gió {cur.get('windspeedKmph')} km/h"
        return s + "."
    except Exception as exc:
        logger.warning("wttr fetch failed for %s: %s", city, exc)
        return None


# ── VN district gazetteer (huyen -> tinh) ──────────────────────────────────
# Geocoder toan cau index tot cap TINH nhung sot/khop-mo cap HUYEN nong thon
# ("Kim Thanh" -> "Thon Tam"). Map huyen->tinh (du lieu hanh chinh chung, KHONG
# hardcode nha user) cho phep tra ve thoi tiet TINH (thoi tiet dong nhat theo
# tinh) khi geocode truc tiep that bai -> phu 100% huyen mot cach tin cay.

_DISTRICTS: dict[str, str] | None = None


def _wfold(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().replace("đ", "d").strip()


def _district_map() -> dict[str, str]:
    global _DISTRICTS
    if _DISTRICTS is None:
        try:
            import json
            from pathlib import Path
            p = Path(__file__).with_name("vn_districts.json")
            _DISTRICTS = json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning("vn_districts load failed: %s", exc)
            _DISTRICTS = {}
    return _DISTRICTS


_DIST_ADMIN_PRE = ("thanh pho ", "tp ", "tp. ", "quan ", "huyen ", "thi xa ", "thi tran ")


def _vn_district_lookup(city: str) -> tuple[str | None, str | None]:
    """Tra ten huyen VN -> (tinh, ten-hien-thi) hoac (None, None)."""
    if not city:
        return None, None
    f = _wfold(city)
    for p in _DIST_ADMIN_PRE:
        if f.startswith(p):
            f = f[len(p):].strip()
            break
    m = _district_map()
    if f in m:
        return m[f], city.strip()
    for key in m:  # "kim thanh hai duong" -> prefix khop "kim thanh"
        if f.startswith(key + " "):
            return m[key], city.strip()
    return None, None


# ── MCP Tools ─────────────────────────────────────────────────────────────

@mcp.tool()
def get_current_weather(city: str) -> str:
    """Lay thoi tiet hien tai. Ho tro VN va quoc te.

    Args:
        city: Ten thanh pho (vd: "Ha Noi", "London", "New York").
    Returns:
        Mo ta thoi tiet: nhiet do, do am, gio, UV.
    """
    # Gazetteer cho biet TINH ky vong (neu la huyen da biet) -> rang buoc geocoder.
    prov, dist = _vn_district_lookup(city)

    # 1. GEOCODER CHINH cho VN: AccuWeather web-api (mien phi, khong key, phu toi
    #    cap phuong). Trung ten >=2 tinh / lech dau -> HOI lai user tinh nao.
    res = _accuweather_resolve(city, prefer_prov=prov or "")
    if res["status"] == "ask":
        return _ask_text(res)
    if res["status"] == "ok":
        r = _om_fetch(res["lat"], res["lon"], res["name"])
        if r:
            return r

    # 2. Fallback: huyen VN da biet (gazetteer) khi web-api truot -> Open-Meteo
    #    truc tiep (Sa Pa/Hoan Kiem khop) hoac thoi tiet TINH (dung tinh).
    if prov:
        # web-api đã lo huyện có sẵn; tới đây = huyện quê web-api trượt → quy về
        # TỈNH ngay (1 geocode, bỏ bước geocode-trực-tiếp luôn fail cho nhanh).
        coords = _geocode_coords(prov)
        if coords:
            r = _om_fetch(coords[0], coords[1], f"{dist or city}, {prov}")
            if r:
                return r
        r = _wttr_current(prov)
        if r:
            return r
        return f"Mình chưa lấy được thời tiết cho {city}, anh thử lại sau nhé."

    # 3. Khong phai VN (tinh/dia danh nuoc ngoai) hoac web-api truot: chuoi thuong.
    for fn in (_open_meteo_current, _nws_current, _wttr_current):
        result = fn(city)
        if result:
            return result
    return f"Mình chưa lấy được thời tiết cho {city}, anh thử lại sau nhé."


@mcp.tool()
def get_minutecast(city: str) -> str:
    """Du bao mua ~2 gio toi (tung 15 phut) cho dia danh VN qua Open-Meteo
    minutely_15 (mien phi). Tra 'sap mua sau X phut' / 'khong mua' / 'dang mua'.

    Args:
        city: Ten dia danh (vd 'Cau Giay', 'Sa Pa').
    """
    prov, _ = _vn_district_lookup(city)
    res = _accuweather_resolve(city, prefer_prov=prov or "")
    if res["status"] == "ask":
        return _ask_text(res)
    if res["status"] == "ok":
        lat, lon, name = res["lat"], res["lon"], res["name"]
    else:
        coords = _geocode_coords(prov or city)
        if not coords:
            return f"Mình chưa xác định được vị trí {city}."
        lat, lon = coords
        name = f"{city}, {prov}" if prov else city
    try:
        with httpx.Client(timeout=10.0) as c:
            wr = c.get(OPEN_METEO_URL, params={
                "latitude": lat, "longitude": lon,
                "minutely_15": "precipitation",
                "forecast_minutely_15": 8,  # 8 x 15' = 2h
                "timezone": "auto",
            })
            wr.raise_for_status()
        precip = (wr.json().get("minutely_15", {}) or {}).get("precipitation") or []
    except Exception as exc:
        logger.warning("minutecast failed: %s", exc)
        return f"Mình chưa lấy được dự báo mưa cho {name}."
    seq = [(v or 0) for v in precip[:8]]
    first = next((i for i, v in enumerate(seq) if v >= 0.1), -1)
    if first < 0:
        return f"{name} không mưa trong khoảng 2 giờ tới."
    if first == 0:
        return f"{name} đang có mưa (khoảng {round(sum(seq), 1)}mm trong 2 giờ tới)."
    return f"{name} sắp mưa sau khoảng {first * 15} phút nữa."


@mcp.tool()
def get_forecast(city: str, days: int = 3) -> str:
    """Lay du bao thoi tiet 1-3 ngay.

    Args:
        city: Ten thanh pho.
        days: So ngay du bao (1-3, mac dinh 3).
    Returns:
        Tom tat du bao tung ngay.
    """
    days = max(1, min(3, days))
    if not _is_enabled("wttr"):
        return "Du bao chi kha dung qua wttr.in (dang tat trong Sources). Bat wttr trong Studio."
    location = _normalise(city)
    url = WTTR_URL.format(location=location.replace(" ", "+"))
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url, params={"format": "j1", "lang": "vi"})
            r.raise_for_status()
        data = r.json()
    except Exception as exc:
        return f"Khong lay duoc du bao cho '{city}': {exc}"
    weather = data.get("weather") or []
    lines = [f"**Du bao {city}:**"]
    for d in weather[:days]:
        date = d.get("date")
        mn = d.get("mintempC")
        mx = d.get("maxtempC")
        avg = d.get("avgtempC")
        hourly = d.get("hourly") or []
        midday = hourly[len(hourly) // 2] if hourly else {}
        desc = ((midday.get("lang_vi") or [{}])[0]).get("value") or \
               ((midday.get("weatherDesc") or [{}])[0]).get("value", "")
        lines.append(f"- {date}: {mn}-{mx}C (TB {avg}C), {desc}")
    return "\n".join(lines)
