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

## ⭐ Bản CHỐT (zero-CLI) — [stack.portainer.yml](stack.portainer.yml)

Dán trọn [stack.portainer.yml](stack.portainer.yml) vào Portainer → Update. Service
`xiaozhi-config` **tự sinh** `.config.yaml` từ `${AUTH_KEY}` (không gõ lệnh tạo file
trên host). Mọi thứ còn lại làm trong **web UI c2a**: chọn giọng, bật MCP "Loa Phicomm
R1", chat/ra lệnh. Chỉ đổi `SERVER_IP` nếu host ≠ 172.16.10.38.

> Bước duy nhất KHÔNG có nút web UI là **tải model giọng** (`/api/voice/speech` trả
> 404 "chạy scripts/download_…" nếu thiếu). Trên `.38` đã tải sẵn (26/07) nên bỏ qua;
> kiểm trong web UI c2a mục Giọng nói / `/api/voice/status`.

## Module đầy đủ, STACK RIÊNG — [stack.portainer.full.yml](stack.portainer.full.yml)

Muốn **chọn model/giọng/STT/persona bất kỳ trong web console** (thay vì sửa file):
bản đầy đủ có console `:8002` + MySQL + Redis. Deploy như **một stack Portainer
RIÊNG, tách khỏi c2a** — vì xiaozhi hiếm khi cập nhật còn c2a cập nhật thường
xuyên; để riêng thì update c2a không đụng tới xiaozhi.

- MySQL/Redis **không dùng chung Postgres của c2a được** (khác engine); data để
  chung `/opt/c2a/data/xiaozhi` (một chỗ backup, dù stack riêng).
- Vì khác stack → **khác mạng Docker → không gọi được tên `c2a`**. Trong console,
  trỏ LLM/ASR/TTS về c2a qua **domain** `https://gpt.vhtatn.io.vn/...` (hoặc IP host
  `http://172.16.10.38:3030/...`).
- Chế độ full: `.config.yaml` chỉ trỏ manager-api + secret; mọi cấu hình khác
  (LLM/model/ASR/TTS/giọng/persona/SERVER_IP) nằm **trong console**.

Lần đầu (tóm tắt; chi tiết ở đầu file stack):
1. Deploy (để trống `XZ_MANAGER_SECRET`) → console `http://<host>:8002` → đăng ký admin.
2. Console → 参数管理 → copy `server.secret` → đặt `XZ_MANAGER_SECRET` trong Environment → Update lại.
3. Console → 参数管理: `server.websocket=ws://<SERVER_IP>:8000/xiaozhi/v1/`, `server.ota=http://<SERVER_IP>:8003/xiaozhi/ota/`.
4. Console → 模型配置: LLM/ASR/TTS kiểu OpenAI trỏ `https://gpt.vhtatn.io.vn/...` (key=AUTH_KEY) → chọn model/giọng/STT tuỳ ý.

⚠️ Java+MySQL+Redis, nặng hơn hẳn; chưa test build được — dựng bám sát compose chính chủ, kiểm khi deploy.

## Cách 2 — Portainer stack gộp (host-path, khớp .38 hiện tại)

Nếu bạn sửa stack bằng **web-editor Portainer** (không kéo từ Git), dùng đường dẫn
tuyệt đối trên host thay cho bind mount `./` — khớp đúng khuôn `/opt/c2a/data` bạn
đang dùng. Thêm service này **cùng stack** với `c2a` (vẫn "một stack, không compose
khác"):

```yaml
  xiaozhi-server:
    image: ghcr.io/xinnan-tech/xiaozhi-esp32-server:server_latest
    container_name: xiaozhi-esp32-server
    restart: unless-stopped
    ports:
      - "8000:8000"     # WebSocket — loa nối vào
      - "8003:8003"     # OTA — loa trỏ tới http://<SERVER_IP>:8003/xiaozhi/ota/
    volumes:
      - /opt/xiaozhi/data:/opt/xiaozhi-esp32-server/data
    security_opt:
      - no-new-privileges:true
```

Tạo file config một lần trên host (thay `<AUTH_KEY>` = đúng `${AUTH_KEY}` của stack):

```bash
sudo mkdir -p /opt/xiaozhi/data
sudo tee /opt/xiaozhi/data/.config.yaml >/dev/null <<'YAML'
server:
  ip: 0.0.0.0
  port: 8000
  http_port: 8003
  websocket: ws://172.16.10.38:8000/xiaozhi/v1/
  vision_explain: http://172.16.10.38:8003/mcp/vision/explain
selected_module:
  VAD: SileroVAD
  ASR: OpenaiASR
  LLM: C2A
  TTS: OpenAITTS
  Intent: function_call
  Memory: nomem
LLM:
  C2A: {type: openai, model_name: gpt-4o, url: "http://c2a:80/v1/", api_key: "<AUTH_KEY>"}
ASR:
  OpenaiASR: {type: openai, base_url: "http://c2a:80/v1/audio/transcriptions", api_key: "<AUTH_KEY>", model_name: whisper-1, output_dir: tmp/}
TTS:
  OpenAITTS: {type: openai, api_url: "http://c2a:80/v1/audio/speech", api_key: "<AUTH_KEY>", model: tts-1, voice: "", speed: 1, output_dir: tmp/}
YAML
```

`http://c2a:80` phân giải được vì **cùng stack** với c2a. Cổng 8000/8003 không đụng
c2a (3030/6080/3001/10600/10700).

## Cách 3 — Loa ở xa, không cùng LAN: dùng qua domain

Firmware loa hỗ trợ `https://`/`wss://`. Đưa xiaozhi-server ra internet qua reverse
proxy (cái đang phục vụ `gpt.vhtatn.io.vn`) và đổi URL advertise sang domain — còn
LLM/STT/TTS vẫn gọi nội bộ `c2a:80`:

```yaml
# trong .config.yaml
server:
  websocket: wss://loa.vhtatn.io.vn/xiaozhi/v1/
  vision_explain: https://loa.vhtatn.io.vn/mcp/vision/explain
```

Reverse proxy (TLS + cho phép WebSocket upgrade):
- `wss://loa.vhtatn.io.vn/xiaozhi/v1/`  → `xiaozhi-server:8000` (bật header `Upgrade`/`Connection`)
- `https://loa.vhtatn.io.vn/xiaozhi/ota/` và `/mcp/...` → `xiaozhi-server:8003`

Trên loa: OTA Tùy chỉnh → `https://loa.vhtatn.io.vn/xiaozhi/ota/`.

⚠️ Mở ra internet: ai biết domain cũng cắm loa vào được. Nên bật đăng ký/allowlist
thiết bị của xiaozhi hoặc chặn bằng Cloudflare Access. Loa qua WAN sẽ trễ hơn LAN.

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

## R1 là một MCP server sẵn — điều khiển từ MỌI kênh (gần như không cần code)

Loa chạy sẵn **MCP server tại `http://<IP-loa>:8083/`** (tên `AIBOX-Phicomm-R1`;
kiểm 07/08/2026: POST JSON-RPC `initialize`/`tools/list`/`tools/call` chạy, CORS mở).
Vì c2a **thêm MCP server bằng toggle**, chỉ cần đăng ký URL này là R1 thành "một chức
năng tích-để-bật", và LLM gọi được từ **mọi kênh** (web/Telegram/Zalo), không chỉ loa.

**Cách thêm:** c2a → Cài đặt → MCP → thêm server `http://172.16.10.17:8083/`
(nếu UI đòi endpoint SSE thì `http://172.16.10.17:8083/sse`) → bật toggle.

**10 tool thật (đã xác minh qua `tools/list`):**

| Nói | Tool |
|---|---|
| "Đặt âm lượng 40%" | `R1_speaker_set_volume` (0–100) |
| "Mở nhạc/kể chuyện … (Zing)" | `R1_music_zing_play` |
| "Mở … trên YouTube" | `R1_youtube_music_play` / `R1_youtube_music_playlist` |
| "Dừng / bài tiếp / bài trước / phát tiếp" | `R1_music_stop` |
| "Mở/tắt đài VOV" | `R1_radio_play` / `R1_radio_stop` |
| "Loa thế nào rồi" | `R1_get_device_status` |
| "Đặt/sửa báo thức" | `R1_alarm_manage` |
| "Gửi Zalo …" | `R1_send_zalo_message` |

**Không có trong MCP:** *reboot* và *tắt nguồn cứng*. MCP chỉ có chỉnh âm lượng
(đặt 0 = im) + `R1_music_stop`. Reboot-bằng-giọng phải đi kênh khác (WS shell :8080),
cần thêm dependency WebSocket + build lại image → để riêng, không làm trừ khi cần.

Khi nói trực tiếp với loa (qua xiaozhi-server), chính bộ tool này cũng tự lộ cho LLM.

## Kiểm khi chạy thật

- **Auth**: `/v1/audio/speech` cần admin key (đúng `CHATGPT2API_AUTH_KEY`).
- **TTS méo/không phát**: c2a trả WAV; xem `docker logs xiaozhi-esp32-server`,
  cân nhắc thêm `response_format: wav` vào khối TTS trong template.
- **`tool_calls`**: gpt-4o qua c2a (gateway ChatGPT-web) — test độ ổn định thực tế.
