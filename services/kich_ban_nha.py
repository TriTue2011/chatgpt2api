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
import re
import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

_PATH = Path(DATA_DIR) / "agent" / "kich_ban_nha.json"
_khoa = threading.RLock()
NEN = ("bat", "tat", "giu", "khong_lam", "hoi", "bao")
HIEN_TAI = ("dung", "sai", "khong_ro")
_NEN_DOC = {"bat": "bật", "tat": "tắt", "giu": "giữ nguyên", "khong_lam": "không làm gì", "hoi": "hỏi anh",
            "bao": "báo anh"}
#: Tối đa câu hỏi mỗi lượt dựng — hỏi dồn thì chủ nhà không trả lời hết (chủ máy 11/09: "xác minh lần lượt").
HOI_TOI_DA = 8
#: Loại nơi — mỗi loại một phần hướng dẫn RIÊNG `sinh_kich_ban_<noi>.md` ghép sau phần chung (chủ máy
#: 30/09/2026: "hướng dẫn theo từng địa điểm, gói gọn promt theo nó ví dụ chung cư").
NOI = ("chung_cu", "nha_pho", "biet_thu", "van_phong", "xuong")
#: Kiểu nhà trong sơ đồ (so_do_nha.KIEU) → loại nơi; "nha_dat" cũ coi như nhà phố.
_KIEU_NOI = {"chung_cu": "chung_cu", "nha_pho": "nha_pho", "nha_dat": "nha_pho", "biet_thu": "biet_thu",
             "van_phong": "van_phong", "xuong": "xuong"}
_MA_RE = re.compile(r"^- `([a-z_]+)` —", re.MULTILINE)


def noi_cua(kieu: Any) -> str:
    """Loại nơi của kiểu nhà; chưa rõ thì ``""`` (chỉ dùng phần chung)."""
    return _KIEU_NOI.get(str(kieu or ""), "")


def huong_dan_cho(noi: str) -> tuple[str, str]:
    """Phần chung + phần riêng của ``noi`` — đúng một nơi, không lẫn chuyện xưởng vào căn hộ."""
    from services import hieu_thiet_bi_nha as ht
    chung, b1 = ht.huong_dan("sinh_kich_ban")
    if noi not in NOI:
        return chung, b1
    rieng, b2 = ht.huong_dan(f"sinh_kich_ban_{noi}")
    return chung + "\n\n---\n\n" + rieng, f"{b1}+{b2}"


def danh_muc(huong: str) -> list[str]:
    """Mã loại tình huống bot PHẢI đi qua cho mỗi thiết bị — đọc thẳng từ hướng dẫn (một nguồn duy nhất)."""
    return list(dict.fromkeys(_MA_RE.findall(huong)))


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
        elif hd == "on" and cd.get("hoi_de_hoc") and kh.phut_o_lai(tb) is not None:
            moc = (f"{cd['o_lai_giay']} giây (anh đặt)" if cd.get("o_lai_giay")
                   else f"{mh['o_lai']['phut']} phút (bot học)")
            dong.append(f"BẬT: có người ở lại ≥ {moc} (hợp các cảm biến "
                        + ", ".join(cb(x) for x in (mh.get("o_lai") or {}).get("cam_bien") or [])
                        + ") thì HỎI anh để học")
        elif hd == "on":
            dong.append("BẬT: chưa tự bật (luật học chưa đủ tin)")
    tv = cd.get("tat_khi_vang") or {}
    if tv.get("bat"):
        if cd.get("roi_giay"):
            cho_tat = f"{cd['roi_giay']} giây (anh đặt)"
        else:
            cho = sorted({round(kh.phut_vang(cd, time.time() + h * 3600)) for h in range(24)})
            cho_tat = f"{cho[0]}–{cho[-1]} phút (bot tự học theo giờ)"
        x = f"TẮT KHI VẮNG: {' hoặc '.join(cb(m) for m in tv.get('cam_bien') or [])} báo vắng liền {cho_tat}"
        if tv.get("giu") and tv.get("nhin"):
            x += f"; lúc {cb(tv['giu'])} thì chụp {', '.join(tv['nhin'])} đếm người trước khi tắt"
        if tv.get("roi") and not cd.get("roi_giay"):
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
    # Ai đang ở nhà: người (person) và máy người cầm (device_tracker) — cần để xét "cả nhà vắng mà có người".
    nguoi = [f"{ten.get(str(x['entity_id']), x['entity_id'])} ({x.get('state')})" for x in st
             if str(x["entity_id"]).split(".")[0] in ("person", "device_tracker")][:12]
    so_do = so_do_nha.so()
    ap = so_do.get("ap")
    moi = next((b for b in reversed(so_do["bai"]) if b.get("ket_qua") != "sai"), None)
    s = ap or (moi or {}).get("gia_tri")
    d = kh._nap()
    tbs = {tb: {"ten": ten.get(tb, tb), "khu": boi_canh_nha.phong_cua(tb) or "chưa xếp khu",
                "viec": _viec_dang_cai(tb, cd, d["mo_hinh"].get(tb) or {}, ten)}
           for tb, cd in sorted(d["thiet_bi"].items()) if cd.get("bat")}
    return {"so_do": so_do_nha.doc(s) if s else "", "so_do_chac": bool(ap), "phong": phong, "nguoi": nguoi,
            "noi": noi_cua((s or {}).get("kieu")), "thiet_bi": tbs, "cham": so().get("cham") or [],
            "mo_ta": [x["noi_dung"] for x in so_do["mo_ta"]]}


def de(uv: dict[str, Any], da_hoi: list[dict[str, Any]], tb: str, ma: list[str]) -> str:
    x = uv["thiet_bi"][tb]
    dong = [f"THIẾT BỊ ĐANG XÉT: {tb} | {x['ten']} | ở {x['khu']}",
            f"DANH MỤC phải đi qua (mỗi mã: tình huống hoặc khong_ap_dung): {', '.join(ma)}", "",
            ("A. SƠ ĐỒ NHÀ (đã chấm):" if uv["so_do_chac"] else "A. SƠ ĐỒ NHÀ (bot vẽ, CHƯA chấm):"),
            uv["so_do"] or "(chưa có)", "\nB. CẢM BIẾN THEO PHÒNG:"]
    dong += [f"- {p}: {', '.join(ds)}" for p, ds in sorted(uv["phong"].items())] or ["(không có)"]
    dong += ["\nB2. AI Ở NHÀ — người và điện thoại/máy người cầm (home = ở nhà, not_home = đi vắng; cả nhà "
             "not_home mà trong nhà có người là bất thường):"]
    dong += [f"- {x}" for x in uv.get("nguoi") or []] or ["(không có — bot không biết lúc nào cả nhà vắng)"]
    dong.append("\nC. THIẾT BỊ và việc ĐANG CÀI (bộ kích hoạt sẽ làm đúng như thế) — ĐANG XÉT thiết bị đánh ►; "
                "thiết bị khác chỉ để biết quanh nó có gì:")
    for m, y in uv["thiet_bi"].items():
        dong.append(f"{'►' if m == tb else '-'} {m} | {y['ten']} | ở {y['khu']}")
        dong += [f"    {v}" for v in y["viec"]] if m == tb else []
    dong += ["\nD. CHỦ NHÀ MÔ TẢ (kể cả bot đọc ảnh camera — dòng «Ảnh …»):"] + ([f"- {x}" for x in uv["mo_ta"]]
                                                                                 or ["(chưa có)"])
    if da_hoi:
        dong += ["\nE. ĐÃ HỎI CHỦ NHÀ (đừng hỏi lại câu đã có trả lời):"]
        dong += [f"- {x['cau']} → {x.get('tra_loi') or '(chưa trả lời)'}" for x in da_hoi[-20:]]
    if uv.get("cham"):
        dong += ["\nF. LỜI CHẤM các lần dựng trước (bài học — đừng lặp lại chỗ bị chấm sai):"]
        dong += [f"- ({'chủ nhà' if c['cham_boi'] == 'chu_may' else 'giáo viên'} chấm "
                 f"{'ĐÚNG' if c['dung'] else 'SAI'}) {c['thiet_bi']} — «{c['tinh_huong']}»: {c['ghi_chu']}"
                 for c in uv["cham"][-15:]]
    return "\n".join(dong)


def cham(lan_id: int, so_thu_tu: int, dung: bool, *, cham_boi: str, ghi_chu: str) -> bool:
    """Chấm MỘT tình huống của một lần dựng (số thứ tự từ 1 như trong sổ). Lời chấm vào đề lần sau (mục F)."""
    if cham_boi not in ("chu_may", "claude"):
        raise ValueError("cham_boi là chu_may hoặc claude")
    with _khoa:
        d = _nap()
        lan = next((x for x in d["lan"] if x["id"] == int(lan_id)), None)
        if lan is None or not 1 <= int(so_thu_tu) <= len(lan["kich_ban"]):
            return False
        x = lan["kich_ban"][int(so_thu_tu) - 1]
        d.setdefault("cham", []).append({"luc": time.time(), "lan": int(lan_id), "stt": int(so_thu_tu),
                                         "thiet_bi": x["thiet_bi"], "tinh_huong": x["tinh_huong"],
                                         "dung": bool(dung), "cham_boi": cham_boi,
                                         "ghi_chu": str(ghi_chu or "")[:400]})
        d["cham"] = d["cham"][-50:]
        _luu(d)
    return True


def kiem(data: Any, tb: str, ma: list[str]) -> dict[str, Any] | str:
    """Loại bài sai khuôn (mã ngoài danh mục, giá trị lạ); đúng/sai về nội dung là việc người chấm."""
    if not isinstance(data, dict) or not isinstance(data.get("kich_ban"), list):
        return "phải là JSON có «kich_ban»: [ … ]"
    ra, kad = [], []
    for x in data["kich_ban"]:
        if not isinstance(x, dict):
            return "mỗi kịch bản là một object"
        if x.get("loai") not in ma:
            return f"«loai» phải là mã trong danh mục: {x.get('loai')!r}"
        if "khong_ap_dung" in (x.get("nen"), x.get("hien_tai")):
            # Bot nói mã này KHÔNG ÁP DỤNG nhưng đặt nhầm vào danh sách tình huống — ý đúng, sai chỗ: chuyển sang
            # «khong_ap_dung». Đo 30/09/2026 (ChatGPT miễn phí): 4/8 lượt bị loại cả bài chỉ vì chỗ này.
            kad.append({"thiet_bi": tb, "loai": x["loai"],
                        "vi_sao": str(x.get("vi_sao") or x.get("tinh_huong") or "")[:200]})
            continue
        if x.get("nen") not in NEN or x.get("hien_tai") not in HIEN_TAI:
            return f"«nen» phải thuộc {NEN}, «hien_tai» thuộc {HIEN_TAI}"
        if not str(x.get("tinh_huong") or "").strip():
            return "thiếu «tinh_huong»"
        ra.append({"thiet_bi": tb, "loai": x["loai"], "tinh_huong": str(x["tinh_huong"])[:300],
                   "cam_bien_thay": str(x.get("cam_bien_thay") or "")[:300], "nen": x["nen"],
                   "hien_tai": x["hien_tai"], "vi_sao": str(x.get("vi_sao") or "")[:300],
                   "hoi": (str(x["hoi"]).strip()[:300] or None) if x.get("hoi") else None})
    for x in data.get("khong_ap_dung") or []:
        if isinstance(x, dict) and x.get("loai") in ma:
            kad.append({"thiet_bi": tb, "loai": x["loai"], "vi_sao": str(x.get("vi_sao") or "")[:200]})
    return {"kich_ban": ra, "khong_ap_dung": kad, "tom_tat": str(data.get("tom_tat") or "")[:300]}


def thieu(k: dict[str, Any], ma: list[str]) -> list[str]:
    """Mã danh mục chưa có tình huống lẫn lời «không áp dụng» — bot bỏ sót."""
    co = {x["loai"] for x in k["kich_ban"]} | {x["loai"] for x in k["khong_ap_dung"]}
    return [m for m in ma if m not in co]


def giai_mot(uv: dict[str, Any], tb: str, huong: str, model: str, da_hoi: list[dict[str, Any]]) -> dict[str, Any] | str:
    """Bot dựng tình huống cho MỘT thiết bị. Thiếu mã nào của danh mục thì hỏi lại ĐÚNG những mã đó một lần
    (chủ máy 30/09/2026: "tránh bỏ sót, tránh nhầm, thiếu tình huống với chỉ 1 thiết bị")."""
    from services import hieu_thiet_bi_nha as ht
    from services.thoi_quen_nha import _hoi_bot

    ma = danh_muc(huong)
    dde = de(uv, da_hoi, tb, ma)
    b = _hoi_bot(ht, model, huong, dde)
    k = kiem(b, tb, ma) if not isinstance(b, str) else b
    if isinstance(k, str) and not isinstance(b, str):
        # Trả JSON mà SAI KHUÔN (thiếu `loai`, `nen` lạ…): một tình huống sai là cả bài bị loại. Hỏi lại MỘT lần
        # kèm đúng lỗi — cùng cách với lượt bổ sung mã bỏ sót. Đo 30/09/2026 lúc Codex hết lượt, combo rơi về
        # ChatGPT miễn phí: 5/18 bài đề chung cư + văn phòng bị loại chỉ vì một tình huống thiếu `loai`.
        b = _hoi_bot(ht, model, huong, dde + "\n\nBÀI EM VỪA LÀM:\n" + json.dumps(b, ensure_ascii=False)
                     + f"\n\nBÀI BỊ LOẠI VÌ SAI KHUÔN: {k}\nTrả lại JSON ĐÚNG khuôn ở phần «Trả lời»: giữ nội dung, "
                     "mỗi tình huống đủ `loai` (mã trong danh mục), `nen`, `hien_tai` đúng các giá trị cho phép.")
        k = kiem(b, tb, ma) if not isinstance(b, str) else b
    if isinstance(k, str):
        return k
    con = thieu(k, ma)
    if con:
        bo_sung = (dde + "\n\nBÀI EM VỪA LÀM:\n" + json.dumps(b, ensure_ascii=False)
                   + f"\n\nEM ĐÃ BỎ SÓT các mã: {', '.join(con)}. Trả lại JSON ĐẦY ĐỦ: giữ mọi tình huống đã có, "
                   "thêm tình huống (hoặc khong_ap_dung kèm vì sao) cho TỪNG mã còn thiếu.")
        b2 = _hoi_bot(ht, model, huong, bo_sung)
        k2 = kiem(b2, tb, ma) if not isinstance(b2, str) else b2
        if isinstance(k2, dict) and len(thieu(k2, ma)) < len(con):
            k = k2
    k["thieu"] = thieu(k, ma)
    return k


# ── Dựng, báo, hỏi ──────────────────────────────────────────────────────────
def giai() -> dict[str, Any]:
    """Bot dựng kịch bản cho TỪNG thiết bị (mỗi thiết bị một lượt gọi). Ghi sổ một lượt + câu hỏi (chưa gửi)."""
    from services import hieu_thiet_bi_nha as ht

    uv = do()
    if not uv["thiet_bi"]:
        return {"ok": False, "loi": "chưa có thiết bị nào bot điều khiển"}
    huong, ban = huong_dan_cho(uv["noi"])
    model = ht._model()
    kq: dict[str, Any] = {"kich_ban": [], "khong_ap_dung": [], "thieu": {}, "loi": {}, "tom_tat": []}
    for tb in uv["thiet_bi"]:
        k = giai_mot(uv, tb, huong, model, so()["hoi"])
        if isinstance(k, str):
            kq["loi"][tb] = k
            logger.warning({"event": "kich_ban_loai", "thiet_bi": tb, "loi": k})
            continue
        kq["kich_ban"] += k["kich_ban"]
        kq["khong_ap_dung"] += k["khong_ap_dung"]
        if k["thieu"]:
            kq["thieu"][tb] = k["thieu"]
        if k["tom_tat"]:
            kq["tom_tat"].append(f"{uv['thiet_bi'][tb]['ten']}: {k['tom_tat']}")
    if not kq["kich_ban"]:
        return {"ok": False, "loi": "; ".join(f"{t}: {l}" for t, l in kq["loi"].items())[:300]}
    kq["tom_tat"] = " ".join(kq["tom_tat"])[:1500]
    with _khoa:
        d = _nap()
        id_ = max((x["id"] for x in d["lan"]), default=0) + 1
        d["lan"] = (d["lan"] + [{"id": id_, "luc": time.time(), "huong_dan": ban, "noi": uv["noi"], **kq}])[-10:]
        da = {x["cau"] for x in d["hoi"]}
        so_hoi = max((x["so"] for x in d["hoi"]), default=0)
        for x in kq["kich_ban"]:
            if x["hoi"] and x["hoi"] not in da and sum(1 for h in d["hoi"] if h["lan"] == id_) < HOI_TOI_DA:
                so_hoi += 1
                d["hoi"].append({"so": so_hoi, "lan": id_, "thiet_bi": x["thiet_bi"], "tinh_huong": x["tinh_huong"],
                                 "cau": x["hoi"], "gui_luc": None, "tra_loi": None})
                da.add(x["hoi"])
        _luu(d)
    return {"ok": True, "id": id_, "uv": uv, **kq}


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
    dong = [f"🧭 TH{kq['id']} — em đã dựng {len(kq['kich_ban'])} tình huống từ sơ đồ nhà:"]
    for tb in kq["uv"]["thiet_bi"]:
        ds = [(i + 1, x) for i, x in enumerate(kq["kich_ban"]) if x["thiet_bi"] == tb]
        if not ds:
            continue
        dem = {h: sum(1 for _, x in ds if x["hien_tai"] == h) for h in HIEN_TAI}
        dong.append(f"• {ten[tb]}: ✓{dem['dung']} ✗{dem['sai']} ?{dem['khong_ro']}")
        dong += [f"   ✗ [{i}] {x['tinh_huong']} → nên {_NEN_DOC[x['nen']]}" for i, x in ds if x["hien_tai"] == "sai"][:3]
    if kq.get("thieu"):
        dong.append("Còn bỏ sót: " + "; ".join(f"{ten.get(t, t)} ({', '.join(m)})" for t, m in kq["thieu"].items()))
    dong.append("Em nhận định sai chỗ nào anh nói, vd «tình huống 3 sai, quạt đó ...» — em ghi làm bài học.")
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
