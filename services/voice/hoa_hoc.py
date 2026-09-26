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
lẫn chữ thường kiểu NaCl).

Ký hiệu ĐỨNG MỘT MÌNH xét theo NGỮ CẢNH (chủ máy 24/09/2026: "Mg và mg khác
nhau… Ca, Ba, La, Co căn cứ vào ngữ cảnh chứ không phải do từ"):
* không thể là âm tiết tiếng Việt (Mg, Zn, Fe, Hg, Cl… — xét bằng luật cấu tạo
  âm tiết, không bằng từ điển) → luôn là nguyên tố; "mg" viết thường không phải
  ký hiệu nên vẫn là mi-li-gam;
* có dáng âm tiết (Ca, Ba, La, Co, Na…) → là nguyên tố khi CÂU có ngữ cảnh hoá
  học: một công thức, hoặc một ký hiệu chắc chắn như Mg. "Ba mẹ đi làm" giữ
  nguyên; "Cho Ba vào H2SO4" đọc "bê a"; nhưng tên người thì không — "cô Na",
  "Thứ Ba", "Lê Văn Co" (xem ``_la_ten_nguoi``).

Không tự tạo ngữ cảnh (đo 25/09/2026 trên 2.000 câu trả lời thật, chủ máy hỏi
"giảm lỗi giữa tên người và ký hiệu hoá học"): chữ cái đơn (°C, hợp âm C–G–Am,
"bảng C"), mũi tên (chỉ đường "Hà Nội → Hải Phòng"), và chữ trong URL. Bản cũ
lấy "C" của "28.7°C" làm Cacbon nên bản tin sáng đọc "Thứ bê a".

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

#: Tên nguyên tố — tập đóng như chính bảng tuần hoàn. Ký hiệu đứng MỘT MÌNH trong câu là
#: nói về nguyên tố, đọc bằng tên ("nồng độ K trong máu" là kali — chủ máy 25/09/2026:
#: "không ai gọi là K"); trong công thức thì vẫn đánh vần như lớp học ("NaOH" → "nờ a ô
#: hát"). Ghi sẵn CÁCH ĐỌC bằng âm tiết Việt có dấu: viết kiểu sách ("magie", "iot",
#: "brom") thì bước phiên âm tiếng Anh chạy sau đọc thành "ma ghi", "ai ô ti", "brum".
TEN_NGUYEN_TO = dict(x.split(":") for x in """
H:hi_đrô He:hê_li Li:li_ti Be:bê_ri B:bo C:các_bon N:ni_tơ O:ô_xi F:phờ_lo Ne:nê_ông
Na:nát_tri Mg:ma_giê Al:nhôm Si:si_líc P:phốt_pho S:lưu_huỳnh Cl:cờ_lo Ar:a_gông K:ka_li
Ca:can_xi Sc:xcan_đi Ti:ti_tan V:va_na_đi Cr:crôm Mn:man_gan Fe:sắt Co:cô_ban Ni:ni_ken
Cu:đồng Zn:kẽm Ga:ga_li Ge:giéc_ma_ni As:a_xen Se:xê_len Br:brôm Kr:kríp_tôn Rb:ru_bi_đi
Sr:xtrôn_ti Y:y_tri Zr:di_cô_ni Nb:ni_ô_bi Mo:mô_líp_đen Tc:tếch_nê_ti Ru:ru_tê_ni Rh:rô_đi
Pd:pa_la_đi Ag:bạc Cd:ca_đi_mi In:in_đi Sn:thiếc Sb:an_ti_moan Te:tê_lu I:i_ốt Xe:xê_nông
Cs:xê_si Ba:ba_ri La:lan_tan Ce:xê_ri Pr:pra_xê_ô_đim Nd:nê_ô_đim Pm:prô_mê_ti Sm:sa_ma_ri
Eu:ơ_rô_pi Gd:ga_đô_li_ni Tb:téc_bi Dy:đi_xprô_xi Ho:hôn_mi Er:éc_bi Tm:tu_li Yb:y_téc_bi
Lu:lu_tê_xi Hf:háp_ni Ta:tan_tan W:vôn_fram Re:rê_ni Os:ô_xmi Ir:i_ri_đi Pt:pla_tin
Au:vàng Hg:thủy_ngân Tl:ta_li Pb:chì Bi:bít_mút Po:pô_lô_ni At:a_xta_tin Rn:ra_đông
Fr:phran_xi Ra:ra_đi Ac:ác_ti_ni Th:thô_ri Pa:prô_tác_ti_ni U:u_ra_ni Np:nép_tu_ni
Pu:plu_tô_ni Am:a_mê_ri_xi Cm:cu_ri Bk:béc_kê_li Cf:ca_li_phoóc_ni Es:anh_xtai_ni
Fm:phéc_mi Md:men_đê_lê_vi No:nô_bê_li Lr:lô_ren_xi Rf:rơ_dơ_phoóc_đi Db:đúp_ni
Sg:xi_bo_gi Bh:bô_ri Hs:ha_xi Mt:mai_nơ_ri Ds:đam_xta_đi Rg:rơn_ghen Cn:cô_péc_ni_xi
Nh:ni_hô_ni Fl:phlê_rô_vi Mc:mát_cô_vi Lv:li_vơ_mo_ri Ts:ten_nê_xin Og:ô_ga_nét_xôn""".split())
TEN_NGUYEN_TO = {k: v.replace("_", " ") for k, v in TEN_NGUYEN_TO.items()}
assert set(TEN_NGUYEN_TO) == NGUYEN_TO

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
# Ứng viên: bắt đầu bằng hệ số/chữ hoa/ngoặc, không dính chữ phía trước LẪN
# phía sau — thiếu đuôi (?!\w) thì "Nước" tách ra "N" + "ước" rồi thành "nờước".
# Chữ dính sau "°" là đơn vị nhiệt độ (°C, °F), không bao giờ là công thức.
_UNG_VIEN = re.compile(r"(?<![\w°])\d*[A-Z(][A-Za-z0-9₀-₉()·." + _MU + r"^+\-]*(?!\w)")
_NGUYEN_TO_RE = re.compile(r"[A-Z][a-z]?")
#: Cấu tạo âm tiết tiếng Việt viết không dấu: phụ âm đầu? + nguyên âm + âm cuối?
_AM_TIET = re.compile(r"(ngh|ng|nh|ch|gh|gi|kh|ph|qu|th|tr|[bcdghklmnprstvx])?"
                      r"[aeiouy]+(ng|nh|ch|[cmnptiyou])?")
#: Hết câu = dấu câu rồi khoảng trắng/hết chữ, hoặc xuống dòng — "CuSO4.5H2O",
#: "TP.HCM", "9.8" không phải chỗ hết câu.
_CAU = re.compile(r".+?(?:[.!?](?=\s|$)|\n|$)\s*", re.S)


def _dang_am_tiet(tu: str) -> bool:
    """Có thể là một âm tiết tiếng Việt không (không cần dấu) — "Ca" có, "Mg" không."""
    return bool(_AM_TIET.fullmatch(tu.lower()))


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


def doc_cong_thuc(token: str, *, ngu_canh: bool = False, viet: bool = True,
                  ten_nguyen_to: bool = True) -> str | None:
    """Lời đọc của MỘT công thức, hoặc None nếu chuỗi không phải công thức.

    ``ten_nguyen_to``: ký hiệu đứng một mình đọc bằng TÊN ("kali"); tắt trong phương trình
    phản ứng, nơi mọi chất đọc kiểu công thức ("ép e cộng xê u ét ô bốn…")."""
    # Chỉ gồm I/V/X, không chữ số: SỐ LA MÃ ("RON 95-III", "quý IV"), không phải công
    # thức — công thức ghi số lượng bằng chữ số (I2, V2O5). Đo 25/09/2026: "Galaxy S27"
    # tạo ngữ cảnh hoá học rồi "III" thành ba nguyên tố iốt, đọc "i i i".
    if re.fullmatch(r"[IVX]+[+\-]?", token.rstrip(".,;:!?")):
        return None
    # Số dính MỘT chữ cái đơn ("4K", "8K", "2G"): độ phân giải, thế hệ mạng… — cùng lý do
    # chữ cái đơn không tự tạo ngữ cảnh (đo 25/09/2026: "màn hình 4K" làm "Xe" thành xenon).
    if not ngu_canh and re.fullmatch(r"\d+[A-Z]", token.rstrip(".,;:!?")):
        return None
    goc = token
    dien_tich = ""
    # Điện tích: số mũ ("²⁻"), dạng "^2-", hoặc viết thường "Fe3+" (MỘT chữ số
    # dính dấu). Không gộp chỉ số thường vào: "SO4²⁻" là "bốn" rồi "hai trừ".
    m = (re.search(r"([⁰¹²³⁴⁵⁶⁷⁸⁹]*[⁺⁻])$", token) or re.search(r"(\^\d*[+\-])$", token)
         or re.search(r"(?<=[A-Za-z)])(\d?[+\-])$", token))
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
    # Chỉ số hoá học nhỏ (C6H12O6 lớn nhất 12). Không có ngữ cảnh hoá học mà chỉ số ≥ 20 là
    # TÊN MẪU / MÃ ("COP30", "S27", "U23"), không phải công thức (đo 25/09/2026: "COP30" →
    # "xê ô phê ba mươi").
    if not ngu_canh and any(int(x) >= 20 for x in re.findall(r"\d+", token)):
        return None
    co_dau_hieu = (bool(dien_tich) or any(_la_so(c) for c in goc.translate(_DUOI))
                   or "(" in goc or (tong >= 2 and any(c.islower() for c in goc)))
    if not co_dau_hieu:
        # Đứng một mình, không chỉ số: chắc chắn là nguyên tố khi không thể là
        # âm tiết tiếng Việt; có dáng âm tiết (Ca, Ba, CO) thì cần ngữ cảnh.
        # Luật âm tiết chỉ có nghĩa trong câu tiếng Việt ("As you know" là tiếng Anh).
        # CHỮ CÁI ĐƠN (C, K, V, F…) thì không: nó trùng đơn vị, hợp âm, chữ viết
        # tắt — đo 25/09/2026, "C" trong "28.7°C" từng biến bản tin sáng thành câu
        # hoá học. Nó chỉ là nguyên tố khi câu đã có ngữ cảnh; để nguyên thì bộ
        # chuẩn hoá phía sau vẫn đọc đúng tên chữ.
        if not (ngu_canh or (viet and tong == 1 and len(token) >= 2
                             and not _dang_am_tiet(token))):
            return None
        if ten_nguyen_to and token in TEN_NGUYEN_TO:
            return TEN_NGUYEN_TO[token]
    return " ".join(loi + ([dien_tich] if dien_tich else []))


_CO_DAU = re.compile("[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]",
                     re.IGNORECASE)


#: URL: chữ trong đó ("%C3%A0", "CT4BX2") không bao giờ là công thức.
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def _xoa_url(cau: str) -> str:
    """Thay URL bằng khoảng trắng CÙNG độ dài — vị trí các chữ khác giữ nguyên."""
    return _URL.sub(lambda m: " " * len(m.group(0)), cau)


#: Đơn vị LƯỢNG CHẤT của SI (mol và bội ước) chỉ dùng trong hoá học / xét nghiệm:
#: "Nồng độ K trong máu là 4,2 mmol/L" — K ở đây là kali.
_DON_VI_MOL = re.compile(r"(?<![\w])[mµnk]?mol(?![a-zà-ỹ])", re.IGNORECASE)


def _co_ngu_canh(cau: str, viet: bool) -> bool:
    """Câu có dấu hiệu hoá học chắc chắn: một công thức / ký hiệu nhận ra được mà
    KHÔNG cần ngữ cảnh, hoặc đơn vị lượng chất (mol, mmol/L).

    Mũi tên KHÔNG tự tạo ngữ cảnh: "Tây Na → Phường…", "Hà Nội → Hải Phòng" là
    chỉ đường. Phương trình thật luôn có công thức hai bên nên vẫn nhận ra."""
    if _DON_VI_MOL.search(_xoa_url(cau)):
        return True
    for m in _UNG_VIEN.finditer(_xoa_url(cau)):
        s = m.group(0).rstrip(".,;:!?")
        if s and doc_cong_thuc(s, viet=viet) is not None:
            return True
    return False


#: Từ xưng hô đứng trước tên người ("cô Na", "anh Ba"). Đây là chỗ DUY NHẤT phải
#: dựa vào từ: "bạn Na" và "kim loại Na" giống hệt nhau về mặt chữ, chỉ nghĩa từ
#: đứng trước mới phân biệt. Xưng hô tiếng Việt là lớp từ đóng của ngữ pháp —
#: như bảng tuần hoàn là tập đóng — nên không phải danh sách phải vá dần.
_XUNG_HO = frozenset("""
anh chị em cô chú bác dì cậu mợ thím dượng ông bà cụ thầy bạn bé con cháu
mẹ bố cha má u chồng vợ""".split())
_TU_TRUOC = re.compile(r"(\S+)[ \t]+$")


def _la_ten_nguoi(cau: str, vi_tri: int, viet: bool) -> bool:
    """Ký hiệu dáng âm tiết ở ``vi_tri`` là (một phần) tên người/tên riêng không.

    Hai dấu hiệu, xét từ ngay trước nó (chỉ cách bằng khoảng trắng):
    * một từ xưng hô: "Cô Na", "bạn Na", "Anh Ba";
    * một từ VIẾT HOA không đứng đầu câu và không phải ký hiệu/công thức: "Thứ
      Ba", "Lê Văn Co", "Nguyen Van Ba", "Tây Na". Đầu câu thì mọi từ viết hoa
      ("Cho Ba vào…"); danh sách "K Na Ca" thì từ trước là ký hiệu.
    """
    m = _TU_TRUOC.search(cau, 0, vi_tri)
    if not m:
        return False
    truoc = m.group(1)
    if not truoc[-1].isalnum():
        return False  # "Mg, Na": dấu câu ngắt, không phải tên nối tiếp
    if truoc.lower() in _XUNG_HO:
        return True
    if not truoc[0].isupper():
        return False
    if not cau[:m.start()].strip(" \t\n-–•*>\"'([{"):
        return False  # từ trước là từ đầu câu
    return doc_cong_thuc(truoc, ngu_canh=True, viet=viet) is None


def doc(text: str) -> str:
    """Thay mọi công thức và ký hiệu phản ứng trong ``text`` bằng lời đọc."""
    if not text or not re.search(r"[A-Z(]", text):
        return text
    return "".join(_doc_cau(m.group(0)) for m in _CAU.finditer(text)) or text


def _doc_cau(cau: str) -> str:
    viet = bool(_CO_DAU.search(cau))
    ngu_canh = _co_ngu_canh(cau, viet)
    trong_phan_ung = any(k in cau for k in _PHAN_UNG)

    trong_url = [u.span() for u in _URL.finditer(cau)]
    # Phương trình: mũi tên phản ứng hoặc "+" giữa các chất. "↑" "↓" chỉ ghi trạng thái (khí,
    # kết tủa), có cả trong câu văn ("tạo khí H2↑") — không làm câu thành phương trình.
    phuong_trinh = any(k in cau for k in "→⟶⇌") or bool(re.search(r"[\w)]\s\+\s[\dA-Z(]", cau))

    def thay(m: re.Match) -> str:
        s = m.group(0)
        if any(a <= m.start() < b for a, b in trong_url):
            return s
        tron = s.rstrip(".,;:!?-+")
        if (_NGUYEN_TO_RE.fullmatch(tron) and _dang_am_tiet(tron)
                and _la_ten_nguoi(cau, m.start(), viet)):
            return s
        # Ngay sau "số + khoảng trắng" là ĐƠN VỊ, không phải nguyên tố: "0 K" (kelvin),
        # "12 V", "5 N". Hệ số của công thức viết liền ("2Na").
        if _NGUYEN_TO_RE.fullmatch(tron) and re.search(r"\d[ \t]+$", cau[:m.start()]):
            return s
        # Dấu câu dính cuối ("… H2SO4.") không thuộc công thức.
        duoi = ""
        while s and s[-1] in ".,;:!?-+":
            loi = doc_cong_thuc(s, ngu_canh=ngu_canh, viet=viet, ten_nguyen_to=not phuong_trinh)
            if loi is not None:
                return loi + duoi
            duoi = s[-1] + duoi
            s = s[:-1]
        loi = doc_cong_thuc(s, ngu_canh=ngu_canh, viet=viet, ten_nguyen_to=not phuong_trinh) if s else None
        return (loi if loi is not None else s) + duoi

    ra = _UNG_VIEN.sub(thay, cau)
    # Mũi tên/dấu cộng chỉ là phản ứng trong câu có công thức; "Hà Nội → Hải
    # Phòng" giữ nguyên mũi tên.
    for ky, loi in (_PHAN_UNG.items() if ngu_canh else ()):
        # Ký hiệu chỉ nhắc lại chữ đã viết ngay trước ("tạo kết tủa BaSO4↓")
        # thì bỏ, không thì đọc thành "kết tủa … kết tủa".
        ra = re.sub(re.escape(ky), lambda m, loi=loi: " " if loi in m.string[max(0, m.start() - 40):m.start()]
                    else f" {loi} ", ra)
    if trong_phan_ung and ngu_canh:
        # "+" giữa các chất: ZeroTTS không tự đọc dấu này.
        ra = re.sub(r"\s\+\s", " cộng ", ra)
    return re.sub(r"[ \t]{2,}", " ", ra)
