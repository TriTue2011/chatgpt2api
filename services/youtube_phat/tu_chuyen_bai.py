"""Tự chuyển bài phía máy chủ c2a — tắt trình duyệt, bot đã trả lời xong, nhạc vẫn chạy tiếp.

Chủ máy 14/09/2026: "tắt trình duyệt vẫn hoạt động". Tab web và bot mở phiên với
controller "c2a"; luồng nền này nhìn loa dẫn của từng phiên đó (loa nhận luồng
âm thanh — tivi mở ứng dụng YouTube gốc không báo hết bài) và khi loa hết bài thì
phát bài kế trong hàng đợi của phiên ra đúng các loa đó. Cùng luật với tích hợp HA
(`custom_components/tritue_youtube_player/sessions.observe_track`): tạm dừng không
tính, dừng giữa bài (còn hơn 15 giây) không chuyển.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from utils.log import logger

NHIP_GIAY = 3.0
SAI_SO_CUOI_BAI = 15
DANG_PHAT = {"playing", "buffering"}
DA_XONG = {"idle", "off", "standby"}

_khoa = threading.Lock()
_luong: threading.Thread | None = None
_theo_doi: dict[tuple, dict[str, Any]] = {}


def quan_sat(tracker: dict[str, Any], trang_thai: str, vi_tri: float | None,
             thoi_luong: float | None, bay_gio: float) -> bool:
    """Nạp một lần đọc trạng thái loa; True đúng một lần khi bài vừa hết."""
    if trang_thai in DANG_PHAT:
        tracker["da_phat"] = True
        if vi_tri is not None:
            tracker["vi_tri"], tracker["luc"] = float(vi_tri), bay_gio
        if thoi_luong:
            tracker["thoi_luong"] = float(thoi_luong)
        return False
    if trang_thai not in DA_XONG or not tracker.get("da_phat"):
        return False
    tracker["da_phat"] = False
    if not tracker.get("thoi_luong") or tracker.get("vi_tri") is None:
        return True
    uoc = tracker["vi_tri"] + max(0.0, bay_gio - tracker["luc"])
    return uoc >= tracker["thoi_luong"] - SAI_SO_CUOI_BAI


def mot_vong(bay_gio: float | None = None) -> list[str]:
    """Một lượt kiểm; trả session_id đã chuyển bài (để test)."""
    from . import hang_cho, phat_ha

    bay_gio = time.monotonic() if bay_gio is None else bay_gio
    phien = [p for p in phat_ha.cac_phien()
             if p.get("controller") == phat_ha.CONTROLLER and p.get("auto_advance", True)]
    if not phien:
        _theo_doi.clear()
        return []
    theo_ma = {d["entity_id"]: d for d in phat_ha.danh_sach()}
    song = set()
    da_chuyen = []
    for p in phien:
        nguon = str((p.get("item") or {}).get("source") or "")
        dan = next((theo_ma[e] for e in p["output_entity_ids"]
                    if e in theo_ma and not (nguon == "youtube" and theo_ma[e]["youtube"] == "goc")), None)
        if dan is None:
            continue
        hang = p.get("queue") or {}
        khoa = (p["session_id"], (p.get("item") or {}).get("id"), hang.get("index"), dan["entity_id"])
        song.add(khoa)
        tracker = _theo_doi.setdefault(khoa, {})
        if dan["trang_thai"] in DANG_PHAT and not phat_ha.dang_phat_bai(dan, p.get("item")):
            continue  # loa còn báo bài trước: chưa phải bài của phiên này
        if not quan_sat(tracker, dan["trang_thai"], dan.get("vi_tri"), dan.get("thoi_luong") or (p.get("item") or {}).get("duration"), bay_gio):
            continue
        # Queue của loa tích đầu tiên đi TRƯỚC hàng đợi phiên (chủ máy 23/09/2026).
        # Phát một bài từ ô tìm kiếm thì hàng đợi phiên chính là kết quả tìm kiếm
        # (session.py `_search_queues`) — không ưu tiên thì Queue không tới lượt.
        # Hết Queue thì phiên chạy tiếp như cũ (kết quả tìm / playlist đã chọn).
        loa_dau = p["output_entity_ids"][0]
        try:
            if hang_cho.kho().co_bai_ke(loa_dau):
                bai = hang_cho.kho().tiep(loa_dau)
                if bai:
                    phat_ha.phat_bai_trong_phien(p, bai)
                    da_chuyen.append(p["session_id"])
                continue
        except (ValueError, OSError, RuntimeError) as error:
            logger.warning({"event": "youtube_phat_queue_loi", "phien": p["session_id"], "loi": str(error)[:160]})
            continue
        if int(hang.get("index", -1)) + 1 >= len(hang.get("items") or []):
            continue
        try:
            phat_ha.chuyen_bai(p["session_id"], 1)
            da_chuyen.append(p["session_id"])
        except (ValueError, OSError, RuntimeError) as error:
            logger.warning({"event": "youtube_phat_tu_chuyen_bai_loi", "phien": p["session_id"], "loi": str(error)[:160]})
    for khoa in list(_theo_doi):
        if khoa not in song:
            del _theo_doi[khoa]
    return da_chuyen


def _chay() -> None:
    while True:
        time.sleep(NHIP_GIAY)
        try:
            mot_vong()
        except Exception as error:  # luồng nền không được chết vì một lượt hỏng
            logger.warning({"event": "youtube_phat_tu_chuyen_bai_vong_loi", "loi": str(error)[:160]})


def dam_bao_chay() -> None:
    """Khởi động luồng nền lần đầu có phiên do c2a mở."""
    global _luong
    with _khoa:
        if _luong is None or not _luong.is_alive():
            _luong = threading.Thread(target=_chay, name="youtube-phat-tu-chuyen-bai", daemon=True)
            _luong.start()
