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

#: Làm mượt m-estimate: tỉ lệ của một điều kiện được kéo về TẦN SUẤT CHUNG của
#: chính nó, không phải cộng 1 hai phía (Laplace). Xem `_xac_suat`.
_M_LAM_MUOT = 2.0

#: KIỂM TIẾN DẦN từng thiết bị trước khi cho mở miệng: đếm trên phần đầu cửa sổ
#: học, thử trên `_KIEM_NGAY` ngày cuối như thể đang sống lại những ngày đó. Chỉ
#: được gợi ý khi trong mấy ngày thử có ít nhất `_KIEM_TOI_THIEU` lần đoán ≥
#: `_P_GOI_Y`, và từ `_KIEM_TY_LE` số lần đó thiết bị thật sự được bật — cổng
#: 60% CLAUDE.md đặt cho tầng xác suất, nay áp cho từng thiết bị. Nếp nhà đổi
#: (con nghỉ hè, đổi phòng) thì mấy ngày thử đoán trượt và bot tự im.
_KIEM_NGAY = 7
_KIEM_TOI_THIEU = 5
_KIEM_TY_LE = 0.60

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


def dem_dieu_kien_thiet_bi(thiet_bi: str, cac_khoa: list[str],
                          so_ngay: int | None = None,
                          *, bo_nho_o: dict[int, dict[str, str]] | None = None,
                          ) -> dict[str, dict[str, Any]]:
    """Với MỖI lần `thiet_bi` bật trong `so_ngay` ngày qua, điều kiện `cac_khoa`
    thường mang giá trị gì — cho tab Học hỏi trả lời "điều kiện này xảy ra khi
    nào" khi chủ máy vừa thêm một điều kiện mới trên sơ đồ kích hoạt.

    Nhận thẳng `cac_khoa` (không lọc theo bot đã chọn hay chưa — khác `hoc()`)
    để đo được cả điều kiện bot CHƯA TỪNG chọn. Trả mỗi khoá:
    ``{"nhan_hay_gap": str, "ty_le": float, "mau": int}`` — `mau` là số lần
    bật CÓ đo được nhãn đó (bỏ những lần thiếu cảm biến, không tính là "không
    khớp"). Rỗng hoặc `mau=0` khi chưa đủ dữ liệu.

    DỰNG BỐI CẢNH MỘT LẦN CHO MỖI Ô 30 PHÚT, y như `hoc()` — không phải mỗi
    lần bật một lần. Đo trên máy chủ thật 12/09/2026: `switch.bep_left` có
    1.153 lần bật nhưng chỉ nằm trong 125 ô, mà `boi_canh()` tốn 32ms mỗi
    lượt; gọi theo từng lần bật làm riêng nó mất ~37 giây, và cả sơ đồ 13
    thiết bị mất 47 giây — trình duyệt bỏ cuộc trước, chủ máy chỉ thấy "chưa
    có thiết bị nào được học". Đây đúng cái bẫy `hoc()` đã ghi lại và đã tự
    sửa một lần.

    `bo_nho_o` là bộ nhớ ô DÙNG CHUNG giữa nhiều thiết bị (nơi gọi truyền vào,
    xem `hieu_thiet_bi_nha.so_do_kich_hoat`): 13 thiết bị chỉ chạm 187 ô duy
    nhất, chia sẻ bộ nhớ thì tổng còn ~6 giây thay vì cộng dồn từng thiết bị."""
    from services import lich_su_nha

    ngay = max(1, int(so_ngay or _so_ngay_hoc()))
    den = time.time()
    tu = den - ngay * 86400
    khac_ma = {k[len("bat_"):] for k in cac_khoa if k.startswith("bat_")}
    try:
        sk = lich_su_nha.doc_trang_thai(
            tu, den, tien_to=tuple(sorted({thiet_bi} | khac_ma)), bo_do_ai=True)
    except Exception as exc:
        logger.warning({"event": "dem_dieu_kien_doc_loi", "error": str(exc)[:160]})
        return {}
    on_ts: list[float] = []
    doi_trong_o: dict[int, set[str]] = {}
    for r in sk:
        if str(r.get("truong") or "") != "state":
            continue
        tb = str(r.get("thiet_bi") or "")
        ts = float(r.get("ts") or 0)
        doi_trong_o.setdefault(int(ts // (_O_PHUT * 60)), set()).add(tb)
        if tb == thiet_bi and _la_bat(r.get("gia_tri")):
            on_ts.append(ts)
    if not on_ts:
        return {}
    # Bối cảnh của một ô KHÔNG phụ thuộc thiết bị đang xét: `_dieu_kien` ở đây
    # nhận `dang_bat`/`vua_lam` RỖNG nên `tru=` không đổi gì — nhờ vậy bộ nhớ ô
    # dùng chung được cho mọi thiết bị. Nhãn `bat_<mã>` thì thêm ở dưới, trên
    # BẢN SAO, không được ghi đè vào bộ nhớ chung.
    nhan_o = bo_nho_o if bo_nho_o is not None else {}
    dem: dict[str, dict[str, int]] = {k: {} for k in cac_khoa}
    for ts in on_ts:
        slot = int(ts // (_O_PHUT * 60))
        goc = nhan_o.get(slot)
        if goc is None:
            goc = _dieu_kien(ts, {}, {})
            nhan_o[slot] = goc
        nhan = dict(goc)
        nhan.pop(f"bat_{thiet_bi}", None)
        for khac in doi_trong_o.get(slot, ()):
            if khac != thiet_bi:
                nhan[f"bat_{khac}"] = "co"
        for k in cac_khoa:
            if k in nhan:
                d = dem[k]
                d[nhan[k]] = d.get(nhan[k], 0) + 1
    ra: dict[str, dict[str, Any]] = {}
    for k, d in dem.items():
        mau = sum(d.values())
        if not mau:
            ra[k] = {"nhan_hay_gap": "", "ty_le": 0.0, "mau": 0}
            continue
        nhan_hay_gap, so_lan = max(d.items(), key=lambda x: x[1])
        ra[k] = {"nhan_hay_gap": nhan_hay_gap, "ty_le": round(so_lan / mau, 3), "mau": mau}
    return ra


def hoc(so_ngay: int | None = None) -> dict[str, Any]:
    """Đếm mẫu dương và mẫu âm cho các thiết bị ĐƯỢC HỌC, trả bảng đếm.

    Trả ``{ten: {"n_bat", "n_khong", "dk": {nhãn: {"bat": k, "khong": k}}}}``.

    HỌC CÁI GÌ DO BOT HỌC HỎI KẾT LUẬN (`hieu_thiet_bi_nha.thiet_bi_hoc`),
    không do code liệt kê. Chủ máy chốt 11/09/2026: *"Việc học hỏi nên học
    theo các thiết bị bật tắt được chứ các thiết bị trạng thái học làm gì"* —
    và Claude chỉ soạn hướng dẫn cho bot tự giải rồi chấm. Bot chưa kết luận
    gì thì BỎ LƯỢT: học rỗng hay học bừa đều tệ hơn im.

    CHỈ ĐỌC THIẾT BỊ ĐƯỢC HỌC, lọc ngay trong SQL. Bản trước kéo mọi sự kiện về
    rồi tự bỏ: đo kho thật 11/09/2026, 30 ngày có 609.089 sự kiện mà trần đọc
    là 200.000 — tầng học chỉ thấy 4,5 ngày gần nhất.

    Đọc với ``bo_do_ai=True``: học từ hành động của chính bot là tự khẳng định
    vòng quanh.
    """
    from services import hieu_thiet_bi_nha, lich_su_nha

    duoc_hoc = set(hieu_thiet_bi_nha.thiet_bi_hoc())
    if not duoc_hoc:
        logger.info({"event": "du_doan_bo_luot",
                     "ly_do": "bot học hỏi chưa kết luận thiết bị nào được học"})
        return {}
    # Điều kiện nào đi với thiết bị nào cũng do bot học hỏi kết luận — chủ máy
    # 11/09/2026: "AI không phân tích trước khi học hỏi à, khu vực đang khác nhau".
    chon = hieu_thiet_bi_nha.dieu_kien_hoc()
    ngay = so_ngay if so_ngay else _so_ngay_hoc()
    den = time.time()
    tu = den - max(1, int(ngay)) * 86400
    try:
        sk = lich_su_nha.doc_trang_thai(tu, den, tien_to=tuple(sorted(duoc_hoc)),
                                        bo_do_ai=True)
        # Mẫu âm lấy từ MỌI ô có dữ liệu, kể cả ô chỉ có cảm biến — y như khi
        # còn đọc cả nhà. Chỉ lấy ô có thiết bị được học thì còn 192/535 ô (đo
        # 11/09/2026) và xác suất phồng lên. Ô nhà vắng hoàn toàn không nói lên
        # "chủ máy chọn không bật" nên vẫn không tính.
        o_moc = lich_su_nha.o_co_su_kien(tu, den, _O_PHUT * 60, bo_do_ai=True)
    except Exception as exc:
        logger.warning({"event": "du_doan_doc_loi", "error": str(exc)[:160]})
        return {}

    # Lượt BẬT của từng thiết bị, và thiết bị nào đổi trong từng ô.
    bat_luc: dict[str, list[float]] = {}
    doi_trong_o: dict[int, set[str]] = {}

    for r in sk:
        tb = str(r.get("thiet_bi") or "")
        # Tiền tố trong SQL là LIKE: `switch.bep_left` khớp cả `switch.bep_left_2`.
        if tb not in duoc_hoc or str(r.get("truong") or "") != "state":
            continue
        ts = float(r.get("ts") or 0)
        if _la_bat(r.get("gia_tri")):
            bat_luc.setdefault(tb, []).append(ts)
        doi_trong_o.setdefault(int(ts // (_O_PHUT * 60)), set()).add(tb)

    if not bat_luc:
        return {}

    o_ds = sorted(o_moc)

    # DỰNG BỐI CẢNH MỘT LẦN CHO MỖI Ô, rồi mọi thiết bị dùng chung.
    #
    # Bản đầu gọi `_dieu_kien()` NGAY TRONG vòng lặp thiết bị, nên cùng một ô
    # thời gian bị dựng lại một lần cho mỗi thiết bị. Đo trên máy chủ thật
    # 11/09/2026: `boi_canh()` mất 26ms mỗi lần (nó chạy vài truy vấn SQLite),
    # 30 ngày có 1.440 ô, nhà có 414 thiết bị từng đổi trạng thái:
    #
    #     414 thiết bị × 1.440 ô × 26ms  ≈  262 PHÚT cho một lượt `hoc()`
    #
    # Mà `hoc()` gọi từ heartbeat. Đó gần như chắc chắn là thủ phạm làm c2a
    # treo hẳn đêm 11/09 (uvicorn `R (running)`, CPU cao, mọi endpoint trả 000).
    #
    # Bối cảnh của một ô KHÔNG phụ thuộc thiết bị đang xét — `tru=tb` chỉ bỏ
    # nhãn `bat_<tên>` của chính nó, mà nhãn đó thêm ở vòng dưới. Nên tách ra
    # được, và chi phí còn 1.440 lần thay vì 596.160 lần: **nhanh gấp 414**.
    nhan_o: dict[int, dict[str, str]] = {
        o: _dieu_kien(o_moc[o], {}, {}) for o in o_ds
    }

    # Ô từ mốc này trở đi là NGÀY THỬ của phép kiểm tiến dần (`_KIEM_NGAY`).
    o_thu = int((den - _KIEM_NGAY * 86400) // (_O_PHUT * 60))

    ra: dict[str, Any] = {}
    for tb, moc in bat_luc.items():
        o_bat = {int(t // (_O_PHUT * 60)) for t in moc}
        # Đếm Ô, không đếm SỰ KIỆN. Đo 11/09/2026: cảm biến phòng khách có 10
        # lần "bật" nhập từ lịch sử HA mà chỉ nằm trong 2 ô 30 phút — đếm sự
        # kiện thì nó qua ngưỡng, trong khi 2 mẫu dương thì không học được gì.
        if len(o_bat) < _TOI_THIEU_DIEU_KIEN:
            continue
        # CHỈ đếm điều kiện bot học hỏi chọn cho thiết bị này. Chưa có kết
        # luận điều kiện thì không đếm điều kiện nào: chỉ còn tỉ lệ nền, không
        # bao giờ đủ để mở miệng — thà im còn hơn lấy nhiệt độ phòng học làm
        # lý do bật dàn âm thanh phòng khách (11/09/2026).
        duoc = set(chon.get(tb) or ())
        dem: dict[str, dict[str, int]] = {}
        dem_truoc: dict[str, dict[str, int]] = {}
        n_bat = n_khong = nb_truoc = nk_truoc = 0
        thu: list[tuple[dict[str, str], bool]] = []
        for o in o_ds:
            co = o in o_bat
            nhan = {k: v for k, v in nhan_o[o].items() if k in duoc}
            # Thiết bị khác đổi trong ô này (mở rộng 1 và 2), nếu bot chọn nó.
            for khac in doi_trong_o.get(o, ()):
                if khac != tb and f"bat_{khac}" in duoc:
                    nhan[f"bat_{khac}"] = "co"
            if co:
                n_bat += 1
            else:
                n_khong += 1
            for k, v in nhan.items():
                d = dem.setdefault(f"{k}={v}", {"bat": 0, "khong": 0})
                d["bat" if co else "khong"] += 1
            if o >= o_thu:
                thu.append((nhan, co))
                continue
            if co:
                nb_truoc += 1
            else:
                nk_truoc += 1
            for k, v in nhan.items():
                d = dem_truoc.setdefault(f"{k}={v}", {"bat": 0, "khong": 0})
                d["bat" if co else "khong"] += 1
        # Sống lại những ngày thử bằng bảng đếm của những ngày TRƯỚC chúng.
        bang_truoc = {"n_bat": nb_truoc, "n_khong": nk_truoc, "dk": dem_truoc}
        doan = trung = 0
        for nhan, co in thu:
            if _xac_suat(bang_truoc, nhan)[0] >= _P_GOI_Y:
                doan += 1
                trung += int(co)
        ra[tb] = {"n_bat": n_bat, "n_khong": n_khong, "dk": dem,
                  "dieu_kien": sorted(duoc),
                  "kiem": {"doan": doan, "trung": trung, "ngay": _KIEM_NGAY}}
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
    """Naive Bayes: nền + tổng bằng chứng. Trả (xác suất, danh sách bằng chứng).

    CHƯA TỪNG ĐI CÙNG LẦN BẬT THÌ KHÔNG PHẢI BẰNG CHỨNG BẬT. Bản trước làm mượt
    Laplace ``(k+1)/(n+2)`` cho cả hai phía. Thiết bị ít bật thì phía "bật" chỉ
    có vài mẫu, và số 1 cộng thêm lấn át hết: đo 11/09/2026, cảm biến phòng
    khách "bật" ở 2/556 ô; điều kiện "độ ẩm ban công đang ẩm" gặp 6 ô, CẢ SÁU ô
    đều không bật, vậy mà phía bật thành (0+1)/(2+2) = 1/4 so với 7/556 phía
    không bật — trọng số +2,99. Cộng 21 điều kiện như thế là "em chắc 100%",
    gửi chủ máy bốn giờ liền.

    Nay kéo cả hai phía về TẦN SUẤT CHUNG q của chính điều kiện (m-estimate,
    ``(k + m·q)/(n + m)``): điều kiện không nói gì về chuyện bật thì hai phía
    cùng ≈ q và trọng số ≈ 0; chưa từng đi cùng lần bật thì trọng số âm. Bằng
    chứng DƯƠNG còn phải có ít nhất `_TOI_THIEU_DIEU_KIEN` ô bật đi cùng — một
    hai lần trùng hợp không phải bằng chứng.
    """
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
        q = (d["bat"] + d["khong"]) / (n_bat + n_khong)
        p_co = (d["bat"] + _M_LAM_MUOT * q) / (n_bat + _M_LAM_MUOT)
        p_khong = (d["khong"] + _M_LAM_MUOT * q) / (n_khong + _M_LAM_MUOT)
        w = math.log(p_co / p_khong)
        if w > 0 and d["bat"] < _TOI_THIEU_DIEU_KIEN:
            continue
        logit += w
        bang_chung.append({"dieu_kien": f"{k}={v}", "trong_so": round(w, 3),
                           "khi_bat": d["bat"], "khi_khong": d["khong"]})

    bang_chung.sort(key=lambda x: -abs(x["trong_so"]))
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, logit)))), bang_chung


def du_doan(ten: str, luc: float | None = None,
            bang: dict[str, Any] | None = None, *,
            vua_doi: set[str] | frozenset[str] = frozenset()) -> dict[str, Any]:
    """Bây giờ có nên bật `ten` không, và VÌ SAO.

    Trả ``{"ten", "p", "cap", "cach", "bang_chung", "nhan", "kiem", "dat_cong",
    "ly_do"}``. ``cach`` là ``"im"`` | ``"goi_y"`` | ``"tu_lam"``.

    ``vua_doi`` — thiết bị được học vừa đổi trạng thái trong ô 30 phút này, đúng
    nghĩa nhãn ``bat_<tên>`` lúc học (`hoc`). Không truyền thì nhãn thiết bị
    không bao giờ có mặt lúc đoán, dù bot đã chọn nó làm điều kiện.

    Qua ngưỡng xác suất mà chưa qua KIỂM TIẾN DẦN (`_KIEM_NGAY`) thì vẫn im:
    xác suất cao trên chính dữ liệu đã học chưa chứng minh được gì — gợi ý
    "chắc 100%" ngày 11/09/2026 cũng cao như thế.
    """
    t = float(luc) if luc else time.time()
    b = bang if bang is not None else hoc().get(ten, {})
    if not b:
        return {"ten": ten, "p": 0.0, "cap": 0, "cach": "im",
                "bang_chung": [], "nhan": {}, "ly_do": "chưa đủ dữ liệu"}

    from services import boi_canh_nha
    nhan = boi_canh_nha.roi_rac(boi_canh_nha.hien_tai() if not luc
                                else boi_canh_nha.boi_canh(t))
    for khac in vua_doi:
        if khac != ten:
            nhan[f"bat_{khac}"] = "co"
    p, bc = _xac_suat(b, nhan)
    c = cap(ten)
    kiem = b.get("kiem") or {}
    doan, trung = int(kiem.get("doan") or 0), int(kiem.get("trung") or 0)
    dat = doan >= _KIEM_TOI_THIEU and trung >= _KIEM_TY_LE * doan
    ly_do = ""
    if p < _P_GOI_Y:
        cach = "im"
    elif not dat:
        cach = "im"
        ly_do = (f"chưa qua kiểm tiến dần: {kiem.get('ngay', _KIEM_NGAY)} ngày thử "
                 f"đoán {doan} lần, trúng {trung}")
    elif c >= 2:
        cach = "tu_lam"
    else:
        cach = "goi_y"
    return {"ten": ten, "p": round(p, 4), "cap": c, "cach": cach,
            "bang_chung": bc[:6], "nhan": nhan, "kiem": kiem, "dat_cong": dat,
            "ly_do": ly_do}


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
        # Quá hạn ('lo') mà chủ máy vẫn chấm thì nhận: trả lời muộn vẫn là trả
        # lời. Đã chấm (dung/sai) thì thôi — chấm lại là cộng dồn thành tích.
        muon = r is not None and r["ket_qua"] == "lo" and ket_qua in ("dung", "sai")
        if not r or (r["ket_qua"] != _TRANG_THAI_CHO and not muon):
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


def cho_cham(toi_da: int = 50) -> list[dict[str, Any]]:
    """Gợi ý ĐÃ GỬI, còn chờ chấm ('cho') — cho tab Học hỏi. Khác `quet()`: đây là
    hàng thật đã có id, chấm/xoá được; `quet()` chỉ là bản xem trước, chưa ghi."""
    with _khoa:
        rows = _db().execute(
            "SELECT id, ts, ten, hanh_dong, p FROM du_doan"
            " WHERE ket_qua='cho' ORDER BY ts DESC LIMIT ?",
            (int(toi_da),)).fetchall()
    return [{"id": int(r["id"]), "ts": float(r["ts"]), "ten": r["ten"],
             "hanh_dong": r["hanh_dong"], "p": float(r["p"])} for r in rows]


def xoa(id_: int) -> bool:
    """Chủ máy xoá một dòng gợi ý khỏi sổ (tab Học hỏi). Trả False nếu không có.

    Xoá KHÔNG chạm bảng `thanh_tich`: một lần đã chấm rồi đóng góp vào thang tin
    cậy, xoá dòng gợi ý không nên viết lại lịch sử chấm."""
    with _khoa:
        conn = _db()
        conn.execute("DELETE FROM du_doan WHERE id=?", (int(id_),))
        n = conn.total_changes
        conn.commit()
    if n:
        logger.info({"event": "du_doan_xoa", "id": int(id_)})
    return n > 0


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

    Thiết bị ĐANG BẬT thì không mời bật: 11/09/2026 bình nóng lạnh đang `on`
    mà chủ máy vẫn nhận "anh có muốn em bật không".
    """
    # Không hỏi được HA cái gì bật được thì cũng không bật được gì — im là
    # đúng, và khỏi tốn một lượt `hoc()`.
    if not mien_bat_duoc():
        return []
    # Không lọc lại theo miền ở đây: `hoc()` chỉ học thứ bot học hỏi đã kết
    # luận là bật được (`hieu_thiet_bi_nha._kiem` loại mọi `ma_hoc` không có
    # lệnh bật). Hai nơi giữ cùng một luật thì sớm muộn sẽ lệch nhau.
    bang = hoc()
    if not bang:
        return []
    from services import ha_client, lich_su_nha

    dang = {str(s.get("entity_id") or ""): s.get("state")
            for s in (ha_client.get_states() or [])}
    t = float(luc) if luc else time.time()
    o_giay = _O_PHUT * 60
    try:
        vua_doi = {str(r.get("thiet_bi") or "") for r in lich_su_nha.doc_trang_thai(
            t // o_giay * o_giay, t, tien_to=tuple(sorted(bang)), bo_do_ai=True)
            if str(r.get("truong") or "") == "state"} & set(bang)
    except Exception as exc:
        logger.warning({"event": "du_doan_doc_loi", "error": str(exc)[:160]})
        vua_doi = set()
    ra = []
    for ten, b in bang.items():
        if _la_bat(dang.get(ten)):
            continue
        d = du_doan(ten, luc, bang=b, vua_doi=vua_doi)
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

    VIẾT BẰNG TIẾNG NGƯỜI. Bản cũ in thẳng khoá máy, nên chủ máy nhận được
    "binary_sensor.ariston_is_heating … vì nhiet_do_khac nong" rồi trả lời
    "lỗi font chữ rồi nói tôi chả hiểu gì" (11/09/2026). Mã thực thể và nhãn
    điều kiện chỉ để mô hình ĐẾM cho khớp; ra tới tin nhắn thì phải là tên
    chủ máy đặt trong Home Assistant (`ten_thiet_bi`) và câu chữ tiếng Việt
    (`_ly_do`).

    Còn một lý do nữa phải bỏ mã máy: Zalo gửi tin ở `parse_mode=markdown`,
    mà markdown ăn dấu gạch dưới làm ký hiệu in nghiêng. `lux_phòng_khách`
    tới tay chủ máy thành `luxphòngkhách`.
    """
    if not ds:
        return ""
    dong = ["🏠 Em để ý nếp nhà, thấy mấy việc này:"]
    so_hoi: list[int] = []
    for d in ds:
        # Lý do là bằng chứng NGHIÊNG VỀ BẬT. Xếp theo độ lớn thì một điều kiện
        # đang kéo xác suất xuống cũng lọt vào sau chữ "vì".
        ung_ho = [b for b in (d.get("bang_chung") or [])
                  if float(b.get("trong_so") or 0) > 0]
        vi_sao = ", ".join(x for x in (
            _ly_do(str(b.get("dieu_kien") or "")) for b in ung_ho[:3]) if x)
        lam = "em bật rồi" if d["cach"] == "tu_lam" else "giờ này nhà hay bật"
        so = f"#{d['id']} " if d.get("id") else ""
        if d.get("id"):
            so_hoi.append(int(d["id"]))
        dong.append(f"• {so}{ten_thiet_bi(str(d['ten']))} — {lam} "
                    f"(em chắc {d['p'] * 100:.0f}%"
                    + (f", vì {vi_sao}" if vi_sao else "") + ")")
    if so_hoi:
        dong += ["", f"Em đoán đúng nếp nhà thì anh gõ «gy {so_hoi[0]} đúng», sai thì "
                     f"«gy {so_hoi[0]} sai vì …» — lý do anh gõ em ghi thành dữ kiện để "
                     "học. Nhiều số cùng lúc: «gy "
                     + ", ".join(str(x) for x in so_hoi) + " đúng»."]
    return "\n".join(dong)


def _da_goi_y_buoi_nay(ten: str, luc: float) -> bool:
    """Buổi này đã gợi ý thiết bị này chưa.

    Đo 11/09/2026: cùng ba gợi ý gửi 15:33, 16:03, 17:03, 18:03 — không ai trả
    lời nên cứ mỗi giờ lại gửi. Người không trả lời là quyết định của người;
    nhắc lại mỗi giờ là làm phiền. Mỗi thiết bị tối đa một lần mỗi buổi.
    """
    from services.boi_canh_nha import ten_buoi

    with _khoa:
        r = _db().execute(
            "SELECT ts FROM du_doan WHERE ten=? AND ts>? ORDER BY ts DESC LIMIT 1",
            (ten, luc - 12 * 3600)).fetchone()
    if not r:
        return False
    truoc = datetime.fromtimestamp(float(r["ts"]), _TZ).hour
    return ten_buoi(truoc) == ten_buoi(datetime.fromtimestamp(luc, _TZ).hour)


def tra_loi(text: str, *, nguoi: str = "") -> Optional[str]:
    """Câu chấm gợi ý trong nhóm học hỏi: «gy 13 đúng», «gy 13, 14 sai vì …».

    Trả câu đáp; None = không phải câu chấm. Tiền tố `gy` do CHÍNH bot in ra
    trong tin gợi ý (`soan_tin`), cùng khuôn với «hh» của tầng hiểu thiết bị.

    Trước 11/09/2026 tin gợi ý hỏi "anh có muốn em bật không" mà chỉ chấm được
    trên web: 9 gợi ý quá hạn không ai chấm, bot không học được gì từ chủ máy.
    Trả lời muộn — gợi ý đã quá hạn thành 'lo' — vẫn là câu trả lời, vẫn nhận.
    Lý do kèm theo ghi vào sổ dữ kiện để bot học hỏi dùng ở lượt giải sau.
    """
    from services import hieu_thiet_bi_nha

    cau = hieu_thiet_bi_nha.doc_cau_cham(text, "gy")
    if cau is None:
        return None
    if not cau:
        return "Anh gõ giúp em: «gy <số> đúng» hoặc «gy <số> sai vì …»."
    so, dung, con = cau["so"], cau["dung"], cau["con"]
    duoc = [x for x in so if _cham(x, "dung" if dung else "sai")]
    khong = [x for x in so if x not in duoc]
    id_dk = hieu_thiet_bi_nha.ghi_du_kien(con, nguoi=nguoi, nguon="gy") if con else 0
    dong = []
    if duoc:
        dong.append(f"Em ghi rồi: gợi ý {', '.join(f'#{x}' for x in duoc)} "
                    f"{'đúng' if dung else 'sai'}.")
    if id_dk:
        dong.append(f"Phần anh dặn thêm em ghi thành dữ kiện #{id_dk} để học.")
    if khong:
        dong.append(f"Không có gợi ý nào số {', '.join(f'#{x}' for x in khong)} "
                    "đang chờ chấm.")
    return " ".join(dong)


def chay_mot_lan(toi_da: int = 1) -> dict[str, Any]:
    """Heartbeat gọi. Dọn quá hạn, tự chấm, rồi BÁO việc đáng nói.

    MỖI LƯỢT MỘT GỢI Ý, và gợi ý trước còn chờ chấm thì im. Chủ máy chốt
    11/09/2026: "tin gửi để tôi xác minh đang dài quá. Tôi muốn nó xác minh lần
    lượt, khi tôi phản hồi xong thì mới gửi xác minh tiếp".
    """
    if not is_enabled():
        return {"bo_qua": "đang tắt"}
    lo = don_qua_han()
    huy = soi_bi_huy()
    with _khoa:
        dang_cho = _db().execute("SELECT COUNT(*) FROM du_doan WHERE ket_qua=?",
                                 (_TRANG_THAI_CHO,)).fetchone()[0]
    if dang_cho:
        return {"lo": lo, "tu_cham_sai": huy, "gui": 0,
                "ly_do": "gợi ý trước còn chờ chủ máy chấm"}
    now = time.time()
    ds = [d for d in quet() if not _da_goi_y_buoi_nay(str(d["ten"]), now)]
    ds = ds[:max(1, int(toi_da))]
    if not ds:
        return {"lo": lo, "tu_cham_sai": huy, "gui": 0,
                "ly_do": "chưa có gì đáng nói"}

    # Ghi TRƯỚC để tin mang số «gy N» cho chủ máy chấm ngay trong Zalo. Gửi
    # không tới thì XOÁ ở dưới — chấm cái chủ máy chưa thấy là hỏng thành tích.
    for d in ds:
        d["id"] = ghi_nhan(str(d["ten"]), "on", float(d["p"]),
                           d.get("nhan") or {}, str(d["cach"]))
    tin = soan_tin(ds)
    # MỘT đường duy nhất: sổ đăng ký `services/thong_bao.py`. Nhánh dự phòng
    # rơi về admin đã bỏ theo yêu cầu 13/09/2026 (không mặc định).
    from services import thong_bao

    gui = thong_bao.gui("nha.goi_y", tin)

    if not gui:
        with _khoa:
            conn = _db()
            conn.executemany("DELETE FROM du_doan WHERE id=?",
                             [(int(d["id"]),) for d in ds])
            conn.commit()
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
        # Cho tab Học hỏi hiện "đang theo dõi", không phải nhãn tĩnh "đã tin"
        # đọc như đóng băng mãi mãi — sai 2/10 lượt gần nhất là tụt về hỏi lại.
        x["sai_gan_day"] = sai_gan_day(str(x["ten"]))
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
