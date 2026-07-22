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

---

## 1. Chạy lần đầu

### 1.1. Cần gì trước khi bắt đầu

| Thứ | Bắt buộc? | Ghi chú |
|---|---|---|
| Docker + Docker Compose | ✅ | Bản mới bất kỳ |
| RAM | ✅ | Tối thiểu 2 GB; bật giọng nói local nên có 4 GB |
| Ổ đĩa | ✅ | ~10 GB cho image (có sẵn Chrome để tự động hoá web) |
| Tài khoản AI | ✅ | ít nhất một: ChatGPT, Gemini, Claude… |
| Domain HTTPS | ❌ | chỉ cần khi dùng bot Telegram/Zalo (xem Cloudflare Tunnel) |

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
      - "10600:10600"  # Wyoming multi — TTS+STT vi/en (1 port; HA khác host; đừng bind 127.0.0.1)

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
| `10600` / `3001` | **Không** bind `127.0.0.1` nếu Home Assistant / client nằm máy khác trong LAN (`10600` = Wyoming multi vi/en) |

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
       image: ghcr.io/<tên-tổ-chức>/chatgpt2api:latest
       container_name: c2a
       restart: unless-stopped
       ports:
         - "3030:80"
         - "6080:6080"      # noVNC — đặt VNC_PASSWORD; siết 127.0.0.1 nếu chỉ SSH tunnel
         - "3001:3001"      # zalo — LAN (HA có thể khác host)
         - "10600:10600"    # Wyoming multi vi/en — HA khác host (không bind 127.0.0.1)
       volumes:
         - /opt/c2a-data:/app/data
       environment:
         CHATGPT2API_AUTH_KEY: your_secret_key_here
         CAPTCHA_SOLVER_API_KEY: your_secret_key_here
         VNC_PASSWORD: your_vnc_password
         STORAGE_BACKEND: json
   ```

   > Repo private thì Portainer cần đăng nhập registry trước: **Registries** →
   > **Add registry** → chọn **GitHub Container Registry**, điền username + Personal
   > Access Token có quyền `read:packages`.

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
# Giọng đọc Piper — gói tối thiểu ~60 MB, hoặc --pack full cho cả 19 giọng (~1.2 GB)
python scripts/download_piper_voices.py --pack minimal

# Model nghe (nhận dạng giọng nói tiếng Việt) ~97 MB
python scripts/download_stt_model.py

# (Tuỳ chọn) VieNeu-TTS v3 Turbo — giọng 48 kHz tự nhiên hơn hẳn Piper, đọc
# được câu trộn Anh–Việt. Chọn giọng dạng "vieneu:Phạm Tuyên" trong WebUI.
python scripts/download_vieneu_model.py

# (Tuỳ chọn) Nghe tiếng Anh — NVIDIA Parakeet-TDT 0.6B (~600 MB).
# Bật bằng config voice.stt.language = "en" hoặc form field language=en.
python scripts/download_stt_en_model.py

# (Tuỳ chọn) Giọng đọc tiếng Anh Kokoro-82M — 11 giọng Anh-Mỹ/Anh-Anh,
# chọn dạng "kokoro:af_sky" trong WebUI (chỉ đọc tiếng Anh). Script TỰ DÒ CPU:
# có VNNI (Xeon gen2 2019+, Core gen11+, Ryzen 7000+) → bản int8 (~100 MB,
# nhanh hơn); CPU cũ chỉ AVX2 → bản fp32 (~320 MB, vì int8 thiếu VNNI chậm
# hơn 2.5x). Ép tay: --int8 / --fp32.
python scripts/download_kokoro_model.py
```

File về `data/piper/`, `data/stt/`, `data/hf/`, `data/stt-en/`, `data/kokoro/`.
**Không** nằm trong image nên cập nhật image không mất, và image không nặng thêm.

### 4.2. Cài đặt trong `▸ Hệ thống → Cài đặt → Giọng nói & Loa`

| Ô | Ý nghĩa |
|---|---|
| **Backend đọc (TTS)** | `Tự động` (khuyên dùng) · `Chỉ local` · `Chỉ Wyoming` · `Tắt` |
| **Giọng đọc** | Chọn trong các giọng đã tải về. Giọng `vieneu:*` = VieNeu 48 kHz (Việt + Anh xen kẽ); `kokoro:*` = tiếng Anh; còn lại = Piper. Giọng VieNeu/Kokoro lỗi sẽ tự rơi về Piper để trợ lý không bao giờ "câm" |
| **Wyoming TTS / STT** | Tuỳ chọn — trỏ tới máy chủ giọng nói sẵn có trong nhà |
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

Gateway CÓ SẴN **một Wyoming multi** (bật mặc định, port `10600`) — pattern giống
[wyoming-microsoft-stt](https://github.com/hugobloem/wyoming-microsoft-stt) /
[wyoming-microsoft-tts](https://github.com/hugobloem/wyoming-microsoft-tts):
**1 cổng, 1 integration**, TTS+STT đa ngôn ngữ, streaming "chữ tới đâu đọc tới đó".
Không cần container tiếng nói riêng (vieneu-wyoming / wyoming-stt / piper).

| Cổng | Vai trò | TTS | STT |
|------|---------|-----|-----|
| `10600` | Multi vi+en | VieNeu / Piper / Kokoro | Zipformer (vi) + Parakeet (en) |

- **STT multi** (đủ 2 model + `voice.stt.language: auto`): auto-detect (thử vi rồi en),
  **bỏ qua** language picker HA — giống microsoft-stt multi.
- **STT cố định**: đặt `voice.stt.language` = `vi` hoặc `en`.
- **TTS**: chọn giọng trong pipeline (Kokoro cho Anh, VieNeu/Piper cho Việt).

1. Publish port: `ports: ["10600:10600"]` rồi recreate container.
2. Firewall LAN: `deploy/firewall-c2a-ports.sh` (mở **10600** cho IP Home Assistant).
3. Model EN (tuỳ chọn multi): `scripts/download_kokoro_model.py` +
   `scripts/download_stt_en_model.py`. Chỉ có VI thì STT/TTS vẫn chạy tiếng Việt.
4. HA → *Add Integration → Wyoming Protocol*: host = IP gateway, port = **`10600`**
   (chỉ **một** integration).
5. Assist pipeline: chọn STT/TTS từ entity đó; pipeline Việt chọn giọng VieNeu/Piper,
   pipeline Anh chọn Kokoro (cùng server).
6. Tắt/đổi: `voice.wyoming_server.enabled = false`; cổng: `.port` (mặc định 10600);
   STT multi/cố định: `voice.stt.language` = `auto` | `vi` | `en`.

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

### 6.2. Các nhóm chức năng

🏠 Nhà (HA) · 🖥️ Server · 🎨 Ảnh · 🎬 Video · 🎵 Nhạc · 🌐 Web · 💻 Code · 🧠 Ghi nhớ ·
📚 RAG/tài liệu · 📝 PDF→Word · 🧾 Tổng hợp · ⏰ Nhắc hẹn · 🧩 Skill/Workflow ·
📖 Wiki · 📒 Danh bạ · **🔉 Trả lời bằng giọng nói** · **📢 Được ra lệnh phát loa**

### 6.3. Hai tầng: nhóm và từng người

Với thread là **nhóm chat**, thêm được **User ID** để giới hạn riêng từng người.
Quy tắc chung: quyền của người = giao của quyền nhóm và quyền người.

**Riêng quyền giọng nói thì người thắng nhóm**: nhóm không bật `🔉 Trả lời bằng
giọng nói` nhưng một người bật thì **chỉ người đó** nhận âm thanh — trong nhóm đông,
ai thích nghe thì nghe, không phiền người khác.

### 6.4. Hai tuỳ chọn khác của mỗi thread

- **🏷️ Bắt buộc tag mới trả lời** — cho nhóm đông, tránh bot chen mọi câu.
- **🔗 Chuyển tiếp webhook** — đẩy tin sang HA/n8n. Cấp thread = cả nhóm chung URL;
  cấp người = mỗi người một URL riêng.

---

## 7. Sự cố thường gặp

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| Bot trả lời “⛔ Không được phép” | Chat chưa được cấp phép trên **đúng bot đó** | Nhắn `/id` lấy Chat ID rồi thêm vào Chat IDs của bot, hoặc tạo dòng lọc thread |
| Ảnh/âm thanh gửi ra là link hỏng | Chưa đặt **Địa chỉ truy cập hình ảnh** hoặc đang `localhost` | Điền IP thật của máy |
| Loa không phát | Chưa đặt **URL công khai của gateway**, hoặc container không chạm tới IP loa | Bấm **🔌 Kiểm tra** trên thẻ loa để biết lỗi ở đâu |
| Không tự dò thấy loa | Docker bridge chặn mDNS/SSDP | Nhập IP loa bằng tay — hành vi bình thường |
| Gửi ghi âm mà bot im | Chưa tải model STT | Chạy `download_stt_model.py`; xem ô trạng thái 🎤 |
| Bot không đọc thành tiếng | Chưa tích `🔉 Trả lời bằng giọng nói` cho thread/người | Xem Phần 6 |
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
