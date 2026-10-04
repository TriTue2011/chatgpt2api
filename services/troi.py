"""TRỜI TỐI hay SÁNG — để luật nói được «trời tối» mà không phải đoán ngưỡng độ sáng.

05/10/2026: đo bộ đề nhà giả, bot BỎ mọi trường hợp «trời tối, người vào … → bật đèn» vì quy tắc cấm đoán ngưỡng lux
khi mục B chưa có số đã học — nhà mới nào cũng vậy; luật bật đèn trần nhà thật (#14) cũng không có điều kiện tối.
Nên có điều kiện chuẩn ``{"ma": "troi", "la": "toi" | "sang"}`` cho mọi nhà.

Nguồn: `sun.sun` của Home Assistant nếu c2a thấy (nhà chủ máy để nó trong sổ «Bỏ khỏi c2a»); không thì TỰ TÍNH góc
mặt trời theo toạ độ nhà (`/api/config` của HA) bằng công thức thiên văn rút gọn (sai số < 1 phút ở vĩ độ Việt Nam).
Tối = mặt trời dưới đường chân trời (góc < 0°). Không biết toạ độ → None (điều kiện coi là không đúng).
"""
from __future__ import annotations

import math
import threading
import time
from typing import Any

_khoa = threading.Lock()
_toa_do: dict[str, Any] = {"luc": 0.0, "gt": None}
_GIU_TOA_DO = 86400.0


def goc_mat_troi(ts: float, vi_do: float, kinh_do: float) -> float:
    """Góc cao mặt trời (độ) tại thời điểm ``ts`` (giây UNIX) ở toạ độ đã cho."""
    n = ts / 86400.0 + 2440587.5 - 2451545.0
    L = (280.460 + 0.9856474 * n) % 360
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians(L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 0.0000004 * n)
    xich_vi = math.asin(math.sin(eps) * math.sin(lam))
    xich_kinh = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    gmst = (18.697374558 + 24.06570982441908 * n) % 24
    goc_gio = math.radians(gmst * 15 + kinh_do) - xich_kinh
    vd = math.radians(vi_do)
    return math.degrees(math.asin(math.sin(vd) * math.sin(xich_vi)
                                  + math.cos(vd) * math.cos(xich_vi) * math.cos(goc_gio)))


def _toa_do_nha() -> tuple[float, float] | None:
    now = time.time()
    with _khoa:
        if now - _toa_do["luc"] < _GIU_TOA_DO:
            return _toa_do["gt"]
    gt = None
    try:
        from services import ha_client
        code, body = ha_client._api_request("GET", "/api/config")
        if code == 200 and isinstance(body, dict) and body.get("latitude") is not None:
            gt = (float(body["latitude"]), float(body["longitude"]))
    except Exception:  # noqa: BLE001 — không có HA thì không biết trời
        gt = None
    with _khoa:
        _toa_do.update(luc=now, gt=gt)
    return gt


def toi(luc: float | None = None) -> bool | None:
    """True = trời tối, False = sáng, None = không biết."""
    luc = float(luc or time.time())
    try:
        from services import ha_client
        s = ha_client.get_state("sun.sun")
        if s and abs(luc - time.time()) < 120 and s.get("state") in ("below_horizon", "above_horizon"):
            return s["state"] == "below_horizon"
    except Exception:  # noqa: BLE001
        pass
    td = _toa_do_nha()
    if td is None:
        return None
    return goc_mat_troi(luc, td[0], td[1]) < 0.0


def _reset_for_tests(toa_do: tuple[float, float] | None) -> None:
    with _khoa:
        _toa_do.update(luc=time.time(), gt=toa_do)
