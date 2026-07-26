---
name: Vận hành hệ thống
description: Kiến trúc gateway, luồng chat, MCP hub, cách đọc log/kiểm tra sức khoẻ, luồng deploy.
group: Hệ thống
---

# Vận hành hệ thống (gateway chatgpt2api)

## Khi nào dùng
- Chủ nhà hỏi "hệ thống chạy sao", "kiến trúc thế nào", "log ở đâu", "kiểm tra sức khoẻ server"
- Vừa deploy xong, nghi ngờ có gì chưa lên đúng bản
- Cần giải thích vì sao 1 câu hỏi lại đi qua provider nào

## Luồng 1 lượt chat
1. Tin nhắn vào → **orchestrator** dựng system prompt (persona + skill + quyền hạn thread) rồi chạy vòng gọi tool tối đa 4 bước.
2. Mỗi bước gọi model qua `runtime.call_model` — POST vào chính `/v1/chat/completions` của gateway (không gọi thẳng provider), để tái dùng toàn bộ pipeline có sẵn (fast-path HA, tìm kiếm, sinh ảnh…).
3. **backend_router** đọc tiền tố model để chọn provider: `cx/`→Codex, `gmw/`→Gemini web, `oc/`→OpenCode, `claude/`→Claude, `gma/`→Gemini (cookie)… không tiền tố → ChatGPT free.
4. Payload lớn (>100KB) mà ChatGPT free không còn account active → tự chuyển sang OpenCode (free, khỏi đăng nhập).
5. Provider gọi vào **pool tài khoản** riêng (account_service) — nhiều account cùng provider xoay vòng theo quota/cooldown.

## 1 container, nhiều tiến trình (supervisord)
- **vn-mcp-hub** (127.0.0.1:8005): các MCP nội bộ — thời tiết/tin tức/tỷ giá/âm lịch/tìm kiếm/luật/chứng khoán VN, YouTube, Wikipedia, arXiv, đọc web, web agent, SSH server, file server, và 6 kho kiến thức (điện nước, y tế, giáo dục, ngoại ngữ, khoa học, xã hội).
- **captcha-api** (127.0.0.1:8010): giải captcha + đăng nhập web thủ công (màn hình ảo, xem qua noVNC :6080).
- **zalo-server** (Node, :3001): kênh Zalo cá nhân.
- **chatgpt2api** (:80): gateway chính + web UI — process em đang chạy bên trong.

## Đọc log
Mọi tiến trình ghi thẳng ra stdout container (không file riêng) → `docker logs -f <container>` gộp cả các tiến trình (chủ nhà tự chạy trên server). Muốn tách riêng 1 service: `docker exec -it <container> supervisorctl tail -f vn-mcp-hub` (đổi tên: chatgpt2api / captcha-api / zalo-server). Log tự che token/base64 nên xem thoải mái. Với MỘT SERVER KHÁC đã khai báo trước (SSH Server, tab External MCP) — vd NAS, đầu ghi camera, VPS — cứ hỏi tự nhiên ("log nginx trên VPS thế nào", "container frigate còn chạy không"); hệ thống tự nhận diện và chạy lệnh thật qua `ssh_run`/`fs_*`, không cần tự chọn tool.

## Kiểm tra sức khoẻ
- `GET /version` — probe sống/chết, dùng cho HEALTHCHECK docker.
- `GET /api/v1/health` (cần quyền admin) — accounts theo nhóm provider (active/limited/error), quota_watcher, model_cooldown, backoff, provider_circuits. Đây là nơi tra khi nghi ngờ pool tài khoản.
- Với chính máy chủ đang chạy bot: tool **system_status** (CPU/RAM/ổ đĩa/uptime).
- Với máy khác CHƯA khai báo trước, có sẵn mật khẩu ngay lúc hỏi: tool **remote_system_status** — CHỈ đọc phần cứng cố định (OS, uptime, CPU, RAM, ổ đĩa, top tiến trình), KHÔNG chạy lệnh tuỳ ý và KHÔNG đọc được log/file — muốn vậy phải khai báo server trước (SSH Server ở trên).

## Deploy (tóm tắt)
Push `main`/tag → GitHub Actions chạy test nhanh (pytest subset) → build ảnh amd64 + arm64 (mỗi kiến trúc 1 runner riêng, không qua giả lập) → gộp thành 1 manifest đa kiến trúc → đẩy `ghcr.io/tritue2011/chatgpt2api`. Trên server: script deploy dọn ảnh cũ → pull ảnh mới → dừng container cũ → chạy container mới (volume `/app/data`) → chờ `/version` trả 200 tối đa ~1 phút, lỗi thì tự rollback về ảnh cũ.

## Dữ liệu bền (volume /app/data)
`config.json` (mọi cấu hình), `accounts.json` (pool tài khoản), `piper/` `hf/` `kokoro/` (giọng TTS), `stt/` `stt-en/` (nhận diện giọng nói), `agent/` (skills, workflows, phiên chat, run_journal…), `zalo_bot/`, `chroma_db` (RAG hub).

## Không làm
- Không tự bịa số liệu sức khoẻ khi chưa gọi system_status/remote_system_status hoặc chưa xem log thật.
- Không tự ý chạy lệnh dọn/deploy trên server khi chưa được chủ nhà đồng ý.
