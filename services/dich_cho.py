"""Bản CHỜ CHỌN cho việc dịch — bot hỏi trước khi làm, không tự đoán.

Chủ máy chốt 14/08: "bot khi dùng đến phải có lựa chọn rõ ràng, ví dụ phụ đề
phải cho chọn ngôn ngữ chuyển là gì và lấy file phụ đề hay chỉ là file văn bản".
Trước đây bot tự quyết cả hai (luôn .srt, luôn dịch sang tiếng Việt/Anh theo
luật `chon_dich_sang`) — nghe một video 2 giờ xong mới biết không phải thứ mình
cần là mất cả tiếng.

Và chốt tiếp: "/dich mà không có đích ngôn ngữ thì phải đưa ra các lựa chọn" —
trước đây `/dich xin chào` tự nhảy sang tiếng Anh theo luật `chon_dich_sang`.

Cùng nếp ``pdf_intent`` / ``photo_intent``: giữ bản chờ theo khoá phiên, gửi menu
đánh số, người dùng nhắn số thì chạy. Ba loại nguồn dùng chung sổ chờ này:
TỆP (đường dẫn tạm), LINK (url), CHỮ (chu) — menu khác nhau theo loại.

Ngôn ngữ NGUỒN không có trong menu vì chưa nghe thì chưa biết; máy tự dò trong
cặp (tiếng Việt ↔ tiếng đích đã chọn) — xem ``video_asr._chon_ngon_ngu``.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

#: Bản chờ sống ngần này giây rồi tự dọn (kèm xoá tệp tạm). Dài hơn menu PDF
#: (10 phút) vì người dùng gửi video xong hay đi làm việc khác.
_TTL = 30 * 60
_pending: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()

#: Tiếng đích chọn được. Khoá = tên gõ trong menu ("4 nhật").
TIENG = {
    "vi": ("việt", "viet", "vn", "vietnamese"),
    "en": ("anh", "en", "english"),
    "ja": ("nhật", "nhat", "ja", "japanese"),
    "zh": ("trung", "zh", "chinese", "hoa"),
    "ko": ("hàn", "han", "ko", "korean"),
}
TEN_TIENG = {"vi": "Việt", "en": "Anh", "ja": "Nhật", "zh": "Trung", "ko": "Hàn"}


def _gc() -> None:
    """Dọn bản chờ hết hạn. Gọi khi ĐÃ giữ ``_lock``."""
    now = time.time()
    for k in [k for k, v in _pending.items() if now - v["ts"] > _TTL]:
        v = _pending.pop(k, None)
        if v and v.get("path"):
            try:
                os.unlink(v["path"])
            except OSError:
                pass


def set_pending(key: str, *, path: str = "", url: str = "", chu: str = "",
                ten: str = "", so_byte: int = 0) -> None:
    """Ghi bản chờ. Đúng MỘT trong ba: ``path`` (tệp tạm) · ``url`` (link) ·
    ``chu`` (đoạn chữ cần dịch)."""
    with _lock:
        cu = _pending.pop(key, None)
        if cu and cu.get("path"):
            try:
                os.unlink(cu["path"])
            except OSError:
                pass
        _pending[key] = {"path": path, "url": url, "chu": chu,
                         "ten": ten or ("đoạn chữ" if chu else "video"),
                         "so_byte": int(so_byte or 0), "ts": time.time()}
        _gc()


def has_pending(key: str) -> bool:
    with _lock:
        _gc()
        return key in _pending


def get_pending(key: str) -> dict[str, Any] | None:
    with _lock:
        p = _pending.get(key)
        return dict(p) if p else None


def pop_pending(key: str) -> dict[str, Any] | None:
    """Lấy bản chờ ra khỏi sổ — người gọi có trách nhiệm xoá tệp tạm."""
    with _lock:
        return _pending.pop(key, None)


def don_tep(pend: dict[str, Any] | None) -> None:
    """Xoá tệp tạm của một bản chờ đã lấy ra."""
    if pend and pend.get("path"):
        try:
            os.unlink(pend["path"])
        except OSError:
            pass


def _la_phu_de(ten: str) -> bool:
    return str(ten or "").lower().endswith((".srt", ".vtt"))


def la_chu(pend: dict[str, Any]) -> bool:
    """Bản chờ này là ĐOẠN CHỮ (không phải tệp/link) — menu chỉ hỏi tiếng đích."""
    return bool(pend.get("chu"))


def menu(pend: dict[str, Any]) -> str:
    """Menu đánh số gửi cho người dùng."""
    if la_chu(pend):
        xem = str(pend.get("chu") or "").strip().replace("\n", " ")
        if len(xem) > 60:
            xem = xem[:60] + "…"
        return (
            f"🌐 «{xem}»\nDịch sang tiếng nào ạ? Nhắn số:\n"
            "1. Tiếng Việt\n2. Tiếng Anh\n3. Tiếng Nhật\n"
            "4. Tiếng Trung\n5. Tiếng Hàn\n"
            "Lần sau nhắn thẳng «/dich tiếng nhật …» thì em làm ngay, khỏi hỏi.\n"
            "Nhắn «thôi» để bỏ."
        )
    ten = str(pend.get("ten") or "video")
    mb = pend.get("so_byte") or 0
    co = f" ({mb / 1024 / 1024:.0f} MB)" if mb else ""
    if pend.get("url"):
        dau = f"🎬 Link video: {ten}{co}"
        cho = "Em lấy phụ đề của video rồi làm gì ạ?"
    elif _la_phu_de(ten):
        dau = f"📄 Tệp phụ đề: {ten}{co}"
        cho = "Em dịch phụ đề này thành gì ạ?"
    else:
        dau = f"🎬 Tệp: {ten}{co}"
        cho = "Em nghe rồi làm gì ạ? (video dài mất vài phút)"
    return (
        f"{dau}\n{cho} Nhắn số:\n"
        "1. Phụ đề .srt — dịch sang tiếng Việt\n"
        "2. Bản chữ (chỉ lời thoại) — dịch sang tiếng Việt\n"
        "3. Phụ đề .srt — GIỮ nguyên tiếng gốc (chép lời, không dịch)\n"
        "4. Phụ đề .srt sang tiếng khác — nhắn «4 anh» / «4 nhật» / «4 trung» / «4 hàn»\n"
        "5. Bản chữ sang tiếng khác — nhắn «5 anh» / «5 nhật» …\n"
        "Nhắn «thôi» để bỏ."
    )


_BO = ("thôi", "thoi", "bỏ", "bo", "huỷ", "huy", "cancel", "khỏi", "khoi")
_SO = re.compile(r"^\s*([1-5])\b(.*)$", re.DOTALL)


#: Số trong menu CHỮ → tiếng đích (khác menu video: ở đó số là kiểu kết quả).
_SO_TIENG_CHU = {"1": "vi", "2": "en", "3": "ja", "4": "zh", "5": "ko"}


def giai_chon(text: str, *, cho_chu: bool = False) -> dict[str, Any] | None:
    """Câu người dùng nhắn → lựa chọn.

    ``cho_chu=True`` giải theo menu CHỮ (số = tiếng đích); mặc định giải theo
    menu video/phụ đề (số = kiểu kết quả + tiếng).

    Trả ``{"bo": True}`` nếu xin bỏ; ``{"kieu": "phu-de"|"chu", "target": …}``
    nếu chọn hợp lệ (``target`` = "giu-goc" nghĩa là không dịch, "cap:xx"
    nghĩa là cặp Việt ↔ xx); ``None`` nếu câu này không phải trả lời menu.
    """
    t = str(text or "").strip().lower()
    if not t:
        return None
    if t in _BO:
        return {"bo": True}
    m = _SO.match(t)
    if not m:
        return None
    so, con = m.group(1), (m.group(2) or "").strip()
    if cho_chu:
        return {"kieu": "chu", "target": f"cap:{_SO_TIENG_CHU[so]}"}
    if so == "1":
        return {"kieu": "phu-de", "target": "cap:vi"}
    if so == "2":
        return {"kieu": "chu", "target": "cap:vi"}
    if so == "3":
        return {"kieu": "phu-de", "target": "giu-goc"}
    # 4 / 5 — phải kèm tên tiếng
    kieu = "phu-de" if so == "4" else "chu"
    for ma, ten in TIENG.items():
        if any(x in con for x in ten):
            return {"kieu": kieu, "target": f"cap:{ma}"}
    return {"thieu_tieng": True, "kieu": kieu}


def target_cho_may(chon: dict[str, Any], nguon_biet: str = "") -> str:
    """Lựa chọn → giá trị ``target`` mà ``video_dich`` hiểu.

    - ``"cap:vi"`` (chọn 1/2) → cặp Việt↔Anh mặc định, tức truyền ``""``:
      máy tự chọn chiều (nguồn Việt thì sang Anh, còn lại về Việt).
    - ``"cap:xx"`` khác → giữ nguyên dạng cặp.
    - ``"giu-goc"`` → dịch sang CHÍNH tiếng nguồn = không dịch (bản chép lời);
      chưa biết nguồn thì trả ``"giu-goc"`` để tầng gọi tự xử.
    """
    tg = str(chon.get("target") or "")
    if tg == "cap:vi":
        return ""
    if tg == "giu-goc":
        return nguon_biet or "giu-goc"
    return tg
