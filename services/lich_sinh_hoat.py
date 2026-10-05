"""Lịch sinh hoạt của cả nhà — chủ máy khai, bot dùng chung cho MỌI thiết bị.

Chủ máy 26/09/2026: "Giờ dậy buổi sáng, giờ nghỉ trưa, giờ ngủ buổi tối, giờ đi làm …
chưa kể chia theo thứ. Ví dụ thứ 7 vợ hay nghỉ, tôi nghỉ chủ nhật" — và "không phải áp
dụng riêng mà là cơ chế chung cho toàn bộ thiết bị".

Mỗi mục: ``{"ma", "ten", "loai", "tu", "den", "thu"}`` — ``thu`` là các ngày trong tuần
(0 = thứ 2 … 6 = chủ nhật). Mục qua nửa đêm (21:45–06:00) THUỘC NGÀY BẮT ĐẦU: "Ngủ, thứ 6"
vẫn đang diễn ra lúc 02:00 sáng thứ 7.

Ai dùng:

* `kich_hoat_nha` — khung giờ ngoại lệ của một thiết bị có thể ĐI THEO một mục lịch
  (``{"lich": "ngu"}``) thay cho giờ cố định; mỗi mục lịch cũng là một đặc trưng cho cây
  học ("đang giờ Ăn tối"), để bot phân biệt được thứ 2 ăn muộn với thứ 3 ăn sớm.

Lịch là lời KHAI của chủ máy, không phải dữ liệu đo — đúng "thường thường", có hôm lệch.
Nên lịch không tự bật/tắt gì; nó chỉ đổi cách bot cân nhắc.

THEO TỪNG NGƯỜI (chủ máy 30/09/2026: "viết lại code chia theo từng người trong gia đình, có thể tự thêm,
căn cứ vào độ tuổi để có list thời gian phù hợp, có thể tự thêm tay"): sổ có thêm ``thanh_vien`` —
``{"ma", "ten", "nam_sinh", "theo_doi", "vai", "mat", "chat"}`` (``theo_doi``: mã person./device_tracker. của người
đó; ``vai``: `VAI`; ``mat``: mã khuôn mặt trong sổ mặt; ``chat``: tài khoản «kênh:mã» — 05/10/2026). Mục lịch
có thêm ``ai`` (mã thành viên); rỗng = CẢ NHÀ, nên lịch cũ giữ nguyên nghĩa. Nhóm tuổi tính từ năm sinh
(không lưu tuổi — sang năm vẫn đúng); ``goi_y(nhom)`` là khung giờ THƯỜNG GẶP của nhóm tuổi đó để chủ
nhà bấm thêm rồi sửa — không tự áp.

«Cả nhà ngủ / vắng» (``ca_nha``) = mục CẢ NHÀ loại đó đang diễn ra, HOẶC mọi thành viên đều đang ở một mục
loại đó. Một người đi làm không phải cả nhà vắng.
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.config import DATA_DIR

_TZ = timezone(timedelta(hours=7))
_PATH = Path(DATA_DIR) / "agent" / "lich_sinh_hoat.json"

#: Loại mục — tập đóng để bot biết mục ấy NGHĨA là gì mà không phải khớp chữ trong tên:
#: "ngu" (cả nhà ngủ), "vang" (thường không ai ở nhà), "an" (bữa ăn), "khac".
LOAI = ("ngu", "vang", "an", "khac")
TOI_DA = 40
_GIO = re.compile(r"([01]\d|2[0-3]):[0-5]\d")

TV_TOI_DA = 12
_MA = re.compile(r"[a-z0-9_]{1,24}")
#: Vai của từng người (chủ máy 05/10/2026: "Bot đã biết ai là chủ nhà, vợ chủ nhà, con chủ nhà, ai là khách chưa").
#: «khach_quen» KHÔNG tính vào cả nhà (`ca_nha`). Khuôn mặt đã đặt tên mà không gắn với ai ở đây cũng là khách quen.
VAI = {"chu_nha": "chủ nhà", "vo_chong": "vợ/chồng chủ nhà", "con": "con", "nguoi_than": "người thân",
       "giup_viec": "giúp việc", "khach_quen": "khách quen"}
#: Tài khoản chat của một người: «kênh:mã người dùng» (cùng mã orchestrator thấy ở khoá phiên).
_CHAT = re.compile(r"(zalop|zalo|tg):[A-Za-z0-9_\-]{1,64}")
_MAT = re.compile(r"[0-9a-f]{6,40}")

#: Nhóm tuổi: (mã, tên, tuổi từ, tuổi tới — không gồm).
NHOM = (("tre_nho", "Trẻ nhỏ (dưới 6 tuổi)", 0, 6), ("tieu_hoc", "Học sinh tiểu học (6–10)", 6, 11),
        ("trung_hoc", "Học sinh THCS, THPT (11–17)", 11, 18), ("nguoi_lon", "Người lớn (18–59)", 18, 60),
        ("nguoi_gia", "Người cao tuổi (60+)", 60, 200))
_T2_T6, _MOI_NGAY = [0, 1, 2, 3, 4], [0, 1, 2, 3, 4, 5, 6]
#: Khung giờ thường gặp ở Việt Nam theo nhóm tuổi — GỢI Ý để bấm thêm, mỗi nhà một khác nên luôn sửa được.
_GOI_Y: dict[str, list[tuple[str, str, str, str, list[int]]]] = {
    "tre_nho": [("Ngủ trưa", "ngu", "12:00", "14:30", _MOI_NGAY), ("Ngủ tối", "ngu", "20:30", "06:30", _MOI_NGAY),
                ("Đi nhà trẻ", "vang", "07:30", "16:30", _T2_T6)],
    "tieu_hoc": [("Đi học", "vang", "07:00", "16:30", _T2_T6), ("Học bài tối", "khac", "19:30", "21:00", _T2_T6),
                 ("Ngủ", "ngu", "21:30", "06:15", _MOI_NGAY)],
    "trung_hoc": [("Đi học", "vang", "06:45", "17:00", _T2_T6), ("Học bài tối", "khac", "19:30", "22:00", _T2_T6),
                  ("Ngủ", "ngu", "22:30", "06:00", _MOI_NGAY)],
    "nguoi_lon": [("Đi làm", "vang", "07:30", "17:30", _T2_T6), ("Ngủ", "ngu", "23:00", "06:00", _MOI_NGAY)],
    "nguoi_gia": [("Tập thể dục sáng", "khac", "05:00", "06:00", _MOI_NGAY),
                  ("Ngủ trưa", "ngu", "12:00", "13:30", _MOI_NGAY), ("Ngủ", "ngu", "21:00", "05:00", _MOI_NGAY)],
}

_khoa = threading.RLock()
_du_lieu: list[dict[str, Any]] | None = None
_tv: list[dict[str, Any]] | None = None


def _nap() -> None:
    global _du_lieu, _tv
    if _du_lieu is None:
        try:
            d = json.loads(_PATH.read_text(encoding="utf-8")) if _PATH.is_file() else {}
            _du_lieu, _tv = list(d.get("muc") or []), list(d.get("thanh_vien") or [])
        except (OSError, ValueError, AttributeError):
            _du_lieu, _tv = [], []
        for x in _du_lieu:
            x.setdefault("ai", [])


def ds() -> list[dict[str, Any]]:
    with _khoa:
        _nap()
        return [dict(x) for x in _du_lieu or []]


def thanh_vien() -> list[dict[str, Any]]:
    """Thành viên kèm ``tuoi`` và ``nhom`` tính theo năm hiện tại (không có năm sinh → None)."""
    with _khoa:
        _nap()
        nam = datetime.now(_TZ).year
        return [{**x, "tuoi": (nam - x["nam_sinh"]) if x.get("nam_sinh") else None,
                 "nhom": nhom_tuoi(x.get("nam_sinh"), nam)} for x in _tv or []]


def nhom_tuoi(nam_sinh: Any, nam: int | None = None) -> str | None:
    if not nam_sinh:
        return None
    tuoi = (nam or datetime.now(_TZ).year) - int(nam_sinh)
    return next((m for m, _t, a, b in NHOM if a <= tuoi < b), None)


def goi_y(nhom: str) -> list[dict[str, Any]]:
    """Khung giờ thường gặp của một nhóm tuổi (chưa có ``ma``/``ai``) — để chủ nhà bấm thêm rồi sửa."""
    return [{"ten": t, "loai": l, "tu": a, "den": b, "thu": list(th)} for t, l, a, b, th in _GOI_Y.get(nhom, [])]


def _ma_tu_ten(ten: str, da_co: set[str]) -> str:
    """Mã BỀN cho mục mới: khung giờ của thiết bị trỏ tới mục bằng mã này, nên không được
    sinh theo vị trí (xoá một mục phía trên là mọi mục sau đổi mã, khung trỏ nhầm)."""
    goc = "".join(c for c in unicodedata.normalize("NFD", ten.lower().replace("đ", "d"))
                  if unicodedata.category(c) != "Mn")
    goc = re.sub(r"[^a-z0-9]+", "_", goc).strip("_")[:20] or "muc"
    ma, i = goc, 2
    while ma in da_co:
        ma, i = f"{goc}_{i}", i + 1
    return ma


def _chuan(x: Any) -> dict[str, Any]:
    if not isinstance(x, dict):
        raise ValueError("Mỗi mục lịch phải là {ten, loai, tu, den, thu}.")
    ten = str(x.get("ten") or "").strip()
    if not ten or len(ten) > 40:
        raise ValueError("Tên mục lịch phải có, tối đa 40 chữ.")
    if x.get("loai", "khac") not in LOAI:
        raise ValueError(f"Loại mục lịch phải là một trong {', '.join(LOAI)}.")
    if not all(_GIO.fullmatch(str(x.get(k) or "")) for k in ("tu", "den")) or x["tu"] == x["den"]:
        raise ValueError(f"«{ten}»: giờ phải dạng HH:MM và từ ≠ đến.")
    thu = sorted({int(t) for t in x.get("thu") or []})
    if not thu or any(not 0 <= t <= 6 for t in thu):
        raise ValueError(f"«{ten}»: chọn ít nhất một ngày (0 = thứ 2 … 6 = chủ nhật).")
    ma = str(x.get("ma") or "").strip()
    if ma and not _MA.fullmatch(ma):
        raise ValueError(f"«{ten}»: mã chỉ gồm chữ thường không dấu, số, gạch dưới.")
    ai = list(dict.fromkeys(str(a) for a in x.get("ai") or []))
    return {"ma": ma, "ten": ten, "loai": str(x.get("loai") or "khac"), "tu": x["tu"], "den": x["den"], "thu": thu,
            "ai": ai}


def _chuan_tv(x: Any) -> dict[str, Any]:
    if not isinstance(x, dict):
        raise ValueError("Mỗi thành viên phải là {ten, nam_sinh?, theo_doi?}.")
    ten = str(x.get("ten") or "").strip()
    if not ten or len(ten) > 30:
        raise ValueError("Tên thành viên phải có, tối đa 30 chữ.")
    nam = x.get("nam_sinh")
    nam_nay = datetime.now(_TZ).year
    if nam in ("", None):
        nam = None
    else:
        try:
            nam = int(nam)
        except (TypeError, ValueError):
            raise ValueError(f"«{ten}»: năm sinh phải là số.") from None
        if not nam_nay - 120 <= nam <= nam_nay:
            raise ValueError(f"«{ten}»: năm sinh {nam} không hợp lý.")
    theo_doi = [str(t) for t in x.get("theo_doi") or []
                if re.fullmatch(r"(person|device_tracker)\.[a-z0-9_]+", str(t))]
    ma = str(x.get("ma") or "").strip()
    if ma and not _MA.fullmatch(ma):
        raise ValueError(f"«{ten}»: mã chỉ gồm chữ thường không dấu, số, gạch dưới.")
    vai = str(x.get("vai") or "") or None
    if vai and vai not in VAI:
        raise ValueError(f"«{ten}»: vai phải là một trong {', '.join(VAI)}.")
    mat = str(x.get("mat") or "").strip() or None
    if mat and not _MAT.fullmatch(mat):
        raise ValueError(f"«{ten}»: mã khuôn mặt sai dạng.")
    chat = list(dict.fromkeys(str(c).strip() for c in x.get("chat") or [] if str(c).strip()))
    sai = [c for c in chat if not _CHAT.fullmatch(c)]
    if sai:
        raise ValueError(f"«{ten}»: tài khoản chat phải dạng kênh:mã (zalop / zalo / tg) — sai: {sai[0]}")
    return {"ma": ma, "ten": ten, "nam_sinh": nam, "theo_doi": theo_doi, "vai": vai, "mat": mat, "chat": chat}


def _gan_ma(ds_: list[dict[str, Any]], loai: str) -> None:
    co_ma = [x["ma"] for x in ds_ if x["ma"]]
    if len(set(co_ma)) != len(co_ma):
        raise ValueError(f"Hai {loai} trùng mã.")
    da_co = set(co_ma)
    for x in ds_:
        if not x["ma"]:
            x["ma"] = _ma_tu_ten(x["ten"], da_co)
            da_co.add(x["ma"])


def dat(muc: list[Any], thanh_vien: list[Any] | None = None) -> list[dict[str, Any]]:
    """Thay TOÀN BỘ lịch (và danh sách thành viên nếu truyền; ``None`` = giữ thành viên cũ). Mã trùng, sai
    kiểu, hoặc mục trỏ tới thành viên không có → ValueError, không ghi gì."""
    global _du_lieu, _tv
    if len(muc) > TOI_DA:
        raise ValueError(f"Lịch tối đa {TOI_DA} mục.")
    with _khoa:
        _nap()
        tv = [_chuan_tv(x) for x in thanh_vien] if thanh_vien is not None else [dict(x) for x in _tv or []]
        if len(tv) > TV_TOI_DA:
            raise ValueError(f"Tối đa {TV_TOI_DA} thành viên.")
        _gan_ma(tv, "thành viên")
        moi = [_chuan(x) for x in muc]
        _gan_ma(moi, "mục lịch")
        # Mục trỏ tới thành viên theo MÃ; thành viên mới chưa có mã thì web gửi theo tên — đổi ra mã ở đây.
        theo_ten = {x["ten"]: x["ma"] for x in tv}
        co = {x["ma"] for x in tv}
        for x in moi:
            x["ai"] = [a if a in co else theo_ten.get(a, a) for a in x["ai"]]
            la = [a for a in x["ai"] if a not in co]
            if la:
                raise ValueError(f"«{x['ten']}»: không có thành viên {', '.join(la)}.")
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"thanh_vien": tv, "muc": moi}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(_PATH)
        _du_lieu, _tv = moi, tv
    return [dict(x) for x in moi]


def _phut(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def trong(x: dict[str, Any], luc: float) -> bool:
    """Lúc ``luc`` có nằm trong mục ``x`` không — mục qua nửa đêm tính theo ngày bắt đầu."""
    d = datetime.fromtimestamp(luc, _TZ)
    p, a, b = d.hour * 60 + d.minute, _phut(x["tu"]), _phut(x["den"])
    if a < b:
        return a <= p < b and d.weekday() in x["thu"]
    if p >= a:
        return d.weekday() in x["thu"]
    return p < b and (d.weekday() - 1) % 7 in x["thu"]


def dang(luc: float) -> list[dict[str, Any]]:
    return [x for x in ds() if trong(x, luc)]


def tim(ma: str) -> dict[str, Any] | None:
    return next((x for x in ds() if x["ma"] == ma), None)


def ca_nha(loai: str, luc: float) -> bool:
    """Cả nhà đang ở loại ``loai`` (``ngu``, ``vang``…): một mục CẢ NHÀ loại đó đang diễn ra, hoặc có thành
    viên và AI CŨNG đang ở một mục loại đó (mục cả nhà tính cho mọi người)."""
    dang_ = [x for x in dang(luc) if x["loai"] == loai]
    if any(not x.get("ai") for x in dang_):
        return True
    tv = [x["ma"] for x in thanh_vien() if x.get("vai") != "khach_quen"]      # khách quen không phải «cả nhà»
    return bool(tv) and all(any(m in x["ai"] for x in dang_) for m in tv)


def _ten_mat() -> dict[str, str]:
    """Mã khuôn mặt → tên trong sổ mặt (camera gọi người này là gì)."""
    try:
        from services import so_mat_nha
        return {str(n["id"]): str(n.get("ten") or "") for n in so_mat_nha.danh_sach_nguoi()}
    except Exception:  # noqa: BLE001 — chưa bật nhận mặt thì thôi
        return {}


def _mo_ta(x: dict[str, Any], mat: dict[str, str]) -> str:
    phan = [VAI.get(x.get("vai") or "", "")] + ([f"{x['tuoi']} tuổi"] if x.get("tuoi") is not None else [])
    if x.get("mat") and mat.get(x["mat"]):
        phan.append(f"camera gọi là «{mat[x['mat']]}»")
    return f"«{x['ten']}»" + (f" — {', '.join(p for p in phan if p)}" if any(phan) else "")


def nguoi_cua_phien(user_id: str) -> dict[str, Any] | None:
    """Người trong nhà đang nhắn ở phiên này (khớp «kênh:mã người dùng» đã gắn), None nếu chưa gắn."""
    from services.agent import scope
    sc = scope.tach_khoa_phien(user_id)
    uid = sc.actor or sc.chat
    if not sc.kenh or not uid:
        return None
    khoa = f"{sc.kenh}:{uid}"
    return next((x for x in thanh_vien() if khoa in (x.get("chat") or [])), None)


def khoi_prompt_nguoi(user_id: str) -> str:
    """Khối «ai là ai» cho lời trò chuyện: người trong nhà (vai, tuổi, tên camera gọi) + ai đang nhắn. Rỗng khi chưa
    khai người nào. Khuôn mặt đã đặt tên mà không gắn với ai = khách quen; mặt chưa biết = người lạ."""
    tv = thanh_vien()
    if not tv:
        return ""
    mat = _ten_mat()
    nha = [x for x in tv if x.get("vai") != "khach_quen"]
    khach = [x for x in tv if x.get("vai") == "khach_quen"]
    da_gan = {x.get("mat") for x in tv if x.get("mat")}
    khach_mat = [t for m, t in mat.items() if m not in da_gan and t]
    dong = ["NGƯỜI TRONG NHÀ (chủ nhà khai — dùng đúng vai, đừng đoán quan hệ khác):",
            *[f"- {_mo_ta(x, mat)}" for x in nha]]
    if khach or khach_mat:
        dong.append("KHÁCH QUEN: " + ", ".join([_mo_ta(x, mat) for x in khach] + [f"«{t}» (camera)" for t in khach_mat]))
    dong.append("Mặt camera chưa biết là NGƯỜI LẠ.")
    ai = nguoi_cua_phien(user_id)
    dong.append(f"NGƯỜI ĐANG NHẮN VỚI EM: {_mo_ta(ai, mat)}." if ai else
                "Người đang nhắn CHƯA được gắn với ai trong nhà — đừng đoán là ai, cần thì hỏi lịch sự.")
    return "\n".join(dong)


def doc_cho_bot(luc: float | None = None) -> list[str]:
    """Mấy dòng «ai trong nhà, lịch từng người» cho đề của bot (rỗng khi chưa khai gì)."""
    import time as _time
    luc = _time.time() if luc is None else luc
    tv = thanh_vien()
    ten_nhom = {m: t for m, t, _a, _b in NHOM}
    ten_tv = {x["ma"]: x["ten"] for x in tv}
    dong = [f"- {x['ten']}" + (f" [{VAI[x['vai']]}]" if x.get("vai") in VAI else "")
            + (f" ({x['tuoi']} tuổi, {ten_nhom.get(x['nhom'], '')})" if x["tuoi"] is not None else "")
            + (f" — theo dõi qua {', '.join(x['theo_doi'])}" if x["theo_doi"] else "") for x in tv]
    for x in ds():
        ai = ", ".join(ten_tv.get(a, a) for a in x["ai"]) or "cả nhà"
        thu = "mọi ngày" if len(x["thu"]) == 7 else ",".join(("T2", "T3", "T4", "T5", "T6", "T7", "CN")[t] for t in x["thu"])
        dong.append(f"- Lịch {ai}: {x['ten']} ({x['loai']}) {x['tu']}–{x['den']} {thu}"
                    + (" ← ĐANG DIỄN RA" if trong(x, luc) else ""))
    return dong


def _reset_for_tests(duong: Path) -> None:
    global _PATH, _du_lieu, _tv
    _PATH = duong
    _du_lieu = _tv = None
