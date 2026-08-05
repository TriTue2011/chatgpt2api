"""Nhận ra câu nói là YÊU CẦU MỚI chứ không phải trả lời cho việc đang chờ.

Bot có nhiều trạng thái chờ: chờ chọn 1–4 cho ảnh, chờ mô tả để tạo ảnh, chờ lớp
và môn cho RAG teacher, chờ chọn số trong menu tài liệu. Trước đây câu nào rơi
vào lúc đang chờ cũng bị coi là câu trả lời, dẫn tới ba kiểu hỏng đo được 05/08:

* Đang chờ mô tả ảnh mà nói "gửi file cho nhóm A" → câu đó bị lấy làm mô tả ảnh.
* Đang chờ lớp và môn mà nói việc khác → bot hỏi lại đúng câu cũ rồi dừng, khoá
  chặt 10 phút, không yêu cầu nào khác đi qua được.
* Bản chờ không được đóng nên còn treo tới hết hạn, lát sau gõ "1" cho việc khác
  là bị bản chờ cũ ăn mất.

Quy tắc chủ máy chốt 05/08: câu nào **kích hoạt được một năng lực khác** của bot
thì coi là yêu cầu mới — đóng bản chờ cũ rồi chạy việc mới. Câu không kích hoạt
gì thì vẫn hiểu là đang trả lời cho việc đang chờ.

CỐ Ý NHẬN DIỆN HẸP. Nhận nhầm một câu trả lời thành yêu cầu mới thì người dùng
mất bản chờ và phải gửi lại tệp — khó chịu hơn hẳn so với bỏ sót. Nên chỉ nhận
khi câu nói có động từ ra lệnh rõ ràng, và luôn bỏ qua các câu NGẮN vì trả lời
cho việc đang chờ gần như luôn ngắn ("1", "phân tích", "lớp 4 toán").
"""
from __future__ import annotations

import re

#: Câu trả lời cho việc đang chờ gần như luôn ngắn. Dưới ngưỡng này thì không
#: xét là yêu cầu mới, dù có trúng từ khoá — "gửi" một mình không phải mệnh lệnh.
_TOI_THIEU_TU = 3

#: Động từ ra lệnh của các năng lực khác. Mỗi cụm phải đủ đặc trưng để không
#: đụng vào lời trả lời thông thường.
_MENH_LENH = re.compile(
    r"\b("
    r"gửi\s+(file|tệp|tài\s*liệu|ảnh|tin|tin\s*nhắn)|"
    r"tải\s+(lên|về|file|tệp)|"
    r"lưu\s+(lên|vào)\s+(kho|drive|đám\s*mây)|"
    r"(bật|tắt|mở|đóng)\s+(đèn|quạt|điều\s*hoà|máy|cửa|tivi|tv)|"
    r"mấy\s+giờ|giờ\s+rồi|"
    r"nhắc\s+(tôi|em|anh|chị|lúc|vào)|"
    r"đặt\s+(lịch|báo\s*thức|hẹn)|"
    r"tìm\s+(kiếm|giúp|trên\s*mạng)|"
    r"tra\s+cứu|"
    r"thời\s+tiết|"
    r"dịch\s+(sang|giúp)|"
    r"tóm\s+tắt\s+(bài|trang|link|web)"
    r")\b",
    re.IGNORECASE,
)


def la_yeu_cau_moi(text: str) -> bool:
    """True nếu câu nói là một yêu cầu MỚI, không phải trả lời việc đang chờ."""
    s = str(text or "").strip()
    if not s:
        return False
    if len(s.split()) < _TOI_THIEU_TU:
        return False
    # Câu mở đầu bằng một con số gần như luôn là chọn mục trong menu.
    if re.match(r"^\s*[1-9]\b", s):
        return False
    return bool(_MENH_LENH.search(s))
