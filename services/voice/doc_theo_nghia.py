"""Đọc chữ viết tắt / ký hiệu / đơn vị cho ĐÚNG — bước chuẩn bị trước sea_g2p.

Chủ máy 25/09/2026: "làm máy móc sợ không thoát được cái sai" — muốn đọc theo
nghĩa, chính xác ≥ 97%. Đo trên 2.410 chữ "cần đọc theo nghĩa" trong 2.000 câu trả
lời thật của bot (bộ đo ở /opt/claude-c2a/doc_dung, NGOÀI repo vì chứa câu trả
lời thật): sea_g2p + hoa_hoc đúng 89,1%. Ba thư viện chuẩn hoá tiếng Việt có sẵn
đều THUA (soe-vinorm 81,5%, pyvinorm 72,5%, vietnormalizer 68,1%) — nên không thay,
mà sửa từng LỚP lỗi có quy luật mà sea_g2p mắc:

* "- 60%" (gạch đầu dòng) đọc "ÂM sáu mươi phần trăm";
* "7.3 km/h" đọc "bảy CHẤM ba" — dấu chấm thập phân kiểu Anh;
* "120 ph" → "phê hát", "12V" → "vê", "800W" → "vê kép", "10Ah" → "a hát",
  "235 Nm" → "na nô mét", "650 kcal" → "kilocalorie";
* "92-II", "95-III" → "i i", "i i i"; "quý IV";
* mục "1g. … 1h." → "một GAM", "một GIỜ";
* "CT4B-X2" → "…NHÂN hai", "GPT-5" → "g p t năm";
* viết tắt lạ để trơ phụ âm: "API" → "a p i", "USD" → "u s d";
* tiêu đề IN HOA đánh vần từng chữ: "CAMERA GIÁM SÁT" → "xê a mờ e rờ a…";
* tên viết tắt "L.T.M.P" đọc cả chữ "chấm".

Sau khi sửa: 98,0% trên bộ ca cũ, 94,1% trên bộ ca MỚI (tin tức 25/09, gắn đáp án
trước khi chạy). Phần còn sai cần HIỂU NGHĨA (HCV = huy chương vàng, "UV" là tia
cực tím hay ủy viên, BTC là ban tổ chức hay bitcoin) — việc của mô hình ngôn ngữ,
không phải của quy tắc.

Mọi quy tắc theo NGUYÊN TẮC về định dạng; hai danh sách duy nhất là tập ĐÓNG: đơn
vị đo (SI + thông dụng) và tên chữ cái tiếng Việt.
"""
from __future__ import annotations

import csv
import functools
import re
from pathlib import Path
from typing import Callable

TEN_CHU = {"A": "a", "B": "bê", "C": "xê", "D": "đê", "Đ": "đê", "E": "e", "F": "ép", "G": "gờ",
           "H": "hát", "I": "i", "J": "giây", "K": "ca", "L": "lờ", "M": "mờ", "N": "nờ", "O": "ô",
           "P": "phê", "Q": "qui", "R": "rờ", "S": "ét", "T": "tê", "U": "u", "V": "vê",
           "W": "vê kép", "X": "ích", "Y": "i", "Z": "dét"}
_PHU_AM = set("bcdfghjklmnpqrstvwxz")

#: Âm tiết đọc được (không cần dấu): phụ âm đầu? + nguyên âm + âm cuối?
_AM = r"(?:ch|gh|gi|kh|ng|nh|ph|qu|th|tr|[bcdfghjklmnpqrstvwxz])?[aeiouy]+(?:ng|nh|ch|[cmnpt])?"

_LA_MA = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}

#: Đơn vị đo đứng NGAY sau số — tập đóng. Chỉ những đơn vị sea_g2p đọc sai (đo
#: 25/09/2026); các đơn vị nó đọc đúng (km, kg, °C, %) để nó lo.
_DON_VI = {"ph": "phút", "V": "vôn", "W": "oát", "kW": "ki lô oát", "kWh": "ki lô oát giờ",
           "Ah": "am pe giờ", "mAh": "mi li am pe giờ", "h": "giờ", "S": "ét", "m": "mét",
           "Gbps": "gi ga bít trên giây", "Mbps": "mê ga bít trên giây",
           "Nm": "niu tơn mét", "kcal": "ki lô ca lo", "cal": "ca lo"}
_DON_VI_RE = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s?("
                        + "|".join(sorted(_DON_VI, key=len, reverse=True)) + r")(?![\w/])")


def danh_van(chu: str) -> str:
    return " ".join(TEN_CHU.get(c.upper(), c) for c in chu if c.isalpha())


def _doc_duoc(tu: str) -> bool:
    """Ghép được từ các âm tiết: "asean" (a-se-an), "fifa" — còn "dna", "url" thì không."""
    return bool(re.fullmatch(f"(?:{_AM})+", tu.lower()))


def _mot_am_tiet(tu: str) -> bool:
    return bool(re.fullmatch(_AM, tu.lower()))


class _SeaBiet:
    """Hỏi sea_g2p có TỪ ĐIỂN cho một chữ viết tắt không: cho nó đọc riêng chữ đó.

    Từ điển của sea_g2p nằm trong tệp nhị phân (không liệt kê được). Nó biết thì trả
    lời thật ("TP" → "thành phố", "GB" → "gigabyte"); không biết thì đánh vần hoặc
    để trơ phụ âm ("API" → "a p i") — nhận ra được từ chính câu trả lời.
    """

    def __init__(self, sea: Callable[[str], str]):
        self._sea = sea
        self._nho: dict[str, bool] = {}

    def biet(self, cum: str) -> bool:
        if cum not in self._nho:
            goc = cum.split()[-1]
            ra = [w for w in re.findall(r"\w+", self._sea(cum).lower()) if w != "một"]
            self._nho[cum] = not (" ".join(ra) == goc.lower() or all(len(w) == 1 for w in ra)
                                  or " ".join(ra) == danh_van(goc)
                                  or any(len(w) == 1 and w in _PHU_AM for w in ra))
        return self._nho[cum]


def _ha_tieu_de(t: str) -> str:
    tu = list(re.finditer(r"\w+", t))
    ra, cuoi, j = [], 0, 0
    while j < len(tu):
        k = j
        while (k < len(tu) and tu[k].group().isupper()
               and (k == j or re.fullmatch(r"[ \t]+", t[tu[k - 1].end():tu[k].start()]))):
            k += 1
        if k - j >= 2 and any(not w.group().isascii() for w in tu[j:k]):
            a, b = tu[j].start(), tu[k - 1].end()
            ra.append(t[cuoi:a] + t[a:b].lower())
            cuoi = b
        j = max(k, j + 1)
    return "".join(ra) + t[cuoi:]


def chuan_bi(t: str, sea: Callable[[str], str]) -> str:
    """Chữ hiển thị → chữ đã sửa các lớp lỗi có quy luật, rồi mới đưa sea_g2p."""
    sea_biet = _SeaBiet(sea)

    # Gạch đầu dòng "- 60%": dấu gạch CÓ khoảng trắng phía sau không phải dấu âm.
    t = re.sub(r"(?m)^(\s*)[-–•]\s+", r"\1", t)

    # Tiêu đề IN HOA ("TIN CẢNH BÁO LŨ QUÉT", "CAMERA GIÁM SÁT"): cụm ≥2 từ in hoa liền nhau,
    # có dấu tiếng Việt → đọc như chữ thường. Kiểm từng từ bằng isupper() — ĐỪNG dùng khoảng
    # ký tự: "à-ỹ" của Unicode xen kẽ cả chữ HOA có dấu (Ả, Ạ…), từng làm cụm bị cắt.
    t = _ha_tieu_de(t)

    # Số La Mã: hậu tố sau số/mã ("92-II", "0,05S-II", "95-V") và đứng riêng ≥2 chữ ("quý IV").
    t = re.sub(r"(?<=[\dA-Za-z])-(VIII|VII|VI|IV|IX|III|II|I|V|X)(?![\w])",
               lambda m: f" {_LA_MA[m.group(1)]}", t)
    t = re.sub(r"(?<![\w-])(VIII|VII|VI|IV|IX|III|II)(?![\w-])", lambda m: str(_LA_MA[m.group(1)]), t)

    # Nhãn mục "1a. … 1g. … 1h." — chỉ khi có CHUỖI nhãn; "đến 1h." đứng một mình là giờ.
    if len(re.findall(r"(?<![\w.,])\d{1,2}[a-z](?=\.\s)", t)) >= 2:
        t = re.sub(r"(?<![\w.,])(\d{1,2})([a-z])(?=\.\s)",
                   lambda m: f"{m.group(1)} {TEN_CHU[m.group(2).upper()]}", t)

    # Tên viết tắt có chấm "L.T.M.P", "N.V.Q." — đọc tên chữ, KHÔNG đọc "chấm".
    t = re.sub(r"(?<![\w.])(?:[A-ZĐ]\.){1,}[A-ZĐ](?![\w])\.?",
               lambda m: " ".join(TEN_CHU[c] for c in m.group(0) if c.isalpha()), t)

    # Đơn vị ngay sau số. "h" chỉ là giờ khi ≤ 24 — "350h" là tên mẫu (Lexus ES 350h).
    def _don_vi(m):
        if m.group(2) == "h" and float(m.group(1).replace(",", ".")) > 24:
            return m.group(0)
        return f"{m.group(1)} {_DON_VI[m.group(2)]}"
    t = _DON_VI_RE.sub(_don_vi, t)

    # Mã chữ-số ("CT4BX2", "GPT-5", "3WL", "DDR5-6400", "n8n", "ct4b-x2"): chữ đánh vần
    # kiểu Việt, số giữ cho sea đọc; gạch nối thành dấu phẩy để "5-6400" không dính số.
    def _ma(m):
        return re.sub(r"[A-Za-z]+", lambda k: f" {danh_van(k.group(0))} ", m.group(0)).replace("-", ", ")
    t = re.sub(r"(?<![\w.-])(?=[\w-]*\d)(?=[\w-]*[A-Z]{2})[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*(?![\w-])", _ma, t)
    t = re.sub(r"(?<![\w.-])(?=[a-z0-9]*\d)[a-z]+\d+[a-z]+[a-z0-9]*(?:-[a-z0-9]+)*(?![\w-])", _ma, t)

    # Số thập phân kiểu Anh: đúng một dấu chấm và 1–2 chữ số sau → dấu phẩy Việt.
    t = re.sub(r"(?<![\w.,])(\d+)\.(\d{1,2})(?![\d.,])", r"\1,\2", t)

    # Chữ viết tắt IN HOA đứng riêng: sea biết thì để sea; đọc được thành từ ("RAM",
    # "ASEAN") thì đọc từ; còn lại đánh vần kiểu Việt ("API" → "a phê i").
    def _vt(m):
        tu = m.group(0)
        if sea_biet.biet(tu):
            return tu
        if re.search(r"\d\s?$", t[max(0, m.start() - 3):m.start()]) and sea_biet.biet("1 " + tu):
            return tu                       # đơn vị sau số mà sea biết: "16 GB"
        if len(tu) >= 3 and (_mot_am_tiet(tu) or (len(tu) >= 4 and _doc_duoc(tu))):
            return tu.lower()
        return danh_van(tu)
    t = re.sub(r"(?<![\w&/-])[A-ZĐ]{2,6}(?:&[A-ZĐ]{2,4})?(?![\w-])", _vt, t)
    return phien_am_anh(t)


# ── Phiên âm từ tiếng Anh (25/09/2026, chủ máy: "có phiên âm các từ tiếng Anh chưa") ──
# Đo bằng cách cho giọng Nghị đọc "Từ tiếp theo là X." rồi để STT của c2a nghe lại:
# để nguyên chữ Anh chỉ ~18% từ được nhận ra ("google" → "graham le", "youtube" →
# "hù chùa") vì espeak-ng chuyển sang âm vị tiếng Anh mà giọng Nghị không được luyện;
# phiên âm theo từ điển → ~36% (250 từ: 130 từ câu trả lời thật + 120 từ tin tức).

_CO_DAU = "àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"
#: Âm tiết tiếng Việt viết KHÔNG dấu ("nghe", "xe", "pin", "bot") là tiếng Việt — không
#: phiên âm. Bộ nhận biết của chính VietNormalizer coi "nghe" là tiếng nước ngoài (và từ
#: điển có mục "nghe → nghê") — nên nhận biết bằng cấu tạo âm tiết, chỉ mượn TỪ ĐIỂN.
_AM_TIET_VIET = re.compile(
    r"(?:ngh|ng|nh|ch|gh|gi|kh|ph|qu|th|tr|[bcdđghklmnprstvx])?"
    r"(?:uye|uya|oai|oay|uoi|uou|uay|ieu|yeu|ai|ao|au|ay|eo|eu|ia|ie|iu|oa|oe|oi|ua|ue|ui|uo|uy|ye|[aeiouy])"
    r"(?:ng|nh|ch|[cmnpt])?")
_KY_HIEU_DO = {"km", "kg", "cm", "mm", "ml", "ph", "kw", "kwh", "mb", "gb", "ms", "hz"}


@functools.lru_cache(maxsize=1)
def _tu_dien_anh() -> dict[str, str]:
    """17.718 từ nước ngoài → cách đọc tiếng Việt, của VietNormalizer (MIT, xem
    data/phien_am_anh.LICENSE). Nạp một lần, lúc cần."""
    ra: dict[str, str] = {}
    with open(Path(__file__).with_name("data") / "phien_am_anh.csv", encoding="utf-8") as f:
        for dong in csv.DictReader(f):
            ra[dong["original"].strip().lower()] = dong["transliteration"].strip().replace("-", " ")
    return ra


def phien_am_anh(t: str) -> str:
    """Từ tiếng Anh LẪN trong câu tiếng Việt → cách đọc tiếng Việt ("YouTube" → "yu túp").

    Không đụng: âm tiết Việt không dấu, chữ IN HOA (viết tắt — việc của chuan_bi), ký
    hiệu đo, đoạn thuần tiếng Anh (phiên âm từng chữ vô nghĩa), chữ trong tên miền /
    đường dẫn / email ("google.com"). Từ không có trong từ điển: để nguyên như cũ.
    """
    tu_dien = _tu_dien_anh()

    def _thay(m):
        w = m.group(0)
        if len(w) < 2 or w.isupper() or _AM_TIET_VIET.fullmatch(w.lower()) or w.lower() in _KY_HIEU_DO:
            return w
        # Đoạn thuần tiếng Anh: tỉ lệ TỪ có dấu Việt quanh đó < 25% (câu Việt lẫn nhiều thuật
        # ngữ như "Home Assistant cập nhật firmware cho camera" vẫn 3/7; tiếng Anh là 0).
        quanh = re.findall(r"\w+", t[max(0, m.start() - 80):m.end() + 80].lower())
        if sum(any(c in _CO_DAU for c in x) for x in quanh) < 0.25 * len(quanh):
            return w
        return tu_dien.get(w.lower(), w)
    return re.sub(r"(?<![\w./@-])[A-Za-z][a-z]*(?:[A-Z][a-z]+)*(?![\w/@-]|\.\w)", _thay, t)


def don_cuoi(t: str) -> str:
    """Phụ âm Latinh trơn còn sót sau sea_g2p ("b p m") — giọng Việt không phát âm được."""
    return re.sub(r"(?<![\w])([bcdfghjklmnpqrstvwxz])(?![\w])", lambda m: TEN_CHU[m.group(1).upper()], t)
