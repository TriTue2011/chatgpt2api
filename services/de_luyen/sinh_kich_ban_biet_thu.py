"""Bộ đề LUYỆN cho `sinh_kich_ban_biet_thu.md` (ghép sau phần chung `sinh_kich_ban.md`) — nhà vườn / biệt thự."""

from __future__ import annotations

from typing import Any

from services.de_luyen._kich_ban import _TAT_RADAR, TAT_CA, _uv, cham_cho, de_cho, giai_de  # noqa: F401

TANG = "services.kich_ban_nha"

_VUON = ("nhà vườn, 2 tầng\n• Sân — thông Cổng, có vách với Phòng khách\n• Hồ bơi — thông Sân\n"
         "• Cổng mở ra đường, cửa chính mở vào Phòng khách")

DE: list[dict[str, Any]] = [d for d in TAT_CA if d["uv"]["noi"] == "biet_thu"] + [
    {"ten": "mot_den_san_du_danh_muc",
     "tinh_huong": "Chỉ đèn sân (cảm biến chuyển động ngoài trời + camera sân): cây lay, chó chạy báo giả; người đi từ "
                   "cổng vào cửa chính.",
     "uv": _uv(_VUON, {"Sân": ["Chuyển động sân (sóng/chuyển động)", "Camera sân Person (camera)"]},
               {"light.den_san": ("Đèn sân", "Sân", [
                   "BẬT (bot học, tự làm): khi Chuyển động sân có người vào, Độ sáng sân ≤ 10",
                   _TAT_RADAR.format(cb="Chuyển động sân", p=2)])},
               ["Nhà nuôi một con chó thả trong sân ban đêm."]),
     "dap_an": {"phu_du": True,
                "phai_co": [{"thiet_bi": "light.den_san", "loai": ["san_vuon", "thu_cung", "nhieu_cam_bien"],
                             "hien_tai": ["sai", "khong_ro"], "tu": ["chó", "cây", "lá", "gió", "báo giả", "nhiễu"]}]}},

    {"ten": "ho_boi_tre_nho_mot_minh",
     "tinh_huong": "Nhà có hai bé 4 và 6 tuổi: bé ra hồ bơi một mình — BÁO NGAY, không chỉ bật đèn hồ.",
     "uv": _uv(_VUON, {"Hồ bơi": ["Camera hồ bơi Person (camera)"], "Sân": ["Chuyển động sân (sóng/chuyển động)"]},
               {"light.den_ho_boi": ("Đèn hồ bơi", "Hồ bơi", [
                   "BẬT (bot học, tự làm): khi Camera hồ bơi Person có người vào, Độ sáng ≤ 10",
                   _TAT_RADAR.format(cb="Camera hồ bơi Person", p=5)])},
               ["Nhà có hai bé 4 và 6 tuổi."]),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_ho_boi", "nen": "bao", "loai": ["ho_nuoc", "nguoi_yeu"],
                             "tu": ["bé", "trẻ", "con"]}]}},
]
