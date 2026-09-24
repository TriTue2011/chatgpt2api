"""Đọc công thức hoá học bằng lời cho TTS tiếng Việt — chữ hiển thị giữ nguyên.

Chủ máy 24/09/2026: "Công thức hoá học tìm thêm xem có chuẩn hoá nào gộp vào
cho hoàn hảo". Không có thư viện nào đổi công thức sang lời đọc (OPSIN,
Chemical-Converters chỉ đổi giữa các dạng ký hiệu), và bộ chuẩn hoá chung
``sea_g2p`` đọc sai (đo cùng ngày): "3CO" → "ba co", "Mg" → "mi li gam",
"C6H12O6" → "…hát một hai…", "Fe³⁺" → "fe lập phương cộng", "Zn"/"Ag"/"Hg"
để nguyên, "⇌ ↑ ↓" bị xoá.

Nhận diện theo NGUYÊN TẮC, không theo danh sách từ: một chuỗi là công thức
khi tách được HẾT thành ký hiệu trong bảng tuần hoàn (118 nguyên tố — tập đóng
của khoa học) VÀ có dấu hiệu công thức (chỉ số, điện tích, ngoặc, hoặc chữ hoa
lẫn chữ thường kiểu NaCl). Nhờ vậy "Co giãn", "CON", "WHO" không bị đụng.
Trong câu có mũi tên phản ứng thì "CO", "NO" viết hoa cũng là công thức.

Cách đọc như lớp học: ký hiệu đánh vần bằng tên chữ cái ("ép e", "nờ a") —
cùng tên chữ cái mà sea_g2p dùng, nên giọng đọc thống nhất —, chỉ số đọc thành
số, "(OH)2" đọc "ô hát hai lần", điện tích "²⁻" đọc "hai trừ".
"""
from __future__ import annotations

import re

NGUYEN_TO = frozenset("""
H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu
Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba
La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi
Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds
Rg Cn Nh Fl Mc Lv Ts Og""".split())

#: Tên chữ cái — lấy đúng cách sea_g2p đọc từng chữ (đo 24/09/2026).
_CHU = {"A": "a", "B": "bê", "C": "xê", "D": "đê", "E": "e", "F": "ép", "G": "gờ",
        "H": "hát", "I": "i", "J": "giây", "K": "ca", "L": "lờ", "M": "mờ", "N": "nờ",
        "O": "ô", "P": "phê", "Q": "qui", "R": "rờ", "S": "ét", "T": "tê", "U": "u",
        "V": "vê", "W": "vê kép", "X": "ích", "Y": "y", "Z": "dét"}
_DUOI = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_TREN = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")
_PHAN_UNG = {"→": "tạo thành", "⟶": "tạo thành", "⇌": "thuận nghịch",
             "↑": "bay lên", "↓": "kết tủa"}
_SO = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]

#: Chữ số mũ KHÔNG liền mạch trong Unicode (¹²³ ở khối Latin-1, ⁰⁴…⁹ ở U+207x)
#: — khoảng "⁰-⁹" bỏ sót ²³, nên liệt kê đủ.
_MU = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻"
# Ứng viên: bắt đầu bằng hệ số/chữ hoa/ngoặc, không dính chữ phía trước.
_UNG_VIEN = re.compile(r"(?<![\w])\d*[A-Z(][A-Za-z0-9₀-₉()·." + _MU + r"^+\-]*")
_NGUYEN_TO_RE = re.compile(r"[A-Z][a-z]?")


def _la_so(c: str) -> bool:
    """Chỉ 0–9 THƯỜNG: str.isdigit() nhận cả "³", làm "Fe³⁺," đổ lỗi int()."""
    return "0" <= c <= "9"


def doc_so(n: int) -> str:
    """0–999 thành chữ (chỉ số, hệ số trong công thức không lớn hơn)."""
    if n < 10:
        return _SO[n]
    if n < 100:
        chuc, dv = divmod(n, 10)
        dau = "mười" if chuc == 1 else f"{_SO[chuc]} mươi"
        if dv == 0:
            return dau
        duoi = {1: "mốt" if chuc > 1 else "một", 4: "bốn", 5: "lăm"}.get(dv, _SO[dv])
        return f"{dau} {duoi}"
    tram, du = divmod(n, 100)
    if du == 0:
        return f"{_SO[tram]} trăm"
    return f"{_SO[tram]} trăm {'linh ' + _SO[du] if du < 10 else doc_so(du)}"


def _danh_van(ky_hieu: str) -> str:
    return " ".join(_CHU[c.upper()] for c in ky_hieu)


def _doc_phan(s: str) -> tuple[list[str], int] | None:
    """Đọc dãy nguyên tố/nhóm; trả (lời, số nguyên tố) hoặc None nếu không phải."""
    ra: list[str] = []
    dem = 0
    i = 0
    while i < len(s):
        if s[i] == "(":
            j = s.find(")", i)
            if j < 0:
                return None
            trong = _doc_phan(s[i + 1:j])
            if trong is None:
                return None
            k = j + 1
            while k < len(s) and _la_so(s[k]):
                k += 1
            ra += trong[0] + ([doc_so(int(s[j + 1:k])) + " lần"] if k > j + 1 else [])
            dem += trong[1]
            i = k
            continue
        m = _NGUYEN_TO_RE.match(s, i)
        if not m:
            return None
        ky = m.group(0)
        if ky not in NGUYEN_TO:
            return None
        k = i + len(ky)
        while k < len(s) and _la_so(s[k]):
            k += 1
        ra.append(_danh_van(ky) + (" " + doc_so(int(s[i + len(ky):k])) if k > i + len(ky) else ""))
        dem += 1
        i = k
    return (ra, dem) if ra else None


def doc_cong_thuc(token: str, *, trong_phan_ung: bool = False) -> str | None:
    """Lời đọc của MỘT công thức, hoặc None nếu chuỗi không phải công thức."""
    goc = token
    dien_tich = ""
    # Điện tích: số mũ ("²⁻"), dạng "^2-", hoặc viết thường "Fe3+" (MỘT chữ số
    # dính dấu). Không gộp chỉ số thường vào: "SO4²⁻" là "bốn" rồi "hai trừ".
    m = (re.search(r"([⁰¹²³⁴⁵⁶⁷⁸⁹]*[⁺⁻])$", token) or re.search(r"(\^\d*[+\-])$", token)
         or re.search(r"(?<=[A-Za-z)])(\d[+\-])$", token))
    if m:
        so = m.group(1).translate(_TREN).lstrip("^")
        dien_tich = (doc_so(int(so[:-1])) + " " if so[:-1] else "") + ("cộng" if so[-1] == "+" else "trừ")
        token = token[:m.start()]
    token = token.translate(_DUOI)
    phan = re.split(r"[·.](?=\d*[A-Z(])", token)
    loi: list[str] = []
    tong = 0
    for p in phan:
        he_so = re.match(r"\d*", p).group(0)
        than = p[len(he_so):]
        d = _doc_phan(than)
        if d is None:
            return None
        if loi:
            loi.append("chấm")
        loi += ([doc_so(int(he_so))] if he_so else []) + d[0]
        tong += d[1]
    co_dau_hieu = (bool(dien_tich) or any(_la_so(c) for c in goc.translate(_DUOI))
                   or "(" in goc or (tong >= 2 and any(c.islower() for c in goc)))
    if not (co_dau_hieu or (trong_phan_ung and tong >= 2)):
        return None
    return " ".join(loi + ([dien_tich] if dien_tich else []))


def doc(text: str) -> str:
    """Thay mọi công thức và ký hiệu phản ứng trong ``text`` bằng lời đọc."""
    if not text or not re.search(r"[A-Z(]", text):
        return text
    trong_phan_ung = any(k in text for k in _PHAN_UNG)

    def thay(m: re.Match) -> str:
        s = m.group(0)
        # Dấu câu dính cuối ("… H2SO4.") không thuộc công thức.
        duoi = ""
        while s and s[-1] in ".,;:!?-+":
            loi = doc_cong_thuc(s, trong_phan_ung=trong_phan_ung)
            if loi is not None:
                return loi + duoi
            duoi = s[-1] + duoi
            s = s[:-1]
        loi = doc_cong_thuc(s, trong_phan_ung=trong_phan_ung) if s else None
        return (loi if loi is not None else s) + duoi

    ra = _UNG_VIEN.sub(thay, text)
    for ky, loi in _PHAN_UNG.items():
        ra = ra.replace(ky, f" {loi} ")
    if trong_phan_ung:
        # "+" giữa các chất: ZeroTTS không tự đọc dấu này.
        ra = re.sub(r"\s\+\s", " cộng ", ra)
    return re.sub(r"[ \t]{2,}", " ", ra)
