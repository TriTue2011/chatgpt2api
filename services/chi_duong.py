"""Chỉ đường A→B: link Google Maps + chỉ dẫn chi tiết + khoảng cách.

Hoàn toàn MIỄN PHÍ, không API key:
  * geocode địa chỉ  → BÓC TỪ WEB GOOGLE MAPS (endpoint tìm kiếm nội bộ, đúng
    toạ độ như Google), fallback Nominatim (OpenStreetMap) nếu Google đổi format
  * định tuyến + bước rẽ → OSRM public (router.project-osrm.org)
  * link mở được → Google Maps URL dựng từ TOẠ ĐỘ (deep-link, không cần key)

Vì sao bóc endpoint nội bộ chứ không bóc HTML: đo 05/09 thấy `/maps/search/` là
trang SPA — HTML ban đầu chỉ có TÂM KHUNG NHÌN, lệch ~5 km so với ghim thật. Còn
`GET google.com/search?tbm=map&pb=…` (qua curl_cffi giả lập Chrome, đúng kỹ thuật
accuweather) trả JSON có ghim CHUẨN: "114 Mai Hắc Đế, Hà Nội" → 21.0103763,
105.8507264. OSRM cho 7,x km / bước rẽ có tên phố tiếng Việt.

GIỚI HẠN: OSRM public chỉ có đồ thị Ô TÔ (nhận mọi profile nhưng route như xe
hơi). Nên chỉ dẫn text chỉ chính xác cho xe máy/ô tô; xe buýt không định tuyến
được (Google Maps lo phần tuyến bus khi người dùng mở link).

Module THUẦN: mọi lỗi thành giá trị trả về, KHÔNG raise — bên gọi (capabilities)
lo dựng câu cho người dùng.
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import parse_qs, quote, urlencode, urlparse

import requests

logger = logging.getLogger(__name__)

_UA = "c2a-bot/1.0 (personal assistant; contact via Zalo)"
_NOMINATIM = "https://nominatim.openstreetmap.org/search"
_OSRM = "https://router.project-osrm.org/route/v1"
_TIMEOUT = 15

#: Endpoint TÌM KIẾM nội bộ của Google Maps (SPA gọi qua XHR). Trả text mở đầu
#: ")]}'" rồi JSON. `pb` là tham số dạng protobuf-text; `!2d105.85!3d21.02` là
#: tâm bản đồ (thiên về Hà Nội — câu khác tỉnh cần kèm tên tỉnh, đã lo ở
#: `tinh_goi_y`). Đo 05/09: template này ra đúng ghim; nếu Google đổi, geocode tự
#: tụt xuống Nominatim nên không mất tính năng.
_GMAPS_SEARCH = "https://www.google.com/search"
_PB_TMPL = (
    "!4m12!1m3!1d10000!2d105.85!3d21.02!2m3!1f0!2f0!3f0!3m2!1i1024!2i768"
    "!4f13.1!7i20!10b1!12m6!2m3!5m1!6e2!20e3!10b1!16b1!19m3!2m2!1i392!2i106!20m48"
)

#: Tên phương tiện tiếng Việt (đã hạ chữ thường, bỏ dấu để so linh hoạt ở
#: `chuan_phuong_tien`) → (osrm_profile | "", gmaps_travelmode, có_route_text).
_PHUONG_TIEN = {
    "xe may": ("driving", "driving", True),
    "o to": ("driving", "driving", True),
    "oto": ("driving", "driving", True),
    "di bo": ("walking", "walking", True),
    "xe dap": ("cycling", "bicycling", True),
    "xe buyt": ("", "transit", False),
    "bus": ("", "transit", False),
}

#: Các phương tiện chào ra menu (thứ tự hiển thị). Xe đạp bỏ khỏi menu cho gọn
#: bốn lựa chọn phổ biến, nhưng vẫn nhận nếu người dùng tự gõ.
MENU_PHUONG_TIEN = ["xe máy", "ô tô", "đi bộ", "xe buýt"]

_MANEUVER_VI = {
    "turn": "Rẽ", "new name": "Đi tiếp vào", "depart": "Xuất phát trên",
    "arrive": "Tới nơi", "merge": "Nhập vào", "on ramp": "Lên đường nhánh",
    "off ramp": "Xuống đường nhánh", "fork": "Rẽ nhánh", "end of road": "Cuối đường rẽ vào",
    "continue": "Đi thẳng theo", "roundabout": "Vào vòng xuyến", "rotary": "Vào vòng xuyến",
    "roundabout turn": "Ở vòng xuyến rẽ vào", "notification": "Tiếp tục trên",
}
_MODIFIER_VI = {
    "left": "trái", "right": "phải", "straight": "thẳng",
    "slight left": "chếch trái", "slight right": "chếch phải",
    "sharp left": "gấp trái", "sharp right": "gấp phải", "uturn": "quay đầu",
}


def _bo_dau(s: str) -> str:
    b = "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    k = "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd"
    return (s or "").lower().translate(str.maketrans(b, k))


#: Tiền tố đơn vị TỈNH/THÀNH ở đoạn cuối địa chỉ.
_TIEN_TO_TINH = ("thanh pho ", "tinh ", "tp ", "tp.", "t.p ", "t.p.")


def _bo_tinh_tp(q: str) -> str:
    """Bỏ đoạn TỈNH/THÀNH khỏi truy vấn Google (giữ quận/phường/landmark).

    Đo 05/09: thêm ", thành phố Hà Nội" làm Google trả SAI ghim — "CT4B-X2 Bắc
    Linh Đàm, …, thành phố Hà Nội" nhảy về ~Ba Đình (21.028) thay vì Linh Đàm
    (20.965). `gl=vn` + tâm bản đồ đã ngầm là Hà Nội nên đoạn tỉnh/thành thừa mà
    lại gây hại; bỏ đi thì landmark ra đúng."""
    segs = [s.strip() for s in str(q or "").split(",")]
    giu = [s for s in segs
           if s and not any(_bo_dau(s).startswith(p) for p in _TIEN_TO_TINH)]
    return ", ".join(giu) if giu else str(q or "")


def _tinh_ngan(s: str) -> str:
    """"Thành phố Hà Nội" → "Hà Nội" (giữ dấu, bỏ tiền tố đơn vị) — để bù tỉnh
    liên đầu mà KHÔNG bị `_bo_tinh_tp` cắt mất."""
    s = str(s or "").strip()
    fl = _bo_dau(s)
    for pre in ("thanh pho ", "tinh ", "tp ", "tp."):
        if fl.startswith(pre):
            return s[len(pre):].strip()
    return s


def chuan_phuong_tien(pt: str) -> tuple[str, str, bool]:
    """Tên phương tiện tự do → (osrm_profile, gmaps_travelmode, có_route_text).

    Không nhận ra → mặc định xe máy (phổ biến nhất ở VN)."""
    key = " ".join(_bo_dau(pt).split())
    return _PHUONG_TIEN.get(key, _PHUONG_TIEN["xe may"])


def maps_link(diem_di: str, diem_den: str, travelmode: str = "driving") -> str:
    """URL Google Maps mở sẵn tuyến đường — KHÔNG cần API key (Maps URLs)."""
    q = urlencode({
        "api": 1,
        "origin": diem_di,
        "destination": diem_den,
        "travelmode": travelmode,
    })
    return f"https://www.google.com/maps/dir/?{q}"


def maps_search_link(lat: float, lon: float) -> str:
    """URL ghim một điểm, dùng làm lựa chọn không mơ hồ giữa các kết quả tìm.

    Không nhét địa chỉ chữ vào menu rồi tìm lại ở lượt sau: một tên phố có thể
    xuất hiện ở nhiều tỉnh và Google/Nominatim có thể đổi thứ hạng. URL chuẩn
    Maps URLs với ``query=lat,lon`` giữ nguyên chính xác ghim người dùng bấm.
    """
    def _toa(v: float) -> str:
        return f"{float(v):.7f}".rstrip("0").rstrip(".")

    q = urlencode({"api": 1, "query": f"{_toa(lat)},{_toa(lon)}"})
    return f"https://www.google.com/maps/search/?{q}"


#: Chữ ĐỆM đứng trước mã toà/số nhà, bỏ khi tra khái quát (viết KHÔNG dấu).
_DEM_DAU = {"toa", "nha", "so", "can", "ho", "phong", "chung", "cu", "khu"}


def _bo_ma_toa(dc: str) -> str:
    """Bỏ mã toà nhà + chữ đệm đứng ĐẦU địa chỉ, GIỮ dấu phẩy còn lại.

    Nominatim thường thiếu từng toà nhưng CÓ khu đô thị/phố, và nó KÉN dấu phẩy:
    "phường Hoàng Liệt, Hà Nội" ra được còn bản gộp không phẩy thì không. Đo
    04/09: "CT4B X2 Bắc Linh Đàm" ra đúng toà; bỏ "CT4B X2" → "Bắc Linh Đàm" vẫn
    ra. Bỏ cả chữ đệm "tòa nhà"/"số"/"căn hộ" — "tòa nhà CT4Bx2 Bắc Linh Đàm" mà
    không bỏ thì Nominatim trượt. Mã toà = token vừa có CHỮ vừa có SỐ."""
    def bo_qua(t: str) -> bool:
        f = _bo_dau(t)
        la_ma = any(c.isdigit() for c in t) and any(c.isalpha() for c in t)
        return f in _DEM_DAU or la_ma

    segs = [s.strip() for s in dc.split(",") if s.strip()]
    if not segs:
        return ""
    toks = segs[0].split()
    i = 0
    while i < len(toks) and bo_qua(toks[i]):
        i += 1
    segs[0] = " ".join(toks[i:]).strip()
    return ", ".join(s for s in segs if s)


#: URL Google Maps (link chia sẻ rút gọn hoặc link đầy đủ).
_RE_MAPS_URL = re.compile(
    r"https?://(maps\.app\.goo\.gl|(www\.)?google\.[a-z.]+/maps|goo\.gl/maps)/", re.I)
_RE_TOA_DO_MAPS = re.compile(
    r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*")


def _toa_do_tu_url_maps(raw: str) -> tuple[float, float] | None:
    """Lấy tọa độ từ URL Maps canonical, không gọi mạng."""
    try:
        parsed = urlparse(raw)
        queries = parse_qs(parsed.query)
        for value in queries.get("query") or queries.get("q") or []:
            m = _RE_TOA_DO_MAPS.fullmatch(value)
            if m:
                return float(m.group(1)), float(m.group(2))
        m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", raw)
        if m:
            return float(m.group(1)), float(m.group(2))
    except (TypeError, ValueError):
        pass
    return None


def _truy_van_tu_link_maps(raw: str) -> str:
    """URL `/maps/search/?query=<chữ>` → chữ cần tìm, không coi là ghim."""
    try:
        parsed = urlparse(raw)
        if "/maps/search" not in parsed.path.lower():
            return raw
        queries = parse_qs(parsed.query)
        for value in queries.get("query") or queries.get("q") or []:
            if value.strip() and not _RE_TOA_DO_MAPS.fullmatch(value):
                return value.strip()
    except (TypeError, ValueError):
        pass
    return raw


def _giai_link_maps(s: str) -> tuple[float, float] | str | None:
    """Link Google Maps → toạ độ (lat, lon) hoặc chuỗi ĐỊA CHỈ; None nếu không phải link.

    Người dùng hay chỉ vị trí bằng cách CHIA SẺ ghim Google Maps (maps.app.goo.gl).
    Theo redirect tới link đầy đủ rồi lấy `@lat,lng` (chính xác nhất) hoặc tên
    trong `/place/<địa chỉ>`. Đo 05/09: `maps.app.goo.gl/…` → `/place/CT4B-X2 Bắc
    Linh Đàm, …, Hoàng Liệt, Hà Nội`."""
    raw = str(s or "").strip()
    if not _RE_MAPS_URL.search(raw):
        return None
    # Menu lựa chọn dùng URL này. Đọc ngay từ query, không gọi mạng và không để
    # redirect/thứ hạng Google thay đổi ghim mà người dùng vừa chọn.
    toa_do = _toa_do_tu_url_maps(raw)
    if toa_do:
        return toa_do
    from urllib.parse import unquote_plus
    try:
        r = requests.get(raw, headers={"User-Agent": "Mozilla/5.0"},
                         timeout=_TIMEOUT, allow_redirects=True)
        url = r.url
    except Exception as exc:
        logger.warning("chi_duong: giải link maps lỗi: %s", exc)
        return None
    m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r"/place/([^/@?]+)", url)
    if m:
        return unquote_plus(m.group(1)).strip()
    return None


def la_ghim_maps(dia_chi: str) -> bool:
    """Có phải một ghim Maps do người dùng đã chỉ rõ hay không.

    Link chia sẻ ngắn / `place` và URL có tọa độ là một vị trí người dùng đã
    chọn. URL ``/maps/search/?query=<chữ>`` chỉ là truy vấn mơ hồ, vẫn phải ra
    menu; nếu không nó lại lách yêu cầu không tự chọn top-1.
    """
    raw = str(dia_chi or "").strip()
    if not _RE_MAPS_URL.search(raw):
        return False
    if _toa_do_tu_url_maps(raw):
        return True
    try:
        parsed = urlparse(raw)
        host = parsed.netloc.lower()
        path = parsed.path.lower()
        return host in {"maps.app.goo.gl", "goo.gl"} or "/maps/place/" in path
    except (TypeError, ValueError):
        return False


def _nominatim_1(q: str) -> tuple[float, float, str, str] | None:
    """Một lượt Nominatim → (lat, lon, tên, TỈNH) hoặc None.

    `addressdetails=1` để lấy TỈNH/THÀNH: dùng đối chiếu hai đầu tuyến. "Mai Hắc
    Đế" có ở CẢ Hà Nội lẫn Đà Nẵng — đo 04/09: thiếu thành phố thì Nominatim
    chọn Đà Nẵng rồi ra 766 km."""
    out = _nominatim_nhieu(q, so=1)
    return out[0] if out else None


def _nominatim_nhieu(q: str, so: int = 8) -> list[tuple[float, float, str, str]]:
    """Các kết quả Nominatim, chỉ làm đường lùi khi Google không đủ lựa chọn."""
    try:
        r = requests.get(
            _NOMINATIM,
            params={"q": q, "format": "json", "limit": max(1, min(int(so), 8)),
                    "addressdetails": 1},
            headers={"User-Agent": _UA}, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning("chi_duong.tim_dia_diem(%.40s) Nominatim lỗi: %s", q, exc)
        return []
    out: list[tuple[float, float, str, str]] = []
    for item in data if isinstance(data, list) else []:
        try:
            ad = item.get("address") or {}
            out.append((
                float(item["lat"]), float(item["lon"]),
                str(item.get("display_name") or q),
                str(ad.get("city") or ad.get("state") or ad.get("province") or "").strip(),
            ))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return out


def _duyet_toa_do(x, out: list[tuple[float, float]]) -> None:
    """Duyệt cây JSON tìm mọi [None, None, lat, lng] nằm trong khung VN.

    Dự phòng khi cấu trúc kết quả đầu rỗng nhánh (đo 05/09: "CT4B X2 Bắc Linh
    Đàm" ra body ngắn, `[0][1][0][14]` rỗng nhưng ghim vẫn nằm rải trong cây)."""
    if isinstance(x, list):
        if (len(x) >= 4 and x[0] is None and x[1] is None
                and isinstance(x[2], (int, float)) and isinstance(x[3], (int, float))
                and 8 < x[2] < 24 and 102 < x[3] < 110):
            out.append((round(float(x[2]), 7), round(float(x[3]), 7)))
        for it in x:
            _duyet_toa_do(it, out)


def _boc_pb(data) -> tuple[float, float, str, str] | None:
    """JSON endpoint Google Maps → (lat, lon, địa_chỉ_đầy_đủ, tỉnh) hoặc None.

    Kết quả đầu ở `data[0][1][0][14]`: `[9]`=[_,_,lat,lng] (ghim chuẩn), `[18]`=
    địa chỉ đầy đủ, `[2]`=các dòng địa chỉ (tỉnh là phần trước "Việt Nam")."""
    try:
        r0 = data[0][1][0][14]
    except (IndexError, TypeError, KeyError):
        r0 = None
    lat = lon = None
    ten = tinh = ""
    if isinstance(r0, list):
        try:
            g = r0[9]
            if isinstance(g, list) and len(g) >= 4:
                lat, lon = float(g[2]), float(g[3])
        except (IndexError, TypeError, ValueError):
            pass
        try:
            ten = str(r0[18] or "").strip()
        except (IndexError, TypeError):
            pass
        try:
            xs = [str(c).strip() for c in r0[2] if str(c).strip()]
            if xs and _bo_dau(xs[-1]) in ("viet nam", "vietnam"):
                xs = xs[:-1]
            if xs:
                tinh = xs[-1]
        except (IndexError, TypeError):
            pass
    if lat is None:
        found: list[tuple[float, float]] = []
        _duyet_toa_do(data, found)
        if found:
            lat, lon = found[0]
    if lat is None or lon is None:
        return None
    return lat, lon, ten, tinh


def _boc_pb_nhieu(data) -> list[tuple[float, float, str, str]]:
    """Bóc mọi hàng kết quả Maps mà format hiện tại công khai được.

    Google đặt kết quả tại ``data[0][1][i][14]``; `_boc_pb` vẫn giữ lại để
    tương thích đường geocode cũ (một kết quả + fallback quét cây JSON).
    """
    out: list[tuple[float, float, str, str]] = []
    try:
        rows = data[0][1]
    except (IndexError, TypeError, KeyError):
        rows = []
    for row in rows if isinstance(rows, list) else []:
        # Tái dùng parser cũ cho từng hàng, gồm cả đường lùi quét toạ độ.
        one = _boc_pb([[None, [row]]])
        if one and not any(abs(one[0] - x[0]) < 1e-7 and abs(one[1] - x[1]) < 1e-7
                           for x in out):
            out.append(one)
    if out:
        return out
    one = _boc_pb(data)
    return [one] if one else []


def _doc_gmaps_pb(q: str):
    """Gọi endpoint Maps một lần; parser một/nhiều kết quả dùng chung body này."""
    try:
        from curl_cffi import requests as creq
        url = f"{_GMAPS_SEARCH}?tbm=map&hl=vi&gl=vn&q={quote(_bo_tinh_tp(q))}&pb={_PB_TMPL}"
        body = creq.get(url, impersonate="chrome", timeout=_TIMEOUT,
                        headers={"Accept-Language": "vi,en;q=0.9"}).text
        nl = body.find("\n")
        return json.loads(body[nl + 1:] if nl != -1 else body.lstrip(")]}'"))
    except Exception as exc:
        logger.warning("chi_duong.gmaps_pb(%.40s) lỗi: %s", q, exc)
        return None


def _gmaps_pb(q: str) -> tuple[float, float, str, str] | None:
    """Địa chỉ → (lat, lon, địa_chỉ_đầy_đủ, tỉnh) BÓC TỪ WEB Google Maps.

    Giống nếp accuweather: curl_cffi giả lập Chrome để qua chặn bot, đọc JSON
    nhúng (mở đầu ")]}'"). None nếu không ra/hỏng/format lạ — bên gọi tụt xuống
    Nominatim."""
    data = _doc_gmaps_pb(q)
    if data is None:
        return None
    return _boc_pb(data)


def _gmaps_pb_nhieu(q: str) -> list[tuple[float, float, str, str]]:
    """Danh sách kết quả Google Maps; hỏng thì list rỗng để gọi Nominatim."""
    data = _doc_gmaps_pb(q)
    return _boc_pb_nhieu(data) if data is not None else []


def tim_dia_diem(dia_chi: str, so: int = 8) -> list[dict[str, object]]:
    """Tìm tối đa tám ghim để người dùng chọn, tuyệt đối không tự lấy top-1.

    Kết quả có URL Maps ghim toạ độ: handler đưa URL đó vào lựa chọn, nên sau
    khi bấm chỉ đường dùng đúng tọa độ người dùng chọn thay vì search tên lần nữa.
    """
    dc = _truy_van_tu_link_maps(str(dia_chi or "").strip())
    if not dc:
        return []
    limit = max(1, min(int(so), 8))
    raw = _gmaps_pb_nhieu(dc)
    if len(raw) < limit:
        raw += _nominatim_nhieu(f"{dc}, Việt Nam", so=limit)
    out: list[dict[str, object]] = []
    for lat, lon, ten, tinh in raw:
        if any(abs(float(lat) - float(x["lat"])) < 1e-7 and
               abs(float(lon) - float(x["lon"])) < 1e-7 for x in out):
            continue
        out.append({
            "lat": float(lat), "lon": float(lon),
            "ten": str(ten or dc).strip(), "tinh": str(tinh or "").strip(),
            "link": maps_search_link(float(lat), float(lon)),
        })
        if len(out) >= limit:
            break
    return out


def geocode(dia_chi: str, tinh_goi_y: str = "") -> tuple[float, float, str, str, bool] | None:
    """Địa chỉ → (lat, lon, tên, tỉnh, chính_xác); None nếu không thấy.

    Đường CHÍNH: bóc endpoint Google Maps (`_gmaps_pb`) — đúng ghim như Google.
    Fallback: Nominatim (giữ logic bỏ mã toà + hậu tố tỉnh cũ) khi Google rỗng.

    ``tinh_goi_y``: tỉnh/thành của ĐẦU KIA để bù khi câu thiếu thành phố — "114
    Mai Hắc Đế" một mình có thể lạc tỉnh, thêm ", Hà Nội" (tỉnh của điểm đến) thì
    ra đúng. Chỉ thêm khi câu chưa nhắc tỉnh đó.

    ``chính_xác`` = True khi ra ghim thẳng (Google, hoặc Nominatim khớp nguyên
    văn); False khi phải BỎ MÃ TOÀ mới ra (Nominatim, gần đúng ở mức khu/phố)."""
    dc = str(dia_chi or "").strip()
    if not dc:
        return None
    # Link Google Maps (ghim chia sẻ) → toạ độ chính xác, hoặc TÊN để tra tiếp.
    giai = _giai_link_maps(dc)
    if isinstance(giai, tuple):
        return giai[0], giai[1], "Vị trí đã ghim trên Google Maps", "", True
    if isinstance(giai, str) and giai:
        dc = giai
    fdc = _bo_dau(dc)
    # Kèm tỉnh gợi ý (dạng NGẮN, không tiền tố) nếu câu chưa nhắc — để bù tỉnh
    # liên đầu mà không bị `_bo_tinh_tp` cắt mất ở đường Google.
    _tg = _tinh_ngan(tinh_goi_y)
    q_full = dc if (not _tg or _bo_dau(_tg) in fdc) else f"{dc}, {_tg}"

    # (1) Đường chính — Google Maps nội bộ.
    pb = _gmaps_pb(q_full)
    if pb:
        lat, lon, ten, tinh = pb
        return lat, lon, (ten or dc), tinh, True

    # (2) Fallback — Nominatim, tối đa 2 lượt (tôn trọng 1 req/giây).
    hau_to = "" if ("viet nam" in fdc or "vietnam" in fdc) else ", Việt Nam"
    if tinh_goi_y and _bo_dau(tinh_goi_y) not in fdc:
        hau_to = f", {tinh_goi_y}" + hau_to
    bien_the: list[tuple[str, bool]] = [(dc, True)]
    ngan = _bo_ma_toa(dc)
    if ngan and ngan != dc and len(ngan.split()) >= 2:
        bien_the.append((ngan, False))
    for q, chinh_xac in bien_the:
        kq = _nominatim_1(q + hau_to)
        if kq:
            return (*kq, chinh_xac)
    return None


#: Chỉ các bước RẼ thật mới gắn hướng (trái/phải); depart/arrive/new name…
#: gắn hướng vào đọc ngược ("Xuất phát trên phải").
_CO_HUONG = {"turn", "end of road", "fork", "roundabout turn", "on ramp", "off ramp"}


def _mo_ta_buoc(step: dict) -> str:
    """Một bước OSRM → câu chỉ dẫn tiếng Việt ngắn."""
    m = step.get("maneuver") or {}
    loai = str(m.get("type") or "")
    kieu = _MANEUVER_VI.get(loai, "Đi tiếp")
    huong = _MODIFIER_VI.get(str(m.get("modifier") or ""), "") if loai in _CO_HUONG else ""
    ten = str(step.get("name") or "").strip()
    met = step.get("distance") or 0
    phan = kieu + (f" {huong}" if huong else "")
    if ten:
        phan += f" {ten}"
    if met and met >= 1:
        phan += f" (~{int(met)} m)" if met < 1000 else f" (~{met/1000:.1f} km)"
    return phan


def _chuan_tinh(s: str) -> str:
    """Chuẩn hoá tên tỉnh/thành để so khớp: bỏ dấu + bỏ tiền tố loại đơn vị.

    Google trả lúc "Hà Nội", lúc "Thành phố Hà Nội" cho CÙNG một nơi — so trần
    là báo khác tỉnh oan (đo 05/09: Hoàng Thành ↔ CT4B Bắc Linh Đàm đều Hà Nội mà
    bị chặn 'tinh_khong_khop')."""
    f = _bo_dau(s).strip()
    for pre in ("thanh pho ", "tinh ", "tp. ", "tp.", "tp ", "t.p ", "t."):
        if f.startswith(pre):
            f = f[len(pre):].strip()
            break
    return f


def _dinh_vi_hai_dau(diem_di: str, diem_den: str):
    """Geocode hai đầu (bù tỉnh liên đầu) → (a, b, ly_do).

    ``ly_do`` None nếu ổn; ngược lại "khong_ra_diem_den"/"khong_ra_diem_di"/
    "tinh_khong_khop". Dùng chung cho `dinh_vi` (bước xác nhận) và `chi_duong`
    (định tuyến) — một chỗ, khỏi lệch logic."""
    # Điểm ĐẾN trước (landmark rõ), lấy tỉnh nó bù cho điểm đi — chữa "114 Mai
    # Hắc Đế" một mình lạc sang Đà Nẵng (766 km).
    b = geocode(diem_den)
    if not b:
        return None, None, "khong_ra_diem_den"
    a = geocode(diem_di, tinh_goi_y=b[3])
    if not a:
        return None, None, "khong_ra_diem_di"
    if a[3] and b[3] and _chuan_tinh(a[3]) != _chuan_tinh(b[3]):
        return a, b, "tinh_khong_khop"
    return a, b, None


def _link_tu(a, b, diem_di: str, diem_den: str, travelmode: str) -> str:
    """Deep-link Google Maps ưu tiên TOẠ ĐỘ đã geocode (mở chỉ đường chắc chắn).

    Người dùng dán short-link hoặc địa chỉ mơ hồ làm origin/destination dạng chữ
    thì Google hay không dựng nổi tuyến (lỗi "bấm vào không ra chỉ đường"). Có
    toạ độ thì `origin=lat,lng` luôn mở đúng; thiếu (geocode trượt) mới dùng chữ."""
    origin = f"{a[0]},{a[1]}" if a else diem_di
    dest = f"{b[0]},{b[1]}" if b else diem_den
    return maps_link(origin, dest, travelmode)


def dinh_vi(diem_di: str, diem_den: str, phuong_tien: str = "xe máy") -> dict:
    """Chỉ GEOCODE (không định tuyến) — cho bước XÁC NHẬN địa chỉ.

    ``ok=True`` → {tu, den, gan_dung, link}  (tên địa chỉ bot hiểu được, để hỏi
    người dùng đúng chưa trước khi chỉ đường). ``ok=False`` → {ly_do, link,
    [tinh_di, tinh_den]} như `chi_duong`."""
    profile, travelmode, co_route = chuan_phuong_tien(phuong_tien)
    goc = {"phuong_tien": phuong_tien}
    # Xe buýt không định tuyến → vẫn geocode để link mở đúng, khỏi bước xác nhận.
    if not co_route or not profile:
        a, b, _ = _dinh_vi_hai_dau(diem_di, diem_den)
        return {"ok": False, "ly_do": "khong_dinh_tuyen",
                "link": _link_tu(a, b, diem_di, diem_den, travelmode), **goc}
    a, b, ly = _dinh_vi_hai_dau(diem_di, diem_den)
    link = _link_tu(a, b, diem_di, diem_den, travelmode)
    if ly == "tinh_khong_khop":
        return {"ok": False, "ly_do": ly, "tinh_di": a[3], "tinh_den": b[3],
                "link": link, **goc}
    if ly:
        return {"ok": False, "ly_do": ly, "link": link, **goc}
    return {"ok": True, "tu": a[2], "den": b[2],
            "gan_dung": not (a[4] and b[4]), "link": link, **goc}


def chi_duong(diem_di: str, diem_den: str, phuong_tien: str = "xe máy") -> dict:
    """A→B → dict chỉ đường. KHÔNG raise; mọi lỗi thành `ok=False` + `ly_do`.

    ``ok=True``  → {km, phut, buoc:[str], link, tu, den, phuong_tien, gan_dung}
    ``ok=False`` → {ly_do, link, phuong_tien, [tinh_di, tinh_den]}
        ly_do: khong_dinh_tuyen | khong_ra_diem_di | khong_ra_diem_den |
               tinh_khong_khop (hai đầu ở tỉnh khác nhau — hỏi lại địa chỉ)
    """
    profile, travelmode, co_route = chuan_phuong_tien(phuong_tien)
    goc = {"phuong_tien": phuong_tien}

    # Xe buýt: OSRM không làm transit → chỉ trả link (dựng từ toạ độ để mở đúng),
    # Google Maps lo tuyến bus.
    if not co_route or not profile:
        a, b, _ = _dinh_vi_hai_dau(diem_di, diem_den)
        return {"ok": False, "ly_do": "khong_dinh_tuyen",
                "link": _link_tu(a, b, diem_di, diem_den, travelmode), **goc}

    a, b, ly = _dinh_vi_hai_dau(diem_di, diem_den)
    link = _link_tu(a, b, diem_di, diem_den, travelmode)
    if ly == "tinh_khong_khop":
        return {"ok": False, "ly_do": ly, "tinh_di": a[3], "tinh_den": b[3],
                "link": link, **goc}
    if ly:
        return {"ok": False, "ly_do": ly, "link": link, **goc}

    # OSRM: kinh độ,vĩ độ;kinh độ,vĩ độ  (LƯU Ý thứ tự lon,lat).
    toa_do = f"{a[1]},{a[0]};{b[1]},{b[0]}"
    try:
        r = requests.get(
            f"{_OSRM}/{profile}/{toa_do}",
            params={"overview": "false", "steps": "true"},
            headers={"User-Agent": _UA}, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning("chi_duong.osrm lỗi: %s", exc)
        return {"ok": False, "ly_do": "khong_dinh_tuyen", "link": link, **goc}

    if data.get("code") != "Ok" or not data.get("routes"):
        return {"ok": False, "ly_do": "khong_dinh_tuyen", "link": link, **goc}

    route = data["routes"][0]
    steps = (route.get("legs") or [{}])[0].get("steps") or []
    buoc = [_mo_ta_buoc(s) for s in steps if s.get("maneuver")]
    return {
        "ok": True,
        "km": round(route.get("distance", 0) / 1000, 1),
        "phut": max(1, round(route.get("duration", 0) / 60)),
        "buoc": buoc,
        "link": link,
        "tu": a[2],
        "den": b[2],
        # Một trong hai đầu chỉ ra được ở mức khu đô thị/phố (bỏ mã toà) → km là
        # GẦN ĐÚNG; bên gọi nói rõ để người dùng biết mà tin có mức độ.
        "gan_dung": not (a[4] and b[4]),
        "phuong_tien": phuong_tien,
    }
