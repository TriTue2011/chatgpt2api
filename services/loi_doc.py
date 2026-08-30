"""Chuẩn hoá bản dịch thành LỜI ĐỌC cho giọng máy — và HỌC lại cách đọc.

Vì sao cần: bản dịch tốt để ĐỌC BẰNG MẮT vẫn có thể không đọc THÀNH TIẾNG
được. Đo thật 30/08/2026 trên một video kỹ thuật 4 phút: 29/34 câu còn ít nhất
một chỗ giọng Việt không phát âm nổi — mã sản phẩm ``3wl`` (6 lần), cả cụm
``incoming feeder, distribution tie và outgoing feeder`` để nguyên tiếng Anh,
``PROFIBUS DP``, ``Modbus RTU``, ``shunt``, và ``Seamans`` (phụ đề tự sinh nghe
nhầm *Siemens*). Chủ máy nghe ra ngay: "lồng tiếng bị ngọng".

Luật chủ máy chốt 30/08/2026:

* **Tên người, tên hãng, địa danh, danh từ riêng** — đọc ĐÚNG tên đó, nhưng
  bằng PHIÊN ÂM tiếng Việt (``Siemens`` → "Xi-mừn"), không đánh vần.
* **Mã thiết bị** — đọc theo TIẾNG ĐÍCH (``3WL`` → "ba vê kép eo").
* Phụ đề để XEM giữ nguyên, chỉ bản dành cho giọng đọc mới được viết lại.

Thứ tự tra, để MẤT INTERNET VẪN CHẠY:

1. Kho ``<dich>.doc.json`` — cách đọc đã học ở những lượt trước. Tất định.
2. Kho thuật ngữ đã học ``<src>.hoc.json`` — do ``dich_llm.hoc_thuat_ngu`` ghi.
3. LLM, chỉ cho phần còn lại, rồi GHI NGƯỢC vào (1) để lần sau khỏi cần.

Không có model (hoặc không có mạng) thì bước 3 bỏ qua: câu nào chưa học được
cách đọc thì giữ nguyên như hiện nay, không bao giờ tệ hơn.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

GoiModel = Callable[[str, list[dict]], str]

#: Số chỗ khó đọc gửi đi hỏi trong MỘT lượt model.
CHO_MOI_LO = 40
#: Chỗ khó đọc dài hơn ngần này ký tự là đã trượt sang cả câu, không phải một
#: tên riêng hay mã thiết bị — bỏ, đừng nhờ model viết lại cả câu.
DAI_TOI_DA = 48

_DAU_VIET = set("àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩị"
                "òóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ")
#: Chữ cái KHÔNG có trong bảng chữ cái tiếng Việt — thấy là chắc chắn từ ngoại.
_CHU_NGOAI = set("fjwz")
_TU = re.compile(r"[0-9A-Za-zÀ-ỹ][0-9A-Za-zÀ-ỹ'’.-]*")

_khoa = threading.RLock()


class LoiLoiDoc(Exception):
    """Model trả lỗi / không gọi được."""


def _duong_kho(dich: str) -> Path:
    from services.config import DATA_DIR

    ma = str(dich or "vi").strip().lower()[:5] or "vi"
    return DATA_DIR / "glossary" / f"{ma}.doc.json"


def doc_kho(dich: str = "vi") -> dict[str, str]:
    """Kho cách đọc đã học. Hỏng tệp thì coi như rỗng, không chặn lồng tiếng."""
    p = _duong_kho(dich)
    try:
        d = json.loads(p.read_text("utf-8"))
    except Exception:
        return {}
    return {str(k): str(v) for k, v in d.items()
            if isinstance(d, dict) and str(k).strip() and str(v).strip()}


def ghi_kho(moi: dict[str, str], dich: str = "vi") -> int:
    """Gộp cách đọc mới vào kho. Trả số mục THẬT SỰ thêm được."""
    sach = {str(k).strip(): str(v).strip() for k, v in (moi or {}).items()
            if str(k).strip() and str(v).strip()}
    if not sach:
        return 0
    p = _duong_kho(dich)
    with _khoa:
        cu = doc_kho(dich)
        them = {k: v for k, v in sach.items() if k not in cu}
        if not them:
            return 0
        cu.update(them)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(cu, ensure_ascii=False, indent=2), "utf-8")
        except OSError as exc:
            logger.warning("không ghi được kho cách đọc: %s", str(exc)[:160])
            return 0
    return len(them)


def _sach(tu: str) -> str:
    """Bỏ dấu câu bám hai đầu, giữ nguyên ruột chữ."""
    return tu.strip("\"'“”‘’()[]{}<>.,;:!?…-–—")


def _co_dau_viet(tu: str) -> bool:
    return any(ch in _DAU_VIET for ch in unicodedata.normalize("NFC", tu).lower())


def la_ma_thiet_bi(tu: str) -> bool:
    """Lẫn CHỮ và SỐ trong một token → mã thiết bị (3WL, RS485, S7-1200)."""
    t = _sach(tu)
    return (len(t) >= 2 and any(c.isdigit() for c in t)
            and any(c.isalpha() for c in t))


def _kho_doc_mot_tu(t: str, goc: set[str]) -> bool:
    if len(t) < 2 or len(t) > DAI_TOI_DA or t.isdigit() or _co_dau_viet(t):
        return False
    return bool(la_ma_thiet_bi(t)
                or (t.lower() in goc and any(c.isalpha() for c in t))
                or any(ch in _CHU_NGOAI for ch in t.lower()))


def cho_kho_doc(cau_viet: str, cau_goc: str = "") -> list[str]:
    """Những chỗ trong câu tiếng Việt mà giọng Việt không đọc đúng được.

    Hai dấu hiệu, cố ý CHẶT để không bắt nhầm từ Việt không dấu (dao, minh,
    trang — đo thật 30/08: dò bằng "không có dấu thanh" bắt nhầm hàng loạt):

    1. Token lẫn chữ và số → mã thiết bị.
    2. Token cũng xuất hiện NGUYÊN VĂN trong câu GỐC → chữ ngoại còn sót lại
       chưa dịch. Đây là dấu hiệu chắc nhất và không cần bộ luật ngữ âm nào.

    Không có câu gốc thì chỉ còn dò được (1) và các token mang chữ f/j/w/z —
    những chữ cái không có trong bảng chữ cái tiếng Việt.

    Các chỗ khó ĐỨNG LIỀN NHAU (chỉ cách nhau khoảng trắng) được gộp thành MỘT
    cụm: kho thuật ngữ giữ nguyên cụm "incoming feeder", tách lẻ ra thì tra
    không thấy. Dấu phẩy cắt cụm, nên "feeder, distribution" không dính nhau.
    """
    cau = unicodedata.normalize("NFC", cau_viet or "")
    goc = {(_sach(t) or "").lower()
           for t in _TU.findall(unicodedata.normalize("NFC", cau_goc or ""))}
    cum: list[str] = []
    dang: list[str] = []
    het_truoc = -1
    for m in _TU.finditer(cau):
        t = _sach(m.group(0))
        lien = (het_truoc >= 0 and cau[het_truoc:m.start()].strip() == "")
        if _kho_doc_mot_tu(t, goc):
            if dang and not lien:
                cum.append(" ".join(dang))
                dang = []
            dang.append(t)
        elif dang:
            cum.append(" ".join(dang))
            dang = []
        het_truoc = m.end()
    if dang:
        cum.append(" ".join(dang))
    ra: list[str] = []
    for c in cum:
        if c and c not in ra:
            ra.append(c)
    return ra


def _thay(cau: str, bang: dict[str, str]) -> str:
    """Thay từng chỗ khó đọc bằng cách đọc đã biết, khớp CẢ TỪ, không phân biệt
    hoa thường. Thay chỗ DÀI trước để "incoming feeder" không bị "feeder" ăn mất."""
    ra = cau
    for k in sorted(bang, key=len, reverse=True):
        v = bang[k]
        if not v:
            continue
        mau = re.compile(rf"(?<![0-9A-Za-zÀ-ỹ]){re.escape(k)}(?![0-9A-Za-zÀ-ỹ])",
                         re.IGNORECASE)
        ra = mau.sub(lambda _m: v, ra)
    return ra


def _hoi_model(cho: list[str], nhac: str, model: str,
               goi_model: GoiModel) -> dict[str, str]:
    """Hỏi cách đọc cho các chỗ chưa học được. Hỏng → trả rỗng."""
    system = (
        "Bạn chuẩn bị LỜI ĐỌC tiếng Việt cho máy đọc văn bản. Người dùng đưa "
        "danh sách những chỗ mà giọng đọc tiếng Việt không phát âm được. Với "
        "MỖI chỗ, cho biết phải VIẾT LẠI thành chữ gì để giọng Việt đọc lên "
        "nghe đúng:\n"
        "1. Tên người, tên hãng, địa danh, danh từ riêng: giữ ĐÚNG tên đó "
        "nhưng viết bằng PHIÊN ÂM tiếng Việt theo cách đọc thật của nó "
        "(Siemens → Xi-mừn, Schneider → Sờ-nai-đơ). KHÔNG đánh vần từng chữ.\n"
        "2. Mã thiết bị, mã model, ký hiệu: đọc theo TIẾNG VIỆT, đánh vần "
        "từng ký tự bằng tên chữ cái tiếng Việt (3WL → ba vê kép eo).\n"
        "3. Từ hoặc cụm từ thông thường chưa được dịch: DỊCH sang tiếng Việt.\n"
        "Lời thoại có thể do máy nghe sai chính tả tên riêng; hãy đọc theo tên "
        "ĐÚNG mà nó định nói.\n"
        'Trả về DUY NHẤT một mảng JSON, mỗi phần tử {"goc": "chỗ đó", '
        '"doc": "cách viết để đọc"}. Không giải thích, không văn xuôi.'
    )
    user = (f"Lĩnh vực: {nhac or 'chung'}.\nCác chỗ cần cách đọc:\n"
            + "\n".join(f"- {x}" for x in cho))
    try:
        raw = goi_model(model, [{"role": "system", "content": system},
                                {"role": "user", "content": user}])
    except Exception as exc:
        logger.warning("hỏi cách đọc lỗi: %s", str(exc)[:160])
        return {}
    s = re.sub(r"^```(?:json)?|```$", "", str(raw or "").strip(), flags=re.MULTILINE)
    m = re.search(r"\[.*\]", s, re.DOTALL)
    if not m:
        return {}
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return {}
    hop = {x.lower() for x in cho}
    bang: dict[str, str] = {}
    for x in arr:
        if not isinstance(x, dict):
            continue
        g = str(x.get("goc") or "").strip()
        d = str(x.get("doc") or "").strip()
        # Chỉ nhận đúng những chỗ đã hỏi, và cách đọc phải là chữ THẬT (có dấu
        # hoặc ít nhất không còn là chính nó) — model trả lại y nguyên nghĩa là
        # nó không biết, giữ nguyên còn hơn ghi vào kho một mục vô dụng.
        if g.lower() in hop and d and d.lower() != g.lower() and len(d) <= 120:
            bang[g] = d
    return bang


def chuan_hoa(cau_viet: list[str], cau_goc: list[str] | None = None, *,
              nguon: str = "", dich: str = "vi", model: str = "",
              goi_model: GoiModel | None = None,
              linh_vuc: list[str] | None = None) -> tuple[list[str], int, int]:
    """Bản dịch → LỜI ĐỌC. Trả ``(câu đã sửa, số chỗ sửa, số cách đọc học mới)``.

    Danh sách trả về CÙNG ĐỘ DÀI, cùng thứ tự. Chỗ nào chưa biết cách đọc thì
    giữ nguyên — không bao giờ tệ hơn đầu vào.
    """
    if not cau_viet:
        return list(cau_viet), 0, 0
    goc = list(cau_goc or [])
    goc += [""] * (len(cau_viet) - len(goc))

    cho_theo_cau = [cho_kho_doc(v, g) for v, g in zip(cau_viet, goc)]
    tat_ca: list[str] = []
    for ds in cho_theo_cau:
        for x in ds:
            if x not in tat_ca:
                tat_ca.append(x)
    if not tat_ca:
        return list(cau_viet), 0, 0

    bang = dict(_tu_kho_da_hoc(tat_ca, nguon, dich))
    con = [x for x in tat_ca if x not in bang]
    hoc_moi = 0
    if con and model and goi_model is not None:
        nhac = ", ".join(linh_vuc or []).replace("_", " ")
        moi: dict[str, str] = {}
        for i in range(0, len(con), CHO_MOI_LO):
            moi.update(_hoi_model(con[i:i + CHO_MOI_LO], nhac, model, goi_model))
        if moi:
            bang.update(moi)
            hoc_moi = ghi_kho(moi, dich)

    ra, so_sua = [], 0
    for v, ds in zip(cau_viet, cho_theo_cau):
        rieng = {k: bang[k] for k in ds if k in bang}
        if not rieng:
            ra.append(v)
            continue
        moi_cau = _thay(v, rieng)
        so_sua += len(rieng)
        ra.append(moi_cau)
    return ra, so_sua, hoc_moi


def _tu_kho_da_hoc(cho: list[str], nguon: str, dich: str) -> dict[str, str]:
    """Cách đọc lấy được mà KHÔNG cần mạng: kho cách đọc, rồi kho thuật ngữ."""
    kho = {k.lower(): v for k, v in doc_kho(dich).items()}
    bang = {x: kho[x.lower()] for x in cho if x.lower() in kho}
    thieu = [x for x in cho if x not in bang]
    if not thieu:
        return bang
    # Thuật ngữ do dich_llm.hoc_thuat_ngu học được ở các lượt trước — chính là
    # nơi đang giữ 'incoming feeder' → 'bộ cấp nguồn vào'.
    try:
        from services import thuat_ngu as tn

        src = str(nguon or "").strip().lower()[:2]
        if src:
            gop: dict[str, str] = {}
            for bang_lv in (tn.nap_glossary(src) or {}).values():
                if isinstance(bang_lv, dict):
                    gop.update({str(k).lower(): str(v) for k, v in bang_lv.items()})
            for x in thieu:
                v = gop.get(x.lower())
                if v:
                    bang[x] = v
                    continue
                # Cụm nhiều chữ tra không thấy thì gỡ từng chữ ra tra tiếp:
                # thà đọc đúng được một nửa còn hơn ngọng cả cụm.
                for w in x.split():
                    wv = gop.get(w.lower()) or kho.get(w.lower())
                    if wv:
                        bang[w] = wv
    except Exception as exc:
        logger.info("không đọc được kho thuật ngữ: %s", str(exc)[:120])
    return bang
