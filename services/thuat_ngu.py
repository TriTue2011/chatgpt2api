"""Glossary thuật ngữ + hậu kỳ (KHÔNG LLM) cho dịch phụ đề / lồng tiếng.

Kiến trúc chốt với chủ máy:
    NLLB dịch thô  →  HẬU KỲ thay thuật ngữ theo glossary lĩnh vực (module này,
    tất định, không LLM)  →  (bước sau) LLM chỉnh nghĩa-ngữ-cảnh + mượt câu.

Vì sao hậu kỳ chứ không nhồi glossary vào NLLB: repo đã có tiền lệ thất bại —
NLLB/Marian bỏ qua token che (``video_dich`` ghi rõ, CTranslate2 #1798). Cách
chạy được là XỬ LÝ PHÍA ĐÍCH: dịch xong rồi thay chuỗi.

Glossary lưu ở ``<data>/glossary/<src>.json`` (src = mã tiếng nguồn: en/ja/zh/ko):

    {
      "<lĩnh vực>": { "<term nguồn thường hoá>": "<thuật ngữ VI chuẩn>", ... },
      ...
    }

Trình nạp (OMW / Wiktionary-kaikki / FreeDict / CC-CEDICT) sẽ GHI ra đúng dạng
này — nằm ở bước sau. Module này chỉ lo ĐỌC glossary, đoán lĩnh vực, và thay
thuật ngữ; tách vậy để phần lõi test được mà không cần mạng.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

#: Số term nguồn của một lĩnh vực phải BẮT GẶP trong bản thoại thì mới coi video
#: thuộc lĩnh vực đó. Đặt ngưỡng để một hai từ trùng ngẫu nhiên không kéo nhầm
#: cả glossary y khoa vào một video nấu ăn.
NGUONG_LINH_VUC = 3

#: Trần số lĩnh vực áp cùng lúc: video có thể chạm nhiều ngành (một bài giảng kỹ
#: thuật vẫn nói xen đời thường), nhưng nhồi mọi glossary vào là mời gọi thay
#: nhầm. Lấy các lĩnh vực điểm cao nhất.
TOI_DA_LINH_VUC = 3


def _thu_muc_glossary() -> Path:
    """Thư mục chứa glossary. Đọc ``DATA_DIR`` từ namespace của config lúc gọi
    (giống ``config.images_dir``) để test chỉnh được đường trước khi nạp."""
    import services.config as _cfg
    return _cfg.DATA_DIR / "glossary"


def thuong_hoa(s: str) -> str:
    """Thường hoá một cụm để so khớp: bỏ dấu câu rìa, gộp khoảng trắng, hạ chữ.

    KHÔNG bỏ dấu tiếng Việt (thuật ngữ VI cần đúng dấu); chỉ chuẩn hoá Unicode
    về NFC để 'ộ' dựng sẵn và tổ hợp so khớp như nhau.
    """
    s = unicodedata.normalize("NFC", str(s or ""))
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _doc_glossary_file(tep: Path) -> dict[str, dict[str, str]]:
    """Đọc một tệp glossary → {lĩnh vực: {term nguồn đã THƯỜNG HOÁ: thuật ngữ VI}}.

    Thiếu tệp trả rỗng; tệp hỏng cũng trả rỗng (ghi cảnh báo). Thường hoá khoá
    ngay lúc đọc để khớp không phụ thuộc hoa/thường.
    """
    try:
        raw = json.loads(tep.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("glossary %s hỏng, bỏ qua: %s", tep, str(exc)[:200])
        return {}
    goi: dict[str, dict[str, str]] = {}
    if isinstance(raw, dict):
        for linh_vuc, cap in raw.items():
            if not isinstance(cap, dict):
                continue
            goi[str(linh_vuc)] = {
                thuong_hoa(k): str(v)
                for k, v in cap.items()
                if str(k).strip() and str(v).strip()
            }
    return goi


class _KhoTinh:
    """Bộ nhớ đệm glossary đã nạp theo tiếng nguồn (đọc file một lần)."""

    def __init__(self) -> None:
        self._theo_src: dict[str, dict[str, dict[str, str]]] = {}
        self._da_doc: set[str] = set()
        #: Bảng SỬA TAY đã làm phẳng (bỏ lĩnh vực) — dùng ở MỌI lượt dịch chữ
        #: nên không đọc lại file mỗi lần. ``xoa()`` dọn cùng lúc với phần trên.
        self._sua_phang: dict[str, list[tuple[str, str]]] = {}

    def nap(self, src: str) -> dict[str, dict[str, str]]:
        src = str(src or "").lower().strip()
        if src in self._da_doc:
            return self._theo_src.get(src, {})
        self._da_doc.add(src)
        thu_muc = _thu_muc_glossary()
        # Bản CURATED (dựng từ termbase) là chuẩn. Bản TỰ HỌC (<src>.hoc.json,
        # chắt lọc từ LLM) chỉ BỔ SUNG term chưa có — curated luôn thắng khi trùng.
        goi = _doc_glossary_file(thu_muc / f"{src}.json")
        for lv, cap in _doc_glossary_file(thu_muc / f"{src}.hoc.json").items():
            ban = goi.setdefault(lv, {})
            for term, vi in cap.items():
                ban.setdefault(term, vi)
        # Bản NGƯỜI DÙNG SỬA (<src>.sua.json) THẮNG tất cả — sửa lỗi thì phải
        # đè cả curated lẫn tự học, và có hiệu lực ngay lượt dịch sau.
        for lv, cap in _doc_glossary_file(thu_muc / f"{src}.sua.json").items():
            ban = goi.setdefault(lv, {})
            for term, vi in cap.items():
                ban[term] = vi
        self._theo_src[src] = goi
        return goi

    def sua_phang(self, src: str) -> list[tuple[str, str]]:
        src = str(src or "").lower().strip()
        if src not in self._sua_phang:
            gop: dict[str, str] = {}
            for cap in _doc_glossary_file(_thu_muc_glossary() / f"{src}.sua.json").values():
                for term, vi in cap.items():
                    if term and vi:
                        gop[term] = vi
            self._sua_phang[src] = list(gop.items())
        return self._sua_phang[src]

    def xoa(self) -> None:
        self._theo_src.clear()
        self._da_doc.clear()
        self._sua_phang.clear()


_KHO = _KhoTinh()


def nap_glossary(src: str) -> dict[str, dict[str, str]]:
    """Glossary của một tiếng nguồn: {lĩnh vực: {term nguồn: thuật ngữ VI}}."""
    return _KHO.nap(src)


def _reset_cache_cho_test() -> None:
    _KHO.xoa()


def ghi_hoc(src: str, moi: dict[str, dict[str, str]]) -> int:
    """Thêm thuật ngữ TỰ HỌC (chắt lọc từ LLM) vào ``<src>.hoc.json``.

    Chỉ thêm term CHƯA có trong bản curated (``<src>.json``) lẫn bản học sẵn —
    tuyệt đối không đè thuật ngữ đã chuẩn. Trả số term thực thêm mới, và xoá
    cache để lượt dịch sau dùng được ngay. ``moi`` = {lĩnh vực: {term: thuật ngữ VI}}.
    """
    src = str(src or "").lower().strip()
    if not src or not moi:
        return 0
    thu_muc = _thu_muc_glossary()
    thu_muc.mkdir(parents=True, exist_ok=True)
    base = _doc_glossary_file(thu_muc / f"{src}.json")
    tep_hoc = thu_muc / f"{src}.hoc.json"
    hoc = _doc_glossary_file(tep_hoc)   # khoá đã thường hoá
    them = 0
    for lv, cap in moi.items():
        if not isinstance(cap, dict):
            continue
        lv = str(lv)
        base_lv = base.get(lv, {})
        hoc_lv = hoc.setdefault(lv, {})
        for term, vi in cap.items():
            term_n = thuong_hoa(term)
            vi_s = str(vi).strip()
            if not term_n or not vi_s or term_n in base_lv or term_n in hoc_lv:
                continue
            hoc_lv[term_n] = vi_s
            them += 1
    if them:
        sach = {lv: cap for lv, cap in hoc.items() if cap}
        tep_hoc.write_text(json.dumps(sach, ensure_ascii=False, indent=1),
                           encoding="utf-8")
        _KHO.xoa()
    return them


LINH_VUC_NHAN: dict[str, str] = {
    "cong_nghe": "Công nghệ", "ky_thuat": "Kỹ thuật", "toan_hoc": "Toán học",
    "vat_ly": "Vật lý", "hoa_hoc": "Hóa học", "sinh_hoc": "Sinh học",
    "y_khoa": "Y khoa", "tam_ly": "Tâm lý", "phap_ly": "Pháp lý",
    "tai_chinh": "Tài chính", "kinh_doanh": "Kinh doanh", "quan_su": "Quân sự",
    "am_nhac": "Âm nhạc", "ngon_ngu": "Ngôn ngữ", "thien_van": "Thiên văn",
    "dia_chat": "Địa chất", "am_thuc": "Ẩm thực", "the_thao": "Thể thao",
    "hang_hai": "Hàng hải", "hang_khong": "Hàng không", "kien_truc": "Kiến trúc",
}


def danh_sach_linh_vuc() -> list[dict[str, str]]:
    """[{'slug','ten'}] cho ô chọn lĩnh vực trên UI (thứ tự khai bên trên)."""
    return [{"slug": s, "ten": t} for s, t in LINH_VUC_NHAN.items()]


def doc_sua(src: str) -> dict[str, dict[str, str]]:
    """Bảng người dùng SỬA của một tiếng — đọc thẳng file, để UI liệt kê."""
    return _doc_glossary_file(_thu_muc_glossary() / f"{str(src or '').lower().strip()}.sua.json")


def _ghi_sua_file(src: str, bang: dict[str, dict[str, str]]) -> None:
    tep = _thu_muc_glossary() / f"{src}.sua.json"
    tep.parent.mkdir(parents=True, exist_ok=True)
    tep.write_text(json.dumps({lv: cap for lv, cap in bang.items() if cap},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    _KHO.xoa()


def ghi_sua(src: str, linh_vuc: str, term: str, vi: str) -> None:
    """Thêm/ghi đè một sửa tay vào ``<src>.sua.json`` (thắng mọi tầng). Xoá cache."""
    src = str(src or "").lower().strip()
    lv = str(linh_vuc or "").strip()
    term_n = thuong_hoa(term)
    vi_s = str(vi or "").strip()
    if not (src and lv and term_n and vi_s):
        raise ValueError("thiếu tiếng / lĩnh vực / từ gốc / từ Việt")
    bang = doc_sua(src)
    bang.setdefault(lv, {})[term_n] = vi_s
    _ghi_sua_file(src, bang)


def xoa_sua(src: str, linh_vuc: str, term: str) -> bool:
    """Bỏ một sửa tay. Trả True nếu có xoá."""
    src = str(src or "").lower().strip()
    lv = str(linh_vuc or "").strip()
    term_n = thuong_hoa(term)
    bang = doc_sua(src)
    if term_n not in bang.get(lv, {}):
        return False
    del bang[lv][term_n]
    _ghi_sua_file(src, bang)
    return True


# ── Thuật ngữ NGƯỜI DÙNG tự thêm: áp thẳng, KHÔNG qua đoán lĩnh vực ─────────
# Đoán lĩnh vực (``doan_linh_vuc``) sinh ra để bảo vệ văn bản DÀI khỏi một từ
# trùng ngẫu nhiên. Từ do người dùng gõ tay ở tab Dịch thì không cần lớp bảo vệ
# đó — họ đã nói rõ ý rồi. Lỗi thật đã gặp: thêm "stroke → đột quỵ" xong gõ mỗi
# chữ "stroke", văn bản không đủ 3 thuật ngữ y khoa nên không lĩnh vực nào được
# nhận, và bản sửa tay chưa bao giờ có cơ hội chạy.


#: Mẫu khớp-nguyên-từ đã biên dịch, theo term. ``None`` = term không viết bằng
#: chữ Latin nên phải khớp chuỗi con (Nhật/Trung viết không cách từ).
_MAU_CA_TU: dict[str, re.Pattern[str] | None] = {}
_LA_LATIN = re.compile(r"[a-z0-9][a-z0-9\s\-'.&/]*", re.ASCII)


def co_trong(term: str, hay: str) -> bool:
    """``term`` (đã thường hoá) có xuất hiện trong ``hay`` (đã thường hoá) không.

    Term viết bằng chữ Latin phải khớp NGUYÊN TỪ. Kho có những term rất ngắn —
    'la', 'mi', 'fa' là nốt nhạc, 'ok', 'hip', 'app' — mà khớp lỏng thì chúng
    nằm sẵn trong 'player', 'important', 'fact', 'look', 'ship'. Hệ quả đã đo
    được: mọi bản thoại tiếng Anh đều đủ ba lần khớp và bị chấm là ÂM NHẠC.

    Tiếng Nhật/Trung viết không cách từ nên không có biên chữ để tựa vào; term
    của các tiếng đó giữ nguyên lối khớp chuỗi con.
    """
    if term not in _MAU_CA_TU:
        _MAU_CA_TU[term] = (
            re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)")
            if _LA_LATIN.fullmatch(term) else None)
    mau = _MAU_CA_TU[term]
    return bool(mau.search(hay)) if mau is not None else term in hay


def cap_nguoi_dung(src: str) -> list[tuple[str, str]]:
    """[(term nguồn, thuật ngữ VI)] người dùng TỰ THÊM cho tiếng ``src``.

    Gộp mọi lĩnh vực trong ``<src>.sua.json`` — lúc áp không hỏi lĩnh vực nữa.
    Trùng term giữa hai lĩnh vực thì bản đọc sau thắng; hiếm, và cả hai đều là
    ý người dùng nên không có lựa chọn nào đúng hơn.
    """
    return _KHO.sua_phang(src)


def tach_thuat_ngu(text: str, cap: list[tuple[str, str]]) -> list[tuple[bool, str]]:
    """Cắt đoạn thành [(gửi_máy_dịch, chữ)] — thuật ngữ thành mảnh KHOÁ đã mang
    sẵn bản dịch bắt buộc, phần còn lại để máy dịch lo.

    Đây là cách DeepL glossary và Microsoft dynamic dictionary làm: không "dạy"
    engine mà THAY trước rồi chỉ dịch phần còn lại, nên thuật ngữ ra đúng trăm
    lần như một, với mọi engine, 0 token.

    Khớp không phân biệt hoa thường và ưu tiên cụm DÀI trước ("short circuit
    breaker" không để "circuit breaker" cướp mất thành hai mảnh). Chữ hoa đầu
    câu của bản gốc được giữ sang bản dịch bắt buộc.

    Bản SINH ĐÔI chạy trong máy dịch là ``vn-translate/app/terms.py``
    (hàm cùng tên) — hai tiến trình tách rời nên không dùng chung code được;
    sửa một bên nhớ ngó bên kia.
    """
    if not cap or not text:
        return [(True, text)] if text else []
    thu_tu = sorted(cap, key=lambda c: len(c[0]), reverse=True)
    mau = "|".join(re.escape(goc) for goc, _ in thu_tu)
    rx = re.compile(rf"(?<!\w)({mau})(?!\w)", re.IGNORECASE)
    tra = {thuong_hoa(goc): dich for goc, dich in thu_tu}
    ra: list[tuple[bool, str]] = []
    vt = 0
    text = unicodedata.normalize("NFC", text)
    for m in rx.finditer(text):
        if m.start() > vt:
            ra.append((True, text[vt:m.start()]))
        thay = tra[thuong_hoa(m.group(1))]
        if m.group(1)[:1].isupper() and thay[:1].islower():
            thay = thay[0].upper() + thay[1:]
        ra.append((False, thay))
        vt = m.end()
    if vt < len(text):
        ra.append((True, text[vt:]))
    return ra


def doan_linh_vuc(text_nguon: str, src: str) -> list[str]:
    """Đoán lĩnh vực của bản thoại — thống kê thuần, KHÔNG LLM.

    Đếm mỗi lĩnh vực có bao nhiêu TERM RIÊNG của nó xuất hiện trong text. Lĩnh
    vực nào đạt ``NGUONG_LINH_VUC`` thì nhận; trả tối đa ``TOI_DA_LINH_VUC`` cái
    điểm cao nhất. Rỗng = không đoán được lĩnh vực nào (hậu kỳ sẽ bỏ qua).
    """
    goi = nap_glossary(src)
    if not goi:
        return []
    hay = thuong_hoa(text_nguon)
    diem: dict[str, int] = {}
    for linh_vuc, cap in goi.items():
        n = sum(1 for term in cap if term and co_trong(term, hay))
        if n >= NGUONG_LINH_VUC:
            diem[linh_vuc] = n
    return sorted(diem, key=lambda k: diem[k], reverse=True)[:TOI_DA_LINH_VUC]


def hau_ky_thuat_ngu(
    ban_dich: str,
    nguon: str,
    src: str,
    linh_vuc: list[str],
    render_nllb: Callable[[str], str],
    *,
    cache_render: Optional[dict[str, str]] = None,
) -> str:
    """Thay thuật ngữ trong MỘT câu đã dịch bằng thuật ngữ VI chuẩn.

    Với mỗi term nguồn (của các ``linh_vuc`` đã chọn) mà XUẤT HIỆN trong ``nguon``:
    hỏi ``render_nllb(term)`` xem NLLB tự dịch term đó ra chữ gì, rồi thay chữ
    đó trong ``ban_dich`` bằng thuật ngữ chuẩn. Chỉ đụng tới cụm NLLB thật sự
    sinh ra, nên không thay bừa.

    ``render_nllb`` do caller cấp (thường là ``translate_service.translate``);
    truyền vào để module này test được mà không cần máy dịch. ``cache_render``
    dùng chung giữa các câu để mỗi term chỉ dịch-đơn một lần cho cả video.
    """
    goi = nap_glossary(src)
    if not goi or not linh_vuc:
        return ban_dich
    nguon_hay = thuong_hoa(nguon)
    if cache_render is None:
        cache_render = {}

    # Gom term của mọi lĩnh vực đã chọn; term dài thay TRƯỚC để cụm dài không bị
    # cụm con của nó cắt mất ('học máy' trước 'máy').
    can_thay: dict[str, str] = {}
    for lv in linh_vuc:
        for term, vi in goi.get(lv, {}).items():
            if term and co_trong(term, nguon_hay):
                can_thay.setdefault(term, vi)

    bang: dict[str, str] = {}
    for term in sorted(can_thay, key=len, reverse=True):
        vi_chuan = can_thay[term]
        if term not in cache_render:
            try:
                cache_render[term] = thuong_hoa(render_nllb(term))
            except Exception as exc:
                logger.debug("render term '%s' lỗi: %s", term, str(exc)[:120])
                cache_render[term] = ""
        nllb_render = cache_render[term]
        if not nllb_render or thuong_hoa(vi_chuan) == nllb_render:
            continue
        # Khai chính thuật ngữ chuẩn làm khoá trỏ về nó: chỗ NLLB đã dịch đúng
        # sẽ khớp vào khoá DÀI này và giữ nguyên, thay vì bị bản render ngắn
        # hơn khớp trúng phần đầu rồi nối thêm đuôi ("công tắc phụ" nằm gọn
        # trong "công tắc phụ trợ").
        bang.setdefault(thuong_hoa(vi_chuan), vi_chuan)
        bang.setdefault(nllb_render, vi_chuan)
    if not bang:
        return ban_dich
    # Thay MỘT LƯỢT bằng một mẫu gộp, khớp cụm dài trước: chữ vừa thay xong
    # không được quét lại, nếu không thì term sau cắn vào thuật ngữ term trước
    # vừa sinh ra và cụm dài thêm một đuôi sau mỗi vòng lặp.
    mau = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(k) for k in
                               sorted(bang, key=len, reverse=True)) + r")(?!\w)",
        re.IGNORECASE)

    def _thay(m: re.Match) -> str:
        # Giữ chữ hoa đầu câu của bản dịch: thuật ngữ trong kho viết thường,
        # thay thẳng vào đầu câu là câu mất chữ hoa.
        thay = bang[thuong_hoa(m.group(1))]
        if m.group(1)[:1].isupper() and thay[:1].islower():
            return thay[0].upper() + thay[1:]
        return thay

    return mau.sub(_thay, ban_dich)
