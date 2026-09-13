"""Thiết bị chủ máy BỎ KHỎI c2a — vẫn còn nguyên trong Home Assistant/MQTT/Tuya.

Chủ máy 13/09/2026: *"Thêm cả nút xóa thiết bị trong thiết bị và tên để xóa các
thiết bị không cần thiết"*, và chọn: bỏ khỏi c2a (không xoá trong HA), xoá luôn
lịch sử c2a đã ghi.

Bỏ nghĩa là c2a coi như không có thiết bị đó:

* không đọc thấy — `ha_client.get_states`/`get_state`/gương `ha_live` ẩn thực
  thể HA; `mqtt_nha.danh_sach_thiet_bi` và `tuya_nha.danh_sach_thiet_bi` bỏ
  thiết bị MQTT/Tuya, nên bot không đưa vào ngữ cảnh, không điều khiển, không học;
* không ghi lịch sử mới — `lich_su_nha.ghi`;
* lịch sử cũ bị xoá lúc bỏ — `lich_su_nha.xoa_thiet_bi`.

Sổ là file JSON riêng, KHÔNG đi qua `/api/settings`: thẻ web nào nạp config cũ
rồi lưu nguyên khối sẽ ghi đè mất sổ (bẫy #9 của kho).

Mỗi mục lưu thêm thứ cần để khôi phục và để khớp lịch sử:
* `ten_goc` — trang Thiết bị & tên vẫn hiện được mục đã bỏ;
* `goc` (MQTT) — gốc CHỦ ĐỀ mà lịch sử ghi theo (`zigbee2mqtt/Hiện diện bếp`,
  `frigate/bep`), vì danh sách MQTT đặt tên theo tên thiết bị tự khai báo còn
  lịch sử thì ghi theo chủ đề;
* `ten_lich_su` (Tuya) — tên `tuya_local` ghi vào lịch sử.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR

logger = logging.getLogger(__name__)

_FILE = Path(DATA_DIR) / "agent" / "thiet_bi_da_bo.json"
_khoa = threading.Lock()
#: Bộ nhớ đệm — `la_bo_lich_su` chạy cho MỌI tin MQTT (hàng trăm tin/phút) và
#: `la_bo_ha` cho mỗi lần đọc trạng thái HA, nên không được đọc đĩa mỗi lần.
_dem: dict[str, Any] | None = None

NGUON = ("ha", "mqtt", "tuya")


def khoa(nguon: str, ma: str) -> str:
    return f"{nguon}:{ma}"


def _nap() -> dict[str, Any]:
    global _dem
    if _dem is not None:
        return _dem
    try:
        with open(_FILE, encoding="utf-8") as f:
            so = json.load(f)
        so = so if isinstance(so, dict) else {}
    except (OSError, ValueError):
        so = {}
    _dem = {
        "so": so,
        "ha": {m["ma"] for m in so.values() if m.get("nguon") == "ha"},
        "ten": {t for m in so.values() if m.get("nguon") == "tuya"
                for t in (m.get("ten_lich_su") or [])},
        "goc": sorted({m["goc"] for m in so.values() if m.get("nguon") == "mqtt" and m.get("goc")}),
        "mqtt": {m["ma"] for m in so.values() if m.get("nguon") == "mqtt"},
        "tuya": {m["ma"] for m in so.values() if m.get("nguon") == "tuya"},
    }
    return _dem


def _luu(so: dict[str, Any]) -> None:
    """Ghi nguyên tử (.tmp rồi replace), rồi bỏ bộ nhớ đệm."""
    global _dem
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(so, f, ensure_ascii=False, indent=1)
    tmp.replace(_FILE)
    _dem = None


def goc_chu_de(chu_de: list[str]) -> str:
    """Gốc chung theo TỪNG ĐOẠN của các chủ đề một thiết bị MQTT.

    Trả rỗng khi gốc chỉ còn một đoạn (`zigbee2mqtt`): bỏ theo gốc đó là bỏ cả
    nhánh của mọi thiết bị khác.
    """
    phan = [c.strip("/").split("/") for c in chu_de if c and c.strip("/")]
    if not phan:
        return ""
    chung = phan[0]
    for p in phan[1:]:
        n = 0
        while n < min(len(chung), len(p)) and chung[n] == p[n]:
            n += 1
        chung = chung[:n]
    return "/".join(chung) if len(chung) >= 2 else ""


def bo(nguon: str, ma: str, *, ten_goc: str = "", goc: str = "",
       ten_lich_su: list[str] | None = None) -> dict[str, Any]:
    """Ghi một thiết bị vào sổ bỏ. Trả mục đã ghi."""
    return bo_nhieu([{"nguon": nguon, "ma": ma, "ten_goc": ten_goc, "goc": goc,
                      "ten_lich_su": ten_lich_su}])[0]


def bo_nhieu(ds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ghi nhiều thiết bị vào sổ bỏ bằng MỘT lần ghi đĩa — chủ máy bỏ hơn 100
    mục một lượt (13/09/2026). Mục nào sai thì không ghi mục nào."""
    now = time.time()
    muc: list[dict[str, Any]] = []
    for x in ds:
        nguon, ma, goc = x.get("nguon"), x.get("ma"), x.get("goc") or ""
        if nguon not in NGUON or not ma:
            raise ValueError("nguồn hoặc mã không hợp lệ")
        if nguon == "mqtt" and not goc:
            raise ValueError("thiết bị MQTT cần gốc chủ đề để khớp lịch sử")
        muc.append({"nguon": nguon, "ma": ma, "ten_goc": x.get("ten_goc") or ma, "goc": goc,
                    "ten_lich_su": list(x.get("ten_lich_su") or []), "luc": now})
    with _khoa:
        so = dict(_nap()["so"])
        for m in muc:
            so[khoa(m["nguon"], m["ma"])] = m
        _luu(so)
    logger.info({"event": "thiet_bi_bo", "so": len(muc),
                 "ma": [m["ma"][:60] for m in muc[:5]]})
    return muc


def bo_lai(nguon: str, ma: str) -> bool:
    """Khôi phục — thiết bị hiện lại và ghi lịch sử từ giờ (lịch sử cũ đã mất)."""
    with _khoa:
        so = dict(_nap()["so"])
        if so.pop(khoa(nguon, ma), None) is None:
            return False
        _luu(so)
    logger.info({"event": "thiet_bi_bo_lai", "nguon": nguon, "ma": ma[:80]})
    return True


def danh_sach() -> list[dict[str, Any]]:
    return sorted(_nap()["so"].values(), key=lambda m: (m["nguon"], m["ten_goc"].lower()))


def la_bo(nguon: str, ma: str) -> bool:
    return ma in _nap().get(nguon, set())


def co_bo(nguon: str) -> bool:
    """Nguồn này có thiết bị nào bị bỏ không — để đường nóng khỏi lọc suông."""
    return bool(_nap().get(nguon))


def la_bo_lich_su(thiet_bi: str) -> bool:
    """Mã `thiet_bi` của một dòng lịch sử có thuộc thiết bị đã bỏ không."""
    d = _nap()
    if thiet_bi in d["ha"] or thiet_bi in d["ten"]:
        return True
    return any(thiet_bi == g or thiet_bi.startswith(g + "/") for g in d["goc"])


def _reset_for_tests() -> None:
    global _dem
    _dem = None
