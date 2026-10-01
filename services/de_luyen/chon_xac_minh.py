"""Bộ đề LUYỆN cho `chon_xac_minh.md` — bot tự xác minh trước khi bật/tắt, tự chấm sau khi làm.

Chủ máy 01/10/2026: "nhà tôi thì thế nhưng nhà khác thì chỉ có mỗi cảm biến chuyển động hoặc hiện diện";
"dạy cho bot phải đúng, đủ các trường hợp"; "đây mới chỉ là khu vực phòng khách — khu vực bếp, ban công,
phòng học, phòng ngủ". Nên bộ đề có: nhà nhiều nguồn (dáng nhà chủ máy, đủ các khu), nhà chỉ cảm biến
chuyển động, chỉ hiện diện, chỉ camera, văn phòng; trẻ nhỏ, chó mèo, người làm giờ thất thường; thiết bị
nguy hiểm; nguồn kẹt / chết; camera nhìn khu khác.

Đáp án — khoá ``<đường>`` là ``bat.xac_minh``, ``tat.nha_vang``, ``tu_cham.tat``…, kèm đuôi:
  ``_phai_co: [mã]``     phải có đủ          ``_phai_co_mot: [mã]``  phải có ít nhất một
  ``_khong_co: [mã]``    không được có        ``_rong: True``         phải rỗng
  ``bat.hoi`` / ``tat.hoi``: giá trị phải đúng; ``…_mot_trong: [giá trị]`` một trong.
"""

from __future__ import annotations

from typing import Any

TANG = "services.xac_minh_nha"


def _n(ma: str, loai: str, khu: str = "", ghi_chu: str = "") -> dict[str, str]:
    return {"ma": ma, "loai": loai, "khu": khu, "ghi_chu": ghi_chu}


def _c(ten: str, thay: list[str], ghi_chu: str = "") -> dict[str, Any]:
    return {"ten": ten, "thay": thay, "ghi_chu": ghi_chu}


def _uv(tb: str, khu: str, loai_tb: str, nguon: list, camera: list | None = None, *, lich: list | None = None,
        ket_qua: list | None = None, so_do: list | None = None, noi: str = "", nguy_hiem: bool = False) -> dict:
    return {"tb": tb, "khu": khu, "loai_tb": loai_tb, "noi": noi, "nguy_hiem": nguy_hiem, "nguon": nguon,
            "camera": camera or [], "lich": lich or [], "ket_qua": ket_qua or [], "so_do": so_do or []}


# ── Nhà nhiều nguồn — dáng nhà chủ máy (chung cư, bếp mở liền phòng khách) ───────────────────────────
RPK, KPK = "binary_sensor.radar_phong_khach", "sensor.radar_phong_khach_khoang_cach"
FPK, FB, FBC = ("binary_sensor.cam_phong_khach_person", "binary_sensor.cam_bep_person",
                "binary_sensor.cam_ban_cong_person")
RB, KB = "binary_sensor.radar_bep", "sensor.radar_bep_khoang_cach"
RN, KN = "binary_sensor.radar_phong_ngu", "sensor.radar_phong_ngu_khoang_cach"
RH, RBC = "binary_sensor.radar_phong_hoc", "binary_sensor.radar_ban_cong"
DTA, DTV, LAPV = "device_tracker.dien_thoai_anh", "device_tracker.dien_thoai_vo", "device_tracker.laptop_vo"
CAM_PK, CAM_B, CAM_BC, CAM_CUA = "Cam phòng khách", "Cam bếp", "Cam ban công", "Cam cửa"


def _nguon_nha() -> list[dict[str, str]]:
    return [_n(RPK, "hien_dien", "Phòng khách", "xuyên vách, hay báo lây người ở bếp"),
            _n(KPK, "khoang_cach", "Phòng khách", "cùng radar phòng khách"),
            _n(FPK, "camera_nguoi", "Phòng khách"), _n(RB, "hien_dien", "Bếp"),
            _n(KB, "khoang_cach", "Bếp", "cùng radar bếp"), _n(FB, "camera_nguoi", "Bếp"),
            _n(RBC, "hien_dien", "Ban công"), _n(FBC, "camera_nguoi", "Ban công"),
            _n(RN, "hien_dien", "Phòng ngủ"), _n(KN, "khoang_cach", "Phòng ngủ", "cùng radar phòng ngủ"),
            _n(RH, "hien_dien", "Phòng học"),
            _n(DTA, "mang", "", "điện thoại anh"), _n(DTV, "mang", "", "điện thoại vợ"),
            _n(LAPV, "mang", "", "laptop vợ, dùng ở phòng khách")]


def _cam_nha() -> list[dict[str, Any]]:
    return [_c(CAM_PK, ["Phòng khách"], "thấy trọn phòng khách"),
            _c(CAM_B, ["Bếp", "Phòng khách"], "chỉ thấy MỘT GÓC bếp (8 ô); phần lớn khung hình là phòng khách"),
            _c(CAM_BC, ["Ban công"]), _c(CAM_CUA, [], "nhìn ra hành lang chung cư")]


LICH_NHA = ["Cả nhà ngủ 21:45–06:00 hằng ngày", "Nhà vắng (đi học, đi làm) 07:15–16:00 thứ 2–6",
            "Ăn tối 19:00–19:45", "Thành viên: anh, vợ, con trai (tiểu học, không có điện thoại), con gái nhỏ"]
SO_DO_NHA = ["Phòng khách THÔNG Bếp", "Bếp có cửa sang Ban công, Nhà tắm",
             "Phòng ngủ, Phòng học có vách (cửa) ra phía bếp – phòng khách"]


def _nha(tb: str, khu: str, loai_tb: str, ket_qua: list | None = None, **k: Any) -> dict:
    return _uv(tb, khu, loai_tb, _nguon_nha(), _cam_nha(), lich=LICH_NHA, so_do=SO_DO_NHA, noi="chung cư",
               ket_qua=ket_qua, **k)


# ── Nhà khác ──────────────────────────────────────────────────────────────────────────────────────────
PIR_PK, PIR_N, PIR_HL = ("binary_sensor.motion_phong_khach", "binary_sensor.motion_phong_ngu",
                         "binary_sensor.motion_hanh_lang")
FP2_N = "binary_sensor.fp2_phong_ngu"

DE: list[dict[str, Any]] = [
    {"ten": "nha_nhieu_nguon_den_tran_phong_khach",
     "tinh_huong": "Đèn trần phòng khách, nhà đủ nguồn: tắt thì phải có camera thấy trọn khu và khoảng cách "
                   "(radar phòng khách báo lây người ở bếp); không dùng radar bếp, không dùng điện thoại. Hỏi "
                   "người 7/11 lần không ai trả lời → không hỏi, tự chấm bằng camera.",
     "ten_tb": "Đèn trần phòng khách",
     "dan": ["Tắt thì cũng dựa vào khoảng cách để tắt, chứ không phải chỉ là trống ở cảm biến phòng khách."],
     "uv": _nha("light.den_tran", "Phòng khách", "đèn",
                ["Tự tắt 16 lần, bị bật lại 6 lần — đều «vắng 3 phút» lúc người ngồi yên",
                 "Hỏi 11 lần, 7 lần không ai trả lời"]),
     "dap_an": {"tat.xac_minh_phai_co": [CAM_PK, KPK], "tat.xac_minh_khong_co": [RB, FB, DTA, DTV, LAPV],
                "tat.hoi": "khong", "tat.nha_vang_rong": True,
                "bat.xac_minh_phai_co_mot": [CAM_PK, FPK, RPK],
                "tu_cham.tat_phai_co_mot": [CAM_PK, RPK, FPK], "tu_cham.bat_phai_co_mot": [CAM_PK, RPK, FPK]}},

    {"ten": "nha_nhieu_nguon_quat_phong_khach_gio_lech",
     "tinh_huong": "Quạt phòng khách; chủ nhà dặn vợ có hôm làm chiều, sáng ở nhà — giờ «nhà vắng» hay lệch: "
                   "lệch lịch phải kiểm thêm bằng camera thấy khu.",
     "ten_tb": "Quạt phòng khách",
     "dan": ["Đôi khi vợ tôi làm buổi chiều, sáng có ở nhà."],
     "uv": _nha("fan.quat", "Phòng khách", "quạt",
                ["Tự bật 7 lần, 3 lần người chỉ đi ngang rồi tắt"]),
     "dap_an": {"bat.lech_lich_phai_co_mot": [CAM_PK, CAM_B], "tat.lech_lich_phai_co_mot": [CAM_PK, CAM_B],
                "tat.xac_minh_phai_co": [CAM_PK], "tat.xac_minh_khong_co": [RB, DTV],
                "tu_cham.bat_phai_co_mot": [CAM_PK, RPK, FPK], "tat.hoi_mot_trong": ["khong", "khi_khong_ro"]}},

    {"ten": "nha_nhieu_nguon_den_bep",
     "tinh_huong": "Đèn bếp: Cam bếp chỉ thấy một góc bếp (không chứng minh được bếp trống một mình); radar bếp "
                   "có khoảng cách; radar / camera phòng khách KHÔNG được dùng để nói bếp trống.",
     "ten_tb": "Đèn bếp", "dan": [],
     "uv": _nha("light.den_bep", "Bếp", "đèn"),
     "dap_an": {"tat.xac_minh_phai_co_mot": [KB, RB],
                "tat.xac_minh_khong_co": [RPK, KPK, CAM_PK, FPK], "bat.xac_minh_phai_co_mot": [CAM_B, FB, RB],
                "tat.hoi_mot_trong": ["khong", "khi_khong_ro"]}},

    {"ten": "nha_nhieu_nguon_den_phong_ngu_khong_camera",
     "tinh_huong": "Phòng ngủ không có camera (riêng tư): tắt chỉ dựa radar phòng ngủ (+ khoảng cách); giờ ngủ "
                   "người nằm yên — sai là phiền thật nên chỉ hỏi khi không rõ; camera khác không thấy phòng ngủ.",
     "ten_tb": "Đèn phòng ngủ", "dan": [],
     "uv": _nha("light.den_ngu", "Phòng ngủ", "đèn",
                ["Tự tắt 10 lần, bị bật lại 4 lần (vắng 3–9 phút lúc tối)"]),
     "dap_an": {"tat.xac_minh_phai_co": [RN], "tat.xac_minh_khong_co": [CAM_PK, CAM_B, RPK, RB, DTA, DTV],
                "bat.xac_minh_khong_co": [CAM_PK, CAM_B], "tu_cham.tat_phai_co": [RN],
                "tat.hoi_mot_trong": ["khi_khong_ro", "khong"]}},

    {"ten": "nha_nhieu_nguon_den_phong_hoc_cam_bien_ket",
     "tinh_huong": "Phòng học chỉ có một radar và nó đang KẸT báo có người: không dùng được; không camera nào "
                   "thấy phòng học → không xác minh được, hỏi khi không rõ.",
     "ten_tb": "Đèn phòng học", "dan": [],
     "uv": {**_nha("light.den_hoc", "Phòng học", "đèn"),
            "nguon": [{**x, "ghi_chu": "KẸT «có người» từ 3 ngày nay"} if x["ma"] == RH else x
                      for x in _nguon_nha()]},
     "dap_an": {"tat.xac_minh_khong_co": [RH, CAM_PK, CAM_B, RPK], "bat.xac_minh_khong_co": [RH],
                "tat.hoi": "khi_khong_ro"}},

    {"ten": "nha_nhieu_nguon_binh_nong_lanh",
     "tinh_huong": "Bình nóng lạnh: nguy hiểm — luôn hỏi.",
     "ten_tb": "Bình nóng lạnh", "dan": [],
     "uv": _nha("switch.binh_nong_lanh", "Nhà tắm", "bình nóng lạnh", nguy_hiem=True),
     "dap_an": {"bat.hoi": "luon", "tat.hoi": "luon"}},

    {"ten": "nha_nhieu_nguon_den_ban_cong",
     "tinh_huong": "Đèn ban công: Cam ban công thấy ban công; Cam cửa nhìn hành lang ngoài, không dùng.",
     "ten_tb": "Đèn ban công", "dan": [],
     "uv": _nha("light.den_ban_cong", "Ban công", "đèn"),
     "dap_an": {"tat.xac_minh_phai_co": [CAM_BC], "tat.xac_minh_khong_co": [CAM_CUA, RB, CAM_B, FB],
                "bat.xac_minh_phai_co_mot": [CAM_BC, FBC, RBC], "bat.kiem_lai_rong": True}},

    {"ten": "nha_nhieu_nguon_ban_cong_radar_bao_ao",
     "tinh_huong": "Chủ máy 01/10/2026: radar ban công hay báo ẢO nên đèn ban công hay bật, mà YOLO, Frigate không "
                   "thấy người. Bật ngay theo radar nhưng KIỂM LẠI bằng camera + Frigate; radar không được tự xác "
                   "nhận mình.",
     "ten_tb": "Đèn ban công",
     "dan": ["Cảm biến hiện diện ban công hay báo ảo nên đèn ban công hay bật, nhưng YOLO, Frigate lại không có "
             "người. Bật thì kết hợp với cảm biến Frigate."],
     "uv": {**_nha("light.den_ban_cong2", "Ban công", "đèn",
                   ["Radar ban công báo có người mà camera không thấy ai: 141 giờ / 30 ngày (hay báo ẢO)",
                    "Tự bật 20 lần, 12 lần không có ai ra ban công"]),
            "nguon": [{**x, "ghi_chu": "hay báo ẢO (gió, đồ phơi)"} if x["ma"] == RBC else x
                      for x in _nguon_nha()]},
     "dap_an": {"bat.kiem_lai_phai_co": [CAM_BC], "bat.kiem_lai_phai_co_mot": [FBC], "bat.kiem_lai_khong_co": [RBC],
                "tat.xac_minh_phai_co": [CAM_BC], "tu_cham.bat_phai_co_mot": [CAM_BC, FBC],
                "tu_cham.bat_khong_co": [RBC]}},

    # ── BÁO ẢO ở nhà khác — cùng lớp với ban công nhà chủ máy (chủ máy: "đây là ví dụ cụ thể nhưng phải dạy
    # bot để có thể nhiều trường hợp").
    {"ten": "phong_ngu_quat_tran_lam_radar_bao_ao",
     "tinh_huong": "Quạt trần làm radar phòng ngủ báo ảo lúc phòng trống; có camera hành lang không thấy phòng "
                   "ngủ — không có nguồn kiểm lại trong phòng: kiem_lai rỗng, không lấy camera hành lang; tự chấm "
                   "bật nhầm bằng việc người tắt đi.",
     "ten_tb": "Đèn phòng ngủ", "dan": [],
     "uv": _uv("light.den_ngu9", "Phòng ngủ", "đèn",
               [_n("binary_sensor.radar_ngu9", "hien_dien", "Phòng ngủ", "hay báo ẢO khi quạt trần quay"),
                _n("binary_sensor.motion_hanh_lang9", "chuyen_dong", "Hành lang")],
               [_c("Camera hành lang", ["Hành lang"])], noi="nhà phố",
               ket_qua=["Tự bật 15 lần, 6 lần phòng không có ai (quạt trần đang quay)"]),
     "dap_an": {"bat.kiem_lai_khong_co": ["Camera hành lang", "binary_sensor.motion_hanh_lang9"],
                "bat.xac_minh_khong_co": ["Camera hành lang"], "tat.xac_minh_khong_co": ["Camera hành lang"]}},

    {"ten": "san_vuon_cay_va_xe_lam_bao_ao",
     "tinh_huong": "Đèn sân: cảm biến chuyển động ngoài trời báo cả cây lay, xe chạy qua cổng; camera sân thấy "
                   "trọn sân và có Frigate — bật ngay, kiểm lại bằng camera (YOLO) + Frigate.",
     "ten_tb": "Đèn sân", "dan": [],
     "uv": _uv("light.den_san", "Sân", "đèn",
               [_n("binary_sensor.motion_san", "chuyen_dong", "Sân", "ngoài trời, hay báo ẢO khi gió lay cây, xe qua"),
                _n("binary_sensor.cam_san_person", "camera_nguoi", "Sân")],
               [_c("Camera sân", ["Sân"], "thấy trọn sân, có hồng ngoại ban đêm")], noi="biệt thự"),
     "dap_an": {"bat.kiem_lai_phai_co": ["Camera sân"], "bat.kiem_lai_phai_co_mot": ["binary_sensor.cam_san_person"],
                "bat.kiem_lai_khong_co": ["binary_sensor.motion_san"], "tat.xac_minh_phai_co": ["Camera sân"],
                "tat.xac_minh_khong_co": ["binary_sensor.motion_san"]}},

    {"ten": "cho_lam_chuyen_dong_bao_khong_co_camera",
     "tinh_huong": "Nhà nuôi chó, chỉ có cảm biến chuyển động phòng khách, không camera: không tách được chó với "
                   "người, không có gì để kiểm lại → bật thì hỏi khi không rõ, không tự tin bật theo chuyển động.",
     "ten_tb": "Đèn phòng khách", "dan": ["Nhà có con chó to, ban đêm hay đi lại trong phòng khách."],
     "uv": _uv("light.den_pk10", "Phòng khách", "đèn",
               [_n("binary_sensor.motion_pk10", "chuyen_dong", "Phòng khách", "báo cả khi chó đi lại")],
               noi="nhà phố"),
     "dap_an": {"bat.hoi_mot_trong": ["khi_khong_ro", "luon"], "bat.kiem_lai_rong": True,
                "tat.xac_minh_rong": True}},

    {"ten": "chi_cam_bien_chuyen_dong_phong_khach",
     "tinh_huong": "Chung cư chỉ có MỘT cảm biến chuyển động: bật theo nó; tắt không nguồn nào chứng minh vắng "
                   "(xac_minh rỗng), không hỏi — tự chấm bằng chính cảm biến báo lại ngay sau khi tắt.",
     "ten_tb": "Đèn phòng khách", "dan": [],
     "uv": _uv("light.den_pk", "Phòng khách", "đèn", [_n(PIR_PK, "chuyen_dong", "Phòng khách")], noi="chung cư"),
     "dap_an": {"bat.xac_minh_phai_co": [PIR_PK], "tat.xac_minh_rong": True, "tat.hoi": "khong",
                "tu_cham.tat_phai_co": [PIR_PK]}},

    {"ten": "chi_hien_dien_phong_ngu",
     "tinh_huong": "Chỉ một cảm biến hiện diện (mmWave) phòng ngủ, không khoảng cách: dùng cho cả bật, tắt, tự "
                   "chấm.",
     "ten_tb": "Đèn ngủ", "dan": [],
     "uv": _uv("light.den_ngu2", "Phòng ngủ", "đèn", [_n(FP2_N, "hien_dien", "Phòng ngủ")], noi="nhà phố"),
     "dap_an": {"bat.xac_minh_phai_co": [FP2_N], "tat.xac_minh_phai_co": [FP2_N], "tu_cham.tat_phai_co": [FP2_N],
                "bat.hoi_mot_trong": ["khong", "khi_khong_ro"]}},

    {"ten": "chi_camera_phong_khach",
     "tinh_huong": "Nhà chỉ có camera (không radar): camera là nguồn xác minh cả hai chiều.",
     "ten_tb": "Đèn phòng khách", "dan": [],
     "uv": _uv("light.den_pk3", "Phòng khách", "đèn", [_n("binary_sensor.cam_pk_person", "camera_nguoi", "Phòng khách")],
               [_c("Camera phòng khách", ["Phòng khách"], "thấy trọn phòng khách")], noi="nhà phố"),
     "dap_an": {"bat.xac_minh_phai_co_mot": ["Camera phòng khách", "binary_sensor.cam_pk_person"],
                "tat.xac_minh_phai_co": ["Camera phòng khách"], "tat.hoi": "khong"}},

    {"ten": "van_phong_chuyen_dong_va_may_nhan_vien",
     "tinh_huong": "Văn phòng: cảm biến chuyển động + máy của MỌI nhân viên. Ai cũng mang máy → nha_vang dùng "
                   "máy; chuyển động không chứng minh vắng.",
     "ten_tb": "Đèn khu làm việc", "dan": [],
     "uv": _uv("light.den_lam_viec", "Khu làm việc", "đèn",
               [_n("binary_sensor.motion_lam_viec", "chuyen_dong", "Khu làm việc"),
                _n("device_tracker.may_nv_1", "mang", "", "máy nhân viên 1"),
                _n("device_tracker.may_nv_2", "mang", "", "máy nhân viên 2"),
                _n("device_tracker.may_nv_3", "mang", "", "máy nhân viên 3")],
               lich=["Giờ làm 08:00–17:30 thứ 2–6", "3 nhân viên, ai cũng có máy tính và điện thoại"], noi="văn phòng"),
     "dap_an": {"tat.nha_vang_phai_co": ["device_tracker.may_nv_1", "device_tracker.may_nv_2",
                                         "device_tracker.may_nv_3"],
                "tat.xac_minh_khong_co": ["binary_sensor.motion_lam_viec"],
                "bat.xac_minh_phai_co": ["binary_sensor.motion_lam_viec"]}},

    {"ten": "nha_co_tre_nho_khong_dung_nha_vang",
     "tinh_huong": "Nhà có bà và cháu nhỏ không có điện thoại: mọi điện thoại đi vắng chưa phải nhà trống → "
                   "nha_vang rỗng.",
     "ten_tb": "Đèn phòng khách", "dan": [],
     "uv": _uv("light.den_pk4", "Phòng khách", "đèn",
               [_n("binary_sensor.radar_pk4", "hien_dien", "Phòng khách"),
                _n("device_tracker.dt_bo", "mang", "", "điện thoại bố"), _n("device_tracker.dt_me", "mang", "", "điện thoại mẹ")],
               [_c("Cam phòng khách", ["Phòng khách"])],
               lich=["Thành viên: bố, mẹ, bà nội (không dùng điện thoại), bé 3 tuổi", "Bố mẹ đi làm 07:30–17:30"],
               noi="nhà phố"),
     "dap_an": {"tat.nha_vang_rong": True, "tat.xac_minh_phai_co": ["Cam phòng khách"]}},

    {"ten": "nuoi_meo_chuyen_dong_va_camera",
     "tinh_huong": "Nhà nuôi mèo: cảm biến chuyển động báo cả mèo → bật phải xác minh bằng camera (YOLO tách "
                   "người), không để chuyển động một mình quyết.",
     "ten_tb": "Đèn phòng khách", "dan": ["Nhà tôi nuôi 2 con mèo, hay chạy lung tung ban đêm."],
     "uv": _uv("light.den_pk5", "Phòng khách", "đèn",
               [_n("binary_sensor.motion_pk5", "chuyen_dong", "Phòng khách")],
               [_c("Camera phòng khách", ["Phòng khách"])], noi="chung cư"),
     "dap_an": {"bat.xac_minh_phai_co": ["Camera phòng khách"], "bat.xac_minh_khong_co": ["binary_sensor.motion_pk5"],
                "tat.xac_minh_phai_co": ["Camera phòng khách"], "tat.xac_minh_khong_co": ["binary_sensor.motion_pk5"]}},

    {"ten": "camera_chet_dung_radar",
     "tinh_huong": "Camera phòng khách hay mất kết nối (ghi chú «chết»): không dựa vào nó; dùng radar, hỏi khi "
                   "không rõ.",
     "ten_tb": "Đèn phòng khách", "dan": [],
     "uv": _uv("light.den_pk6", "Phòng khách", "đèn", [_n("binary_sensor.radar_pk6", "hien_dien", "Phòng khách")],
               [_c("Camera phòng khách", ["Phòng khách"], "CHẾT — mất kết nối 5 ngày nay")], noi="chung cư"),
     "dap_an": {"tat.xac_minh_khong_co": ["Camera phòng khách"], "tat.xac_minh_phai_co": ["binary_sensor.radar_pk6"],
                "bat.xac_minh_khong_co": ["Camera phòng khách"]}},

    {"ten": "bep_tu_nguy_hiem",
     "tinh_huong": "Bếp từ: nguy hiểm — luôn hỏi dù có camera.",
     "ten_tb": "Bếp từ", "dan": [],
     "uv": _uv("switch.bep_tu", "Bếp", "bếp từ", [_n("binary_sensor.radar_bep7", "hien_dien", "Bếp")],
               [_c("Camera bếp", ["Bếp"])], nguy_hiem=True, noi="chung cư"),
     "dap_an": {"bat.hoi": "luon", "tat.hoi": "luon"}},

    {"ten": "nha_pho_phong_ngu_tang_2_hanh_lang",
     "tinh_huong": "Nhà phố: phòng ngủ tầng 2 có cảm biến chuyển động trong phòng + chuyển động hành lang: hành "
                   "lang là khu khác — không dùng để nói phòng ngủ trống; chuyển động phòng ngủ không chứng minh "
                   "vắng.",
     "ten_tb": "Đèn phòng ngủ tầng 2", "dan": [],
     "uv": _uv("light.den_ngu_t2", "Phòng ngủ", "đèn",
               [_n(PIR_N, "chuyen_dong", "Phòng ngủ"), _n(PIR_HL, "chuyen_dong", "Hành lang tầng 2")],
               noi="nhà phố", so_do=["Phòng ngủ có cửa sang Hành lang tầng 2"]),
     "dap_an": {"tat.xac_minh_khong_co": [PIR_N, PIR_HL], "bat.xac_minh_phai_co": [PIR_N],
                "bat.xac_minh_khong_co": [PIR_HL], "tu_cham.tat_phai_co": [PIR_N]}},

    {"ten": "lech_lich_dem_khong_camera",
     "tinh_huong": "Giờ lệch nhưng khu không có camera nào: lech_lich chỉ còn radar của khu, không lấy camera "
                   "khu khác.",
     "ten_tb": "Đèn phòng làm việc", "dan": ["Tôi hay làm việc khuya bất chợt, không theo lịch."],
     "uv": _uv("light.den_lv", "Phòng làm việc", "đèn",
               [_n("binary_sensor.radar_lv", "hien_dien", "Phòng làm việc"),
                _n("binary_sensor.radar_pk8", "hien_dien", "Phòng khách")],
               [_c("Camera phòng khách", ["Phòng khách"])],
               lich=["Cả nhà ngủ 22:30–06:00"], noi="nhà phố"),
     "dap_an": {"tat.lech_lich_khong_co": ["Camera phòng khách", "binary_sensor.radar_pk8"],
                "bat.lech_lich_khong_co": ["Camera phòng khách", "binary_sensor.radar_pk8"],
                "tat.xac_minh_phai_co": ["binary_sensor.radar_lv"]}},
]


def _lay(bai: dict[str, Any], duong: str) -> Any:
    x: Any = bai
    for p in duong.split("."):
        x = (x or {}).get(p) if isinstance(x, dict) else None
    return x


def cham_cho(bai: dict[str, Any] | str, dap_an: dict[str, Any]) -> list[str]:
    if isinstance(bai, str):
        return [f"bài bị loại: {bai}"]
    loi: list[str] = []
    for k, v in dap_an.items():
        for duoi in ("_phai_co_mot", "_phai_co", "_khong_co", "_rong", "_mot_trong", ""):
            if k.endswith(duoi):
                duong = k[:len(k) - len(duoi)] if duoi else k
                break
        x = _lay(bai, duong)
        co = set(x) if isinstance(x, list) else set()
        if duoi == "_phai_co":
            loi += [f"{duong} thiếu {m}" for m in v if m not in co]
        elif duoi == "_phai_co_mot" and not co & set(v):
            loi.append(f"{duong} phải có ít nhất một trong {v}")
        elif duoi == "_khong_co":
            loi += [f"{duong} không được có {m}" for m in v if m in co]
        elif duoi == "_rong" and co:
            loi.append(f"{duong} phải rỗng, bài viết {sorted(co)}")
        elif duoi == "_mot_trong" and x not in v:
            loi.append(f"{duong} phải là một trong {v}, bài viết {x!r}")
        elif duoi == "" and x != v:
            loi.append(f"{duong} phải là {v!r}, bài viết {x!r}")
    return loi
