"""Nhận ra TÌNH HUỐNG trong nhà — "giờ ăn tối", "buổi sáng", "trước khi ngủ".

``thoi_quen_nha`` học được một chiều: "thiết bị X hay bật lúc mấy giờ". Không
trả lời được câu của chủ máy: *"giờ ăn nhận ra qua quạt bật liên tục, check qua
cam, rồi sau này yolo"*. Tình huống là TỔ HỢP nhiều nguồn cùng lúc, và nó cần
một cái TÊN để báo cáo cho người đọc hiểu.

═══ VÌ SAO LÕI LÀ CẢM BIẾN HIỆN DIỆN, KHÔNG PHẢI ĐÈN ═══

Chủ máy hỏi 09/09/2026: *"nếu ngồi ăn ở phòng khách thì sao"*. Câu hỏi đó chỉ
ra lỗi thiết kế thật, và số liệu xác nhận. Đo khung 19h–21h, 7 ngày liền:

    Định nghĩa bằng ĐÈN NÀO BẬT   →  3/35 thiết bị có mặt mọi ngày =  9% ổn định
    Định nghĩa bằng NGƯỜI Ở ĐÂU   → 10/13 cảm biến có mặt mọi ngày = 77% ổn định

Từng ngày dùng một bộ đèn khác nhau (thứ Sáu có phòng học, Chủ nhật không, thứ
Tư lại thiếu bếp trái). Nhưng cảm biến hiện diện thì gần như y nhau — ăn ở bếp
hay phòng khách, người vẫn là người, chỉ khác phòng.

Nên: **lõi = presence/occupancy/person**, đèn và công tắc chỉ là ``kem_theo``
để tham khảo khi đặt tên. Đổi phòng ăn không làm mất tình huống.

═══ CHỪA CHỖ CHO NHẬN DIỆN KHUÔN MẶT VÀ YOLO ═══

``loi_cot`` lưu danh sách nguồn dạng ``{"nguon": …, "ten": …}``. Thêm khuôn mặt
về sau chỉ là thêm ``{"nguon": "khuon_mat", "ten": "con_trai"}`` — không đổi
lược đồ, không đổi hàm nào. YOLO cũng vậy: ``{"nguon": "yolo", "ten": "nguoi"}``.

═══ CHỈ QUAN SÁT VÀ HỎI, KHÔNG TỰ LÀM ═══

Chủ máy chốt: quan sát → ghi → hỏi trước khi làm. Module này KHÔNG bật/tắt gì
cả. Model đoán tên, người duyệt rồi mới lưu — vì model đặt tên sai là chuyện
thường, và 7 ngày dữ liệu chưa đủ để tin.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR, config

logger = logging.getLogger(__name__)

_TZ = timezone(timedelta(hours=7))
_DB_PATH = Path(DATA_DIR) / "agent" / "tinh_huong_nha.sqlite"
_conn: Optional[sqlite3.Connection] = None
_khoa = threading.RLock()

#: Ô thời gian gom sự kiện. 30 phút: nhỏ hơn thì một bữa ăn bị chẻ làm đôi,
#: to hơn thì sáng với trưa dính vào nhau.
_O_PHUT = 30
#: Ô phải lặp ít nhất ngần này ngày KHÁC NHAU mới coi là nếp.
_TOI_THIEU_NGAY = 3
#: Ô phải nhộn nhịp hơn mức nền ngần này lần mới coi là tình huống. 1.5 =
#: đông hơn rưỡi lúc thường. Thấp hơn thì cả ngày đều "có nếp"; cao hơn thì
#: chỉ còn giờ cao điểm nhất.
_HON_NEN = 1.5

#: Nguồn được coi là LÕI — ổn định 77%, không đổi khi người dùng đổi phòng.
#: Thêm "khuon_mat"/"yolo" vào đây khi có, không phải sửa gì khác.
_NGUON_LOI = ("presence", "occupancy", "person", "khuon_mat", "yolo", "motion")
#: Nguồn KÈM THEO — chỉ 9% ổn định, dùng để gợi ý đặt tên chứ không định nghĩa.
_NGUON_KEM = ("state", "switch", "light", "fan")

#: Bỏ khỏi phần đặt tên: đèn bếp có tự động hoá nhấp nháy (đo: 905 lần bật/7
#: ngày, trung vị 23 giây một lần). Để nguyên thì model gọi mọi tình huống là
#: "bếp" vì bếp lúc nào cũng có mặt.
_BO_KHI_DAT_TEN = ("bep_left", "bep_center")

_PROMPT_TEN = (
    "Em là bộ phận đặt tên tình huống của một trợ lý nhà thông minh tiếng Việt.\n"
    "Dưới đây là một nếp sinh hoạt bot quan sát được. Hãy đặt cho nó MỘT cái tên\n"
    "ngắn bằng tiếng Việt đời thường, như người trong nhà vẫn gọi.\n\n"
    "Trả lời ĐÚNG khuôn này, không thêm lời dẫn:\n"
    "## TÊN\n"
    "- (tên ngắn 2-4 chữ, vd: giờ ăn tối, buổi sáng, trước khi ngủ, đi làm về)\n\n"
    "Không đoán được thì ghi đúng một dòng: KHÔNG RÕ\n"
)


def _cfg() -> dict[str, Any]:
    raw = (config.data.get("mqtt") or {}).get("tinh_huong")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("bat", True))


def _toi_thieu_ngay() -> int:
    try:
        return max(2, int(_cfg().get("toi_thieu_ngay") or _TOI_THIEU_NGAY))
    except (TypeError, ValueError):
        return _TOI_THIEU_NGAY


# ── Cơ sở dữ liệu ───────────────────────────────────────────────────────────
def _db() -> sqlite3.Connection:
    """Khuôn theo lich_su_nha._db(): WAL + busy_timeout + CREATE IF NOT EXISTS."""
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS tinh_huong ("
            " id INTEGER PRIMARY KEY,"
            " ten TEXT NOT NULL,"
            " trang_thai TEXT NOT NULL DEFAULT 'cho_duyet',"
            " gio_tb REAL NOT NULL,"
            " do_lech REAL NOT NULL,"
            " thu INTEGER NOT NULL DEFAULT -1,"       # -1 = mọi ngày
            " loi_cot TEXT NOT NULL DEFAULT '[]',"    # JSON, nguồn ổn định
            " kem_theo TEXT NOT NULL DEFAULT '[]',"   # JSON, chỉ tham khảo
            " so_lan INTEGER NOT NULL DEFAULT 0,"
            " lan_cuoi REAL,"
            " tao_luc REAL,"
            " dung INTEGER NOT NULL DEFAULT 0,"
            " sai INTEGER NOT NULL DEFAULT 0)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_th_ten ON tinh_huong(ten, thu)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_th_tt ON tinh_huong(trang_thai)")
        conn.commit()
        _conn = conn
    return _conn


# ── Gom cửa sổ ──────────────────────────────────────────────────────────────
def _phan_loai(truong: str, thiet_bi: str) -> str:
    """'loi' | 'kem' | '' (bỏ qua).

    Xét LÕI trước: mọi cảm biến hiện diện đều có trường 'state', nên nếu xét
    'state' trước thì chúng rơi hết vào nhóm kèm theo và tình huống mất lõi.
    """
    t = f"{truong} {thiet_bi}".lower()
    if any(k in t for k in _NGUON_LOI):
        return "loi"
    # Chỉ đèn/công tắc/quạt mới là kèm theo. binary_sensor còn lại (cửa mở,
    # khói, rò nước) không nói lên nếp sinh hoạt nên bỏ qua hẳn.
    if t.startswith(("light.", "switch.", "fan.")) or " light." in t or " switch." in t:
        return "kem"
    return ""


def _mad(xs: list[float]) -> float:
    """Độ lệch tuyệt đối trung vị, quy về thang σ. Y như thoi_quen_nha._mad."""
    if len(xs) < 2:
        return 0.0
    m = statistics.median(xs)
    return statistics.median([abs(x - m) for x in xs]) * 1.4826


def gom_cua_so(so_ngay: int = 14) -> list[dict[str, Any]]:
    """Gom sự kiện theo ô 30 phút, tìm ô lặp lại nhiều ngày.

    Trả danh sách ứng viên: mỗi cái là một ô thời gian có nếp, kèm nguồn LÕI
    (ổn định) tách khỏi nguồn KÈM THEO (đổi mỗi ngày).
    """
    from services import lich_su_nha

    den = time.time()
    tu = den - max(1, int(so_ngay)) * 86400
    try:
        sk = lich_su_nha.doc_cua_so(tu, den)
    except Exception as exc:
        logger.warning({"event": "tinh_huong_doc_loi", "error": str(exc)[:160]})
        return []

    # (ngày, ô) → {loi: set, kem: set, gio: float}
    o: dict[tuple, dict[str, Any]] = {}
    for r in sk:
        try:
            t = datetime.fromtimestamp(float(r["ts"]), _TZ)
        except (TypeError, ValueError, KeyError):
            continue
        tb, tr = str(r.get("thiet_bi") or ""), str(r.get("truong") or "")
        loai = _phan_loai(tr, tb)
        if not loai:
            continue
        # Chỉ tính lúc BẬT/CÓ, không tính lúc tắt — tình huống là "đang diễn ra".
        gt = str(r.get("gia_tri") or "").lower()
        if gt in ("off", "0", "false", "", "none", "unavailable", "unknown"):
            continue
        khoa = (t.date(), t.hour * 2 + (t.minute // _O_PHUT))
        m = o.setdefault(khoa, {"loi": set(), "kem": set(),
                                "gio": t.hour + t.minute / 60, "thu": t.weekday()})
        m[loai].add(f"{tb}/{tr}" if tr and tr != "state" else tb)

    # ô nào lặp nhiều ngày
    theo_o: dict[int, list[dict]] = {}
    for (_ngay, slot), m in o.items():
        if not m["loi"]:
            continue                      # không có người → không phải tình huống
        theo_o.setdefault(slot, []).append(m)

    # NGƯỠNG SO VỚI MỨC NỀN, không phải ngưỡng tuyệt đối. Cảm biến hiện diện
    # báo suốt ngày đêm (người ngủ trong nhà vẫn là "có người"), nên nếu chỉ
    # đòi "lặp ≥3 ngày" thì CẢ 48 Ô đều qua — kể cả 2h sáng — rồi bước gộp
    # nuốt trọn 24 tiếng thành một "tình huống". Đo thật: 48/48 ô qua ngưỡng.
    #
    # Tình huống là lúc nhà HOẠT ĐỘNG HƠN BÌNH THƯỜNG, nên phải so số nguồn
    # cùng hoạt động với mức nền của chính nhà đó.
    do_o = {slot: statistics.median([len(m["loi"]) + len(m["kem"]) for m in ds])
            for slot, ds in theo_o.items() if ds}
    # Mức nền lấy PHÂN VỊ 25%, không phải trung vị: nhà chỉ hoạt động vài
    # khung trong ngày, nên trung vị đã nằm giữa các khung bận và ngưỡng đội
    # lên loại luôn chính chúng. Phân vị thấp mới là "lúc nhà yên".
    muc = sorted(do_o.values())
    nen = muc[max(0, len(muc) // 4 - 1)] if muc else 0
    nguong = max(nen * _HON_NEN, 2)     # sàn 2: một nguồn đơn độc không là tình huống

    ra = []
    for slot, ds in theo_o.items():
        if len(ds) < _toi_thieu_ngay():
            continue
        if do_o.get(slot, 0) < nguong:
            continue                      # chỉ là mức nền, không phải tình huống
        gio = [m["gio"] for m in ds]
        # Nguồn LÕI xuất hiện ở đa số ngày mới được tính là lõi của tình huống.
        dem_loi: dict[str, int] = {}
        dem_kem: dict[str, int] = {}
        for m in ds:
            for x in m["loi"]:
                dem_loi[x] = dem_loi.get(x, 0) + 1
            for x in m["kem"]:
                dem_kem[x] = dem_kem.get(x, 0) + 1
        nua = max(1, len(ds) // 2)
        ra.append({
            "slot": slot,
            "gio_tb": round(statistics.median(gio), 3),
            "do_lech": round(max(_mad(gio), 10 / 60), 3),
            "so_ngay": len(ds),
            "loi_cot": sorted(k for k, v in dem_loi.items() if v >= nua),
            "kem_theo": sorted(k for k, v in dem_kem.items() if v >= nua),
        })
    ra.sort(key=lambda x: -x["so_ngay"])
    return ra


def hoc(so_ngay: int = 14) -> list[dict[str, Any]]:
    """Ứng viên tình huống, đã gộp những ô liền nhau thành một.

    19h00, 19h30, 20h00 đều lặp 7/7 ngày thật ra là MỘT bữa tối, không phải ba
    tình huống. Gộp các ô kề nhau có lõi giống nhau.
    """
    uv = gom_cua_so(so_ngay)
    if not uv:
        return []
    uv.sort(key=lambda x: x["slot"])
    ra: list[dict[str, Any]] = []
    for m in uv:
        truoc = ra[-1] if ra else None
        # Kề nhau (cách ≤1 ô) và lõi trùng quá nửa → cùng một tình huống.
        if truoc and m["slot"] - truoc["_slot_cuoi"] <= 1:
            a, b = set(truoc["loi_cot"]), set(m["loi_cot"])
            if a & b and len(a & b) >= min(len(a), len(b)) / 2:
                truoc["_slot_cuoi"] = m["slot"]
                truoc["so_ngay"] = max(truoc["so_ngay"], m["so_ngay"])
                truoc["loi_cot"] = sorted(a | b)
                truoc["kem_theo"] = sorted(set(truoc["kem_theo"]) | set(m["kem_theo"]))
                truoc["gio_tb"] = round((truoc["gio_tb"] + m["gio_tb"]) / 2, 3)
                truoc["do_lech"] = round(max(truoc["do_lech"], m["do_lech"]), 3)
                continue
        ra.append({**m, "_slot_cuoi": m["slot"]})
    for m in ra:
        m.pop("_slot_cuoi", None)
        m.pop("slot", None)
    ra.sort(key=lambda x: -x["so_ngay"])
    return ra


# ── Đặt tên ─────────────────────────────────────────────────────────────────
def _mo_ta_ung_vien(uv: dict[str, Any]) -> str:
    g = float(uv["gio_tb"])
    dong = [f"Giờ: khoảng {int(g)}h{int(g % 1 * 60):02d}, lặp {uv['so_ngay']} ngày"]
    loi = [x.split("/")[0] for x in uv.get("loi_cot") or []]
    if loi:
        dong.append("Có người ở: " + ", ".join(sorted(set(loi))[:6]))
    kem = [x for x in (uv.get("kem_theo") or [])
           if not any(b in x for b in _BO_KHI_DAT_TEN)]
    if kem:
        dong.append("Thiết bị hay bật: " + ", ".join(kem[:6]))
    return "\n".join(dong)


def de_xuat_ten(uv: dict[str, Any]) -> str:
    """Nhờ model đặt tên. Hỏng hoặc không đoán được → trả ``""``.

    KHÔNG raise: đây là job nền, model lỗi thì bỏ qua ứng viên này, mai gom lại.
    """
    try:
        from services.agent import runtime
        resp = runtime.call_model(
            _model(),
            [{"role": "user", "content": _PROMPT_TEN + "\n" + _mo_ta_ung_vien(uv)}],
            timeout=60, max_tokens=120,
            # BẮT BUỘC: prompt đầy tên thiết bị, không có cờ này thì bị đường
            # tắt điều khiển nhà của HA cướp mất (xem runtime.py:206-209).
            no_smart_home=True,
        )
        if resp.get("error"):
            return ""
        text = runtime.content_of(resp) or ""
    except Exception as exc:
        logger.info({"event": "tinh_huong_dat_ten_loi", "error": str(exc)[:160]})
        return ""

    if "## TÊN" not in text.upper().replace("TEN", "TÊN"):
        return ""
    phan = text.split("##", 1)[-1]
    for dong in phan.splitlines():
        d = dong.strip().lstrip("-").strip()
        if not d or d.upper().startswith("TÊN"):
            continue
        # So NGUYÊN DÒNG, không phải chuỗi con — "không rõ giờ nào" là tên hợp lệ.
        if d.upper().rstrip(".") == "KHÔNG RÕ":
            return ""
        return d[:60]
    return ""


def _model() -> str:
    try:
        from services.agent import compaction
        return compaction._main_model()
    except Exception:
        return ""


# ── Lưu và duyệt ────────────────────────────────────────────────────────────
def luu_cho_duyet(uv: dict[str, Any], ten: str, thu: int = -1) -> int:
    """Ghi ứng viên vào sổ, trạng thái 'cho_duyet'. Trả id, 0 nếu trùng."""
    ten = (ten or "").strip()
    if not ten:
        return 0
    with _khoa:
        conn = _db()
        cur = conn.execute(
            "INSERT OR IGNORE INTO tinh_huong"
            " (ten, trang_thai, gio_tb, do_lech, thu, loi_cot, kem_theo,"
            "  so_lan, lan_cuoi, tao_luc)"
            " VALUES (?, 'cho_duyet', ?, ?, ?, ?, ?, ?, ?, ?)",
            (ten, float(uv["gio_tb"]), float(uv["do_lech"]), int(thu),
             json.dumps(uv.get("loi_cot") or [], ensure_ascii=False),
             json.dumps(uv.get("kem_theo") or [], ensure_ascii=False),
             int(uv.get("so_ngay") or 0), time.time(), time.time()))
        conn.commit()
        return int(cur.lastrowid or 0) if cur.rowcount else 0


def duyet(id_: int, ten: str = "") -> bool:
    """Người xác nhận. Truyền ``ten`` để đổi tên model đặt."""
    with _khoa:
        conn = _db()
        if ten.strip():
            conn.execute("UPDATE tinh_huong SET trang_thai='da_duyet', ten=? WHERE id=?",
                         (ten.strip(), int(id_)))
        else:
            conn.execute("UPDATE tinh_huong SET trang_thai='da_duyet' WHERE id=?",
                         (int(id_),))
        n = conn.total_changes
        conn.commit()
    return n > 0


def bo(id_: int) -> bool:
    """Người bỏ qua. KHÔNG tính là 'sai' — theo skill_quality._KHONG_TINH:
    người từ chối là quyết định của người, không phải lỗi của máy."""
    with _khoa:
        conn = _db()
        conn.execute("UPDATE tinh_huong SET trang_thai='bo' WHERE id=?", (int(id_),))
        n = conn.total_changes
        conn.commit()
    return n > 0


# ── Nhận ra ─────────────────────────────────────────────────────────────────
def nhan_ra(luc: float | None = None, *, cua_so_phut: int = 45) -> dict[str, Any] | None:
    """Đang ở trong tình huống nào? Chỉ xét tình huống ĐÃ DUYỆT.

    Trả ``None`` khi không chắc — thà im còn hơn đoán sai tên gọi cho người đọc.
    """
    now = luc or time.time()
    t = datetime.fromtimestamp(now, _TZ)
    gio = t.hour + t.minute / 60
    with _khoa:
        conn = _db()
        rows = conn.execute(
            "SELECT * FROM tinh_huong WHERE trang_thai='da_duyet'").fetchall()
    ung = []
    for r in rows:
        if int(r["thu"]) >= 0 and int(r["thu"]) != t.weekday():
            continue
        lech = abs(gio - float(r["gio_tb"])) * 60
        if lech <= max(cua_so_phut, float(r["do_lech"]) * 60 * 2):
            ung.append((lech, dict(r)))
    if not ung:
        return None
    ung.sort(key=lambda x: x[0])
    # Hai tình huống sát nhau quá thì không dám chọn — khuôn của
    # ha_intent_rank: có biên cách biệt mới quyết, không thì trả None.
    if len(ung) > 1 and ung[1][0] - ung[0][0] < 10:
        return None
    d = ung[0][1]
    d["loi_cot"] = json.loads(d.get("loi_cot") or "[]")
    d["kem_theo"] = json.loads(d.get("kem_theo") or "[]")
    d["lech_phut"] = round(ung[0][0])
    return d


# ── Chấm điểm ───────────────────────────────────────────────────────────────
def ghi_dung(id_: int) -> None:
    with _khoa:
        conn = _db()
        conn.execute("UPDATE tinh_huong SET dung=dung+1, lan_cuoi=? WHERE id=?",
                     (time.time(), int(id_)))
        conn.commit()


def ghi_sai(id_: int) -> None:
    with _khoa:
        conn = _db()
        conn.execute("UPDATE tinh_huong SET sai=sai+1 WHERE id=?", (int(id_),))
        conn.commit()


def diem(id_: int) -> float:
    """Laplace, y hệt skill_quality.diem(): chưa có dữ liệu → 0.5 (chưa biết)."""
    with _khoa:
        conn = _db()
        r = conn.execute("SELECT dung, sai FROM tinh_huong WHERE id=?",
                         (int(id_),)).fetchone()
    if not r:
        return 0.5
    return (int(r["dung"]) + 1) / (int(r["dung"]) + int(r["sai"]) + 2)


def danh_sach(trang_thai: str = "") -> list[dict[str, Any]]:
    with _khoa:
        conn = _db()
        if trang_thai:
            rows = conn.execute(
                "SELECT * FROM tinh_huong WHERE trang_thai=? ORDER BY so_lan DESC",
                (trang_thai,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tinh_huong ORDER BY trang_thai, so_lan DESC").fetchall()
    ra = []
    for r in rows:
        d = dict(r)
        d["loi_cot"] = json.loads(d.get("loi_cot") or "[]")
        d["kem_theo"] = json.loads(d.get("kem_theo") or "[]")
        g = float(d["gio_tb"])
        d["gio"] = f"{int(g)}h{int(g % 1 * 60):02d}"
        d["lech_phut"] = round(float(d["do_lech"]) * 60)
        d["diem"] = round(diem(int(d["id"])), 3)
        ra.append(d)
    return ra


def chay_mot_lan(so_ngay: int = 14, *, toi_da: int = 3) -> dict[str, Any]:
    """Gom → đặt tên → lưu chờ duyệt. Heartbeat gọi mỗi ngày một lần.

    ``toi_da`` chặn chi phí model: mỗi lần chạy chỉ đặt tên vài cái mới.
    """
    if not is_enabled():
        return {"moi": 0, "ly_do": "tắt trong cấu hình"}
    da_co = {d["ten"] for d in danh_sach()}
    moi = 0
    for uv in hoc(so_ngay):
        if moi >= toi_da:
            break
        ten = de_xuat_ten(uv)
        if not ten or ten in da_co:
            continue
        if luu_cho_duyet(uv, ten):
            moi += 1
            da_co.add(ten)
    return {"moi": moi, "cho_duyet": len(danh_sach("cho_duyet"))}


def thong_ke() -> dict[str, Any]:
    ds = danh_sach()
    return {
        "bat": is_enabled(),
        "tong": len(ds),
        "cho_duyet": sum(1 for d in ds if d["trang_thai"] == "cho_duyet"),
        "da_duyet": sum(1 for d in ds if d["trang_thai"] == "da_duyet"),
    }


def _reset_for_tests() -> None:
    global _conn
    with _khoa:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        _conn = None
