"""Bộ đề LUYỆN cho `chuyen_truong_hop.md` — bot chuyển TRƯỜNG HỢP chủ nhà duyệt thành LUẬT chạy được.

Chủ máy 05/10/2026: "quạt, bình nóng lạnh, đèn trần, đèn tủ lạnh, đèn cửa sổ, đèn ban công, đèn phòng học … rút ra
cái chung để train, hướng dẫn áp dụng cho cả nhà khác" — "Tạo nhà giả". Nên NHÀ GIẢ hai kiểu: chung cư có radar +
camera (dáng nhà chủ máy, đổi tên) và nhà phố chỉ cảm biến chuyển động + cửa. Mỗi đề MỘT loại thiết bị + các bẫy rút
từ lỗi đo được 04/10/2026: luật chỉ nghe cửa (72 lần vào phòng bị nuốt), quạt bật lúc đi ngang (5/9 lần bật rồi tắt
ngay), radar 0 bị hiểu là «gần», hai cảm biến cùng tín hiệu bị bắt khác nhau (luật chết), dựa vào cảm biến nhiễu.

Đề dùng đúng khuôn của nhà thật (`luat_duyet.de_tu`), kiểm biên đúng như thật (`luat_duyet.kiem`).

Đáp án (khoá tuỳ chọn):
  nen: {so: [giá trị]}          luật của trường hợp `so` phải có nen trong danh sách ("khong_chuyen" = để ngoài)
  khi_co: {so: [chuỗi]}         một `khi` của luật `so` chứa một trong các chuỗi
  bat_nghe_mot: [chuỗi]         ít nhất một luật nen=bat có `khi` chứa một trong các chuỗi
  tham_chieu: {so: [mã]}        luật `so` nhắc tới một trong các mã (ở khi hoặc nếu)
  xac_minh: [so]                luật `so` phải xac_minh=true
  khong_nen: [giá trị]          không luật nào có nen này
  khong_tren: [mã]              không điều kiện «tren» trên mã này (radar 0 = không ai)
  khong_nguoc: [[a, b]]         không luật nào đòi a=on mà b không on (a, b cùng một tín hiệu)
  nhieu_kem: {mã_nhiễu: [mã_lành]}  luật nhắc mã nhiễu phải xac_minh hoặc kèm một mã lành
"""

from __future__ import annotations

from typing import Any

TANG = "services.de_luyen.chuyen_truong_hop"


def _cb(ma: str, ten: str, khu: str, loai: str, don_vi: str = "") -> dict[str, str]:
    return {"ma": ma, "ten": ten, "khu": khu, "loai": loai, "don_vi": don_vi}


def _th(chieu: str, tinh_huong: str, nen: str) -> dict[str, str]:
    return {"chieu": chieu, "tinh_huong": tinh_huong, "nen": nen}


# ── Nhà A: chung cư, bếp mở liền phòng khách, radar + camera mỗi khu ─────────────────────────────────
RK, KK, CK = "binary_sensor.radar_khach", "sensor.radar_khach_khoang_cach", "binary_sensor.cam_khach_nguoi"
CK2 = "binary_sensor.cam_khach_moi_vat"                       # cùng camera — gần như cùng tín hiệu với CK
RB, CB = "binary_sensor.radar_bep", "binary_sensor.cam_bep_nguoi"
RN, RH, KH = "binary_sensor.radar_ngu", "binary_sensor.radar_hoc", "sensor.radar_hoc_khoang_cach"
RBC, CBC = "binary_sensor.radar_ban_cong", "binary_sensor.cam_ban_cong_nguoi"
CUA, TV = "binary_sensor.cua_chinh", "binary_sensor.c2a_tivi_khach"
LUX_K, LUX_BC = "sensor.do_sang_khach", "sensor.do_sang_ban_cong"
NHIET = "sensor.nhiet_do_khach"

CB_A = [
    _cb(RK, "Radar phòng khách", "Phòng khách", "có người (presence)"),
    _cb(KK, "Radar phòng khách khoảng cách", "Phòng khách", "khoảng cách", "m"),
    _cb(CK, "Camera phòng khách thấy người", "Phòng khách", "camera thấy người"),
    _cb(CK2, "Camera phòng khách thấy vật", "Phòng khách", "camera thấy người"),
    _cb(RB, "Radar bếp", "Bếp", "có người (presence)"),
    _cb(CB, "Camera bếp thấy người", "Bếp", "camera thấy người"),
    _cb(RN, "Radar phòng ngủ", "Phòng ngủ", "có người (occupancy)"),
    _cb(RH, "Radar phòng học", "Phòng học", "có người (occupancy)"),
    _cb(KH, "Radar phòng học khoảng cách", "Phòng học", "khoảng cách", "m"),
    _cb(RBC, "Radar ban công", "Ban công", "có người (occupancy)"),
    _cb(CBC, "Camera ban công thấy người", "Ban công", "camera thấy người"),
    _cb(CUA, "Cửa chính", "Phòng khách", "cửa (on = mở)"),
    _cb(TV, "Tivi phòng khách đang bật", "Phòng khách", "GHÉP do bot tính — Tivi đang bật"),
    _cb(LUX_K, "Độ sáng phòng khách", "Phòng khách", "độ sáng", "lx"),
    _cb(LUX_BC, "Độ sáng ban công", "Ban công", "độ sáng", "lx"),
    _cb(NHIET, "Nhiệt độ phòng khách", "Phòng khách", "nhiệt độ", "°C"),
]
LICH_A = [{"ma": "ngu", "ten": "Cả nhà ngủ", "loai": "ngu", "tu": "22:00", "den": "06:00"},
          {"ma": "vang", "ten": "Đi làm, đi học", "loai": "vang", "tu": "07:30", "den": "16:30"}]
VUNG_A = [(KK, "duoi", 3.5, RK), (KH, "duoi", 2.5, RH)]

# ── Nhà B: nhà phố hai tầng, CHỈ cảm biến chuyển động (PIR) + cửa, không camera, không radar ────────────
PIR_K, PIR_CT, CUA_B = "binary_sensor.pir_phong_khach", "binary_sensor.pir_cau_thang", "binary_sensor.cua_truoc"
LUX_B = "sensor.lux_phong_khach"
CB_B = [
    _cb(PIR_K, "Chuyển động phòng khách", "Phòng khách", "có người (motion)"),
    _cb(PIR_CT, "Chuyển động cầu thang", "Cầu thang", "có người (motion)"),
    _cb(CUA_B, "Cửa trước", "Phòng khách", "cửa (on = mở)"),
    _cb(LUX_B, "Độ sáng phòng khách", "Phòng khách", "độ sáng", "lx"),
]


def _de(ten: str, tb: str, ten_tb: str, th: list[dict], dap_an: dict, *, nha: str = "A",
        trung: list | None = None, do_tin: list | None = None) -> dict[str, Any]:
    cb, lich, vung = (CB_A, LICH_A, VUNG_A) if nha == "A" else (CB_B, [], [])
    return {"ten": ten, "tb": tb, "ten_tb": ten_tb, "th": th, "cb": cb, "lich": lich, "vung": vung,
            "trung": trung or [], "do_tin": do_tin or [], "dap_an": dap_an,
            "uv": {"n": len(th), "ma_co": {c["ma"] for c in cb} | {tb}, "lich": {x["ma"] for x in lich}}}


DE: list[dict[str, Any]] = [
    # Thiết bị TIỆN NGHI: bật khi người Ở LẠI, không bật lúc vừa mở cửa / đi ngang.
    _de("quat_o_lai", "fan.quat_khach", "Quạt phòng khách", [
        _th("bat", "Người ngồi xem tivi ở phòng khách hơn 15 giây, trời nóng.", "bat"),
        _th("bat", "Người mở cửa chính rồi đi thẳng vào bếp, không ngồi lại phòng khách.", "khong_lam"),
        _th("tat", "Phòng khách vắng hơn 5 phút, mọi cảm biến không thấy ai.", "tat")],
        {"nen": {1: ["bat"], 2: ["khong_lam", "khong_chuyen"], 3: ["tat"]}, "khi_co": {1: [" ở lại 15 giây"]}}),
    # Thiết bị NGUY HIỂM: không bao giờ tự bật/tắt dù trường hợp ghi «nên bật».
    _de("binh_nong_lanh", "switch.binh_nong_lanh", "Bình nóng lạnh", [
        _th("bat", "Chiều khoảng 17 giờ, người về nhà, trời mát — thường bật bình để tắm.", "bat"),
        _th("tat", "Bình đã bật hơn 30 phút.", "tat")],
        {"khong_nen": ["bat", "tat"]}),
    # Đèn CHÍNH: phục vụ MỌI đường vào khu, không chỉ cửa chính.
    _de("den_tran_moi_duong_vao", "light.den_tran_khach", "Đèn trần phòng khách", [
        _th("bat", "Trời tối, người mở cửa chính bước vào phòng khách.", "bat"),
        _th("bat", "Trời tối, người từ phòng ngủ đi ra phòng khách (không qua cửa chính).", "bat"),
        _th("tat", "Phòng khách vắng 3 phút, radar, khoảng cách và camera cùng không thấy ai.", "tat")],
        {"nen": {1: ["bat"], 2: ["bat"], 3: ["tat"]}, "bat_nghe_mot": [RK, CK],
         "tham_chieu": {2: [RK, CK, KK]}, "khong_tren": [KK]}),
    # Đèn PHỤ gắn hoạt động: theo khu bếp, không theo cả phòng khách.
    _de("den_tu_lanh", "light.den_tu_lanh", "Đèn cạnh tủ lạnh (góc bếp)", [
        _th("bat", "Trời tối, có người đứng ở khu bếp mở tủ lạnh.", "bat"),
        _th("bat", "Trời tối, người ngồi ở phòng khách xem tivi, không ai ở bếp.", "khong_lam")],
        {"nen": {1: ["bat"], 2: ["khong_lam", "khong_chuyen"]}, "tham_chieu": {1: [RB, CB]}}),
    # Đèn PHỤ gắn hoạt động: theo tivi.
    _de("den_cua_so_tivi", "light.den_cua_so", "Đèn cửa sổ phòng khách", [
        _th("bat", "Buổi tối tivi phòng khách bật.", "bat"),
        _th("tat", "Tivi tắt hơn 3 phút.", "tat")],
        {"nen": {1: ["bat"], 2: ["tat"]}, "tham_chieu": {1: [TV], 2: [TV]}}),
    # Đèn NGOÀI TRỜI: cảm biến ngoài trời hay báo ảo → nhìn lại camera.
    _de("den_ban_cong", "light.den_ban_cong", "Đèn ban công", [
        _th("bat", "Trời tối, người ra ban công phơi đồ.", "bat"),
        _th("bat", "Một con mèo đi qua ban công, radar báo có người nhưng camera không thấy người.", "khong_lam")],
        {"nen": {1: ["bat"], 2: ["khong_lam", "khong_chuyen"]}, "xac_minh": [1]}),
    # Đèn BÀN HỌC: người ngồi yên lâu — đừng tắt khi radar mất dấu; tắt theo VẮNG, không theo «khoảng cách trên».
    _de("den_phong_hoc", "light.den_phong_hoc", "Đèn phòng học", [
        _th("bat", "Trời tối, người vào phòng học ngồi học.", "bat"),
        _th("tat", "Người ngồi học yên 40 phút, radar có lúc mất dấu.", "giu"),
        _th("tat", "Phòng học vắng hơn 30 giây.", "tat")],
        {"nen": {1: ["bat"], 2: ["giu", "khong_chuyen"], 3: ["tat"]}, "khi_co": {3: [" vắng 30 giây"]},
         "khong_tren": [KH]}),
    # BẪY: cặp cảm biến cùng tín hiệu + cảm biến nhiễu.
    _de("nhieu_va_trung", "fan.quat_khach", "Quạt phòng khách", [
        _th("bat", "Người ngồi lại phòng khách quá 3 phút.", "bat"),
        _th("tat", "Phòng khách vắng hơn 5 phút.", "tat")],
        {"nen": {1: ["bat"], 2: ["tat"]}, "khong_nguoc": [[CK, CK2], [CK2, CK]], "nhieu_kem": {RK: [KK, CK, CK2]}},
        trung=[(CK, CK2, 1.0)], do_tin=[(RK, "NHIỄU (880 lần/ngày, 42% dưới 10s)")]),
    # Nhà CHỈ cảm biến chuyển động: dùng thứ có, không bịa camera / radar.
    _de("nha_pho_pir", "light.den_khach_b", "Đèn trần phòng khách", [
        _th("bat", "Trời tối, người vào phòng khách (từ cửa trước hoặc từ cầu thang xuống).", "bat"),
        _th("tat", "Phòng khách không có chuyển động hơn 10 phút.", "tat")],
        {"nen": {1: ["bat"], 2: ["tat"]}, "bat_nghe_mot": [PIR_K], "khi_co": {2: [" vắng"]}}, nha="B"),
    # Radar 0: «người rời khu» là sự kiện VẮNG, không phải «khoảng cách trên X».
    _de("radar_khong", "light.den_tran_khach", "Đèn trần phòng khách", [
        _th("tat", "Người rời phòng khách, không còn ai trong vùng radar.", "tat")],
        {"nen": {1: ["tat"]}, "khong_tren": [KK], "khi_co": {1: [" vắng"]}}),
]


# ── Hook cho `de_luyen.luyen` ────────────────────────────────────────────────
def de_cho(d: dict[str, Any]) -> str:
    from services import luat_duyet
    return luat_duyet.de_tu(d["tb"], d["ten_tb"], d["th"], d["cb"], vung=d["vung"], trung=d["trung"],
                            do_tin=d["do_tin"], lich=d["lich"])


def kiem(b: Any, uv: dict[str, Any]) -> dict[str, Any] | str:
    from services import luat_duyet
    luat, khong, loi = luat_duyet.kiem(b, uv["n"], uv["ma_co"], uv["lich"])
    return {"luat": luat, "khong": khong, "loi": loi, "vi_sao": "; ".join(l.get("vi_sao", "") for l in luat)[:400]}


def _ma_cua(l: dict[str, Any]) -> set[str]:
    return {k.split(" ")[0] for k in l["khi"]} | {str(x["ma"]) for x in l["neu"]}


def cham_cho(k: dict[str, Any] | str, dap_an: dict[str, Any]) -> list[str]:
    if isinstance(k, str):
        return [f"bài bị loại: {k}"]
    loi: list[str] = [f"kiểm biên: {e}" for e in k["loi"]]
    theo_so = {l["so"]: l for l in k["luat"]}
    ngoai = {x["so"] for x in k["khong"]}
    for so, cho in (dap_an.get("nen") or {}).items():
        if so in ngoai:
            if "khong_chuyen" not in cho:
                loi.append(f"trường hợp {so} bị để ngoài, phải có luật nen {cho}")
        elif so in theo_so and theo_so[so]["nen"] not in cho:
            loi.append(f"trường hợp {so}: nen {theo_so[so]['nen']!r}, phải là một trong {cho}")
    for so, chuoi in (dap_an.get("khi_co") or {}).items():
        l = theo_so.get(so)
        if l and not any(c in k_ for k_ in l["khi"] for c in chuoi):
            loi.append(f"trường hợp {so}: «khi» {l['khi']} phải có {chuoi}")
    bn = dap_an.get("bat_nghe_mot")
    if bn and not any(l["nen"] == "bat" and any(c in k_ for k_ in l["khi"] for c in bn) for l in k["luat"]):
        loi.append(f"không luật BẬT nào nghe {bn} — người vào khu không qua cửa sẽ không được phục vụ")
    for so, ma in (dap_an.get("tham_chieu") or {}).items():
        l = theo_so.get(so)
        if l and not _ma_cua(l) & set(ma):
            loi.append(f"trường hợp {so}: phải dựa vào một trong {ma}, bài dùng {sorted(_ma_cua(l))}")
    for so in dap_an.get("xac_minh") or []:
        l = theo_so.get(so)
        if l and not l["xac_minh"]:
            loi.append(f"trường hợp {so}: phải xac_minh=true (cảm biến ngoài trời hay báo ảo)")
    for l in k["luat"]:
        if l["nen"] in (dap_an.get("khong_nen") or []):
            loi.append(f"trường hợp {l['so']}: thiết bị nguy hiểm không được nen {l['nen']!r}")
        for x in l["neu"]:
            if "tren" in x and x["ma"] in (dap_an.get("khong_tren") or []):
                loi.append(f"trường hợp {l['so']}: «{x['ma']} trên {x['tren']}» — radar 0 là không ai; dùng sự kiện vắng")
        dk = {str(x["ma"]): x for x in l["neu"]}
        for a, b in dap_an.get("khong_nguoc") or []:
            xa, xb = dk.get(a), dk.get(b)
            if xa and xb and not xa.get("phu_dinh") and xa.get("la") == "on" and (
                    xb.get("phu_dinh") or xb.get("la") == "off"):
                loi.append(f"trường hợp {l['so']}: đòi {a}=on mà {b} không on — hai mã cùng tín hiệu, luật chết")
        for nh, lanh in (dap_an.get("nhieu_kem") or {}).items():
            if nh in _ma_cua(l) and not l["xac_minh"] and not _ma_cua(l) & set(lanh):
                loi.append(f"trường hợp {l['so']}: dựa vào cảm biến NHIỄU {nh} mà không xac_minh / không kèm cảm biến lành")
    return loi
