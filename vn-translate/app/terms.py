"""Thuật ngữ CHUYÊN NGÀNH cho máy dịch — dịch bằng BẢNG TRA, không cho engine đoán.

Vấn đề: máy dịch thống kê (Argos/NLLB) dịch thuật ngữ theo nghĩa phổ thông —
"circuit breaker" thành "người phá vòng", "formwork" thành "công việc theo mẫu",
"tụ điện" thành "electric gathering". LLM đỡ hơn nhưng chủ máy đã chốt KHÔNG
dùng LLM (chậm + đốt hạn mức).

Cách của các sản phẩm lớn (DeepL glossary, Microsoft dynamic dictionary) không
phải là "dạy" engine: họ THAY thuật ngữ bằng bản dịch bắt buộc rồi chỉ để engine
dịch phần còn lại. Ở đây làm đúng như vậy, thuần Python, 0 token, chạy với MỌI
engine:

    "Chọn tụ điện cho mạch lọc"  →  [chữ]"Chọn "  [bảng]"capacitor"  [chữ]" cho mạch lọc"
                                       ↓ engine dịch      ↓ giữ nguyên
    →  "Choose capacitor for the filter circuit"

Thuật ngữ chưa từng chạm engine — nó được dịch bằng bảng, trăm lần như một.

Nhận diện NGÀNH tự động: đếm số thuật ngữ khớp theo từng ngành, ngành nào có ≥2
mục khớp thì bảng của ngành đó được áp. Ngưỡng 2 để một chữ "cột" lạc trong câu
văn thường không kéo cả bảng xây dựng vào.

Bảng mẫu đi kèm 5 ngành (điện tử, y tế, xây dựng, CNTT, pháp lý), chỉ cặp
Anh⇄Việt. Chủ máy thêm/đè bằng file JSON trong ``data/translate/glossary/``::

    data/translate/glossary/y_te.json
    {"ten": "Y tế", "cap": [{"en": "sepsis", "vi": "nhiễm khuẩn huyết"}, …]}

File cùng tên ngành thì CẶP TỪ được gộp vào bảng mẫu (trùng ``en`` thì bản của
chủ máy thắng); tên mới thì thành ngành mới. Tắt cả tầng này bằng
``translate_glossary_enabled: false``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Bảng mẫu — chọn thuật ngữ mà máy dịch thống kê HAY SAI nghĩa phổ thông ──
# Không tham đủ ngành: mỗi cặp ở đây là một chỗ engine từng dịch bậy. Bảng dài
# do chủ máy nuôi qua data/translate/glossary/.
_BANG_MAU: dict[str, dict[str, Any]] = {
    "dien_tu": {"ten": "Điện tử", "cap": [
        {"en": "circuit breaker", "vi": "áp-tô-mát"},
        {"en": "relay", "vi": "rơ-le"},
        {"en": "capacitor", "vi": "tụ điện"},
        {"en": "resistor", "vi": "điện trở"},
        {"en": "inverter", "vi": "biến tần"},
        {"en": "transformer", "vi": "máy biến áp"},
        {"en": "short circuit", "vi": "ngắn mạch"},
        {"en": "grounding", "vi": "tiếp địa"},
        {"en": "printed circuit board", "vi": "bảng mạch in"},
        {"en": "microcontroller", "vi": "vi điều khiển"},
        {"en": "semiconductor", "vi": "chất bán dẫn"},
        {"en": "alternating current", "vi": "dòng điện xoay chiều"},
        {"en": "direct current", "vi": "dòng điện một chiều"},
        {"en": "voltage drop", "vi": "sụt áp"},
    ]},
    "y_te": {"ten": "Y tế", "cap": [
        {"en": "hypertension", "vi": "tăng huyết áp"},
        {"en": "diabetes mellitus", "vi": "đái tháo đường"},
        {"en": "myocardial infarction", "vi": "nhồi máu cơ tim"},
        {"en": "stroke", "vi": "đột quỵ"},
        {"en": "antibiotic", "vi": "kháng sinh"},
        {"en": "anesthesia", "vi": "gây mê"},
        {"en": "biopsy", "vi": "sinh thiết"},
        {"en": "benign", "vi": "lành tính"},
        {"en": "malignant", "vi": "ác tính"},
        {"en": "contraindication", "vi": "chống chỉ định"},
        {"en": "side effect", "vi": "tác dụng phụ"},
        {"en": "blood pressure", "vi": "huyết áp"},
        {"en": "prescription", "vi": "đơn thuốc"},
        {"en": "intensive care unit", "vi": "khoa hồi sức tích cực"},
    ]},
    "xay_dung": {"ten": "Xây dựng", "cap": [
        {"en": "reinforced concrete", "vi": "bê tông cốt thép"},
        {"en": "formwork", "vi": "cốp pha"},
        {"en": "rebar", "vi": "cốt thép"},
        {"en": "load-bearing wall", "vi": "tường chịu lực"},
        {"en": "scaffolding", "vi": "giàn giáo"},
        {"en": "pile foundation", "vi": "móng cọc"},
        {"en": "curing", "vi": "bảo dưỡng bê tông"},
        {"en": "mortar", "vi": "vữa"},
        {"en": "aggregate", "vi": "cốt liệu"},
        {"en": "shop drawing", "vi": "bản vẽ thi công"},
        {"en": "bill of quantities", "vi": "bảng tiên lượng"},
        {"en": "settlement", "vi": "độ lún"},
        {"en": "waterproofing", "vi": "chống thấm"},
    ]},
    "cntt": {"ten": "CNTT", "cap": [
        {"en": "database", "vi": "cơ sở dữ liệu"},
        {"en": "firewall", "vi": "tường lửa"},
        {"en": "encryption", "vi": "mã hoá"},
        {"en": "bandwidth", "vi": "băng thông"},
        {"en": "cache", "vi": "bộ nhớ đệm"},
        {"en": "operating system", "vi": "hệ điều hành"},
        {"en": "source code", "vi": "mã nguồn"},
        {"en": "vulnerability", "vi": "lỗ hổng bảo mật"},
        {"en": "authentication", "vi": "xác thực"},
        {"en": "load balancer", "vi": "bộ cân bằng tải"},
        {"en": "deployment", "vi": "triển khai"},
        {"en": "backup", "vi": "sao lưu"},
    ]},
    "phap_ly": {"ten": "Pháp lý", "cap": [
        {"en": "plaintiff", "vi": "nguyên đơn"},
        {"en": "defendant", "vi": "bị đơn"},
        {"en": "breach of contract", "vi": "vi phạm hợp đồng"},
        {"en": "jurisdiction", "vi": "thẩm quyền"},
        {"en": "arbitration", "vi": "trọng tài"},
        {"en": "power of attorney", "vi": "giấy uỷ quyền"},
        {"en": "intellectual property", "vi": "sở hữu trí tuệ"},
        {"en": "damages", "vi": "bồi thường thiệt hại"},
        {"en": "notarization", "vi": "công chứng"},
        {"en": "liability", "vi": "trách nhiệm pháp lý"},
        {"en": "statute of limitations", "vi": "thời hiệu"},
        {"en": "due diligence", "vi": "thẩm định pháp lý"},
    ]},
}

# Thư mục bảng thuật ngữ của CHỦ MÁY (volume /data). Bảng mẫu nằm ngay trong
# code (_BANG_MAU) — image tự đủ, volume chỉ để thêm/đè.
GLOSSARY_DIR = Path(os.getenv("TT_GLOSSARY_DIR", "/data/glossary"))

#: Ngành phải có ít nhất ngần này THUẬT NGỮ KHÁC NHAU khớp trong văn bản thì bảng
#: của nó mới được áp — một chữ "cột" lạc trong câu văn thường không được phép
#: kéo cả bảng xây dựng vào.
NGUONG_KHOP = 2

_TTL = 300.0
_cache: tuple[float, dict[str, dict[str, Any]]] = (0.0, {})
_lock = threading.Lock()


def _chuan(s: str) -> str:
    """Hạ chữ + chuẩn NFC để so khớp ổn định (dấu tiếng Việt có 2 cách mã hoá)."""
    return unicodedata.normalize("NFC", str(s or "").strip().lower())


def bang_nganh(force: bool = False) -> dict[str, dict[str, Any]]:
    """Bảng mẫu + file của chủ máy trong ``data/translate/glossary/``.

    File cùng tên ngành: gộp cặp, trùng ``en`` thì bản chủ máy thắng. Đệm 5 phút
    — sửa file thấy hiệu lực trong vòng đó, không cần khởi động lại.
    """
    global _cache
    with _lock:
        ts, cached = _cache
        if cached and not force and (time.time() - ts) < _TTL:
            return cached
        ra: dict[str, dict[str, Any]] = {
            k: {"ten": v["ten"], "cap": list(v["cap"])} for k, v in _BANG_MAU.items()
        }
        try:
            for f in sorted(GLOSSARY_DIR.glob("*.json")):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    cap = [c for c in (d.get("cap") or [])
                           if isinstance(c, dict) and c.get("en") and c.get("vi")]
                    if not cap:
                        continue
                    ma = f.stem
                    if ma in ra:
                        de = {_chuan(c["en"]): c for c in ra[ma]["cap"]}
                        for c in cap:
                            de[_chuan(c["en"])] = c
                        ra[ma]["cap"] = list(de.values())
                        if d.get("ten"):
                            ra[ma]["ten"] = str(d["ten"])
                    else:
                        ra[ma] = {"ten": str(d.get("ten") or ma), "cap": cap}
                except Exception as exc:
                    logger.warning("bảng thuật ngữ %s lỗi, bỏ qua: %s", f.name, exc)
        except OSError:
            pass
        _cache = (time.time(), ra)
        return ra


def _cap_theo_huong(nganh: dict[str, Any], nguon: str, dich: str) -> list[tuple[str, str]]:
    """[(thuật ngữ nguồn, bản dịch bắt buộc)] cho hướng nguon→dich.

    Bảng chỉ có cặp en⇄vi — hướng khác (ja/ko/zh) trả rỗng, tầng này tự tắt.
    """
    if nguon == "en" and dich == "vi":
        return [(c["en"], c["vi"]) for c in nganh["cap"]]
    if nguon == "vi" and dich == "en":
        return [(c["vi"], c["en"]) for c in nganh["cap"]]
    return []


def _khop_mot(term: str, text_chuan: str) -> bool:
    """Thuật ngữ có xuất hiện (nguyên từ, không dính giữa từ khác)."""
    return re.search(rf"(?<![\w]){re.escape(_chuan(term))}(?![\w])", text_chuan) is not None


def doan_nganh(text: str, nguon: str, dich: str) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """Ngành nào áp được cho văn bản này → [(mã, tên, cặp từ đã khớp hướng)].

    Chỉ ngành có ≥ ``NGUONG_KHOP`` thuật ngữ KHÁC NHAU xuất hiện. Nhiều ngành
    cùng đạt thì áp tất — một tài liệu đấu thầu có cả xây dựng lẫn pháp lý.
    """
    tc = _chuan(text)
    if not tc:
        return []
    ra = []
    for ma, nganh in bang_nganh().items():
        cap = _cap_theo_huong(nganh, nguon, dich)
        if not cap:
            continue
        khop = sum(1 for goc, _ in cap if _khop_mot(goc, tc))
        if khop >= NGUONG_KHOP:
            ra.append((ma, nganh["ten"], cap))
    return ra


def tach_thuat_ngu(text: str, cap: list[tuple[str, str]]) -> list[tuple[bool, str]]:
    """Cắt đoạn thành [(dịch_được, chữ)] — thuật ngữ thành đoạn KHÓA đã mang sẵn
    bản dịch bắt buộc, phần còn lại để engine dịch.

    Khớp không phân biệt hoa thường, ưu tiên thuật ngữ DÀI trước ("short circuit
    breaker" không được để "circuit breaker" cướp trước thành hai mảnh). Chữ hoa
    đầu câu của bản gốc được giữ sang bản dịch bắt buộc.
    """
    if not cap or not text:
        return [(True, text)] if text else []
    thu_tu = sorted(cap, key=lambda c: len(c[0]), reverse=True)
    mau = "|".join(re.escape(goc) for goc, _ in thu_tu)
    rx = re.compile(rf"(?<![\w])({mau})(?![\w])", re.IGNORECASE)
    tra = {_chuan(goc): dich for goc, dich in thu_tu}
    ra: list[tuple[bool, str]] = []
    vt = 0
    for m in rx.finditer(unicodedata.normalize("NFC", text)):
        if m.start() > vt:
            ra.append((True, text[vt:m.start()]))
        thay = tra[_chuan(m.group(1))]
        if m.group(1)[:1].isupper() and thay[:1].islower():
            thay = thay[0].upper() + thay[1:]
        ra.append((False, thay))
        vt = m.end()
    if vt < len(text):
        ra.append((True, text[vt:]))
    return ra
