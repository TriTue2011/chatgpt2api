"""Đọc câu trả lời JSON của AI cho thẻ "Phân tích AI" trên /ui.

Phát sinh 23/09/2026 (thiết kế lại /ui theo bản mẫu Money Manager): thẻ phân
tích có cấu trúc — tóm tắt, đánh giá từng hũ, việc nên làm, tỉ lệ gợi ý kèm nút
"Điền vào bảng phân bổ". Xem
docs/superpowers/specs/2026-09-23-thiet-ke-lai-ui-design.md.

AI qua C2A "auto" route có thể bọc JSON trong rào ```json, kèm chữ thừa, hoặc
bỏ qua yêu cầu và trả markdown — hàm ở đây không bao giờ raise: không đọc được
thì trả None để /ui lùi về markdown -> HTML (app/markdown_an_toan.py). Chuỗi
trả về vẫn là văn bản thô — /ui hiện bằng textContent, không chèn HTML.
"""
from __future__ import annotations

import json
import math

_TOI_DA_TOM_TAT = 600
_TOI_DA_DANH_GIA = 24
_TOI_DA_NHAN_XET = 300
_TOI_DA_VIEC = 200
_SO_VIEC_TOI_DA = 5


def phan_tich_json(van_ban, cac_ma_hu: list[str]) -> dict | None:
    """{"tom_tat", "tung_hu": [{"ma", "danh_gia", "nhan_xet"}], "nen_lam": [str],
    "ty_le_goi_y": {ma: %} | None} hoặc None nếu không có object JSON đọc được
    hoặc thiếu cả tóm tắt lẫn đánh giá từng hũ."""
    du_lieu = _object_json_dau_tien(van_ban)
    if du_lieu is None:
        return None
    tom_tat = _chuoi(du_lieu.get("tom_tat"), _TOI_DA_TOM_TAT)

    tung_hu = []
    da_co: set[str] = set()
    for muc in _danh_sach(du_lieu.get("tung_hu")):
        if not isinstance(muc, dict):
            continue
        ma = muc.get("ma")
        if ma not in cac_ma_hu or ma in da_co:
            continue
        danh_gia = _chuoi(muc.get("danh_gia"), _TOI_DA_DANH_GIA)
        nhan_xet = _chuoi(muc.get("nhan_xet"), _TOI_DA_NHAN_XET)
        if not danh_gia and not nhan_xet:
            continue
        da_co.add(ma)
        tung_hu.append({"ma": ma, "danh_gia": danh_gia, "nhan_xet": nhan_xet})

    if not tom_tat and not tung_hu:
        return None
    nen_lam = [v for v in (_chuoi(x, _TOI_DA_VIEC) for x in _danh_sach(du_lieu.get("nen_lam"))) if v]
    return {
        "tom_tat": tom_tat,
        "tung_hu": tung_hu,
        "nen_lam": nen_lam[:_SO_VIEC_TOI_DA],
        "ty_le_goi_y": _ty_le_hop_le(du_lieu.get("ty_le_goi_y"), cac_ma_hu),
    }


def _object_json_dau_tien(van_ban) -> dict | None:
    """Object JSON bắt đầu ở dấu { đầu tiên; raw_decode bỏ qua chữ thừa phía
    sau (vd rào ``` đóng, lời chúc có ngoặc nhọn)."""
    if not isinstance(van_ban, str):
        return None
    dau = van_ban.find("{")
    if dau < 0:
        return None
    try:
        du_lieu, _ = json.JSONDecoder().raw_decode(van_ban, dau)
    except (ValueError, RecursionError):
        return None
    return du_lieu if isinstance(du_lieu, dict) else None


def _chuoi(gia_tri, toi_da: int) -> str:
    if not isinstance(gia_tri, str):
        return ""
    return " ".join(gia_tri.split())[:toi_da].rstrip()


def _danh_sach(gia_tri) -> list:
    return gia_tri if isinstance(gia_tri, list) else []


def _ty_le_hop_le(ty_le, cac_ma_hu: list[str]) -> dict | None:
    """Chỉ nhận khi đủ ĐÚNG bộ mã hũ, mỗi số 0..100, tổng 100 ± 0,5. Làm tròn
    1 chữ số rồi dồn phần dư vào hũ lớn nhất để tổng đúng 100,0 — /ui chỉ cho
    lưu cấu hình khi tổng đúng 100."""
    if not isinstance(ty_le, dict) or set(ty_le) != set(cac_ma_hu) or not cac_ma_hu:
        return None
    ket_qua: dict[str, float] = {}
    for ma in cac_ma_hu:
        so = ty_le[ma]
        if isinstance(so, bool) or not isinstance(so, (int, float)):
            return None
        if not math.isfinite(so) or not 0 <= so <= 100:
            return None
        ket_qua[ma] = round(float(so), 1)
    if abs(sum(ket_qua.values()) - 100) > 0.5:
        return None
    du = round(100 - sum(ket_qua.values()), 1)
    if du:
        lon_nhat = max(cac_ma_hu, key=lambda ma: ket_qua[ma])
        ket_qua[lon_nhat] = round(ket_qua[lon_nhat] + du, 1)
        if not 0 <= ket_qua[lon_nhat] <= 100:
            return None
    return ket_qua
