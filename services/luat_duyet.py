"""LUẬT từ trường hợp chủ nhà đã DUYỆT — bot chuyển từng trường hợp thành luật chạy được, giáo viên / chủ nhà chấm.

Chủ máy 02/10/2026: duyệt trường hợp bật rồi tắt (`kich_ban_nha` — «Duyệt trường hợp BẬT rồi TẮT»), "rồi thực hiện
đúng theo đó và hỏi lại để học cách làm đúng hơn, xem đã làm đúng chưa, chưa đúng thì nhìn lại ở đâu không đạt,
chỉnh lại cho phù hợp". Trường hợp đã duyệt là LỜI; bộ kích hoạt cần mã cảm biến, ngưỡng, khung giờ.

Cùng khung các tầng học khác (vai giáo viên): CODE bày đề (trường hợp đã duyệt, cảm biến THẬT kèm mã / loại / đơn vị /
số bot đã học, lịch sinh hoạt, lời chấm trước) và KIỂM Ở BIÊN (mã có thật, dạng điều kiện đúng); BOT (hướng dẫn
`chuyen_truong_hop.md`) viết luật; giáo viên / chủ nhà CHẤM từng luật, lời chấm vào đề lần sau. Luật chỉ áp khi
được chấm ĐÚNG (`ap`).

Dạng điều kiện là dạng chung của các tầng học (câu thói quen): ``{"ma", "la"}``, ``{"ma", "duoi"|"tren"}``,
``{"ma": "gio", "tu", "den"}``; thêm ``{"ma": "lich", "la": <mã lịch>}``, ``{"ma": "ca_nha", "la": "ngu"|"vang"}``
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
_NGUON_RE = re.compile(r"^binary_sensor\.[a-z0-9_]+ (có người vào|vắng|ở lại (\d{1,4}) giây)$")
#: «ở lại N giây»: N trong khoảng này (dưới 10 giây là nhiễu, trên một giờ là chuyện khác).
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
    from services import kich_hoat_nha as kh, lich_sinh_hoat, vung_khoang_cach

    ten = kh._ten_ha()
    cb = cam_bien()
    th = truong_hop(tb)
    dong = [f"THIẾT BỊ: {tb} | {ten.get(tb, tb)}", "", "A. TRƯỜNG HỢP CHỦ NHÀ ĐÃ DUYỆT:"]
    dong += [f"{i}. [{'BẬT' if m['chieu'] == 'bat' else 'TẮT'}] {m['tinh_huong']} → nên {m['nen']}"
             + (f" (cảm biến thấy: {m['cam_bien_thay']})" if m.get("cam_bien_thay") else "")
             for i, m in enumerate(th, 1)]
    dong += ["", "B. CẢM BIẾN kiểm được (mã | tên | khu | loại | đơn vị):"]
    dong.append(f"- {tb} | {ten.get(tb, tb)} | (chính thiết bị đang xét) | on = đang bật")
    dong += [f"- {c['ma']} | {c['ten']} | {c['khu']} | {c['loai']}" + (f" | {c['don_vi']}" if c["don_vi"] else "")
             for c in cb]
    vung = []
    for ma, v in vung_khoang_cach.ds().items():
        d = vung_khoang_cach.vung_dang_dung(v)
        if d:
            vung.append(f"- {ma}: người ở TRONG khu khi {'dưới' if d[0] == 'duoi' else 'từ'} {d[1]:g}"
                        f" (radar {v.get('radar', '?')})")
    if vung:
        dong += ["", "B2. VÙNG KHOẢNG CÁCH bot đã học (số đo thật, dùng làm ngưỡng):"] + vung
    trung = _cam_bien_trung([c["ma"] for c in cb])
    if trung:
        dong += ["", "B3. CẢM BIẾN GẦN NHƯ CÙNG MỘT TÍN HIỆU (đo trên lịch sử thật) — ĐỪNG viết điều kiện bắt chúng "
                 "KHÁC nhau (vd cái này on, cái kia off): như thế luật không bao giờ chạy. Dùng MỘT trong chúng, hoặc "
                 "cùng chiều:"]
        dong += [f"- {a} ≈ {b} (giống nhau {ti:.0%} số lần)" for a, b, ti in trung]
    do_tin = _do_tin_cam_bien([c["ma"] for c in cb])
    if do_tin:
        dong += ["", "B4. ĐỘ TIN cảm biến (đo lịch sử thật) — «nhiễu» hay đổi chớp nhoáng, ĐỪNG dựa chính vào nó; "
                 "dùng phải kèm xac_minh=true hoặc một cảm biến «lành»:"]
        dong += [f"- {ma}: {nh}" for ma, nh in do_tin]
    dong += ["", "C. LỊCH SINH HOẠT (mã | tên | loại | giờ):"]
    dong += [f"- {x['ma']} | {x['ten']} | {x['loai']} | {x['tu']}–{x['den']}" for x in lich_sinh_hoat.ds()] or ["(chưa có)"]
    sai = [c for c in (so().get(tb) or {}).get("chay_sai") or []][-10:]
    if sai:
        dong += ["", "E. LẦN CHẠY BỊ CHẤM SAI — luật đã làm, chủ nhà nói sai (hoặc tự làm ngược lại ngay). Tìm điều "
                 "kiện nào khớp mà lẽ ra không được khớp (✓ là điều kiện đã đúng lúc đó), sửa luật đó cho chặt hơn "
                 "hoặc thêm luật chặn; đừng bỏ trường hợp:"]
        dong += [f"- trường hợp {c['so']} lúc {c['gio']}: {', '.join(c['doc'])}"
                 + (f" — chủ nhà: {c['loi']}" if c.get("loi") else "") for c in sai]
    cham = [c for c in (so().get(tb) or {}).get("cham") or []][-15:]
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
        _luu(d)
    logger.info({"event": "luat_duyet_giai", "thiet_bi": tb, "luat": len(luat), "khong": len(khong), "loi": loi[:3]})
    return {"ok": True, **lan}


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
        tb = max((t for t, x in d.items() if x.get("lan")), key=lambda t: d[t]["lan"][-1]["luc"], default="")
    if not tb:
        return "Em chưa chuyển luật cho thiết bị nào ạ."
    if not cham(tb, so_th, dung, cham_boi="chu_may", ghi_chu=ghi_chu):
        return f"Lần chuyển mới nhất không có luật cho trường hợp {so_th} ạ."
    return (f"Dạ, em ghi luật {so_th} {'đúng — từ giờ em chạy theo luật này' if dung else 'sai — lần chuyển sau em sửa'}.")


def ap(tb: str) -> list[dict[str, Any]]:
    """Luật ĐANG ÁP: của lần giải MỚI NHẤT đã được chấm (lần mới chưa ai chấm thì lần đã chấm trước vẫn chạy), chỉ
    những luật chấm ĐÚNG (lần chấm sau cùng thắng). Mỗi luật kèm ``lan`` để lần chạy sai truy về đúng bài."""
    with _khoa:
        x = _nap().get(tb) or {}
    cham = x.get("cham") or []
    for lan in reversed(x.get("lan") or []):
        kq: dict[int, bool] = {}
        for c in cham:
            if c["lan"] == lan["id"]:
                kq[c["so"]] = c["dung"]
        if kq:
            return [{**l, "lan": lan["id"]} for l in lan["luat"] if kq.get(l["so"])]
    return []


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
        else:
            s = ht._dieu_kien_doc(x, {}, ten) + (f" liền {x['lien_giay']} giây" if x.get("lien_giay") else "") + (
                f" (trong {x['trong_giay']} giây vừa qua)" if x.get("trong_giay") else "")
        return f"KHÔNG ({s})" if x.get("phu_dinh") else s

    khi = " hoặc ".join(f"{ten.get(k.split(' ')[0], k.split(' ')[0])} {k.split(' ', 1)[1]}" for k in l["khi"])
    neu = (", nếu " + ", ".join(dk(x) for x in l["neu"])) if l["neu"] else ""
    return f"khi {khi}{neu} → {_NEN_DOC[l['nen']]}" + (" (nhìn lại camera trước)" if l["xac_minh"] else "")


def bao(tb: str, kq: dict[str, Any]) -> str:
    from services import hieu_thiet_bi_nha as ht, kich_hoat_nha as kh

    ten = kh._ten_ha()
    th = kq.get("truong_hop") or []
    dong = [f"⚙️ Luật em chuyển từ trường hợp anh đã duyệt — {ten.get(tb, tb)} (lần {kq['id']}):"]
    for l in kq["luat"]:
        dong.append(f"{l['so']}. «{th[l['so'] - 1][:70]}» → {doc_luat(l, ten)}")
    for k in kq.get("khong_chuyen_duoc") or []:
        dong.append(f"{k['so']}. «{th[k['so'] - 1][:70]}» → chưa chuyển được: {k['ly_do']}")
    if kq.get("loi"):
        dong.append("Lỗi em tự loại: " + "; ".join(kq["loi"][:4]))
    dong.append("Anh thấy luật nào sai thì nói «luật 3 sai, …» — em sửa lần sau. Luật được chấm đúng mới chạy.")
    tin = "\n".join(dong)
    ht.bao_nhom(tin)
    return tin


def giai_va_bao(tb: str) -> dict[str, Any]:
    kq = giai(tb)
    if kq.get("ok"):
        bao(tb, kq)
    return kq


def _reset_for_tests(duong: Path) -> None:
    global _PATH
    _PATH = duong
