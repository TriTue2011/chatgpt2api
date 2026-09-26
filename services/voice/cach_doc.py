"""Sổ cách đọc — chủ máy DẠY cách đọc một chữ, từ đó mọi giọng tiếng Việt đọc đúng.

Chủ máy 26/09/2026: "smart TV LG được bảo hành ở TBBH — đọc lỗi". Ba chữ sai vì ba lý do
mà không quy tắc chung nào sửa được: "TV" có hai nghĩa trong từ điển (ti vi, thư viện)
nhưng kho tin tức viết đủ "thư viện" gấp 8 lần "tivi" — tự học sẽ nghiêng về thư viện;
"LG" là tên hãng (đọc kiểu Anh hay Việt tuỳ thói quen); "TBBH" không có trong từ điển
nào. Cách chữa đúng lớp lỗi là để người nghe dạy — sai một lần, dạy một lần (cùng tinh
thần ``services/bai_hoc.py``), thay vì lập trình viên nối thêm từng chữ vào mã.

Dạy bằng hai đường: nhắn bot (công cụ ``day_cach_doc``) hoặc trang web (Cài đặt → Giọng
nói & Loa → Cách đọc, qua ``/api/voice/cach-doc``). Lưu ``DATA_DIR/voice/cach_doc.json``:

    {"<chữ>": {"chu": "TBBH", "doc": "trung tâm bảo hành", "luc": <epoch>}}

Áp ĐẦU TIÊN trong ``engines._doc_cong_thuc`` — trên toàn văn, trước công thức hoá học và
bộ chọn nghĩa: điều người dạy luôn thắng điều máy đoán.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR

logger = logging.getLogger(__name__)

_PATH = Path(DATA_DIR) / "voice" / "cach_doc.json"
_lock = threading.RLock()
_data: dict[str, dict[str, Any]] = {}
_loaded = False
_mau: re.Pattern | None = None          # regex gộp mọi chữ đã dạy, dựng lại khi sổ đổi

#: Giới hạn ở biên hệ thống (người dùng gõ): chữ là một cụm ngắn, cách đọc là một câu ngắn.
CHU_TOI_DA = 40
DOC_TOI_DA = 160


def _ensure() -> None:
    global _loaded, _data
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        try:
            if _PATH.is_file():
                raw = json.loads(_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    _data = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
        except Exception as exc:  # noqa: BLE001 — sổ hỏng không được làm câm TTS
            logger.warning("voice.cach_doc: khong doc duoc so: %s", exc)
            _data = {}
        _loaded = True


def _save() -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_PATH)


def _doi_so() -> None:
    """Sổ vừa đổi: dựng lại regex, bỏ audio đã đệm (câu cũ đọc theo cách cũ)."""
    global _mau
    _mau = None
    try:
        from services.voice import tts_cache
        tts_cache.clear()
    except Exception as exc:  # noqa: BLE001
        logger.warning("voice.cach_doc: khong xoa duoc bo dem TTS: %s", exc)


def _khoa(chu: str) -> str:
    """Chữ có HOA ("TV", "LG") khớp đúng hoa; chữ thường ("smart") khớp mọi kiểu hoa."""
    return chu if any(c.isupper() for c in chu) else chu.lower()


def danh_sach() -> list[dict[str, Any]]:
    _ensure()
    with _lock:
        rows = [dict(v) for v in _data.values()]
    rows.sort(key=lambda r: str(r.get("chu") or "").lower())
    return rows


def day(chu: str, doc: str) -> dict[str, Any]:
    """Thêm / sửa một cách đọc. ``ValueError`` nếu chữ hay cách đọc không hợp lệ."""
    chu = " ".join(str(chu or "").split())
    doc = " ".join(str(doc or "").split())
    if not chu or len(chu) > CHU_TOI_DA:
        raise ValueError(f"Chữ cần dạy phải có 1–{CHU_TOI_DA} ký tự.")
    if not doc or len(doc) > DOC_TOI_DA:
        raise ValueError(f"Cách đọc phải có 1–{DOC_TOI_DA} ký tự.")
    if not re.search(r"\w", chu):
        raise ValueError("Chữ cần dạy phải có chữ hoặc số.")
    # Cách đọc chứa lại chính chữ đó ("LG" → "LG điện tử") thì áp hai lần thành lặp chữ.
    if re.search(r"(?<!\w)" + re.escape(chu) + r"(?!\w)", doc,
                 0 if any(c.isupper() for c in chu) else re.IGNORECASE):
        raise ValueError("Cách đọc không được chứa lại chính chữ cần dạy — viết hẳn ra cách đọc.")
    _ensure()
    rec = {"chu": chu, "doc": doc, "luc": int(time.time())}
    with _lock:
        _data[_khoa(chu)] = rec
        _save()
        _doi_so()
    return dict(rec)


def xoa(chu: str) -> bool:
    _ensure()
    with _lock:
        k = _khoa(" ".join(str(chu or "").split()))
        if k not in _data:
            return False
        del _data[k]
        _save()
        _doi_so()
    return True


def _regex() -> re.Pattern | None:
    global _mau
    _ensure()
    with _lock:
        if _mau is None and _data:
            hoa = sorted((k for k in _data if k != k.lower()), key=len, reverse=True)
            thuong = sorted((k for k in _data if k == k.lower()), key=len, reverse=True)
            phan = []
            if hoa:
                phan.append("(?-i:" + "|".join(map(re.escape, hoa)) + ")")
            if thuong:
                phan.append("|".join(map(re.escape, thuong)))
            # Ranh giới chữ ở hai đầu: "TV" không khớp trong "TVB", "smart" không trong "smartphone".
            _mau = re.compile(r"(?<!\w)(?:" + "|".join(phan) + r")(?!\w)", re.IGNORECASE)
        return _mau


def ap(text: str) -> str:
    """Thay mọi chữ đã dạy bằng cách đọc của nó."""
    mau = _regex()
    if not text or mau is None:
        return text
    with _lock:
        bang = dict(_data)

    def _thay(m: re.Match) -> str:
        rec = bang.get(m.group(0)) or bang.get(m.group(0).lower())
        return rec["doc"] if rec else m.group(0)
    return mau.sub(_thay, text)
