"""Bot tự XÁC MINH trước khi bật/tắt và tự CHẤM sau khi làm — hỏi người dùng ít dần.

Chủ máy 01/10/2026: "Việc xác nhận đúng hay không nên dùng qua các ngoại vi như cảm biến, camera, bếp,
yolo, vision vào những khung giờ lệch sinh hoạt"; "việc bật hay tắt nên giảm dần phụ thuộc vào người dùng
vì có rất nhiều cảm biến, cam để check"; "với nhà tôi thì thế nhưng nhà khác thì chỉ có mỗi cảm biến
chuyển động hoặc hiện diện"; "dạy cho bot phải đúng, đủ các trường hợp".

Đo 14 ngày trước đó (`du_doan_nha`, đèn trần / quạt phòng khách / đèn phòng ngủ — 66 lượt): bot tự tắt
bị bật lại 11/31 lần (vắng 3–9 phút trong khi người ngồi yên, radar mất dấu); bot HỎI 11 lần thì 7 lần
không ai trả lời. Hỏi người không phải đường xác minh dùng được.

Mỗi thiết bị một bài: bot đọc những NGUỒN nhà đó có (camera + YOLO, radar, cảm biến chuyển động, khoảng
cách radar, máy theo người, đọc ảnh) cùng lịch sinh hoạt, rồi chọn nguồn nào xác minh trước khi bật, trước
khi tắt, thêm gì lúc giờ lệch lịch, khi nào mới hỏi người, và nguồn nào tự chấm đúng/sai sau khi làm. Code
chỉ bày đủ dữ kiện và kiểm biên (mã có thật trong đề); chọn gì là việc của bot theo hướng dẫn
`huong_dan_hoc/chon_xac_minh.md`.
"""

from __future__ import annotations

from typing import Any

#: Loại nguồn — tên bày trong đề, cùng điều nó CHỨNG MINH được (bot đọc ở hướng dẫn).
LOAI = {
    "camera": "camera — YOLO đếm người trong vùng của khu",
    "camera_nguoi": "cảm biến người của camera (Frigate)",
    "hien_dien": "cảm biến hiện diện / radar",
    "chuyen_dong": "cảm biến chuyển động",
    "khoang_cach": "khoảng cách người tới radar",
    "mang": "máy theo người (điện thoại, laptop)",
    "anh": "đọc ảnh camera bằng model (chậm)",
}
HOI = ("khong", "khi_khong_ro", "luon")
HUONG = ("bat", "tat")
#: Tối đa ngần này nguồn mỗi danh sách — xác minh bằng cả chục nguồn là chưa chọn.
TOI_DA = 6
#: Bật NGAY rồi KIỂM LẠI (`bat.kiem_lai`) mỗi ngần này giây khi cảm biến khu hay báo ảo — số của chủ máy
#: 01/10/2026: "kiểm tra theo chu kỳ 2p 1 lần nếu gặp tình trạng nhiễu của cảm biến".
KIEM_LAI_GIAY = 120


def de(uv: dict[str, Any], ten_tb: str, dan: list[str]) -> str:
    """Đề cho MỘT thiết bị. ``uv``: tb, khu, loai_tb, nguy_hiem, noi, so_do (dòng), nguon (danh sách
    {ma, ten, loai, khu, ghi_chu}), camera (danh sách {ten, thay, ghi_chu}), lich (dòng), ket_qua (dòng)."""
    dong = [f"A. THIẾT BỊ: {ten_tb} ({uv['tb']}) — {uv.get('loai_tb') or 'thiết bị'} ở khu {uv['khu']}"
            + (f", nơi: {uv['noi']}" if uv.get("noi") else "")
            + (" — NGUY HIỂM nếu bật/tắt nhầm (nhiệt, lửa, nước nóng, khoá)" if uv.get("nguy_hiem") else "")]
    dong += ["\nB. NGUỒN BOT ĐỌC ĐƯỢC (mã | loại | khu | ghi chú):"]
    dong += [f"- {x['ma']} | {LOAI.get(x['loai'], x['loai'])} | {x.get('khu') or '—'} | {x.get('ghi_chu') or '—'}"
             for x in uv.get("nguon") or []] or ["(không có)"]
    dong += ["\nC. CAMERA (tên | thấy khu nào — theo sơ đồ đã chấm | ghi chú):"]
    dong += [f"- {c['ten']} | {', '.join(c.get('thay') or []) or 'không thấy khu nào trong nhà'} | "
             f"{c.get('ghi_chu') or '—'}" for c in uv.get("camera") or []] or ["(không có camera)"]
    dong += ["\nD. LỊCH SINH HOẠT:"] + ([f"- {x}" for x in uv.get("lich") or []] or ["(chưa khai)"])
    dong += ["\nE. KẾT QUẢ GẦN ĐÂY của thiết bị này:"] + ([f"- {x}" for x in uv.get("ket_qua") or []]
                                                       or ["(chưa có)"])
    dong += ["\nF. SƠ ĐỒ NHÀ:"] + ([f"- {x}" for x in uv.get("so_do") or []] or ["(chưa có)"])
    if dan:
        dong += ["\nCHỦ NHÀ DẶN:"] + [f"- {x}" for x in dan]
    return "\n".join(dong)


def _ds(x: Any, co: set[str], ten: str) -> list[str] | str:
    if x is None:
        return []
    if not isinstance(x, list):
        return f"{ten} phải là danh sách mã"
    la = [m for m in x if str(m) not in co]
    if la:
        return f"{ten} có mã không có trong đề: {la!r}"
    if len(x) > TOI_DA:
        return f"{ten} quá {TOI_DA} nguồn"
    return [str(m) for m in x]


def kiem(data: Any, uv: dict[str, Any]) -> dict[str, Any] | str:
    """Loại bài sai khuôn hoặc nhắc mã không có trong đề; đúng/sai về nội dung là việc người chấm."""
    if not isinstance(data, dict):
        return "không phải JSON object"
    co = {str(x["ma"]) for x in uv.get("nguon") or []} | {str(c["ten"]) for c in uv.get("camera") or []}
    ra: dict[str, Any] = {}
    for h in HUONG:
        x = data.get(h)
        if not isinstance(x, dict):
            return f"{h} phải là object"
        if x.get("hoi") not in HOI:
            return f"{h}.hoi phải là một trong {HOI}"
        y: dict[str, Any] = {"hoi": x["hoi"]}
        for k in ("xac_minh", "lech_lich") + (("nha_vang",) if h == "tat" else ("kiem_lai",)):
            v = _ds(x.get(k), co, f"{h}.{k}")
            if isinstance(v, str):
                return v
            y[k] = v
        ra[h] = y
    tc = data.get("tu_cham")
    if not isinstance(tc, dict):
        return "tu_cham phải là object {bat, tat}"
    ra["tu_cham"] = {}
    for h in HUONG:
        v = _ds(tc.get(h), co, f"tu_cham.{h}")
        if isinstance(v, str):
            return v
        ra["tu_cham"][h] = v
    try:
        chac = min(1.0, max(0.0, float(data.get("chac"))))
    except (TypeError, ValueError):
        chac = 0.0
    ra.update(chac=round(chac, 2), vi_sao=str(data.get("vi_sao") or "")[:500])
    return ra
