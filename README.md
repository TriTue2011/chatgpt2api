# chatgpt2api — OpenAI-compatible AI Gateway

[![Docker Pulls](https://img.shields.io/docker/pulls/tritue2011/chatgpt2api)](https://github.com/TriTue2011/chatgpt2api/pkgs/container/chatgpt2api)
[![GitHub Actions](https://github.com/TriTue2011/chatgpt2api/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/TriTue2011/chatgpt2api/actions)

OpenAI-compatible API gateway tích hợp **ChatGPT Web, Codex OAuth, OpenCode free, Gemini, DALL-E, SD WebUI**. Dùng làm AI agent backend cho Home Assistant.

**Tài liệu đầy đủ:** [README.md](./homeassistant-addon/README.md)

## Quick Start

```bash
docker run -d --name chatgpt2api --restart unless-stopped \
  -p 3030:80 \
  -v chatgpt2api_data:/app/data \
  -e CHATGPT2API_AUTH_KEY=sk-your-key \
  ghcr.io/tritue2011/chatgpt2api:latest
```

Mở `http://localhost:3030` → đăng nhập `sk-your-key`.

## Cài qua Home Assistant Addon Store

**Bước 1:** Vào HA → **Settings → Addons → Addon Store → 3 chấm (góc phải trên) → Repositories**

**Bước 2:** Thêm URL: `https://github.com/TriTue2011/chatgpt2api`

**Bước 3:** Vào Addon Store → tìm **chatgpt2api** → **Install**

**Bước 4:** Vào tab **Configuration** → sửa `auth_key` → **Save**

**Bước 5:** **Start** → mở Web UI → vào `http://HA_IP:3030`

Sau khi cài, vào HA **Settings → Devices & Services → Add Integration → OpenAI Conversation**:

| Field | Value |
|-------|-------|
| Base URL | `http://localhost:3030/v1` |
| API Key | `sk-chatgpt2api` (hoặc key bạn đặt) |
| Model | `ha-agent` |

## Cấu hình Home Assistant

```yaml
# OpenAI Conversation hoặc Local OpenAI
base_url: http://IP:3030/v1
api_key: sk-your-key
model: ha-agent
```

## Model chính

| Model | Chat | Tool Call | Ảnh | Token |
|-------|------|-----------|-----|-------|
| `ha-agent` | ✅ | ✅ | ✅ | Auto |
| `oc/auto` | ✅ | ✅ | ❌ | Free |
| `cx/auto` | ✅ | ✅ | ❌ | OAuth |
| `gemini_free/auto` | ✅ | ✅ | ❌ | API key |
| `chatgpt/auto` | ✅ | ✅ | ✅ | Web |

## Tính năng

- **Multi-provider**: ChatGPT, Codex OAuth, OpenCode free, Gemini, OpenRouter
- **Image generation**: DALL-E (gpt-image-2), SD WebUI, HuggingFace FLUX
- **Search**: Google Search qua Gemini/Serper/SearXNG, tự động inject kết quả
- **Multi-account**: Round-robin token pool, tự fallback khi rate limit
- **Combo models**: Tự động thử model khác khi lỗi
- **Backup/Restore**: Export/import toàn bộ state
- **Web UI**: Dashboard tiếng Việt, quản lý tài khoản + provider
- **Import 9router**: Kéo thả file backup 9router

## License

MIT

## Credits

- [9router](https://github.com/TriTue2011/9router) — OAuth architectures
- [chatgpt2api](https://github.com/TriTue2011/chatgpt2api) — ChatGPT Web API, Web UI
- [local_openai](https://github.com/skye-harris/hass_local_openai_llm) — HA integration
- OpenCode.ai, Google Gemini — Free APIs
