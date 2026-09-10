"""Học nếp sinh hoạt từ nhật ký, rồi cảnh báo lệch nếp và đón đầu việc quen làm.

Hai việc chủ máy nêu 09/09/2026:

1. *"con trai đi học ngày này về mấy giờ của từng ngày, nhưng hôm nay về muộn
   hơn nên cảnh báo"*
2. *"mùa đông, căn cứ thói quen sinh hoạt, giờ về mà bật bình nóng lạnh"*

Cả hai đều là: học GIỜ QUEN của một việc lặp, rồi so hôm nay với nếp đó.

DÙNG TRUNG VỊ, KHÔNG DÙNG TRUNG BÌNH. Chủ máy chỉ ra 09/09/2026: *"55 phút
quá lâu, nhất là con đi học, chỉ trong 10 phút thôi… ngoài đi học còn đi chơi
rất dễ nhiễu"*. Đúng: ±55 phút đo được là do TRỘN ngày về thẳng với ngày đi
chơi. Vài lần về muộn 3 tiếng kéo trung bình lệch hẳn, và độ lệch phình ra tới
mức không còn báo được gì.

Trung vị + MAD miễn nhiễm với chuyện đó. Đo trên 15 lần về đúng nếp (16h30
±10 phút) trộn 4 lần đi chơi (18–20h):

    trung bình + σ  → 16h55 ± 60 phút   (nếp bị kéo lệch 25 phút)
    trung vị  + MAD → 16h31 ± 18 phút   (đúng nếp thật)

Với trung vị, ngưỡng 1.5σ là hợp nhất:

    ngưỡng   báo nhầm   bắt muộn 30 phút   bắt muộn 60 phút
    1.0σ       6.8%          98%                100%
    1.5σ       1.8%          86%                100%      ← chọn
    2.0σ       0.5%          49%                100%

SÀN 10 PHÚT, theo đúng con số chủ máy nêu cho việc đi học.

CẦN BAO NHIÊU DỮ LIỆU. Ít mẫu thì độ lệch tính ra vô nghĩa — hai lần về đúng
giờ nhau cho σ=0, rồi lần thứ ba lệch 10 phút là báo động. Nên đòi tối thiểu
``_TOI_THIEU_MAU`` lần cho mỗi ô (người × thứ × buổi), và cộng thêm sàn
``_SAN_LECH_PHUT`` vào độ lệch để nếp quá đều không sinh báo động giả.

CHỈ ĐỌC TỪ ``lich_su_nha``, không tự gọi API thiết bị. Nhật ký khoá cửa Tuya
chỉ trả 100 bản ghi gần nhất bất kể xin bao nhiêu ngày — đo thật: xin 30 ngày
chỉ được 7 ngày dữ liệu. Nên nguồn học phải là bảng ``su_kien`` của c2a, thứ
tích luỹ mãi mãi.
"""

from __future__ import annotations

import logging
import statistics
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from services.config import config

logger = logging.getLogger(__name__)

_TZ = timezone(timedelta(hours=7))

#: Ít hơn ngần này lần thì chưa đủ để nói "đây là nếp".
_TOI_THIEU_MAU = 4
#: Sàn độ lệch. 10 phút — chủ máy nêu đúng con số này cho việc con đi học.
#: Không có sàn thì nếp quá đều (σ≈0) khiến lệch 1 phút cũng thành báo động.
_SAN_LECH_PHUT = 10.0
#: Lệch quá ngần này lần MAD thì coi là bất thường (xem bảng trên).
_NGUONG_SIGMA = 1.5
#: Buổi trong ngày. Gộp cả ngày thì sáng lẫn chiều trộn vào nhau, độ lệch vô
#: nghĩa — đo thật: gộp cho ±297 phút, tách buổi còn ±35–60 phút.
_BUOI = ((5, 11, "sáng"), (11, 14, "trưa"), (14, 19, "chiều"), (19, 29, "tối"))

_THU = ("thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật")


def _cfg() -> dict[str, Any]:
    raw = (config.data.get("mqtt") or {}).get("thoi_quen")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("bat", True))


def _nguong_sigma() -> float:
    try:
        return max(1.0, min(float(_cfg().get("nguong_sigma") or _NGUONG_SIGMA), 4.0))
    except (TypeError, ValueError):
        return _NGUONG_SIGMA


def _toi_thieu_mau() -> int:
    try:
        return max(2, int(_cfg().get("toi_thieu_mau") or _TOI_THIEU_MAU))
    except (TypeError, ValueError):
        return _TOI_THIEU_MAU


def _ten_buoi(gio: int) -> str:
    for a, b, ten in _BUOI:
        if a <= gio < b:
            return ten
    return "đêm"


def _mad(xs: list[float]) -> float:
    """Độ lệch tuyệt đối trung vị, quy về thang σ (nhân 1.4826).

    Dùng thay độ lệch chuẩn vì σ bị vài giá trị lạc kéo phình: 4 ngày đi chơi
    về muộn làm σ nhảy từ 10 lên 60 phút, và từ đó không báo được ca muộn thật.
    """
    if len(xs) < 2:
        return 0.0
    m = statistics.median(xs)
    return statistics.median([abs(x - m) for x in xs]) * 1.4826


def _gio_thap_phan(t: datetime) -> float:
    """Giờ dạng thập phân, ĐÊM TÍNH TIẾP 24 (0h30 → 24.5).

    Không làm vậy thì về lúc 23h50 và 0h10 bị coi là cách nhau 23 tiếng rưỡi,
    trung bình rơi vào giữa trưa — vô nghĩa.
    """
    g = t.hour + t.minute / 60
    return g + 24 if g < 5 else g


# ── Học nếp ─────────────────────────────────────────────────────────────────
def hoc(thiet_bi: str, truong: str = "", *, so_ngay: int = 60) -> dict[str, Any]:
    """Dựng nếp giờ cho từng (giá trị × thứ × buổi) từ bảng ``su_kien``.

    ``giá trị`` là thứ phân biệt người: với khoá cửa Tuya đó là số vân tay hay
    khuôn mặt. Trả ``{khoá_ô: {n, trung_binh, do_lech, mau}}``.
    """
    from services import lich_su_nha

    den = time.time()
    tu = den - max(1, int(so_ngay)) * 86400
    try:
        sk = lich_su_nha.doc_su_kien(thiet_bi, tu, den, truong or None)
    except Exception as exc:
        logger.warning({"event": "thoi_quen_doc_loi", "error": str(exc)[:160]})
        return {}

    gom: dict[str, list[float]] = {}
    for r in sk:
        try:
            t = datetime.fromtimestamp(float(r["ts"]), _TZ)
        except (TypeError, ValueError, KeyError):
            continue
        khoa = f"{r.get('gia_tri')}|{t.weekday()}|{_ten_buoi(t.hour)}"
        gom.setdefault(khoa, []).append(_gio_thap_phan(t))

    nep: dict[str, Any] = {}
    for khoa, gio in gom.items():
        if len(gio) < _toi_thieu_mau():
            continue
        nep[khoa] = {
            "n": len(gio),
            # TRUNG VỊ, không phải trung bình: vài ngày đi chơi về muộn không
            # được phép kéo lệch nếp của những ngày về đúng giờ.
            "trung_binh": round(statistics.median(gio), 3),
            "do_lech": round(max(_mad(gio), _SAN_LECH_PHUT / 60), 3),
            "mau": sorted(round(g, 2) for g in gio)[-8:],
        }
    return nep


def _doc_khoa(khoa: str) -> tuple[str, int, str]:
    gt, _, con = khoa.partition("|")
    thu, _, buoi = con.partition("|")
    try:
        return gt, int(thu), buoi
    except ValueError:
        return gt, 0, buoi


def mo_ta_nep(thiet_bi: str, truong: str = "", *, so_ngay: int = 60) -> list[dict[str, Any]]:
    """Nếp đã học, dạng đọc được — cho web và cho bot thuật lại."""
    ra = []
    for khoa, v in hoc(thiet_bi, truong, so_ngay=so_ngay).items():
        gt, thu, buoi = _doc_khoa(khoa)
        tb = float(v["trung_binh"]) % 24
        ra.append({
            "ai": gt, "thu": _THU[thu % 7], "buoi": buoi, "so_lan": v["n"],
            "gio_quen": f"{int(tb)}h{int(tb % 1 * 60):02d}",
            "lech_phut": round(float(v["do_lech"]) * 60),
        })
    ra.sort(key=lambda x: (-x["so_lan"], x["ai"]))
    return ra


# ── So hôm nay với nếp ──────────────────────────────────────────────────────
def soi_lech(thiet_bi: str, truong: str = "", *, so_ngay: int = 60) -> list[dict[str, Any]]:
    """Hôm nay có ai lệch nếp không? Trả danh sách điều đáng nói.

    Hai kiểu lệch:

    * ``muon`` — đã xảy ra nhưng muộn hơn nếp quá ngưỡng.
    * ``chua_ve`` — tới giờ quen rồi mà chưa thấy, và đã quá ngưỡng.

    Kiểu thứ hai mới là thứ chủ máy cần: biết con CHƯA về, chứ không phải đợi
    con về rồi mới báo là muộn.
    """
    from services import lich_su_nha

    nep = hoc(thiet_bi, truong, so_ngay=so_ngay)
    if not nep:
        return []

    now = datetime.now(_TZ)
    dau_ngay = now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        hom_nay = lich_su_nha.doc_su_kien(
            thiet_bi, dau_ngay.timestamp(), now.timestamp(), truong or None)
    except Exception:
        hom_nay = []

    da_xay: dict[str, float] = {}
    for r in hom_nay:
        try:
            t = datetime.fromtimestamp(float(r["ts"]), _TZ)
        except (TypeError, ValueError, KeyError):
            continue
        khoa = f"{r.get('gia_tri')}|{t.weekday()}|{_ten_buoi(t.hour)}"
        da_xay.setdefault(khoa, _gio_thap_phan(t))

    gio_bay_gio = _gio_thap_phan(now)
    ng = _nguong_sigma()
    ra = []
    for khoa, v in nep.items():
        gt, thu, buoi = _doc_khoa(khoa)
        if thu != now.weekday():
            continue                      # nếp của thứ khác, hôm nay không xét
        tb = float(v["trung_binh"])
        sd = float(v["do_lech"])
        han = tb + ng * sd

        if khoa in da_xay:
            lech = da_xay[khoa] - tb
            if lech > ng * sd:
                ra.append({
                    "loai": "muon", "ai": gt, "buoi": buoi,
                    "gio_quen": tb % 24, "gio_thuc": da_xay[khoa] % 24,
                    "muon_phut": round(lech * 60), "so_lan_hoc": v["n"],
                })
            continue

        # Chưa xảy ra: chỉ báo khi đã QUA hạn, và buổi đó đã bắt đầu.
        if gio_bay_gio > han and gio_bay_gio - tb < 6:
            ra.append({
                "loai": "chua_ve", "ai": gt, "buoi": buoi,
                "gio_quen": tb % 24, "gio_thuc": None,
                "muon_phut": round((gio_bay_gio - tb) * 60), "so_lan_hoc": v["n"],
            })

    ra.sort(key=lambda x: -x["muon_phut"])
    return ra


def _ten_nguoi(ma: str) -> str:
    """Đổi mã kỹ thuật thành tên người, nếu chủ nhà đã dạy bot.

    Khoá cửa chỉ báo "vân tay số 11". Chủ máy nói lại "11 là con trai" thì
    ``state.nho_hoac_cap_nhat`` giữ câu đó, và từ đó báo cáo gọi đúng tên.

    CÓ ĐƯỜNG TỐT HƠN: Tuya cho đặt tên ngay trên khoá — API
    ``/v1.0/devices/<id>/door-lock/open-logs`` trả sẵn ``unlock_name`` và
    ``user_id``. Đo 09/09/2026 trên khoá nhà: hai trường đó RỖNG vì chủ máy
    chưa đặt tên trong app Smart Life. Đặt tên ở đó thì khỏi phải dạy bot, và
    mọi nơi khác (app, HA) cũng hiện đúng tên.
    """
    # Uỷ cho SỔ DÙNG CHUNG. Bản cũ tự tra trí nhớ theo cách riêng nên KHÔNG
    # thấy tên chủ máy đã dạy qua khoá cửa — dạy "vân tay 11 là con trai" xong
    # mà báo cáo thói quen vẫn gọi "vân tay số 11". Đó là lỗi thật.
    try:
        from services import so_ten_nha
        loai, _, so = str(ma).partition("#")
        for nguon in ("tuya", "frigate", "mqtt", "ha"):
            t = so_ten_nha.ten_cua(nguon, loai or "unlock", so or ma)
            if t:
                return t
    except Exception:
        pass
    return ma


def mo_ta_lech(ds: list[dict[str, Any]]) -> str:
    """Soạn lời cảnh báo cho người đọc."""
    if not ds:
        return ""
    dong = []
    for d in ds:
        ai = _ten_nguoi(str(d["ai"]))
        qn = d["gio_quen"]
        quen = f"{int(qn)}h{int(qn % 1 * 60):02d}"
        if d["loai"] == "chua_ve":
            cau = (f"⏰ {ai} thường về buổi {d['buoi']} khoảng {quen} "
                   f"(học từ {d['so_lan_hoc']} lần), giờ đã muộn "
                   f"{d['muon_phut']} phút mà chưa thấy.")
            if d.get("bang_chung"):
                # Nguồn khác bác lại → nói rõ để người đọc tự quyết, đừng
                # khẳng định "chưa về" khi camera đang thấy người.
                cau += (" (Nhưng " + ", ".join(d["bang_chung"][:3])
                        + " — có thể đã về mà khoá không ghi nhận.)")
            dong.append(cau)
        else:
            gt = d["gio_thuc"]
            dong.append(f"🕐 {ai} về lúc {int(gt)}h{int(gt % 1 * 60):02d}, "
                        f"muộn hơn nếp thường ({quen}) {d['muon_phut']} phút.")
    return "\n".join(dong)


# ── Đón đầu việc quen làm ───────────────────────────────────────────────────
def sap_den_gio(thiet_bi: str, truong: str = "", *, truoc_phut: int = 30,
                so_ngay: int = 60) -> list[dict[str, Any]]:
    """Việc gì SẮP tới giờ quen, trong ``truoc_phut`` tới.

    KHÔNG bó hẹp vào "ai sắp về". Chủ máy nhắc 09/09/2026: *"tôi cần bot quản
    lý, quản gia không bó hẹp"*. Hàm này trả lời cho MỌI việc lặp mà lịch sử
    có ghi — giờ về, giờ ngủ, giờ bật điều hoà, giờ nấu ăn, giờ tưới cây —
    vì nó chỉ đọc bảng ``su_kien``, không quan tâm việc đó là gì.

    Ví dụ chủ máy nêu: biết trước 30 phút thì bình nóng lạnh kịp nóng. Hàm
    CHỈ nói "việc này sắp tới giờ" — quyết định có làm gì không là của tầng
    trên, vì còn phụ thuộc mùa, nhiệt độ, và mức tự chủ người dùng cho phép.
    """
    nep = hoc(thiet_bi, truong, so_ngay=so_ngay)
    now = datetime.now(_TZ)
    bay_gio = _gio_thap_phan(now)
    ra = []
    for khoa, v in nep.items():
        gt, thu, buoi = _doc_khoa(khoa)
        if thu != now.weekday():
            continue
        con = (float(v["trung_binh"]) - bay_gio) * 60
        if 0 < con <= truoc_phut:
            ra.append({"ai": gt, "viec": f"{thiet_bi}/{truong}" if truong else thiet_bi,
                       "buoi": buoi, "con_phut": round(con),
                       "gio_quen": float(v["trung_binh"]) % 24,
                       "lech_phut": round(float(v["do_lech"]) * 60),
                       "so_lan_hoc": v["n"]})
    ra.sort(key=lambda x: x["con_phut"])
    return ra


# ── Xác nhận trước khi báo ──────────────────────────────────────────────────
def doi_chung(khi_nao: float, *, cua_so_phut: int = 20) -> list[str]:
    """Nguồn khác có thấy gì quanh mốc ``khi_nao`` không?

    Chủ máy nêu 09/09/2026: *"đi chơi rất dễ nhiễu, có thể xác nhận thêm qua
    cam, qua tôi"*. Một mình nhật ký khoá cửa không phân biệt được "chưa về"
    với "về bằng cửa khác" hay "khoá hết pin". Trước khi báo động, soi xem
    camera và cảm biến quanh nhà có nói gì khác không.

    Trả danh sách bằng chứng đọc được. RỖNG nghĩa là không nguồn nào thấy gì —
    lúc đó cảnh báo mới đáng tin.
    """
    from services import lich_su_nha

    ra: list[str] = []
    tu, den = khi_nao - cua_so_phut * 60, khi_nao + cua_so_phut * 60
    try:
        tuoi = lich_su_nha.doc_tuoi()
    except Exception:
        return ra

    for r in tuoi:
        tb, tr = str(r.get("thiet_bi") or ""), str(r.get("truong") or "")
        ts = float(r.get("ts") or 0)
        if not (tu <= ts <= den):
            continue
        gt = str(r.get("gia_tri") or "").lower()
        # Camera đếm người, hoặc cảm biến hiện diện báo có — cả hai đều là
        # bằng chứng "có người trong nhà" độc lập với khoá cửa.
        if ("person" in tr or "occupancy" in tr or "presence" in tr) and gt not in ("0", "off", "false", ""):
            ra.append(f"{tb} thấy người")
        elif "motion" in tr and gt in ("on", "true", "1"):
            ra.append(f"{tb} có chuyển động")
    return sorted(set(ra))


def dang_tin(ds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lọc bớt cảnh báo mà nguồn khác đã bác.

    "Chưa về" mà camera trong nhà đang thấy người thì hoặc đã về bằng đường
    khác, hoặc khoá không ghi nhận — báo động lúc đó là sai. Giữ lại cảnh báo,
    nhưng hạ mức và kèm bằng chứng để người đọc tự quyết.
    """
    ra = []
    for d in ds:
        if d.get("loai") != "chua_ve":
            ra.append(d)
            continue
        bc = doi_chung(time.time())
        if bc:
            d = {**d, "nghi_ngo": True, "bang_chung": bc}
        ra.append(d)
    return ra


def thong_ke(thiet_bi: str = "", truong: str = "") -> dict[str, Any]:
    """Cho web + health."""
    if not thiet_bi:
        return {"bat": is_enabled(), "nguong_sigma": _nguong_sigma(),
                "toi_thieu_mau": _toi_thieu_mau()}
    nep = hoc(thiet_bi, truong)
    return {
        "bat": is_enabled(),
        "so_o_da_hoc": len(nep),
        "nguong_sigma": _nguong_sigma(),
        "toi_thieu_mau": _toi_thieu_mau(),
        "nep": mo_ta_nep(thiet_bi, truong)[:20],
    }


#: Tên cũ, giữ lại cho code đã gọi. Dùng ``sap_den_gio`` cho việc mới.
sap_ve = sap_den_gio
