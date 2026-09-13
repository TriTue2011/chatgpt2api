"""Tầng THÓI QUEN — thiết bị được học đi theo NGOẠI VI nào.

Chủ máy chốt 13/09/2026, nguyên văn:

    "Phần học thói quen mới chỉ đang xét đến các ngoại vi, nhưng chưa phân loại
    rõ ràng ngoại vi nào sẽ ảnh hưởng đến thói quen, chưa có hướng dẫn chi tiết.
    Ví dụ bật đèn A, thì đèn ở khu vực nào thì ngoại vi đi theo khu vực đó,
    không nên nhặt bừa. [...] hướng dẫn ngắn gọn và xúc tích, tránh dài để bot
    nghĩ nhiều, quá dung lượng làm cắt bớt thông tin"

    "Ảnh chụp không phải cái để học, cảm biến hiện diện, cảm biến đếm người mới
    là cái cần."

Số đo làm đề (kho thật 13/09/2026) — vì sao tầng này tồn tại, KHÔNG để code dùng:

* Điều kiện cũ gom theo KHOÁ PHÒNG bằng khớp chuỗi tên: `nguoi_phòng_khách` gom
  14 mã có chữ motion/person/occupancy/presence — cả công tắc bật tính năng phát
  hiện của Frigate, số ngưỡng `motion_threshold`, ảnh `image.*`. 7 ngày: 23/194
  ô 30 phút (12%) do những giá trị luôn đọc là "có người" quyết.
* "Đèn ban công" nằm trên công tắc bếp nên HA xếp khu Bếp, và bot chọn ánh sáng
  bếp, người ở bếp làm điều kiện cho nó.
* 10 thiết bị được học; mỗi khu vực 18–66 ngoại vi riêng lẻ, khu "chưa rõ" 458.

Nên: CODE bày ngoại vi của những khu vực LIÊN QUAN tới từng thiết bị (khu HA ghi
cộng khu có tên nằm trong tên thiết bị), TỪNG MÃ MỘT kèm số đo; BOT chọn theo bản
hướng dẫn ngắn `huong_dan_hoc/chon_ngoai_vi.md`, MỖI THIẾT BỊ MỘT LƯỢT GỌI để đề
ngắn; kết luận lưu chung sổ `hieu_thiet_bi_nha` (câu `ngoai_vi`) và được chấm
«hh N» như mọi câu khác.

Code chỉ bỏ hai thứ, đều là số đo chứ không phải phán quyết: mã chỉ có MỘT giá
trị trong cửa sổ (không bao giờ đổi thì không mang tin), và mã HA không còn
trong `ha_client.get_states()` (hàm đó ẩn thực thể mang mật khẩu camera trong
tên — mã sinh từ tên nên cũng mang mật khẩu).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from utils.log import logger

#: Ngoại vi đổi trong ngần này giây quanh một lần bật/tắt thì tính là "đổi quanh
#: lúc bật/tắt" — manh mối phụ cho bot, không phải điều kiện.
_QUANH_GIAY = 600

_TOI_DA_NGOAI_VI = 5

_dang_chay = threading.Lock()


def _ma(thiet_bi: str, truong: str) -> str:
    """Cùng quy ước mã với `hieu_thiet_bi_nha._ma`: trường `state` không ghi."""
    return thiet_bi if truong == "state" else f"{thiet_bi}#{truong}"


def _la_ma_ha(thiet_bi: str) -> bool:
    mien, cham, ten = thiet_bi.partition(".")
    return bool(cham) and "/" not in thiet_bi and mien.isidentifier() and bool(ten)


def _khu_vuc_lien_quan(ma: str, ten: str, du_kien: list[dict[str, Any]]) -> list[str]:
    """Khu HA ghi cho mã, khu có TÊN nằm trong tên thiết bị, và khu được nêu
    trong dòng dữ kiện chủ nhà có nhắc tên thiết bị.

    Tên phòng lấy từ chính sổ khu vực của HA (`boi_canh_nha._nap_so_phong`) —
    chủ nhà đổi tên phòng thì bảng này đổi theo, không có danh sách phòng cài
    cứng. Hai nguồn lệch nhau ("Đèn ban công" ở khu Bếp) thì bày CẢ HAI cho bot
    quyết theo hướng dẫn.

    Nguồn thứ ba vì dữ kiện chủ nhà có thể nối thiết bị với khu khác: 11/09/2026
    "Bình nóng lạnh lấy theo thời tiết, cảm biến nhiệt ẩm ban công" — bình ở
    khu Nhà tắm, không bày khu Ban công thì bot không thể làm theo lời dạy.
    """
    from services.boi_canh_nha import _khong_dau, _nap_so_phong

    so, ten_phong = _nap_so_phong()
    theo_dai = sorted((k for k in ten_phong if k), key=len, reverse=True)
    ra: list[str] = []

    def them(chuoi: str) -> None:
        t = _khong_dau(chuoi)
        for kd in theo_dai:
            if kd in t and ten_phong[kd] not in ra:
                ra.append(ten_phong[kd])

    if so.get(ma):
        ra.append(str(so[ma]))
    them(ten or "")
    ten_kd = _khong_dau(ten or "")
    for d in du_kien:
        for dong in str(d.get("noi_dung") or "").splitlines():
            if ten_kd and ten_kd in _khong_dau(dong):
                them(dong)
    return ra


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
        so_do = {(r[0], r[1]): {"nho": r[2], "tb": r[3], "lon": r[4]} for r in ro.execute(
            "SELECT thiet_bi, truong, MIN(nho), AVG(tb), MAX(lon) FROM so_do"
            " WHERE o_5p>=? AND o_5p<? GROUP BY thiet_bi, truong",
            (int(tu // 300), int(den // 300) + 1))}
    finally:
        ro.close()
    return {"tu": tu, "den": den, "trang_thai": trang_thai, "so_do": so_do}


def _chi_tiet(tu: float, den: float, cap: list[tuple[str, str]]) -> dict[tuple[str, str], Any]:
    """Giá trị hay gặp và các mốc đổi của những mã được bày — theo chỉ mục
    `(thiet_bi, truong, ts)`, nhanh."""
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


def ung_vien(ma_hoc: str, kho: dict[str, Any], *, ten_ha: dict[str, str],
             du_kien: list[dict[str, Any]], bo_ma: set[str],
             con_trong_ha: set[str]) -> dict[str, Any]:
    """Đề cho MỘT thiết bị: khu vực liên quan và ngoại vi của từng khu.

    Trả ``{"ma", "ten", "khu_vuc_ha", "khu_vuc", "so_bat", "so_tat",
    "ngoai_vi": {mã: {…}}}``. `bo_ma` là các mã của CHÍNH thiết bị (cùng nhóm
    vật lý) — một bóng đèn không phải ngoại vi của chính nó.
    """
    from services import boi_canh_nha, du_doan_nha

    tu, den = kho["tu"], kho["den"]
    so_ngay = max(1.0, (den - tu) / 86400)
    ten = ten_ha.get(ma_hoc, "")
    khu = _khu_vuc_lien_quan(ma_hoc, ten, du_kien)
    ban_than = _chi_tiet(tu, den, [(ma_hoc, "state")]).get((ma_hoc, "state"), [])
    moc = [t for t, _ in ban_than]
    so_bat = sum(1 for _, g in ban_than if du_doan_nha._la_bat(g))

    chon: dict[tuple[str, str], str] = {}
    for tb, tr in set(kho["trang_thai"]) | set(kho["so_do"]):
        if _ma(tb, tr) in bo_ma or tb == ma_hoc:
            continue
        if _la_ma_ha(tb) and tb not in con_trong_ha:
            continue
        kv = boi_canh_nha.phong_cua(tb)
        if kv in khu:
            chon[(tb, tr)] = kv
    trang_thai_cap = [c for c in chon if c not in kho["so_do"]
                      and kho["trang_thai"][c]["so_gt"] >= 2]
    chi = _chi_tiet(tu, den, trang_thai_cap)

    ngoai_vi: dict[str, dict[str, Any]] = {}
    for (tb, tr), kv in sorted(chon.items(), key=lambda x: (x[1], x[0])):
        ma = _ma(tb, tr)
        ten_nv = (ten_ha.get(tb) or tb.rsplit("/", 1)[-1]) + ("" if tr == "state" else f" · {tr}")
        if (tb, tr) in kho["so_do"]:
            s = kho["so_do"][(tb, tr)]
            if s["nho"] is None or s["nho"] == s["lon"]:
                continue
            ngoai_vi[ma] = {"ten": ten_nv, "khu_vuc": kv, "kieu": "số đo",
                            "gia_tri": f"{s['nho']:g}–{s['lon']:g} (tb {s['tb']:.4g})",
                            "doi_ngay": "", "quanh": ""}
            continue
        if (tb, tr) not in chi:
            continue
        dong = chi[(tb, tr)]
        dem: dict[str, int] = {}
        for _, g in dong:
            dem[g] = dem.get(g, 0) + 1
        hay = sorted(dem.items(), key=lambda x: -x[1])[:3]
        mt = [t for t, _ in dong]
        trung = sum(1 for t in moc if _co_trong(mt, t - _QUANH_GIAY, t + _QUANH_GIAY))
        ngoai_vi[ma] = {
            "ten": ten_nv, "khu_vuc": kv, "kieu": "trạng thái",
            "gia_tri": ", ".join(f"{g[:24]} {round(100 * n / len(dong))}%" for g, n in hay),
            "doi_ngay": f"{len(dong) / so_ngay:.1f}",
            "quanh": f"{round(100 * trung / len(moc))}%" if moc else ""}
    return {"ma": ma_hoc, "ten": ten, "khu_vuc_ha": boi_canh_nha.phong_cua(ma_hoc),
            "khu_vuc": khu, "so_bat": so_bat, "so_tat": len(ban_than) - so_bat,
            "ngoai_vi": ngoai_vi}


def _co_trong(ds_tang: list[float], a: float, b: float) -> bool:
    import bisect
    i = bisect.bisect_left(ds_tang, a)
    return i < len(ds_tang) and ds_tang[i] <= b


def de_bai(uv: dict[str, Any], du_kien: list[dict[str, Any]]) -> str:
    """Đề dạng bảng chữ — ngắn hơn JSON gần một nửa cho cùng số dòng."""
    dong = [f"THIẾT BỊ: {uv['ma']} | {uv['ten']} | khu vực HA: {uv['khu_vuc_ha'] or 'chưa có'}"
            f" | bật {uv['so_bat']} lần, tắt {uv['so_tat']} lần"]
    if du_kien:
        dong.append("\nDỮ KIỆN CHỦ NHÀ:")
        dong += [f"#{d['id']}: {d['noi_dung']}" for d in du_kien]
    if not uv["khu_vuc"]:
        dong.append("\nKHÔNG có khu vực liên quan nào (HA chưa xếp khu, tên không nêu khu).")
    for kv in uv["khu_vuc"]:
        dong.append(f"\nNGOẠI VI — khu vực {kv}:")
        dong.append("mã | tên | kiểu | giá trị | đổi/ngày | đổi quanh lúc bật/tắt")
        dong += [f"{ma} | {x['ten']} | {x['kieu']} | {x['gia_tri']} | {x['doi_ngay']} | {x['quanh']}"
                 for ma, x in uv["ngoai_vi"].items() if x["khu_vuc"] == kv]
    return "\n".join(dong)


def kiem(data: Any, uv: dict[str, Any]) -> dict[str, Any] | str:
    """Kiểm câu trả lời NGAY TẠI BIÊN. Trả kết luận đã chuẩn hoá, hoặc lý do loại.

    Loại hẳn thay vì sửa hộ — cùng lẽ `hieu_thiet_bi_nha._kiem`: sửa hộ thì lỗi
    không bao giờ lộ ra để sửa hướng dẫn. Code chỉ kiểm mã CÓ trong đề và khu
    vực có trong đề; chọn đúng hay sai là việc người chấm.
    """
    from services.hieu_thiet_bi_nha import VAI_TRO_NGOAI_VI

    if not isinstance(data, dict):
        return "không phải JSON object"
    kv = data.get("khu_vuc")
    if not isinstance(kv, str) or (kv and kv not in uv["khu_vuc"]):
        return f"khu vực không có trong đề: {kv!r}"
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
    return {"ma_hoc": uv["ma"], "khu_vuc": kv, "ngoai_vi": ra, "chac": round(chac, 2),
            "vi_sao": str(data.get("vi_sao") or "")[:300]}


def giai(chi: list[str] | None = None, *, so_ngay: int = 30) -> dict[str, Any]:
    """Bot chọn ngoại vi cho từng thiết bị được học. KHÔNG ghi sổ — `chay_mot_lan`
    ghi; tách ra để giáo viên thử hướng dẫn trên đề thật mà không đụng sổ."""
    from services import ha_client, hieu_thiet_bi_nha as ht

    ds = [m for m in ht.thiet_bi_hoc() if not chi or m in chi]
    trang_thai = ha_client.get_states() or []
    con_trong_ha = {str(s.get("entity_id") or "") for s in trang_thai}
    if not ds or not con_trong_ha:
        return {"ket_luan": [], "loi": [], "bo_qua": "chưa có thiết bị được học hoặc HA chưa trả trạng thái"}
    ten = ht._ten_ha()
    nhom = {d["khoa"]: set(d["nhom"].get("ma") or []) for d in ht.dang_hieu_luc()
            if d["loai_cau_hoi"] == "hoc"}
    den = time.time()
    kho = _doc_kho(den - so_ngay * 86400, den)
    huong, ban = ht.huong_dan("chon_ngoai_vi")
    model = ht._model()
    du_kien = ht.du_kien_gan_day()
    ket_luan: list[dict[str, Any]] = []
    loi: list[dict[str, str]] = []
    for ma in ds:
        uv = ung_vien(ma, kho, ten_ha=ten, du_kien=du_kien,
                      bo_ma=nhom.get(ma, set()), con_trong_ha=con_trong_ha)
        de = de_bai(uv, du_kien)
        if ha_client._URL_CO_MAT_KHAU.search(de):
            loi.append({"ma": ma, "loi": "đề có chuỗi dạng tài khoản:mật khẩu — bỏ lượt"})
            continue
        r = ht._goi_model(model, huong, de)
        if r.get("error"):
            loi.append({"ma": ma, "loi": f"model lỗi: {str(r['error'])[:160]}"})
            continue
        tho = str(((r.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        kq = kiem(ht._doc_json(tho), uv)
        if isinstance(kq, str):
            loi.append({"ma": ma, "loi": kq})
            continue
        ket_luan.append(kq)
    return {"phien_ban": ban, "model": model, "so_thiet_bi": len(ds),
            "ket_luan": ket_luan, "loi": loi}


def chay_mot_lan() -> dict[str, Any]:
    """Heartbeat gọi: bot chọn ngoại vi → lưu sổ → báo nhóm học hỏi một câu."""
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
        tin = (f"🧠 Bot học hỏi vừa chọn ngoại vi theo khu vực cho {kq['so_thiet_bi']} "
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
