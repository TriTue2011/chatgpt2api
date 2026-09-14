"""Mở nhạc ra loa/tivi Home Assistant qua kênh chat (Zalo, Telegram).

Chủ máy 14/09/2026: "Khi mở nhạc cần hiện list danh sách 10 bài nhạc để lựa chọn,
sau đó là list loa phát, phát 1 hoặc nhiều loa hoặc tất cả".

Ba bước, mỗi bước là một menu `<<<ASK>>>` do CODE dựng:
  1. từ khoá → 10 bài, mỗi bài một nút
  2. bài đã chọn → danh sách loa + «Tất cả loa» (gõ tay được nhiều loa)
  3. bài + loa → phát qua `phat_ha.phat`, cùng phiên/hàng đợi với tab YouTube

Nội dung nút mang đủ bài và loa, nên `orchestrator` đọc lại bằng `doc_nut` mà
không cần giữ trạng thái tạm nào trên máy chủ, và bấm lại sau khởi động lại vẫn
chạy. Tên loa gõ tay khớp cùng luật với công cụ Assist của tích hợp HA
(`assist_tools.match_speakers` trong repo TriTue2011/youtube).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import dich_vu, phat_ha
from .search import youtube_url_query
from .thong_bao import cau_loi

SO_BAI = 10
NGUON = ("youtube", "zing")
LENH_DIEU_KHIEN = ("tam_dung", "tiep_tuc", "bai_ke", "bai_truoc", "dung")

_TAT_CA = {"tat ca", "tat ca loa", "moi loa", "all", "ca nha", "toan bo"}
_TACH = re.compile(r"\s*(?:,|;|\+|&|\bva\b|\band\b)\s*")

NUT_CHON_LOA = re.compile(
    r"^\s*mở\s+nhạc\s+(?P<nguon>youtube|zing)\s+«(?P<bai>[^«»]+)»\s+chọn\s+loa\s*$", re.I)
NUT_PHAT = re.compile(
    r"^\s*phát\s+nhạc\s+(?P<nguon>youtube|zing)\s+«(?P<bai>[^«»]+)»\s+ra\s+loa\s+«(?P<loa>[^«»]+)»\s*$", re.I)


def doc_nut(text: Any) -> dict[str, str] | None:
    """args cho `mo_nhac` nếu câu là nội dung nút do menu nhạc sinh ra."""
    t = str(text or "")
    m = NUT_PHAT.match(t) or NUT_CHON_LOA.match(t)
    if not m:
        return None
    return {k: v.strip() for k, v in m.groupdict().items() if v}


def bo_dau(text: Any) -> str:
    text = unicodedata.normalize("NFD", str(text or "")).replace("đ", "d").replace("Đ", "D")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text).strip().lower()


def khop_loa(cau: Any, loa: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """(entity_id khớp, phần không nhận ra). `loa` = danh sách theo thứ tự đã hiện."""
    text = bo_dau(cau)
    if not text or text in _TAT_CA:
        return [d["entity_id"] for d in loa], []
    chon: list[str] = []
    thieu: list[str] = []
    for phan in [p for p in _TACH.split(text) if p]:
        # "loa 2", "tivi LG": thử cả câu nguyên (tên có thể bắt đầu bằng "Tivi") rồi
        # mới bỏ chữ loại thiết bị ở đầu.
        gon = re.sub(r"^(loa|tivi|ti vi|man hinh)\s+", "", phan).strip()
        thay = None
        for thu in dict.fromkeys(x for x in (phan, gon) if x):
            if thu.isdigit() and 1 <= int(thu) <= len(loa):
                thay = loa[int(thu) - 1]["entity_id"]
            else:
                thay = next((d["entity_id"] for d in loa
                             if thu in {d["entity_id"], bo_dau(d["ten"])}
                             or (len(thu) >= 3 and thu in bo_dau(d["ten"]))), None)
            if thay:
                break
        if thay is None:
            thieu.append(phan)
        elif thay not in chon:
            chon.append(thay)
    return chon, thieu


def thoi_gian(giay: Any) -> str:
    try:
        so = int(float(giay))
    except (TypeError, ValueError):
        return ""
    if so <= 0:
        return ""
    gio, con = divmod(so, 3600)
    phut, s = divmod(con, 60)
    return f"{gio}:{phut:02d}:{s:02d}" if gio else f"{phut}:{s:02d}"


def loa_phat_duoc(cho_phep: set[str] | None) -> list[dict[str, Any]]:
    """Loa/tivi HA đang trực tuyến, nhận phát nhạc, không bị ẩn ở tab YouTube.
    `cho_phep` = entity_id khung chat này được dùng; None = mọi loa."""
    return [d for d in phat_ha.danh_sach()
            if not d["an"] and d["phat_duoc"] and d["trang_thai"] != "unavailable"
            and (cho_phep is None or d["entity_id"] in cho_phep)]


def _nhan(text: str, dai: int) -> str:
    text = re.sub(r"\s+", " ", text.replace("|", "/").replace("«", "\"").replace("»", "\"")).strip()
    return text if len(text) <= dai else text[: dai - 1] + "…"


def _menu_bai(ket_qua: list[dict[str, Any]], nguon: str, tu_khoa: str, loa: str) -> dict[str, Any]:
    dong = [f"🎵 {len(ket_qua)} bài cho «{_nhan(tu_khoa, 60)}» — chọn bài ạ:", "<<<ASK>>>"]
    for bai in ket_qua:
        ma = str(bai.get("url") or bai.get("id"))
        phu = " · ".join(x for x in (_nhan(str(bai.get("channel") or bai.get("artist") or ""), 20),
                                     thoi_gian(bai.get("duration"))) if x)
        nhan = _nhan(str(bai.get("title") or ma), 70) + (f" ({phu})" if phu else "")
        gui = (f"phát nhạc {nguon} «{ma}» ra loa «{loa}»" if loa
               else f"mở nhạc {nguon} «{ma}» chọn loa")
        dong.append(f"{nhan} | {gui}")
    dong.append("<<<END>>>")
    return {"text": "\n".join(dong), "deliver_now": True}


def _menu_loa(nguon: str, bai: str, loa: list[dict[str, Any]], dau: str = "") -> dict[str, Any]:
    dong = [dau + "🔊 Phát ra loa nào ạ? Muốn nhiều loa thì gõ: "
            f"phát nhạc {nguon} «{bai}» ra loa «tên 1, tên 2»", "<<<ASK>>>"]
    for d in loa:
        trang_thai = " · đang phát" if d["trang_thai"] == "playing" else ""
        dong.append(f"{_nhan(d['ten'], 60)}{trang_thai} | phát nhạc {nguon} «{bai}» ra loa «{d['ten']}»")
    if len(loa) > 1:
        dong.append(f"Tất cả loa | phát nhạc {nguon} «{bai}» ra loa «tất cả»")
    dong.append("<<<END>>>")
    return {"text": "\n".join(dong), "deliver_now": True}


def mo_nhac(args: dict[str, Any], cho_phep: set[str] | None) -> dict[str, Any]:
    """Hợp đồng: args {tu_khoa | bai, nguon?, loa?} → {"text", "deliver_now"?}.

    Thiếu bài → menu 10 bài; có bài, thiếu loa (hoặc loa không nhận ra) → menu
    loa; đủ → phát. Lỗi tìm/phát trả câu tiếng Việt, không ném."""
    nguon = str(args.get("nguon") or "youtube").strip().lower()
    if nguon not in NGUON:
        nguon = "youtube"
    bai = str(args.get("bai") or "").strip()
    tu_khoa = str(args.get("tu_khoa") or "").strip()
    loa_hoi = str(args.get("loa") or "").strip()
    if not bai and nguon == "youtube" and youtube_url_query(tu_khoa):
        if youtube_url_query(tu_khoa)[0] == "video":
            bai = tu_khoa                         # dán link một video: khỏi tìm
    loa = loa_phat_duoc(cho_phep)
    if not loa:
        return {"text": "Không có loa/tivi Home Assistant nào đang trực tuyến để phát nhạc ạ."}

    if not bai:
        if not tu_khoa:
            return {"text": "Anh/chị muốn nghe bài gì ạ? Gõ tên bài, ca sĩ hoặc dán link YouTube."}
        try:
            ket_qua = dich_vu.core().search(nguon, tu_khoa, SO_BAI)[:SO_BAI]
        except ValueError as loi:
            return {"text": cau_loi(str(loi))}
        except Exception:                          # tìm kiếm là dịch vụ ngoài
            return {"text": cau_loi("search_unavailable")}
        if not ket_qua:
            return {"text": f"Không tìm thấy bài nào cho «{tu_khoa}» ạ."}
        # Loa đã nêu và nhận ra đủ thì nút bài phát luôn, khỏi hỏi loa lần nữa.
        chon, thieu = khop_loa(loa_hoi, loa) if loa_hoi else ([], [])
        return _menu_bai(ket_qua, nguon, tu_khoa, loa_hoi if chon and not thieu else "")

    if not loa_hoi:
        return _menu_loa(nguon, bai, loa)
    chon, thieu = khop_loa(loa_hoi, loa)
    if thieu or not chon:
        return _menu_loa(nguon, bai, loa, dau=f"Em không nhận ra loa trong «{loa_hoi}» ạ. ")
    try:
        kq = phat_ha.phat(nguon, bai, chon, phat_ha.url_goc_nen() or "")
    except ValueError as loi:
        return {"text": f"Em phát không được ạ: {cau_loi(str(loi))}"}
    ten = {d["entity_id"]: d["ten"] for d in loa}
    item = (kq.get("phien") or {}).get("item") or {}
    cau = f"[đang phát «{item.get('title') or bai}» trên {', '.join(ten[e] for e in chon if e in kq['da_gui'])}]"
    if kq["bo_qua"]:
        cau += " [bỏ qua: " + ", ".join(
            f"{ten.get(b['entity_id'], b['entity_id'])} — {cau_loi(b['ly_do'])}" for b in kq["bo_qua"]) + "]"
    return {"text": cau}


def _phien_cua(cho_phep: set[str] | None) -> list[dict[str, Any]]:
    return [p for p in phat_ha.cac_phien()
            if cho_phep is None or any(e in cho_phep for e in p["output_entity_ids"])]


def dang_phat(cho_phep: set[str] | None) -> dict[str, Any]:
    """Mỗi nhóm loa đang phát bài gì, tới đâu."""
    phien = _phien_cua(cho_phep)
    if not phien:
        return {"text": "[không loa nào đang phát nhạc]"}
    theo_ma = {d["entity_id"]: d for d in phat_ha.danh_sach()}
    dong = []
    for p in phien:
        loa = [theo_ma[e] for e in p["output_entity_ids"] if e in theo_ma]
        dan = next((d for d in loa if d["vi_tri"] is not None), None)
        item = p.get("item") or {}
        tien_do = ""
        if dan:
            tien_do = " · " + "/".join(x for x in (thoi_gian(dan["vi_tri"]) or "0:00",
                                                   thoi_gian(dan["thoi_luong"] or item.get("duration"))) if x)
        trang_thai = {"playing": "đang phát", "paused": "tạm dừng"}.get(loa[0]["trang_thai"] if loa else "", "")
        hang = p.get("queue") or {}
        vi_tri_hang = (f" · bài {int(hang['index']) + 1}/{len(hang['items'])}"
                       if len(hang.get("items") or []) > 1 and int(hang.get("index", -1)) >= 0 else "")
        dong.append(f"🔊 {', '.join(d['ten'] for d in loa) or ', '.join(p['output_entity_ids'])}: "
                    f"«{item.get('title') or item.get('id') or '?'}»"
                    f"{' · ' + trang_thai if trang_thai else ''}{tien_do}{vi_tri_hang}")
    return {"text": "\n".join(dong)}


def dieu_khien(args: dict[str, Any], cho_phep: set[str] | None) -> dict[str, Any]:
    """Hợp đồng: args {lenh ∈ LENH_DIEU_KHIEN, loa?}. Không nêu loa: một nhóm đang
    phát thì lệnh cho nhóm đó; nhiều nhóm thì tạm dừng/tiếp/dừng áp cho tất cả,
    còn chuyển bài phải hỏi lại nhóm nào."""
    lenh = str(args.get("lenh") or "").strip()
    if lenh not in LENH_DIEU_KHIEN:
        return {"text": cau_loi("lenh_khong_ho_tro")}
    phien = _phien_cua(cho_phep)
    if not phien:
        return {"text": "[không loa nào đang phát nhạc]"}
    theo_ma = {d["entity_id"]: d for d in phat_ha.danh_sach()}
    loa_hoi = str(args.get("loa") or "").strip()
    if loa_hoi:
        dang_co = [theo_ma[e] for p in phien for e in p["output_entity_ids"]
                   if e in theo_ma and (cho_phep is None or e in cho_phep)]
        chon, thieu = khop_loa(loa_hoi, dang_co)
        if thieu or not chon:
            return {"text": f"Không loa nào trong «{loa_hoi}» đang phát nhạc ạ.\n" + dang_phat(cho_phep)["text"]}
        phien = [p for p in phien if any(e in chon for e in p["output_entity_ids"])]
    else:
        chon = [e for p in phien for e in p["output_entity_ids"] if cho_phep is None or e in cho_phep]
    ten = ", ".join(theo_ma[e]["ten"] if e in theo_ma else e for e in chon)
    try:
        if lenh in {"bai_ke", "bai_truoc"}:
            if len(phien) > 1:
                return {"text": "Đang có nhiều nhóm loa phát nhạc — chuyển bài cho loa nào ạ?\n"
                                + dang_phat(cho_phep)["text"]}
            kq = phat_ha.chuyen_bai(phien[0]["session_id"], 1 if lenh == "bai_ke" else -1)
            item = (kq.get("phien") or {}).get("item") or {}
            return {"text": f"[đã chuyển sang «{item.get('title') or item.get('id')}» trên {ten}]"}
        if lenh == "dung":
            if loa_hoi:
                phat_ha.bo_loa(chon)
            else:
                for p in phien:
                    phat_ha.dung_phien(p["session_id"])
            return {"text": f"[đã dừng nhạc trên {ten}]"}
        nhan = [e for e in chon if theo_ma.get(e, {}).get("tam_dung")]
        if not nhan:
            return {"text": f"{ten} không nhận lệnh tạm dừng/phát tiếp ạ."}
        da_gui = phat_ha.dieu_khien(lenh, nhan)
    except ValueError as loi:
        return {"text": f"Em làm không được ạ: {cau_loi(str(loi))}"}
    if not da_gui:
        return {"text": cau_loi("ha_tu_choi")}
    viec = "tạm dừng" if lenh == "tam_dung" else "phát tiếp"
    return {"text": f"[đã {viec} trên {', '.join(theo_ma[e]['ten'] for e in da_gui)}]"}
