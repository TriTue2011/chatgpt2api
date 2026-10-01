"""Kiểm tra ngưỡng vượt hũ theo chu kỳ, đẩy cảnh báo chủ động ra Zalo qua C2A.

Mỗi ngưỡng (65/80/100%) chỉ gửi 1 lần / hũ / tháng — chống spam (xem
storage.da_gui_canh_bao). Ngoài từng hũ, còn cảnh báo theo TỔNG ngân sách
tháng (sau khi các hũ tự bù cho nhau), chống gửi trùng bằng khoá MA_TONG
(khi tổng đã ÂM dùng khoá riêng MA_TONG_VUOT, để "đã dùng hết 100%" và
"vượt tổng" mỗi loại đều được gửi đúng 1 lần/tháng, không bị mức 1.0 đã gửi
của loại kia nuốt mất) trong cùng bảng. Lỗi gọi C2A (server down, key
sai...) chỉ log, không crash scheduler — vòng kiểm tra kế tiếp thử lại
bình thường.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from app import storage
from app.c2a_client import gui_canh_bao
from app.jars import (
    ngay_bat_dau_chu_ky, ngay_bat_dau_ky_sau, nguong_canh_bao, so_ngay_con_lai_trong_ky,
    thang_hien_tai, tinh_ngan_sach_thang,
)

logger = logging.getLogger("chi-tieu-bot.alerts")

# Khoá "hu_ma" giả cho cảnh báo TỔNG trong bảng canh_bao_da_gui -- mã hũ thật
# không bao giờ bắt đầu bằng "__" nên không đụng nhau.
MA_TONG = "__tong__"
# Khoá dedup RIÊNG cho lúc tổng đã ÂM (vượt) -- tách khỏi MA_TONG để "đã dùng
# hết đúng 100%" (🔴) và "vượt tổng" (🚨) mỗi loại đều được gửi 1 lần/tháng:
# dùng chung 1 khoá thì chạm mốc 100% trước sẽ đánh dấu mức 1.0 đã gửi, làm
# 🚨 sau đó không bao giờ được gửi (review M1).
MA_TONG_VUOT = "__tong_vuot__"


async def kiem_tra_va_canh_bao() -> list[dict]:
    thang = thang_hien_tai()
    ngan_sach = tinh_ngan_sach_thang(thang)
    da_gui: list[dict] = []

    for hu in ngan_sach["hu"]:
        # Ngưỡng từng hũ tính trên hạn mức RIÊNG (trước tự bù) -- hũ chỉ bị
        # rút tiền bù cho hũ khác không bị báo "vượt".
        han_muc = hu["han_muc_truoc_bu"]
        da_chi = hu["da_chi"]
        if han_muc <= 0 and da_chi == 0:
            continue
        ty_le = da_chi / han_muc if han_muc > 0 else 1.0
        await _gui_nguong_cao_nhat(
            thang, hu["ma"], ty_le,
            lambda nguong, hu=hu: _soan_tin_canh_bao(
                hu["ten"], nguong, hu["da_chi"], hu["han_muc_truoc_bu"], hu["duoc_bu"]),
            {"da_chi": da_chi, "han_muc": han_muc},
            da_gui,
        )

    hom_nay = datetime.now().date()
    ngay_bd = ngay_bat_dau_chu_ky()
    so_ngay = so_ngay_con_lai_trong_ky(hom_nay, ngay_bd)
    ky_sau = ngay_bat_dau_ky_sau(hom_nay, ngay_bd).strftime("%d/%m")
    # Tổng đã âm (vượt) dùng khoá riêng MA_TONG_VUOT -- xem comment ở khai
    # báo hằng số phía trên. ty_le_tong_da_dung luôn >= 1.0 khi đã âm nên
    # ngưỡng chọn được luôn là 1.0, dòng dedup là (thang, "__tong_vuot__", 1.0).
    khoa_tong = MA_TONG_VUOT if ngan_sach["tong_con_lai"] < 0 else MA_TONG
    await _gui_nguong_cao_nhat(
        thang, khoa_tong, ngan_sach["ty_le_tong_da_dung"],
        lambda nguong: _soan_tin_canh_bao_tong(nguong, ngan_sach, so_ngay, ky_sau),
        {"da_chi": ngan_sach["tong_da_chi"], "han_muc": ngan_sach["tong_ngan_sach"]},
        da_gui,
    )

    return da_gui


async def _gui_nguong_cao_nhat(thang: str, khoa: str, ty_le: float,
                               soan_tin: Callable[[float], str], so_lieu: dict,
                               da_gui: list[dict]) -> None:
    # Duyệt ngưỡng từ cao xuống thấp, gửi ĐÚNG 1 cảnh báo cao nhất đã đạt
    # trong lượt kiểm tra này — tránh gửi dồn "65% rồi 80% rồi 100%" cùng lúc
    # khi bot mới khởi động lại sau một thời gian dài không kiểm tra.
    for nguong in sorted(nguong_canh_bao(), reverse=True):
        if ty_le < nguong:
            continue
        if storage.da_gui_canh_bao(thang, khoa, nguong):
            break  # ngưỡng cao nhất đạt được đã gửi rồi, khỏi kiểm ngưỡng thấp hơn
        try:
            await gui_canh_bao(soan_tin(nguong))
            storage.danh_dau_da_gui_canh_bao(thang, khoa, nguong)
            da_gui.append({"hu": khoa, "nguong": nguong, **so_lieu})
        except Exception as exc:
            logger.warning("Gửi cảnh báo %s (ngưỡng %.0f%%) thất bại: %s",
                           khoa, nguong * 100, exc)
        break


def _soan_tin_canh_bao(ten_hu: str, nguong: float, da_chi: int, han_muc: int,
                       duoc_bu: int = 0) -> str:
    if nguong >= 1.0:
        tin = (f"🔴 Vượt hạn mức hũ \"{ten_hu}\": đã chi {da_chi:,} / "
               f"{han_muc:,} VNĐ tháng này.")
        if duoc_bu > 0:
            tin += f" Đã tự bù {duoc_bu:,} VNĐ từ các hũ khác."
        return tin
    return (f"🟡 Cảnh báo hũ \"{ten_hu}\": đã dùng {nguong*100:.0f}% hạn mức "
            f"({da_chi:,} / {han_muc:,} VNĐ).")


def _soan_tin_canh_bao_tong(nguong: float, ngan_sach: dict, so_ngay: int, ky_sau: str) -> str:
    con_lai = ngan_sach["tong_con_lai"]
    if con_lai < 0:
        return (f"🚨 ĐÃ CHI VƯỢT TỔNG NGÂN SÁCH THÁNG {-con_lai:,} VNĐ! "
                f"Tuyệt đối không chi thêm cho tới kỳ lương {ky_sau}.")
    if nguong >= 1.0:
        return (f"🔴 Đã dùng hết 100% tổng ngân sách tháng. "
                f"Tuyệt đối không chi thêm cho tới kỳ lương {ky_sau}.")
    return (f"🟡 Đã dùng {ngan_sach['ty_le_tong_da_dung'] * 100:.0f}% tổng ngân sách tháng "
            f"({ngan_sach['tong_da_chi']:,} / {ngan_sach['tong_ngan_sach']:,} VNĐ). "
            f"Còn {con_lai:,} VNĐ cho {so_ngay} ngày tới kỳ lương {ky_sau} "
            f"(~{con_lai // so_ngay:,} VNĐ/ngày).")
