"""Luồng HỎI khi «Dịch chữ trong ảnh» — channel-agnostic (soi [[so_da_luu]]).

Chủ máy chốt (05/09): đọc chữ trong ảnh → nếu ảnh có NHIỀU thứ tiếng thì cho
CHỌN phần cần dịch (đánh số, kèm «Toàn bộ») → HỎI tiếng đích (kèm «Song ngữ» =
dịch ra HAI tiếng) → mới dịch. Một máy trạng thái ở đây, ba kênh (Zalo cá nhân /
Telegram / Zalo Bot) chỉ gọi ``khoi_dong()`` lúc chọn mục dịch và ``tra_loi()``
sớm trong dispatch — không chép logic ba lần.

Trạng thái theo NGƯỜI, trong RAM, TTL ngắn; mất (restart) chỉ lỡ một lượt hỏi.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_TTL = 600.0
_lock = threading.Lock()
#: user → {chu, dong:[{line,ma}], tiengs:[ma], buoc, nguon, ts}
_phien: dict[str, dict] = {}

#: Tên hiển thị tiếng Việt cho mã server (đủ cho menu; thiếu thì hiện mã).
_TEN_HIEN = {
    "vi": "Việt", "en": "Anh", "zh": "Trung", "zh-Hans": "Trung",
    "zh-Hant": "Trung", "ja": "Nhật", "ko": "Hàn", "fr": "Pháp", "de": "Đức",
    "ru": "Nga", "es": "Tây Ban Nha", "it": "Ý", "pt": "Bồ Đào Nha",
    "pt-BR": "Bồ Đào Nha", "th": "Thái", "id": "Indonesia", "ar": "Ả Rập",
    "hi": "Hindi", "nl": "Hà Lan", "pl": "Ba Lan", "tr": "Thổ Nhĩ Kỳ",
    "uk": "Ukraina", "cs": "Séc", "hu": "Hungary", "el": "Hy Lạp",
}
#: Tiếng đích chào sẵn trong menu (mã model; `_chuan_ma` đổi sang mã server).
_DICH_MENU = ["vi", "en", "zh", "ja", "ko"]


def _ten(ma: str) -> str:
    return _TEN_HIEN.get(str(ma or ""), str(ma or "?"))


def _fold(s: str) -> str:
    from services import translate_service as ts
    return ts._bo_dau(s)


def _server(ma_model: str) -> str:
    """Mã model ("zh") → mã server ("zh-Hans"); "" nếu server không có."""
    from services import translate_service as ts
    return ts._chuan_ma(ma_model, ts.lang_codes()) or ""


def _ma_tu_ten(s: str) -> str:
    """"tiếng Nhật"/"nhật"/"Anh" → mã server, hoặc "" nếu không nhận ra."""
    from services import translate_service as ts
    f = " ".join(_fold(s).split()).strip(":,.")
    f = f.replace("tieng ", "").replace(" ", "")
    ma = ts._TEN_NGON_NGU.get(f, "")
    return _server(ma) if ma else ""


def _menu_nguon(tiengs: list[str]) -> str:
    d = ["🌐 Ảnh có nhiều thứ tiếng. Dịch phần nào ạ?"]
    for i, m in enumerate(tiengs, 1):
        d.append(f"{i}. Chỉ tiếng {_ten(m)}")
    d.append(f"{len(tiengs) + 1}. Toàn bộ")
    d.append("→ trả lời SỐ")
    return "\n".join(d)


def _menu_dich(nguon: str) -> str:
    hint = f" (chữ đang là tiếng {_ten(nguon)})" if nguon and nguon != "all" else ""
    d = [f"Dịch sang tiếng gì ạ?{hint}"]
    for i, m in enumerate(_DICH_MENU, 1):
        d.append(f"{i}. Tiếng {_ten(m)}")
    d.append(f"{len(_DICH_MENU) + 1}. Song ngữ (2 tiếng)")
    d.append("→ trả lời SỐ, hoặc gõ tên tiếng khác (vd «tiếng Pháp»)")
    return "\n".join(d)


def khoi_dong(user_id: str, image_bytes: bytes, *, channel: str = "") -> dict:
    """Chọn «Dịch chữ trong ảnh» → OCR + dò tiếng → câu HỎI đầu tiên.

    Trả ``{"text": …}`` để kênh gửi. Đặt trạng thái CHỜ (nếu đọc được chữ)."""
    from services.photo_intent import analyze_photo
    from services.translate_service import NHAC_OCR, detect, is_configured
    uid = str(user_id or "").strip()
    if not uid:
        return {"text": "Em chưa xác định được anh/chị để dịch ạ."}
    if not is_configured():
        return {"text": "Máy chủ dịch chưa cấu hình nên em chưa dịch được ạ."}
    try:
        chu = (analyze_photo(image_bytes, NHAC_OCR, channel=channel,
                             neo_tieng_viet=False, max_tokens=2000) or "").strip()
    except Exception as exc:
        logger.warning("dich_anh_hoi OCR: %s", exc)
        return {"text": f"Em chưa đọc được chữ trong ảnh ạ ({str(exc)[:80]})."}
    if not chu or "KHONGCOCHU" in chu.upper():
        return {"text": "Em không thấy chữ nào trong ảnh ạ."}

    dong: list[dict] = []
    dem: dict[str, int] = {}
    for ln in chu.splitlines()[:40]:
        t = ln.strip()
        if len(t) < 2:
            continue
        try:
            ma, _ = detect(t[:500])
        except Exception:
            ma = ""
        dong.append({"line": t, "ma": ma})
        if ma:
            dem[ma] = dem.get(ma, 0) + 1
    tiengs = sorted(dem, key=lambda m: -dem[m])

    with _lock:
        _phien[uid] = {"chu": chu, "dong": dong, "tiengs": tiengs,
                       "buoc": "", "nguon": "", "ts": time.time()}
        if len(tiengs) <= 1:
            _phien[uid]["nguon"] = tiengs[0] if tiengs else "all"
            _phien[uid]["buoc"] = "dich"
            return {"text": _menu_dich(_phien[uid]["nguon"])}
        _phien[uid]["buoc"] = "nguon"
        return {"text": _menu_nguon(tiengs)}


def _giai_dich(t: str) -> str:
    """Câu chọn tiếng đích → mã server | "SONGNGU" | "" (không nhận ra)."""
    m = re.match(r"^\s*(\d{1,2})\b", t)
    if m:
        i = int(m.group(1)) - 1
        if i == len(_DICH_MENU):
            return "SONGNGU"
        if 0 <= i < len(_DICH_MENU):
            return _server(_DICH_MENU[i])
    if "song ngu" in _fold(t):
        return "SONGNGU"
    return _ma_tu_ten(t)


def _giai_hai_tieng(t: str) -> list[str]:
    """"Việt và Anh" / "Việt, Anh" → [ma1, ma2]."""
    phan = re.split(r"\s*(?:,|;|\bva\b|\bvà\b|&|\+)\s*", t)
    ra: list[str] = []
    for p in phan:
        ma = _ma_tu_ten(p)
        if ma and ma not in ra:
            ra.append(ma)
    return ra


def _dich_ra(rec: dict, targets: list[str]) -> dict:
    """Dịch phần chữ đã chọn sang các tiếng đích → câu trả lời."""
    from services.translate_service import translate
    nguon = rec.get("nguon")
    if nguon and nguon != "all":
        lines = [d["line"] for d in rec["dong"] if d["ma"] == nguon]
        src = nguon
    else:
        lines = [d["line"] for d in rec["dong"]]
        src = "auto"
    goc = "\n".join(lines).strip() or str(rec.get("chu") or "").strip()
    if not goc:
        return {"text": "Em không tách được phần chữ đó ạ."}
    phan: list[str] = []
    for tg in targets:
        try:
            bd = goc if tg == src else translate(goc, tg, src)
        except Exception as exc:
            logger.warning("dich_anh_hoi dịch %s: %s", tg, exc)
            bd = f"(lỗi dịch sang tiếng {_ten(tg)}: {str(exc)[:60]})"
        phan.append(f"【Tiếng {_ten(tg)}】\n{bd}" if len(targets) > 1 else bd)
    return {"text": "\n\n".join(phan)[:3800]}


def tra_loi(user_id: str, text: str) -> dict | None:
    """Câu này có phải trả lời một bước của luồng dịch ảnh không.

    None → không liên quan (kênh xử lý bình thường). Ngược lại ``{"text": …}``."""
    uid = str(user_id or "").strip()
    t = str(text or "").strip()
    if not uid or not t:
        return None
    with _lock:
        rec = _phien.get(uid)
        if not rec or time.time() - float(rec.get("ts", 0)) > _TTL:
            _phien.pop(uid, None)
            return None
        buoc = rec.get("buoc")

        if buoc == "nguon":
            m = re.match(r"^\s*(\d{1,2})\b", t)
            if not m:
                return {"text": "Anh/chị trả lời SỐ giúp em ạ.\n"
                                + _menu_nguon(rec["tiengs"])}
            i = int(m.group(1)) - 1
            tiengs = rec["tiengs"]
            if i == len(tiengs):
                rec["nguon"] = "all"
            elif 0 <= i < len(tiengs):
                rec["nguon"] = tiengs[i]
            else:
                return {"text": "Số không có trong danh sách ạ.\n"
                                + _menu_nguon(tiengs)}
            rec["buoc"] = "dich"
            rec["ts"] = time.time()
            return {"text": _menu_dich(rec["nguon"])}

        if buoc == "dich":
            tg = _giai_dich(t)
            if tg == "SONGNGU":
                rec["buoc"] = "dich2"
                rec["ts"] = time.time()
                return {"text": "Song ngữ — cho em HAI tiếng đích ạ "
                                "(vd «Việt và Anh»):"}
            if not tg:
                return {"text": "Em chưa nhận ra tiếng đích. Gõ tên tiếng "
                                "(vd «tiếng Nhật») hoặc số ạ.\n"
                                + _menu_dich(rec.get("nguon"))}
            _phien.pop(uid, None)
            return _dich_ra(rec, [tg])

        if buoc == "dich2":
            mas = _giai_hai_tieng(t)
            if len(mas) < 2:
                return {"text": "Em cần ĐỦ HAI tên tiếng ạ (vd «Việt và Anh»)."}
            _phien.pop(uid, None)
            return _dich_ra(rec, mas[:2])
    return None
