"""Tag bot xong thì bot CHỜ người đó gửi tiếp — áp cho mọi kênh.

Chủ máy chốt 06/08: "khi user tag tên bot mà không có yêu cầu cụ thể thì cần chờ
đợi user gửi thông tin gì rồi mới phản hồi; gửi ảnh thì đưa ra các lựa chọn, gửi
file đưa ra các lựa chọn. Việc chờ phản hồi thực hiện trên TOÀN CỤC khi có việc
tag tên bot".

Vì sao cần: trong nhóm, bot chỉ nghe khi được tag. Nhưng Zalo (và Telegram trên
điện thoại) KHÔNG cho vừa tag vừa đính ảnh/tệp trong một tin — người ta buộc phải
tag trước, gửi ảnh sau. Cổng tag loại tin thứ hai, nên tấm ảnh không bao giờ tới
được phần xử lý. Đo thật trên máy chủ 06/08 lúc 11:43–11:45 (nhóm Homeassistant):

    11:43:32  Nguyễn Việt: @BenBap
    11:43:49  Nguyễn Việt: [Hình ảnh]        ← không tag → bị loại IM LẶNG
    11:45:04  Nguyễn Việt: @BenBap mô tả ảnh
    11:45:09  Botmitbap:   Dạ em đây ạ 😊 …  ← không còn ảnh nào để xem

Loại im lặng vì dòng log báo điều đó ở mức INFO, còn logger của
`services.zalo_personal` chạy ở mức WARNING (đo: `getEffectiveLevel()` = 30).

Cách chữa: **tag bot là mở một cửa sổ chờ cho ĐÚNG người đó**. Trong cửa sổ đó,
tin tiếp theo của họ đi qua cổng tag mà không cần tag lại — ảnh ra menu lựa chọn,
tệp ra menu lựa chọn, chữ thì là yêu cầu.

Ba ràng buộc, đừng gỡ khi sửa về sau:

1. **Theo TỪNG NGƯỜI, không theo thread.** Chủ máy chốt 05/08: "chờ là chờ theo
   từng người chứ không phải chờ xong có người xen vào thành câu phản hồi được".
   A tag bot rồi B nói chuyện trong nhóm thì câu của B không được đi ké.
2. **Có hạn.** Hết hạn thì nhóm trở lại nếp "phải tag mới nghe". Không có hạn là
   một lần tag mở cổng vĩnh viễn — coi như tắt hẳn yêu cầu tag của nhóm đó.
3. **Không thay bản chờ nào đang có.** Đây chỉ là cái CỔNG. Việc "đang chờ ảnh",
   "đang chờ chọn 1/2/3" vẫn do `photo_intent` / `pdf_intent` / `luu_tru_day` giữ,
   và luật "yêu cầu mới thì đóng yêu cầu cũ" (`yeu_cau_moi`) vẫn nguyên.
"""
from __future__ import annotations

import threading
import time

#: 5 phút. Đủ để tìm ảnh trong máy rồi gửi, ngắn để nhóm sớm trở lại nếp cũ.
TTL_S = 300.0

_cho: dict[str, float] = {}
_khoa = threading.RLock()


def mo(khoa: str) -> None:
    """Người này vừa tag bot → mở (hoặc gia hạn) cửa sổ chờ của họ."""
    if not khoa:
        return
    with _khoa:
        _don_het_han()
        _cho[str(khoa)] = time.time()


def dang_cho(khoa: str) -> bool:
    """Người này có đang trong cửa sổ chờ không?"""
    if not khoa:
        return False
    with _khoa:
        t = _cho.get(str(khoa))
        if not t:
            return False
        if time.time() - t > TTL_S:
            _cho.pop(str(khoa), None)
            return False
        return True


def dong(khoa: str) -> None:
    """Đóng cửa sổ chờ của một người."""
    with _khoa:
        _cho.pop(str(khoa), None)


def _don_het_han() -> None:
    nay = time.time()
    for k in [k for k, t in _cho.items() if nay - t > TTL_S]:
        _cho.pop(k, None)


def _reset_for_tests() -> None:
    with _khoa:
        _cho.clear()
