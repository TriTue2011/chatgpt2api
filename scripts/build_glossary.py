#!/usr/bin/env python3
"""Trình nạp glossary thuật ngữ → data/glossary/<tiếng>.json.

Sinh dữ liệu cho ``services/thuat_ngu.py`` (đọc lúc chạy). Dạng ghi ra:

    { "<lĩnh vực slug>": { "<term nguồn thường hoá>": "<thuật ngữ VI chuẩn>" } }

BƯỚC 1 (tệp này) — nguồn TIẾNG ANH: Wiktextract (bản kaikki đã bóc của English
Wiktionary). Mỗi mục có ``senses[].topics`` (lĩnh vực chuẩn hoá) và
``translations`` (bản dịch, kèm ``code:"vi"`` và ``sense`` mô tả nghĩa). Ta chỉ
giữ những cặp từ có LĨNH VỰC rõ — đúng thứ cần cho hậu kỳ thuật ngữ, và tự lọc
bỏ từ đời thường.

JA/ZH/KO (pivot qua tiếng Anh bằng FreeDict jpn-eng / CC-CEDICT / OMW) là bước
sau; khung dữ liệu và hàm ghi ở đây dùng lại được.

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


def _slug_toan_muc(entry: dict) -> set[str]:
    """Mọi slug suy ra từ topics của tất cả senses trong một mục."""
    ra: set[str] = set()
    for s in entry.get("senses") or []:
        for t in s.get("topics") or []:
            sl = slug_cho_topic(t)
            if sl:
                ra.add(sl)
    return ra


def them_tu_kaikki_en(entry: dict, store: dict[str, dict[str, str]]) -> int:
    """Rút cặp (term Anh → thuật ngữ VI) có lĩnh vực từ MỘT mục Wiktextract.

    Gán lĩnh vực theo thứ tự ưu tiên:
      1. slug suy từ chính ``sense`` của bản dịch (khử nhập nhằng đúng nghĩa),
      2. nếu bản dịch không có tín hiệu VÀ mục chỉ thuộc ĐÚNG MỘT lĩnh vực →
         dùng lĩnh vực đó,
      3. nhập nhằng (nhiều lĩnh vực, dịch không rõ) → BỎ, không đoán bừa.
    Trả số cặp đã thêm. Giữ term VI ĐẦU TIÊN cho mỗi (lĩnh vực, từ).
    """
    tu = _thuong(entry.get("word"))
    if not tu or entry.get("lang_code") not in (None, "en", "English"):
        return 0
    dich_vi = [t for t in (entry.get("translations") or [])
               if (t.get("code") == "vi" or t.get("lang") == "Vietnamese")
               and str(t.get("word") or "").strip()]
    if not dich_vi:
        return 0
    slug_muc = _slug_toan_muc(entry)
    them = 0
    for t in dich_vi:
        slugs = _slug_tu_sense(t.get("sense", ""))
        if not slugs:
            if len(slug_muc) == 1:
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


def _mo(duong: str) -> Iterator[str]:
    """Mở .jsonl hoặc .jsonl.gz, trả từng dòng."""
    if str(duong).endswith(".gz"):
        with gzip.open(duong, "rt", encoding="utf-8") as f:
            yield from f
    else:
        with open(duong, "r", encoding="utf-8") as f:
            yield from f


def nap_kaikki_en(dong: Iterable[str],
                  store: Optional[dict[str, dict[str, str]]] = None
                  ) -> dict[str, dict[str, str]]:
    """Nạp một luồng dòng JSONL Wiktextract (English) vào store {slug:{từ:vi}}."""
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
        them_tu_kaikki_en(entry, store)
    return store


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
    ap.add_argument("--out", default="data/glossary", help="Thư mục xuất")
    args = ap.parse_args(argv)

    thu_muc = Path(args.out)
    if args.kaikki_en:
        store = nap_kaikki_en(_mo(args.kaikki_en))
        tep = ghi_store(store, "en", thu_muc)
        tong = sum(len(v) for v in store.values())
        print(f"en: {len(store)} lĩnh vực, {tong} thuật ngữ → {tep}")
    else:
        ap.error("cần ít nhất --kaikki-en (các nguồn JA/ZH/KO là bước sau)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
