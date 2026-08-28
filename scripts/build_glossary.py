#!/usr/bin/env python3
"""Trình nạp glossary thuật ngữ → data/glossary/<tiếng>.json.

Sinh dữ liệu cho ``services/thuat_ngu.py`` (đọc lúc chạy). Dạng ghi ra:

    { "<lĩnh vực slug>": { "<term nguồn thường hoá>": "<thuật ngữ VI chuẩn>" } }

Nguồn CHÍNH — TIẾNG ANH: Wiktextract (bản kaikki đã bóc của English Wiktionary).
Mỗi mục có ``senses[].topics`` (lĩnh vực chuẩn hoá) và ``translations`` (kèm
``code:"vi"`` và ``sense`` mô tả nghĩa). Ta chỉ giữ cặp từ có LĨNH VỰC rõ — đúng
thứ cần cho hậu kỳ thuật ngữ, và tự lọc bỏ từ đời thường.

JA/ZH/KO — pivot QUA tiếng Anh: FreeDict ``jpn-eng`` (JA→EN), CC-CEDICT
(ZH→EN), và OMW (gióng synset nguồn↔VI, lĩnh vực lấy theo từ VI qua glossary
EN — dùng cho KO và gia cố JA/ZH).

Nguồn tải ngoài + lệnh dựng: xem ``docs/GLOSSARY.md``.

Chạy (trên server, nơi tải được tệp lớn)::

    python scripts/build_glossary.py --kaikki-en /duong/den/en-extract.jsonl \\
        --out data/glossary

Có thể truyền .jsonl hoặc .jsonl.gz. Đọc theo dòng (stream) nên không nạp cả
tệp ~10GB vào RAM.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Iterator, Optional

# ── Bản đồ topic Wiktextract → slug lĩnh vực tiếng Việt ──────────────────────
# Chỉ liệt kê topic hữu ích cho THUẬT NGỮ. Topic không có trong bảng → bỏ (từ
# đời thường không có lĩnh vực rõ thì không nên nhét vào glossary chuyên ngành).
TOPIC_SLUG: dict[str, str] = {}


def _dang_ky(slug: str, *topics: str) -> None:
    for t in topics:
        TOPIC_SLUG[t] = slug


_dang_ky("cong_nghe", "computing", "internet", "telecommunications", "electronics",
         "information-technology", "programming", "software", "hardware",
         "networking", "cryptography", "databases")
_dang_ky("ky_thuat", "engineering", "mechanical-engineering", "electrical-engineering",
         "automotive", "robotics")
_dang_ky("toan_hoc", "mathematics", "geometry", "algebra", "statistics",
         "calculus", "topology")
_dang_ky("vat_ly", "physics", "thermodynamics", "mechanics", "optics",
         "electromagnetism", "nuclear-physics")
_dang_ky("hoa_hoc", "chemistry", "biochemistry", "organic-chemistry",
         "inorganic-chemistry")
_dang_ky("sinh_hoc", "biology", "genetics", "botany", "zoology", "microbiology",
         "ecology", "cytology", "molecular-biology")
_dang_ky("y_khoa", "medicine", "anatomy", "pathology", "pharmacology",
         "physiology", "surgery", "cardiology", "immunology", "dentistry",
         "psychiatry", "oncology", "neurology")
_dang_ky("tam_ly", "psychology")
_dang_ky("phap_ly", "law", "legal")
_dang_ky("tai_chinh", "finance", "economics", "accounting", "banking")
_dang_ky("kinh_doanh", "business", "marketing", "management")
_dang_ky("quan_su", "military", "weaponry", "firearms")
_dang_ky("am_nhac", "music", "music-theory")
_dang_ky("ngon_ngu", "linguistics", "grammar", "phonetics", "phonology")
_dang_ky("thien_van", "astronomy", "astronautics", "astrophysics")
_dang_ky("dia_chat", "geology", "geography", "meteorology")
_dang_ky("am_thuc", "cooking", "culinary", "food")
_dang_ky("the_thao", "sports")
_dang_ky("hang_hai", "nautical", "sailing")
_dang_ky("hang_khong", "aviation", "aeronautics")
_dang_ky("kien_truc", "architecture", "construction")

_TACH_TIENG_VIET = re.compile(r"\s+")


def _thuong(s: str) -> str:
    return _TACH_TIENG_VIET.sub(" ", str(s or "").strip().lower())


def slug_cho_topic(topic: str) -> Optional[str]:
    """Topic Wiktextract → slug lĩnh vực, hoặc None nếu không thuộc ngành nào."""
    return TOPIC_SLUG.get(str(topic or "").strip().lower())


def _slug_tu_sense(sense_text: str) -> set[str]:
    """Đoán slug từ chuỗi ``sense`` của bản dịch, dạng 'computing: ...'.

    Lấy phần trước dấu ':' rồi tra bảng; cũng quét mọi từ topic biết trong cả
    câu (một số sense ghi 'computing, engineering: ...').
    """
    s = str(sense_text or "").lower()
    ra: set[str] = set()
    dau = s.split(":", 1)[0] if ":" in s else s
    for tu in re.split(r"[,/;]| and ", dau):
        sl = slug_cho_topic(tu.strip())
        if sl:
            ra.add(sl)
    return ra


#: Từ chức năng — bỏ khi so gloss với sense, không mang thông tin phân biệt.
_TU_RONG = {
    "a", "an", "the", "of", "or", "and", "to", "in", "for", "with", "on", "at",
    "by", "from", "as", "is", "are", "be", "was", "were", "that", "this",
    "which", "any", "some", "other", "such", "its", "it", "he", "she", "they",
    "one", "two", "esp", "especially", "etc", "eg", "ie",
}


#: Số TỪ NỘI DUNG phải trùng thì mới coi là ghép được nghĩa. Đặt 1 sau khi đo
#: cả hai mức trên kaikki 28/08 — xem docs/GLOSSARY.md mục "Vì sao --chat".
DIEM_KHOP_TOI_THIEU = 1


def _tu_noi_dung(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z]+", str(s or "").lower())
            if len(t) >= 3 and t not in _TU_RONG}


def _slug_tu_nghia_khop(entry: dict, sense_text: str) -> Optional[set[str]]:
    """Slug lấy từ topics của ĐÚNG nghĩa mà bản dịch trỏ tới.

    Đây là chỗ sửa cái sai gốc của kho dựng 25/08. ``_slug_toan_muc`` gộp topics
    của MỌI nghĩa trong mục, nên mục "region" — có một nghĩa giải phẫu — kéo cả
    bản dịch "tỉnh" (nghĩa hành chính) vào lĩnh vực y khoa. Đo thật trên kaikki
    28/08::

        region  dịch "tỉnh"   sense 'an administrative subdivision'
                → gloss 'An administrative subdivision of a city…'  topics []
        neurosurgery  dịch "phẫu thuật thần kinh"
                → gloss 'The surgical discipline focused on…'
                  topics ['medicine','neurology','neuroscience','sciences']

    Cùng một luật giữ được mục tốt và bỏ được mục rác, vì nó hỏi đúng câu hỏi:
    *nghĩa NÀY* có thuộc chuyên ngành không, chứ không phải *từ này* có nghĩa
    nào thuộc chuyên ngành không.

    Ghép nghĩa bằng số TỪ NỘI DUNG trùng nhau giữa chuỗi ``sense`` của bản dịch
    và ``glosses`` của nghĩa — ``sense`` là bản tóm gọn của gloss chứ không
    trùng khít ('colour' ↔ 'A colour between red and blue; violet…').

    Phân biệt HAI trạng thái khác hẳn nhau, đây là chỗ dễ sai nhất:

    * ``None`` — **không khớp được nghĩa nào**, tức KHÔNG CÓ BẰNG CHỨNG. Xảy ra
      khi sense viết tắt tới mức không chung chữ nào với gloss: 'gout' dịch
      "thống phong" ghi sense *arthritic disease*, còn gloss là *An extremely
      painful inflammation of joints*. Nơi gọi phải rơi xuống luật cũ, đừng bỏ
      — bỏ là mất đúng những thuật ngữ y khoa thật (đo 28/08: gout, spleen,
      diarrhea, acid, embryo đều rơi vào ô này).
    * ``set()`` — **khớp được nghĩa, và nghĩa đó KHÔNG thuộc chuyên ngành nào**,
      tức BẰNG CHỨNG NGƯỢC. 'region' dịch "tỉnh" khớp gloss *An administrative
      subdivision…* topics rỗng. Nơi gọi phải BỎ, không được rơi xuống luật cũ.
    """
    can = _tu_noi_dung(sense_text)
    if not can:
        return None
    tot, diem_tot = None, DIEM_KHOP_TOI_THIEU - 1
    for ng in entry.get("senses") or []:
        for g in ng.get("glosses") or []:
            diem = len(can & _tu_noi_dung(g))
            if diem > diem_tot:
                tot, diem_tot = ng, diem
    if tot is None:
        return None
    ra: set[str] = set()
    for t in tot.get("topics") or []:
        sl = slug_cho_topic(t)
        if sl:
            ra.add(sl)
    return ra


def _slug_toan_muc(entry: dict) -> set[str]:
    """Mọi slug suy ra từ topics của tất cả senses trong một mục."""
    ra: set[str] = set()
    for s in entry.get("senses") or []:
        for t in s.get("topics") or []:
            sl = slug_cho_topic(t)
            if sl:
                ra.add(sl)
    return ra


def _rac_vi(vi: str) -> bool:
    """Bản dịch VI 'rác' cần bỏ: ghi chú tiếng Anh lọt vào ô dịch, hoặc quá dài.

    Wiktextract đôi khi để ghi chú như 'no exact matching verb' vào chỗ bản
    dịch. Term chuyên ngành VI thật thì ngắn và không phải câu ghi chú Anh.
    """
    s = str(vi or "").strip().lower()
    if not s or len(s) > 60:
        return True
    if "matching verb" in s or re.search(r"\bno\b.*\bmatch", s):
        return True
    if s.startswith("(") or s.startswith("["):
        return True
    return False


def them_tu_kaikki_en(entry: dict, store: dict[str, dict[str, str]],
                      *, noi_long: bool = False, chat: bool = False) -> int:
    """Rút cặp (term Anh → thuật ngữ VI) có lĩnh vực từ MỘT mục Wiktextract.

    Gán lĩnh vực theo thứ tự ưu tiên:
      1. slug suy từ chính ``sense`` của bản dịch (khử nhập nhằng đúng nghĩa),
      2. nếu bản dịch không có tín hiệu VÀ mục chỉ thuộc ĐÚNG MỘT lĩnh vực →
         dùng lĩnh vực đó,
      3. nhập nhằng (nhiều lĩnh vực, dịch không rõ) → BỎ, không đoán bừa.
    Trả số cặp đã thêm. Giữ term VI ĐẦU TIÊN cho mỗi (lĩnh vực, từ).

    ``chat`` (CHẶT): thêm một bước TRƯỚC luật 2 — lấy lĩnh vực từ ĐÚNG nghĩa mà
    bản dịch trỏ tới (``_slug_tu_nghia_khop``). Khớp được nghĩa mà nghĩa đó
    không thuộc chuyên ngành nào thì BỎ hẳn; không khớp được nghĩa nào thì coi
    như không có bằng chứng và vẫn theo luật 2 như cũ. Luật 2 chính là nguồn gốc của những
    cặp phá bản dịch trong kho dựng 25/08 — ``region → tỉnh``, ``failure →
    thất bại``, ``purple → tía`` đều nằm trong lĩnh vực y khoa. Cơ chế: mục
    "region" của Wiktionary chỉ mang đúng một topic, nên MỌI bản dịch trong mục
    ấy — kể cả bản lạc nghĩa — bị gán hết vào lĩnh vực đó. Cụm nhiều từ vẫn
    được hưởng luật 2: "artificial intelligence" thì dài tới mức gần như luôn
    là thuật ngữ thật.
    """
    tu = _thuong(entry.get("word"))
    if not tu or entry.get("lang_code") not in (None, "en", "English"):
        return 0
    dich_vi = [t for t in (entry.get("translations") or [])
               if (t.get("code") == "vi" or t.get("lang") == "Vietnamese")
               and str(t.get("word") or "").strip() and not _rac_vi(t.get("word"))]
    if not dich_vi:
        return 0
    slug_muc = _slug_toan_muc(entry)
    cum_nhieu_tu = " " in tu     # 'machine learning' vs 'account'
    them = 0
    for t in dich_vi:
        slugs = _slug_tu_sense(t.get("sense", ""))
        if not slugs and chat:
            khop = _slug_tu_nghia_khop(entry, t.get("sense", ""))
            if khop is not None:
                # Khớp được nghĩa: nghĩa ĐÓ nói lên tất cả. Không mang lĩnh vực
                # nào nghĩa là bản dịch này thuộc nghĩa đời thường → bỏ hẳn,
                # tuyệt đối không rơi xuống luật cả-mục (chính là 'region').
                if not khop:
                    continue
                slugs = khop
        if not slugs:
            if len(slug_muc) == 1:
                slugs = set(slug_muc)
            elif noi_long and slug_muc and cum_nhieu_tu:
                # NỚI mà GIỮ CHÍNH XÁC: chỉ nhận CỤM NHIỀU TỪ đa lĩnh vực
                # ('artificial intelligence') → gán vào mọi lĩnh vực của mục.
                # Cụm dài gần như luôn là thuật ngữ thật. TỪ ĐƠN đa lĩnh vực
                # ('account', 'bear') nhập nhằng nặng → vẫn BỎ, khỏi thay bừa.
                slugs = set(slug_muc)
            else:
                continue
        vi = str(t["word"]).strip()
        for sl in slugs:
            bang = store.setdefault(sl, {})
            if tu not in bang:      # term VI đầu tiên (thường là nghĩa chính) thắng
                bang[tu] = vi
                them += 1
    return them


# ── Pivot qua tiếng Anh (JA/ZH/KO) ──────────────────────────────────────────
# JA/ZH/KO không có termbase sang thẳng tiếng Việt, nhưng có sang tiếng Anh
# (FreeDict jpn-eng, CC-CEDICT). Ta dùng glossary tiếng Anh ĐÃ DỰNG làm cầu:
# term nguồn → nghĩa tiếng Anh → tra trong glossary Anh ra (lĩnh vực, thuật ngữ
# VI). Chỉ term nào có nghĩa Anh TRÙNG một thuật ngữ Anh đã biết mới vào — tự
# lọc còn đúng từ chuyên ngành, khỏi kéo cả từ đời thường.

def chi_muc_en(en_store: dict[str, dict[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """Đảo glossary Anh thành: term Anh → [(lĩnh vực, thuật ngữ VI)]."""
    idx: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for slug, bang in en_store.items():
        for term_en, vi in bang.items():
            idx[term_en].append((slug, vi))
    return idx


_NGOAC = re.compile(r"\([^)]*\)|\[[^\]]*\]")


def _nghia_sach(gloss: str) -> str:
    """Chuẩn hoá một nghĩa tiếng Anh để tra cầu: bỏ ngoặc chú, 'to '/'a ' đầu,
    gộp khoảng trắng, hạ chữ."""
    g = _NGOAC.sub(" ", str(gloss or ""))
    g = _thuong(g)
    g = re.sub(r"^(to|a|an|the) ", "", g)
    return g.strip()


def _pivot(term_nguon: str, glosses: Iterable[str],
           en_index: dict[str, list[tuple[str, str]]],
           store: dict[str, dict[str, str]]) -> int:
    """Gắn term nguồn vào store theo các (lĩnh vực, VI) tra được qua nghĩa Anh."""
    term = _thuong(term_nguon)
    if not term:
        return 0
    them = 0
    for g in glosses:
        cap = en_index.get(_nghia_sach(g))
        if not cap:
            continue
        for slug, vi in cap:
            bang = store.setdefault(slug, {})
            if term not in bang:
                bang[term] = vi
                them += 1
    return them


_CC_DONG = re.compile(r"^\S+\s+(\S+)\s+\[[^\]]*\]\s+/(.+)/\s*$")


def nap_cc_cedict(dong: Iterable[str],
                  en_index: dict[str, list[tuple[str, str]]],
                  store: Optional[dict[str, dict[str, str]]] = None
                  ) -> dict[str, dict[str, str]]:
    """CC-CEDICT (ZH→EN) → glossary ZH→VI qua cầu tiếng Anh.

    Dòng CC-CEDICT: ``繁 简 [pin1 yin1] /gloss1/gloss2/``. Lấy chữ GIẢN THỂ làm
    khoá (video hiện đại dùng giản thể), các gloss là nghĩa tiếng Anh để pivot.
    """
    if store is None:
        store = defaultdict(dict)
    for d in dong:
        d = d.rstrip("\n")
        if not d or d.startswith("#"):
            continue
        m = _CC_DONG.match(d)
        if not m:
            continue
        gian = m.group(1)
        glosses = [g for g in m.group(2).split("/") if g.strip()]
        _pivot(gian, glosses, en_index, store)
    return store


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _freedict_entries(source):
    """Duyệt TEI FreeDict (stream) → (từ nguồn, [nghĩa tiếng Anh]).

    ``source``: đường dẫn tệp .tei hoặc đối tượng file/BytesIO. Chỉ lấy nghĩa
    trong ``<cit type="trans">`` (bỏ ví dụ dùng từ). Không phụ thuộc namespace.
    """
    import xml.etree.ElementTree as ET
    for _ev, el in ET.iterparse(source, events=("end",)):
        if _localname(el.tag) != "entry":
            continue
        orth = None
        glosses: list[str] = []
        for sub in el.iter():
            ln = _localname(sub.tag)
            if ln == "orth" and orth is None and (sub.text or "").strip():
                orth = sub.text.strip()
            elif ln == "cit" and sub.get("type") == "trans":
                for q in sub.iter():
                    if _localname(q.tag) == "quote" and (q.text or "").strip():
                        glosses.append(q.text.strip())
        if orth:
            yield orth, glosses
        el.clear()


def nap_freedict_jpn(source,
                     en_index: dict[str, list[tuple[str, str]]],
                     store: Optional[dict[str, dict[str, str]]] = None
                     ) -> dict[str, dict[str, str]]:
    """FreeDict ``jpn-eng`` (TEI, JA→EN) → glossary JA→VI qua cầu tiếng Anh."""
    if store is None:
        store = defaultdict(dict)
    for orth, glosses in _freedict_entries(source):
        _pivot(orth, glosses, en_index, store)
    return store


# ── OMW — Open Multilingual Wordnet (gồm KO, và gia cố JA/ZH) ────────────────
# OMW gióng lemma các tiếng về cùng SYNSET WordNet. Pivot: từ nguồn → synset →
# từ VI (cùng synset), còn LĨNH VỰC lấy theo chính từ VI tra trong glossary EN
# đã dựng. Nhờ vậy không cần Princeton WordNet mà vẫn gắn được lĩnh vực, và chỉ
# giữ cặp mà từ VI là thuật ngữ ĐÃ BIẾT lĩnh vực (tự lọc còn từ chuyên ngành).

def chi_muc_vi_domain(en_store: dict[str, dict[str, str]]) -> dict[str, set[str]]:
    """Thuật ngữ VI (thường hoá) → tập lĩnh vực, suy từ glossary EN."""
    idx: dict[str, set[str]] = defaultdict(set)
    for slug, bang in en_store.items():
        for vi in bang.values():
            idx[_thuong(vi)].add(slug)
    return idx


def doc_omw_tab(dong: Iterable[str]) -> dict[str, set[str]]:
    """Đọc một tệp OMW ``.tab`` (một ngôn ngữ) → {synset: set(lemma)}.

    Dòng: ``<synset>\t<lang>:<type>\t<lemma>``; dòng ``#`` là chú thích. Dấu
    gạch dưới trong lemma OMW là khoảng trắng ('New_York').
    """
    ra: dict[str, set[str]] = defaultdict(set)
    for d in dong:
        d = d.rstrip("\n")
        if not d or d.startswith("#"):
            continue
        parts = d.split("\t")
        if len(parts) < 3:
            continue
        synset = parts[0].strip()
        lemma = parts[-1].strip().replace("_", " ")
        if synset and lemma:
            ra[synset].add(lemma)
    return ra


def nap_omw(src_tab: Iterable[str], vi_tab: Iterable[str],
            vi_dom_index: dict[str, set[str]],
            store: Optional[dict[str, dict[str, str]]] = None
            ) -> dict[str, dict[str, str]]:
    """OMW: gióng synset nguồn↔VI, gắn lĩnh vực theo từ VI (glossary EN)."""
    if store is None:
        store = defaultdict(dict)
    nguon = doc_omw_tab(src_tab)
    viet = doc_omw_tab(vi_tab)
    for synset, src_lemmas in nguon.items():
        vi_lemmas = viet.get(synset)
        if not vi_lemmas:
            continue
        for sl in src_lemmas:
            sl_n = _thuong(sl)
            if not sl_n:
                continue
            for vl in vi_lemmas:
                doms = vi_dom_index.get(_thuong(vl))
                if not doms:
                    continue
                for slug in doms:
                    store.setdefault(slug, {}).setdefault(sl_n, vl)
    return store


def _mo(duong: str) -> Iterator[str]:
    """Mở .jsonl hoặc .jsonl.gz, trả từng dòng."""
    if str(duong).endswith(".gz"):
        with gzip.open(duong, "rt", encoding="utf-8") as f:
            yield from f
    else:
        with open(duong, "r", encoding="utf-8") as f:
            yield from f


def nap_kaikki_en(dong: Iterable[str],
                  store: Optional[dict[str, dict[str, str]]] = None,
                  *, noi_long: bool = False,
                  chat: bool = False) -> dict[str, dict[str, str]]:
    """Nạp một luồng dòng JSONL Wiktextract (English) vào store {slug:{từ:vi}}.

    ``noi_long``: hạ ngưỡng lọc — nhận cả term đa lĩnh vực mà bản dịch không ghi
    sense (gán vào mọi lĩnh vực của mục). Phủ rộng hơn, đổi lại lẫn ngành nhiều
    hơn — nhưng hậu kỳ vẫn có cổng (term phải có ở câu gốc + lĩnh vực phải được
    đoán ra) nên rủi ro có hạn."""
    if store is None:
        store = defaultdict(dict)
    for d in dong:
        d = d.strip()
        if not d:
            continue
        try:
            entry = json.loads(d)
        except Exception:
            continue
        them_tu_kaikki_en(entry, store, noi_long=noi_long, chat=chat)
    return store


#: Cặp ĐÃ SOÁT TAY và xác định là SAI — luật tự động không bắt được vì chúng
#: được Wiktionary gắn đúng lĩnh vực, chỉ sai ở bản dịch. Đã thử thẩm định lại
#: bằng từ điển Anh–Việt 104k mục (28/08) và BỎ hướng đó: từ điển diễn đạt khác
#: chữ nên nó giết nhầm 'neurosurgery', 'theorem', 'pandemic'. Soát tay là cách
#: trung thực hơn cho một danh sách ngắn thế này.
#:
#: Khoá theo (lĩnh vực, từ) chứ không theo từ: 'quantum → lượng tử' đúng trong
#: vật lý, chỉ sai khi nằm ở pháp lý.
_DA_SOAT_LA_SAI: dict[tuple[str, str], str] = {
    ("phap_ly", "appealable"): "bản dịch là chữ tục, rác hoàn toàn",
    ("phap_ly", "tenant"): "NGƯỢC nghĩa — tenant là người THUÊ, không phải chủ",
    ("phap_ly", "quantum"): "trong pháp lý là mức bồi thường, không phải số lượng",
    ("kinh_doanh", "account"): "phải là 'tài khoản'; 'chuyện kể' là nghĩa tường thuật",
    ("tai_chinh", "account"): "như trên",
    ("kinh_doanh", "cent"): "cent là 'xu', không phải 'phần trăm'",
    ("tai_chinh", "cent"): "như trên",
    ("toan_hoc", "angle"): "sai dấu: phải là 'góc', không phải 'gốc'",
    ("toan_hoc", "lemon"): "không phải thuật ngữ toán, lại còn sai chính tả",
    ("dia_chat", "today"): "không phải thuật ngữ địa chất",
    ("kien_truc", "tympanum"): "trong kiến trúc là 'trán tường'; đây là nghĩa y khoa",
    ("hoa_hoc", "gas"): "'khí tê' sai; gas là 'khí'",
    ("am_thuc", "nut"): "nut là 'hạt', không phải 'đậu'",
    ("cong_nghe", "user"): "user là 'người dùng', không phải 'thành viên'",
    ("ky_thuat", "user"): "như trên",
    ("toan_hoc", "user"): "như trên",
    ("y_khoa", "cream"): "trong y khoa là 'kem bôi'; 'màu kem' là nghĩa màu sắc",
    ("y_khoa", "empiricism"): "thuộc triết học, không phải y khoa",
    # Tiếng lóng nhạc công bị dịch thành tên con vật: clam = nốt sai, frog = gót
    # vĩ (bộ phận cây vĩ), wolf = tiếng sói (cộng hưởng lỗi của đàn dây).
    ("am_nhac", "clam"): "tiếng lóng 'nốt đánh sai', không phải con nghêu",
    ("am_nhac", "frog"): "là gót cây vĩ đàn dây, không phải con ếch",
    ("am_nhac", "wolf"): "là 'tiếng sói' — cộng hưởng lỗi, không phải con sói",
}


def bo_cap_da_soat(store: dict[str, dict[str, str]]) -> int:
    """Bỏ các cặp trong ``_DA_SOAT_LA_SAI``. Trả số cặp đã bỏ."""
    bo = 0
    for (lv, tu) in _DA_SOAT_LA_SAI:
        if store.get(lv, {}).pop(tu, None) is not None:
            bo += 1
    for lv in [k for k, v in store.items() if not v]:
        del store[lv]
    return bo


def ghi_store(store: dict[str, dict[str, str]], src: str, thu_muc: Path) -> Path:
    """Ghi store ra ``<thu_muc>/<src>.json`` (khoá lĩnh vực sắp xếp cho ổn định)."""
    thu_muc.mkdir(parents=True, exist_ok=True)
    tep = thu_muc / f"{src}.json"
    goi = {lv: dict(sorted(store[lv].items())) for lv in sorted(store)}
    tep.write_text(json.dumps(goi, ensure_ascii=False, indent=1), encoding="utf-8")
    return tep


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Nạp glossary thuật ngữ")
    ap.add_argument("--kaikki-en", help="Đường dẫn JSONL(.gz) Wiktextract English")
    ap.add_argument("--cc-cedict", help="Đường dẫn CC-CEDICT (ZH→EN) — cần en.json đã dựng trong --out")
    ap.add_argument("--freedict-jpn", help="Đường dẫn FreeDict jpn-eng .tei (JA→EN) — cần en.json")
    ap.add_argument("--omw-src", help="OMW .tab tiếng nguồn (kor/jpn/cmn) — cần en.json + --omw-vi + --omw-lang")
    ap.add_argument("--omw-vi", help="OMW .tab tiếng Việt (vie)")
    ap.add_argument("--omw-lang", help="mã tiếng nguồn để ghi ra (ko/ja/zh)")
    ap.add_argument("--chat", action="store_true",
                    help="CHẶT: từ đơn phải có tín hiệu lĩnh vực ngay trong "
                         "sense của bản dịch (bỏ suy lĩnh vực từ cả mục)")
    ap.add_argument("--noi-long", action="store_true",
                    help="Hạ ngưỡng lọc EN: nhận cả term đa lĩnh vực dịch không rõ sense")
    ap.add_argument("--out", default="data/glossary", help="Thư mục xuất")
    args = ap.parse_args(argv)

    thu_muc = Path(args.out)
    lam_gi = False
    if args.kaikki_en:
        store = nap_kaikki_en(_mo(args.kaikki_en), noi_long=args.noi_long,
                              chat=args.chat)
        bo = bo_cap_da_soat(store)
        tep = ghi_store(store, "en", thu_muc)
        if bo:
            print(f"bỏ {bo} cặp đã soát tay là sai")
        tong = sum(len(v) for v in store.values())
        print(f"en: {len(store)} lĩnh vực, {tong} thuật ngữ → {tep}")
        lam_gi = True
    if args.cc_cedict:
        en = json.loads((thu_muc / "en.json").read_text(encoding="utf-8"))
        idx = chi_muc_en(en)
        store = nap_cc_cedict(_mo(args.cc_cedict), idx)
        tep = ghi_store(store, "zh", thu_muc)
        tong = sum(len(v) for v in store.values())
        print(f"zh: {len(store)} lĩnh vực, {tong} thuật ngữ (pivot qua en) → {tep}")
        lam_gi = True
    if args.freedict_jpn:
        en = json.loads((thu_muc / "en.json").read_text(encoding="utf-8"))
        idx = chi_muc_en(en)
        store = nap_freedict_jpn(args.freedict_jpn, idx)
        tep = ghi_store(store, "ja", thu_muc)
        tong = sum(len(v) for v in store.values())
        print(f"ja: {len(store)} lĩnh vực, {tong} thuật ngữ (pivot qua en) → {tep}")
        lam_gi = True
    if args.omw_src:
        if not (args.omw_vi and args.omw_lang):
            ap.error("--omw-src cần kèm --omw-vi và --omw-lang")
        en = json.loads((thu_muc / "en.json").read_text(encoding="utf-8"))
        vi_dom = chi_muc_vi_domain(en)
        # GIA CỐ: nếu <lang>.json đã có (ja/zh dựng từ pivot), nạp làm nền để OMW
        # CHỈ THÊM term mới, không ghi đè — không thì chạy OMW cho ja/zh sẽ xoá
        # mất bản pivot. KO chưa có file thì bắt đầu rỗng.
        nen: dict[str, dict[str, str]] = defaultdict(dict)
        tep_cu = thu_muc / f"{args.omw_lang}.json"
        if tep_cu.exists():
            for lv, cap in json.loads(tep_cu.read_text(encoding="utf-8")).items():
                nen[lv].update(cap)
        so_truoc = sum(len(v) for v in nen.values())
        store = nap_omw(_mo(args.omw_src), _mo(args.omw_vi), vi_dom, nen)
        tep = ghi_store(store, args.omw_lang, thu_muc)
        tong = sum(len(v) for v in store.values())
        print(f"{args.omw_lang} (OMW): {len(store)} lĩnh vực, {tong} thuật ngữ "
              f"(+{tong - so_truoc} mới) → {tep}")
        lam_gi = True
    if not lam_gi:
        ap.error("cần --kaikki-en / --cc-cedict / --freedict-jpn / --omw-src")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
