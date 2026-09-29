"""Bộ đề LUYỆN cho `hieu_so_do_nha.md` — nhiều kiểu nhà, không riêng nhà nào (chủ máy 29/09/2026:
"train cho bot các kiến thức về kiến trúc, nội thất, xây dựng").

Đáp án (mọi khoá tuỳ chọn): ``kieu``; ``so_tang``; ``thong``: [[A, B]] phải thông; ``khong_thong``:
[[A, B]] không được ghi thông; ``cua_vao``; ``camera_thay``: {camera: [phòng phải có]};
``camera_khong_thay``: {camera: [phòng không được có]}; ``phai_hoi``: True (còn điều chưa chắc).
"""

from __future__ import annotations

from typing import Any

TANG = "services.so_do_nha"


def _p(hien: list[str], tb: list[str] | None = None) -> dict[str, list[str]]:
    return {"hien_dien": hien, "thiet_bi": tb or []}


def _uv(phong: dict, cung_bao: list, camera: dict, cua: dict) -> dict[str, Any]:
    ten = {m: m.split(".")[1].replace("_", " ") for p in phong.values() for m in p["hien_dien"] + p["thiet_bi"]}
    ten.update({m: m.split(".")[1].replace("_", " ") for m in cua})
    return {"phong": phong, "khu_radar": sorted(phong), "ket": [], "cung_bao": cung_bao, "camera": camera,
            "loi_camera": "", "cua": cua, "ten": ten}


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
     "dap_an": {"kieu": "nha_dat", "so_tang": 3, "thong": [["Phòng khách", "Bếp"]],
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
    if "kieu" in dap_an and bai.get("kieu") != dap_an["kieu"]:
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
    if dap_an.get("phai_hoi") and not bai.get("hoi_chu_nha"):
        loi.append("bằng chứng mơ hồ mà không hỏi chủ nhà")
    return loi
