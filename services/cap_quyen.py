"""Cấp quyền dùng bot NGAY TRONG KÊNH, có thời hạn — chủ máy duyệt, bot tự tích bộ lọc.

Chủ máy 03/10/2026: "Tôi là admin, khi có người xin, gửi thông báo tới tôi, tôi duyệt trên kênh thì bot tự tích,
cấp quyền cho người đó. Thứ 2 có thể cấp quyền trong bao lâu … Tôi đỡ phải vào thay đổi cài đặt."
Duyệt bảng gói đề xuất (``GOI``) cùng ngày.

Đấu nối: tin «💬 chat mới» → `admin_workspace.start_save_prompt` (đã có) → admin trả lời trong luồng chờ
`save_contact` → `cap()` ghi ``thread_filters[<nền tảng>:<bot>:<chat>]`` (khoá bot-riêng mà
`allowed_groups_for_member` đọc ĐẦU TIÊN) và sổ hạn ``data/agent/cap_quyen.json``. Heartbeat gọi `het_han()`: quá
hạn thì gỡ — CHỈ khi bản ghi còn đúng như bot đã ghi (anh sửa tay trên web rồi thì bot không đụng) — và báo anh.

«Chặn» = bản ghi lọc RỖNG: `duoc_giao_tiep` coi là «đã thêm nhưng chưa cho gì» → bot im, và không báo lạ nữa.
Nhóm trong ``KHONG_TU_CAP`` không bao giờ vào gói — chỉ anh tích tay trên web.
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

_PATH = Path(DATA_DIR) / "agent" / "cap_quyen.json"
_khoa = threading.Lock()

GOI: dict[str, tuple[str, ...]] = {
    "khach": ("web", "summary", "wiki", "rag", "image", "music", "tts_reply", "memory"),
    "nguoi_nha": ("web", "summary", "wiki", "rag", "image", "music", "tts_reply", "memory",
                  "homeassistant", "camera", "schedule", "tts_speaker", "chi_tieu", "office", "word", "video",
                  "teacher", "skills"),
}
KHONG_TU_CAP = frozenset({"server", "code", "device", "contacts", "facebook", "kho_dam_may"})
TEN_GOI = {"khach": "Khách", "nguoi_nha": "Người nhà", "chan": "Chặn"}

#: Lựa chọn đánh số trong tin báo (chủ máy duyệt 03/10/2026). None = mãi mãi.
SO: dict[str, tuple[str, int | None]] = {
    "1": ("khach", 86400), "2": ("khach", 7 * 86400),
    "3": ("nguoi_nha", 7 * 86400), "4": ("nguoi_nha", None),
    "5": ("chan", None),
}
HUONG_DAN = ("🔐 **Cấp quyền dùng bot?** Trả lời số:\n"
             "1. Khách 1 ngày   2. Khách 7 ngày\n"
             "3. Người nhà 7 ngày   4. Người nhà mãi mãi\n"
             "5. Chặn   6. Bỏ qua\n"
             "(hoặc gõ: «khách 3 ngày», «người nhà 12 giờ»)")

_DON_VI = {"phut": 60, "gio": 3600, "tieng": 3600, "ngay": 86400, "tuan": 7 * 86400, "thang": 30 * 86400}


def _bo_dau(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s or "").lower()).replace("đ", "d")
    return " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").split())


def doc_lua_chon(text: str) -> dict[str, Any] | None:
    """Câu trả lời của admin → {"goi": khach|nguoi_nha|chan|bo, "giay": số giây | None (mãi)}; không phải → None.
    Cú pháp lệnh của chính tin báo (số 1–6, «khách/người nhà N ngày|giờ|tuần», «mãi», «chặn», «bỏ qua»)."""
    t = _bo_dau(text).strip(" .!")
    if t in SO:
        goi, giay = SO[t]
        return {"goi": goi, "giay": giay}
    if t in ("6", "bo qua"):
        return {"goi": "bo", "giay": None}
    if t in ("chan", "block"):
        return {"goi": "chan", "giay": None}
    m = re.fullmatch(r"(khach|nguoi nha)(?:\s+(\d+)\s*(phut|gio|tieng|ngay|tuan|thang)|\s+(mai|mai mai|vinh vien))?", t)
    if not m:
        return None
    goi = "khach" if m.group(1) == "khach" else "nguoi_nha"
    if m.group(2):
        return {"goi": goi, "giay": int(m.group(2)) * _DON_VI[m.group(3)]}
    if m.group(4):
        return {"goi": goi, "giay": None}
    return {"goi": goi, "giay": SO["1"][1] if goi == "khach" else SO["3"][1]}


def _nap() -> dict[str, Any]:
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _luu(d: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_PATH)


def khoa_loc(platform: str, bot_id: str, chat_id: str) -> str:
    """Khoá bot-riêng của `thread_filters` — khoá `allowed_groups_for_member` thử ĐẦU TIÊN."""
    bot_id = str(bot_id or "").strip()
    return f"{platform}:{bot_id}:{chat_id}" if bot_id else f"{platform}:{chat_id}"


def _thoi_han(giay: int | None) -> str:
    if giay is None:
        return "mãi mãi"
    for ten, s in (("tuần", 7 * 86400), ("ngày", 86400), ("giờ", 3600), ("phút", 60)):
        if giay >= s and giay % s == 0:
            return f"{giay // s} {ten}"
    return f"{round(giay / 3600, 1)} giờ"


def cap(platform: str, bot_id: str, chat_id: str, goi: str, giay: int | None, *,
        ten: str = "", nguoi_duyet: str = "", now: float | None = None) -> str:
    """Ghi bộ lọc + sổ hạn. Trả câu báo cho admin."""
    from services.config import config

    now = float(now or time.time())
    if goi not in ("khach", "nguoi_nha", "chan"):
        raise ValueError(f"gói lạ: {goi}")
    nhom = [] if goi == "chan" else sorted(set(GOI[goi]) - KHONG_TU_CAP)
    k = khoa_loc(platform, bot_id, chat_id)

    def _ghi(data: dict) -> None:
        data.setdefault("thread_filters", {})[k] = list(nhom)
    config.mutate(_ghi)
    with _khoa:
        d = _nap()
        d[k] = {"goi": goi, "nhom": nhom, "luc": now, "het_han": None if giay is None or goi == "chan" else now + giay,
                "ten": ten, "nguoi_duyet": nguoi_duyet, "platform": platform, "chat_id": str(chat_id)}
        _luu(d)
    logger.info({"event": "cap_quyen", "khoa": k, "goi": goi, "giay": giay, "nguoi_duyet": nguoi_duyet})
    ai = f"**{ten}**" if ten else f"`{chat_id}`"
    if goi == "chan":
        return f"⛔ Đã chặn {ai}: bot im với khung chat này và không báo lạ nữa."
    return (f"✅ Đã cấp gói **{TEN_GOI[goi]}** cho {ai} — {_thoi_han(giay)}"
            + ("" if giay is None else f" (tới {time.strftime('%H:%M %d/%m', time.localtime(now + giay))})")
            + f".\nNhóm: {', '.join(nhom)}. Hết hạn em tự gỡ và báo anh.")


def het_han(now: float | None = None) -> list[str]:
    """Gỡ quyền đã quá hạn. Bản ghi lọc anh đã sửa tay (khác cái bot ghi) thì để nguyên. Trả câu báo."""
    from services.config import config

    now = float(now or time.time())
    with _khoa:
        d = _nap()
    qua = {k: v for k, v in d.items() if v.get("het_han") and float(v["het_han"]) <= now}
    if not qua:
        return []
    bao: list[str] = []
    da_go: list[str] = []

    def _go(data: dict) -> None:
        tf = data.setdefault("thread_filters", {})
        for k, v in qua.items():
            if sorted(tf.get(k) or []) == sorted(v.get("nhom") or []):
                tf.pop(k, None)
                da_go.append(k)
    config.mutate(_go)
    with _khoa:
        d = _nap()
        for k, v in qua.items():
            d.pop(k, None)
            ai = v.get("ten") or v.get("chat_id") or k
            bao.append(f"⌛ Hết hạn gói {TEN_GOI.get(v.get('goi'), v.get('goi'))} của {ai} — "
                       + ("em đã gỡ quyền." if k in da_go else "anh đã sửa tay trên web nên em để nguyên."))
        _luu(d)
    logger.info({"event": "cap_quyen_het_han", "da_go": da_go, "giu": sorted(set(qua) - set(da_go))})
    return bao


def chay_mot_lan(now: float | None = None) -> int:
    """Heartbeat: gỡ quyền hết hạn rồi báo qua thông báo «💬 Chat/nhóm mới» (cùng nơi anh nhận tin xin quyền)."""
    bao = het_han(now)
    if bao:
        from services import thong_bao
        thong_bao.gui("chat.moi", "\n".join(bao))
    return len(bao)


def ds() -> dict[str, Any]:
    with _khoa:
        return _nap()


def _reset_for_tests(duong: Path) -> None:
    global _PATH
    _PATH = duong
