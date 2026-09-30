"""Bộ đề LUYỆN cho `sinh_kich_ban_van_phong.md` (ghép sau phần chung `sinh_kich_ban.md`) — văn phòng / cơ quan."""

from __future__ import annotations

from typing import Any

from services.de_luyen._kich_ban import _TAT_RADAR, TAT_CA, _uv, cham_cho, de_cho, giai_de  # noqa: F401

TANG = "services.kich_ban_nha"

_VP = ("văn phòng, 1 tầng\n• Khu làm việc — thông Sảnh\n• Phòng họp — có vách với Khu làm việc (cửa kính)\n"
       "• Sảnh — có vách với Hành lang tòa nhà\n• Cửa chính mở vào Sảnh")

DE: list[dict[str, Any]] = [d for d in TAT_CA if d["uv"]["noi"] == "van_phong"] + [
    {"ten": "phong_hop_trong_dieu_hoa_van_chay",
     "tinh_huong": "Họp xong mọi người ra hết, điều hoà phòng họp chỉ tắt theo radar vắng 30 phút — chạy phí; radar "
                   "phòng họp xuyên cửa kính bắt người ở khu làm việc nên không bao giờ «vắng».",
     "uv": _uv(_VP, {"Phòng họp": ["Radar phòng họp (sóng/chuyển động)", "Cửa phòng họp (cửa)"],
                     "Khu làm việc": ["Radar khu làm việc (sóng/chuyển động)"]},
               {"climate.dieu_hoa_hop": ("Điều hoà phòng họp", "Phòng họp", [
                   "BẬT: chưa tự bật (luật học chưa đủ tin)",
                   _TAT_RADAR.format(cb="Radar phòng họp", p=30)])},
               ["Giờ làm việc 8:00–17:30 thứ 2–thứ 6."]),
     "dap_an": {"phai_co": [{"thiet_bi": "climate.dieu_hoa_hop", "loai": ["phong_hop", "lay_ben_canh", "de_quen"],
                             "hien_tai": ["sai", "khong_ro"],
                             "tu": ["họp xong", "trống", "không còn ai", "kính", "xuyên", "lây"]}]}},

    {"ten": "mot_den_khu_lam_viec_du_danh_muc",
     "tinh_huong": "Chỉ đèn khu làm việc: ngồi máy tính yên lâu, nghỉ trưa, ngoài giờ, lao công buổi tối — đủ danh mục.",
     "uv": _uv(_VP, {"Khu làm việc": ["Radar khu làm việc (sóng/chuyển động)", "Camera văn phòng Person (camera)"],
                     "Sảnh": ["Cửa kính sảnh (cửa)"]},
               {"light.den_lam_viec_1": ("Đèn khu làm việc", "Khu làm việc", [
                   "BẬT (bot học, tự làm): khi Radar khu làm việc có người vào",
                   _TAT_RADAR.format(cb="Radar khu làm việc", p=10)])},
               ["Giờ làm việc 8:00–17:30 thứ 2–thứ 6; nghỉ trưa 12:00–13:00, nhân viên ngủ trưa tại bàn."]),
     "dap_an": {"phu_du": True,
                "phai_co": [{"thiet_bi": "light.den_lam_viec_1", "loai": ["lich_lam", "o_lai"],
                             "tu": ["nghỉ trưa", "ngủ trưa", "trưa"]}]}},
]
