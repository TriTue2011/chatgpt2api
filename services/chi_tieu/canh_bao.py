"""Cảnh báo chủ động — chuyển từ ``chi-tieu-mcp/app/alerts.py`` (Quiz99, MIT).

Bản gốc gửi MỘT người qua ``/api/zalo-personal/test-send``. Ở c2a mỗi sổ gửi tới mọi kênh chat ĐÃ LIÊN KẾT với
sổ đó, qua đúng đường gửi của nhắc việc (`services/agent/reminders._send`: Telegram, Zalo Bot, Zalo Cá Nhân —
đúng bot / tài khoản đã nhận tin lúc liên kết). Mỗi mốc gửi một lần mỗi kỳ; nhiều mốc cùng đạt thì chỉ gửi mốc
cao nhất (bot vừa khởi động lại không dội 65% rồi 80% rồi 100%).
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any, Callable

from services.chi_tieu import kho, ngan_sach as ns
from utils.log import logger

CHU_KY_GIAY = 1800
MA_TONG, MA_TONG_VUOT = "__tong__", "__tong_vuot__"
_da_chay = False


def co_the_nhan_tin(kenh_user: str) -> bool:
    """Liên kết nào gửi tin riêng được: chat web không có kênh đẩy, còn người trong NHÓM (`zalop_<nhóm>:u<người>`)
    thì gửi vào nhóm là lộ số tiền cho cả nhóm."""
    return not kenh_user.startswith("web_") and ":u" not in kenh_user


def _gui(so_id: int, tin: str) -> int:
    from services.agent import reminders
    n = 0
    for lk in kho.kenh_cua_so(so_id):
        if not co_the_nhan_tin(lk["kenh_user"]):
            continue
        kenh, chat_id = reminders.channel_of(lk["kenh_user"])
        try:
            reminders._send(kenh, chat_id, tin, lk.get("meta") or {})
            n += 1
        except Exception as exc:  # noqa: BLE001 — một kênh hỏng không chặn kênh khác, vòng sau thử lại
            logger.warning({"event": "chi_tieu_canh_bao_loi", "so_id": so_id, "kenh": kenh, "error": str(exc)[:160]})
    return n


def _moc_cao_nhat(so_id: int, thang: str, khoa: str, ty_le: float, nguong: list[float],
                  soan: Callable[[float], str], gui: Callable[[int, str], int]) -> dict[str, Any] | None:
    for m in sorted(nguong, reverse=True):
        if ty_le < m:
            continue
        if kho.da_gui(so_id, thang, khoa, m):
            return None
        if gui(so_id, soan(m)) > 0:
            kho.danh_dau_da_gui(so_id, thang, khoa, m)
            return {"khoa": khoa, "nguong": m}
        return None
    return None


def kiem_so(so_id: int, gui: Callable[[int, str], int] = _gui) -> list[dict[str, Any]]:
    s = kho.so(so_id)
    if s is None or not any(co_the_nhan_tin(x["kenh_user"]) for x in kho.kenh_cua_so(so_id)):
        return []
    n = ns.tinh(so_id)
    thang, nguong = n["thang"], list(s["nguong"] or [0.65, 0.8, 1.0])
    ra = []
    for h in n["hu"]:
        hm, chi = h["han_muc_truoc_bu"], h["da_chi"]
        if hm <= 0 and chi == 0:
            continue
        x = _moc_cao_nhat(so_id, thang, f"hu:{h['id']}", chi / hm if hm > 0 else 1.0, nguong,
                          lambda m, h=h: (f"🔴 Vượt hạn mức hũ «{h['ten']}»: đã chi {h['da_chi']:,} / "
                                          f"{h['han_muc_truoc_bu']:,} đ kỳ này."
                                          + (f" Đã tự bù {h['duoc_bu']:,} đ từ hũ khác." if h["duoc_bu"] else "")
                                          if m >= 1.0 else
                                          f"🟡 Hũ «{h['ten']}» đã dùng {m * 100:.0f}% hạn mức "
                                          f"({h['da_chi']:,} / {h['han_muc_truoc_bu']:,} đ)."), gui)
        if x:
            ra.append(x)
    hom_nay = datetime.now().date()
    ngay_bd = ns.ngay_bat_dau(s)
    so_ngay = ns.so_ngay_con_lai(hom_nay, ngay_bd)
    ky_sau = ns.ngay_bat_dau_ky_sau(hom_nay, ngay_bd).strftime("%d/%m")
    con = n["tong_con_lai"]

    def soan_tong(m: float) -> str:
        if con < 0:
            return f"🚨 ĐÃ CHI VƯỢT TỔNG NGÂN SÁCH KỲ {-con:,} đ! Đừng chi thêm tới kỳ lương {ky_sau}."
        if m >= 1.0:
            return f"🔴 Đã dùng hết tổng ngân sách kỳ. Đừng chi thêm tới kỳ lương {ky_sau}."
        return (f"🟡 Đã dùng {n['ty_le_tong_da_dung'] * 100:.0f}% tổng ngân sách kỳ ({n['tong_da_chi']:,} / "
                f"{n['tong_ngan_sach']:,} đ). Còn {con:,} đ cho {so_ngay} ngày tới {ky_sau} "
                f"(~{con // so_ngay:,} đ/ngày).")

    x = _moc_cao_nhat(so_id, thang, MA_TONG_VUOT if con < 0 else MA_TONG, n["ty_le_tong_da_dung"], nguong,
                      soan_tong, gui)
    if x:
        ra.append(x)
    return ra


def kiem_tat_ca() -> None:
    for s in kho.moi_so():
        if not s["lien_ket"]:
            continue
        try:
            da = kiem_so(int(s["id"]))
            if da:
                logger.info({"event": "chi_tieu_canh_bao", "so_id": s["id"], "moc": da})
        except Exception as exc:  # noqa: BLE001 — một sổ hỏng không chặn sổ khác
            logger.warning({"event": "chi_tieu_kiem_loi", "so_id": s["id"], "error": str(exc)[:160]})


def _vong() -> None:
    time.sleep(120)
    while True:
        kiem_tat_ca()
        time.sleep(CHU_KY_GIAY)


def start() -> None:
    global _da_chay
    if _da_chay:
        return
    _da_chay = True
    threading.Thread(target=_vong, name="chi-tieu-canh-bao", daemon=True).start()
