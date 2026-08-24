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


class _KhoTinh:
    """Bộ nhớ đệm glossary đã nạp theo tiếng nguồn (đọc file một lần)."""

    def __init__(self) -> None:
        self._theo_src: dict[str, dict[str, dict[str, str]]] = {}
        self._da_doc: set[str] = set()

    def nap(self, src: str) -> dict[str, dict[str, str]]:
        src = str(src or "").lower().strip()
        if src in self._da_doc:
            return self._theo_src.get(src, {})
        self._da_doc.add(src)
        tep = _thu_muc_glossary() / f"{src}.json"
        try:
            raw = json.loads(tep.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._theo_src[src] = {}
            return {}
        except Exception as exc:
            logger.warning("glossary %s hỏng, bỏ qua: %s", tep, str(exc)[:200])
            self._theo_src[src] = {}
            return {}
        # Thường hoá KHOÁ term nguồn ngay lúc nạp để khớp không phụ thuộc hoa/thường.
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
        self._theo_src[src] = goi
        return goi

    def xoa(self) -> None:
        self._theo_src.clear()
        self._da_doc.clear()


_KHO = _KhoTinh()


def nap_glossary(src: str) -> dict[str, dict[str, str]]:
    """Glossary của một tiếng nguồn: {lĩnh vực: {term nguồn: thuật ngữ VI}}."""
    return _KHO.nap(src)


def _reset_cache_cho_test() -> None:
    _KHO.xoa()


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
        n = sum(1 for term in cap if term and term in hay)
        if n >= NGUONG_LINH_VUC:
            diem[linh_vuc] = n
    return sorted(diem, key=lambda k: diem[k], reverse=True)[:TOI_DA_LINH_VUC]


def _thay_ca_tu(chuoi: str, tim: str, thay: str) -> tuple[str, int]:
    """Thay ``tim`` bằng ``thay`` trong ``chuoi``, KHỚP NGUYÊN CỤM (biên chữ),
    không phân biệt hoa thường. Trả (chuỗi mới, số lần thay).

    Biên chữ để 'cache' không nuốt trong 'cached' hay 'cacher'. Với tiếng Việt
    (âm tiết cách nhau bằng khoảng trắng) ``\\b`` quanh cụm vẫn đúng vì hai đầu
    cụm là chữ cái/số.
    """
    if not tim:
        return chuoi, 0
    mau = re.compile(r"(?<!\w)" + re.escape(tim) + r"(?!\w)", re.IGNORECASE)
    return mau.subn(lambda _m: thay, chuoi)


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
            if term and term in nguon_hay:
                can_thay.setdefault(term, vi)

    ra = ban_dich
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
        moi, n = _thay_ca_tu(ra, nllb_render, vi_chuan)
        if n:
            ra = moi
    return ra
