"""Theo dõi CHỦ ĐỀ tin tức — bù chỗ quote không xuyên được thời gian.

Người dùng hỏi "vụ cháy Hải Dương" rồi muốn quay lại hỏi "có gì mới không" sau
vài ngày. Quote chỉ trỏ được vào MỘT tin cũ; theo dõi chủ đề thì bot nhớ CHỦ ĐỀ
và tự đi lấy tin mới nhất (qua web_search), kể cả khi người dùng không còn tin
gốc để reply. Nhiều bot tin tức/chứng khoán chuyển sang mô hình này thay vì phụ
thuộc tính năng reply của nền tảng.

Sổ JSON theo người: ``{user_id: [ {chu_de, ts}, … ]}`` (mới nhất trước, chặn
`_TOI_DA` chủ đề mỗi người). Nhẹ — mất sổ chỉ mất danh sách theo dõi, không hỏng
gì khác. Liên quan: [[so_da_luu]] (cùng nếp sổ-theo-người).
"""
from __future__ import annotations

import json
import logging
import threading
import time

logger = logging.getLogger(__name__)

_TOI_DA = 30
_lock = threading.Lock()


def _fold(s: str) -> str:
    b = "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    k = "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd"
    return " ".join((s or "").lower().translate(str.maketrans(b, k)).split())


def _duong():
    from pathlib import Path

    from services.config import DATA_DIR
    return Path(DATA_DIR) / "agent" / "tracked_topic.json"


def _doc() -> dict[str, list[dict]]:
    try:
        p = _duong()
        if p.is_file():
            d = json.loads(p.read_text("utf-8") or "{}")
            return d if isinstance(d, dict) else {}
    except Exception as exc:
        logger.warning("tracked_topic: đọc sổ lỗi: %s", exc)
    return {}


def _ghi_file(d: dict) -> None:
    try:
        p = _duong()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
    except Exception as exc:
        logger.warning("tracked_topic: ghi sổ lỗi: %s", exc)


def them(user_id: str, chu_de: str) -> bool:
    """Thêm/nâng-lên-đầu một chủ đề theo dõi. Trả True nếu ghi được."""
    uid = str(user_id or "").strip()
    cd = str(chu_de or "").strip()
    if not uid or not cd:
        return False
    f = _fold(cd)
    with _lock:
        d = _doc()
        ds = [m for m in (d.get(uid) or [])
              if isinstance(m, dict) and _fold(str(m.get("chu_de"))) != f]
        ds.insert(0, {"chu_de": cd[:200], "ts": time.time()})
        d[uid] = ds[:_TOI_DA]
        _ghi_file(d)
    return True


def liet_ke(user_id: str) -> list[dict]:
    """Danh sách chủ đề đang theo dõi của người này (mới nhất trước)."""
    uid = str(user_id or "").strip()
    if not uid:
        return []
    return [m for m in _doc().get(uid) or [] if isinstance(m, dict)]


def xoa(user_id: str, chu_de: str) -> bool:
    """Bỏ theo dõi chủ đề khớp (so khớp không dấu, chứa chuỗi). True nếu có bỏ."""
    uid = str(user_id or "").strip()
    f = _fold(chu_de)
    if not uid or not f:
        return False
    with _lock:
        d = _doc()
        cu = [m for m in (d.get(uid) or []) if isinstance(m, dict)]
        moi = [m for m in cu if f not in _fold(str(m.get("chu_de")))]
        if len(moi) == len(cu):
            return False
        d[uid] = moi
        _ghi_file(d)
    return True


def gan_nhat(user_id: str) -> str:
    """Chủ đề theo dõi gần nhất — cho câu 'có gì mới không' không nêu chủ đề."""
    ds = liet_ke(user_id)
    return str(ds[0].get("chu_de")) if ds else ""
