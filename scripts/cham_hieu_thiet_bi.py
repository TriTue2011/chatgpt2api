#!/usr/bin/env python3
"""Claude CHẤM bài của bot học hỏi — tầng hiểu thiết bị.

Vì sao có tệp này: chủ máy chốt 11/09/2026, Claude là giáo viên — "tạo hướng
dẫn để bot của tôi giải bài toán, sau đó xem lại giải đúng không", và "sau khi
chấm xong phải cải thiện hướng dẫn". Tệp này là phần XEM LẠI: đo lại đề bằng
luật của giáo viên, so với kết luận bot đang dùng, in từng chỗ lệch kèm số liệu
để giáo viên sửa HƯỚNG DẪN — không sửa code, không sửa kết luận hộ bot.

Luật của giáo viên chỉ chấm khi CHẮC. Ca lưng chừng in "chưa chấm": chấm bừa
là làm hỏng thang lên cấp của chính bot.

Chạy trong container (đọc đúng kho, ghi điểm đúng chỗ):
    docker exec c2a /app/.venv/bin/python /app/scripts/cham_hieu_thiet_bi.py
    docker exec c2a /app/.venv/bin/python /app/scripts/cham_hieu_thiet_bi.py --ghi --bao

Chấm thử một bài chưa lưu (đề đo trên bản sao kho, bài là JSON model trả):
    uv run python scripts/cham_hieu_thiet_bi.py --de de.json --bai bai.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: Cả hai chiều trùng từ ngần này: chắc là MỘT thiết bị. Cặp thật đo 11/09/2026
#: trùng 88–100%, cặp kế tiếp chỉ 9,5% — khoảng trống rộng, nên ngưỡng chấm đặt
#: xa cả hai phía.
_CHAC_TRUNG = 0.8
#: Cả hai chiều trùng không quá ngần này: chắc là HAI thứ.
_CHAC_KHAC = 0.2
#: Đổi trước từ ngần này số lần trùng: chắc là mã dẫn.
_CHAC_TRUOC = 0.8
#: Trung vị số mã khác đổi cùng giây từ ngần này: chắc là hệ thống đổi. Đo
#: 11/09/2026: công tắc cấu hình Frigate 25–29, đèn thật 1–2.
_DONG_LOAT = 10


def _quan_he(ho: dict[str, dict[str, Any]], a: str, b: str) -> tuple | None:
    """(trùng a→b, trùng b→a, phần a đổi trước) theo đề; None = đề không nói.

    Đề chỉ kể tối đa 5 mã trùng từ 10%. Nên mã không được kể mà danh sách của
    CẢ HAI bên còn dưới 5 mã nghĩa là trùng dưới 10% — chắc là khác.
    """
    for x in ho[a]["doi_cung_luc"]:
        if x["ma"] == b:
            return x["ty_le_minh"], x["ty_le_ban"], x["minh_doi_truoc"]
    for x in ho[b]["doi_cung_luc"]:
        if x["ma"] == a:
            return x["ty_le_ban"], x["ty_le_minh"], round(1 - x["minh_doi_truoc"], 3)
    if len(ho[a]["doi_cung_luc"]) < 5 and len(ho[b]["doi_cung_luc"]) < 5:
        return 0.0, 0.0, None
    return None


def _cham_cung_thiet_bi(ma: list[str], ho: dict) -> tuple[bool | None, str]:
    for i, a in enumerate(ma):
        for b in ma[i + 1:]:
            q = _quan_he(ho, a, b)
            if q is None:
                return None, f"đề không kể quan hệ {a} – {b}"
            if max(q[0], q[1]) <= _CHAC_KHAC:
                return False, f"{a} và {b} chỉ trùng {q[0]:.0%}/{q[1]:.0%} — hai thứ khác nhau"
            if min(q[0], q[1]) < _CHAC_TRUNG:
                return None, f"{a} – {b} trùng {q[0]:.0%}/{q[1]:.0%}, lưng chừng"
    for a in ma:
        for x in ho[a]["doi_cung_luc"]:
            if x["ma"] not in ma and min(x["ty_le_minh"], x["ty_le_ban"]) >= _CHAC_TRUNG:
                return False, (f"thiếu {x['ma']}: trùng với {a} "
                               f"{x['ty_le_minh']:.0%}/{x['ty_le_ban']:.0%}")
    return True, "mọi cặp trùng từ 80% cả hai chiều, không sót mã nào"


def _cham_nguon_nhanh(nhanh: str, ma: list[str], ho: dict) -> tuple[bool | None, str]:
    chua_ro = []
    for m in ma:
        if m == nhanh:
            continue
        q = _quan_he(ho, nhanh, m)
        if q is None or q[2] is None:
            chua_ro.append(m)
            continue
        if q[2] <= 1 - _CHAC_TRUOC:
            return False, f"{m} đổi trước {nhanh} {1 - q[2]:.0%} số lần"
        if q[2] < _CHAC_TRUOC:
            chua_ro.append(m)
    if chua_ro:
        return None, "chưa đủ số liệu thứ tự với " + ", ".join(chua_ro)
    return True, f"{nhanh} đổi trước mọi mã còn lại từ 80% số lần"


def _cham_hoc(khoa: str, gt: dict, ho: dict) -> tuple[bool | None, str]:
    p = ho[khoa]
    tv = p["so_ma_khac_doi_cung_luc"]["trung_vi"]
    if tv >= _DONG_LOAT:
        return (not gt["hoc"]), (f"mỗi lần đổi có trung vị {tv} mã khác đổi cùng giây"
                                 " — hệ thống đổi, không phải người bật")
    if not gt["hoc"]:
        if p["so_lan_bat"] < 3:
            return True, f"chỉ {p['so_lan_bat']} lần bật"
        return None, "không học một thứ bật tắt được — giáo viên chưa có luật chắc, cần người xem"
    if p["so_lan_bat"] < 3:
        return False, f"chỉ {p['so_lan_bat']} lần bật mà vẫn học"
    for x in p["doi_cung_luc"]:
        khac = ho.get(x["ma"])
        if not (khac and khac["ha_bat_duoc"]
                and min(x["ty_le_minh"], x["ty_le_ban"]) >= _CHAC_TRUNG):
            continue
        if x["minh_doi_truoc"] <= 1 - _CHAC_TRUOC:
            return False, (f"{x['ma']} cùng thiết bị mà đổi trước "
                           f"{1 - x['minh_doi_truoc']:.0%} số lần — nên học mã đó")
        if x["minh_doi_truoc"] < _CHAC_TRUOC:
            return None, f"chưa rõ {x['ma']} hay {khoa} đổi trước"
    if p["so_lan_doi"] < 10:
        return None, f"ít dữ liệu ({p['so_lan_doi']} lần đổi)"
    return True, f"{p['so_lan_bat']} lần bật, đổi riêng lẻ (trung vị {tv} mã kèm), là mã dẫn"


def cham_mot(d: dict[str, Any], ho: dict[str, dict[str, Any]]) -> tuple[bool | None, str]:
    """Chấm một kết luận theo luật giáo viên. (đúng/sai/None = chưa chấm, vì sao)."""
    gt, g = d["gia_tri"], d["nhom"]
    if any(m not in ho for m in g["ma"]) or d["khoa"].split("|")[0] not in ho:
        return None, "đề hôm nay không còn đủ mã của nhóm này"
    if d["loai_cau_hoi"] == "cung_thiet_bi":
        return _cham_cung_thiet_bi(gt["ma"], ho)
    if d["loai_cau_hoi"] == "nguon_nhanh":
        return _cham_nguon_nhanh(gt["nguon_nhanh"], g["ma"], ho)
    return _cham_hoc(d["khoa"], gt, ho)


def _doc_tu_kho() -> tuple[list[dict], dict[str, dict], str]:
    from services import hieu_thiet_bi_nha as ht

    ho = {x["ma"]: x for x in ht.ho_so().get("thiet_bi") or []}
    return ht.dang_hieu_luc(), ho, ht.huong_dan()[1]


def _doc_tu_tep(duong_de: str, duong_bai: str) -> tuple[list[dict], dict[str, dict], str]:
    from services import hieu_thiet_bi_nha as ht

    with open(duong_de, encoding="utf-8") as f:
        de = json.load(f)
    with open(duong_bai, encoding="utf-8") as f:
        bai = json.load(f)
    nhom, loai_bo = ht._kiem(bai, de["thiet_bi"])
    bo_sot = {x["ma"] for x in de["thiet_bi"]} - {m for g in nhom for m in g["ma"]}
    print(f"Bài có {len(nhom)} nhóm hợp lệ, {loai_bo} nhóm phạm luật bị loại, "
          f"bỏ sót {len(bo_sot)} mã: {sorted(bo_sot)}")
    ds = []
    for g in nhom:
        for loai, khoa, gt in ht._cau_hoi(g):
            ds.append({"id": len(ds) + 1, "loai_cau_hoi": loai, "khoa": khoa,
                       "gia_tri": gt, "nhom": g, "ket_qua": "cho", "cham_boi": ""})
    return ds, {x["ma"]: x for x in de["thiet_bi"]}, "(tệp)"


def main(argv: list[str]) -> int:
    from services import hieu_thiet_bi_nha as ht

    tu_tep = "--de" in argv
    ghi, bao = "--ghi" in argv, "--bao" in argv
    if tu_tep and (ghi or bao):
        print("Chấm từ tệp là chấm thử — không ghi điểm, không báo nhóm.")
        return 2
    if tu_tep:
        ds, ho, ban = _doc_tu_tep(argv[argv.index("--de") + 1], argv[argv.index("--bai") + 1])
    else:
        ds, ho, ban = _doc_tu_kho()
    ten = {m: p["ten"] for m, p in ho.items() if p.get("ten")}
    dem = {True: 0, False: 0, None: 0}
    sai: list[tuple[dict, str]] = []
    for d in ds:
        if d.get("cham_boi") == "lap_lai":
            continue
        ket, vi_sao = cham_mot(d, ho)
        dem[ket] += 1
        nhan = {True: "ĐÚNG", False: "SAI ", None: "—   "}[ket]
        print(f"{nhan} #{d['id']} [{d['loai_cau_hoi']}] {ht._cau_doc(d, ten)}"
              f"\n       bot: {d['nhom'].get('vi_sao', '')}\n       giáo viên: {vi_sao}")
        if ket is False:
            sai.append((d, vi_sao))
        if ghi and ket is not None and d.get("ket_qua") == "cho":
            ht.cham(int(d["id"]), ket, cham_boi="claude", ghi_chu=vi_sao)
    print(f"\nHướng dẫn bản {ban}: đúng {dem[True]}, sai {dem[False]}, chưa chấm {dem[None]}")
    if bao:
        dong = [f"🧑‍🏫 Claude chấm bài hiểu thiết bị (hướng dẫn bản {ban}): "
                f"đúng {dem[True]}, sai {dem[False]}, chưa đủ chắc để chấm {dem[None]}."]
        if sai:
            dong.append("Bot sai ở:")
            dong += [f"• #{d['id']} {ht._cau_doc(d, ten)} — {vs}" for d, vs in sai[:15]]
        ht.bao_nhom("\n".join(dong).replace("_", " "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
