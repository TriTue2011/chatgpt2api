[🇺🇸 English](README.md) | [🇻🇳 Tiếng Việt](README.vi.md)

# 🚀 ChatGPT2API - Ultimate AI Gateway & VN MCP Hub

**📚 Các tài liệu hướng dẫn (Click để xem chi tiết):**
- **[📘 Hướng dẫn CHI TIẾT từng tab, từng ô cài đặt — đọc trước nếu mới cài lần đầu](HUONG_DAN.md)**
- **[📖 Hướng Dẫn Sử Dụng & Đăng Nhập ChatGPT2API](README_ChatGPT2API.vi.md)**
- **[🧠 Hướng Dẫn Dạy AI & Cấu Hình VN MCP Hub](README_VN_MCP_HUB.vi.md)**

**ChatGPT2API** là dự án toàn diện cho phép biến tài khoản ChatGPT Web của bạn thành một API chuẩn OpenAI, đồng thời đóng vai trò là một **AI Agent Backend** mạnh mẽ. Phiên bản này được thiết kế tối ưu hóa đặc biệt cho các hệ thống nhà thông minh như **Home Assistant** (đặc biệt là lọc sạch định dạng để Loa thông minh TTS có thể đọc tự nhiên 100%), cũng như hoàn hảo cho **Open WebUI**, **n8n** và bất kỳ ứng dụng nào hỗ trợ chuẩn OpenAI API.

Kèm theo đó là **VN MCP Hub (Model Context Protocol Hub)** - Cung cấp hơn 20+ custom MCP servers giúp mở rộng bộ não AI của bạn với khả năng tìm kiếm web (Search), cập nhật thời tiết, tin tức, tài chính, luật pháp và hệ thống RAG (Knowledge Base).

Dự án còn đi kèm **Captcha Solver** giúp giải quyết các rào cản từ Cloudflare và bảo vệ đăng nhập tự động.

---

## 🌟 Tính Năng Nổi Bật

### 🧠 Core ChatGPT2API
- **10+ AI Provider**: Hỗ trợ ChatGPT Web (Free/Plus), Codex OAuth, OpenCode (Free không cần tài khoản), Gemini (Free AI Studio), DeepSeek, Groq, Mistral, NVIDIA NIM, v.v.
- **Model Combo Orchestration**: Cơ chế tự động chuyển đổi (fallback) thông minh. Nếu API A lỗi, tự động chuyển sang API B mà không làm gián đoạn trải nghiệm người dùng.
- **Tối ưu hóa Loa Thông Minh (TTS)**: Bộ lọc RTK thông minh tự động loại bỏ các định dạng Markdown (`#`, `*`, `-`) giúp giọng nói mượt mà, tự nhiên.
- **Web Dashboard**: Giao diện quản lý trực quan cho phép thêm tài khoản, cấu hình model, theo dõi token và backup dễ dàng.
- **RTK Token Optimizer**: Thuật toán tiết kiệm 60-90% lượng token tiêu thụ mà vẫn giữ nguyên chất lượng câu trả lời.

### 🔌 VN MCP Hub
- **7 MCP VN Core**: Tích hợp sẵn Thời tiết (4 nguồn), Tin tức (6 nguồn), Tỷ giá/Vàng, Lịch Âm, Tìm kiếm DuckDuckGo, Tra cứu Luật, Chứng khoán.
- **7 Knowledge Base RAG**: Dữ liệu điện nước, y tế sơ cứu, giáo dục, ngoại ngữ, khoa học, tự nhiên và xã hội Việt Nam.
- **Federated Multi-Search**: 9 Search engines quốc tế chạy song song (Brave, Mojeek, PubMed, v.v.).
- **Studio UI**: Quản lý trực quan, tạo KB (Knowledge Base) mới từ Markdown, lưu trữ R2 Cloudflare.

### 🛡️ Captcha Solver
- **Vượt Cloudflare/Turnstile**: Tự động xử lý Captcha bảo vệ của ChatGPT.
- **Quản lý VNC/API**: Hỗ trợ debug giao diện trực quan qua cổng 6080.

---

## 💻 Yêu Cầu Hệ Thống

| Thành Phần | Tối Thiểu | Khuyến Nghị |
| :--- | :--- | :--- |
| **Hệ Điều Hành** | Linux (Ubuntu/Debian), Raspberry Pi OS, Synology/QNAP | Linux (Ubuntu/Debian) |
| **RAM** | 2GB | 4GB+ (image all-in-one có cả trình duyệt) |
| **Disk** | 5GB | 20GB+ (Dành cho lưu trữ RAG và Cache) |
| **Phần Mềm** | Docker & Docker Compose | Phiên bản Docker mới nhất (24.0+) |

---

## 🚀 Hướng Dẫn Cài Đặt Chi Tiết Từng Bước

Dưới đây là hướng dẫn cài đặt từ cơ bản đến chuyên sâu. Toàn bộ hệ thống nay gói gọn trong **1 Docker Container all-in-one** (`c2a`) — đã tích hợp sẵn API gateway, VN MCP Hub và Captcha Solver.

### Chuẩn Bị Môi Trường
Trước khi bắt đầu, máy chủ của bạn cần được cài đặt sẵn Docker và Docker Compose.
- **Cài đặt Docker trên Linux (Ubuntu/Debian):**
  ```bash
  curl -fsSL https://get.docker.com -o get-docker.sh
  sudo sh get-docker.sh
  ```

### Cách 1: Cài Đặt Bằng Docker Compose (Khuyên dùng)

Từ phiên bản này, **ChatGPT2API + VN MCP Hub + Captcha Solver đã được gộp vào MỘT image / MỘT container duy nhất** (`c2a`). Bên trong, `supervisord` chạy đồng thời: API gateway (cổng 80), MCP Hub (nội bộ 8005), Captcha Solver (nội bộ 8010) và trình duyệt noVNC (cổng 6080) để đăng nhập web thủ công. Không còn các docker riêng lẻ cho các thành phần này.

**Bước 1: Khởi tạo thư mục**
Tạo thư mục chứa cấu hình và dữ liệu cho ứng dụng:
```bash
mkdir -p /opt/chatgpt2api
cd /opt/chatgpt2api
```

**Bước 2: Tạo file cấu hình docker-compose.yml**
Sử dụng trình soạn thảo `nano` để tạo file:
```bash
nano docker-compose.yml
```
Dán đoạn mã sau vào file:
```yaml
services:
  # All-in-one: API gateway + VN MCP Hub + Captcha Solver trong 1 container
  c2a:
    image: ghcr.io/tritue2011/chatgpt2api:latest
    container_name: c2a
    restart: unless-stopped
    ports:
      - "3030:80"     # API + giao diện web
      - "6080:6080"   # noVNC — đăng nhập web thủ công (captcha-solver)
      - "10600:10600" # Wyoming Protocol server nhúng (TTS+STT cho Home Assistant)
    volumes:
      # 1 thư mục dữ liệu duy nhất: accounts, config, KB + chroma, profile trình duyệt
      - ./c2a-data:/app/data
    environment:
      - CHATGPT2API_AUTH_KEY=mat_khau_cua_ban   # ĐỔI MẬT KHẨU NÀY
      - CAPTCHA_SOLVER_API_KEY=mat_khau_cua_ban # ĐỔI MẬT KHẨU NÀY
      - STORAGE_BACKEND=json
```
> Ghi chú: MCP Hub (8005) và Captcha API (8010) chỉ chạy nội bộ trong container nên không cần publish ra ngoài.
Lưu lại bằng cách nhấn `Ctrl + X`, sau đó nhấn `Y` và `Enter`.

**Bước 3: Khởi động hệ thống**
Chạy lệnh sau để tải image và khởi động các container:
```bash
docker compose up -d
```
Sau khi hoàn tất, bạn có thể truy cập trang quản trị chính tại `http://[IP_MÁY_CHỦ]:3030`.

### Cách 2: Cài Đặt Qua Giao Diện Portainer

Nếu bạn sử dụng Portainer để quản lý Docker:
1. Đăng nhập vào Portainer, chọn môi trường (Local/Primary).
2. (Nếu GHCR báo `unauthorized`): Vào **Registries** -> **Add registry** -> **GitHub Container Registry**, điền username + Personal Access Token. Hoặc trên GitHub chuyển Package `chatgpt2api` sang **Public**.
3. Chuyển đến mục **Stacks** ở menu bên trái -> Bấm **Add stack**.
4. Đặt tên stack là `chatgpt2api` (hoặc `c2a`).
5. Trong phần Web editor, dán đoạn mã `docker-compose.yml` phía trên vào.
6. Chú ý chỉnh sửa `CHATGPT2API_AUTH_KEY` thành mật khẩu bảo mật của riêng bạn và đường dẫn volume `/opt/c2a/data:/app/data`.
7. Cuộn xuống dưới cùng và bấm **Deploy the stack**. Chờ khoảng 1-2 phút để hệ thống tải về và khởi chạy.


---

## 🎛️ Đào Sâu Dashboard ChatGPT2API (Hướng Dẫn Chi Tiết Từng Tab)

> **👉 XEM CHI TIẾT:** Các cách Đăng nhập ChatGPT (Access Token/Refresh Token) và hướng dẫn cấu hình chuyên sâu các Tab tại đây: **[📖 Hướng Dẫn Sử Dụng ChatGPT2API](README_ChatGPT2API.vi.md)**

Sau khi cài đặt xong, bạn truy cập vào trang quản trị tại `http://[IP_MÁY_CHỦ]:3030` và đăng nhập bằng mật khẩu (Auth Key). Giao diện bên tay trái sẽ gồm các Tab chính, đây là cách làm chủ từng mục:

### 1. Tab Overview (Tổng Quan)
- **Công dụng**: Bảng điều khiển trung tâm theo dõi sức khỏe hệ thống theo thời gian thực.
- **Tính năng**: Xem số lượng Requests, Success Rate, và thống kê Token tiết kiệm được.

### 2. Tab Account Pool (Kho Tài Khoản ChatGPT)
- **Công dụng**: Quản lý các tài khoản ChatGPT Web miễn phí và trả phí (Plus/Pro).
- **Cách lấy Access Token an toàn**:
  1. Mở trình duyệt ẩn danh (Incognito), đăng nhập [chatgpt.com](https://chatgpt.com).
  2. Dán link `https://chatgpt.com/api/auth/session` vào thanh địa chỉ.
  3. Copy chuỗi rất dài nằm sau chữ `"accessToken":`. (Chú ý: Đóng cửa sổ, KHÔNG BẤM ĐĂNG XUẤT).
- **Cách sử dụng**: Bấm **Import Access Token** và dán token vào. Hệ thống tự động kiểm tra token sống hay chết.

### 3. Tab Providers (Nhà Cung Cấp Bên Thứ 3)
- **Công dụng**: Thêm API của Gemini, DeepSeek, Groq.
- **Cách sử dụng**: Chọn nhà cung cấp, dán API Key lấy từ Google/Deepseek vào ô trống và **Save**.

### 4. Tab Combos (Định Tuyến & Fallback Thông Minh - Quan Trọng Nhất)
- **Công dụng**: Tạo ra một luồng xử lý thông minh để AI không bao giờ bị "đơ" nếu một nguồn bị lỗi.
- **Cách cấu hình "Bất Tử"**:
  1. Bấm **Create Combo**. Đặt tên: `AI Agent`.
  2. Tại phần Fallback Chain, thêm theo thứ tự từ xịn đến dự phòng: `cx/auto` -> `chatgpt/auto` -> `gemini_free/auto` -> `oc/auto`.
  3. Hệ thống sẽ tự động quét lỗi 429 và ngay lập tức chuyển nguồn dự phòng chưa tới 1 giây.

### 5. Tab Models
- **Công dụng**: Ẩn/Hiện model. Đảm bảo bạn bật đúng model cần xài để ứng dụng ngoài quét được `/v1/models`.

### 6. Tab MCP Servers & Studio (Công Cụ Mở Rộng AI)
- **Công dụng**: Gắn thêm "Tay chân", "Mắt mũi" cho AI (Search, thời tiết, RAG…) và quản lý mọi cài đặt MCP/RAG.
- **Cách dùng**: MCP Hub đã chạy nội bộ sẵn — chỉ cần bấm Install các Preset. Mọi cài đặt trước đây ở trang `:8005/studio` nay nằm ngay trong các tab con: **Knowledge Base, Cài đặt RAG, R2 Storage, External MCP, Nạp RAG**.

---

## 🧠 Đào Sâu Studio (trong Tab MCP)

> **👉 XEM CHI TIẾT:** Hướng dẫn dạy kiến thức cho AI (RAG) và cấu hình cỗ máy tìm kiếm tại đây: **[📖 Hướng Dẫn Cấu Hình VN MCP Hub](README_VN_MCP_HUB.vi.md)**

Studio nay đã được tích hợp vào **Tab MCP** của dashboard (không còn trang `:8005/studio` riêng).

### 1. Tab Knowledge Base (Trí Nhớ Cục Bộ - RAG)
Tự dạy AI bằng cách dán tài liệu công ty/gia đình vào kho. Hub sẽ băm nhỏ và nhét vào Vector DB. AI sẽ ưu tiên tìm trong kho này khi trả lời.

### 2. Tab Multi-Search
Chọn các cỗ máy tìm kiếm như DuckDuckGo, Brave Search, Wikipedia. Nếu RAG không có đáp án, Hub âm thầm gọi Search thực tế.

### 3. Tab Cloud Storage
Lưu trữ định kỳ dữ liệu RAG lên Cloudflare R2 / AWS S3 để tránh mất mát.

---

## 🏠 Hướng Dẫn Tích Hợp Chi Tiết (Home Assistant, n8n, WebUI)

### 1. Tích Hợp Vào Home Assistant
1. **Settings** -> **Devices & Services** -> **Add Integration** -> **OpenAI Conversation**.
2. **API Key**: Mật khẩu của bạn.
3. **Base URL**: `http://[IP_MÁY_CHỦ]:3030/v1`
4. Cấu hình Integration chọn model là `AI Agent` (Combo vừa tạo).

#### 🔊 Tối Ưu Hóa Giọng Nói (TTS)
Vào Voice Assistants, dán Prompt sau vào **Instructions**:
> *"Bạn là trợ lý ảo nhà thông minh. Hãy trả lời cực kỳ ngắn gọn, tự nhiên và giống văn nói của con người để hệ thống TTS có thể đọc mượt mà. Tuyệt đối KHÔNG sử dụng các ký tự định dạng (như dấu sao *, dấu thăng #, gạch đầu dòng -). Không dùng danh sách liệt kê, hạn chế tối đa ngoặc đơn. Trả lời thẳng vào trọng tâm câu hỏi. QUAN TRỌNG: Ngay cả khi lấy dữ liệu từ Web Search hoặc MCP, tuyệt đối không được dùng định dạng liệt kê."*

### 2. Tích Hợp Open WebUI
1. Admin Panel -> **Settings** -> **Connections** -> **OpenAI API**.
2. **URL**: `http://[IP_MÁY_CHỦ]:3030/v1` và **Key**: Mật khẩu của bạn.

---

## 🚨 Khắc Phục Sự Cố (Troubleshooting)

| Tình Trạng | Nguyên Nhân & Cách Xử Lý |
| :--- | :--- |
| **Assistant trả lời có mã `#`, `*` đọc khó nghe** | Kiểm tra lại System Prompt trong Home Assistant. Đảm bảo có câu "Tuyệt đối không dùng định dạng liệt kê". |
| **Báo lỗi 400 "Model not supported"** | Bạn điền sai tên model. Kiểm tra Tab Models để lấy đúng Prefix (VD: `chatgpt/auto`). |
| **Tài khoản ChatGPT bị Expired** | Bạn đã Log Out tài khoản. Hãy mở tab ẩn danh mới, copy accessToken và tắt tab, KHÔNG ĐƯỢC bấm Log Out. |

---

## 🔄 Cập Nhật Phiên Bản Mới

```bash
cd /opt/chatgpt2api
docker compose pull
docker compose up -d
```
Mọi cấu hình và dữ liệu của bạn đều được giữ nguyên 100%.
