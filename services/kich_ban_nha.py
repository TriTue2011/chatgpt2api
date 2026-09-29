"""KỊCH BẢN NHÀ — bot tự dựng những TÌNH HUỐNG đời thường cho từng thiết bị từ sơ đồ nhà, tự xét cách
đang cài có làm đúng không, chỗ chưa chắc thì HỎI chủ nhà — mỗi lần một câu.

Chủ máy 30/09/2026: "dựa vào sơ đồ nhà đã lên được mặt bằng chưa, căn cứ vào đó để tạo ra các tình
huống có thể xảy ra, cái nào chưa chắc chắn dữ kiện thì hỏi lại"; "quan trọng nhất là train bot, không
phải bạn làm. Sau đó xem bot có hoàn thiện được các tình huống cho đèn trần, quạt, đèn phòng ngủ",
"đèn cửa sổ và đèn tủ lạnh nữa".

Cùng khung các tầng học khác: CODE bày sơ đồ (đã chấm, hoặc bài mới nhất kèm nhãn chưa chấm), cảm
biến theo phòng (camera / sóng / cửa) và việc MỖI thiết bị đang được cài làm — bằng lời; BOT (hướng
dẫn `sinh_kich_ban.md`) dựng tình huống, xét đúng/sai, đặt câu hỏi; CHỦ NHÀ trả lời — câu trả lời vào
sổ mô tả của sơ đồ nhà (mọi tầng học đọc nó) và vào đề lần dựng sau.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

_PATH = Path(DATA_DIR) / "agent" / "kich_ban_nha.json"
_khoa = threading.RLock()
NEN = ("bat", "tat", "giu", "khong_lam", "hoi")
HIEN_TAI = ("dung", "sai", "khong_ro")
_NEN_DOC = {"bat": "bật", "tat": "tắt", "giu": "giữ nguyên", "khong_lam": "không làm gì", "hoi": "hỏi anh"}
#: Tối đa câu hỏi mỗi lượt dựng — hỏi dồn thì chủ nhà không trả lời hết (chủ máy 11/09: "xác minh lần lượt").
HOI_TOI_DA = 8


# ── Sổ ──────────────────────────────────────────────────────────────────────
def _nap() -> dict[str, Any]:
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("lan", [])
    d.setdefault("hoi", [])
    return d


def _luu(d: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_PATH)


def so() -> dict[str, Any]:
    with _khoa:
        return _nap()


# ── Đề ──────────────────────────────────────────────────────────────────────
def _viec_dang_cai(tb: str, cd: dict[str, Any], mh: dict[str, Any], ten: dict[str, str]) -> list[str]:
    """Việc thiết bị đang được cài làm, bằng lời — đúng những gì bộ kích hoạt sẽ làm lúc sống."""
    from services import cam_bien_ghep, kich_hoat_nha as kh
    from services.hieu_thiet_bi_nha import _bieu_thuc_doc

    ghep = cam_bien_ghep.ds()

    def cb(m: str) -> str:
        g = ghep.get(m)
        return f"«{_bieu_thuc_doc(g['bieu_thuc'], ten)}»" if g else ten.get(m, m)

    def nguon(n: str) -> str:
        ma, _, su = n.partition(" ")
        if su == "có người vào" and kh._la_cua(n):
            # Bày đủ cơ chế đang chạy: 30/09 bot hỏi "cảm biến cửa có phân biệt vào/ra không" vì đề thiếu.
            return (f"{cb(ma)} mở (chỉ khi trong {kh.CUA_XAC_NHAN_GIAY} giây khu của thiết bị có người MỚI vào"
                    " — người đi ra thì không)")
        return f"{cb(ma)} {su}"

    dong: list[str] = []
    luat_chu = cd.get("luat_chu") or []
    for hd, chu in (("on", "BẬT"), ("off", "TẮT")):
        chu_dat = [x for x in luat_chu if x.get("hanh_dong") == hd]
        if chu_dat:
            dong += [f"{chu} (luật anh đặt «{x.get('ten') or ''}»): khi " + " hoặc ".join(nguon(n) for n in x["khi"])
                     for x in chu_dat]
            continue
        m = mh.get(hd) or {}
        if (m.get("kiem") or {}).get("dat"):
            luat = [x for x in m.get("luat") or [] if x.get("p", 0) >= kh.P_HOI][:3]
            dong += [f"{chu} (bot học, {'tự làm' if kh._duoc_tu_lam(tb, hd) else 'hỏi trước'}): khi "
                     + ", ".join(x["neu"]) for x in luat] or [f"{chu}: luật học không có nhánh đủ chắc"]
        elif hd == "on" and cd.get("hoi_de_hoc") and (mh.get("o_lai") or {}).get("phut") is not None:
            dong.append(f"BẬT: có người ở lại ≥ {mh['o_lai']['phut']} phút (hợp các cảm biến "
                        + ", ".join(cb(x) for x in mh["o_lai"].get("cam_bien") or []) + ") thì HỎI anh để học")
        elif hd == "on":
            dong.append("BẬT: chưa tự bật (luật học chưa đủ tin)")
    tv = cd.get("tat_khi_vang") or {}
    if tv.get("bat"):
        cho = sorted({round(kh.phut_vang(cd, time.time() + h * 3600)) for h in range(24)})
        x = (f"TẮT KHI VẮNG: {' hoặc '.join(cb(m) for m in tv.get('cam_bien') or [])} báo vắng liền "
             f"{cho[0]}–{cho[-1]} phút (bot tự học theo giờ)")
        if tv.get("giu") and tv.get("nhin"):
            x += f"; lúc {cb(tv['giu'])} thì chụp {', '.join(tv['nhin'])} đếm người trước khi tắt"
        if tv.get("roi"):
            x += (f"; vắng mà {cb(tv['roi'])} (người sang khu khác) thì tắt sau 1 phút"
                  + (f", chỉ khi người mới ở ≤ {tv['roi_phut']:g} phút" if tv.get("roi_phut") else ""))
        dong.append(x)
    elif not any(x.get("hanh_dong") == "off" for x in luat_chu):
        dong.append("TẮT: không tự tắt")
    if (cd.get("tat_khi_sang") or {}).get("bat"):
        dong.append(f"TẮT KHI TRỜI SÁNG: phòng trống mà trời ≥ {cd['tat_khi_sang'].get('lux')} lux")
    for x in cd.get("ngoai_le") or []:
        dong.append(f"KHUNG GIỜ «{x.get('ten') or x.get('lich') or ''}»: hướng "
                    f"{'bật' if x['hanh_dong'] == 'on' else 'tắt'} {'luôn hỏi' if x.get('cach') == 'hoi' else 'không làm'}")
    return dong


def do() -> dict[str, Any]:
    """Mọi thứ cho đề: sơ đồ, cảm biến theo phòng, thiết bị và việc đang cài, lời chủ nhà."""
    from services import boi_canh_nha, cam_bien_ghep, ha_client, kich_hoat_nha as kh, so_do_nha

    st = ha_client.get_states() or []
    nen = (ha_client.get_ha_area_index() or {}).get("entity_platform") or {}
    ten = {str(s["entity_id"]): str((s.get("attributes") or {}).get("friendly_name") or s["entity_id"]) for s in st}
    phong: dict[str, list[str]] = {}
    for s in st:
        ma = str(s["entity_id"])
        lop = (s.get("attributes") or {}).get("device_class")
        if not ma.startswith("binary_sensor.") or cam_bien_ghep.la_ghep(ma):
            continue
        if lop in kh._LOP_HIEN_DIEN:
            loai = "camera" if nen.get(ma) == "frigate" else "sóng/chuyển động"
        elif lop in kh._LOP_CUA:
            loai = "cửa"
        else:
            continue
        phong.setdefault(boi_canh_nha.phong_cua(ma) or "chưa xếp khu", []).append(f"{ten.get(ma, ma)} ({loai})")
    so_do = so_do_nha.so()
    ap = so_do.get("ap")
    moi = next((b for b in reversed(so_do["bai"]) if b.get("ket_qua") != "sai"), None)
    s = ap or (moi or {}).get("gia_tri")
    d = kh._nap()
    tbs = {tb: {"ten": ten.get(tb, tb), "khu": boi_canh_nha.phong_cua(tb) or "chưa xếp khu",
                "viec": _viec_dang_cai(tb, cd, d["mo_hinh"].get(tb) or {}, ten)}
           for tb, cd in sorted(d["thiet_bi"].items()) if cd.get("bat")}
    return {"so_do": so_do_nha.doc(s) if s else "", "so_do_chac": bool(ap), "phong": phong, "thiet_bi": tbs,
            "mo_ta": [x["noi_dung"] for x in so_do["mo_ta"]]}


def de(uv: dict[str, Any], da_hoi: list[dict[str, Any]]) -> str:
    dong = [("A. SƠ ĐỒ NHÀ (đã chấm):" if uv["so_do_chac"] else "A. SƠ ĐỒ NHÀ (bot vẽ, CHƯA chấm):"),
            uv["so_do"] or "(chưa có)", "\nB. CẢM BIẾN THEO PHÒNG:"]
    dong += [f"- {p}: {', '.join(ds)}" for p, ds in sorted(uv["phong"].items())] or ["(không có)"]
    dong.append("\nC. THIẾT BỊ và việc ĐANG CÀI (bộ kích hoạt sẽ làm đúng như thế):")
    for tb, x in uv["thiet_bi"].items():
        dong.append(f"- {tb} | {x['ten']} | ở {x['khu']}")
        dong += [f"    {v}" for v in x["viec"]]
    dong += ["\nD. CHỦ NHÀ MÔ TẢ (kể cả bot đọc ảnh camera — dòng «Ảnh …»):"] + ([f"- {x}" for x in uv["mo_ta"]]
                                                                                 or ["(chưa có)"])
    if da_hoi:
        dong += ["\nE. ĐÃ HỎI CHỦ NHÀ (đừng hỏi lại câu đã có trả lời):"]
        dong += [f"- {x['cau']} → {x.get('tra_loi') or '(chưa trả lời)'}" for x in da_hoi[-20:]]
    return "\n".join(dong)


def kiem(data: Any, uv: dict[str, Any]) -> dict[str, Any] | str:
    """Loại bài sai khuôn; đúng/sai về nội dung là việc chủ nhà và giáo viên."""
    if not isinstance(data, dict) or not isinstance(data.get("kich_ban"), list) or not data["kich_ban"]:
        return "phải là JSON có «kich_ban»: [ … ]"
    ra = []
    for x in data["kich_ban"]:
        if not isinstance(x, dict):
            return "mỗi kịch bản là một object"
        if x.get("thiet_bi") not in uv["thiet_bi"]:
            return f"thiết bị không có trong đề: {x.get('thiet_bi')!r}"
        if x.get("nen") not in NEN or x.get("hien_tai") not in HIEN_TAI:
            return f"«nen» phải thuộc {NEN}, «hien_tai» thuộc {HIEN_TAI}"
        if not str(x.get("tinh_huong") or "").strip():
            return "thiếu «tinh_huong»"
        ra.append({"thiet_bi": x["thiet_bi"], "tinh_huong": str(x["tinh_huong"])[:300],
                   "cam_bien_thay": str(x.get("cam_bien_thay") or "")[:300], "nen": x["nen"],
                   "hien_tai": x["hien_tai"], "vi_sao": str(x.get("vi_sao") or "")[:300],
                   "hoi": (str(x["hoi"]).strip()[:300] or None) if x.get("hoi") else None})
    return {"kich_ban": ra, "tom_tat": str(data.get("tom_tat") or "")[:500]}


# ── Dựng, báo, hỏi ──────────────────────────────────────────────────────────
def giai() -> dict[str, Any]:
    """Bot dựng kịch bản. Ghi sổ một lượt + các câu hỏi (chưa gửi)."""
    from services import hieu_thiet_bi_nha as ht
    from services.thoi_quen_nha import _hoi_bot

    uv = do()
    if not uv["thiet_bi"]:
        return {"ok": False, "loi": "chưa có thiết bị nào bot điều khiển"}
    huong, ban = ht.huong_dan("sinh_kich_ban")
    b = _hoi_bot(ht, ht._model(), huong, de(uv, so()["hoi"]))
    k = kiem(b, uv) if not isinstance(b, str) else b
    if isinstance(k, str):
        logger.warning({"event": "kich_ban_loai", "loi": k})
        return {"ok": False, "loi": k}
    with _khoa:
        d = _nap()
        id_ = max((x["id"] for x in d["lan"]), default=0) + 1
        d["lan"] = (d["lan"] + [{"id": id_, "luc": time.time(), "huong_dan": ban, **k}])[-10:]
        da = {x["cau"] for x in d["hoi"]}
        so_hoi = max((x["so"] for x in d["hoi"]), default=0)
        for x in k["kich_ban"]:
            if x["hoi"] and x["hoi"] not in da and sum(1 for h in d["hoi"] if h["lan"] == id_) < HOI_TOI_DA:
                so_hoi += 1
                d["hoi"].append({"so": so_hoi, "lan": id_, "thiet_bi": x["thiet_bi"], "tinh_huong": x["tinh_huong"],
                                 "cau": x["hoi"], "gui_luc": None, "tra_loi": None})
                da.add(x["hoi"])
        _luu(d)
    return {"ok": True, "id": id_, "uv": uv, **k}


def gui_cau_tiep() -> str:
    """Gửi MỘT câu hỏi (chủ máy: "xác minh lần lượt"); trả nội dung đã gửi, "" nếu hết câu."""
    from services import hieu_thiet_bi_nha as ht, kich_hoat_nha

    ten = kich_hoat_nha._ten_ha()
    with _khoa:
        d = _nap()
        c = next((x for x in d["hoi"] if not x.get("tra_loi")), None)
        if c is None:
            return ""
        con = sum(1 for x in d["hoi"] if not x.get("tra_loi")) - 1
        tin = (f"❓ KB{c['so']} ({ten.get(c['thiet_bi'], c['thiet_bi'])} — {c['tinh_huong']})\n{c['cau']}"
               + (f"\n(còn {con} câu nữa, em hỏi lần lượt)" if con > 0 else ""))
        c["gui_luc"] = c.get("gui_luc") or time.time()
        _luu(d)
    ht.bao_nhom(tin)
    return tin


def bao(kq: dict[str, Any]) -> str:
    """Tin tóm tắt ngắn: mỗi thiết bị mấy tình huống đúng / sai / chưa rõ, và những chỗ sai."""
    ten = {tb: x["ten"] for tb, x in kq["uv"]["thiet_bi"].items()}
    dong = [f"🧭 Em đã dựng {len(kq['kich_ban'])} tình huống từ sơ đồ nhà:"]
    for tb in kq["uv"]["thiet_bi"]:
        ds = [x for x in kq["kich_ban"] if x["thiet_bi"] == tb]
        if not ds:
            continue
        dem = {h: sum(1 for x in ds if x["hien_tai"] == h) for h in HIEN_TAI}
        dong.append(f"• {ten[tb]}: ✓{dem['dung']} ✗{dem['sai']} ?{dem['khong_ro']}")
        dong += [f"   ✗ {x['tinh_huong']} → nên {_NEN_DOC[x['nen']]}" for x in ds if x["hien_tai"] == "sai"][:3]
    return "\n".join(dong)


def giai_va_bao() -> dict[str, Any]:
    from services import hieu_thiet_bi_nha as ht

    kq = giai()
    if kq.get("ok"):
        ht.bao_nhom(bao(kq))
        gui_cau_tiep()
    kq.pop("uv", None)
    return kq


def tra_loi(noi_dung: str, so_cau: int | None = None) -> str:
    """Chủ nhà trả lời câu đang hỏi → ghi sổ + thành lời mô tả của sơ đồ nhà (mọi tầng học đọc) → gửi câu kế."""
    from services import so_do_nha

    noi = str(noi_dung or "").strip()
    if not noi:
        return "Anh trả lời giúp em câu đang hỏi ạ."
    with _khoa:
        d = _nap()
        cho = [x for x in d["hoi"] if not x.get("tra_loi")]
        c = (next((x for x in cho if x["so"] == so_cau), None) if so_cau
             else next((x for x in cho if x.get("gui_luc")), None) or (cho[0] if cho else None))
        if c is None:
            return "Em không có câu hỏi tình huống nào đang chờ ạ."
        c.update(tra_loi=noi[:500], tra_luc=time.time())
        _luu(d)
    so_do_nha.them_mo_ta(f"Tình huống «{c['tinh_huong']}» — hỏi: {c['cau']} — chủ nhà: {noi}", nguon="kich_ban")
    if gui_cau_tiep():
        return f"Dạ, em ghi KB{c['so']}."
    # Hết câu hỏi: dựng lại kịch bản với mọi câu trả lời — xem còn chỗ nào sai.
    threading.Thread(target=giai_va_bao, name="kich-ban-nha", daemon=True).start()
    return f"Dạ, em ghi KB{c['so']}. Hết câu hỏi rồi ạ — em dựng lại tình huống theo lời anh, xong em gửi nhóm."


def _reset_for_tests(duong: Path) -> None:
    global _PATH
    _PATH = duong
