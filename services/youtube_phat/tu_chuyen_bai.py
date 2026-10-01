"""Tự chuyển bài phía máy chủ c2a — tắt trình duyệt, bot đã trả lời xong, nhạc vẫn chạy tiếp.

Chủ máy 14/09/2026: "tắt trình duyệt vẫn hoạt động". Tab web và bot mở phiên với
controller "c2a"; luồng nền này nhìn loa dẫn của từng phiên đó (loa nhận luồng
âm thanh — tivi mở ứng dụng YouTube gốc không báo hết bài) và khi loa hết bài thì
phát bài kế trong hàng đợi của phiên ra đúng các loa đó. Cùng luật với tích hợp HA
(`custom_components/tritue_youtube_player/sessions.observe_track`): tạm dừng không
tính, dừng giữa bài (còn hơn 15 giây) không chuyển mà bỏ loa đó khỏi phiên; nội dung khác (TTS)
chen giữa bài thì đọc xong phát tiếp đúng giây đang dở.
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
#: Phát tiếp sau khi bị chen: chờ loa phát lại tối đa ngần này giây rồi tua; dưới `TUA_TOI_THIEU` giây thì khỏi tua.
CHO_TUA_GIAY = 15.0
TUA_TOI_THIEU = 3.0

_khoa = threading.Lock()
_luong: threading.Thread | None = None
_theo_doi: dict[tuple, dict[str, Any]] = {}


def quan_sat(tracker: dict[str, Any], trang_thai: str, vi_tri: float | None,
             thoi_luong: float | None, bay_gio: float) -> bool:
    """Nạp một lần đọc trạng thái loa; True đúng một lần khi bài vừa hết."""
    if trang_thai in DANG_PHAT:
        tracker["da_phat"] = True
        tracker.setdefault("bat_dau", bay_gio)
        if vi_tri is not None:
            tracker["vi_tri"], tracker["luc"] = float(vi_tri), bay_gio
        if thoi_luong:
            tracker["thoi_luong"] = float(thoi_luong)
        return False
    if trang_thai not in DA_XONG or not tracker.get("da_phat"):
        return False
    tracker["da_phat"] = False
    vi_tri, luc = tracker.get("vi_tri"), tracker.get("luc")
    if vi_tri is None and tracker.get("bat_dau") is not None:
        vi_tri, luc = 0.0, tracker["bat_dau"]      # loa không báo vị trí: đếm từ lúc thấy nó phát bài này
    tracker.pop("bat_dau", None)
    # Không biết thời lượng thì loa về nghỉ KHÔNG phải hết bài (youtube issue #3: mỗi lần bấm Stop trên loa không
    # báo media_duration là nhảy sang bài kế).
    if not tracker.get("thoi_luong") or vi_tri is None:
        return False
    if vi_tri + max(0.0, bay_gio - luc) >= tracker["thoi_luong"] - SAI_SO_CUOI_BAI:
        return True
    tracker["dung_som"] = True                     # dừng giữa bài — bên gọi bỏ loa khỏi phiên
    return False


def quan_sat_chen(tracker: dict[str, Any], thiet_bi: dict[str, Any], dang_bai: bool, bay_gio: float) -> float | None:
    """Loa dẫn bị CHEN (TTS, thông báo) giữa bài: trả GIÂY cần phát tiếp đúng một lần khi nội dung chen dứt.

    Chủ máy 30/09/2026: "đang phát nhạc, tts thì nhạc dừng không". Loa Google / R1 phát TTS là thay luôn bài, không
    tự phát lại. Dấu hiệu: đã phát luồng của phiên rồi báo nội dung khác — nhớ giây đang dở; nội dung ấy dứt thì
    phát tiếp. Loa tự quay về luồng của mình thì thôi."""
    trang_thai = thiet_bi["trang_thai"]
    if thiet_bi.get("muc_dang_phat"):
        if dang_bai:
            tracker.pop("chen_tu", None)
            tracker["luong_minh"] = True
        return None
    if (trang_thai in DANG_PHAT and thiet_bi.get("ma_ngoai_bam") and not dang_bai
            and tracker.get("luong_minh") and "chen_tu" not in tracker):
        if tracker.get("vi_tri") is None:
            return None
        giay = tracker["vi_tri"] + max(0.0, bay_gio - tracker["luc"])
        if tracker.get("thoi_luong") and giay >= tracker["thoi_luong"] - SAI_SO_CUOI_BAI:
            return None                            # gần hết bài: để chuyển bài như thường
        tracker["chen_tu"] = giay
        tracker["da_phat"] = False                 # TTS dứt không phải hết bài
        return None
    if "chen_tu" in tracker and (trang_thai in DA_XONG or trang_thai == "paused"):
        tracker["luong_minh"] = False
        return tracker.pop("chen_tu")
    return None


def _tua_khi_phat_lai(p: dict[str, Any], tracker: dict[str, Any], dan: dict[str, Any], theo_ma: dict,
                      dang_bai: bool, bay_gio: float) -> None:
    """Sau khi phát lại bài bị chen: loa dẫn phát đúng bài thì tua mọi loa của phiên có tua tới giây đang dở."""
    from . import phat_ha

    tua = tracker.get("tua_toi")
    if tua is None:
        return
    if bay_gio - tua[1] > CHO_TUA_GIAY:
        tracker.pop("tua_toi", None)
        return
    if dan["trang_thai"] not in DANG_PHAT or not dan.get("muc_dang_phat") or not dang_bai:
        return
    tracker.pop("tua_toi", None)
    for e in p["output_entity_ids"]:
        if theo_ma.get(e, {}).get("tua"):
            phat_ha.goi_loa("media_player", "media_seek", {"entity_id": e, "seek_position": float(tua[0])})


def mot_vong(bay_gio: float | None = None) -> list[str]:
    """Một lượt kiểm; trả session_id đã chuyển bài (để test)."""
    from . import dich_vu, hang_cho, phat_ha

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
        dang_bai = phat_ha.dang_phat_bai(dan, p.get("item"), tracker)
        _tua_khi_phat_lai(p, tracker, dan, theo_ma, dang_bai, bay_gio)
        tiep = quan_sat_chen(tracker, dan, dang_bai, bay_gio)
        if tiep is not None:
            try:
                phat_ha.phat_bai_trong_phien(p, p.get("item") or {})
                if tiep >= TUA_TOI_THIEU:
                    tracker["tua_toi"] = (tiep, bay_gio)
                logger.info({"event": "youtube_phat_tiep_sau_chen", "phien": p["session_id"], "giay": round(tiep)})
            except (ValueError, OSError, RuntimeError) as error:
                logger.warning({"event": "youtube_phat_tiep_sau_chen_loi", "phien": p["session_id"],
                                "loi": str(error)[:160]})
            continue
        if "chen_tu" in tracker:
            continue  # đang bị chen: TTS dứt không phải hết bài
        if dan["trang_thai"] in DANG_PHAT and not dang_bai:
            continue  # loa còn báo bài trước / nội dung khác: chưa phải bài của phiên này
        if dan["trang_thai"] in DANG_PHAT and dan.get("muc_dang_phat"):
            tracker["luong_minh"] = True
        if not quan_sat(tracker, dan["trang_thai"], dan.get("vi_tri"), dan.get("thoi_luong") or (p.get("item") or {}).get("duration"), bay_gio):
            if tracker.pop("dung_som", False):
                # Bấm Stop trên loa (dừng xa cuối bài): bỏ loa đó khỏi phiên thay vì nhảy bài; phiên một loa thì kết
                # thúc (youtube issue #3).
                con = [e for e in p["output_entity_ids"] if e != dan["entity_id"]]
                try:
                    dich_vu.core().set_session_outputs(p["session_id"], con)
                    logger.info({"event": "youtube_phat_loa_dung_som", "phien": p["session_id"],
                                 "loa": dan["entity_id"]})
                except (ValueError, OSError, RuntimeError) as error:
                    logger.warning({"event": "youtube_phat_bo_loa_loi", "phien": p["session_id"],
                                    "loi": str(error)[:160]})
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
