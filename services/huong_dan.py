"""Hướng dẫn dùng — menu đánh số, do CODE dựng, không qua LLM.

Vì sao cần: bot trả lời "em làm được gì" bằng danh sách năng lực (xem
``capabilities.persona_list``), nhưng người dùng đọc xong vẫn không biết BẤM GÌ
để dùng. Danh sách năng lực trả lời "cái gì", còn đây trả lời "làm thế nào".

Vì sao do code dựng chứ không để model tự kể: model kể cách dùng thì mỗi lượt
một kiểu và rất dễ bịa ra lệnh không tồn tại — người dùng gõ theo, không thấy
gì xảy ra, rồi kết luận là bot hỏng. Bảng ở đây có test đối chiếu với mã nguồn
bot, lệnh nào không có thật thì test đỏ.

Menu này KHÔNG dùng chung sổ chờ với dich_cho: nó chỉ đọc, không giữ tệp, và
cổng đọc số của nó đặt SAU cổng của dich_cho — đang mở menu dịch mà nhắn "2"
thì đó là trả lời cho menu dịch, không phải chọn mục hướng dẫn.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

#: (tên chức năng, cách dùng). Thứ tự này là số thứ tự người dùng nhắn.
MUC: list[tuple[str, str]] = [
    ("Dịch chữ, tệp, video",
     "Nhắn «/dich» kèm câu cần dịch, ví dụ «/dich xin chào». Không nêu tiếng "
     "đích thì em hỏi lại bằng menu số.\n"
     "Gửi thẳng tệp video, tệp âm thanh hay tệp phụ đề .srt thì em hỏi ba "
     "bước: làm gì với tệp, tệp nói tiếng gì, dịch sang tiếng nào. Dịch dài "
     "thì em đóng thành tệp Word song ngữ cho dễ đối chiếu.\n"
     "Làm được cả năm tiếng: Việt, Anh, Nhật, Trung, Hàn."),
    ("Nghe tệp âm thanh thành chữ",
     "Nhắn «/stt» rồi gửi tệp âm thanh hoặc video. Em hỏi tệp nói tiếng gì, "
     "rồi trả bản chữ giữ nguyên tiếng gốc — ngắn thì nhắn thẳng, dài thì đóng "
     "tệp Word.\n"
     "Muốn có phụ đề .srt kèm mốc thời gian thì gửi tệp không kèm lệnh, rồi "
     "chọn ô phụ đề."),
    ("Đọc chữ thành giọng nói",
     "Nhắn «/tts» kèm đoạn cần đọc, ví dụ «/tts xin chào các bạn». Nhắn mỗi "
     "«/tts» thì em hỏi nội dung sau.\n"
     "Em hỏi đọc bằng tiếng nào. Chọn tiếng khác tiếng của đoạn chữ thì em "
     "dịch trước và gửi anh xem, duyệt xong mới đọc.\n"
     "Giọng đọc lấy theo Cài đặt ▸ Giọng nói & Loa."),
    ("Gửi tin nhắn thoại cho em",
     "Bấm giữ nút ghi âm rồi nói như nhắn tin thường. Em nghe ra chữ và xử lý "
     "y như anh gõ. Tiếng nghe đặt trong Cài đặt ▸ Giọng nói ▸ Theo từng tính "
     "năng ▸ Tin nhắn thoại."),
    ("Tài liệu PDF, Word, Excel",
     "Gửi thẳng tệp vào khung chat. Em hiện menu số: tóm tắt, nạp vào kho kiến "
     "thức để hỏi đáp sau, hay chuyển sang Word/Excel."),
    ("Ảnh",
     "Gửi ảnh kèm câu hỏi thì em trả lời thẳng. Gửi ảnh không kèm gì thì em "
     "hiện menu: đọc chữ trong ảnh, dịch chữ trong ảnh, hay tả ảnh."),
    ("Nhà thông minh",
     "Nói tự nhiên: «bật đèn phòng khách», «nhà đang thế nào». Muốn phát ra "
     "loa thì nói rõ loa nào, ví dụ «phát ra loa phòng khách nhắc cả nhà ăn "
     "cơm»."),
    ("Lịch và lời nhắc",
     "Nói «nhắc tôi 7 giờ sáng mai uống thuốc». Em tự đặt lịch và nhắc đúng "
     "giờ, không cần cú pháp gì đặc biệt."),
    ("Đổi nhân vật của em",
     "Nhắn «persona» để chọn: có sẵn vài nhân vật mẫu, hoặc tự xây từng bước "
     "theo vùng miền, giới tính, độ tuổi, nghề, tông giọng. Nhắn «tắt persona» "
     "để trở lại bình thường."),
    ("Đăng bài Facebook",
     "Nhắn «/facebook» để mở menu đăng bài lên Page."),
]

#: Câu người dùng hay dùng để xin hướng dẫn.
_HOI_RE = re.compile(
    r"^\s*/?(huong\s*dan|hướng\s*dẫn|help|trợ\s*giúp|tro\s*giup)\b"
    r"|^\s*(cách|cach)\s+(dùng|dung|sử dụng|su dung)\b"
    r"|^\s*(dùng|dung)\s+(thế nào|the nao|sao|kiểu gì|kieu gi)\b",
    re.IGNORECASE)

_TTL = 10 * 60
_cho: dict[str, float] = {}
_lock = threading.Lock()


def la_xin_huong_dan(text: str) -> bool:
    return bool(_HOI_RE.search(str(text or "")))


def menu() -> str:
    dong = "\n".join(f"{i}. {ten}" for i, (ten, _) in enumerate(MUC, 1))
    return ("📖 Em hướng dẫn dùng chức năng nào ạ? Nhắn số:\n" + dong +
            "\nNhắn «thôi» để bỏ.")


def mo(key: str) -> str:
    """Mở menu hướng dẫn cho một phiên."""
    with _lock:
        now = time.time()
        for k in [k for k, t in _cho.items() if now - t > _TTL]:
            _cho.pop(k, None)
        _cho[str(key)] = now
    return menu()


def dang_mo(key: str) -> bool:
    with _lock:
        t = _cho.get(str(key))
        return bool(t and time.time() - t <= _TTL)


def dong(key: str) -> None:
    with _lock:
        _cho.pop(str(key), None)


def chon(key: str, text: str) -> dict[str, Any] | None:
    """Người dùng nhắn số → phần hướng dẫn của mục đó.

    ``None`` khi câu này không phải trả lời menu (để bot xử lý như thường).
    """
    if not dang_mo(key):
        return None
    t = str(text or "").strip().lower()
    if t in ("thôi", "thoi", "bỏ", "bo", "huỷ", "hủy", "huy"):
        dong(key)
        return {"bo": True}
    if not t.isdigit():
        return None
    i = int(t)
    if not 1 <= i <= len(MUC):
        return None
    dong(key)
    ten, cach = MUC[i - 1]
    return {"text": f"📖 {ten}\n{cach}"}
