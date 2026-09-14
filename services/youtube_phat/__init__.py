"""Trình phát YouTube / Zing MP3 / audio HTTP ra loa — nằm ngay trong c2a.

Chủ máy 14/09/2026: "đang phụ thuộc addon, tích hợp trực tiếp trên dự án, và
ha có thể kết nối đến, có thể ra lệnh trên ha mở nhạc ở thiết bị trên ha".

c2a đóng vai add-on TriTue YouTube Player (github.com/TriTue2011/youtube): trả
đúng Integration API v1 dưới tiền tố `/yt` (`api/youtube_phat.py`), nên tích hợp
HA của repo chỉ cần đổi URL sang `http://<c2a>:3030/yt` và dán token c2a sinh.
Không chuyển trang web player của add-on (chủ máy chọn chỉ phát ra loa/tivi).

- `search.py`, `streaming.py`, `session.py`: chuyển nguyên từ add-on.
- `dich_vu.py`: phần lõi của máy chủ add-on, bỏ lớp HTTP.
"""
