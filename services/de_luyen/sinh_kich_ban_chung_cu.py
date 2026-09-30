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


# ── Chủ máy 30/09/2026 tối: "chưa đầy đủ các tình huống" — thiết bị ở cửa và việc của nó; người ngoài cửa
# (lướt qua / đứng trước cửa / vào nhà / người nhà nói chuyện hàng xóm) qua toạ độ camera + thời gian đứng +
# nhận mặt, rồi nói qua loa / chào qua loa camera; cảm biến cửa kẹt; lịch TỪNG NGƯỜI theo tuổi (về muộn bật đèn
# bếp thay đèn trần); radar có KHOẢNG CÁCH; khu không có cảm biến (nhà tắm) suy LOẠI TRỪ bằng đếm người, trừ người
# hai camera cùng thấy. "Toàn diện, đừng chỉ có cho duy nhất nhà tôi" — đề là căn hộ giả lập, không phải nhà chủ máy.
_CB_CUA = {**_CB_CAN_HO, "Hành lang (ngoài căn)": ["Camera cửa Person (camera)"]}
_KHA_NANG = ["NHẬN MẶT người quen trên Camera cửa (đã dạy mặt: Bố, Mẹ, Bé Na); mặt cúi / quay đi / ngược sáng thì "
             "không nhận được — không nhận ra ≠ người lạ.",
             "Frigate: HỘP (toạ độ) từng người trên khung hình mỗi camera, theo dõi một người qua các khung (đứng yên "
             "bao lâu, đi về phía nào), đếm người từng camera. Hai camera cùng thấy một vùng thì một người có thể bị "
             "đếm HAI lần — dùng ô chung trong sơ đồ để trừ.",
             "Chụp NGAY một camera và đếm người bằng YOLO."]
_LOA = ["Loa phòng khách (ở Phòng khách)"]
_LICH_3 = ["- Bố (38 tuổi, Người lớn (18–59)) — theo dõi qua device_tracker.dien_thoai_bo",
           "- Mẹ (35 tuổi, Người lớn (18–59)) — theo dõi qua device_tracker.dien_thoai_me",
           "- Bé Na (4 tuổi, Trẻ nhỏ (dưới 6 tuổi))",
           "- Lịch Bé Na: Ngủ tối (ngu) 20:30–06:30 mọi ngày",
           "- Lịch Mẹ: Ngủ (ngu) 22:30–06:00 mọi ngày",
           "- Lịch Bố: Đi làm (vang) 07:30–22:30 T2,T3,T4,T5,T6",
           "- Lịch Bố: Ngủ (ngu) 23:30–06:00 mọi ngày"]
_DEN_TRAN_CUA = ("Đèn trần phòng khách", "Phòng khách", [
    "BẬT (bot học, tự làm): khi Cảm biến cửa chính mở (chỉ khi trong 60 giây khu của thiết bị có người MỚI vào), "
    "từ 17:30",
    _TAT_RADAR.format(cb="Radar phòng khách", p=3)])

DE += [
    {"ten": "ngoai_cua_khach_dung_lau_va_nguoi_luot_qua",
     "tinh_huong": "Camera cửa nhìn ra hành lang chung: hàng xóm lướt qua nhiều lần mỗi ngày; shipper/khách ĐỨNG trước "
                   "cửa lâu mà không bấm chuông — phải phân biệt bằng toạ độ gần cửa + thời gian đứng, khách đứng lâu thì "
                   "NÓI qua loa trong nhà; không bật đèn vì người lướt qua.",
     "uv": _uv(_CAN_HO, _CB_CUA, {"light.den_tran_pk_c": _DEN_TRAN_CUA},
               ["Camera cửa nhìn ra hành lang chung, cửa nhà mình ở mép phải khung hình; nhà đối diện ở mép trái."],
               nguoi=_NGUOI, loa=_LOA, kha_nang=_KHA_NANG),
     # `nen` là việc của CHÍNH thiết bị đang xét (đèn trần): khách đứng ngoài thì đèn `khong_lam` là ĐÚNG — báo qua
     # loa là việc của loa (đề nhà phố có loa camera kiểm `noi`). Bản đầu đòi đèn `noi`/`bao` là đáp án sai.
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_tran_pk_c", "loai": ["ngoai_cua", "cua_chinh"],
                             "nen": ["noi", "bao", "khong_lam"], "tu": ["đứng", "khách", "shipper", "lâu"]}],
                # Chỉ chữ «lướt qua»: tình huống người MỞ CỬA VÀO cũng nhắc «hành lang», bật đèn khi đó là đúng.
                "khong_nen_tu": [{"thiet_bi": "light.den_tran_pk_c", "nen": "bat", "tu": ["lướt qua"]}]}},

    {"ten": "nguoi_nha_dung_noi_chuyen_hang_xom",
     "tinh_huong": "Mẹ đứng trước cửa nói chuyện với hàng xóm 15 phút: camera cửa thấy người đứng lâu sát cửa — nhận mặt "
                   "(khi quay vào) là người nhà thì KHÔNG báo khách, không nói qua loa; mặt quay đi không nhận được ≠ lạ.",
     "uv": _uv(_CAN_HO, _CB_CUA, {"light.den_tran_pk_d": _DEN_TRAN_CUA},
               ["Camera cửa nhìn ra hành lang chung, cửa nhà mình ở mép phải khung hình."],
               nguoi=_NGUOI, loa=_LOA, kha_nang=_KHA_NANG),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_tran_pk_d", "loai": ["ngoai_cua", "cua_chinh"],
                             "nen": ["khong_lam", "giu"],
                             "tu": ["người nhà", "nhận mặt", "nhận ra", "nói chuyện", "hàng xóm"]}],
                "khong_nen_tu": [{"thiet_bi": "light.den_tran_pk_d", "nen": "noi",
                                  "tu": ["nói chuyện", "người nhà"]}]}},

    {"ten": "cam_bien_cua_ket_mo",
     "tinh_huong": "Cảm biến cửa chính kẹt «mở» từ sáng (không đổi trạng thái): đèn trần bật theo «cửa mở» thì không còn "
                   "nhận ra người về — phải dùng nguồn thứ hai (camera cửa / camera phòng khách thấy người gần cửa) và báo "
                   "chủ nhà xem lại cảm biến.",
     "uv": _uv(_CAN_HO, _CB_CUA, {"light.den_tran_pk_k": _DEN_TRAN_CUA},
               ["Cảm biến cửa chính báo «mở» liền từ 07:05 sáng nay, không đổi lần nào dù cả nhà đi rồi về."],
               nguoi=_NGUOI, loa=_LOA, kha_nang=_KHA_NANG),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_tran_pk_k", "loai": ["cam_bien_ket", "nhieu_cam_bien"],
                             "hien_tai": ["sai", "khong_ro"], "tu": ["kẹt", "không đổi", "đơ", "giữ"]},
                            {"thiet_bi": "light.den_tran_pk_k", "tu": ["camera"],
                             "loai": ["cam_bien_ket", "nhieu_cam_bien", "cua_chinh", "vao"]}]}},

    {"ten": "ve_muon_tre_da_ngu_bat_den_nho",
     "tinh_huong": "Bố đi làm về 23:00 (lịch từng người), Bé Na 4 tuổi và mẹ đã ngủ ở phòng ngủ cạnh phòng khách: bật đèn "
                   "trần theo cửa mở làm bé thức — nên bật đèn bếp / để tối, không bật đèn trần.",
     "uv": _uv(_CAN_HO, _CB_CUA,
               {"light.den_tran_pk_m": _DEN_TRAN_CUA,
                "light.den_bep_m": ("Đèn bếp", "Bếp", ["BẬT: không tự bật", _TAT_RADAR.format(cb="Radar bếp", p=3)])},
               nguoi=_NGUOI, loa=_LOA, kha_nang=_KHA_NANG, lich=_LICH_3),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_tran_pk_m", "loai": ["lich_tung_nguoi", "dem", "vao", "cua_chinh"],
                             "hien_tai": ["sai", "khong_ro"], "nen": ["khong_lam", "hoi", "giu"],
                             "tu": ["ngủ", "muộn", "bé", "23"]}],
                "khong_nen_tu": [{"thiet_bi": "light.den_tran_pk_m", "nen": "bat", "tu": ["23:00", "về muộn", "bé ngủ"]}]}},

    {"ten": "radar_khoang_cach_den_ban_lam_viec",
     "tinh_huong": "Đèn bàn làm việc góc phòng khách bật theo «radar phòng khách có người» — radar thấy cả người đi lại "
                   "phía bếp; radar có số KHOẢNG CÁCH: nên bật khi người vào gần bàn (ngưỡng mét do chủ nhà đặt / đo).",
     "uv": _uv(_CAN_HO, {**_CB_CAN_HO, "Phòng khách": _CB_CAN_HO["Phòng khách"] + [
                   "Radar phòng khách Khoảng cách (KHOẢNG CÁCH người tới radar, m)"]},
               {"light.den_ban_lv": ("Đèn bàn làm việc", "Phòng khách", [
                   "BẬT (bot học, tự làm): khi Radar phòng khách có người vào",
                   _TAT_RADAR.format(cb="Radar phòng khách", p=3)])},
               ["Radar phòng khách đặt trên bàn làm việc ở góc phòng, nhìn ra cả phòng khách và bếp."],
               nguoi=_NGUOI),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_ban_lv", "loai": ["khoang_cach", "lay_ben_canh", "di_ngang"],
                             "tu": ["khoảng cách", "mét", "gần bàn", "ngưỡng"]}],
                "phai_hoi_ve": [["xa nhất", "ngưỡng", "bao nhiêu mét", "khoảng cách", "mét"]]}},

    {"ten": "nha_tam_khong_cam_bien_loai_tru_dem_nguoi",
     "tinh_huong": "Nhà tắm KHÔNG có cảm biến, đèn nhà tắm bật tay, hay quên tắt: nhà 3 người — camera phòng khách thấy 2, "
                   "camera bếp thấy 2 trong đó 1 người đứng ở vùng hai camera cùng thấy → thật ra 3 người ở ngoài → nhà tắm "
                   "vắng → tắt; đếm thiếu người thì chưa chắc.",
     "uv": _uv(_CAN_HO, {**{k: v for k, v in _CB_CAN_HO.items() if k != "WC"},
                         "Bếp": ["Radar bếp (sóng/chuyển động)", "Camera bếp Person count (ĐẾM số vật thể camera thấy)"],
                         "Phòng khách": _CB_CAN_HO["Phòng khách"] + [
                             "Camera phòng khách Person count (ĐẾM số vật thể camera thấy)"]},
               {"light.den_wc_lt": ("Đèn WC", "WC", ["BẬT: người bật tay", "TẮT: không tự tắt"])},
               ["WC không có cảm biến nào. Camera phòng khách và camera bếp cùng thấy khu bàn ăn.",
                "Nhà hay quên tắt đèn WC."],
               nguoi=_NGUOI, kha_nang=_KHA_NANG, lich=_LICH_3[:3]),
     "dap_an": {"phai_co": [{"thiet_bi": "light.den_wc_lt", "loai": ["loai_tru", "de_quen"], "nen": ["tat", "hoi"],
                             "tu": ["đủ", "3 người", "đếm", "trùng", "hai lần", "trừ"]}]}},
]
