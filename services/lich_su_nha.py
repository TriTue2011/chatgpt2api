"""Lịch sử nhà — c2a tự ghi, KHÔNG phụ thuộc Home Assistant.

Vì sao có file này: quản gia tự học cần dữ liệu quá khứ để biết nếp nhà. HA
mặc định chỉ giữ 10 ngày (đo trên HA thật của chủ máy 09/09/2026: lùi 10 ngày
còn dữ liệu, lùi 14 ngày sạch trơn), và tắt HA là mất hết. Chủ máy chốt: *"tôi
muốn là c2a lưu riêng để dùng sau này chứ không phải trên ha"*.

BA BẢNG, ba nhịp khác nhau — không nhập một bảng được:

``su_kien``  Trạng thái ĐỔI (đèn bật/tắt, có người, mở cửa). Giữ 90 ngày.
             Đây là thứ quản gia học.
``so_do``    Số đo liên tục (lux, nhiệt độ, sóng), GỘP 5 phút. Giữ 1 năm.
             Không gộp thì ``linkquality`` một mình đổi 94 lần/phút (đo trên
             EMQX thật) → 90 ngày thành 67 triệu bản ghi, không dùng được.
``tuoi``     Giá trị MỚI NHẤT mọi trường, mỗi trường đúng một hàng. Có bảng này
             vì chủ máy yêu cầu *"khi hỏi phải lấy theo thời gian thực"*: số đo
             đã gộp 5 phút chỉ hợp vẽ biểu đồ, còn hỏi "phòng khách bao nhiêu
             lux" thì phải là số của giây vừa rồi.

CỘT ``do_ai`` LÀ CỐT LÕI, đừng bỏ khi thấy nó luôn bằng 0 lúc đầu. Không có nó
thì giai đoạn sau bot học từ chính hành động của mình rồi tự khẳng định vòng
quanh, và KHÔNG CÁCH NÀO đo được "bot đoán đúng bao nhiêu lần" để biết khi nào
đủ tin mà tự làm.

Đo thật trên nhà chủ máy (09/09/2026): mô hình đoán đèn phòng khách chỉ đúng
58,3% theo kiểm tiến dần, so với đoán bừa 50%. Nên tầng này CHỈ GHI, không
quyết định gì — quyết định để giai đoạn sau, khi đã đủ dữ liệu mà cân.
"""

from __future__ import annotations

import json
import logging
import queue
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR, config

logger = logging.getLogger(__name__)

_TZ = timezone(timedelta(hours=7))  # giờ VN — 168 ô thời gian phải theo giờ nhà
_DB_PATH = Path(DATA_DIR) / "agent" / "lich_su_nha.sqlite"

_conn: Optional[sqlite3.Connection] = None
_khoa_db = threading.Lock()

# Ghi qua hàng đợi + luồng nền: gương MQTT gọi ``ghi()`` trong callback của
# paho, chặn ở đó là chặn cả gương. Khuôn theo memory_service.store_async,
# nhưng dùng MỘT luồng + hàng đợi thay vì một luồng mỗi lần ghi — ở đây tần
# suất cao gấp bội (hàng trăm tin/phút), đẻ luồng mỗi tin là sập.
_hang: "queue.Queue[tuple | None]" = queue.Queue(maxsize=10000)
_thread: Optional[threading.Thread] = None
_started_lock = threading.Lock()
_stop = threading.Event()

_stats: dict[str, Any] = {
    "ghi": 0,        # số bản ghi đã nhận
    "bo": 0,         # bỏ vì hàng đợi đầy
    "loi": 0,        # lỗi khi ghi xuống đĩa
    "don_cuoi": 0.0,
    "cham_tran": 0,  # số lần một hàm đọc bị trần cắt — xem `_cat_tran`
}

_GOP_GIAY_MAC_DINH = 300  # 5 phút
_DON_MOI_GIAY = 6 * 3600

# ── Phân loại trường ────────────────────────────────────────────────────────
# Trạng thái RỜI RẠC → su_kien. Đây là thứ nói lên nếp sinh hoạt.
#: Trường mà MỖI LẦN XẢY RA là một sự kiện riêng, kể cả trùng giá trị liền
#: nhau. "Vân tay 11 mở cửa" hai lần trong ngày là HAI lần về, không phải một
#: — luật "chỉ ghi khi đổi" nuốt mất lần thứ hai. Đo thật 09/09/2026: 48 lần
#: mở cửa nạp vào chỉ còn 35, mất 13 lần.
TRUONG_LAP_LAI = frozenset({
    "action", "nguoi_mo", "unlock", "doorbell", "chuong", "su_kien",
    "scene", "event",
    # Thuộc tính của thực thể `event.` trong Home Assistant: mỗi lần xảy ra là
    # một sự kiện riêng, kể cả trùng giá trị. Vợ chủ nhà ra rồi vào lại thì
    # `value` vẫn là 17 cả hai lần — thiếu hai trường này là nuốt mất lần thứ
    # hai, đúng kiểu 48 lần mở cửa nạp vào còn 35 (đo 09/09/2026).
    "event_type", "value",
})

TRUONG_SU_KIEN = frozenset({
    "state", "state_l1", "state_l2", "state_l3",
    "state_left", "state_center", "state_right",
    "presence", "occupancy", "contact", "smoke", "action",
    "water_leak", "battery_low", "tamper", "vibration", "gas",
    "motion", "door", "lock", "alarm",
})

# Số ĐO LIÊN TỤC → so_do (gộp 5 phút).
# linkquality / distance / uptime GIỮ LẠI dù không nói lên thói quen: chủ máy
# đã bác đề nghị bỏ của tôi, đúng — chúng là đầu vào để hệ tự chỉnh chính nó
# (sóng yếu thì lệnh có thể trượt; distance phân biệt đứng với ngồi).
TRUONG_SO_DO = frozenset({
    "illuminance", "illuminance_lux", "temperature", "humidity",
    "linkquality", "distance", "target_distance", "power", "current",
    "voltage", "energy", "battery", "pressure", "co2", "pm25", "pm10",
    "uptime", "rssi", "signal_strength", "brightness", "color_temp",
})

# Không ghi: tự khai báo, trạng thái hạ tầng, thứ đổi liên tục mà vô nghĩa.
BO_HAN = (
    "zigbee2mqtt/bridge/", "homeassistant/", "frigate/stats",
    "frigate/available", "/status/", "/availability",
)
BO_TRUONG = frozenset({"last_seen", "update", "update_available", "elapsed"})

# Không bao giờ ghi bí mật xuống đĩa. Lịch sử giữ 90 ngày và có API đọc ra, nên
# một mật khẩu lọt vào là nằm đó rất lâu. Thiết bị ESP tự chế hay phát cả cấu
# hình (kèm mật khẩu WiFi/MQTT) lên chủ đề trạng thái của chính nó.
TRUONG_BI_MAT = ("password", "passwd", "pass", "secret", "token", "api_key",
                 "apikey", "psk", "credential", "auth", "private_key")


def _cfg() -> dict[str, Any]:
    raw = (config.data.get("mqtt") or {}).get("lich_su")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("bat", True))


def _giu_su_kien_ngay() -> int:
    try:
        return max(1, int(_cfg().get("giu_su_kien_ngay") or 90))
    except (TypeError, ValueError):
        return 90


def _giu_so_do_ngay() -> int:
    try:
        return max(1, int(_cfg().get("giu_so_do_ngay") or 365))
    except (TypeError, ValueError):
        return 365


def _o_gop_giay() -> int:
    try:
        return max(60, int(_cfg().get("o_gop_giay") or _GOP_GIAY_MAC_DINH))
    except (TypeError, ValueError):
        return _GOP_GIAY_MAC_DINH


def _bo_them() -> tuple[str, ...]:
    raw = _cfg().get("bo_them")
    return tuple(str(x) for x in raw) if isinstance(raw, list) else ()


# ── Cơ sở dữ liệu ───────────────────────────────────────────────────────────
def _db() -> sqlite3.Connection:
    """Khuôn theo reminders.py: WAL + CREATE IF NOT EXISTS + index tổ hợp."""
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        # timeout=10: luồng nền ghi lô 500 bản ghi trong khi API đọc thống kê
        # → không có timeout thì SQLite ném "database is locked" NGAY thay vì
        # chờ. Đã gặp thật lúc chạy test luồng nền.
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS su_kien ("
            " id INTEGER PRIMARY KEY,"
            " ts REAL NOT NULL,"
            " nguon TEXT NOT NULL,"          # mqtt | ha | ha_nhap | frigate
            " thiet_bi TEXT NOT NULL,"
            " truong TEXT NOT NULL,"
            " gia_tri TEXT NOT NULL,"
            " gia_tri_cu TEXT,"
            " do_ai INTEGER NOT NULL DEFAULT 0,"
            " gio INTEGER NOT NULL,"
            " thu INTEGER NOT NULL)"
        )
        # Chống ghi trùng khi nạp lại lịch sử HA (chạy hai lần không nhân đôi).
        # Khuôn theo memory_service: UNIQUE + INSERT OR IGNORE.
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sk_uniq "
            "ON su_kien(thiet_bi, truong, ts)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sk_tb_ts ON su_kien(thiet_bi, ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sk_ts ON su_kien(ts)")
        # 168 ô thời gian (7 ngày × 24 giờ) — truy vấn chính của phần học.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sk_o ON su_kien(thiet_bi, thu, gio)")

        conn.execute(
            "CREATE TABLE IF NOT EXISTS so_do ("
            " id INTEGER PRIMARY KEY,"
            " o_5p INTEGER NOT NULL,"
            " thiet_bi TEXT NOT NULL,"
            " truong TEXT NOT NULL,"
            " nho REAL, lon REAL, tb REAL,"
            " n INTEGER NOT NULL DEFAULT 0)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sd_o ON so_do(o_5p, thiet_bi, truong)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sd_ts ON so_do(o_5p)")

        conn.execute(
            "CREATE TABLE IF NOT EXISTS tuoi ("
            " thiet_bi TEXT NOT NULL,"
            " truong TEXT NOT NULL,"
            " gia_tri TEXT,"
            " ts REAL,"
            " PRIMARY KEY (thiet_bi, truong))"
        )

        # Bảng thứ tư: NHỊP ĐỔI của từng trường. Một dòng cho mỗi cặp
        # (thiết bị × trường) — vài nghìn dòng, không phải dữ liệu lịch sử.
        # Đây là thứ cho phép phân loại trường bằng ĐO thay vì bằng TÊN, xem
        # `_phan_loai_theo_nhip`.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS nhip ("
            " thiet_bi TEXT NOT NULL,"
            " truong TEXT NOT NULL,"
            " n INTEGER NOT NULL DEFAULT 0,"        # số lần đã nhận
            " so_gt INTEGER NOT NULL DEFAULT 0,"    # số giá trị khác nhau đã thấy
            " gt_dau TEXT,"                         # giá trị đầu tiên
            " doi_lan INTEGER NOT NULL DEFAULT 0,"  # số lần khác giá trị trước
            " gt_cuoi TEXT,"
            " loai TEXT NOT NULL DEFAULT '?',"      # '?'|'su_kien'|'so_do'|'hang_so'
            " chot_luc REAL,"
            " PRIMARY KEY (thiet_bi, truong))"
        )
        conn.commit()
        _conn = conn
    return _conn


def _so(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v or v in (float("inf"), float("-inf")) else v


def _bo_qua(thiet_bi: str, truong: str) -> bool:
    if truong in BO_TRUONG:
        return True
    t = truong.lower()
    if any(k in t for k in TRUONG_BI_MAT):
        return True
    khoa = f"{thiet_bi}/{truong}"
    for m in BO_HAN + _bo_them():
        if m and (m in khoa or thiet_bi.startswith(m)):
            return True
    return False


def _loai_truong(truong: str, gia_tri: Any) -> str:
    """'su_kien' | 'so_do' — phỏng đoán ban đầu, dùng khi chưa đủ mẫu.

    Trường lạ KHÔNG bị bỏ — bỏ là mất vĩnh viễn, không lấy lại được. Là số thì
    coi như số đo, còn lại coi như sự kiện.

    Hai danh sách tên dưới đây nay chỉ là MỒI cho nhanh, không còn quyền từ
    chối: `_phan_loai_theo_nhip` mới là nơi quyết định, và nó ĐO.
    """
    t = truong.lower()
    if t in TRUONG_SU_KIEN:
        return "su_kien"
    if t in TRUONG_SO_DO:
        return "so_do"
    if isinstance(gia_tri, bool):
        return "su_kien"
    return "so_do" if _so(gia_tri) is not None else "su_kien"


#: Ghi ngần này lần mà giá trị CHƯA ĐỔI BAO GIỜ → đó là hằng số cấu hình.
_NGUONG_HANG = 30
#: Thấy ngần này giá trị số khác nhau → đó là số đo liên tục, không phải cờ.
_NGUONG_LIEN_TUC = 3


def _phan_loai_theo_nhip(conn: sqlite3.Connection, thiet_bi: str, truong: str,
                         gia_tri: Any) -> str:
    """'su_kien' | 'so_do' | 'hang_so' — quyết định bằng ĐO, không bằng TÊN.

    Vì sao không dùng danh sách từ khoá: trước 10/09/2026 có HAI danh sách
    lệch nhau. Đường Home Assistant (`ha_live._GHI_SENSOR`) chỉ cho qua bốn từ
    "occupancy/presence/person/motion" nên chặn mất nhiệt độ, độ ẩm và lux —
    đúng những điều kiện chủ máy cần để học thói quen; đo thật: tra ngược 400
    lần bật đèn bếp xem lúc đó bao nhiêu lux thì được 0/400. Đường MQTT thì
    ngược lại, không lọc gì, nên `so_do` đầy `over_voltage_threshold`,
    `meter_id`, `linkquality` — mỗi thứ 193 bản ghi mỗi ngày mà không bao giờ
    đổi giá trị.

    Danh sách nào cũng thiếu, vì tên không nói lên bản chất. Nhưng CÁCH MỘT
    TRƯỜNG ĐỔI thì nói:

    * đã nhận ``_NGUONG_HANG`` lần mà chưa đổi lần nào → hằng số cấu hình.
      `over_voltage_threshold` tự lộ diện, không cần ai biết tên nó.
    * là số và đã thấy ``_NGUONG_LIEN_TUC`` giá trị khác nhau → số đo liên tục.
    * còn lại → trạng thái rời rạc.

    Chỉ chỗ này thấy được lịch sử của trường, nên chỉ chỗ này phân loại được.
    Hai đường ghi kia chỉ đưa dữ liệu vào, không có quyền từ chối.

    TRONG ``_NGUONG_HANG`` LẦN ĐẦU thì KHÔNG kết luận, cứ ghi theo phỏng đoán
    kiểu dữ liệu. Ghi thừa 30 bản ghi rồi dọn còn hơn bỏ sót vĩnh viễn — cùng
    nguyên tắc "trường lạ không bị bỏ" của `_loai_truong`.

    Hằng số ĐỔI được thì mở khoá đếm lại: chủ máy sửa ngưỡng trong app Tuya là
    chuyện thật, chốt cứng một lần là mất luôn trường đó.
    """
    gt = str(gia_tri)
    r = conn.execute(
        "SELECT n, so_gt, doi_lan, gt_cuoi, loai FROM nhip"
        " WHERE thiet_bi=? AND truong=?", (thiet_bi, truong)).fetchone()

    if r is None:
        conn.execute(
            "INSERT OR IGNORE INTO nhip (thiet_bi, truong, n, so_gt, gt_dau,"
            " doi_lan, gt_cuoi, loai) VALUES (?,?,1,1,?,0,?,'?')",
            (thiet_bi, truong, gt, gt))
        return _loai_truong(truong, gia_tri)

    n = int(r["n"]) + 1
    doi = int(r["doi_lan"]) + (1 if r["gt_cuoi"] != gt else 0)
    so_gt = int(r["so_gt"]) + (1 if r["gt_cuoi"] != gt else 0)
    loai = str(r["loai"] or "?")

    # Đã chốt hằng số mà nay đổi → sai, mở khoá đếm lại từ đầu.
    if loai == "hang_so" and r["gt_cuoi"] != gt:
        loai, n, doi, so_gt = "?", 1, 1, 2

    if loai == "?":
        if doi == 0 and n >= _NGUONG_HANG:
            loai = "hang_so"
        elif truong.lower() in TRUONG_LAP_LAI:
            # Mỗi lần xảy ra là một sự kiện riêng dù giá trị trùng: "khuôn mặt
            # số 17 mở cửa" hai lần là hai lần về. Không có ngoại lệ này thì
            # `value` bị chốt hằng số và bot mất sạch lần mở cửa thứ hai.
            loai = "su_kien"
        elif _so(gia_tri) is not None and not isinstance(gia_tri, bool):
            if so_gt >= _NGUONG_LIEN_TUC:
                loai = "so_do"
            elif doi >= 1 and n >= _NGUONG_HANG:
                # Số nhưng chỉ nhận hai giá trị sau 30 lần: đó là CỜ đội lốt
                # số (0/1, 100/0), không phải số đo. Trung bình của cờ vô
                # nghĩa; nó thuộc về `su_kien`.
                loai = "su_kien"
        elif doi >= 1:
            # Đổi giá trị mà không phải số → trạng thái rời rạc. Chốt NGAY,
            # đừng đợi đủ 30 lần: `on`/`off` không bao giờ thành hằng số cũng
            # không bao giờ thành số đo, để `'?'` là mỗi bản ghi tra lại bảng
            # `nhip` một lần vô ích.
            loai = "su_kien"

    conn.execute(
        "UPDATE nhip SET n=?, so_gt=?, doi_lan=?, gt_cuoi=?, loai=?,"
        " chot_luc=? WHERE thiet_bi=? AND truong=?",
        (n, so_gt, doi, gt, loai,
         time.time() if loai != "?" else None, thiet_bi, truong))

    return loai if loai != "?" else _loai_truong(truong, gia_tri)


# ── Ghi ─────────────────────────────────────────────────────────────────────
def ghi(nguon: str, thiet_bi: str, truong: str, gia_tri: Any,
        *, do_ai: bool = False, ts: float | None = None) -> None:
    """Xếp một bản ghi vào hàng đợi.

    KHÔNG BAO GIỜ raise, KHÔNG BAO GIỜ chặn. Gọi từ callback của paho — ghi
    hỏng thì mất bản ghi đó, tuyệt đối không được làm chết gương MQTT.
    """
    try:
        if not is_enabled():
            return
        thiet_bi = (thiet_bi or "").strip()
        truong = (truong or "").strip()
        if not thiet_bi or not truong or gia_tri is None:
            return
        if _bo_qua(thiet_bi, truong):
            return
        _hang.put_nowait((nguon, thiet_bi, truong, gia_tri, bool(do_ai),
                          float(ts) if ts else time.time()))
        _stats["ghi"] += 1
    except queue.Full:
        _stats["bo"] += 1
    except Exception:
        _stats["bo"] += 1


def _ghi_thang(conn: sqlite3.Connection, nguon: str, thiet_bi: str, truong: str,
               gia_tri: Any, do_ai: bool, ts: float) -> None:
    """Ghi thật xuống đĩa. Chỉ luồng nền (và nap_tu_ha) gọi."""
    if _bo_qua(thiet_bi, truong):
        return
    gt = str(gia_tri)
    loai = _phan_loai_theo_nhip(conn, thiet_bi, truong, gia_tri)

    # Hằng số cấu hình: vẫn cập nhật `tuoi` ở cuối hàm (hỏi ra vẫn trả lời
    # được) nhưng không tốn một dòng lịch sử nào. Đây là chỗ `meter_id` và
    # `over_voltage_threshold` ngừng chiếm chỗ của lux với nhiệt độ.
    if loai == "hang_so":
        loai = ""

    if loai == "so_do":
        v = _so(gia_tri)
        if v is None:
            loai = "su_kien"
        else:
            o = int(ts // _o_gop_giay())
            # Gộp tại chỗ: đã có ô thì nới min/max, cộng dồn trung bình.
            cu = conn.execute(
                "SELECT nho, lon, tb, n FROM so_do WHERE o_5p=? AND thiet_bi=? AND truong=?",
                (o, thiet_bi, truong),
            ).fetchone()
            if cu is None:
                conn.execute(
                    "INSERT OR IGNORE INTO so_do (o_5p, thiet_bi, truong, nho, lon, tb, n)"
                    " VALUES (?,?,?,?,?,?,1)",
                    (o, thiet_bi, truong, v, v, v),
                )
            else:
                n = int(cu["n"]) + 1
                conn.execute(
                    "UPDATE so_do SET nho=?, lon=?, tb=?, n=?"
                    " WHERE o_5p=? AND thiet_bi=? AND truong=?",
                    (min(cu["nho"], v), max(cu["lon"], v),
                     (float(cu["tb"]) * int(cu["n"]) + v) / n, n,
                     o, thiet_bi, truong),
                )

    if loai == "su_kien":
        cu = conn.execute(
            "SELECT gia_tri FROM tuoi WHERE thiet_bi=? AND truong=?",
            (thiet_bi, truong),
        ).fetchone()
        gia_tri_cu = cu["gia_tri"] if cu else None
        # CHỈ ghi khi ĐỔI — đây là chỗ 67 triệu bản ghi rút còn 1,7 triệu.
        # NGOẠI TRỪ trường lặp lại: mỗi lần xảy ra là một sự kiện riêng.
        lap_lai = truong.lower() in TRUONG_LAP_LAI
        if lap_lai or gia_tri_cu != gt:
            t = datetime.fromtimestamp(ts, _TZ)
            conn.execute(
                "INSERT OR IGNORE INTO su_kien"
                " (ts, nguon, thiet_bi, truong, gia_tri, gia_tri_cu, do_ai, gio, thu)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (ts, nguon, thiet_bi, truong, gt, gia_tri_cu,
                 1 if do_ai else 0, t.hour, t.weekday()),
            )

    conn.execute(
        "INSERT INTO tuoi (thiet_bi, truong, gia_tri, ts) VALUES (?,?,?,?)"
        " ON CONFLICT(thiet_bi, truong) DO UPDATE SET gia_tri=excluded.gia_tri, ts=excluded.ts",
        (thiet_bi, truong, gt, ts),
    )


def ghi_frigate(su_kien: dict[str, Any]) -> None:
    """Chỉ ghi lúc BẮT ĐẦU và KẾT THÚC — chủ máy chốt, bỏ 'update'.

    Frigate phát 208 tin/40 giây, phần lớn là 'update' của cùng một sự kiện.
    """
    try:
        if not isinstance(su_kien, dict):
            return
        loai = str(su_kien.get("type") or "")
        if loai not in ("new", "end"):
            return
        sau = su_kien.get("after") or su_kien.get("before") or {}
        if not isinstance(sau, dict):
            return
        cam = str(sau.get("camera") or "?")
        nhan = str(sau.get("label") or "?")
        ghi("frigate", f"frigate/{cam}", nhan,
            "bat_dau" if loai == "new" else "ket_thuc",
            ts=_so(sau.get("start_time" if loai == "new" else "end_time")) or None)
    except Exception:
        pass


# ── Luồng nền ───────────────────────────────────────────────────────────────
def _vong() -> None:
    don_cuoi = time.time()
    while not _stop.is_set():
        try:
            muc = _hang.get(timeout=1.0)
        except queue.Empty:
            muc = None
        else:
            if muc is None:
                break

        if muc is not None:
            lo = [muc]
            # Vét thêm cho một lần commit — ghi từng tin một là quá tốn.
            for _ in range(499):
                try:
                    m = _hang.get_nowait()
                except queue.Empty:
                    break
                if m is None:
                    _stop.set()
                    break
                lo.append(m)
            try:
                with _khoa_db:
                    conn = _db()
                    for nguon, tb, tr, gt, ai, ts in lo:
                        try:
                            _ghi_thang(conn, nguon, tb, tr, gt, ai, ts)
                        except Exception:
                            _stats["loi"] += 1
                    conn.commit()
            except Exception as exc:
                _stats["loi"] += len(lo)
                logger.warning({"event": "lich_su_ghi_loi", "error": str(exc)[:200]})

        if time.time() - don_cuoi >= _DON_MOI_GIAY:
            don_cuoi = time.time()
            try:
                don()
            except Exception as exc:
                logger.warning({"event": "lich_su_don_loi", "error": str(exc)[:200]})


def start() -> bool:
    """Khuôn theo tracked_topic.py: cờ module + Event + luồng daemon."""
    global _thread
    with _started_lock:
        if _thread is not None and _thread.is_alive():
            return True
        if not is_enabled():
            return False
        _stop.clear()
        _thread = threading.Thread(target=_vong, name="lich-su-nha", daemon=True)
        _thread.start()
        logger.info({"event": "lich_su_start"})
        return True


def stop() -> None:
    global _thread
    with _started_lock:
        _stop.set()
        try:
            _hang.put_nowait(None)
        except queue.Full:
            pass
        t = _thread
        _thread = None
    if t is not None and t.is_alive():
        t.join(timeout=5.0)


def stats() -> dict[str, Any]:
    return {**_stats, "hang_doi": _hang.qsize(),
            "chay": bool(_thread and _thread.is_alive())}


# ── Đọc ─────────────────────────────────────────────────────────────────────
#: Trần mặc định cho mọi hàm đọc theo khoảng thời gian. Rộng rãi: nó chỉ để
#: chặn việc vô tình kéo cả kho vào RAM, KHÔNG phải để lọc bớt dữ liệu.
_TRAN_MAC_DINH = 200_000


def _cat_tran(conn: sqlite3.Connection, sql: str, tham_so: tuple[Any, ...],
              tran: int, ten: str) -> list[dict[str, Any]]:
    """Chạy truy vấn có trần, luôn giữ phần MỚI NHẤT, và KÊU khi phải cắt.

    Hai luật ở đây chữa một lớp lỗi đã đo được 10/09/2026 chứ không phải
    phòng xa:

    1. ``ORDER BY ts DESC ... LIMIT n`` rồi đảo lại. Bản cũ dùng ``ASC`` nên
       trần cắt mất phần MỚI, giữ phần CŨ — trong khi mọi nơi gọi đều tưởng
       mình đang xin "dữ liệu gần đây". Đo thật: xin 14 ngày (593.395 sự
       kiện) chỉ nhận về 13,9 giờ của ngày đầu tiên, mất 96,6%. Bộ học tình
       huống vì thế học trên một buổi tối của 11 ngày trước, và bộ khoá cửa
       không hề thấy lần mở cửa nào của hôm nay.
    2. Chạm trần thì ghi log VÀ đếm vào ``_stats["cham_tran"]``. Lớp lỗi ở
       đây không phải "trần đặt thấp" — nâng trần lên một triệu vẫn sai nếu
       cắt nhầm đầu. Lớp lỗi là **vứt dữ liệu trong im lặng**. Nên luật
       chung cho cả ba hàm đọc là: được phép cắt, không được phép im.

    Trả về theo thứ tự ts TĂNG DẦN — nơi gọi duyệt tuần tự và gộp ô kề nhau
    (``tinh_huong_nha.gom_cua_so``), trả giảm dần là hỏng âm thầm.
    """
    rows = conn.execute(sql, tham_so).fetchall()
    ra = [dict(r) for r in reversed(rows)]
    if len(ra) >= tran:
        _stats["cham_tran"] = _stats.get("cham_tran", 0) + 1
        logger.warning({"event": "lich_su_cham_tran", "ham": ten,
                        "tran": tran, "cu_nhat_con_lai": ra[0].get("ts")})
    return ra


def doc_tuoi(thiet_bi: str | None = None) -> list[dict[str, Any]]:
    """Giá trị mới nhất — cho yêu cầu "hỏi phải lấy theo thời gian thực"."""
    with _khoa_db:
        conn = _db()
        if thiet_bi:
            rows = conn.execute(
                "SELECT thiet_bi, truong, gia_tri, ts FROM tuoi WHERE thiet_bi=?"
                " ORDER BY truong", (thiet_bi,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT thiet_bi, truong, gia_tri, ts FROM tuoi"
                " ORDER BY thiet_bi, truong").fetchall()
    return [dict(r) for r in rows]


def doc_su_kien(thiet_bi: str, tu_ts: float, den_ts: float,
                truong: str | None = None, *,
                tran: int = _TRAN_MAC_DINH) -> list[dict[str, Any]]:
    """Sự kiện của MỘT thiết bị trong khoảng. Trả về theo ts tăng dần.

    Trước 10/09/2026 hàm này KHÔNG có trần — rủi ro ngược với ``doc_cua_so``:
    ``thoi_quen_nha.hoc(so_ngay=60)`` có thể kéo cả kho vào RAM. Nay cùng một
    luật với hai hàm đọc kia (xem ``_cat_tran``).
    """
    with _khoa_db:
        conn = _db()
        if truong:
            return _cat_tran(
                conn,
                "SELECT * FROM su_kien WHERE thiet_bi=? AND truong=? AND ts>=? AND ts<=?"
                " ORDER BY ts DESC LIMIT ?",
                (thiet_bi, truong, tu_ts, den_ts, int(tran)), int(tran), "doc_su_kien")
        return _cat_tran(
            conn,
            "SELECT * FROM su_kien WHERE thiet_bi=? AND ts>=? AND ts<=?"
            " ORDER BY ts DESC LIMIT ?",
            (thiet_bi, tu_ts, den_ts, int(tran)), int(tran), "doc_su_kien")


def doc_cua_so(tu_ts: float, den_ts: float, *,
               tran: int = _TRAN_MAC_DINH,
               tien_to: tuple[str, ...] = (),
               truong: tuple[str, ...] = (),
               bo_do_ai: bool = False) -> list[dict[str, Any]]:
    """MỌI sự kiện trong một khoảng, không bắt buộc nêu thiết bị.

    ``doc_su_kien`` bắt buộc nêu tên thiết bị nên không trả lời được câu hỏi
    "lúc 19h30 trong nhà có những gì đang xảy ra" — mà đó chính là câu hỏi của
    phần nhận ra tình huống. Dùng ``idx_sk_ts`` đã có nên quét cả nhà vẫn nhanh.

    LỌC Ở SQL, ĐỪNG LỌC SAU. Ba tham số dưới đây tồn tại để nơi gọi không phải
    kéo cả nhà về rồi bỏ đi 99%: lọc trong SQL thì trần gần như không bao giờ
    chạm tới, mà chạm cũng còn đúng phần cần.

    * ``tien_to`` — chỉ lấy thiết bị bắt đầu bằng một trong các tiền tố này.
      ``khoa_cua_nha`` chỉ cần ``("event.",)`` là 7 ngày còn vài trăm dòng.
    * ``truong`` — chỉ lấy các trường nêu tên.
    * ``bo_do_ai`` — bỏ những việc do CHÍNH BOT làm. Bắt buộc bật khi lấy dữ
      liệu để học, nếu không bot học từ hành động của mình rồi tự khẳng định
      vòng quanh (xem phần ``do_ai`` ở đầu tệp).
    """
    dk = ["ts>=?", "ts<=?"]
    ts: list[Any] = [tu_ts, den_ts]
    if tien_to:
        dk.append("(" + " OR ".join("thiet_bi LIKE ?" for _ in tien_to) + ")")
        ts += [f"{x}%" for x in tien_to]
    if truong:
        dk.append("truong IN (" + ",".join("?" for _ in truong) + ")")
        ts += list(truong)
    if bo_do_ai:
        dk.append("do_ai=0")
    ts.append(int(tran))
    with _khoa_db:
        conn = _db()
        return _cat_tran(
            conn,
            f"SELECT * FROM su_kien WHERE {' AND '.join(dk)} ORDER BY ts DESC LIMIT ?",
            tuple(ts), int(tran), "doc_cua_so")


def doc_so_do(thiet_bi: str, truong: str, tu_ts: float, den_ts: float, *,
              tran: int = _TRAN_MAC_DINH) -> list[dict[str, Any]]:
    """Số đo đã gộp ô, theo ô tăng dần. Cùng luật trần với hai hàm đọc kia."""
    g = _o_gop_giay()
    with _khoa_db:
        conn = _db()
        rows = conn.execute(
            "SELECT * FROM so_do WHERE thiet_bi=? AND truong=? AND o_5p>=? AND o_5p<=?"
            " ORDER BY o_5p DESC LIMIT ?",
            (thiet_bi, truong, int(tu_ts // g), int(den_ts // g), int(tran))).fetchall()
    ra = [{**dict(r), "ts": r["o_5p"] * g} for r in reversed(rows)]
    if len(ra) >= tran:
        _stats["cham_tran"] = _stats.get("cham_tran", 0) + 1
        logger.warning({"event": "lich_su_cham_tran", "ham": "doc_so_do",
                        "tran": tran, "thiet_bi": thiet_bi, "truong": truong})
    return ra


def thong_ke() -> dict[str, Any]:
    try:
        with _khoa_db:
            conn = _db()
            sk = conn.execute("SELECT COUNT(*) FROM su_kien").fetchone()[0]
            sd = conn.execute("SELECT COUNT(*) FROM so_do").fetchone()[0]
            tu = conn.execute("SELECT COUNT(*) FROM tuoi").fetchone()[0]
            cu = conn.execute("SELECT MIN(ts) FROM su_kien").fetchone()[0]
        mb = 0.0
        for hau in ("", "-wal", "-shm"):
            p = Path(str(_DB_PATH) + hau)
            if p.exists():
                mb += p.stat().st_size / 1024 / 1024
        return {"su_kien": sk, "so_do": sd, "tuoi": tu,
                "mb": round(mb, 1), "cu_nhat_ts": cu, **stats()}
    except Exception as exc:
        return {"loi": str(exc)[:200], **stats()}


def don() -> dict[str, Any]:
    """Xoá quá hạn. Luồng nền gọi mỗi 6 giờ."""
    now = time.time()
    with _khoa_db:
        conn = _db()
        a = conn.execute("DELETE FROM su_kien WHERE ts < ?",
                         (now - _giu_su_kien_ngay() * 86400,)).rowcount
        b = conn.execute("DELETE FROM so_do WHERE o_5p < ?",
                         (int((now - _giu_so_do_ngay() * 86400) // _o_gop_giay()),)).rowcount
        # Dọn nốt dấu vết của hằng số cấu hình: 30 dòng "mồi" trước khi
        # `_phan_loai_theo_nhip` chốt được loại, cộng với những gì bản cũ đã
        # ghi khi chưa có luật này. Không cần biết tên trường nào — bảng
        # `nhip` đã đo ra chúng.
        c = conn.execute(
            "DELETE FROM so_do WHERE (thiet_bi, truong) IN"
            " (SELECT thiet_bi, truong FROM nhip WHERE loai='hang_so')").rowcount
        conn.commit()
    _stats["don_cuoi"] = now
    if a or b or c:
        logger.info({"event": "lich_su_don", "su_kien": a, "so_do": b,
                     "hang_so": c})
    return {"su_kien": a, "so_do": b, "hang_so": c}


# ── Nạp lịch sử Home Assistant ──────────────────────────────────────────────
def _ha_lay(duong_dan: str, timeout: int = 120) -> Any:
    from services.ha_client import _get_ha_config

    cfg = _get_ha_config()
    if not cfg:
        raise RuntimeError("chưa cấu hình Home Assistant")
    req = urllib.request.Request(
        cfg["url"].rstrip("/") + duong_dan,
        headers={"Authorization": f"Bearer {cfg['token']}",
                 "Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def nap_tu_ha(so_ngay: int = 10, thuc_the: list[str] | None = None) -> dict[str, Any]:
    """Nạp lịch sử HA sẵn có để quản gia khỏi bắt đầu từ số không.

    Đo trên HA thật 09/09/2026: giữ ~10 ngày, 40 đèn/công tắc cho ~4.000 bản
    ghi. Chạy hai lần không nhân đôi nhờ UNIQUE(thiet_bi, truong, ts).

    ⚠️ Mốc thời gian PHẢI url-encode: dấu ``+`` của múi giờ mà để nguyên thì bị
    hiểu thành dấu cách → HTTP 400 ở mọi mốc, rất dễ tưởng nhầm HA hết dữ liệu.

    ⚠️ Mọi bản ghi ghi ``do_ai=0``: /api/history KHÔNG cho biết ai bật (chỉ có
    state + thời điểm). Chấp nhận được vì đây là quá khứ trước khi quản gia tồn
    tại. Đánh dấu ``nguon='ha_nhap'`` để sau không lẫn với dữ liệu đo trực tiếp.
    """
    now = datetime.now(timezone.utc)
    tu = now - timedelta(days=max(1, int(so_ngay)))

    if not thuc_the:
        st = _ha_lay("/api/states", timeout=90)
        thuc_the = [s["entity_id"] for s in st
                    if str(s.get("entity_id", "")).startswith(
                        ("light.", "switch.", "binary_sensor.", "sensor.", "climate.", "fan."))]

    tong = bo = 0
    loi: list[str] = []
    for i in range(0, len(thuc_the), 40):
        lot = thuc_the[i:i + 40]
        q = urllib.parse.urlencode({
            "end_time": now.isoformat(),
            "filter_entity_id": ",".join(lot),
            "minimal_response": "true",
        })
        try:
            chuoi = _ha_lay(
                "/api/history/period/" + urllib.parse.quote(tu.isoformat()) + "?" + q)
        except Exception as exc:
            loi.append(str(exc)[:120])
            continue

        with _khoa_db:
            conn = _db()
            for day in chuoi or []:
                if not day:
                    continue
                eid = str(day[0].get("entity_id") or "")
                if not eid:
                    continue
                mien, _, ten = eid.partition(".")
                truong = "state"
                truoc: str | None = None
                for r in day:
                    gt = str(r.get("state") or "")
                    if gt.lower() in ("unavailable", "unknown", "none", ""):
                        bo += 1
                        continue
                    lc = r.get("last_changed") or r.get("last_updated")
                    if not lc:
                        continue
                    try:
                        ts = datetime.fromisoformat(str(lc)).timestamp()
                    except (TypeError, ValueError):
                        continue
                    if gt == truoc:
                        continue
                    t = datetime.fromtimestamp(ts, _TZ)
                    try:
                        cur = conn.execute(
                            "INSERT OR IGNORE INTO su_kien"
                            " (ts, nguon, thiet_bi, truong, gia_tri, gia_tri_cu, do_ai, gio, thu)"
                            " VALUES (?,'ha_nhap',?,?,?,?,0,?,?)",
                            (ts, f"{mien}.{ten}", truong, gt, truoc,
                             t.hour, t.weekday()),
                        )
                        tong += cur.rowcount
                        # Cập nhật luôn bảng `tuoi`: soi_hong đo "im lặng bao
                        # lâu" từ bảng này. Không ghi thì thiết bị nạp về không
                        # bao giờ bị soi ra là hỏng.
                        conn.execute(
                            "INSERT INTO tuoi (thiet_bi, truong, gia_tri, ts)"
                            " VALUES (?,?,?,?) ON CONFLICT(thiet_bi, truong)"
                            " DO UPDATE SET gia_tri=excluded.gia_tri, ts=excluded.ts"
                            " WHERE excluded.ts > tuoi.ts",
                            (f"{mien}.{ten}", truong, gt, ts),
                        )
                    except Exception:
                        _stats["loi"] += 1
                    truoc = gt
            conn.commit()

    kq = {"nap": tong, "bo_qua": bo, "thuc_the": len(thuc_the), "so_ngay": so_ngay}
    if loi:
        kq["loi"] = loi[:5]
    logger.info({"event": "lich_su_nap_ha", **kq})
    return kq


# ── Soi thiết bị hỏng ───────────────────────────────────────────────────────
# Ngưỡng "bao lâu không đổi thì coi là đơ" phải theo LOẠI cảm biến: pin không
# đổi 30 ngày là bình thường, lux không đổi 24 giờ là hỏng.
_NGUONG_DO_GIAY: dict[str, float] = {
    "illuminance": 24 * 3600, "illuminance_lux": 24 * 3600,
    "temperature": 24 * 3600, "humidity": 24 * 3600,
    "presence": 48 * 3600, "occupancy": 48 * 3600, "motion": 48 * 3600,
    "linkquality": 24 * 3600, "distance": 24 * 3600, "target_distance": 24 * 3600,
    "power": 24 * 3600, "current": 24 * 3600, "voltage": 7 * 86400,
    "battery": 30 * 86400,
}
_NGUONG_DO_MAC_DINH = 7 * 86400
_TY_LE_CHAP_CHON = 20.0


def _nguong(thiet_bi: str, truong: str) -> float:
    """Ngưỡng "im bao lâu thì coi là hỏng", theo LOẠI cảm biến.

    Pin đứng yên 30 ngày là bình thường; lux đứng yên 24 giờ là hỏng.

    Phải tra CẢ TÊN THIẾT BỊ, không chỉ tên trường: dữ liệu nạp từ Home
    Assistant có trường luôn là "state", còn loại nằm trong tên
    (``sensor.hien_dien_phong_hoc_illuminance``). Chỉ tra trường thì mọi cảm
    biến HA đều rơi về mặc định 7 ngày và hỏng nhẹ không bao giờ bị bắt.
    """
    t = truong.lower()
    if t in _NGUONG_DO_GIAY:
        return _NGUONG_DO_GIAY[t]
    tb = thiet_bi.lower()
    for k, v in _NGUONG_DO_GIAY.items():
        if k in tb:
            return v
    return _NGUONG_DO_MAC_DINH


def soi_hong(so_ngay: int = 7) -> list[dict[str, Any]]:
    """Cảm biến chết / đơ / chập chờn.

    Không cần học máy — đối chiếu quá khứ là đủ, nên chắc chắn hơn hẳn phần
    đoán thói quen. Đo thật trên HA chủ máy 09/09/2026 (500 cảm biến, 7 ngày):
    24 chết hẳn, 63 đơ, 69 chập chờn.

    GIÁ TRỊ KÉP: vừa cảnh báo chủ nhà, vừa BẢO VỆ phần học — cảm biến đơ mà
    đem đi học thì dạy quản gia điều sai. Đo được: đèn phòng học ra đúng 50,0%
    (bằng hệt đoán bừa) vì cảm biến phòng học báo lux đứng yên ở 86 suốt 7 ngày.

    ⚠️ KHÔNG dùng ``last_changed`` của trạng thái hiện tại để đo "bao lâu không
    đổi" — HA vừa khởi động lại là đặt lại hết, cả 415 cảm biến trông như vừa
    cập nhật. Phải đọc qua lịch sử, và đây chính là lý do bảng ``su_kien``
    dùng được cho việc này.
    """
    now = time.time()
    tu = now - max(1, int(so_ngay)) * 86400
    ra: list[dict[str, Any]] = []

    with _khoa_db:
        conn = _db()
        # PHẢI soi CẢ HAI bảng: cảm biến số (lux, nhiệt độ) nằm ở so_do, chỉ
        # trạng thái rời rạc mới ở su_kien. Soi mỗi su_kien thì bỏ sót đúng ca
        # quan trọng nhất — phòng học báo lux=86 đứng yên 7 ngày.
        #
        # ⚠️ KHÔNG lọc "ts >= cửa sổ" khi gom danh sách thiết bị: cảm biến hỏng
        # lâu thì KHÔNG có bản ghi nào trong cửa sổ, lọc là loại đúng cái cần
        # tìm. Đã gặp thật: cảm biến phòng học im 9 ngày biến mất khỏi kết quả.
        # Lấy TOÀN BỘ, rồi mới xét thời gian im lặng.
        thong = {}
        for r in conn.execute(
                "SELECT thiet_bi, truong, COUNT(*) n, COUNT(DISTINCT gia_tri) dm,"
                " MAX(ts) cuoi FROM su_kien GROUP BY thiet_bi, truong"):
            thong[(r["thiet_bi"], r["truong"])] = [int(r["n"]), int(r["dm"]), float(r["cuoi"])]
        g = _o_gop_giay()
        for r in conn.execute(
                "SELECT thiet_bi, truong, SUM(n) n, COUNT(DISTINCT nho||'/'||lon) dm,"
                " MAX(o_5p) cuoi FROM so_do GROUP BY thiet_bi, truong"):
            k = (r["thiet_bi"], r["truong"])
            cu = thong.get(k)
            moi = [int(r["n"]), int(r["dm"]), float(r["cuoi"]) * g]
            thong[k] = moi if cu is None else [cu[0] + moi[0],
                                               max(cu[1], moi[1]),
                                               max(cu[2], moi[2])]
        moi_nhat = {(r["thiet_bi"], r["truong"]): (r["gia_tri"], r["ts"])
                    for r in conn.execute("SELECT thiet_bi, truong, gia_tri, ts FROM tuoi")}

    for (tb, tr), (n, dm, cuoi) in thong.items():
        gt_cuoi, ts_cuoi = moi_nhat.get((tb, tr), (None, cuoi))
        im = now - float(ts_cuoi or cuoi)
        nguong = _nguong(tb, tr)

        if im > max(nguong * 2, 3 * 86400):
            ra.append({
                "thiet_bi": tb, "truong": tr, "loai": "chet",
                "chi_tiet": f"không tin nào trong {im / 86400:.1f} ngày",
                "lan_cuoi_tot": ts_cuoi, "so_ban_ghi": n,
            })
        elif dm <= 1 and im > nguong:
            ra.append({
                "thiet_bi": tb, "truong": tr, "loai": "do",
                "chi_tiet": f"chỉ một giá trị \"{gt_cuoi}\" suốt {im / 86400:.1f} ngày",
                "lan_cuoi_tot": ts_cuoi, "so_ban_ghi": n,
            })

    # Chập chờn: đếm số lần rơi vào unavailable/unknown trong chính su_kien.
    with _khoa_db:
        conn = _db()
        cc = conn.execute(
            "SELECT thiet_bi, truong,"
            " SUM(CASE WHEN lower(gia_tri) IN ('unavailable','unknown') THEN 1 ELSE 0 END) xau,"
            " COUNT(*) n FROM su_kien WHERE ts>=? GROUP BY thiet_bi, truong"
            " HAVING n>=10 AND xau>0", (tu,)).fetchall()
    for r in cc:
        ty = 100.0 * int(r["xau"]) / int(r["n"])
        if ty > _TY_LE_CHAP_CHON:
            ra.append({
                "thiet_bi": r["thiet_bi"], "truong": r["truong"], "loai": "chap_chon",
                "chi_tiet": f"{ty:.1f}% bản ghi là unavailable/unknown ({r['n']} bản ghi)",
                "lan_cuoi_tot": None, "so_ban_ghi": int(r["n"]),
            })

    thu_tu = {"chet": 0, "do": 1, "chap_chon": 2}
    ra.sort(key=lambda x: (thu_tu.get(x["loai"], 9), x["thiet_bi"]))
    return ra


def _reset_for_tests() -> None:
    """Chỉ dùng trong test — đóng kết nối, xoá trạng thái module."""
    global _conn, _thread
    stop()
    with _khoa_db:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        _conn = None
    while not _hang.empty():
        try:
            _hang.get_nowait()
        except queue.Empty:
            break
    _thread = None
    _stop.clear()
    for k in ("ghi", "bo", "loi"):
        _stats[k] = 0
