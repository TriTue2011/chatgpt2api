# chatgpt2api — OpenAI-compatible API Gateway

AI Agent backend cho Home Assistant, Open WebUI, n8n và mọi ứng dụng hỗ trợ OpenAI API.

**Tính năng chính:**
- 10+ AI provider (ChatGPT Web, Codex OAuth, OpenCode, Gemini, DeepSeek, Groq, Mistral...)
- **MCP Server integration** — mở rộng AI với search, weather, knowledge base
- Model combo (tự động fallback khi provider lỗi)
- Search service (tích hợp sẵn + MCP search fallback)
- Web dashboard quản lý tài khoản, model, backup
- RTK token optimizer (tiết kiệm 60-90% token)

---

## Yêu cầu hệ thống

| Môi trường | Tối thiểu | Khuyến nghị |
|-----------|----------|------------|
| RAM | 1GB | 2GB+ |
| Disk | 2GB | 10GB+ |
| Docker | 24.0+ | latest |

---

## Cài đặt nhanh

### 1. Docker CLI

```bash
docker run -d \
  --name chatgpt2api \
  --restart unless-stopped \
  -p 3030:80 \
  -v /opt/chatgpt2api-data:/app/data \
  -e CHATGPT2API_AUTH_KEY="your-secret-key" \
  ghcr.io/tritue2011/chatgpt2api:latest
```

- Dashboard: `http://your-ip:3030`
- API endpoint: `http://your-ip:3030/v1/chat/completions`
- Login: `admin` / `your-secret-key`

### 2. Docker Compose

```yaml
# docker-compose.yml
services:
  chatgpt2api:
    image: ghcr.io/tritue2011/chatgpt2api:latest
    container_name: chatgpt2api
    restart: unless-stopped
    ports:
      - "3030:80"
    volumes:
      - ./data:/app/data
    environment:
      - CHATGPT2API_AUTH_KEY=your-secret-key
```

```bash
docker compose up -d
```

### 3. NAS (Synology / QNAP)

**Container Manager (Synology):**
1. Registry → tìm `ghcr.io/tritue2011/chatgpt2api` → Download
2. Image → Launch → Advanced Settings:
   - Port Forwarding: Local 3030 → Container 80
   - Volume: Add Folder → mount to `/app/data`
   - Environment: `CHATGPT2API_AUTH_KEY` = `your-secret-key`
3. Apply → Next → Done

**Container Station (QNAP):**
1. Create → Search `ghcr.io/tritue2011/chatgpt2api`
2. Advanced Settings → Network: Host 3030 → Container 80
3. Shared Folders: add volume → `/app/data`
4. Environment: `CHATGPT2API_AUTH_KEY` = `your-secret-key`

### 4. Portainer

1. **Stacks** → **Add stack**
2. Name: `chatgpt2api`
3. Web editor → paste nội dung:

```yaml
services:
  chatgpt2api:
    image: ghcr.io/tritue2011/chatgpt2api:latest
    container_name: chatgpt2api
    restart: unless-stopped
    ports:
      - "3030:80"
    volumes:
      - chatgpt2api_data:/app/data
    environment:
      - CHATGPT2API_AUTH_KEY=your-secret-key

volumes:
  chatgpt2api_data:
```

4. **Deploy the stack**

---

## Cấu hình ban đầu

Sau khi cài đặt, mở `http://your-ip:3030` và đăng nhập.

### Bước 1: Thêm tài khoản AI

**Cách A — Import 9router backup (có sẵn token ChatGPT):**
1. Vào **Backup** → Upload file backup `.json` hoặc `.json.gz`
2. Hệ thống tự động import ChatGPT tokens + OAuth refresh credentials

**Cách B — Thêm API key:**
1. Vào **Providers** → chọn provider (Gemini, DeepSeek, Groq...)
2. Điền API key → Save

### Bước 2: Cấu hình Model Combo

Vào **Combos** → tạo combo `AI Agent`:
```
cx/auto → chatgpt/auto → oc/auto
```
Combo tự động thử model đầu, lỗi → fallback model kế tiếp.

### Bước 3: Cài MCP Servers (tuỳ chọn)

Mở rộng AI với search, weather, knowledge base:

1. **Cài vn-mcp-hub** (xem [vn-mcp-hub/README.md](vn-mcp-hub/README.md))
2. Vào **MCP Servers** → chọn preset → **Cài**
3. Tools từ MCP tự động inject vào request

### Bước 4: Kết nối ứng dụng

**Home Assistant:**
```yaml
# configuration.yaml
conversation:
  - platform: openai_conversation
    api_key: your-secret-key
    base_url: http://172.16.10.x:3030/v1
    model: AI Agent
```

**Open WebUI:**
Admin Panel → Settings → Connections → OpenAI API
- URL: `http://172.16.10.x:3030/v1`
- Key: `your-secret-key`

**n8n:**
OpenAI Chat Model node → Custom URL: `http://172.16.10.x:3030/v1`

---

## API Endpoints

| Endpoint | Mô tả |
|----------|-------|
| `POST /v1/chat/completions` | Chat completion (OpenAI format) |
| `POST /v1/images/generations` | Tạo ảnh (DALL-E, SD) |
| `GET /v1/models` | Danh sách model |
| `GET /health` | Health check |
| `GET /api/mcp/presets` | Danh sách MCP presets |
| `POST /api/mcp/install` | Cài đặt MCP server |

## Model Prefix

| Prefix | Provider | Ghi chú |
|--------|----------|--------|
| `cx/` | Codex OAuth | ChatGPT Pro/Plus, tự refresh token |
| `chatgpt/` | ChatGPT Web | Free account |
| `oc/` | OpenCode | Free, không cần tài khoản |
| `gemini_free/` | Gemini AI Studio | Free 15 RPM |
| `nv/` | NVIDIA NIM | Cần API key |
| `custom:...` | Custom Provider | OpenAI-compatible API |

## Environment Variables

| Biến | Mặc định | Mô tả |
|------|---------|-------|
| `CHATGPT2API_AUTH_KEY` | (bắt buộc) | Mật khẩu dashboard + API key |

## Troubleshooting

| Vấn đề | Giải pháp |
|--------|----------|
| Container crash loop | `docker logs chatgpt2api` |
| Codex 400 "model not supported" | Models → bỏ tick `cx/auto`, tick model cụ thể như `cx/gpt-5.5` |
| Token expired liên tục | Import lại 9router backup để có refresh_token |
| MCP tools không thấy | MCP Servers → kiểm tra enabled + URL đúng |
| Out of disk | `docker system prune -af` |

## Update

```bash
docker pull ghcr.io/tritue2011/chatgpt2api:latest
docker rm -f chatgpt2api
# Chạy lại lệnh docker run ở trên (giữ nguyên volume mount)
```
