[🇺🇸 English](README_ChatGPT2API.md) | [🇻🇳 Tiếng Việt](README_ChatGPT2API.vi.md)

**[🔙 Quay lại Trang Chủ (Main README)](README.vi.md)**

# 📖 Hướng Dẫn Sử Dụng & Đăng Nhập ChatGPT2API

Tài liệu này hướng dẫn chi tiết các cách thêm tài khoản ChatGPT vào hệ thống và cách làm chủ từng Tab trên giao diện quản trị (Dashboard) của Docker **ChatGPT2API**.

---

## 🔑 PHẦN 1: Các Cách Đăng Nhập / Thêm Tài Khoản ChatGPT

ChatGPT2API hỗ trợ nhiều cách để lấy và nạp tài khoản. Chọn cách phù hợp nhất với bạn.

### Cách 1: Nạp bằng Access Token (Dễ nhất - Khuyên dùng cho acc Free)
Được sử dụng chủ yếu cho tài khoản ChatGPT Free (hoặc Plus nếu bạn không lấy được Refresh Token). Token này sống khoảng 10-30 ngày tùy chính sách của OpenAI.

1. Mở trình duyệt ẩn danh (Incognito Window) để tránh ảnh hưởng đến phiên làm việc hiện tại.
2. Đăng nhập bình thường vào trang [https://chatgpt.com](https://chatgpt.com).
3. Sau khi vào được giao diện chat, mở tab mới và truy cập: `https://chatgpt.com/api/auth/session`
4. Màn hình sẽ hiện ra một đoạn mã. Hãy bôi đen toàn bộ chuỗi ký tự RẤT DÀI nằm sau chữ `"accessToken": "..."` (Chỉ copy phần ký tự bên trong dấu ngoặc kép, bắt đầu bằng `eyJ...`).
5. Vào ChatGPT2API Dashboard -> Tab **Account Pool** -> **Import Access Token**. Dán mã vừa copy vào (có thể dán nhiều dòng nếu có nhiều acc).
6. **⚠️ GHI CHÚ QUAN TRỌNG NHẤT**: Sau khi lấy xong Token, **KHÔNG ĐƯỢC BẤM NÚT LOG OUT (Đăng xuất)** trên trình duyệt. Chỉ cần đóng hẳn cửa sổ ẩn danh đó lại. Nếu bạn bấm Log Out, Token sẽ chết ngay lập tức!

### Cách 2: Nạp bằng Refresh Token (Dành cho Plus/Pro/Codex)
Được sử dụng khi bạn dùng tính năng OAuth (Codex) để lấy Refresh Token. Refresh Token có lợi thế là "Sống dai, bất tử", hệ thống sẽ tự động dùng nó để làm mới Access Token mỗi khi hết hạn.

1. Sau khi bạn có chuỗi Refresh Token (có thể lấy qua các tool trích xuất token của cộng đồng).
2. Vào ChatGPT2API Dashboard -> Tab **Account Pool** -> Chọn **Import via Credentials** (hoặc nếu dán vào ô Token bình thường, hệ thống sẽ tự nhận dạng nếu có cấu trúc Refresh Token).
3. **Ghi chú**: Refresh Token giúp tài khoản của bạn luôn giữ trạng thái Active mà không cần lấy lại mã thủ công. Thích hợp để làm Combo siêu bền (Fallback Chain).

### Cách 3: Nạp Tự Động Qua Captcha Solver (Đăng nhập Google)
Hệ thống đi kèm module `captcha-solver` cho phép tự động login bằng tài khoản Google để vượt Cloudflare.

1. Mở giao diện VNC của Captcha Solver tại cổng `http://[IP_MÁY_CHỦ]:6080` (Ví dụ).
2. Bạn sẽ thấy một trình duyệt giả lập. Nếu hệ thống tự động chạy quy trình, nó sẽ điều khiển chuột/bàn phím.
3. Cấu hình module sẽ tự động nạp kết quả `accessToken` vào thẳng database của ChatGPT2API thông qua mạng nội bộ Docker.

---

## 🎛️ PHẦN 2: Chi Tiết Cách Cài Đặt Từng Tab (ChatGPT2API)

Sau khi truy cập `http://[IP_MÁY_CHỦ]:3000` và nhập Auth Key, bạn sẽ thấy giao diện quản trị.

### 1. Tab Overview (Tổng Quan)
- Không cần cài đặt gì. Tab này dùng để "ngắm". 
- Hiển thị số Token bạn đã tiết kiệm được nhờ thuật toán RTK Optimizer, số lượng request đang chạy, và tỷ lệ thành công. Dùng để xem khi nào server bị nghẽn (Status 429).

### 2. Tab Account Pool (Kho Tài Khoản)
- Nơi bạn quản lý "hạm đội" tài khoản của mình.
- Bạn có thể **bật/tắt** từng tài khoản bằng công tắc bên cạnh.
- Hệ thống tự check "Health" của token. Nếu thấy nút báo màu đỏ (Error/Disabled), hãy xóa tài khoản đó đi và add lại bằng Token mới (Cách 1).

### 3. Tab Providers (Nhà Cung Cấp)
- Thêm sức mạnh ngoài ChatGPT. 
- Mặc định hệ thống hỗ trợ `gemini_free` (Gemini API Studio miễn phí), `deepseek`, `groq`.
- **Cách cài đặt**: 
  - Chọn Provider trong danh sách thả xuống.
  - Điền Base URL (nếu có) hoặc API Key tương ứng.
  - Nhấn Save. Lúc này bạn đã có thể dùng model của hãng đó (ví dụ `gemini_free/auto`).

### 4. Tab Combos (Định Tuyến Phân Luồng - QUAN TRỌNG NHẤT)
Tab này giúp hệ thống của bạn "Bất tử". Nó ghép các tài khoản ở trên lại thành 1 đội hình.
- Bấm **Create Combo**. Đặt tên Combo (ví dụ: `AI Agent`).
- **Fallback Chain**: Đây là thứ tự ưu tiên. Nếu cái số 1 xịt, nó tự động nhảy sang số 2 trong vòng nửa giây.
  - Dòng 1 (Xịn nhất): Điền `cx/auto` (Sẽ rút từ tài khoản Plus/Pro dùng Refresh Token).
  - Dòng 2 (Vừa tầm): Điền `chatgpt/auto` (Rút từ đống Acc Free nạp bằng Access Token).
  - Dòng 3 (Phòng thủ): Điền `gemini_free/auto` (Lấy từ Tab Providers).
  - Dòng 4 (Cấp cứu): Điền `oc/auto` (OpenCode API không cần token luôn).
- Lưu lại. Khi tích hợp vào Home Assistant, bạn chỉ cần gõ tên model là `AI Agent`, kệ cho hệ thống backend tự đổi số đằng sau.

### 5. Tab Models (Quản Lý Hiển Thị)
- Các ứng dụng như Open WebUI hay n8n có tính năng "Lấy danh sách Models". Tab này cho phép bạn ẩn bớt các model rác để danh sách trông gọn gàng hơn.
- Chỉ tick xanh vào các model bạn muốn sử dụng (VD: `chatgpt/auto`, `AI Agent`).

### 6. Tab MCP Servers (Công cụ mở rộng cho AI)
- AI không thể biết thời tiết hôm nay hay tin tức mới nếu không có MCP.
- **Cách cài đặt**:
  - MCP Hub đã chạy nội bộ sẵn trong container — không cần nhập URL.
  - Màn hình hiện sẵn các Preset như "Tìm Web", "Tin Tức", "Thời Tiết". Bấm cài đặt (Enable) tool bạn muốn.
  - Lưu ý: Cài càng nhiều, AI nghĩ càng lâu. Khuyên dùng 3-4 tool cơ bản. Mọi cài đặt RAG/KB/R2 nằm trong các tab con của Tab MCP.

### 7. Tab Backup / System (Sao Lưu)
- Nơi xuất (Export) toàn bộ Token và cấu hình ra file JSON để mang sang máy khác.
- Tuyệt đối giữ bí mật file Backup này vì nó chứa toàn bộ Token của bạn.
