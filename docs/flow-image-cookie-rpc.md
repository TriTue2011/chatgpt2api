# Sửa tạo ảnh Flow — 07/09/2026

Flow đã chuyển từ `labs.google/fx/tools/flow` sang `flow.google.com`.
Endpoint `labs.google/fx/api/auth/session` có thể trả `access_token` đã hết hạn
kèm `ACCESS_TOKEN_REFRESH_NEEDED`. Gọi JavaScript trong trang cũ còn bị huỷ khi
trang chuyển hướng. Chỉ làm mới cache OAuth không giải quyết được việc chuyển ứng dụng.

`flow_rest.tao_anh` giữ nguyên chữ ký và hợp đồng của endpoint solver
`/v1/google/flow/rest/generate-image`, nhưng gọi `flow_rpc.generate_image`.
Module mới mở đúng dự án, chờ reCAPTCHA runtime và CSRF của ứng dụng, rồi gọi
RPC từ cùng trang bằng cookie. Video và các hàm REST cũ giữ nguyên.

Hợp đồng được đối chiếu với request tạo ảnh thành công trong giao diện thật và
JavaScript chính thức của Google (`wO1vlb`):

- `ogiZ0b`: `FlowService.BatchGenerateImages`.
- `maseQ`: `FlowService.UploadImage`; lấy token `UPLOAD_IMAGE` cho từng ảnh.
- Lấy token `IMAGE_GENERATION` sau khi upload xong, giữ cùng khóa browser profile.
- Tỷ lệ protobuf: 16:9 = 3, 4:3 = 5, 1:1 = 1, 3:4 = 4, 9:16 = 2.
- Đọc media ID và URL trực tiếp từ kết quả RPC; không gọi OAuth/media redirect cũ.
- Giải mã cả lỗi RPC nằm trong HTTP 200, giữ 400/401/403/429 cho bộ xoay tài khoản.

## Kiểm chứng trên máy chủ 172.16.10.38

- Tạo ảnh Pro dọc: JPEG 768×1376, khoảng 32 giây.
- Upload ảnh đó và chỉnh nền: JPEG 1024×1024, khoảng 46 giây.
- Gọi thật `/v1/images/generations`, model `flow/banana-pro`, `n=1`,
  `size=1792x1024`, `response_format=b64_json`: HTTP 200 sau 32,3 giây;
  giải mã được JPEG 1376×768, 95.028 byte. Flow trả kích thước theo tỷ lệ model.
- Hồ sơ được kiểm chứng: `google-mitbap0610`. Không suy ra các hồ sơ Google
  khác đã đăng nhập lại từ kết quả này.

Kiểm thử hồi quy:

```sh
.venv/bin/python -m pytest test/test_flow_*.py -o addopts='' -q --tb=short
```

Test chính chặn mọi lần gọi OAuth cũ khi tạo ảnh. Đã xác nhận test thất bại
với `tao_anh` cũ, rồi qua với bản sửa. Các test còn lại kiểm tra giao thức,
runtime readiness, chuyển hướng đăng nhập, upload, tỷ lệ và xử lý lỗi.

## Triển khai

Đã cập nhật `flow_rest.py` và thêm `flow_rpc.py` trong `/app/captcha/src/solvers/`
của container `c2a`, khởi động lại riêng `captcha-api`. Bản sao để khôi phục và
bản sửa được giữ ở `/app/data/patch-backups/flow-20260906/`.

Đây là bản vá container đang chạy. Mã nguồn Dockerfile đã COPY toàn bộ
`captcha-solver/src`, nên lần build từ mã nguồn đã sửa sẽ có module mới.
Cần build/phát hành image từ mã nguồn này trước khi recreate hoặc re-pull
image cũ trong Portainer; thay đổi trong container không tự cập nhật image registry.
