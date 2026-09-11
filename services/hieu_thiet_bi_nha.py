"""Tầng HIỂU THIẾT BỊ — bot học hỏi tự đọc hồ sơ thiết bị rồi kết luận.

Chủ máy chốt 11/09/2026, nguyên văn:

    "Việc học hỏi nên học theo các thiết bị bật tắt được chứ các thiết bị
    trạng thái học làm gì. […] Bỏ các thiết bị bật tắt rác, sensor rác,
    sensor lỗi đi"

    "bạn chỉ như là giáo viên tạo hướng dẫn để bot của tôi giải bài toán,
    sau đó xem lại giải đúng không"

Nên việc chia làm bốn phần, và KHÔNG phần nào là danh sách lọc cài cứng:

1. CODE CHỈ ĐO (`ho_so`). Mã nào đổi cùng lúc với mã nào, ai đổi trước, mỗi
   lần đổi có bao nhiêu mã khác đổi theo, HA có lệnh bật không. Code không
   phán thiết bị nào là rác.
2. BOT GIẢI (`giai`). Một lời gọi model mà system prompt CHỈ có hướng dẫn
   (`huong_dan()`) — không persona, không skill, không tool — để khỏi nhiễu.
3. NGƯỜI CHẤM (`cham`, `tra_loi`). Hiện Claude chấm bằng số đo thật
   (`scripts/cham_hieu_thiet_bi.py`), sau này chủ máy chấm trong nhóm Zalo
   "AI học hỏi". Chấm đúng đủ nhiều thì bot thôi hỏi — cùng thang với
   `du_doan_nha.cap`.
4. GIÁO VIÊN SỬA HƯỚNG DẪN. Bản chạy thật nằm trong DATA_DIR để sửa được mà
   không dựng lại ảnh; mỗi lượt giải ghi phiên bản hướng dẫn, để biết điểm
   chấm thuộc bản nào.

Kết luận của bot được `du_doan_nha.hoc()` dùng NGAY — bị chấm sai thì thôi.
Kết luận sai không tự bật được gì: lời gợi ý bật thiết bị vẫn đi qua thang tự
chủ riêng của `du_doan_nha`.

Số đo làm đề (kho thật 11/09/2026) — để người sau hiểu vì sao hồ sơ có từng
trường, KHÔNG phải để code dùng:

* 6 cặp `light.X`/`switch.X` đổi cùng lúc 88–100% cả hai chiều, `switch` đổi
  trước 98–100%; cặp kế tiếp chỉ trùng 9,5%.
* MQTT (zigbee2mqtt) báo trước HA trực tiếp 86–100% số lần, sớm 2–3 ms.
* 30 công tắc cấu hình Frigate: lần nào đổi cũng có 25–29 mã khác đổi cùng
  giây — hệ thống nạp lại, không phải người bật.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
import statistics
import threading
import time
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR, config

logger = logging.getLogger(__name__)

_DB_PATH = Path(DATA_DIR) / "agent" / "hieu_thiet_bi_nha.sqlite"
_HUONG_DAN_GOC = Path(__file__).with_name("huong_dan_hoc") / "hieu_thiet_bi.md"
_conn: Optional[sqlite3.Connection] = None
_khoa = threading.Lock()

#: Hai lần đổi cách nhau không quá ngần này giây thì coi là CÙNG LÚC. Đo
#: 11/09/2026: đèn và công tắc của cùng một bóng lệch trung vị 0–60 ms, MQTT
#: với HA lệch 2–3 ms. Một giây rộng gấp chục lần mà vẫn ngắn hơn một lần người
#: bấm hai công tắc liền nhau.
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

_LOAI = ("bat_tat", "rac", "khong_ro")

_LOAI_DOC = {"rac": "đổi đồng loạt, không phải người bật",
             "khong_ro": "chưa rõ là gì",
             "bat_tat": "chưa đủ lần bật"}

#: Loại câu hỏi được chấm và lên cấp RIÊNG: bot giỏi nhận ra thiết bị trùng
#: chưa chắc đã giỏi chọn nguồn nhanh.
LOAI_CAU_HOI = ("cung_thiet_bi", "nguon_nhanh", "hoc")


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
            " cham_luc REAL)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qd_khoa"
                     " ON quyet_dinh(loai_cau_hoi, khoa, hieu_luc)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS thanh_tich ("
            " loai_cau_hoi TEXT PRIMARY KEY,"
            " dung INTEGER NOT NULL DEFAULT 0,"
            " sai INTEGER NOT NULL DEFAULT 0)"
        )
        conn.commit()
        _conn = conn
    return _conn


# ── Hướng dẫn ───────────────────────────────────────────────────────────────
def _duong_huong_dan() -> Path:
    return Path(DATA_DIR) / "agent" / "hoc_hoi" / "hieu_thiet_bi.md"


def huong_dan() -> tuple[str, str]:
    """(nội dung, phiên bản) của hướng dẫn đang dùng.

    Bản chạy thật nằm trong DATA_DIR để giáo viên sửa được mà không dựng lại
    ảnh. Chưa có thì chép từ bản gốc trong repo — chép MỘT lần, không bao giờ
    ghi đè, cùng luật `skills._ensure_seeded`. Phiên bản là 12 ký tự đầu của
    sha256: đổi một chữ là đổi phiên bản, điểm chấm không lẫn giữa hai bản.
    """
    p = _duong_huong_dan()
    if not p.is_file():
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_HUONG_DAN_GOC, p)
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
    ung_vien = {ma for ma in la_ha
                if ma.split(".")[0] in mien
                and any(du_doan_nha._la_bat(g) for _, g, _ in su_kien[ma])}
    xet = ung_vien | (set(su_kien) - la_ha)

    # Đổi cùng lúc: với mỗi lần đổi, mã khác nào đổi trong ±1 giây (lấy lần
    # gần nhất của mỗi mã), và ai đổi trước. Chia theo giây để khỏi so từng cặp.
    theo_giay: dict[int, list[tuple[float, str]]] = {}
    for ma in xet:
        for t, _, _ in su_kien[ma]:
            theo_giay.setdefault(int(t), []).append((t, ma))
    trung: dict[str, dict[str, int]] = {ma: {} for ma in xet}
    truoc: dict[str, dict[str, int]] = {ma: {} for ma in xet}
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
             "minh_doi_truoc": round(truoc[ma].get(b, 0) / trung[ma][b], 3)}
            for minh, ban, b in xep[:_TOI_DA_KE]]

    # Đề gồm mã bật tắt được, cộng mã ngoài HA đổi cùng lúc với chúng — bản MQTT
    # của cùng một công tắc chính là thứ để trả lời "nguồn nào báo trước".
    ho = set(ung_vien)
    for ma in ung_vien:
        ho.update(x["ma"] for x in doi_cung[ma])

    ten = {str(s.get("entity_id") or ""):
           str((s.get("attributes") or {}).get("friendly_name") or "")
           for s in (ha_client.get_states() or [])}
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
    return {"so_ngay": ngay, "thiet_bi": ra}


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


def _kiem(data: Any, phan: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Kiểm câu trả lời của model NGAY TẠI BIÊN. Trả (nhóm hợp lệ, số nhóm loại).

    Model là nguồn ngoài: có thể bịa mã, xếp một mã vào hai nhóm, hoặc bảo học
    một cái cảm biến. Nhóm phạm luật cứng của hướng dẫn thì LOẠI hẳn — sửa hộ
    là giáo viên làm bài thay học trò, và lỗi đó sẽ không bao giờ lộ ra để sửa
    hướng dẫn.
    """
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
        da_co.update(ma)
        nhanh = str(g.get("nguon_nhanh") or "")
        loai = str(g.get("loai") or "")
        try:
            chac = min(1.0, max(0.0, float(g.get("chac"))))
        except (TypeError, ValueError):
            chac = 0.0
        ra.append({"ma": ma, "ma_hoc": ma_hoc if hoc else "",
                   "nguon_nhanh": nhanh if nhanh in ma else "",
                   "loai": loai if loai in _LOAI else "khong_ro",
                   "hoc": hoc, "chac": round(chac, 2),
                   "vi_sao": str(g.get("vi_sao") or "")[:300]})
    return ra, loai_bo


def _ghi_lan(phien_ban: str, model: str, so_ho_so: int, so_nhom: int,
             bo_sot: int, loai_bo: int, loi: str) -> int:
    with _khoa:
        conn = _db()
        cur = conn.execute(
            "INSERT INTO lan_giai (ts, phien_ban, model, so_ho_so, so_nhom,"
            " bo_sot, loai_bo, loi) VALUES (?,?,?,?,?,?,?,?)",
            (time.time(), phien_ban, model, so_ho_so, so_nhom, bo_sot, loai_bo, loi))
        conn.commit()
        return int(cur.lastrowid or 0)


def giai(hs: dict[str, Any]) -> dict[str, Any]:
    """Bot đọc đề theo hướng dẫn, trả các nhóm đã kiểm ở biên.

    Một phần đề hỏng (model lỗi, JSON không đọc được) là CẢ LƯỢT hỏng: lưu nửa
    đề thì các mã ở nửa kia bị coi là bỏ sót, và kết luận hai nửa lệch phiên.
    """
    huong, ban = huong_dan()
    model = _model()
    ho = list(hs.get("thiet_bi") or [])
    nhom: list[dict[str, Any]] = []
    loai_bo = 0
    loi = ""
    for phan in _chia(ho):
        de = json.dumps({"so_ngay": hs.get("so_ngay"), "thiet_bi": phan},
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
        hop_le, bo = _kiem(data, phan)
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
            nhom_json = json.dumps(g, ensure_ascii=False)
            for loai, khoa, gt in _cau_hoi(g):
                s = json.dumps(gt, ensure_ascii=False, sort_keys=True)
                con.add((loai, khoa))
                cu = conn.execute(
                    "SELECT id, gia_tri FROM quyet_dinh"
                    " WHERE loai_cau_hoi=? AND khoa=? AND hieu_luc=1",
                    (loai, khoa)).fetchone()
                if cu and cu["gia_tri"] == s:
                    # Giữ lý do mới nhất để người chấm đọc, không hỏi lại.
                    conn.execute("UPDATE quyet_dinh SET nhom=? WHERE id=?",
                                 (nhom_json, cu["id"]))
                    continue
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
        for r in conn.execute(
                "SELECT id, loai_cau_hoi, khoa, nhom FROM quyet_dinh WHERE hieu_luc=1"
        ).fetchall():
            if (r["loai_cau_hoi"], r["khoa"]) in con:
                continue
            if ma_moi & set(json.loads(r["nhom"]).get("ma") or []):
                conn.execute("UPDATE quyet_dinh SET hieu_luc=0 WHERE id=?", (r["id"],))
        conn.commit()
    return {"moi": moi, "lap_lai": lap_lai}


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
    if gt.get("hoc"):
        return f"Học thói quen {_nhan(d['khoa'], ten)}"
    return (f"Không học {_nhan(d['khoa'], ten)} "
            f"({_LOAI_DOC.get(gt.get('loai'), 'chưa rõ là gì')})")


def soan_bao(kq: dict[str, Any], moi: list[dict[str, Any]],
             lap_lai: list[dict[str, Any]], ten: dict[str, str]) -> list[str]:
    """Tin cho nhóm "AI học hỏi": bot nghĩ gì, và câu nào cần người chấm.

    Chủ máy chốt: gửi để "tôi biết bot nghĩ gì và bạn xử lý cái gì, để tôi cũng
    học bạn và sửa chữa nếu lỗi". Nên mỗi kết luận kèm VÌ SAO và độ chắc.

    Không có gì mới thì không nhắn — nhắn "vẫn thế" là làm phiền. Viết bằng
    tên người đọc được, và bỏ hết dấu gạch dưới: Zalo gửi ở markdown, gạch dưới
    bị ăn làm in nghiêng (bài học `test_TIN_NHAN_khong_con_MA_MAY`).

    Trả danh sách tin, mỗi tin không quá ~1.800 ký tự.
    """
    if kq.get("loi"):
        return [f"🧠 Bot học hỏi — lượt hiểu thiết bị chưa xong: {kq['loi']}. "
                "Em giữ nguyên các kết luận cũ.".replace("_", " ")]
    if not moi and not lap_lai:
        return []
    dau = [f"🧠 Bot học hỏi — em vừa xem lại thiết bị nhà "
           f"(hướng dẫn bản {kq.get('phien_ban', '')})"]
    if kq.get("bo_sot"):
        dau.append(f"Em còn bỏ sót {kq['bo_sot']} mã chưa xếp được.")
    if kq.get("loai_bo"):
        dau.append(f"{kq['loai_bo']} nhóm em trả sai luật nên bị loại.")
    phai_hoi = {loai: can_hoi(loai) for loai in LOAI_CAU_HOI}
    dong: list[str] = []
    hoi: list[int] = []
    for d in moi:
        g = d["nhom"]
        vi_sao = f" — {g['vi_sao']}" if g.get("vi_sao") else ""
        tu_quyet = "" if phai_hoi[d["loai_cau_hoi"]] else " (em tự quyết — đã đủ tin)"
        dong.append(f"• #{d['id']} {_cau_doc(d, ten)}, chắc "
                    f"{round(float(g.get('chac') or 0) * 100)}%{vi_sao}{tu_quyet}")
        if phai_hoi[d["loai_cau_hoi"]]:
            hoi.append(d["id"])
    for d in lap_lai:
        dong.append(f"• Em lại nghĩ: {_cau_doc(d, ten)} — câu này từng bị chấm "
                    "SAI nên em không dùng.")
    cuoi: list[str] = []
    if hoi:
        cuoi = ["", f"Anh chấm giúp em ngay trong nhóm này ({len(hoi)} câu): "
                    f"gõ «hh {hoi[0]} đúng» hoặc «hh {hoi[0]} sai vì …». "
                    "Nhiều câu cùng đúng thì gõ liền số: «hh 12 13 14 đúng»."]
    tin: list[str] = []
    hien = dau + [""]
    for x in dong:
        if len(hien) > 2 and len("\n".join(hien + [x])) > 1800:
            tin.append("\n".join(hien))
            hien = []
        hien.append(x)
    tin.append("\n".join(hien + cuoi))
    return [t.replace("_", " ") for t in tin]


def bao_nhom(tin: str | list[str]) -> int:
    """Gửi vào kênh học hỏi (`du_doan_nha._kenh_nhan`) — nhóm "AI học hỏi".

    Trả số tin gửi được. Chưa chọn kênh thì KHÔNG rơi về admin như gợi ý bật
    đèn: chủ máy chỉ định rõ nhóm này là nơi đọc chuyện bot học.
    """
    from services import digest, du_doan_nha

    kenh = du_doan_nha._kenh_nhan()
    if not kenh:
        logger.warning({"event": "hieu_thiet_bi_chua_co_kenh",
                        "ghi_chu": "chưa chọn mqtt.du_doan.kenh_nhan"})
        return 0
    ds = [tin] if isinstance(tin, str) else list(tin)
    return sum(digest.send_targets(kenh, t) for t in ds if t)


def tra_loi(text: str) -> Optional[str]:
    """Câu chấm trong nhóm học hỏi: «hh 12 đúng», «hh 12 13 sai vì là quạt».

    Tiền tố `hh` và hai chữ đúng/sai do CHÍNH bot in ra trong tin hỏi, nên đây
    không phải danh sách đoán ý người dùng — cùng lý do với
    `orchestrator._TRA_LOI_DUNG`. So sau khi bỏ dấu: chủ máy gõ trên điện
    thoại, "dung" và "đúng" là một chữ.

    Trả None = không phải câu chấm, tin đi tiếp như thường.
    """
    from services.boi_canh_nha import _khong_dau

    phan = (text or "").split()
    if not phan or _khong_dau(phan[0]) != "hh":
        return None
    so: list[int] = []
    i = 1
    while i < len(phan) and phan[i].lstrip("#").isdigit():
        so.append(int(phan[i].lstrip("#")))
        i += 1
    chu = _khong_dau(phan[i]) if i < len(phan) else ""
    if not so or chu not in ("dung", "sai"):
        return "Anh gõ giúp em: «hh <số> đúng» hoặc «hh <số> sai vì …»."
    ghi_chu = " ".join(phan[i + 1:])
    duoc = [x for x in so if cham(x, chu == "dung", cham_boi="chu_may", ghi_chu=ghi_chu)]
    khong = [x for x in so if x not in duoc]
    dong = []
    if duoc:
        dong.append(f"Em ghi rồi: {', '.join(f'#{x}' for x in duoc)} "
                    f"{'đúng' if chu == 'dung' else 'sai'}.")
        if chu == "sai":
            dong.append("Câu sai em thôi dùng ngay; Claude sẽ xem để sửa hướng dẫn cho em.")
    if khong:
        dong.append(f"Không thấy câu đang chờ chấm: {', '.join(f'#{x}' for x in khong)}.")
    return " ".join(dong)


# ── Vòng chạy ───────────────────────────────────────────────────────────────
def chay_mot_lan() -> dict[str, Any]:
    """Heartbeat gọi mỗi ngày: đo đề → bot giải → lưu → báo nhóm học hỏi."""
    if not is_enabled():
        return {"bo_qua": "đang tắt"}
    hs = ho_so()
    if not hs:
        return {"bo_qua": "HA chưa trả sổ dịch vụ — giữ kết luận cũ"}
    if not hs["thiet_bi"]:
        return {"bo_qua": "chưa có thiết bị bật tắt nào có lịch sử"}
    kq = giai(hs)
    ghi = (ghi_ket_qua(kq["lan_giai"], kq["nhom"]) if not kq["loi"]
           else {"moi": [], "lap_lai": []})
    ten = {x["ma"]: x["ten"] for x in hs["thiet_bi"] if x.get("ten")}
    tin = soan_bao(kq, ghi["moi"], ghi["lap_lai"], ten)
    gui = bao_nhom(tin) if tin else 0
    return {"lan_giai": kq["lan_giai"], "phien_ban": kq["phien_ban"],
            "nhom": len(kq["nhom"]), "moi": len(ghi["moi"]),
            "lap_lai": len(ghi["lap_lai"]), "gui": gui, "loi": kq["loi"]}


def _reset_for_tests() -> None:
    global _conn
    try:
        if _conn is not None:
            _conn.close()
    except Exception:
        pass
    _conn = None
