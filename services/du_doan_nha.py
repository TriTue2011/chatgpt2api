"""Từ bối cảnh, tính XÁC SUẤT nên bật thiết bị hay nên báo tin.

Chủ máy nêu 10/09/2026: *"Rồi sau này căn cứ các điều kiện đó tính xác suất
cần bật thiết bị hay thông báo. Triển khai và phát triển rộng hơn."*

Bốn sơ đồ chủ máy vẽ là bốn TRƯỜNG HỢP của một luật chung, nên tầng này không
đóng khung theo tên thiết bị: bất cứ thứ gì có trong lịch sử đều học được, và
điều kiện là bất cứ thứ gì `boi_canh_nha` trả về.

BA MỞ RỘNG QUÁ SƠ ĐỒ, chủ máy chốt cùng ngày:

1. THIẾT BỊ LÀ ĐIỀU KIỆN CỦA NHAU. Mũi tên trong sơ đồ vẽ hai chiều — thiết bị
   này đang bật cũng là bối cảnh cho thiết bị khác. Không cần cấu trúc mới:
   mỗi thiết bị đang bật thành một điều kiện `bat_<tên>` như mọi điều kiện
   khác, và phép đếm tự tìm ra cặp nào đi với nhau. Bật bình nóng lạnh thì lát
   nữa bật đèn nhà tắm; bật bếp thì sắp tới giờ ăn. Không ai phải liệt kê.
2. "HÀNH ĐỘNG" — ô có mặt trong cả bốn sơ đồ — là việc chủ máy VỪA LÀM, cũng
   là điều kiện: `vua_lam_<tên>` trong 15 phút qua.
3. XÁC SUẤT ÁP CHO CẢ THÔNG BÁO. Cùng mô hình, chỉ đổi câu hỏi: thay vì "có
   nên bật đèn không" là "tin này chủ máy có muốn nghe không".

VÌ SAO NAIVE BAYES ĐẾM, KHÔNG PHẢI MÔ HÌNH LỚN HƠN:

* Nhà mới có 11 ngày dữ liệu, mỗi (thiết bị × giờ) được 5–15 mẫu. Hồi quy
  logistic cần cỡ trăm mẫu cho mỗi tham số; ở đây nó sẽ khớp quá mức rồi phun
  ra xác suất 0.99 sai bét.
* Naive Bayes CỘNG bằng chứng độc lập, nên thiếu một điều kiện chỉ là bớt một
  số hạng. Khớp thẳng với thực tế "đa số trường hợp sẽ thiếu" của
  `boi_canh_nha`. Hồi quy logistic thiếu đặc trưng thì phải điền số bịa.
* Giải thích được. `giai_thich()` nói ra từng bằng chứng, nên chủ máy sửa được
  bot. Mô hình không giải thích được thì sai cũng chịu.
* Công thức Laplace ``(k+1)/(n+2)`` ĐÃ LÀ công thức của dự án —
  `tinh_huong_nha.diem`, `skill_quality.diem`, `bai_hoc`. Dùng lại, khỏi có
  hai định nghĩa lệch nhau.
* Toàn bộ là đếm và `math.log`. Không thêm phụ thuộc nào.

BA LỚP CHỐNG HỌC TỪ CHÍNH MÌNH. Không có chúng thì bot bật đèn, thấy đèn bật,
kết luận "đúng rồi, giờ này hay bật đèn", rồi càng chắc càng bật:

1. `bo_do_ai=True` khi đọc lịch sử — cột `do_ai` sinh ra cho đúng việc này.
2. Mẫu ÂM phải tự sinh: mỗi ô 30 phút mà thiết bị KHÔNG bật là một mẫu "không
   bật". Log chỉ ghi cái đã xảy ra; không có mẫu âm thì mọi xác suất đều bằng
   1. Đây là lỗi kinh điển của hệ học từ log sự kiện.
3. Bot gợi ý mà người làm ngược lại trong 10 phút → tự chấm là sai, không cần
   chủ máy bấm.

MỨC TỰ CHỦ TỰ LÊN CẤP, TỪNG THIẾT BỊ MỘT. Chủ máy chốt ngưỡng: đúng 19/20 lần
và ít nhất 50 lượt được chấm thì thiết bị đó được tự làm. Không ai phải bật
tay, và cũng không ai phải nhớ tắt khi bot làm dở — sai 2 lần trong 10 lượt
gần nhất là tự tụt về chế độ hỏi.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR, config

logger = logging.getLogger(__name__)

_TZ = timezone(timedelta(hours=7))
_DB_PATH = Path(DATA_DIR) / "agent" / "du_doan_nha.sqlite"
_conn: Optional[sqlite3.Connection] = None
_khoa = threading.Lock()

#: Ô thời gian sinh mẫu âm. 30 phút: hẹp hơn thì mẫu âm nhiều gấp bội mẫu
#: dương và mô hình chỉ học được "phần lớn thời gian không ai bật gì".
_O_PHUT = 30

#: Cửa sổ coi là "vừa làm" — ô "Hành động" trong sơ đồ chủ máy.
_VUA_LAM_GIAY = 900.0

#: Điều kiện xuất hiện ít hơn ngần này lần thì bỏ: một lần trùng hợp không
#: phải bằng chứng, mà lại được Laplace thổi lên thành 2/3.
_TOI_THIEU_DIEU_KIEN = 3

#: Dưới ngưỡng này thì im hẳn. Trên `_P_GOI_Y` mới mở miệng.
_P_IM = 0.60
_P_GOI_Y = 0.75

#: Chủ máy chốt 10/09/2026: đúng 19/20 lần và ít nhất 50 lượt ĐƯỢC CHẤM.
_MAU_LEN_CAP = 50
_TY_LE_LEN_CAP = 0.95

#: Đang tự làm mà sai ngần này lần trong 10 lượt gần nhất là tụt cấp NGAY.
#: Đường xuống phải nhạy hơn đường lên: tỉ lệ cộng dồn trên 50 lượt phản ứng
#: quá chậm, mà nhà đổi nếp (con nghỉ hè, đổi phòng) thì bot phải nhận ra
#: trong vài ngày chứ không phải vài tuần.
_SAI_TUT_CAP = 2
_CUA_SO_TUT_CAP = 10

#: Không trả lời sau ngần này thì bỏ qua, KHÔNG tính là sai — theo
#: `skill_quality._KHONG_TINH`: người không trả lời là quyết định của người.
_HAN_TRA_LOI_GIAY = 1800.0

#: KHÔNG BAO GIỜ tự làm, dù điểm tuyệt đối.
#:
#: Đây là một danh sách tên, và là ngoại lệ có lý do không nguyên tắc nào thay
#: được: không có cách nào ĐO từ dữ liệu rằng "bật nhầm cái này thì cháy nhà
#: hoặc mở cửa cho người lạ". Mọi luật đo được đều nhìn vào nhịp đổi, mà khoá
#: cửa với đèn ngủ đổi giống hệt nhau.
#: So sánh SAU KHI bỏ dấu và chuẩn hoá gạch nối/gạch dưới thành dấu cách
#: (`boi_canh_nha._khong_dau`), nếu không thì `switch.binh_nong_lanh` lọt qua
#: mục "bình nóng" — đúng kiểu thiếu sót mà mọi danh sách từ khoá đều mắc.
_KHONG_TU_LAM = ("lock", "khoa", "cua", "bep", "binh nong", "water heater",
                 "o cam", "socket", "outlet", "quat suoi", "lo ")

_TRANG_THAI_CHO = "cho"


def _cfg() -> dict[str, Any]:
    raw = (config.data.get("mqtt") or {}).get("du_doan")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("bat", True))


def _so_ngay_hoc() -> int:
    try:
        return max(3, int(_cfg().get("so_ngay") or 30))
    except (TypeError, ValueError):
        return 30


def _db() -> sqlite3.Connection:
    """Khuôn theo `tinh_huong_nha`: WAL + CREATE IF NOT EXISTS."""
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS du_doan ("
            " id INTEGER PRIMARY KEY,"
            " ts REAL NOT NULL,"
            " loai TEXT NOT NULL DEFAULT 'thiet_bi',"   # thiet_bi | thong_bao
            " ten TEXT NOT NULL,"
            " hanh_dong TEXT NOT NULL,"
            " p REAL NOT NULL,"
            " boi_canh TEXT,"                # JSON — để còn giải thích được
            " cach TEXT NOT NULL,"           # goi_y | tu_lam
            " ket_qua TEXT NOT NULL DEFAULT 'cho',"   # cho|dung|sai|lo
            " tra_loi_luc REAL)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dd_ten ON du_doan(ten, ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dd_kq ON du_doan(ket_qua)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS thanh_tich ("
            " ten TEXT PRIMARY KEY,"
            " dung INTEGER NOT NULL DEFAULT 0,"
            " sai INTEGER NOT NULL DEFAULT 0)"
        )
        conn.commit()
        _conn = conn
    return _conn


# ── Gom mẫu ─────────────────────────────────────────────────────────────────
def _la_so(gt: Any) -> bool:
    try:
        float(str(gt).strip())
        return True
    except (TypeError, ValueError):
        return False


def _la_bat(gt: Any) -> bool:
    """Giá trị này có nghĩa THIẾT BỊ ĐANG BẬT không.

    MỘT CON SỐ LÀ SỐ ĐO, KHÔNG PHẢI TRẠNG THÁI. `sensor.entities` = "1080" là
    Home Assistant đang có 1.080 thực thể; nhiệt độ "23.5" là 23,5 độ. Bản cũ
    dùng danh sách loại trừ — bất cứ gì không nằm trong `_LA_TAT` đều tính là
    ĐANG BẬT — nên mỗi lần bộ đếm nhảy 979 → 1080 bot ghi sổ "ai đó vừa bật
    sensor.entities", rồi mời chủ máy bật lại cái đếm ấy.

    Danh sách loại trừ không bao giờ đủ, vì tập "mọi giá trị nghĩa là tắt" là
    vô hạn. Hỏi "giá trị này có phải số đo không" thì đóng được cả lớp.

    Đo 11/09/2026 trên 11 ngày dữ liệu thật: luật này loại 165/322 thực thể
    rác mà KHÔNG loại oan cái nào bật được (0 ca).

    Khác `boi_canh_nha._co_mat`: ở đó số là ĐẾM NGƯỜI, "2" nghĩa là có người.
    """
    from services.boi_canh_nha import _LA_TAT

    if _la_so(gt):
        return False
    return str(gt or "").strip().lower() not in _LA_TAT


def mien_bat_duoc() -> frozenset[str]:
    """Miền Home Assistant nào có lệnh `turn_on` — HỎI HA, không tự liệt kê.

    `GET /api/services` là sổ đăng ký thật của chính căn nhà này, gồm cả
    integration tự cài. Nhà thêm loại thiết bị mới thì danh sách tự đúng theo,
    không ai phải nhớ sửa code — đó là khác biệt giữa sửa theo NGUYÊN TẮC và
    sửa theo DANH SÁCH.

    Đo 11/09/2026 trên HA thật: 94 miền, 15 miền có `turn_on`. `sensor`,
    `binary_sensor`, `image`, `event` đều KHÔNG có.

    HA sập thì `get_service_catalog()` trả rỗng → bot im, không gợi ý gì. Im
    là đúng: thà không nói còn hơn mời bật một cái đồng hồ đo.
    """
    from services import ha_client

    cat = ha_client.get_service_catalog()
    mien = frozenset(d for d, svc in (cat or {}).items()
                     if "turn_on" in (svc or {}))
    if not mien:
        logger.warning({"event": "du_doan_khong_ro_mien_bat_duoc",
                        "ghi_chu": "HA chua tra ve so dich vu — tam thoi im"})
    return mien


def ten_thiet_bi(ten: str) -> str:
    """Mã thực thể → tên chủ máy tự đặt trong Home Assistant.

    `light.bep_left` → "Đèn bếp". Mã máy chỉ để mô hình đếm cho khớp; ra tới
    tin nhắn thì phải là tên người đọc được.

    Đo 11/09/2026: cả 1.046 thực thể của nhà đều có `friendly_name`, nên
    đường này gần như luôn có tên thật. Tra không ra thì giữ nguyên mã — thà
    khó đọc còn hơn bịa ra một cái tên.
    """
    from services import ha_client

    ma = str(ten or "")
    for s in ha_client.get_states():
        if s.get("entity_id") == ma:
            return str((s.get("attributes") or {}).get("friendly_name") or ma)
    return ma


def _dieu_kien(luc: float, dang_bat: dict[str, float],
               vua_lam: dict[str, float], tru: str = "") -> dict[str, str]:
    """Toàn bộ điều kiện lúc `luc`, dạng nhãn.

    `tru` là thiết bị đang được đoán — phải BỎ nó khỏi điều kiện, nếu không mô
    hình học được "đèn bếp đang bật thì hay bật đèn bếp", đúng 100% và vô
    dụng. Đây là rò rỉ nhãn, cùng họ với chuyện dùng `tuoi` cho quá khứ.
    """
    from services import boi_canh_nha

    nhan = boi_canh_nha.roi_rac(boi_canh_nha.boi_canh(luc))
    for ten, tu in dang_bat.items():
        if ten != tru and luc - tu < 6 * 3600:
            nhan[f"bat_{ten}"] = "co"
    for ten, tu in vua_lam.items():
        if ten != tru and 0 <= luc - tu < _VUA_LAM_GIAY:
            nhan[f"vua_lam_{ten}"] = "co"
    return nhan


def hoc(so_ngay: int | None = None) -> dict[str, Any]:
    """Đếm mẫu dương và mẫu âm cho mọi thiết bị, trả bảng đếm.

    Trả ``{ten: {"n_bat", "n_khong", "dk": {nhãn: {"bat": k, "khong": k}}}}``.

    Đọc với ``bo_do_ai=True``: học từ hành động của chính bot là tự khẳng định
    vòng quanh.
    """
    from services import lich_su_nha

    ngay = so_ngay if so_ngay else _so_ngay_hoc()
    den = time.time()
    tu = den - max(1, int(ngay)) * 86400
    try:
        sk = lich_su_nha.doc_cua_so(tu, den, bo_do_ai=True)
    except Exception as exc:
        logger.warning({"event": "du_doan_doc_loi", "error": str(exc)[:160]})
        return {}

    # Lượt BẬT của từng thiết bị, và trạng thái đang bật theo thời gian.
    bat_luc: dict[str, list[float]] = {}
    dang_bat: dict[str, float] = {}
    vua_lam: dict[str, float] = {}
    moc_o: dict[int, dict[str, Any]] = {}

    for r in sk:
        tb = str(r.get("thiet_bi") or "")
        tr = str(r.get("truong") or "").lower()
        if not tb or not tr.startswith("state"):
            continue
        ts = float(r.get("ts") or 0)
        if _la_bat(r.get("gia_tri")):
            bat_luc.setdefault(tb, []).append(ts)
            dang_bat[tb] = ts
        else:
            dang_bat.pop(tb, None)
        vua_lam[tb] = ts
        o = int(ts // (_O_PHUT * 60))
        moc_o.setdefault(o, {"ts": ts, "bat": set()})["bat"].add(tb)

    if not bat_luc:
        return {}

    # Ô thời gian có mặt trong dữ liệu — mẫu âm chỉ lấy từ ô CÓ hoạt động, vì
    # ô nhà vắng hoàn toàn không nói lên "chủ máy chọn không bật".
    o_ds = sorted(moc_o)
    ra: dict[str, Any] = {}
    for tb, moc in bat_luc.items():
        if len(moc) < _TOI_THIEU_DIEU_KIEN:
            continue
        o_bat = {int(t // (_O_PHUT * 60)) for t in moc}
        dem: dict[str, dict[str, int]] = {}
        n_bat = n_khong = 0
        for o in o_ds:
            co = o in o_bat
            t = moc_o[o]["ts"]
            nhan = _dieu_kien(t, {}, {}, tru=tb)
            # Trạng thái thiết bị khác tại ô này (mở rộng 1 và 2).
            for khac in moc_o[o]["bat"]:
                if khac != tb:
                    nhan[f"bat_{khac}"] = "co"
            if co:
                n_bat += 1
            else:
                n_khong += 1
            for k, v in nhan.items():
                d = dem.setdefault(f"{k}={v}", {"bat": 0, "khong": 0})
                d["bat" if co else "khong"] += 1
        ra[tb] = {"n_bat": n_bat, "n_khong": n_khong, "dk": dem}
    return ra


# ── Ước lượng ───────────────────────────────────────────────────────────────
def uoc_luong(dem_muc: list[tuple[int, int]]) -> float:
    """Trộn nhiều mức phân cấp thành một xác suất (Jelinek–Mercer).

    ``dem_muc`` xếp từ HẸP tới RỘNG: [(k, n) mức riêng nhất, ..., mức chung].
    Phân cấp của chủ máy — mùa → phòng → thời gian → thiết bị — chính là thứ
    tự lùi khi thiếu mẫu.

    λ = n/(n+K): mức nào nhiều mẫu thì tự nói to, ít mẫu thì tự nhường cho mức
    rộng hơn. KHÔNG dùng ngưỡng cứng kiểu "đủ 4 mẫu mới tính" vì như thế mẫu
    thứ 4 xuất hiện là xác suất nhảy vọt, rồi mẫu thứ 5 lại nhảy về.

    Với 11 ngày dữ liệu, mức riêng nhất thường n=0 → λ=0, hoàn toàn nhường mức
    rộng. Sau vài tháng nó tự nặng dần lên. Phân cấp không phải để dùng ngay,
    mà để TỰ CHÍN theo dữ liệu, không ai phải sửa hằng số.
    """
    _K = 5
    p = 0.5
    for k, n in reversed(dem_muc):
        if n <= 0:
            continue
        lam = n / (n + _K)
        p = lam * ((k + 1) / (n + 2)) + (1 - lam) * p
    return max(0.001, min(0.999, p))


def _xac_suat(bang: dict[str, Any], nhan: dict[str, str]) -> tuple[float, list[dict]]:
    """Naive Bayes: nền + tổng bằng chứng. Trả (xác suất, danh sách bằng chứng)."""
    n_bat = int(bang.get("n_bat") or 0)
    n_khong = int(bang.get("n_khong") or 0)
    if n_bat + n_khong <= 0:
        return 0.0, []

    nen = uoc_luong([(n_bat, n_bat + n_khong)])
    logit = math.log(nen / (1 - nen))
    bang_chung: list[dict[str, Any]] = []

    for k, v in nhan.items():
        d = (bang.get("dk") or {}).get(f"{k}={v}")
        if not d or (d["bat"] + d["khong"]) < _TOI_THIEU_DIEU_KIEN:
            continue
        # Laplace hai phía, cùng công thức `tinh_huong_nha.diem`.
        p_co = (d["bat"] + 1) / (n_bat + 2)
        p_khong = (d["khong"] + 1) / (n_khong + 2)
        w = math.log(p_co / p_khong)
        logit += w
        bang_chung.append({"dieu_kien": f"{k}={v}", "trong_so": round(w, 3),
                           "khi_bat": d["bat"], "khi_khong": d["khong"]})

    bang_chung.sort(key=lambda x: -abs(x["trong_so"]))
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, logit)))), bang_chung


def du_doan(ten: str, luc: float | None = None,
            bang: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bây giờ có nên bật `ten` không, và VÌ SAO.

    Trả ``{"ten", "p", "cap", "cach", "bang_chung": [...], "nhan": {...}}``.
    ``cach`` là ``"im"`` | ``"goi_y"`` | ``"tu_lam"``.
    """
    t = float(luc) if luc else time.time()
    b = bang if bang is not None else hoc().get(ten, {})
    if not b:
        return {"ten": ten, "p": 0.0, "cap": 0, "cach": "im",
                "bang_chung": [], "nhan": {}, "ly_do": "chưa đủ dữ liệu"}

    from services import boi_canh_nha
    nhan = boi_canh_nha.roi_rac(boi_canh_nha.hien_tai() if not luc
                                else boi_canh_nha.boi_canh(t))
    p, bc = _xac_suat(b, nhan)
    c = cap(ten)
    if p < _P_GOI_Y:
        cach = "im"
    elif c >= 2:
        cach = "tu_lam"
    else:
        cach = "goi_y"
    return {"ten": ten, "p": round(p, 4), "cap": c, "cach": cach,
            "bang_chung": bc[:6], "nhan": nhan}


# ── Thành tích và cấp tự chủ ────────────────────────────────────────────────
def diem(ten: str) -> float:
    """Tỉ lệ đúng, làm mượt Laplace — cùng công thức `tinh_huong_nha.diem`."""
    with _khoa:
        r = _db().execute(
            "SELECT dung, sai FROM thanh_tich WHERE ten=?", (ten,)).fetchone()
    if not r:
        return 0.5
    return (int(r["dung"]) + 1) / (int(r["dung"]) + int(r["sai"]) + 2)


def so_luot(ten: str) -> int:
    """Số lượt ĐƯỢC CHẤM. Lượt 'lo' không tính — người không trả lời là quyết
    định của người, không phải bot sai."""
    with _khoa:
        r = _db().execute(
            "SELECT dung, sai FROM thanh_tich WHERE ten=?", (ten,)).fetchone()
    return (int(r["dung"]) + int(r["sai"])) if r else 0


def sai_gan_day(ten: str, so_luot_xet: int = _CUA_SO_TUT_CAP) -> int:
    with _khoa:
        rows = _db().execute(
            "SELECT ket_qua FROM du_doan WHERE ten=? AND ket_qua IN ('dung','sai')"
            " ORDER BY ts DESC LIMIT ?", (ten, int(so_luot_xet))).fetchall()
    return sum(1 for r in rows if r["ket_qua"] == "sai")


def _cam_tu_lam(ten: str) -> bool:
    from services.boi_canh_nha import _khong_dau
    t = _khong_dau(ten)
    return any(k in t for k in _KHONG_TU_LAM)


def cap(ten: str) -> int:
    """Cấp tự chủ của RIÊNG thiết bị này: 0 im, 1 gợi ý, 2 tự làm.

    Không thiết bị nào bắt đầu ở cấp 2. Đường lên là việc của chính bot: gợi ý
    → chủ máy chấm → đủ 50 lượt mà đúng ≥95% → tự làm. Chủ máy không phải bật
    tay cho từng cái, và cũng không phải nhớ tắt khi bot làm dở.

    Đường XUỐNG nhạy hơn đường lên, xem `_SAI_TUT_CAP`.
    """
    if _cam_tu_lam(ten):
        return 1
    if sai_gan_day(ten) >= _SAI_TUT_CAP:
        return 1
    if so_luot(ten) >= _MAU_LEN_CAP and diem(ten) >= _TY_LE_LEN_CAP:
        return 2
    return 1


def ghi_nhan(ten: str, hanh_dong: str, p: float, nhan: dict[str, Any],
             cach: str, loai: str = "thiet_bi") -> int:
    """Lưu một lần đoán để sau còn chấm và giải thích. Trả id."""
    with _khoa:
        conn = _db()
        cur = conn.execute(
            "INSERT INTO du_doan (ts, loai, ten, hanh_dong, p, boi_canh, cach)"
            " VALUES (?,?,?,?,?,?,?)",
            (time.time(), loai, ten, hanh_dong, float(p),
             json.dumps(nhan, ensure_ascii=False), cach))
        conn.commit()
        return int(cur.lastrowid or 0)


def _cham(id_: int, ket_qua: str) -> bool:
    with _khoa:
        conn = _db()
        r = conn.execute("SELECT ten, ket_qua FROM du_doan WHERE id=?",
                         (int(id_),)).fetchone()
        if not r or r["ket_qua"] != _TRANG_THAI_CHO:
            return False
        conn.execute("UPDATE du_doan SET ket_qua=?, tra_loi_luc=? WHERE id=?",
                     (ket_qua, time.time(), int(id_)))
        if ket_qua in ("dung", "sai"):
            cot = "dung" if ket_qua == "dung" else "sai"
            conn.execute(
                f"INSERT INTO thanh_tich (ten, {cot}) VALUES (?,1)"
                f" ON CONFLICT(ten) DO UPDATE SET {cot}={cot}+1", (r["ten"],))
        conn.commit()
    return True


def ghi_dung(id_: int) -> bool:
    return _cham(id_, "dung")


def ghi_sai(id_: int) -> bool:
    return _cham(id_, "sai")


def ghi_lo(id_: int) -> bool:
    """Người không trả lời. KHÔNG tính là sai — theo `skill_quality._KHONG_TINH`."""
    return _cham(id_, "lo")


def don_qua_han() -> int:
    """Gợi ý quá hạn mà chưa ai chấm → 'lo'."""
    cat = time.time() - _HAN_TRA_LOI_GIAY
    with _khoa:
        conn = _db()
        n = conn.execute(
            "UPDATE du_doan SET ket_qua='lo', tra_loi_luc=?"
            " WHERE ket_qua='cho' AND ts < ?", (time.time(), cat)).rowcount
        conn.commit()
    return int(n)


def soi_bi_huy(cua_so_phut: int = 10) -> int:
    """Bot tự làm, người làm ngược lại ngay → lần đó SAI.

    Tín hiệu mạnh nhất và không tốn của chủ máy câu nào: người tắt ngay cái bot
    vừa bật là phản đối rõ ràng hơn mọi nút bấm.
    """
    from services import lich_su_nha

    with _khoa:
        rows = _db().execute(
            "SELECT id, ten, hanh_dong, ts FROM du_doan"
            " WHERE cach='tu_lam' AND ket_qua='cho' AND ts > ?",
            (time.time() - 86400,)).fetchall()
    n = 0
    for r in rows:
        try:
            sk = lich_su_nha.doc_su_kien(
                str(r["ten"]), float(r["ts"]),
                float(r["ts"]) + cua_so_phut * 60)
        except Exception:
            continue
        nguoc = "off" if str(r["hanh_dong"]).lower() == "on" else "on"
        if any(str(x.get("gia_tri") or "").lower() == nguoc
               and not x.get("do_ai") for x in sk):
            if ghi_sai(int(r["id"])):
                n += 1
    return n


def giai_thich(id_: int) -> str:
    """Vì sao bot đoán vậy — để chủ máy sửa được bot.

    Mô hình không giải thích được thì sai cũng đành chịu; đây là lý do chọn
    Naive Bayes thay vì thứ mạnh hơn.
    """
    with _khoa:
        r = _db().execute("SELECT * FROM du_doan WHERE id=?",
                          (int(id_),)).fetchone()
    if not r:
        return ""
    try:
        nhan = json.loads(r["boi_canh"] or "{}")
    except (ValueError, TypeError):
        nhan = {}
    g = datetime.fromtimestamp(float(r["ts"]), _TZ)
    dong = [f"{g:%H:%M %d/%m} — {ten_thiet_bi(str(r['ten']))} {r['hanh_dong']}, "
            f"em chắc {float(r['p']) * 100:.0f}%"]
    if nhan:
        luc_do = [x for x in (_ly_do(f"{k}={v}")
                              for k, v in list(nhan.items())[:8]) if x]
        if luc_do:
            dong.append("Lúc đó: " + ", ".join(luc_do))
    return "\n".join(dong)


# ── Vòng chạy ───────────────────────────────────────────────────────────────
def quet(luc: float | None = None) -> list[dict[str, Any]]:
    """Xem có việc nào đáng gợi ý bây giờ không.

    KHÔNG tự bật gì trong hàm này — nó chỉ trả về danh sách. Việc bật là tác
    dụng phụ, phải đi qua cổng riêng của tầng gọi.
    """
    bang = hoc()
    # Cổng chặn đặt ở ĐÂY chứ không ở `hoc()`: học là phân tích ngoại tuyến,
    # buộc nó phụ thuộc Home Assistant còn sống là đấu nối sai chỗ. Còn lời đề
    # nghị thì vốn đã cần HA — không hỏi được HA cái gì bật được thì cũng
    # không bật được gì, im là đúng.
    #
    # Cảm biến vẫn học bình thường để làm bối cảnh; chỉ không được đứng tên
    # trong câu "anh có muốn em bật không".
    mien = mien_bat_duoc()
    ra = []
    for ten, b in bang.items():
        if str(ten).split(".")[0] not in mien:
            continue
        d = du_doan(ten, luc, bang=b)
        if d["cach"] != "im":
            ra.append(d)
    ra.sort(key=lambda x: -x["p"])
    return ra


def _kenh_nhan() -> list[str]:
    """Kênh nhận gợi ý — khoá ``plat:bot:chat`` như «Lọc thread».

    Dùng CHUNG khoá với `bai_hoc` (`mqtt.bai_hoc.kenh_nhan`): cả hai đều là
    "phần học hỏi", chủ máy chọn một lần cho cả hai chứ không phải chỉnh hai
    nơi. Riêng `mqtt.du_doan.kenh_nhan` đặt riêng thì thắng.

    Rỗng = chưa chọn → rơi về admin mặc định, đường của `canh_bao_nha`.
    """
    for cau in (_cfg().get("kenh_nhan"),
                ((config.data.get("mqtt") or {}).get("bai_hoc") or {}).get("kenh_nhan")):
        if isinstance(cau, list):
            ds = [str(x).strip() for x in cau if str(x).strip()]
            if ds:
                return ds
    return []


def _ly_do(dieu_kien: str) -> str:
    """Một dòng bằng chứng của mô hình → một mệnh đề tiếng Việt.

    Khoá do `boi_canh_nha.roi_rac()` sinh ra nên nhờ chính module đó dịch:
    một nguồn duy nhất, không có bảng thứ hai để mà lệch.

    Dịch không ra thì trả rỗng và tầng trên bỏ hẳn lý do đó đi.
    """
    from services import boi_canh_nha

    khoa, _, gt = str(dieu_kien or "").partition("=")
    return boi_canh_nha.mo_ta_dieu_kien(khoa, gt) if khoa else ""


def soan_tin(ds: list[dict[str, Any]]) -> str:
    """Lời nhắn cho chủ máy — nói cả VÌ SAO, không chỉ đề nghị.

    Không giải thích được thì chủ máy không có cách nào sửa bot, mà sửa được
    bot chính là lý do chọn Naive Bayes thay vì mô hình mạnh hơn.
    """
    if not ds:
        return ""
    dong = ["🏠 Em để ý nếp nhà, thấy mấy việc này:"]
    for d in ds:
        vi_sao = ", ".join(x for x in (
            _ly_do(str(b.get("dieu_kien") or ""))
            for b in (d.get("bang_chung") or [])[:3]) if x)
        lam = "em bật rồi" if d["cach"] == "tu_lam" else "anh có muốn em bật không"
        dong.append(f"• {ten_thiet_bi(str(d['ten']))} — {lam} "
                    f"(em chắc {d['p'] * 100:.0f}%"
                    + (f", vì {vi_sao}" if vi_sao else "") + ")")
    return "\n".join(dong)


def chay_mot_lan(toi_da: int = 3) -> dict[str, Any]:
    """Heartbeat gọi. Dọn quá hạn, tự chấm, rồi BÁO việc đáng nói."""
    if not is_enabled():
        return {"bo_qua": "đang tắt"}
    lo = don_qua_han()
    huy = soi_bi_huy()
    ds = quet()[:max(1, int(toi_da))]
    if not ds:
        return {"lo": lo, "tu_cham_sai": huy, "gui": 0,
                "ly_do": "chưa có gì đáng nói"}

    tin = soan_tin(ds)
    gui = 0
    kenh = _kenh_nhan()
    if kenh:
        try:
            from services import digest
            gui = digest.send_targets(kenh, tin)
        except Exception as exc:
            logger.warning({"event": "du_doan_gui_loi", "loi": str(exc)[:150]})
    else:
        try:
            from services import canh_bao_nha
            from services.agent import reminders as rem
            for uid in canh_bao_nha._nguoi_nhan():
                channel, chat_id = rem.channel_of(uid)
                rem._send(channel, chat_id, tin, {})
                gui += 1
        except Exception as exc:
            logger.warning({"event": "du_doan_gui_loi", "loi": str(exc)[:150]})

    # Ghi lại từng gợi ý ĐÃ GỬI để sau còn chấm đúng/sai và tính cấp tự chủ.
    if gui:
        for d in ds:
            ghi_nhan(str(d["ten"]), "on", float(d["p"]),
                     d.get("nhan") or {}, str(d["cach"]))
    return {"lo": lo, "tu_cham_sai": huy, "gui": gui, "goi_y": ds}


def thong_ke() -> dict[str, Any]:
    with _khoa:
        conn = _db()
        tong = conn.execute("SELECT COUNT(*) FROM du_doan").fetchone()[0]
        theo = {r["ket_qua"]: r["n"] for r in conn.execute(
            "SELECT ket_qua, COUNT(*) n FROM du_doan GROUP BY ket_qua")}
        tt = [dict(r) for r in conn.execute(
            "SELECT ten, dung, sai FROM thanh_tich ORDER BY dung+sai DESC LIMIT 20")]
    for x in tt:
        x["diem"] = round(diem(str(x["ten"])), 3)
        x["cap"] = cap(str(x["ten"]))
        x["con_thieu_luot"] = max(0, _MAU_LEN_CAP - int(x["dung"]) - int(x["sai"]))
    return {"bat": is_enabled(), "tong": tong, "theo_ket_qua": theo,
            "thanh_tich": tt, "nguong_len_cap":
                {"so_luot": _MAU_LEN_CAP, "ty_le": _TY_LE_LEN_CAP}}


def _reset_for_tests() -> None:
    global _conn
    try:
        if _conn is not None:
            _conn.close()
    except Exception:
        pass
    _conn = None
