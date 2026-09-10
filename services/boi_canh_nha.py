"""Lúc ấy trong nhà thế nào — bối cảnh của MỘT mốc thời gian.

Vì sao có file này: chủ máy nêu 10/09/2026 bằng bốn sơ đồ — đèn và rèm học
theo LUX, quạt và bình nóng lạnh học theo NHIỆT ĐỘ, thời gian về nhà học theo
VỊ TRÍ NGƯỜI, và tất cả đều học theo GIỜ, HIỆN DIỆN, MÙA. *"Khi học tập thói
quen cần phải xem các điều kiện lúc đó như nào mà được sử dụng, xảy ra."*

Tầng học cũ (`thoi_quen_nha`, `tinh_huong_nha`) chỉ biết GIỜ và THỨ. Biết
"19h30 hay bật đèn bếp" thì không phân biệt được hôm trời mưa sập tối từ 17h
với hôm nắng hè còn sáng tới 19h. File này trả lời phần còn thiếu.

TRẢ VỀ CÁI BIẾT, NÓI RÕ CÁI KHÔNG BIẾT. Mỗi giá trị kèm độ tin, và cái nào
không có thì VẮNG MẶT khỏi kết quả chứ không mang giá trị mặc định. Tầng xác
suất phải phân biệt được "trời tối" với "không biết trời sáng hay tối" — trộn
hai cái đó lại là học nhầm, và học nhầm kiểu này không báo lỗi bao giờ.

KHÔNG DÙNG BẢNG ``tuoi`` CHO MỐC QUÁ KHỨ. ``tuoi`` giữ giá trị MỚI NHẤT; đem
nó trả lời "8 giờ trước lux bao nhiêu" là rò rỉ tương lai. Mô hình học từ đó
sẽ thấy "lux lúc bật đèn = lux bây giờ" đúng gần 100% trên dữ liệu cũ rồi vô
dụng ngoài đời. Đây là bẫy dễ mắc nhất ở tầng này nên chặn ngay trong code.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from services.config import config

logger = logging.getLogger(__name__)

_TZ = timezone(timedelta(hours=7))

#: Số đo cũ hơn ngần này thì thôi, coi như không biết. Lux và nhiệt độ đổi
#: chậm nên 30 phút vẫn nói lên chuyện; xa hơn là đoán mò.
_HAN_SO_DO_PHUT = 30.0

#: ``tuoi`` chỉ được dùng khi hỏi về HIỆN TẠI. Xem lời dặn ở đầu tệp.
_HAN_TUOI_GIAY = 300.0

#: Dấu hiệu "có người" còn hiệu lực bao lâu sau bản ghi cuối.
_HAN_NGUOI_GIAY = 900.0

#: Ngưỡng rời rạc hoá tính theo PHÂN VỊ của chính nhà này, không đặt cứng.
_PHAN_VI_DUOI, _PHAN_VI_TREN = 33, 66

#: Cache ngưỡng phân vị — tính lại mỗi giờ là đủ, nếp nhà không đổi trong ngày.
_HAN_CACHE_GIAY = 3600.0
_cache_nguong: dict[str, Any] = {}
_cache_luc = 0.0
_cache_phong: dict[str, str] = {}
_cache_ten_phong: dict[str, str] = {}
_cache_phong_luc = 0.0

#: Buổi trong ngày — trùng cách chia của `thoi_quen_nha` để hai tầng nói cùng
#: một thứ tiếng. Đổi ở đây mà không đổi bên kia là hai tầng học lệch nhau.
_BUOI = ((5, 11, "sáng"), (11, 14, "trưa"), (14, 19, "chiều"), (19, 29, "tối"))

#: Trường nói lên CÓ NGƯỜI. Đây là danh sách tên, và là ngoại lệ có lý do:
#: "trường này nói về sự hiện diện của người" là ngữ nghĩa, không đo được từ
#: nhịp đổi — một cảm biến hiện diện và một công tắc đèn đổi giống hệt nhau.
_TRUONG_NGUOI = ("occupancy", "presence", "motion", "person")

#: Giá trị coi như KHÔNG/TẮT. Dùng chung cho mọi nơi phải hiểu "đang bật".
_LA_TAT = frozenset({"off", "0", "false", "", "none", "unavailable",
                     "unknown", "closed", "not_home", "away"})


def _cfg() -> dict[str, Any]:
    raw = (config.data.get("mqtt") or {}).get("boi_canh")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("bat", True))


def ten_buoi(gio: int) -> str:
    for a, b, ten in _BUOI:
        if a <= gio < b:
            return ten
    return "đêm"


def mua(thang: int) -> str:
    """Mùa theo tháng, miền Bắc Việt Nam.

    Đây là XẤP XỈ RẺ TIỀN cho "trời đang lạnh hay nóng", dùng khi chưa có
    nhiệt độ đo được. Có nhiệt độ thật thì nhiệt độ tốt hơn hẳn — mùa chỉ nói
    được cái chung của cả tháng, còn cái quyết định việc bật bình nóng lạnh là
    trời hôm nay lạnh hay không.

    Sau khoảng một năm dữ liệu, tầng xác suất tự học được ngưỡng nhiệt độ thật
    của nhà này và mùa lùi về thành một điều kiện phụ.
    """
    if thang in (12, 1, 2, 3) or thang == 11:
        return "lanh"
    if thang in (4, 10):
        return "chuyen"
    return "nong"


def _co_mat(gia_tri: Any) -> bool:
    """Giá trị này có nghĩa CÓ NGƯỜI không.

    Tách hẳn khỏi "thiết bị có đang bật" (`du_doan_nha._la_bat`), dù hai câu
    hỏi nhìn giống nhau. Cảm biến người ở nhà này ĐẾM SỐ NGƯỜI:
    `sensor.bep_person_count` = "2" nghĩa là có hai người, nên một con số khác
    0 ở đây là CÓ. Còn `sensor.entities` = "1080" chỉ là đếm số thực thể
    trong Home Assistant, không phải ai vừa bật cái gì.

    Dùng chung MỘT hàm cho cả hai câu hỏi chính là lỗi đã khiến bot mời chủ
    máy "bật" `sensor.entities` và `binary_sensor.ariston_is_heating`
    (11/09/2026). Hai câu hỏi khác nhau thì phải là hai hàm khác tên.
    """
    return str(gia_tri or "").strip().lower() not in _LA_TAT


def _khong_dau(s: str) -> str:
    """Bỏ dấu tiếng Việt VÀ chuẩn hoá dấu phân tách, để so tên phòng.

    Mỗi nguồn viết tên phòng một kiểu: HA ghi "Ban công", Frigate ghi
    `frigate/ban-cong`, Zigbee2MQTT ghi `zigbee2mqtt/Hiện diện ban công`. Quy
    hết về "ban cong" thì cả ba khớp cùng một phòng. Không chuẩn hoá thì
    `frigate/ban-cong` trượt trong khi `frigate/bep` khớp — đo thật, và lỗi
    kiểu đó không báo gì cả, chỉ làm bot mất một phòng.
    """
    import unicodedata
    t = "".join(c for c in unicodedata.normalize("NFD", s.lower())
                if unicodedata.category(c) != "Mn").replace("đ", "d")
    for k in ("-", "_", "."):
        t = t.replace(k, " ")
    return " ".join(t.split())


def _nap_so_phong() -> tuple[dict[str, str], dict[str, str]]:
    """(sổ thực thể → phòng, sổ tên phòng không dấu → tên gốc)."""
    global _cache_phong, _cache_phong_luc, _cache_ten_phong
    now = time.time()
    if now - _cache_phong_luc > _HAN_CACHE_GIAY:
        try:
            from services.ha_client import get_ha_area_index
            idx = get_ha_area_index()
            _cache_phong = dict(idx.get("entity_area") or {})
            _cache_ten_phong = {
                _khong_dau(str(v)): str(v)
                for v in (idx.get("area_names") or {}).values()}
            if not _cache_ten_phong:
                _cache_ten_phong = {_khong_dau(v): v
                                    for v in set(_cache_phong.values())}
        except Exception as exc:
            logger.info({"event": "boi_canh_phong_loi", "error": str(exc)[:120]})
            _cache_phong = _cache_phong or {}
            _cache_ten_phong = _cache_ten_phong or {}
        _cache_phong_luc = now
    return _cache_phong, _cache_ten_phong


def phong_cua(thiet_bi: str) -> str:
    """Thiết bị này thuộc phòng nào.

    HỎI SỔ KHU VỰC THẬT của Home Assistant trước — đó là nơi chủ nhà đã xếp
    phòng, chính xác tuyệt đối, không phải suy diễn.

    Nhưng sổ HA chỉ phủ được thực thể HA. Đo thật 10/09/2026: 36/38 thiết bị
    trong kho số đo là MQTT thuần (`zigbee2mqtt/Nhiệt ẩm phòng học`), không có
    trong 151 thực thể của sổ. Chỉ dựa vào sổ thì gần như mọi số đo rơi vào
    "phòng khác", và bot mất khả năng phân biệt bếp tối với phòng ngủ tối —
    tức mất đúng thứ bốn sơ đồ cần.

    Nên nấc hai: đối chiếu tên thiết bị với DANH SÁCH PHÒNG CÓ THẬT của nhà
    (6 phòng: Bếp, Phòng khách, Phòng ngủ, Phòng học, Ban công, Nhà tắm). Đây
    không phải đoán bừa theo từ khoá tự nghĩ ra — tên phòng do chủ nhà đặt
    trong HA, và chỉ khớp khi tên thiết bị chứa đúng tên một phòng có thật.
    Chủ nhà đổi tên phòng thì bảng này tự đổi theo.

    Không khớp nấc nào → trả rỗng, tầng trên tự lùi lên mức cả nhà.
    """
    if not thiet_bi:
        return ""
    so, ten_phong = _nap_so_phong()
    thang = so.get(thiet_bi)
    if thang:
        return str(thang)

    t = _khong_dau(thiet_bi)
    # Khớp tên phòng DÀI trước: "phong khach" phải thắng "phong" nếu có cả hai.
    for kd in sorted(ten_phong, key=len, reverse=True):
        if kd and kd in t:
            return ten_phong[kd]
    return ""


def _khoa_phong(thiet_bi: str) -> str:
    """Tên phòng rút gọn để làm khoá — bỏ dấu cách, thường hoá."""
    p = phong_cua(thiet_bi)
    return p.strip().lower().replace(" ", "_") if p else "khac"


def _so_do_gan(luc: float, mau_truong: str) -> dict[str, dict[str, Any]]:
    """Số đo gần mốc `luc` nhất, theo từng phòng.

    Ba nấc, dừng ở nấc đầu tiên có dữ liệu — độ tin giảm dần theo khoảng cách:

    1. Ô chứa đúng `luc`            → tin 1.0
    2. Ô gần nhất trong ±30 phút    → tin giảm tuyến tính, sàn 0.5
    3. Không có                     → vắng mặt, ghi vào `thieu`

    KHÔNG NỘI SUY giữa hai ô xa nhau. `so_do` đã là trung bình 5 phút; nội suy
    giữa hai ô cách ba tiếng cho ra số bịa đội lốt số đo. Lấy điểm gần nhất
    kèm độ tin là trung thực hơn, và tầng trên chỉ rời rạc hoá thành
    "tối/nhá nhem/sáng" nên lệch vài lux không đổi kết luận.
    """
    from services import lich_su_nha

    o = int(luc // 300)
    do = int(_HAN_SO_DO_PHUT * 60 // 300)
    ra: dict[str, dict[str, Any]] = {}
    try:
        with lich_su_nha._khoa_db:
            rows = lich_su_nha._db().execute(
                "SELECT thiet_bi, o_5p, tb FROM so_do WHERE truong LIKE ?"
                " AND o_5p>=? AND o_5p<=? ORDER BY ABS(o_5p-?)",
                (mau_truong, o - do, o + do, o)).fetchall()
    except Exception as exc:
        logger.info({"event": "boi_canh_so_do_loi", "error": str(exc)[:120]})
        return ra

    for r in rows:
        khoa = _khoa_phong(str(r["thiet_bi"]))
        if khoa in ra:               # đã có bản gần hơn (ORDER BY ABS)
            continue
        lech_phut = abs(int(r["o_5p"]) - o) * 5
        tin = 1.0 if lech_phut == 0 else max(0.5, 1.0 - lech_phut / 60.0)
        ra[khoa] = {"gt": float(r["tb"]), "tin": round(tin, 2),
                    "nguon": "so_do" if lech_phut == 0 else "so_do_gan"}
    return ra


def _co_nguoi(luc: float) -> dict[str, dict[str, Any]]:
    """Lúc ấy phòng nào có người — bản ghi cuối TRƯỚC `luc`, còn hiệu lực."""
    from services import lich_su_nha

    ra: dict[str, dict[str, Any]] = {}
    try:
        sk = lich_su_nha.doc_cua_so(luc - _HAN_NGUOI_GIAY, luc)
    except Exception as exc:
        logger.info({"event": "boi_canh_nguoi_loi", "error": str(exc)[:120]})
        return ra

    for r in sk:                    # tăng dần → bản sau đè bản trước
        tr = str(r.get("truong") or "").lower()
        tb = str(r.get("thiet_bi") or "")
        if not any(k in tr or k in tb.lower() for k in _TRUONG_NGUOI):
            continue
        ra[_khoa_phong(tb)] = {
            "gt": _co_mat(r.get("gia_tri")), "tin": 1.0, "nguon": "su_kien"}
    return ra


def boi_canh(luc: float | None = None) -> dict[str, Any]:
    """Lúc `luc` thì nhà đang thế nào.

    Trả về::

        {"ts", "gio", "thu", "buoi", "mua", "thang",
         "lux":      {"<phòng>": {"gt", "tin", "nguon"}},
         "nhiet_do": {...}, "do_am": {...},
         "nguoi":    {"<phòng>": {"gt": True/False, ...}},
         "thoi_tiet": None,
         "thieu":    ["lux", ...]}

    Mỗi số đo kèm ``tin`` (0..1). Thứ không biết thì VẮNG MẶT và có tên trong
    ``thieu`` — không bao giờ có giá trị mặc định, xem lời dặn ở đầu tệp.

    Không bao giờ ném lỗi: hỏng phần nào thì phần đó vắng mặt, vì đây là tầng
    đọc phụ trợ, không được phép kéo theo tầng gọi nó.
    """
    t = float(luc) if luc else time.time()
    g = datetime.fromtimestamp(t, _TZ)
    ra: dict[str, Any] = {
        "ts": t,
        "gio": round(g.hour + g.minute / 60, 3),
        "thu": g.weekday(),
        "buoi": ten_buoi(g.hour),
        "thang": g.month,
        "mua": mua(g.month),
        # `thoi_tiet` để sẵn khoá cho lần sau: dự án mới có `thoi_tiet_bao`
        # (chỉ bão), chưa có thời tiết thường. Sơ đồ "quạt, bình nóng lạnh"
        # cần nó, nhưng thêm một dịch vụ ngoài là việc khác.
        "thoi_tiet": None,
        "thieu": [],
    }

    for ten, mau in (("lux", "%illuminance%"), ("nhiet_do", "%temperature%"),
                     ("do_am", "%humidity%")):
        v = _so_do_gan(t, mau)
        ra[ten] = v
        if not v:
            ra["thieu"].append(ten)

    ra["nguoi"] = _co_nguoi(t)
    if not ra["nguoi"]:
        ra["thieu"].append("nguoi")
    return ra


def _nguong(mau_truong: str, so_ngay: int = 30) -> tuple[float, float]:
    """Hai ngưỡng rời rạc hoá, lấy theo PHÂN VỊ CỦA CHÍNH NHÀ NÀY.

    Không đặt cứng "dưới 50 lux là tối": mỗi cảm biến một thang đo. Cảm biến
    báo 0–10 thì mọi lúc đều "tối"; cảm biến báo 0–20.000 thì mọi lúc đều
    "sáng". Phân vị tự khớp với thang thật của thiết bị trong nhà.
    """
    from services import lich_su_nha

    try:
        cat = time.time() - so_ngay * 86400
        with lich_su_nha._khoa_db:
            rows = lich_su_nha._db().execute(
                "SELECT tb FROM so_do WHERE truong LIKE ? AND o_5p>=?",
                (mau_truong, int(cat // 300))).fetchall()
        xs = sorted(float(r["tb"]) for r in rows)
    except Exception:
        xs = []
    if len(xs) < 10:
        return (0.0, 0.0)           # chưa đủ mẫu → không rời rạc hoá được
    return (xs[len(xs) * _PHAN_VI_DUOI // 100],
            xs[len(xs) * _PHAN_VI_TREN // 100])


def _nguong_cache(mau_truong: str) -> tuple[float, float]:
    global _cache_nguong, _cache_luc
    now = time.time()
    if now - _cache_luc > _HAN_CACHE_GIAY:
        _cache_nguong, _cache_luc = {}, now
    if mau_truong not in _cache_nguong:
        _cache_nguong[mau_truong] = _nguong(mau_truong)
    return _cache_nguong[mau_truong]


def _bac(gt: float, duoi: float, tren: float, ten: tuple[str, str, str]) -> str:
    if duoi == tren == 0.0:
        return ""
    return ten[0] if gt <= duoi else (ten[2] if gt >= tren else ten[1])


#: Ba phép đo bối cảnh, mỗi dòng: khoá máy, mẫu tên trường trong kho, ba mức
#: dạng mã, tên cho người đọc, ba mức viết ra tiếng Việt.
#:
#: Gộp làm MỘT hằng vì `roi_rac()` sinh ra khoá còn `mo_ta_dieu_kien()` dịch
#: khoá ngược lại cho chủ máy đọc. Để hai nơi tự giữ bảng riêng thì sớm muộn
#: lệch nhau, và cái lệch đó tới tay chủ máy dưới dạng tin nhắn không hiểu nổi.
_DO_DAC = (
    ("lux", "%illuminance%", ("toi", "nha_nhem", "sang"),
     "ánh sáng", ("tối", "nhá nhem", "sáng")),
    ("nhiet_do", "%temperature%", ("lanh", "vua", "nong"),
     "nhiệt độ", ("lạnh", "vừa", "nóng")),
    ("do_am", "%humidity%", ("kho", "vua", "am"),
     "độ ẩm", ("khô", "vừa", "ẩm")),
)

#: Thứ trong tuần — `datetime.weekday()` đếm từ 0 là thứ Hai.
_TEN_THU = ("thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm",
            "thứ Sáu", "thứ Bảy", "Chủ nhật")


def roi_rac(bc: dict[str, Any]) -> dict[str, str]:
    """Bối cảnh số → nhãn rời rạc. Tầng xác suất CHỈ ăn nhãn.

    Trường THIẾU thì không xuất hiện trong kết quả — không có nhãn
    "khong_biet". Nếu có, mô hình sẽ học được "khi không biết lux thì hay bật
    đèn", mà thật ra đó là "hồi tháng 8 nhà chưa có cảm biến". Naive Bayes bỏ
    qua điều kiện vắng mặt là đúng; biến cái thiếu thành một nhãn là sai.
    """
    ra: dict[str, str] = {
        "buoi": str(bc.get("buoi") or ""),
        "thu": str(bc.get("thu")),
        "mua": str(bc.get("mua") or ""),
    }
    for ten, mau, nhan, _, _ in _DO_DAC:
        duoi, tren = _nguong_cache(mau)
        for phong, v in (bc.get(ten) or {}).items():
            b = _bac(float(v["gt"]), duoi, tren, nhan)
            if b:
                ra[f"{ten}_{phong}"] = b

    co_ai = False
    for phong, v in (bc.get("nguoi") or {}).items():
        ra[f"nguoi_{phong}"] = "co" if v["gt"] else "khong"
        co_ai = co_ai or bool(v["gt"])
    if bc.get("nguoi"):
        ra["nguoi_trong_nha"] = "co" if co_ai else "khong"
    return ra


def _ten_phong(khoa: str) -> str:
    """Khoá phòng → tên đọc được.

    `khac` là chỗ `_khoa_phong()` xếp thiết bị CHƯA GÁN PHÒNG, không phải một
    phòng tên là "khác". Trả rỗng để câu văn bỏ hẳn phần phòng đi, chứ viết
    "nhiệt độ khác đang nóng" thì chủ máy đọc ra một phòng không tồn tại.
    """
    return "" if khoa == "khac" else khoa.replace("_", " ")


def mo_ta_dieu_kien(khoa: str, gia_tri: str) -> str:
    """Một điều kiện của mô hình → một mệnh đề tiếng Việt.

    Mô hình đếm bằng khoá máy (`lux_phòng_khách=toi`) vì phải khớp chính xác;
    chủ máy cần câu chữ ("ánh sáng phòng khách đang tối"). Chỗ dịch đặt ngay
    cạnh `roi_rac()` — nơi sinh ra khoá — và đọc chung hằng `_DO_DAC`, nên
    thêm một phép đo mới là thấy ngay phải đặt tên người đọc được cho nó.

    Khoá lạ thì trả RỖNG để tầng trên bỏ hẳn lý do đó. Thà chủ máy đọc được
    hai lý do còn hơn ba lý do mà một cái là chuỗi máy móc.
    """
    k = str(khoa or "").strip()
    v = str(gia_tri or "").strip()
    if not k or not v:
        return ""
    if k == "buoi":
        return f"buổi {v}"          # `ten_buoi()` vốn đã trả tiếng Việt
    if k == "mua":
        return {"nong": "mùa nóng", "lanh": "mùa lạnh",
                "chuyen": "lúc giao mùa"}.get(v, "")
    if k == "thu":
        try:
            return _TEN_THU[int(v)]
        except (ValueError, IndexError):
            return ""
    if k == "nguoi_trong_nha":
        return "trong nhà có người" if v == "co" else "trong nhà không có ai"
    if k.startswith("nguoi_"):
        phong = _ten_phong(k[len("nguoi_"):])
        if not phong:
            return ""
        return f"có người ở {phong}" if v == "co" else f"không có ai ở {phong}"
    for ten, _mau, muc, ten_doc, muc_doc in _DO_DAC:
        if k != ten and not k.startswith(f"{ten}_"):
            continue
        if v not in muc:
            return ""
        phong = _ten_phong(k[len(ten) + 1:]) if k != ten else ""
        phan = (ten_doc, phong, "đang", muc_doc[muc.index(v)])
        return " ".join(x for x in phan if x)
    return ""


def hien_tai() -> dict[str, Any]:
    """Bối cảnh BÂY GIỜ — được phép dùng bảng `tuoi` vì không có tương lai.

    Tách hẳn khỏi `boi_canh()` để chỗ nào lỡ dùng `tuoi` cho quá khứ thì phải
    gọi nhầm tên hàm mới lọt, chứ không lọt bằng một tham số đặt sai.
    """
    from services import lich_su_nha

    bc = boi_canh(time.time())
    now = time.time()
    try:
        for r in lich_su_nha.doc_tuoi():
            tr = str(r.get("truong") or "").lower()
            if now - float(r.get("ts") or 0) > _HAN_TUOI_GIAY:
                continue
            for ten, k in (("lux", "illuminance"), ("nhiet_do", "temperature"),
                           ("do_am", "humidity")):
                if k not in tr:
                    continue
                try:
                    v = float(r.get("gia_tri"))
                except (TypeError, ValueError):
                    continue
                bc.setdefault(ten, {})[_khoa_phong(str(r.get("thiet_bi")))] = {
                    "gt": v, "tin": 1.0, "nguon": "tuoi"}
                if ten in bc.get("thieu", []):
                    bc["thieu"].remove(ten)
    except Exception as exc:
        logger.info({"event": "boi_canh_tuoi_loi", "error": str(exc)[:120]})
    return bc


def _reset_for_tests() -> None:
    global _cache_nguong, _cache_luc, _cache_phong, _cache_phong_luc
    global _cache_ten_phong
    _cache_nguong, _cache_luc = {}, 0.0
    _cache_phong, _cache_ten_phong, _cache_phong_luc = {}, {}, 0.0
