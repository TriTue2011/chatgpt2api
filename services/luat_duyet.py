"""LUẬT từ trường hợp chủ nhà đã DUYỆT — bot chuyển từng trường hợp thành luật chạy được, giáo viên / chủ nhà chấm.

Chủ máy 02/10/2026: duyệt trường hợp bật rồi tắt (`kich_ban_nha` — «Duyệt trường hợp BẬT rồi TẮT»), "rồi thực hiện
đúng theo đó và hỏi lại để học cách làm đúng hơn, xem đã làm đúng chưa, chưa đúng thì nhìn lại ở đâu không đạt,
chỉnh lại cho phù hợp". Trường hợp đã duyệt là LỜI; bộ kích hoạt cần mã cảm biến, ngưỡng, khung giờ.

Cùng khung các tầng học khác (vai giáo viên): CODE bày đề (trường hợp đã duyệt, cảm biến THẬT kèm mã / loại / đơn vị /
số bot đã học, lịch sinh hoạt, lời chấm trước) và KIỂM Ở BIÊN (mã có thật, dạng điều kiện đúng); BOT (hướng dẫn
`chuyen_truong_hop.md`) viết luật; bot HỎI CHỦ NHÀ TỪNG LUẬT (`hoi_tiep`: «đúng» / «sửa …»). Chỉ CHỦ NHÀ quyết luật
nào chạy (`ap`); giáo viên chỉ chấm đúng/sai theo mô tả của chủ nhà — lời chấm đó vào đề lần sau để dạy bot.

Dạng điều kiện là dạng chung của các tầng học (câu thói quen): ``{"ma", "la"}``, ``{"ma", "duoi"|"tren"}``,
``{"ma": "gio", "tu", "den"}``; thêm ``{"ma": "lich", "la": <mã lịch>}``, ``{"ma": "ca_nha", "la": "ngu"|"vang"}``,
``{"ma": "troi", "la": "toi"|"sang"}`` (mặt trời — `services/troi.py`)
và ``"phu_dinh"`` để lấy điều ngược lại.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

_PATH = Path(DATA_DIR) / "agent" / "luat_duyet.json"
_khoa = threading.RLock()
NEN = ("bat", "tat", "khong_lam", "giu", "hoi")
_NEN_DOC = {"bat": "bật", "tat": "tắt", "khong_lam": "KHÔNG bật", "giu": "GIỮ (không tắt)", "hoi": "hỏi anh"}
_NGUON_RE = re.compile(r"^binary_sensor\.[a-z0-9_]+ (có người vào|vắng|(?:ở lại|vắng) (\d{1,4}) giây)$")
#: «ở lại N giây» / «vắng N giây»: N trong khoảng này (dưới 10 giây là nhiễu, trên một giờ là chuyện khác).
O_LAI_GIAY = (10, 3600)
_GIO_RE = re.compile(r"^([01]\d|2[0-4]):[0-5]\d$")
_LOAI_SO = {"distance": "khoảng cách", "illuminance": "độ sáng", "temperature": "nhiệt độ", "humidity": "độ ẩm"}


# ── Sổ ──────────────────────────────────────────────────────────────────────
def _nap() -> dict[str, Any]:
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _luu(d: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_PATH)


def so() -> dict[str, Any]:
    with _khoa:
        return _nap()


# ── Đề ──────────────────────────────────────────────────────────────────────
def truong_hop(tb: str) -> list[dict[str, Any]]:
    """Trường hợp đã duyệt của ``tb``, đánh số liền: phần bật trước, phần tắt sau."""
    from services import kich_ban_nha
    x = kich_ban_nha.duyet().get(tb) or {}
    return [{**m, "chieu": h} for h in ("bat", "tat") for m in x.get(h) or []]


def cam_bien() -> list[dict[str, str]]:
    """Cảm biến bộ kích hoạt kiểm được: nhị phân có người / cửa / ghép, số (khoảng cách, độ sáng, đếm, nhiệt)."""
    from services import boi_canh_nha, cam_bien_ghep, ha_client, kich_hoat_nha as kh

    ghep = cam_bien_ghep.ds()
    nen = (ha_client.get_ha_area_index() or {}).get("entity_platform") or {}
    ra = []
    # Cảm biến GHÉP do c2a tính, KHÔNG có trong trạng thái HA (đo 05/10/2026: «Tivi phòng khách đang bật» vắng mặt
    # khỏi đề và mọi điều kiện dùng nó luôn sai) — lấy cả hai như bộ kích hoạt (`_trang_thai_ha`).
    for s in kh._trang_thai_ha():
        ma = str(s["entity_id"])
        a = s.get("attributes") or {}
        lop, dv = a.get("device_class"), a.get("unit_of_measurement")
        loai = ""
        if ma in ghep:
            loai = "GHÉP do bot tính — " + str(ghep[ma].get("ten") or ghep[ma].get("mo_ta") or "có người")
        elif ma.startswith("binary_sensor."):
            if lop in kh._LOP_HIEN_DIEN:
                loai = "camera thấy người" if nen.get(ma) == "frigate" else f"có người ({lop})"
            elif lop in kh._LOP_CUA:
                loai = "cửa (on = mở)"
        elif ma.startswith("sensor."):
            if lop in _LOAI_SO or dv in ("m", "cm", "mm", "lx"):
                loai = _LOAI_SO.get(lop, "khoảng cách" if dv in ("m", "cm", "mm") else "độ sáng")
            elif dv == "objects":
                loai = "số người camera đếm"
        if loai:
            ra.append({"ma": ma, "ten": str(a.get("friendly_name") or ma), "loai": loai, "don_vi": str(dv or ""),
                       "khu": boi_canh_nha.phong_cua(ma) or "chưa xếp khu"})
    return sorted(ra, key=lambda x: (x["khu"], x["ma"]))


def de(tb: str) -> str:
    """Đề cho MỘT thiết bị của nhà thật: gom dữ liệu thật rồi trình bày bằng `de_tu` (bộ đề luyện dùng chung khuôn)."""
    from services import kich_hoat_nha as kh, lich_sinh_hoat, vung_khoang_cach

    ten = kh._ten_ha()
    cb = cam_bien()
    vung = []
    for ma, v in vung_khoang_cach.ds().items():
        d = vung_khoang_cach.vung_dang_dung(v)
        if d:
            vung.append((ma, d[0], d[1], v.get("radar", "?")))
    x = so().get(tb) or {}
    th = truong_hop(tb)
    return de_tu(tb, ten.get(tb, tb), th, cb, vung=vung,
                 trung=_cam_bien_trung([c["ma"] for c in cb]), do_tin=_do_tin_cam_bien([c["ma"] for c in cb]),
                 lich=lich_sinh_hoat.ds(), sai=_theo_loi(x, x.get("chay_sai") or [], th)[-10:],
                 cham=_theo_loi(x, x.get("cham") or [], th)[-15:])


def _theo_loi(x: dict[str, Any], ds: list[dict[str, Any]], th: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lời chấm / lần chạy sai ghi theo SỐ của lần giải cũ → đổi sang số của danh sách trường hợp HIỆN TẠI, khớp theo
    LỜI trường hợp; trường hợp không còn thì bỏ. 05/10/2026 chủ máy bỏ 19/24 trường hợp đèn trần: không đổi số thì
    lời sửa của «trường hợp 14» cũ sẽ dạy nhầm sang trường hợp 14 mới (hoặc trỏ vào khoảng trống)."""
    loi_lan = {l["id"]: l.get("truong_hop") or [] for l in x.get("lan") or []}
    so_moi = {m["tinh_huong"]: i for i, m in enumerate(th, 1)}
    ra = []
    for c in ds:
        cu = loi_lan.get(c.get("lan"), [])
        loi = cu[c["so"] - 1] if 1 <= int(c.get("so") or 0) <= len(cu) else None
        if loi in so_moi:
            ra.append({**c, "so": so_moi[loi]})
    return ra


def de_tu(tb: str, ten_tb: str, th: list[dict[str, Any]], cb: list[dict[str, Any]], *,
          vung: list[tuple[str, str, float, str]] | None = None, trung: list[tuple[str, str, float]] | None = None,
          do_tin: list[tuple[str, str]] | None = None, lich: list[dict[str, Any]] | None = None,
          sai: list[dict[str, Any]] | None = None, cham: list[dict[str, Any]] | None = None) -> str:
    """Trình bày đề từ dữ liệu ĐÃ GOM — hàm thuần, không đọc gì. Nhà thật (`de`) và nhà giả (bộ đề luyện) cùng khuôn."""
    dong = [f"THIẾT BỊ: {tb} | {ten_tb}", "", "A. TRƯỜNG HỢP CHỦ NHÀ ĐÃ DUYỆT:"]
    dong += [f"{i}. [{'BẬT' if m['chieu'] == 'bat' else 'TẮT'}] {m['tinh_huong']} → nên {m['nen']}"
             + (f" (cảm biến thấy: {m['cam_bien_thay']})" if m.get("cam_bien_thay") else "")
             for i, m in enumerate(th, 1)]
    dong += ["", "B. CẢM BIẾN kiểm được (mã | tên | khu | loại | đơn vị):"]
    dong.append(f"- {tb} | {ten_tb} | (chính thiết bị đang xét) | on = đang bật")
    dong += [f"- {c['ma']} | {c['ten']} | {c['khu']} | {c['loai']}" + (f" | {c['don_vi']}" if c.get("don_vi") else "")
             for c in cb]
    if vung:
        dong += ["", "B2. VÙNG KHOẢNG CÁCH bot đã học (số đo thật, dùng làm ngưỡng):"]
        dong += [f"- {ma}: người ở TRONG khu khi {'dưới' if h == 'duoi' else 'từ'} {ng:g} (radar {rd})"
                 for ma, h, ng, rd in vung]
    if trung:
        dong += ["", "B3. CẢM BIẾN GẦN NHƯ CÙNG MỘT TÍN HIỆU (đo trên lịch sử thật) — ĐỪNG viết điều kiện bắt chúng "
                 "KHÁC nhau (vd cái này on, cái kia off): như thế luật không bao giờ chạy. Dùng MỘT trong chúng, hoặc "
                 "cùng chiều:"]
        dong += [f"- {a} ≈ {b} (giống nhau {ti:.0%} số lần)" for a, b, ti in trung]
    if do_tin:
        dong += ["", "B4. ĐỘ TIN cảm biến (đo lịch sử thật) — «nhiễu» hay đổi chớp nhoáng, ĐỪNG dựa chính vào nó; "
                 "dùng phải kèm xac_minh=true hoặc một cảm biến «lành»:"]
        dong += [f"- {ma}: {nh}" for ma, nh in do_tin]
    dong += ["", "C. LỊCH SINH HOẠT (mã | tên | loại | giờ):"]
    dong += [f"- {x['ma']} | {x['ten']} | {x['loai']} | {x['tu']}–{x['den']}" for x in lich or []] or ["(chưa có)"]
    dong += ["", "C2. TRỜI: {\"ma\": \"troi\", \"la\": \"toi\"} khi mặt trời đã lặn, \"sang\" khi đã mọc — dùng cho"
             " «trời tối / ban ngày» khi mục B2 không có ngưỡng độ sáng đã học."]
    if sai:
        dong += ["", "E. LẦN CHẠY BỊ CHẤM SAI — luật đã làm, chủ nhà nói sai (hoặc tự làm ngược lại ngay). Tìm điều "
                 "kiện nào khớp mà lẽ ra không được khớp (✓ là điều kiện đã đúng lúc đó), sửa luật đó cho chặt hơn "
                 "hoặc thêm luật chặn; đừng bỏ trường hợp:"]
        dong += [f"- trường hợp {c['so']} lúc {c['gio']}: {', '.join(c['doc'])}"
                 + (f" — chủ nhà: {c['loi']}" if c.get("loi") else "") for c in sai]
    if cham:
        dong += ["", "D. LỜI CHẤM các lần trước:"]
        dong += [f"- ({'chủ nhà' if c['cham_boi'] == 'chu_may' else 'giáo viên'} chấm "
                 f"{'ĐÚNG' if c['dung'] else 'SAI'}) trường hợp {c['so']}: {c['ghi_chu']}" for c in cham]
    return "\n".join(dong)


def _cam_bien_trung(ma_ds: list[str], so_ngay: int = 5, nguong: float = 0.97) -> list[tuple[str, str, float]]:
    """Cặp binary_sensor đo gần như cùng một tín hiệu (trạng thái giống nhau ≥ ``nguong`` số lần), theo lịch sử THẬT.

    Vì sao cần: 04/10/2026 luật bật quạt #5 đòi ``all_occupancy=on`` VÀ ``person_occupancy=off`` — hai cảm biến này
    giống hệt nhau (đo 5 ngày: 0/2340 lần khác nhau) nên luật KHÔNG BAO GIỜ chạy. Lớp lỗi: model không biết hai cảm
    biến là một. Chỉ đo binary_sensor (trạng thái on/off rõ ràng); so bằng trạng thái của B TẠI mỗi mốc A đổi.
    """
    import sqlite3

    from services import lich_su_nha
    bs = [m for m in ma_ds if str(m).startswith("binary_sensor.")]
    if len(bs) < 2:
        return []
    try:
        ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    except sqlite3.Error:
        return []
    try:
        tu = time.time() - so_ngay * 86400
        chuoi: dict[str, list[tuple[float, str]]] = {}
        for m in bs:
            chuoi[m] = [(float(ts), str(g)) for ts, g in ro.execute(
                "SELECT ts, gia_tri FROM su_kien WHERE thiet_bi=? AND truong='state' AND ts>? ORDER BY ts", (m, tu))]
    except sqlite3.Error:
        return []
    finally:
        ro.close()

    ra: list[tuple[str, str, float]] = []
    for i, a in enumerate(bs):
        for b in bs[i + 1:]:
            ca, cb2 = chuoi[a], chuoi[b]
            if len(ca) < 20 or len(cb2) < 20:
                continue
            # Trùng theo THỜI GIAN (không theo mốc đổi), nên hai cảm biến đổi lệch nhau vài mili giây không bị tính là
            # khác: gộp hai dòng sự kiện, áp hết thay đổi tại một mốc rồi mới đo khoảng tiếp theo.
            sk = sorted([(t, 0, g) for t, g in ca] + [(t, 1, g) for t, g in cb2])
            sa = sb = None
            t_truoc = None
            giong = tong = 0.0
            for t, ai, g in sk:
                if t_truoc is not None and sa is not None and sb is not None and t > t_truoc:
                    tong += t - t_truoc
                    giong += (t - t_truoc) if sa == sb else 0.0
                if ai == 0:
                    sa = g
                else:
                    sb = g
                t_truoc = t
            if tong > 0 and giong / tong >= nguong:
                ra.append((a, b, giong / tong))
    return ra


def _do_tin_cam_bien(ma_ds: list[str]) -> list[tuple[str, str]]:
    """(mã, nhãn) cho cảm biến NHIỄU / KẸT trong đề — để model tránh dựa vào chúng. Lành thì không liệt (đỡ dài)."""
    try:
        from services import do_tin_cam_bien as dt
        d = dt.tat_ca(3.0)
    except Exception as exc:  # noqa: BLE001 — thiếu độ tin thì bỏ mục, không chặn soạn luật
        logger.warning({"event": "luat_duyet_do_tin_loi", "error": str(exc)[:160]})
        return []
    co = set(ma_ds)
    ra: list[tuple[str, str]] = []
    for x in (d.get("nhi_phan") or []):
        if x["ma"] in co and x["nhan"] == "nhieu":
            ra.append((x["ma"], f"NHIỄU ({x.get('doi_ngay'):.0f} lần/ngày, {x.get('ngan_tl', 0) * 100:.0f}% dưới 10s)"))
        elif x["ma"] in co and x["nhan"] == "ket":
            ra.append((x["ma"], f"KẸT (đứng im {x.get('im_gio')} giờ)"))
    for x in (d.get("so") or []):
        if x["ma"] in co and x["nhan"] == "nhieu":
            ra.append((x["ma"], f"NHIỄU (radar mất mục tiêu {x.get('cham0_tl', 0) * 100:.0f}%)"))
    return ra


def _mau_thuan_trong_luat(neu: list[dict[str, Any]]) -> str | None:
    """Lý do nếu các điều kiện của MỘT luật không bao giờ cùng đúng (cùng mã đòi hai trạng thái), None nếu ổn.
    04/10/2026: bot giải lại quạt vẫn ra luật #1 đòi person_occupancy=on VÀ =off — chặn ở biên để luật chết không
    vào sổ, thay vì chờ chấm tay từng cái."""
    from collections import defaultdict
    gom: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for x in neu:
        if x["ma"] not in ("gio",):
            gom[x["ma"]].append(x)
    for ma, xs in gom.items():
        duong: set[str] = set()
        am: set[str] = set()
        duois: list[float] = []
        trens: list[float] = []
        for x in xs:
            if "duoi" in x:
                duois.append(x["duoi"])
            elif "tren" in x:
                trens.append(x["tren"])
            else:
                (am if x.get("phu_dinh") else duong).add(x["la"])
        if len(duong) >= 2:
            return f"{ma} phải cùng lúc = {sorted(duong)}"
        if duong & am:
            return f"{ma} vừa = vừa ≠ «{sorted(duong & am)[0]}»"
        if duois and trens and min(duois) <= max(trens):
            return f"{ma} vừa < {min(duois):g} vừa > {max(trens):g}"
    return None


# ── Kiểm ở biên ─────────────────────────────────────────────────────────────
def _kiem_dk(x: Any, ma_co: set[str], lich: set[str]) -> dict[str, Any]:
    if not isinstance(x, dict) or not x.get("ma"):
        raise ValueError("điều kiện thiếu «ma»")
    ma = str(x["ma"])
    pd = {"phu_dinh": True} if x.get("phu_dinh") else {}
    if ma == "gio":
        tu, den = str(x.get("tu") or ""), str(x.get("den") or "")
        if not (_GIO_RE.fullmatch(tu) and _GIO_RE.fullmatch(den)):
            raise ValueError(f"khung giờ sai dạng: {tu}–{den}")
        return {"ma": "gio", "tu": tu, "den": den, **pd}
    if ma == "lich":
        if str(x.get("la")) not in lich:
            raise ValueError(f"không có lịch «{x.get('la')}»")
        return {"ma": "lich", "la": str(x["la"]), **pd}
    if ma == "ca_nha":
        if x.get("la") not in ("ngu", "vang"):
            raise ValueError("ca_nha chỉ «ngu» hoặc «vang»")
        return {"ma": "ca_nha", "la": str(x["la"]), **pd}
    if ma == "troi":
        if x.get("la") not in ("toi", "sang"):
            raise ValueError("troi chỉ «toi» hoặc «sang»")
        return {"ma": "troi", "la": str(x["la"]), **pd}
    if ma not in ma_co:
        raise ValueError(f"mã không có trong nhà: {ma}")
    if x.get("dung_yen_giay") is not None:
        g, lech = int(x["dung_yen_giay"]), float(x.get("lech") or 0.3)
        if not 60 <= g <= 86400 or not 0 < lech <= 5:
            raise ValueError(f"dung_yen_giay {g} ngoài 60–86400 hoặc lech {lech} ngoài 0–5")
        return {"ma": ma, "dung_yen_giay": g, "lech": lech, **pd}
    for k in ("duoi", "tren"):
        if x.get(k) is not None:
            return {"ma": ma, k: float(x[k]), **pd}
    ra = {"ma": ma, "la": str(x.get("la") or "on"), **pd}
    for k in ("lien_giay", "trong_giay"):
        if x.get(k) is not None:
            g = int(x[k])
            if not 1 <= g <= 86400:
                raise ValueError(f"{k} {g} ngoài 1–86400")
            ra[k] = g
    if "lien_giay" in ra and "trong_giay" in ra:
        raise ValueError("lien_giay và trong_giay không đi chung một điều kiện")
    return ra


def kiem(data: Any, n: int, ma_co: set[str], lich: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """(luật hợp lệ, không chuyển được, lỗi). Mã / nguồn / dạng điều kiện sai thì loại luật đó kèm lỗi."""
    luat, khong, loi = [], [], []
    if not isinstance(data, dict):
        return [], [], ["không phải JSON object"]
    da: set[int] = set()
    for l in data.get("luat") or []:
        try:
            s = int(l.get("so"))
            if not 1 <= s <= n or s in da:
                raise ValueError(f"số trường hợp {l.get('so')} sai / lặp")
            if l.get("nen") not in NEN:
                raise ValueError(f"nen «{l.get('nen')}» sai")
            khi = [str(k) for k in l.get("khi") or []]
            if not khi or not all(_NGUON_RE.fullmatch(k) and k.split(" ")[0] in ma_co for k in khi):
                raise ValueError(f"«khi» sai: {khi}")
            for k in khi:
                g = _NGUON_RE.fullmatch(k).group(2)
                if g and not O_LAI_GIAY[0] <= int(g) <= O_LAI_GIAY[1]:
                    raise ValueError(f"«{k}»: số giây ngoài {O_LAI_GIAY[0]}–{O_LAI_GIAY[1]}")
            neu = [_kiem_dk(x, ma_co, lich) for x in l.get("neu") or []]
            mt = _mau_thuan_trong_luat(neu)
            if mt:
                raise ValueError(f"luật tự mâu thuẫn, không bao giờ chạy: {mt}")
            luat.append({"so": s, "nen": l["nen"], "khi": khi, "neu": neu, "xac_minh": bool(l.get("xac_minh")),
                         "vi_sao": str(l.get("vi_sao") or "")[:300]})
            da.add(s)
        except (TypeError, ValueError) as exc:
            loi.append(f"luật {l.get('so') if isinstance(l, dict) else '?'}: {exc}")
    for k in data.get("khong_chuyen_duoc") or []:
        try:
            s = int(k.get("so"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 1 <= s <= n and s not in da:
            khong.append({"so": s, "ly_do": str(k.get("ly_do") or "")[:300]})
            da.add(s)
    thieu = sorted(set(range(1, n + 1)) - da)
    if thieu:
        loi.append(f"bỏ sót trường hợp {thieu}")
    return luat, khong, loi


# ── Giải / chấm / áp ────────────────────────────────────────────────────────
def giai(tb: str) -> dict[str, Any]:
    from services import hieu_thiet_bi_nha as ht, lich_sinh_hoat

    th = truong_hop(tb)
    if not th:
        return {"ok": False, "loi": "thiết bị chưa có trường hợp đã duyệt"}
    huong, ban = ht.huong_dan("chuyen_truong_hop")
    model = ht._model()
    r = ht._goi_model(model, huong, de(tb))
    if r.get("error"):
        return {"ok": False, "loi": f"model lỗi: {str(r['error'])[:160]}"}
    tho = str(((r.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    data = ht._doc_json(tho)
    ma_co = {c["ma"] for c in cam_bien()} | {tb}
    luat, khong, loi = kiem(data, len(th), ma_co, {x["ma"] for x in lich_sinh_hoat.ds()})
    for l in luat:
        l["chieu"] = th[l["so"] - 1]["chieu"]
    with _khoa:
        d = _nap()
        x = d.setdefault(tb, {"lan": [], "cham": []})
        lan = {"id": (x["lan"][-1]["id"] + 1) if x["lan"] else 1, "luc": time.time(), "huong_dan": ban,
               "model": model, "luat": luat, "khong_chuyen_duoc": khong, "loi": loi,
               "truong_hop": [m["tinh_huong"] for m in th]}
        x["lan"] = (x["lan"] + [lan])[-10:]
        giu = _mang_sang(x, lan)
        _luu(d)
    logger.info({"event": "luat_duyet_giai", "thiet_bi": tb, "luat": len(luat), "khong": len(khong), "loi": loi[:3],
                 "giu": giu})
    return {"ok": True, **lan, "giu": giu}


def _cung_luat(a: dict[str, Any], b: dict[str, Any]) -> bool:
    k = ("nen", "khi", "neu", "xac_minh")
    return json.dumps([a.get(x) for x in k], sort_keys=True) == json.dumps([b.get(x) for x in k], sort_keys=True) \
        or (a.get("nen") == b.get("nen") and a.get("xac_minh") == b.get("xac_minh")
            and sorted(a.get("khi") or []) == sorted(b.get("khi") or [])
            and sorted(json.dumps(n, sort_keys=True) for n in a.get("neu") or [])
            == sorted(json.dumps(n, sort_keys=True) for n in b.get("neu") or []))


def _mang_sang(x: dict[str, Any], lan: dict[str, Any]) -> list[int]:
    """Luật của lần giải mới GIỐNG HỆT luật CHỦ NHÀ đã duyệt cho cùng trường hợp → ghi lời duyệt sang lần mới, khỏi hỏi
    lại. Chỉ lời chủ nhà mới mang sang (giáo viên không có quyền duyệt). Chủ máy 05/10/2026: hỏi duyệt từng trường hợp —
    chỉ hỏi cái chưa duyệt / đã đổi."""
    cuoi: dict[tuple[int, int], dict[str, Any]] = {}
    for c in x.get("cham") or []:
        if c.get("cham_boi") == "chu_may":
            cuoi[(c["lan"], c["so"])] = c
    th_moi = lan.get("truong_hop") or []
    da = [(l, (cu.get("truong_hop") or [])[l["so"] - 1]) for cu in x["lan"][:-1] for l in cu["luat"]
          if (c := cuoi.get((cu["id"], l["so"]))) and c["dung"] and l["so"] <= len(cu.get("truong_hop") or [])]
    giu = []
    for l in lan["luat"]:
        loi = th_moi[l["so"] - 1] if l["so"] <= len(th_moi) else None
        if any(loi == loi_cu and _cung_luat(l, d) for d, loi_cu in da):
            x["cham"] = (x.get("cham") or []) + [{"lan": lan["id"], "so": l["so"], "dung": True, "cham_boi": "chu_may",
                                                  "ghi_chu": "giữ — luật không đổi so với lần anh duyệt",
                                                  "luc": time.time()}]
            giu.append(l["so"])
    x["cham"] = (x.get("cham") or [])[-60:]
    return giu


def cham(tb: str, so_th: int, dung: bool, *, cham_boi: str, ghi_chu: str = "", lan_id: int | None = None) -> bool:
    """Chấm luật của trường hợp ``so_th`` ở lần giải ``lan_id`` (mặc định mới nhất). Lời chấm vào đề lần sau (mục D)."""
    if cham_boi not in ("chu_may", "claude"):
        raise ValueError("cham_boi là chu_may hoặc claude")
    with _khoa:
        d = _nap()
        x = d.get(tb)
        if not x or not x["lan"]:
            return False
        lan = next((l for l in x["lan"] if l["id"] == lan_id), None) if lan_id else x["lan"][-1]
        if lan is None:
            return False
        if not any(l["so"] == so_th for l in lan["luat"]):
            return False
        x["cham"] = (x.get("cham") or []) + [{"lan": lan["id"], "so": so_th, "dung": bool(dung), "cham_boi": cham_boi,
                                              "ghi_chu": str(ghi_chu or "")[:300], "luc": time.time()}]
        x["cham"] = x["cham"][-60:]
        _luu(d)
    return True


def chay_sai(tb: str, lan_id: int, so_th: int, doc: list[str], loi: str = "") -> None:
    """Một lần LÀM theo luật bị chấm sai → ghi kèm giá trị lúc đó, chấm luật đó SAI (thôi chạy) và cho bot giải lại
    ngay với mục E — chủ máy: "chưa đúng thì nhìn lại ở đâu không đạt, chỉnh lại cho phù hợp"."""
    from datetime import datetime, timedelta, timezone
    if not lan_id:
        # Luật anh tự đặt trên web: không có bài để bot giải lại — TẠM DỪNG luật đó, chờ anh sửa / bật lại.
        with _khoa:
            d = _nap()
            x = d.setdefault(tb, {"lan": [], "cham": []})
            c = next((l for l in x.get("chu") or [] if l["id"] == so_th), None)
            if c:
                khoa = c["loi"] if c.get("loi") in ((x.get("lan") or [{}])[-1].get("truong_hop") or []) else f"chu:{so_th}"
                x["dung"] = sorted(set(x.get("dung") or []) | {khoa})
                c["sai"] = f"{datetime.now(timezone(timedelta(hours=7))):%d/%m %H:%M}: {', '.join(doc)[:200]}"
                _luu(d)
        return
    with _khoa:
        d = _nap()
        x = d.setdefault(tb, {"lan": [], "cham": []})
        x["chay_sai"] = ((x.get("chay_sai") or []) + [{
            "lan": lan_id, "so": so_th, "doc": list(doc)[:12], "loi": str(loi or "")[:200], "luc": time.time(),
            "gio": datetime.now(timezone(timedelta(hours=7))).strftime("%d/%m %H:%M")}])[-30:]
        _luu(d)
    cham(tb, so_th, False, cham_boi="chu_may", ghi_chu=f"chạy sai lúc làm thật: {', '.join(doc)[:200]}",
         lan_id=lan_id)
    threading.Thread(target=giai_va_bao, args=(tb,), name="luat-duyet-giai-lai", daemon=True).start()


def cham_moi_nhat(so_th: int, dung: bool, ghi_chu: str = "", tb: str = "") -> str:
    """Chủ nhà chấm qua kênh («luật 3 sai, …»): thiết bị nêu tên, không thì thiết bị vừa được báo luật gần nhất."""
    with _khoa:
        d = _nap()
    if not tb:
        # Đang hỏi luật của thiết bị nào thì là thiết bị đó — «mới giải gần nhất» có thể là thiết bị khác.
        tb = str((_hoi_nap().get("cho") or {}).get("tb") or "") or max(
            (t for t, x in d.items() if x.get("lan")), key=lambda t: d[t]["lan"][-1]["luc"], default="")
    if not tb:
        return "Em chưa chuyển luật cho thiết bị nào ạ."
    if not cham(tb, so_th, dung, cham_boi="chu_may", ghi_chu=ghi_chu):
        return f"Lần chuyển mới nhất không có luật cho trường hợp {so_th} ạ."
    return (f"Dạ, em ghi luật {so_th} {'đúng — từ giờ em chạy theo luật này' if dung else 'sai — lần chuyển sau em sửa'}.")


def ap(tb: str) -> list[dict[str, Any]]:
    """Luật ĐANG ÁP: mỗi trường hợp (của lần giải mới nhất) lấy QUYẾT ĐỊNH SAU CÙNG CỦA CHỦ NHÀ về nó, ở bất kỳ lần
    giải nào — «đúng» thì luật của lần đó chạy. Lần giải mới mà chủ nhà chưa trả lời thì luật cũ anh đã duyệt vẫn chạy.
    Cộng thêm luật CHỦ NHÀ tự thêm / sửa trên web (`x["chu"]` — sửa là duyệt; sửa sau lời chấm thì thắng), trừ luật
    anh TẠM DỪNG (`x["dung"]`).

    Chỉ CHỦ NHÀ quyết. Chủ máy 05/10/2026: "Bạn không có quyền xác nhận luật, bạn chỉ chấm đúng sai dựa trên cơ sở là
    tôi mô tả, mọi việc tôi quyết mới là đúng, bot phán đoán đưa tôi quyết định là làm luôn". Lời GIÁO VIÊN chấm
    (``cham_boi='claude'``) chỉ là ghi chú vào đề lần sau (mục D), không làm luật nào chạy hay thôi chạy.

    Khoá theo LỜI trường hợp, không theo số: thêm trường hợp làm số đổi, lời thì không. Mỗi luật kèm ``lan`` / ``so``
    để lần chạy sai truy về đúng bài (luật anh tự đặt: ``lan`` = 0, ``so`` = mã luật) và ``loi`` để báo."""
    with _khoa:
        x = _nap().get(tb) or {}
    return _ap_tu(x)


def _ap_tu(x: dict[str, Any]) -> list[dict[str, Any]]:
    ds_lan = x.get("lan") or []
    theo_id = {l["id"]: l for l in ds_lan}
    quyet: dict[str, tuple[bool, int, int, float]] = {}     # lời trường hợp → (đúng?, lần, số, lúc)
    for c in x.get("cham") or []:                           # sổ ghi theo thời gian: lời sau đè lời trước
        lan = theo_id.get(c["lan"])
        if c.get("cham_boi") != "chu_may" or lan is None:
            continue
        th = lan.get("truong_hop") or []
        if 1 <= c["so"] <= len(th):
            quyet[th[c["so"] - 1]] = (bool(c["dung"]), lan["id"], c["so"], float(c.get("luc") or 0))
    dung = set(x.get("dung") or [])
    chu = {l["loi"]: l for l in x.get("chu") or [] if l.get("loi")}
    ra = []
    loi_moi = ds_lan[-1].get("truong_hop") or [] if ds_lan else []
    for loi in loi_moi:
        if loi in dung:
            continue
        q = quyet.get(loi)
        c = chu.get(loi)
        if c and (not q or float(c.get("luc") or 0) >= q[3]):
            ra.append({**c, "lan": 0, "so": c["id"]})          # anh sửa sau lời chấm → luật anh sửa chạy
            continue
        if not q or not q[0]:
            continue
        l = next((l for l in theo_id[q[1]]["luat"] if l["so"] == q[2]), None)
        if l is not None:
            ra.append({**l, "lan": q[1], "loi": loi})
    ra += [{**c, "lan": 0, "so": c["id"]} for c in x.get("chu") or []
           if c.get("loi") not in loi_moi and f"chu:{c['id']}" not in dung]
    return ra


# ── Danh sách TRƯỜNG HỢP cho trang web: mỗi thiết bị, mỗi chiều một danh sách; anh ✓ / ✗ / 🗑 / ✎ ─────────────
# Chủ máy 05/10/2026: "mỗi thiết bị luôn ẩn, mở ra chia làm bật và tắt … gom theo từng trường hợp. Mỗi trường hợp
# kèm các điều kiện đi theo … cuối có tích v, x để xác nhận thực hiện theo hay tạm dừng, có thùng rác để xoá. Tất cả
# đều có thể chỉnh sửa, thêm, xoá"; bot tự học "chỉ là học hỏi đưa ra cho tôi điều kiện hợp lý, còn đâu tôi mới là
# người quyết định"; sửa trên web = duyệt.
CHIEU_HD = {"bat": "on", "tat": "off"}


def _tu_luat_hoc(chieu: str, l: dict[str, Any]) -> dict[str, Any] | None:
    """Một lá cây bot học (`kich_hoat_nha.luat`: dk = [{key, nho_hon, nguong}]) → luật cùng dạng luật duyệt; None nếu
    có điều kiện không nói được bằng dạng đó (vd «phút đã ở»)."""
    from services import kich_hoat_nha as kh
    khi = [d["key"][1:-1] for d in l.get("dk") or [] if d["key"].startswith("[") and not d["nho_hon"]]
    if len(khi) != 1 or not _NGUON_RE.fullmatch(khi[0]):
        return None
    neu: list[dict[str, Any]] = []
    tu = den = None
    for d in l.get("dk") or []:
        k, nho, ng = d["key"], bool(d["nho_hon"]), float(d["nguong"])
        if k.startswith("["):
            continue
        if k == "giờ":
            hhmm = f"{int(ng) % 24:02d}:{int(round((ng % 1) * 60)) % 60:02d}"
            if nho:
                den = min(den or "24:00", hhmm)
            else:
                tu = max(tu or "00:00", hhmm)
        elif k.startswith("lịch:"):
            neu.append({"ma": "lich", "la": k[5:], **({"phu_dinh": True} if nho else {})})
        elif k.startswith(kh.CAM_NHAN):
            continue                                    # nóng / lạnh: bộ kích hoạt tự xét nhiệt độ cảm nhận
        elif k.startswith(kh.PHUT_TU):
            neu.append({"ma": k[len(kh.PHUT_TU):], "la": "on", "trong_giay": max(1, int(ng * 60)),
                        **({} if nho else {"phu_dinh": True})})
        elif "." in k and not k.startswith(kh.PHUT_DA_O):
            neu.append({"ma": k, "duoi" if nho else "tren": round(ng, 2)})
        else:
            return None
    if tu or den:
        neu.insert(0, {"ma": "gio", "tu": tu or "00:00", "den": den or "24:00"})
    return {"chieu": chieu, "nen": chieu, "khi": khi, "neu": neu, "xac_minh": False,
            "hoc": {"p": l.get("p"), "k": l.get("k"), "n": l.get("n")}}


def de_xuat_hoc(tb: str, tq: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Luật bot học từ lịch sử ĐỦ CHẮC (p ≥ `P_HOI`) đổi được sang dạng luật — ĐỀ XUẤT cho anh duyệt, không tự chạy."""
    import hashlib
    from services import kich_hoat_nha as kh
    if tq is None:
        tq = next((d for d in kh.tong_quan() if d.get("thiet_bi") == tb), {}) or {}
    with _khoa:
        x = _nap().get(tb) or {}
    bo = set(x.get("bo_hoc") or [])
    co = [json.dumps([c.get("khi"), c.get("neu")], sort_keys=True) for c in x.get("chu") or []]
    ra = []
    for chieu, hd in CHIEU_HD.items():
        for l in ((tq.get("huong") or {}).get(hd) or {}).get("luat") or []:
            if float(l.get("p") or 0) < kh.P_HOI:
                continue
            r = _tu_luat_hoc(chieu, l)
            if r is None:
                continue
            ky = json.dumps([r["khi"], r["neu"]], sort_keys=True)
            id_ = "hoc:" + hashlib.sha1(f"{chieu}|{ky}".encode(), usedforsecurity=False).hexdigest()[:10]
            if id_ in bo or ky in co:
                continue
            ra.append({**r, "id": id_, "loi": f"Bot học từ lịch sử: {l['k']}/{l['n']} lần anh {_NEN_DOC[chieu]} "
                                              f"khi gặp điều kiện này ({float(l['p']):.0%})"})
    return ra


def danh_sach(tb: str, tq: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    """{bat: [...], tat: [...]} — mỗi trường hợp: id, loi, nen, khi, neu, xac_minh, nguon (anh | bot | bot_hoc),
    trang_thai (chay | dung | cho | sai | chua_chuyen | de_xuat), dong (từng dòng điều kiện đọc được), ly_do."""
    from services import kich_ban_nha as kb, kich_hoat_nha as kh
    ten = kh._ten_ha()
    with _khoa:
        x = _nap().get(tb) or {}
    lan = (x.get("lan") or [{}])[-1]
    th_lan = lan.get("truong_hop") or []
    dang = {(c.get("loi"), c["so"], c["lan"]) for c in _ap_tu(x)}
    dang_loi = {c.get("loi") for c in _ap_tu(x)}
    dung = set(x.get("dung") or [])
    chu = {c["loi"]: c for c in x.get("chu") or [] if c.get("loi")}
    quyet: dict[str, bool] = {}
    for c in x.get("cham") or []:
        l_ = next((l for l in x.get("lan") or [] if l["id"] == c["lan"]), None)
        if c.get("cham_boi") == "chu_may" and l_ and 1 <= c["so"] <= len(l_.get("truong_hop") or []):
            quyet[l_["truong_hop"][c["so"] - 1]] = bool(c["dung"])
    khong = {th_lan[k["so"] - 1]: k["ly_do"] for k in lan.get("khong_chuyen_duoc") or [] if k["so"] <= len(th_lan)}
    ra: dict[str, list[dict[str, Any]]] = {"bat": [], "tat": []}

    dv = {str(s_["entity_id"]): str((s_.get("attributes") or {}).get("unit_of_measurement") or "")
          for s_ in kh._trang_thai_ha()}

    def _muc(l: dict[str, Any] | None, **k: Any) -> dict[str, Any]:
        m = {"id": "", "loi": "", "nen": "", "khi": [], "neu": [], "xac_minh": False, **(l or {}), **k}
        m["dong"] = (doc_dong({**m, "neu": [{**n, "_dv": dv.get(n["ma"], "")} for n in m["neu"]]}, ten)
                     if m.get("khi") else [])
        return m

    for h in ("bat", "tat"):
        for m in (kb.duyet().get(tb) or {}).get(h) or []:
            loi = m["tinh_huong"]
            nguon = "anh" if m.get("nguon") == "chu_may" else "bot"
            if loi in chu:
                c = chu[loi]
                tt = "dung" if loi in dung else ("chay" if loi in dang_loi else "cho")
                ra[h].append(_muc(c, id=f"chu:{c['id']}", loi=loi, nguon=nguon, trang_thai=tt, sua=True))
                continue
            l = next((r for r in lan.get("luat") or [] if r["so"] <= len(th_lan) and th_lan[r["so"] - 1] == loi), None)
            if l is None:
                ra[h].append(_muc(None, id=f"th:{loi}", loi=loi, nen=m.get("nen", h), nguon=nguon,
                                  trang_thai="chua_chuyen", ly_do=khong.get(loi, "bot chưa chuyển trường hợp này")))
                continue
            tt = ("dung" if loi in dung else "chay" if (loi, l["so"], lan["id"]) in dang or loi in dang_loi
                  else "sai" if quyet.get(loi) is False else "cho")
            ra[h].append(_muc(l, id=f"lan:{lan['id']}:{l['so']}", loi=loi, nguon=nguon, trang_thai=tt))
    for c in x.get("chu") or []:
        if c.get("loi") in th_lan or any(c.get("loi") == m["loi"] for h in ra for m in ra[h]):
            continue
        ra[c["chieu"]].append(_muc(c, id=f"chu:{c['id']}", nguon=c.get("nguon", "anh"), sua=True,
                                   trang_thai="dung" if f"chu:{c['id']}" in dung else "chay"))
    for d in de_xuat_hoc(tb, tq):
        ra[d["chieu"]].append(_muc(d, nguon="bot_hoc", trang_thai="de_xuat"))
    return ra


_GIO_NGUOI_RE = re.compile(r"^\s*(\d{1,2})\s*(?:[:hH.]\s*(\d{1,2})?)?\s*$")


def _chuan_dk_nguoi(x: Any) -> Any:
    """Điều kiện NGƯỜI gõ trên web → dạng lõi đòi. Chủ máy 05/10/2026 «Lưu & chạy» bị từ chối vì gõ ``6:30`` (lõi
    đòi ``06:30``) và «liền 0» (lõi đòi 1–86400). Lõi `_kiem_dk` vẫn khắt khe với luật BOT viết — bot phải học viết
    đúng; ở đây chỉ nới cho chữ người gõ: giờ ``6:30`` / ``6h30`` / ``6`` → ``06:30``; liền/trong 0 giây = không đòi
    kéo dài → bỏ khoá. Không nhận ra thì để nguyên cho lõi báo lỗi."""
    if not isinstance(x, dict):
        return x
    x = dict(x)
    if x.get("ma") == "gio":
        for k in ("tu", "den"):
            m = _GIO_NGUOI_RE.fullmatch(str(x.get(k) or ""))
            if m and int(m.group(1)) <= 24 and int(m.group(2) or 0) <= 59:
                x[k] = f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}"
    for k in ("lien_giay", "trong_giay"):
        if x.get(k) in (0, "0", ""):
            x.pop(k)
    return x


def kiem_mot(tb: str, l: dict[str, Any]) -> dict[str, Any]:
    """Một luật anh nhập / sửa trên web → dạng chuẩn (kiểm ở biên như luật bot viết). Sai thì ValueError."""
    from services import lich_sinh_hoat
    chieu = str(l.get("chieu") or "")
    if chieu not in CHIEU_HD:
        raise ValueError("chiều phải là bat hoặc tat")
    l = {**l, "neu": [_chuan_dk_nguoi(x) for x in l.get("neu") or []]}
    nen = str(l.get("nen") or chieu)
    luat, _, loi = kiem({"luat": [{**l, "so": 1, "nen": nen}]}, 1, {c["ma"] for c in cam_bien()} | {tb},
                        {x["ma"] for x in lich_sinh_hoat.ds()})
    if not luat:
        raise ValueError("; ".join(e for e in loi if not e.startswith("bỏ sót")) or "luật không hợp lệ")
    return {**luat[0], "chieu": chieu}


def quyet(tb: str, viec: str, id_: str = "", luat: dict[str, Any] | None = None, loi: str = "") -> str:
    """Anh quyết MỘT trường hợp trên web: duyet (✓ chạy) | dung (✗ tạm dừng) | xoa (🗑) | sua (✎ — áp ngay) | them.
    Trả lời báo lại. Lời sửa cũng vào đề lần sau (mục D) để bot hiểu."""
    with _khoa:
        x = _nap().get(tb) or {}
    lan = (x.get("lan") or [{}])[-1]
    th_lan = lan.get("truong_hop") or []
    kieu, _, phan = id_.partition(":")

    def _luu_x(f: Any) -> None:
        with _khoa:
            d = _nap()
            xx = d.setdefault(tb, {"lan": [], "cham": []})
            f(xx)
            _luu(d)

    def _bo_dung(k: str) -> None:
        _luu_x(lambda xx: xx.__setitem__("dung", [v for v in xx.get("dung") or [] if v != k]))

    if viec in ("sua", "them"):
        r = kiem_mot(tb, luat or {})
        if kieu == "lan":
            l_id, so_th = (int(v) for v in phan.split(":"))
            loi = th_lan[so_th - 1] if l_id == lan.get("id") and so_th <= len(th_lan) else loi
        elif kieu == "th":
            loi = phan
        loi = (loi or (luat or {}).get("loi") or "").strip()[:300]
        cu = next((c for c in x.get("chu") or [] if kieu == "chu" and str(c["id"]) == phan), None)

        def f(xx: dict[str, Any]) -> None:
            ds = xx.setdefault("chu", [])
            if cu:
                c = next(c for c in ds if c["id"] == cu["id"])
                c.update(r, luc=time.time(), loi=loi or c.get("loi", ""))
                c.pop("sai", None)
            else:
                ds.append({**r, "id": max([c["id"] for c in ds] or [0]) + 1, "loi": loi,
                           "nguon": "bot_hoc" if kieu == "hoc" else "anh", "luc": time.time()})
            if loi:
                xx["dung"] = [v for v in xx.get("dung") or [] if v != loi]
        if kieu == "lan":
            # Lời sửa vào bài học TRƯỚC, luật anh sửa lưu SAU — `_ap_tu` để quyết định sau cùng thắng.
            l_id, so_th = (int(v) for v in phan.split(":"))
            cham(tb, so_th, False, cham_boi="chu_may", lan_id=l_id,
                 ghi_chu=f"chủ nhà sửa thành: {doc_luat(r, {})}"[:300])
        _luu_x(f)
        return "Đã lưu — luật anh đặt chạy ngay."
    if kieu == "lan":
        l_id, so_th = (int(v) for v in phan.split(":"))
        loi = th_lan[so_th - 1] if l_id == lan.get("id") and so_th <= len(th_lan) else ""
        if viec == "duyet":
            cham(tb, so_th, True, cham_boi="chu_may", ghi_chu="chủ nhà duyệt (web)", lan_id=l_id)
            _bo_dung(loi)
            return "Đã duyệt — luật chạy."
        if viec == "dung":
            _luu_x(lambda xx: xx.__setitem__("dung", sorted(set(xx.get("dung") or []) | {loi})))
            return "Đã tạm dừng."
        if viec == "xoa":
            cham(tb, so_th, False, cham_boi="chu_may", ghi_chu="chủ nhà BỎ trường hợp này (web)", lan_id=l_id)
            _bo_truong_hop(tb, l_id, so_th)
            return "Đã xoá trường hợp."
    if kieu == "chu":
        k = int(phan)
        c = next((c for c in x.get("chu") or [] if c["id"] == k), None)
        if c is None:
            raise ValueError("không còn luật đó")
        khoa = c["loi"] if c.get("loi") in th_lan else f"chu:{k}"
        if viec == "duyet":
            _bo_dung(khoa)
            _luu_x(lambda xx: [cc.pop("sai", None) for cc in xx.get("chu") or [] if cc["id"] == k])
            return "Đã bật lại — luật chạy."
        if viec == "dung":
            _luu_x(lambda xx: xx.__setitem__("dung", sorted(set(xx.get("dung") or []) | {khoa})))
            return "Đã tạm dừng."
        if viec == "xoa":
            _luu_x(lambda xx: xx.__setitem__("chu", [cc for cc in xx.get("chu") or [] if cc["id"] != k]))
            return "Đã xoá luật."
    if kieu == "th" and viec == "xoa":
        from services import kich_ban_nha as kb
        for h in ("bat", "tat"):
            for i, m in enumerate((kb.duyet().get(tb) or {}).get(h) or []):
                if m["tinh_huong"] == phan:
                    kb.sua_duyet(tb, h, "bo", i + 1)
                    return "Đã xoá trường hợp."
        raise ValueError("không còn trường hợp đó")
    if kieu == "hoc":
        if viec == "duyet":
            d = next((d for d in de_xuat_hoc(tb) if d["id"] == id_), None)
            if d is None:
                raise ValueError("đề xuất này không còn (bot vừa học lại)")
            return quyet(tb, "them", id_, {k: d[k] for k in ("chieu", "nen", "khi", "neu", "xac_minh")}, d["loi"])
        if viec in ("dung", "xoa"):
            _luu_x(lambda xx: xx.__setitem__("bo_hoc", sorted(set(xx.get("bo_hoc") or []) | {id_})))
            return "Đã bỏ đề xuất."
    raise ValueError(f"không làm được «{viec}» cho {id_ or 'trường hợp này'}")


# ── Kiểm điều kiện lúc chạy ────────────────────────────────────────────────
def _trong_khung(tu: str, den: str, luc: float) -> bool:
    from datetime import datetime, timedelta, timezone
    d = datetime.fromtimestamp(luc, timezone(timedelta(hours=7)))
    p = d.hour * 60 + d.minute
    a, b = (int(x[:2]) * 60 + int(x[3:]) for x in (tu, den))
    return a <= p < b if a <= b else (p >= a or p < b)


def _da_o_trong(ma: str, la: str, tu: float) -> bool:
    """``ma`` có ở trạng thái ``la`` lúc nào đó từ ``tu`` tới nay không (sổ lịch sử: đổi SANG hoặc RỜI trạng thái đó)."""
    import sqlite3
    from services import cam_bien_ghep, lich_su_nha
    ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    try:
        if cam_bien_ghep.la_ghep(ma):           # cảm biến ghép không có sổ riêng — dựng từ cảm biến gốc
            return any(g == la for _, g in cam_bien_ghep.chuoi(ro, ma, tu, time.time() + 1))
        return ro.execute("SELECT 1 FROM su_kien WHERE thiet_bi=? AND truong='state' AND ts>=?"
                          " AND (gia_tri=? OR gia_tri_cu=?) LIMIT 1", (ma, tu, la, la)).fetchone() is not None
    finally:
        ro.close()


def _doi_luc(ma: str, st: dict[str, Any], luc: float) -> float:
    """Lúc ``ma`` đổi sang trạng thái hiện tại: `last_changed` của HA; cảm biến ghép thì dựng từ cảm biến gốc."""
    from datetime import datetime
    from services import cam_bien_ghep
    if cam_bien_ghep.la_ghep(ma):
        import sqlite3
        from services import lich_su_nha
        ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
        try:
            ch = cam_bien_ghep.chuoi(ro, ma, luc - 86400, luc + 1)
        finally:
            ro.close()
        return ch[-1][0] if ch else luc
    try:
        return datetime.fromisoformat(str(st.get("last_changed"))).timestamp()
    except ValueError:
        return luc


def _dung_yen(ma: str, gt: str, giay: int, lech: float, luc: float) -> bool:
    """Khoảng cách ``ma`` ĐỨNG YÊN suốt ``giay`` giây vừa qua: các số đo CÓ mục tiêu (> 0; gộp 5 phút: nhỏ nhất / lớn
    nhất) cùng giá trị hiện tại lệch nhau không quá ``lech``. Số 0 = radar không thấy CỬ ĐỘNG — người nằm yên cũng
    về 0 — nên không phá «đứng yên»; luật phải kèm cảm biến có người bật liền để 0 không bị hiểu là «nhà trống».

    Chủ máy 05/10/2026: nhận ra «có người ngủ ở phòng khách» = giờ ngủ + radar có người liên tục 30 phút + khoảng cách
    đứng yên. Đo 14 đêm: radar phòng khách về 0 ở 371/392 ô 5 phút giờ ngủ, chuỗi liền có số dài nhất 10 phút — bản
    «mọi số > 0» không bao giờ đúng với radar này."""
    import sqlite3
    from services import lich_su_nha
    ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    try:
        hang = ro.execute("SELECT nho, lon FROM so_do WHERE thiet_bi=? AND truong='state' AND o_5p>=? AND o_5p<=?",
                          (ma, int((luc - giay) // 300), int(luc // 300))).fetchall()
    finally:
        ro.close()
    try:
        so = [float(gt)]
    except ValueError:
        so = []
    so = [x for x in so + [float(v) for r in hang for v in r if v is not None] if x > 0]
    return not so or max(so) - min(so) <= lech


def kiem_dieu_kien(neu: list[dict[str, Any]], luc: float,
                   trang_thai: dict[str, dict[str, Any]] | None = None) -> tuple[bool, list[str]]:
    """(mọi điều kiện cùng đúng?, giá trị đọc được từng điều kiện). Trạng thái HA đọc MỘT lần cho cả luật; giá trị
    lưu kèm lần làm để khi bị chấm sai thì bot thấy điều kiện nào đã khớp với số nào."""
    from services import ha_client, lich_sinh_hoat as lsh

    if trang_thai is None:
        trang_thai = {str(s["entity_id"]): s for s in ha_client.get_states() or []}
    from services import cam_bien_ghep
    if cam_bien_ghep.ds():
        # Cảm biến ghép không có trong trạng thái HA — tính từ CHÍNH trạng thái đang xét (cùng một lúc).
        tt = {m: str(v.get("state") or "").lower() for m, v in trang_thai.items()}
        trang_thai = {**trang_thai, **{g["entity_id"]: g for g in cam_bien_ghep.hien_tai(tt)}}
    dung, doc = True, []
    for x in neu:
        ma = x["ma"]
        if ma == "gio":
            ok, gt = _trong_khung(x["tu"], x["den"], luc), "giờ hiện tại"
        elif ma == "lich":
            m = lsh.tim(x["la"])
            ok, gt = bool(m and lsh.trong(m, luc)), "lịch"
        elif ma == "ca_nha":
            ok, gt = lsh.ca_nha(x["la"], luc), "lịch cả nhà"
        elif ma == "troi":
            from services import troi
            t = troi.toi(luc)
            ok = (t is True) if x["la"] == "toi" else (t is False)
            gt = "không biết trời" if t is None else ("trời tối" if t else "trời sáng")
        else:
            st = trang_thai.get(ma) or {}
            gt = str(st.get("state") or "")
            if x.get("dung_yen_giay"):
                ok = _dung_yen(ma, gt, int(x["dung_yen_giay"]), float(x.get("lech") or 0.3), luc)
            elif "duoi" in x or "tren" in x:
                # Radar mmwave báo 0 (hoặc không đọc được) = KHÔNG bắt được mục tiêu, không phải «0 mét». `vung_khoang_cach`
                # đã xử lý thế từ lâu; đường luật duyệt trước đây so thô nên 0 < ngưỡng = «có người gần» (sai dương) và
                # 0 > ngưỡng = False khiến luật TẮT «người rời, không ai trong X» KHÔNG BAO GIỜ chạy (đo 04/10/2026:
                # luật #20 bị chặn 96 lần vì distance=0). Nay: không mục tiêu → «gần hơn X» sai, «xa hơn X / không ai
                # trong X» đúng. Chỉ áp cho cảm biến ĐỘ DÀI (device_class distance hoặc đơn vị m/cm/mm), số khác giữ nguyên.
                a = st.get("attributes") or {}
                la_do_dai = a.get("device_class") == "distance" or a.get("unit_of_measurement") in ("m", "cm", "mm")
                try:
                    v: float | None = float(gt)
                except ValueError:
                    v = None
                if la_do_dai and (v is None or v <= 0):
                    ok = "tren" in x
                elif v is None:
                    ok = False
                else:
                    ok = v < x["duoi"] if "duoi" in x else v > x["tren"]
            elif x.get("trong_giay"):
                ok = gt == x["la"] or _da_o_trong(ma, x["la"], luc - x["trong_giay"])
            else:
                ok = gt == x["la"]
                # Giữ bao lâu mới tin: điều kiện ghi rõ `lien_giay`, HOẶC cảm biến NHIỄU thì tự lọc mềm bằng ngưỡng
                # giữ học từ chính nó (chủ máy 04/10/2026: "một đổi chỉ tính là thật khi giữ ≥ ngưỡng"). Lọc mềm
                # không áp cho điều kiện phủ định (vd «cửa KHÔNG mở»): một cảm biến nhiễu vừa chớp sang «on» thì
                # «không on» vẫn nên tin ngay, chờ đủ lâu mới coi là mở sẽ bỏ sót.
                giu = x.get("lien_giay")
                if ok and giu is None and not x.get("phu_dinh"):
                    try:
                        from services import do_tin_cam_bien
                        giu = do_tin_cam_bien.nguong_giu_nhanh(ma, luc)
                    except Exception:  # noqa: BLE001 — thiếu độ tin thì không lọc, tin như cũ
                        giu = None
                if ok and giu:
                    ok = luc - _doi_luc(ma, st, luc) >= giu
        if x.get("phu_dinh"):
            ok = not ok
        doc.append(f"{ma}={gt}{'✓' if ok else '✗'}")
        dung = dung and ok
    return dung, doc


# ── Báo ─────────────────────────────────────────────────────────────────────
def _doc_dk(x: dict[str, Any], ten: dict[str, str]) -> str:
    """Một điều kiện → chữ người đọc."""
    from services import hieu_thiet_bi_nha as ht
    if x["ma"] == "gio":
        s = f"trong {x['tu']}–{x['den']}"
    elif x["ma"] == "lich":
        s = f"đang lịch «{x['la']}»"
    elif x["ma"] == "ca_nha":
        s = "cả nhà đang ngủ" if x["la"] == "ngu" else "cả nhà đi vắng"
    elif x["ma"] == "troi":
        s = "trời tối" if x["la"] == "toi" else "trời sáng"
    elif x.get("dung_yen_giay"):
        s = (f"{ten.get(x['ma'], x['ma'])} đứng yên (lệch ≤ {x['lech']:g}{' ' + x['_dv'] if x.get('_dv') else ''})"
             f" liền {x['dung_yen_giay']} giây")
    else:
        s = ht._dieu_kien_doc(x, ten, ten) + (f" {x['_dv']}" if x.get("_dv") and ("duoi" in x or "tren" in x)
                                             else "") + (f" liền {x['lien_giay']} giây" if x.get("lien_giay") else "") + (
            f" (trong {x['trong_giay']} giây vừa qua)" if x.get("trong_giay") else "")
    return f"KHÔNG ({s})" if x.get("phu_dinh") else s


def _doc_khi(l: dict[str, Any], ten: dict[str, str]) -> str:
    return " hoặc ".join(f"{ten.get(k.split(' ')[0], k.split(' ')[0])} {k.split(' ', 1)[1]}" for k in l["khi"])


def doc_dong(l: dict[str, Any], ten: dict[str, str]) -> list[str]:
    """Từng dòng đọc được — «Khi …», mỗi điều kiện một dòng, «nhìn lại camera» nếu có — cho trang web."""
    return ([f"Khi {_doc_khi(l, ten)}"] + [_doc_dk(x, ten) for x in l.get("neu") or []]
            + (["Nhìn lại camera trước khi làm"] if l.get("xac_minh") else []))


def doc_luat(l: dict[str, Any], ten: dict[str, str]) -> str:
    neu = (", nếu " + ", ".join(_doc_dk(x, ten) for x in l["neu"])) if l["neu"] else ""
    return f"khi {_doc_khi(l, ten)}{neu} → {_NEN_DOC[l['nen']]}" + (" (nhìn lại camera trước)" if l["xac_minh"] else "")


def bao(tb: str, kq: dict[str, Any]) -> str:
    """Báo lần chuyển rồi HỎI TỪNG LUẬT một (`hoi_tiep`). Chủ máy 05/10/2026: "bot phải hỏi tôi duyệt từng trường
    hợp, khoảng cách như nào. Nếu đúng thì nhắn đúng, nếu sai thì tôi nhắn «sửa …» các thông tin sai"."""
    from services import hieu_thiet_bi_nha as ht, kich_hoat_nha as kh

    ten = kh._ten_ha()
    th = kq.get("truong_hop") or []
    giu = set(kq.get("giu") or [])
    hoi = [l for l in kq["luat"] if l["so"] not in giu]
    dong = [f"⚙️ {ten.get(tb, tb)}: em chuyển {len(kq['luat'])} trường hợp anh duyệt thành luật (lần {kq['id']})."]
    if giu:
        dong.append(f"{len(giu)} luật giữ nguyên như anh đã duyệt: {', '.join(str(x) for x in sorted(giu))}.")
    if hoi:
        dong.append(f"Em hỏi anh lần lượt {len(hoi)} luật còn lại — luật anh nhắn «đúng» mới chạy.")
    for k in kq.get("khong_chuyen_duoc") or []:
        dong.append(f"{k['so']}. «{th[k['so'] - 1][:70]}» → chưa chuyển được: {k['ly_do']}")
    if kq.get("loi"):
        dong.append("Lỗi em tự loại: " + "; ".join(kq["loi"][:4]))
    tin = "\n".join(dong)
    ht.bao_nhom(tin)
    from services import loi_khuyen_nha
    xep_hoi(loi_khuyen_nha.muc_xac_nhan(tb))       # sau các luật: hỏi thời gian ở lại, thời gian vắng — từng cái
    return tin


# ── Hỏi chủ nhà TỪNG luật ──────────────────────────────────────────────────
#: Câu hỏi chờ quá ngần này thì thôi chờ (tin trôi): lượt hỏi kế gửi lại đúng câu đó.
CHO_HOI_GIAY = 24 * 3600


def _hoi_path() -> Path:
    return _PATH.with_name("luat_duyet_hoi.json")


def _hoi_nap() -> dict[str, Any]:
    try:
        return json.loads(_hoi_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _hoi_luu(d: dict[str, Any]) -> None:
    p = _hoi_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _chua_hoi() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(thiết bị, lần, luật) của lần giải MỚI NHẤT mỗi thiết bị mà chủ nhà chưa trả lời."""
    ra = []
    for tb, x in _nap().items():
        if not x.get("lan"):
            continue
        lan = x["lan"][-1]
        da = {c["so"] for c in x.get("cham") or [] if c["lan"] == lan["id"] and c["cham_boi"] == "chu_may"}
        # Anh đã quyết trên web (tạm dừng / sửa thành luật của anh) thì khỏi hỏi qua Zalo nữa.
        xong = set(x.get("dung") or []) | {c.get("loi") for c in x.get("chu") or []}
        th = lan.get("truong_hop") or []
        ra += [(tb, lan, l) for l in lan["luat"] if l["so"] not in da
               and (th[l["so"] - 1] if l["so"] <= len(th) else None) not in xong]
    return ra


def xep_hoi(muc: list[dict[str, Any]]) -> None:
    """Thêm câu hỏi THỜI GIAN (xác nhận / lời khuyên — `loi_khuyen_nha`) vào hàng; câu trùng (cùng kiểu, thiết bị,
    loại) thay câu cũ. Gửi câu kế nếu chưa có câu nào chờ."""
    with _khoa:
        h = _hoi_nap()
        hang = [x for x in h.get("hang") or []
                if not any((x["kieu"], x["tb"], x["loai"]) == (m["kieu"], m["tb"], m["loai"]) for m in muc)]
        h["hang"] = hang + list(muc)
        _hoi_luu(h)
    hoi_tiep()


def _cau(tb: str, lan: dict[str, Any], l: dict[str, Any], con: int) -> str:
    from services import ha_client, kich_hoat_nha as kh

    ten = kh._ten_ha()
    th = lan.get("truong_hop") or []
    dv = {str(s["entity_id"]): str((s.get("attributes") or {}).get("unit_of_measurement") or "")
          for s in ha_client.get_states() or []}
    l2 = {**l, "neu": [{**n, "_dv": dv.get(n["ma"], "")} for n in l["neu"]]}
    return (f"⚙️ {ten.get(tb, tb)} — trường hợp {l['so']} (lần {lan['id']}, còn {con} câu chờ anh):\n"
            f"«{th[l['so'] - 1] if l['so'] <= len(th) else ''}»\n"
            f"→ Em hiểu: {doc_luat(l2, ten)}.\n"
            "Đúng thì anh nhắn «đúng»; sai chỗ nào anh nhắn «sửa …» (vd «sửa khoảng cách dưới 3 m», «sửa vắng 30 "
            "giây», «sửa thêm cam bếp xác nhận»).")


def _cau_thoi_gian(m: dict[str, Any], con: int) -> str:
    from services import kich_hoat_nha as kh, loi_khuyen_nha as lk

    ten = kh._ten_ha().get(m["tb"], m["tb"])
    loai = lk._TEN[m["loai"]]
    y = ("chờ người ở lại bao lâu mới bật" if m["loai"] == "o_lai" else "phòng vắng bao lâu thì tắt")
    if m["kieu"] == "cai_dat":
        return (f"⏱️ {ten} — {loai} ({y}), còn {con} câu chờ anh:\nEm đang dùng: {lk.doc_giay(m['cu'])}.\n"
                "Đúng thì anh nhắn «đúng»; khác thì nhắn «sửa …» (vd «sửa 30 giây», «sửa 2 phút»).")
    return (f"💡 {ten} — lời khuyên {loai} ({y}), còn {con} câu chờ anh:\n{m['vi']}.\n"
            f"Em khuyên đổi {lk.doc_giay(m['cu'])} → {lk.doc_giay(m['moi'])}.\n"
            "Anh nhắn «đồng ý» để em đổi, «không» để giữ nguyên, hoặc «sửa …» số khác.")


def hoi_tiep(*, ep: bool = False) -> str | None:
    """Gửi câu hỏi kế — MỘT luật hoặc MỘT thời gian (luật trước). Đang có câu chờ chưa quá hạn thì thôi (``ep`` = gửi
    ngay câu kế)."""
    from services import hieu_thiet_bi_nha as ht

    with _khoa:
        h = _hoi_nap()
        c = h.get("cho")
        if c and not ep and time.time() - float(c.get("luc") or 0) < CHO_HOI_GIAY:
            return None
        ds = _chua_hoi()
        hang = h.get("hang") or []
        con = len(ds) + len(hang)
        if ds:
            tb, lan, l = ds[0]
            h["cho"] = {"kieu": "luat", "tb": tb, "lan": lan["id"], "so": l["so"], "luc": time.time()}
            tin = _cau(tb, lan, l, con)
        elif hang:
            m = hang[0]
            h["cho"] = {**m, "luc": time.time()}
            tin = _cau_thoi_gian(m, con)
        else:
            h.pop("cho", None)
            _hoi_luu(h)
            return None
        _hoi_luu(h)
    ht.bao_nhom(tin)
    return tin


_DUNG = {"đúng", "dung", "đúng rồi", "dung roi", "đúng ạ", "chuẩn", "ok", "duyệt", "đồng ý", "dong y", "có", "co"}
_KHONG = {"không", "khong", "ko", "giữ", "giữ nguyên", "giu nguyen", "không đổi"}


def _tra_loi_thoi_gian(c: dict[str, Any], dung: bool, khong: bool, sua: str | None) -> str:
    from services import kich_hoat_nha as kh, loi_khuyen_nha as lk

    ten = kh._ten_ha().get(c["tb"], c["tb"])
    loai = lk._TEN[c["loai"]]
    if sua is not None:
        g = lk.doc_so(sua)
        if g is None:
            raise ValueError(f"Em chưa đọc được số trong «{sua}» — anh nhắn kiểu «sửa 30 giây» / «sửa 2 phút» ạ.")
        lk.dat(c["tb"], c["loai"], g)
        return f"Dạ, {ten}: em đặt {loai} = {lk.doc_giay(g)}."
    if c["kieu"] == "khuyen" and dung:
        lk.dat(c["tb"], c["loai"], float(c["moi"]))
        return f"Dạ, {ten}: em đổi {loai} {lk.doc_giay(c['cu'])} → {lk.doc_giay(c['moi'])}."
    if c["kieu"] == "khuyen" or khong:
        return f"Dạ, {ten}: em giữ nguyên {loai} {lk.doc_giay(c['cu'])}."
    return f"Dạ, {ten}: {loai} {lk.doc_giay(c['cu'])} anh xác nhận."


_LOAI_HIEU = ("duyet", "sua", "bo", "khong", "sai_chua_ro", "khong_lien_quan")


def _hieu(c: dict[str, Any], t: str) -> dict[str, str] | None:
    """Lời TỰ NHIÊN của chủ nhà cho câu đang chờ → {loai, noi_dung, dap} (model đọc hiểu, hướng dẫn
    `hieu_tra_loi_duyet.md`). None = không hiểu được / model lỗi.

    Chủ máy 05/10/2026 trả lời câu luật #16 bằng «điều kiện này sai», «bỏ điều kiện này đi», «trường hợp 16 xoá
    bỏ», «bỏ 16» — bản đầu chỉ khớp chuỗi «đúng» / «sửa …» nên cả 5 tin rơi sang bot chat, bot chat không biết câu
    nào đang chờ và đòi gửi lại danh sách. Khớp thêm từ khoá thì vẫn thiếu; để model hiểu theo NGỮ CẢNH câu hỏi."""
    from services import hieu_thiet_bi_nha as ht, kich_hoat_nha as kh, loi_khuyen_nha as lk

    ten = kh._ten_ha()
    if (c.get("kieu") or "luat") == "luat":
        lan = next((l for l in (_nap().get(c["tb"]) or {}).get("lan") or [] if l["id"] == c["lan"]), None)
        l = next((x for x in (lan or {}).get("luat") or [] if x["so"] == c["so"]), None)
        if l is None:
            return None
        th = (lan.get("truong_hop") or [""] * c["so"])[c["so"] - 1]
        mo_ta = f"luật cho {ten.get(c['tb'], c['tb'])}, trường hợp {c['so']} «{th}» → em hiểu: {doc_luat(l, ten)}"
    else:
        mo_ta = (f"{lk._TEN[c['loai']]} của {ten.get(c['tb'], c['tb'])}: đang dùng {lk.doc_giay(c.get('cu'))}"
                 + (f"; em khuyên đổi thành {lk.doc_giay(c.get('moi'))}" if c["kieu"] == "khuyen" else ""))
    huong, _ = ht.huong_dan("hieu_tra_loi_duyet")
    r = ht._goi_model(ht._model(), huong, f"A. Em đã hỏi: {mo_ta}\nB. Chủ nhà nhắn: {t[:400]}")
    if r.get("error"):
        logger.warning({"event": "luat_duyet_hieu_loi", "loi": str(r["error"])[:160]})
        return None
    data = ht._doc_json(str(((r.get("choices") or [{}])[0].get("message") or {}).get("content") or "")) or {}
    loai = str(data.get("loai") or "")
    if loai not in _LOAI_HIEU:
        return None
    logger.info({"event": "luat_duyet_hieu", "loai": loai, "tb": c["tb"]})
    return {"loai": loai, "noi_dung": str(data.get("noi_dung") or "")[:300], "dap": str(data.get("dap") or "")[:300]}


def _bo_truong_hop(tb: str, lan_id: int, so_th: int) -> str:
    """Chủ nhà bảo BỎ trường hợp: gỡ khỏi danh sách đã duyệt (`kich_ban_nha`), tìm theo LỜI trường hợp (số có thể đã
    đổi). Trả lời trường hợp đã bỏ, "" nếu không còn trong danh sách."""
    from services import kich_ban_nha as kb
    lan = next((l for l in (_nap().get(tb) or {}).get("lan") or [] if l["id"] == lan_id), None)
    th = ((lan or {}).get("truong_hop") or [])
    loi = th[so_th - 1] if 1 <= so_th <= len(th) else ""
    x = kb.duyet().get(tb) or {}
    for h in ("bat", "tat"):
        for i, m in enumerate(x.get(h) or []):
            if m.get("tinh_huong") == loi:
                kb.sua_duyet(tb, h, "bo", i + 1)
                return loi
    return ""


def tra_loi(text: str, *, sau: float = 0.0, hieu: bool = True) -> str | None:
    """Lời chủ nhà cho câu đang chờ.

    * Câu LUẬT: «đúng» → chấm đúng (luật chạy); «sửa …» → chấm sai kèm lời sửa (vào đề lần sau, mục D); «bỏ» → bỏ
      hẳn trường hợp khỏi danh sách đã duyệt. Hỏi hết các luật của thiết bị mà có luật bị sửa thì bot chuyển lại.
    * Câu THỜI GIAN: «đúng» giữ; «sửa 30 giây» đặt số mới. Câu LỜI KHUYÊN: «đồng ý» đổi theo lời khuyên, «không» giữ.
    * Lời tự nhiên khác: model hiểu theo ngữ cảnh câu đang chờ (`_hieu`).

    ``sau``: mốc câu hỏi KHÁC đang chờ (vd bot vừa tự bật đèn hỏi đúng/sai) — câu này cũ hơn mốc đó thì lời không
    mở đầu bằng «sửa» không thuộc về nó. ``hieu=False``: chỉ khớp «đúng» / «sửa …» / «không» (rẻ, chạy trước các
    đường trả lời khác); model đọc hiểu chạy ở lượt sau cùng. None = không phải lời cho câu đang chờ."""
    import unicodedata
    t = unicodedata.normalize("NFC", str(text or "")).strip()
    thap = t.lower()
    m = re.match(r"^(sửa|sua)\b\s*[:：]?\s*(.+)$", thap, re.S)
    tron = " ".join(re.sub(r"[^\w\s]", " ", thap).split())
    dung, khong, bo = tron in _DUNG, tron in _KHONG, False
    sua = t[m.start(2):].strip() if m else None
    if not t:
        return None
    with _khoa:
        c = _hoi_nap().get("cho")
    if not c or time.time() - float(c.get("luc") or 0) >= 3 * CHO_HOI_GIAY:
        return None
    if sua is None and float(c["luc"]) < sau:
        return None
    if not (sua is not None or dung or khong):
        if not hieu:
            return None
        y = _hieu(c, t)
        if y is None or y["loai"] == "khong_lien_quan":
            return None
        if y["loai"] == "sai_chua_ro":
            return y["dap"] or "Dạ, sai chỗ nào ạ? Anh nhắn «sửa …» (vd «sửa khoảng cách dưới 3 m») hoặc «bỏ» giúp em."
        dung, khong, bo = y["loai"] == "duyet", y["loai"] == "khong", y["loai"] == "bo"
        if y["loai"] == "sua":
            sua = y["noi_dung"] or t
    with _khoa:
        if _hoi_nap().get("cho") != c:
            return None                         # câu chờ vừa đổi (trả lời khác tới trước) — lời này không còn khớp
        kieu = c.get("kieu") or "luat"
        if kieu != "luat":
            try:
                dap = _tra_loi_thoi_gian(c, dung, khong or bo, sua)
            except ValueError as exc:
                return str(exc)
            h = _hoi_nap()
            h.pop("cho", None)
            h["hang"] = [x for x in h.get("hang") or []
                         if (x["kieu"], x["tb"], x["loai"]) != (c["kieu"], c["tb"], c["loai"])]
            _hoi_luu(h)
            threading.Thread(target=hoi_tiep, kwargs={"ep": True}, name="luat-duyet-hoi", daemon=True).start()
            return dap
        if khong and sua is None and not bo:
            return "Luật này sai chỗ nào anh nhắn «sửa …» giúp em (vd «sửa khoảng cách dưới 3 m»), hoặc «bỏ» ạ."
        tb, lan_id, so_th = c["tb"], int(c["lan"]), int(c["so"])
        if bo:
            ok = cham(tb, so_th, False, cham_boi="chu_may", ghi_chu="chủ nhà BỎ trường hợp này", lan_id=lan_id)
        elif sua is not None:
            ok = cham(tb, so_th, False, cham_boi="chu_may", ghi_chu=f"chủ nhà sửa: {sua}", lan_id=lan_id)
        else:
            ok = cham(tb, so_th, True, cham_boi="chu_may", ghi_chu="chủ nhà duyệt", lan_id=lan_id)
        h = _hoi_nap()
        h.pop("cho", None)
        if sua is not None and ok:
            h.setdefault("sua", {})[tb] = lan_id
        con_tb = any(t_ == tb for t_, _, _ in _chua_hoi())
        lai = None if con_tb else h.get("sua", {}).pop(tb, None)
        _hoi_luu(h)
    if not ok:
        return "Luật đó em không còn giữ (đã chuyển lần mới) ạ."
    if bo:
        loi = _bo_truong_hop(tb, lan_id, so_th)
        dap = (f"Dạ, em bỏ trường hợp {so_th}" + (f" «{loi[:80]}»" if loi else "")
               + " khỏi danh sách anh duyệt — luật này không chạy nữa.")
    elif sua is not None:
        dap = f"Dạ, em ghi trường hợp {so_th} cần sửa: «{sua}». Hỏi xong các luật còn lại em chuyển lại theo lời anh."
    else:
        dap = f"Dạ, luật trường hợp {so_th} anh duyệt — từ giờ em chạy theo luật này."
    if lai is not None:
        threading.Thread(target=giai_va_bao, args=(tb,), name="luat-duyet-sua", daemon=True).start()
        dap += " Em đang chuyển lại các luật anh sửa, xong em hỏi lại anh."
    else:
        threading.Thread(target=hoi_tiep, kwargs={"ep": True}, name="luat-duyet-hoi", daemon=True).start()
    return dap


def giai_va_bao(tb: str) -> dict[str, Any]:
    kq = giai(tb)
    if kq.get("ok"):
        bao(tb, kq)
    return kq


def _reset_for_tests(duong: Path) -> None:
    global _PATH
    _PATH = duong
