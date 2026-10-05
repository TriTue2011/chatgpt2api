"""THỜI GIAN ở lại / vắng của từng thiết bị: hỏi chủ nhà xác nhận từng cái, rồi theo CHU KỲ HỌC rút LỜI KHUYÊN từ nhật
ký kích hoạt — chủ nhà «đồng ý» thì đổi, «không» thì giữ.

Chủ máy 05/10/2026: "Thời gian ở lại, thời gian vắng nữa. Từng cái 1, sau đó kết hợp nhật ký để đưa ra lời khuyên,
đồng ý thì làm theo lời khuyên, không thì giữ nguyên. Lời khuyên này chính trong các chu kỳ học hỏi. Chu kỳ lúc đầu theo
cơ chế tăng dần, ví dụ 2 lần 5 ngày, sau đó 4 lần 7 ngày, rồi đến 1 tháng 1 lần".

Lời khuyên theo NGUYÊN TẮC, đo trên nhật ký thật (14 ngày tới 05/10/2026):
* bot BẬT rồi NGƯỜI tắt trong 5 phút = bật khi người không cần (đi ngang) → nên chờ người ở lại LÂU hơn
  (đèn ngủ 4/7 lần, đèn trần 3/21);
* bot TẮT rồi NGƯỜI bật lại trong 5 phút = tắt khi người vẫn ở đó (ngồi yên, cảm biến mất dấu) → nên chờ VẮNG lâu hơn
  (đèn trần 6/36, đèn ngủ 3/8, quạt 3/21);
* nhiều lần tắt mà KHÔNG lần nào bị bật lại → có thể rút ngắn thời gian vắng (tiết kiệm điện) — đề xuất, chủ nhà quyết.
Bot tự TẮT ngay sau khi tự bật không tính là lỗi: đèn bật cho người đi ngang rồi tắt khi vắng là đúng việc.

Thời gian vừa đổi (khác lần chụp của chu kỳ trước) thì chu kỳ này KHÔNG khuyên về nó: dữ liệu cũ là của số cũ.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

_PATH = Path(DATA_DIR) / "agent" / "loi_khuyen_nha.json"
_khoa = threading.RLock()

#: Khoảng cách (ngày) giữa các chu kỳ: dày lúc đầu, giãn dần; hết danh sách thì mỗi tháng một lần.
CHU_KY_NGAY = (5, 5, 7, 7, 7, 7)
THANG_NGAY = 30
#: Đảo lại trong ngần này giây sau lần bot làm = lần làm đó sai.
CUA_SO_GIAY = 300
#: Nhật ký kích hoạt chỉ giữ 14 ngày (`nhat_ky_kich_hoat.GIU_NGAY`).
NHAT_KY_NGAY = 14
#: Cần ít nhất ngần này lần đảo, và chiếm ít nhất tỉ lệ này số lần bot làm, mới khuyên tăng.
DAO_TOI_THIEU, DAO_TI_LE = 2, 0.15
#: Khuyên RÚT NGẮN vắng chỉ khi bot đã tắt ít nhất ngần này lần mà không lần nào bị bật lại.
RUT_TOI_THIEU = 10

_TEN = {"o_lai": "thời gian ở lại", "vang": "thời gian vắng"}


def _nap() -> dict[str, Any]:
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _luu(d: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_PATH)


# ── Số đang dùng ────────────────────────────────────────────────────────────
def gia_tri(tb: str) -> dict[str, float | None]:
    """{o_lai: giây | None (bật ngay), vang: giây} đang dùng — số chủ nhà đặt, không thì số bot học."""
    from services import kich_hoat_nha as kh
    cd = kh.ds_thiet_bi().get(tb) or {}
    p = kh.phut_o_lai(tb)
    return {"o_lai": round(p * 60) if p else None, "vang": round(kh.phut_vang(cd, time.time()) * 60)}


def doc_giay(g: float | None) -> str:
    if not g:
        return "bật ngay khi có người vào (không chờ)"
    g = int(round(g))
    if g < 60:
        return f"{g} giây"
    p, s = divmod(g, 60)
    return f"{p} phút" + (f" {s} giây" if s else "")


def doc_so(text: str) -> float | None:
    """«30 giây», «2 phút», «1 phút 30», «90s», «0» → giây. None = không đọc được."""
    t = str(text or "").lower().replace(",", ".")
    tong, co = 0.0, False
    for so, dv in re.findall(r"(\d+(?:\.\d+)?)\s*(giây|giay|s\b|phút|phut|p\b|'|)", t):
        co = True
        tong += float(so) * (60 if dv in ("phút", "phut", "p", "'") else 1)
    if not co:
        return None
    # «1 phút 30» — số trơn đứng sau phút là giây; số trơn duy nhất là giây.
    return tong


def dat(tb: str, loai: str, giay: float) -> None:
    from services import kich_hoat_nha as kh
    if loai == "o_lai":
        kh.dat_thiet_bi(tb, o_lai_giay=float(giay))
    else:
        kh.dat_thiet_bi(tb, roi_giay=float(giay))
    with _khoa:
        d = _nap()
        d.setdefault("chup", {}).setdefault(tb, {})[loai] = gia_tri(tb)[loai]
        _luu(d)


# ── Câu xác nhận từng thời gian ─────────────────────────────────────────────
def muc_xac_nhan(tb: str) -> list[dict[str, Any]]:
    """Hai câu (ở lại, vắng) cho hàng hỏi của `luat_duyet` — mỗi câu MỘT thời gian."""
    gt = gia_tri(tb)
    return [{"kieu": "cai_dat", "tb": tb, "loai": k, "cu": gt[k]} for k in ("o_lai", "vang")]


# ── Đo nhật ký → lời khuyên ─────────────────────────────────────────────────
def do(tb: str, tu: float, den: float | None = None) -> dict[str, int]:
    """Đếm trên nhật ký kích hoạt: lần bot bật / tắt, lần NGƯỜI đảo lại trong ``CUA_SO_GIAY``."""
    import sqlite3
    from services import nhat_ky_kich_hoat as nk
    ro = sqlite3.connect(f"file:{nk._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    try:
        ev = ro.execute("SELECT ts, hanh_dong, ket_qua FROM nhat_ky WHERE thiet_bi=? AND ket_qua IN ('lam','nguoi')"
                        " AND ts>=? AND ts<? ORDER BY ts", (tb, tu, den or time.time())).fetchall()
    finally:
        ro.close()
    ra = {"bot_bat": 0, "bot_tat": 0, "bat_bi_tat": 0, "tat_bi_bat": 0}
    for i, (t, hd, kq) in enumerate(ev):
        if kq != "lam":
            continue
        ra["bot_bat" if hd == "on" else "bot_tat"] += 1
        if i + 1 < len(ev):
            t2, hd2, kq2 = ev[i + 1]
            if kq2 == "nguoi" and hd2 != hd and float(t2) - float(t) <= CUA_SO_GIAY:
                ra["bat_bi_tat" if hd == "on" else "tat_bi_bat"] += 1
    return ra


def _lam_tron(g: float) -> int:
    return int(round(g / 5) * 5) if g < 60 else int(round(g / 30) * 30)


def khuyen(tb: str, gt: dict[str, float | None], so: dict[str, int], ngay: float) -> list[dict[str, Any]]:
    """Lời khuyên cho một thiết bị (rỗng = không có gì nên đổi)."""
    ra = []
    n, sai = so["bot_bat"], so["bat_bi_tat"]
    if sai >= DAO_TOI_THIEU and sai >= DAO_TI_LE * n:
        cu = gt["o_lai"]
        moi = min(600, _lam_tron(max(30.0, 2 * float(cu or 0))))
        ra.append({"kieu": "khuyen", "tb": tb, "loai": "o_lai", "cu": cu, "moi": moi,
                   "vi": f"{ngay:.0f} ngày qua em tự bật {n} lần, {sai} lần anh tắt lại ngay trong 5 phút — người "
                         "chỉ đi ngang, chưa cần"})
    n, sai = so["bot_tat"], so["tat_bi_bat"]
    cu = float(gt["vang"] or 0)
    if cu and sai >= DAO_TOI_THIEU and sai >= DAO_TI_LE * n:
        ra.append({"kieu": "khuyen", "tb": tb, "loai": "vang", "cu": cu, "moi": min(3600, _lam_tron(cu * 1.5)),
                   "vi": f"{ngay:.0f} ngày qua em tự tắt {n} lần, {sai} lần anh phải bật lại trong 5 phút — người "
                         "vẫn ở đó, cảm biến mất dấu"})
    elif cu > 90 and sai == 0 and n >= RUT_TOI_THIEU:
        ra.append({"kieu": "khuyen", "tb": tb, "loai": "vang", "cu": cu, "moi": max(60, _lam_tron(cu * 0.75)),
                   "vi": f"{ngay:.0f} ngày qua em tự tắt {n} lần, không lần nào anh phải bật lại — rút ngắn cho đỡ "
                         "tốn điện"})
    return ra


# ── Chu kỳ ──────────────────────────────────────────────────────────────────
def cach_ngay(lan_da: int) -> int:
    return CHU_KY_NGAY[lan_da] if lan_da < len(CHU_KY_NGAY) else THANG_NGAY


def chu_ky(now: float | None = None) -> dict[str, Any]:
    """Trạng thái chu kỳ: đã chạy mấy lần, lần cuối, lần tới."""
    now = float(now or time.time())
    with _khoa:
        d = _nap()
        ck = d.get("chu_ky")
        if not ck:
            ck = d["chu_ky"] = {"lan": 0, "luc": now}       # bắt đầu đếm từ lần đầu được hỏi
            _luu(d)
    return {**ck, "toi": float(ck["luc"]) + cach_ngay(int(ck["lan"])) * 86400}


def chay(now: float | None = None) -> list[dict[str, Any]]:
    """Tới kỳ thì rút lời khuyên cho mọi thiết bị đang bật và xếp vào hàng hỏi. Trả các lời khuyên (rỗng nếu chưa tới
    kỳ hoặc không có gì nên đổi)."""
    from services import kich_hoat_nha as kh, luat_duyet
    now = float(now or time.time())
    ck = chu_ky(now)
    if now < ck["toi"]:
        return []
    ngay = min(NHAT_KY_NGAY, (now - float(ck["luc"])) / 86400)
    ra: list[dict[str, Any]] = []
    with _khoa:
        d = _nap()
        chup = d.setdefault("chup", {})
        for tb, cd in kh.ds_thiet_bi().items():
            if not cd.get("bat"):
                continue
            gt = gia_tri(tb)
            cu = chup.get(tb) or {}
            for x in khuyen(tb, gt, do(tb, now - ngay * 86400, now), ngay):
                if x["loai"] in cu and cu[x["loai"]] != gt[x["loai"]]:
                    continue                    # vừa đổi giữa kỳ: dữ liệu là của số cũ
                ra.append(x)
            chup[tb] = gt
        d["chu_ky"] = {"lan": int(ck["lan"]) + 1, "luc": now}
        _luu(d)
    logger.info({"event": "loi_khuyen_chu_ky", "lan": ck["lan"] + 1, "so": len(ra)})
    if ra:
        luat_duyet.xep_hoi(ra)
    return ra


def _reset_for_tests(duong: Path) -> None:
    global _PATH
    _PATH = duong
