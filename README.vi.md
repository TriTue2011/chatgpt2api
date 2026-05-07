# Hướng Dẫn Cài Đặt & Sử Dụng ChatGPT2API Cho Home Assistant

ChatGPT2API biến tài khoản ChatGPT Web thành một API chuẩn OpenAI, tương thích hoàn hảo với Home Assistant và các loa thông minh như Phicomm R1 qua hệ thống giọng nói TTS.

---

## Mục Lục
1. [Cách Lấy Access Token](#1-cách-lấy-access-token)
2. [Cài Đặt Bản Đầy Đủ (Có Web UI)](#2-cài-đặt-bản-đầy-đủ-có-web-ui)
3. [Cài Đặt Bản Lite (Không Web UI - Khuyên Dùng Cho LXC/Server)](#3-cài-đặt-bản-lite-không-web-ui)
4. [Dùng Portainer](#4-dùng-portainer)
5. [Tích Hợp Vào Home Assistant](#5-tích-hợp-vào-home-assistant)
6. [Tối Ưu Hóa Cho Loa Thông Minh TTS](#6-tối-ưu-hóa-cho-loa-thông-minh-tts)

---

## 1. Cách Lấy Access Token

1. Mở trình duyệt ẩn danh (Incognito) → Đăng nhập vào [chatgpt.com](https://chatgpt.com).
2. Mở tab mới, dán link: `https://chatgpt.com/api/auth/session`
3. Tìm chuỗi bắt đầu bằng `eyJhbG...` nằm sau `"accessToken":` → Copy toàn bộ chuỗi đó.

> ⚠️ **Không đăng xuất** ChatGPT trên trình duyệt đó, nếu không token sẽ bị hủy.

---

## 2. Cài Đặt Bản Đầy Đủ (Có Web UI)

```bash
git clone https://github.com/TriTue2011/chatgpt2api.git
cd chatgpt2api
docker compose up -d --build
```

Sau khi chạy:
- **Web quản lý**: `http://[IP]:3030`
- **API Endpoint**: `http://[IP]:3030/v1`

---

## 3. Cài Đặt Bản Lite (Không Web UI)

Bản Lite nhẹ hơn ~70%, build nhanh hơn 10 lần, phù hợp cho LXC, Proxmox, VPS nhỏ.
Tài khoản được nạp qua **biến môi trường** thay vì Web UI.

### Cách 1: Dùng Image Dựng Sẵn Từ GitHub (Nhanh nhất)

```bash
git clone https://github.com/TriTue2011/chatgpt2api.git
cd chatgpt2api

# Tạo file cấu hình
cp .env.example .env
nano .env  # Điền AUTH_KEY và TOKEN_1, TOKEN_2...

# Chạy ngay (không cần build, tải image về dùng luôn)
docker compose -f docker-compose.lite.yml up chatgpt-multi -d
```

### Cách 2: Tự Build Image

```bash
# Build image bản Lite
docker build -f Dockerfile.lite -t chatgpt2api:lite .

# Sau đó sửa docker-compose.lite.yml, thay dòng:
#   image: ghcr.io/tritue2011/chatgpt2api-lite:latest
# Thành:
#   image: chatgpt2api:lite
docker compose -f docker-compose.lite.yml up chatgpt-multi -d
```

### File `.env` Mẫu

```env
# Key xác thực (bắt buộc)
AUTH_KEY=mat_khau_cua_ban

# Cổng chạy
PORT=3030

# Token ChatGPT (lấy từ bước 1)
TOKEN_1=eyJhbGci...
TOKEN_2=eyJhbGci...  # Thêm nhiều token nếu có nhiều tài khoản
```

### Chạy Nhiều Node Riêng Biệt (Giống Gemini FastAPI)

```bash
# Mỗi node 1 cổng, 1 tài khoản
docker compose -f docker-compose.lite.yml up chatgpt-1 chatgpt-2 chatgpt-3 -d
# Node 1: http://[IP]:3031
# Node 2: http://[IP]:3032
# Node 3: http://[IP]:3033
```

---

## 4. Dùng Portainer

### Cách A: Deploy qua Stack (Đơn giản nhất)

1. Vào **Portainer** → **Stacks** → **Add Stack**.
2. Đặt tên stack (ví dụ: `chatgpt2api`).
3. Chọn **"Web editor"** và dán nội dung sau vào:

```yaml
services:
  chatgpt2api:
    image: ghcr.io/tritue2011/chatgpt2api-lite:latest
    container_name: chatgpt2api
    restart: unless-stopped
    ports:
      - "3030:80"
    volumes:
      - /opt/chatgpt2api/data:/app/data
    environment:
      - CHATGPT2API_AUTH_KEY=mat_khau_cua_ban
      - CHATGPT_TOKEN_1=eyJhbGci...TOKEN_1...
      - CHATGPT_TOKEN_2=eyJhbGci...TOKEN_2...
```

4. Bấm **Deploy the stack**.

### Cách B: Deploy Nhiều Node Qua Stack

```yaml
services:
  chatgpt-1:
    image: ghcr.io/tritue2011/chatgpt2api-lite:latest
    container_name: chatgpt2api-1
    restart: unless-stopped
    ports:
      - "3031:80"
    volumes:
      - /opt/chatgpt2api/data-1:/app/data
    environment:
      - CHATGPT2API_AUTH_KEY=mat_khau_cua_ban
      - CHATGPT_TOKEN_1=eyJhbGci...TOKEN_1...

  chatgpt-2:
    image: ghcr.io/tritue2011/chatgpt2api-lite:latest
    container_name: chatgpt2api-2
    restart: unless-stopped
    ports:
      - "3032:80"
    volumes:
      - /opt/chatgpt2api/data-2:/app/data
    environment:
      - CHATGPT2API_AUTH_KEY=mat_khau_cua_ban
      - CHATGPT_TOKEN_1=eyJhbGci...TOKEN_2...
```

> 💡 **Mỗi node** có thể dùng chung **API Key** nhưng có **Token** và **cổng** khác nhau.

---

## 5. Tích Hợp Vào Home Assistant

1. Vào **Settings → Devices & Services → Add Integration**.
2. Tìm và cài **OpenAI Conversation**.
3. Điền:
   - **API Key**: `mat_khau_cua_ban` (khớp với `AUTH_KEY` trong `.env`)
   - **Base URL**: `http://[IP_MÁY_CHỦ]:3030/v1`
4. Bấm **Submit**. Chọn model `auto` hoặc `gpt-4o`.

---

## 6. Tối Ưu Hóa Cho Loa Thông Minh TTS

Vào **Settings → Voice Assistants → [Trợ lý của bạn] → Instructions**, dán:

> *"Bạn là trợ lý ảo nhà thông minh. Hãy trả lời cực kỳ ngắn gọn, tự nhiên và giống văn nói của con người để hệ thống TTS có thể đọc mượt mà. Tuyệt đối KHÔNG sử dụng các ký tự định dạng (như dấu sao *, dấu thăng #, gạch đầu dòng -). Không dùng danh sách liệt kê, hạn chế tối đa ngoặc đơn. Trả lời thẳng vào trọng tâm câu hỏi."*

---

## 7. Cập Nhật

```bash
cd chatgpt2api
docker compose -f docker-compose.lite.yml pull
docker compose -f docker-compose.lite.yml up -d
```
