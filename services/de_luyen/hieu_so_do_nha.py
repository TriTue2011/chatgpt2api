"""Bộ đề LUYỆN cho `hieu_so_do_nha.md` — nhiều kiểu nhà, không riêng nhà nào (chủ máy 29/09/2026:
"train cho bot các kiến thức về kiến trúc, nội thất, xây dựng").

Đáp án (mọi khoá tuỳ chọn): ``kieu``; ``so_tang``; ``thong``: [[A, B]] phải thông; ``khong_thong``:
[[A, B]] không được ghi thông; ``cua_vao``; ``camera_thay``: {camera: [phòng phải có]};
``camera_khong_thay``: {camera: [phòng không được có]}; ``phai_hoi``: True (còn điều chưa chắc);
``loi_di``: [[A, B]] phải đi thẳng sang được (thông hoặc `cua_sang`); ``khong_loi_di``: [[A, B]] không được.
"""

from __future__ import annotations

from typing import Any

TANG = "services.so_do_nha"


def _p(hien: list[str], tb: list[str] | None = None) -> dict[str, list[str]]:
    return {"hien_dien": hien, "thiet_bi": tb or []}


def _uv(phong: dict, cung_bao: list, camera: dict, cua: dict, loi_vao: dict | None = None,
        khong_cb: dict | None = None) -> dict[str, Any]:
    ten = {m: m.split(".")[1].replace("_", " ") for p in phong.values() for m in p["hien_dien"] + p["thiet_bi"]}
    ten.update({m: m.split(".")[1].replace("_", " ") for m in cua})
    return {"phong": phong, "khu_radar": sorted(k for k, p in phong.items() if p["hien_dien"]), "ket": [],
            "cung_bao": cung_bao, "camera": camera, "loi_camera": "", "cua": cua, "ten": ten,
            "loi_vao": loi_vao or {}, "khong_cb": khong_cb or {}}


def _v(n: int, *dau_hieu: tuple[str, float, float]) -> dict[str, Any]:
    """Một khu ở mục D2: ``n`` lần vào, mỗi dấu hiệu (tên, % lúc vào, % mốc nền) — tỉ lệ 0–1."""
    return {"n": n, "dau_hieu": [list(x) for x in dau_hieu]}


def _o(ds: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    return ds


CAN_HO = {"Phòng khách": _p(["binary_sensor.radar_pk"], ["light.den_tran"]),
          "Bếp": _p(["binary_sensor.radar_bep"], ["light.den_bep"]),
          "Phòng ngủ": _p(["binary_sensor.radar_ngu"], ["light.den_ngu"]),
          "Ban công": _p(["binary_sensor.radar_ban_cong"])}

DE: list[dict[str, Any]] = [
    {"ten": "chung_cu_bep_mo",
     "tinh_huong": "Chung cư, bếp mở liền phòng khách: cùng báo cao, camera phòng khách thấy cả góc bếp.",
     "mo_ta": ["Nhà tôi là căn hộ chung cư 2 phòng ngủ, bếp mở liền phòng khách."],
     "uv": _uv(CAN_HO,
               [{"a": "Phòng khách", "b": "Bếp", "ty_le": 0.55}, {"a": "Bếp", "b": "Phòng khách", "ty_le": 0.45},
                {"a": "Phòng ngủ", "b": "Phòng khách", "ty_le": 0.05}],
               {"Cam phòng khách": {"A5": {"Bếp": 80, "Phòng khách": 20}, "B5": {"Bếp": 70, "Phòng khách": 30},
                                    "E5": {"Phòng khách": 85, "Bếp": 15}, "F6": {"Phòng khách": 90, "Bếp": 10}}},
               {"binary_sensor.cua_chinh": {"Phòng khách": 80, "(không phòng nào)": 60, "Bếp": 10}}),
     "dap_an": {"kieu": "chung_cu", "thong": [["Phòng khách", "Bếp"]], "khong_thong": [["Phòng ngủ", "Phòng khách"]],
                "cua_vao": "Phòng khách", "camera_thay": {"Cam phòng khách": ["Phòng khách", "Bếp"]}}},

    {"ten": "chung_cu_bep_kin_vach_kinh",
     "tinh_huong": "Bếp có vách kính + cửa lùa: radar xuyên kính nên cùng báo khá cao, nhưng camera phòng khách "
                   "không thấy người trong bếp — chủ nhà nói có vách kính.",
     "mo_ta": ["Chung cư, bếp có vách kính và cửa lùa ngăn với phòng khách."],
     "uv": _uv(CAN_HO,
               [{"a": "Phòng khách", "b": "Bếp", "ty_le": 0.42}],
               {"Cam phòng khách": {"D5": {"Phòng khách": 90, "Bếp": 10}, "E6": {"Phòng khách": 88, "Bếp": 12}}},
               {"binary_sensor.cua_chinh": {"Phòng khách": 70, "(không phòng nào)": 50}}),
     "dap_an": {"kieu": "chung_cu", "khong_thong": [["Phòng khách", "Bếp"]],
                "camera_khong_thay": {"Cam phòng khách": ["Bếp"]}}},

    {"ten": "nha_pho_ba_tang",
     "tinh_huong": "Nhà phố 3 tầng: tầng 1 phòng khách + bếp thông nhau, tầng 2 phòng ngủ, tầng 3 phòng thờ; "
                   "chủ nhà mô tả — số tầng phải theo lời chủ nhà.",
     "mo_ta": ["Nhà ống 3 tầng. Tầng 1 phòng khách và bếp phía sau thông nhau, tầng 2 phòng ngủ, "
               "tầng 3 phòng thờ và sân phơi."],
     "uv": _uv({"Phòng khách": _p(["binary_sensor.radar_pk"]), "Bếp": _p(["binary_sensor.radar_bep"]),
                "Phòng ngủ": _p(["binary_sensor.radar_ngu"])},
               [{"a": "Phòng khách", "b": "Bếp", "ty_le": 0.5}, {"a": "Phòng ngủ", "b": "Phòng khách", "ty_le": 0.03}],
               {}, {"binary_sensor.cua_chinh": {"Phòng khách": 90, "(không phòng nào)": 40}}),
     "dap_an": {"kieu": "nha_pho", "so_tang": 3, "thong": [["Phòng khách", "Bếp"]],
                "khong_thong": [["Phòng ngủ", "Phòng khách"]], "cua_vao": "Phòng khách"}},

    {"ten": "chua_co_mo_ta_bang_chung_mo_ho",
     "tinh_huong": "Chưa có lời chủ nhà, lưới camera lẫn lộn — không được bịa kiểu nhà, phải hỏi.",
     "mo_ta": [],
     "uv": _uv(CAN_HO, [{"a": "Phòng khách", "b": "Bếp", "ty_le": 0.3}],
               {"Cam phòng khách": {"C5": {"Phòng khách": 45, "Bếp": 35, "Phòng ngủ": 20}}}, {}),
     "dap_an": {"kieu": "khong_ro", "phai_hoi": True}},

    {"ten": "radar_xuyen_vach_phong_ngu_ban_cong",
     "tinh_huong": "Phòng ngủ và ban công cùng báo 70% (radar xuyên cửa kính ban công) nhưng camera ban công chỉ "
                   "thấy ban công — cùng báo cao chưa chắc thông; chủ nhà nói có cửa kính.",
     "mo_ta": ["Chung cư. Phòng ngủ có cửa kính ra ban công."],
     "uv": _uv(CAN_HO, [{"a": "Ban công", "b": "Phòng ngủ", "ty_le": 0.7}],
               {"Cam ban công": {"D5": {"Ban công": 90, "Phòng ngủ": 10}, "D6": {"Ban công": 85, "Phòng ngủ": 15}}}, {}),
     "dap_an": {"kieu": "chung_cu", "khong_thong": [["Ban công", "Phòng ngủ"]],
                "camera_khong_thay": {"Cam ban công": ["Phòng ngủ"]}, "camera_thay": {"Cam ban công": ["Ban công"]}}},

    # ── LỐI ĐI giữa các khu (mục D2/D3) — chủ máy 01/10/2026: "cảm biến hiện diện bếp đang trống mà phát hiện
    # trước phòng khách là từ nhà tắm". Đề viết cho NHIỀU kiểu nơi; số liệu đề 1 lấy dáng từ nhà thật.
    {"ten": "chung_cu_nha_tam_mo_ra_bep",
     "tinh_huong": "Nhà tắm không có cảm biến: tắt đèn nhà tắm rồi bếp báo đầu tiên nhiều nhất; vào phòng khách "
                   "thì dấu hiệu nhà tắm hay đi cùng «bếp báo trước» — nhà tắm mở ra bếp, không mở thẳng ra phòng "
                   "khách.",
     "mo_ta": ["Chung cư, bếp mở liền phòng khách."],
     "uv": _uv({**CAN_HO, "Nhà tắm": _p([], ["light.den_nha_tam"])},
               [{"a": "Phòng khách", "b": "Bếp", "ty_le": 0.5}], {},
               {"binary_sensor.cua_chinh": {"Phòng khách": 60, "(không phòng nào)": 50}},
               {"Phòng khách": _v(1300, ("Bếp hết người ngay sau", 0.41, 0.05), ("Bếp báo có người trước", 0.08, 0.003),
                                  ("Nhà tắm: người vừa tắt thiết bị", 0.05, 0.004), ("cua chinh vừa mở", 0.04, 0.0003)),
                "Bếp": _v(1800, ("Phòng khách báo có người trước", 0.25, 0.02), ("Nhà tắm: người vừa tắt thiết bị", 0.06, 0.005),
                          ("Ban công hết người ngay sau", 0.22, 0.07)),
                "Ban công": _v(1300, ("Bếp báo có người trước", 0.30, 0.04), ("Phòng khách báo có người trước", 0.16, 0.05)),
                "Phòng ngủ": _v(500, ("Bếp hết người ngay sau", 0.56, 0.22), ("Phòng khách hết người ngay sau", 0.37, 0.19),
                                ("Bếp báo có người trước", 0.22, 0.06), ("Phòng khách báo có người trước", 0.19, 0.06))},
               {"Nhà tắm": {"Bếp": 115, "Phòng khách": 75, "Ban công": 33, "Phòng ngủ": 28,
                            "(không khu nào — khu bên cạnh có thể đã có người sẵn)": 186}}),
     "dap_an": {"kieu": "chung_cu", "loi_di": [["Nhà tắm", "Bếp"], ["Phòng khách", "Bếp"], ["Ban công", "Bếp"]],
                "khong_loi_di": [["Nhà tắm", "Phòng khách"], ["Nhà tắm", "Ban công"]]}},

    {"ten": "nha_pho_cau_thang_len_phong_ngu",
     "tinh_huong": "Nhà phố 2 tầng: vào phòng ngủ tầng 2 thì cầu thang báo trước gấp nhiều lần nền; «phòng khách hết "
                   "người ngay sau» chỉ hơi cao hơn nền — người đi qua cầu thang, không có lối thẳng phòng khách ↔ "
                   "phòng ngủ.",
     "mo_ta": ["Nhà phố 2 tầng: tầng 1 phòng khách và bếp, tầng 2 phòng ngủ."],
     "uv": _uv({"Phòng khách": _p(["binary_sensor.radar_pk"]), "Bếp": _p(["binary_sensor.radar_bep"]),
                "Cầu thang": _p(["binary_sensor.radar_cau_thang"]), "Phòng ngủ": _p(["binary_sensor.radar_ngu"])},
               [{"a": "Phòng khách", "b": "Bếp", "ty_le": 0.5}], {},
               {"binary_sensor.cua_chinh": {"Phòng khách": 90, "(không phòng nào)": 40}},
               {"Phòng ngủ": _v(400, ("Cầu thang báo có người trước", 0.45, 0.01),
                                ("Phòng khách hết người ngay sau", 0.30, 0.22), ("Cầu thang hết người ngay sau", 0.50, 0.04)),
                "Cầu thang": _v(900, ("Phòng khách báo có người trước", 0.35, 0.03), ("Phòng ngủ hết người ngay sau", 0.30, 0.03),
                                ("Bếp báo có người trước", 0.04, 0.02))}),
     "dap_an": {"kieu": "nha_pho", "so_tang": 2, "loi_di": [["Phòng ngủ", "Cầu thang"], ["Cầu thang", "Phòng khách"]],
                "khong_loi_di": [["Phòng ngủ", "Phòng khách"], ["Cầu thang", "Bếp"]]}},

    {"ten": "van_phong_wc_ra_hanh_lang",
     "tinh_huong": "Văn phòng: WC không cảm biến, tắt đèn WC rồi hành lang báo đầu tiên; khu làm việc chỉ lẻ tẻ.",
     "mo_ta": ["Văn phòng công ty một tầng."],
     "uv": _uv({"Khu làm việc": _p(["binary_sensor.radar_lam_viec"]), "Phòng họp": _p(["binary_sensor.radar_hop"]),
                "Hành lang": _p(["binary_sensor.radar_hanh_lang"]), "WC": _p([], ["light.den_wc"])},
               [{"a": "Khu làm việc", "b": "Hành lang", "ty_le": 0.2}], {},
               {"binary_sensor.cua_vao": {"Hành lang": 150, "(không phòng nào)": 60}},
               {"Phòng họp": _v(300, ("Hành lang báo có người trước", 0.6, 0.02), ("Khu làm việc hết người ngay sau", 0.3, 0.25)),
                "Khu làm việc": _v(700, ("Hành lang báo có người trước", 0.4, 0.03),
                                   ("WC: người vừa tắt thiết bị", 0.05, 0.03))},
               {"WC": {"Hành lang": 210, "Khu làm việc": 12, "(không khu nào — khu bên cạnh có thể đã có người sẵn)": 90}}),
     "dap_an": {"kieu": "van_phong", "cua_vao": "Hành lang",
                "loi_di": [["WC", "Hành lang"], ["Phòng họp", "Hành lang"], ["Khu làm việc", "Hành lang"]],
                "khong_loi_di": [["WC", "Khu làm việc"], ["Phòng họp", "Khu làm việc"]]}},

    {"ten": "chung_cu_wc_rieng_phong_ngu",
     "tinh_huong": "Phòng ngủ master có WC riêng không cảm biến: tắt đèn WC rồi phòng ngủ báo đầu tiên (còn lại "
                   "là «không khu nào» vì phòng ngủ đang có người sẵn) — WC mở vào phòng ngủ.",
     "mo_ta": ["Chung cư 2 phòng ngủ."],
     "uv": _uv({**CAN_HO, "WC phòng ngủ": _p([], ["light.den_wc_ngu"])},
               [{"a": "Phòng khách", "b": "Bếp", "ty_le": 0.5}], {},
               {"binary_sensor.cua_chinh": {"Phòng khách": 80, "(không phòng nào)": 60}},
               {"Phòng ngủ": _v(450, ("Phòng khách báo có người trước", 0.3, 0.04),
                                ("WC phòng ngủ: người vừa tắt thiết bị", 0.12, 0.01))},
               {"WC phòng ngủ": {"Phòng ngủ": 64, "Phòng khách": 3,
                                 "(không khu nào — khu bên cạnh có thể đã có người sẵn)": 140}}),
     "dap_an": {"kieu": "chung_cu", "loi_di": [["WC phòng ngủ", "Phòng ngủ"], ["Phòng ngủ", "Phòng khách"]],
                "khong_loi_di": [["WC phòng ngủ", "Phòng khách"]]}},

    {"ten": "cua_mo_vao_bep",
     "tinh_huong": "Căn hộ cửa chính mở vào lối bếp: mở cửa thì radar bếp báo trước.",
     "mo_ta": ["Chung cư, vào cửa là tới khu bếp rồi mới ra phòng khách."],
     "uv": _uv(CAN_HO, [{"a": "Phòng khách", "b": "Bếp", "ty_le": 0.5}], {},
               {"binary_sensor.cua_chinh": {"Bếp": 110, "Phòng khách": 30, "(không phòng nào)": 70}}),
     "dap_an": {"kieu": "chung_cu", "cua_vao": "Bếp"}},
]


def de_cho(d: dict[str, Any]) -> str:
    from services import so_do_nha
    return so_do_nha.de(d["uv"], d["mo_ta"], [])


def cham_cho(bai: dict[str, Any] | str, dap_an: dict[str, Any]) -> list[str]:
    if isinstance(bai, str):
        return [f"bài bị loại: {bai}"]
    loi: list[str] = []
    phong = {p["ten"]: p for p in bai.get("phong") or []}

    def thong(a: str, b: str) -> bool:
        return b in (phong.get(a) or {}).get("thong_voi", []) or a in (phong.get(b) or {}).get("thong_voi", [])
    if "kieu" in dap_an and bai.get("kieu") != dap_an["kieu"] and not (
            dap_an["kieu"] == "nha_pho" and bai.get("kieu") == "nha_dat"):    # tên cũ của nhà phố vẫn nhận
        loi.append(f"kieu phải là {dap_an['kieu']}, bài: {bai.get('kieu')}")
    if "so_tang" in dap_an and bai.get("so_tang") != dap_an["so_tang"]:
        loi.append(f"so_tang phải là {dap_an['so_tang']}, bài: {bai.get('so_tang')}")
    loi += [f"{a}–{b} phải THÔNG" for a, b in dap_an.get("thong", []) if not thong(a, b)]
    loi += [f"{a}–{b} không được ghi thông" for a, b in dap_an.get("khong_thong", []) if thong(a, b)]
    if "cua_vao" in dap_an and (bai.get("cua_chinh") or {}).get("vao") != dap_an["cua_vao"]:
        loi.append(f"cửa chính phải vào {dap_an['cua_vao']}, bài: {(bai.get('cua_chinh') or {}).get('vao')}")
    cam = {c.get("ten"): (c.get("thay") or {}) for c in bai.get("camera") or []}
    for c, ds in (dap_an.get("camera_thay") or {}).items():
        loi += [f"{c} phải thấy {k}" for k in ds if not cam.get(c, {}).get(k)]
    for c, ds in (dap_an.get("camera_khong_thay") or {}).items():
        loi += [f"{c} không được ghi thấy {k}" for k in ds if cam.get(c, {}).get(k)]
    def di(a: str, b: str) -> bool:
        return thong(a, b) or b in (phong.get(a) or {}).get("cua_sang", []) or a in (phong.get(b) or {}).get(
            "cua_sang", [])
    loi += [f"{a}–{b} phải có lối đi thẳng (thông hoặc cua_sang)" for a, b in dap_an.get("loi_di", []) if not di(a, b)]
    loi += [f"{a}–{b} không được ghi lối đi thẳng" for a, b in dap_an.get("khong_loi_di", []) if di(a, b)]
    if dap_an.get("phai_hoi") and not bai.get("hoi_chu_nha"):
        loi.append("bằng chứng mơ hồ mà không hỏi chủ nhà")
    return loi
