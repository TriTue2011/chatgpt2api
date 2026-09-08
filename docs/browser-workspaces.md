# Workspace trình duyệt và giữ phiên ít tốn tài nguyên

## Cách dùng

Trong **Cài đặt → Workspace trình duyệt**:

1. Tạo workspace cho mỗi tài khoản Google. Tên hiển thị có thể trùng, thư mục hồ sơ luôn có ID riêng.
2. Chọn Google → Mở workspace → đăng nhập qua noVNC.
3. Chọn ChatGPT, Claude, Flow hoặc Gemini → Mở **cùng workspace** → dùng “Tiếp tục với Google” nếu dịch vụ chưa có phiên. Phiên Google không thay thế phiên của từng dịch vụ.
4. Bấm **Đóng · giữ phiên** khi xong. Cookie bền vững và dữ liệu trang vẫn ở hồ sơ trên đĩa. Workspace khác không bị đóng hay đăng xuất.
5. Muốn đưa tài khoản vào API pool, dùng mục **Provider qua tài khoản Google → Tái dùng** bên dưới, chọn đúng ID workspace đã đóng. Có thể tái dùng lần lượt cho tất cả dịch vụ. Chỉ mở trang trong workspace chưa tự thêm tài khoản vào API pool.

Hồ sơ cũ vẫn dùng đúng thư mục cũ. Hồ sơ mới có ID ngẫu nhiên `workspace-…`, không suy ra từ phần trước `@` của email. Tài khoản khác dùng workspace khác; đăng xuất hoặc đổi tài khoản bên trong cùng một workspace vẫn có thể thay phiên của workspace đó.

Workspace đang mở thủ công được bảo vệ khỏi dọn idle, đổi sang headless và đăng nhập lại nền. Tác vụ tự động trên hồ sơ đó nhận trạng thái bận; đóng workspace để cho phép chạy. noVNC là màn hình chung của máy chủ: chọn Mở đưa cửa sổ tương ứng lên trước, cookie vẫn tách theo hồ sơ.

Nút **Thử bấm ô reCAPTCHA** chỉ click một lần vào checkbox hiển thị của iframe Google/reCAPTCHA hợp lệ. Không sửa DOM để giả trạng thái đã xác minh. Nếu xuất hiện thử thách tiếp theo, người dùng hoàn thành trên noVNC.

## Vòng đời theo dịch vụ

| Dịch vụ | Giữ/tái dùng phiên | Trình duyệt |
| --- | --- | --- |
| Google | Cookie trong hồ sơ riêng trên volume bền vững | Mở khi đăng nhập/xác minh; đóng khi người dùng xong |
| Gemini HTTP (`gma/`) | Client HTTP xoay cookie mỗi 600 giây, cache cookie trên đĩa như cơ chế có sẵn | Đọc seed khi cần, đóng ngay context tạm; không mở lại mỗi lần TTL seed hết nếu client HTTP còn chạy |
| ChatGPT | Dùng JWT hiện có và lịch kiểm tra JWT của dự án | Mở ngắn để lấy lại JWT khi cần, đóng sau bước kiểm tra; hồ sơ bận không bị coi là hết phiên |
| Claude | Dùng `sessionKey`; sau restart đọc cookie lưu trên đĩa trước khi đăng nhập lại | Context đọc cookie tạm đóng ngay; lưu key trong RAM để các lần đọc tiếp theo không mở Chrome; bận/lỗi solver tạm thời không kích hoạt đăng nhập lại |
| Flow | Tái dùng hồ sơ Google và lịch kiểm tra project hiện có | Các thao tác cần trang Flow vẫn dùng trình duyệt; kiểm tra project xong đóng ngay |

`web_prewarmer` chỉ khởi tạo client Gemini HTTP; bỏ các request làm nóng trang không có tác dụng. Khi loại client lỗi, đóng cả client HTTP và task refresh cũ trước khi tạo lại, theo khóa riêng từng client. Không giữ Chrome chạy chỉ để “hâm nóng” mọi tài khoản.

Các context tự động còn sót vẫn có dọn idle 5 phút. Cửa sổ thủ công chỉ đóng khi người dùng yêu cầu hoặc dịch vụ tắt. Chưa đặt giới hạn tổng số cửa sổ thủ công: mở nhiều workspace đồng thời vẫn dùng nhiều RAM; chỉ mở workspace cần dùng.

Lưu volume `CAPTCHA_SOLVER_DATA_DIR/profiles` và thư mục cookie Gemini (`DATA_DIR/gemini_cookies`) qua lần triển khai/restart. Không xóa hồ sơ nếu muốn giữ đăng nhập. Nhà cung cấp vẫn có thể hết hạn/thu hồi phiên hoặc yêu cầu 2FA/CAPTCHA; việc xoay cookie Gemini không gia hạn được phiên ChatGPT/Claude/Flow.

## Tham khảo đã kiểm tra

Gemini-FastAPI, commit `66dc3f71a40a283e17539d0c47058a04ad26b179`:

- [config/config.yaml](https://github.com/luuquangvu/Gemini-FastAPI/blob/66dc3f71a40a283e17539d0c47058a04ad26b179/config/config.yaml): `auto_refresh: true`, `refresh_interval: 600`, `auto_close: false` là cấu hình **client HTTP**.
- [app/services/client.py](https://github.com/luuquangvu/Gemini-FastAPI/blob/66dc3f71a40a283e17539d0c47058a04ad26b179/app/services/client.py) và [pool.py](https://github.com/luuquangvu/Gemini-FastAPI/blob/66dc3f71a40a283e17539d0c47058a04ad26b179/app/services/pool.py): client riêng, khởi tạo lệch thời điểm, khóa khởi động lại và đóng client.

Áp dụng nguyên tắc HTTP + cache + nhả tài nguyên cho dự án này, không chạy Chrome liên tục để bắt chước hoạt động người dùng.

## Kiểm chứng

- Kiểm thử khóa/cách ly workspace, cookie reader, khôi phục Claude từ cookie, giải phóng HTTP client, luồng bận ChatGPT/Claude, dọn Flow, quyền admin qua cookie/Bearer và thao tác checkbox.
- Chrome thật với hồ sơ tạm: tạo A/B qua giao diện, lưu cookie bền vững + localStorage khác nhau, đóng B không ảnh hưởng A, mở lại B giữ dữ liệu, đọc cookie lạnh không để lại context. Các nút chọn đủ năm dịch vụ; desktop/mobile không lỗi JavaScript hoặc tràn ngang.
- `npm run build` thành công. Chưa đăng nhập tài khoản thật tại Google/ChatGPT/Claude/Flow trong kiểm chứng này; chưa đo mức giảm CPU/RAM trên máy chủ thực tế và chưa triển khai.
- Kết quả 08/09/2026: 99 kiểm thử liên quan và 12 subtest qua; lượt toàn bộ suite ghi nhận 5.379 qua, 83 bỏ qua, 564 subtest qua và 17 lỗi HTTP tích hợp do không có API tại `localhost:8000`. Kiểm thử khóa bổ sung sau lượt toàn bộ đã chạy lại trong nhóm 99 kiểm thử.
