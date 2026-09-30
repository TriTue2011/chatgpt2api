"""Bộ đề LUYỆN cho `sinh_kich_ban_xuong.md` (ghép sau phần chung `sinh_kich_ban.md`) — xưởng / khu công nghiệp."""

from __future__ import annotations

from typing import Any

from services.de_luyen._kich_ban import _TAT_RADAR, TAT_CA, _uv, cham_cho, de_cho, giai_de  # noqa: F401

TANG = "services.kich_ban_nha"

_XUONG = ("xưởng, 1 tầng\n• Kho — thông Lối đi\n• Lối đi — thông Vùng máy\n• Vùng máy — thông Lối đi\n"
          "• Cửa kho mở ra bãi xe")

DE: list[dict[str, Any]] = [d for d in TAT_CA if d["uv"]["noi"] == "xuong"] + [
    {"ten": "xe_tu_hanh_kich_cam_bien_kho",
     "tinh_huong": "Kho có xe tự hành (AGV) chạy cả đêm: cảm biến chuyển động bật đèn kho suốt đêm, và báo «có người» "
                   "ngoài ca là báo giả — phải phân biệt bằng camera.",
     "uv": _uv(_XUONG, {"Kho": ["Chuyển động kho (sóng/chuyển động)", "Camera kho Person (camera)", "Cửa kho (cửa)"]},
               {"light.den_kho": ("Đèn kho", "Kho", [
                   "BẬT (bot học, tự làm): khi Chuyển động kho có người vào",
                   _TAT_RADAR.format(cb="Chuyển động kho", p=5)])},
               ["Xưởng làm 2 ca 6:00–22:00; kho có xe tự hành AGV chạy 24/24."]),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_kho", "hien_tai": ["sai", "khong_ro"],
                             "tu": ["AGV", "xe tự hành", "tự hành", "xe"]}]}},

    {"ten": "mot_den_vung_may_du_danh_muc",
     "tinh_huong": "Chỉ đèn cảnh báo vùng máy: người vào vùng khi máy chạy, giao ca, ngoài ca — đủ danh mục.",
     "uv": _uv(_XUONG, {"Vùng máy": ["Camera vùng máy Person (camera)", "Máy dập đang chạy (sóng/chuyển động)"]},
               {"switch.den_bao_vung_may": ("Đèn cảnh báo vùng máy", "Vùng máy", [
                   "BẬT: chưa tự bật (luật học chưa đủ tin)", "TẮT: không tự tắt"])},
               ["Xưởng làm 2 ca 6:00–22:00."]),
     "dap_an": {"phu_du": True,
                "phai_co": [{"thiet_bi": "switch.den_bao_vung_may", "loai": ["vung_nguy_hiem"], "hien_tai": "sai",
                             "tu": ["máy", "vùng"]}]}},
]
