"""Tầng THÓI QUEN — thiết bị được học đi theo NGOẠI VI nào.

Chủ máy chốt 13/09/2026, nguyên văn:

    "Phần học thói quen mới chỉ đang xét đến các ngoại vi, nhưng chưa phân loại
    rõ ràng ngoại vi nào sẽ ảnh hưởng đến thói quen, chưa có hướng dẫn chi tiết.
    Ví dụ bật đèn A, thì đèn ở khu vực nào thì ngoại vi đi theo khu vực đó,
    không nên nhặt bừa. [...] hướng dẫn ngắn gọn và xúc tích, tránh dài để bot
    nghĩ nhiều, quá dung lượng làm cắt bớt thông tin"

    "Ảnh chụp không phải cái để học, cảm biến hiện diện, cảm biến đếm người mới
    là cái cần."

    "Bạn là giáo viên hướng dẫn, bot tôi là học sinh làm bài chứ không phải bạn"

Số đo làm đề (kho thật 13/09/2026) — vì sao tầng này tồn tại, KHÔNG để code dùng:

* Điều kiện cũ gom theo KHOÁ PHÒNG bằng khớp chuỗi tên: `nguoi_phòng_khách` gom
  14 mã có chữ motion/person/occupancy/presence — cả công tắc bật tính năng phát
  hiện của Frigate, số ngưỡng `motion_threshold`, ảnh `image.*`. 7 ngày: 23/194
  ô 30 phút (12%) do những giá trị luôn đọc là "có người" quyết.
* "Đèn ban công" nằm trên công tắc bếp nên HA xếp khu Bếp, và bot chọn ánh sáng
  bếp, người ở bếp làm điều kiện cho nó.
* 10 thiết bị được học; mỗi khu vực 18–66 ngoại vi riêng lẻ, khu "chưa xếp" 458.

Ai làm gì:

* CODE chỉ bày số đo: mọi khu vực trong sổ HA kèm ngoại vi của nó, rồi ngoại vi
  TỪNG MÃ MỘT của những khu bot chọn. Code không quyết khu nào liên quan, không
  bỏ mã nào vì "vô ích" — mã chỉ có một giá trị vẫn được bày, ghi rõ để bot tự
  loại theo hướng dẫn.
* BOT làm hai bước theo bản hướng dẫn ngắn `huong_dan_hoc/chon_ngoai_vi.md`:
  chọn khu vực, rồi chọn ngoại vi. Mỗi bước một lượt gọi để đề ngắn.
* NGƯỜI CHẤM: kết luận lưu chung sổ `hieu_thiet_bi_nha` (câu `ngoai_vi`), chấm
  «hh N» như mọi câu khác.

Kiểm ở biên duy nhất ngoài "mã có thật trong đề": mã HA không còn trong
`ha_client.get_states()` thì không bày — hàm đó ẩn thực thể mang mật khẩu camera
trong tên, mà mã sinh từ tên nên cũng mang mật khẩu.
"""

from __future__ import annotations

import bisect
import json
import sqlite3
import threading
import time
from typing import Any

from utils.log import logger

#: Ngoại vi đổi trong ngần này giây quanh một lần bật/tắt thì tính là "đổi quanh
#: lúc bật/tắt" — số đo phụ bày cho bot, không phải điều kiện.
_QUANH_GIAY = 600

_TOI_DA_NGOAI_VI = 5
_TOI_DA_KHU_XEM = 3

#: Ngoại vi không có khu trong sổ HA và tên không chứa tên khu nào.
CHUA_XEP = "Chưa xếp khu vực"

#: Bước 1 kể ngần này tên ngoại vi tiêu biểu mỗi khu (đổi nhiều nhất trước), để
#: bot nhận ra khu mà đề không phải dài bằng cả danh sách.
_TIEU_BIEU = 6

_dang_chay = threading.Lock()


def _ma(thiet_bi: str, truong: str) -> str:
    """Cùng quy ước mã với `hieu_thiet_bi_nha._ma`: trường `state` không ghi."""
    return thiet_bi if truong == "state" else f"{thiet_bi}#{truong}"


def _la_ma_ha(thiet_bi: str) -> bool:
    mien, cham, ten = thiet_bi.partition(".")
    return bool(cham) and "/" not in thiet_bi and mien.isidentifier() and bool(ten)


def _doc_kho(tu: float, den: float) -> dict[str, Any]:
    """Một lượt đọc chung cho mọi thiết bị, bằng kết nối CHỈ-ĐỌC riêng.

    Không đi qua `lich_su_nha._khoa_db`: gom 30 ngày mất vài giây, trong khi
    lượt chat của bot đọc bối cảnh qua cùng khoá đó.
    """
    from services import lich_su_nha

    ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    try:
        trang_thai = {(r[0], r[1]): {"n": int(r[2]), "so_gt": int(r[3])} for r in ro.execute(
            "SELECT thiet_bi, truong, COUNT(*), COUNT(DISTINCT gia_tri) FROM su_kien"
            " WHERE ts>=? AND ts<? AND do_ai=0 GROUP BY thiet_bi, truong", (tu, den))}
        so_do = {(r[0], r[1]): {"nho": r[2], "tb": r[3], "lon": r[4], "n": int(r[5])}
                 for r in ro.execute(
            "SELECT thiet_bi, truong, MIN(nho), AVG(tb), MAX(lon), COUNT(*) FROM so_do"
            " WHERE o_5p>=? AND o_5p<? GROUP BY thiet_bi, truong",
            (int(tu // 300), int(den // 300) + 1))}
    finally:
        ro.close()
    return {"tu": tu, "den": den, "trang_thai": trang_thai, "so_do": so_do}


def _chi_tiet(tu: float, den: float, cap: list[tuple[str, str]]) -> dict[tuple[str, str], Any]:
    """Các lần đổi của những mã được bày — theo chỉ mục `(thiet_bi, truong, ts)`."""
    from services import lich_su_nha

    ra: dict[tuple[str, str], Any] = {}
    ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    try:
        for tb, tr in cap:
            dong = ro.execute(
                "SELECT ts, gia_tri FROM su_kien WHERE thiet_bi=? AND truong=?"
                " AND ts>=? AND ts<? AND do_ai=0 ORDER BY ts", (tb, tr, tu, den)).fetchall()
            ra[(tb, tr)] = [(float(r[0]), str(r[1])) for r in dong]
    finally:
        ro.close()
    return ra


def ban_do_khu(kho: dict[str, Any], *, con_trong_ha: set[str]) -> dict[str, list[tuple[str, str]]]:
    """Mọi mã ngoại vi xếp theo khu vực — theo sổ khu vực của HA
    (`boi_canh_nha.phong_cua`); không có khu thì vào `CHUA_XEP`."""
    from services import boi_canh_nha

    ra: dict[str, list[tuple[str, str]]] = {}
    for tb, tr in sorted(set(kho["trang_thai"]) | set(kho["so_do"])):
        if _la_ma_ha(tb) and tb not in con_trong_ha:
            continue
        ra.setdefault(boi_canh_nha.phong_cua(tb) or CHUA_XEP, []).append((tb, tr))
    return ra


def _ten_ngoai_vi(tb: str, tr: str, ten_ha: dict[str, str]) -> str:
    return (ten_ha.get(tb) or tb.rsplit("/", 1)[-1]) + ("" if tr == "state" else f" · {tr}")


def _dau_thiet_bi(ma: str, ten_ha: dict[str, str], so_bat: int, so_tat: int,
                  du_kien: list[dict[str, Any]]) -> list[str]:
    from services import boi_canh_nha

    dong = [f"THIẾT BỊ: {ma} | {ten_ha.get(ma, '')} | khu vực HA: "
            f"{boi_canh_nha.phong_cua(ma) or 'chưa có'} | bật {so_bat} lần, tắt {so_tat} lần"]
    if du_kien:
        dong.append("\nDỮ KIỆN CHỦ NHÀ:")
        dong += [f"#{d['id']}: {d['noi_dung']}" for d in du_kien]
    return dong


def de_khu_vuc(ma: str, kho: dict[str, Any], ban_do: dict[str, list[tuple[str, str]]], *,
               ten_ha: dict[str, str], du_kien: list[dict[str, Any]],
               so_bat: int, so_tat: int) -> str:
    """Đề BƯỚC 1: thiết bị, dữ kiện, và mọi khu vực kèm vài ngoại vi tiêu biểu."""
    def so_doi(c: tuple[str, str]) -> int:
        return (kho["trang_thai"].get(c) or kho["so_do"].get(c) or {"n": 0})["n"]

    dong = ["BƯỚC 1 — CHỌN KHU VỰC", ""] + _dau_thiet_bi(ma, ten_ha, so_bat, so_tat, du_kien)
    dong.append("\nKHU VỰC (số ngoại vi — vài ngoại vi tiêu biểu):")
    for kv in sorted(ban_do, key=lambda k: (k == CHUA_XEP, k)):
        tieu = sorted(ban_do[kv], key=lambda c: -so_doi(c))[:_TIEU_BIEU]
        dong.append(f"- {kv}: {len(ban_do[kv])} — "
                    + "; ".join(_ten_ngoai_vi(tb, tr, ten_ha) for tb, tr in tieu))
    return "\n".join(dong)


def kiem_khu(data: Any, ban_do: dict[str, Any]) -> dict[str, Any] | str:
    """Kiểm bài BƯỚC 1 tại biên: khu phải có trong đề."""
    if not isinstance(data, dict):
        return "không phải JSON object"
    kv = data.get("khu_vuc")
    if not isinstance(kv, str) or (kv and kv not in ban_do):
        return f"khu vực không có trong đề: {kv!r}"
    xem = data.get("khu_xem")
    if (not isinstance(xem, list) or not 0 < len(xem) <= _TOI_DA_KHU_XEM
            or any(not isinstance(x, str) or x not in ban_do for x in xem)):
        return f"khu_xem phải là 1–{_TOI_DA_KHU_XEM} khu có trong đề: {xem!r}"
    return {"khu_vuc": kv, "khu_xem": list(dict.fromkeys(xem)),
            "vi_sao": str(data.get("vi_sao") or "")[:300]}


def ung_vien(ma_hoc: str, khu_xem: list[str], kho: dict[str, Any],
             ban_do: dict[str, list[tuple[str, str]]], *, ten_ha: dict[str, str],
             bo_ma: set[str]) -> dict[str, Any]:
    """Ngoại vi TỪNG MÃ MỘT của các khu bot chọn, kèm số đo.

    `bo_ma` là các mã của CHÍNH thiết bị (cùng nhóm vật lý bot đã kết luận ở
    lượt hiểu thiết bị) — một bóng đèn không phải ngoại vi của chính nó.
    """
    tu, den = kho["tu"], kho["den"]
    so_ngay = max(1.0, (den - tu) / 86400)
    ban_than = _chi_tiet(tu, den, [(ma_hoc, "state")]).get((ma_hoc, "state"), [])
    moc = [t for t, _ in ban_than]
    cap = [(c, kv) for kv in khu_xem for c in ban_do.get(kv, [])
           if _ma(*c) not in bo_ma and c[0] != ma_hoc]
    chi = _chi_tiet(tu, den, [c for c, _ in cap if c not in kho["so_do"]])

    ngoai_vi: dict[str, dict[str, Any]] = {}
    for (tb, tr), kv in cap:
        ma = _ma(tb, tr)
        ten = _ten_ngoai_vi(tb, tr, ten_ha)
        if (tb, tr) in kho["so_do"]:
            s = kho["so_do"][(tb, tr)]
            gt = (f"chỉ một giá trị: {s['nho']:g}" if s["nho"] == s["lon"]
                  else f"{s['nho']:g}–{s['lon']:g} (tb {s['tb']:.4g})")
            ngoai_vi[ma] = {"ten": ten, "khu_vuc": kv, "kieu": "số đo", "gia_tri": gt,
                            "doi_ngay": "", "quanh": ""}
            continue
        dong = chi.get((tb, tr)) or []
        if not dong:
            continue
        dem: dict[str, int] = {}
        for _, g in dong:
            dem[g] = dem.get(g, 0) + 1
        hay = sorted(dem.items(), key=lambda x: -x[1])[:3]
        gt = (f"chỉ một giá trị: {hay[0][0][:24]}" if len(dem) == 1
              else ", ".join(f"{g[:24]} {round(100 * n / len(dong))}%" for g, n in hay))
        mt = [t for t, _ in dong]
        trung = sum(1 for t in moc if _co_trong(mt, t - _QUANH_GIAY, t + _QUANH_GIAY))
        ngoai_vi[ma] = {"ten": ten, "khu_vuc": kv, "kieu": "trạng thái", "gia_tri": gt,
                        "doi_ngay": f"{len(dong) / so_ngay:.1f}",
                        "quanh": f"{round(100 * trung / len(moc))}%" if moc else ""}
    return {"ma": ma_hoc, "khu_xem": khu_xem, "ngoai_vi": ngoai_vi}


def _co_trong(ds_tang: list[float], a: float, b: float) -> bool:
    i = bisect.bisect_left(ds_tang, a)
    return i < len(ds_tang) and ds_tang[i] <= b


def de_ngoai_vi(uv: dict[str, Any], dau: list[str], khu_vuc: str) -> str:
    """Đề BƯỚC 2 — bảng chữ, ngắn hơn JSON gần một nửa cho cùng số dòng."""
    dong = ["BƯỚC 2 — CHỌN NGOẠI VI", ""] + dau
    dong.append(f"\nKHU VỰC CỦA THIẾT BỊ (bước 1): {khu_vuc or 'chưa xác định'}")
    for kv in uv["khu_xem"]:
        dong.append(f"\nNGOẠI VI — khu vực {kv}:")
        dong.append("mã | tên | kiểu | giá trị | đổi/ngày | đổi quanh lúc bật/tắt")
        dong += [f"{ma} | {x['ten']} | {x['kieu']} | {x['gia_tri']} | {x['doi_ngay']} | {x['quanh']}"
                 for ma, x in uv["ngoai_vi"].items() if x["khu_vuc"] == kv]
    return "\n".join(dong)


def kiem(data: Any, uv: dict[str, Any]) -> dict[str, Any] | str:
    """Kiểm bài BƯỚC 2 NGAY TẠI BIÊN. Trả kết luận đã chuẩn hoá, hoặc lý do loại.

    Loại hẳn thay vì sửa hộ — cùng lẽ `hieu_thiet_bi_nha._kiem`: sửa hộ thì lỗi
    không bao giờ lộ ra để sửa hướng dẫn. Code chỉ kiểm mã CÓ trong đề; chọn
    đúng hay sai là việc người chấm.
    """
    from services.hieu_thiet_bi_nha import VAI_TRO_NGOAI_VI

    if not isinstance(data, dict):
        return "không phải JSON object"
    ds = data.get("ngoai_vi")
    if not isinstance(ds, list) or len(ds) > _TOI_DA_NGOAI_VI:
        return "ngoai_vi phải là danh sách tối đa 5 mục"
    ra: list[dict[str, str]] = []
    for x in ds:
        ma = x.get("ma") if isinstance(x, dict) else None
        vt = x.get("vai_tro") if isinstance(x, dict) else None
        if ma not in uv["ngoai_vi"]:
            return f"mã không có trong đề: {ma!r}"
        if vt not in VAI_TRO_NGOAI_VI:
            return f"vai trò lạ: {vt!r}"
        if any(y["ma"] == ma for y in ra):
            return f"mã lặp: {ma!r}"
        ra.append({"ma": ma, "vai_tro": vt, "ten": uv["ngoai_vi"][ma]["ten"]})
    try:
        chac = min(1.0, max(0.0, float(data.get("chac"))))
    except (TypeError, ValueError):
        chac = 0.0
    return {"ngoai_vi": ra, "chac": round(chac, 2), "vi_sao": str(data.get("vi_sao") or "")[:300]}


def _hoi_bot(ht: Any, model: str, huong: str, de: str) -> Any | str:
    """Một lượt gọi; trả JSON đã đọc hoặc chuỗi lý do hỏng."""
    from services import ha_client

    if ha_client._URL_CO_MAT_KHAU.search(de):
        return "đề có chuỗi dạng tài khoản:mật khẩu — bỏ lượt"
    r = ht._goi_model(model, huong, de)
    if r.get("error"):
        return f"model lỗi: {str(r['error'])[:160]}"
    tho = str(((r.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    data = ht._doc_json(tho)
    return "không đọc được JSON" if data is None else data


def giai(chi: list[str] | None = None, *, so_ngay: int = 30) -> dict[str, Any]:
    """Bot chọn khu vực rồi ngoại vi cho từng thiết bị được học. KHÔNG ghi sổ —
    `chay_mot_lan` ghi; tách ra để giáo viên thử hướng dẫn trên đề thật."""
    from services import du_doan_nha, ha_client, hieu_thiet_bi_nha as ht

    ds = [m for m in ht.thiet_bi_hoc() if not chi or m in chi]
    con_trong_ha = {str(s.get("entity_id") or "") for s in (ha_client.get_states() or [])}
    if not ds or not con_trong_ha:
        return {"ket_luan": [], "loi": [],
                "bo_qua": "chưa có thiết bị được học hoặc HA chưa trả trạng thái"}
    ten_ha = ht._ten_ha()
    nhom = {d["khoa"]: set(d["nhom"].get("ma") or []) for d in ht.dang_hieu_luc()
            if d["loai_cau_hoi"] == "hoc"}
    den = time.time()
    kho = _doc_kho(den - so_ngay * 86400, den)
    ban_do = ban_do_khu(kho, con_trong_ha=con_trong_ha)
    huong, ban = ht.huong_dan("chon_ngoai_vi")
    model = ht._model()
    du_kien = ht.du_kien_gan_day()
    ket_luan: list[dict[str, Any]] = []
    loi: list[dict[str, str]] = []
    for ma in ds:
        ban_than = _chi_tiet(kho["tu"], kho["den"], [(ma, "state")]).get((ma, "state"), [])
        so_bat = sum(1 for _, g in ban_than if du_doan_nha._la_bat(g))
        so_tat = len(ban_than) - so_bat
        b1 = _hoi_bot(ht, model, huong, de_khu_vuc(
            ma, kho, ban_do, ten_ha=ten_ha, du_kien=du_kien, so_bat=so_bat, so_tat=so_tat))
        k1 = kiem_khu(b1, ban_do) if not isinstance(b1, str) else b1
        if isinstance(k1, str):
            loi.append({"ma": ma, "buoc": "khu vực", "loi": k1})
            continue
        uv = ung_vien(ma, k1["khu_xem"], kho, ban_do, ten_ha=ten_ha, bo_ma=nhom.get(ma, set()))
        dau = _dau_thiet_bi(ma, ten_ha, so_bat, so_tat, du_kien)
        b2 = _hoi_bot(ht, model, huong, de_ngoai_vi(uv, dau, k1["khu_vuc"]))
        k2 = kiem(b2, uv) if not isinstance(b2, str) else b2
        if isinstance(k2, str):
            loi.append({"ma": ma, "buoc": "ngoại vi", "loi": k2})
            continue
        vi_sao = " ".join(x for x in (k1["vi_sao"], k2["vi_sao"]) if x)[:300]
        ket_luan.append({"ma_hoc": ma, "khu_vuc": k1["khu_vuc"], "khu_xem": k1["khu_xem"],
                         "ngoai_vi": k2["ngoai_vi"], "chac": k2["chac"], "vi_sao": vi_sao})
    return {"phien_ban": ban, "model": model, "so_thiet_bi": len(ds),
            "ket_luan": ket_luan, "loi": loi}


def chay_mot_lan() -> dict[str, Any]:
    """Heartbeat gọi: bot chọn khu vực + ngoại vi → lưu sổ → báo nhóm học hỏi."""
    from services import hieu_thiet_bi_nha as ht

    if not ht.is_enabled():
        return {"bo_qua": "đang tắt"}
    if not _dang_chay.acquire(blocking=False):
        return {"bo_qua": "lượt trước chưa xong"}
    try:
        kq = giai()
        if kq.get("bo_qua"):
            return kq
        lan = ht._ghi_lan(kq["phien_ban"], kq["model"], kq["so_thiet_bi"],
                          len(kq["ket_luan"]), 0, len(kq["loi"]),
                          json.dumps(kq["loi"], ensure_ascii=False)[:500] if kq["loi"] else "",
                          viec="ngoai_vi")
        ghi = ht.ghi_ngoai_vi(lan, kq["ket_luan"])
        if kq["loi"]:
            logger.warning({"event": "thoi_quen_ngoai_vi_loai", "loi": kq["loi"][:5]})
        if not ghi["moi"] and not ghi["lap_lai"] and not kq["loi"]:
            return {"lan_giai": lan, "moi": 0}
        tin = (f"🧠 Bot học hỏi vừa chọn khu vực và ngoại vi cho {kq['so_thiet_bi']} "
               f"thiết bị (hướng dẫn bản {kq['phien_ban']}): {len(ghi['moi'])} kết luận "
               f"mới hoặc vừa đổi")
        if ghi["lap_lai"]:
            tin += f", {len(ghi['lap_lai'])} câu lặp lại điều từng bị chấm sai nên không dùng"
        if kq["loi"]:
            tin += f", {len(kq['loi'])} thiết bị bài giải bị loại"
        cau, id_hoi = ht.cau_hoi_tiep()
        if cau:
            tin += ".\n\n" + cau
        gui = ht.bao_nhom(tin.replace("_", " "))
        if gui and id_hoi:
            ht.danh_dau_da_hoi(id_hoi)
        return {"lan_giai": lan, "moi": len(ghi["moi"]), "lap_lai": len(ghi["lap_lai"]),
                "loai": len(kq["loi"]), "gui": gui}
    finally:
        _dang_chay.release()
