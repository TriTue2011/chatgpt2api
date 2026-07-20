# Zalo Server (nhúng) — attribution

Thư mục `zalo-server/` là server Node.js điều khiển tài khoản Zalo cá nhân qua thư
viện [`zca-js`](https://github.com/RFS-ADRENO/zca-js) (đăng nhập QR như Zalo Web,
đa tài khoản, webhook theo tài khoản, REST API `/api/*ByAccount`).

Mã nguồn bắt nguồn từ dự án MIT của cộng đồng:
- [smarthomeblack/zalo_bot addon](https://github.com/smarthomeblack/hass-addon) (MIT)
- tham khảo [ChickenAI/multizlogin](https://github.com/ChickenAI/multizlogin) (MIT)
- thư viện [RFS-ADRENO/zca-js](https://github.com/RFS-ADRENO/zca-js)

Ở đây được **nhúng thẳng vào image chatgpt2api** (chạy nội bộ `127.0.0.1:3001` qua
supervisord) thay vì pull image `ghcr.io/smarthomeblack/zalobot-*` — để toàn bộ hệ
thống là một artifact tự chủ, không phụ thuộc image bên thứ ba khi deploy.

Kênh Python tương ứng: `services/zalo_personal.py` + `api/zalo_personal.py`, trang
quản lý web `/zalo`. Home Assistant có thể cài custom integration
[smarthomeblack/zalo_bot](https://github.com/smarthomeblack/zalo_bot) (HACS) trỏ
thẳng vào cổng `3001` của server này để gửi tin/thông báo độc lập.

**Cảnh báo**: đây là tích hợp KHÔNG chính thức với Zalo, tài khoản cá nhân có thể
bị hạn chế/khóa. Người dùng tự chịu rủi ro.
