"""Học "KHI … NẾU … THÌ bật/tắt" theo SỰ KIỆN KÍCH HOẠT, rồi hỏi — đủ tin thì tự làm.

Chủ máy 26/09/2026: "Đèn trần được bật khi nào gồm thời gian hay bật, khi đó cảm biến
hiện diện báo gì, chỉ số lux bao nhiêu, cam có người không, khi kích hoạt cảm biến nào.
Những cái đó tổng hợp lại mới là điều kiện bật đèn trần. Nhưng có thể có ngoại lệ …
buổi đêm thường hay tắt đèn kể cả có người." Rồi: "test điều khiển của bot với đèn
phòng ngủ. Bật tắt đèn và có hỏi lại … sau số lần thấy tôi trả lời đúng thì bot tự
động làm. Tôi không cần phải trả lời."

Vì sao KHÔNG dùng lại cách của `du_doan_nha` (đếm ô 30 phút, Naive Bayes):

* Câu hỏi "trong 30 phút tới có ai bật không" không khớp cách nhà dùng đèn. Đo 26/09/2026
  trên 30 ngày thật: 13 thiết bị, 7 ngày thử, Naive Bayes chưa lần nào đủ chắc để gợi ý.
* Naive Bayes CỘNG bằng chứng rời, không nói được "có người thì bật, TRỪ ban đêm".
  Cây quyết định nhỏ (sâu ≤ 3) nói được, và ra luật đọc bằng tiếng người.
* Cảm biến hiện diện nhảy liên tục (radar phòng khách ~1.000 lần/ngày) — trạng thái ở
  MỘT khoảnh khắc gần như ngẫu nhiên. Sự kiện "có người VÀO" (bật sau ≥ 3 phút tắt)
  thì có nghĩa.

NGUỒN KÍCH HOẠT LÀ CẢM BIẾN, và cảm biến nào thì DỮ LIỆU chọn, không do tên:

* Chỉ cảm biến nhị phân (``binary_sensor``: hiện diện, người trên camera, cửa…) — thứ
  QUAN SÁT nhà. Bật/tắt một đèn khác là một QUYẾT ĐỊNH khác của cùng người đó, đi kèm
  chứ không kích hoạt. Chủ máy 26/09/2026: đèn bếp trái, đèn nhà tắm "không liên quan,
  có khi bật sau, tắt trước". Đo: đèn bếp đứng trước đèn phòng ngủ 84 lần, đứng sau 88
  lần — việc làm kèm. Loại theo MIỀN chứ không theo tỉ lệ trước/sau: cảm biến thì đứng
  sau cũng nhiều vì người còn ở đó (hiện diện phòng ngủ 71 trước / 50 sau lần bật đèn
  phòng ngủ — chính là nguồn thật).
* Đứng trong 2 phút TRƯỚC lần người bật/tắt ở ≥ 5 lần. Đo: nguồn mạnh nhất của đèn
  trần phòng khách là CẢM BIẾN CỬA CHÍNH (47/100 lần bật) — không ai đoán ra từ tên.

BA CHỐT AN TOÀN:

1. Chỉ mở miệng khi luật của thiết bị qua KIỂM TIẾN DẦN (≥ 5 lần đoán trên 7 ngày cuối,
   ≥ 60% đúng) — cùng cổng của `du_doan_nha`.
2. Tự làm theo thang CỦA `du_doan_nha` (95% và ≥ 50 lượt được chấm, sai 2/10 là tụt;
   khoá cửa, bếp, bình nóng lạnh không bao giờ tự làm) — mỗi hướng bật/tắt một thang.
3. BÁO ẢO KHI NHÀ VẮNG — xem `nha_co_nguoi`.

Việc bot TỰ làm được ghi `do_ai=1` (`lich_su_nha.bot_tu_lam`) để lượt học sau không tự
khẳng định vòng quanh. Việc bot làm vì chủ máy trả lời «có» thì KHÔNG — đó là quyết
định của người, và chính câu trả lời ấy là nhãn học (xem `_nhan_da_cham`).
"""

from __future__ import annotations

import bisect
import json
import math
import re
import sqlite3
import threading
import time
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

_TZ = timezone(timedelta(hours=7))
_PATH = Path(DATA_DIR) / "agent" / "kich_hoat_nha.json"

#: Sự kiện đứng trong ngần này giây TRƯỚC lần người bật/tắt thì có thể là nguồn.
TRUOC = 120
#: Sau nguồn, người bật/tắt trong ngần này giây thì mẫu đó là "có làm".
CHO = 180
#: Cảm biến nhị phân tắt ≥ ngần này giây rồi bật lại mới là "có người VÀO"; tắt giữ
#: ngần này giây là "VẮNG".
VANG = 180
#: Nguồn phải đứng trước ≥ ngần này lần người làm (phần học).
NGUON_TOI_THIEU = 5
#: Ngần này thiết bị trở lên đổi trong cùng một giây là việc của máy, không phải người
#: (người không bấm 13 công tắc trong một giây) — cảnh "tắt hết", HA khởi động lại, dữ
#: liệu nạp lại. Kho thật có đúng ca này lúc 19:54:02 ngày 30/08/2026.
DONG_LOAT = 3
NGAY_HOC = 30
NGAY_THU = 7
#: Cây: sâu tối đa, mẫu tối thiểu mỗi lá, lợi ích tối thiểu (log-likelihood) để chia.
SAU = 3
LA_TOI_THIEU = 8
LOI_TOI_THIEU = 2.0
#: Ngưỡng mở miệng và cổng kiểm tiến dần — cùng số của `du_doan_nha`.
P_HOI = 0.75
KIEM_TOI_THIEU = 5
KIEM_TY_LE = 0.60
#: Cân nhắc THEO GIỜ (chủ máy 26/09/2026: "khi đi ngủ, kéo rèm đóng cửa thì vẫn có người,
#: lúc này có bật không" — "thì 1 là hỏi tôi"). Luật cây chỉ biết "từ 15:52", không biết
#: giờ ngủ vì dữ liệu giờ muộn ít; đo 30 ngày đèn phòng ngủ: lúc 23h luật sẽ bật 5/5 lần
#: có người vào, người bật 0/5. Nên xét thêm: những lần luật nói "bật" QUANH giờ này
#: (± QUANH_GIO), người thật sự bật bao nhiêu —
#: ≥ TIN_QUANH thì được tự làm; < IM_QUANH (rõ là KHÔNG — đo: 23h 2/9) thì im, không
#: nhắn Zalo đánh thức người ngủ; lưng chừng (22h: 7/15) hoặc chưa đủ MAU_QUANH lần thì HỎI.
QUANH_GIO = 1
MAU_QUANH = 5
TIN_QUANH = 0.9
IM_QUANH = 0.25
#: Khung giờ chủ máy đặt (26/09/2026: "tôi đặt khung giờ rồi bot đánh giá xem có cần bật
#: không, kiểu đọc sách. Hoặc quá giờ chưa muốn tắt"): trong khung, một hướng là
#: "hoi" (luôn hỏi — không tự làm, cũng không im) hoặc "khong" (không bao giờ làm).
CACH_KHUNG = ("hoi", "khong")
#: Giữ ngần này lần chặn báo ảo gần nhất để chủ máy xem trên trang Học hỏi.
BAO_AO_GIU = 20
#: Báo ảo: nhìn lại ngần này giây tìm dấu hiệu người.
AO_NHIN_LAI = 6 * 3600
HOC_LAI = 6 * 3600
#: Câu hỏi chờ quá ngần này thì thôi (không tính sai — `du_doan_nha` đổi thành 'lo').
HAN_HOI = 900
#: Cùng thiết bị, cùng hướng: không hỏi/làm lại trong ngần này giây.
NGHI_LAP = 600
#: Người vừa tự bật/tắt thiết bị trong ngần này giây thì người đang tự lo — không hỏi,
#: không làm. Đo 26/09/2026: 17 lần "có người vào phòng ngủ rồi tắt đèn" đều là vào lấy
#: đồ — bật đèn, radar báo chậm vài chục giây, rồi tắt. Không có chốt này bot sẽ hỏi
#: "tắt đèn không?" ngay sau khi người vừa bật.
NGUOI_VUA_CHAM = 300
#: Bot tự làm mà ngần này giây không ai làm ngược lại → lần đó ĐÚNG ("tôi không cần
#: phải trả lời"). Làm ngược lại trong khoảng đó → SAI. Cùng cửa sổ `soi_bi_huy`.
CHAM_TU_LAM = 600

HANH_DONG = ("on", "off")
_TEN_HD = {"on": "Bật", "off": "Tắt"}
#: Miền ĐIỀU KHIỂN được bằng turn_on/turn_off — cũng là miền mà một lần đổi do người
#: (do_ai=0) chứng tỏ có người ở nhà.
_MIEN_DIEU_KHIEN = ("switch", "light", "fan", "input_boolean", "media_player", "climate")
#: device_class của HA (tập đóng) nghĩa là "cảm thấy người" — chỉ nhóm này mới có thể
#: BÁO ẢO kiểu radar thấy người trong nhà vắng.
_LOP_HIEN_DIEN = ("occupancy", "presence", "motion")
#: device_class nghĩa là "có ai vừa mở" — người về nhà phải qua đây.
_LOP_CUA = ("door", "garage_door", "opening")
_KHONG_RO = {"unavailable", "unknown", "none", ""}

_khoa = threading.RLock()
#: Một lượt xét mỗi lúc — hai nguồn cùng lúc không hỏi hai lần. Tách khỏi `_khoa`: lượt
#: xét gọi mạng tới HA, giữ `_khoa` thì luồng `ha_live` phải chờ theo.
_khoa_xet = threading.Lock()
_du_lieu: dict[str, Any] | None = None
_dang_hoc: set[str] = set()
#: Sống: lần tắt gần nhất mỗi cảm biến nhị phân (cho "vào"), hẹn giờ "vắng".
_lan_off: dict[str, float] = {}
_hen_vang: dict[str, threading.Timer] = {}
#: Sống: hẹn giờ "tắt khi vắng" theo từng thiết bị.
_hen_tat: dict[str, threading.Timer] = {}
_cham_luc = 0.0


# ── Kho (cài đặt chủ máy + mô hình đã học) ─────────────────────────────────
def _nap() -> dict[str, Any]:
    global _du_lieu
    with _khoa:
        if _du_lieu is None:
            try:
                _du_lieu = json.loads(_PATH.read_text(encoding="utf-8")) if _PATH.is_file() else {}
            except Exception as exc:  # noqa: BLE001 — kho hỏng không được làm chết luồng HA
                logger.warning({"event": "kich_hoat_doc_loi", "error": str(exc)[:160]})
                _du_lieu = {}
            _du_lieu.setdefault("thiet_bi", {})
            _du_lieu.setdefault("mo_hinh", {})
        return _du_lieu


def _luu() -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_du_lieu, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_PATH)


def ds_thiet_bi() -> dict[str, dict[str, Any]]:
    """Thiết bị chủ máy bật cho học kích hoạt: {mã: cài đặt}."""
    return {k: dict(v) for k, v in _nap()["thiet_bi"].items() if v.get("bat")}


def dat_thiet_bi(tb: str, *, bat: bool | None = None, bo_nguon: list[str] | None = None,
                 ngoai_le: list[dict[str, str]] | None = None,
                 tu_lam: bool | None = None,
                 kiem_ao: dict[str, Any] | None = None,
                 tat_khi_vang: dict[str, Any] | None = None) -> dict[str, Any]:
    """Chủ máy sửa sơ đồ: bật/tắt, cho TỰ LÀM ngay, BỎ nguồn, đặt khung giờ NGOẠI LỆ
    (``{"hanh_dong": "on"|"off", "tu": "HH:MM", "den": "HH:MM"}`` — trong khung đó
    không bao giờ làm hướng ấy). Điều chủ máy đặt luôn thắng điều máy học."""
    tb = str(tb or "").strip()
    if tb.split(".")[0] not in _MIEN_DIEU_KHIEN or "." not in tb:
        raise ValueError(f"{tb or '(trống)'} không phải thiết bị bật/tắt được.")
    for x in ngoai_le or []:
        if x.get("hanh_dong") not in HANH_DONG or not all(
                re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(x.get(k) or "")) for k in ("tu", "den")):
            raise ValueError("Khung giờ phải có hanh_dong on/off và giờ dạng HH:MM.")
        if x.get("cach", "khong") not in CACH_KHUNG or len(str(x.get("ten") or "")) > 40:
            raise ValueError("Khung giờ: cách là «hoi» hoặc «khong», tên tối đa 40 chữ.")
    if kiem_ao is not None:
        kiem_ao = _kiem_kiem_ao(kiem_ao)
    if tat_khi_vang is not None:
        tat_khi_vang = _kiem_tat_khi_vang(tat_khi_vang)
    with _khoa:
        d = _nap()
        cu = d["thiet_bi"].setdefault(tb, {"bat": False, "bo_nguon": [], "ngoai_le": []})
        if kiem_ao is not None:
            cu["kiem_ao"] = kiem_ao
        if tat_khi_vang is not None:
            cu["tat_khi_vang"] = tat_khi_vang
            _hen_tat_huy(tb)
        if bat is not None:
            cu["bat"] = bool(bat)
        if bo_nguon is not None:
            cu["bo_nguon"] = sorted({str(x) for x in bo_nguon})
            d["mo_hinh"].pop(tb, None)          # đổi nguồn là phải học lại
        if tu_lam is not None:
            cu["tu_lam"] = bool(tu_lam)
        if ngoai_le is not None:
            cu["ngoai_le"] = [{"hanh_dong": str(x["hanh_dong"]), "tu": str(x["tu"]), "den": str(x["den"]),
                               "cach": str(x.get("cach") or "khong"), "ten": str(x.get("ten") or "").strip()}
                              for x in ngoai_le]
        _luu()
        return dict(cu)


#: Bằng chứng "có người" đặc biệt: bấm công tắc/đèn/quạt bằng tay (không đồng loạt).
CONG_TAC = "cong_tac"


def _kiem_kiem_ao(x: Any) -> dict[str, Any]:
    """Kiểm báo ảo chủ máy đặt (26/09/2026: "check thiết bị gì trong bao lâu, có thể chỉnh
    sửa"): nhìn lại ``gio`` giờ, bằng chứng là ``bang_chung`` (``cong_tac`` hoặc mã thực thể)."""
    if not isinstance(x, dict):
        raise ValueError("kiem_ao phải là {gio, bang_chung}.")
    gio = int(x.get("gio") or 0)
    bc = [str(m) for m in x.get("bang_chung") or []]
    if not 1 <= gio <= 48 or not bc or any(m != CONG_TAC and "." not in m for m in bc):
        raise ValueError("Kiểm báo ảo: 1–48 giờ, ít nhất một bằng chứng (công tắc hoặc mã thực thể).")
    return {"gio": gio, "bang_chung": sorted(set(bc))}


def _kiem_tat_khi_vang(x: Any) -> dict[str, Any]:
    """Tắt khi vắng: ``cam_bien`` (cảm biến nhị phân) cùng tắt liền ``phut`` phút thì tắt."""
    if not isinstance(x, dict):
        raise ValueError("tat_khi_vang phải là {bat, cam_bien, phut}.")
    cb = sorted({str(m) for m in x.get("cam_bien") or []})
    phut = int(x.get("phut") or 0)
    if any(not m.startswith("binary_sensor.") for m in cb) or not 1 <= phut <= 240:
        raise ValueError("Tắt khi vắng: cảm biến là binary_sensor, 1–240 phút.")
    if x.get("bat") and not cb:
        raise ValueError("Tắt khi vắng: bật thì phải chọn ít nhất một cảm biến.")
    return {"bat": bool(x.get("bat")), "cam_bien": cb, "phut": phut}


def _so_do(tb: str) -> tuple[set[str], set[str]]:
    """(cảm biến nhị phân, cảm biến số) trong SƠ ĐỒ KÍCH HOẠT của thiết bị — điều kiện và
    ngoại vi (`hieu_thiet_bi_nha`, đã áp phần chủ máy sửa). Chủ máy 26/09/2026: bật/tắt
    thiết bị "cơ sở là lấy theo sơ đồ kích hoạt"."""
    try:
        from services import hieu_thiet_bi_nha as h
        dk = (h.thoi_quen_hoc().get(tb) or {}).get("bat") or []
        nv = (h.ngoai_vi_hoc().get(tb) or {}).get("ngoai_vi") or []
    except Exception as exc:  # noqa: BLE001 — sơ đồ hỏng thì tự dò như cũ
        logger.warning({"event": "kich_hoat_so_do_loi", "thiet_bi": tb, "error": str(exc)[:160]})
        return set(), set()
    ma = {str(x.get("ma")) for x in [*dk, *nv] if "." in str(x.get("ma") or "")}
    return ({m for m in ma if m.startswith("binary_sensor.")},
            {m for m in ma if m.startswith("sensor.")})


# ── Cây quyết định nhỏ ─────────────────────────────────────────────────────
def _ll(k: int, n: int) -> float:
    if n == 0:
        return 0.0
    p = (k + 1) / (n + 2)
    return -(k * math.log(p) + (n - k) * math.log(1 - p))


def dung_cay(mau: list[tuple[dict[str, float], int]], sau: int = 0) -> dict[str, Any]:
    """CART theo log-likelihood; lá mang xác suất Laplace (k+1)/(n+2)."""
    n = len(mau)
    k = sum(y for _, y in mau)
    nut: dict[str, Any] = {"p": (k + 1) / (n + 2), "n": n, "k": k}
    if sau >= SAU or k == 0 or k == n:
        return nut
    goc = _ll(k, n)
    tot = None
    for key in sorted(set().union(*(x.keys() for x, _ in mau))):
        gia = sorted({x[key] for x, _ in mau if key in x})
        buoc = max(1, len(gia) // 24)
        for i in range(0, len(gia) - 1, buoc):
            nguong = (gia[i] + gia[i + 1]) / 2
            trai = [(x, y) for x, y in mau if x.get(key, -1e9) <= nguong]
            if len(trai) < LA_TOI_THIEU or n - len(trai) < LA_TOI_THIEU:
                continue
            kt = sum(y for _, y in trai)
            loi = goc - _ll(kt, len(trai)) - _ll(k - kt, n - len(trai))
            if tot is None or loi > tot[0]:
                tot = (loi, key, nguong)
    if tot is None or tot[0] < LOI_TOI_THIEU:
        return nut
    _, key, nguong = tot
    trai = [(x, y) for x, y in mau if x.get(key, -1e9) <= nguong]
    phai = [(x, y) for x, y in mau if x.get(key, -1e9) > nguong]
    nut.update(key=key, nguong=nguong, trai=dung_cay(trai, sau + 1), phai=dung_cay(phai, sau + 1))
    return nut


def doan_cay(nut: dict[str, Any], x: dict[str, float]) -> float:
    while "key" in nut:
        nut = nut["trai"] if x.get(nut["key"], -1e9) <= nut["nguong"] else nut["phai"]
    return float(nut["p"])


def _dieu_kien_doc(key: str, nho_hon: bool, nguong: float, ten: dict[str, str]) -> str:
    if key == "giờ":
        h, m = divmod(int(round(nguong * 60)), 60)
        return f"{'trước' if nho_hon else 'từ'} {h:02d}:{m:02d}"
    if key.startswith("["):
        return f"{'không phải ' if nho_hon else ''}{_ten_nguon(key[1:-1], ten)}"
    return f"{ten.get(key, key)} {'≤' if nho_hon else '>'} {nguong:.3g}"


def luat(nut: dict[str, Any], ten: dict[str, str], duong: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Cây → luật đọc được: [{"neu": [...], "p", "k", "n"}]."""
    if "key" not in nut:
        return [{"neu": list(duong), "p": round(float(nut["p"]), 3), "k": nut["k"], "n": nut["n"]}]
    return (luat(nut["trai"], ten, duong + (_dieu_kien_doc(nut["key"], True, nut["nguong"], ten),))
            + luat(nut["phai"], ten, duong + (_dieu_kien_doc(nut["key"], False, nut["nguong"], ten),)))


# ── Sự kiện nguồn ──────────────────────────────────────────────────────────
def _ten_nguon(nguon: str, ten: dict[str, str]) -> str:
    ma, _, duoi = nguon.partition(" ")
    return f"{ten.get(ma, ma)} {duoi}"


def _giay_dong_loat(ro: sqlite3.Connection, tu: float, den: float) -> set[int]:
    """Những giây có ≥ DONG_LOAT thiết bị ĐIỀU KHIỂN đổi cùng lúc — việc của máy."""
    mau = " OR ".join(f"thiet_bi LIKE '{m}.%'" for m in _MIEN_DIEU_KHIEN)
    return {int(r[0]) for r in ro.execute(
        f"SELECT CAST(ts AS INTEGER) g FROM su_kien WHERE ts>=? AND ts<? AND truong='state'"
        f" AND ({mau}) GROUP BY g HAVING COUNT(DISTINCT thiet_bi)>=?", (tu, den, DONG_LOAT))}


def _su_kien_nguon(ro: sqlite3.Connection, tu: float, den: float, bo: set[str],
                   chi: set[str] | None = None) -> list[tuple[float, str]]:
    """(ts, tên nguồn) của cảm biến nhị phân, chỉ hai mốc có nghĩa: "có người vào" (bật
    sau ≥ VANG giây tắt) và "vắng" (tắt giữ ≥ VANG giây; mốc đặt ở CUỐI quãng chờ — lúc
    ấy mới biết, đặt ở đầu là rò rỉ tương lai)."""
    ra: list[tuple[float, str]] = []
    tat_tu: dict[str, float] = {}
    for ts, ma, gt in ro.execute(
            "SELECT ts, thiet_bi, gia_tri FROM su_kien WHERE ts>=? AND ts<? AND truong='state'"
            " AND thiet_bi LIKE 'binary_sensor.%' ORDER BY ts", (tu, den)):
        ts, ma, gt = float(ts), str(ma), str(gt).lower()
        if ma in bo or (chi is not None and ma not in chi):
            continue
        if gt == "on":
            t0 = tat_tu.pop(ma, None)
            if t0 is not None and ts - t0 >= VANG:
                ra.append((t0 + VANG, f"{ma} vắng"))
                ra.append((ts, f"{ma} có người vào"))
        elif gt == "off":
            tat_tu[ma] = ts
        else:
            tat_tu.pop(ma, None)            # unavailable: không biết đã tắt bao lâu
    ra += [(t0 + VANG, f"{ma} vắng") for ma, t0 in tat_tu.items() if den - t0 >= VANG]
    ra.sort()
    return ra


def _trang_thai_ha() -> list[dict[str, Any]]:
    try:
        from services import ha_client
        return list(ha_client.get_states() or [])
    except Exception:  # noqa: BLE001
        return []


def _ten_ha() -> dict[str, str]:
    return {str(s["entity_id"]): str((s.get("attributes") or {}).get("friendly_name") or s["entity_id"])
            for s in _trang_thai_ha()}


def _lop(dc: tuple[str, ...]) -> set[str]:
    return {str(s["entity_id"]) for s in _trang_thai_ha()
            if (s.get("attributes") or {}).get("device_class") in dc}


def _dac_trung(luc: float, nguon: str, ds_nguon: list[str],
               lux: dict[str, tuple[list[float], list[str]]]) -> dict[str, float]:
    """Giờ + nguồn nào (one-hot) + độ sáng CHẶT TRƯỚC lúc đó (`tq._truoc`).

    Lux là đại lượng vật lý của đúng việc bật đèn nên mọi cảm biến độ sáng đều được
    đưa vào; cây tự bỏ cái không liên quan."""
    from services import thoi_quen_nha as tq

    d = datetime.fromtimestamp(luc, _TZ)
    x: dict[str, float] = {"giờ": d.hour + d.minute / 60}
    for n in ds_nguon:
        x[f"[{n}]"] = 1.0 if n == nguon else 0.0
    for ma, (ts, gt) in lux.items():
        try:
            x[ma] = float(tq._truoc(ts, gt, luc))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass
    return x


def _nhan_da_cham(tb: str, hd: str) -> list[tuple[float, str]]:
    """(ts, ket_qua) những lần bot đã hỏi/làm cho hướng này — nhãn của chính chủ máy."""
    from services import du_doan_nha as dd
    with dd._khoa:
        return [(float(r["ts"]), str(r["ket_qua"]) + ":" + str(r["cach"])) for r in dd._db().execute(
            "SELECT ts, ket_qua, cach FROM du_doan WHERE ten=? ORDER BY ts", (_ten_tt(tb, hd),))]


# ── Học ─────────────────────────────────────────────────────────────────────
def hoc(tb: str) -> dict[str, Any]:
    """Học nguồn + luật cho hai hướng bật/tắt của MỘT thiết bị, kiểm tiến dần, lưu."""
    from services import lich_su_nha, thoi_quen_nha as tq

    cd = _nap()["thiet_bi"].get(tb) or {}
    bo = set(cd.get("bo_nguon") or [])
    den = time.time()
    tu = den - NGAY_HOC * 86400
    moc_thu = den - NGAY_THU * 86400
    # Nguồn + đặc trưng số lấy từ SƠ ĐỒ của thiết bị; sơ đồ chưa có cảm biến nào thì tự dò
    # (mọi cảm biến nhị phân, mọi cảm biến độ sáng) như trước.
    nhi_phan, so = _so_do(tb)
    ma_lux = sorted(so) if so else sorted(_lop(("illuminance",)))
    ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    try:
        bat, tat, ts_tb, gt_tb = tq._bat_tat(ro, tb, tu, den)
        sk_toan_nha = _su_kien_nguon(ro, tu, den, bo)
        sk = [x for x in sk_toan_nha if x[1].split(" ")[0] in nhi_phan] if nhi_phan else sk_toan_nha
        lux = {m: tq._tuyen(ro, m, "state", tu, den) for m in ma_lux}
    finally:
        ro.close()
    ts_sk = [t for t, _ in sk]
    ten = _ten_ha()
    ra: dict[str, Any] = {"luc": den, "co_so": "so_do" if nhi_phan else "tu_do", "dac_trung_so": ma_lux,
                          "goi_y_them": _goi_y_them(sk_toan_nha, bat, nhi_phan, moc_thu)}
    for hd, dich in (("on", bat), ("off", tat)):
        truoc: Counter = Counter()
        for t in dich:
            if t >= moc_thu:
                continue
            i, j = bisect.bisect_left(ts_sk, t - TRUOC), bisect.bisect_left(ts_sk, t)
            truoc.update({n for _, n in sk[i:j]})
        ds_nguon = sorted(n for n, v in truoc.items() if v >= NGUON_TOI_THIEU)
        nguoi = sorted(bat + tat)
        cham = _nhan_da_cham(tb, hd)
        ts_cham = [t for t, _ in cham]
        mau: list[tuple[dict[str, float], int, float]] = []
        nguon_set = set(ds_nguon)
        for t, n in sk:
            if n not in nguon_set:
                continue
            g = tq._truoc(ts_tb, gt_tb, t)
            if g is None or g.strip().lower() in _KHONG_RO or (g.strip().lower() == "on") == (hd == "on"):
                continue            # đã ở đúng trạng thái đích thì không phải lúc để làm
            i = bisect.bisect_left(nguoi, t)
            if i and t - nguoi[i - 1] <= NGUOI_VUA_CHAM:
                continue            # người vừa tự chạm — cùng luật với lúc sống (`xet`)
            # Bot đã hỏi/làm ngay sau nguồn này: câu chủ máy trả lời là nhãn; bot tự làm
            # hoặc không ai trả lời thì KHÔNG biết người định làm gì — bỏ mẫu.
            i = bisect.bisect_left(ts_cham, t)
            if i < len(ts_cham) and ts_cham[i] - t <= CHO:
                kq = cham[i][1].split(":")[0]
                if kq not in ("dung", "sai"):
                    continue
                y = int(kq == "dung")
            else:
                y = int(any(t < d <= t + CHO for d in dich[bisect.bisect_right(dich, t):][:3]))
            mau.append((_dac_trung(t, n, ds_nguon, lux), y, t))
        hoc_ = [(x, y) for x, y, t in mau if t < moc_thu]
        thu = [(x, y) for x, y, t in mau if t >= moc_thu]
        cay = (dung_cay(hoc_) if sum(y for _, y in hoc_) >= NGUON_TOI_THIEU
               else {"p": 0.0, "n": len(hoc_), "k": sum(y for _, y in hoc_)})
        theo_gio = [[0, 0] for _ in range(24)]
        for x, y in hoc_:
            if doan_cay(cay, x) >= P_HOI:
                theo_gio[int(x["giờ"])][0] += y
                theo_gio[int(x["giờ"])][1] += 1
        # Nguồn THẬT SỰ điều khiển: có mẫu rơi vào nhánh đủ chắc (và giờ đó không im). Còn
        # lại là ứng viên đã xét rồi loại — chủ máy 26/09/2026 thấy cảm biến ban công trong
        # danh sách của đèn phòng ngủ mà cây không bao giờ bật theo nó.
        dieu_khien: Counter = Counter()
        for x, y in hoc_:
            if doan_cay(cay, x) >= P_HOI and quanh_gio(theo_gio, x["giờ"])[2] != "im":
                dieu_khien[next(k[1:-1] for k, v in x.items() if k.startswith("[") and v)] += 1
        doan = trung = 0
        for x, y in thu:
            if doan_cay(cay, x) >= P_HOI and quanh_gio(theo_gio, x["giờ"])[2] != "im":
                doan += 1
                trung += y
        ra[hd] = {
            "nguon": ds_nguon,
            "dem_nguon": {n: truoc[n] for n in ds_nguon}, "cay": cay, "theo_gio": theo_gio,
            "dieu_khien": dict(dieu_khien),
            "luat": sorted(luat(cay, ten), key=lambda r: -r["p"]),
            "ten": {n: _ten_nguon(n, ten) for n in ds_nguon},
            "so_lan": sum(1 for t in dich if t < moc_thu),
            "kiem": {"doan": doan, "trung": trung, "ngay": NGAY_THU,
                     "dat": doan >= KIEM_TOI_THIEU and trung >= KIEM_TY_LE * doan},
        }
    with _khoa:
        _nap()["mo_hinh"][tb] = ra
        _luu()
    logger.info({"event": "kich_hoat_hoc", "thiet_bi": tb,
                 "kiem": {hd: ra[hd]["kiem"] for hd in HANH_DONG}})
    return ra


def quanh_gio(theo_gio: list[list[int]], gio: float) -> tuple[int, int, str]:
    """(k, n, cách) những lần luật nói "làm" quanh giờ này: "tu_lam" / "hoi" / "im"."""
    h = int(gio)
    k = sum(theo_gio[(h + d) % 24][0] for d in range(-QUANH_GIO, QUANH_GIO + 1))
    n = sum(theo_gio[(h + d) % 24][1] for d in range(-QUANH_GIO, QUANH_GIO + 1))
    if n >= MAU_QUANH and k >= TIN_QUANH * n:
        return k, n, "tu_lam"
    if n >= MAU_QUANH and k < IM_QUANH * n:
        return k, n, "im"
    return k, n, "hoi"


def _goi_y_them(sk: list[tuple[float, str]], bat: list[float], nhi_phan: set[str],
                moc_thu: float) -> list[dict[str, Any]]:
    """Cảm biến NGOÀI sơ đồ hay đứng ngay trước lần người bật — gợi ý chủ máy thêm vào sơ đồ
    (bot không tự thêm). Đo 26/09/2026: sơ đồ đèn trần phòng khách thiếu cảm biến cửa chính,
    nguồn mạnh nhất của nó (22/22 lần "cửa mở, 15:27–18:38 thì bật") — học theo sơ đồ thì
    0 lần đoán."""
    ts = [t for t, _ in sk]
    dem: Counter = Counter()
    for t in bat:
        if t >= moc_thu:
            continue
        i, j = bisect.bisect_left(ts, t - TRUOC), bisect.bisect_left(ts, t)
        dem.update({n.split(" ")[0] for _, n in sk[i:j]} - nhi_phan)
    return [{"ma": m, "so_lan": k} for m, k in dem.most_common(5) if k >= NGUON_TOI_THIEU]


def _hoc_nen(tb: str) -> None:
    with _khoa:
        if tb in _dang_hoc:
            return
        _dang_hoc.add(tb)

    def chay() -> None:
        try:
            hoc(tb)
        except Exception as exc:  # noqa: BLE001
            logger.warning({"event": "kich_hoat_hoc_loi", "thiet_bi": tb, "error": str(exc)[:200]})
        finally:
            with _khoa:
                _dang_hoc.discard(tb)
    threading.Thread(target=chay, name="kich-hoat-hoc", daemon=True).start()


# ── Báo ảo khi nhà vắng ─────────────────────────────────────────────────────
def _kiem_ao_cua(tb: str | None) -> dict[str, Any]:
    """Cấu hình kiểm báo ảo của thiết bị; chưa đặt thì mặc định đã đo (công tắc bấm tay +
    mọi cảm biến cửa, 6 giờ)."""
    cd = ((_nap()["thiet_bi"].get(tb) or {}).get("kiem_ao") if tb else None) or {}
    return {"gio": int(cd.get("gio") or AO_NHIN_LAI // 3600),
            "bang_chung": list(cd.get("bang_chung") or [CONG_TAC, *sorted(_lop(_LOP_CUA))])}


def nha_co_nguoi(tru: set[str], luc: float, tb: str | None = None) -> bool:
    """6 giờ qua có dấu hiệu NGƯỜI nào ngoài ``tru`` không.

    Chủ máy 26/09/2026: "tôi về quê nhưng bị báo ảo thì phải kiểm tra lại các hiện
    diện khác trong 6 tiếng gần nhất". Đo trên dịp lễ 30/08–02/09/2026 (61,7 giờ không
    ai bấm công tắc): radar bếp vẫn báo có người 12 lần, phòng ngủ 4 lần; camera cửa và
    ban công báo 46 và 26 lần (người đi đường). Tức CẢM BIẾN HIỆN DIỆN KHÁC không phải
    bằng chứng — chúng cũng báo khi nhà vắng.

    Bằng chứng dùng được là thứ chỉ người trong nhà làm ra: bấm công tắc/đèn/quạt
    (do_ai=0, không đồng loạt) và MỞ CỬA. Đo trên 30 ngày: chặn 4/4 báo ảo phòng ngủ
    dịp lễ, chặn nhầm 5/330 lần lúc có người — đều 4–5 giờ sáng khi cả nhà ngủ, và chặn
    nhầm thì bot chỉ im."""
    from services import lich_su_nha

    cfg = _kiem_ao_cua(tb)
    nhin = cfg["gio"] * 3600
    bc = set(cfg["bang_chung"])
    cong_tac = CONG_TAC in bc
    ma_bc = sorted(m for m in bc if m != CONG_TAC)
    mau = " OR ".join(f"thiet_bi LIKE '{m}.%'" for m in _MIEN_DIEU_KHIEN) if cong_tac else "0"
    dau = ",".join("?" * len(ma_bc)) or "''"
    ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    try:
        dong_loat = _giay_dong_loat(ro, luc - nhin, luc)
        for ts, ma, gt in ro.execute(
                f"SELECT ts, thiet_bi, gia_tri FROM su_kien WHERE ts>=? AND ts<? AND truong='state'"
                f" AND do_ai=0 AND ({mau} OR thiet_bi IN ({dau}))",
                (luc - nhin, luc, *ma_bc)):
            ma, g = str(ma), str(gt).lower()
            if ma in tru or g in _KHONG_RO:
                continue
            if ma in bc:
                # Bằng chứng chủ máy chọn: bật / mở / về nhà là có người.
                if g in ("on", "open", "home", "unlocked", "playing"):
                    return True
                continue
            if cong_tac and ma.split(".")[0] in _MIEN_DIEU_KHIEN and int(float(ts)) not in dong_loat:
                return True
    finally:
        ro.close()
    return False


# ── Sống: nhận sự kiện, hỏi, làm ───────────────────────────────────────────
def _trong_khoang(luc: float, tu: str, den: str) -> bool:
    d = datetime.fromtimestamp(luc, _TZ)
    phut = d.hour * 60 + d.minute
    a, b = int(tu[:2]) * 60 + int(tu[3:]), int(den[:2]) * 60 + int(den[3:])
    return a <= phut < b if a <= b else (phut >= a or phut < b)


def _ten_tt(tb: str, hd: str) -> str:
    """Tên trong sổ thành tích của `du_doan_nha` — MỖI HƯỚNG một thang lên cấp."""
    return f"{tb}#{hd}"


def _dang_cho(tb: str) -> dict[str, Any] | None:
    from services import du_doan_nha as dd
    with dd._khoa:
        r = dd._db().execute(
            "SELECT id, ts, ten, hanh_dong, p FROM du_doan WHERE ten IN (?,?) AND cach='hoi'"
            " AND ket_qua='cho' AND ts>? ORDER BY ts DESC LIMIT 1",
            (_ten_tt(tb, "on"), _ten_tt(tb, "off"), time.time() - HAN_HOI)).fetchone()
    return dict(r) if r else None


def _vua_lam(tb: str, hd: str) -> bool:
    """Trong NGHI_LAP: đã hỏi/làm CÙNG hướng, hoặc bot đã TỰ làm thiết bị này ở BẤT KỲ
    hướng nào. Chủ máy 26/09/2026: tự làm nhưng "không máy móc và nhiễu như HA" — đo 3
    ngày: automation đèn bếp đổi trạng thái ~250 lần theo từng nhịp nhấp nháy của radar.
    Bot vừa bật thì không được tắt ngay chỉ vì cảm biến vừa báo vắng."""
    from services import du_doan_nha as dd
    with dd._khoa:
        r = dd._db().execute(
            "SELECT 1 FROM du_doan WHERE ts>? AND (ten=? OR (ten IN (?,?) AND cach='tu_lam')) LIMIT 1",
            (time.time() - NGHI_LAP, _ten_tt(tb, hd), _ten_tt(tb, "on"), _ten_tt(tb, "off"))).fetchone()
    return r is not None


def _lam(tb: str, hd: str, *, tu_lam: bool) -> bool:
    """Gọi HA. ``tu_lam``: bot tự quyết → đánh dấu để thay đổi sắp tới ghi do_ai=1."""
    from services import ha_client, lich_su_nha
    if tu_lam:
        lich_su_nha.bot_tu_lam(tb)
    return ha_client.call_service(tb.split(".")[0], "turn_on" if hd == "on" else "turn_off",
                                  {"entity_id": tb})


def _ten_tb(tb: str) -> str:
    return _ten_ha().get(tb, tb)


def _nguoi_vua_cham(tb: str, luc: float) -> bool:
    from services import lich_su_nha
    ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    try:
        return ro.execute(
            "SELECT 1 FROM su_kien WHERE thiet_bi=? AND truong='state' AND do_ai=0 AND ts>=?"
            " AND ts<? LIMIT 1", (tb, luc - NGUOI_VUA_CHAM, luc)).fetchone() is not None
    finally:
        ro.close()


def xet(tb: str, hd: str, nguon: str, luc: float) -> dict[str, Any]:
    """Một nguồn vừa xảy ra: nên hỏi / tự làm / im. Không gửi gì — chỉ trả quyết định."""
    from services import du_doan_nha as dd

    mh = (_nap()["mo_hinh"].get(tb) or {}).get(hd) or {}
    if nguon not in (mh.get("nguon") or []):
        return {"lam": "im", "ly_do": "không phải nguồn"}
    if not (mh.get("kiem") or {}).get("dat"):
        return {"lam": "im", "ly_do": "luật chưa qua kiểm tiến dần"}
    if _nguoi_vua_cham(tb, luc):
        return {"lam": "im", "ly_do": "người vừa tự bật/tắt"}
    khung = next((x for x in (_nap()["thiet_bi"].get(tb) or {}).get("ngoai_le") or []
                  if x.get("hanh_dong") == hd and _trong_khoang(luc, x["tu"], x["den"])), None)
    ten_khung = f"khung «{khung.get('ten') or ''}» {khung['tu']}–{khung['den']}" if khung else ""
    if khung and khung.get("cach", "khong") == "khong":
        return {"lam": "im", "ly_do": f"{ten_khung}: anh đặt không làm"}
    dts = (_nap()["mo_hinh"].get(tb) or {}).get("dac_trung_so")
    lux = {str(s["entity_id"]): ([luc - 1.0], [str(s.get("state"))]) for s in _trang_thai_ha()
           if (str(s["entity_id"]) in dts if dts is not None
               else (s.get("attributes") or {}).get("device_class") == "illuminance")}
    x = _dac_trung(luc, nguon, list(mh["nguon"]), lux)
    p = doan_cay(mh["cay"], x)
    if p < P_HOI:
        return {"lam": "im", "ly_do": f"chỉ chắc {p:.0%}", "p": p}
    k, n, cach = quanh_gio(mh.get("theo_gio") or [[0, 0]] * 24, x["giờ"])
    if cach == "im" and not khung:
        return {"lam": "im", "p": p, "ly_do": f"quanh giờ này anh ít khi {_TEN_HD[hd].lower()} ({k}/{n})"}
    ma_nguon = nguon.split(" ")[0]
    if (hd == "on" and nguon.endswith(" có người vào") and ma_nguon in _lop(_LOP_HIEN_DIEN)
            and not nha_co_nguoi({ma_nguon}, luc, tb)):
        return {"lam": "im", "p": p,
                "ly_do": f"nghi báo ảo: {_kiem_ao_cua(tb)['gio']} giờ qua không có dấu hiệu người nào"}
    if khung:
        return {"lam": "hoi", "p": p, "x": x, "ly_do": f"{ten_khung}: anh đặt luôn hỏi"}
    if cach == "hoi":
        return {"lam": "hoi", "p": p, "x": x, "ly_do": f"quanh giờ này mới đúng {k}/{n} — hỏi anh"}
    return {"lam": "tu_lam" if _duoc_tu_lam(tb, hd) else "hoi", "p": p, "x": x}


def _duoc_tu_lam(tb: str, hd: str) -> bool:
    """Tự làm khi: đủ thang của `du_doan_nha` (50 lượt, 95%), HOẶC chủ máy cho tự làm
    ngay (26/09/2026: "tôi muốn test thử tính năng bot tự thực hiện"). Cho tự làm ngay
    vẫn KHÔNG vượt được hai chốt: khoá cửa/bếp/bình nóng lạnh, và sai 2 trong 10 lượt
    gần nhất (chủ máy làm ngược lại) là quay về hỏi."""
    from services import du_doan_nha as dd
    ten = _ten_tt(tb, hd)
    if dd.cap(ten) >= 2:
        return True
    return (bool((_nap()["thiet_bi"].get(tb) or {}).get("tu_lam")) and not dd._cam_tu_lam(ten)
            and dd.sai_gan_day(ten) < dd._SAI_TUT_CAP)


def _xu_ly(tb: str, hd: str, nguon: str, luc: float) -> None:
    from services import du_doan_nha as dd, ha_client, thong_bao

    try:
        with _khoa_xet:
            st = ha_client.get_state(tb) or {}
            if str(st.get("state") or "").lower() in (hd, *_KHONG_RO):
                return
            if _dang_cho(tb) or _vua_lam(tb, hd):
                return
            # Cảm biến hay báo mất người 1–2 phút dù người vẫn ở đó (chủ máy 26/09/2026;
            # đo phòng ngủ 30 ngày: 270/605 lần tắt-rồi-bật-lại ngắn dưới 3 phút). "Vắng"
            # đã chờ VANG giây; tới lúc làm mà cảm biến đã thấy người lại thì thôi.
            if nguon.endswith(" vắng") and str((ha_client.get_state(nguon.split(" ")[0]) or {})
                                               .get("state") or "").lower() != "off":
                return
            q = xet(tb, hd, nguon, luc)
            if q["lam"] == "im":
                if "báo ảo" in str(q.get("ly_do")):
                    logger.info({"event": "kich_hoat_bao_ao", "thiet_bi": tb, "nguon": nguon})
                    with _khoa:
                        ds = _nap().setdefault("bao_ao", [])
                        ds.append({"luc": luc, "thiet_bi": tb, "nguon": nguon})
                        del ds[:-BAO_AO_GIU]
                        _luu()
                return
            vi = (_nap()["mo_hinh"][tb][hd].get("ten") or {}).get(nguon, nguon)
            nhan = {"nguon": nguon, **{k: round(v, 2) for k, v in q["x"].items() if not k.startswith("[")}}
            if q["lam"] == "tu_lam":
                if not _lam(tb, hd, tu_lam=True):
                    return
                dd.ghi_nhan(_ten_tt(tb, hd), hd, q["p"], nhan, "tu_lam")
            else:
                id_ = dd.ghi_nhan(_ten_tt(tb, hd), hd, q["p"], nhan, "hoi")
        if q["lam"] == "tu_lam":
            thong_bao.gui("nha.goi_y",
                          f"🤖 Em đã {_TEN_HD[hd].lower()} {_ten_tb(tb)} (vì {vi}, em chắc "
                          f"{q['p']:.0%}). Sai thì anh cứ {'tắt' if hd == 'on' else 'bật'} "
                          f"lại trong 10 phút, em tự ghi là em sai.")
        elif not thong_bao.gui("nha.goi_y",
                             f"💡 #{id_} {_TEN_HD[hd]} {_ten_tb(tb)} không ạ? (vì {vi}, em chắc "
                             f"{q['p']:.0%}{'; ' + q['ly_do'] if q.get('ly_do') else ''}) — anh trả lời «có» hoặc «không»."):
            dd.xoa(id_)             # chấm cái chủ máy chưa thấy là hỏng thành tích
    except Exception as exc:  # noqa: BLE001 — một lượt hỏng không được làm chết luồng HA
        logger.warning({"event": "kich_hoat_loi", "thiet_bi": tb, "error": str(exc)[:200]})


def _nguon_cua(ma: str, gt: str, luc: float) -> list[str]:
    """Sự kiện sống → tên nguồn, CÙNG luật với `_su_kien_nguon` lúc học."""
    if not ma.startswith("binary_sensor."):
        return []
    with _khoa:
        cu = _hen_vang.pop(ma, None)
        if cu:
            cu.cancel()
        if gt == "on":
            t0 = _lan_off.pop(ma, None)
            return [f"{ma} có người vào"] if t0 is not None and luc - t0 >= VANG else []
        if gt == "off":
            _lan_off[ma] = luc
            t = threading.Timer(VANG, _bao_vang, args=(ma,))
            t.daemon = True
            _hen_vang[ma] = t
            t.start()
        else:
            _lan_off.pop(ma, None)
    return []


def _bao_vang(ma: str) -> None:
    with _khoa:
        _hen_vang.pop(ma, None)
    _phat(f"{ma} vắng", time.time())


def _phat(nguon: str, luc: float) -> None:
    mh = _nap()["mo_hinh"]
    for tb in ds_thiet_bi():
        for hd in HANH_DONG:
            if nguon in ((mh.get(tb) or {}).get(hd) or {}).get("nguon", []):
                threading.Thread(target=_xu_ly, args=(tb, hd, nguon, luc),
                                 name="kich-hoat-xu-ly", daemon=True).start()


def _nguoi_lam(tb: str, gt: str, luc: float) -> None:
    """Người đổi thiết bị đang theo dõi: chấm các lần bot hỏi/làm gần đây.

    * Bot đang hỏi mà người tự làm đúng việc đó → câu hỏi ĐÚNG.
    * Bot vừa tự làm mà người làm NGƯỢC lại trong CHAM_TU_LAM → SAI (`soi_bi_huy` của
      `du_doan_nha` không bắt được: nó tra lịch sử theo tên sổ ``tb#on``, không phải mã
      thiết bị)."""
    from services import du_doan_nha as dd
    cho = _dang_cho(tb)
    if cho and cho["hanh_dong"] == gt:
        dd.ghi_dung(int(cho["id"]))
    nguoc = "off" if gt == "on" else "on"
    with dd._khoa:
        r = dd._db().execute(
            "SELECT id FROM du_doan WHERE ten=? AND cach='tu_lam' AND ket_qua='cho' AND ts>?",
            (_ten_tt(tb, nguoc), luc - CHAM_TU_LAM)).fetchall()
    for x in r:
        dd.ghi_sai(int(x["id"]))


def cham_tu_lam() -> int:
    """Bot tự làm, qua CHAM_TU_LAM giây không ai làm ngược lại → ĐÚNG. Chủ máy: "Tôi
    không cần phải trả lời". Phải chạy trước `du_doan_nha.don_qua_han` (30 phút) biến
    chúng thành 'lo'."""
    from services import du_doan_nha as dd
    ten = [_ten_tt(tb, hd) for tb in ds_thiet_bi() for hd in HANH_DONG]
    if not ten:
        return 0
    with dd._khoa:
        r = dd._db().execute(
            f"SELECT id FROM du_doan WHERE cach='tu_lam' AND ket_qua='cho' AND ts<?"
            f" AND ten IN ({','.join('?' * len(ten))})", (time.time() - CHAM_TU_LAM, *ten)).fetchall()
    return sum(1 for x in r if dd.ghi_dung(int(x["id"])))


# ── Tắt khi vắng ───────────────────────────────────────────────────────────
# Chủ máy 26/09/2026: bật/tắt thiết bị phải có "check thiết bị gì trong bao lâu (có thể
# chỉnh sửa)" — chọn cảm biến và số phút; mọi cảm biến đã chọn cùng báo vắng liền ngần ấy
# phút mà thiết bị còn bật thì tắt. Mặc định TẮT: đo phòng ngủ 30 ngày, radar mất người
# 10–60 phút 146 lần (người nằm yên lúc ngủ, đọc sách) — chủ máy tự chọn số phút.
def _hen_tat_huy(tb: str) -> None:
    with _khoa:
        cu = _hen_tat.pop(tb, None)
    if cu:
        cu.cancel()


def _deu_vang(cam_bien: list[str]) -> bool:
    tt = {str(s["entity_id"]): str(s.get("state") or "").lower() for s in _trang_thai_ha()}
    return bool(cam_bien) and all(tt.get(m) == "off" for m in cam_bien)


def _theo_vang(ma: str, gt: str, ds: dict[str, dict[str, Any]]) -> None:
    """Một thay đổi trạng thái: hẹn / huỷ hẹn tắt cho các thiết bị theo dõi cảm biến đó."""
    for tb, cd in ds.items():
        tv = cd.get("tat_khi_vang") or {}
        if not tv.get("bat"):
            continue
        cb = list(tv.get("cam_bien") or [])
        if ma in cb and gt == "on":
            _hen_tat_huy(tb)
        elif (ma in cb and gt == "off") or (ma == tb and gt == "on"):
            if _deu_vang(cb):
                _hen_tat_huy(tb)
                t = threading.Timer(float(tv.get("phut") or 15) * 60, _tat_vi_vang, args=(tb,))
                t.daemon = True
                with _khoa:
                    _hen_tat[tb] = t
                t.start()


def _tat_vi_vang(tb: str) -> None:
    """Hẹn giờ tới: xét LẠI mọi thứ tại thời điểm này rồi mới tắt."""
    from services import du_doan_nha as dd, ha_client, thong_bao

    with _khoa:
        _hen_tat.pop(tb, None)
    try:
        cd = ds_thiet_bi().get(tb) or {}
        tv = cd.get("tat_khi_vang") or {}
        luc = time.time()
        if not tv.get("bat") or not _deu_vang(list(tv.get("cam_bien") or [])):
            return
        if str((ha_client.get_state(tb) or {}).get("state") or "").lower() != "on":
            return
        if _nguoi_vua_cham(tb, luc) or _vua_lam(tb, "off"):
            return
        if any(x.get("hanh_dong") == "off" and x.get("cach", "khong") == "khong"
               and _trong_khoang(luc, x["tu"], x["den"]) for x in cd.get("ngoai_le") or []):
            return
        if not _lam(tb, "off", tu_lam=True):
            return
        phut = int(tv.get("phut") or 15)
        dd.ghi_nhan(_ten_tt(tb, "off"), "off", 1.0, {"nguon": f"vắng {phut} phút"}, "tu_lam")
        thong_bao.gui("nha.goi_y", f"🤖 Em đã tắt {_ten_tb(tb)} (vắng {phut} phút). Sai thì anh "
                                   f"bật lại trong 10 phút, em tự ghi là em sai.")
    except Exception as exc:  # noqa: BLE001
        logger.warning({"event": "kich_hoat_tat_vang_loi", "thiet_bi": tb, "error": str(exc)[:200]})


def su_kien(ma: str, gia_tri: Any, *, do_ai: bool = False) -> None:
    """Gọi từ `ha_live` với MỌI thay đổi trạng thái. Không bao giờ raise, không chặn."""
    global _cham_luc
    try:
        ds = ds_thiet_bi()
        if not ds:
            return
        gt = str(gia_tri).lower()
        luc = time.time()
        mh = _nap()["mo_hinh"]
        for tb in ds:
            if tb not in mh or luc - float(mh[tb].get("luc") or 0) > HOC_LAI:
                _hoc_nen(tb)
        if luc - _cham_luc > 60:
            _cham_luc = luc
            threading.Thread(target=cham_tu_lam, name="kich-hoat-cham", daemon=True).start()
        _theo_vang(ma, gt, ds)
        if do_ai:
            return
        if ma in ds and gt in HANH_DONG:
            threading.Thread(target=_nguoi_lam, args=(ma, gt, luc), daemon=True).start()
        for nguon in _nguon_cua(ma, gt, luc):
            _phat(nguon, luc)
    except Exception as exc:  # noqa: BLE001
        logger.warning({"event": "kich_hoat_su_kien_loi", "error": str(exc)[:160]})


# ── Trả lời trong Zalo ─────────────────────────────────────────────────────
#: Câu trả lời có/không: tập đóng các cách nói của tiếng Việt. Đây là CÂU TRẢ LỜI cho
#: đúng câu bot vừa hỏi, không phải dò ý trong câu tự do — tin nào không khớp NGUYÊN câu
#: thì trả None và đi tiếp đường khác.
#:
#: So trên chữ CÓ DẤU: bỏ dấu thì "đúng" (có) và "dừng" (không) cùng thành "dung".
#: Bản không dấu chỉ nhận khi không hai nghĩa ("co", "khong"). "bật"/"tắt" không phải
#: câu trả lời: hỏi "tắt không?" mà đáp "bật" là ý ngược lại.
_CO = {"có", "co", "ok", "oke", "okay", "ừ", "ừm", "uh", "um", "đồng ý", "dong y", "yes",
       "được", "duoc", "có em", "co em", "có đi", "co di", "làm đi", "lam di", "đúng", "đúng rồi"}
_KHONG = {"không", "khong", "ko", "k", "kg", "thôi", "thoi", "không cần", "khong can", "no",
          "dừng", "dừng lại", "không phải", "khong phai", "sai"}


def tra_loi(text: str) -> str | None:
    """«có» / «không» (kèm số «có 12» nếu cần) cho câu hỏi bật/tắt đang chờ.
    None = không phải câu trả lời cho việc này."""
    from services import du_doan_nha as dd

    t = " ".join(re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFC", str(text or "")).lower()).split())
    m = re.fullmatch(r"(.*?)\s*(\d+)?", t)
    cau, so = (m.group(1).strip(), m.group(2)) if m else ("", None)
    if cau not in _CO and cau not in _KHONG:
        return None
    with dd._khoa:
        r = dd._db().execute(
            "SELECT id, ten, hanh_dong FROM du_doan WHERE cach='hoi' AND ket_qua='cho'"
            " AND ten LIKE '%#%' AND ts>?" + (" AND id=?" if so else "") + " ORDER BY ts DESC LIMIT 1",
            (time.time() - HAN_HOI, *([int(so)] if so else []))).fetchone()
    if not r:
        return None
    tb, hd = str(r["ten"]).rsplit("#", 1)
    if cau in _KHONG:
        dd.ghi_sai(int(r["id"]))
        return f"Dạ, em không {_TEN_HD[hd].lower()} {_ten_tb(tb)}. Em ghi lại để lần sau đoán đúng hơn."
    if not _lam(tb, hd, tu_lam=False):
        return f"Em chưa {_TEN_HD[hd].lower()} được {_ten_tb(tb)} — Home Assistant không nhận lệnh."
    dd.ghi_dung(int(r["id"]))
    ten = _ten_tt(tb, hd)
    con = max(0, dd._MAU_LEN_CAP - dd.so_luot(ten))
    return (f"Dạ, em đã {_TEN_HD[hd].lower()} {_ten_tb(tb)}."
            + (f" Còn {con} lượt anh chấm nữa (và đúng ≥ {dd._TY_LE_LEN_CAP:.0%}) là em tự làm."
               if dd.cap(ten) < 2 else " Em đã đủ tin, lần sau em tự làm."))


# ── Cho trang Học hỏi ──────────────────────────────────────────────────────
def tong_quan() -> list[dict[str, Any]]:
    from services import du_doan_nha as dd
    d = _nap()
    ten_ha = _ten_ha()
    hien_dien = _lop(_LOP_HIEN_DIEN)
    cua = sorted(_lop(_LOP_CUA))
    ra = []
    for tb, cd in sorted(d["thiet_bi"].items()):
        mh = d["mo_hinh"].get(tb) or {}
        ka = _kiem_ao_cua(tb)
        tv = cd.get("tat_khi_vang") or {}
        nhi_phan, _so = _so_do(tb)
        huong = {}
        for hd in HANH_DONG:
            m = mh.get(hd) or {}
            ten = _ten_tt(tb, hd)
            dk = m.get("dieu_khien")

            def _muc(n: str, m=m, dk=dk) -> dict[str, Any]:
                return {"ma": n, "ten": (m.get("ten") or {}).get(n, n),
                        "so_lan": (m.get("dem_nguon") or {}).get(n, 0), "du_chac": (dk or {}).get(n, 0)}
            huong[hd] = {
                # Mô hình học trước khi có "dieu_khien" thì chưa tách được — coi như đều dùng.
                "nguon": [_muc(n) for n in m.get("nguon") or [] if dk is None or n in dk],
                "da_xet": [_muc(n) for n in m.get("nguon") or [] if dk is not None and n not in dk],
                "luat": m.get("luat") or [], "kiem": m.get("kiem") or {}, "so_lan": m.get("so_lan", 0),
                "theo_gio": [{"gio": h, "k": kk, "n": nn, "cach": quanh_gio(m["theo_gio"], h)[2]}
                             for h, (kk, nn) in enumerate(m.get("theo_gio") or []) if nn]
                            if m.get("theo_gio") else [],
                "cap": 2 if _duoc_tu_lam(tb, hd) else 1, "diem": round(dd.diem(ten), 3), "so_luot": dd.so_luot(ten),
                "sai_gan_day": dd.sai_gan_day(ten),
            }
        ra.append({"thiet_bi": tb, "ten": ten_ha.get(tb, tb), "bat": bool(cd.get("bat")),
                   "tu_lam": bool(cd.get("tu_lam")),
                   "bo_nguon": [{"ma": n, "ten": _ten_nguon(n, ten_ha)} for n in cd.get("bo_nguon") or []],
                   "ngoai_le": cd.get("ngoai_le") or [], "hoc_luc": mh.get("luc"), "huong": huong,
                   # Kiểm báo ảo TÁCH khỏi điều khiển: chỉ áp khi BẬT theo cảm biến hiện diện,
                   # và dựa vào thứ KHÁC hẳn — bấm công tắc, mở cửa (xem `nha_co_nguoi`).
                   "kiem_ao": {
                       "ap_cho": [huong["on"]["nguon"][i]["ten"] for i, n in enumerate(huong["on"]["nguon"])
                                  if n["ma"].endswith(" có người vào") and n["ma"].split(" ")[0] in hien_dien],
                       "nhin_lai_gio": ka["gio"],
                       "bang_chung": [{"ma": m, "ten": "Công tắc bấm tay" if m == CONG_TAC else ten_ha.get(m, m)}
                                      for m in ka["bang_chung"]],
                       "cua": [ten_ha.get(c, c) for c in cua],
                       "chan_gan_day": [{"luc": x["luc"], "nguon": _ten_nguon(x["nguon"], ten_ha)}
                                        for x in d.get("bao_ao") or [] if x.get("thiet_bi") == tb][-5:],
                   },
                   "tat_khi_vang": {
                       "bat": bool(tv.get("bat")), "phut": int(tv.get("phut") or 15),
                       "cam_bien": [{"ma": m, "ten": ten_ha.get(m, m)} for m in tv.get("cam_bien") or []],
                       # Gợi ý: cảm biến hiện diện trong sơ đồ của thiết bị.
                       "goi_y": [{"ma": m, "ten": ten_ha.get(m, m)} for m in sorted(nhi_phan & hien_dien)],
                   },
                   "co_so": mh.get("co_so") or "tu_do",
                   "goi_y_them": [{**x, "ten": ten_ha.get(x["ma"], x["ma"])} for x in mh.get("goi_y_them") or []],
                   "nguong": {"so_luot": dd._MAU_LEN_CAP, "ty_le": dd._TY_LE_LEN_CAP}})
    return ra


def _reset_for_tests(duong: Path) -> None:
    global _PATH, _du_lieu, _cham_luc
    _PATH = duong
    _du_lieu = None
    _cham_luc = 0.0
    _lan_off.clear()
    for t in [*_hen_vang.values(), *_hen_tat.values()]:
        t.cancel()
    _hen_vang.clear()
    _hen_tat.clear()
