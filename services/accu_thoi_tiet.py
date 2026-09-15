"""Thời tiết hiện tại từ AccuWeather — KHÔNG cần Home Assistant, KHÔNG cần khoá API.

Port từ `custom_components/accuweather/utils.py` (kho TriTue2011/accuweather),
cùng nếp `services/thoi_tiet_bao.py` đã port `windy.py`: bỏ phụ thuộc
`homeassistant`, gọi đồng bộ bằng curl_cffi giả lập Chrome.

Vì sao không dùng bộ dò của `vn_weather` (vn-mcp-hub): nó hỏi autocomplete bằng
`language=en-us`, nhận về mã `GEO_…` lẫn khách sạn, rồi khớp tên trần. Đo thật
15/09/2026 trên 63 tên tỉnh: 20 tên trượt hoặc sai chỗ — «Hà Nội» thành một nơi
trùng tên ở Hà Nam (lệch 64 km), «Bình Định» lệch 1.367 km, «Hoàng Mai» không
có ứng viên nào ở Hà Nội. Hỏi bằng `language=vi` kèm Accept-Language như
component HA thì «Hoàng Mai» ra đúng mã 3558175 «Hoàng Mai, Hà Nội, VN» — chính
mã mà thực thể `weather.accuweather_hoang_mai` đang dùng.

Hai hàm công khai:
  * `tim_dia_danh(ten)`  — ứng viên AccuWeather cho tên người dùng gõ.
  * `thoi_tiet_hien_tai(dia_danh)` — một đoạn văn thời tiết cho ứng viên đã chọn.
"""
from __future__ import annotations

import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from utils.log import logger

BASE_URL = "https://www.accuweather.com"
AUTOCOMPLETE_URL = f"{BASE_URL}/web-api/autocomplete"
_TIMEOUT = 15
# Component HA làm mới trang hiện tại mỗi 5 phút; hỏi dồn trong khoảng đó thì
# dùng lại, khỏi gọi AccuWeather ba trang cho mỗi câu.
_TTL = 300.0
# Tên người dùng gõ hiếm khi quá chừng này từ; chặn để một câu dài không thành
# cả chục lượt gọi autocomplete khi bớt dần từ cuối.
_TOI_DA_TU = 6

# Nhãn dòng chi tiết trên trang, theo `const.DETAIL_LABELS` của component — trang
# xin bằng tiếng Việt nhưng AccuWeather thỉnh thoảng trả lẫn tiếng Anh.
_NHAN = {
    "realfeel": ("RealFeel®",),
    "uv": ("Chỉ số UV tối đa", "Max UV Index"),
    "gio": ("Gió", "Wind"),
    "gio_giat": ("Gió giật mạnh", "Gió giật", "Wind Gusts"),
    "do_am": ("Độ ẩm", "Humidity"),
}

_cache: dict[str, tuple[float, str]] = {}
_cache_tim: dict[str, tuple[float, list[dict[str, str]]]] = {}


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower().replace("đ", "d"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _headers(json_: bool = False) -> dict[str, str]:
    # Cookie chốt °C và tiếng Việt: thiếu nó AccuWeather chọn đơn vị theo vị trí
    # đoán được của máy chủ, trang °F sẽ bị đọc nhầm thành °C.
    return {
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": ("application/json, text/javascript, */*; q=0.01" if json_ else
                   "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        "Cookie": "awx_user=tp:C|lang:vi",
    }


def _get(url: str, *, params: dict | None = None, json_: bool = False):
    from curl_cffi import requests as creq
    return creq.get(url, params=params, headers=_headers(json_),
                    impersonate="chrome", timeout=_TIMEOUT)


def _autocomplete(q: str) -> list[dict[str, str]] | None:
    """None = không gọi được AccuWeather; [] = gọi được mà không có ứng viên."""
    hit = _cache_tim.get(q)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    try:
        r = _get(AUTOCOMPLETE_URL, params={"query": q, "language": "vi"}, json_=True)
        if r.status_code != 200:
            logger.warning({"event": "accu_autocomplete_http", "status": r.status_code})
            return None
        data = r.json() or []
    except Exception as exc:
        logger.warning({"event": "accu_autocomplete_loi", "error": str(exc)[:150]})
        return None
    ra = []
    for it in data if isinstance(data, list) else []:
        key, ten = str(it.get("key") or ""), str(it.get("localizedName") or "")
        if key.isdigit() and ten:
            ra.append({"key": key, "ten": ten,
                       "day_du": str(it.get("longName") or ten),
                       "quoc_gia": str((it.get("country") or {}).get("id") or "")})
    _cache_tim[q] = (time.time(), ra)
    return ra


def _tu(s: str) -> list[str]:
    return [t for t in re.split(r"[\s,]+", _fold(s).strip(" .?!")) if t]


def khop_ten(go: str, u: dict[str, str]) -> bool:
    """`go` là ĐÚNG tên ứng viên, hoặc đầu tên đầy đủ («Hoàng Mai, Hà Nội»)."""
    tu = _tu(go)
    return bool(tu) and (tu == _tu(u.get("ten", "")) or tu == _tu(u.get("day_du", ""))[:len(tu)])


def tim_dia_danh(ten: str) -> list[dict[str, str]] | None:
    """Ứng viên AccuWeather cho `ten`: [{key, ten, day_du, quoc_gia}].

    AccuWeather không tra được nguyên cụm có phần định vị («Hoàng Mai, Hà Nội»,
    «Hoàng Mai Hà Nội» đều ra 0 ứng viên). Nên bớt dần từ ở CUỐI, và phần bị bớt
    trở thành điều kiện lọc: ứng viên phải có đủ các từ đó trong tên đầy đủ
    («Hoàng Mai, Hà Nội, VN»). Nhờ vậy chính câu người dùng tự khử trùng tên —
    «Hoàng Mai» ở Hồ Bắc (CN) bị loại mà không cần bảng tỉnh nào.

    Tên ứng viên phải TRÙNG phần tên đang tra. Autocomplete là tra theo đầu chữ:
    đo thật 15/09, «ha noi» không dấu ra 0 ứng viên, bớt còn «ha» thì ra
    «Hailar, Nội Mông, CN» — và chữ «noi» bị bớt lại khớp «Nội Mông», nên bot báo
    thời tiết Nội Mông cho câu hỏi Hà Nội. Không trùng tên thì coi như không có.

    Ứng viên Việt Nam xếp trước. None = không gọi được AccuWeather.
    """
    tu = [t for t in re.split(r"[\s,]+", (ten or "").strip()) if t][:_TOI_DA_TU]
    for n in range(len(tu), 0, -1):
        q = " ".join(tu[:n])
        ung_vien = _autocomplete(q)
        if ung_vien is None:
            return None
        ung_vien = [u for u in ung_vien if khop_ten(q, u)]
        con_lai = [_fold(t) for t in tu[n:]]
        if con_lai:
            ung_vien = [u for u in ung_vien
                        if set(con_lai) <= set(re.split(r"[\s,]+", _fold(u["day_du"])))]
        if ung_vien:
            return sorted(ung_vien, key=lambda u: u["quoc_gia"] != "VN")
    return []


def _so(text: str | None) -> float | None:
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(text or "").replace("°", " "))
    return float(m.group(0).replace(",", ".")) if m else None


def _gon(x: float | None) -> str:
    return "" if x is None else str(round(x))


def _slug(ten: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9-]", "", _fold(ten).replace(" ", "-"))).strip("-")


def _url(dd: dict[str, str], trang: str) -> str:
    quoc_gia = (dd.get("quoc_gia") or "vn").lower()
    return (f"{BASE_URL}/vi/{quoc_gia}/{_slug(dd.get('ten') or 'x') or 'x'}/"
            f"{dd['key']}/{trang}/{dd['key']}")


def _html(dd: dict[str, str], trang: str) -> str | None:
    try:
        r = _get(_url(dd, trang))
        if r.status_code == 200:
            return r.text
        logger.warning({"event": "accu_trang_http", "trang": trang, "status": r.status_code})
    except Exception as exc:
        logger.warning({"event": "accu_trang_loi", "trang": trang, "error": str(exc)[:150]})
    return None


def doc_hien_tai(html: str) -> dict[str, Any] | None:
    """Thẻ «Thời tiết hiện tại» — theo `parse_weather_html` của component."""
    from bs4 import BeautifulSoup
    card = BeautifulSoup(html, "html.parser").select_one(".current-weather-card")
    if not card:
        return None

    def _txt(sel: str) -> str | None:
        el = card.select_one(sel)
        return el.get_text(" ", strip=True) if el else None

    chi_tiet: dict[str, str] = {}
    for item in card.select(".current-weather-details .detail-item"):
        nhan, gia_tri = item.select_one("div:nth-child(1)"), item.select_one("div:nth-child(2)")
        if nhan and gia_tri:
            chi_tiet[nhan.get_text(strip=True)] = gia_tri.get_text(" ", strip=True)

    def _ct(khoa: str) -> str | None:
        return next((chi_tiet[n] for n in _NHAN[khoa] if n in chi_tiet), None)

    nhiet_hien = _txt(".display-temp") or ""
    do_f = bool(re.search(r"°\s*F", nhiet_hien))

    def _doi(x: float | None) -> float | None:
        return (x - 32) * 5 / 9 if (x is not None and do_f) else x

    cam_giac_chu = None
    extra = card.select_one(".current-weather-extra")
    if extra and (nhan := extra.select_one(".label")):
        cam_giac_chu = nhan.get_text(strip=True)
    return {
        "gio_do": _txt(".card-header .sub"),
        "nhiet_do": _doi(_so(nhiet_hien)),
        "mo_ta": _txt(".phrase"),
        "cam_giac": _doi(_so(_ct("realfeel"))),
        "cam_giac_chu": cam_giac_chu,
        "uv": _ct("uv"),
        "gio": _ct("gio"),
        "do_am": _so(_ct("do_am")),
    }


def doc_khong_khi(html: str) -> dict[str, Any]:
    """Chỉ số AQI hiện tại — theo `parse_air_html`, phạm vi `#current`."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    cur = soup.select_one("#current") or soup.select_one(".air-quality-card")
    if not cur:
        return {}
    so, loai = cur.select_one(".aq-number"), cur.select_one(".category-text")
    return {"aqi": _so(so.get_text(strip=True)) if so else None,
            "muc": loai.get_text(strip=True) if loai else None}


def doc_minutecast(html: str) -> str | None:
    """Câu tóm tắt mưa trong 2 giờ tới — theo `parse_minutecast_html`."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    el = (soup.select_one(".minute-cast-chart .current-summary .summary")
          or soup.select_one(".minute-cast-chart .summary"))
    return el.get_text(strip=True) if el else None


def _ten_hien_thi(dd: dict[str, str]) -> str:
    # «Hoàng Mai, Hà Nội, VN» → «Hoàng Mai, Hà Nội»: mã nước chỉ là nhiễu trong câu.
    day_du = str(dd.get("day_du") or dd.get("ten") or "")
    phan = [p.strip() for p in day_du.split(",") if p.strip()]
    if len(phan) >= 2 and phan[-1] == dd.get("quoc_gia") == "VN":
        phan = phan[:-1]
    # «Hà Nội, Hà Nội» → «Hà Nội».
    return ", ".join(p for i, p in enumerate(phan) if i == 0 or p != phan[i - 1])


def thoi_tiet_hien_tai(dd: dict[str, str]) -> str | None:
    """Đoạn văn thời tiết hiện tại cho một ứng viên của `tim_dia_danh`.

    None = không lấy được trang thời tiết hiện tại (mạng / AccuWeather đổi giao
    diện). Không khí và MinuteCast chỉ là phần thêm: hỏng thì bỏ câu đó, không
    làm hỏng cả đoạn.
    """
    key = str(dd.get("key") or "")
    if not key.isdigit():
        return None
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_ht = ex.submit(_html, dd, "current-weather")
        f_kk = ex.submit(_html, dd, "air-quality-index")
        f_mc = ex.submit(_html, dd, "minute-weather-forecast")
        html_ht, html_kk, html_mc = f_ht.result(), f_kk.result(), f_mc.result()
    ht = doc_hien_tai(html_ht) if html_ht else None
    if not ht or ht.get("nhiet_do") is None:
        logger.warning({"event": "accu_khong_doc_duoc_the_hien_tai", "key": key,
                        "co_html": bool(html_ht)})
        return None
    try:
        kk = doc_khong_khi(html_kk) if html_kk else {}
    except Exception:
        kk = {}
    try:
        mc = doc_minutecast(html_mc) if html_mc else None
    except Exception:
        mc = None

    dau = f"Thời tiết {_ten_hien_thi(dd)}"
    if ht.get("gio_do"):
        dau += f" lúc {ht['gio_do']}"
    ve = [f"{ht['mo_ta'].lower()}" if ht.get("mo_ta") else "", f"{_gon(ht['nhiet_do'])}°C"]
    if ht.get("cam_giac") is not None:
        cg = f"cảm giác như {_gon(ht['cam_giac'])}°C"
        if ht.get("cam_giac_chu"):
            cg += f" ({ht['cam_giac_chu'].lower()})"
        ve.append(cg)
    if ht.get("do_am") is not None:
        ve.append(f"độ ẩm {_gon(ht['do_am'])}%")
    if ht.get("gio"):
        ve.append(f"gió {ht['gio']}")
    cau = [f"{dau}: " + ", ".join(v for v in ve if v) + "."]
    if ht.get("uv"):
        cau.append(f"Chỉ số UV {ht['uv']}.")
    if kk.get("muc"):
        cau.append(f"Chất lượng không khí {kk['muc'].lower()}"
                   + (f" (AQI {_gon(kk['aqi'])})" if kk.get("aqi") is not None else "") + ".")
    if mc:
        cau.append(mc.rstrip(".") + ".")
    text = " ".join(cau)
    _cache[key] = (now, text)
    return text
