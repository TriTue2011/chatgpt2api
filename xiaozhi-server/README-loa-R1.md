# Loa Phicomm R1 (AI Box) → ChatGPT qua xiaozhi-server

Biến loa **Phicomm R1 / AI Box Plus** thành loa nói chuyện với **chatgpt2api**.
Loa vốn đã chạy firmware chuẩn **xiaozhi**, nên chỉ cần bật **xiaozhi-server**
(đã gói sẵn trong `docker-compose.yml`) rồi trỏ loa về đó.

## Không phụ thuộc bên thứ 3

LLM, STT, TTS **đều gọi c2a nội bộ** (`http://c2a:80`). Model tiếng Việt (VieNeu
TTS, Zipformer STT) chạy trong c2a. Không EdgeTTS/Microsoft, không server nhà bán.

```
Loa (nói "Alexa" → Snowboy offline)
   │ audio Opus / WebSocket
   ▼
xiaozhi-server  :8000 WS  :8003 OTA   ← image công khai, KHÔNG build
   │ VAD → STT → LLM → TTS  (đều http://c2a:80)
   └► c2a  ├ /v1/chat/completions      LLM
           ├ /v1/audio/transcriptions  STT → Zipformer VN (tự host)
           └ /v1/audio/speech          TTS → VieNeu VN (tự host)
```

## "Ai cài cũng dùng ngay" — chỉ 2 giá trị trong `.env`

Config `.config.yaml` **tự sinh** lúc khởi động (service `xiaozhi-config` thay
key + IP vào [data/config.template.yaml](data/config.template.yaml)). Bạn chỉ đặt:

```dotenv
CHATGPT2API_AUTH_KEY=<key admin của c2a>     # đã có sẵn cho c2a
SERVER_IP=172.16.10.38                        # IP LAN host — loa quay số tới
```

rồi:

```bash
docker compose up -d          # lên c2a + xiaozhi-config (render) + xiaozhi-server
docker logs -f xiaozhi-esp32-server           # thấy WS :8000, OTA :8003
```

**Portainer** (host .38): dùng **Stack từ Git repository** để có sẵn thư mục
`xiaozhi-server/` cho bind mount; đặt 2 biến trên trong phần Environment của stack.

## Hai việc theo bản chất KHÔNG nhét vào image được

1. **Tải model giọng 1 lần** (nặng, nằm ngoài image — Dockerfile ghi rõ tải lúc
   chạy vào volume `data/`):
   ```bash
   docker exec c2a /app/.venv/bin/python /app/scripts/download_vieneu_model.py   # TTS Việt
   docker exec c2a /app/.venv/bin/python /app/scripts/download_stt_model.py --hf  # STT Việt
   ```
   (server .38 đã tải sẵn từ 26/07 — bỏ qua nếu đã có.)

2. **Trỏ loa vật lý về server** (mỗi máy/mạng khác nhau): mở panel loa
   `http://<IP-loa>:8081` → OTA Server → **Tùy chỉnh** → nhập
   `http://<SERVER_IP>:8003/xiaozhi/ota/` → Lưu → reboot loa.
   *(Chỉ đổi SAU KHI xiaozhi-server đã chạy.)*

Nói **"Alexa"** → hỏi → c2a trả lời bằng giọng Việt.

## Điều khiển mọi thứ bằng giọng nói (MCP tool của loa)

Firmware loa tự dựng MCP server; khi nối vào xiaozhi-server, tool tự xuất hiện cho
LLM gọi (`Intent: function_call`, c2a đã hỗ trợ `tools`/`tool_calls`).

| Nói | Tool loa |
|---|---|
| "Đặt âm lượng 40%" | `R1_speaker_set_volume` (0–100) |
| "Mở bài … trên YouTube" | YouTube search/play (NewPipe, chạy trên loa) |
| "Mở nhạc … Zing" | `play_zing` / `search_song` / `play_song` |
| "Tạo/thêm/xoá playlist" | `create_playlist` / `add_song` / `remove_song` |
| "Chỉnh bass / EQ / loudness" | `set_bass` / `set_eq` / `set_loudness` |
| "Đổi đèn …" | `background_light` / `frame_light` / `music_light` |

## Kiểm khi chạy thật

- **Auth**: `/v1/audio/speech` cần admin key (đúng `CHATGPT2API_AUTH_KEY`).
- **TTS méo/không phát**: c2a trả WAV; xem `docker logs xiaozhi-esp32-server`,
  cân nhắc thêm `response_format: wav` vào khối TTS trong template.
- **`tool_calls`**: gpt-4o qua c2a (gateway ChatGPT-web) — test độ ổn định thực tế.
