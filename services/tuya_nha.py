"""Lớp Tuya cho c2a — TỰ VIẾT, không chép code GPL.

Chủ máy đưa bốn dự án tham khảo (rospogrigio/localtuya, make-all/tuya-local,
xZetsubou/hass-localtuya, azerty9971/xtend_tuya) và yêu cầu gộp làm một. BA
trong bốn là **GPL-3.0**: chép code của chúng vào đây là buộc cả chatgpt2api
phải mở mã theo GPL. Chủ máy chốt 09/09/2026: **tự viết lại**. File này vì thế
chỉ mượn Ý TƯỞNG (cách nhận diện thiết bị bằng điểm số, học từ tuya-local —
giấy phép MIT), không mượn dòng code nào.

CŨNG KHÔNG DÙNG SDK: `tuya-iot-py-sdk` là MIT nhưng kéo theo `pycryptodome`
+ `websocket-client`. Cách ký của Tuya chỉ là HMAC-SHA256 mà Python có sẵn
trong thư viện chuẩn, nên tự ký để khỏi thêm hai gói nặng — đúng quy ước
"chấm điểm bằng Python thuần" của repo (xem rrf.py, ha_intent_rank.py).

CÁCH KÝ (đo thật với tài khoản chủ máy 09/09/2026, endpoint America):

    chuỗi_ký = client_id + [access_token] + t + method + "\\n"
               + sha256(body) + "\\n\\n" + đường_dẫn
    sign     = HMAC-SHA256(secret, chuỗi_ký).hexdigest().upper()

Header: ``client_id``, ``sign``, ``t``, ``sign_method: HMAC-SHA256``, và
``access_token`` khi đã có. Sai một dấu xuống dòng là trả "sign invalid".

⚠️ BÍ MẬT: ``access_id``, ``access_secret``, ``local_key``, ``device_id`` đều
đã có trong ``settings_secrets._TEN_BI_MAT`` nên tự động bị che ở
``/api/settings``. Đừng ghi chúng ra log — lộ cặp access_id + secret là điều
khiển được thiết bị từ xa, mà nhà chủ máy có KHOÁ CỬA chạy Tuya.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from services.config import config

logger = logging.getLogger(__name__)


class LoiTuya(Exception):
    """Lỗi có lời giải thích sẵn cho người đọc — tầng trên đưa nguyên văn."""


#: Máy chủ theo vùng. Chủ máy chọn "America" trong app dù ở Việt Nam — đó là
#: vùng của TÀI KHOẢN lúc đăng ký, không phải nơi ở, nên đừng "sửa" thành
#: tuyaeu cho hợp lý: sai vùng là mọi lời gọi trả "cross-region access".
MAY_CHU = {
    "america": "https://openapi.tuyaus.com",
    "china": "https://openapi.tuyacn.com",
    "europe": "https://openapi.tuyaeu.com",
    "india": "https://openapi.tuyain.com",
    "west-america": "https://openapi-ueaz.tuyaus.com",
    "west-europe": "https://openapi-weaz.tuyaeu.com",
}

_TOKEN_SOM = 60.0          # xin lại token trước khi hết hạn ngần này giây
_TIMEOUT = 20.0

_khoa = threading.RLock()
_token: dict[str, Any] = {"token": "", "het_han": 0.0}
_stats: dict[str, Any] = {"goi": 0, "loi": 0, "last_error": "", "last_ts": 0.0}


# ── Cấu hình ────────────────────────────────────────────────────────────────
def _cfg() -> dict[str, Any]:
    raw = config.data.get("tuya")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    c = _cfg()
    return bool(c.get("bat", True) and c.get("access_id") and c.get("access_secret"))


def _base() -> str:
    c = _cfg()
    kv = str(c.get("endpoint") or c.get("vung") or "america").strip().lower()
    if kv.startswith("http"):
        return kv.rstrip("/")
    return MAY_CHU.get(kv, MAY_CHU["america"])


def che_bi_mat(c: dict[str, Any]) -> dict[str, Any]:
    """Bản sao an toàn để hiện lên web / ghi log."""
    ra = dict(c)
    for k in ("access_secret", "password", "local_key"):
        if ra.get(k):
            ra[k] = "***"
    if ra.get("access_id"):
        ra["access_id"] = str(ra["access_id"])[:4] + "…"
    return ra


# ── Ký và gọi ───────────────────────────────────────────────────────────────
def _ky(secret: str, chuoi: str) -> str:
    return hmac.new(secret.encode("utf-8"), chuoi.encode("utf-8"),
                    hashlib.sha256).hexdigest().upper()


def _goi(duong: str, *, method: str = "GET", body: Any = None,
         token: str = "", timeout: float = _TIMEOUT) -> dict[str, Any]:
    """Một lời gọi OpenAPI đã ký. Ném ``LoiTuya`` kèm lời giải thích tiếng Việt."""
    c = _cfg()
    aid = str(c.get("access_id") or "").strip()
    sec = str(c.get("access_secret") or "").strip()
    if not aid or not sec:
        raise LoiTuya("Chưa khai Access ID / Access Secret của Tuya. "
                      "Vào Cài đặt → Home Assistant → thẻ Tuya để nhập.")

    # THAM SỐ TRUY VẤN PHẢI SẮP XẾP theo bảng chữ cái trước khi ký, nếu không
    # Tuya trả "sign invalid" — dễ tưởng nhầm là nhập sai Access Secret. Đo
    # thật 09/09/2026: cùng một URL, để nguyên thứ tự thì hỏng, sắp xếp thì
    # trả về 20 bản ghi. Đường dẫn GỬI ĐI cũng phải là bản đã sắp xếp.
    if "?" in duong:
        goc, _, truy_van = duong.partition("?")
        duong = goc + "?" + "&".join(sorted(truy_van.split("&")))

    raw = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    t = str(int(time.time() * 1000))
    chuoi = f"{aid}{token}{t}{method}\n{hashlib.sha256(raw).hexdigest()}\n\n{duong}"
    headers = {
        "client_id": aid,
        "sign": _ky(sec, chuoi),
        "t": t,
        "sign_method": "HMAC-SHA256",
        "Content-Type": "application/json",
    }
    if token:
        headers["access_token"] = token

    req = urllib.request.Request(_base() + duong, data=raw or None,
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            kq = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        _stats["loi"] += 1
        raise LoiTuya(f"Máy chủ Tuya trả lỗi {exc.code}.") from exc
    except Exception as exc:
        _stats["loi"] += 1
        _stats["last_error"] = str(exc)[:160]
        raise LoiTuya(f"Không nối được máy chủ Tuya: {str(exc)[:120]}") from exc

    _stats["goi"] += 1
    _stats["last_ts"] = time.time()
    if not kq.get("success"):
        msg = str(kq.get("msg") or "không rõ")
        _stats["last_error"] = msg[:160]
        # Dịch mấy lỗi hay gặp sang lời người đọc hiểu được, thay vì để nguyên
        # tiếng Anh của Tuya.
        thap = msg.lower()
        if "subscription has expired" in thap:
            raise LoiTuya("Gói IoT Core trên Tuya Cloud đã hết hạn. Vào "
                          "iot.tuya.com → Cloud → dự án → Service API để gia hạn "
                          "(bản dùng thử miễn phí, gia hạn lại được).")
        if "sign invalid" in thap:
            raise LoiTuya("Chữ ký sai — thường là Access Secret nhập nhầm, hoặc "
                          "giờ máy chủ lệch quá nhiều.")
        if "cross-region" in thap or "not exists" in thap:
            raise LoiTuya(f"Sai vùng máy chủ. Đang dùng {_base()} — thử đổi mục "
                          "«Vùng» sang đúng vùng lúc đăng ký tài khoản Tuya.")
        raise LoiTuya(f"Tuya từ chối: {msg}")
    return kq


def _lay_token(buoc_moi: bool = False) -> str:
    """Token sống 2 tiếng. Giữ lại và xin mới trước khi hết hạn."""
    with _khoa:
        if not buoc_moi and _token["token"] and time.time() < _token["het_han"]:
            return str(_token["token"])
        kq = _goi("/v1.0/token?grant_type=1")
        r = kq.get("result") or {}
        tok = str(r.get("access_token") or "")
        if not tok:
            raise LoiTuya("Tuya không trả token.")
        _token["token"] = tok
        _token["het_han"] = time.time() + float(r.get("expire_time") or 7200) - _TOKEN_SOM
        return tok


def goi_api(duong: str, *, method: str = "GET", body: Any = None) -> dict[str, Any]:
    """Gọi API cần token, tự xin lại token khi hết hạn giữa chừng."""
    tok = _lay_token()
    try:
        return _goi(duong, method=method, body=body, token=tok)
    except LoiTuya as exc:
        if "token" not in str(exc).lower():
            raise
        return _goi(duong, method=method, body=body, token=_lay_token(True))


# ── Thiết bị ────────────────────────────────────────────────────────────────
#: Đoán loại thiết bị từ mã ngành của Tuya. Danh sách này KHÔNG phải để tra
#: cứu đầy đủ — chỉ để gọi tên cho người đọc. Thiết bị lạ vẫn dùng được, chỉ
#: hiện nguyên mã (xem `_doan_loai`).
_NGANH = {
    "videolock": "khoá cửa có camera", "jtmspro": "khoá cửa", "ms": "khoá cửa",
    "mk": "khoá cửa", "bxx": "khoá cửa",
    "kg": "công tắc", "cz": "ổ cắm", "pc": "ổ cắm nhiều cổng",
    "dj": "đèn", "dd": "dải đèn LED", "fwd": "đèn trang trí", "xdd": "đèn trần",
    "wk": "bộ điều nhiệt", "ktkzq": "điều hoà", "ks": "quạt",
    "wsdcg": "cảm biến nhiệt ẩm", "ldcg": "cảm biến ánh sáng",
    "pir": "cảm biến chuyển động", "mcs": "cảm biến cửa",
    "sj": "cảm biến rò nước", "ywbj": "báo khói", "rqbj": "báo gas",
    "sp": "camera", "qt": "cổng kết nối", "wg2": "cổng kết nối",
    "cl": "rèm cửa", "clkg": "công tắc rèm",
}


def _doan_loai(d: dict[str, Any]) -> str:
    """Tên loại cho người đọc. Không biết thì trả nguyên mã, KHÔNG đoán bừa."""
    ma = str(d.get("category") or "").strip().lower()
    return _NGANH.get(ma) or (f"loại {ma}" if ma else "chưa rõ loại")


def danh_sach_thiet_bi(lam_moi: bool = False) -> list[dict[str, Any]]:
    """Mọi thiết bị trong tài khoản Tuya, kèm loại đã đoán."""
    # page_size TỐI ĐA LÀ 20 — đo thật 09/09/2026: 50 và 100 đều trả
    # "param size too much". Phải lật trang, không thì tài khoản nhiều thiết bị
    # sẽ mất im lặng những cái từ thứ 21 trở đi.
    ds: list[dict[str, Any]] = []
    moc = ""
    for _ in range(25):                      # trần 500 thiết bị, đủ cho nhà ở
        duong = "/v2.0/cloud/thing/device?page_size=20"
        if moc:
            duong += f"&last_row_key={moc}"
        kq = goi_api(duong)
        r = kq.get("result") or []
        lo = r if isinstance(r, list) else (r.get("list") or r.get("devices") or [])
        ds.extend(lo)
        moc = (r.get("last_row_key") or "") if isinstance(r, dict) else ""
        if len(lo) < 20 or not moc:
            break
    from services import thiet_bi_bo

    ra = []
    for d in ds:
        # Chủ máy «Bỏ khỏi c2a» — bot không thấy, không điều khiển được.
        if thiet_bi_bo.la_bo("tuya", str(d.get("id") or "")):
            continue
        ra.append({
            "id": d.get("id"),
            "ten": d.get("name") or "?",
            "nganh": d.get("category") or "",
            "loai": _doan_loai(d),
            "model": d.get("model") or "",
            "online": d.get("is_online", d.get("online")),
        })
    return ra


def thuoc_tinh(device_id: str) -> dict[str, Any]:
    """Mọi thuộc tính hiện tại của một thiết bị (mã → giá trị)."""
    if not device_id:
        raise LoiTuya("Chưa chọn thiết bị nào.")
    kq = goi_api(f"/v2.0/cloud/thing/{device_id}/shadow/properties")
    props = (kq.get("result") or {}).get("properties") or []
    return {str(p.get("code")): p.get("value") for p in props if p.get("code")}


def dieu_khien(device_id: str, ma: str, gia_tri: Any) -> bool:
    """Gửi một lệnh. Trả True khi Tuya xác nhận đã nhận."""
    if not device_id or not ma:
        raise LoiTuya("Thiếu thiết bị hoặc mã lệnh.")
    kq = goi_api(f"/v1.0/iot-03/devices/{device_id}/commands", method="POST",
                 body={"commands": [{"code": ma, "value": gia_tri}]})
    return bool(kq.get("result", True))


def _khop_ten(ten: str, ds: list[dict[str, Any]] | None = None) -> str:
    """Khớp câu người dùng với một thiết bị. Mập mờ → trả "" để tầng trên HỎI.

    Cùng nguyên tắc với ``mqtt_nha._khop_ten`` và ``camera_nha._khop``: mở nhầm
    KHOÁ CỬA là chuyện không sửa lại được, nên thà hỏi lại còn hơn đoán.
    """
    from services.agent.vi_text import fold

    ten = (ten or "").strip()
    if not ten:
        return ""
    ds = ds if ds is not None else danh_sach_thiet_bi()
    q = {t for t in fold(ten.lower()).split() if len(t) > 1}
    if not q:
        return ""

    diem = []
    for d in ds:
        # So với CẢ tên lẫn LOẠI: thiết bị hay mang tên tiếng Anh nhà sản xuất
        # đặt sẵn ("Smart Lock"), còn người dùng gọi bằng tiếng Việt ("khoá
        # cửa"). Chỉ so tên thì câu tiếng Việt không bao giờ khớp.
        tu = {t for t in fold(str(d["ten"]).lower()).split() if len(t) > 1}
        tu |= {t for t in fold(str(d.get("loai") or "").lower()).split() if len(t) > 1}
        diem.append((len(q & tu), str(d["id"]), d["ten"]))
    cao = max((n for n, _i, _t in diem), default=0)
    if cao < 1:
        return ""
    dan = [i for n, i, _t in diem if n == cao]
    return dan[0] if len(dan) == 1 else ""


def thu_ket_noi() -> dict[str, Any]:
    """Cho nút «Kiểm tra kết nối» trên web."""
    try:
        _lay_token(True)
        ds = danh_sach_thiet_bi()
        return {"ok": True, "so_thiet_bi": len(ds),
                "thiet_bi": [d["ten"] for d in ds[:10]], "may_chu": _base()}
    except LoiTuya as exc:
        return {"ok": False, "error": str(exc), "may_chu": _base()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "may_chu": _base()}


def stats() -> dict[str, Any]:
    with _khoa:
        con = max(0.0, _token["het_han"] - time.time()) if _token["token"] else 0.0
    return {**_stats, "bat": is_enabled(), "may_chu": _base(),
            "token_con_giay": round(con)}


def _reset_for_tests() -> None:
    with _khoa:
        _token["token"] = ""
        _token["het_han"] = 0.0
    for k in ("goi", "loi"):
        _stats[k] = 0
    _stats["last_error"] = ""
