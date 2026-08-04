"""Chuẩn hoá tiếng Việt cho TÌM KIẾM/KHỚP — không đụng tới bản gốc khi lưu.

Hai việc:

* `fold(s)` — bỏ thanh điệu + dấu nguyên âm (â/ê/ô/ơ/ư…) + đ→d. Dùng để KHỚP
  không phụ thuộc dấu: người dùng gõ "toi co lich" vẫn khớp "tôi có lịch",
  "dong" khớp "đông". KHÔNG phụ thuộc thư viện ngoài — luôn chạy.

* `segment(s)` — tách từ ghép ("học sinh" → "học_sinh") bằng **pyvi** NẾU có.
  pyvi kéo theo scikit-learn (nặng) nên import MỀM: thiếu thì trả nguyên văn,
  không bao giờ vỡ. Nhờ vậy bật/tắt pyvi không đổi tính đúng, chỉ đổi độ mịn.

Nguyên tắc: chỉ dùng ở tầng index/query của tìm kiếm. LƯU vẫn giữ nguyên bản có
dấu để hiển thị — fold là bản BÓNG để khớp, không thay bản gốc.
"""

from __future__ import annotations

import unicodedata


def fold(s: str) -> str:
    """Hạ chữ, bỏ mọi dấu tiếng Việt (kể cả đ→d). Không phụ thuộc thư viện."""
    t = unicodedata.normalize("NFKD", str(s or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.replace("đ", "d")


# pyvi nạp một lần, mềm: thiếu → None, mọi lời gọi segment() trả nguyên văn.
_seg = None
_seg_tried = False


def _segmenter():
    global _seg, _seg_tried
    if not _seg_tried:
        _seg_tried = True
        try:
            from pyvi import ViTokenizer  # type: ignore
            _seg = ViTokenizer.tokenize
        except Exception:
            _seg = None
    return _seg


def co_pyvi() -> bool:
    """pyvi có sẵn không (để log/chẩn đoán)."""
    return _segmenter() is not None


def segment(s: str) -> str:
    """Tách từ tiếng Việt nếu có pyvi; thiếu pyvi thì trả nguyên văn."""
    seg = _segmenter()
    if not seg:
        return str(s or "")
    try:
        return str(seg(str(s or "")))
    except Exception:
        return str(s or "")


def khoa_tim(s: str) -> str:
    """Chuỗi dùng để INDEX/QUERY: tách từ rồi bỏ dấu.

    An toàn khi thiếu pyvi (khi đó chỉ còn bỏ dấu — vẫn khớp được không dấu).
    """
    return fold(segment(s))

# Ghi chú: FTS của memory_service/state/session KHÔNG cần đổi — tokenizer mặc định
# `unicode61` của SQLite FTS5 đã fold thanh điệu + dấu nguyên âm (remove_diacritics
# mặc định = 1): "ket" khớp "két", "hoc sinh" khớp "học sinh". Điểm còn thiếu duy
# nhất của FTS là đ→d ("dong" không khớp "đông") — cả mode 1 lẫn 2 đều không làm.
# Muốn fold cả đ trong FTS phải index bản đã fold (đổi cấu trúc + dựng lại index),
# để dành. wiki dùng vi_text.fold nên đã fold đầy đủ (kể cả đ).
