"""Bộ đề LUYỆN cho `sinh_kich_ban_nha_pho.md` (ghép sau phần chung `sinh_kich_ban.md`) — nhà phố nhiều tầng."""

from __future__ import annotations

from typing import Any

from services.de_luyen._kich_ban import _TAT_RADAR, TAT_CA, _uv, cham_cho, de_cho, giai_de  # noqa: F401

TANG = "services.kich_ban_nha"

_NHA_PHO = ("nhà phố, 4 tầng\n• Garage (tầng 1) — thông Phòng khách (tầng 1)\n• Phòng khách — thông Bếp (tầng 1), "
            "Cầu thang\n• Cầu thang — thông các tầng\n• Phòng ngủ tầng 2, Phòng ngủ tầng 3 — có vách với Cầu thang\n"
            "• Sân thượng (tầng 4) — có vách với Phòng thờ\n• Cửa cuốn mở ra đường")

DE: list[dict[str, Any]] = [d for d in TAT_CA if d["uv"]["noi"] == "nha_pho"] + [
    {"ten": "mot_den_cau_thang_du_danh_muc",
     "tinh_huong": "Chỉ đèn cầu thang, cảm biến ở chân cầu thang tầng 1 và đầu cầu thang tầng 3: đi từ tầng 2 (không "
                   "có cảm biến) — đủ danh mục; bẫy tầng 2 tối.",
     "uv": _uv(_NHA_PHO,
               {"Cầu thang": ["Radar chân cầu thang tầng 1 (sóng/chuyển động)",
                              "Radar đầu cầu thang tầng 3 (sóng/chuyển động)"]},
               {"light.den_cau_thang_1": ("Đèn cầu thang", "Cầu thang", [
                   "BẬT (bot học, tự làm): khi Radar chân cầu thang tầng 1 hoặc Radar đầu cầu thang tầng 3 có người vào, "
                   "từ 18:00",
                   _TAT_RADAR.format(cb="Radar chân cầu thang tầng 1 hoặc Radar đầu cầu thang tầng 3", p=2)])},
               ["Ông bà ở phòng ngủ tầng 2."]),
     "dap_an": {"phu_du": True,
                "phai_co": [{"thiet_bi": "light.den_cau_thang_1", "loai": ["cau_thang", "di_ngang", "tang"],
                             "hien_tai": "sai", "tu": ["tầng 2"]},
                            {"thiet_bi": "light.den_cau_thang_1", "nen": "bao", "tu": ["ông", "bà", "già", "ngã"]}]}},

    {"ten": "san_thuong_phoi_do_troi_mua",
     "tinh_huong": "Sân thượng phơi đồ: trời đổ mưa lúc cả nhà ở tầng dưới / đi vắng — phải BÁO rút đồ; cửa sân thượng "
                   "mở ban đêm.",
     "uv": _uv(_NHA_PHO,
               {"Sân thượng": ["Radar sân thượng (sóng/chuyển động)", "Cửa sân thượng (cửa)",
                               "Cảm biến mưa (sóng/chuyển động)"]},
               {"light.den_san_thuong": ("Đèn sân thượng", "Sân thượng", [
                   "BẬT (bot học, tự làm): khi Radar sân thượng có người vào, Độ sáng ≤ 10",
                   _TAT_RADAR.format(cb="Radar sân thượng", p=3)])},
               ["Nhà phơi quần áo trên sân thượng."]),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_san_thuong", "nen": "bao", "tu": ["mưa"]},
                            {"thiet_bi": "light.den_san_thuong", "nen": "bao",
                             "tu": ["cửa sân thượng", "cửa mở", "ban đêm", "đêm"]}]}},
]

# Chủ máy 30/09/2026: người ngoài cửa — "toàn diện, đừng chỉ có cho duy nhất nhà tôi": nhà phố mặt đường có
# LOA TRÊN CAMERA cổng — khách đứng lâu thì chào qua loa camera; người đi đường lướt qua thì im.
DE += [
    {"ten": "khach_dung_truoc_cua_cuon_chao_qua_loa_camera",
     "tinh_huong": "Camera trước cửa cuốn có loa: người đi đường lướt qua vỉa hè liên tục; khách đứng sát cửa > 20 giây "
                   "thì chào qua loa camera và báo người trong nhà; không bật đèn cho người lướt qua.",
     "uv": _uv(_NHA_PHO,
               {"Vỉa hè (ngoài nhà)": ["Camera cửa cuốn Person (camera)"],
                "Phòng khách": ["Radar phòng khách (sóng/chuyển động)", "Cửa cuốn (cửa)"]},
               {"light.den_hien_nha": ("Đèn hiên", "Phòng khách", [
                   "BẬT (bot học, tự làm): khi Camera cửa cuốn Person có người vào, Độ sáng ≤ 10",
                   _TAT_RADAR.format(cb="Camera cửa cuốn Person", p=2)])},
               ["Nhà mặt đường, camera trước cửa cuốn nhìn cả vỉa hè; cửa nhà ở giữa khung hình."],
               loa=["Loa camera cửa cuốn (ở Vỉa hè — loa TRÊN CAMERA)", "Loa phòng khách (ở Phòng khách)"],
               kha_nang=["Frigate: HỘP (toạ độ) từng người trên khung hình mỗi camera, theo dõi một người qua các khung "
                         "(đứng yên bao lâu, đi về phía nào), đếm người từng camera."]),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_hien_nha", "hien_tai": ["sai", "khong_ro"],
                             "tu": ["lướt qua", "đi đường", "đi qua", "vỉa hè"]},
                            {"thiet_bi": "light.den_hien_nha", "nen": ["noi", "bao"],
                             "tu": ["đứng", "khách", "lâu", "chào"]}]}},
]
