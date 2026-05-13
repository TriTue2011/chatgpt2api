# chatgpt2api

OpenAI-compatible API gateway tích hợp **ChatGPT Web, Codex OAuth, OpenCode free, Gemini, DALL-E, SD WebUI**. Dùng làm AI agent backend cho Home Assistant.

## Mục lục

- [Cài đặt qua Home Assistant Addon](#cai-dat-qua-home-assistant-addon)
- [Cài đặt qua Docker](#cai-dat-qua-docker)
- [Cài đặt qua Docker Compose / Portainer](#cai-dat-qua-docker-compose--portainer)
- [Cài đặt trực tiếp (source)](#cai-dat-truc-tiep-source)
- [Cấu hình Home Assistant](#cau-hinh-home-assistant)
- [Thêm tài khoản](#them-tai-khoan)
- [Model](#model)
- [Tìm kiếm (Search)](#tim-kiem-search)
- [API Endpoints](#api-endpoints)
- [Troubleshooting](#troubleshooting)

---

## Cài đặt qua Home Assistant Addon

[![Add Repository](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FTriTue2011%2Fhas-addons)

**Bước 1:** Vào **Settings → Add-ons → Add-on Store**

**Bước 2:** Nhấn **⋮** (góc phải trên) → **Repositories**

**Bước 3:** Thêm URL: `https://github.com/TriTue2011/has-addons` → **Add**

**Bước 4:** Tìm **chatgpt2api** trong store → **Install**

**Bước 5:** Tab **Configuration** → sửa `auth_key` (mặc định: `sk-chatgpt2api`) → **Save**

**Bước 6:** **Start** → mở Web UI tại `http://HA_IP:3030`

**Bước 7:** Đăng nhập bằng `auth_key` đã đặt

Sau đó vào [Cấu hình Home Assistant](#cau-hinh-home-assistant).

---

## Cài đặt qua Docker

```bash
docker run -d \
  --name chatgpt2api \
  --restart unless-stopped \
  -p 3030:80 \
  -v chatgpt2api_data:/app/data \
  -e CHATGPT2API_AUTH_KEY=your_secret_key_here \
  ghcr.io/tritue2011/chatgpt2api:latest
```

Sau khi chạy:
- Web UI: `http://IP:3030`
- API: `http://IP:3030/v1/chat/completions`
- Đăng nhập Web UI bằng `your_secret_key_here`

> **Quan trọng**: Volume `chatgpt2api_data` lưu TOÀN Bộ dữ liệu: accounts, API keys (Gemini, NVIDIA, DeepSeek...), custom providers, model settings, combos, ảnh, backup. **Không được xóa volume này** nếu không muốn mất hết cài đặt.

---

## Cài đặt qua Docker Compose / Portainer

```yaml
services:
  chatgpt2api:
    image: ghcr.io/tritue2011/chatgpt2api:latest
    container_name: chatgpt2api
    restart: unless-stopped
    ports:
      - "3030:80"
    volumes:
      # [QUAN TRỌNG] Bind mount → thư mục thật trên host, không bao giờ mất khi build lại
      - ./chatgpt2api-data:/app/data
    environment:
      # [BẮT BUỘC] Đổi thành key bảo mật của bạn
      CHATGPT2API_AUTH_KEY: your_secret_key_here
      STORAGE_BACKEND: json

# Không cần khai báo volumes ở cuối nếu dùng bind mount
```

**Portainer:** Stacks → Add Stack → Web Editor → paste nội dung trên → Deploy.

### Cập nhật lên phiên bản mới (giữ nguyên dữ liệu)

```bash
docker compose pull
docker compose up -d
```

Dữ liệu trong `./chatgpt2api-data/` (thư mục thật trên host) **không bao giờ mất** khi pull image mới.

---

## Cài đặt trực tiếp (source)

Yêu cầu: Python 3.12+, Node.js 20+, Git

```bash
git clone https://github.com/TriTue2011/chatgpt2api
cd chatgpt2api

# Cài Python dependencies
pip install uv
uv sync

# Build web UI
cd web && npm install && npm run build && cd ..

# Chạy
cp .env.example .env
# Sửa CHATGPT2API_AUTH_KEY trong .env
uv run uvicorn main:app --host 0.0.0.0 --port 3030
```

---

## Cấu hình Home Assistant

Sau khi chatgpt2api đã chạy, cấu hình HA để dùng nó làm conversation agent.

### Dùng OpenAI Conversation (có sẵn trong HA)

**Settings → Devices & Services → Add Integration → OpenAI Conversation:**

| Field | Value |
|-------|-------|
| Base URL | `http://localhost:3030/v1` |
| API Key | Key đã đặt ở bước trên |
| Model | `ha-agent` |

### Dùng với hass_local_openai_llm

```yaml
# configuration.yaml
openai_llm:
  - name: chatgpt2api
    base_url: http://localhost:3030
    api_key: your_secret_key_here
    model: ha-agent
```

### Voice Pipeline

**Settings → Voice Assistants →** chọn pipeline → **Conversation Agent** → chọn agent đã config.

---

## Thêm tài khoản

### Token ChatGPT Web (chat + tạo ảnh)

1. Mở browser, đăng nhập https://chatgpt.com
2. Vào https://chatgpt.com/api/auth/session
3. Copy giá trị `accessToken`
4. Web UI → **Tài khoản → Nhập tài khoản → Nhập Access Token** → paste
5. Token JWT (bắt đầu `eyJ`) tự động dùng được cho cả chat (`cx/auto`) và tạo ảnh (`gpt-image-2`)

### Token Codex OAuth từ 9router (chat không giới hạn)

1. Web UI → **Sao lưu** → kéo thả file backup `.json` từ 9router
2. 10 token tự động thêm vào pool
3. Dùng model `cx/auto` — không giới hạn 24KB, native tool calling

### Gemini API Key (chat + search)

1. Vào https://aistudio.google.com/apikey → tạo API key (miễn phí 15 RPM)
2. Web UI → **Cài đặt → Gemini AI Studio**
3. Dán key (mỗi dòng 1 key nếu có nhiều)
4. Chọn model: `gemini-2.5-flash` (ổn định) hoặc `gemini-3-flash-preview` (mới nhất)
5. **Lưu**
6. Dùng model `gemini_free/auto` cho chat + tự động search Google

---

## Model

### Model cho chat

| Model | Provider | Cần token | Tool Call | Giới hạn |
|-------|----------|-----------|-----------|----------|
| `ha-agent` | **Combo tự động** | Auto | ✅ Native | Tự fallback |
| `oc/auto` | OpenCode | **Không** | ✅ Text→Native | Không |
| `cx/auto` | Codex OAuth | 9router backup | ✅ Native | Không |
| `gemini_free/auto` | Gemini | API key | ✅ Native | 15 RPM/key |
| `chatgpt/auto` | ChatGPT Web | Session cookie | ✅ Native | 24KB (free) |

### Model cho tạo ảnh

| Model | Provider | Cần |
|-------|----------|-----|
| `gpt-image-2` | DALL-E (chatgpt.com) | Token ChatGPT |
| `sdwebui/sd-v1.5` | Stable Diffusion local | GPU + SD WebUI |
| `huggingface/flux-schnell` | FLUX qua HuggingFace | API key (free tier) |

### Combo Models

Combo tự động thử từng model đến khi có kết quả. Cấu hình trong Web UI → **Cài đặt → Providers Card**:

```json
{
  "ha-agent": ["gemini_free/auto", "cx/auto", "oc/auto"],
  "ha-agent-image": ["chatgpt/gpt-image-2", "sdwebui/stable-diffusion"]
}
```

---

## Tìm kiếm (Search)

Khi dùng model không có search built-in (`cx/auto`, `oc/auto`, `gemini_free/auto`), hệ thống tự động:

1. Phát hiện câu hỏi cần tìm kiếm (regex tiếng Việt)
2. Gọi Google Search qua Gemini API (dùng key từ Cài đặt Gemini)
3. Inject kết quả vào prompt
4. Model trả lời dựa trên dữ liệu thực

**Cấu hình:** Web UI → **Tìm kiếm** → bật + chọn backend → Lưu.

Backend hỗ trợ:
- **Gemini** (Google Search grounding, miễn phí 15 RPM)
- **SearXNG** (tự host, không giới hạn)
- **Serper.dev** (Google Search API, 2.5K req/tháng free)
- **Brave Search** (2K req/tháng free)

---

## API Endpoints

| Method | Path | Auth | Mô tả |
|--------|------|------|-------|
| POST | `/v1/chat/completions` | API key | Chat (OpenAI format) |
| POST | `/v1/images/generations` | API key | Tạo ảnh |
| POST | `/v1/messages` | API key | Chat (Anthropic format) |
| GET | `/v1/models` | API key | Danh sách model |
| GET | `/api/accounts` | Admin | Danh sách tài khoản |
| POST | `/api/accounts` | Admin | Thêm tài khoản |
| POST | `/api/v1/import-9router-upload` | Admin | Import backup 9router |
| POST | `/api/v1/backup` | Admin | Tạo backup toàn bộ |
| POST | `/api/v1/restore` | Admin | Phục hồi từ backup |
| GET | `/api/v1/health` | Admin | Trạng thái hệ thống |

---

## Troubleshooting

### "Mất API key Gemini/NVIDIA/DeepSeek sau khi cập nhật"

**Nguyên nhân**: Volume name không cố định, hoặc dùng `docker compose down -v`.

**Cách fix**:
1. Đảm bảo `docker-compose.yml` có volume với `name:` cố định:
   ```yaml
   volumes:
     chatgpt2api_data:
       name: chatgpt2api_data
   ```
2. Khi cập nhật, chỉ dùng: `docker compose pull && docker compose up -d`
3. **Không dùng** `docker compose down -v` (cờ `-v` xóa volume)

### "Error talking to API" / HTTP 413

Payload vượt 24KB (giới hạn ChatGPT free account). Giải pháp:
- Đổi model sang `oc/auto`, `cx/auto`, hoặc `gemini_free/auto`
- Giảm **Max Message History** trong HA integration xuống 5
- Tắt **Content Injection** (date/time) trong HA integration

### Token hết quota (429)

- **ChatGPT/Codex**: Hệ thống tự động round-robin token khác trong pool
- **Gemini**: Thêm nhiều API key (mỗi dòng 1 key trong Cài đặt Gemini)
- **OpenCode**: Không giới hạn, luôn hoạt động

### Không kết nối được từ HA

- Base URL phải có `/v1` ở cuối: `http://IP:3030/v1`
- Kiểm tra `docker logs chatgpt2api` xem có request đến không
- Nếu HA và chatgpt2api khác máy, dùng IP thay vì localhost

### Addon không hiện trong HA Add-on Store

- **Ctrl+F5** refresh cứng
- **Add-on Store → ⋮ → Check for updates**
- Xóa repository → thêm lại
- Kiểm tra **Settings → System → Logs → Supervisor**

### Search không có kết quả

- Kiểm tra Gemini API key trong **Cài đặt → Gemini**
- Key phải có dạng `AIza...`
- Model preview có thể chưa hỗ trợ search grounding → dùng `gemini-2.5-flash`

## Credits

- [9router](https://github.com/TriTue2011/9router) — OAuth flow, multi-provider architecture
- [hass_local_openai_llm](https://github.com/skye-harris/hass_local_openai_llm) — HA integration
- OpenCode.ai — Free LLM API
- Google Gemini — Search grounding + free tier

## License

MIT
