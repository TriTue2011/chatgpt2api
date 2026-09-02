"""Đoán tin cũ người dùng đang nhắc tới, khi nền tảng KHÔNG gửi trích dẫn.

Nhiều nền tảng không kèm tham chiếu tin được trả lời — đo thật 02/09: Zalo Bot
chính thức chỉ gửi chat/date/from/message_id/text, không có trường trích dẫn nào
(khác Zalo cá nhân/Telegram vốn có). Khi ấy người dùng bấm "Trả lời" một tin cũ
rồi hỏi cụt ("cái này sao rồi", "vụ đó dập chưa") thì bot không biết "cái này" là
gì.

Module này bù theo XÁC SUẤT: khi câu hỏi mơ hồ và KHÔNG có trích dẫn thật, tra
nhật ký phiên + sổ nhóm bằng chính chữ trong câu, rồi trả về một khối ngữ cảnh
có ĐÁNH DẤU PHỎNG ĐOÁN để model dùng nếu hợp, bỏ (và hỏi lại) nếu trật. KHÔNG
thay được trích dẫn thật — câu trỏ trống hoàn toàn vào tin xa không chữ khoá thì
vẫn chịu, khi ấy tầng 1 lấy tin gần nhất còn model được dặn hỏi lại.

Bám khuôn `services/agent/super_context.py` (đã tra ngược lịch sử để chèn "Chat
cũ liên quan"), nhưng chạy được ở lượt GIỮA hội thoại — đúng lúc reply-quote xảy
ra — chứ không chỉ lượt đầu.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Dấu hiệu câu TRỎ về một thứ đã nói mà không nêu tên: đại từ chỉ định / hồi chỉ
# đứng như một từ riêng (đó, này, kia, ấy, nó). Tiếng Việt hay tách "vụ CHÁY đó"
# nên không đòi cụm liền — chỉ cần có đại từ + câu đủ ngắn (xét ở `_la_mo_ho`).
_RE_TRO = re.compile(r"(?iu)\b(đó|đấy|nầy|này|kia|ấy|nó)\b")

_WORD_RE = re.compile(r"[\wÀ-ỹ]{2,}", re.UNICODE)

# Bỏ khỏi truy vấn: đại từ trỏ + từ đệm/hỏi, giữ lại từ mang nội dung ("cháy",
# "họp"). Không bỏ thì "vụ"/"đó" trùng khắp nơi làm tra cứu nhiễu.
_BO = {
    "cai", "nay", "do", "kia", "no", "ay", "cho", "dieu", "chuyen", "viec",
    "vu", "tin", "the", "la", "gi", "sao", "roi", "chua", "nao", "ra", "va",
    "thi", "a", "o", "voi", "cho", "cua", "duoc", "khong", "co", "em", "anh",
    "chi", "minh", "ban", "giup", "hoi", "xong", "lai", "nhe", "nha", "day",
}


def _fold(s: str) -> str:
    """Bỏ dấu thô để lọc stopword (khớp _BO viết không dấu)."""
    b = "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    k = "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd"
    return (s or "").translate(str.maketrans(b, k))


def _la_mo_ho(user_text: str) -> bool:
    """Câu này có TRỎ về thứ đã nói mà không nêu tên không."""
    t = (user_text or "").strip()
    if not t or len(t) > 120:
        return False
    return bool(_RE_TRO.search(t))


def _tu_khoa(user_text: str) -> list[str]:
    """Từ mang nội dung trong câu, để tra ngược lịch sử. [] nếu chỉ toàn từ trỏ."""
    ra: list[str] = []
    seen: set[str] = set()
    for w in _WORD_RE.findall((user_text or "").lower()):
        f = _fold(w)
        if f in _BO or w in seen:
            continue
        seen.add(w)
        ra.append(w)
        if len(ra) >= 5:
            break
    return ra


def _tin_bot_gan_nhat(hist: list[dict[str, Any]]) -> str:
    """Nội dung tin GẦN NHẤT của bot — ứng viên khi câu chỉ có từ trỏ trống."""
    for m in reversed(hist or []):
        if (m.get("role") or "") == "assistant":
            c = str(m.get("content") or "").strip()
            if c:
                return c
    return ""


def doan(user_id: str, user_text: str, hist: list[dict[str, Any]] | None,
         *, budget: int = 600) -> str:
    """Khối ngữ cảnh phỏng đoán cho system prompt, hoặc "" nếu không đoán được.

    Bên gọi chỉ dùng khi lượt này KHÔNG có trích dẫn thật từ nền tảng.
    """
    if not _la_mo_ho(user_text):
        return ""

    ung_vien: list[str] = []

    # Tầng 2 — có chữ nội dung thì tra ngược nhật ký phiên (FTS toàn văn các lượt
    # của chính người này — nơi tin được trích nằm). Sổ nhóm (`chatlog`) chỉ tra
    # được theo người-được-@nhắc, không theo nội dung, nên không dùng ở đây.
    tu = _tu_khoa(user_text)
    if tu:
        q = " ".join(tu)
        try:
            from services.agent import session as _sess
            if _sess.is_enabled():
                for h in _sess.search(user_id, q, limit=2):
                    c = str(h.get("content") or "").strip()
                    if c:
                        ai = "em (bot)" if h.get("role") == "assistant" else "người dùng"
                        ung_vien.append(f"({ai}) {c[:200]}")
        except Exception as exc:
            logger.debug("tham_chieu session: %s", exc)

    # Tầng 1 — không có chữ nội dung (trỏ trống) → tin gần nhất của bot.
    if not ung_vien:
        gan = _tin_bot_gan_nhat(hist or [])
        if gan:
            ung_vien.append(f"(em (bot)) {gan[:200]}")

    if not ung_vien:
        return ""

    than = "\n".join(f"- {u}" for u in ung_vien)[:budget]
    return (
        "\n\n## Có thể người dùng đang nhắc tới (PHỎNG ĐOÁN)\n"
        + than
        + "\n\nTin này KHÔNG kèm trích dẫn nên đây là em TỰ ĐOÁN từ lịch sử. "
          "Nếu nó khớp câu hỏi thì trả lời thẳng dựa vào đó; nếu thấy KHÔNG "
          "liên quan thì ĐỪNG bịa — hỏi lại một câu ngắn «anh/chị đang nhắc "
          "tới điều gì ạ?»."
    )
