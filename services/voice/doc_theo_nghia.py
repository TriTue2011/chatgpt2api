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

Lớp thêm tối 25/09/2026 (14 câu khó chủ máy thử): nghĩa chọn trên TOÀN VĂN trước khi
engine cắt câu; tiêu đề in hoa nuốt mất "GĐ BV"; viết tắt một nghĩa sea không biết
("BQL", "DNNN"); "NĐ-CP"; số La Mã tới 39 ("XXX"); "2-3 ngày" thành ngày tháng; "kết quả
3-1" thành phép trừ; "0 K" kelvin; đường dẫn web.

Sau khi sửa: 98,2% trên bộ ca cũ, 95,0% trên bộ ca MỚI (tin tức 25/09, gắn đáp án
trước khi chạy). Phần còn sai cần HIỂU NGHĨA (HCV = huy chương vàng, "UV" là tia
cực tím hay ủy viên, BTC là ban tổ chức hay bitcoin) — việc của mô hình ngôn ngữ,
không phải của quy tắc.

Mọi quy tắc theo NGUYÊN TẮC về định dạng; hai danh sách duy nhất là tập ĐÓNG: đơn
vị đo (SI + thông dụng) và tên chữ cái tiếng Việt.
"""
from __future__ import annotations

import csv
import functools
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Callable

TEN_CHU = {"A": "a", "B": "bê", "C": "xê", "D": "đê", "Đ": "đê", "E": "e", "F": "ép", "G": "gờ",
           "H": "hát", "I": "i", "J": "giây", "K": "ca", "L": "lờ", "M": "mờ", "N": "nờ", "O": "ô",
           "P": "phê", "Q": "qui", "R": "rờ", "S": "ét", "T": "tê", "U": "u", "V": "vê",
           "W": "vê kép", "X": "ích", "Y": "i", "Z": "dét"}
_PHU_AM = set("bcdfghjklmnpqrstvwxz")

#: Âm tiết đọc được (không cần dấu): phụ âm đầu? + nguyên âm + âm cuối?
_AM = r"(?:ch|gh|gi|kh|ng|nh|ph|qu|th|tr|[bcdfghjklmnpqrstvwxz])?[aeiouy]+(?:ng|nh|ch|[cmnpt])?"

_LA_MA = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9}


def _so_la_ma(s: str) -> int | None:
    """Giá trị số La Mã chỉ gồm I/V/X viết đúng luật (1–39); None nếu không phải."""
    m = re.fullmatch(r"(X{0,3})(IX|IV|VIII|VII|VI|V|III|II|I)?", s)
    if not m or not s:
        return None
    return 10 * len(m.group(1)) + _LA_MA.get(m.group(2) or "", 0)

#: Đơn vị đo đứng NGAY sau số — tập đóng. Chỉ những đơn vị sea_g2p đọc sai (đo
#: 25/09/2026); các đơn vị nó đọc đúng (km, kg, °C, %) để nó lo.
_DON_VI = {"ph": "phút", "V": "vôn", "W": "oát", "kW": "ki lô oát", "kWh": "ki lô oát giờ",
           "Ah": "am pe giờ", "mAh": "mi li am pe giờ", "h": "giờ", "S": "ét", "m": "mét",
           "Gbps": "gi ga bít trên giây", "Mbps": "mê ga bít trên giây",
           "Nm": "niu tơn mét", "kcal": "ki lô ca lo", "cal": "ca lo", "K": "ken vin"}
_DON_VI_RE = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s?("
                        + "|".join(sorted(_DON_VI, key=len, reverse=True)) + r")(?![\w/-])")


#: Mã tiền đứng NGAY SAU số là đơn vị tiền, không phải chữ viết tắt: "10 BTC" là mười
#: bitcoin (chủ máy 25/09/2026 nghe "mười BAN TỔ CHỨC"), "52 USD". Tập đóng: mã ISO 4217
#: thông dụng + vài đồng tiền số lớn. Không đứng sau số thì để nguyên ("BTC giải chạy").
#: Cách đọc ghi sẵn bằng âm tiết Việt — không trông vào bước phiên âm chạy sau (bước đó
#: bỏ qua câu ngắn ít dấu, "BTC trao giải 10 BTC" từng ra "bitcoin" để nguyên).
_TIEN = {"USD": "đô la Mỹ", "EUR": "ơ rô", "JPY": "yên Nhật", "CNY": "nhân dân tệ",
         "GBP": "bảng Anh", "KRW": "uôn Hàn Quốc", "SGD": "đô la Xin ga po", "THB": "bạt Thái",
         "AUD": "đô la Úc", "CAD": "đô la Ca na đa", "HKD": "đô la Hồng Kông", "TWD": "đài tệ",
         "CHF": "phrăng Thụy Sĩ", "INR": "ru pi Ấn Độ", "RUB": "rúp Nga", "MYR": "rinh gít Ma lai xi a",
         "IDR": "ru pi a In đô nê xi a", "VND": "đồng", "BTC": "bít côi", "ETH": "ê thơ ri um",
         "USDT": "u ét đê tê"}


# ── Chọn nghĩa chữ viết tắt NHIỀU NGHĨA theo ngữ cảnh (25/09/2026, chủ máy chọn "cách 1") ──
# Tự học, KHÔNG gắn nhãn tay: trong 2.155 bài tin tức, mỗi chỗ viết ĐẦY ĐỦ ("Chính phủ",
# "đội tuyển", "dịch vụ") là một mẫu có nhãn sẵn cho chữ viết tắt (CP, ĐT, DV). Đếm từ
# quanh từng nghĩa → Naive Bayes; mỗi chữ tự chọn cửa sổ / độ mịn / NGƯỠNG TIN CẬY trên phần
# kiểm định (dưới ngưỡng thì giữ nghĩa hay gặp nhất). Đo trên phần kiểm tra chưa dùng để
# chọn gì: 89,3% so với 67,8% nếu luôn đọc nghĩa hay gặp nhất (7.805 mẫu, 50 chữ). Danh
# sách nghĩa lấy từ từ điển của soe-vinorm (MIT, data/nghia_viet_tat.LICENSE). Công cụ học
# lại: /opt/claude-c2a/doc_dung/kho/hoc_nghia2.py (ngoài repo cùng kho văn bản).


@functools.lru_cache(maxsize=1)
def _mo_hinh_nghia() -> dict:
    with open(Path(__file__).with_name("data") / "nghia_viet_tat.json", encoding="utf-8") as f:
        return json.load(f)


def _tu_thuong(s: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFC", s.lower()).replace("uỷ", "ủy"))


def chon_nghia(vt: str, t: str, a: int, b: int, *, can_bang_chung: bool = False) -> str | None:
    """Nghĩa của chữ viết tắt ``vt`` (đứng ở t[a:b]) theo các từ quanh nó; None nếu không học.
    ``can_bang_chung``: không có từ nào quanh nó từng gặp thì None thay vì nghĩa hay gặp."""
    m = _mo_hinh_nghia().get(vt)
    if not m:
        return None
    w, k = m["w"], m.get("k", 1)
    trai = _tu_thuong(t[max(0, a - 200):a])[-w:]
    phai = _tu_thuong(t[b:b + 200])[:w]
    # Từ LIỀN KỀ tính k lần: "gọi ĐT" giữa câu toàn chuyện bóng đá vẫn là điện thoại. k=2 học
    # lại 26/09/2026: phần kiểm tra 89,2% → 89,3% (+8 mẫu), ĐT 92% → 93%; k=3 thì tụt 88,4%.
    f = ([f"w:{x}" for x in trai + phai] + ([f"L1:{trai[-1]}"] * k if trai else [])
         + ([f"R1:{phai[0]}"] * k if phai else []))
    # ``can_bang_chung`` (chuỗi ghép "ThS.BS", "NĐ-CP"): chỉ từ ĐÃ GẶP ở ít nhất một nghĩa
    # mới tính. Từ chưa gặp mà vẫn tính thì làm mượt kéo về nghĩa ÍT mẫu (mẫu số nhỏ hơn):
    # "ThS.BS" ra "biển số" (13 mẫu) thay vì "bác sĩ" (356 mẫu) vì chưa từng thấy "ths".
    # KHÔNG áp cho cả câu: ngưỡng `nguong` được chỉnh trên cách tính cũ, và đo 26/09/2026
    # áp toàn cục làm "Giá BTC hôm nay tăng" đổi từ bít côi (đúng) sang ban tổ chức.
    if can_bang_chung:
        f = [x for x in f if any(x in sn["dem"] for sn in m["nghia"].values())]
        if not f:
            return None
    diem = {ng: s["tien"] + sum(math.log((s["dem"].get(x, 0) + m["alpha"]) / (s["tong"] + m["alpha"] * m["v"]))
                                for x in f)
            for ng, s in m["nghia"].items()}
    hay = max(m["nghia"], key=lambda ng: m["nghia"][ng]["so_mau"])
    tot = max(diem, key=diem.get)
    return tot if tot == hay or diem[tot] - diem[hay] >= m["nguong"] else hay


# ── Chữ viết tắt MỘT nghĩa mà sea_g2p không biết ("BQL", "DNNN", "GĐ", "NĐ", "HCV") ──
# Từ điển soe-vinorm (MIT, data/nghia_viet_tat.LICENSE), chỉ mục IN HOA một nghĩa. Dùng SAU
# sea_g2p và sau "đọc được thành từ" ("SARS" vẫn là "sars"), TRƯỚC đánh vần. Chữ 2 ký tự quá
# nhập nhằng ("PC" = phiếu chuyển?, "HD", "SK" = sân khấu?) — đo 25/09/2026: dùng cả chữ 2 ký
# tự làm bộ ca cũ tụt 98,1% → 97,6%; chỉ ≥3 ký tự thì bộ tin tức mới lên 94,0% → 95,5%. Riêng
# chữ có "Đ" thì 2 ký tự vẫn dùng: viết tắt tiếng Anh không bao giờ có Đ, nên đó chắc chắn là
# lối viết tắt tiếng Việt, đọc bằng nghĩa ("GĐ" giám đốc, "NĐ" nghị định).


@functools.lru_cache(maxsize=1)
def _mot_nghia() -> dict[str, str]:
    with open(Path(__file__).with_name("data") / "viet_tat_mot_nghia.json", encoding="utf-8") as f:
        return json.load(f)


def _nghia_tu_dien(tu: str) -> str | None:
    return _mot_nghia().get(tu) if len(tu) >= 3 or "Đ" in tu else None


#: Chữ viết tắt IN HOA đứng riêng ("CP", "ĐT", "UBND", "R&D"), kể cả sau "/" trong số hiệu
#: văn bản ("100/2019/NĐ-CP").
_VT_RE = re.compile(r"(?<![\w&-])[A-ZĐ]{2,6}(?:&[A-ZĐ]{2,4})?(?![\w-])")
#: Như `_VT_RE`, trừ phần của chuỗi nối bằng dấu chấm ("PGS.TS", "ThS.BS"): nghĩa của nó
#: theo các phần đứng cạnh (`chuan_bi._cum_viet_tat`), không theo cả bài. Chuỗi mà
#: `_cum_viet_tat` không nhận (tên miền "VOV.VN") thì từng phần vẫn qua `_VT_RE` như cũ.
_VT_CA_BAI_RE = re.compile(r"(?<![\w&-])(?<![A-Za-zĐđ]\.)[A-ZĐ]{2,6}(?:&[A-ZĐ]{2,4})?(?![\w-])(?!\.[A-ZĐ])")


def _nghia_tai(tu: str, t: str, a: int, b: int) -> str | None:
    """Nghĩa theo ngữ cảnh của chữ viết tắt ở t[a:b]; None = không đoán ở đây."""
    if tu in _TIEN and re.search(r"\d\s?$", t[max(0, a - 3):a]):
        return None                         # "10 BTC" là đơn vị tiền — chuan_bi lo
    # Đứng ngay trước số là TÊN GỌI / MÃ ("ĐT 767" đường tỉnh, "BT.2020") — nghĩa có thể
    # nằm ngoài từ điển, đừng đoán.
    if re.match(r"\s?[.\-]?\d", t[b:b + 3]):
        return None
    return chon_nghia(tu, t, a, b)


def chon_nghia_ca_bai(t: str) -> str:
    """Chọn nghĩa chữ viết tắt NHIỀU NGHĨA trên CẢ BÀI, trước khi bài bị cắt thành câu/vế.

    Engine đọc theo câu (NghiTTS, Piper, Kokoro) cắt chữ ở dấu câu rồi mới chuẩn hoá
    từng mẩu — mẩu "CP chỉ đạo giảm 15% giá CP…" mất vế trước "UBND… họp với BQL dự án"
    nên chọn "cổ phiếu" (chủ máy nghe 25/09/2026; cả câu một lượt thì ra "Chính phủ").
    Mọi quyết định cần ngữ cảnh phải làm ở đây, một lần, trên toàn văn.
    """
    return _VT_CA_BAI_RE.sub(lambda m: _nghia_tai(m.group(0), t, m.start(), m.end()) or m.group(0), t)


#: Đơn vị thời gian và đơn vị đo thường gặp sau một khoảng số — tập đóng.
_KHOANG_RE = re.compile(
    r"(?<![\w/.,:-])(\d{1,4})-(\d{1,4})(?![\w/.,:-]|\.\d)(?=\s?(?:"
    r"giây|phút|giờ|tiếng|ngày|tuần|tháng|năm|tuổi|lần|người|km/h|km|m|cm|mm|kg|g|mg|l|lít|ml"
    r"|ha|độ|°C|%|triệu|tỷ|nghìn)(?![\wÀ-ỹ]))")

_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"'()]+[^\s<>\"'().,;:!?]", re.IGNORECASE)


def _nhan_mien(p: str) -> str:
    """Một nhãn tên miền: từ tiếng Anh có trong từ điển thì phiên âm ("google"), đọc được
    thành từ thì để ("com", "net"), ngắn mà không đọc được thì đánh vần ("vn")."""
    k = p.lower()
    if k in _tu_dien_anh():
        return _tu_dien_anh()[k]
    return danh_van(p) if len(p) <= 3 and p.isalpha() and not _doc_duoc(p) else p


def _doc_url(m: re.Match) -> str:
    u = re.sub(r"^(?:https?://)?(?:www\.)?", "", m.group(0), flags=re.IGNORECASE)
    u = re.split(r"[?#]", u, maxsplit=1)[0].rstrip("/")
    may, _, duong = u.partition("/")
    phan = [" chấm ".join(_nhan_mien(p) for p in may.split(".") if p)]
    phan += [re.sub(r"[-_.]+", " ", p) for p in duong.split("/") if p]
    return " gạch chéo ".join(phan)


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


def _bo_dau(tu: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", tu.lower().replace("đ", "d"))
                   if not unicodedata.combining(c))


def _la_tu_doc_duoc(tu: str) -> bool:
    """Một âm tiết Việt ("CẢNH", "NGHỆ") hay một từ ghép được âm tiết ("CAMERA"). Chữ viết
    tắt ("GĐ", "BV", "UBND") thì không — nó không phải một phần của tiêu đề in hoa."""
    k = _bo_dau(tu)
    return bool(_AM_TIET_VIET.fullmatch(k)) or (len(k) >= 4 and _doc_duoc(k))


def _ha_tieu_de(t: str) -> str:
    tu = list(re.finditer(r"\w+", t))
    ra, cuoi, j = [], 0, 0
    while j < len(tu):
        k = j
        while (k < len(tu) and tu[k].group().isupper() and _la_tu_doc_duoc(tu[k].group())
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

    # Số La Mã: hậu tố sau số/mã ("92-II", "0,05S-II", "95-V") và đứng riêng ≥2 chữ ("quý IV",
    # "lần thứ XXX", "thế kỷ XXI"). Chỉ nhận số viết ĐÚNG luật (tới 39) — "VIX" không phải số.
    t = re.sub(r"(?<=[\dA-Za-z])-([IVX]+)(?![\w])",
               lambda m: f" {n}" if (n := _so_la_ma(m.group(1))) else m.group(0), t)
    t = re.sub(r"(?<![\w-])([IVX]{2,})(?![\w-])",
               lambda m: str(n) if (n := _so_la_ma(m.group(1))) else m.group(0), t)

    # Nhãn mục "1a. … 1g. … 1h." — chỉ khi có CHUỖI nhãn; "đến 1h." đứng một mình là giờ.
    if len(re.findall(r"(?<![\w.,])\d{1,2}[a-z](?=\.\s)", t)) >= 2:
        t = re.sub(r"(?<![\w.,])(\d{1,2})([a-z])(?=\.\s)",
                   lambda m: f"{m.group(1)} {TEN_CHU[m.group(2).upper()]}", t)

    # Tên viết tắt có chấm "L.T.M.P", "N.V.Q." — đọc tên chữ, KHÔNG đọc "chấm".
    t = re.sub(r"(?<![\w.])(?:[A-ZĐ]\.){1,}[A-ZĐ](?![\w])\.?",
               lambda m: " ".join(TEN_CHU[c] for c in m.group(0) if c.isalpha()), t)

    # Đường dẫn web: bỏ "https://", "www."; tên miền đọc "chấm", đường dẫn "gạch chéo", bỏ phần
    # "?id=5" (sea đọc cả thành tiếng Anh: "colon slash slash … question mark … equals").
    t = _URL_RE.sub(_doc_url, t)

    # Số hiệu văn bản "15/2023/QH15", "100/2019/NĐ-CP" — dạng số/năm/ký hiệu (Nghị định
    # 30/2020/NĐ-CP về thể thức văn bản): đọc "15 năm 2023 QH15". sea đọc "/" là "trên":
    # "mười lăm trên hai nghìn … trên quốc hội" (chủ máy nghe 26/09/2026). Ký hiệu phải có
    # chữ in hoa nên ngày tháng "10/11/2025" không khớp. Ký hiệu một khối sea đã biết ("QH15"
    # → "quốc hội mười lăm") đọc ngay — tách khỏi "/" thì bước mã chữ-số sẽ đánh vần nó.
    t = re.sub(r"(?<![\w/])(\d{1,5})/((?:19|20)\d{2})/([A-ZĐ][A-ZĐ0-9]*(?:-[A-ZĐ][A-ZĐ0-9]*)*)(?![\w/])",
               lambda m: f"{m.group(1)} năm {m.group(2)} "
                         + (sea(m.group(3)) if "-" not in m.group(3) and sea_biet.biet(m.group(3))
                            else m.group(3)), t)
    # Khoảng ngày "10-21/11/2025" → "10 đến ngày 21/11/2025" (sea đọc "ngày mười ngày hai mươi mốt").
    t = re.sub(r"(?<![\w/.,-])(\d{1,2})-(\d{1,2})(?=/\d{1,2}(?:/\d{2,4})?(?![\w/]))",
               lambda m: f"{m.group(1)} đến ngày {m.group(2)}" if int(m.group(1)) < int(m.group(2))
               else m.group(0), t)
    # Khoảng số TĂNG DẦN ngay trước đơn vị thời gian / đơn vị đo: "2-3 ngày", "8-10 giờ",
    # "0-100 km/h". sea đọc nhầm thành ngày tháng ("ngày hai tháng ba ngày") hoặc mất "đến".
    # Chỉ khi tăng dần — "3-1", "2-0" là tỉ số; và chỉ trước đơn vị (tập đóng), vì sau cặp số
    # còn là tỉ số ("thua 1-3 trước Leeds").
    # Khoảng bắt đầu từ 0 phải có "từ": "xe chạy 0-100 km/h" đọc "chạy không đến một trăm"
    # nghe thành PHỦ ĐỊNH ("chạy không tới 100") — "không" vừa là số 0 vừa là "not" (chủ máy
    # 26/09/2026). Khoảng khác không thêm: "trong từ hai đến ba ngày" gượng.
    def _khoang(m):
        a, b = int(m.group(1)), int(m.group(2))
        if a >= b:
            return m.group(0)
        tu = "từ " if a == 0 and not re.search(r"\btừ\s*$", m.string[:m.start()]) else ""
        return f"{tu}{m.group(1)} đến {m.group(2)}"
    t = _KHOANG_RE.sub(_khoang, t)
    # Cặp số KHÔNG tăng ("3-1", "2-2") không bao giờ là khoảng, cũng không phải phép trừ trong
    # văn xuôi: sea đọc "kết quả 3-1" thành "ba TRỪ một", "trận 2-2" thành "hai ĐẾN hai". Là
    # ngày ("ngày 25-9", "sáng 3-1") thì sea tự nhận ra (đọc có "tháng") — hỏi chính sea với
    # từ đứng trước; không phải ngày thì là tỉ số: "ba một".
    def _cap_giam(m):
        a, b = int(m.group(2)), int(m.group(3))
        if a < b or "tháng" in sea(m.group(0)):
            return m.group(0)
        return f"{m.group(1)}{m.group(2)} {m.group(3)}"
    t = re.sub(r"((?:\S+\s+){0,2})(?<![\w/.,:-])(\d{1,3})-(\d{1,3})(?![\w/.,:-]|\.\d)", _cap_giam, t)

    # Chuỗi viết tắt nối bằng gạch nối ("NĐ-CP", "QĐ-UBND") hoặc dấu chấm ("PGS.TS",
    # "ThS.BS"): đọc CẢ CHUỖI, mỗi phần chọn nghĩa theo các phần đứng cạnh nó — không theo
    # cả câu. Theo cả câu thì "Nghị định 100/2019/NĐ-CP có hiệu lực" ra "nghị định CỔ PHIẾU"
    # (chủ máy nghe 26/09/2026), và "PGS.TS" còn trơ dấu chấm thành chỗ ngắt hơi.
    def _cum_viet_tat(m):
        phan = re.split(r"[-.]", m.group(0))
        if "." in m.group(0) and any(sum(c.isupper() for c in p) < 2 for p in phan):
            return m.group(0)           # "Google.Com" không phải chuỗi viết tắt
        cum = " ".join(phan)
        ra, vt = [], 0
        for p in phan:
            doc = (chon_nghia(p, cum, vt, vt + len(p), can_bang_chung=True)
                   or _nghia_tu_dien(p) or (sea(p) if sea_biet.biet(p) else None)
                   or (p if p in _mo_hinh_nghia() else None))
            if doc is None:
                return m.group(0)       # có phần lạ: để nguyên cho sea đọc cả chuỗi
            ra.append(doc)
            vt += len(p) + 1
        return " ".join(ra)
    t = re.sub(r"(?<![\w-])[A-ZĐ]{2,6}(?:-[A-ZĐ]{2,6})+(?![\w-])", _cum_viet_tat, t)
    t = re.sub(r"(?<![\w.])[A-ZĐ][A-Za-zĐđ]{1,5}(?:\.[A-ZĐ][A-Za-zĐđ]{1,5})+(?![\w])", _cum_viet_tat, t)

    # Đơn vị ngay sau số. "h" chỉ là giờ khi ≤ 24 — "350h" là tên mẫu (Lexus ES 350h).
    def _don_vi(m):
        if m.group(2) == "h" and float(m.group(1).replace(",", ".")) > 24:
            return m.group(0)
        # "0 K" là kelvin; "4K" (viết liền) là độ phân giải — để sea đọc "bốn ca".
        if m.group(2) == "K" and " " not in m.group(0):
            return m.group(0)
        return f"{m.group(1)} {_DON_VI[m.group(2)]}"
    t = _DON_VI_RE.sub(_don_vi, t)

    # Mã chữ-số ("CT4BX2", "GPT-5", "3WL", "DDR5-6400", "n8n", "ct4b-x2"): chữ đánh vần
    # kiểu Việt, số giữ cho sea đọc; gạch nối thành dấu phẩy để "5-6400" không dính số.
    def _chu_trong_ma(chu: str) -> str:
        # Phần chữ đọc thành từ được thì đọc từ, như viết tắt đứng riêng: "COP30" → "cop ba
        # mươi", "COVID-19" → "cô vít mười chín" (từ điển phiên âm); "GPT-5", "CT4B" đánh vần.
        k = chu.lower()
        if len(k) >= 3 and (_mot_am_tiet(k) or (len(k) >= 4 and _doc_duoc(k))):
            return k
        return _tu_dien_anh().get(k) if len(k) >= 4 and k in _tu_dien_anh() else danh_van(chu)

    def _ma(m):
        # Gạch nối giữa HAI SỐ thành dấu phẩy ("DDR5-6400": để "5-6400" không dính số); giữa
        # chữ và số chỉ là khoảng trắng — "COVID-19" đọc liền, không ngắt hơi "cô vít, mười chín".
        ra = re.sub(r"[A-Za-z]+", lambda k: f" {_chu_trong_ma(k.group(0))} ", m.group(0))
        return re.sub(r"(?<=\d)-(?=\d)", ", ", ra).replace("-", " ")
    t = re.sub(r"(?<![\w.-])(?=[\w-]*\d)(?=[\w-]*[A-Z]{2})[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*(?![\w-])", _ma, t)
    t = re.sub(r"(?<![\w.-])(?=[a-z0-9]*\d)[a-z]+\d+[a-z]+[a-z0-9]*(?:-[a-z0-9]+)*(?![\w-])", _ma, t)

    # Số thập phân kiểu Anh: đúng một dấu chấm và 1–2 chữ số sau → dấu phẩy Việt.
    t = re.sub(r"(?<![\w.,])(\d+)\.(\d{1,2})(?![\d.,])", r"\1,\2", t)

    # Chữ viết tắt IN HOA đứng riêng: sea biết thì để sea; đọc được thành từ ("RAM",
    # "ASEAN") thì đọc từ; còn lại đánh vần kiểu Việt ("API" → "a phê i").
    def _vt(m):
        tu = m.group(0)
        if tu in _TIEN and re.search(r"\d\s?$", t[max(0, m.start() - 3):m.start()]):
            return _TIEN[tu]
        if (nghia := _nghia_tai(tu, t, m.start(), m.end())) is not None:
            return nghia
        if sea_biet.biet(tu):
            return tu
        if re.search(r"\d\s?$", t[max(0, m.start() - 3):m.start()]) and sea_biet.biet("1 " + tu):
            return tu                       # đơn vị sau số mà sea biết: "16 GB"
        if len(tu) >= 3 and (_mot_am_tiet(tu) or (len(tu) >= 4 and _doc_duoc(tu))):
            return tu.lower()
        if nghia := _nghia_tu_dien(tu):
            return nghia
        return danh_van(tu)
    t = _VT_RE.sub(_vt, t)
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
