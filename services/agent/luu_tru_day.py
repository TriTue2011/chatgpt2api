"""Đẩy tệp lên kho đám mây — chờ admin xác nhận, rồi chạy nền.

Hai phần:

* **Chờ xác nhận.** Tệp vừa tới thì hỏi admin "1. Lưu / 2. Luôn luôn lưu /
  3. Xoá" rồi mới làm gì. Thứ tự HỎI TRƯỚC ĐẨY SAU là bắt buộc: chủ máy chốt
  "xoá là không đẩy lên online vì không muốn lưu file cục bộ", nên không được
  có cảnh tệp đã nằm trên mây rồi mới nhận lệnh xoá.
* **Đẩy nền.** Đẩy 3 MB lên Drive mất vài giây; làm ngay trong lượt chat là bắt
  người dùng ngồi chờ. Chạy luồng riêng, hỏng thì ghi log rồi thôi — mạng chập
  hay Drive đầy không được làm gãy luồng trả lời.

Bản chờ giữ trong bộ nhớ tiến trình, có hạn: khởi động lại là mất, và mất thì
tệp cục bộ vẫn còn nguyên theo hạn giữ cũ. Không đáng dựng thêm một kho trên đĩa
chỉ để nhớ một câu hỏi đang treo.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from services.agent import luu_tru_online as lt
from utils.log import logger

# Câu hỏi treo quá lâu thì bỏ — admin đã lướt qua, đừng để nó trả lời "1" cho
# một tệp từ hôm kia.
_HAN_CHO_S = 30 * 60
_cho: dict[str, dict] = {}
_khoa = threading.RLock()

LUA_CHON = ("Lưu", "Luôn luôn lưu (khỏi hỏi lại)", "Xoá")


def cau_hoi(ten_tep: str, *, ten_nhom: str = "") -> str:
    """Khối lựa chọn gửi cho admin. Ba lựa chọn, đánh số, bấm chọn được."""
    o = f" từ {ten_nhom}" if ten_nhom else ""
    return (f"📎 Nhận tệp {ten_tep}{o} — lưu lên kho đám mây ạ?\n"
            "<<<ASK>>>\n"
            f"{LUA_CHON[0]} | lưu tệp vừa nhận lên kho online\n"
            f"{LUA_CHON[1]} | luôn luôn lưu tệp của phạm vi này lên kho online\n"
            f"{LUA_CHON[2]} | xoá tệp vừa nhận, không lưu\n"
            "<<<END>>>")


def dat_cho(khoa_admin: str, *, tep: str, kenh: str, chat: str,
            topic: str = "", user: str = "") -> None:
    """Ghi nhận một tệp đang chờ admin trả lời."""
    with _khoa:
        _don_het_han()
        _cho[str(khoa_admin)] = {"tep": str(tep), "kenh": kenh, "chat": chat,
                                 "topic": topic, "user": user, "luc": time.time()}


def lay_cho(khoa_admin: str) -> dict:
    with _khoa:
        _don_het_han()
        return dict(_cho.get(str(khoa_admin)) or {})


def bo_cho(khoa_admin: str) -> None:
    with _khoa:
        _cho.pop(str(khoa_admin), None)


def _don_het_han() -> None:
    nay = time.time()
    for k in [k for k, v in _cho.items() if nay - float(v.get("luc") or 0) > _HAN_CHO_S]:
        _cho.pop(k, None)


def tra_loi(khoa_admin: str, chon: int) -> dict:
    """Xử lý lựa chọn của admin. chon: 1=lưu, 2=luôn luôn lưu, 3=xoá.

    Trả {ok, text} — `text` là câu báo lại cho admin.
    """
    ban = lay_cho(khoa_admin)
    if not ban:
        return {"ok": False, "text": "Không còn tệp nào đang chờ ạ."}
    bo_cho(khoa_admin)
    tep = str(ban.get("tep") or "")
    ten = Path(tep).name

    if chon == 3:
        _xoa_cuc_bo(tep)
        return {"ok": True, "text": f"Đã bỏ {ten}, không lưu lên đâu cả ạ."}

    if chon == 2:
        lt.dat_luon_luon_luu(ban["kenh"], ban["chat"],
                             ban.get("topic") or "", ban.get("user") or "")

    cd = lt.cai_dat(ban["kenh"], ban["chat"], ban.get("topic") or "",
                    ban.get("user") or "")
    day_nen(tep, cd)
    them = " Từ giờ phạm vi này tự lưu, khỏi hỏi lại ạ." if chon == 2 else ""
    return {"ok": True, "text": f"Đang lưu {ten} lên kho đám mây.{them}"}


def _xoa_cuc_bo(tep: str) -> None:
    try:
        os.unlink(tep)
    except OSError:
        pass


def day_nen(tep: str, cd: dict, *, nhat_ky: bool = False) -> bool:
    """Đẩy một tệp lên kho, chạy ở luồng riêng. Trả False nếu chưa bật.

    Không bao giờ ném lỗi ra ngoài: đây là việc phụ, hỏng thì chat vẫn phải chạy.
    """
    if not (cd or {}).get("enabled"):
        return False
    dich = lt.duong_dan_dich(cd, Path(tep).name, nhat_ky=nhat_ky)
    if not dich:
        return False
    threading.Thread(target=_day, args=(tep, dich), daemon=True).start()
    return True


def _day(tep: str, dich: str) -> None:
    try:
        from services import rclone_service as rcl
        kq = rcl.gui_len(tep, dich)
        if kq.get("ok"):
            logger.info("luu_tru_online: đã đẩy %s → %s", Path(tep).name, dich)
        else:
            logger.warning("luu_tru_online: đẩy %s hỏng: %s",
                           Path(tep).name, str(kq.get("error"))[:150])
    except Exception as exc:
        logger.warning("luu_tru_online: đẩy %s lỗi: %s", Path(tep).name, str(exc)[:150])
