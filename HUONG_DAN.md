# 📘 Hướng dẫn sử dụng chatgpt2api (chi tiết từng tab, từng ô cài đặt)

Tài liệu này dành cho người **mới cài lần đầu**. Đọc theo thứ tự: Phần 1 để chạy
được, Phần 2 để hiểu từng tab, Phần 3 để hiểu từng ô trong Cài đặt.

> Quy ước: `▸` là đường dẫn menu bên trái. Ví dụ `▸ Hệ thống → Cài đặt`.

---

## Mục lục

1. [Chạy lần đầu](#1-chạy-lần-đầu)
2. [Bản đồ giao diện — từng tab làm gì](#2-bản-đồ-giao-diện--từng-tab-làm-gì)
3. [Chi tiết từng ô trong tab Cài đặt](#3-chi-tiết-từng-ô-trong-tab-cài-đặt)
4. [Bật giọng nói (TTS/STT) và phát ra loa](#4-bật-giọng-nói-ttsstt-và-phát-ra-loa)
5. [Kết nối bot Telegram / Zalo](#5-kết-nối-bot-telegram--zalo)
6. [Lọc chức năng theo thread — trái tim của phân quyền](#6-lọc-chức-năng-theo-thread)
7. [Sự cố thường gặp](#7-sự-cố-thường-gặp)
8. [Nghe nhạc YouTube / Zing ra loa (tab YouTube)](#8-nghe-nhạc-youtube--zing-ra-loa-tab-youtube)

---

## 1. Chạy lần đầu

### 1.1. Cần gì trước khi bắt đầu

| Thứ | Bắt buộc? | Ghi chú |
|---|---|---|
| Docker + Docker Compose | ✅ | Bản mới bất kỳ |
| RAM | ✅ | Tối thiểu 2 GB; bật giọng nói local nên có 4 GB |
| Ổ đĩa | ✅ | ~12 GB: image 5,7 GB (kèm Chrome để tự động hoá web) + chỗ cho dữ liệu và model giọng nói |
| Tài khoản AI | ✅ | ít nhất một: ChatGPT, Gemini, Claude… |
| Domain HTTPS | ❌ | chỉ cần khi dùng bot Telegram/Zalo (xem Cloudflare Tunnel) |

Bảng trên là mức tối thiểu để chạy. Muốn biết con số đĩa đã đo thật, cách cài
Docker trên NAS (Synology / QNAP / TrueNAS / Unraid), và danh sách những thứ
**không** đóng gói sẵn trong image: [CHUAN_BI_TRUOC_KHI_PULL.md](CHUAN_BI_TRUOC_KHI_PULL.md).

### 1.2. Cách A — Docker Compose (dòng lệnh)

**Bước 1 — Lấy mã nguồn:**

```bash
git clone <repo-url> chatgpt2api
cd chatgpt2api
```

**Bước 2 — Mở `docker-compose.yml`, sửa 2 chỗ bắt buộc:**

```yaml
services:
  c2a:
    build:
      context: .
      dockerfile: Dockerfile
    image: c2a:latest
    container_name: c2a
    restart: unless-stopped

    ports:
      - "3030:80"      # ← web UI + API (đổi số trái nếu 3030 bị chiếm)
      - "6080:6080"    # noVNC — LAN; BẮT BUỘC đặt VNC_PASSWORD
      - "3001:3001"    # zalo-server (HA/integration có thể ở máy khác)
      - "10600-10604:10600-10604"  # Wyoming ĐỌC: việt/anh/nhật/trung/hàn (HA khác host → đừng bind 127.0.0.1)
      - "10700-10704:10700-10704"  # Wyoming NGHE: cùng thứ tự tiếng

    volumes:
      - /opt/c2a-data:/app/data   # ← đổi /opt/c2a-data thành thư mục BẤT KỲ trên máy bạn

    environment:
      CHATGPT2API_AUTH_KEY: your_secret_key_here     # ← ĐỔI thành chuỗi bí mật của bạn
      CAPTCHA_SOLVER_API_KEY: your_secret_key_here    # ← đổi luôn (khác giá trị trên cũng được)
      VNC_PASSWORD: your_vnc_password                 # ← bắt buộc nếu mở 6080 trên LAN
      STORAGE_BACKEND: json
      # CAPTCHA_SOLVER_NOVNC_EXTERNAL_URL: "http://IP_HOST:6080/vnc.html?host=IP_HOST&port=6080&autoconnect=1"
```

| Chỗ cần sửa | Vì sao |
|---|---|
| `CHATGPT2API_AUTH_KEY` | Mật khẩu đăng nhập + API key. Để nguyên `your_secret_key_here` thì ai cũng đăng nhập được |
| `VNC_PASSWORD` | noVNC không mật khẩu = ai trên LAN cũng điều khiển trình duyệt captcha |
| `/opt/c2a-data` (vế trái của volume) | Nơi lưu **toàn bộ** dữ liệu — tài khoản, cấu hình, model giọng nói. Thư mục này phải tồn tại và còn chỗ trống (khuyên ≥15 GB) |
| `3030:80` | Nếu máy đã có dịch vụ khác dùng cổng 3030, đổi số bên trái, vd `8080:80` |
| `10600-10604` / `10700-10704` / `3001` | **Không** bind `127.0.0.1` nếu Home Assistant / client nằm máy khác trong LAN (106xx = Wyoming ĐỌC, 107xx = NGHE — mỗi cổng một tiếng, xem 4.2c) |

**Máy ít RAM, chạy chung với container khác?** Đặt trần RAM cho từng container bằng
biến môi trường (trong tệp `.env` cạnh `docker-compose.yml`, hoặc ô **Environment
variables** của Portainer). Bỏ trống = không giới hạn (mặc định):

| Biến | Gợi ý | Ghi chú |
|---|---|---|
| `C2A_MEM_LIMIT` | `4g` | c2a gồm trình duyệt, giọng nói, MCP, Zalo — đo thật ~2,5 GB ngay sau khởi động, đặt dưới ~3,5g dễ bị tắt vì hết RAM |
| `SEARXNG_MEM_LIMIT` | `512m` | đo ~110 MB |
| `VN_TRANSLATE_MEM_LIMIT` | `1g` | model dịch nạp vào RAM khi dùng |
| `LIBRETRANSLATE_MEM_LIMIT` | `2g` | chỉ khi bật profile `libretranslate` |

Container chạm trần thì Docker tắt nó và tự bật lại — trần là để không kéo sập cả
máy, không làm c2a nhẹ hơn.

**Bước 3 — Chạy:**

```bash
# Build image từ mã nguồn (lần đầu mất 5–15 phút tuỳ máy)
docker compose up -d --build

# Hoặc nếu chỉ muốn dùng image build sẵn (nhanh hơn, không cần build)
docker compose up -d --no-build
```

**Bước 4 — Kiểm tra đã chạy chưa:**

```bash
docker compose ps          # cột STATUS phải là "Up ... (healthy)"
docker compose logs -f c2a # xem log trực tiếp, Ctrl+C để thoát xem
```

Mở trình duyệt: `http://<ip-máy>:3030` (đổi `<ip-máy>` thành `localhost` nếu chạy
ngay trên máy đang mở trình duyệt, hoặc IP LAN của máy chủ nếu chạy từ xa).

**Lệnh hay dùng về sau:**

```bash
docker compose pull && docker compose up -d --no-build   # cập nhật lên bản mới nhất
docker compose restart c2a                                # khởi động lại
docker compose down                                       # dừng hẳn (dữ liệu vẫn còn trong volume)
```

### 1.3. Cách B — Portainer (giao diện web, không cần gõ lệnh)

Portainer là bảng điều khiển Docker chạy trên web — hợp với ai không quen dòng lệnh
hoặc quản lý nhiều container cùng lúc.

**Bước 1 — Có Portainer chưa?** Nếu máy chưa cài:

```bash
docker volume create portainer_data
docker run -d -p 9443:9443 --name portainer --restart=always \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v portainer_data:/data \
  portainer/portainer-ce:latest
```

Mở `https://<ip-máy>:9443`, tạo tài khoản quản trị ở lần đăng nhập đầu.

**Bước 2 — Tạo Stack:**

1. Menu trái → **Stacks** → **Add stack**.
2. **Name**: gõ `chatgpt2api` (tuỳ ý).
3. **Build method**: chọn **Web editor**.
4. Dán nội dung file `docker-compose.yml` của repo vào ô soạn thảo (xem mẫu ở
   Cách A) — **sửa `CHATGPT2API_AUTH_KEY` và đường dẫn volume** giống hệt Cách A.
5. Vì Portainer không tự có mã nguồn để build, đổi phần `build:` thành `image:` trỏ
   thẳng tới bản build sẵn trên GHCR:

   ```yaml
   services:
     c2a:
       image: ghcr.io/tritue2011/chatgpt2api:latest
       container_name: c2a
       restart: unless-stopped
       ports:
         - "3030:80"
         - "6080:6080"      # noVNC — đặt VNC_PASSWORD; siết 127.0.0.1 nếu chỉ SSH tunnel
         - "3001:3001"      # zalo — LAN (HA có thể khác host)
         - "10600-10604:10600-10604"   # Wyoming ĐỌC (TTS) — HA khác host
         - "10700-10704:10700-10704"   # Wyoming NGHE (STT)
       volumes:
         - /opt/c2a/data:/app/data
       environment:
         CHATGPT2API_AUTH_KEY: your_secret_key_here
         CAPTCHA_SOLVER_API_KEY: your_secret_key_here
         VNC_PASSWORD: your_vnc_password
         STORAGE_BACKEND: json
   ```

   > 💡 **Khắc phục lỗi `unauthorized` khi pull image trong Portainer**:
   > Nếu GHCR báo lỗi `unauthorized`, truy cập GitHub Package `chatgpt2api` -> **Package settings** -> Chuyển **Package visibility** sang `Public`. Hoặc trong Portainer: **Registries** -> **Add registry** -> **GitHub Container Registry**, điền username + Personal Access Token (PAT có quyền `read:packages`).


6. Bấm **Deploy the stack** ở cuối trang. Đợi cột trạng thái chuyển xanh.

**Bước 3 — Vào container xem log / chạy lệnh** (khi cần, ví dụ tải model giọng nói
ở Phần 4): **Containers** → bấm vào `c2a` → tab **Logs** để xem log, hoặc nút
**Console** → **Connect** → chọn `/bin/sh` để mở terminal ngay trong trình duyệt.

**Cập nhật lên bản mới:** **Stacks** → mở stack `chatgpt2api` → **Pull and redeploy**
(hoặc **Update the stack** nếu bạn vừa sửa nội dung file).

### 1.4. `CHATGPT2API_AUTH_KEY` dùng để làm gì

Vừa là mật khẩu đăng nhập trang quản trị, vừa là API key khi ứng dụng ngoài gọi vào
(`Authorization: Bearer <khóa>`). Đặt chuỗi khó đoán và **không** đưa lên GitHub.

### 1.5. Bốn việc nên làm ngay sau khi đăng nhập

1. **Thêm tài khoản AI** — `▸ AI Core → Tài khoản`. Chưa có tài khoản thì mọi thứ
   khác đều vô nghĩa.
2. **Kiểm tra model** — `▸ AI Core → Model`. Danh sách phải hiện ra model từ tài
   khoản vừa thêm.
3. **Thử chat** — `▸ Studio → Chat`. Gõ một câu; có trả lời tức là đường ống thông.
4. **Đặt “Địa chỉ truy cập hình ảnh”** — `▸ Hệ thống → Cài đặt → Cấu hình chung`.
   Điền `http://<ip-máy>:3030`. Thiếu ô này thì ảnh/âm thanh sinh ra sẽ hiện link
   hỏng khi gửi ra ngoài.

### 1.6. Dữ liệu nằm ở đâu

Mọi thứ trong thư mục `data/` (mount volume, sống qua mọi lần cập nhật image):

```
data/config.json    cấu hình (tài khoản, bot, bộ lọc…)
data/piper/         giọng đọc .onnx        ← tải riêng, KHÔNG có trong image
data/stt/           model nhận dạng giọng  ← tải riêng
data/voice/         file âm thanh tạm + sổ loa
data/agent/         trí nhớ, phiên chat, nhắc hẹn, wiki
```

Nguyên tắc xuyên suốt: **mã nguồn nằm trong image, model nằm ngoài volume** — nhờ
vậy image không phình thêm hơn 1 GB.

### 1.7. Sử dụng Cơ Sở Dữ Liệu PostgreSQL & Chuyển Đổi Dữ Liệu (Migration)

Nếu muốn sử dụng **PostgreSQL** để lưu trữ bền vững (thay thế file JSON/SQLite):

**1. Mẫu `docker-compose.yml` tích hợp PostgreSQL:**
```yaml
version: "3.8"

services:
  db:
    image: postgres:15-alpine
    container_name: c2a-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: c2a_user
      POSTGRES_PASSWORD: c2a_secure_password_123
      POSTGRES_DB: c2a_db
    volumes:
      - /opt/c2a/postgres:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U c2a_user -d c2a_db"]
      interval: 5s
      timeout: 5s
      retries: 5

  c2a:
    image: ghcr.io/tritue2011/chatgpt2api:latest
    container_name: c2a
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "3030:80"
      - "6080:6080"
      - "3001:3001"
      - "10600-10604:10600-10604"
      - "10700-10704:10700-10704"
    volumes:
      - /opt/c2a/data:/app/data
    environment:
      - STORAGE_BACKEND=postgres
      - DATABASE_URL=postgresql://c2a_user:c2a_secure_password_123@db:5432/c2a_db
      - CHATGPT2API_AUTH_KEY=your_secret_key_here
      - CAPTCHA_SOLVER_API_KEY=your_secret_key_here
      - VNC_PASSWORD=your_vnc_password
```

**2. Lệnh chuyển đổi toàn bộ dữ liệu từ JSON sang Postgres:**
```bash
docker exec -it c2a python scripts/migrate_storage.py \
  --from json \
  --to postgres \
  --to-url "postgresql://c2a_user:c2a_secure_password_123@db:5432/c2a_db"
```

### 1.8. Cho AI hỏi thẳng database (Postgres MCP Pro — tuỳ chọn)

Chỉ làm khi bạn đã chuyển sang PostgreSQL ở mục 1.7. Sau bước này, bot trả lời
được những câu như *"bảng nào đang nặng nhất"*, *"câu truy vấn này chậm ở đâu"*,
*"thiếu index chỗ nào"* — nó tự chạy `EXPLAIN` và đọc thống kê thật.

Thêm khối này vào file compose (hoặc Stack trong Portainer), ngang hàng với `c2a`:

```yaml
  postgres-mcp:
    image: crystaldba/postgres-mcp:latest
    container_name: postgres-mcp
    restart: unless-stopped
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      - DATABASE_URI=postgresql://c2a_user:${DB_PASSWORD}@host.docker.internal:5432/c2a_db
    command: ["--access-mode=restricted", "--transport=sse"]
    security_opt:
      - no-new-privileges:true
```

Rồi vào **Cài đặt → MCP** thêm một server với URL:

```
http://postgres-mcp:8000/sse
```

Ba điều nên biết trước khi đổi cấu hình này:

- **`--access-mode=restricted` là chỉ đọc.** Model gọi nhầm cũng không sửa hay xoá
  được dữ liệu. Trên máy chạy thật thì **đừng** đổi sang `unrestricted`.
- **`--transport=sse` là bắt buộc.** MCP client của gateway nói chuyện qua HTTP;
  MCP kiểu `stdio` cắm vào sẽ không nhận (đây cũng là lý do nhiều MCP server khác
  không dùng thẳng được).
- **Không cần mở cổng ra ngoài.** c2a gọi nội bộ theo tên service `postgres-mcp`.
  Thêm `ports:` là lộ đường vào database ra LAN — đừng làm.

Kiểm tra chạy được chưa:

```bash
docker logs postgres-mcp | tail -5
```

---



## 2. Bản đồ giao diện — từng tab làm gì

### 📊 Tổng quan (`/`)

Trang đầu tiên. Xem nhanh: số tài khoản đang sống/bị giới hạn, lượng dùng 14 ngày
gần nhất, trạng thái các dịch vụ nền. Vào đây trước khi nghi ngờ “sao bot không trả
lời” — thường thấy ngay tài khoản nào chết.

### 🧠 AI Core

| Tab | Dùng để làm gì | Mẹo |
|---|---|---|
| **Tài khoản** | Thêm/xoá tài khoản AI (ChatGPT, Gemini, Claude…), xem token còn hạn không, khôi phục tài khoản lỗi | Tài khoản đỏ = hết hạn hoặc bị rate-limit; bấm khôi phục trước khi xoá |
| **Nhà cung cấp** | Bật/tắt từng nhà cung cấp, cắm API key, thêm endpoint tương thích OpenAI | Tắt hẳn nhà cung cấp không dùng cho nhẹ |
| **Model** | Danh sách model khả dụng, bật/tắt, đổi tên hiển thị | Tên ở đây chính là tên gọi trong API và trong Combo |
| **Combo** | Ghép nhiều model thành một chuỗi dự phòng | Thử model ❶ trước, lỗi mới sang ❷ — chống chết một nhà cung cấp |
| **MCP** | Bật các máy chủ MCP (tìm web, thời tiết, RAG…), chuyển tài liệu sang markdown | MCP = “tay chân” của AI; tắt bớt nếu thấy chậm |

### 🎨 Studio

| Tab | Dùng để làm gì |
|---|---|
| **Chat** | Khung chat thử nghiệm, chọn model, xem agent gọi công cụ gì |
| **Tạo ảnh** | Sinh ảnh; kích thước lấy theo mặc định trong Cài đặt |
| **Quản lý ảnh** | Thư viện ảnh đã tạo, gắn thẻ, tải về, xoá hàng loạt |
| **Tạo video** | Sinh video (Veo 3.1 — Google DeepMind) |
| **Quản lý video** | Thư viện video đã tạo |
| **Dịch** | Dịch bằng máy dịch trong stack (không tốn lượt AI): chữ · link YouTube · ảnh · tài liệu · phụ đề `.srt/.vtt` · video/âm thanh. Tab con **Đàm thoại** = phiên dịch hai chiều qua mic. Xem 4.4b |
| **YouTube** (chỉ quản trị) | Tìm YouTube · Zing MP3 · link audio rồi nghe/xem ngay trên máy hoặc phát ra loa, tivi trong nhà (loa trong Sổ loa c2a và loa Home Assistant). Xem Phần 8 |

### 📡 Kênh

| Tab | Dùng để làm gì |
|---|---|
| **Cấu hình tìm kiếm** | Chọn nguồn tìm kiếm web cho AI, khoá API tìm kiếm |

> Cài đặt bot Telegram/Zalo **không** nằm ở đây mà ở `▸ Hệ thống → Cài đặt → Kênh chat`.

### ⚙️ Hệ thống

| Tab | Dùng để làm gì |
|---|---|
| **Agent runs** | Nhật ký từng lượt agent: gọi công cụ nào, model nào, mất bao lâu, lỗi gì. Nơi đầu tiên cần xem khi bot trả lời sai |
| **Sao lưu & Phục hồi** | Sao lưu cấu hình lên Cloudflare R2, phục hồi khi chuyển máy |
| **Cài đặt** | Toàn bộ cấu hình — mô tả chi tiết ở Phần 3 |

---

## 3. Chi tiết từng ô trong tab Cài đặt

Các card xếp theo đúng thứ tự trên màn hình.

### 3.1. Cấu hình chung

| Ô | Ý nghĩa | Gợi ý |
|---|---|---|
| **Khoảng thời gian làm mới tài khoản** | Bao nhiêu phút kiểm tra lại token một lần | 30–60 phút |
| **Proxy toàn cầu** | Proxy cho mọi kết nối ra ngoài | Để trống nếu mạng vào thẳng được. Có nút **Kiểm tra Proxy** |
| **Địa chỉ truy cập hình ảnh** (`base_url`) | Tiền tố URL cho ảnh/âm thanh sinh ra | **Quan trọng** — phải là địa chỉ máy khác truy cập được, không dùng `localhost` |
| **Tự động dọn dẹp hình ảnh** | Xoá ảnh cũ hơn N ngày | 30 |
| **Kích thước ảnh mặc định** | Áp cho mọi model sinh ảnh (GPT, Gemini, SD, FLUX…) | 1792×1024 (16:9) |
| **Thời gian chờ thăm dò hình ảnh** | Đợi tối đa bao lâu cho một ảnh | Tăng nếu hay bị treo giữa chừng |
| **Số luồng ảnh mỗi tài khoản** | Sinh song song bao nhiêu ảnh trên một tài khoản | 1–2 để tránh bị khoá |
| **Model mặc định cho Web Session** | Model dùng khi client không nêu rõ | |
| **Mức độ nhật ký console** | Lượng log in ra | `INFO`; `DEBUG` khi cần soi lỗi |
| **Chỉ thị bổ sung toàn cầu** | System prompt cộng thêm cho MỌI cuộc trò chuyện | Đặt giọng điệu, xưng hô |
| **Từ nhạy cảm** | Danh sách từ bị chặn | Mỗi dòng một từ |

### 3.2. Gemini / NVIDIA NIM / Nhà cung cấp tuỳ chỉnh / Google

Bốn card cắm khoá cho từng nhà cung cấp. Ô hay dùng:

- **API Keys (mỗi dòng 1 key)** — nhiều khoá tự xoay vòng khi một khoá bị giới hạn.
- **Base URL / API Key / Model** — cho endpoint tương thích OpenAI bất kỳ
  (LM Studio, vLLM, OpenRouter…).
- **Model mặc định** — model dùng khi không nêu tên.

### 3.3. Codex Onboard

Tự động tạo/khôi phục tài khoản ChatGPT bằng hộp thư Gmail.

| Ô | Ý nghĩa |
|---|---|
| **Email Gmail IMAP** | Hộp thư nhận mã xác minh |
| **App Password Gmail** | Mật khẩu ứng dụng (không phải mật khẩu Gmail thường) |

### 3.4. Khoá người dùng (User Keys)

Tạo khoá API riêng cho từng người/ứng dụng, thay vì chia sẻ khoá quản trị.

| Ô | Ý nghĩa |
|---|---|
| **Tên (tuỳ chọn)** | Ghi nhớ khoá này của ai |
| **Khoá mới (tuỳ chọn)** | Để trống thì hệ thống tự sinh |

### 3.5. Kênh chat (Telegram · Zalo Bot · Zalo Cá Nhân)

Card lớn nhất, chia **3 tab kênh**, mỗi kênh có **3 tab con** (Cài đặt kênh · Lọc
thread · Nhánh agent; Zalo Cá Nhân thêm 🔑 Tài khoản & QR). Xem Phần 5 và 6.

### 3.6. Cloudflare

Hạ tầng dùng chung cho mọi bot:

| Ô | Ý nghĩa |
|---|---|
| **Webhook URL** | Domain HTTPS mà Telegram/Zalo gọi ngược về. Mọi bot dùng chung một URL, phân biệt bằng token bí mật tự sinh |
| **Tunnel Token** | Token từ Cloudflare Zero Trust → Tunnels. Lưu xong tunnel tự chạy, không cần mở cổng router |

### 3.7. Home Assistant

| Ô | Ý nghĩa |
|---|---|
| **HA URL** | Ví dụ `http://192.168.1.10:8123` |
| **Long-Lived Access Token** | Tạo trong HA: hồ sơ người dùng → cuối trang → Long-lived access tokens |
| **Chu kỳ làm mới danh sách thiết bị (giây)** | 3600 là hợp lý; ngắn hơn khi hay thêm thiết bị |

Có HA thì AI đọc được trạng thái nhà và điều khiển thiết bị. **Không bắt buộc** —
phần loa ở Phần 4 chạy được mà không cần HA.

#### Camera nhà (cùng mục, ngay dưới ô HA)

Khai camera **thẳng vào cổng**, không qua Home Assistant — ai không cài HA vẫn
dùng được. Đặt tên tiếng Việt cho từng cái rồi hỏi bằng tên đó, từ Zalo,
Telegram hay trợ lý trong nhà: «xem camera sân trước», «ngoài cổng có ai không».

Hai đường vào:

| Kiểu | Cần khai | Khi nào chọn |
|---|---|---|
| **go2rtc** | Địa chỉ máy chủ go2rtc (cổng mặc định **1984**) và **tên luồng** đặt trong mục `streams` của nó | Đã chạy go2rtc rồi. Nhanh hơn vì go2rtc giữ sẵn kết nối tới camera |
| **RTSP** | Một URL `rtsp://…` | Chưa có gì thêm. Mỗi lần chụp tốn vài giây bắt tay |

#### Luồng phụ cho AI — khai hay không

Mỗi camera khai được **hai luồng**: luồng chính để gửi ảnh nét cho bạn, luồng
phụ để AI đọc. Cách chọn:

| Bạn hỏi gì | Bấm luồng nào |
|---|---|
| «Chụp ảnh sân trước» | Chỉ **luồng chính**, gửi tấm nét. Không đụng model |
| «Sân trước có ai không» | AI đọc **luồng phụ**, bạn nhận tấm **luồng chính** kèm câu trả lời |
| Camera không khai luồng phụ | Bóc một khung luồng chính, dùng cho cả hai việc |

**Không khai luồng phụ cũng chạy bình thường** — chỉ là AI đọc luôn luồng chính.

⚠️ Với **RTSP thẳng thì thường KHÔNG nên khai luồng phụ.** Ba lý do, đều đo trên
camera Dahua thật:

1. Ảnh đưa cho model đằng nào cũng được thu về 768px trước khi gửi. Luồng phụ
   640×480 ra **27,6 KB**, luồng chính thu nhỏ ra **25,1 KB** — luồng phụ còn
   nhỉnh hơn. Không tiết kiệm gì cả.
2. Hỏi cùng một câu về hai ảnh đó, model trả lời **giống nhau**. Nên cũng không
   được thêm độ chính xác nào.
3. Khai luồng phụ thì mỗi lần hỏi phải bấm camera **hai lần nối đuôi**. Bấm song
   song thì nhanh hơn, nhưng camera này **không chịu nổi hai phiên RTSP cùng
   lúc** — thử hai lần, hỏng cả hai, mỗi lần chờ hết 25 giây. Nên hệ thống bấm
   nối đuôi, và hai tấm cách nhau vài giây.

Con số «rẻ hơn hai mươi lần» hay được nhắc là so ảnh **nguyên cỡ 1920×1080** với
ảnh luồng phụ. Ở đây không áp dụng, vì hệ thống đã tự thu nhỏ trước khi gửi model.

Luồng phụ **đáng khai khi đi qua go2rtc**: go2rtc giữ sẵn một kết nối tới camera
rồi phục vụ nhiều khách, nên hai lời gọi cùng lúc không phiền camera, và hệ
thống bấm song song — hai tấm cùng một khoảnh khắc.

Ô **Ghi chú** cũng được dùng để nhận tên. Đặt tên camera là `cam1` nhưng ghi chú
«cổng ngoài» thì hỏi «xem cổng ngoài» vẫn ra đúng cái đó.

Nút **Chụp thử** chỉ chạy được sau khi đã bấm **Lưu**, vì nó đọc camera từ cấu
hình đã lưu chứ không đọc từ ô đang gõ dở. Nút **Sửa** nạp camera đó lên form để
chỉnh; đổi tên trong lúc sửa thì bản ghi cũ được bỏ đi, không thành hai cái.

> 🔐 **Ai được xem.** Cài ở **Kênh chat**, không phải ở thẻ Camera: chọn kênh
> (📨 Telegram · 💬 Zalo Bot · 👤 Zalo Cá Nhân) → tab **🎚️ Lọc thread** → tìm
> hội thoại → tích ô **📷 Camera nhà (go2rtc · RTSP)**. Cùng một chỗ với mọi
> quyền khác của hội thoại đó, nên không còn cảnh bật một nơi mà nơi kia vẫn
> chặn.
>
> Camera **phải tích mới có**: hội thoại chưa đặt bộ lọc thì không xem được, dù
> các chức năng khác đang mở hết — ngược với mọi nhóm khác, và cố ý như vậy vì
> camera nhìn vào trong nhà. Cùng lý do, bản cập nhật thêm nhóm camera **không
> tự bật** nó cho các bộ lọc đã lưu từ trước; phải tự tay tích.

Camera mập mờ tên thì bot **hỏi lại** chứ không chụp đại. Có hai camera cùng chữ
«sân» mà bạn chỉ nói «xem camera sân» thì nó liệt kê ra để bạn chọn — chụp nhầm
camera phòng ngủ khi người ta hỏi camera sân là chuyện không sửa lại được.

### 3.8. Email & Lịch

| Ô | Ý nghĩa |
|---|---|
| **Bật email channel** | Bật là AI đọc thư đến và trả lời |
| **IMAP host / port** | Ví dụ `imap.gmail.com` / `993` |
| **SMTP host / port** | Ví dụ `smtp.gmail.com` / `465` |
| **User / email** | Địa chỉ hộp thư |
| **Password / app password** | Mật khẩu ứng dụng |
| **Poll seconds** | Bao lâu kiểm thư một lần (60) |
| **Bật lịch ICS** | Kéo lịch để AI biết lịch sắp tới |
| **ICS URL** | Link bí mật của Google Calendar |
| **burst / reason** | Model cho việc nhanh-rẻ và việc cần suy luận |

> ⚠️ **Chặn theo danh sách trắng**: người gửi không nằm trong danh sách cho phép thì
> bị bỏ qua. Để trống nghĩa là **chặn tất cả** — cố ý như vậy cho an toàn.
> Bật/tắt có hiệu lực ở lần kiểm thư kế tiếp, **không cần khởi động lại**.

### 3.9. Giọng nói & Loa

Xem Phần 4.

### 3.10. Sao lưu

| Ô | Ý nghĩa |
|---|---|
| **Cloudflare Account ID / R2 Endpoint / Bucket** | Nơi cất bản sao lưu |
| **Access Key ID / Secret Access Key** | Khoá R2 |
| **Tiền tố sao lưu** | Thư mục con trong bucket |
| **Khoảng thời gian sao lưu định kỳ** | Phút |
| **Số bản sao lưu giữ lại** | Cũ hơn sẽ bị xoá |
| **Mật khẩu mã hoá** | Có điền thì bản sao lưu được mã hoá — **mất mật khẩu là mất luôn dữ liệu** |

---

## 4. Bật giọng nói (TTS/STT) và phát ra loa

Ba việc: tải model → bật trong Cài đặt → khai báo loa.

### 4.1. Tải model (chỉ làm một lần)

```bash
# --- CÁCH A: Chạy script trực tiếp trong container c2a (Khuyên dùng) ---
# Tiếng Việt (đủ để dùng ngay)
docker exec -it c2a python scripts/download_piper_voices.py --pack minimal
docker exec -it c2a python scripts/download_stt_model.py
docker exec -it c2a python scripts/download_vieneu_model.py

# Giọng Việt GIỮ THANH ĐIỆU tốt nhất (tuỳ chọn, xem mục 4.2g)
docker exec -it c2a python scripts/download_kokoro_vi.py --all   # Kokoro Việt, 14 giọng ~330 MB
docker exec -it c2a python scripts/download_zerotts.py           # ZeroTTS, 8 giọng ~900 MB

# Tiếng Anh (tuỳ chọn) — giọng Kokoro + bộ nghe Parakeet
docker exec -it c2a python scripts/download_kokoro_model.py
docker exec -it c2a python scripts/download_stt_en_model.py

# Trung / Nhật / Hàn (tuỳ chọn) — cho tab Dịch, đàm thoại, cổng Wyoming
docker exec -it c2a python scripts/download_stt_da_ngu.py       # NGHE  ~340 MB
docker exec -it c2a python scripts/download_tts_da_ngu.py       # ĐỌC   ~263 MB

# --- CÁCH B: Tải thủ công bằng wget từ GitHub Release về host (/opt/c2a/data/) ---

# 1. Model nghe tiếng Việt (Zipformer STT -> /opt/c2a/data/stt/)
mkdir -p /opt/c2a/data/stt && cd /opt/c2a/data/stt
wget https://github.com/TriTue2011/chatgpt2api/releases/download/stt-zipformer-v1/bpe.model
wget https://github.com/TriTue2011/chatgpt2api/releases/download/stt-zipformer-v1/config.json
wget https://github.com/TriTue2011/chatgpt2api/releases/download/stt-zipformer-v1/decoder-epoch-20-avg-10.onnx
wget https://github.com/TriTue2011/chatgpt2api/releases/download/stt-zipformer-v1/encoder-epoch-20-avg-10.onnx
wget https://github.com/TriTue2011/chatgpt2api/releases/download/stt-zipformer-v1/joiner-epoch-20-avg-10.onnx

# 2. Giọng đọc tiếng Việt (Piper TTS -> /opt/c2a/data/piper/)
mkdir -p /opt/c2a/data/piper && cd /opt/c2a/data/piper
wget https://github.com/TriTue2011/chatgpt2api/releases/download/piper-voices-v1/ngochuyennew.onnx
wget https://github.com/TriTue2011/chatgpt2api/releases/download/piper-voices-v1/ngochuyennew.onnx.json
wget https://github.com/TriTue2011/chatgpt2api/releases/download/piper-voices-v1/banmai.onnx
wget https://github.com/TriTue2011/chatgpt2api/releases/download/piper-voices-v1/banmai.onnx.json
wget https://github.com/TriTue2011/chatgpt2api/releases/download/piper-voices-v1/minhkhang.onnx
wget https://github.com/TriTue2011/chatgpt2api/releases/download/piper-voices-v1/minhkhang.onnx.json
```

File lưu vào `data/piper/`, `data/stt/`, `data/hf/`, `data/kokoro-vi/`, `data/zerotts/`, `data/stt-en/`, `data/kokoro/`,
`data/stt-{zh,ja,ko}/`, `data/kokoro-zh/`, `data/supertonic/`.
**Không** nằm trong image nên cập nhật image không mất, và image không nặng thêm.
Tải tiếng nào thì tiếng đó dùng được — chưa tải thì mục tương ứng trong Cài đặt
hiện `✗` và cổng Wyoming của tiếng đó không mở.

### 4.2. Cài đặt trong `▸ Hệ thống → Cài đặt → Giọng nói & Loa`

| Ô | Ý nghĩa |
|---|---|
| **Theo từng tiếng** | Năm mục thu gọn (Việt · Anh · Nhật · Trung · Hàn), bấm để xoè: chọn **giọng đọc** của tiếng đó, **Nghe thử**, và hai ô **cổng Wyoming** (đọc/nghe). Tiêu đề mỗi mục hiện `đọc ✓ · nghe ✓` = model đã tải |
| **Backend đọc (TTS)** | `Tự động` (khuyên dùng) · `Chỉ local` · `Chỉ Wyoming` · `Tắt` |
| **Giọng đọc** | Chọn trong các giọng đã tải về. Giọng `vieneu:*` = VieNeu 48 kHz (Việt + Anh xen kẽ); `kokorovi:*` = Kokoro Việt 24 kHz và `zerotts:*` = ZeroTTS 48 kHz (hai họ giữ thanh điệu tốt nhất — mục 4.2g); `kokoro:*` = tiếng Anh; còn lại = Piper. Giọng các họ này lỗi sẽ tự rơi về Piper để trợ lý không bao giờ "câm" |
| **Wyoming TTS / STT** | Tuỳ chọn — trỏ tới máy chủ giọng nói sẵn có trong nhà |
| **Nghe (STT) — tin nhắn thoại & API** | Khối này CHỈ chi phối tin nhắn thoại gửi bot và `/v1/audio/transcriptions`. Home Assistant **không** dùng nó (HA đi cổng nghe riêng từng tiếng — mục 4.2c) |
| **URL công khai của gateway** | **Bắt buộc nếu muốn phát ra loa.** Loa trong nhà tải file từ địa chỉ này nên **không dùng `localhost`** — điền `http://<ip-máy>:3030` |

Hai ô trạng thái phía trên cho biết engine sẵn sàng chưa (có binary chưa, đã tải
model chưa) — nhìn vào đó để biết còn thiếu gì.

### 4.2b. Đọc theo dòng chảy (chữ sinh ra tới đâu đọc tới đó)

Trong tab **Chat**, bật nút **🔊** cạnh ô chọn model rồi chọn giọng. Khi trợ lý trả
lời, mỗi khi đủ một câu là câu đó được đọc ngay trong lúc AI vẫn đang gõ tiếp — không
phải chờ hết bài. Cạnh ô nhập còn có nút **🎤**: bấm để nói bằng micro của máy
tính/điện thoại, bấm lần nữa để dừng — lời nói được nhận dạng (STT) rồi điền vào ô
nhập cho bạn sửa trước khi gửi. (Micro yêu cầu trang chạy qua HTTPS hoặc localhost.) Giọng `vieneu:*` đọc theo *frame* (âm thanh ra sau ~1 giây, mượt vì
chạy nhanh hơn thời gian thực ngay trên 1 nhân CPU); các giọng khác đọc theo *câu*.

Dưới nền, hai đường API dùng chung:

```bash
# Chunked WAV — phát dần khi sinh (thẻ <audio> nhận token qua ?key=)
GET  /api/voice/stream?voice=vieneu:Phạm%20Tuyên&text=...&key=<auth>

# Tương thích OpenAI, thêm "stream": true để nhận âm thanh theo dòng chảy
POST /v1/audio/speech   {"input":"...","voice":"vieneu:Ngọc Trân","stream":true}
```

> ⚙️ **1 nhân là đủ.** TTS local (VieNeu + Kokoro) mặc định chạy `voice.tts.num_threads = 1`
> — đo trên Xeon E5 v4: VieNeu int8 streaming đạt RTF ≈ 0.87 (<1) nên phát không giật mà
> vẫn chừa CPU cho phần còn lại. Tăng số này chỉ khi muốn âm thanh ra nhanh hơn nữa.
> (Lưu ý: model Kokoro int8 chỉ nhanh hơn trên CPU có AVX512-VNNI; CPU cũ giữ bản fp32.)

### 4.2c. Home Assistant dùng thẳng TTS/STT của gateway (Wyoming)

Gateway mở Wyoming theo **quy chuẩn cổng** (từ 14/08/2026): mỗi cổng MỘT vai
MỘT tiếng — HA thêm từng integration, pipeline Assist không bao giờ lẫn
tiếng/giọng. Không cần container tiếng nói riêng (vieneu-wyoming /
wyoming-stt / piper).

| Tiếng | Đọc (TTS) | Nghe (STT) | Giọng đọc | Model nghe |
|-------|-----------|------------|-----------|------------|
| Việt  | `10600` | `10700` | NghiTTS / VieNeu / Piper | Zipformer vi |
| Anh   | `10601` | `10701` | Kokoro (11 giọng) | Parakeet-TDT 0.6B |
| Nhật  | `10602` | `10702` | Supertonic | Zipformer ja (ReazonSpeech) |
| Trung | `10603` | `10703` | Kokoro đa ngữ (100 giọng) | Zipformer zh |
| Hàn   | `10604` | `10704` | Supertonic | Zipformer ko |

- Cổng chỉ **tự mở khi có model** của (vai, tiếng) đó trên volume; cổng đọc
  không khai phần nghe với HA và ngược lại.
- Giọng của từng tiếng chọn trong **Cài đặt → Giọng nói & Loa → "Theo từng
  tiếng"** (mỗi tiếng một mục thu gọn, có nút Nghe thử); cùng chỗ đó chỉnh
  được từng cổng (trống = theo chuẩn, `0` = tắt cổng).

1. Publish port: `ports: ["10600-10604:10600-10604", "10700-10704:10700-10704"]`
   rồi recreate container (chỉ mở dải mình dùng cũng được).
2. Firewall LAN: `deploy/firewall-c2a-ports.sh` (mở các cổng trên cho IP HA).
3. Model: tiếng Việt + Anh tải bằng `scripts/download_stt_model.py`,
   `download_stt_en_model.py`, `download_kokoro_model.py`; Nhật/Trung/Hàn:
   `scripts/download_stt_da_ngu.py` (nghe) + `scripts/download_tts_da_ngu.py`
   (đọc — Kokoro đa ngữ cho Trung, Supertonic cho Nhật+Hàn).
4. HA → *Add Integration → Wyoming Protocol*: host = IP gateway, port theo
   bảng — mỗi cổng một integration, thêm đúng những tiếng cần dùng.
5. Assist pipeline: chọn entity STT/TTS của đúng tiếng đó.
6. Tắt cả cụm: `voice.wyoming_server.enabled = false`; tắt/đổi từng cổng:
   `voice.wyoming_server.tts_port_vi` / `stt_port_ja` / … (hoặc UI);
   ngôn ngữ tin nhắn thoại của bot: `voice.stt.language` = `auto`|`vi`|`en`.

### 4.2d. Điều khiển loa Google Cast (âm lượng / bật / tắt)

Mỗi dòng loa Cast trong Cài đặt có: **thanh âm lượng** (kéo-thả — đặt ngay và lưu
làm mặc định mỗi lần phát), **⏻ bật** (đánh thức loa), **⏹ dừng phát**, **🔌 tắt**
(thoát app đang cast — như `media_player.turn_on/turn_off` của HA). API tương ứng:
`POST /api/voice/speakers/{id}/volume {"level":0..100,"save":true}`,
`.../control {"action":"pause|resume|stop|on|off|mute|unmute"}`, `GET .../status`.

> Loa phát KHÔNG ra tiếng dù "Kiểm tra" xanh? 99% là chưa điền **URL công khai
> của gateway** (mục 4.2) — loa phải tự tải file audio từ địa chỉ đó.

### 4.2e. Image GPU (tuỳ chọn, tag `:gpu`)

`ghcr.io/tritue2011/chatgpt2api:gpu` (amd64) cài sẵn torch CUDA — VieNeu tự chạy
PyTorch/GPU (`voice.tts.vieneu_backend` mặc định `auto`), hợp khi phục vụ nhiều
luồng đọc đồng thời. Nặng hơn image thường ~6GB; host cần driver NVIDIA +
`nvidia-container-toolkit` + compose `gpus: all`. Một phiên chat đơn lẻ thì image
thường (CPU 1 nhân, RTF < 1) là đủ.

### 4.2f. Kiểm chất lượng phát âm và chất lượng nghe (khi thêm giọng / model mới)

Hai bệ đo tự động, dùng khi bạn thêm giọng hoặc đổi model và muốn biết nó đọc đủ
phụ âm hay không — thay vì nghe thử từng giọng bằng tai.

```bash
# ĐỌC (TTS): mỗi câu đọc lại 3 lần rồi cho STT của chính máy nghe lại
docker exec c2a /app/.venv/bin/python /app/scripts/kiem_phat_am.py vi --lap 3
docker exec c2a /app/.venv/bin/python /app/scripts/kiem_phat_am.py en zh ja ko --lap 3

# NGHE (STT): tiếng NGƯỜI kèm bản chữ đúng — cần tải bộ FLEURS trước (xem docstring)
docker exec c2a /app/.venv/bin/python /app/scripts/kiem_nghe.py vi --so 200
```

Bảng đọc phủ đủ phụ âm đầu và phụ âm cuối tiếng Việt, cộng 10–16 câu cho mỗi
tiếng còn lại. Bốn điều cần biết khi đọc kết quả:

- **Câu mà ≥70% giọng đều sai** được tách riêng và không dùng để xếp hạng: đó
  hoặc là STT nghe không ra, hoặc cả họ model đọc kém. Muốn phân định thì đo một
  **họ giọng khác** (ví dụ Piper so với NghiTTS) — chữ nào chỉ một họ sai thì lỗi
  ở họ đó.
- **Chữ đồng âm không tính là rụng.** Tiếng Việt Bắc bộ: d/gi/r cùng đọc /z/, s/x
  cùng /s/, ch/tr cùng /tɕ/. Máy nghe "da" ra "ra" là âm vẫn còn, chỉ khác chữ.
  Tiếng Nhật cũng vậy với kana: máy nghe 今日 ra きょう là đọc đúng mà ghi khác
  chữ, nên bảng nhận cả hai cách viết.
- **Cột "âm xát"** đo riêng độ rõ của /s/ (chữ x, s). Cần cột này vì vòng
  TTS→STT chỉ bắt được âm *bị thay* hoặc *bị mất*; âm còn mà đọc quá nhẹ thì máy
  vẫn nghe ra trong khi tai người đã thấy lệch ("xin" nghe như "chin"). Số này
  chỉ đáng tin ở mức thứ tự và mức thô mạnh/yếu.
- **Xếp hạng theo cột "lượt hụt", đừng theo riêng cột "đúng".** Cột đúng lấy đa
  số các lần đọc lại nên nó bão hoà: đọc lại càng nhiều lần thì các giọng càng
  dồn về cùng một điểm. Đo giọng Nhật ra bốn giọng cùng 12/13 mà lượt hụt là
  2/55 với 10/55 — chênh năm lần.

**Giọng mặc định của tiếng Nhật là giọng 5 (Nữ F1)**, chọn theo đúng bảng đó
(2/55 lượt hụt, so với 10/55 của giọng 0). Tiếng Hàn giữ giọng 0. Đổi trong
Cài đặt → Giọng nói & Loa → Theo từng tiếng.

Kết quả đo ngày 14/08/2026 nằm trong `services/voice/chat_luong_giong.py`, và
hiện thành nhãn ngay trong ô chọn giọng ("đọc rõ" / "⚠ rụng gi, k, d · âm xát
yếu") nên không cần tra tài liệu mới biết giọng nào tốt. Đã đo **52 giọng tiếng
Việt** của cả ba họ; muốn chắc ăn thì chọn theo thứ tự này:

| Họ giọng | Đọc đủ 33/33 âm | Giọng kém nhất | Gợi ý |
|---|---|---|---|
| **VieNeu** (48 kHz) | 3/14 | 30/33 | Thái Sơn · Mai Anh · Thục Đoan đọc trọn, và cả họ không giọng nào tệ |
| **Piper** | 10/19 | 28/33 | ngochuyen · ngocngan3701 · tranthanh3870 (âm xát mạnh) |
| **NghiTTS** | 2/19 | 26/33 | chỉ manh-dung và viet-thao; các giọng khác rụng âm rõ |

Âm /k/ (chữ "kem") là chỗ yếu chung của mọi họ — 8/14 giọng VieNeu, 13/19 giọng
NghiTTS làm rụng nó, riêng Piper thì 15/19 giọng đọc đúng.

**Chất lượng NGHE đo được** (150 bản thu tiếng người mỗi tiếng — cùng bộ, ba
đường: model tại chỗ trước 15/08, model tại chỗ **hiện nay**, và máy GPU):

| Tiếng | Tại chỗ (cũ) | **Tại chỗ (nay)** | GPU | Bỏ trắng: cũ → nay → GPU |
|---|---|---|---|---|
| Việt | 9,3% sai từ | 9,3% sai từ | 8,4% | 0 → 0 → 0 |
| Anh | 16,6% sai từ | 16,6% sai từ | **4,5%** | **11/150** → 11/150 → **0** |
| Trung | 13,6% sai ký tự | **10,2%** | 10,0% | 0 → 0 → 0 |
| Nhật | 9,8% sai ký tự | **7,0%** | 5,1% | 0 → 0 → 0 |
| Hàn | 55,5% sai ký tự | **6,2%** | 2,8% | **67/150** → **0** → 0 |

Cột giữa đổi được nhờ **SenseVoice** — một model làm cả Trung/Nhật/Hàn, thay ba
model Zipformer riêng (`scripts/download_stt_da_ngu.py --sense`; tải 228 MB thay
cho 1,3 GB, còn trên đĩa thì 229 MB so với 295 MB). Đáng kể nhất là tiếng Hàn:
model cũ **trả rỗng 45% số đoạn** mà không báo lỗi, nay hết hẳn. Chưa tải
SenseVoice thì hệ thống tự dùng ba model cũ, không đứt gì.

Hai thứ đã đo và **quyết định không đổi**: model tiếng Việt 70.000 giờ mới
(`sherpa-onnx-zipformer-vi-2025-04-20`) đo ra 9,8% sai từ, tức không hơn model
đang chạy; và tiếng Anh giữ Parakeet vì bộ dò ngôn ngữ vi/en đang dựa vào độ tự
tin của model transducer, mà SenseVoice không trả số đó (dù riêng độ chính xác
thì SenseVoice hơn: 8,2% sai từ, không bỏ trắng bản nào — ai cần thì bật bằng
`voice.stt.sense_tieng = "zh,ja,ko,en"`).

Hai chỗ cần lưu ý khi làm phụ đề:

- **Tiếng Anh bỏ trắng 7% đoạn** — Parakeet không trả chữ nào mà cũng không báo
  lỗi, nên phụ đề mất dòng một cách im lặng. Đây là lý do có đường
  faster-whisper trên máy GPU ([docs/NGHE_GPU.md](docs/NGHE_GPU.md)): mặc định
  chỉ tiếng Anh và tiếng Hàn đi GPU — đúng hai tiếng bỏ trắng — còn tiếng Việt
  giữ tại chỗ vì hai đường gần như hoà nhau (9,3% so với 8,4%).
- **Tiếng Hàn 55,5% là do lệch miền, không phải model hỏng.** Model học trên
  tiếng nói hội thoại câu ngắn (KsponSpeech) nên đọc thoại phim khá hơn số này
  nhiều, còn giọng đọc bản tin câu dài thì hay trả rỗng. Đã kiểm: model đọc đúng
  bộ thử của chính nó, cắt ngắn audio vẫn rỗng, và bản fp32 cho kết quả y hệt bản
  int8 — nên không phải lỗi cấu hình bên ta.

### 4.2g. Giọng giữ thanh điệu: Kokoro Việt (`kokorovi:`) và ZeroTTS (`zerotts:`)

Nhiều giọng cũ đọc **mất thanh**: thanh ngang đọc trầm nên nghe thành huyền
(«nay→này», «may→mày»), thanh nặng thiếu độ hụt nên nghe thành hỏi («chị→chỉ»).
Hai họ giọng dưới đây được thêm để chữa đúng chỗ đó.

**Tải model** (không nằm trong image, tải một lần vào volume):

```bash
# Kokoro Việt — model chung ~326 MB + mỗi giọng ~0,5 MB
docker exec -it c2a python scripts/download_kokoro_vi.py              # chỉ giọng hung_thinh
docker exec -it c2a python scripts/download_kokoro_vi.py mai_linh     # thêm một giọng
docker exec -it c2a python scripts/download_kokoro_vi.py --all        # cả 14 giọng
docker exec -it c2a python scripts/download_kokoro_vi.py --list       # xem giọng nào đã có

# ZeroTTS — cả gói ~900 MB, đủ 8 giọng
docker exec -it c2a python scripts/download_zerotts.py
docker exec -it c2a python scripts/download_zerotts.py --check        # chỉ kiểm tra
```

Tải xong vào **Cài đặt → Giọng nói & Loa → Tiếng Việt**, chọn giọng `kokorovi:<mã>`
hoặc `zerotts:<mã>` rồi bấm **Nghe thử**. Chưa tải thì giọng vẫn hiện trong danh
sách nhưng nút nghe thử báo đúng lệnh cần chạy.

**Đo ngày 15/09/2026 trên máy chủ** (10 nhân Xeon E5 v4). Mỗi giọng đọc 18 câu
thường, STT của máy nghe lại, đếm âm tiết đúng vần mà sai dấu thanh. Mốc của
chính STT trên 120 bản thu giọng người thật (FLEURS) là 0,14%.

| Họ giọng | Sai thanh (câu thường) | Đọc đúng dãy «ma má mà mả mã mạ» | Tốc độ (RTF, <1 là nhanh hơn thời gian thực) |
|---|---|---|---|
| **Kokoro Việt** (`kokorovi:`) | **0,04%** | **45%** | 0,75–0,80 (2 luồng) |
| **ZeroTTS** (`zerotts:`) | **0%** | 30% | 1,1–1,3 (4 luồng) — chậm hơn thời gian thực |
| VieNeu (`vieneu:`) | 0,65% | 23% | 1,25–1,53 |
| Piper (`manhdung`…) | 0,73% | 4% | 0,27–0,43 |
| NghiTTS (`nghi:`) | 0,80% | 4% | nhanh |

**Nên chọn giọng nào:**

- **Đọc loa, trả lời thoại hằng ngày:** `kokorovi:hung_thinh` — giữ thanh tốt nhất
  (dãy sáu thanh chỉ sai 1/11) và vẫn nhanh hơn thời gian thực. Giọng nữ:
  `kokorovi:mai_linh` (sai 3/12).
- **Tin nhắn thoại, không cần tức thì:** `zerotts:baotrang`, `zerotts:maichi` hoặc
  `zerotts:huuduc` — không sai thanh, không rụng âm; nhưng CPU này đọc chậm hơn
  thời gian thực nên không hợp phát loa theo dòng chảy.
- So với giọng mặc định `manhdung`: Kokoro Việt **chậm hơn khoảng gấp đôi** (câu
  ngắn ~1,9 giây so với ~1,2 giây) nhưng **ít sai thanh hơn khoảng 18 lần**.

Ghi chú kỹ thuật:

- Kokoro Việt phiên âm bằng **vig2p** nhưng đưa CẢ MỆNH ĐỀ vào sea-g2p thay vì
  từng từ: tách từng từ thì từ không dấu trùng tiếng Anh bị đọc kiểu Anh («máy
  bay» ra `beɪ`, «may» ra `meɪ`). Số, giờ, ngày được chuẩn hoá thành chữ trước.
- espeak `vi` của Piper/NghiTTS phiên ĐỦ sáu thanh (đo trên 7.500 âm tiết) — giọng
  cũ mất thanh do chính model, nên thay bộ phiên âm cho giọng cũ không chữa được.
- Số luồng ZeroTTS: `voice.tts.zerotts_threads` (mặc định 4 — đo trên máy chủ: 2
  luồng RTF 1,7, 8 luồng 2,3). Kokoro Việt dùng chung `voice.tts.num_threads`.

### 4.3. Khai báo loa

Phần **📢 Loa đã kết nối**. Ba kiểu:

| Kiểu | Điền gì | Ghi chú |
|---|---|---|
| **Google Cast** | IP của loa/Nest/Android TV | Nối thẳng, không qua HA |
| **DLNA / UPnP** | `http://IP:PORT/` của loa | Không cần thư viện ngoài |
| **Qua Home Assistant** | `media_player.xxx` | Cho thiết bị lạ mà HA đã nhận |

Nút **Nhập từ Home Assistant** kéo sẵn mọi `media_player` về, đỡ gõ tay.

Ba nút mỗi dòng: **🔌 Kiểm tra** (chạm tới loa được không) · **▶️ Phát thử** (đọc một
câu) · **🗑 Xoá**.

> ⚠️ Container chạy mạng bridge nên **không tự dò được loa** (mDNS/SSDP không qua
> được). Phải nhập IP tay — hạn chế của mạng Docker, không phải lỗi.

**Đặt tên loa như đặt tên người**: “loa phòng khách”, “loa bếp”. Sau đó ra lệnh tự
nhiên: *“phát ra loa phòng khách nhắc cả nhà ăn cơm”*.

### 4.4. Cách dùng hằng ngày

- **Nói thay vì gõ**: gửi tin ghi âm cho bot Telegram/Zalo cá nhân → hệ thống chuyển
  thành chữ rồi xử lý **y như tin nhắn chữ**.
- **Nghe thay vì đọc**: bật quyền `🔉 Trả lời bằng giọng nói` cho khung chat (Phần 6)
  → bot gửi kèm file âm thanh.
- **Phát ra loa**: cần quyền `📢 Được ra lệnh phát loa`. Không nói rõ loa nào thì bot
  **liệt kê danh sách và hỏi lại**, không tự chọn hộ.

---

### 4.4b. Tab Dịch — dịch chữ, video, phụ đề (không tốn lượt AI)

`▸ Studio → Dịch`. Toàn bộ chạy bằng máy dịch + bộ nghe **trong nhà**, không gọi
LLM, không qua bên thứ ba. Chi tiết kỹ thuật: [docs/DICH_MAY_TU_CHU.md](docs/DICH_MAY_TU_CHU.md).

**Tab "Dịch":**

| Bỏ vào | Nhận lại | Ghi chú |
|---|---|---|
| Chữ dán vào ô | Bản dịch ngay trên trang | Nút chép sẵn |
| **Link YouTube** | Tệp phụ đề `.srt` đã dịch | Lấy phụ đề có sẵn — vài chục giây, không tải video |
| Ảnh | Bản dịch chữ trong ảnh | Kèm phần chữ gốc đọc được để đối chiếu |
| PDF / Word / Excel / PowerPoint | Bản dịch (tệp cùng định dạng nếu dựng lại được) | Dài quá thì đóng `.docx` |
| **Phụ đề `.srt` / `.vtt`** | `.srt` đã dịch | **Nhanh + chuẩn nhất cho phim** (~1 phút cho phim 2 giờ) |
| **Video / âm thanh** (≤ 4 GB, ≤ 150 phút) | `.srt` **hoặc** bản chữ lời thoại | Máy tự nghe; phim 2 giờ mất ~20–40 phút tuỳ tiếng |

- **Cặp ngôn ngữ**: Việt ↔ Anh / Trung / Nhật / Hàn. Máy tự nhận chiều: nguồn
  tiếng Việt thì dịch sang tiếng kia, ngược lại về tiếng Việt.
- Kết quả video luôn kèm **bản chữ-trên** (`phu-de-tren…`): dùng khi video đã có
  chữ in cứng ở đáy hình, phụ đề dịch nhảy lên mép trên cho khỏi đè nhau.
- Ghép phụ đề với video: đặt `.srt` **cùng tên, cùng thư mục** với video rồi mở
  bằng **VLC** / **MX Player**; hoặc CapCut → nhập phụ đề → xuất video có chữ.
- Tệp lớn được **cắt khúc 25 MB** gửi tuần tự nên đi qua domain vẫn lọt. Việc
  chậm chạy ở luồng nền và trang báo tiến độ — **đừng đóng trang** nếu muốn nhận
  kết quả (việc vẫn chạy tiếp, chỉ mất đường trả về).

**Tab "Đàm thoại"** — phiên dịch trực tiếp cho hai người: chọn cặp tiếng, hai ô
hai tiếng, ai nói tiếng nào thì bấm mic ô đó → bản dịch hiện sang ô bên kia,
tick *Đọc bản dịch* thì máy đọc thành tiếng (đủ 5 tiếng, giọng chọn ở mục 4.2).
Mỗi lượt ≤ 90 giây, bấm-nói-bấm dừng. **Mic chỉ hoạt động qua HTTPS** — mở bằng
IP LAN thì trình duyệt chặn micro (luật của trình duyệt, không phải lỗi máy).

> Bot chat cũng làm được: `/dich <chữ>`, `/dich <link YouTube>`, hoặc gửi tệp
> video/âm thanh kèm chú thích `/dich` (Zalo cá nhân nhận tệp ≤ 250 MB).

## 5. Kết nối bot Telegram / Zalo

Vào `▸ Hệ thống → Cài đặt → Kênh chat`, chọn tab kênh rồi tab con **⚙️ Cài đặt kênh**.

### 5.1. Telegram

1. Nhắn `@BotFather` trên Telegram → `/newbot` → lấy token.
2. Dán token vào **Danh sách bot Telegram**. Lưu xong, tên bot hiện ra ngay bên dưới.
3. Điền **Webhook URL** ở card Cloudflare (phải HTTPS).
4. **Chat IDs**: để trống = ai nhắn cũng trả lời. Điền = chỉ những chat đó.
5. Nhắn cho bot chữ `/id` để lấy Chat ID.

### 5.2. Zalo Bot

Tương tự Telegram, dùng chung Webhook URL. Lưu ý: trong **nhóm**, Zalo chỉ chuyển
tin cho bot khi tin đó **tag bot** — quy định nền tảng, không cấu hình được.

### 5.3. Zalo Cá Nhân

Tab con **🔑 Tài khoản & QR** → bấm tạo mã QR → quét bằng app Zalo. Cookie được lưu
nên khởi động lại vẫn đăng nhập. Tab này cũng có webhook per-account, proxy, danh bạ
để lấy Thread ID.

Trong **nhóm**: bot trả lời thì **tag đúng người vừa hỏi** (họ nhận thông báo có phản
hồi); gửi `@All` thì chỉ tag cả nhóm. Tag bot bằng tên hiển thị nhiều chữ vẫn nhận
lệnh, vd `@Bot Ben Bắp /dich xin chào`.

### 5.4. Mỗi bot có gì riêng

Trên thẻ từng bot: model AI riêng, Chat IDs riêng, **Thread ID admin riêng**, và ô
**⚡ Điều khiển nhà cục bộ** — bật thì lệnh bật/tắt thiết bị chạy thẳng không vòng
qua AI: phản hồi tức thì, vẫn chạy khi không có nhà cung cấp AI nào.

---

## 6. Lọc chức năng theo thread

Nơi quyết định **ai được làm gì** — phần quan trọng nhất khi cho người khác dùng
chung bot.

Vị trí: `▸ Cài đặt → Kênh chat → [chọn kênh] → 🎚️ Lọc thread`.

### 6.1. Quy tắc nền

- Chat **không có** trong danh sách → được phép tất cả (tới khi bạn thêm nó vào).
- Chat **có** trong danh sách → **chỉ** được các nhóm chức năng đã tích.
- Tích **rỗng** → chặn hết công cụ, chỉ còn trò chuyện.
- Không có quyền cho việc được yêu cầu → bot **im lặng**, không giải thích.
- **Ngoại lệ 📷 Camera nhà**: phải **tích mới có**. Chat chưa có trong danh sách
  vẫn **không** xem được camera, dù dòng đầu nói "được phép tất cả" — camera nhìn
  vào trong nhà, nên người lạ vừa nhắn bot lần đầu không được xin ảnh. Cũng vì
  thế nó **không tự bật** cho các bộ lọc lưu từ trước.

### 6.2. Các nhóm chức năng

🏠 Nhà (HA) · 🖥️ Server · 🎨 Ảnh · 🎬 Video · 🎵 Nhạc · 🌐 Web · 💻 Code · 🧠 Ghi nhớ ·
📚 RAG/tài liệu · 📝 PDF→Word · 📄 Tài liệu Office · 🔌 Thiết bị ·
**📷 Camera nhà** · 🧾 Tổng hợp · ⏰ Nhắc hẹn · 🧩 Skill/Workflow · 📖 Wiki ·
📒 Danh bạ · ☁️ Kho đám mây · **🔉 Trả lời bằng giọng nói** ·
**📢 Được ra lệnh phát loa** · 📚 Giáo viên · 📘 Đăng Facebook Page

> **Cập nhật (2026-07-25) — Trả lời bằng giọng nói = CHỈ giọng, không kèm chữ.**
> Khi tích `🔉 Trả lời bằng giọng nói`, bot **chỉ gửi âm thanh** (trước đây gửi cả
> chữ lẫn tiếng). Nếu TTS lỗi / chưa tải model, bot **tự gửi lại bằng chữ** để không
> mất câu trả lời. Áp cho **mọi nơi** bật quyền này (cả nhóm lẫn từng người). Riêng
> tin có **nút bấm chọn số** thì vẫn gửi chữ (kèm giọng, để còn bấm chọn).

### 6.3. Hai tầng: nhóm và từng người

Với thread là **nhóm chat**, thêm được **User ID** để giới hạn riêng từng người.
Quy tắc chung: quyền của người = giao của quyền nhóm và quyền người.

**Riêng quyền giọng nói thì người thắng nhóm**: nhóm không bật `🔉 Trả lời bằng
giọng nói` nhưng một người bật thì **chỉ người đó** nhận âm thanh — trong nhóm đông,
ai thích nghe thì nghe, không phiền người khác.

### 6.3b. Ba tầng với nhóm bật Topics (Telegram)

> **Mới (2026-07-26).** Nhóm Telegram bật **Topics** (nhóm dạng diễn đàn) có thêm
> tầng giữa: **Nhóm → 🧵 Topic → 👤 User**. Nhóm **không** bật Topics thì **giữ
> nguyên 2 tầng** như cũ, không phải sửa gì.

Vị trí: trong mỗi dòng thread loại **Nhóm** (kênh Telegram) → khối
`🧵 Lọc theo Topic (nhóm bật Topics)` → **+ Thêm topic**.

**Lấy Topic ID**: gõ `/id` **ngay trong topic đó** — bot trả về thêm dòng
`🧵 Topic ID`. Topic "General" không có ID → tính như nhóm thường.
Tên topic phải **gõ tay** (Bot API của Telegram không trả tên topic).

Quy tắc từng tầng — mỗi tầng là **tập con** của tầng trên:

| Tình huống | Quyền hiệu lực |
|---|---|
| Topic **chưa** thêm vào danh sách | Hưởng **full quyền của nhóm** |
| Topic đã thêm | **giao(quyền nhóm, quyền topic)** — tích thứ nhóm không cho thì vô hiệu |
| Topic **không có** user nào | **Ai nhắn cũng được**, hưởng full quyền topic |
| Topic có user | **giao(nhóm, topic, user)** |
| User đặt ở **cấp nhóm** | Áp cho **mọi topic** chưa có bản ghi riêng cho người đó |

Mỗi topic còn có **riêng**: 🤖 Model AI · ⚡ Đường tắt điều khiển nhà ·
🏷️ Bắt buộc tag bot mới trả lời · 🔗 Webhook chuyển tiếp. Nhờ vậy làm được
**mỗi topic một loại log** (topic A đẩy webhook này, topic B webhook khác) và
**mỗi topic một bộ chức năng** trong cùng một nhóm.

Thứ tự tra cứu khi có tin đến (hẹp thắng rộng):
`user trong topic → user cả nhóm → topic → cả nhóm`.

Bot cũng **trả lời ngay trong topic** đã nhận tin (chữ, ảnh, video, âm thanh,
tệp) — không còn dồn hết về topic General.

### 6.4. Giọng đọc · Tắt TTS · STT theo từng phạm vi

Ngay dưới mỗi dòng thread (nhóm / cá nhân) và mỗi **User** có một khối cấu hình giọng
**RIÊNG**, lưu độc lập (khác phần tích nhóm chức năng, lưu ở `voice_sessions.json`):

- **🔊 Giọng đọc** — CHỈ hiện khi đã tích `🔉 Trả lời bằng giọng nói`. Bỏ trống =
  đọc theo **persona** đang bật; chọn 1 giọng = ép **giọng đọc** đó. Lưu ý: đây là
  **giọng đọc** (âm sắc), còn **giọng văn / cách xưng hô** vẫn theo persona. Chọn lại
  mục `(theo persona)` để bỏ ép giọng.
- **🔇 Tắt giọng nói (TTS)** — chặn hẳn đọc thành tiếng cho phạm vi này (kể cả khi
  quyền `🔉 Trả lời bằng giọng nói` đang bật ở tầng khác).
- **🎙️ STT tiếng Anh** — khi user gửi ghi âm: bỏ tích = nghe **tiếng Việt** (mặc
  định), tích = nghe **tiếng Anh**.

Thứ tự áp dụng: **User-trong-nhóm → Nhóm / chat 1-1 → Bot → Kênh** (cụ thể thắng tổng
quát). Nên đặt ở dòng đã chọn **đúng tài khoản/bot** — dòng "mọi bot / mọi tài khoản"
có thể không khớp lúc chạy.

**Giọng cho Admin**: mục Admin (Chat IDs) không có khối giọng riêng. Muốn chỉnh
giọng/STT/persona cho admin → thêm **Chat ID admin thành một dòng loại "Cá nhân"**
trong tab Lọc thread (nhớ **tích đủ nhóm chức năng** để không hạn chế quyền), rồi cài
Persona + giọng ngay tại dòng đó.

### 6.5. Bắt buộc tag + Chuyển tiếp webhook (chi tiết)

**🏷️ Bắt buộc tag mới trả lời** (chỉ nhóm)

- Tắt = trả lời **mọi tin** (kể cả tin có tag).
- Bật = **chỉ trả lời khi bị tag**. Nhận diện theo **định danh bot**, KHÔNG theo tên:
  - **Telegram**: @mention theo `@username` của bot / reply vào bot / chạm chọn bot.
  - **Zalo Cá Nhân**: bấm `@` **chọn bot** trong danh sách nhóm → khớp theo **UID
    tài khoản bot**, nên **mỗi người lưu tên bot khác nhau vẫn nhận đúng**.
  - **Zalo Bot (OA)**: nền tảng chỉ đẩy tin khi đã @tag bot → tự tính là tag.
- **Không bắt buộc điền Từ khóa** nếu người dùng bấm `@` chọn bot chuẩn. Ô **Từ khóa**
  chỉ cần khi muốn bắt cả trường hợp user **gõ tên bằng chữ thường** (không dùng
  @mention thật). Gõ `@tênsai` bất kỳ (không đúng bot, không trùng từ khóa) → bot
  **không** trả lời.

**🔗 Chuyển tiếp webhook** (HA / n8n / URL bất kỳ)

- **Bật webhook ở cấp thread = ChatGPT KHÔNG trả lời** — mọi tin đẩy sang URL, **bật
  hay tắt tag đều thế** (dùng khi muốn n8n/HA xử lý thay bot).
- Ẩn/hiện phần webhook cấp **User** theo trạng thái của nhóm:

  | Trạng thái nhóm | Webhook của User |
  |---|---|
  | Bật webhook (dù bật/tắt tag) | **Ẩn hết** — thread đã đẩy tất, AI im |
  | Bật tag, tắt webhook | Hiện "🔗 webhook riêng" (+ ô URL); **ẩn** "chỉ chuyển khi tag" |
  | Tắt tag, tắt webhook | Hiện "🔗 webhook riêng" + **hiện** "🏷️ chỉ chuyển khi tag" |

- **🏷️ Chỉ chuyển webhook khi TAG bot** (cấp user): tin có tag → **CHỈ** đẩy webhook,
  AI im; tin thường (không tag) → AI trả lời như bình thường.

---

## 7. Sự cố thường gặp

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| Bot trả lời “⛔ Không được phép” | Chat chưa được cấp phép trên **đúng bot đó** | Nhắn `/id` lấy Chat ID rồi thêm vào Chat IDs của bot, hoặc tạo dòng lọc thread |
| Ảnh/âm thanh gửi ra là link hỏng | Chưa đặt **Địa chỉ truy cập hình ảnh** hoặc đang `localhost` | Điền IP thật của máy |
| Loa không phát | Chưa đặt **URL công khai của gateway**, hoặc container không chạm tới IP loa | Bấm **🔌 Kiểm tra** trên thẻ loa để biết lỗi ở đâu |
| Không tự dò thấy loa | Docker bridge chặn mDNS/SSDP | Nhập IP loa bằng tay — hành vi bình thường |
| Gửi ghi âm mà bot im | Chưa tải model STT | Chạy `download_stt_model.py`; xem ô trạng thái 🎤 |
| Bot không đọc thành tiếng | Chưa tích `🔉 Trả lời bằng giọng nói`, hoặc đã bật `🔇 Tắt giọng nói (TTS)` cho phạm vi đó | Xem Phần 6.2/6.4 |
| Bật giọng nói mà **vẫn ra chữ** | TTS lỗi / chưa tải model → bot tự fallback gửi chữ | Tải model TTS (Phần 4.1); xem ô trạng thái 🔊 |
| Nhóm bật "bắt buộc tag" mà bot không trả lời | User chỉ **gõ tên bằng chữ**, chưa bấm `@` chọn bot; hoặc **Từ khóa** chưa khớp | Bấm `@` chọn bot, hoặc điền đúng Từ khóa (Phần 6.5) |
| Bật webhook mà ChatGPT im | Đúng thiết kế: **bật webhook cấp thread = AI không trả lời** | Tắt webhook nếu vẫn muốn AI trả (Phần 6.5) |
| Bot trả lời sai/lạ | Xem nó gọi công cụ nào | `▸ Hệ thống → Agent runs` |
| Tài khoản AI báo đỏ | Token hết hạn hoặc bị giới hạn | `▸ AI Core → Tài khoản` → khôi phục |

### Xem log

```bash
docker logs -f <tên-container>
```
Hoặc trang **Quản lý nhật ký** trong giao diện.

---

## Phụ lục: API cho ứng dụng ngoài

Gateway tương thích chuẩn OpenAI — cắm thẳng vào Open WebUI, n8n, hay app bất kỳ:

```
POST /v1/chat/completions          trò chuyện
POST /v1/images/generations        sinh ảnh
POST /v1/audio/speech              chữ → tiếng nói
POST /v1/audio/transcriptions      tiếng nói → chữ
GET  /v1/models                    danh sách model
```

Đều dùng header `Authorization: Bearer <CHATGPT2API_AUTH_KEY>`.

---

## 8. Nghe nhạc YouTube / Zing ra loa (tab YouTube)

Tab **YouTube** (thanh bên, chỉ quản trị): tìm bài rồi nghe/xem ngay trên máy đang mở,
hoặc phát ra loa và tivi trong nhà. Nhạc phát ra loa **chạy trên máy chủ** — đóng
trình duyệt, tắt máy tính thì loa vẫn phát và vẫn tự sang bài kế.

### 8.1. Tìm và phát

- Chọn nguồn **YouTube**, **Zing MP3** (bài công khai, không VIP) hoặc **Link audio**
  (link MP3/AAC/FLAC/OGG/HLS trực tiếp), gõ tên bài/ca sĩ hoặc **dán link YouTube**.
- Mỗi bài YouTube có **hai nút**:

| Nút | Chưa tích loa | Đang tích loa |
|---|---|---|
| 🎧 **Nghe** (chỉ tiếng) | Nghe trên máy này | Phát ra các loa đã tích, không mở video |
| 🖥 **Xem video** | Xem video có tiếng trên trang | Phát ra loa, mở thêm video **tắt tiếng chạy theo loa** |

- Zing và link audio chỉ có nút nghe (không có video). Link audio phải tích loa.
- Thanh điều khiển: ⏮ bài trước · ⏯ · ⏭ bài kế · ⏹ dừng — hàng đợi là danh sách vừa tìm.

### 8.2. Danh sách loa & tivi

- Gộp **loa trong Sổ loa c2a** (Phần 4.3) với **media_player của Home Assistant**. Cùng
  một thiết bị (nhận ra theo mã thiết bị, không theo tên) chỉ hiện **một dòng**, mang
  **tên đặt trong Sổ loa**.
- **Ưu tiên Sổ loa:** loa Google Cast trong sổ được c2a **nối thẳng** (nhãn
  «Sổ loa c2a») — Home Assistant khởi động lại hay lỗi thì vẫn thấy loa và vẫn phát.
  c2a chưa nối được mà HA còn thấy thì tạm đi qua HA (nhãn «Sổ loa c2a qua HA»).
- Thiết bị **mất kết nối không hiện**; kết nối lại thì tự hiện. Đầu mục ghi số thiết bị
  đang mất kết nối.
- Nút 👁 ẩn thiết bị không muốn thấy; khôi phục ở mục **Đã ẩn** (gập sẵn, bấm mới mở).
- Tích một loa có thanh âm lượng riêng.

### 8.3. Mỗi loa một bài, nghe cùng một bài

- Mỗi lần phát ra các loa đang tích tạo **một nhóm**; một loa chỉ thuộc một nhóm, nên
  vừa phát chung một bài cho nhiều loa, vừa phát **mỗi loa một bài** được.
- **Tích loa nào thì thấy của loa đó**: tên bài, tiến độ, video (tua tới đúng chỗ loa
  đang phát). Các nhóm khác hiện thành nút nhỏ bên dưới — bấm để chuyển sang xem.
- **Cho loa B nghe bài đang phát ở loa A**: tích B, rồi tích A → bấm **«Cho B nghe
  cùng»** — B vào đúng bài, đúng chỗ của A.
- ⏭ ⏮ ⏹ áp cho nhóm đang xem; ⏹ khi chỉ tích vài loa của nhóm thì chỉ các loa đó dừng.

### 8.4. Tiếng trên máy đang mở trang

- **Đang phát ra loa**: máy này mặc định **tắt tiếng**. Nút **«Nghe trên máy này»** mở
  tiếng trên máy, chạy theo vị trí loa (tạm dừng/phát/sang bài theo loa); bấm lại để tắt.
- **«Nghe khi tắt màn hình»** (bật/tắt, nhớ lựa chọn, mặc định tắt):
  - **Tắt**: tắt màn hình hay chuyển sang ứng dụng khác thì tiếng trên máy dừng, mở lại
    thì phát tiếp.
  - **Bật**: vẫn nghe khi tắt màn hình, có nút điều khiển ở màn hình khoá; video trên
    trang (nếu mở) tắt tiếng và chạy theo tiếng.
- Nghe nền cần **trình duyệt** (Chrome/Safari trên điện thoại). Ứng dụng **AI Ben Bap**
  là WebView — Android tạm dừng khi chuyển ứng dụng nên tiếng tắt sau ít giây; muốn
  nghe nền thì mở trang c2a bằng Chrome.

### 8.5. Xem video

- Cỡ **Vừa** / **Rạp** (hết bề ngang) / **Thu nhỏ** (khung nổi góc màn hình, vẫn chạy
  khi cuộn trang); đổi cỡ không làm video tải lại.
- **Toàn màn hình** (nút trên thanh điều khiển của trang): điện thoại **tự xoay ngang**
  (Chrome Android), video giữ tỉ lệ 16:9 vừa khít, không bị cắt.
- Trình duyệt chặn tự phát có tiếng (điện thoại, WebView) thì khung video hiện
  **«Chạm vào video để phát có tiếng»** — chạm vào chính khung video là có tiếng.

### 8.6. Nối với Home Assistant

- Khối **Kết nối Home Assistant** (đầu tab) có **URL** (dạng `http://IP:3030/yt`) và
  **TOKEN** kèm nút sao chép. Trong HA cài tích hợp **TriTue YouTube Player** (HACS,
  bản ≥ 0.9.4 mới nhận URL có `/yt`) → thêm tích hợp → dán URL và token.
- Ô **Địa chỉ c2a trong LAN** (vd `http://172.16.10.38:3030`): loa tải nhạc qua địa chỉ
  này. Để trống thì c2a dùng địa chỉ trình duyệt đang mở hoặc địa chỉ công khai.
- **Assist của HA mở nhạc**: Cài đặt HA → Thiết bị & dịch vụ → mục trợ lý LLM đang dùng
  (vd *chatgptapi → AI Agent*) → **Cấu hình** → tích **TriTue Music** → Lưu. Rồi nói
  "mở bài người yêu cũ": trợ lý đưa 10 bài, hỏi loa (một, nhiều, tất cả) rồi phát.

### 8.7. Mở nhạc qua bot Zalo / Telegram

Khung chat cần quyền `📢 Được ra lệnh phát loa` (Phần 6); loa bot thấy là loa khung chat
đó được phép.

- **"mở nhạc Sơn Tùng"**, **"phát bài … ra loa phòng khách"**, hoặc dán link YouTube →
  bot hiện **10 bài** → chọn bài → chọn **loa** (một loa, **Tất cả loa**, hoặc gõ nhiều
  tên: `phòng khách, bếp`). Nói sẵn loa trong câu thì chọn bài xong là phát luôn.
- **"tạm dừng nhạc"**, **"bài kế"** / **"bài trước"**, **"dừng nhạc ở bếp"** — nhiều nhóm
  loa đang phát mà không nêu loa thì bot hỏi lại nhóm nào, không đoán.
- **"loa nào đang phát bài gì"** — từng loa: bài, tới phút nào, bài mấy trong hàng đợi.

