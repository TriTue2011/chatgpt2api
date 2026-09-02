"""Dựng dòng ngữ cảnh “tin đang được trích dẫn” cho model — dùng chung ba kênh.

Người dùng bấm nút "Trả lời/đính kèm" một tin cũ rồi hỏi tiếp; Zalo cá nhân,
Zalo Bot và Telegram đều có thao tác này. Mỗi kênh rút ra được gì thì đưa vào
một dict phẳng (JSON-an-toàn để đi xuyên pipeline, kể cả qua thread/worker):

    {"noi_dung": str, "ts": float, "cua_ai": str, "co_dinh_kem": bool}

- ``noi_dung``  nội dung tin được trích (rỗng nếu nền tảng không kèm).
- ``ts``        mốc thời gian tin đó, epoch GIÂY (0 nếu không có).
- ``cua_ai``    tên người gửi tin được trích; "bot" nếu là tin của chính bot.
- ``co_dinh_kem`` tin được trích có ảnh/tệp không.

`mo_ta()` biến dict đó thành một câu cho model. Khi nền tảng KHÔNG kèm nội dung
(chỉ có tham chiếu + mốc thời gian — Zalo Bot có thể vậy), nó tra lại nội dung
từ nhật ký phiên (``session.turns``) rồi tới sổ nhóm (``chatlog``) trước khi
đành dùng câu chữa cháy. Đây là phần "dùng nhật ký/memory lấy thông tin tin
nhắn gán vào để hỏi".
"""
from __future__ import annotations

import time
from typing import Any

#: Cửa sổ khớp mốc thời gian khi tra lại nội dung tin trích. Rộng tay: mốc của
#: tin (do nền tảng đóng dấu) và ``created_at`` của lượt lưu (lúc bot xử lý
#: xong) lệch nhau vài giây tới vài phút là chuyện thường.
_CUA_SO_S = 900.0


def _luc(ts: float) -> str:
    """Mốc epoch giây → chữ giờ-ngày người đọc được; "" nếu không có mốc."""
    try:
        t = float(ts or 0)
    except (TypeError, ValueError):
        return ""
    if t <= 0:
        return ""
    return " lúc " + time.strftime("%H:%M %d/%m/%Y", time.localtime(t))


def _tu_nhat_ky(session_key: str, ts: float) -> tuple[str, str]:
    """Lấy lại (nội dung, người gửi) của tin gần mốc ``ts`` từ nhật ký đã lưu.

    Thử phiên 1-1/nhóm của chính người này trước (``session.turns`` — bật mặc
    định), rồi tới sổ chung của nhóm (``chatlog`` — chỉ có nếu nhóm bật ghi).
    Trả ("","") nếu không tìm được — bên gọi tự lo câu chữa cháy.
    """
    if not session_key or not ts:
        return "", ""
    try:
        from services.agent import session as _sess
        row = _sess.turn_gan_ts(session_key, ts, window_s=_CUA_SO_S)
        if row and str(row.get("content") or "").strip():
            ai = "bot" if row.get("role") == "assistant" else ""
            return str(row["content"]).strip(), ai
    except Exception:
        pass
    try:
        from services.agent import chatlog as _cl
        row = _cl.tin_gan_ts(session_key, ts, window_s=_CUA_SO_S)
        if row and str(row.get("text") or "").strip():
            return str(row["text"]).strip(), str(row.get("sender") or "")
    except Exception:
        pass
    return "", ""


def mo_ta(q: dict[str, Any] | None, *, session_key: str = "",
          gioi_han: int = 1200) -> str:
    """dict trích dẫn → một câu cho model, hoặc "" nếu không có gì để trích.

    ``session_key`` là khoá phiên của lượt hiện tại (``zalo_…`` / ``zalop_…`` /
    khoá Telegram) — cần cho bước tra nhật ký khi nội dung tin trích bị thiếu.
    """
    if not isinstance(q, dict):
        return ""
    noi_dung = str(q.get("noi_dung") or "").strip()
    ts = q.get("ts") or 0
    cua_ai = str(q.get("cua_ai") or "").strip()
    co_dinh_kem = bool(q.get("co_dinh_kem"))

    # Nền tảng không kèm nội dung → tra lại từ nhật ký/sổ nhóm theo mốc thời gian.
    if not noi_dung and ts and session_key:
        lay, ai = _tu_nhat_ky(session_key, ts)
        if lay:
            noi_dung = lay
            if ai and not cua_ai:
                cua_ai = ai

    if not noi_dung and not co_dinh_kem:
        return ""

    nguoi = "chính em (bot)" if cua_ai == "bot" else (cua_ai or "ai đó")
    than = noi_dung[:gioi_han] if noi_dung else "(một tin có ảnh/tệp đính kèm)"
    return f"{nguoi}{_luc(ts)} đã nhắn: “{than}”"
