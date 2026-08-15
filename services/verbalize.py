"""Verbalize text for TTS — chuyển KÝ TỰ/ĐƠN VỊ sang VĂN XUÔI tiếng Việt.

Mục đích: TIN NHẮN giữ ký tự (°C, %, km/h, 20/06...) cho dễ đọc bằng mắt; còn
khi đọc bằng GIỌNG NÓI (TTS) thì chuyển sang chữ để máy đọc không ngang tai.
Dùng chung cho mọi nguồn: canonicalizer cục bộ, model (codex), tìm kiếm, RAG.

Nguyên tắc AN TOÀN: chỉ đổi khi NGỮ CẢNH RÕ (đơn vị đứng sau số, ngày dd/mm/yyyy,
giờ hh:mm, ký hiệu đứng riêng) để không phá URL, mã, phân số trong văn bản model.
"""

from __future__ import annotations

import re

# Đơn vị: viết tắt -> chữ đọc. Chỉ đổi khi đứng SAU MỘT SỐ.
_UNITS: dict[str, str] = {
    # nhiệt độ
    "°C": "độ C", "°F": "độ F", "°K": "độ K", "℃": "độ C", "℉": "độ F", "K": "độ K",
    # phần trăm
    "%": "phần trăm", "‰": "phần nghìn",
    # tốc độ
    "km/h": "ki lô mét trên giờ", "km/s": "ki lô mét trên giây",
    "m/s": "mét trên giây", "m/s²": "mét trên giây bình phương", "knot": "hải lý trên giờ",
    # chiều dài
    "km": "ki lô mét", "dm": "đề xi mét", "cm": "xen ti mét", "mm": "mi li mét",
    "µm": "micrô mét", "nm": "na nô mét", "m": "mét", "inch": "inh", "ft": "phít",
    # khối lượng
    "kg": "ki lô gam", "mg": "mi li gam", "µg": "micrô gam", "g": "gam", "t": "tấn",
    # diện tích / thể tích
    "km²": "ki lô mét vuông", "m²": "mét vuông", "cm²": "xen ti mét vuông",
    "m³": "mét khối", "cm³": "xen ti mét khối", "ml": "mi li lít", "l": "lít",
    # điện / năng lượng
    "kWh": "ki lô oát giờ", "Wh": "oát giờ", "MW": "mê ga oát", "kW": "ki lô oát", "W": "oát",
    "kV": "ki lô vôn", "mV": "mi li vôn", "V": "vôn", "mA": "mi li ampe", "A": "ampe", "Ω": "ôm",
    # áp suất
    "hPa": "héc tô pát can", "kPa": "ki lô pát can", "Pa": "pát can",
    "mbar": "mi li ba", "bar": "ba", "mmHg": "mi li mét thủy ngân", "atm": "át mốt phe",
    # không khí
    "µg/m³": "micrô gam trên mét khối", "mg/m³": "mi li gam trên mét khối",
    "ppm": "phần triệu", "ppb": "phần tỉ",
    # ánh sáng / âm thanh
    "lx": "lux", "lm": "lu men", "cd": "can đê la", "dB": "đề xi ben", "dBA": "đề xi ben",
    # tần số
    "GHz": "gi ga héc", "MHz": "mê ga héc", "kHz": "ki lô héc", "Hz": "héc",
    # dữ liệu
    "TB": "tê ra bai", "GB": "gi ga bai", "MB": "mê ga bai", "KB": "ki lô bai", "Mbps": "mê ga bit trên giây",
    # thời gian
    "ms": "mi li giây", "µs": "micrô giây", "kcal": "ki lô ca lo", "cal": "ca lo",
}

# Tiền tệ đứng SAU số. (Bỏ 'đ' trần vì trùng quá nhiều chữ tiếng Việt.)
_CURRENCY: dict[str, str] = {
    "₫": "đồng", "VNĐ": "đồng", "VND": "đồng",
    "USD": "đô la", "EUR": "ơ rô", "JPY": "yên", "CNY": "nhân dân tệ", "GBP": "bảng",
}

# Ký hiệu đứng riêng -> chữ (hoặc bỏ).
# Mở rộng để bắt được cả trong trường hợp stream bị cắt chunk (không có số đi kèm)
_SYMBOLS: list[tuple[str, str]] = [
    ("°C", " độ C "), ("°F", " độ F "), ("℃", " độ C "), ("℉", " độ F "),
    ("%", " phần trăm "), ("‰", " phần nghìn "),
    ("m²", " mét vuông "), ("m³", " mét khối "), ("km²", " ki lô mét vuông "),
    ("km/h", " ki lô mét trên giờ "), ("m/s", " mét trên giây "),
    ("µg/m³", " micrô gam trên mét khối "), ("mg/m³", " mi li gam trên mét khối "),
    ("₫", " đồng "), ("VNĐ", " đồng "), ("VND", " đồng "),
    ("→", " "), ("←", " "), ("↔", " "), ("⇒", " "), ("➜", " "),
    ("—", " "), ("–", " "), ("•", " "), ("·", " "), ("▪", " "), ("◦", " "),
    ("×", " nhân "), ("÷", " chia "), ("≈", " xấp xỉ "), ("≤", " nhỏ hơn hoặc bằng "),
    ("≥", " lớn hơn hoặc bằng "), ("±", " cộng trừ "), ("°", " độ "),
    ("&", " và "), ("@", " a còng "), ("№", " số "),
]

_UNIT_MAP = {**_UNITS, **_CURRENCY}
# Đơn vị 1 KÝ TỰ ascii dễ nhầm (5g mạng, phòng 5A...) -> bắt buộc có DẤU CÁCH.
_SINGLE = {"m", "g", "l", "t", "W", "V", "A", "K"}
_multi = sorted((u for u in _UNIT_MAP if u not in _SINGLE), key=len, reverse=True)
_single = sorted((u for u in _UNIT_MAP if u in _SINGLE), key=len, reverse=True)
# Số + khoảng trắng tùy chọn + đơn vị NHIỀU ký tự; số + DẤU CÁCH + đơn vị 1 ký tự.
_UNIT_RE_MULTI = re.compile(
    r"(?<![\w])(\d[\d.,]*)\s*(" + "|".join(re.escape(u) for u in _multi) + r")(?![\wÀ-ỹ])")
_UNIT_RE_SINGLE = re.compile(
    r"(?<![\w])(\d[\d.,]*)\s+(" + "|".join(re.escape(u) for u in _single) + r")(?![\wÀ-ỹ²³])")
_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?!\d)")
_TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:hg]([0-5]\d)(?!\d)")
_RANGE_RE = re.compile(r"(\d[\d.,]*)\s*-\s*(\d[\d.,]*)")  # 28-35 -> 28 đến 35

# Các đơn vị CHỮ CÁI an toàn để thay thế độc lập (không trùng với từ thông dụng tiếng Việt)
_SAFE_STANDALONE_UNITS = {
    "km": "ki lô mét", "cm": "xen ti mét", "mm": "mi li mét", "nm": "na nô mét", "µm": "micrô mét",
    "kg": "ki lô gam", "mg": "mi li gam", "µg": "micrô gam",
    "ml": "mi li lít",
    "kWh": "ki lô oát giờ", "mA": "mi li am pe", "mV": "mi li vôn", "kV": "ki lô vôn",
    "GHz": "gi ga héc", "MHz": "mê ga héc", "kHz": "ki lô héc", "Hz": "héc",
    "Mbps": "mê ga bít trên giây", "Gbps": "gi ga bít trên giây", "Kbps": "ki lô bít trên giây",
    "MB": "mê ga bai", "GB": "gi ga bai", "TB": "tê ra bai", "KB": "ki lô bai",
    "hPa": "héc tô pát can", "kPa": "ki lô pát can", "mbar": "mi li ba",
    "USD": "đô la", "EUR": "ơ rô", "JPY": "yên", "CNY": "nhân dân tệ", "GBP": "bảng anh",
    "VNĐ": "đồng", "VND": "đồng", "AQI": "a quy y"
}
# Bắt các từ đứng độc lập (có word boundary) để phòng trường hợp stream bị cắt mảnh (chunk)
_STANDALONE_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _SAFE_STANDALONE_UNITS) + r")\b"
)


def _unit_sub(m: re.Match) -> str:
    return f"{m.group(1)} {_UNIT_MAP[m.group(2)]}"


def _date_sub(m: re.Match) -> str:
    d, mo, y = m.group(1), m.group(2), m.group(3)
    s = f"ngày {int(d)} tháng {int(mo)}"
    if y:
        s += f" năm {y if len(y) == 4 else '20' + y}"
    return s


def _time_sub(m: re.Match) -> str:
    """hh:mm → cách người Việt ĐỌC giờ, không phải cách người Việt VIẾT giờ.

    Ba chỗ khác nhau, đo thật 15/08/2026 bằng vòng TTS → STT trên cả giọng Piper
    lẫn VieNeu (cả hai giọng đều mắc y hệt):

        "09:00"  cũ → "09 giờ 00" → máy đọc ra "KHÔNG CHÍN GIỜ KHÔNG KHÔNG"
                 nay → "9 giờ"    → "chín giờ"
        "14:05"  cũ → "14 giờ 05" → "…giờ không năm"
                 nay → "14 giờ 5"

    Số 0 đứng đầu là quy ước VIẾT cho thẳng cột, đọc lên thì thành thừa chữ. Phút
    bằng 00 cũng vậy: người Việt nói "chín giờ", không ai nói "chín giờ không".
    """
    gio, phut = int(m.group(1)), int(m.group(2))
    return f"{gio} giờ" if phut == 0 else f"{gio} giờ {phut}"


def verbalize(text: str | None, *, keep_edges: bool = False) -> str:
    """Đổi ký tự/đơn vị sang văn xuôi cho TTS. An toàn để áp lên văn bản model.

    keep_edges=True: GIỮ khoảng trắng ĐẦU/CUỐI nguyên bản của `text`. Bắt buộc
    khi verbalize TỪNG DELTA của stream — nếu strip mỗi mảnh thì dấu cách ở biên
    ("Xin " + "chào") biến mất, chữ dính vào nhau ("Xinchào"). Xem
    _verbalize_in_stream trong openai_v1_chat_complete."""
    if not text:
        return text or ""
    s = text
    s = _DATE_RE.sub(_date_sub, s)               # 20/06/2026 -> ngày 20 tháng 6 năm 2026
    s = _TIME_RE.sub(_time_sub, s)               # 14:30 -> 14 giờ 30; 09:00 -> 9 giờ
    s = _RANGE_RE.sub(r"\1 đến \2", s)           # 28-35 -> 28 đến 35
    s = _UNIT_RE_MULTI.sub(_unit_sub, s)         # 30°C -> 30 độ C; 5 m/s -> 5 mét trên giây
    s = _UNIT_RE_SINGLE.sub(_unit_sub, s)        # 45 W -> 45 oát (đơn vị 1 ký tự cần dấu cách)
    s = _STANDALONE_RE.sub(lambda m: f" {_SAFE_STANDALONE_UNITS[m.group(1)]} ", s) # km -> ki lô mét
    for sym, rep in _SYMBOLS:                     # → — • × ÷ ...
        s = s.replace(sym, rep)
    s = re.sub(r"([Nn]gày)\s+ngày\b", r"\1", s)  # 'ngày 20/06' -> tránh 'ngày ngày'
    
    # Loại bỏ TẤT CẢ ký tự thừa (emoji, markdown sót lại như *, #, _, ~, ngoặc vuông...)
    # Chỉ giữ lại: chữ cái (\w), số, khoảng trắng (\s), và các dấu câu cơ bản (. , ! ? -)
    s = s.replace("_", " ")  # \w bao gồm cả _, nên phải đổi _ thành khoảng trắng trước
    s = re.sub(r'[^\w\s\.,!\?\-]', '', s)
    
    s = re.sub(r"[ \t]{2,}", " ", s)             # gộp khoảng trắng thừa
    core = s.strip()
    if keep_edges:
        lead = text[: len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()):]
        if not core:
            # Chunk stream chỉ chứa emoji/ký hiệu (model hay tách emoji thành
            # delta riêng) → chỉ giữ khoảng trắng biên, KHÔNG trả lại nguyên văn
            # kẻo emoji lọt qua. text toàn khoảng trắng thì giữ nguyên (lead và
            # trail lúc đó trùng nhau, cộng lại sẽ nhân đôi).
            return text if not text.strip() else lead + trail
        return lead + core + trail
    return core
