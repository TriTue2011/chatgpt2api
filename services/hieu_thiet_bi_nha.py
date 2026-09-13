"""Tầng HIỂU THIẾT BỊ — bot học hỏi tự đọc hồ sơ thiết bị rồi kết luận.

Chủ máy chốt 11/09/2026, nguyên văn:

    "Việc học hỏi nên học theo các thiết bị bật tắt được chứ các thiết bị
    trạng thái học làm gì. […] Bỏ các thiết bị bật tắt rác, sensor rác,
    sensor lỗi đi"

    "bạn chỉ như là giáo viên tạo hướng dẫn để bot của tôi giải bài toán,
    sau đó xem lại giải đúng không"

Nên việc chia làm năm phần, và KHÔNG phần nào là danh sách lọc cài cứng:

1. CODE CHỈ ĐO (`ho_so`). Mã nào đổi cùng lúc với mã nào, lệch nhau bao nhiêu
   mili-giây, ai đổi trước, mỗi lần đổi có bao nhiêu mã khác đổi theo, HA có
   lệnh bật không. Code không phán thiết bị nào là rác.
2. BOT GIẢI (`giai`). Một lời gọi model mà system prompt CHỈ có hướng dẫn
   (`huong_dan()`) — không persona, không skill, không tool — để khỏi nhiễu.
3. NGƯỜI CHẤM (`cham`, `sua_cham`, `tra_loi`). Claude chấm bằng số đo thật
   (`scripts/cham_hieu_thiet_bi.py`), chủ máy chấm trong nhóm Zalo "AI học
   hỏi" và là người chấm cuối cùng. Chấm đúng đủ nhiều thì bot thôi hỏi — cùng
   thang với `du_doan_nha.cap`.
4. CHỦ MÁY DẠY (`ghi_du_kien`, `nhan_du_kien`). Lời chủ máy nhắn vào nhóm học
   hỏi được ghi vào sổ dữ kiện và đưa vào đề ở lượt giải kế tiếp — lượt đó
   chạy ngay tick sau chứ không chờ sang ngày.
5. GIÁO VIÊN SỬA HƯỚNG DẪN. Bản chạy thật nằm trong DATA_DIR để sửa được mà
   không dựng lại ảnh; mỗi lượt giải ghi phiên bản hướng dẫn, để biết điểm
   chấm thuộc bản nào.

Kết luận của bot được `du_doan_nha.hoc()` dùng NGAY — bị chấm sai thì thôi.
Kết luận sai không tự bật được gì: lời gợi ý bật thiết bị vẫn đi qua thang tự
chủ riêng của `du_doan_nha`.

Số đo làm đề (kho thật 11/09/2026) — để người sau hiểu vì sao hồ sơ có từng
trường, KHÔNG phải để code dùng:

* 6 cặp `light.X`/`switch.X` đổi cùng lúc 88–100% cả hai chiều, `switch` đổi
  trước 98–100%, lệch trung vị 0 ms; cặp kế tiếp chỉ trùng 9,5%.
* MQTT (zigbee2mqtt) báo trước HA trực tiếp 86–100% số lần, sớm 2–3 ms.
* Điều hòa ↔ Aptomat điều hòa và Công tắc mini ↔ Dàn âm thanh cũng trùng gần
  100% hai chiều, nhưng lệch 29 ms và 60 ms — chủ máy xác nhận là HAI thiết bị
  nối bằng automation. Tỉ lệ trùng một mình không phân biệt được hai chuyện đó.
* 30 công tắc cấu hình Frigate: lần nào đổi cũng có 25–29 mã khác đổi cùng
  giây — hệ thống nạp lại, không phải người bật.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR, config

# Bộ ghi log của nhà — xem chú thích cùng việc ở `services/canh_bao_nha.py`.
from utils.log import logger

_TZ = timezone(timedelta(hours=7))
_DB_PATH = Path(DATA_DIR) / "agent" / "hieu_thiet_bi_nha.sqlite"
_HUONG_DAN_GOC = Path(__file__).with_name("huong_dan_hoc") / "hieu_thiet_bi.md"
_conn: Optional[sqlite3.Connection] = None
_khoa = threading.Lock()

#: Một lượt giải tốn vài phút gọi model, mà dữ kiện mới làm heartbeat gọi lại
#: mỗi tick 5 phút — không chặn thì hai lượt chồng nhau ghi đè kết luận của nhau.
_dang_giai = threading.Lock()

#: Hai lần đổi cách nhau không quá ngần này giây thì coi là CÙNG LÚC. Đo
#: 11/09/2026: hai mã của cùng một bóng lệch 0–3 ms, hai thiết bị nối bằng
#: automation lệch vài chục ms. Một giây rộng hơn cả hai mà vẫn ngắn hơn một lần
#: người bấm hai công tắc liền nhau.
_CUNG_LUC_GIAY = 1.0

#: Hồ sơ chỉ kể các mã trùng từ 10% số lần đổi trở lên (một trong hai chiều),
#: tối đa 5 mã. Không cắt thì một lần HA khởi động lại làm mọi mã "trùng" với
#: mọi mã, và đề ngập những dòng 1%. Con số tổng vẫn còn nguyên ở
#: `so_ma_khac_doi_cung_luc`.
_TY_LE_KE = 0.1
_TOI_DA_KE = 5

#: Mỗi lượt gọi model tối đa ngần này hồ sơ; nhiều hơn thì chia theo cụm, để
#: các mã trùng nhau luôn nằm chung một lượt.
_TOI_DA_MOI_LUOT = 40

#: Đề đưa kèm tối đa ngần này dữ kiện gần nhất của chủ máy.
_TOI_DA_DU_KIEN = 40

_LOAI = ("bat_tat", "cam_bien", "rac", "khong_ro")

#: Vai trò một ngoại vi với thiết bị — tầng thói quen dùng khi đọc số đo.
VAI_TRO_NGOAI_VI = ("hien_dien", "dem_nguoi", "anh_sang", "nhiet_do", "do_am",
                    "thiet_bi", "khac")
_VAI_TRO_DOC = {"hien_dien": "hiện diện", "dem_nguoi": "đếm người",
                "anh_sang": "ánh sáng", "nhiet_do": "nhiệt độ", "do_am": "độ ẩm",
                "thiet_bi": "thiết bị đi kèm", "khac": "khác"}

_LOAI_DOC = {"rac": "đổi đồng loạt, không phải người bật",
             "cam_bien": "là cảm biến, dùng làm điều kiện",
             "khong_ro": "chưa rõ là gì",
             "bat_tat": "chưa đủ lần bật"}

#: Loại câu hỏi được chấm và lên cấp RIÊNG: bot giỏi nhận ra thiết bị trùng
#: chưa chắc đã giỏi chọn nguồn nhanh, càng chưa chắc giỏi chọn điều kiện.
LOAI_CAU_HOI = ("cung_thiet_bi", "nguon_nhanh", "hoc", "dieu_kien", "ngoai_vi", "thoi_quen")

#: Các loại câu do LƯỢT HIỂU THIẾT BỊ (`giai`) sinh ra. `ghi_ket_qua` chỉ được vô
#: hiệu những loại này khi một mã đổi nhóm; câu `ngoai_vi` và `thoi_quen` do tầng
#: thói quen (`services/thoi_quen_nha.py`) sinh ra, lượt hằng ngày ở đây không được
#: xoá chúng.
_LOAI_CUA_LUOT_HIEU = ("cung_thiet_bi", "nguon_nhanh", "hoc", "dieu_kien")

#: Một thiết bị học theo tối đa ngần này điều kiện. Naive Bayes cộng các điều
#: kiện như thể độc lập; ánh sáng bốn phòng cùng "tối" lúc đêm là MỘT chuyện bị
#: đếm bốn lần — đó là một nửa lý do gợi ý 11/09/2026 ra "chắc 100%".
_TOI_DA_DIEU_KIEN = 5


def _cfg() -> dict[str, Any]:
    raw = (config.data.get("mqtt") or {}).get("hieu_thiet_bi")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("bat", True))


def _db() -> sqlite3.Connection:
    """Khuôn theo `du_doan_nha._db`: WAL + CREATE IF NOT EXISTS."""
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS lan_giai ("
            " id INTEGER PRIMARY KEY,"
            " ts REAL NOT NULL,"
            " phien_ban TEXT NOT NULL,"        # sha256 hướng dẫn, 12 ký tự
            " model TEXT NOT NULL,"
            " so_ho_so INTEGER NOT NULL,"
            " so_nhom INTEGER NOT NULL,"
            " bo_sot INTEGER NOT NULL DEFAULT 0,"
            " loai_bo INTEGER NOT NULL DEFAULT 0,"
            " loi TEXT NOT NULL DEFAULT '')"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS quyet_dinh ("
            " id INTEGER PRIMARY KEY,"
            " lan_giai INTEGER NOT NULL,"
            " ts REAL NOT NULL,"
            " loai_cau_hoi TEXT NOT NULL,"
            " khoa TEXT NOT NULL,"
            " gia_tri TEXT NOT NULL,"          # JSON — đúng thứ được chấm
            " nhom TEXT NOT NULL,"             # JSON — cả nhóm bot trả, để kể lại
            " hieu_luc INTEGER NOT NULL DEFAULT 1,"
            " ket_qua TEXT NOT NULL DEFAULT 'cho',"   # cho | dung | sai
            " cham_boi TEXT NOT NULL DEFAULT '',"     # claude | chu_may | lap_lai
            " ghi_chu TEXT NOT NULL DEFAULT '',"
            " cham_luc REAL,"
            " hoi_luc REAL)"                  # lúc câu này được gửi hỏi chủ máy
        )
        # Sổ tạo trước 11/09/2026 chưa có cột `hoi_luc` (hỏi lần lượt từng câu).
        if "hoi_luc" not in {r[1] for r in conn.execute("PRAGMA table_info(quyet_dinh)")}:
            conn.execute("ALTER TABLE quyet_dinh ADD COLUMN hoi_luc REAL")
        # Sổ tạo trước 13/09/2026 chỉ có MỘT việc giải. Tầng thói quen ghi lượt
        # của nó vào cùng bảng; không tách thì lượt chọn ngoại vi làm
        # `co_du_kien_moi` tưởng dữ kiện mới đã được lượt hiểu thiết bị xem.
        if "viec" not in {r[1] for r in conn.execute("PRAGMA table_info(lan_giai)")}:
            conn.execute("ALTER TABLE lan_giai ADD COLUMN viec TEXT NOT NULL"
                         " DEFAULT 'hieu_thiet_bi'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qd_khoa"
                     " ON quyet_dinh(loai_cau_hoi, khoa, hieu_luc)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS thanh_tich ("
            " loai_cau_hoi TEXT PRIMARY KEY,"
            " dung INTEGER NOT NULL DEFAULT 0,"
            " sai INTEGER NOT NULL DEFAULT 0)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS du_kien ("
            " id INTEGER PRIMARY KEY,"
            " ts REAL NOT NULL,"
            " nguoi TEXT NOT NULL DEFAULT '',"
            " noi_dung TEXT NOT NULL,"
            " nguon TEXT NOT NULL DEFAULT 'nhom')"   # nhom | hh
        )
        conn.commit()
        _conn = conn
    return _conn


# ── Hướng dẫn ───────────────────────────────────────────────────────────────
def _duong_huong_dan(ten: str = "hieu_thiet_bi") -> Path:
    return Path(DATA_DIR) / "agent" / "hoc_hoi" / f"{ten}.md"


def huong_dan(ten: str = "hieu_thiet_bi") -> tuple[str, str]:
    """(nội dung, phiên bản) của hướng dẫn đang dùng.

    Bản chạy thật nằm trong DATA_DIR để giáo viên sửa được mà không dựng lại
    ảnh. Phiên bản là 12 ký tự đầu của sha256: đổi một chữ là đổi phiên bản,
    điểm chấm không lẫn giữa hai bản.

    Bản gốc trong repo ĐỔI thì bản chạy thật đổi theo — trừ khi bản chạy thật
    đã được sửa tay (`ghi_huong_dan`, hoặc giáo viên sửa file). Xem
    `services/ban_goc.py`: 13/09/2026 code chọn ngoại vi đã sang hai bước mà
    `chon_ngoai_vi.md` chạy thật vẫn là bản một bước.

    `ten` chọn bản hướng dẫn: mỗi việc học một bản NGẮN riêng (chủ máy chốt
    13/09/2026 "hướng dẫn ngắn gọn và xúc tích, tránh dài để bot nghĩ nhiều").
    """
    from services import ban_goc

    p = _duong_huong_dan(ten)
    p.parent.mkdir(parents=True, exist_ok=True)
    ban_goc.dong_bo(_HUONG_DAN_GOC.with_name(f"{ten}.md"), p, p.with_suffix(".goc"),
                    ten=f"huong_dan:{ten}")
    noi = p.read_text(encoding="utf-8")
    return noi, hashlib.sha256(noi.encode("utf-8")).hexdigest()[:12]


# ── Đo hồ sơ ────────────────────────────────────────────────────────────────
def _ma(r: dict[str, Any]) -> str:
    """Mã của một dòng lịch sử.

    Công tắc nhiều nút của zigbee2mqtt ghi mỗi nút một trường (`state_left`,
    `state_l1`…) trên CÙNG một chủ đề, nên trường phải là một phần của mã —
    không thì ba nút thành một thiết bị.
    """
    tb = str(r.get("thiet_bi") or "")
    tr = str(r.get("truong") or "")
    return tb if tr == "state" else f"{tb}#{tr}"


def ho_so(so_ngay: int | None = None, *, den: float | None = None) -> dict[str, Any]:
    """Đo hồ sơ các mã bật tắt được và các mã đổi cùng lúc với chúng.

    Trả ``{"so_ngay": n, "thiet_bi": [hồ sơ, …]}``. Rỗng = Home Assistant chưa
    trả sổ dịch vụ: không biết cái gì bật được thì không ra đề, và kết luận cũ
    được giữ nguyên.

    Chỉ ĐO. Mọi con số ở đây đều trả lời được bằng đếm; câu "cái này là rác
    không" là việc của bot, theo hướng dẫn.
    """
    from services import boi_canh_nha, du_doan_nha, ha_client, lich_su_nha

    mien = du_doan_nha.mien_bat_duoc()
    if not mien:
        return {}
    ngay = max(1, int(so_ngay or du_doan_nha._so_ngay_hoc()))
    den = float(den or time.time())
    tu = den - ngay * 86400
    dong = (lich_su_nha.doc_trang_thai(
                tu, den, tien_to=tuple(f"{m}." for m in sorted(mien)), bo_do_ai=True)
            + lich_su_nha.doc_trang_thai(tu, den, ngoai_ha=True, bo_do_ai=True))

    su_kien: dict[str, list[tuple[float, str, str]]] = {}
    da_doc: set[Any] = set()
    for r in dong:
        if r.get("id") in da_doc:
            continue
        da_doc.add(r.get("id"))
        su_kien.setdefault(_ma(r), []).append(
            (float(r.get("ts") or 0), str(r.get("gia_tri") or ""), str(r.get("nguon") or "")))
    for ds in su_kien.values():
        ds.sort()

    nguon_ha = set(lich_su_nha.NGUON_HA)
    la_ha = {ma for ma, ds in su_kien.items() if any(n in nguon_ha for _, _, n in ds)}
    # Mã HA KHÔNG CÒN trong HA thì không ra đề: thiết bị đã đổi tên hay đã xoá
    # không còn để học, mà mã cũ còn nằm trong lịch sử 30 ngày. Đo 11/09/2026:
    # 4 camera go2rtc mang mật khẩu ngay trong mã; `ha_client.get_states` ẩn
    # chúng, nhưng đọc mã từ lịch sử mà không đối chiếu thì mật khẩu vẫn vào đề
    # gửi model.
    trang_thai = ha_client.get_states() or []
    con_trong_ha = {str(s.get("entity_id") or "") for s in trang_thai}
    if not con_trong_ha:
        return {}
    for ma in la_ha - con_trong_ha:
        del su_kien[ma]
    la_ha &= con_trong_ha
    ung_vien = {ma for ma in la_ha
                if ma.split(".")[0] in mien
                and any(du_doan_nha._la_bat(g) for _, g, _ in su_kien[ma])}
    xet = ung_vien | (set(su_kien) - la_ha)

    # Đổi cùng lúc: với mỗi lần đổi, mã khác nào đổi trong ±1 giây (lấy lần
    # gần nhất của mỗi mã), lệch nhau bao lâu, và ai đổi trước. Chia theo giây
    # để khỏi so từng cặp.
    theo_giay: dict[int, list[tuple[float, str]]] = {}
    for ma in xet:
        for t, _, _ in su_kien[ma]:
            theo_giay.setdefault(int(t), []).append((t, ma))
    trung: dict[str, dict[str, int]] = {ma: {} for ma in xet}
    truoc: dict[str, dict[str, int]] = {ma: {} for ma in xet}
    lech: dict[str, dict[str, list[float]]] = {ma: {} for ma in xet}
    so_kem: dict[str, list[int]] = {ma: [] for ma in xet}
    for ma in xet:
        for t, _, _ in su_kien[ma]:
            gan: dict[str, float] = {}
            for g in (int(t) - 1, int(t), int(t) + 1):
                for t2, khac in theo_giay.get(g, ()):
                    if khac == ma or abs(t2 - t) > _CUNG_LUC_GIAY:
                        continue
                    if khac not in gan or abs(t2 - t) < abs(gan[khac] - t):
                        gan[khac] = t2
            so_kem[ma].append(len(gan))
            for khac, t2 in gan.items():
                trung[ma][khac] = trung[ma].get(khac, 0) + 1
                lech[ma].setdefault(khac, []).append(abs(t2 - t))
                if t < t2:
                    truoc[ma][khac] = truoc[ma].get(khac, 0) + 1

    # Hai mã chỉ so được với nhau trong lúc NGUỒN của cả hai đều đang ghi. Đo
    # kho thật 11/09/2026: MQTT mới ghi 1,5 ngày còn HA có 11,8 ngày — chia cho
    # mọi lần đổi của công tắc HA thì bản MQTT của chính nó chỉ "trùng 9%", và
    # bot sẽ tách một bóng đèn làm hai.
    phu: dict[str, tuple[float, float]] = {}
    for ds in su_kien.values():
        for t, _, n in ds:
            a, b = phu.get(n, (t, t))
            phu[n] = (min(a, t), max(b, t))
    nguon_cua = {ma: frozenset(n for _, _, n in ds) for ma, ds in su_kien.items()}
    dem_luc_ghi: dict[tuple[str, frozenset], int] = {}

    def ty_le(a: str, b: str) -> float:
        """Phần số lần `a` đổi — trong lúc nguồn của `b` đang ghi — có `b` đổi cùng."""
        khoa = (a, nguon_cua[b])
        if khoa not in dem_luc_ghi:
            # Nới mỗi mép thêm một khoảng "cùng lúc": lần đổi của `a` khớp với
            # bản ghi đầu/cuối của nguồn kia vẫn là lúc nguồn ấy đang ghi.
            khoang = [(phu[n][0] - _CUNG_LUC_GIAY, phu[n][1] + _CUNG_LUC_GIAY)
                      for n in nguon_cua[b]]
            dem_luc_ghi[khoa] = sum(1 for t, _, _ in su_kien[a]
                                    if any(x <= t <= y for x, y in khoang))
        mau = dem_luc_ghi[khoa]
        return trung[a].get(b, 0) / mau if mau else 0.0

    doi_cung: dict[str, list[dict[str, Any]]] = {}
    for ma in xet:
        cap = [(ty_le(ma, b), ty_le(b, ma), b) for b in trung[ma]]
        # Xếp theo chiều YẾU hơn. Đo kho thật: một mã chỉ đổi đúng một lần lúc
        # HA khởi động lại "trùng 100%" ở chiều của nó; xếp theo chiều mạnh thì
        # những mã như vậy chiếm hết năm chỗ, đẩy bản sao thật của thiết bị ra.
        xep = sorted((x for x in cap if max(x[0], x[1]) >= _TY_LE_KE),
                     key=lambda x: (-min(x[0], x[1]), -max(x[0], x[1]), x[2]))
        doi_cung[ma] = [
            {"ma": b, "ty_le_minh": round(minh, 3), "ty_le_ban": round(ban, 3),
             "minh_doi_truoc": round(truoc[ma].get(b, 0) / trung[ma][b], 3),
             # Tỉ lệ trùng không tách được "một thiết bị hiện hai mã" với "hai
             # thiết bị nối bằng automation" — độ lệch thì tách được (xem đầu tệp).
             "lech_ms": round(statistics.median(lech[ma][b]) * 1000)}
            for minh, ban, b in xep[:_TOI_DA_KE]]

    # Đề gồm mã bật tắt được, cộng mã ngoài HA đổi cùng lúc với chúng — bản MQTT
    # của cùng một công tắc chính là thứ để trả lời "nguồn nào báo trước".
    ho = set(ung_vien)
    for ma in ung_vien:
        ho.update(x["ma"] for x in doi_cung[ma])

    ten = {str(s.get("entity_id") or ""):
           str((s.get("attributes") or {}).get("friendly_name") or "")
           for s in trang_thai}
    ra: list[dict[str, Any]] = []
    for ma in sorted(ho):
        ds = su_kien[ma]
        gia: dict[str, int] = {}
        nguon: dict[str, int] = {}
        for _, g, n in ds:
            gia[g] = gia.get(g, 0) + 1
            nguon[n] = nguon.get(n, 0) + 1
        cua_ha = ma in la_ha
        ra.append({
            "ma": ma,
            "ten": ten.get(ma, "") if cua_ha else "",
            "phong": (boi_canh_nha.phong_cua(ma) or "") if cua_ha else "",
            "mien": ma.split(".")[0] if cua_ha else "",
            "ha_bat_duoc": cua_ha and ma.split(".")[0] in mien,
            "nguon": nguon,
            "so_lan_doi": len(ds),
            "so_lan_bat": sum(1 for _, g, _ in ds if du_doan_nha._la_bat(g)),
            "so_gia_tri": len(gia),
            "gia_tri_hay_gap": sorted(gia.items(), key=lambda x: (-x[1], x[0]))[:3],
            "doi_cung_luc": [x for x in doi_cung[ma] if x["ma"] in ho],
            "so_ma_khac_doi_cung_luc": {
                "trung_vi": statistics.median(so_kem[ma]) if so_kem[ma] else 0,
                "lon_nhat": max(so_kem[ma], default=0)},
        })
    # Thực đơn điều kiện: mọi điều kiện đo được, cộng "thiết bị khác vừa bật hay
    # tắt" cho từng mã HA bật được trong đề — mở rộng "thiết bị là điều kiện của
    # nhau" của `du_doan_nha`. Chọn cái nào là việc của bot.
    thuc_don = boi_canh_nha.thuc_don_dieu_kien(ngay) + [
        {"khoa": f"bat_{x['ma']}", "ten": f"{x['ten'] or x['ma']} vừa bật hoặc tắt",
         "loai": "thiet_bi", "phong": x["phong"], "do_bang": [x["ma"]]}
        for x in ra if x["ha_bat_duoc"]]
    return {"so_ngay": ngay, "thiet_bi": ra, "thuc_don_dieu_kien": thuc_don}


# ── Sổ dữ kiện của chủ máy ──────────────────────────────────────────────────
def ghi_du_kien(noi_dung: str, *, nguoi: str = "", nguon: str = "nhom",
                ts: float | None = None) -> int:
    """Ghi MỘT dữ kiện chủ máy dạy bot. Trả id; nội dung rỗng thì 0.

    Chủ máy nhắn 11/09/2026 vào nhóm "AI học hỏi" hai tin dạy bot — aptomat và
    điều hòa phòng ngủ là hai thiết bị nối bằng automation, cảm biến phòng
    khách là cảm biến… — và bot không học được chữ nào: ngoài hai chữ đúng/sai,
    không có chỗ nào nhận lời chủ máy. Sổ này là chỗ đó.
    """
    noi = (noi_dung or "").strip()
    if not noi:
        return 0
    with _khoa:
        conn = _db()
        cur = conn.execute(
            "INSERT INTO du_kien (ts, nguoi, noi_dung, nguon) VALUES (?,?,?,?)",
            (float(ts or time.time()), (nguoi or "")[:80], noi[:2000], nguon))
        conn.commit()
        return int(cur.lastrowid or 0)


def du_kien_gan_day(toi_da: int = _TOI_DA_DU_KIEN) -> list[dict[str, Any]]:
    """Dữ kiện mới nhất, xếp cũ → mới, để đưa vào đề của bot."""
    with _khoa:
        rows = _db().execute(
            "SELECT id, ts, noi_dung FROM du_kien ORDER BY ts DESC, id DESC LIMIT ?",
            (int(toi_da),)).fetchall()
    return [{"id": int(r["id"]),
             "luc": datetime.fromtimestamp(float(r["ts"]), _TZ).strftime("%d/%m/%Y %H:%M"),
             "noi_dung": r["noi_dung"]} for r in reversed(rows)]


def co_du_kien_moi(viec: str = "hieu_thiet_bi") -> bool:
    """Có dữ kiện ghi SAU lượt giải gần nhất CỦA VIỆC NÀY không.

    Có thì heartbeat cho giải lại ngay tick sau — chủ máy dạy xong là muốn xem
    bot hiểu ra sao ("tôi vừa đưa 2 dữ kiện xem bot học sao"), không phải chờ
    tới mai.
    """
    with _khoa:
        conn = _db()
        dk = conn.execute("SELECT MAX(ts) FROM du_kien").fetchone()[0]
        lg = conn.execute("SELECT MAX(ts) FROM lan_giai WHERE viec=?", (viec,)).fetchone()[0]
    return dk is not None and (lg is None or float(dk) > float(lg))


def nhan_du_kien(text: str, *, nguoi: str = "") -> Optional[str]:
    """Tin dạy thường (không phải câu chấm) trong nhóm học hỏi → dữ kiện.

    Trả câu báo đã nhận; tin rỗng thì None để tin đi tiếp như thường.
    """
    id_ = ghi_du_kien(text, nguoi=nguoi, nguon="nhom")
    if not id_:
        return None
    return (f"📝 Em ghi dữ kiện #{id_} vào sổ học. Vài phút nữa em xem lại thiết bị "
            "có dùng dữ kiện này, rồi báo anh em hiểu ra sao.")


# ── Bot giải ────────────────────────────────────────────────────────────────
def _chia(ho: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Chia đề thành từng lượt gọi, KHÔNG tách các mã đổi cùng lúc với nhau.

    Bot chỉ nhận ra hai mã là một thiết bị khi thấy cả hai trong cùng một đề.
    """
    theo_ma = {x["ma"]: x for x in ho}
    goc = {m: m for m in theo_ma}

    def tim(m: str) -> str:
        while goc[m] != m:
            goc[m] = goc[goc[m]]
            m = goc[m]
        return m

    for x in ho:
        for k in x.get("doi_cung_luc") or []:
            if k["ma"] in goc:
                goc[tim(x["ma"])] = tim(k["ma"])
    cum: dict[str, list[dict[str, Any]]] = {}
    for m in sorted(theo_ma):
        cum.setdefault(tim(m), []).append(theo_ma[m])
    phan: list[list[dict[str, Any]]] = []
    hien: list[dict[str, Any]] = []
    for c in sorted(cum.values(), key=len, reverse=True):
        if hien and len(hien) + len(c) > _TOI_DA_MOI_LUOT:
            phan.append(hien)
            hien = []
        hien = hien + c
    if hien:
        phan.append(hien)
    return phan


def _model() -> str:
    """Cùng khoá `mqtt.bai_hoc.model` với các phần học hỏi khác; chưa đặt thì
    model `reason` — việc ở đây là đọc bảng số rồi suy luận, không phải tán gẫu."""
    from services import bai_hoc
    from services.agent.orchestrator import _main_model

    return bai_hoc.model_hoc() or _main_model("reason")


def _goi_model(model: str, huong: str, de: str) -> dict[str, Any]:
    """Lời gọi TÁCH BIỆT: system prompt chỉ có hướng dẫn, không tool, không
    ngữ cảnh nhà thông minh — chủ máy chốt "promt chỉ duy mình hướng dẫn để
    tránh nhiễu". Khuôn theo `bai_hoc._ai_cung_y`."""
    from services.agent.runtime import call_model

    return call_model(
        model,
        [{"role": "system", "content": huong},
         {"role": "user", "content": de}],
        timeout=180, max_tokens=6000,
        response_format={"type": "json_object"},
        no_smart_home=True, allowed_groups=set())


def _doc_json(tho: str) -> Any:
    """Model hay bọc JSON trong khối ```json dù đã xin json_object. Lấy từ `{`
    đầu tới `}` cuối; không đọc được thì None."""
    a, b = tho.find("{"), tho.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(tho[a:b + 1])
    except ValueError:
        return None


def _kiem(data: Any, phan: list[dict[str, Any]],
          thuc_don: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Kiểm câu trả lời của model NGAY TẠI BIÊN. Trả (nhóm hợp lệ, số nhóm loại).

    Model là nguồn ngoài: có thể bịa mã, xếp một mã vào hai nhóm, hoặc bảo học
    một cái cảm biến. Nhóm phạm luật cứng của hướng dẫn thì LOẠI hẳn — sửa hộ
    là giáo viên làm bài thay học trò, và lỗi đó sẽ không bao giờ lộ ra để sửa
    hướng dẫn.

    Nhóm được học phải kèm 1–`_TOI_DA_DIEU_KIEN` khoá `dieu_kien` CÓ trong thực
    đơn. Khoá bịa thì tầng xác suất không bao giờ gặp, thiết bị âm thầm học
    không theo điều kiện nào — lỗi không ai thấy. Code chỉ kiểm khoá CÓ THẬT;
    khoá nào hợp lẽ với thiết bị là việc của bot và người chấm.
    """
    trong_don = {str(x.get("khoa") or "") for x in thuc_don}
    hop_le = {x["ma"] for x in phan}
    bat_duoc = {x["ma"] for x in phan if x.get("ha_bat_duoc")}
    ds = data.get("nhom") if isinstance(data, dict) else None
    if not isinstance(ds, list):
        return [], 0
    ra: list[dict[str, Any]] = []
    loai_bo = 0
    da_co: set[str] = set()
    for g in ds:
        if not isinstance(g, dict):
            loai_bo += 1
            continue
        ma = [m for m in dict.fromkeys(x for x in (g.get("ma") or []) if isinstance(x, str))
              if m in hop_le and m not in da_co]
        hoc = g.get("hoc") is True
        ma_hoc = str(g.get("ma_hoc") or "")
        if not ma or (hoc and (ma_hoc not in ma or ma_hoc not in bat_duoc)):
            loai_bo += 1
            continue
        dk = g.get("dieu_kien") if hoc else []
        if hoc and not (isinstance(dk, list) and all(isinstance(k, str) for k in dk)
                        and 0 < len(set(dk)) <= _TOI_DA_DIEU_KIEN
                        and set(dk) <= trong_don and f"bat_{ma_hoc}" not in dk):
            loai_bo += 1
            continue
        da_co.update(ma)
        nhanh = str(g.get("nguon_nhanh") or "")
        loai = str(g.get("loai") or "")
        try:
            chac = min(1.0, max(0.0, float(g.get("chac"))))
        except (TypeError, ValueError):
            chac = 0.0
        ra.append({"ma": ma, "ma_hoc": ma_hoc if hoc else "",
                   "dieu_kien": sorted(set(dk)),
                   "nguon_nhanh": nhanh if nhanh in ma else "",
                   "loai": loai if loai in _LOAI else "khong_ro",
                   "hoc": hoc, "chac": round(chac, 2),
                   "vi_sao": str(g.get("vi_sao") or "")[:300]})
    return ra, loai_bo


def _ghi_lan(phien_ban: str, model: str, so_ho_so: int, so_nhom: int,
             bo_sot: int, loai_bo: int, loi: str, *, viec: str = "hieu_thiet_bi") -> int:
    with _khoa:
        conn = _db()
        cur = conn.execute(
            "INSERT INTO lan_giai (ts, phien_ban, model, so_ho_so, so_nhom,"
            " bo_sot, loai_bo, loi, viec) VALUES (?,?,?,?,?,?,?,?,?)",
            (time.time(), phien_ban, model, so_ho_so, so_nhom, bo_sot, loai_bo, loi, viec))
        conn.commit()
        return int(cur.lastrowid or 0)


def giai(hs: dict[str, Any]) -> dict[str, Any]:
    """Bot đọc đề theo hướng dẫn, trả các nhóm đã kiểm ở biên.

    Đề gồm hồ sơ đo được VÀ sổ dữ kiện của chủ máy — chủ máy biết nhà mình, số
    đo không biết cái gì nối bằng automation.

    Một phần đề hỏng (model lỗi, JSON không đọc được) là CẢ LƯỢT hỏng: lưu nửa
    đề thì các mã ở nửa kia bị coi là bỏ sót, và kết luận hai nửa lệch phiên.
    """
    huong, ban = huong_dan()
    model = _model()
    du_kien = du_kien_gan_day()
    thuc_don = list(hs.get("thuc_don_dieu_kien") or [])
    ho = list(hs.get("thiet_bi") or [])
    nhom: list[dict[str, Any]] = []
    loai_bo = 0
    loi = ""
    for phan in _chia(ho):
        de = json.dumps({"so_ngay": hs.get("so_ngay"), "du_kien_chu_may": du_kien,
                         "thuc_don_dieu_kien": thuc_don, "thiet_bi": phan},
                        ensure_ascii=False)
        r = _goi_model(model, huong, de)
        if r.get("error"):
            loi = f"model lỗi: {str(r['error'])[:160]}"
            break
        tho = str(((r.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        data = _doc_json(tho)
        if data is None:
            loi = f"không đọc được JSON: {tho[:120]}"
            break
        hop_le, bo = _kiem(data, phan, thuc_don)
        nhom += hop_le
        loai_bo += bo
    if loi:
        nhom = []
    bo_sot = 0 if loi else len({x["ma"] for x in ho} - {m for g in nhom for m in g["ma"]})
    lan = _ghi_lan(ban, model, len(ho), len(nhom), bo_sot, loai_bo, loi)
    if loi:
        logger.warning({"event": "hieu_thiet_bi_giai_loi", "loi": loi})
    return {"lan_giai": lan, "phien_ban": ban, "nhom": nhom,
            "bo_sot": bo_sot, "loai_bo": loai_bo, "loi": loi}


def giai_mot_thiet_bi(ma: str) -> dict[str, Any]:
    """Chủ máy chỉ đích danh MỘT mã bot bỏ sót → giải ngay, không đợi heartbeat.

    Không viết lại bộ giải: chỉ thu hẹp đầu vào của `ho_so()` xuống còn mã đó
    (cộng những mã đổi CÙNG LÚC với nó — `doi_cung_luc`, để bot vẫn thấy đủ dữ
    kiện trả lời câu "cùng thiết bị") rồi gọi `giai()` như thường. Trả rỗng với
    `loi` nếu không tìm thấy mã trong hồ sơ (đo chưa đủ lịch sử, hoặc mã sai).
    """
    hs = ho_so()
    if not hs or not hs.get("thiet_bi"):
        return {"loi": "chưa đo được hồ sơ nào (HA chưa trả sổ dịch vụ, hoặc chưa có lịch sử)"}
    ca = [x for x in hs["thiet_bi"] if x["ma"] == ma]
    if not ca:
        return {"loi": f"không thấy mã '{ma}' trong hồ sơ đo được"}
    lien_quan = {c["ma"] for x in ca for c in x.get("doi_cung_luc") or []}
    con = [x for x in hs["thiet_bi"] if x["ma"] == ma or x["ma"] in lien_quan]
    kq = giai({**hs, "thiet_bi": con})
    if not kq["loi"]:
        ghi = ghi_ket_qua(kq["lan_giai"], kq["nhom"])
        kq["moi"] = len(ghi["moi"])
        kq["lap_lai"] = len(ghi["lap_lai"])
    return kq


# ── Sổ kết luận ─────────────────────────────────────────────────────────────
def _cau_hoi(g: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Một nhóm bot trả → các câu được chấm riêng: (loại, khoá, giá trị).

    Khoá câu `hoc` là mã học — ổn định qua các lượt. Khoá hai câu kia là tập mã
    của nhóm: câu hỏi chính là "tập này có phải một thiết bị không", đổi tập
    là đổi câu.
    """
    khoa_nhom = "|".join(sorted(g["ma"]))
    ra: list[tuple[str, str, dict[str, Any]]] = []
    if len(g["ma"]) > 1:
        ra.append(("cung_thiet_bi", khoa_nhom, {"ma": sorted(g["ma"])}))
        if g["nguon_nhanh"]:
            ra.append(("nguon_nhanh", khoa_nhom, {"nguon_nhanh": g["nguon_nhanh"]}))
    ra.append(("hoc", g["ma_hoc"] or sorted(g["ma"])[0],
               {"hoc": g["hoc"], "loai": g["loai"]}))
    if g["hoc"]:
        # Chấm RIÊNG: học đúng thiết bị mà chọn sai điều kiện (cảm biến phòng
        # khác) vẫn là bài sai — đúng lỗi chủ máy bắt được 11/09/2026.
        ra.append(("dieu_kien", g["ma_hoc"],
                   {"dieu_kien": sorted(g.get("dieu_kien") or [])}))
    return ra


def ghi_ket_qua(lan: int, nhom: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Lưu kết luận của một lượt giải.

    Trả ``{"moi": [...], "lap_lai": [...]}``:

    * ``moi`` — câu MỚI hoặc VỪA ĐỔI: cần kể lại, và có thể cần hỏi. Câu y hệt
      lần trước thì không hỏi lại — chủ máy đã thấy rồi.
    * ``lap_lai`` — bot lặp lại đúng câu từng bị chấm SAI. Không dùng, không
      hỏi lại, nhưng phải kể ra: đó là dấu hiệu hướng dẫn còn thiếu, việc của
      giáo viên.

    Mã bot bỏ sót trong lượt này GIỮ kết luận cũ: bỏ sót không phải là đổi ý.
    """
    now = time.time()
    moi: list[dict[str, Any]] = []
    lap_lai: list[dict[str, Any]] = []
    ma_moi = {m for g in nhom for m in g["ma"]}
    con: set[tuple[str, str]] = set()
    with _khoa:
        conn = _db()
        for g in nhom:
            for loai, khoa, gt in _cau_hoi(g):
                con.add((loai, khoa))
                _ghi_mot_cau(conn, lan, now, loai, khoa, gt, g, moi, lap_lai)
        for r in conn.execute(
                "SELECT id, loai_cau_hoi, khoa, nhom FROM quyet_dinh WHERE hieu_luc=1"
        ).fetchall():
            if (r["loai_cau_hoi"], r["khoa"]) in con:
                continue
            if r["loai_cau_hoi"] not in _LOAI_CUA_LUOT_HIEU:
                continue
            if ma_moi & set(json.loads(r["nhom"]).get("ma") or []):
                conn.execute("UPDATE quyet_dinh SET hieu_luc=0 WHERE id=?", (r["id"],))
        conn.commit()
    return {"moi": moi, "lap_lai": lap_lai}


def _ghi_mot_cau(conn: sqlite3.Connection, lan: int, now: float, loai: str, khoa: str,
                 gt: dict[str, Any], g: dict[str, Any],
                 moi: list[dict[str, Any]], lap_lai: list[dict[str, Any]]) -> None:
    """Lưu MỘT câu: y hệt câu đang hiệu lực thì chỉ cập nhật lý do; đổi thì câu
    cũ hết hiệu lực; lặp lại đúng điều từng bị chấm sai thì ghi 'sai' ngay.

    Dùng chung cho lượt hiểu thiết bị (`ghi_ket_qua`) và tầng thói quen
    (`ghi_ngoai_vi`) — một luật lưu, một thang chấm."""
    nhom_json = json.dumps(g, ensure_ascii=False)
    s = json.dumps(gt, ensure_ascii=False, sort_keys=True)
    cu = conn.execute(
        "SELECT id, gia_tri FROM quyet_dinh"
        " WHERE loai_cau_hoi=? AND khoa=? AND hieu_luc=1",
        (loai, khoa)).fetchone()
    if cu and cu["gia_tri"] == s:
        # Giữ lý do mới nhất để người chấm đọc, không hỏi lại.
        conn.execute("UPDATE quyet_dinh SET nhom=? WHERE id=?", (nhom_json, cu["id"]))
        return
    if cu:
        conn.execute("UPDATE quyet_dinh SET hieu_luc=0 WHERE id=?", (cu["id"],))
    da_sai = conn.execute(
        "SELECT 1 FROM quyet_dinh WHERE loai_cau_hoi=? AND khoa=?"
        " AND gia_tri=? AND ket_qua='sai' LIMIT 1",
        (loai, khoa, s)).fetchone() is not None
    cur = conn.execute(
        "INSERT INTO quyet_dinh (lan_giai, ts, loai_cau_hoi, khoa,"
        " gia_tri, nhom, ket_qua, cham_boi) VALUES (?,?,?,?,?,?,?,?)",
        (lan, now, loai, khoa, s, nhom_json,
         "sai" if da_sai else "cho", "lap_lai" if da_sai else ""))
    (lap_lai if da_sai else moi).append({
        "id": int(cur.lastrowid or 0), "loai_cau_hoi": loai,
        "khoa": khoa, "gia_tri": gt, "nhom": g})


def ghi_ngoai_vi(lan: int, ket_luan: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Lưu kết luận NGOẠI VI của tầng thói quen — mỗi thiết bị một câu `ngoai_vi`.

    Mỗi mục ``{"ma_hoc", "khu_vuc", "ngoai_vi": [{"ma", "vai_tro"}], "chac",
    "vi_sao"}`` (đã kiểm ở biên trong `thoi_quen_nha`). `nhom` mang `ma` =
    [mã học] để tin hỏi và phần vô hiệu theo mã đọc được như mọi câu khác.
    """
    now = time.time()
    moi: list[dict[str, Any]] = []
    lap_lai: list[dict[str, Any]] = []
    with _khoa:
        conn = _db()
        for k in ket_luan:
            g = {"ma": [k["ma_hoc"]], "ma_hoc": k["ma_hoc"],
                 "chac": k["chac"], "vi_sao": k["vi_sao"]}
            gt = {"khu_vuc": k["khu_vuc"], "ngoai_vi": k["ngoai_vi"]}
            _ghi_mot_cau(conn, lan, now, "ngoai_vi", k["ma_hoc"], gt, g, moi, lap_lai)
        conn.commit()
    return {"moi": moi, "lap_lai": lap_lai}


def ghi_thoi_quen(lan: int, ket_luan: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Lưu kết luận ĐỌC THÓI QUEN — mỗi thiết bị một câu `thoi_quen`.

    Mỗi mục đã kiểm ở biên trong `thoi_quen_nha.kiem_thoi_quen`. `gia_tri` chỉ
    mang ĐIỀU KIỆN (thứ tầng xác suất sẽ dùng); lời văn thói quen nằm ở `nhom`,
    để bot viết lại câu chữ khác đi mà điều kiện y hệt thì không thành câu hỏi
    mới. `doc_luc` cho `thoi_quen_nha._can_doc_lai` biết lần đọc gần nhất.
    """
    now = time.time()
    moi: list[dict[str, Any]] = []
    lap_lai: list[dict[str, Any]] = []
    with _khoa:
        conn = _db()
        for k in ket_luan:
            g = {"ma": [k["ma_hoc"]], "ma_hoc": k["ma_hoc"], "chac": k["chac"],
                 "vi_sao": k["vi_sao"], "thoi_quen_bat": k["bat"]["thoi_quen"],
                 "thoi_quen_tat": k["tat"]["thoi_quen"], "ngoai_vi": k["ngoai_vi"],
                 "ten_ngoai_vi": k.get("ten_ngoai_vi") or {}, "doc_luc": now}
            gt = {"bat": k["bat"]["dieu_kien"], "tat": k["tat"]["dieu_kien"]}
            _ghi_mot_cau(conn, lan, now, "thoi_quen", k["ma_hoc"], gt, g, moi, lap_lai)
        conn.commit()
    return {"moi": moi, "lap_lai": lap_lai}


def ngoai_vi_hoc() -> dict[str, dict[str, Any]]:
    """Ngoại vi bot chọn cho từng mã được học — bỏ kết luận bị chấm sai."""
    hoc = set(thiet_bi_hoc())
    return {d["khoa"]: d["gia_tri"] for d in dang_hieu_luc()
            if d["loai_cau_hoi"] == "ngoai_vi" and d["ket_qua"] != "sai"
            and d["khoa"] in hoc}


def dang_hieu_luc() -> list[dict[str, Any]]:
    """Mọi kết luận đang hiệu lực, đã giải JSON — cho tầng học và người chấm."""
    with _khoa:
        rows = _db().execute(
            "SELECT * FROM quyet_dinh WHERE hieu_luc=1 ORDER BY id").fetchall()
    return [{**dict(r), "gia_tri": json.loads(r["gia_tri"]),
             "nhom": json.loads(r["nhom"])} for r in rows]


def thiet_bi_hoc() -> list[str]:
    """Mã tầng học được học — theo kết luận đang hiệu lực, bỏ câu bị chấm sai.

    Nhóm bị chấm "không phải một thiết bị" thì cũng thôi học theo nhóm đó cho
    tới lượt giải sau: học tiếp là học trên một kết luận đã biết là sai.
    """
    ds = dang_hieu_luc()
    nhom_sai = {d["khoa"] for d in ds
                if d["loai_cau_hoi"] == "cung_thiet_bi" and d["ket_qua"] == "sai"}
    return sorted(
        d["khoa"] for d in ds
        if d["loai_cau_hoi"] == "hoc" and d["ket_qua"] != "sai"
        and d["gia_tri"].get("hoc")
        and "|".join(sorted(d["nhom"].get("ma") or [])) not in nhom_sai)


def dieu_kien_hoc() -> dict[str, list[str]]:
    """Điều kiện bot chọn cho từng mã được học — bỏ kết luận bị chấm sai.

    Mã được học mà chưa có kết luận điều kiện (sổ trước 11/09/2026, hoặc câu
    điều kiện vừa bị chấm sai) thì KHÔNG có mục ở đây: tầng xác suất học nó
    không kèm điều kiện nào, chỉ còn tỉ lệ nền — không bao giờ đủ để gợi ý.
    Thiếu kết luận thì im, không rơi về "mọi cảm biến cả nhà" như bản cũ.
    """
    hoc = set(thiet_bi_hoc())
    return {d["khoa"]: list(d["gia_tri"].get("dieu_kien") or [])
            for d in dang_hieu_luc()
            if d["loai_cau_hoi"] == "dieu_kien" and d["ket_qua"] != "sai"
            and d["khoa"] in hoc}


# ── CRUD cho tab Học hỏi (chủ máy xem / sửa / xoá / thêm tay) ────────────────
def xoa_ket_luan(id_: int) -> bool:
    """Chủ máy xoá hẳn một kết luận (dòng quyết định). Trả False nếu không có.

    Xoá khác chấm-sai: chấm-sai giữ dòng lại để thang tin cậy đếm; xoá là bỏ
    hẳn khỏi sổ khi kết luận đó rác (mã đã đổi tên, thiết bị gỡ đi…)."""
    with _khoa:
        conn = _db()
        conn.execute("DELETE FROM quyet_dinh WHERE id=?", (int(id_),))
        n = conn.total_changes
        conn.commit()
    if n:
        logger.info({"event": "hieu_xoa_ket_luan", "id": int(id_)})
    return n > 0


def sua_dieu_kien_ket_luan(khoa_hoc: str, dieu_kien_moi: list[str]) -> bool | str:
    """Chủ máy sửa TRỰC TIẾP điều kiện của một thiết bị đã học — trên sơ đồ
    kích hoạt hoặc trong "Bot hiểu thiết bị", trước hay sau khi chấm đều được.

    Có dòng 'dieu_kien' cho `khoa_hoc` (bất kể đang cho/dung/sai) thì SỬA đè;
    chưa có (bot chưa từng đề xuất điều kiện cho thiết bị này) thì THÊM MỚI,
    coi như chủ máy vừa dạy — ``ket_qua='dung', cham_boi='chu_may'`` ngay,
    khỏi phải tự chấm lại cái mình vừa gõ.

    Trả ``True`` khi sửa xong, hoặc một câu tiếng Việt giải thích lý do từ
    chối (khoá lạ / rỗng / quá 5 điều kiện) — KHÔNG tin dữ liệu từ web, kiểm
    lại đúng luật đã áp cho bot trong `_kiem`."""
    khoa_hoc = (khoa_hoc or "").strip()
    if not khoa_hoc:
        return "Thiếu mã thiết bị."
    ds = sorted({str(k).strip() for k in (dieu_kien_moi or []) if str(k).strip()})
    if not ds:
        return "Thiếu điều kiện — xoá hẳn kết luận thì dùng nút Xoá."
    if len(ds) > _TOI_DA_DIEU_KIEN:
        return f"Tối đa {_TOI_DA_DIEU_KIEN} điều kiện cho một thiết bị."
    if ds == [f"bat_{khoa_hoc}"] or khoa_hoc in ds:
        return "Không được lấy chính thiết bị đang học làm điều kiện của nó."
    # Thực đơn ĐẦY ĐỦ (điều kiện môi trường + `bat_<mã>` thiết bị khác) — cùng
    # nguồn bot đã dùng khi tự đề xuất, xem `ho_so()`. Chỉ gọi
    # `boi_canh_nha.thuc_don_dieu_kien()` sẽ bỏ sót mọi khoá `bat_<mã>`.
    hs = ho_so()
    thuc_don = {str(m.get("khoa")) for m in (hs.get("thuc_don_dieu_kien") or [])}
    la = [k for k in ds if k not in thuc_don]
    if la:
        return f"Khoá không có trong thực đơn điều kiện hiện tại: {', '.join(la)}."
    gia_tri = json.dumps({"dieu_kien": ds}, ensure_ascii=False)
    with _khoa:
        conn = _db()
        r = conn.execute(
            "SELECT id, ket_qua FROM quyet_dinh"
            " WHERE loai_cau_hoi='dieu_kien' AND khoa=? AND hieu_luc=1",
            (khoa_hoc,)).fetchone()
        if r:
            if r["ket_qua"] == "cho":
                conn.execute("UPDATE quyet_dinh SET gia_tri=? WHERE id=?",
                             (gia_tri, int(r["id"])))
            else:
                conn.execute(
                    "UPDATE quyet_dinh SET gia_tri=?, ket_qua='dung',"
                    " cham_boi='chu_may', cham_luc=? WHERE id=?",
                    (gia_tri, time.time(), int(r["id"])))
        else:
            lan = conn.execute("SELECT MAX(id) FROM lan_giai").fetchone()[0] or 0
            conn.execute(
                "INSERT INTO quyet_dinh (lan_giai, ts, loai_cau_hoi, khoa,"
                " gia_tri, nhom, ket_qua, cham_boi, cham_luc)"
                " VALUES (?,?,'dieu_kien',?,?,?,?,?,?)",
                (int(lan), time.time(), khoa_hoc, gia_tri, "{}",
                 "dung", "chu_may", time.time()))
        conn.commit()
    logger.info({"event": "hieu_sua_dieu_kien", "khoa": khoa_hoc, "dieu_kien": ds})
    return True


def xoa_du_kien(id_: int) -> bool:
    """Xoá một dữ kiện chủ máy đã dạy. Trả False nếu không có dòng đó."""
    with _khoa:
        conn = _db()
        conn.execute("DELETE FROM du_kien WHERE id=?", (int(id_),))
        n = conn.total_changes
        conn.commit()
    if n:
        logger.info({"event": "hieu_xoa_du_kien", "id": int(id_)})
    return n > 0


def sua_du_kien(id_: int, noi_dung: str) -> bool:
    """Sửa nội dung một dữ kiện. Nội dung rỗng thì không sửa (dùng xoá để bỏ)."""
    noi = (noi_dung or "").strip()
    if not noi:
        return False
    with _khoa:
        conn = _db()
        conn.execute("UPDATE du_kien SET noi_dung=? WHERE id=?",
                     (noi[:2000], int(id_)))
        n = conn.total_changes
        conn.commit()
    if n:
        logger.info({"event": "hieu_sua_du_kien", "id": int(id_)})
    return n > 0


def ghi_huong_dan(noi_dung: str) -> bool:
    """Chủ máy sửa hướng dẫn bản chạy thật (DATA_DIR), không đụng bản gốc repo.

    Ghi thẳng đè lên `_duong_huong_dan()`; lượt giải sau dùng ngay bản mới và
    `huong_dan()` tính lại phiên bản (sha256) nên điểm chấm không lẫn hai bản."""
    noi = noi_dung if isinstance(noi_dung, str) else ""
    if not noi.strip():
        return False
    p = _duong_huong_dan()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(noi, encoding="utf-8")
    logger.info({"event": "hieu_ghi_huong_dan",
                 "phien_ban": hashlib.sha256(noi.encode("utf-8")).hexdigest()[:12]})
    return True


def lich_su_giai(toi_da: int = 50) -> list[dict[str, Any]]:
    """Các lượt bot giải hiểu thiết bị, mới → cũ, cho mục 'lịch sử các lượt giải'."""
    with _khoa:
        rows = _db().execute(
            "SELECT id, ts, phien_ban, model, so_ho_so, so_nhom, bo_sot,"
            " loai_bo, loi FROM lan_giai WHERE viec='hieu_thiet_bi'"
            " ORDER BY id DESC LIMIT ?",
            (int(toi_da),)).fetchall()
    return [{"id": int(r["id"]),
             "luc": datetime.fromtimestamp(float(r["ts"]), _TZ).strftime("%d/%m/%Y %H:%M"),
             "phien_ban": r["phien_ban"], "model": r["model"],
             "so_ho_so": int(r["so_ho_so"]), "so_nhom": int(r["so_nhom"]),
             "bo_sot": int(r["bo_sot"]), "loai_bo": int(r["loai_bo"]),
             "loi": r["loi"]} for r in rows]


def so_do_kich_hoat(*, kem_so_do: bool = True) -> list[dict[str, Any]]:
    """Sơ đồ kích hoạt từng thiết bị học được: NHÂN TỐ CHÍNH ← ĐIỀU KIỆN + NGOẠI VI.

    - nhân tố chính: thiết bị được bật (mã học);
    - ngoại vi: cảm biến/thiết bị đi kèm — điều kiện dạng `bat_<mã>` và các mã
      khác cùng nhóm vật lý;
    - điều kiện: lux / nhiệt độ / có người / buổi / mùa… (các khoá còn lại).
    Chỉ vẽ thứ bot đã kết luận (bỏ câu bị chấm sai), khớp `dieu_kien_hoc`.

    `kem_so_do=True` thì mỗi mục điều kiện/ngoại vi kèm số đo THẬT (`do`) —
    mấy % lần bật rơi vào nhãn hay gặp nhất, xem
    `du_doan_nha.dem_dieu_kien_thiet_bi`.

    NHƯNG phần đo TỐN VÀI GIÂY (dựng lại bối cảnh từng ô 30 phút), nên đường
    web tách làm hai: `/api/hoc-hoi/so-do` gọi `kem_so_do=False` để sơ đồ hiện
    NGAY, rồi `/api/hoc-hoi/so-do/do` đo sau và điền vào. Gộp một lượt thì mất
    47 giây (đo thật 12/09/2026, 13 thiết bị) — trình duyệt bỏ cuộc trước và
    chủ máy chỉ thấy "chưa có thiết bị nào được học".
    """
    from services import boi_canh_nha, du_doan_nha
    ten = _ten_ha()
    dk = dieu_kien_hoc()
    thanh_vien: dict[str, list[str]] = {}
    for d in dang_hieu_luc():
        if (d["loai_cau_hoi"] == "hoc" and d["ket_qua"] != "sai"
                and d["gia_tri"].get("hoc")):
            thanh_vien[d["khoa"]] = sorted(d["nhom"].get("ma") or [])
    ra: list[dict[str, Any]] = []
    # Bộ nhớ ô DÙNG CHUNG cho mọi thiết bị: 13 thiết bị chỉ chạm 187 ô duy nhất
    # (đo 12/09/2026), chia sẻ thì tổng còn ~6 giây thay vì cộng dồn từng cái.
    bo_nho_o: dict[int, dict[str, str]] = {}
    for khoa in thiet_bi_hoc():
        khoa_dieu_kien = list(dk.get(khoa, []))
        do_dem = (du_doan_nha.dem_dieu_kien_thiet_bi(
                      khoa, khoa_dieu_kien, bo_nho_o=bo_nho_o)
                  if kem_so_do else {})
        ngoai_vi: list[dict[str, Any]] = []
        dieu_kien: list[dict[str, Any]] = []
        da_them: set[str] = set()
        for k in khoa_dieu_kien:
            do = ((do_dem.get(k) or {"nhan_hay_gap": "", "ty_le": 0.0, "mau": 0})
                  if kem_so_do else None)
            if k.startswith("bat_"):
                nv = _nhan(k[len("bat_"):], ten)
                if nv not in da_them:
                    da_them.add(nv)
                    ngoai_vi.append({"khoa": k, "ten": nv, "do": do})
            else:
                dieu_kien.append({"khoa": k, "ten": boi_canh_nha.ten_dieu_kien(k), "do": do})
        for m in thanh_vien.get(khoa, []):
            if m != khoa:
                nv = _nhan(m, ten)
                if nv not in da_them:
                    da_them.add(nv)
                    ngoai_vi.append({"khoa": "", "ten": nv, "do": None})
        ra.append({"khoa": khoa, "nhan_to_chinh": _nhan(khoa, ten),
                   "ngoai_vi": ngoai_vi, "dieu_kien": dieu_kien})
    return ra


# ── Chấm và thang tin cậy ───────────────────────────────────────────────────
def cham(id_: int, dung: bool, *, cham_boi: str, ghi_chu: str = "") -> bool:
    """Chấm MỘT kết luận đang chờ. Trả False nếu không có hoặc đã chấm rồi —
    chấm hai lần không được cộng dồn thành tích."""
    kq = "dung" if dung else "sai"
    with _khoa:
        conn = _db()
        r = conn.execute("SELECT loai_cau_hoi, ket_qua FROM quyet_dinh WHERE id=?",
                         (int(id_),)).fetchone()
        if not r or r["ket_qua"] != "cho":
            return False
        conn.execute(
            "UPDATE quyet_dinh SET ket_qua=?, cham_boi=?, ghi_chu=?, cham_luc=?"
            " WHERE id=?", (kq, cham_boi, (ghi_chu or "")[:300], time.time(), int(id_)))
        conn.execute(
            f"INSERT INTO thanh_tich (loai_cau_hoi, {kq}) VALUES (?,1)"
            f" ON CONFLICT(loai_cau_hoi) DO UPDATE SET {kq}={kq}+1",
            (r["loai_cau_hoi"],))
        conn.commit()
    return True


def sua_cham(id_: int, dung: bool, *, cham_boi: str, ghi_chu: str = "") -> bool:
    """Chấm, hoặc CHẤM LẠI, một kết luận. Trả False nếu không có kết luận đó.

    Chủ máy là người chấm cuối cùng. 11/09/2026 Claude chấm "đúng" cho việc học
    công tắc "cảm biến phòng khách living room"; chủ máy nói đó là cảm biến.
    Điểm sai phải sửa được, và thành tích phải chuyển theo — không thì thang tin
    cậy đứng trên một con số đã biết là sai.
    """
    kq = "dung" if dung else "sai"
    with _khoa:
        conn = _db()
        r = conn.execute(
            "SELECT loai_cau_hoi, ket_qua, cham_boi FROM quyet_dinh WHERE id=?",
            (int(id_),)).fetchone()
        if not r:
            return False
        # Câu `lap_lai` mang chữ "sai" nhưng chưa từng được cộng vào thành tích.
        cu = "cho" if r["cham_boi"] == "lap_lai" else r["ket_qua"]
        conn.execute(
            "UPDATE quyet_dinh SET ket_qua=?, cham_boi=?, ghi_chu=?, cham_luc=?"
            " WHERE id=?", (kq, cham_boi, (ghi_chu or "")[:300], time.time(), int(id_)))
        if cu != kq:
            if cu in ("dung", "sai"):
                conn.execute(f"UPDATE thanh_tich SET {cu}=MAX(0, {cu}-1)"
                             " WHERE loai_cau_hoi=?", (r["loai_cau_hoi"],))
            conn.execute(
                f"INSERT INTO thanh_tich (loai_cau_hoi, {kq}) VALUES (?,1)"
                f" ON CONFLICT(loai_cau_hoi) DO UPDATE SET {kq}={kq}+1",
                (r["loai_cau_hoi"],))
        conn.commit()
    return True


def _thanh_tich(loai: str) -> tuple[int, int]:
    with _khoa:
        r = _db().execute("SELECT dung, sai FROM thanh_tich WHERE loai_cau_hoi=?",
                          (loai,)).fetchone()
    return (int(r["dung"]), int(r["sai"])) if r else (0, 0)


def diem(loai: str) -> float:
    """Tỉ lệ đúng làm trơn Laplace — cùng công thức `du_doan_nha.diem`."""
    dung, sai = _thanh_tich(loai)
    return (dung + 1) / (dung + sai + 2)


def sai_gan_day(loai: str) -> int:
    from services.du_doan_nha import _CUA_SO_TUT_CAP

    with _khoa:
        rows = _db().execute(
            "SELECT ket_qua FROM quyet_dinh WHERE loai_cau_hoi=?"
            " AND ket_qua IN ('dung','sai') AND cham_luc IS NOT NULL"
            " ORDER BY cham_luc DESC, id DESC LIMIT ?",
            (loai, _CUA_SO_TUT_CAP)).fetchall()
    return sum(1 for r in rows if r["ket_qua"] == "sai")


def can_hoi(loai: str) -> bool:
    """Loại câu này còn phải hỏi người chấm không — cùng thang `du_doan_nha.cap`.

    Chủ máy chốt: chính xác tăng dần thì bỏ dần câu hỏi. Đủ 50 lượt chấm mà
    đúng từ 95% thì bot tự quyết; đang tự quyết mà sai 2 trong 10 lượt gần
    nhất thì quay lại hỏi — đường xuống nhạy hơn đường lên.
    """
    from services import du_doan_nha as dd

    if sai_gan_day(loai) >= dd._SAI_TUT_CAP:
        return True
    dung, sai = _thanh_tich(loai)
    return not (dung + sai >= dd._MAU_LEN_CAP and diem(loai) >= dd._TY_LE_LEN_CAP)


# ── Báo nhóm học hỏi ────────────────────────────────────────────────────────
def _nhan(ma: str, ten: dict[str, str]) -> str:
    """Mã máy → chữ người đọc được.

    Tên chủ máy đặt trong HA nếu có, kèm miền trong ngoặc vuông để "Đèn bếp
    [switch]" và "Đèn bếp [light]" không trông như một. Mã MQTT
    `zigbee2mqtt/Bếp#state_left` thành "Bếp, nút left (MQTT)".
    """
    if "#" in ma or "/" in ma:
        chu_de, _, truong = ma.partition("#")
        s = chu_de.rsplit("/", 1)[-1]
        nut = truong[len("state"):].strip("_") if truong.startswith("state") else truong
        return f"{s}, nút {nut} (MQTT)" if nut else f"{s} (MQTT)"
    mien, _, ten_goc = ma.partition(".")
    return f"{ten.get(ma) or ten_goc} [{mien}]"


def _cau_doc(d: dict[str, Any], ten: dict[str, str]) -> str:
    gt, g = d["gia_tri"], d["nhom"]
    if d["loai_cau_hoi"] == "cung_thiet_bi":
        return " + ".join(_nhan(m, ten) for m in gt["ma"]) + " là MỘT thiết bị"
    if d["loai_cau_hoi"] == "nguon_nhanh":
        chinh = g.get("ma_hoc") or sorted(g["ma"])[0]
        return (f"{_nhan(chinh, ten)}: báo tin nhanh nhất qua "
                f"{_nhan(gt['nguon_nhanh'], ten)}")
    if d["loai_cau_hoi"] == "dieu_kien":
        from services import boi_canh_nha

        ds = [f"{_nhan(k[len('bat_'):], ten)} vừa bật hoặc tắt" if k.startswith("bat_")
              else boi_canh_nha.ten_dieu_kien(k) for k in gt.get("dieu_kien") or []]
        return (f"Học {_nhan(d['khoa'], ten)} theo: "
                + (", ".join(ds) if ds else "không điều kiện nào"))
    if d["loai_cau_hoi"] == "ngoai_vi":
        kv = gt.get("khu_vuc") or "chưa rõ khu vực"
        ds = [f"{x.get('ten') or _nhan(x['ma'], ten)} "
              f"({_VAI_TRO_DOC.get(x.get('vai_tro'), 'khác')})"
              for x in gt.get("ngoai_vi") or []]
        return (f"{_nhan(d['khoa'], ten)} ở {kv}, đi theo: "
                + (", ".join(ds) if ds else "chưa có ngoại vi nào"))
    if d["loai_cau_hoi"] == "thoi_quen":
        phan = []
        for chieu, chu in (("bat", "bật"), ("tat", "tắt")):
            ds = gt.get(chieu) or []
            gio = [f"{x['tu']}–{x['den']}" for x in ds if x["ma"] == "gio"]
            dk = ([f"trong {' hoặc '.join(gio)}"] if gio else []) + [
                _dieu_kien_doc(x, g.get("ten_ngoai_vi") or {}, ten) for x in ds if x["ma"] != "gio"]
            loi = g.get(f"thoi_quen_{chieu}") or ""
            phan.append(f"{chu}: {loi}" + (f" (khi {', '.join(dk)})" if dk else " (không điều kiện)"))
        return f"{_nhan(d['khoa'], ten)} — " + "; ".join(phan)
    if gt.get("hoc"):
        return f"Học thói quen {_nhan(d['khoa'], ten)}"
    return (f"Không học {_nhan(d['khoa'], ten)} "
            f"({_LOAI_DOC.get(gt.get('loai'), 'chưa rõ là gì')})")


def _dieu_kien_doc(x: dict[str, Any], ten_nv: dict[str, str], ten: dict[str, str]) -> str:
    """Một điều kiện thói quen thành chữ người đọc: "Hiện diện bếp là on"."""
    if x["ma"] == "ngay":
        return "ngày thường" if x["la"] == "thuong" else "cuối tuần"
    if x["ma"] == "mua":
        return {"lanh": "mùa lạnh", "chuyen": "lúc chuyển mùa"}.get(x["la"], "mùa nóng")
    nhan = ten_nv.get(x["ma"]) or _nhan(x["ma"], ten)
    if "duoi" in x:
        return f"{nhan} dưới {x['duoi']:g}"
    if "tren" in x:
        return f"{nhan} trên {x['tren']:g}"
    return f"{nhan} là {x.get('la')}"


def _ten_ha() -> dict[str, str]:
    """Mã HA → tên chủ nhà đặt, để câu hỏi viết bằng tên người đọc được."""
    from services import ha_client

    return {str(s.get("entity_id") or ""): str((s.get("attributes") or {}).get("friendly_name"))
            for s in (ha_client.get_states() or [])
            if (s.get("attributes") or {}).get("friendly_name")}


#: Câu đã gửi mà quá ngần này chưa được trả lời thì thôi chờ, hỏi lại đúng câu
#: đó — tin có thể đã trôi trong nhóm.
_CHO_TRA_LOI_GIAY = 24 * 3600


def cau_hoi_tiep(ten: dict[str, str] | None = None) -> tuple[str, int]:
    """MỘT câu xác minh kế tiếp cho chủ máy: (lời hỏi, id). ("", 0) = không hỏi.

    Chủ máy chốt 11/09/2026: *"tin gửi để tôi xác minh đang dài quá. Tôi muốn nó
    xác minh lần lượt, khi tôi phản hồi xong thì mới gửi xác minh tiếp"*. Nên:

    * câu trước còn chờ trả lời (chưa quá `_CHO_TRA_LOI_GIAY`) thì không hỏi thêm;
    * chỉ hỏi câu CHƯA ai chấm — câu Claude đã chấm chắc thì chủ máy khỏi đọc;
    * loại câu bot đã đủ tin (`can_hoi` = False) thì không hỏi.

    Không tự đánh dấu đã hỏi: nơi GỬI đánh dấu sau khi gửi được
    (`danh_dau_da_hoi`), để câu gửi hỏng không chặn các câu sau.
    """
    now = time.time()
    cho = [d for d in dang_hieu_luc() if d["ket_qua"] == "cho"]
    if any(d.get("hoi_luc") and now - float(d["hoi_luc"]) < _CHO_TRA_LOI_GIAY for d in cho):
        return "", 0
    cho = [d for d in cho if can_hoi(d["loai_cau_hoi"])]
    if not cho:
        return "", 0
    d, g = cho[0], cho[0]["nhom"]
    ten = _ten_ha() if ten is None else ten
    vi_sao = f"\nVì sao: {g['vi_sao']}" if g.get("vi_sao") else ""
    con = len(cho) - 1
    loi = (f"❓ Câu #{d['id']}: {_cau_doc(d, ten)} — em chắc "
           f"{round(float(g.get('chac') or 0) * 100)}%.{vi_sao}\n"
           f"Anh gõ «hh {d['id']} đúng» hoặc «hh {d['id']} sai vì …»"
           + (f" — còn {con} câu, anh trả lời xong em hỏi tiếp." if con else "."))
    return loi.replace("_", " "), int(d["id"])


def danh_dau_da_hoi(id_: int) -> None:
    """Câu này đã tới tay chủ máy — chờ trả lời rồi mới hỏi câu sau."""
    with _khoa:
        conn = _db()
        conn.execute("UPDATE quyet_dinh SET hoi_luc=? WHERE id=?", (time.time(), int(id_)))
        conn.commit()


def soan_bao(kq: dict[str, Any], moi: list[dict[str, Any]],
             lap_lai: list[dict[str, Any]], ten: dict[str, str]) -> tuple[str, int]:
    """Tin cho nhóm "AI học hỏi" sau một lượt giải: MỘT dòng tóm tắt, MỘT câu hỏi.

    Bản đầu kể mọi kết luận trong một lượt — 11/09/2026 lúc 19:20 là bốn tin
    dài — và chủ máy bảo "dài quá … xác minh lần lượt". Kết luận nào cũng còn
    trong sổ; tin chỉ nói bot vừa làm gì rồi hỏi đúng một câu (`cau_hoi_tiep`).
    Câu kế tiếp đi kèm câu đáp khi chủ máy chấm xong (`tra_loi`).

    Trả (tin, id câu hỏi kèm theo — 0 nếu không có). Không có gì mới thì
    ("", 0): nhắn "vẫn thế" là làm phiền. Bỏ gạch dưới: Zalo gửi ở markdown.
    """
    if kq.get("loi"):
        return (f"🧠 Bot học hỏi — lượt hiểu thiết bị chưa xong: {kq['loi']}. "
                "Em giữ nguyên các kết luận cũ.").replace("_", " "), 0
    if not moi and not lap_lai:
        return "", 0
    phan = [f"{len(moi)} kết luận mới hoặc vừa đổi"]
    tu_quyet = sum(1 for d in moi if not can_hoi(d["loai_cau_hoi"]))
    if tu_quyet:
        phan.append(f"{tu_quyet} câu em đủ tin để tự quyết")
    if lap_lai:
        phan.append(f"{len(lap_lai)} câu em lặp lại điều từng bị chấm sai nên không dùng")
    if kq.get("bo_sot"):
        phan.append(f"{kq['bo_sot']} mã chưa xếp được")
    tin = (f"🧠 Bot học hỏi vừa xem lại thiết bị nhà (hướng dẫn bản "
           f"{kq.get('phien_ban', '')}): " + ", ".join(phan) + ".")
    cau, id_ = cau_hoi_tiep(ten)
    if cau:
        tin += "\n\n" + cau
    return tin.replace("_", " "), id_


def bao_nhom(tin: str | list[str]) -> int:
    """Gửi bản tin "bot hiểu thiết bị" theo sổ đăng ký `services/thong_bao.py`.

    Khoá `hoc_hoi.hieu_thiet_bi`; chọn kênh ở Cài đặt → Thông báo. Trả số tin
    gửi được, chưa chọn kênh thì trả 0 và KHÔNG rơi về admin — chủ máy chốt
    13/09/2026: mọi thông báo theo cài đặt trên web, không mặc định.

    (Trước đây hàm này đọc `du_doan_nha._kenh_nhan`; câu đó đã sai từ lúc dời
    sang sổ đăng ký nên viết lại luôn, đừng để chú thích chỉ sai đường.)
    """
    from services import thong_bao

    ds = [tin] if isinstance(tin, str) else list(tin)
    return sum(thong_bao.gui("hoc_hoi.hieu_thiet_bi", t) for t in ds if t)


#: Câu chấm: «hh 12 đúng», «hh 11, 32 đúng, ghi chú…», «gy #12 và 13 sai vì …».
#: Tiền tố và hai chữ đúng/sai do CHÍNH bot in ra trong tin hỏi.
_CAU_CHAM = (r"\s*{tien_to}\s*[:,]?\s*(?P<so>#?\d+(?:\s*(?:,|;|&|và|va)?\s*#?\d+)*)"
             r"\s*[,:;.\-]?\s*(?P<chu>đúng|dung|sai)\b[\s,.:;\-]*(?P<con>.*)")


def doc_cau_cham(text: str, tien_to: str) -> Optional[dict[str, Any]]:
    """Đọc câu chấm «<tiền tố> <số…> đúng|sai <ghi chú>».

    Trả None khi tin không mở đầu bằng tiền tố (không phải câu chấm); ``{}`` khi
    mở đầu đúng mà viết sai khuôn (để hỏi lại); còn lại
    ``{"so": [...], "dung": bool, "con": ghi chú}``. Dùng chung cho «hh» (hiểu
    thiết bị) và «gy» (gợi ý bật, `du_doan_nha.tra_loi`) — một khuôn, hai sổ.
    """
    from services.boi_canh_nha import _khong_dau

    phan = (text or "").split()
    if not phan or _khong_dau(phan[0]).strip(":,") != tien_to:
        return None
    m = re.match(_CAU_CHAM.format(tien_to=re.escape(tien_to)), text or "",
                 re.IGNORECASE | re.DOTALL)
    if not m:
        return {}
    return {"so": list(dict.fromkeys(int(x) for x in re.findall(r"\d+", m.group("so")))),
            "dung": _khong_dau(m.group("chu")) == "dung",
            "con": m.group("con").strip()}


def tra_loi(text: str, *, nguoi: str = "") -> Optional[str]:
    """Câu chấm trong nhóm học hỏi. Trả câu đáp; None = không phải câu chấm.

    Tiền tố `hh` và hai chữ đúng/sai do CHÍNH bot in ra trong tin hỏi, nên đây
    không phải danh sách đoán ý người dùng — cùng lý do với
    `orchestrator._TRA_LOI_DUNG`. So không phân biệt hoa thường và nhận cả chữ
    không dấu: chủ máy gõ trên điện thoại.

    Chủ máy nhắn 11/09/2026 «hh 11, 32 đúng, aptomat … là 1 thiết bị, …» và bot
    trả lời "Anh gõ giúp em…" — bản cũ chỉ tách theo dấu cách nên "11," không
    phải số, và phần dạy phía sau bị vứt. Nay số cách nhau bằng dấu cách, dấu
    phẩy hay chữ "và" đều nhận; phần chữ sau đúng/sai vừa là ghi chú của câu
    chấm, vừa được ghi vào sổ dữ kiện để lượt giải sau dùng.

    Chủ máy là người chấm cuối cùng nên câu đã chấm (kể cả do Claude) vẫn chấm
    lại được (`sua_cham`).
    """
    cau = doc_cau_cham(text, "hh")
    if cau is None:
        return None
    if not cau:
        return ("Anh gõ giúp em: «hh <số> đúng» hoặc «hh <số> sai vì …» — nhiều số "
                "thì cách nhau bằng dấu cách hoặc dấu phẩy.")
    so, dung, con = cau["so"], cau["dung"], cau["con"]
    duoc = [x for x in so if sua_cham(x, dung, cham_boi="chu_may", ghi_chu=con)]
    khong = [x for x in so if x not in duoc]
    id_dk = ghi_du_kien(con, nguoi=nguoi, nguon="hh") if con else 0
    dong = []
    if duoc:
        dong.append(f"Em ghi rồi: {', '.join(f'#{x}' for x in duoc)} "
                    f"{'đúng' if dung else 'sai'}.")
        if not dung:
            dong.append("Câu sai em thôi dùng ngay; Claude sẽ xem để sửa hướng dẫn cho em.")
    if id_dk:
        dong.append(f"Phần anh dặn thêm em ghi thành dữ kiện #{id_dk}, "
                    "lượt xem lại tới em dùng luôn.")
    if khong:
        dong.append(f"Không thấy câu nào số: {', '.join(f'#{x}' for x in khong)}.")
    tra = " ".join(dong)
    # Chấm xong thì hỏi câu kế tiếp NGAY trong câu đáp — lần lượt, như chủ máy
    # chốt 11/09/2026. Câu đáp đi thẳng vào nhóm (`zalo_personal._nhom_hoc_hoi`).
    cau, id_hoi = cau_hoi_tiep()
    if cau:
        danh_dau_da_hoi(id_hoi)
        tra += "\n\n" + cau
    return tra


# ── Vòng chạy ───────────────────────────────────────────────────────────────
def chay_mot_lan() -> dict[str, Any]:
    """Heartbeat gọi: đo đề → bot giải → lưu → báo nhóm học hỏi."""
    if not is_enabled():
        return {"bo_qua": "đang tắt"}
    if not _dang_giai.acquire(blocking=False):
        return {"bo_qua": "lượt giải trước chưa xong"}
    try:
        hs = ho_so()
        if not hs:
            return {"bo_qua": "HA chưa trả sổ dịch vụ — giữ kết luận cũ"}
        if not hs["thiet_bi"]:
            return {"bo_qua": "chưa có thiết bị bật tắt nào có lịch sử"}
        kq = giai(hs)
        ghi = (ghi_ket_qua(kq["lan_giai"], kq["nhom"]) if not kq["loi"]
               else {"moi": [], "lap_lai": []})
        ten = {x["ma"]: x["ten"] for x in hs["thiet_bi"] if x.get("ten")}
        tin, id_hoi = soan_bao(kq, ghi["moi"], ghi["lap_lai"], ten)
        gui = bao_nhom(tin) if tin else 0
        if gui and id_hoi:
            danh_dau_da_hoi(id_hoi)
        return {"lan_giai": kq["lan_giai"], "phien_ban": kq["phien_ban"],
                "nhom": len(kq["nhom"]), "moi": len(ghi["moi"]),
                "lap_lai": len(ghi["lap_lai"]), "gui": gui, "loi": kq["loi"]}
    finally:
        _dang_giai.release()


def _reset_for_tests() -> None:
    global _conn
    try:
        if _conn is not None:
            _conn.close()
    except Exception:
        pass
    _conn = None
