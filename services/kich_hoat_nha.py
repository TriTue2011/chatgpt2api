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

from services import cam_bien_ghep as _cbg
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
_da_khoi_phuc = False
#: Soát cặp gương (`_gop_guong`) trên đường sống mỗi ngần này giây — sổ đăng ký HA đổi hiếm.
GOP_GIAY = 300
_gop_luc = 0.0


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


# ── Cặp gương: MỘT thiết bị thật ───────────────────────────────────────────
# Chủ máy 27/09/2026 tích cả light.phong_ngu_l1 lẫn switch.phong_ngu_l1 (cặp `switch_as_x`,
# một bóng đèn) → hai thiết bị học riêng: luật bật lệch (độ sáng ≤ 38,5 so với ≤ 62,2), cài
# đặt lệch, cùng "tự làm" nên một cảm biến đẻ hai lượt xét, hai lệnh, hai tin Zalo. Mục light
# còn không thấy SƠ ĐỒ (tầng hiểu thiết bị xếp cặp dưới mã switch) nên tự dò toàn nhà và học
# luật tắt theo độ sáng Ở BẾP.
def _chinh(tb: str) -> str:
    """Mã CHÍNH của thiết bị thật chứa ``tb``: thực thể BỌC của cặp gương (cái HA đưa người
    dùng) nếu miền của nó điều khiển được, không thì công tắc gốc. Không thuộc cặp nào → ``tb``."""
    try:
        from services import ha_client
        boc = ha_client.thuc_the_boc(tb)
        if not boc:
            return tb
        return boc if boc.split(".")[0] in _MIEN_DIEU_KHIEN else (ha_client.thuc_the_guong(boc) or tb)
    except Exception:  # noqa: BLE001 — HA chưa trả sổ đăng ký thì giữ nguyên mã
        return tb


def _gop_guong() -> list[str]:
    """Dồn mục của thực thể phụ trong cặp gương vào mã chính. Cài đặt của mã chính thắng, khoá
    nào thiếu lấy từ mục kia, «bỏ nguồn» lấy hợp (chủ máy đã bỏ ở đâu thì vẫn bỏ); sổ thành tích
    đổi sang tên chính (thang tự làm không mất lượt đã chấm); mô hình bỏ để học lại. Chạy lại bao
    nhiêu lần cũng vậy. Trả các mã phụ đã dồn."""
    from services import du_doan_nha as dd

    cap = {tb: c for tb in list(_nap()["thiet_bi"]) if (c := _chinh(tb)) != tb}   # gọi HA ngoài khoá
    if not cap:
        return []
    with _khoa:
        d = _nap()
        for tb, c in cap.items():
            phu = d["thiet_bi"].pop(tb, None)
            if phu is None:
                continue
            dich = d["thiet_bi"].setdefault(c, {})
            for k, v in phu.items():
                dich.setdefault(k, v)
            dich["bat"] = bool(dich.get("bat")) or bool(phu.get("bat"))
            dich["bo_nguon"] = sorted(set(dich.get("bo_nguon") or []) | set(phu.get("bo_nguon") or []))
            d["mo_hinh"].pop(tb, None)
            d["mo_hinh"].pop(c, None)
            for x in d.get("bao_ao") or []:
                if x.get("thiet_bi") == tb:
                    x["thiet_bi"] = c
        _luu()
    for tb, c in cap.items():
        _hen_tat_huy(tb)
        _huy_sang(tb)
        with dd._khoa:
            conn = dd._db()
            for hd in HANH_DONG:
                moi, cu = _ten_tt(c, hd), _ten_tt(tb, hd)
                conn.execute("UPDATE du_doan SET ten=? WHERE ten=?", (moi, cu))
                # Bảng tổng của thang tự làm (`du_doan_nha.so_luot`) cũng theo tên — cộng dồn.
                r = conn.execute("SELECT dung, sai FROM thanh_tich WHERE ten=?", (cu,)).fetchone()
                if r:
                    conn.execute("INSERT INTO thanh_tich (ten, dung, sai) VALUES (?,?,?) ON CONFLICT(ten)"
                                 " DO UPDATE SET dung=dung+excluded.dung, sai=sai+excluded.sai",
                                 (moi, int(r["dung"]), int(r["sai"])))
                    conn.execute("DELETE FROM thanh_tich WHERE ten=?", (cu,))
            conn.commit()
        logger.info({"event": "kich_hoat_gop_guong", "phu": tb, "chinh": c})
    return list(cap)


def dat_thiet_bi(tb: str, *, bat: bool | None = None, bo_nguon: list[str] | None = None,
                 ngoai_le: list[dict[str, str]] | None = None,
                 tu_lam: bool | None = None,
                 kiem_ao: dict[str, Any] | None = None,
                 tat_khi_vang: dict[str, Any] | None = None,
                 tat_khi_sang: dict[str, Any] | None = None,
                 luat_chu: list[dict[str, Any]] | None = None,
                 im_lang: bool | None = None,
                 hoi_de_hoc: bool | None = None) -> dict[str, Any]:
    """Chủ máy sửa sơ đồ: bật/tắt, cho TỰ LÀM ngay, BỎ nguồn, đặt khung giờ NGOẠI LỆ
    (``{"hanh_dong": "on"|"off", "tu": "HH:MM", "den": "HH:MM", "thu"?: [0..6]}`` hoặc
    ĐI THEO LỊCH SINH HOẠT ``{"hanh_dong", "lich": "<mã mục lịch>"}`` — trong khung đó
    hướng ấy luôn hỏi hoặc không làm). Điều chủ máy đặt luôn thắng điều máy học."""
    from services import lich_sinh_hoat as lsh

    tb = str(tb or "").strip()
    if tb.split(".")[0] not in _MIEN_DIEU_KHIEN or "." not in tb:
        raise ValueError(f"{tb or '(trống)'} không phải thiết bị bật/tắt được.")
    for x in ngoai_le or []:
        if x.get("hanh_dong") not in HANH_DONG:
            raise ValueError("Khung giờ phải có hanh_dong on/off.")
        if x.get("lich"):
            if lsh.tim(str(x["lich"])) is None:
                raise ValueError(f"Lịch sinh hoạt không có mục «{x['lich']}».")
        elif not all(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(x.get(k) or "")) for k in ("tu", "den")) \
                or any(not isinstance(t, int) or not 0 <= t <= 6 for t in x.get("thu") or []):
            raise ValueError("Khung giờ phải có giờ dạng HH:MM (thu: 0 = thứ 2 … 6 = chủ nhật) hoặc theo lịch.")
        if x.get("cach", "khong") not in CACH_KHUNG or len(str(x.get("ten") or "")) > 40:
            raise ValueError("Khung giờ: cách là «hoi» hoặc «khong», tên tối đa 40 chữ.")
    if kiem_ao is not None:
        kiem_ao = _kiem_kiem_ao(kiem_ao)
    if tat_khi_vang is not None:
        tat_khi_vang = _kiem_tat_khi_vang(tat_khi_vang)
    if tat_khi_sang is not None:
        tat_khi_sang = _kiem_tat_khi_sang(tat_khi_sang)
    if luat_chu is not None:
        luat_chu = _kiem_luat_chu(luat_chu)
    _gop_guong()
    tb = _chinh(tb)          # tích công tắc gốc hay đèn bọc thì cũng là một thiết bị
    with _khoa:
        d = _nap()
        cu = d["thiet_bi"].setdefault(tb, {"bat": False, "bo_nguon": [], "ngoai_le": []})
        if kiem_ao is not None:
            cu["kiem_ao"] = kiem_ao
        if tat_khi_vang is not None:
            cu["tat_khi_vang"] = {**{k: v for k, v in (cu.get("tat_khi_vang") or {}).items()
                                     if k in ("giu", "nhin", "roi", "roi_phut")}, **tat_khi_vang}
            _hen_tat_huy(tb)
        if tat_khi_sang is not None:
            cu["tat_khi_sang"] = tat_khi_sang
            _huy_sang(tb)
        if luat_chu is not None:
            cu["luat_chu"] = luat_chu
        if im_lang is not None:
            cu["im_lang"] = bool(im_lang)
        if hoi_de_hoc is not None:
            cu["hoi_de_hoc"] = bool(hoi_de_hoc)
            d["mo_hinh"].pop(tb, None)          # thêm/bỏ nguồn «ở lại» là phải học lại
        if bat is not None:
            cu["bat"] = bool(bat)
            if bat and "tat_khi_vang" not in cu and tat_khi_vang is None:
                # TẮT là ngược của BẬT (chủ máy 26/09/2026): người rời phòng — cảm biến hiện
                # diện trong sơ đồ vắng liền MAC_DINH_VANG_PHUT phút. Không học được từ lịch sử:
                # đo 30 ngày, 115/115 lần đèn phòng ngủ tắt ĐÚNG GIÂY cảm biến báo vắng (automation
                # HA cũ), bot chưa từng thấy người tắt sau khi rời phòng.
                hd_so_do = sorted(_so_do(tb)[0] & _lop(_LOP_HIEN_DIEN))
                cu["tat_khi_vang"] = {"bat": bool(hd_so_do), "cam_bien": hd_so_do,
                                      "phut": MAC_DINH_VANG_PHUT}
        if bo_nguon is not None:
            cu["bo_nguon"] = sorted({str(x) for x in bo_nguon})
            d["mo_hinh"].pop(tb, None)          # đổi nguồn là phải học lại
        if tu_lam is not None:
            cu["tu_lam"] = bool(tu_lam)
        if ngoai_le is not None:
            cu["ngoai_le"] = [{"hanh_dong": str(x["hanh_dong"]),
                               **({"lich": str(x["lich"])} if x.get("lich") else
                                  {"tu": str(x["tu"]), "den": str(x["den"]),
                                   **({"thu": sorted(set(x["thu"]))} if x.get("thu") else {})}),
                               "cach": str(x.get("cach") or "khong"), "ten": str(x.get("ten") or "").strip()}
                              for x in ngoai_le]
        _luu()
        return dict(cu)


#: Tắt khi vắng mặc định cho thiết bị vừa tích — chủ máy sửa được. Radar mất người 1–2 phút dù
#: người còn đó (270/605 lần ở phòng ngủ dưới 3 phút); 10 phút bỏ qua gần hết các lần đó.
MAC_DINH_VANG_PHUT = 10
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


def _kiem_tat_khi_sang(x: Any) -> dict[str, Any]:
    """Tắt khi đủ sáng: trời (lux đo − phần đèn góp) ≥ ``lux``. Phòng trống thì tắt sau ``giay``
    giây; còn người thì sáng liền ``phut`` phút mới hỏi."""
    if not isinstance(x, dict):
        raise ValueError("tat_khi_sang phải là {bat, cam_bien, lux, phut}.")
    cb = str(x.get("cam_bien") or "").strip()
    try:
        lux, phut = float(x.get("lux") or 0), int(x.get("phut") or 0)
        giay = int(x.get("giay") or SANG_VANG_GIAY)
    except (TypeError, ValueError):
        raise ValueError("Tắt khi đủ sáng: lux, phút, giây phải là số.") from None
    if ((cb and not cb.startswith("sensor.")) or not 1 <= lux <= 100000 or not 1 <= phut <= 60
            or not 5 <= giay <= 600):
        raise ValueError("Tắt khi đủ sáng: cảm biến sensor.*, lux 1–100000, 1–60 phút, 5–600 giây.")
    if x.get("bat") and not cb:
        raise ValueError("Tắt khi đủ sáng: bật thì phải chọn cảm biến độ sáng.")
    return {"bat": bool(x.get("bat")), "cam_bien": cb, "lux": round(lux, 1), "phut": phut, "giay": giay}


# ── Luật ANH ĐẶT: KHI … NẾU … THÌ bật/tắt ─────────────────────────────────
# Chủ máy 29/09/2026: quạt phòng khách "khi mở cửa chính căn cứ vào nhiệt độ, độ ẩm, mùa để xem
# có bật quạt hay không, nhưng nếu có người trong nhà thì không bật nữa … khi người ra lại bật
# lại"; đèn cửa sổ, đèn tủ lạnh "khi … xem tivi … thì bật lên". Đo 30 ngày: bot KHÔNG học ra được
# các luật ấy — automation HA cũ bật quạt bằng nút hồng ngoại mà không đổi trạng thái quạt (lịch
# sử không có lần nào), còn đèn cửa sổ / tủ lạnh chỉ 6–7 lần bật. Nên chủ máy ĐẶT luật; ngưỡng
# nhiệt thì bot TỰ RÚT từ lịch sử quạt đang bật theo nhiệt độ (``muc_hay_bat``) — đúng dần theo mùa.
# Luật anh đặt THẮNG luật bot học: hướng nào có luật anh đặt thì bot không tự xét hướng ấy nữa.
#
# Điều kiện:
#   {"loai": "nha_trong", "tru": [...]}  mọi cảm biến hiện diện (trừ ``tru``) đang vắng — "nếu có
#       người trong nhà thì không bật".
#   {"loai": "muc_hay_bat", "cam_bien": "sensor.…", "co_mat": "binary_sensor.…", "nguong": 0.5}
#       60 ngày qua, lúc ``co_mat`` có người mà ``cam_bien`` ở mức bây giờ (±1 đơn vị nếu thiếu mẫu)
#       thì thiết bị đang bật ≥ ``nguong`` thời gian (bỏ quãng BOT bật — không tự khẳng định).
NGAY_HAY_BAT = 60
#: Mẫu (ô 5 phút) tối thiểu của một mức — ít hơn thì gộp hai mức lân cận; vẫn thiếu thì không làm.
MAU_HAY_BAT = 12
_NGUON_RE = re.compile(r"^binary_sensor\.[a-z0-9_]+ (có người vào|vắng)$")


def _kiem_luat_chu(x: Any) -> list[dict[str, Any]]:
    if not isinstance(x, list):
        raise ValueError("luat_chu phải là danh sách luật.")
    ra = []
    for l in x:
        if not isinstance(l, dict) or l.get("hanh_dong") not in HANH_DONG:
            raise ValueError("Luật phải có hanh_dong on/off.")
        khi = l.get("khi")
        if not isinstance(khi, list) or not khi or not all(_NGUON_RE.fullmatch(str(n)) for n in khi):
            raise ValueError("«khi» là danh sách nguồn dạng «binary_sensor.… có người vào|vắng».")
        neu = []
        for d in l.get("neu") or []:
            loai = (d or {}).get("loai")
            if loai == "nha_trong":
                neu.append({"loai": loai, "tru": [str(m) for m in d.get("tru") or []]})
            elif loai == "muc_hay_bat":
                cb, cm = str(d.get("cam_bien") or ""), str(d.get("co_mat") or "")
                ng = float(d.get("nguong", 0.5))
                if not cb.startswith("sensor.") or not cm.startswith("binary_sensor.") or not 0 < ng <= 1:
                    raise ValueError("muc_hay_bat cần cam_bien sensor.…, co_mat binary_sensor.…, nguong 0–1.")
                neu.append({"loai": loai, "cam_bien": cb, "co_mat": cm, "nguong": ng})
            else:
                raise ValueError("Điều kiện: nha_trong | muc_hay_bat.")
        ra.append({"hanh_dong": l["hanh_dong"], "khi": [str(n) for n in khi], "neu": neu,
                   "ten": str(l.get("ten") or "")[:60]})
    return ra


def _hoc_hay_bat(ro: sqlite3.Connection, tb: str, cam_bien: str, co_mat: str,
                 tu: float, den: float) -> dict[str, list[int]]:
    """{mức (làm tròn xuống): [số ô 5 phút có người, số ô thiết bị đang bật]}. Ô thiết bị đang
    bật do BOT bật (do_ai=1) thì bỏ — không để việc bot làm tự dạy lại bot."""
    from services import ha_client

    ma_tb = [m for m in {tb, ha_client.thuc_the_guong(tb)} if m]
    dau = ",".join("?" * len(ma_tb))
    tb_ts, tb_gt = [], []
    for ts, gt, ai in ro.execute(
            f"SELECT ts, gia_tri, do_ai FROM su_kien WHERE truong='state' AND ts>=? AND ts<?"
            f" AND thiet_bi IN ({dau}) ORDER BY ts", (tu - 86400, den, *ma_tb)):
        tb_ts.append(float(ts))
        tb_gt.append("bot" if str(gt).lower() == "on" and ai else str(gt).lower())
    if _cbg.la_ghep(co_mat):
        cm = _cbg.chuoi(ro, co_mat, tu, den)
    else:
        cm = [(float(t), str(g).lower()) for t, g in ro.execute(
            "SELECT ts, gia_tri FROM su_kien WHERE thiet_bi=? AND truong='state' AND ts>=? AND ts<? ORDER BY ts",
            (co_mat, tu - 86400, den))]
    cm_ts = [t for t, _ in cm]
    ra: dict[str, list[int]] = {}
    for o, v in ro.execute("SELECT o_5p, tb FROM so_do WHERE thiet_bi=? AND truong='state'"
                           " AND o_5p>=? AND o_5p<? ORDER BY o_5p", (cam_bien, int(tu // 300), int(den // 300))):
        t = int(o) * 300 + 150
        i = bisect.bisect_right(cm_ts, t) - 1
        if i < 0 or cm[i][1] != "on":
            continue
        j = bisect.bisect_right(tb_ts, t) - 1
        gt = tb_gt[j] if j >= 0 else "off"
        if gt == "bot":
            continue
        o_ = ra.setdefault(str(math.floor(float(v))), [0, 0])
        o_[0] += 1
        o_[1] += gt == "on"
    return ra


def _muc_hay_bat(tb: str, d: dict[str, Any]) -> tuple[bool, str]:
    bang = (((_nap()["mo_hinh"].get(tb) or {}).get("hay_bat") or {}).get(d["cam_bien"]) or {})
    try:
        v = float(_trang_thai_mot(d["cam_bien"]))
    except ValueError:
        return False, f"không đọc được {d['cam_bien']}"
    m = math.floor(v)
    for lan in (0, 1):
        n = sum((bang.get(str(k)) or [0, 0])[0] for k in range(m - lan, m + lan + 1))
        k = sum((bang.get(str(k)) or [0, 0])[1] for k in range(m - lan, m + lan + 1))
        if n >= MAU_HAY_BAT:
            return k / n >= d["nguong"], f"ở {v:g} thường bật {k / n:.0%} ({k}/{n} ô 5 phút)"
    return False, f"chưa đủ dữ liệu ở mức {v:g} ({n} ô 5 phút)"


def _nha_trong(d: dict[str, Any]) -> tuple[bool, str]:
    tru = set(d.get("tru") or [])
    co = [str(s["entity_id"]) for s in _trang_thai_ha()
          if (s.get("attributes") or {}).get("device_class") in _LOP_HIEN_DIEN
          and not _cbg.la_ghep(str(s["entity_id"])) and str(s["entity_id"]) not in tru
          and str(s.get("state") or "").lower() == "on"]
    return (not co), ("nhà trống" if not co else f"trong nhà đang có người ({co[0]})")


def _dieu_kien_chu(tb: str, luat: dict[str, Any]) -> tuple[bool, list[str]]:
    ly_do = []
    for d in luat.get("neu") or []:
        ok, ld = _nha_trong(d) if d["loai"] == "nha_trong" else _muc_hay_bat(tb, d)
        ly_do.append(ld)
        if not ok:
            return False, ly_do
    return True, ly_do


def _xu_ly_chu(tb: str, luat: dict[str, Any], nguon: str, luc: float) -> None:
    """Một nguồn khớp luật anh đặt: kiểm rồi TỰ LÀM (chủ máy đặt luật tức là cho làm)."""
    from services import du_doan_nha as dd, thong_bao

    hd = luat["hanh_dong"]
    try:
        with _khoa_xet:
            if _trang_thai_mot(tb) in (hd, *_KHONG_RO):
                return
            if _vua_lam(tb, hd) or _nguoi_vua_cham(tb, luc):
                return
            if nguon.endswith(" vắng") and _trang_thai_mot(nguon.split(" ")[0]) != "off":
                return
            if any(x.get("hanh_dong") == hd and x.get("cach", "khong") == "khong" and _khung_dang(x, luc)
                   for x in (_nap()["thiet_bi"].get(tb) or {}).get("ngoai_le") or []):
                return
            ok, ly_do = _dieu_kien_chu(tb, luat)
            logger.info({"event": "kich_hoat_luat_chu", "thiet_bi": tb, "hanh_dong": hd, "nguon": nguon,
                         "lam": ok, "ly_do": ly_do})
            if not ok or not _lam(tb, hd, tu_lam=True):
                return
        vi = "; ".join([f"{_ten_nguon(nguon, _ten_ha())}", *ly_do])
        id_ = dd.ghi_nhan(_ten_tt(tb, hd), hd, 1.0, {"nguon": vi, BEN_VUNG: 1, "luat_chu": 1}, "tu_lam")
        _bao_tu_lam(tb, f"🤖 #{id_} Em đã {_TEN_HD[hd].lower()} {_ten_tb(tb)} ({vi}).\nĐúng hay sai "
                        f"ạ? Anh trả lời «đúng» hoặc «sai» — sai thì em làm ngược lại ngay. Không trả "
                        f"lời trong {CHAM_TU_LAM // 60} phút là em tính đúng.")
    except Exception as exc:  # noqa: BLE001
        logger.warning({"event": "kich_hoat_luat_chu_loi", "thiet_bi": tb, "error": str(exc)[:200]})


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
    ra = {"bat": bool(x.get("bat")), "cam_bien": cb, "phut": phut}
    # Ngoại vi NHÌN LẠI (bot chọn ở `co_nguoi_nha`): gửi thì kiểm, không gửi thì giữ cái đang có.
    if "giu" in x:
        giu = str(x.get("giu") or "")
        if giu and not giu.startswith("binary_sensor."):
            raise ValueError("Tắt khi vắng: ngoại vi nhìn lại là binary_sensor.")
        ra["giu"] = giu
    if "roi" in x:
        roi = str(x.get("roi") or "")
        if roi and not roi.startswith("binary_sensor."):
            raise ValueError("Tắt khi vắng: cảm biến «đã rời khu» là binary_sensor.")
        ra["roi"] = roi
    if "roi_phut" in x:
        # Tắt nhanh theo «đã rời khu» chỉ khi người mới ở không quá ngần này phút (đi ngang);
        # None = mọi lúc. Bot chọn ở `co_nguoi_nha` (`roi_khi_o_duoi`).
        rp = x.get("roi_phut")
        if rp not in (None, "") and (not isinstance(rp, (int, float)) or not 0 < float(rp) <= 240):
            raise ValueError("Tắt khi vắng: «roi_phut» là số phút 1–240 hoặc để trống.")
        ra["roi_phut"] = float(rp) if rp not in (None, "") else None
    if "nhin" in x:
        if not isinstance(x.get("nhin") or [], list):
            raise ValueError("Tắt khi vắng: «nhin» là danh sách tên camera.")
        ra["nhin"] = [str(c) for c in x.get("nhin") or []]
    return ra


def _so_do(tb: str) -> tuple[set[str], set[str]]:
    """(cảm biến nhị phân, cảm biến số) trong SƠ ĐỒ KÍCH HOẠT của thiết bị — điều kiện và
    ngoại vi (`hieu_thiet_bi_nha`, đã áp phần chủ máy sửa). Chủ máy 26/09/2026: bật/tắt
    thiết bị "cơ sở là lấy theo sơ đồ kích hoạt"."""
    try:
        from services import ha_client, hieu_thiet_bi_nha as h
        # Tầng hiểu thiết bị có thể xếp cặp gương dưới mã còn lại (đo 27/09/2026: cả 8 cặp có
        # dữ liệu đều nằm dưới switch.*, còn trang kích hoạt dùng light.*) — tìm theo cả cặp.
        ma_cap = [tb, ha_client.thuc_the_guong(tb)]
        tq, nvh = h.thoi_quen_hoc(), h.ngoai_vi_hoc()
        dk = next(((tq.get(m) or {}).get("bat") for m in ma_cap if (tq.get(m) or {}).get("bat")), [])
        nv = next(((nvh.get(m) or {}).get("ngoai_vi") for m in ma_cap if (nvh.get(m) or {}).get("ngoai_vi")), [])
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
    if key.startswith("lịch:"):
        from services import lich_sinh_hoat as lsh
        m = lsh.tim(key[5:]) or {"ten": key[5:]}
        return f"{'ngoài' if nho_hon else 'đang'} giờ {m['ten']}"
    if key == PHUT_DA_O:
        return f"{'ở chưa quá' if nho_hon else 'đã ở hơn'} {nguong:.3g} phút"
    if key.startswith(PHUT_TU):
        ma = key[len(PHUT_TU):]
        return (f"{ten.get(ma, ma)} thấy người trong {nguong:.3g} phút qua" if nho_hon
                else f"{ten.get(ma, ma)} không thấy người đã hơn {nguong:.3g} phút")
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
    if duoi == O_LAI:
        return f"có người ở lại chỗ {ten.get(ma, ma)}"
    return f"{ten.get(ma, ma)} {duoi}"


def _giay_dong_loat(ro: sqlite3.Connection, tu: float, den: float) -> set[int]:
    """Những giây có ≥ DONG_LOAT thiết bị ĐIỀU KHIỂN đổi cùng lúc — việc của máy.

    Đếm THIẾT BỊ THẬT, không đếm thực thể: cặp gương đổi cùng giây là một. Đo 27/09/2026, 30
    ngày: 95/166 giây "đồng loạt" chỉ đạt ngưỡng vì cặp gương bị đếm hai lần (vd 06:20:56 chỉ
    đèn bếp + đèn nhà tắm) — lần bấm tay thật bị loại khỏi bằng chứng có người."""
    mau = " OR ".join(f"thiet_bi LIKE '{m}.%'" for m in _MIEN_DIEU_KHIEN)
    theo_giay: dict[int, set[str]] = {}
    for g, tb in ro.execute(
            f"SELECT CAST(ts AS INTEGER), thiet_bi FROM su_kien WHERE ts>=? AND ts<? AND truong='state'"
            f" AND ({mau})", (tu, den)):
        theo_giay.setdefault(int(g), set()).add(str(tb))
    chinh: dict[str, str] = {}
    return {g for g, ds in theo_giay.items() if len(ds) >= DONG_LOAT
            and len({chinh.setdefault(t, _chinh(t)) for t in ds}) >= DONG_LOAT}


def _su_kien_nguon(ro: sqlite3.Connection, tu: float, den: float, bo: set[str],
                   chi: set[str] | None = None) -> list[tuple[float, str]]:
    """(ts, tên nguồn) của cảm biến nhị phân, chỉ hai mốc có nghĩa: "có người vào" (bật
    sau ≥ VANG giây tắt) và "vắng" (tắt giữ ≥ VANG giây; mốc đặt ở CUỐI quãng chờ — lúc
    ấy mới biết, đặt ở đầu là rò rỉ tương lai)."""
    ra: list[tuple[float, str]] = []
    tat_tu: dict[str, float] = {}
    hang = [(float(ts), str(ma), str(gt)) for ts, ma, gt in ro.execute(
        "SELECT ts, thiet_bi, gia_tri FROM su_kien WHERE ts>=? AND ts<? AND truong='state'"
        " AND thiet_bi LIKE 'binary_sensor.%' ORDER BY ts", (tu, den))]
    # Cảm biến ghép: dựng từ lịch sử cảm biến gốc (không nằm trong kho). Bỏ mốc đầu (giá trị lúc
    # ``tu``) cho cùng luật với cảm biến thật — chúng cũng chỉ có mốc khi ĐỔI.
    hang += [(t, ma, g) for ma in _cbg.ds() if ma not in bo and (chi is None or ma in chi)
             for t, g in _cbg.chuoi(ro, ma, tu, den)[1:]]
    hang.sort()
    for ts, ma, gt in hang:
        gt = gt.lower()
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
    """Trạng thái HA + cảm biến ghép bot tự tính (``cam_bien_ghep``) — cùng một dạng."""
    try:
        from services import ha_client
        st = list(ha_client.get_states() or [])
    except Exception:  # noqa: BLE001
        return []
    tt = {str(s["entity_id"]): str(s.get("state") or "").lower() for s in st}
    return st + _cbg.hien_tai(tt)


def _trang_thai_mot(ma: str) -> str:
    """Trạng thái hiện tại (chữ thường) của một thực thể HA hoặc cảm biến ghép."""
    if _cbg.la_ghep(ma):
        return next((str(s["state"]) for s in _cbg.hien_tai() if s["entity_id"] == ma), "")
    from services import ha_client
    return str((ha_client.get_state(ma) or {}).get("state") or "").lower()


def _ten_ha() -> dict[str, str]:
    return {str(s["entity_id"]): str((s.get("attributes") or {}).get("friendly_name") or s["entity_id"])
            for s in _trang_thai_ha()}


def _lop(dc: tuple[str, ...]) -> set[str]:
    return {str(s["entity_id"]) for s in _trang_thai_ha()
            if (s.get("attributes") or {}).get("device_class") in dc}


def _dac_trung(luc: float, nguon: str, ds_nguon: list[str],
               lux: dict[str, tuple[list[float], list[str]]]) -> dict[str, float]:
    """Giờ + nguồn nào (one-hot) + độ sáng CHẶT TRƯỚC lúc đó (`tq._truoc`) + đang ở mục
    nào của lịch sinh hoạt.

    Lux là đại lượng vật lý của đúng việc bật đèn nên mọi cảm biến độ sáng đều được
    đưa vào; cây tự bỏ cái không liên quan. Lịch là LỜI KHAI theo giờ + thứ, không rò
    tương lai: giờ thôi thì cây không biết thứ 2 ăn tối muộn hơn thứ 3."""
    from services import lich_sinh_hoat as lsh, thoi_quen_nha as tq

    d = datetime.fromtimestamp(luc, _TZ)
    x: dict[str, float] = {"giờ": d.hour + d.minute / 60}
    for m in lsh.ds():
        x[f"lịch:{m['ma']}"] = 1.0 if lsh.trong(m, luc) else 0.0
    for n in ds_nguon:
        x[f"[{n}]"] = 1.0 if n == nguon else 0.0
    for ma, (ts, gt) in lux.items():
        try:
            x[ma] = float(tq._truoc(ts, gt, luc))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass
    return x


def _nhan_da_cham(tb: str, hd: str) -> list[tuple[float, str, str]]:
    """(ts, ket_qua:cach, nguồn) những lần bot đã hỏi/làm cho hướng này — nhãn của chính chủ máy.
    Nguồn để mỗi câu trả lời chỉ làm nhãn cho mẫu của ĐÚNG nguồn đã khiến bot hỏi."""
    from services import du_doan_nha as dd
    with dd._khoa:
        return [(float(r["ts"]), str(r["ket_qua"]) + ":" + str(r["cach"]), str(r["nguon"] or ""))
                for r in dd._db().execute(
                    "SELECT ts, ket_qua, cach, json_extract(boi_canh, '$.nguon') nguon FROM du_doan"
                    " WHERE ten=? ORDER BY ts", (_ten_tt(tb, hd),))]


# ── Có người Ở LẠI — chưa đủ tin thì hỏi để học ────────────────────────────
# Chủ máy 29/09/2026, quạt phòng khách: luật «người vào + nhiệt» bật quạt lúc người chỉ đi ngang
# (16:11 radar vừa báo 0 giây, 13:00 radar chớp 6 giây) — "bật cũng phải căn cứ thực tế", "rất
# nhiều yếu tố, liên hệ với nhau": camera phòng khách, camera bếp (chung cư — camera bếp thấy cả
# phòng khách), hai radar. Đo 30 ngày: 102 lần người bật quạt, 98 lần lúc có người; nhưng người
# ở lại ≥ 3 phút mà quạt tắt thì chỉ 20% lượt người bật (tốt nhất 44%) — lịch sử không qua nổi cổng
# 60%. Chủ máy chọn: CHƯA ĐỦ TIN THÌ HỎI (``hoi_de_hoc``), câu trả lời là nhãn học; đủ thang thì
# tự làm như mọi luật khác.
#
# Lượt ở = hợp mọi cảm biến hiện diện trong sơ đồ, khe tắt ngắn hơn VANG gộp lại (cùng nghĩa
# "vắng" của nguồn). Ở LẠI = lượt đã dài ≥ ``phut`` — bot tự rút mỗi lượt học: phân vị
# O_LAI_PHAN_VI của "đã ở bao lâu" lúc người TỰ bật (quạt: 5,4 phút — 60% lượt ở ngắn hơn 1 phút
# là người đi ngang). Mỗi lượt ở hỏi/làm nhiều nhất MỘT lần; người đã tự chạm thiết bị trong lượt
# thì thôi — anh tắt quạt bot vừa bật thì bot không bật lại tới lượt ở sau.
O_LAI = "có người ở lại"
O_LAI_PHAN_VI = 0.25
#: Lúc sống: nhìn lại ngần này giây để dựng lượt ở đang diễn ra.
O_LAI_NHIN = 6 * 3600
#: Lúc sống: xét lại lượt ở không dày hơn ngần này giây (radar báo hàng nghìn lần mỗi ngày).
O_LAI_XET_GIAY = 60
#: Đặc trưng của cây: lượt ở đã dài bao lâu, và mỗi cảm biến trong sơ đồ thấy người cách đây bao
#: lâu (cắt ở O_LAI_TRAN phút) — radar và camera nhấp nháy, "vừa thấy" bền hơn "đang thấy".
PHUT_DA_O = "phút đã ở"
PHUT_TU = "phút từ "
O_LAI_TRAN = 60.0
_hen_o_lai: dict[str, threading.Timer] = {}
_o_lai_xet_luc: dict[str, float] = {}
#: Lượt ở (mốc bắt đầu) đã phát nguồn «ở lại» — mỗi lượt xét MỘT lần, kể cả khi lần đó bot im.
_o_lai_da_phat: dict[str, float] = {}


def _chuoi_nhi_phan(ro: sqlite3.Connection, ma: str, tu: float, den: float) -> tuple[list[float], list[str]]:
    """Trạng thái (chữ thường) của ``ma`` theo thời gian, kể cả giá trị đang có lúc ``tu``."""
    if _cbg.la_ghep(ma):
        ch = _cbg.chuoi(ro, ma, tu, den)
    else:
        ch = [(float(t), str(g).lower()) for t, g in ro.execute(
            "SELECT ts, gia_tri FROM (SELECT ts, gia_tri FROM su_kien WHERE thiet_bi=? AND truong='state'"
            " AND ts<? ORDER BY ts DESC LIMIT 1) UNION ALL SELECT ts, gia_tri FROM su_kien"
            " WHERE thiet_bi=? AND truong='state' AND ts>=? AND ts<? ORDER BY ts", (ma, tu, ma, tu, den))]
    return [t for t, _ in ch], [g for _, g in ch]


def _luot_o(dong: dict[str, tuple[list[float], list[str]]], den: float) -> list[tuple[float, float]]:
    """Lượt có người (bắt đầu, kết thúc): hợp mọi cảm biến trong ``dong``, khe tắt ngắn hơn VANG
    gộp lại. Lượt còn đang diễn ra (còn cảm biến báo, hoặc tắt chưa đủ VANG) kết thúc ở ``den``."""
    tt: dict[str, str] = {}
    ra: list[list[float]] = []
    a: float | None = None
    for t, ma, g in sorted((t, ma, g) for ma, (ts, gt) in dong.items() for t, g in zip(ts, gt)):
        co = any(v == "on" for v in tt.values())
        tt[ma] = g
        moi = any(v == "on" for v in tt.values())
        if moi and not co:
            a = t
        elif co and not moi and a is not None:
            ra.append([a, t])
            a = None
    if a is not None:
        ra.append([a, den])
    gop: list[list[float]] = []
    for x in ra:
        if gop and x[0] - gop[-1][1] < VANG:
            gop[-1][1] = x[1]
        else:
            gop.append(x)
    if gop and den - gop[-1][1] < VANG:
        gop[-1][1] = den
    return [(x[0], x[1]) for x in gop]


def _dac_trung_o_lai(luc: float, bat_dau: float, dong: dict[str, tuple[list[float], list[str]]]) -> dict[str, float]:
    x = {PHUT_DA_O: (luc - bat_dau) / 60}
    for ma, (ts, gt) in dong.items():
        i = bisect.bisect_right(ts, luc) - 1
        while i >= 0 and gt[i] != "on":
            i -= 1
        x[PHUT_TU + ma] = min(O_LAI_TRAN, (luc - ts[i]) / 60) if i >= 0 else O_LAI_TRAN
    return x


def _hoc_phut_o_lai(luot: list[tuple[float, float]], bat: list[float], moc_thu: float) -> tuple[float | None, int]:
    """(phút "ở lại", số lần người tự bật trong một lượt ở) — phần học, trước ``moc_thu``."""
    bd = [a for a, _ in luot]
    da = []
    for t in bat:
        i = bisect.bisect_right(bd, t) - 1
        if t < moc_thu and i >= 0 and luot[i][1] >= t:
            da.append((t - luot[i][0]) / 60)
    if len(da) < NGUON_TOI_THIEU:
        return None, len(da)
    da.sort()
    return round(da[int(O_LAI_PHAN_VI * (len(da) - 1))], 1), len(da)


def _o_lai_luc(tb: str, luc: float) -> tuple[float, dict[str, tuple[list[float], list[str]]]] | None:
    """(lúc lượt ở hiện tại bắt đầu, chuỗi các cảm biến trong sơ đồ) — không có ai thì None."""
    from services import lich_su_nha
    ol = ((_nap()["mo_hinh"].get(tb) or {}).get("o_lai")) or {}
    if not ol.get("cam_bien"):
        return None
    ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    try:
        dong = {m: _chuoi_nhi_phan(ro, m, luc - O_LAI_NHIN, luc) for m in ol.get("dac_trung") or ol["cam_bien"]}
    finally:
        ro.close()
    # Kho ghi qua HÀNG ĐỢI (`lich_su_nha.ghi`) nên lần "on" vừa tới có thể chưa xuống đĩa — trạng
    # thái HA lúc này mới là sự thật của "bây giờ". Không thêm thì lượt ở của cảm biến bật một lần
    # rồi đứng yên (camera, cảm biến ghép) bị bỏ lỡ trọn.
    tt = {str(s["entity_id"]): str(s.get("state") or "").lower() for s in _trang_thai_ha()}
    for m, (ts, gt) in dong.items():
        if tt.get(m) == "on" and (not gt or gt[-1] != "on"):
            ts.append(luc)
            gt.append("on")
    luot = _luot_o({m: dong[m] for m in ol["cam_bien"] if m in dong}, luc)
    return (luot[-1][0], dong) if luot and luot[-1][1] >= luc else None


def _da_xong_luot(tb: str, bat_dau: float) -> bool:
    """Trong lượt ở này bot đã hỏi/làm hướng bật, hoặc người đã tự chạm thiết bị."""
    from services import du_doan_nha as dd, lich_su_nha
    with dd._khoa:
        if dd._db().execute("SELECT 1 FROM du_doan WHERE ten=? AND ts>=? LIMIT 1",
                            (_ten_tt(tb, "on"), bat_dau)).fetchone():
            return True
    ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    try:
        return ro.execute("SELECT 1 FROM su_kien WHERE thiet_bi=? AND truong='state' AND do_ai=0 AND ts>=?"
                          " LIMIT 1", (tb, bat_dau)).fetchone() is not None
    finally:
        ro.close()


def _xet_o_lai(tb: str) -> None:
    """Lượt ở đang diễn ra đủ ``phut`` phút → phát nguồn «ở lại»; chưa đủ thì hẹn giờ xét lại."""
    with _khoa:
        cu = _hen_o_lai.pop(tb, None)
    if cu:
        cu.cancel()
    try:
        ol = ((_nap()["mo_hinh"].get(tb) or {}).get("o_lai")) or {}
        if ol.get("phut") is None or not (_nap()["thiet_bi"].get(tb) or {}).get("hoi_de_hoc"):
            return
        luc = time.time()
        o = _o_lai_luc(tb, luc)
        if o is None:
            return
        con = o[0] + float(ol["phut"]) * 60 - luc
        if con > 0:
            t = threading.Timer(con + 1, _xet_o_lai, args=(tb,))
            t.daemon = True
            with _khoa:
                _hen_o_lai[tb] = t
            t.start()
            return
        with _khoa:
            if _o_lai_da_phat.get(tb) == o[0]:
                return
            _o_lai_da_phat[tb] = o[0]
        if not _da_xong_luot(tb, o[0]):
            _phat(f"{tb} {O_LAI}", luc)
    except Exception as exc:  # noqa: BLE001
        logger.warning({"event": "kich_hoat_o_lai_loi", "thiet_bi": tb, "error": str(exc)[:200]})


def _theo_o_lai(ma: str, gt: str, ds: dict[str, dict[str, Any]]) -> None:
    """Cảm biến trong sơ đồ vừa thấy người: thiết bị nào đang hỏi để học thì xét lượt ở."""
    if gt != "on":
        return
    luc = time.time()
    for tb, cd in ds.items():
        ol = ((_nap()["mo_hinh"].get(tb) or {}).get("o_lai")) or {}
        if not cd.get("hoi_de_hoc") or ol.get("phut") is None or ma not in (ol.get("cam_bien") or []):
            continue
        with _khoa:
            if tb in _hen_o_lai or luc - _o_lai_xet_luc.get(tb, 0.0) < O_LAI_XET_GIAY:
                continue
            _o_lai_xet_luc[tb] = luc
        threading.Thread(target=_xet_o_lai, args=(tb,), name="kich-hoat-o-lai", daemon=True).start()


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
        cho_vang = _hoc_cho_vang(ro, cd, ts_tb, gt_tb, tu, den)
        nhieu = _hoc_nhieu(ro, tb, tu, den) if (cd.get("tat_khi_vang") or {}).get("bat") else {}
        muc = _hoc_muc(ro, tb, tu, den)
        hay_bat = {d["cam_bien"]: _hoc_hay_bat(ro, tb, d["cam_bien"], d["co_mat"], den - NGAY_HAY_BAT * 86400, den)
                   for l in cd.get("luat_chu") or [] for d in l.get("neu") or [] if d["loai"] == "muc_hay_bat"}
        hien = sorted(nhi_phan & _lop(_LOP_HIEN_DIEN)) if cd.get("hoi_de_hoc") else []
        dong_ol = {m: _chuoi_nhi_phan(ro, m, tu, den) for m in sorted(nhi_phan)} if hien else {}
    finally:
        ro.close()
    luot = _luot_o({m: dong_ol[m] for m in hien}, den) if hien else []
    phut_ol, lan_ol = _hoc_phut_o_lai(luot, bat, moc_thu) if hien else (None, 0)
    ten_ol = f"{tb} {O_LAI}"
    ts_sk = [t for t, _ in sk]
    ten = _ten_ha()
    ra: dict[str, Any] = {"luc": den, "co_so": "so_do" if nhi_phan else "tu_do", "dac_trung_so": ma_lux,
                          "den_gop": _den_gop_hoc(ts_tb, gt_tb, lux),
                          "vang_quay_lai": _vang_quay_lai(sk_toan_nha, nhi_phan, den - tu),
                          "goi_y_them": _goi_y_them(sk_toan_nha, bat, ts_tb, gt_tb, nhi_phan),
                          "cho_vang": cho_vang.get("do") or {}, "hay_bat": hay_bat, "nhieu": nhieu, "muc": muc,
                          "o_lai": {"phut": phut_ol, "lan": lan_ol, "cam_bien": hien,
                                    "dac_trung": sorted(dong_ol)} if hien else {}}
    for hd, dich in (("on", bat), ("off", tat)):
        truoc: Counter = Counter()
        for t in dich:
            if t >= moc_thu:
                continue
            i, j = bisect.bisect_left(ts_sk, t - TRUOC), bisect.bisect_left(ts_sk, t)
            truoc.update({n for _, n in sk[i:j]})
        ds_nguon = sorted(n for n, v in truoc.items() if v >= NGUON_TOI_THIEU)
        co_ol = hd == "on" and phut_ol is not None and ten_ol not in bo
        if co_ol:
            truoc[ten_ol] = lan_ol
            ds_nguon = sorted({*ds_nguon, ten_ol})
        nguoi = sorted(bat + tat)
        cham_moi = _nhan_da_cham(tb, hd)
        cham = [(t, kq) for t, kq, n in cham_moi if not n.endswith(" " + O_LAI)]
        cham_ol = [(t, kq) for t, kq, n in cham_moi if n == ten_ol]
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
        for a, b in luot if co_ol else []:
            # Mẫu «ở lại»: bot đã hỏi/làm trong lượt thì câu chủ máy trả lời là nhãn (lấy đúng lúc
            # hỏi); chưa thì lúc lượt đủ ``phut_ol`` — nhãn là người có tự bật trước khi lượt hết.
            da_hoi = [(tc, kq.split(":")[0]) for tc, kq in cham_ol if a <= tc <= b]
            if da_hoi:
                t, kq = da_hoi[0]
                if kq not in ("dung", "sai"):
                    continue
                y = int(kq == "dung")
            else:
                t = a + phut_ol * 60  # type: ignore[operator]
                g = str(tq._truoc(ts_tb, gt_tb, t) or "").strip().lower()
                if t >= b or t < tu or g in _KHONG_RO or g == "on":
                    continue
                if any(a <= c < t for c in nguoi):
                    continue        # người đã tự chạm trong lượt — cùng luật lúc sống (`_da_xong_luot`)
                y = int(any(t <= d <= b for d in bat))
            mau.append(({**_dac_trung(t, ten_ol, ds_nguon, lux), **_dac_trung_o_lai(t, a, dong_ol)}, y, t))
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
        if cho_vang and tb in _nap()["thiet_bi"]:
            cd_that = _nap()["thiet_bi"][tb]
            cd_that["cho_vang"] = cho_vang["cho"]
            # Lần nới vì tắt nhầm TRƯỚC lượt học này đã nằm trong số đo mất dấu — bỏ đi; lần nới
            # xảy ra trong lúc đang học thì giữ tới lượt sau.
            cd_that["noi_vang"] = {h: x for h, x in (cd_that.get("noi_vang") or {}).items()
                                   if float(x.get("luc") or 0) >= den}
        _luu()
    logger.info({"event": "kich_hoat_hoc", "thiet_bi": tb,
                 "kiem": {hd: ra[hd]["kiem"] for hd in HANH_DONG}})
    return ra


#: Phần đèn góp vào cảm biến độ sáng: đo độ nhảy ở mỗi lần thiết bị đổi bật/tắt — giá trị
#: ĐẦU TIÊN trong ngần này giây sau trừ giá trị ngay trước. Cần ≥ DEN_GOP_MAU lần.
DEN_GOP_CUA_SO = 90
DEN_GOP_MAU = 5


def _den_gop_hoc(ts_tb: list[float], gt_tb: list[str],
                 lux: dict[str, tuple[list[float], list[str]]]) -> dict[str, float]:
    """{cảm biến: số lux thiết bị góp vào}. Đo 26/09/2026 30 ngày, đèn phòng ngủ: bật +63
    (41 lần, giữa 61–71), tắt −68 (47 lần) — đều tới mức tách được trời với đèn."""
    ra: dict[str, float] = {}
    for ma, (ts, gt) in lux.items():
        so = []
        for t, v in zip(ts, gt):
            try:
                so.append((t, float(v)))
            except (TypeError, ValueError):
                pass
        moc = [t for t, _ in so]
        nhay = []
        for t, v in zip(ts_tb, gt_tb):
            if str(v).lower() not in HANH_DONG:
                continue
            i = bisect.bisect_left(moc, t)
            if i == 0 or i >= len(so) or so[i][0] - t > DEN_GOP_CUA_SO:
                continue
            d = so[i][1] - so[i - 1][1]
            nhay.append(d if str(v).lower() == "on" else -d)
        if len(nhay) >= DEN_GOP_MAU:
            nhay.sort()
            ra[ma] = round(nhay[len(nhay) // 2], 1)
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


#: Gợi ý thêm vào sơ đồ khi: sau lúc cảm biến báo có người vào (thiết bị đang tắt), người bật
#: trong CHO giây ở ít nhất ngần này phần số lần. Đo 26/09/2026: đèn trần — cửa chính 59/106 =
#: 56%, các cảm biến khác 2–18%; đèn phòng ngủ — phòng ngủ 29%, ban công/bếp/cửa 5–9% (người đi
#: ngang qua, chủ máy đã hỏi "nó để tránh ảo hay để điều khiển").
GOI_Y_TY_LE = 0.25


#: Số phút xét cho bảng "vắng bao lâu rồi lại có người" trên thẻ.
VANG_MOC_PHUT = (3, 5, 10, 15, 20, 30, 60)


def _vang_quay_lai(sk: list[tuple[float, str]], nhi_phan: set[str], giay: float) -> dict[str, dict[str, float]]:
    """Mỗi cảm biến trong sơ đồ: trung bình MỖI NGÀY có mấy lần báo vắng ≥ N phút rồi lại có
    người — số lần "tắt khi vắng N phút" sẽ tắt trong khi người quay lại / còn đó. Cho chủ máy
    chọn số phút bằng số đo, không đoán."""
    ngay = max(1.0, giay / 86400)
    ra: dict[str, dict[str, float]] = {}
    for ma in sorted(nhi_phan):
        vang = sorted(t for t, n in sk if n == f"{ma} vắng")
        vao = [t for t, n in sk if n == f"{ma} có người vào"]
        # "vắng" đặt ở t0 + VANG; lần "vào" kế tiếp cho độ dài quãng vắng.
        dai = []
        for t in vao:
            i = bisect.bisect_left(vang, t) - 1
            if i >= 0 and t - vang[i] < 86400:
                dai.append((t - vang[i] + VANG) / 60)
        ra[ma] = {str(n): round(sum(1 for x in dai if x >= n) / ngay, 1) for n in VANG_MOC_PHUT}
    return ra


def _goi_y_them(sk: list[tuple[float, str]], bat: list[float], ts_tb: list[float], gt_tb: list[str],
                nhi_phan: set[str]) -> list[dict[str, Any]]:
    """Cảm biến NGOÀI sơ đồ mà báo có người vào rồi người hay bật thiết bị — gợi ý chủ máy thêm
    vào sơ đồ (bot không tự thêm). Đo 26/09/2026: sơ đồ đèn trần phòng khách thiếu cảm biến cửa
    chính, nguồn mạnh nhất của nó — học theo sơ đồ thì 0 lần đoán."""
    from services import thoi_quen_nha as tq

    tong: Counter = Counter()
    trung: Counter = Counter()
    for t, n in sk:
        ma = n.split(" ")[0]
        if not n.endswith(" có người vào") or ma in nhi_phan:
            continue
        g = tq._truoc(ts_tb, gt_tb, t)
        if g is None or g.strip().lower() in ("on", *_KHONG_RO):
            continue
        tong[ma] += 1
        i = bisect.bisect_right(bat, t)
        if i < len(bat) and bat[i] - t <= CHO:
            trung[ma] += 1
    ra = [{"ma": m, "so_lan": trung[m], "ty_le": round(trung[m] / tong[m], 2)} for m in tong
          if trung[m] >= NGUON_TOI_THIEU and trung[m] >= GOI_Y_TY_LE * tong[m]]
    return sorted(ra, key=lambda x: -x["ty_le"])[:5]


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
def _khung_dang(x: dict[str, Any], luc: float) -> bool:
    """Khung ngoại lệ có đang diễn ra không — theo mục lịch sinh hoạt, hoặc giờ (+ thứ)."""
    from services import lich_sinh_hoat as lsh

    if x.get("lich"):
        m = lsh.tim(str(x["lich"]))
        return m is not None and lsh.trong(m, luc)
    return x["tu"] != x["den"] and lsh.trong({"tu": x["tu"], "den": x["den"], "thu": x.get("thu") or range(7)}, luc)


def _ten_khung(x: dict[str, Any]) -> str:
    from services import lich_sinh_hoat as lsh

    if x.get("lich"):
        m = lsh.tim(str(x["lich"])) or {}
        return f"khung «{x.get('ten') or m.get('ten') or x['lich']}» theo lịch {m.get('tu', '?')}–{m.get('den', '?')}"
    return f"khung «{x.get('ten') or ''}» {x['tu']}–{x['den']}"


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


#: Đánh dấu trong ``boi_canh`` của lần bot tự làm vì một điều kiện đã KÉO DÀI (vắng liền N phút,
#: sáng liền N phút) — không phải một nhịp cảm biến. Xem `_vua_lam`.
BEN_VUNG = "ben_vung"


def _vua_lam(tb: str, hd: str, *, ca_chieu_nguoc: bool = True) -> bool:
    """Trong NGHI_LAP: đã hỏi/làm CÙNG hướng, hoặc bot đã TỰ làm thiết bị này ở hướng kia.
    Chủ máy 26/09/2026: tự làm nhưng "không máy móc và nhiễu như HA" — đo 3 ngày: automation
    đèn bếp đổi trạng thái ~250 lần theo từng nhịp nhấp nháy của radar. Bot vừa bật thì không
    được tắt ngay chỉ vì cảm biến vừa báo vắng.

    Chốt đổi chiều chỉ chống NHẤP NHÁY: cả lần trước lẫn lần này đều do một nhịp cảm biến tức
    thời. Nên nó KHÔNG áp khi một trong hai là điều kiện kéo dài:

    * ``ca_chieu_nguoc=False`` — lần NÀY kéo dài («tắt khi vắng» đòi vắng LIỀN số phút chủ máy
      đặt). Đo 27/09/2026: bot bật đèn 18:00:32, người ra 18:04:50, đủ 3 phút vắng lúc 18:07:50
      mà chốt giữ đèn tới 18:10:50 — chủ máy nhắn «sao lại bật khi không có người».
    * Lần TRƯỚC kéo dài (``boi_canh`` có `BEN_VUNG`). Đo cùng tối: bot tắt vì vắng 18:10:50,
      chủ máy quay vào 18:17:39, chốt chặn bật tới 18:20:50 — «sao vừa vào không thấy bật đèn»."""
    from services import du_doan_nha as dd
    nguoc = (_ten_tt(tb, "on"), _ten_tt(tb, "off")) if ca_chieu_nguoc else (_ten_tt(tb, hd),) * 2
    with dd._khoa:
        r = dd._db().execute(
            "SELECT 1 FROM du_doan WHERE ts>? AND (ten=? OR (ten IN (?,?) AND cach='tu_lam'"
            f" AND COALESCE(json_extract(boi_canh, '$.{BEN_VUNG}'), 0) = 0)) LIMIT 1",
            (time.time() - NGHI_LAP, _ten_tt(tb, hd), *nguoc)).fetchone()
    return r is not None


def _lam(tb: str, hd: str, *, tu_lam: bool) -> bool:
    """Gọi HA. ``tu_lam``: bot tự quyết → đánh dấu để thay đổi sắp tới ghi do_ai=1. Bật thì kèm MỨC bot
    đã học theo nhiệt độ (`_chon_muc`), nếu đã đủ mẫu."""
    from services import ha_client, lich_su_nha
    if tu_lam:
        # Đánh dấu cả thực thể GƯƠNG: đo 26/09/2026 19:45 bot bật switch.phong_ngu_l1
        # (do_ai=1), light.phong_ngu_l1 đổi cùng giây nhưng ghi do_ai=0 → "người vừa bật",
        # hẹn tắt khi vắng bị chặn, và lượt học sau tưởng người bật.
        for ma in {tb, ha_client.thuc_the_guong(tb)} - {None}:
            lich_su_nha.bot_tu_lam(ma, hd)
    data: dict[str, Any] = {"entity_id": tb}
    if hd == "on":
        try:
            muc = _chon_muc(tb)
        except Exception:  # noqa: BLE001 — chọn mức hỏng thì bật như cũ
            muc = None
        if muc:
            data[muc[0]] = muc[1]
    return ha_client.call_service(tb.split(".")[0], "turn_on" if hd == "on" else "turn_off", data)


# ── MỨC khi bật — bot tự học theo nhiệt độ ─────────────────────────────────
# Chủ máy 29/09/2026: bật theo bậc, "mức quạt theo nóng/mát" (số là VÍ DỤ, phải tự học). Học từ những lần
# NGƯỜI tự chỉnh mức (do_ai=0 — bỏ việc bot làm, khỏi tự khẳng định vòng quanh), mỗi lần gắn nhiệt độ lúc
# đó của cảm biến nhiệt CÙNG KHU. Trường dùng được = tham số của dịch vụ turn_on của miền (danh mục HA).
MUC_MAU = 8
MUC_MOI_GIA_TRI = 3


def _nhiet_khu(tb: str) -> list[str]:
    from services import boi_canh_nha
    khu = boi_canh_nha.phong_cua(tb)
    return sorted(str(s["entity_id"]) for s in _trang_thai_ha()
                  if khu and str(s["entity_id"]).startswith("sensor.")
                  and (s.get("attributes") or {}).get("device_class") == "temperature"
                  and boi_canh_nha.phong_cua(str(s["entity_id"])) == khu)


def _truong_bat(mien: str) -> set[str]:
    from services import ha_client, ha_live
    meta = ((ha_client.get_service_catalog() or {}).get(mien) or {}).get("turn_on") or {}
    ra: set[str] = set()
    ha_live._gom_truong(meta.get("fields"), ra)
    return ra - {"entity_id", "device_id", "area_id"}


def _hoc_muc(ro: sqlite3.Connection, tb: str, tu: float, den: float) -> dict[str, Any]:
    """{truong, cam_bien, moc: [[nhiệt trung vị, giá trị, số lần], …]} — chưa đủ mẫu thì {} (bật như cũ)."""
    from services import thoi_quen_nha as tq
    cb = _nhiet_khu(tb)
    truong = _truong_bat(tb.split(".")[0])
    if not cb or not truong:
        return {}
    ts_n, gt_n = tq._tuyen(ro, cb[0], "state", tu, den)
    tot: dict[str, Any] = {}
    for f in sorted(truong):
        nhom: dict[str, list[float]] = {}
        for t, g in ro.execute("SELECT ts, gia_tri FROM su_kien WHERE thiet_bi=? AND truong=? AND do_ai=0"
                               " AND ts>=? AND ts<?", (tb, f, tu, den)):
            v = tq._truoc(ts_n, gt_n, float(t))
            try:
                nhom.setdefault(str(g), []).append(float(v))
            except (TypeError, ValueError):
                continue
        du = {g: sorted(x) for g, x in nhom.items() if len(x) >= MUC_MOI_GIA_TRI}
        n = sum(len(x) for x in nhom.values())
        if n >= MUC_MAU and len(du) >= 2 and n > tot.get("n", 0):
            tot = {"truong": f, "cam_bien": cb[0], "n": n,
                   "moc": sorted([round(x[len(x) // 2], 1), g, len(x)] for g, x in du.items())}
    return tot


def _chon_muc(tb: str) -> tuple[str, Any] | None:
    """Mức ứng với nhiệt độ lúc này: giá trị có nhiệt trung vị GẦN nhất."""
    m = ((_nap()["mo_hinh"].get(tb) or {}).get("muc")) or {}
    if not m.get("moc"):
        return None
    tt = {str(s["entity_id"]): s.get("state") for s in _trang_thai_ha()}
    try:
        nhiet = float(tt.get(m["cam_bien"]))
    except (TypeError, ValueError):
        return None
    _, g, _n = min(m["moc"], key=lambda x: abs(float(x[0]) - nhiet))
    try:
        v: Any = int(g) if str(g).lstrip("-").isdigit() else float(g)
    except ValueError:
        v = g
    return str(m["truong"]), v


def _bao_tu_lam(tb: str, noi_dung: str) -> None:
    """Báo một việc bot ĐÃ tự làm — trừ thiết bị chủ máy đặt «im lặng». Đo 29/09/2026: quạt phòng
    khách theo "phòng khách có người thật" đổi ~22 lần/ngày mỗi chiều → ~44 tin "đúng hay sai"
    mỗi ngày. Im lặng vẫn chấm được: người làm ngược lại trong ``CHAM_TU_LAM`` là bot ghi sai."""
    from services import thong_bao
    if not (_nap()["thiet_bi"].get(tb) or {}).get("im_lang"):
        thong_bao.gui("nha.goi_y", noi_dung)


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
    o_lai = nguon.endswith(" " + O_LAI)
    # Chưa qua kiểm tiến dần: im — trừ «ở lại» của thiết bị chủ máy cho HỎI ĐỂ HỌC.
    hoc_hoi = not (mh.get("kiem") or {}).get("dat")
    if hoc_hoi and not (o_lai and (_nap()["thiet_bi"].get(tb) or {}).get("hoi_de_hoc")):
        return {"lam": "im", "ly_do": "luật chưa qua kiểm tiến dần"}
    if _nguoi_vua_cham(tb, luc):
        return {"lam": "im", "ly_do": "người vừa tự bật/tắt"}
    khung = next((x for x in (_nap()["thiet_bi"].get(tb) or {}).get("ngoai_le") or []
                  if x.get("hanh_dong") == hd and _khung_dang(x, luc)), None)
    ten_khung = _ten_khung(khung) if khung else ""
    if khung and khung.get("cach", "khong") == "khong":
        return {"lam": "im", "ly_do": f"{ten_khung}: anh đặt không làm"}
    dts = (_nap()["mo_hinh"].get(tb) or {}).get("dac_trung_so")
    lux = {str(s["entity_id"]): ([luc - 1.0], [str(s.get("state"))]) for s in _trang_thai_ha()
           if (str(s["entity_id"]) in dts if dts is not None
               else (s.get("attributes") or {}).get("device_class") == "illuminance")}
    x = _dac_trung(luc, nguon, list(mh["nguon"]), lux)
    if o_lai:
        o = _o_lai_luc(tb, luc)
        if o is None:
            return {"lam": "im", "ly_do": "không còn ai ở lại"}
        x.update(_dac_trung_o_lai(luc, o[0], o[1]))
    p = doan_cay(mh["cay"], x)
    if p < (IM_QUANH if hoc_hoi else P_HOI):
        return {"lam": "im", "ly_do": f"chỉ chắc {p:.0%}", "p": p}
    k, n, cach = quanh_gio(mh.get("theo_gio") or [[0, 0]] * 24, x["giờ"])
    if cach == "im" and not khung:
        return {"lam": "im", "p": p, "ly_do": f"quanh giờ này anh ít khi {_TEN_HD[hd].lower()} ({k}/{n})"}
    ma_nguon = nguon.split(" ")[0]
    tru = (set(((_nap()["mo_hinh"].get(tb) or {}).get("o_lai") or {}).get("cam_bien") or []) if o_lai
           else {ma_nguon} if nguon.endswith(" có người vào") and ma_nguon in _lop(_LOP_HIEN_DIEN) else set())
    if hd == "on" and tru and not nha_co_nguoi(tru, luc, tb):
        return {"lam": "im", "p": p,
                "ly_do": f"nghi báo ảo: {_kiem_ao_cua(tb)['gio']} giờ qua không có dấu hiệu người nào"}
    if hoc_hoi:
        return {"lam": "hoi", "p": p, "x": x,
                "ly_do": f"đã ở {x[PHUT_DA_O]:.0f} phút; em chưa đủ tin nên hỏi anh để học"}
    if khung:
        return {"lam": "hoi", "p": p, "x": x, "ly_do": f"{ten_khung}: anh đặt luôn hỏi"}
    if cach == "hoi":
        return {"lam": "hoi", "p": p, "x": x, "ly_do": f"quanh giờ này mới đúng {k}/{n} — hỏi anh"}
    return {"lam": "tu_lam" if _duoc_tu_lam(tb, hd) else "hoi", "p": p, "x": x}


#: Định vị: Frigate có thể chậm một nhịp mới có sự kiện của người vừa bước vào — không thấy ai thì nhìn lại
#: sau ngần này giây trước khi kết luận "người ở khu khác".
DINH_VI_NHIN_LAI = 2.5


def _dinh_vi(tb: str, nguon: str) -> str | None:
    """Người vừa kích hoạt thật sự đứng ở khu của thiết bị không — bằng TOẠ ĐỘ trên camera.

    Chủ máy 30/09/2026: "nếu đứng ở bếp nhưng cảm biến phòng khách vẫn báo có người, nhưng không kích hoạt
    gì vì không ở phòng khách, và khi cảm biến hiện diện bếp cùng báo có người phải xác định lại tọa độ.
    Cái này train chứ không phải áp đặt cứng". Nên mọi thứ đi từ SƠ ĐỒ NHÀ bot vẽ và người đã chấm:

    * chỉ xét khi nguồn là cảm biến hiện diện (hoặc «ở lại»), và cảm biến của khu LIỀN KỀ (sơ đồ ghi thông /
      có vách) đang cùng báo — lúc đó mới mơ hồ;
    * nhìn các camera mà sơ đồ gán ô cho khu này, chỉ đếm người đứng trong các ô đó (`_nhin_lai`).

    Trả tên camera thấy người trong khu, "" nếu camera nhìn được mà không ai trong khu (người ở khu khác —
    đừng làm), None nếu không cần / không định vị được (chưa có sơ đồ đã chấm, không camera) — làm như cũ."""
    from services import boi_canh_nha, so_do_nha

    ma = nguon.split(" ")[0]
    if not (nguon.endswith(" " + O_LAI) or (nguon.endswith(" có người vào") and ma in _lop(_LOP_HIEN_DIEN))):
        return None
    s = so_do_nha.ap() or {}
    khu = boi_canh_nha.phong_cua(tb)
    p = next((x for x in s.get("phong") or [] if x.get("ten") == khu), None)
    if not p:
        return None
    ke = set(p.get("thong_voi") or []) | set(p.get("vach_voi") or [])
    cams = [c["ten"] for c in s.get("camera") or [] if (c.get("thay") or {}).get(khu)]
    if not ke or not cams:
        return None
    tt = {str(x["entity_id"]): str(x.get("state") or "").lower() for x in _trang_thai_ha()}
    if not any(tt.get(m) == "on" and boi_canh_nha.phong_cua(m) in ke
               for m in _lop(_LOP_HIEN_DIEN) if not _cbg.la_ghep(m)):
        return None                     # không khu liền kề nào cùng báo — không mơ hồ
    thay = _nhin_lai(cams, khu)
    if thay == "":
        time.sleep(DINH_VI_NHIN_LAI)
        thay = _nhin_lai(cams, khu)
    logger.info({"event": "kich_hoat_dinh_vi", "thiet_bi": tb, "nguon": nguon, "thay": thay})
    return thay


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
            if nguon.endswith(" vắng") and _trang_thai_mot(nguon.split(" ")[0]) != "off":
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
            if hd == "on" and _dinh_vi(tb, nguon) == "":
                logger.info({"event": "kich_hoat_dinh_vi_chan", "thiet_bi": tb, "nguon": nguon})
                with _khoa:
                    ds = _nap().setdefault("dinh_vi", [])
                    ds.append({"luc": luc, "thiet_bi": tb, "nguon": nguon, "ket_qua": "cho"})
                    del ds[:-BAO_AO_GIU]
                    _luu()
                return
            vi = (_nap()["mo_hinh"][tb][hd].get("ten") or {}).get(nguon, nguon)
            nhan = {"nguon": nguon, **{k: round(v, 2) for k, v in q["x"].items() if not k.startswith("[")}}
            if q["lam"] == "tu_lam":
                if not _lam(tb, hd, tu_lam=True):
                    return
                id_ = dd.ghi_nhan(_ten_tt(tb, hd), hd, q["p"], nhan, "tu_lam")
            else:
                id_ = dd.ghi_nhan(_ten_tt(tb, hd), hd, q["p"], nhan, "hoi")
        if q["lam"] == "tu_lam":
            # Chủ máy 26/09/2026: "Đáng lẽ đưa ra lựa chọn đúng hay sai chứ".
            _bao_tu_lam(tb,
                        f"🤖 #{id_} Em đã {_TEN_HD[hd].lower()} {_ten_tb(tb)} (vì {vi}, em chắc "
                        f"{q['p']:.0%}).\nĐúng hay sai ạ? Anh trả lời «đúng» hoặc «sai» — sai thì em "
                        f"{_TEN_HD[_NGUOC[hd]].lower()} lại ngay. Không trả lời trong "
                        f"{CHAM_TU_LAM // 60} phút là em tính đúng.")
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
            if t0 is None:
                t0 = _lan_off_kho(ma, luc)
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


def _lan_off_kho(ma: str, luc: float) -> float | None:
    """Mốc cảm biến tắt lần cuối khi RAM không có (tiến trình vừa khởi động lại): trạng thái
    ghi ngay TRƯỚC lần bật này là 'off' thì lấy mốc đó. Đo 26/09/2026 20:36 và 20:47: hai lần
    triển khai liền nhau, chủ máy vào phòng ngủ ngay sau mỗi lần — bot không bật vì RAM chưa
    có mốc tắt (cảm biến đã tắt từ trước khi khởi động)."""
    from services import lich_su_nha
    ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    try:
        if _cbg.la_ghep(ma):
            ch = _cbg.chuoi(ro, ma, luc - 2 * 86400, luc - 0.5)
            r = ch[-1] if ch else None
        else:
            r = ro.execute("SELECT ts, gia_tri FROM su_kien WHERE thiet_bi=? AND truong='state' AND ts<?"
                           " ORDER BY ts DESC LIMIT 1", (ma, luc - 0.5)).fetchone()
    finally:
        ro.close()
    return float(r[0]) if r and str(r[1]).lower() == "off" else None


def _khoi_phuc(ds: dict[str, dict[str, Any]]) -> None:
    """Sau khởi động lại: hẹn «tắt khi vắng» cũ nằm trong RAM đã mất — thiết bị đang bật trong
    phòng đã trống thì hẹn lại phần thời gian còn lại, tính từ lần cảm biến tắt cuối trong kho."""
    from services import ha_client
    luc = time.time()
    for tb, cd in ds.items():
        tv = cd.get("tat_khi_vang") or {}
        cb = list(tv.get("cam_bien") or [])
        try:
            if not tv.get("bat") or tb in _hen_tat or not _deu_vang(cb):
                continue
            if str((ha_client.get_state(tb) or {}).get("state") or "").lower() != "on":
                continue
            tat = [_lan_off_kho(m, luc) for m in cb]
            if any(t is None for t in tat):
                continue
            con = phut_vang(cd, max(tat)) * 60 - (luc - max(tat))  # type: ignore[type-var,arg-type]
            _hen_tat_luc(tb, max(HEN_LAI, con))
        except Exception as exc:  # noqa: BLE001
            logger.warning({"event": "kich_hoat_khoi_phuc_loi", "thiet_bi": tb, "error": str(exc)[:160]})


def _bao_vang(ma: str) -> None:
    with _khoa:
        _hen_vang.pop(ma, None)
    _phat(f"{ma} vắng", time.time())


#: Cửa mở là VÀO hoặc RA. Chủ máy 29/09/2026: "cửa mở và có người đi vào thì phải bật bằng cách xác
#: nhận qua cảm biến và cam". Nguồn BẬT là cảm biến CỬA thì chờ tối đa ngần này giây để cảm biến có
#: người của CHÍNH khu thiết bị (cảm biến bot chọn cho «tắt khi vắng» — radar, camera) báo có người
#: MỚI vào; không ai vào (người đi ra) thì thôi.
CUA_XAC_NHAN_GIAY = 60
CUA_NHIP = 3


def _khu_co_nguoi(tb: str) -> bool | None:
    """Khu của thiết bị lúc này có người không, theo cảm biến «có người» bot đã chọn cho nó (tắt khi
    vắng). None = thiết bị chưa có cảm biến khu nào — không xác nhận được."""
    cb = list(((_nap()["thiet_bi"].get(tb) or {}).get("tat_khi_vang") or {}).get("cam_bien") or [])
    if not cb:
        return None
    tt = {str(s["entity_id"]): str(s.get("state") or "").lower() for s in _trang_thai_ha()}
    return any(tt.get(m) == "on" for m in cb)


def _cho_nguoi_vao(lam: Any, tb: str, *args: Any) -> None:
    """Chạy ``lam(tb, *args)`` khi khu của thiết bị có người MỚI vào trong CUA_XAC_NHAN_GIAY."""
    try:
        truoc = _khu_co_nguoi(tb)
        han = time.time() + CUA_XAC_NHAN_GIAY
        while True:
            if truoc is None:
                lam(tb, *args)
                return
            co = _khu_co_nguoi(tb)
            if co and not truoc:
                lam(tb, *args)
                return
            if not co:
                truoc = False           # khu đang vắng: lần có người sau đó là người mới vào
            if time.time() >= han:
                break
            time.sleep(CUA_NHIP)
        logger.info({"event": "kich_hoat_cua_khong_ai_vao", "thiet_bi": tb})
    except Exception as exc:  # noqa: BLE001
        logger.warning({"event": "kich_hoat_cho_vao_loi", "thiet_bi": tb, "error": str(exc)[:160]})


def _la_cua(nguon: str) -> bool:
    ma = nguon.split(" ")[0]
    return any(str(s["entity_id"]) == ma and (s.get("attributes") or {}).get("device_class") in _LOP_CUA
               for s in _trang_thai_ha())


def _phat(nguon: str, luc: float) -> None:
    mh = _nap()["mo_hinh"]
    cua = nguon.endswith(" có người vào") and _la_cua(nguon)
    for tb, cd in ds_thiet_bi().items():
        chu = cd.get("luat_chu") or []
        for l in chu:
            if nguon in l["khi"]:
                if cua and l["hanh_dong"] == "on":
                    threading.Thread(target=_cho_nguoi_vao, args=(_xu_ly_chu, tb, l, nguon, luc),
                                     name="kich-hoat-cho-vao", daemon=True).start()
                else:
                    threading.Thread(target=_xu_ly_chu, args=(tb, l, nguon, luc),
                                     name="kich-hoat-luat-chu", daemon=True).start()
        co_chu = {l["hanh_dong"] for l in chu}
        for hd in HANH_DONG:
            if hd in co_chu:
                continue                     # luật anh đặt thắng luật bot học ở hướng này
            if nguon in ((mh.get(tb) or {}).get(hd) or {}).get("nguon", []):
                if cua and hd == "on":
                    threading.Thread(target=_cho_nguoi_vao, args=(_xu_ly, tb, hd, nguon, luc),
                                     name="kich-hoat-cho-vao", daemon=True).start()
                else:
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
    if gt == "on":
        # Bot vừa chặn bật vì định vị thấy người ở khu khác mà người tự bật ngay → định vị sai (ô camera của
        # sơ đồ thiếu / lệch). Lượt vẽ sơ đồ sau đọc những lần này (`so_do_nha.de`, mục G).
        with _khoa:
            sua = False
            for x in _nap().get("dinh_vi") or []:
                if x["thiet_bi"] == tb and x.get("ket_qua") == "cho" and 0 <= luc - float(x["luc"]) <= CHO:
                    x["ket_qua"] = "sai"
                    sua = True
            if sua:
                _luu()
    nguoc = "off" if gt == "on" else "on"
    with dd._khoa:
        r = dd._db().execute(
            "SELECT id, boi_canh FROM du_doan WHERE ten=? AND cach='tu_lam' AND ket_qua='cho' AND ts>?",
            (_ten_tt(tb, nguoc), luc - CHAM_TU_LAM)).fetchall()
    for x in r:
        if dd.ghi_sai(int(x["id"])) and nguoc == "off":
            _noi_vang(tb, x["boi_canh"], luc)       # bot tắt vì vắng mà người bật lại ngay


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
        _han_tat.pop(tb, None)
        _ly_do_tat.pop(tb, None)
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
        if ma == tv.get("roi") and gt == "on":
            # Bot học: cảm biến này báo lúc khu đang vắng = người đã sang khu khác → khỏi chờ đủ
            # số phút, chỉ chờ một nhịp quan sát rồi xét lại (`_tat_vi_vang` kiểm lại mọi thứ).
            # Bot chọn «chỉ khi đi ngang» (`roi_phut`) thì người đã ở lâu hơn — LƯU TRÚ — giữ nguyên.
            han = _han_tat.get(tb)
            if (_deu_vang(cb) and han is not None and han - time.time() > ROI_GIAY
                    and roi_sai_quanh_gio(tb, time.time())[0] < _roi_sai_toi_da()
                    and _di_ngang(tb, cb, tv.get("roi_phut"))):
                _hen_tat_luc(tb, ROI_GIAY)
                with _khoa:
                    _ly_do_tat[tb] = "người đã sang khu khác"
            continue
        if ma in cb and gt == "on":
            _hen_tat_huy(tb)
        elif (ma in cb and gt == "off") or (ma == tb and gt == "on"):
            if _deu_vang(cb):
                sang = _troi_sang(tb, cd) is not None
                _hen_tat_luc(tb, float((cd.get("tat_khi_sang") or {}).get("giay") or SANG_VANG_GIAY) if sang
                             else phut_vang(cd, time.time()) * 60)


# ── Thời gian chờ «tắt khi vắng» bot tự học theo giờ ───────────────────────
# Chủ máy 27/09/2026: "mỗi lần đèn bị tắt rồi có người bật lại ngay, bot tự nới thời gian chờ
# cho đúng khung giờ đó; lâu không sai thì rút dần lại" → "tôi cần BOT học" → "50 phút thì lâu
# quá, không tiết kiệm điện" → "nên dùng thời gian MẤT DẤU để học thời gian chờ, chứ không phải
# cả đoạn thời gian dài".
#
# Mất dấu = mọi cảm biến đã chọn cùng báo vắng lúc thiết bị đang bật rồi thấy người lại trong
# MAT_DAU_GIAY (cùng cửa sổ chấm "bật lại ngay" = tắt nhầm). Quãng dài hơn là người đi thật —
# không dạy gì về thời gian chờ. Mỗi lượt học, chờ của giờ h = phân vị MAT_DAU_PHAN_VI của thời
# gian mất dấu quanh h (± MAT_DAU_LAN giờ, 30 ngày) + 1 phút, không dưới số chủ máy đặt. Rút dần
# tự nhiên: mất dấu cũ trôi khỏi cửa sổ 30 ngày.
# Đo 27/09/2026 đèn phòng ngủ (123 lần phòng trống lúc đèn bật, 77 lần mất dấu): tối chờ 6–9
# phút, tắt nhầm 17–22h còn 9 so với 22 khi giữ 3 phút — cách cũ "gấp đôi mỗi lần sai" cho
# cùng số nhầm nhưng chờ tới 50 phút.
MAT_DAU_GIAY = CHAM_TU_LAM
MAT_DAU_PHAN_VI = 0.9
MAT_DAU_LAN = 1
MAT_DAU_MAU = 5


def phut_vang(cd: dict[str, Any], luc: float) -> float:
    """Số phút chờ «tắt khi vắng» khi phòng trống từ ``luc``: lớn nhất trong số chủ máy đặt, số
    bot học cho giờ đó, và lần nới gần nhất vì tắt nhầm (còn hiệu lực tới lượt học sau)."""
    goc = float((cd.get("tat_khi_vang") or {}).get("phut") or MAC_DINH_VANG_PHUT)
    h = str(datetime.fromtimestamp(luc, _TZ).hour)
    hoc = float((cd.get("cho_vang") or {}).get(h) or 0)
    noi = float(((cd.get("noi_vang") or {}).get(h) or {}).get("phut") or 0)
    return max(goc, hoc, noi)


def _quang_vang(ro: sqlite3.Connection, cam_bien: list[str], tu: float, den: float) -> list[tuple[float, float]]:
    """(bắt đầu, kết thúc) những quãng MỌI cảm biến đã chọn cùng báo vắng — đúng điều kiện
    `_deu_vang` lúc sống. Quãng chưa kết thúc thì bỏ (chưa biết người có quay lại không)."""
    if not cam_bien:
        return []
    that = [m for m in cam_bien if not _cbg.la_ghep(m)]
    dau = ",".join("?" * len(that))
    tt: dict[str, str] = {}
    ra: list[tuple[float, float]] = []
    bat_dau: float | None = None
    hang = [(float(t), str(ma), str(gt)) for t, ma, gt in ro.execute(
        f"SELECT ts, thiet_bi, gia_tri FROM su_kien WHERE truong='state' AND ts>=? AND ts<?"
        f" AND thiet_bi IN ({dau}) ORDER BY ts", (tu, den, *that))] if that else []
    # Cảm biến ghép: dựng từ cảm biến gốc, kể cả giá trị lúc ``tu``.
    hang += [(t, ma, g) for ma in cam_bien if _cbg.la_ghep(ma) for t, g in _cbg.chuoi(ro, ma, tu, den)]
    hang.sort()
    for t, ma, gt in hang:
        tt[ma] = gt.lower()
        deu = len(tt) == len(cam_bien) and all(v == "off" for v in tt.values())
        if deu and bat_dau is None:
            bat_dau = float(t)
        elif not deu and bat_dau is not None:
            ra.append((bat_dau, float(t)))
            bat_dau = None
    return ra


def _hoc_cho_vang(ro: sqlite3.Connection, cd: dict[str, Any], ts_tb: list[float], gt_tb: list[str],
                  tu: float, den: float) -> dict[str, Any]:
    """BOT TỰ HỌC thời gian chờ từng giờ từ thời gian mất dấu của chính thiết bị. Trả
    ``{"cho": {giờ: phút}, "do": {...}}``; thiết bị không bật tắt khi vắng → {}."""
    from services import thoi_quen_nha as tq

    tv = cd.get("tat_khi_vang") or {}
    if not tv.get("bat"):
        return {}
    goc = float(tv.get("phut") or MAC_DINH_VANG_PHUT)
    quang = [(a, b) for a, b in _quang_vang(ro, list(tv.get("cam_bien") or []), tu, den)
             if str(tq._truoc(ts_tb, gt_tb, a) or "").lower() == "on"]
    theo_gio: dict[int, list[float]] = {h: [] for h in range(24)}
    for a, b in quang:
        if b - a <= MAT_DAU_GIAY:
            theo_gio[datetime.fromtimestamp(a, _TZ).hour].append((b - a) / 60)
    cho: dict[str, float] = {}
    for h in range(24):
        gop = sorted(x for d in range(-MAT_DAU_LAN, MAT_DAU_LAN + 1) for x in theo_gio[(h + d) % 24])
        if len(gop) >= MAT_DAU_MAU:
            p = gop[min(len(gop) - 1, math.ceil(MAT_DAU_PHAN_VI * len(gop)) - 1)]
            if math.ceil(p) + 1 > goc:
                cho[str(h)] = float(math.ceil(p) + 1)

    def nham(bang: dict[str, float]) -> int:
        n = 0
        for a, b in quang:
            c = max(goc, bang.get(str(datetime.fromtimestamp(a, _TZ).hour), 0.0)) * 60
            n += c <= b - a < c + MAT_DAU_GIAY
        return n
    return {"cho": cho, "do": {"quang": len(quang), "mat_dau": sum(len(v) for v in theo_gio.values()),
                               "nham": nham(cho), "nham_co_dinh": nham({})}}


def _noi_vang(tb: str, boi_canh: Any, luc: float) -> tuple[int, float] | None:
    """Lần tắt vì vắng bị SAI (người bật lại trong CHAM_TU_LAM, hoặc chủ máy trả lời «sai») →
    giờ lúc phòng bắt đầu trống chờ ĐÚNG bằng thời gian mất dấu vừa gặp + 1 phút, tới lượt học
    sau (lượt học đưa lần mất dấu này vào số đo). Trả (giờ, số phút chờ); không phải lần tắt vì
    vắng thì None."""
    try:
        bc = json.loads(boi_canh or "{}")
        vang_tu = float(bc.get("vang_tu"))
    except (TypeError, ValueError, AttributeError):
        return None
    if bc.get("roi") or bc.get("nhieu"):
        return None     # tắt vì «đã rời khu» / nghi nhiễu, không phải vì hết giờ chờ — sai ở đây không nói gì về giờ chờ
    with _khoa:
        cd = _nap()["thiet_bi"].get(tb)
        if not cd:
            return None
        h = datetime.fromtimestamp(vang_tu, _TZ).hour
        moi = max(phut_vang(cd, vang_tu), float(math.ceil((luc - vang_tu) / 60) + 1))
        cd.setdefault("noi_vang", {})[str(h)] = {"phut": moi, "luc": luc}
        _luu()
    logger.info({"event": "kich_hoat_noi_vang", "thiet_bi": tb, "gio": h, "phut": moi})
    return h, moi


#: Hẹn tắt bị chặn TẠM (người vừa chạm, bot vừa làm) thì ngần này giây kiểm lại — không bỏ
#: hẳn. Đo 26/09/2026 19:45: bị chặn một lần là đèn phòng ngủ sáng mãi trong phòng trống.
HEN_LAI = 60


#: Phòng trống lúc trời đã đủ sáng: tắt sau ngần này giây (chủ máy chỉnh được).
SANG_VANG_GIAY = 30
_han_tat: dict[str, float] = {}


#: Nhịp quan sát "người đi đâu" sau lúc khu vắng — cùng số `co_nguoi_nha.ROI_GIAY` (bảng F của đề).
ROI_GIAY = 60
#: Lý do lượt tắt sắp tới (vd "người đã sang khu khác") — để tin báo nói đúng vì sao.
_ly_do_tat: dict[str, str] = {}


def _roi_sai_toi_da() -> int:
    from services import du_doan_nha as dd
    return dd._SAI_TUT_CAP


def roi_sai_quanh_gio(tb: str, luc: float) -> tuple[int, int]:
    """(sai, số lần) trong 10 lần gần nhất bot tắt theo «đã rời khu» QUANH GIỜ này (± MAT_DAU_LAN).

    Chủ máy 29/09/2026: "bật lại thiết bị vào các thời điểm khác nhau thì cũng có giá trị khác
    nhau" — bị bật lại lúc 22h (đang đọc sách, người khác đi ngang bếp) không nói gì về 14h. Sai
    đủ `du_doan_nha._SAI_TUT_CAP` lần quanh giờ nào thì quanh giờ đó thôi tắt nhanh, về chờ đủ."""
    return _sai_quanh_gio(tb, luc, "roi")


def _sai_quanh_gio(tb: str, luc: float, khoa: str) -> tuple[int, int]:
    """(sai, số lần) trong 10 lần gần nhất bot tắt theo đường ``khoa`` (dấu trong bối cảnh) QUANH GIỜ này."""
    from services import du_doan_nha as dd
    h = datetime.fromtimestamp(luc, _TZ).hour
    gan = {(h + d) % 24 for d in range(-MAT_DAU_LAN, MAT_DAU_LAN + 1)}
    with dd._khoa:
        r = dd._db().execute(
            f"SELECT ts, ket_qua FROM du_doan WHERE ten=? AND COALESCE(json_extract(boi_canh, '$.{khoa}'), 0)=1"
            " ORDER BY ts DESC LIMIT 200", (_ten_tt(tb, "off"),)).fetchall()
    ds = [str(x["ket_qua"]) for x in r if datetime.fromtimestamp(float(x["ts"]), _TZ).hour in gan][:10]
    return sum(1 for k in ds if k == "sai"), len(ds)


def _di_ngang(tb: str, cam_bien: list[str], phut: Any) -> bool:
    """Lượt có người vừa hết trong khu dài không quá ``phut`` phút (None = không xét — luôn đúng).

    Chủ máy 29/09/2026: "đi đến đâu sáng đến đó, và nếu lưu trú thì giữ trạng thái". Cùng cách tính
    với cột «đã ở» của mục F trong đề `co_nguoi_nha`: lượt = các lần cảm biến báo có người, khe vắng
    ngắn hơn VANG gộp lại; đã ở = lúc khu bắt đầu vắng − lúc lượt bắt đầu."""
    if phut in (None, ""):
        return True
    from services import lich_su_nha
    luc = time.time()
    ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    try:
        dong = {m: _chuoi_nhi_phan(ro, m, luc - O_LAI_NHIN, luc) for m in cam_bien}
    finally:
        ro.close()
    # Lần tắt gần nhất mỗi cảm biến: bản sống trước (kho ghi qua hàng đợi, có thể chưa xuống đĩa).
    tat = []
    for m, (ts, gt) in dong.items():
        cuoi = next((ts[i] for i in range(len(gt) - 1, -1, -1) if gt[i] == "off"), None)
        t = max((x for x in (_lan_off.get(m), cuoi) if x is not None), default=None)
        if t is not None:
            tat.append(t)
    vang_tu = max(tat) if tat else luc
    luot = [x for x in _luot_o(dong, luc) if x[0] < vang_tu]
    if not luot:
        return False
    return (vang_tu - luot[-1][0]) / 60 <= float(phut)


def _hen_tat_luc(tb: str, giay: float) -> None:
    _hen_tat_huy(tb)
    t = threading.Timer(giay, _tat_vi_vang, args=(tb,))
    t.daemon = True
    with _khoa:
        _hen_tat[tb] = t
        _han_tat[tb] = time.time() + giay
    t.start()


def _tat_vi_vang(tb: str) -> None:
    """Hẹn giờ tới: xét LẠI mọi thứ tại thời điểm này rồi mới tắt."""
    from services import du_doan_nha as dd, ha_client, thong_bao

    with _khoa:
        _hen_tat.pop(tb, None)
        _han_tat.pop(tb, None)
        ly_do = _ly_do_tat.pop(tb, "")
    try:
        cd = ds_thiet_bi().get(tb) or {}
        tv = cd.get("tat_khi_vang") or {}
        luc = time.time()
        if not tv.get("bat") or not _deu_vang(list(tv.get("cam_bien") or [])):
            return
        if str((ha_client.get_state(tb) or {}).get("state") or "").lower() != "on":
            return
        if _nguoi_vua_cham(tb, luc) or _vua_lam(tb, "off", ca_chieu_nguoc=False):
            _hen_tat_luc(tb, HEN_LAI)       # chặn tạm — vẫn vắng thì lát nữa xét lại
            return
        nhin_lai = ""
        if tv.get("giu") and tv.get("nhin") and _trang_thai_mot(str(tv["giu"])) == "on":
            from services import boi_canh_nha
            thay = _nhin_lai(list(tv["nhin"]), boi_canh_nha.phong_cua(tb))
            logger.info({"event": "kich_hoat_nhin_lai", "thiet_bi": tb, "camera": tv["nhin"], "thay": thay})
            if thay is None or thay:
                _hen_tat_luc(tb, HEN_LAI)   # thấy người, hoặc không nhìn được — lát nữa xét lại
                return
            nhin_lai = f"ngoại vi báo có thể còn người, em nhìn lại {', '.join(tv['nhin'])}: không thấy ai"
        if any(x.get("hanh_dong") == "off" and x.get("cach", "khong") == "khong"
               and _khung_dang(x, luc) for x in cd.get("ngoai_le") or []):
            return
        if not _lam(tb, "off", tu_lam=True):
            return
        troi = _troi_sang(tb, cd)
        nhan: dict[str, Any] = {}
        if troi is None:
            # Lúc phòng bắt đầu trống — để lần tắt này bị chấm sai thì biết nới giờ nào, bao lâu.
            tat = [_lan_off_kho(m, luc) for m in tv.get("cam_bien") or []]
            if tat and all(t is not None for t in tat):
                nhan["vang_tu"] = max(tat)  # type: ignore[type-var]
        if ly_do and troi is None:
            nhan["roi"] = 1
        phut = round(phut_vang(cd, float(nhan.get("vang_tu") or luc)))
        vi = (f"phòng trống, trời đã sáng ~{troi:.0f} lux" if troi is not None
              else ly_do or f"vắng {phut} phút")
        if nhin_lai:
            vi += f"; {nhin_lai}"
        id_ = dd.ghi_nhan(_ten_tt(tb, "off"), "off", 1.0, {"nguon": vi, BEN_VUNG: 1, **nhan}, "tu_lam")
        _bao_tu_lam(tb, f"🤖 #{id_} Em đã tắt {_ten_tb(tb)} ({vi}).\nĐúng hay sai ạ? Anh trả "
                        f"lời «đúng» hoặc «sai» — sai thì em bật lại ngay. Không trả lời trong "
                        f"{CHAM_TU_LAM // 60} phút là em tính đúng.")
    except Exception as exc:  # noqa: BLE001
        logger.warning({"event": "kich_hoat_tat_vang_loi", "thiet_bi": tb, "error": str(exc)[:200]})


def _nhin_lai(camera: list[str], khu: str = "", *, chi_chup: bool = False) -> str | None:
    """Chủ máy 29/09/2026: laptop của vợ "là ngoại vi … để kiểm tra lại xem có ở phòng khách
    không" — không phải lý do giữ đèn. Nhìn lại từng camera bot chọn:

    * Có Frigate cho camera đó thì dùng SỐ NGƯỜI Frigate đã đếm sẵn (chủ máy: "nếu có frigate thì
      tận dụng, không thì mới phải chụp") — camera c2a ứng với camera Frigate trùng ĐÚNG tên luồng
      (`src`), số đếm phải còn mới (`mqtt_nha.dem_nguoi` tự từ chối số đóng băng).
    * Không có thì chụp một khung, đếm NGƯỜI bằng YOLO tại chỗ.

    Sơ đồ nhà (`so_do_nha`) đã biết ô nào của khung hình là phòng ``khu`` thì CHỈ đếm người đứng
    trong các ô đó — camera bếp thấy cả phòng khách thì người nấu ăn không giữ đèn phòng khách
    (chủ máy: "danh giới phòng khách và bếp"). Chưa có sơ đồ cho camera đó thì đếm cả khung.

    ``chi_chup``: bỏ số đếm của Frigate, luôn chụp + YOLO — dùng khi chính camera Frigate là bên đang
    nói "không có ai" và cần một con mắt độc lập để xác nhận (xem `_xet_nhieu`).

    Trả tên camera thấy người, "" nếu không camera nào thấy, None nếu không nhìn được camera nào
    (không đoán là vắng)."""
    from services import camera_nha, mqtt_nha, nhin_nha, so_do_nha, yolo_nha

    try:
        frigate = {} if chi_chup else mqtt_nha.dem_nguoi()
    except Exception:  # noqa: BLE001 — không có MQTT thì chụp
        frigate = {}
    if frigate.get("_cu"):
        frigate = {}
    luong = {str(c.get("name")): str(c.get("src") or "") for c in camera_nha.danh_sach()}
    nhin_duoc = False
    for c in camera:
        o = so_do_nha.o_cua_phong(c, khu) if khu else set()
        dem = frigate.get(luong.get(c, ""))
        if dem is not None and o:
            # Frigate chỉ cho SỐ ĐẾM cả khung; biết vùng phòng thì hỏi các sự kiện đang diễn ra
            # (có hộp toạ độ) rồi lọc theo ô.
            try:
                ev = so_do_nha._frigate(f"/api/events?camera={luong[c]}&label=person&in_progress=1", timeout=10)
                nhin_duoc = True
                if any(so_do_nha.o_cua(*so_do_nha.diem_chan((e.get("data") or {}).get("box") or [0, 0, 0, 0])) in o
                       for e in ev if (e.get("data") or {}).get("box")):
                    return c
                continue
            except Exception:  # noqa: BLE001 — không hỏi được sự kiện thì chụp như chưa có Frigate
                pass
        elif dem is not None:
            nhin_duoc = True
            if int(dem.get("nguoi") or 0) > 0:
                return c
            continue
        try:
            _ten, jpeg = camera_nha.chup(c, cho_ai=True, timeout=15.0)
            anh = yolo_nha.doc_anh(jpeg)
            nhin_duoc = True
            cao, rong = anh.shape[:2]
            for v in nhin_nha.vat_the(anh, chi_nhan={"person"}):
                x1, y1, x2, y2 = v.hop
                if not o or so_do_nha.o_cua((x1 + x2) / 2 / rong, y2 / cao) in o:
                    return c
        except Exception as exc:  # noqa: BLE001 — một camera hỏng không làm hỏng lượt tắt
            logger.warning({"event": "kich_hoat_nhin_lai_loi", "camera": c, "error": str(exc)[:160]})
    return "" if nhin_duoc else None


# ── Nghi NHIỄU: sóng báo có người mà camera cùng khu không thấy ai đã lâu ──────
# Chủ máy 30/09/2026: "cùng ban công nhưng cảm biến hiện diện báo có mà frigate báo không lâu rồi, có thể
# bị nhiễu nên cần xác nhận lại bằng vision để tắt thiết bị. Train chung, không phải đặt riêng thiết bị."
# Đo 30 ngày: ban công 141,5 giờ radar báo có người mà camera không thấy ai rồi radar tự tắt (nhiễu);
# người THẬT khuất tầm camera thì 90% camera thấy lại trong 1,7 phút (phòng khách 0,3', bếp 0,7').
# Nên: mỗi thiết bị bot tự rút X = phân vị 90 "khuất tầm rồi camera thấy lại" của CHÍNH khu nó + 1 phút;
# quá X mà vẫn chỉ sóng báo → chụp + YOLO đếm người trong ô của khu (mắt độc lập với Frigate); không ai thì
# tắt. Người bật lại ngay = sai; sai đủ 2/10 quanh giờ nào thì quanh giờ đó thôi (như «rời khu»).
NHIEU_PHAN_VI = 0.9
NHIEU_MAU = 20
_hen_nhieu: dict[str, threading.Timer] = {}


def _cam_bien_khu(tb: str) -> tuple[list[str], list[str]]:
    """(sóng, camera): cảm biến hiện diện THẬT cùng khu với thiết bị — camera là cảm biến sinh từ tích hợp
    Frigate (nền tảng HA), còn lại là sóng/chuyển động. Theo khu vực HA, không theo tên."""
    from services import boi_canh_nha, ha_client
    khu = boi_canh_nha.phong_cua(tb)
    if not khu:
        return [], []
    nen = (ha_client.get_ha_area_index() or {}).get("entity_platform") or {}
    ds = sorted(m for m in _lop(_LOP_HIEN_DIEN) if not _cbg.la_ghep(m) and boi_canh_nha.phong_cua(m) == khu)
    return [m for m in ds if nen.get(m) != "frigate"], [m for m in ds if nen.get(m) == "frigate"]


def _hoc_nhieu(ro: sqlite3.Connection, tb: str, tu: float, den: float) -> dict[str, Any]:
    """Số phút chờ trước khi nghi nhiễu, bot tự rút từ khu của thiết bị. Không đủ mẫu / khu không có cả
    sóng lẫn camera → {} (không dùng)."""
    song, cam = _cam_bien_khu(tb)
    if not song or not cam:
        return {}
    dong = {m: _chuoi_nhi_phan(ro, m, tu, den) for m in song + cam}
    tt: dict[str, str] = {}
    a: float | None = None
    that: list[float] = []
    for t, ma, g in sorted((t, ma, g) for ma, (ts, gt) in dong.items() for t, g in zip(ts, gt)):
        tt[ma] = g
        co_song = any(tt.get(m) == "on" for m in song)
        co_cam = any(tt.get(m) == "on" for m in cam)
        if co_song and not co_cam and a is None:
            a = t
        elif a is not None and (co_cam or not co_song):
            if co_cam:
                that.append((t - a) / 60)       # khuất tầm rồi camera thấy lại = người thật
            a = None
    if len(that) < NHIEU_MAU:
        return {"song": song, "cam": cam, "phut": None, "mau": len(that)}
    that.sort()
    p = that[min(len(that) - 1, math.ceil(NHIEU_PHAN_VI * len(that)) - 1)]
    return {"song": song, "cam": cam, "phut": float(math.ceil(p) + 1), "mau": len(that)}


def _huy_nhieu(tb: str) -> None:
    with _khoa:
        cu = _hen_nhieu.pop(tb, None)
    if cu:
        cu.cancel()


def _hen_nhieu_luc(tb: str, giay: float) -> None:
    _huy_nhieu(tb)
    t = threading.Timer(giay, _xet_nhieu, args=(tb,))
    t.daemon = True
    with _khoa:
        _hen_nhieu[tb] = t
    t.start()


def _theo_nhieu(ma: str, gt: str, ds: dict[str, dict[str, Any]]) -> None:
    """Camera cùng khu vừa tắt mà sóng còn báo → hẹn xét nhiễu; camera thấy lại / sóng hết báo → huỷ."""
    mh = _nap()["mo_hinh"]
    for tb, cd in ds.items():
        nh = (mh.get(tb) or {}).get("nhieu") or {}
        if not nh.get("phut") or not (cd.get("tat_khi_vang") or {}).get("bat") or not (cd.get("tat_khi_vang") or {}).get("nhin"):
            continue
        if ma not in nh["cam"] and ma not in nh["song"]:
            continue
        tt = {str(s["entity_id"]): str(s.get("state") or "").lower() for s in _trang_thai_ha()}
        tt[ma] = gt
        if any(tt.get(m) == "on" for m in nh["cam"]) or not any(tt.get(m) == "on" for m in nh["song"]):
            _huy_nhieu(tb)
        elif tb not in _hen_nhieu:
            _hen_nhieu_luc(tb, float(nh["phut"]) * 60)


def nhieu_sai_quanh_gio(tb: str, luc: float) -> tuple[int, int]:
    """(sai, số lần) trong 10 lần gần nhất bot tắt vì nghi nhiễu QUANH GIỜ này."""
    return _sai_quanh_gio(tb, luc, "nhieu")


def _xet_nhieu(tb: str) -> None:
    """Hẹn tới: vẫn chỉ sóng báo, camera không ai → chụp lại bằng YOLO; không thấy ai thì tắt."""
    from services import boi_canh_nha, du_doan_nha as dd, ha_client

    with _khoa:
        _hen_nhieu.pop(tb, None)
    try:
        cd = ds_thiet_bi().get(tb) or {}
        tv = cd.get("tat_khi_vang") or {}
        nh = ((_nap()["mo_hinh"].get(tb) or {}).get("nhieu")) or {}
        if not nh.get("phut") or not tv.get("bat") or not tv.get("nhin"):
            return
        tt = {str(s["entity_id"]): str(s.get("state") or "").lower() for s in _trang_thai_ha()}
        if any(tt.get(m) == "on" for m in nh["cam"]) or not any(tt.get(m) == "on" for m in nh["song"]):
            return
        if str((ha_client.get_state(tb) or {}).get("state") or "").lower() != "on":
            return
        luc = time.time()
        if _deu_vang(list(tv.get("cam_bien") or [])):
            return                          # đã vắng: đường «tắt khi vắng» lo
        if _nguoi_vua_cham(tb, luc) or _vua_lam(tb, "off", ca_chieu_nguoc=False):
            _hen_nhieu_luc(tb, HEN_LAI)
            return
        if nhieu_sai_quanh_gio(tb, luc)[0] >= _roi_sai_toi_da():
            return
        if any(x.get("hanh_dong") == "off" and x.get("cach", "khong") == "khong"
               and _khung_dang(x, luc) for x in cd.get("ngoai_le") or []):
            return
        thay = _nhin_lai(list(tv["nhin"]), boi_canh_nha.phong_cua(tb), chi_chup=True)
        logger.info({"event": "kich_hoat_nghi_nhieu", "thiet_bi": tb, "thay": thay})
        if thay is None or thay:
            _hen_nhieu_luc(tb, float(nh["phut"]) * 60)   # thấy người / không nhìn được: lát nữa xét lại
            return
        if not _lam(tb, "off", tu_lam=True):
            return
        vi = (f"cảm biến sóng báo có người nhưng camera không thấy ai quá {nh['phut']:g} phút; em chụp "
              f"{', '.join(tv['nhin'])} nhìn lại: không có ai — nghi cảm biến nhiễu")
        id_ = dd.ghi_nhan(_ten_tt(tb, "off"), "off", 1.0, {"nguon": vi, BEN_VUNG: 1, "nhieu": 1}, "tu_lam")
        _bao_tu_lam(tb, f"🤖 #{id_} Em đã tắt {_ten_tb(tb)} ({vi}).\nĐúng hay sai ạ? Anh trả lời «đúng» hoặc "
                        f"«sai» — sai thì em bật lại ngay. Không trả lời trong {CHAM_TU_LAM // 60} phút là em tính đúng.")
    except Exception as exc:  # noqa: BLE001
        logger.warning({"event": "kich_hoat_nhieu_loi", "thiet_bi": tb, "error": str(exc)[:200]})


# ── Tắt khi đủ sáng — kiểu quản gia ───────────────────────────────────────
# Chủ máy 26/09/2026: "khi mở rèm tăng lux … buổi sáng thì đèn phòng ngủ tắt thế nào" —
# "Lux tôi phải chỉnh được" — "bật tắt như này có máy móc quá không" → chọn KIỂU QUẢN GIA:
# trời sáng không phải lý do để tắt TRƯỚC MẶT người, mà là lý do để không phải chờ:
#   * phòng trống lúc trời sáng → tắt sau ``giay`` giây thay cho số phút của «tắt khi vắng»;
#   * còn người, trời sáng LÊN sau lúc bật (mở rèm) liền ``phut`` phút → HỎI một lần; tự làm
#     chỉ khi thang của `du_doan_nha` đã đủ (không theo cờ «cho tự làm ngay»).
# Cảm biến nằm trong phòng nên ĐÈN cũng làm lux tăng: trời = lux đo − phần đèn góp.
_lux_moi: dict[str, float] = {}
_troi_luc_bat: dict[str, float] = {}
_hen_sang: dict[str, threading.Timer] = {}
_da_hoi_sang: set[str] = set()


def _huy_sang(tb: str) -> None:
    with _khoa:
        cu = _hen_sang.pop(tb, None)
    if cu:
        cu.cancel()


def _troi(tb: str, cb: str, v: float) -> float | None:
    gop = ((_nap()["mo_hinh"].get(tb) or {}).get("den_gop") or {}).get(cb)
    return None if gop is None else v - float(gop)


def _troi_sang(tb: str, cd: dict[str, Any]) -> float | None:
    """Ánh sáng trời lúc này nếu ĐỦ sáng theo ngưỡng chủ máy đặt (thiết bị đang bật), không thì None."""
    tsg = cd.get("tat_khi_sang") or {}
    cb = tsg.get("cam_bien") or ""
    if not tsg.get("bat") or cb not in _lux_moi:
        return None
    troi = _troi(tb, cb, _lux_moi[cb])
    return troi if troi is not None and troi >= float(tsg["lux"]) else None


def _troi_truoc_bat(tb: str, cb: str) -> float | None:
    """Trời lúc thiết bị được bật: lux ngay TRƯỚC lần bật gần nhất (đèn chưa góp). Nhớ
    trong tiến trình; khởi động lại thì tra kho lịch sử."""
    if tb in _troi_luc_bat:
        return _troi_luc_bat[tb]
    from services import lich_su_nha, thoi_quen_nha as tq
    ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    try:
        r = ro.execute("SELECT ts FROM su_kien WHERE thiet_bi=? AND truong='state' AND gia_tri='on'"
                       " ORDER BY ts DESC LIMIT 1", (tb,)).fetchone()
        # Số đo độ sáng nằm ở `su_kien` HOẶC `so_do` (ô 5 phút, từ 11/09) — tra gộp như lúc học.
        ts, gt = tq._tuyen(ro, cb, "state", float(r[0]) - 3600, float(r[0])) if r else ([], [])
    finally:
        ro.close()
    try:
        _troi_luc_bat[tb] = float(tq._truoc(ts, gt, float(r[0])))  # type: ignore[arg-type,index]
    except (TypeError, ValueError, IndexError):
        return None
    return _troi_luc_bat[tb]


def _theo_sang(ma: str, gia_tri: Any, ds: dict[str, dict[str, Any]]) -> None:
    gt = str(gia_tri).lower()
    try:
        so = float(gia_tri)
    except (TypeError, ValueError):
        so = None
    if so is not None:
        _lux_moi[ma] = so
    for tb, cd in ds.items():
        tsg = cd.get("tat_khi_sang") or {}
        if not tsg.get("bat"):
            continue
        cb = tsg["cam_bien"]
        if ma == tb and gt in HANH_DONG:
            _huy_sang(tb)
            if gt == "on":
                _da_hoi_sang.discard(tb)
                if cb in _lux_moi:
                    _troi_luc_bat[tb] = _lux_moi[cb]
            continue
        if ma != cb or so is None:
            continue
        troi = _troi_sang(tb, cd)
        if troi is None:
            _huy_sang(tb)
            continue
        tv = cd.get("tat_khi_vang") or {}
        if tv.get("bat") and _deu_vang(list(tv.get("cam_bien") or [])):
            # Phòng trống mà trời vừa đủ sáng: rút ngắn hẹn «tắt khi vắng».
            han = _han_tat.get(tb)
            if han is None or han > time.time() + float(tsg.get("giay") or SANG_VANG_GIAY):
                _hen_tat_luc(tb, float(tsg.get("giay") or SANG_VANG_GIAY))
            continue
        truoc = _troi_truoc_bat(tb, cb)
        if tb in _da_hoi_sang or tb in _hen_sang or truoc is None or truoc >= float(tsg["lux"]):
            continue                        # đã hỏi / đang chờ / bật lúc trời đã sáng
        t = threading.Timer(float(tsg["phut"]) * 60, _hoi_sang, args=(tb,))
        t.daemon = True
        with _khoa:
            _hen_sang[tb] = t
        t.start()


def _hoi_sang(tb: str) -> None:
    """Trời sáng lên liền N phút mà người còn trong phòng: hỏi một lần (đủ thang thì tự làm)."""
    from services import du_doan_nha as dd, ha_client, thong_bao

    with _khoa:
        _hen_sang.pop(tb, None)
    try:
        cd = ds_thiet_bi().get(tb) or {}
        troi = _troi_sang(tb, cd)
        if troi is None or tb in _da_hoi_sang:
            return
        if str((ha_client.get_state(tb) or {}).get("state") or "").lower() != "on":
            return
        luc = time.time()
        if any(x.get("hanh_dong") == "off" and x.get("cach", "khong") == "khong" and _khung_dang(x, luc)
               for x in cd.get("ngoai_le") or []):
            return
        if _nguoi_vua_cham(tb, luc) or _vua_lam(tb, "off") or _dang_cho(tb):
            t = threading.Timer(HEN_LAI, _hoi_sang, args=(tb,))
            t.daemon = True
            with _khoa:
                _hen_sang[tb] = t
            t.start()
            return
        _da_hoi_sang.add(tb)
        ten, lux = _ten_tt(tb, "off"), cd["tat_khi_sang"]["lux"]
        nhan = {"nguon": f"trời sáng {troi:.0f} lux", "troi": round(troi, 1), BEN_VUNG: 1}
        if dd.cap(ten) >= 2:
            if not _lam(tb, "off", tu_lam=True):
                return
            id_ = dd.ghi_nhan(ten, "off", 1.0, nhan, "tu_lam")
            _bao_tu_lam(tb,
                        f"🤖 #{id_} Trời sáng rồi (~{troi:.0f} lux, ngưỡng anh đặt {lux:g}) nên em đã tắt "
                        f"{_ten_tb(tb)}.\nĐúng hay sai ạ? Anh trả lời «đúng» hoặc «sai» — sai thì em bật lại "
                        f"ngay và nâng ngưỡng. Không trả lời trong {CHAM_TU_LAM // 60} phút là em tính đúng.")
            return
        id_ = dd.ghi_nhan(ten, "off", 1.0, nhan, "hoi")
        if not thong_bao.gui("nha.goi_y",
                             f"💡 #{id_} Trời sáng rồi (~{troi:.0f} lux, ngưỡng anh đặt {lux:g}). Em tắt "
                             f"{_ten_tb(tb)} nhé? — anh trả lời «có» hoặc «không»."):
            dd.xoa(id_)
    except Exception as exc:  # noqa: BLE001
        logger.warning({"event": "kich_hoat_hoi_sang_loi", "thiet_bi": tb, "error": str(exc)[:200]})


def su_kien(ma: str, gia_tri: Any, *, do_ai: bool = False) -> None:
    """Gọi từ `ha_live` với MỌI thay đổi trạng thái. Không bao giờ raise, không chặn."""
    global _cham_luc, _da_khoi_phuc, _gop_luc
    try:
        if time.time() - _gop_luc > GOP_GIAY:
            _gop_luc = time.time()
            _gop_guong()
        ds = ds_thiet_bi()
        if not ds:
            return
        if not _da_khoi_phuc:
            _da_khoi_phuc = True
            threading.Thread(target=_khoi_phuc, args=(ds,), name="kich-hoat-khoi-phuc", daemon=True).start()
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
        _theo_sang(ma, gia_tri, ds)
        _theo_o_lai(ma, gt, ds)
        _theo_nhieu(ma, gt, ds)
        if do_ai:
            return
        if ma in ds and gt in HANH_DONG:
            threading.Thread(target=_nguoi_lam, args=(ma, gt, luc), daemon=True).start()
        for nguon in _nguon_cua(ma, gt, luc):
            _phat(nguon, luc)
    except Exception as exc:  # noqa: BLE001
        logger.warning({"event": "kich_hoat_su_kien_loi", "error": str(exc)[:160]})


# ── Trả lời trong Zalo ─────────────────────────────────────────────────────
#: Trả lời cho việc bot ĐÃ TỰ LÀM: chỉ đúng hai chữ này. Tập «có/không» rộng hơn (ok, ko…)
#: thì một câu "không" nhắn cho việc khác trong 10 phút sẽ tắt nhầm đèn.
_DUNG = {"đúng", "đúng rồi", "đúng rồi em", "chuẩn"}
_SAI = {"sai", "sai rồi", "sai rồi em"}
_NGUOC = {"on": "off", "off": "on"}

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
    if cau not in _CO | _KHONG | _DUNG | _SAI:
        return None
    with dd._khoa:
        r = dd._db().execute(
            "SELECT id, ten, hanh_dong, cach, boi_canh FROM du_doan WHERE ket_qua='cho' AND ten LIKE '%#%'"
            " AND ((cach='hoi' AND ts>?) OR (cach='tu_lam' AND ts>?))"
            + (" AND id=?" if so else "") + " ORDER BY ts DESC LIMIT 1",
            (time.time() - HAN_HOI, time.time() - CHAM_TU_LAM, *([int(so)] if so else []))).fetchone()
    if not r:
        return None
    tb, hd = str(r["ten"]).rsplit("#", 1)
    if r["cach"] == "tu_lam":
        if cau not in _DUNG | _SAI:
            return None
        if cau in _DUNG:
            dd.ghi_dung(int(r["id"]))
            # «Đúng» chỉ chấm lần bật vừa rồi, không phải «giữ đèn sáng». Chủ máy 27/09/2026: "trả
            # lời đúng theo câu hỏi thì nó lại giữ sáng" — nói rõ luật tắt vẫn chạy như thường.
            tv = (ds_thiet_bi().get(tb) or {}).get("tat_khi_vang") or {}
            con = (f" Phòng trống {round(phut_vang(ds_thiet_bi().get(tb) or {}, time.time())):g} phút "
                   "em vẫn tự tắt như thường." if hd == "on" and tv.get("bat") else "")
            return f"Dạ, em ghi là đúng: {_TEN_HD[hd].lower()} {_ten_tb(tb)}.{con}"
        dd.ghi_sai(int(r["id"]))
        nang = _nang_nguong_sang(tb, r["boi_canh"])
        noi = _noi_vang(tb, r["boi_canh"], time.time()) if hd == "off" else None
        if not _lam(tb, _NGUOC[hd], tu_lam=False):
            return (f"Em ghi là em sai, nhưng chưa {_TEN_HD[_NGUOC[hd]].lower()} lại được "
                    f"{_ten_tb(tb)} — Home Assistant không nhận lệnh.")
        return (f"Dạ, em đã {_TEN_HD[_NGUOC[hd]].lower()} lại {_ten_tb(tb)} và ghi là em sai."
                + (f" Em nâng ngưỡng «tắt khi đủ sáng» lên {nang:g} lux." if nang else "")
                + (f" Quanh {noi[0]}h em chờ vắng {noi[1]:g} phút mới tắt (lâu không sai em rút dần lại)."
                   if noi else ""))
    if cau in _KHONG | _SAI:
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
    _gop_guong()
    d = _nap()
    ten_ha = _ten_ha()
    hien_dien = _lop(_LOP_HIEN_DIEN)
    cua = sorted(_lop(_LOP_CUA))
    ra = []
    for tb, cd in sorted(d["thiet_bi"].items()):
        mh = d["mo_hinh"].get(tb) or {}
        ka = _kiem_ao_cua(tb)
        tv = cd.get("tat_khi_vang") or {}
        tsg = cd.get("tat_khi_sang") or {}
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
                   "luat_chu": cd.get("luat_chu") or [], "hay_bat": mh.get("hay_bat") or {},
                   "im_lang": bool(cd.get("im_lang")),
                   "hoi_de_hoc": bool(cd.get("hoi_de_hoc")),
                   "muc": mh.get("muc") or None, "nhieu": mh.get("nhieu") or None,
                   "o_lai": ({"phut": mh["o_lai"].get("phut"), "lan": mh["o_lai"].get("lan", 0),
                              "cam_bien": [{"ma": m, "ten": ten_ha.get(m, m)} for m in mh["o_lai"].get("cam_bien") or []]}
                             if mh.get("o_lai") else None),
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
                       "bat": bool(tv.get("bat")), "phut": int(tv.get("phut") or MAC_DINH_VANG_PHUT),
                       # Ngoại vi bot chọn: báo "có thể còn người" thì bot nhìn lại bằng camera.
                       "giu": ({"ma": tv["giu"], "ten": ten_ha.get(tv["giu"], tv["giu"])} if tv.get("giu") else None),
                       "nhin": list(tv.get("nhin") or []),
                       # Giờ đang được tự nới (tắt nhầm rồi người bật lại) — số phút chờ hiện dùng.
                       # Giờ bot đang chờ lâu hơn số chủ máy đặt (học từ thời gian mất dấu, hoặc
                       # vừa nới vì tắt nhầm) — và số đo của lượt học.
                       "tu_noi": [{"gio": h, "phut": round(p)} for h in range(24)
                                  if (p := max(float((cd.get("cho_vang") or {}).get(str(h)) or 0),
                                               float(((cd.get("noi_vang") or {}).get(str(h)) or {}).get("phut") or 0)))
                                  > float(tv.get("phut") or MAC_DINH_VANG_PHUT)],
                       "tu_hoc": mh.get("cho_vang") or {},
                       "cam_bien": [{"ma": m, "ten": ten_ha.get(m, m)} for m in tv.get("cam_bien") or []],
                       # Gợi ý: cảm biến hiện diện trong sơ đồ của thiết bị.
                       "goi_y": [{"ma": m, "ten": ten_ha.get(m, m)} for m in sorted(nhi_phan & hien_dien)],
                       "quay_lai_moi_ngay": {ten_ha.get(m, m): v for m, v in (mh.get("vang_quay_lai") or {}).items()
                                             if m in (tv.get("cam_bien") or []) or m in hien_dien},
                   },
                   "tat_khi_sang": {
                       "bat": bool(tsg.get("bat")), "lux": tsg.get("lux"), "phut": int(tsg.get("phut") or 2),
                       "giay": int(tsg.get("giay") or SANG_VANG_GIAY),
                       "cam_bien": ({"ma": tsg["cam_bien"], "ten": ten_ha.get(tsg["cam_bien"], tsg["cam_bien"])}
                                    if tsg.get("cam_bien") else None),
                       # Cảm biến độ sáng đã đo được phần thiết bị này góp vào; gợi ý lux = ngưỡng
                       # luật BẬT đang dùng cho cảm biến đó (dưới ngưỡng ấy mới bật).
                       "goi_y": [{"ma": m, "ten": ten_ha.get(m, m), "den_gop": g,
                                  "lux": _nguong_cay((mh.get("on") or {}).get("cay") or {}, m)}
                                 for m, g in (mh.get("den_gop") or {}).items()],
                       "lux_bay_gio": _lux_moi.get(tsg.get("cam_bien") or ""),
                   },
                   "co_so": mh.get("co_so") or "tu_do",
                   "goi_y_them": [{**x, "ten": ten_ha.get(x["ma"], x["ma"])} for x in mh.get("goi_y_them") or []],
                   "nguong": {"so_luot": dd._MAU_LEN_CAP, "ty_le": dd._TY_LE_LEN_CAP}})
    return ra


#: Chủ máy nói «sai» với một lần tắt vì trời sáng: ngưỡng mới = trời lúc đó × hệ số này.
NANG_SANG = 1.2


def _nang_nguong_sang(tb: str, boi_canh: Any) -> float | None:
    """Sai một lần thì tự tránh (chủ máy: "cái này học thêm"): trời lúc bot tắt chưa đủ với
    anh → ngưỡng lên trên mức đó. Chỉ NÂNG, không bao giờ hạ — hạ là việc của chủ máy."""
    try:
        troi = float(json.loads(boi_canh or "{}").get("troi"))
    except (TypeError, ValueError, AttributeError):
        return None
    with _khoa:
        tsg = ((_nap()["thiet_bi"].get(tb) or {}).get("tat_khi_sang")) or {}
        moi = float(math.ceil(troi * NANG_SANG))
        if not tsg or moi <= float(tsg.get("lux") or 0):
            return None
        tsg["lux"] = moi
        _luu()
    return moi


def _nguong_cay(nut: dict[str, Any], key: str) -> float | None:
    """Ngưỡng nông nhất cây chia theo ``key`` (duyệt theo tầng), không có thì None."""
    tang = [nut]
    while tang:
        for n in tang:
            if n.get("key") == key:
                return round(float(n["nguong"]), 1)
        tang = [c for n in tang if "key" in n for c in (n["trai"], n["phai"])]
    return None


def _reset_for_tests(duong: Path) -> None:
    global _PATH, _du_lieu, _cham_luc, _da_khoi_phuc, _gop_luc
    _PATH = duong
    _du_lieu = None
    _cham_luc = 0.0
    _gop_luc = 0.0
    _da_khoi_phuc = True
    _lan_off.clear()
    for t in [*_hen_vang.values(), *_hen_tat.values(), *_hen_sang.values(), *_hen_o_lai.values()]:
        t.cancel()
    _hen_o_lai.clear()
    _ly_do_tat.clear()
    _o_lai_xet_luc.clear()
    _o_lai_da_phat.clear()
    _hen_vang.clear()
    _hen_tat.clear()
    _hen_sang.clear()
    _lux_moi.clear()
    _troi_luc_bat.clear()
    _da_hoi_sang.clear()
    _han_tat.clear()
