"""Quality gate cho nội dung KB do AI tổng hợp (write-back + scheduler).

Mục đích: KHÔNG nạp rác vào kho. Các bản tổng hợp trước đây lẫn quảng cáo
("mã giới thiệu MEXC"), tin lạc đề (Nga–Ukraina) và văn bản META bàn về
"cách cấu trúc kho" thay vì kiến thức thật. Gate này chặn các trường hợp đó.

Pragmatic, không cầu toàn: ngắn quá / có marker rác / là meta về chính kho /
lạc hẳn chủ đề câu hỏi → loại.
"""

from __future__ import annotations

import re

MIN_LEN = 300

# Marker quảng cáo / rác thường gặp trong kết quả web thô lọt vào synthesis.
_JUNK = (
    "mã giới thiệu", "mexc", "binance", "đăng ký tài khoản", "khuyến mãi",
    "nhấp vào đây", "click here", "đăng nhập để", "theo dõi kênh",
    "mã mời", "nhận thưởng", "airdrop", "săn sale", "giảm giá sốc",
)

# Dấu hiệu văn bản META (AI bàn về cách dựng kho thay vì cung cấp tri thức).
_META = (
    "cấu trúc kho", "gợi ý cấu trúc", "knowledge base nên", "kb_",
    "nguyên tắc lọc", "cấu trúc cập nhật cho kho",
)


def is_good_synthesis(text: str, topic: str = "", min_len: int = MIN_LEN) -> tuple[bool, str]:
    """Trả (ok, lý do). ok=False nghĩa là KHÔNG nên nạp vào kho."""
    if not text or len(text.strip()) < min_len:
        return False, "too_short"
    low = text.lower()

    if any(j in low for j in _JUNK):
        return False, "junk_marker"

    if sum(1 for m in _META if m in low) >= 2:
        return False, "meta_commentary"

    # Lạc đề: ít nhất một từ nội dung (>=4 ký tự) của câu hỏi phải xuất hiện.
    words = [w for w in re.findall(r"[0-9a-zà-ỹ]+", topic.lower()) if len(w) >= 4]
    if words and not any(w in low for w in words):
        return False, "off_topic"

    return True, "ok"
