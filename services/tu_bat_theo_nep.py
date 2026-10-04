"""TỰ BẬT THEO NẾP — thiết bị chủ nhà dùng theo GIỜ (bình nóng lạnh, máy lọc nước…): học giờ bật và thời lượng từ các
lần NGƯỜI bật, tới giờ thì bật, tự tắt sau thời lượng học được, báo kèm «đúng / sai».

Chủ máy 05/10/2026: "Với thời gian, thời tiết hiện tại thì bot có bật bình nóng lạnh không, bật thì lúc mấy giờ, bật
chế độ tự bật bình nóng lạnh luôn". Bình nóng lạnh nằm trong `du_doan_nha._KHONG_TU_LAM` (không bao giờ tự làm theo
CẢM BIẾN) — đường này khác: chỉ chạy khi chủ nhà BẬT TAY cho từng thiết bị, theo LỊCH rút từ chính thói quen nhà,
có chốt an toàn: chỉ khi nhà có người, tự tắt (tối đa `MAX_PHUT`), hôm nay người đã tự bật thì thôi.

Đo 05/10/2026 (22 ngày): người bật 24 lần, 20/22 ngày; giờ bật 15:36–19:38, giữa ~17:00; bật trung vị 18 phút, p90
25, max 29; ngày mát (≤ 26°C) bật lâu hơn ngày nóng.

Học CHỈ từ lần NGƯỜI bật (do_ai=0) — bot bật rồi tự học lại từ chính mình là tự khẳng định vòng quanh (bẫy 3 của tầng
học nhà). Giờ bật = trung vị phút-trong-ngày của lần bật đầu mỗi ngày. Thời lượng = p75 các lần bật, chia theo nhiệt
độ lúc bật nếu đủ mẫu mỗi bên.
"""
from __future__ import annotations

import bisect
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

_PATH = Path(DATA_DIR) / "agent" / "tu_bat_theo_nep.json"
_khoa = threading.Lock()
_LECH_GIO = 7 * 3600            # Asia/Ho_Chi_Minh — cùng cách tính ngày với lich_su_nha / lech_nep

SO_NGAY = 60                    # cửa sổ học
IT_NHAT_NGAY = 7                # ít nhất ngần này NGÀY có người bật mới gọi là nếp
TY_LE_NGAY = 0.6                # và ≥ 60% số ngày trong cửa sổ có dùng
KHUNG_PHUT = 20                 # tới giờ nếp, còn trong ngần này phút thì bật (heartbeat 5 phút một lần)
MIN_PHUT, MAX_PHUT = 5, 45      # chặn thời lượng tự bật — cứng, không học vượt
MAU_MOI_BEN = 5                 # đủ ngần này mẫu mỗi bên nhiệt độ mới chia theo trời nóng / mát


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


def _hh(m: float) -> str:
    m = int(round(m)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


# ── Cài đặt ─────────────────────────────────────────────────────────────────
def cai_dat() -> dict[str, dict[str, Any]]:
    """{thiết bị: {"bat": bool, "nhiet": mã cảm biến nhiệt độ ngoài trời | None}} — chỉ chủ nhà bật."""
    with _khoa:
        return dict(_nap().get("thiet_bi") or {})


def dat(tb: str, bat: bool, nhiet: str | None = None) -> dict[str, Any]:
    with _khoa:
        d = _nap()
        x = d.setdefault("thiet_bi", {}).setdefault(tb, {})
        x["bat"] = bool(bat)
        if nhiet is not None:
            x["nhiet"] = nhiet or None
        _luu(d)
        return dict(x)


# ── Học nếp ─────────────────────────────────────────────────────────────────
def _db() -> sqlite3.Connection | None:
    from services import lich_su_nha
    try:
        return sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    except sqlite3.Error:
        return None


def nep(tb: str, now: float | None = None, nhiet: str | None = None,
        ro: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Nếp dùng của một thiết bị. ``du`` = đủ để tự bật. Không đủ thì ``ly_do`` nói vì sao."""
    now = float(now or time.time())
    dong = ro is None
    if ro is None:
        ro = _db()
        if ro is None:
            return {"du": False, "ly_do": "không đọc được lịch sử"}
    try:
        ev = [(float(t), str(g), int(d or 0)) for t, g, d in ro.execute(
            "SELECT ts, gia_tri, do_ai FROM su_kien WHERE thiet_bi=? AND truong='state' AND ts>? ORDER BY ts",
            (tb, now - SO_NGAY * 86400))]
        nd: list[tuple[float, float]] = []
        if nhiet:
            nd = [(float(o) * 300, float(tb_)) for o, tb_ in ro.execute(
                "SELECT o_5p, tb FROM so_do WHERE thiet_bi=? AND o_5p>? ORDER BY o_5p",
                (nhiet, int((now - SO_NGAY * 86400) // 300)))]
    finally:
        if dong:
            ro.close()
    if not ev:
        return {"du": False, "ly_do": "chưa có lịch sử bật/tắt"}

    nd_ts = [t for t, _ in nd]

    def _nhiet_luc(t: float) -> float | None:
        i = bisect.bisect_right(nd_ts, t) - 1
        return nd[i][1] if i >= 0 else None

    dau_ngay: dict[int, float] = {}
    mau: list[tuple[float, float | None]] = []        # (phút bật, nhiệt độ lúc bật) — chỉ lần NGƯỜI bật
    for i, (t, g, d) in enumerate(ev):
        if g != "on" or d:
            continue
        dau_ngay.setdefault(_ngay(t), t)
        tat = next((t2 for t2, g2, _ in ev[i + 1:] if g2 != "on"), None)
        if tat is not None and 0 < tat - t < 3 * 3600:
            mau.append(((tat - t) / 60, _nhiet_luc(t)))
    so_ngay_dung = len(dau_ngay)
    tong_ngay = max(1, _ngay(now) - _ngay(ev[0][0]))
    ty_le = so_ngay_dung / tong_ngay
    if so_ngay_dung < IT_NHAT_NGAY:
        return {"du": False, "so_ngay": so_ngay_dung, "ly_do": f"mới {so_ngay_dung} ngày có người bật (cần {IT_NHAT_NGAY})"}
    if ty_le < TY_LE_NGAY:
        return {"du": False, "so_ngay": so_ngay_dung, "ty_le_ngay": round(ty_le, 2),
                "ly_do": f"chỉ {ty_le:.0%} số ngày có dùng (cần {TY_LE_NGAY:.0%}) — chưa thành nếp"}
    phut = sorted(_phut(t) for t in dau_ngay.values())
    gio = phut[len(phut) // 2]

    def _p75(ds: list[float]) -> float:
        s = sorted(ds)
        return s[min(len(s) - 1, int(len(s) * 0.75))]

    tat_ca = [m for m, _ in mau]
    if not tat_ca:
        return {"du": False, "so_ngay": so_ngay_dung, "ly_do": "chưa có lần bật nào có giờ tắt"}
    thoi_luong = _p75(tat_ca)
    nhiet_nay = None
    co_nd = [(m, n) for m, n in mau if n is not None]
    chia = ""
    if nd and len(co_nd) >= 2 * MAU_MOI_BEN:
        ns = sorted(n for _, n in co_nd)
        giua = (ns[len(ns) // 2 - 1] + ns[len(ns) // 2]) / 2      # mốc GIỮA hai nửa — trung vị `<=` dồn cụm về một bên
        mat = [m for m, n in co_nd if n <= giua]
        nong = [m for m, n in co_nd if n > giua]
        nhiet_nay = _nhiet_luc(now) if nd_ts and now - nd_ts[-1] < 3600 else None
        if nhiet_nay is not None and len(mat) >= MAU_MOI_BEN and len(nong) >= MAU_MOI_BEN:
            thoi_luong = _p75(mat if nhiet_nay <= giua else nong)
            chia = f"trời {'mát' if nhiet_nay <= giua else 'nóng'} ({nhiet_nay:.0f}°C, mốc {giua:.0f}°C)"
    tran = min(MAX_PHUT, max(tat_ca) + 5)
    thoi_luong = max(MIN_PHUT, min(tran, round(thoi_luong)))
    return {"du": True, "gio_phut": gio, "gio": _hh(gio), "so_ngay": so_ngay_dung, "ty_le_ngay": round(ty_le, 2),
            "phut_bat": thoi_luong, "nhiet": nhiet_nay, "chia": chia, "so_mau": len(tat_ca)}


# ── Chạy ────────────────────────────────────────────────────────────────────
def _nguoi_da_bat_hom_nay(tb: str, now: float) -> bool:
    ro = _db()
    if ro is None:
        return False
    try:
        dau = now - (_phut(now) * 60 + (now % 60))
        return ro.execute("SELECT 1 FROM su_kien WHERE thiet_bi=? AND truong='state' AND gia_tri='on' AND do_ai=0"
                          " AND ts>=? LIMIT 1", (tb, dau)).fetchone() is not None
    finally:
        ro.close()


def _tat(tb: str, ly_do: str) -> None:
    from services import ha_client, kich_hoat_nha as kh
    with _khoa:
        d = _nap()
        l = (d.get("lam") or {}).get(tb) or {}
        if not l or l.get("xong"):
            return
        l["xong"] = True
        _luu(d)
    if str((ha_client.get_state(tb) or {}).get("state") or "").lower() != "on":
        return                                   # người đã tắt trước — thôi
    if kh._lam(tb, "off", tu_lam=True):
        kh._nk(tb, "off", "lam", "theo nếp", ly_do)


def _hen_tat(tb: str, giay: float) -> None:
    t = threading.Timer(max(1.0, giay), _tat, args=(tb, "theo nếp: hết thời lượng tự bật"))
    t.daemon = True
    t.start()


def xet(tb: str, now: float | None = None) -> str:
    """Một lượt cho một thiết bị: tới giờ thì bật, quá giờ tắt thì tắt. Trả câu mô tả (cho heartbeat / test)."""
    from services import du_doan_nha as dd, ha_client, kich_hoat_nha as kh, thong_bao
    now = float(now or time.time())
    cd = cai_dat().get(tb) or {}
    if not cd.get("bat"):
        return "chưa bật chế độ"
    with _khoa:
        l = dict(((_nap().get("lam") or {}).get(tb)) or {})
    # Tắt: dự phòng khi container khởi động lại làm mất hẹn giờ.
    if l and not l.get("xong") and now >= float(l.get("tat_luc") or 0):
        _tat(tb, "theo nếp: hết thời lượng tự bật")
        return "tới giờ tắt"
    if l.get("ngay") == _ngay(now):
        return "hôm nay đã xử lý"
    n = nep(tb, now, cd.get("nhiet"))
    if not n.get("du"):
        return f"chưa đủ nếp: {n.get('ly_do')}"
    lech = _phut(now) - int(n["gio_phut"])
    if not 0 <= lech <= KHUNG_PHUT:
        return f"chưa tới giờ ({n['gio']})"

    def _ghi_ngay(**k: Any) -> None:
        with _khoa:
            d = _nap()
            d.setdefault("lam", {})[tb] = {"ngay": _ngay(now), **k}
            _luu(d)

    if str((ha_client.get_state(tb) or {}).get("state") or "").lower() == "on" or _nguoi_da_bat_hom_nay(tb, now):
        _ghi_ngay(xong=True, bo_qua="người đã bật hôm nay")
        kh._nk(tb, "on", "khong", "theo nếp", "người đã tự bật hôm nay — không bật thêm")
        return "người đã bật hôm nay"
    if not kh.nha_co_nguoi(set(), now, tb):
        _ghi_ngay(xong=True, bo_qua="nhà vắng")
        kh._nk(tb, "on", "khong", "theo nếp", f"tới giờ nếp {n['gio']} nhưng nhà không có ai — không bật")
        return "nhà vắng"
    if not kh._lam(tb, "on", tu_lam=True):
        _ghi_ngay(xong=True, bo_qua="lệnh không tới")
        kh._nk(tb, "on", "khong", "theo nếp", "lệnh bật không tới thiết bị")
        return "lệnh không tới"
    phut = float(n["phut_bat"])
    tat_luc = now + phut * 60
    id_ = dd.ghi_nhan(f"{tb}#on", "on", 1.0, {"nguon": "theo nếp", "phut_bat": phut}, "tu_lam")
    _ghi_ngay(xong=False, tat_luc=tat_luc, id=id_)
    _hen_tat(tb, tat_luc - now)
    ly = (f"theo nếp: anh hay bật khoảng {n['gio']} ({n['so_ngay']} ngày), bật {phut:.0f} phút"
          + (f" vì {n['chia']}" if n.get("chia") else ""))
    kh._nk(tb, "on", "lam", "theo nếp", ly)
    thong_bao.gui("nha.goi_y",
                  f"🤖 #{id_} Em đã bật {kh._ten_tb(tb)} theo nếp nhà (anh hay bật khoảng {n['gio']}"
                  + (f"; {n['chia']}" if n.get("chia") else "")
                  + f"), tự tắt lúc {_hh(_phut(tat_luc))}.\nĐúng hay sai ạ? Anh trả lời «đúng» hoặc «sai» — "
                    "sai thì em tắt ngay.")
    return f"đã bật, tắt lúc {_hh(_phut(tat_luc))}"


def chay_mot_lan(now: float | None = None) -> list[str]:
    ra = []
    for tb, cd in cai_dat().items():
        if cd.get("bat"):
            try:
                ra.append(f"{tb}: {xet(tb, now)}")
            except Exception as exc:  # noqa: BLE001 — một thiết bị hỏng không chặn thiết bị khác
                logger.warning({"event": "tu_bat_theo_nep_loi", "thiet_bi": tb, "error": str(exc)[:200]})
    return ra


def _reset_for_tests(duong: Path) -> None:
    global _PATH
    _PATH = duong
