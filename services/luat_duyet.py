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
    for s in ha_client.get_states() or []:
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

    Chỉ CHỦ NHÀ quyết. Chủ máy 05/10/2026: "Bạn không có quyền xác nhận luật, bạn chỉ chấm đúng sai dựa trên cơ sở là
    tôi mô tả, mọi việc tôi quyết mới là đúng, bot phán đoán đưa tôi quyết định là làm luôn". Lời GIÁO VIÊN chấm
    (``cham_boi='claude'``) chỉ là ghi chú vào đề lần sau (mục D), không làm luật nào chạy hay thôi chạy.

    Khoá theo LỜI trường hợp, không theo số: thêm trường hợp làm số đổi, lời thì không. Mỗi luật kèm ``lan`` để lần
    chạy sai truy về đúng bài."""
    with _khoa:
        x = _nap().get(tb) or {}
    ds_lan = x.get("lan") or []
    if not ds_lan:
        return []
    theo_id = {l["id"]: l for l in ds_lan}
    quyet: dict[str, tuple[bool, int, int]] = {}            # lời trường hợp → (đúng?, lần, số)
    for c in x.get("cham") or []:                           # sổ ghi theo thời gian: lời sau đè lời trước
        lan = theo_id.get(c["lan"])
        if c.get("cham_boi") != "chu_may" or lan is None:
            continue
        th = lan.get("truong_hop") or []
        if 1 <= c["so"] <= len(th):
            quyet[th[c["so"] - 1]] = (bool(c["dung"]), lan["id"], c["so"])
    ra = []
    for loi in ds_lan[-1].get("truong_hop") or []:
        q = quyet.get(loi)
        if not q or not q[0]:
            continue
        l = next((l for l in theo_id[q[1]]["luat"] if l["so"] == q[2]), None)
        if l is not None:
            ra.append({**l, "lan": q[1]})
    return ra


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
    from services import lich_su_nha
    ro = sqlite3.connect(f"file:{lich_su_nha._DB_PATH}?mode=ro", uri=True, timeout=10.0)
    try:
        return ro.execute("SELECT 1 FROM su_kien WHERE thiet_bi=? AND truong='state' AND ts>=?"
                          " AND (gia_tri=? OR gia_tri_cu=?) LIMIT 1", (ma, tu, la, la)).fetchone() is not None
    finally:
        ro.close()


def kiem_dieu_kien(neu: list[dict[str, Any]], luc: float,
                   trang_thai: dict[str, dict[str, Any]] | None = None) -> tuple[bool, list[str]]:
    """(mọi điều kiện cùng đúng?, giá trị đọc được từng điều kiện). Trạng thái HA đọc MỘT lần cho cả luật; giá trị
    lưu kèm lần làm để khi bị chấm sai thì bot thấy điều kiện nào đã khớp với số nào."""
    from datetime import datetime
    from services import ha_client, lich_sinh_hoat as lsh

    if trang_thai is None:
        trang_thai = {str(s["entity_id"]): s for s in ha_client.get_states() or []}
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
            if "duoi" in x or "tren" in x:
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
                    try:
                        tu = datetime.fromisoformat(str(st.get("last_changed"))).timestamp()
                    except ValueError:
                        tu = luc
                    ok = luc - tu >= giu
        if x.get("phu_dinh"):
            ok = not ok
        doc.append(f"{ma}={gt}{'✓' if ok else '✗'}")
        dung = dung and ok
    return dung, doc


# ── Báo ─────────────────────────────────────────────────────────────────────
def doc_luat(l: dict[str, Any], ten: dict[str, str]) -> str:
    from services import hieu_thiet_bi_nha as ht

    def dk(x: dict[str, Any]) -> str:
        if x["ma"] == "gio":
            s = f"trong {x['tu']}–{x['den']}"
        elif x["ma"] == "lich":
            s = f"đang lịch «{x['la']}»"
        elif x["ma"] == "ca_nha":
            s = "cả nhà đang ngủ" if x["la"] == "ngu" else "cả nhà đi vắng"
        elif x["ma"] == "troi":
            s = "trời tối" if x["la"] == "toi" else "trời sáng"
        else:
            s = ht._dieu_kien_doc(x, {}, ten) + (f" {x['_dv']}" if x.get("_dv") and ("duoi" in x or "tren" in x)
                                                 else "") + (f" liền {x['lien_giay']} giây" if x.get("lien_giay") else "") + (
                f" (trong {x['trong_giay']} giây vừa qua)" if x.get("trong_giay") else "")
        return f"KHÔNG ({s})" if x.get("phu_dinh") else s

    khi = " hoặc ".join(f"{ten.get(k.split(' ')[0], k.split(' ')[0])} {k.split(' ', 1)[1]}" for k in l["khi"])
    neu = (", nếu " + ", ".join(dk(x) for x in l["neu"])) if l["neu"] else ""
    return f"khi {khi}{neu} → {_NEN_DOC[l['nen']]}" + (" (nhìn lại camera trước)" if l["xac_minh"] else "")


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
        ra += [(tb, lan, l) for l in lan["luat"] if l["so"] not in da]
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
