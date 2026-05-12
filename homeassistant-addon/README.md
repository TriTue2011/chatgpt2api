# chatgpt2api

OpenAI-compatible API gateway tích hợp ChatGPT, Codex OAuth, OpenCode free, Gemini, tạo ảnh DALL-E. Dùng làm AI agent backend cho Home Assistant.

## Tính năng

| Tính năng | Mô tả |
|-----------|-------|
| **ChatGPT** | Chat qua chatgpt.com web API, hỗ trợ token từ `/api/auth/session` |
| **Codex OAuth** | Chat qua `chatgpt.com/backend-api/codex/responses` — không giới hạn 24KB như 9router |
| **OpenCode free** | Chat miễn phí qua opencode.ai, không cần token, không giới hạn |
| **Gemini** | Chat + Google Search grounding qua Gemini API (miễn phí 15 RPM) |
| **Image Gen** | DALL-E qua `gpt-image-2`, SD WebUI local, HuggingFace FLUX |
| **Search** | Google Search qua Gemini/Serper/SearXNG/Brave, tự động inject kết quả |
| **Multi-account** | Round-robin token pool, tự fallback khi rate limit |
| **Backup** | Export/import toàn bộ state (tài khoản, config, provider) |
| **Web UI** | Dashboard tiếng Việt, quản lý tài khoản, provider, combo models |
| **HA Agent** | Native tool calling cho Home Assistant (GetLiveContext...) |

## Kiến trúc

```
HA → chatgpt2api (:3030) → OpenAI-compatible API (/v1/chat/completions, /v1/images/generations)
  ├── cx/auto       → Codex OAuth (chatgpt.com/backend-api/codex/responses)
  ├── oc/auto       → OpenCode free (opencode.ai)
  ├── gemini_free/auto → Gemini API (generativelanguage.googleapis.com)
  ├── chatgpt/auto  → ChatGPT web (chatgpt.com/backend-api/conversation)
  ├── gpt-image-2   → DALL-E image generation
  ├── sdwebui/...   → Stable Diffusion local
  └── ha-agent      → Combo: tự động chọn backend tốt nhất
```

## Cài đặt

### Docker (khuyên dùng)

```bash
docker run -d --name chatgpt2api --restart unless-stopped \
  -p 3030:80 \
  -v chatgpt2api_data:/app/data \
  -e CHATGPT2API_AUTH_KEY=your_secret_key \
  ghcr.io/tritue2011/chatgpt2api:latest
```

### Docker Compose (Portainer)

```yaml
services:
  chatgpt2api:
    image: ghcr.io/tritue2011/chatgpt2api:latest
    container_name: chatgpt2api
    restart: unless-stopped
    ports:
      - "3030:80"
    volumes:
      - data:/app/data
    environment:
      CHATGPT2API_AUTH_KEY: your_secret_key
      STORAGE_BACKEND: json

volumes:
  data: {}
```

### Cài trực tiếp

```bash
git clone https://github.com/TriTue2011/chatgpt2api
cd chatgpt2api
uv sync
cp .env.example .env  # Sửa CHATGPT2API_AUTH_KEY
cd web && npm install && npm run build && cd ..
uv run uvicorn main:app --host 0.0.0.0 --port 3030
```

## Thêm tài khoản

### Cách 1: Import từ backup 9router

Vào Web UI `http://IP:3030` → **Sao lưu** → kéo thả file backup `.json` từ 9router. Token Codex OAuth được thêm tự động.

### Cách 2: Lấy token ChatGPT web

1. Đăng nhập https://chatgpt.com
2. Vào https://chatgpt.com/api/auth/session
3. Copy `accessToken`
4. Vào Web UI → **Tài khoản** → **Nhập tài khoản** → **Nhập Access Token** → paste

### Cách 3: OAuth Login

Vào Web UI → **Tài khoản** → **Nhập tài khoản** → **Đăng nhập Codex OAuth** — mở popup OpenAI để authorize.

## Cấu hình Home Assistant

### Integration: Local OpenAI / OpenAI Conversation

```yaml
# configuration.yaml hoặc UI Settings
base_url: http://IP_CHATGPI2API:3030/v1
api_key: your_secret_key
model: ha-agent   # tự động chọn backend tốt nhất
```

### Model gợi ý cho HA

| Model | Chat | Tool Call | Tạo ảnh | Giới hạn | Token |
|-------|------|-----------|---------|----------|-------|
| `ha-agent` | ✅ | ✅ | ✅ | Combo tự fallback | Auto |
| `oc/auto` | ✅ | ✅ Text | ❌ | Không giới hạn | Không cần |
| `cx/auto` | ✅ | ✅ Native | ❌ | Không (Codex) | 9router OAuth |
| `gemini_free/auto` | ✅ | ✅ Native | ❌ | 15 RPM | API key |
| `chatgpt/auto` | ✅ | ✅ Native | ✅ | 24KB (free) | ChatGPT web |

### Voice Pipeline

Settings → Voice Assistants → chọn pipeline → **Conversation Agent** → chọn tên agent đã config.

## Token & API Key

### ChatGPT (chat + ảnh)

Lấy từ `https://chatgpt.com/api/auth/session` → `accessToken`. Token JWT được tự động nhận diện và thêm vào cả pool chat lẫn pool ảnh.

### Codex OAuth (chat không giới hạn)

Import từ backup 9router hoặc đăng nhập OAuth. Token OAuth gọi thẳng `chatgpt.com/backend-api/codex/responses` — không giới hạn 24KB.

### Gemini (chat + search)

API key miễn phí tại https://aistudio.google.com/apikey (15 RPM/key). Hỗ trợ nhiều key — tự động round-robin khi hết quota.

Cấu hình trong Web UI → **Cài đặt → Gemini AI Studio** → nhập key (mỗi dòng 1 key) → chọn model → Lưu.

Model hỗ trợ: `gemini-3-flash-preview`, `gemini-2.5-flash`, `gemini-2.5-pro-preview-07-02`, `gemini-2.0-flash`.

### OpenCode (chat miễn phí)

Không cần token hay API key. Tự động hoạt động với model `oc/auto`.

## Search

Khi hỏi câu cần thông tin thực tế ("giá xăng hôm nay", "thời tiết", "tin tức"...), hệ thống tự động:

1. Phát hiện intent cần search (regex tiếng Việt)
2. Gọi Google Search qua Gemini API (dùng chung key từ Cài đặt Gemini)
3. Inject kết quả vào prompt
4. Model trả lời dựa trên dữ liệu thực tế

Cấu hình: Web UI → **Tìm kiếm** → chọn backend → Lưu.

Backend hỗ trợ: ChatGPT (built-in), Gemini (Google Search), Serper.dev, SearXNG (self-host), Brave Search.

## Combo Models

Combo tự động thử từng model đến khi thành công:

```json
{
  "combo_models": {
    "ha-agent": ["gemini_free/auto", "cx/auto", "oc/auto"],
    "ha-agent-image": ["chatgpt/gpt-image-2", "sdwebui/stable-diffusion"]
  }
}
```

Cấu hình trong Web UI → **Cài đặt → Providers Card** → Combo Models textarea (mỗi dòng: `tên=model1,model2`).

## API Endpoints

| Method | Path | Auth | Mô tả |
|--------|------|------|-------|
| POST | `/v1/chat/completions` | API key | Chat (OpenAI format) |
| POST | `/v1/images/generations` | API key | Tạo ảnh (OpenAI format) |
| GET | `/v1/models` | API key | Danh sách model |
| POST | `/v1/messages` | API key | Chat (Anthropic format) |
| GET | `/api/accounts` | Admin | Danh sách tài khoản |
| POST | `/api/accounts` | Admin | Thêm tài khoản |
| POST | `/api/v1/import-9router-upload` | Admin | Import backup 9router |
| POST | `/api/v1/backup` | Admin | Tạo backup |
| POST | `/api/v1/restore` | Admin | Phục hồi backup |
| GET | `/api/v1/health` | Admin | Trạng thái hệ thống |
| GET | `/api/oauth/codex/start` | Admin | Lấy URL OAuth Codex |
| POST | `/api/oauth/codex/exchange` | Admin | Exchange OAuth code |

## Cấu hình đầy đủ

```json
{
  "auth-key": "sk-chatgpt2api",
  "refresh_account_interval_minute": 60,
  "image_retention_days": 15,
  "image_poll_timeout_secs": 120,
  "auto_remove_rate_limited_accounts": false,
  "auto_remove_invalid_accounts": true,
  "proxy": "",
  "base_url": "",
  "global_system_prompt": "",
  "image_account_concurrency": 3,
  "backends": {
    "chat": ["chatgpt", "opencode", "gemini_free", "openrouter"],
    "image": ["chatgpt", "sdwebui", "huggingface", "cloudflare"],
    "default_chat": "auto",
    "default_image": "1792x1024"
  },
  "providers": {
    "opencode": {"enabled": true, "noAuth": true},
    "gemini_free": {"enabled": false, "api_key": "", "api_keys": [], "model": "gemini-3-flash-preview"},
    "openrouter": {"enabled": false, "api_key": ""},
    "sdwebui": {"enabled": false, "base_url": "http://localhost:7860"},
    "huggingface": {"enabled": false, "api_key": ""},
    "cloudflare_ai": {"enabled": false, "account_id": "", "api_token": ""},
    "serper": {"enabled": false, "api_key": ""},
    "searxng": {"enabled": false, "base_url": "http://localhost:8080"},
    "brave": {"enabled": false, "api_key": ""}
  },
  "rate_limit": {
    "backoff_base_ms": 2000,
    "backoff_max_ms": 300000,
    "max_levels": 15
  },
  "combo_models": {
    "ha-agent": ["gemini_free/auto", "cx/auto", "oc/auto"],
    "ha-agent-image": ["chatgpt/gpt-image-2"]
  },
  "search": {
    "enabled": true,
    "backend": "gemini",
    "auto_detect": true,
    "max_results": 3,
    "inject_as": "user_message"
  },
  "ninerouter": {
    "base_url": "http://localhost:20128",
    "api_key": ""
  }
}
```

## Web UI

Truy cập `http://IP:3030` → đăng nhập bằng API key. Giao diện tiếng Việt với sidebar:

- **Tổng quan**: Dashboard thống kê tài khoản, health, backoff
- **Tài khoản**: Thêm/xóa/refresh token ChatGPT + OAuth
- **Nhà cung cấp**: Bật/tắt provider, cấu hình API key
- **Mô hình kết hợp**: Tạo combo model với fallback
- **Vẽ ảnh**: Giao diện tạo ảnh DALL-E
- **Thư viện ảnh**: Quản lý ảnh đã tạo
- **Tìm kiếm**: Cấu hình search backend + model
- **Sao lưu**: Backup/restore toàn bộ hệ thống
- **Cài đặt**: Config, Gemini, backup settings

## Troubleshooting

### "Error talking to API" với chatbot

Payload quá 24KB (giới hạn ChatGPT free) → dùng `cx/auto`, `oc/auto`, hoặc `gemini_free/auto`.

### Token hết quota (429)

Hệ thống tự động round-robin token khác. Với Gemini, thêm nhiều API key (mỗi dòng 1 key).

### Search không có kết quả

Kiểm tra Gemini API key trong **Cài đặt → Gemini**. Key phải có dạng `AIza...`. Với model preview, search tự fallback về `gemini-2.5-flash`.

### Không kết nối được từ HA

- Kiểm tra base_url trong HA: `http://IP:3030/v1` (có `/v1` ở cuối)
- Kiểm tra `docker logs chatgpt2api` xem có request đến không
- Nếu dùng Docker bridge network: thử `http://172.16.10.200:3030/v1`

## Development

```bash
git clone https://github.com/TriTue2011/chatgpt2api
cd chatgpt2api
uv sync
uv run uvicorn main:app --reload --port 3030
```

Build Docker:
```bash
docker build -t chatgpt2api:latest .
```

Build web UI:
```bash
cd web && npm install && npm run build
```

## Credits

- 9router: OAuth flow, multi-provider architecture
- chatgpt2api: ChatGPT web API, DALL-E, Web UI
- hass_local_openai_llm: Home Assistant integration pattern
- OpenCode.ai: Free LLM API
- Google Gemini: Search grounding + free tier

## License

MIT
