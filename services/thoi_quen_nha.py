"""Tầng THÓI QUEN — thiết bị được học đi theo NGOẠI VI nào (chặng 1), và thói
quen bật/tắt của nó trông ra sao qua giờ giấc và ngoại vi đó (chặng 2, phần
"Chặng 2" cuối tệp).

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
import re
import sqlite3
import threading
import time
from datetime import datetime
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


# ── Chặng 2: ĐỌC THÓI QUEN ──────────────────────────────────────────────────
# Chủ máy 13/09/2026: "xem thói quen bật hay tắt đèn A xảy ra khi các ngoại vi
# như nào (thời gian, thông số, thời gian thực tế, mùa nào…)", và chọn: bot
# "giải thích + chọn điều kiện"; tầng xác suất vẫn giữ cổng đo.
#
# CODE đo: với từng lần NGƯỜI bật/tắt, giờ giấc và giá trị NGAY TRƯỚC đó của
# các ngoại vi bot đã chọn ở chặng 1 — đặt cạnh NỀN là những ô có thể bật/tắt
# mà không ai làm. BOT đọc số đo, viết thói quen và chọn điều kiện theo
# `huong_dan_hoc/doc_thoi_quen.md`. Code chỉ kiểm điều kiện có mã/giá trị trong
# đề; đúng hay sai là việc người chấm.

#: Ô 30 phút — cùng cỡ ô `du_doan_nha._O_PHUT`, để thói quen bot đọc và tầng xác
#: suất đếm trên cùng một đơn vị. Đếm Ô, không đếm lần: đèn bếp chạy theo tự
#: động hóa bật 1.300 lần trong 149 ô (kho thật 13/09/2026).
_O_GIAY = 1800

#: Giá trị gần nhất TRƯỚC một mốc còn dùng được trong ngần này. HA chỉ báo khi
#: giá trị ĐỔI, nên cảm biến đứng yên cả đêm vẫn đúng là giá trị cũ; quá một
#: ngày thì coi là không biết.
_HAN_GIA_TRI_GIAY = 24 * 3600

#: Trạng thái không nói thiết bị đang bật hay tắt. `off → unavailable → off` là
#: thiết bị mất kết nối, không phải người tắt rồi bật.
_KHONG_RO = frozenset({"unavailable", "unknown", "none", ""})

_TOI_DA_DIEU_KIEN_THOI_QUEN = 3

#: Kết luận thói quen còn mới thì không đọc lại: ngưỡng số đo nhích vài đơn vị
#: mỗi ngày là mỗi ngày một câu hỏi mới cho CÙNG một thói quen.
_DOC_LAI_SAU_GIAY = 7 * 86400

#: Khung giờ đếm tỉ lệ bật/tắt. Ba giờ: đủ mịn để bot đặt được khoảng giờ, đủ
#: thô để 15 ngày dữ liệu mỗi khung vẫn có vài chục ô nền.
_KHUNG_GIO = 3
_MUA_DOC = {"lanh": "lạnh", "chuyen": "chuyển mùa", "nong": "nóng"}


def _tuyen(ro: sqlite3.Connection, tb: str, tr: str, tu: float, den: float
           ) -> tuple[list[float], list[str]]:
    """Mọi giá trị đã biết của một mã theo thời gian, tăng dần.

    Gộp HAI bảng: cảm biến số chuyển từ `su_kien` sang `so_do` khi `nhip` phân
    loại lại (kho thật: ánh sáng bếp ghi `su_kien` tới 11/09 rồi sang `so_do`).

    Ô `so_do` mang mốc KẾT THÚC ô, không phải mốc đầu: trung bình 5 phút gồm cả
    những giây SAU lúc bật — đèn vừa bật làm sáng chính ô đó — nên chỉ được
    dùng khi ô đã khép lại. Cùng họ rò rỉ tương lai với bẫy bảng `tuoi`.
    """
    ra = [(float(r[0]), str(r[1])) for r in ro.execute(
        "SELECT ts, gia_tri FROM su_kien WHERE thiet_bi=? AND truong=? AND ts>=? AND ts<?",
        (tb, tr, tu - _HAN_GIA_TRI_GIAY, den))]
    ra += [((int(r[0]) + 1) * 300.0, f"{float(r[1]):.4g}") for r in ro.execute(
        "SELECT o_5p, tb FROM so_do WHERE thiet_bi=? AND truong=? AND o_5p>=? AND o_5p<?",
        (tb, tr, int((tu - _HAN_GIA_TRI_GIAY) // 300), int(den // 300) + 1))
        if r[1] is not None]
    ra.sort(key=lambda x: x[0])
    return [t for t, _ in ra], [g for _, g in ra]


def _truoc(ts: list[float], gt: list[str], luc: float) -> str | None:
    """Giá trị CHẶT trước `luc` — bằng mốc cũng không lấy, vì cảm biến báo cùng
    giây với lần bật có thể là hệ quả của chính lần bật đó."""
    i = bisect.bisect_left(ts, luc) - 1
    if i < 0 or luc - ts[i] > _HAN_GIA_TRI_GIAY:
        return None
    return gt[i]


def _bat_tat(ro: sqlite3.Connection, ma: str, tu: float, den: float
             ) -> tuple[list[float], list[float], list[float], list[str]]:
    """(lần NGƯỜI bật, lần người tắt, dòng trạng thái đầy đủ).

    Lần bật/tắt bỏ `do_ai=1` — bot bật rồi học "giờ này hay bật" là tự khẳng
    định vòng quanh. Dòng trạng thái thì giữ mọi dòng: bot bật đèn thì đèn vẫn
    đang sáng thật, ô đó không phải "đang tắt mà không ai bật".
    """
    from services.du_doan_nha import _la_bat

    bat: list[float] = []
    tat: list[float] = []
    ts_ds: list[float] = []
    gt_ds: list[str] = []
    cu: str | None = None
    for t, g, ai in ro.execute(
            "SELECT ts, gia_tri, do_ai FROM su_kien WHERE thiet_bi=? AND truong='state'"
            " AND ts>=? AND ts<? ORDER BY ts", (ma, tu - _HAN_GIA_TRI_GIAY, den)):
        t, g = float(t), str(g)
        if (t >= tu and not ai and cu is not None
                and g.strip().lower() not in _KHONG_RO and cu.strip().lower() not in _KHONG_RO):
            if _la_bat(g) and not _la_bat(cu):
                bat.append(t)
            elif _la_bat(cu) and not _la_bat(g):
                tat.append(t)
        cu = g
        ts_ds.append(t)
        gt_ds.append(g)
    return bat, tat, ts_ds, gt_ds


def _o_nha(ro: sqlite3.Connection, tu: float, den: float) -> list[int]:
    """Ô có ít nhất một sự kiện không do bot — cùng nguồn mẫu âm `du_doan_nha.hoc`:
    ô nhà vắng hẳn không nói lên "người chọn không bật"."""
    return sorted(int(r[0]) for r in ro.execute(
        "SELECT DISTINCT CAST(ts / ? AS INTEGER) FROM su_kien WHERE ts>=? AND ts<? AND do_ai=0",
        (_O_GIAY, tu, den)))


def _tom(ds: list[str | None]) -> tuple[str, str, list[str]]:
    """(tóm tắt, kiểu, các giá trị trạng thái đã thấy) của các giá trị đo được."""
    from services.du_doan_nha import _la_so

    co = [g for g in ds if g is not None]
    if not co:
        return "—", "", []
    so = sorted(float(g) for g in co if _la_so(g))
    if len(so) == len(co):
        n = len(so)
        return f"{so[n // 2]:.4g} ({so[n // 4]:.4g}–{so[(3 * n) // 4]:.4g}), n={n}", "số đo", []
    dem: dict[str, int] = {}
    for g in co:
        dem[g] = dem.get(g, 0) + 1
    hay = sorted(dem.items(), key=lambda x: -x[1])
    return (", ".join(f"{g[:24]} {round(100 * k / len(co))}%" for g, k in hay[:3])
            + f", n={len(co)}", "trạng thái", [g for g, _ in hay])


def _gio_phut(t: float) -> datetime:
    from services.boi_canh_nha import _TZ

    return datetime.fromtimestamp(t, _TZ)


def _dong_thoi_gian(co: list[float], nen: list[float]) -> list[str]:
    """Hai dòng giờ giấc, dòng nào cũng đặt số lần làm CẠNH nền: theo khung giờ
    và theo ngày.

    Bản thử đầu có thêm dòng "10% trước…, giữa…, 10% sau…" giờ các lần bật —
    chỉ mẫu dương, không nền. Bot chép nguyên hai mốc làm khoảng thói quen ở cả
    3/3 bài (đo 13/09/2026: đèn bếp "18:00–23:00" trong khi khung chiều vẫn bật
    ở gần nửa số ô) — đúng bẫy thiếu mẫu âm, nên bỏ.
    """
    khung = {g: [0, 0] for g in range(0, 24, _KHUNG_GIO)}
    ngay = {"thường": [0, 0], "cuối tuần": [0, 0]}
    for ds, i in ((co, 0), (nen, 1)):
        for t in ds:
            d = _gio_phut(t)
            khung[d.hour - d.hour % _KHUNG_GIO][i] += 1
            ngay["cuối tuần" if d.weekday() >= 5 else "thường"][i] += 1
    return ["- khung giờ: " + "; ".join(f"{g}–{g + _KHUNG_GIO}h {a}/{a + c}"
                                        for g, (a, c) in khung.items() if a + c),
            "- ngày: " + "; ".join(f"{b} {a}/{a + c}" for b, (a, c) in ngay.items() if a + c)]


def do_thoi_quen(ro: sqlite3.Connection, ma: str, ngoai_vi: list[dict[str, Any]], *,
                 tu: float, den: float, o_nha: list[int]) -> dict[str, Any]:
    """Số đo cho MỘT thiết bị. Mẫu dương là ô có người bật (đo ở lần bật ĐẦU ô),
    mẫu âm là ô đang tắt mà không ai bật (đo ở đầu ô); chiều tắt đối xứng."""
    from services.du_doan_nha import _la_bat

    bat, tat, ts, gt = _bat_tat(ro, ma, tu, den)
    dau_bat: dict[int, float] = {}
    dau_tat: dict[int, float] = {}
    for t in bat:
        dau_bat.setdefault(int(t // _O_GIAY), t)
    for t in tat:
        dau_tat.setdefault(int(t // _O_GIAY), t)
    nen_bat: list[float] = []
    nen_tat: list[float] = []
    for o in o_nha:
        g = _truoc(ts, gt, o * _O_GIAY)
        if g is None or g.strip().lower() in _KHONG_RO:
            continue
        if _la_bat(g):
            if o not in dau_tat:
                nen_tat.append(o * _O_GIAY)
        elif o not in dau_bat:
            nen_bat.append(o * _O_GIAY)
    co_bat, co_tat = sorted(dau_bat.values()), sorted(dau_tat.values())

    nv: dict[str, dict[str, Any]] = {}
    for x in ngoai_vi:
        tb, _, tr = str(x["ma"]).partition("#")
        pts, pgt = _tuyen(ro, tb, tr or "state", tu, den)
        cot: dict[str, str] = {}
        kieu, gia_tri = "", set()
        for ten, moc in (("bat", co_bat), ("nen_bat", nen_bat), ("tat", co_tat), ("nen_tat", nen_tat)):
            cot[ten], k, thay = _tom([_truoc(pts, pgt, t) for t in moc])
            kieu = kieu or k
            gia_tri.update(thay)
        nv[str(x["ma"])] = {"ten": str(x.get("ten") or x["ma"]), "vai_tro": str(x.get("vai_tro") or ""),
                            "kieu": kieu or "chưa đo được", "gia_tri": sorted(gia_tri), **cot}
    return {"ma": ma, "o_bat": len(co_bat), "o_tat": len(co_tat),
            "nen_bat": len(nen_bat), "nen_tat": len(nen_tat),
            "thoi_gian_bat": _dong_thoi_gian(co_bat, nen_bat),
            "thoi_gian_tat": _dong_thoi_gian(co_tat, nen_tat), "ngoai_vi": nv}


def _pham_vi(o_nha: list[int]) -> str:
    from services.boi_canh_nha import mua

    if not o_nha:
        return "chưa có dữ liệu"
    ngay = sorted({_gio_phut(o * _O_GIAY).date() for o in o_nha})
    cac_mua = sorted({mua(d.month) for d in ngay})
    return (f"{ngay[0]:%d/%m}–{ngay[-1]:%d/%m}, {len(ngay)} ngày có dữ liệu; "
            f"mùa trong dữ liệu: {', '.join(_MUA_DOC[m] for m in cac_mua)}")


def de_thoi_quen(do: dict[str, Any], dau: list[str], pham_vi: str) -> str:
    """Đề ĐỌC THÓI QUEN — bảng chữ, cùng lẽ `de_ngoai_vi`."""
    dong = ["ĐỌC THÓI QUEN", ""] + dau
    dong += [f"\nPHẠM VI: {pham_vi}",
             f"\nBẬT: {do['o_bat']} ô có bật; nền {do['nen_bat']} ô đang tắt mà không ai bật"]
    dong += do["thoi_gian_bat"]
    dong.append(f"TẮT: {do['o_tat']} ô có tắt; nền {do['nen_tat']} ô đang bật mà không ai tắt")
    dong += do["thoi_gian_tat"]
    if do["ngoai_vi"]:
        dong.append("\nNGOẠI VI — giá trị ngay trước lúc bật/tắt, và ở nền:")
        dong.append("mã | tên | vai trò | kiểu | lúc bật | nền bật | lúc tắt | nền tắt")
        dong += [f"{ma} | {x['ten']} | {x['vai_tro']} | {x['kieu']} | {x['bat']} | "
                 f"{x['nen_bat']} | {x['tat']} | {x['nen_tat']}" for ma, x in do["ngoai_vi"].items()]
    else:
        dong.append("\nNGOẠI VI: chưa chọn ngoại vi nào — chỉ đọc được giờ giấc.")
    return "\n".join(dong)


def _la_con_so(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def _kiem_dieu_kien(ds: Any, do: dict[str, Any]) -> list[dict[str, Any]] | str:
    if not isinstance(ds, list) or len(ds) > _TOI_DA_DIEU_KIEN_THOI_QUEN:
        return f"dieu_kien phải là danh sách tối đa {_TOI_DA_DIEU_KIEN_THOI_QUEN} mục"
    ra: list[dict[str, Any]] = []
    for x in ds:
        ma = x.get("ma") if isinstance(x, dict) else None
        if ma == "gio":
            # "24:00" chỉ làm mốc CUỐI — hết ngày, như khung "21–24h" trong đề.
            if not (isinstance(x.get("tu"), str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", x["tu"])
                    and isinstance(x.get("den"), str)
                    and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d|24:00", x["den"])):
                return f"giờ phải dạng HH:MM: {x.get('tu')!r}–{x.get('den')!r}"
            dk = {"ma": "gio", "tu": x["tu"], "den": x["den"]}
        elif ma in ("ngay", "mua"):
            hop = ("thuong", "cuoi_tuan") if ma == "ngay" else tuple(_MUA_DOC)
            if x.get("la") not in hop:
                return f"{ma} phải là một trong {hop}: {x.get('la')!r}"
            dk = {"ma": ma, "la": x["la"]}
        elif isinstance(ma, str) and ma in do["ngoai_vi"]:
            nv = do["ngoai_vi"][ma]
            if nv["kieu"] == "số đo":
                nguong = [k for k in ("duoi", "tren") if k in x]
                if len(nguong) != 1 or not _la_con_so(x[nguong[0]]):
                    return f"{ma} là số đo: cần đúng một ngưỡng số 'duoi' hoặc 'tren'"
                dk = {"ma": ma, nguong[0]: round(float(x[nguong[0]]), 2)}
            elif x.get("la") in nv["gia_tri"]:
                dk = {"ma": ma, "la": x["la"]}
            else:
                return f"giá trị {x.get('la')!r} không có trong đề cho {ma!r}"
        else:
            return f"mã không có trong đề: {ma!r}"
        # Nhiều khoảng giờ rời nhau (đèn nhà tắm sáng sớm và buổi tối) là nhiều
        # điều kiện `gio`, hiểu là HOẶC; mã khác lặp lại thì loại.
        if dk["ma"] != "gio" and any(y["ma"] == dk["ma"] for y in ra):
            return f"mã lặp: {ma!r}"
        ra.append(dk)
    return ra


def kiem_thoi_quen(data: Any, do: dict[str, Any]) -> dict[str, Any] | str:
    """Kiểm bài ĐỌC THÓI QUEN tại biên — loại hẳn, không sửa hộ (cùng lẽ `kiem`)."""
    if not isinstance(data, dict):
        return "không phải JSON object"
    ra: dict[str, Any] = {}
    for chieu in ("bat", "tat"):
        p = data.get(chieu)
        if not isinstance(p, dict):
            return f"thiếu phần {chieu!r}"
        dk = _kiem_dieu_kien(p.get("dieu_kien"), do)
        if isinstance(dk, str):
            return f"{chieu}: {dk}"
        ra[chieu] = {"thoi_quen": str(p.get("thoi_quen") or "")[:200], "dieu_kien": dk}
    try:
        chac = min(1.0, max(0.0, float(data.get("chac"))))
    except (TypeError, ValueError):
        chac = 0.0
    return {**ra, "chac": round(chac, 2), "vi_sao": str(data.get("vi_sao") or "")[:300]}


def _can_doc_lai(nv: dict[str, Any], cu: dict[str, Any] | None, now: float) -> bool:
    """Chưa có kết luận, kết luận bị chấm sai, ngoại vi đã đổi, hoặc kết luận đã cũ."""
    if cu is None or cu["ket_qua"] == "sai":
        return True
    if sorted(str(x["ma"]) for x in nv.get("ngoai_vi") or []) != (cu["nhom"].get("ngoai_vi") or []):
        return True
    return now - float(cu["nhom"].get("doc_luc") or cu["ts"]) > _DOC_LAI_SAU_GIAY


def doc(chi: list[str] | None = None, *, so_ngay: int = 30, tat_ca: bool = False) -> dict[str, Any]:
    """Bot đọc thói quen bật/tắt cho từng thiết bị đã có ngoại vi. KHÔNG ghi sổ —
    `chay_mot_lan` ghi; tách ra để giáo viên thử hướng dẫn trên đề thật.

    `tat_ca` đọc lại cả thiết bị có kết luận còn mới (chủ máy vừa thêm dữ kiện).
    """
    from services import ha_client, hieu_thiet_bi_nha as ht

    nv_hoc = ht.ngoai_vi_hoc()
    hl = {d["khoa"]: d for d in ht.dang_hieu_luc() if d["loai_cau_hoi"] == "thoi_quen"}
    now = time.time()
    ds = [m for m in sorted(nv_hoc) if (not chi or m in chi)
          and (tat_ca or chi or _can_doc_lai(nv_hoc[m], hl.get(m), now))]
    con_trong_ha = {str(s.get("entity_id") or "") for s in (ha_client.get_states() or [])}
    if not ds or not con_trong_ha:
        return {"ket_luan": [], "loi": [], "so_thiet_bi": 0,
                "bo_qua": "không thiết bị nào cần đọc thói quen, hoặc HA chưa trả trạng thái"}
    ten_ha = ht._ten_ha()
    huong, ban = ht.huong_dan("doc_thoi_quen")
    model = ht._model()
    du_kien = ht.du_kien_gan_day()
    den = now
    tu = den - so_ngay * 86400
    ket_luan: list[dict[str, Any]] = []
    loi: list[dict[str, str]] = []
    ro = sqlite3.connect(f"file:{_lich_su_db()}?mode=ro", uri=True, timeout=10.0)
    try:
        o_nha = _o_nha(ro, tu, den)
        pham_vi = _pham_vi(o_nha)
        for ma in ds:
            # Mã HA không còn trong `get_states` (mang mật khẩu trong tên, hoặc chủ
            # máy đã «Bỏ khỏi c2a») thì không bày — cùng biên với chặng 1.
            nv = [x for x in nv_hoc[ma].get("ngoai_vi") or []
                  if not _la_ma_ha(str(x["ma"]).partition("#")[0])
                  or str(x["ma"]).partition("#")[0] in con_trong_ha]
            do = do_thoi_quen(ro, ma, nv, tu=tu, den=den, o_nha=o_nha)
            dau = [f"THIẾT BỊ: {ma} | {ten_ha.get(ma, '')} | khu vực: "
                   f"{nv_hoc[ma].get('khu_vuc') or 'chưa rõ'}"]
            if du_kien:
                dau += ["\nDỮ KIỆN CHỦ NHÀ:"] + [f"#{d['id']}: {d['noi_dung']}" for d in du_kien]
            b = _hoi_bot(ht, model, huong, de_thoi_quen(do, dau, pham_vi))
            k = kiem_thoi_quen(b, do) if not isinstance(b, str) else b
            if isinstance(k, str):
                loi.append({"ma": ma, "buoc": "thói quen", "loi": k})
                continue
            ket_luan.append({"ma_hoc": ma, **k, "ngoai_vi": sorted(str(x["ma"]) for x in nv),
                             "ten_ngoai_vi": {str(x["ma"]): str(x.get("ten") or "") for x in nv}})
    finally:
        ro.close()
    return {"phien_ban": ban, "model": model, "so_thiet_bi": len(ds),
            "ket_luan": ket_luan, "loi": loi}


def _lich_su_db() -> Any:
    from services import lich_su_nha

    return lich_su_nha._DB_PATH


def _bao_so(viec: str, kq: dict[str, Any], ghi: dict[str, list[Any]]) -> str:
    tin = (f"{viec} cho {kq['so_thiet_bi']} thiết bị (hướng dẫn bản {kq['phien_ban']}): "
           f"{len(ghi['moi'])} kết luận mới hoặc vừa đổi")
    if ghi["lap_lai"]:
        tin += f", {len(ghi['lap_lai'])} câu lặp lại điều từng bị chấm sai nên không dùng"
    if kq["loi"]:
        tin += f", {len(kq['loi'])} thiết bị bài giải bị loại"
    return tin


def _ghi_luot(ht: Any, kq: dict[str, Any], viec: str) -> int:
    return ht._ghi_lan(kq["phien_ban"], kq["model"], kq["so_thiet_bi"],
                       len(kq["ket_luan"]), 0, len(kq["loi"]),
                       json.dumps(kq["loi"], ensure_ascii=False)[:500] if kq["loi"] else "",
                       viec=viec)


def chay_mot_lan() -> dict[str, Any]:
    """Heartbeat gọi: bot chọn khu vực + ngoại vi, rồi đọc thói quen → lưu sổ →
    báo nhóm học hỏi một tin chung."""
    from services import hieu_thiet_bi_nha as ht

    if not ht.is_enabled():
        return {"bo_qua": "đang tắt"}
    if not _dang_chay.acquire(blocking=False):
        return {"bo_qua": "lượt trước chưa xong"}
    try:
        kq = giai()
        if kq.get("bo_qua"):
            return kq
        lan = _ghi_luot(ht, kq, "ngoai_vi")
        ghi = ht.ghi_ngoai_vi(lan, kq["ket_luan"])
        if kq["loi"]:
            logger.warning({"event": "thoi_quen_ngoai_vi_loai", "loi": kq["loi"][:5]})
        ra: dict[str, Any] = {"lan_giai": lan, "moi": len(ghi["moi"]),
                              "lap_lai": len(ghi["lap_lai"]), "loai": len(kq["loi"])}
        phan: list[str] = []
        if ghi["moi"] or ghi["lap_lai"] or kq["loi"]:
            phan.append(_bao_so("chọn khu vực và ngoại vi", kq, ghi))

        # Đọc SAU khi lưu ngoại vi: thiết bị vừa đổi ngoại vi đọc lại ngay lượt này.
        kq2 = doc(tat_ca=ht.co_du_kien_moi("thoi_quen"))
        if not kq2.get("bo_qua"):
            lan2 = _ghi_luot(ht, kq2, "thoi_quen")
            ghi2 = ht.ghi_thoi_quen(lan2, kq2["ket_luan"])
            if kq2["loi"]:
                logger.warning({"event": "thoi_quen_doc_loai", "loi": kq2["loi"][:5]})
            ra["thoi_quen"] = {"lan_giai": lan2, "moi": len(ghi2["moi"]),
                               "lap_lai": len(ghi2["lap_lai"]), "loai": len(kq2["loi"])}
            if ghi2["moi"] or ghi2["lap_lai"] or kq2["loi"]:
                phan.append(_bao_so("đọc thói quen bật/tắt", kq2, ghi2))
        if not phan:
            return ra
        tin = "🧠 Bot học hỏi vừa " + ";\nvừa ".join(phan)
        cau, id_hoi = ht.cau_hoi_tiep()
        if cau:
            tin += ".\n\n" + cau
        gui = ht.bao_nhom(tin.replace("_", " "))
        if gui and id_hoi:
            ht.danh_dau_da_hoi(id_hoi)
        return {**ra, "gui": gui}
    finally:
        _dang_chay.release()
