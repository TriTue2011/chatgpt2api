"""Nhắc LỆCH NẾP — thiết bị hôm nay không hoạt động vào giờ quen thì hỏi nhẹ, kèm nguyên nhân đo được.

Chủ máy 03/10/2026 (xem bot «Tiểu Vy»: "con sen chưa đi hoạt động hôm nay (thường chạy lúc 15:00).
Có vấn đề gì không ạ?" — "nó bị mất mạng ấy mà, tối về ba sửa"): "làm tính năng nhắc lệch nếp".
Mặc định TẮT (``mqtt.lech_nep.bat``) — chủ máy tích ở tab Học hỏi, như mọi tầng học khác.

NẾP = một khung 60 phút mà thiết bị có hoạt động (đổi trạng thái) ở ≥ ``NGUONG`` số ngày CÙNG LOẠI
(ngày thường / cuối tuần) trong ``SO_NGAY[loại]`` ngày gần nhất, đủ ``IT_NHAT`` ngày mẫu; khung chồng
nhau thì gộp. Cửa sổ RIÊNG từng loại: 21 ngày chỉ có 6 ngày cuối tuần — chung một cửa sổ thì nếp cuối
tuần không bao giờ đủ mẫu.
Tính CẢ lần bot tự bật: câu hỏi ở đây là "thiết bị có làm việc quen không", không phải "người có bật
không" — bỏ ``do_ai`` thì đèn bot đã tự lo bị báo lệch oan (đo 03/10: 6 lần → 2 lần trong 14 ngày).

Đo 03/10/2026 trên lịch sử thật (30/08–03/10): chỉ ĐÈN có nếp (bếp, nhà tắm, phòng ngủ, phòng học,
phòng khách sáng sớm); nhà không có robot hút bụi. Giả lập 14 ngày: 2 lần hỏi, cả hai đèn phòng ngủ.

Câu trả lời tự nhiên do MODEL hiểu (``huong_dan_hoc/lech_nep.md``) — không danh sách từ khoá.
"""
from __future__ import annotations

import collections
import json
import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

_PATH = Path(DATA_DIR) / "agent" / "lech_nep.json"
_khoa = threading.Lock()
_dang_chay = threading.Lock()   # heartbeat 5 phút mở luồng mới — một lượt một lúc, kẻo hỏi đúp

SO_NGAY = {"ngay_thuong": 21, "cuoi_tuan": 35}
NGUONG = 0.85
IT_NHAT = 8
KHUNG_PHUT = 60
BUOC_PHUT = 15
#: Hỏi sau khi hết khung chừng này phút (cho người ta trễ một chút).
TRE_PHUT = 15
#: Chỉ hỏi trong khung này (giờ địa phương) — khung kết thúc khuya thì thôi, sáng mai đã cũ.
GIO_HOI = (7, 22)
TOI_DA_HOI_NGAY = 3
#: Câu hỏi còn chờ trả lời trong chừng này giây.
HAN_TRA_LOI = 4 * 3600
#: Miền HA của thiết bị LÀM việc (bật/tắt/chạy). Cảm biến không có «nếp hoạt động» theo nghĩa này.
MIEN = ("light.", "switch.", "fan.", "vacuum.", "media_player.", "climate.", "water_heater.", "cover.",
        "lock.", "lawn_mower.", "valve.", "humidifier.")
_KHONG_PHAI = ("unavailable", "unknown", "none", "")
_LECH_GIO = 7 * 3600  # Asia/Ho_Chi_Minh; cùng cách tính ngày với lich_su_nha.soi_hong

_hoc_cache: dict[str, Any] = {"ngay": None, "nep": {}}


def _cfg() -> dict[str, Any]:
    from services.config import config
    raw = (config.data.get("mqtt") or {}).get("lech_nep")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("bat", False))


def _nap() -> dict[str, Any]:
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _luu(d: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_PATH)


def _ngay(ts: float) -> int:
    return int((ts + _LECH_GIO) // 86400)


def _phut(ts: float) -> int:
    return int(((ts + _LECH_GIO) % 86400) // 60)


def _loai_ngay(n: int) -> str:
    return "cuoi_tuan" if time.gmtime(n * 86400).tm_wday >= 5 else "ngay_thuong"


def _hh(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _hoat_dong(tu: float, den: float) -> dict[str, list[float]]:
    """{thiết bị: [ts đổi trạng thái]} — gộp cặp gương light/switch về thực thể bọc ngoài."""
    from services import ha_client, lich_su_nha

    rows = lich_su_nha.doc_cua_so(tu, den, tien_to=MIEN, truong=("state",), tran=200_000)
    ev: dict[str, list[float]] = collections.defaultdict(list)
    for r in rows:
        if str(r.get("gia_tri")).lower() in _KHONG_PHAI:
            continue
        tb = str(r["thiet_bi"])
        try:
            tb = ha_client.thuc_the_boc(tb) or tb
        except Exception:  # noqa: BLE001 — chưa có chỉ mục gương thì để nguyên
            pass
        ev[tb].append(float(r["ts"]))
    return ev


def _nep_cua(tss: list[float], ngay_toi: int, ngay_dau: int) -> list[dict[str, Any]]:
    theo: dict[int, set[int]] = collections.defaultdict(set)
    for t in tss:
        n = _ngay(t)
        if ngay_toi - max(SO_NGAY.values()) <= n < ngay_toi:
            theo[n].add(_phut(t))
    ra: list[dict[str, Any]] = []
    for lo in ("ngay_thuong", "cuoi_tuan"):
        ds = [n for n in range(max(ngay_toi - SO_NGAY[lo], ngay_dau), ngay_toi) if _loai_ngay(n) == lo]
        if len(ds) < IT_NHAT:
            continue
        for bd in range(0, 1440, BUOC_PHUT):
            k = sum(1 for n in ds if any(bd <= m < bd + KHUNG_PHUT for m in theo.get(n, ())))
            if k / len(ds) < NGUONG:
                continue
            if ra and ra[-1]["loai"] == lo and bd <= ra[-1]["den"]:
                ra[-1]["den"] = bd + KHUNG_PHUT
                ra[-1]["ti_le"] = max(ra[-1]["ti_le"], k / len(ds))
            else:
                ra.append({"loai": lo, "tu": bd, "den": bd + KHUNG_PHUT, "ti_le": k / len(ds), "so_ngay": len(ds)})
    return ra


def hoc(now: float | None = None) -> dict[str, list[dict[str, Any]]]:
    """Nếp của mọi thiết bị, học lại MỖI NGÀY một lần (lịch sử không đổi trong ngày)."""
    now = now or time.time()
    hom = _ngay(now)
    if _hoc_cache["ngay"] == hom:
        return _hoc_cache["nep"]
    ev = _hoat_dong(now - (max(SO_NGAY.values()) + 1) * 86400, now)
    dau = _ngay(min((min(v) for v in ev.values()), default=now))   # doc_cua_so trả MỚI trước — đừng lấy v[0]
    nep = {tb: n for tb, tss in ev.items() if (n := _nep_cua(tss, hom, dau))}
    _hoc_cache.update(ngay=hom, nep=nep)
    logger.info({"event": "lech_nep_hoc", "so_thiet_bi": len(nep)})
    return nep


def _ten(tb: str) -> str:
    from services import ha_client
    st = ha_client.get_state(tb) or {}
    return str((st.get("attributes") or {}).get("friendly_name") or tb)


def _ly_do(tb: str) -> str:
    from services import su_co_thiet_bi
    cd = su_co_thiet_bi.chan_doan(tb)
    if cd["nguyen_nhan"]:
        return f"Em đo được: {cd['nguyen_nhan']}" + (f" — {cd['chi_tiet']}." if cd["chi_tiet"] else ".")
    return "Thiết bị vẫn kết nối bình thường — có lẽ chỉ là hôm nay chưa ai dùng."


def lech_hom_nay(now: float | None = None) -> list[dict[str, Any]]:
    """Các nếp ĐÃ QUÁ GIỜ hôm nay mà thiết bị chưa hoạt động (chưa xét đã hỏi / tắt / giờ hỏi)."""
    now = now or time.time()
    hom, m_now = _ngay(now), _phut(now)
    nep = hoc(now)
    if not nep:
        return []
    nua_dem = now - m_now * 60 - (now % 60)
    hom_nay = _hoat_dong(nua_dem, now)
    ra = []
    for tb, ds in nep.items():
        for n in ds:
            if n["loai"] != _loai_ngay(hom) or m_now < n["den"] + TRE_PHUT:
                continue
            if any(n["tu"] <= _phut(t) < n["den"] + TRE_PHUT for t in hom_nay.get(tb, ())):
                continue
            ra.append({"thiet_bi": tb, **n})
    return ra


def quet(now: float | None = None) -> int:
    """Heartbeat: hỏi các nếp vừa lệch. Trả số câu đã hỏi."""
    now = now or time.time()
    if not is_enabled():
        return 0
    gio = time.localtime(now).tm_hour
    if not GIO_HOI[0] <= gio < GIO_HOI[1]:
        return 0
    try:
        from services import lich_sinh_hoat
        if lich_sinh_hoat.ca_nha("vang", now):
            return 0
    except Exception:  # noqa: BLE001 — chưa có lịch thì cứ xét
        pass
    hom = _ngay(now)
    with _khoa:
        d = _nap()
    hoi = [h for h in d.get("hoi") or [] if now - float(h.get("luc") or 0) < 30 * 86400]
    da_hoi = {(h["thiet_bi"], h["tu"]) for h in hoi if h.get("ngay") == hom}
    nghi = {h["thiet_bi"] for h in hoi if h.get("ngay") == hom and h.get("loai") == "nghi"}
    tat, hong = d.get("tat") or {}, d.get("hong") or {}
    so = sum(1 for h in hoi if h.get("ngay") == hom)
    moi = 0
    from services import thong_bao
    for x in lech_hom_nay(now):
        tb = x["thiet_bi"]
        if so >= TOI_DA_HOI_NGAY:
            break
        if (tb, x["tu"]) in da_hoi or tb in nghi or f"{tb}|{x['tu']}" in tat or tb in hong:
            continue
        tin = (f"🔔 Hôm nay chưa thấy {_ten(tb)} hoạt động lúc {_hh(x['tu'])}–{_hh(x['den'])} như mọi khi "
               f"({x['ti_le']:.0%} {'ngày thường' if x['loai'] == 'ngay_thuong' else 'ngày cuối tuần'} gần đây "
               f"đều có).\n{_ly_do(tb)}\nCó chuyện gì không ạ? Anh nhắn lại tự nhiên là em hiểu "
               "(vd «mất mạng, tối sửa», «hôm nay đi vắng», «đổi nếp rồi, đừng hỏi nữa»).")
        gui = thong_bao.gui("nha.lech_nep", tin)
        hoi.append({"thiet_bi": tb, "tu": x["tu"], "den": x["den"], "ngay": hom, "luc": now, "gui": gui})
        da_hoi.add((tb, x["tu"]))
        so += 1
        moi += 1
        logger.info({"event": "lech_nep_hoi", "thiet_bi": tb, "khung": f"{_hh(x['tu'])}-{_hh(x['den'])}", "gui": gui})
    if moi:
        with _khoa:
            d = _nap()
            d["hoi"] = hoi
            _luu(d)
    return moi


def _bo_hong_da_chay(d: dict[str, Any], now: float) -> None:
    """Thiết bị chủ nhà báo hỏng mà đã hoạt động lại sau lúc báo → hết «hỏng», hỏi lại như thường."""
    hong = d.get("hong") or {}
    if not hong:
        return
    ev = _hoat_dong(min(float(v) for v in hong.values()), now)
    d["hong"] = {tb: v for tb, v in hong.items() if not any(t > float(v) for t in ev.get(tb, ()))}


def tra_loi(text: str, *, nguoi: str = "", now: float | None = None) -> str | None:
    """Câu trả lời tự nhiên cho câu hỏi lệch nếp đang chờ. None = không phải (để handler khác xử lý)."""
    now = now or time.time()
    chu = " ".join(str(text or "").split())
    if not chu:
        return None
    with _khoa:
        d = _nap()
    cho = [h for h in d.get("hoi") or [] if not h.get("loai") and now - float(h.get("luc") or 0) < HAN_TRA_LOI]
    if not cho:
        return None
    h = max(cho, key=lambda x: float(x["luc"]))
    from services import hieu_thiet_bi_nha as ht
    huong, _ = ht.huong_dan("lech_nep")
    de = (f"A. Em đã hỏi lúc {time.strftime('%H:%M', time.localtime(float(h['luc'])))}: hôm nay chưa thấy "
          f"{_ten(h['thiet_bi'])} hoạt động lúc {_hh(h['tu'])}–{_hh(h['den'])} như mọi khi.\nB. Chủ nhà nhắn: {chu[:400]}")
    r = ht._goi_model(ht._model(), huong, de)
    if r.get("error"):
        logger.warning({"event": "lech_nep_hieu_loi", "loi": str(r["error"])[:160]})
        return None
    data = ht._doc_json(str(((r.get("choices") or [{}])[0].get("message") or {}).get("content") or "")) or {}
    loai = str(data.get("loai") or "")
    if loai not in ("hong", "nghi", "doi_nep"):
        return None
    with _khoa:
        d = _nap()
        for x in d.get("hoi") or []:
            if x.get("luc") == h["luc"] and x.get("thiet_bi") == h["thiet_bi"]:
                x.update(loai=loai, tra_loi=chu[:300], nguoi=nguoi)
        if loai == "hong":
            d.setdefault("hong", {})[h["thiet_bi"]] = now
        elif loai == "doi_nep":
            d.setdefault("tat", {})[f"{h['thiet_bi']}|{h['tu']}"] = now
        _luu(d)
    if loai in ("hong", "doi_nep"):
        # Dữ kiện chủ nhà nói về thiết bị — các tầng học đọc được (vd đừng học nếp từ ngày thiết bị hỏng).
        try:
            ht.ghi_du_kien(f"{_ten(h['thiet_bi'])}: {chu[:200]}", nguoi=nguoi, nguon="lech_nep")
        except Exception as exc:  # noqa: BLE001
            logger.info({"event": "lech_nep_ghi_du_kien_loi", "loi": str(exc)[:120]})
    logger.info({"event": "lech_nep_tra_loi", "thiet_bi": h["thiet_bi"], "loai": loai})
    return str(data.get("dap") or "Dạ em ghi nhận rồi ạ.")[:300]


def chay_mot_lan(now: float | None = None) -> int:
    """Heartbeat gọi: dọn «hỏng» đã chạy lại, rồi quét."""
    now = now or time.time()
    if not is_enabled() or not _dang_chay.acquire(blocking=False):
        return 0
    try:
        with _khoa:
            d = _nap()
            if d.get("hong"):
                _bo_hong_da_chay(d, now)
                _luu(d)
        return quet(now)
    finally:
        _dang_chay.release()


def _reset_for_tests(duong: Path) -> None:
    global _PATH
    _PATH = duong
    _hoc_cache.update(ngay=None, nep={})
