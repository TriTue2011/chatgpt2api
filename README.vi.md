[🇺🇸 English](README.md) | [🇻🇳 Tiếng Việt](README.vi.md)

# 🚀 ChatGPT2API - Ultimate AI Gateway & VN MCP Hub

**📚 Các tài liệu hướng dẫn (Click để xem chi tiết):**
- **[📘 Hướng dẫn CHI TIẾT từng tab, từng ô cài đặt — đọc trước nếu mới cài lần đầu](HUONG_DAN.md)**
- **[🔐 Bảo mật & nâng cấp 08/2026 — biến môi trường mới, các lỗ hổng đã vá, xử lý sự cố](docs/BAO_MAT_VA_NANG_CAP_2026-08.md)** ⬅️ *bắt buộc đọc nếu đang nâng cấp*
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

### 🌐 Dịch & phụ đề tự chủ (không bên thứ ba, không LLM)
- **Máy dịch trong stack** (`vn-translate`): EnViT5 cho en↔vi (42,95 BLEU trên FLORES-200 devtest so với 38,45 của NLLB, nhanh ~3 lần), NLLB-200 cho vi↔nhật/hàn/trung, kèm tầng thuật ngữ chuyên ngành. Tuỳ chọn **bản GPU** nhận việc theo lô (lô 120 câu: 0,84 giây trên RTX 2060S so với 54 giây trên CPU), GPU chết thì tự rơi về CPU.
- **Phụ đề video**: link YouTube (dùng phụ đề có sẵn) hoặc **tự nghe** video/âm thanh tải lên bằng sherpa-onnx (Zipformer Việt · Parakeet Anh · Zipformer Trung/Nhật/Hàn) có mốc thời gian từng từ; khung phụ đề theo chuẩn Netflix/TED (42 ký tự/dòng, 2 dòng, 20 ký tự/giây) và có bộ soát tự kiểm. Dịch được cả tệp `.srt`/`.vtt` sẵn có.
- **Tab Dịch** (Studio): chữ · link · ảnh (đọc chữ trong ảnh) · tài liệu · phụ đề · video, hai kiểu kết quả, cặp Việt↔Anh/Trung/Nhật/Hàn, upload cắt khúc cho tệp lớn.
- **Đàm thoại trực tiếp**: hai ô mic bấm-nói-thả, dịch qua lại và đọc thành tiếng đủ 5 tiếng (NghiTTS · Kokoro · Kokoro đa ngữ · Supertonic).
- **Wyoming cho Home Assistant**: mỗi cổng một vai một tiếng — ĐỌC `10600-10604`, NGHE `10700-10704`.

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

**Bước 2: Tạo file `.env`**

Từ bản vá bảo mật 08/2026, mọi secret **phải** khai bằng biến môi trường — không
còn giá trị mặc định đoán được, và stack sẽ **dừng deploy** nếu thiếu biến bắt
buộc. Chép [`.env.example`](.env.example) rồi điền:

```bash
cp .env.example .env
nano .env
```

Tối thiểu cần:
```bash
CHATGPT2API_AUTH_KEY=khoa_admin_manh
CAPTCHA_SOLVER_API_KEY=khoa_captcha_manh
ZALO_SERVER_API_KEY=khoa_zalo_api_manh
VNC_PASSWORD=mat_khau_vnc_manh
# Nên đặt cho production (xem tài liệu bảo mật bên dưới)
SESSION_SECRET=            # tạo bằng: openssl rand -base64 48
ZALO_SERVER_ADMIN_PASSWORD=
# Mã hoá mật khẩu + hạt giống TOTP đã lưu — xem mục "Mã hoá credential" bên dưới
VAULT_MASTER_KEY=          # python3 -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"
VAULT_REQUIRE_ENCRYPTION=1
```

Nếu để trống hai bí mật Zalo, server nhúng sẽ sinh mỗi bí mật đúng một lần
trong volume dữ liệu (mode `0600`); gateway Python tự đọc credential admin dùng
chung. Hãy đặt biến môi trường khi bạn muốn tự quản lý hoặc luân chuyển bí mật.

**Bước 3: Tạo file cấu hình docker-compose.yml**
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
      - "3030:80"                # API + giao diện web
      - "127.0.0.1:6080:6080"    # noVNC — chỉ localhost (bỏ 127.0.0.1 nếu cần LAN)
      - "3001:3001"              # zalo-server — chỉ giữ nếu HA ở máy khác
      - "10600-10604:10600-10604" # Wyoming ĐỌC (TTS) cho HA — việt/anh/nhật/trung/hàn
      - "10700-10704:10700-10704" # Wyoming NGHE (STT) — cùng thứ tự tiếng
    volumes:
      # 1 thư mục dữ liệu duy nhất: accounts, config, KB + chroma, profile trình duyệt
      - ./c2a-data:/app/data
    environment:
      STORAGE_BACKEND: json

      # Bắt buộc — thiếu là deploy dừng ngay
      CHATGPT2API_AUTH_KEY: ${CHATGPT2API_AUTH_KEY:?required}
      CAPTCHA_SOLVER_API_KEY: ${CAPTCHA_SOLVER_API_KEY:?required}
      ZALO_SERVER_API_KEY: ${ZALO_SERVER_API_KEY:?required}
      VNC_PASSWORD: ${VNC_PASSWORD:?required}

      # zalo-server. Image TRƯỚC hotfix 6d8c039 đòi các biến này phải TỒN TẠI
      # (dù rỗng), nếu thiếu supervisord không parse được config → crash loop.
      SESSION_SECRET: ${SESSION_SECRET:-}
      ZALO_SERVER_ADMIN_PASSWORD: ${ZALO_SERVER_ADMIN_PASSWORD:-}
      ZALO_SERVER_ADMIN_USERNAME: ${ZALO_SERVER_ADMIN_USERNAME:-admin}
      ZALO_COOKIE_SECURE: "0"    # GIỮ "0": bot gọi zalo-server qua HTTP nội bộ
      ZALO_WS_ALLOWED_ORIGINS: ${ZALO_WS_ALLOWED_ORIGINS:-}

      # Mã hoá mật khẩu + hạt giống TOTP trong data/accounts.db.
      # Để rỗng có chủ ý: thiếu khoá KHÔNG được làm container không lên.
      VAULT_MASTER_KEY: ${VAULT_MASTER_KEY:-}
      VAULT_REQUIRE_ENCRYPTION: ${VAULT_REQUIRE_ENCRYPTION:-}

    security_opt:
      - no-new-privileges:true
```
> Ghi chú: MCP Hub (8005) và Captcha API (8010) chỉ chạy nội bộ trong container nên không cần publish ra ngoài.
>
> 📘 **Đang nâng cấp từ bản cũ, hoặc gặp crash loop / Zalo báo `401`?**
> Đọc **[docs/BAO_MAT_VA_NANG_CAP_2026-08.md](docs/BAO_MAT_VA_NANG_CAP_2026-08.md)**
> — liệt kê đầy đủ biến môi trường, các lỗ hổng đã vá, các bước nâng cấp và cách
> xử lý sự cố.

Lưu lại bằng cách nhấn `Ctrl + X`, sau đó nhấn `Y` và `Enter`.

**Bước 4: Khởi động hệ thống**
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
8. Portainer đọc `${BIẾN}` từ ô **Environment variables** của chính stack, không đọc file `.env` trên máy chủ — nhập mọi biến vào đó.

### 🔐 Mã hoá credential (`VAULT_MASTER_KEY`)

Mỗi lần bạn thêm một tài khoản, **mật khẩu và hạt giống TOTP** của nó được lưu
vào `data/accounts.db`. Hạt giống TOTP không phải "mã 6 số" — nó sinh ra *mọi*
mã 6 số từ nay về sau, nên lộ nó là mất hẳn yếu tố thứ hai chứ không phải mất
một lần đăng nhập. File đó nằm trên volume dữ liệu và đi theo mọi bản sao lưu.

Đặt `VAULT_MASTER_KEY` thì cả hai trường được mã hoá bằng AES-256-GCM. Tạo khoá:

```bash
python3 -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"
```

Bốn điều nên biết:

- **Đừng đổi, đừng mất.** Dữ liệu đã mã hoá mà sai khoá thì giải ra rỗng — mọi
  mật khẩu và hạt giống đã lưu phải nhập lại từ đầu. Giữ một bản khoá ngoài máy chủ.
- **Khoá sai định dạng thì hỏng im lặng.** Phải là base64 của **đúng 32 byte**.
  Sai thì hệ thống ghi một dòng log rồi quay về lưu chữ thường — nên đặt kèm
  `VAULT_REQUIRE_ENCRYPTION=1` để biến tình huống đó thành từ chối ghi.
- **Cố ý KHÔNG bắt buộc để khởi động.** Thiếu khoá không được phép làm container
  không lên: mất cả hệ thống tệ hơn nhiều so với thứ khoá này bảo vệ.
- **Dữ liệu cũ chuyển dần.** Bản ghi cũ chưa mã hoá vẫn đọc bình thường và được
  mã hoá ở **lần ghi kế tiếp** của chính nó. Muốn xong ngay thì mở từng tài
  khoản đã lưu bấm lưu lại một lượt.

**Tài khoản được lưu ở đâu:** `Cài đặt` → thẻ **"Provider qua tài khoản Google"**
— ba ô Email / Mật khẩu / TOTP, bấm lưu là ghi vào `accounts.db`. Đây cũng là chỗ
bấm lưu lại để chuyển bản ghi cũ sang dạng mã hoá.

Ngoài ra credential còn được lưu tự động khi bạn onboard qua các thẻ **ChatGPT
via Google OAuth**, **Flow**, **Claude**, **Gemini Web**. Còn muốn thêm hoặc đổi
riêng hạt giống TOTP cho một tài khoản đã có thì vào trang `Tài khoản`, bấm
**+ Set TOTP** ở cuối dòng tài khoản đó — máy chủ sinh mã 6 số tại chỗ, không
cần trang web sinh mã bên ngoài.

Nó bảo vệ dữ liệu **lúc nghỉ** — bản backup, volume bị sao chép, ổ đĩa bị lấy.
Nó không bảo vệ trước kẻ đã vào được bên trong container, vì lúc đó khoá nằm sẵn
trong biến môi trường của tiến trình.


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
