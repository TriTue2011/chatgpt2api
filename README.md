# chatgpt2api — OpenAI-compatible AI Gateway

[![Docker Pulls](https://img.shields.io/badge/docker-ghcr.io-blue)](https://github.com/TriTue2011/chatgpt2api/pkgs/container/chatgpt2api)
[![GitHub Actions](https://github.com/TriTue2011/chatgpt2api/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/TriTue2011/chatgpt2api/actions)

OpenAI-compatible API gateway tích hợp **ChatGPT Web, Codex OAuth, OpenCode free, Gemini, DALL-E, SD WebUI**. Dùng làm AI agent backend cho Home Assistant.

## Cài đặt nhanh

### Home Assistant Addon

[![Add Repository](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FTriTue2011%2Fhas-addons)

Hoặc thủ công: **Settings → Add-ons → Add-on Store → ⋮ → Repositories** → thêm `https://github.com/TriTue2011/has-addons` → tìm **chatgpt2api** → Install.

### Docker

```bash
docker run -d --name chatgpt2api --restart unless-stopped \
  -p 3030:80 \
  -v chatgpt2api_data:/app/data \
  -e CHATGPT2API_AUTH_KEY=sk-your-key \
  ghcr.io/tritue2011/chatgpt2api:latest
```

Mở `http://localhost:3030` → đăng nhập `sk-your-key`.

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
      CHATGPT2API_AUTH_KEY: sk-your-key

volumes:
  data: {}
```

## Cấu hình Home Assistant

Settings → Devices → Add Integration → **OpenAI Conversation** (hoặc Local OpenAI):

| Field | Value |
|-------|-------|
| Base URL | `http://localhost:3030/v1` |
| API Key | key bạn đã đặt |
| Model | `ha-agent` |

## Model chính

| Model | Chat | Tool Call | Ảnh | Token | Giới hạn |
|-------|------|-----------|-----|-------|----------|
| `ha-agent` | ✅ | ✅ | ✅ | Auto | Tự fallback |
| `oc/auto` | ✅ | ✅ | ❌ | **Không cần** | Không |
| `cx/auto` | ✅ | ✅ | ❌ | OAuth (9router) | Không |
| `gemini_free/auto` | ✅ | ✅ | ❌ | API key | 15 RPM |
| `chatgpt/auto` | ✅ | ✅ | ✅ | Web cookie | 24KB (free) |

## Thêm tài khoản

### Token ChatGPT (chat + ảnh)
1. Đăng nhập https://chatgpt.com
2. Vào https://chatgpt.com/api/auth/session → copy `accessToken`
3. Web UI → **Tài khoản** → **Nhập tài khoản** → paste

### Import backup 9router
Web UI → **Sao lưu** → kéo thả file backup `.json`. Token Codex OAuth tự động thêm.

### Gemini API key (chat + search)
1. Lấy key tại https://aistudio.google.com/apikey (free 15 RPM)
2. Web UI → **Cài đặt → Gemini** → dán key → chọn model → Lưu

## Tính năng chính

- **Multi-provider**: ChatGPT, Codex OAuth, OpenCode free, Gemini, OpenRouter
- **Tạo ảnh**: DALL-E (gpt-image-2), SD WebUI, HuggingFace FLUX  
- **Search**: Google Search qua Gemini, tự động inject kết quả vào prompt
- **Multi-account**: Round-robin token, tự fallback khi rate limit
- **Combo models**: Tự động thử model khác khi lỗi (vd: `ha-agent`)
- **Backup/Restore**: Export/import toàn bộ state
- **Web UI**: Dashboard tiếng Việt, quản lý tài khoản + provider
- **Native tool calling**: GetLiveContext, GetEntityState... cho HA

## Troubleshooting

**413 / "Error talking to API"**: Payload quá 24KB → dùng `oc/auto`, `cx/auto`, hoặc `gemini_free/auto`.

**Token hết quota (429)**: Hệ thống tự round-robin. Với Gemini, thêm nhiều key (mỗi dòng 1 key).

**Search không có kết quả**: Vào **Cài đặt → Gemini** kiểm tra API key.

**Addon không hiện trong store**: Refresh (Ctrl+F5), Check for updates, hoặc kiểm tra Supervisor logs.

## License

MIT
