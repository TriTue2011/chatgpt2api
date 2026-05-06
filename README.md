# Hướng Dẫn Cài Đặt & Sử Dụng ChatGPT2API Cho Home Assistant

ChatGPT2API là dự án cho phép biến tài khoản ChatGPT Web của bạn thành một API chuẩn OpenAI. Phiên bản này đã được tùy chỉnh đặc biệt để lọc sạch các ký tự định dạng (Markdown, dấu gạch ngang, tiêu đề...) nhằm tương thích hoàn hảo 100% với hệ thống giọng nói (Text-To-Speech) của loa thông minh như Phicomm R1 qua Home Assistant.

---

## 1. Cài Đặt Hệ Thống (Bằng Docker)

Yêu cầu máy chủ (Ubuntu/Debian, Raspberry Pi, Debian trên Home Assistant...) đã cài đặt sẵn `docker` và `docker-compose`.

```bash
# Clone source code
git clone https://github.com/TriTue2011/chatgpt2api.git
cd chatgpt2api

# Khởi chạy hệ thống (tự động build)
docker-compose up -d --build
```

Sau khi chạy xong, hệ thống sẽ mở 2 cổng:
- Web Quản lý: `http://[IP_MÁY_CHỦ]:3000`
- API Endpoint: `http://[IP_MÁY_CHỦ]:3000/v1`

---

## 2. Cách Lấy Access Token / Session Của ChatGPT

Để hệ thống hoạt động, bạn cần cấp cho nó tài khoản ChatGPT. Cách an toàn và đơn giản nhất là lấy `access_token` từ trình duyệt:

1. Mở trình duyệt ẩn danh (Incognito) và đăng nhập vào trang [chatgpt.com](https://chatgpt.com).
2. Sau khi đăng nhập thành công, mở tab mới và dán đường link này vào thanh địa chỉ:
   `https://chatgpt.com/api/auth/session`
3. Trình duyệt sẽ hiển thị một đoạn mã JSON. Bạn tìm chuỗi bắt đầu bằng `eyJhbG...` nằm sau chữ `"accessToken":`.
4. Copy toàn bộ chuỗi Access Token đó (nó rất dài).

*Lưu ý: Không đăng xuất (Log out) ChatGPT trên trình duyệt đó, nếu không token sẽ bị hủy.*

---

## 3. Cách Gán Tài Khoản Vào ChatGPT2API

1. Truy cập vào Web UI quản lý của hệ thống: `http://[IP_MÁY_CHỦ]:3000`
2. Đăng nhập bằng Auth Key. Mặc định trong file `config.json` là: `chatgpt2api` (bạn có thể đổi tùy ý).
3. Tại giao diện chính, chuyển sang tab **Tài khoản (Account Pool)**.
4. Bấm vào nút **Nhập Access Token (Import Access Token)**.
5. Dán đoạn Access Token bạn vừa copy ở Bước 2 vào ô trống, mỗi token nằm trên 1 dòng nếu bạn có nhiều tài khoản.
6. Bấm **Xác nhận (Confirm)**. Hệ thống sẽ tự động kiểm tra xem tài khoản là Plus hay Thường, và đưa vào trạng thái Hoạt động (Active).

---

## 4. Tích Hợp Vào Home Assistant

Để sử dụng ChatGPT2API làm não bộ cho trợ lý ảo của Home Assistant, bạn cần cấu hình tích hợp **OpenAI Conversation** (Hoặc các bản mod tương tự như Local OpenAI).

1. Vào Home Assistant -> **Cài đặt (Settings)** -> **Thiết bị & Dịch vụ (Devices & Services)**.
2. Thêm tích hợp **OpenAI Conversation**.
3. Điền các thông số sau:
   - **API Key**: `chatgpt2api` (Phải khớp với `auth-key` trong config.json)
   - **Base URL**: `http://[IP_MÁY_CHỦ_CỦA_BẠN]:3000/v1`
4. Bấm Xác nhận. 
5. Sau khi thêm xong, cấu hình Integration và chọn mô hình (Model) là `auto` hoặc `gpt-4o`.

---

## 5. Tối Ưu Hóa Cho Loa Thông Minh (TTS)

Tuy bản thân ChatGPT2API đã tự động lọc sạch các mã Markdown (dấu `#`, `*`, `- `) khi trả về, nhưng để câu văn tự nhiên nhất khi phát qua loa, bạn cần thêm System Prompt vào Home Assistant.

Vào **Cài đặt -> Trợ lý giọng nói -> Chọn Trợ lý của bạn -> Phần Chỉ thị (Instructions)**, dán đoạn sau:

> *"Bạn là trợ lý ảo nhà thông minh. Hãy trả lời cực kỳ ngắn gọn, tự nhiên và giống văn nói của con người để hệ thống TTS có thể đọc mượt mà. Tuyệt đối KHÔNG sử dụng các ký tự định dạng (như dấu sao *, dấu thăng #, gạch đầu dòng -). Không dùng danh sách liệt kê, hạn chế tối đa ngoặc đơn. Trả lời thẳng vào trọng tâm câu hỏi. QUAN TRỌNG: Ngay cả khi lấy dữ liệu từ Web Search, tuyệt đối không được dùng định dạng liệt kê."*

---

## 6. Cập Nhật Code (Khi có bản sửa lỗi mới)

Nếu có bản cập nhật mới trên Github, bạn chỉ cần thực hiện 3 lệnh sau để nâng cấp:

```bash
cd /opt/chatgpt2api
docker-compose down
git pull origin main
docker-compose up -d --build
```
