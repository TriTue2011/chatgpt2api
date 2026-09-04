"""Chỉ đường A→B: link Google Maps + chỉ dẫn chi tiết + khoảng cách.

Hoàn toàn MIỄN PHÍ, không API key:
  * geocode địa chỉ  → Nominatim (OpenStreetMap)
  * định tuyến + bước rẽ → OSRM public (router.project-osrm.org)
  * link mở được → Google Maps URL (deep-link, không cần key)

Đã đo thật 04/09: Nominatim ra đúng "114 Mai Hắc Đế" và "CT4B X2 Bắc Linh Đàm";
OSRM cho 7,3 km / 10 phút / 16 bước rẽ có tên phố tiếng Việt.

GIỚI HẠN: OSRM public chỉ có đồ thị Ô TÔ (nhận mọi profile nhưng route như xe
hơi). Nên chỉ dẫn text chỉ chính xác cho xe máy/ô tô; xe buýt không định tuyến
được (Google Maps lo phần tuyến bus khi người dùng mở link).

Module THUẦN: mọi lỗi thành giá trị trả về, KHÔNG raise — bên gọi (capabilities)
lo dựng câu cho người dùng.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

_UA = "c2a-bot/1.0 (personal assistant; contact via Zalo)"
_NOMINATIM = "https://nominatim.openstreetmap.org/search"
_OSRM = "https://router.project-osrm.org/route/v1"
_TIMEOUT = 15

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


def _giai_link_maps(s: str) -> tuple[float, float] | str | None:
    """Link Google Maps → toạ độ (lat, lon) hoặc chuỗi ĐỊA CHỈ; None nếu không phải link.

    Người dùng hay chỉ vị trí bằng cách CHIA SẺ ghim Google Maps (maps.app.goo.gl).
    Theo redirect tới link đầy đủ rồi lấy `@lat,lng` (chính xác nhất) hoặc tên
    trong `/place/<địa chỉ>`. Đo 05/09: `maps.app.goo.gl/…` → `/place/CT4B-X2 Bắc
    Linh Đàm, …, Hoàng Liệt, Hà Nội`."""
    if not _RE_MAPS_URL.search(s or ""):
        return None
    from urllib.parse import unquote_plus
    try:
        r = requests.get(s.strip(), headers={"User-Agent": "Mozilla/5.0"},
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


def _nominatim_1(q: str) -> tuple[float, float, str, str] | None:
    """Một lượt Nominatim → (lat, lon, tên, TỈNH) hoặc None.

    `addressdetails=1` để lấy TỈNH/THÀNH: dùng đối chiếu hai đầu tuyến. "Mai Hắc
    Đế" có ở CẢ Hà Nội lẫn Đà Nẵng — đo 04/09: thiếu thành phố thì Nominatim
    chọn Đà Nẵng rồi ra 766 km."""
    try:
        r = requests.get(
            _NOMINATIM,
            params={"q": q, "format": "json", "limit": 1, "addressdetails": 1},
            headers={"User-Agent": _UA}, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning("chi_duong.geocode(%.40s) lỗi: %s", q, exc)
        return None
    if not isinstance(data, list) or not data:
        return None
    top = data[0]
    ad = top.get("address") or {}
    tinh = str(ad.get("city") or ad.get("state") or ad.get("province") or "").strip()
    try:
        return float(top["lat"]), float(top["lon"]), str(top.get("display_name") or q), tinh
    except (KeyError, TypeError, ValueError):
        return None


def geocode(dia_chi: str, tinh_goi_y: str = "") -> tuple[float, float, str, str, bool] | None:
    """Địa chỉ → (lat, lon, tên, tỉnh, chính_xác) qua Nominatim; None nếu không thấy.

    ``tinh_goi_y``: tỉnh/thành của ĐẦU KIA để bù khi câu thiếu thành phố — "114
    Mai Hắc Đế" một mình lạc sang Đà Nẵng, thêm ", Hà Nội" (tỉnh của điểm đến)
    thì ra đúng. Chỉ thêm khi câu chưa nhắc tỉnh đó.

    ``chính_xác`` = khớp NGUYÊN VĂN (True); phải BỎ MÃ TOÀ mới ra (False, vị trí
    gần đúng ở mức khu đô thị/phố). Bên gọi dùng để nói rõ độ chính xác.
    Tối đa 2 lượt gọi để tôn trọng giới hạn 1 req/giây của Nominatim."""
    dc = str(dia_chi or "").strip()
    if not dc:
        return None
    # Link Google Maps (ghim chia sẻ) → toạ độ chính xác, hoặc địa chỉ để tra.
    giai = _giai_link_maps(dc)
    if isinstance(giai, tuple):
        return giai[0], giai[1], "Vị trí đã ghim trên Google Maps", "", True
    if isinstance(giai, str) and giai:
        dc = giai
    fdc = _bo_dau(dc)
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
    if a[3] and b[3] and _bo_dau(a[3]) != _bo_dau(b[3]):
        return a, b, "tinh_khong_khop"
    return a, b, None


def dinh_vi(diem_di: str, diem_den: str, phuong_tien: str = "xe máy") -> dict:
    """Chỉ GEOCODE (không định tuyến) — cho bước XÁC NHẬN địa chỉ.

    ``ok=True`` → {tu, den, gan_dung, link}  (tên địa chỉ bot hiểu được, để hỏi
    người dùng đúng chưa trước khi chỉ đường). ``ok=False`` → {ly_do, link,
    [tinh_di, tinh_den]} như `chi_duong`."""
    profile, travelmode, co_route = chuan_phuong_tien(phuong_tien)
    link = maps_link(diem_di, diem_den, travelmode)
    goc = {"link": link, "phuong_tien": phuong_tien}
    # Xe buýt không định tuyến (chỉ link) → khỏi bước xác nhận địa chỉ.
    if not co_route or not profile:
        return {"ok": False, "ly_do": "khong_dinh_tuyen", **goc}
    a, b, ly = _dinh_vi_hai_dau(diem_di, diem_den)
    if ly == "tinh_khong_khop":
        return {"ok": False, "ly_do": ly, "tinh_di": a[3], "tinh_den": b[3], **goc}
    if ly:
        return {"ok": False, "ly_do": ly, **goc}
    return {"ok": True, "tu": a[2], "den": b[2],
            "gan_dung": not (a[4] and b[4]), **goc}


def chi_duong(diem_di: str, diem_den: str, phuong_tien: str = "xe máy") -> dict:
    """A→B → dict chỉ đường. KHÔNG raise; mọi lỗi thành `ok=False` + `ly_do`.

    ``ok=True``  → {km, phut, buoc:[str], link, tu, den, phuong_tien, gan_dung}
    ``ok=False`` → {ly_do, link, phuong_tien, [tinh_di, tinh_den]}
        ly_do: khong_dinh_tuyen | khong_ra_diem_di | khong_ra_diem_den |
               tinh_khong_khop (hai đầu ở tỉnh khác nhau — hỏi lại địa chỉ)
    """
    profile, travelmode, co_route = chuan_phuong_tien(phuong_tien)
    link = maps_link(diem_di, diem_den, travelmode)
    goc = {"link": link, "phuong_tien": phuong_tien}

    # Xe buýt: OSRM không làm transit → chỉ trả link, Google Maps lo tuyến bus.
    if not co_route or not profile:
        return {"ok": False, "ly_do": "khong_dinh_tuyen", **goc}

    a, b, ly = _dinh_vi_hai_dau(diem_di, diem_den)
    if ly == "tinh_khong_khop":
        return {"ok": False, "ly_do": ly, "tinh_di": a[3], "tinh_den": b[3], **goc}
    if ly:
        return {"ok": False, "ly_do": ly, **goc}

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
        return {"ok": False, "ly_do": "khong_dinh_tuyen", **goc}

    if data.get("code") != "Ok" or not data.get("routes"):
        return {"ok": False, "ly_do": "khong_dinh_tuyen", **goc}

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
