"""Bộ đề LUYỆN cho hướng dẫn `chon_co_nguoi.md` — tình huống thực tế ở MỌI kiểu nhà, không riêng
nhà nào.

Chủ máy 29/09/2026: "Tôi cần là train mọi tình huống trong thực tế chứ không phải bó hẹp trong nhà
tôi, để bot biết và hiểu cần làm gì". Mỗi đề dựng số đo giả lập theo ĐÚNG khuôn đề thật
(`co_nguoi_nha.de`) cho một hiện tượng hay gặp, kèm ĐÁP ÁN là những điều bài giải bắt buộc phải
có / không được có. Sửa hướng dẫn xong thì chạy `scripts/luyen_huong_dan.py chon_co_nguoi` — bot phải đúng ở mọi
kiểu nhà chứ không chỉ ở nhà đang chạy.

Mã thực thể là tên chung (``binary_sensor.radar_phong_khach``…), số đo lấy theo cỡ đã đo ở nhà thật
để bot gặp đúng độ nhiễu ngoài đời.
"""

from __future__ import annotations

from typing import Any

#: Tầng dựng đề và kiểm biên cho bộ này.
TANG = "services.co_nguoi_nha"


def _hd(ten: str, khu: str, doi: float, khi_bat: str = "—", rieng: str = "—") -> dict[str, Any]:
    return {"ten": ten, "khu": khu, "doi_ngay": doi, "khi_bat": khi_bat, "rieng": rieng}


def _nv(ma: str, ten: str, gia_tri: list[str], ngan: str, dai: str, doi: float = 1.0) -> dict[str, Any]:
    return {"ma": ma, "ten": ten, "gia_tri": gia_tri, "ngan": ngan, "dai": dai, "doi_ngay": doi, "lech": 0.0}


def _uv(ma: str, khu: str, hien_dien: dict[str, dict[str, Any]], *, cap: list | None = None,
        sang_khac: list | None = None, ngan: int = 300, dai: int = 40, ngoai_vi: list | None = None,
        camera: list[str] | None = None, frigate: list[str] | None = None, roi: list | None = None,
        roi_nen: dict | None = None, roi_da: dict | None = None, ket: list[str] | None = None) -> dict[str, Any]:
    return {"ma": ma, "khu": khu, "so_ngay": 30, "gio_bat": 150, "hien_dien": hien_dien,
            "trong": [m for m, x in hien_dien.items() if x["khu"] == khu and m not in (ket or [])],
            "ket": ket or [], "cap": cap or [], "sang_khac": sang_khac or [], "ngan": ngan, "dai": dai,
            "ngoai_vi": ngoai_vi or [], "camera": camera or [], "camera_frigate": frigate or [],
            "roi": roi or [], "roi_nen": roi_nen or {"n": 0, "nham": "—", "khung": ""}, "roi_da": roi_da or {}}


RPK, CPK, APK, MPK = ("binary_sensor.radar_phong_khach", "binary_sensor.camera_phong_khach_person",
                      "binary_sensor.camera_phong_khach_all", "binary_sensor.motion_phong_khach")
RB, CB = "binary_sensor.radar_bep", "binary_sensor.camera_bep_person"
RN, RT, RH = "binary_sensor.radar_phong_ngu", "binary_sensor.radar_nha_tam", "binary_sensor.radar_phong_hoc"
RBC = "binary_sensor.radar_ban_cong"
LAP, DT = "device_tracker.laptop_chi_lan", "device_tracker.dien_thoai_chi_lan"
TIVI, LOA = "media_player.tivi_phong_khach", "media_player.loa_nha_tam"


def _pk_can_ho() -> dict[str, dict[str, Any]]:
    return {RPK: _hd("Radar phòng khách", "Phòng khách", 350, "36%", "6%"),
            CPK: _hd("Camera phòng khách Person", "Phòng khách", 440, "62%", "26%"),
            RB: _hd("Radar bếp", "Bếp", 310), CB: _hd("Camera bếp Person", "Bếp", 690),
            RN: _hd("Radar phòng ngủ", "Phòng ngủ", 45)}


DE: list[dict[str, Any]] = [
    {"ten": "can_ho_bep_thong_phong_khach",
     "tinh_huong": "Căn hộ, bếp liền phòng khách: radar phòng khách bắt cả người ở bếp; người đi ra bếp "
                   "rồi quay lại liên tục — thấy người ở bếp KHÔNG có nghĩa đã rời phòng khách.",
     "ten_tb": "Đèn trần phòng khách", "dan": [],
     "uv": _uv("light.den_tran", "Phòng khách", _pk_can_ho(),
               cap=[{"r": RPK, "x": RB, "p": 0.55, "xac": {CPK: "35%"}}],
               sang_khac=[{"x": RB, "ngan": "60%", "dai": "50%"}],
               roi=[{"x": RB, "n": 1200, "nham": "93%", "khung": "sáng 94%/300 chiều 92%/300 tối 93%/600"},
                    {"x": CB, "n": 2400, "nham": "95%", "khung": "sáng 96%/600 chiều 95%/600 tối 94%/1200"}],
               roi_nen={"n": 1600, "nham": "78%", "khung": "sáng 88%/500 chiều 74%/400 tối 65%/700"},
               camera=["Cam phòng khách", "Cam bếp"], frigate=["Cam phòng khách", "Cam bếp"]),
     "dap_an": {"co_nguoi_phai_co": [CPK, RPK], "co_nguoi_phu_dinh": [RB], "roi_di": None}},

    {"ten": "nha_pho_phong_ngu_co_vach",
     "tinh_huong": "Nhà phố, phòng ngủ có tường kín: ra khỏi phòng là radar phòng khách thấy ngay, và "
                   "hiếm khi quay lại trong vài phút — tắt sớm được.",
     "ten_tb": "Đèn phòng ngủ", "dan": [],
     "uv": _uv("light.den_ngu", "Phòng ngủ",
               {RN: _hd("Radar phòng ngủ", "Phòng ngủ", 45, "80%", "80%"),
                RPK: _hd("Radar phòng khách", "Phòng khách", 300), RB: _hd("Radar bếp", "Bếp", 200)},
               ngan=80, dai=60,
               roi=[{"x": RPK, "n": 40, "nham": "8%", "khung": "sáng 10%/10 chiều 5%/10 tối 8%/20"},
                    {"x": RB, "n": 12, "nham": "33%", "khung": "tối 33%/12"}],
               roi_nen={"n": 50, "nham": "46%", "khung": "sáng 40%/10 tối 48%/40"},
               camera=["Cam cổng", "Cam phòng khách"]),
     "dap_an": {"co_nguoi_phai_co": [RN], "roi_di_phai_co": [RPK], "roi_di_khong_co": [RB],
                "giu": None, "nhin": None}},

    {"ten": "nhieu_nguoi_o_nha",
     "tinh_huong": "Ba người ở nhà: người KHÁC đi lại ở phòng khách không có nghĩa người trong phòng học đã "
                   "ra — tắt nhầm khi dựa vào khu khác gần bằng lúc không ai báo.",
     "ten_tb": "Đèn phòng học", "dan": [],
     "uv": _uv("light.den_hoc", "Phòng học",
               {RH: _hd("Radar phòng học", "Phòng học", 60, "85%", "85%"),
                RPK: _hd("Radar phòng khách", "Phòng khách", 350), CPK: _hd("Camera phòng khách Person", "Phòng khách", 400)},
               roi=[{"x": RPK, "n": 90, "nham": "38%", "khung": "chiều 35%/30 tối 40%/60"},
                    {"x": CPK, "n": 70, "nham": "41%", "khung": "chiều 40%/20 tối 42%/50"}],
               roi_nen={"n": 60, "nham": "45%", "khung": "tối 45%/60"}, camera=["Cam phòng khách"]),
     "dap_an": {"co_nguoi_phai_co": [RH], "roi_di": None}},

    {"ten": "ngoi_yen_lam_viec_chu_nha_dan_laptop",
     "tinh_huong": "Người ngồi yên làm việc máy tính: radar mất dấu; chủ nhà dặn laptop là ngoại vi để "
                   "NHÌN LẠI — chỉ nhìn lại khi laptop đang dùng và người đó không ở khu khác.",
     "ten_tb": "Đèn phòng khách",
     "dan": ["(chấm sai) Laptop của chị Lan là ngoại vi — có laptop chưa chắc có người, để kiểm tra lại "
             "xem có ai ở phòng khách không."],
     "uv": _uv("light.den_pk", "Phòng khách", _pk_can_ho(),
               ngoai_vi=[_nv(TIVI, "Tivi phòng khách", ["off", "on"], "off 60%, on 30%", "off 80%, on 15%", 4),
                         _nv(LAP, "Laptop chị Lan", ["home", "not_home"], "không rõ 70%, home 25%",
                             "không rõ 65%, not_home 30%", 0.1),
                         _nv(DT, "Điện thoại chị Lan", ["home", "not_home"], "home 80%", "home 60%, not_home 40%", 0.5)],
               camera=["Cam phòng khách", "Cam cổng"], frigate=["Cam phòng khách"]),
     "dap_an": {"co_nguoi_phai_co": [CPK], "giu_phai_co": {LAP: ["home"]}, "giu_khong_co": [TIVI],
                "nhin_phai_co": ["Cam phòng khách"], "nhin_khong_co": ["Cam cổng"]}},

    {"ten": "ngoai_vi_chi_hay_o_trang_thai_tat",
     "tinh_huong": "Số đo cho thấy laptop 'not_home' (tắt) hay gặp lúc mất dấu — trạng thái tắt/vắng không "
                   "bao giờ là dấu hiệu còn người.",
     "ten_tb": "Quạt phòng khách", "dan": [],
     "uv": _uv("fan.quat_pk", "Phòng khách", _pk_can_ho(), ngan=2000, dai=30,
               ngoai_vi=[_nv(LAP, "Laptop", ["home", "not_home"], "không rõ 70%, not_home 25%",
                             "không rõ 70%, home 25%", 0.1)],
               camera=["Cam phòng khách"]),
     "dap_an": {"giu": None, "nhin": None}},

    {"ten": "nha_tam_khong_camera",
     "tinh_huong": "Nhà tắm không có camera (và không được có): loa phát nhạc hay gặp lúc mất dấu nhưng "
                   "không có camera nào nhìn lại được — ngoại vi vô dụng.",
     "ten_tb": "Đèn nhà tắm", "dan": [],
     "uv": _uv("light.den_tam", "Nhà tắm",
               {RT: _hd("Radar nhà tắm", "Nhà tắm", 40, "70%", "70%"), RPK: _hd("Radar phòng khách", "Phòng khách", 300)},
               ngan=120, dai=90,
               ngoai_vi=[_nv(LOA, "Loa nhà tắm", ["idle", "playing"], "playing 70%, idle 30%", "idle 90%, playing 10%", 3)],
               camera=["Cam phòng khách", "Cam cổng"]),
     "dap_an": {"co_nguoi_phai_co": [RT], "giu": None, "nhin": None}},

    {"ten": "camera_co_ca_all_va_person",
     "tinh_huong": "Camera có cả cảm biến 'All' (mọi vật, cả mèo, rèm bay) và 'Person' — chỉ dùng Person.",
     "ten_tb": "Đèn phòng khách", "dan": [],
     "uv": _uv("light.den_pk2", "Phòng khách",
               {**_pk_can_ho(), APK: _hd("Camera phòng khách All", "Phòng khách", 270, "40%", "0%")},
               camera=["Cam phòng khách"]),
     "dap_an": {"co_nguoi_phai_co": [CPK], "co_nguoi_khong_co": [APK]}},

    {"ten": "cam_bien_ket_o_khu_khac",
     "tinh_huong": "Radar phòng học báo có người 100% thời gian (kẹt) — không mang thông tin, không dùng "
                   "cho gì cả.",
     "ten_tb": "Đèn phòng khách", "dan": [],
     "uv": _uv("light.den_pk3", "Phòng khách",
               {**_pk_can_ho(), RH: _hd("Radar phòng học", "Phòng học", 0)}, ket=[RH],
               roi=[{"x": RB, "n": 300, "nham": "90%", "khung": "tối 90%/300"}],
               roi_nen={"n": 400, "nham": "75%", "khung": "tối 75%/400"}, camera=["Cam phòng khách"]),
     "dap_an": {"co_nguoi_khong_co": [RH], "roi_di": None}},

    {"ten": "camera_khu_khac_trum_sang",
     "tinh_huong": "Phòng khách không có camera riêng nhưng camera bếp (chung cư, bếp liền phòng khách) "
                   "thấy cả phòng khách; chủ nhà dặn laptop là ngoại vi.",
     "ten_tb": "Đèn phòng khách",
     "dan": ["(chấm sai) Laptop chị Lan là ngoại vi. Camera bếp nhìn thấy cả phòng khách."],
     "uv": _uv("light.den_pk4", "Phòng khách",
               {RPK: _hd("Radar phòng khách", "Phòng khách", 350, "70%", "70%"),
                RB: _hd("Radar bếp", "Bếp", 310), CB: _hd("Camera bếp Person", "Bếp", 690)},
               ngoai_vi=[_nv(LAP, "Laptop chị Lan", ["home", "not_home"], "home 30%", "not_home 30%", 0.1),
                         _nv(DT, "Điện thoại chị Lan", ["home", "not_home"], "home 80%", "home 60%", 0.5)],
               camera=["Cam bếp", "Cam cổng"], frigate=["Cam bếp"]),
     "dap_an": {"giu_phai_co": {LAP: ["home"]}, "nhin_phai_co": ["Cam bếp"], "nhin_khong_co": ["Cam cổng"]}},

    {"ten": "roi_khu_tung_sai_buoi_toi",
     "tinh_huong": "Lựa chọn «rời khu» cũ bị chủ nhà bật lại ngay nhiều lần buổi tối (người khác đi ngang) — "
                   "bằng chứng lựa chọn cũ sai, phải sửa hoặc bỏ.",
     "ten_tb": "Đèn phòng ngủ", "dan": [],
     "uv": _uv("light.den_ngu2", "Phòng ngủ",
               {RN: _hd("Radar phòng ngủ", "Phòng ngủ", 45, "80%", "80%"),
                RPK: _hd("Radar phòng khách", "Phòng khách", 300), RBC: _hd("Radar ban công", "Ban công", 100)},
               roi=[{"x": RPK, "n": 30, "nham": "17%", "khung": "sáng 5%/10 chiều 5%/8 tối 42%/12"},
                    {"x": RBC, "n": 25, "nham": "12%", "khung": "chiều 10%/10 tối 13%/15"}],
               roi_nen={"n": 50, "nham": "46%", "khung": "tối 48%/40"},
               roi_da={"tối": {"sai": 3, "n": 4}, "chiều": {"sai": 0, "n": 3}}, camera=[]),
     "dap_an": {"roi_di_khong_co": [RPK]}},

    {"ten": "cam_bien_khong_doi_lan_nao",
     "tinh_huong": "Cảm biến chuyển động đổi 0 lần/ngày (hết pin, hỏng) — bỏ.",
     "ten_tb": "Đèn phòng khách", "dan": [],
     "uv": _uv("light.den_pk5", "Phòng khách",
               {**_pk_can_ho(), MPK: _hd("Chuyển động phòng khách", "Phòng khách", 0, "8%", "3%")},
               camera=["Cam phòng khách"]),
     "dap_an": {"co_nguoi_khong_co": [MPK], "co_nguoi_phai_co": [CPK]}},

    {"ten": "radar_lay_nhung_khong_co_camera_xac_nhan",
     "tinh_huong": "Radar phòng khách cùng báo với radar bếp 60% nhưng phòng khách không có camera: cùng báo "
                   "có thể là HAI người ở hai khu — không được loại lây.",
     "ten_tb": "Đèn phòng khách", "dan": [],
     "uv": _uv("light.den_pk6", "Phòng khách",
               {RPK: _hd("Radar phòng khách", "Phòng khách", 350, "70%", "70%"), RB: _hd("Radar bếp", "Bếp", 310)},
               cap=[{"r": RPK, "x": RB, "p": 0.6, "xac": {}}], camera=["Cam cổng"]),
     "dap_an": {"co_nguoi_phai_co": [RPK], "co_nguoi_phu_dinh_khong": [RB]}},
]
