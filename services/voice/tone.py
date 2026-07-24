"""Chọn 'style' đọc VieNeu theo TÍNH CHẤT câu nói — deterministic, 0 token model.

VieNeu v3 Turbo chỉ có đúng 3 style:
  - tu_nhien   : hội thoại, tán gẫu, đùa (mặc định)
  - tin_tuc    : nghiêm túc — báo cáo / số liệu / tin tức / phân tích
  - doc_truyen : kể chuyện, an ủi, khuyên nhủ (ấm & chậm)

Khớp triết lý persona (_SUFFIX): đùa→tu_nhien; tin tức/phân tích/dạy→tin_tuc;
an ủi/khuyên/kể→doc_truyen. Chỉ dùng heuristic từ khoá — không gọi model.
"""

from __future__ import annotations

import re

STYLES = ("tu_nhien", "tin_tuc", "doc_truyen")

# Nghiêm túc / tin tức / báo cáo / phân tích / thời tiết.
_NEWS_RE = re.compile(
    r"(báo cáo|bản tin|cập nhật tình hình|thống kê|số liệu|dữ liệu|kết quả|"
    r"theo (báo|nguồn|thông tin|dự báo)|ghi nhận|công bố|cảnh báo|"
    r"doanh thu|lợi nhuận|tăng trưởng|chỉ số|biểu đồ|quý [1-4]|"
    r"phân tích|tổng hợp|thời tiết|nhiệt độ)",
    re.IGNORECASE)

# Kể chuyện / an ủi / khuyên nhủ / ấm áp.
_STORY_RE = re.compile(
    r"(ngày xửa|ngày xưa|câu chuyện|kể (cho|bạn|em|anh|chị|nghe)|truyện|"
    r"đừng (lo|buồn|khóc|nản)|cố lên|bình tĩnh|không sao (đâu|cả)|ổn (mà|thôi)|"
    r"mình hiểu|thấu hiểu|chia sẻ|an ủi|động viên|"
    r"lời khuyên|khuyên (bạn|em|anh|chị)|nên nhớ|hãy (thử|cứ|tin))",
    re.IGNORECASE)

# Đùa / tán gẫu — thắng mọi tín hiệu khác (giữ tu_nhien).
_FUN_RE = re.compile(
    r"(haha|hihi|hehe|kaka|=\)|:\)|:v|đùa|"
    r"vui (tính|ghê|thế|quá)|buồn cười|troll|xàm|chọc|"
    r"😂|🤣|😅|😆|😜|😉|😁|😄|😝)",
    re.IGNORECASE)


def style_for(text: str, base: str = "") -> str:
    """Trả 1 style VieNeu theo nội dung câu.

    `base` = tông tĩnh gợi ý từ persona (dùng để phá hoà khi câu trung tính).
    Không rõ → 'tu_nhien'.
    """
    t = (text or "").strip()
    if not t:
        return base if base in STYLES else "tu_nhien"
    if _FUN_RE.search(t):
        return "tu_nhien"
    news = bool(_NEWS_RE.search(t))
    story = bool(_STORY_RE.search(t))
    if news and not story:
        return "tin_tuc"
    if story and not news:
        return "doc_truyen"
    if base in STYLES:
        return base
    # Trung tính: nhiều chữ số / phần trăm → thiên tin tức.
    if "%" in t or sum(c.isdigit() for c in t) >= 6:
        return "tin_tuc"
    return "tu_nhien"
