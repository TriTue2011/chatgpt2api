"""Bộ đề LUYỆN cho `sinh_kich_ban_chung_cu.md` (ghép sau phần chung `sinh_kich_ban.md`) — căn hộ chung cư.

Nặng nhất: chủ máy 30/09/2026 "kỹ nhất vẫn cho nhà thông minh … ví dụ chung cư". Đề chung ở `_kich_ban.TAT_CA`
(nơi = chung cư) + đề CHỈ MỘT THIẾT BỊ bắt phủ đủ danh mục ("tránh … thiếu tình huống với chỉ 1 thiết bị").
"""

from __future__ import annotations

from typing import Any

from services.de_luyen._kich_ban import _TAT_RADAR, TAT_CA, _uv, cham_cho, de_cho, giai_de  # noqa: F401

TANG = "services.kich_ban_nha"

_CAN_HO = ("chung cư, 1 tầng\n• Phòng khách — thông Bếp — có vách với Phòng ngủ\n• Bếp — thông Phòng khách — "
           "có vách với Ban công\n• Ban công — có vách với Bếp\n• Phòng ngủ — có vách với Phòng khách, WC\n"
           "• WC — có vách với Phòng ngủ\n• Cửa chính mở vào Phòng khách")
_CB_CAN_HO = {"Phòng khách": ["Radar phòng khách (sóng/chuyển động)", "Camera phòng khách Person (camera)",
                              "Cảm biến cửa chính (cửa)"],
              "Bếp": ["Radar bếp (sóng/chuyển động)"], "Ban công": ["Radar ban công (sóng/chuyển động)"],
              "Phòng ngủ": ["Radar phòng ngủ (sóng/chuyển động)"], "WC": ["Radar WC (sóng/chuyển động)",
                                                                        "Cửa WC (cửa)"]}
_NGUOI = ["Chồng (home)", "Vợ (home)", "Điện thoại chồng (home)", "Điện thoại vợ (home)"]

DE: list[dict[str, Any]] = [d for d in TAT_CA if d["uv"]["noi"] == "chung_cu"] + [
    {"ten": "mot_den_tran_pk_du_danh_muc",
     "tinh_huong": "Căn hộ chỉ có MỘT thiết bị — đèn trần phòng khách; radar phòng khách đặt dưới tivi nhìn thẳng ra "
                   "bếp. Phải đi đủ danh mục; bẫy: người nấu ăn ở bếp giữ đèn phòng khách; cửa chính vào/ra.",
     "uv": _uv(_CAN_HO, _CB_CAN_HO,
               {"light.den_tran_pk_1": ("Đèn trần phòng khách", "Phòng khách", [
                   "BẬT (bot học, tự làm): khi Radar phòng khách có người vào, từ 17:30",
                   _TAT_RADAR.format(cb="Radar phòng khách", p=3)])},
               ["Radar phòng khách đặt dưới tivi, nhìn thẳng ra bếp."], nguoi=_NGUOI),
     "dap_an": {"phu_du": True,
                "phai_co": [{"thiet_bi": "light.den_tran_pk_1", "loai": ["lay_ben_canh", "bep_mo"],
                             "hien_tai": ["sai", "khong_ro"], "tu": ["bếp", "nấu"]},
                            {"thiet_bi": "light.den_tran_pk_1", "loai": ["cua_chinh", "an_ninh"],
                             "tu": ["cửa chính", "cửa"]}]}},

    {"ten": "mot_den_ban_cong_du_danh_muc",
     "tinh_huong": "Chỉ đèn ban công (logia phơi đồ, máy giặt): gió làm quần áo lay, radar báo giả; phơi đồ tối.",
     "uv": _uv(_CAN_HO, _CB_CAN_HO,
               {"light.den_ban_cong_1": ("Đèn ban công", "Ban công", [
                   "BẬT (bot học, tự làm): khi Radar ban công có người vào, Độ sáng ban công ≤ 15",
                   _TAT_RADAR.format(cb="Radar ban công", p=3)])},
               ["Ban công sau bếp để phơi đồ và đặt máy giặt."], nguoi=_NGUOI),
     "dap_an": {"phu_du": True,
                "phai_co": [{"thiet_bi": "light.den_ban_cong_1", "loai": ["ban_cong", "nhieu_cam_bien"],
                             "hien_tai": ["sai", "khong_ro"], "tu": ["gió", "quần áo", "phơi", "rèm", "nhiễu"]}]}},

    {"ten": "mot_quat_phong_ngu_du_danh_muc",
     "tinh_huong": "Chỉ quạt phòng ngủ: người ngủ yên radar mất dấu (tắt quạt giữa đêm), đi WC đêm rồi quay lại.",
     "uv": _uv(_CAN_HO, _CB_CAN_HO,
               {"fan.quat_ngu_1": ("Quạt phòng ngủ", "Phòng ngủ", [
                   "BẬT: có người ở lại ≥ 3 phút (hợp các cảm biến Radar phòng ngủ) thì HỎI anh để học",
                   _TAT_RADAR.format(cb="Radar phòng ngủ", p=3)])}, nguoi=_NGUOI),
     "dap_an": {"phu_du": True,
                "phai_co": [{"thiet_bi": "fan.quat_ngu_1", "loai": ["o_lai", "dem"], "hien_tai": ["sai", "khong_ro"],
                             "tu": ["ngủ", "nằm", "mất dấu"]},
                            {"thiet_bi": "fan.quat_ngu_1", "loai": ["roi_quay_lai", "wc_trong_can"],
                             "tu": ["vệ sinh", "wc", "WC", "nhà tắm"]}]}},
]
