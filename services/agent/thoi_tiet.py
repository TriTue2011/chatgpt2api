"""Thời tiết theo ĐỊA DANH MẶC ĐỊNH của từng cuộc trò chuyện — nguồn AccuWeather.

Chủ máy chốt 15/09/2026:
  * Thời tiết TÁCH khỏi Home Assistant. Hỏi «thời tiết hôm nay» hay tổng hợp
    thời tiết thì dùng địa danh mặc định; chưa có thì HỎI; đổi được bất cứ lúc
    nào. Có địa danh mặc định rồi thì mọi tin thời tiết theo địa danh đó.
  * Mỗi cuộc trò chuyện một địa danh (cùng phạm vi với trí nhớ và sở thích
    trình bày — `scope.khoa_du_lieu`).
  * Loa / trợ lý giọng nói HA vẫn đọc thực thể HA như cũ — file này không đụng
    tới đường đó.

Vì sao phải tách: đường tắt cũ đọc `weather.accuweather_hoang_mai` của HA, còn
lượt bot tự tra (bản tin 8h) lại đi qua bộ dò địa danh của `vn_weather` — cùng
một câu hỏi, hai kho dữ liệu. Đo thật 12–15/09: bản tin tra riêng câu thời tiết
thì nhận «Thời tiết Quinh Loi / Lang Yen» rồi bỏ đi; bản tin gộp câu thì nhận số
liệu của một nơi tên «Hà Nội» thuộc Hà Nam mà vẫn ghi là Hoàng Mai.

Ba lối vào dùng CHUNG lõi `xu_ly`:
  * `tra_loi`      — đường tắt kênh chat (orchestrator), có menu chọn.
  * `cho_cong_cu`  — khối thời tiết chèn vào kết quả `web_search`.
  * capability `thoi_tiet` — model gọi, kể cả để đổi địa danh mặc định.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from utils.log import logger

_SENTINEL = re.compile(r"^__thoi_tiet__:(dat|xem|doi)(?::(\d{1,12}))?$")
# Bot vừa hỏi «địa danh mặc định là nơi nào» — câu trả lời phải tới trong khoảng
# này mới được hiểu là tên nơi; quá hạn thì tin nhắn đi đường thường.
_HAN_CHO_GIAY = 15 * 60
# Lúc đang chờ tên nơi, câu dài hơn chừng này là người dùng đã nói sang chuyện
# khác chứ không phải gõ tên địa danh.
_TOI_DA_TU_TEN_NOI = 8
_SO_UNG_VIEN_HIEN = 6
# Tên bộ dò trong sổ lỗi `bai_hoc` — orchestrator dùng để hỏi lại «đúng ý chưa».
BO_DO = "thoi_tiet_accu"

_lock = threading.RLock()


# ── Sổ địa danh mặc định ───────────────────────────────────────────────────

def _duong() -> Path:
    from services.config import DATA_DIR
    return Path(DATA_DIR) / "agent" / "thoi_tiet_mac_dinh.json"


def _doc() -> dict[str, Any]:
    try:
        p = _duong()
        if p.is_file():
            d = json.loads(p.read_text("utf-8") or "{}")
            return d if isinstance(d, dict) else {}
    except Exception as exc:
        logger.warning({"event": "thoi_tiet_so_doc_loi", "error": str(exc)[:150]})
    return {}


def _ghi(d: dict[str, Any]) -> None:
    p = _duong()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, p)


def _sua(pham_vi: str, **truong: Any) -> None:
    with _lock:
        d = _doc()
        muc = dict(d.get(pham_vi) or {})
        for k, v in truong.items():
            if v is None:
                muc.pop(k, None)
            else:
                muc[k] = v
        d[pham_vi] = muc
        _ghi(d)


def doc_mac_dinh(pham_vi: str) -> dict[str, str] | None:
    dd = (_doc().get(pham_vi) or {}).get("dia_danh")
    return dd if isinstance(dd, dict) and dd.get("key") else None


def dat_mac_dinh(pham_vi: str, dd: dict[str, str]) -> None:
    _sua(pham_vi, dia_danh={k: dd.get(k, "") for k in ("key", "ten", "day_du", "quoc_gia")},
         cho=None)


def _dat_cho(pham_vi: str, viec: str, ung_vien: list[dict] | None = None) -> None:
    _sua(pham_vi, cho={"ts": time.time(), "viec": viec, "ung_vien": ung_vien or []})


def _lay_cho(pham_vi: str) -> dict[str, Any] | None:
    cho = (_doc().get(pham_vi) or {}).get("cho")
    if isinstance(cho, dict) and time.time() - float(cho.get("ts") or 0) < _HAN_CHO_GIAY:
        return cho
    return None


def _pham_vi(user_id: str) -> str:
    from services.agent.scope import khoa_du_lieu
    return khoa_du_lieu(str(user_id or ""))


# ── Nhận câu hỏi thời tiết ─────────────────────────────────────────────────

def _fold(s: str) -> str:
    from services.accu_thoi_tiet import _fold as f
    return f(s)


def _bo_dau_thoi_gian(noi: str) -> str:
    """«hôm nay tại Hoàng Mai» → «Hoàng Mai».

    `_extract_weather_city` chỉ cắt cụm thời gian ở CUỐI câu. Ở đây cắt thêm ở
    ĐẦU, nhưng chỉ các cụm NHIỀU TỪ trong chính danh sách đó và các từ nối — cắt
    từ đơn thì «Mai Châu» mất chữ «Mai» vì «mai» cũng là «ngày mai».
    """
    from services.protocol.openai_v1_chat_complete import _CITY_CONNECTORS, _CITY_TRAILS
    cum = sorted((t for t in _CITY_TRAILS if " " in t), key=len, reverse=True)
    tu = noi.split()
    doi = True
    while doi and tu:
        doi = False
        f = [_fold(t).strip(".,!?") for t in tu]
        for c in cum:
            n = len(c.split())
            if " ".join(f[:n]) == c:
                tu, doi = tu[n:], True
                break
        else:
            if f[0] in _CITY_CONNECTORS:
                tu, doi = tu[1:], True
    return " ".join(tu).strip(" ,.?!")


def phan_tich(cau: str, *, cau_chat: bool) -> str | None:
    """None = không phải câu hỏi thời tiết; "" = hỏi mà không nêu nơi; còn lại = tên nơi.

    `cau_chat=True` (tin người gõ, đường tắt KHÔNG qua model): mọi từ nội dung
    của câu — trừ từ thời tiết/thời gian — phải nằm trong chính tên nơi tách ra.
    Còn từ nào khác là câu mang ý khác, nhường model (model có tool `thoi_tiet`):
      «đổi địa danh thời tiết sang Đà Nẵng» — ý ĐỔI mặc định; ngưỡng đếm từ cũ
        của `_ha_local_weather` (≤4 từ) để lọt, và đường tắt tra nơi «sang Đà Nẵng».
      «một chú mèo… ngoài trời đang mưa» — câu tả cảnh.
    Nhường model chỉ chậm hơn; đoán ý bằng đường tắt thì sai.

    Câu `web_search` do model soạn thì không chặn: model đã quyết định đi tra, và
    câu gộp «tin tức … và thời tiết Hoàng Mai» vẫn phải ra được địa danh.
    """
    from services.protocol.openai_v1_chat_complete import (
        _VE_ANH_KW, _WEATHER_KW, _WEATHER_STOP, _extract_weather_city)
    raw = (cau or "").strip()
    fd = _fold(raw)
    if not raw or not any(k in fd for k in _WEATHER_KW):
        return None
    if any(k in fd for k in _VE_ANH_KW):
        return None
    try:
        from services import thoi_tiet_bao
        if thoi_tiet_bao.y_dinh_cau_hoi(raw, fd):
            return None     # hỏi BÃO — cụ thể hơn, để đường bão trả lời
    except Exception:
        pass
    noi = _bo_dau_thoi_gian(_extract_weather_city(raw))
    if noi and all(_fold(t).strip(".,!?") in _WEATHER_STOP for t in noi.split()):
        noi = ""
    if cau_chat:
        con_lai = {t for t in re.findall(r"[a-z]+", fd) if len(t) >= 2 and t not in _WEATHER_STOP}
        if not con_lai <= set(re.findall(r"[a-z]+", _fold(noi))):
            return None
    return noi


# ── Lõi ────────────────────────────────────────────────────────────────────

def _chon_mot(ung_vien: list[dict[str, str]], go: str) -> dict[str, str] | None:
    """Ứng viên duy nhất rõ ràng, hoặc None nếu phải hỏi người dùng chọn."""
    from services.accu_thoi_tiet import khop_ten
    khop = [u for u in ung_vien if khop_ten(go, u)] or ung_vien
    vn = [u for u in khop if u.get("quoc_gia") == "VN"]
    if len(khop) == 1:
        return khop[0]
    if len(vn) == 1:
        return vn[0]
    return None


def _ten(dd: dict[str, str]) -> str:
    from services.accu_thoi_tiet import _ten_hien_thi
    return _ten_hien_thi(dd)


def _da_dat(dd: dict[str, str]) -> str:
    # Cách đổi chỉ nói MỘT lần, lúc vừa đặt. Bản đầu gắn nút «Đổi địa danh mặc
    # định» vào MỌI câu trả lời thời tiết; chủ máy 15/09/2026 chụp màn hình Zalo:
    # "Hơi fail chỗ trả lời, đâu phải lúc nào cũng lựa chọn".
    return (f"Đã đặt «{_ten(dd)}» làm địa danh mặc định cho thời tiết ạ. Muốn đổi, "
            "anh/chị nhắn «đổi địa danh thời tiết sang <tên nơi>».\n\n")


def _tra(dd: dict[str, str], *, la_mac_dinh: bool) -> dict[str, Any]:
    from services import accu_thoi_tiet as accu
    text = accu.thoi_tiet_hien_tai(dd)
    if not text:
        return {"text": f"Em chưa lấy được thời tiết {_ten(dd)} từ AccuWeather lúc này, "
                        "anh/chị thử lại sau ít phút giúp em nhé."}
    if la_mac_dinh:
        return {"text": f"📍 {_ten(dd)} (địa danh mặc định)\n{text}", "cau_tra_loi": True}
    return {"text": text, "cau_tra_loi": True}


def _hoi_dia_danh(pham_vi: str, *, doi: bool) -> dict[str, Any]:
    _dat_cho(pham_vi, "dat")
    cu = doc_mac_dinh(pham_vi)
    if doi and cu:
        return {"text": f"Địa danh mặc định đang là «{_ten(cu)}». Anh/chị muốn đổi sang "
                        "nơi nào ạ? Nhắn tên nơi, ví dụ «Cầu Giấy, Hà Nội»."}
    return {"text": "Anh/chị muốn đặt địa danh mặc định để xem thời tiết là nơi nào ạ? "
                    "Nhắn tên nơi, ví dụ «Hoàng Mai, Hà Nội» — sau này hỏi thời tiết em "
                    "sẽ báo theo nơi đó."}


def _menu(pham_vi: str, viec: str, go: str, ung_vien: list[dict[str, str]]) -> dict[str, Any]:
    ds = ung_vien[:_SO_UNG_VIEN_HIEN]
    _dat_cho(pham_vi, viec, ds)
    return {"text": f"«{go}» khớp nhiều nơi, anh/chị chọn giúp em:",
            "nut": [(_ten(u), f"__thoi_tiet__:{viec}:{u['key']}") for u in ds]}


def _du_phong_vn_weather(noi: str) -> str | None:
    """Nơi AccuWeather không có («Hồ Chí Minh», «Sa Pa») — hỏi `vn_weather` như cũ.

    Chỉ dùng để XEM; đặt làm mặc định thì bắt buộc phải có mã AccuWeather.
    """
    try:
        from services.mcp_client import call_mcp_tool, la_loi_mcp
        from services.protocol.openai_v1_chat_complete import _clean_weather_text
        res = call_mcp_tool("get_current_weather", {"city": noi})
        if res and str(res).strip() and not la_loi_mcp(str(res)):
            return _clean_weather_text(str(res))
    except Exception as exc:
        logger.warning({"event": "thoi_tiet_du_phong_loi", "error": str(exc)[:150]})
    return None


def xu_ly(user_id: str, *, dia_danh: str = "", dat_mac_dinh_moi: bool = False,
          tu_dong: bool = False) -> dict[str, Any]:
    """Lõi chung. Trả {"text", "nut"?: [(nhãn, gửi)], "cau_tra_loi"?: bool}.

    `tu_dong=True` (web_search / việc theo lịch): không ai bấm menu được, nên
    trùng tên thì lấy ứng viên đầu (Việt Nam xếp trước) và nói rõ đã lấy nơi nào;
    chưa có địa danh mặc định thì trả lời dặn để model nói lại với người dùng.
    """
    from services import accu_thoi_tiet as accu
    pv = _pham_vi(user_id)
    noi = (dia_danh or "").strip()

    if not noi:
        if dat_mac_dinh_moi:
            return _hoi_dia_danh(pv, doi=True)
        dd = doc_mac_dinh(pv)
        if dd:
            return _tra(dd, la_mac_dinh=True)
        if tu_dong:
            return {"text": ("Cuộc trò chuyện này CHƯA có địa danh mặc định cho thời tiết, "
                             "nên chưa có số liệu thời tiết. Nói với người dùng: nhắn tên nơi "
                             "muốn đặt làm mặc định (ví dụ «đặt địa danh thời tiết là Hoàng Mai, "
                             "Hà Nội»); đừng tự chọn nơi nào.")}
        return _hoi_dia_danh(pv, doi=False)

    ung_vien = accu.tim_dia_danh(noi)
    if ung_vien is None:
        return {"text": "Em chưa tra được địa danh trên AccuWeather lúc này, anh/chị thử lại "
                        "sau ít phút giúp em nhé."}
    if not ung_vien:
        if not dat_mac_dinh_moi:
            du_phong = _du_phong_vn_weather(noi)
            if du_phong:
                return {"text": du_phong, "cau_tra_loi": True}
        return {"text": f"Em không tìm thấy «{noi}» trên AccuWeather. Anh/chị ghi rõ hơn giúp "
                        "em, ví dụ thêm tỉnh/thành: «Cầu Giấy, Hà Nội», «Thành phố Hồ Chí Minh»."}

    dd = _chon_mot(ung_vien, noi) or (ung_vien[0] if tu_dong else None)
    if dd is None:
        return _menu(pv, "dat" if dat_mac_dinh_moi else "xem", noi, ung_vien)
    if dat_mac_dinh_moi:
        dat_mac_dinh(pv, dd)
        ra = _tra(dd, la_mac_dinh=True)
        ra["text"] = _da_dat(dd) + ra["text"]
        return ra
    return _tra(dd, la_mac_dinh=False)


# ── Lối vào ─────────────────────────────────────────────────────────────────

def tra_loi(user_text: str, user_id: str) -> dict[str, Any] | None:
    """Đường tắt kênh chat. None = tin này không thuộc luồng thời tiết."""
    raw = (user_text or "").strip()
    if not raw or not user_id:
        return None
    pv = _pham_vi(user_id)

    m = _SENTINEL.match(raw)
    if m:
        viec, key = m.group(1), m.group(2) or ""
        if viec == "doi":
            return _hoi_dia_danh(pv, doi=True)
        cho = _lay_cho(pv) or {}
        dd = next((u for u in cho.get("ung_vien") or [] if u.get("key") == key), None)
        if dd is None:
            return {"text": "Lựa chọn này đã hết hạn ạ. Anh/chị nhắn lại tên nơi giúp em nhé."}
        if viec == "dat":
            dat_mac_dinh(pv, dd)
            ra = _tra(dd, la_mac_dinh=True)
            ra["text"] = _da_dat(dd) + ra["text"]
            return ra
        return _tra(dd, la_mac_dinh=False)

    loai = phan_tich(raw, cau_chat=True)
    if loai:
        # Chỉ trả lời khi AccuWeather XÁC NHẬN có nơi đó. Bộ dò từ khoá có ca bắt
        # nhầm («không khí gia đình dạo này thế nào» → nơi «gia đình dạo này»),
        # và rơi sang `vn_weather` thì nó geocode chữ gì cũng ra MỘT chỗ nào đó.
        # Không xác nhận được → model (tool `thoi_tiet` vẫn còn đường dự phòng
        # cho nơi AccuWeather thiếu như «Hồ Chí Minh»).
        from services import accu_thoi_tiet as accu
        if not accu.tim_dia_danh(loai):
            return None
    if loai is not None:
        return xu_ly(user_id, dia_danh=loai)

    cho = _lay_cho(pv)
    if not cho or cho.get("viec") != "dat":
        return None
    # Đang chờ tên địa danh. Chỉ nhận khi người dùng gõ ĐÚNG tên một ứng viên —
    # tin khác («ok», «bật đèn bếp») phải đi đường thường, không bị nuốt thành
    # tên nơi.
    if len(raw.split()) <= _TOI_DA_TU_TEN_NOI:
        from services import accu_thoi_tiet as accu
        ung_vien = accu.tim_dia_danh(raw)
        if ung_vien is None:
            return {"text": "Em chưa tra được địa danh trên AccuWeather lúc này, anh/chị "
                            "nhắn lại tên nơi sau ít phút giúp em nhé."}
        khop = [u for u in ung_vien if accu.khop_ten(raw, u)]
        if khop:
            return xu_ly(user_id, dia_danh=raw, dat_mac_dinh_moi=True)
    _sua(pv, cho=None)
    return None


def cho_cong_cu(query: str, user_id: str) -> str | None:
    """Khối thời tiết cho kết quả `web_search`; None = câu tra không hỏi thời tiết."""
    loai = phan_tich(query, cau_chat=False)
    if loai is None:
        return None
    return str(xu_ly(user_id, dia_danh=loai, tu_dong=True).get("text") or "") or None


def gan_nut(text: str, nut: list[tuple[str, str]]) -> str:
    """Nút bấm dưới dạng khối <<<ASK>>> mà `ask_choices` bóc ra thành menu."""
    if not nut:
        return text
    return (text + "\n\n<<<ASK>>>\n"
            + "\n".join(f"{nhan} | {gui}" for nhan, gui in nut) + "\n<<<END>>>")
