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


def _bo_ma_toa(dc: str) -> str:
    """Bỏ mã toà nhà đứng ĐẦU địa chỉ (CT4B X2, N01, R6…), GIỮ dấu phẩy còn lại.

    Nominatim thường thiếu từng toà nhưng CÓ khu đô thị/phố, và nó KÉN dấu phẩy:
    "phường Hoàng Liệt, Hà Nội" ra được còn bản gộp không phẩy thì không. Đo
    04/09: "CT4B X2 Bắc Linh Đàm" ra đúng toà; bỏ mã toà "CT4B X2" → "Bắc Linh
    Đàm" vẫn ra khu đô thị. Mã toà = token vừa có CHỮ vừa có SỐ (CT4B, X2, N01)."""
    def la_ma(t: str) -> bool:
        return any(c.isdigit() for c in t) and any(c.isalpha() for c in t)

    segs = [s.strip() for s in dc.split(",") if s.strip()]
    if not segs:
        return ""
    toks = segs[0].split()
    i = 0
    while i < len(toks) and la_ma(toks[i]):
        i += 1
    segs[0] = " ".join(toks[i:]).strip()
    return ", ".join(s for s in segs if s)


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

    # Geocode ĐIỂM ĐẾN trước (thường là landmark rõ), lấy TỈNH của nó làm gợi ý
    # cho điểm đi — chữa lỗi "114 Mai Hắc Đế" một mình lạc sang Đà Nẵng (766 km).
    b = geocode(diem_den)
    if not b:
        return {"ok": False, "ly_do": "khong_ra_diem_den", **goc}
    a = geocode(diem_di, tinh_goi_y=b[3])
    if not a:
        return {"ok": False, "ly_do": "khong_ra_diem_di", **goc}

    # Hai đầu vẫn KHÁC TỈNH sau khi đã bù → không chắc chắn, HỎI LẠI thay vì đưa
    # tuyến sai (đúng yêu cầu chủ máy 04/09: "sai km, không hỏi địa chỉ chính xác").
    if a[3] and b[3] and _bo_dau(a[3]) != _bo_dau(b[3]):
        return {"ok": False, "ly_do": "tinh_khong_khop",
                "tinh_di": a[3], "tinh_den": b[3], **goc}

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
