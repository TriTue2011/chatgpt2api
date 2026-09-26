"""Lịch sinh hoạt của cả nhà — chủ máy khai, bot dùng chung cho MỌI thiết bị.

Chủ máy 26/09/2026: "Giờ dậy buổi sáng, giờ nghỉ trưa, giờ ngủ buổi tối, giờ đi làm …
chưa kể chia theo thứ. Ví dụ thứ 7 vợ hay nghỉ, tôi nghỉ chủ nhật" — và "không phải áp
dụng riêng mà là cơ chế chung cho toàn bộ thiết bị".

Mỗi mục: ``{"ma", "ten", "loai", "tu", "den", "thu"}`` — ``thu`` là các ngày trong tuần
(0 = thứ 2 … 6 = chủ nhật). Mục qua nửa đêm (21:45–06:00) THUỘC NGÀY BẮT ĐẦU: "Ngủ, thứ 6"
vẫn đang diễn ra lúc 02:00 sáng thứ 7.

Ai dùng:

* `kich_hoat_nha` — khung giờ ngoại lệ của một thiết bị có thể ĐI THEO một mục lịch
  (``{"lich": "ngu"}``) thay cho giờ cố định; mỗi mục lịch cũng là một đặc trưng cho cây
  học ("đang giờ Ăn tối"), để bot phân biệt được thứ 2 ăn muộn với thứ 3 ăn sớm.

Lịch là lời KHAI của chủ máy, không phải dữ liệu đo — đúng "thường thường", có hôm lệch.
Nên lịch không tự bật/tắt gì; nó chỉ đổi cách bot cân nhắc.
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.config import DATA_DIR

_TZ = timezone(timedelta(hours=7))
_PATH = Path(DATA_DIR) / "agent" / "lich_sinh_hoat.json"

#: Loại mục — tập đóng để bot biết mục ấy NGHĨA là gì mà không phải khớp chữ trong tên:
#: "ngu" (cả nhà ngủ), "vang" (thường không ai ở nhà), "an" (bữa ăn), "khac".
LOAI = ("ngu", "vang", "an", "khac")
TOI_DA = 40
_GIO = re.compile(r"([01]\d|2[0-3]):[0-5]\d")

_khoa = threading.RLock()
_du_lieu: list[dict[str, Any]] | None = None


def ds() -> list[dict[str, Any]]:
    global _du_lieu
    with _khoa:
        if _du_lieu is None:
            try:
                _du_lieu = json.loads(_PATH.read_text(encoding="utf-8")).get("muc", []) if _PATH.is_file() else []
            except (OSError, ValueError, AttributeError):
                _du_lieu = []
        return [dict(x) for x in _du_lieu]


def _ma_tu_ten(ten: str, da_co: set[str]) -> str:
    """Mã BỀN cho mục mới: khung giờ của thiết bị trỏ tới mục bằng mã này, nên không được
    sinh theo vị trí (xoá một mục phía trên là mọi mục sau đổi mã, khung trỏ nhầm)."""
    goc = "".join(c for c in unicodedata.normalize("NFD", ten.lower().replace("đ", "d"))
                  if unicodedata.category(c) != "Mn")
    goc = re.sub(r"[^a-z0-9]+", "_", goc).strip("_")[:20] or "muc"
    ma, i = goc, 2
    while ma in da_co:
        ma, i = f"{goc}_{i}", i + 1
    return ma


def _chuan(x: Any) -> dict[str, Any]:
    if not isinstance(x, dict):
        raise ValueError("Mỗi mục lịch phải là {ten, loai, tu, den, thu}.")
    ten = str(x.get("ten") or "").strip()
    if not ten or len(ten) > 40:
        raise ValueError("Tên mục lịch phải có, tối đa 40 chữ.")
    if x.get("loai", "khac") not in LOAI:
        raise ValueError(f"Loại mục lịch phải là một trong {', '.join(LOAI)}.")
    if not all(_GIO.fullmatch(str(x.get(k) or "")) for k in ("tu", "den")) or x["tu"] == x["den"]:
        raise ValueError(f"«{ten}»: giờ phải dạng HH:MM và từ ≠ đến.")
    thu = sorted({int(t) for t in x.get("thu") or []})
    if not thu or any(not 0 <= t <= 6 for t in thu):
        raise ValueError(f"«{ten}»: chọn ít nhất một ngày (0 = thứ 2 … 6 = chủ nhật).")
    ma = str(x.get("ma") or "").strip()
    if ma and not re.fullmatch(r"[a-z0-9_]{1,24}", ma):
        raise ValueError(f"«{ten}»: mã chỉ gồm chữ thường không dấu, số, gạch dưới.")
    return {"ma": ma, "ten": ten, "loai": str(x.get("loai") or "khac"), "tu": x["tu"], "den": x["den"], "thu": thu}


def dat(muc: list[Any]) -> list[dict[str, Any]]:
    """Thay TOÀN BỘ lịch. Mã trùng hoặc sai kiểu → ValueError, không ghi gì."""
    global _du_lieu
    if len(muc) > TOI_DA:
        raise ValueError(f"Lịch tối đa {TOI_DA} mục.")
    moi = [_chuan(x) for x in muc]
    co_ma = [x["ma"] for x in moi if x["ma"]]
    if len(set(co_ma)) != len(co_ma):
        raise ValueError("Hai mục lịch trùng mã.")
    da_co = set(co_ma)
    for x in moi:
        if not x["ma"]:
            x["ma"] = _ma_tu_ten(x["ten"], da_co)
            da_co.add(x["ma"])
    with _khoa:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"muc": moi}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(_PATH)
        _du_lieu = moi
    return [dict(x) for x in moi]


def _phut(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def trong(x: dict[str, Any], luc: float) -> bool:
    """Lúc ``luc`` có nằm trong mục ``x`` không — mục qua nửa đêm tính theo ngày bắt đầu."""
    d = datetime.fromtimestamp(luc, _TZ)
    p, a, b = d.hour * 60 + d.minute, _phut(x["tu"]), _phut(x["den"])
    if a < b:
        return a <= p < b and d.weekday() in x["thu"]
    if p >= a:
        return d.weekday() in x["thu"]
    return p < b and (d.weekday() - 1) % 7 in x["thu"]


def dang(luc: float) -> list[dict[str, Any]]:
    return [x for x in ds() if trong(x, luc)]


def tim(ma: str) -> dict[str, Any] | None:
    return next((x for x in ds() if x["ma"] == ma), None)


def _reset_for_tests(duong: Path) -> None:
    global _PATH, _du_lieu
    _PATH = duong
    _du_lieu = None
