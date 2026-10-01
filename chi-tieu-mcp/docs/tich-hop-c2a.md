# Tích hợp chi-tieu-mcp vào C2A

Viết cho tác giả C2A. Bot chạy thật cạnh C2A từ 16/09/2026 **mà không sửa code C2A**,
chỉ qua 3 điểm nối có sẵn bên dưới. Riêng trường hợp chỉ còn model ChatGPT Free thì
phải vá tay C2A — xem [c2a-ban-va-model-free/](c2a-ban-va-model-free/README.md).

## 3 điểm nối

1. **Vào — MCP server tuỳ chỉnh.** C2A gọi `http://<host>:8801/mcp` (streamable HTTP,
   stateless, không xác thực). FastMCP phải tạo với `host="0.0.0.0"`: để mặc định
   `127.0.0.1` thì mcp SDK tự bật chống DNS-rebinding và trả 421 cho Host header là IP
   LAN → C2A không gọi được tool nào, model tự bịa câu trả lời, không có lỗi nào hiện ra.
2. **Ra — cảnh báo chủ động.** `POST {C2A_BASE_URL}/api/zalo-personal/test-send`, JSON
   `{"thread_id": "...", "text": "...", "type": 0}`, header
   `Authorization: Bearer <auth_key>` (key admin tĩnh, `_legacy_admin_identity`). Phải là
   kênh Zalo Cá Nhân: kênh Bot API (`/api/zalo-bot/send`) trả `ok: true` nhưng tin tới
   bot khác, không tới nơi người dùng chat hằng ngày.
3. **Ra — hỏi AI** (nút "Hỏi AI phân tích" trên `/ui`). `POST {C2A_BASE_URL}/v1/chat/completions`,
   cùng header, `model: "auto:text"`, `user: "chi-tieu-bot-ui"` (kho ký ức riêng, không
   lẫn với chat Zalo), `x_allowed_groups: []` (lượt gọi tách biệt). Thiếu
   `x_allowed_groups: []` thì `_apply_branch_routing` có thể đổi sang nhánh vẽ ảnh khi
   prompt dính cụm như "trả về 1" (bỏ dấu thành "ve 1 ") — đã gặp: nhận ảnh PNG thay vì
   JSON sau 83 giây. Bot retry 1 lần khi C2A trả 5xx.

## Gợi ý preset (`services/mcp_presets.py`)

```python
MCPPreset(
    id="chi_tieu", name="Chi tiêu 6 hũ", icon="💰", category="finance",
    description="Ghi chi tiêu qua chat theo mô hình 6 hũ (JARS), cảnh báo vượt hũ "
                "qua Zalo Cá Nhân, trang quản lý /ui. Tự host bằng Docker.",
    url="",  # máy chạy bot của từng nhà — cài bằng url_override, vd http://<IP>:8801/mcp
    homepage="https://github.com/Quiz99/chi-tieu-mcp",
    tags=["finance", "budget", "vietnam"],
),
```

Tên server khi cài nên chứa "Chi tiêu" nếu dùng bản vá model free (bản vá nhận server
theo tên).

## Gợi ý service compose (chạy chung stack C2A)

Service `c2a` chạy trên mạng bridge mặc định của compose, cổng trong container là
`${APP_PORT:-80}` (cổng 3030 của máy chủ ánh xạ vào đó).

```yaml
  chi-tieu-bot:
    build: ./chi-tieu-mcp            # thư mục clone repo này
    container_name: chi-tieu-bot
    restart: unless-stopped
    profiles: ["chi-tieu"]
    env_file: ./chi-tieu-mcp/.env    # C2A_AUTH_KEY, C2A_ZALO_PERSONAL_THREAD_ID, SELF_BASE_URL
    environment:
      - TZ=Asia/Ho_Chi_Minh
      - C2A_BASE_URL=http://c2a:${APP_PORT:-80}   # gọi thẳng service c2a trong cùng network
    volumes:
      - ./chi-tieu-mcp/data:/app/data
    ports:
      - "8801:8801"                  # /ui cho điện thoại; /mcp chỉ nên mở trong LAN
```

- Bật: `docker compose --profile chi-tieu up -d`. URL MCP khai trong C2A:
  `http://chi-tieu-bot:8801/mcp`.
- `environment` đè `env_file`, nên `C2A_BASE_URL` trong `.env` của bot không cần sửa.
- `TZ` bắt buộc: nhãn kỳ lương của mỗi khoản chi được chốt lúc ghi, lệch múi giờ là
  sai vĩnh viễn (không tự sửa lại được).

## Bẫy đã gặp (đều hỏng im lặng)

- **2 kênh Zalo** — xem điểm nối 2.
- **Ký ức dài hạn và tóm tắt phiên.** `memory.sqlite` lưu nguyên văn hỏi–đáp, không kiểm
  chứng, rồi chèn lại cho lượt sau → model trả lời số dư bằng số nhớ được (vốn đã sai
  từ đầu). Tóm tắt phiên (`agent/sessions.sqlite`) cũng vậy: có dòng "Đã ghi nhận chi
  tiêu: X" thì model coi khoản mới giống hệt là tin lặp và không gọi tool. Bot chỉ chống
  được bằng docstring tool (luôn gọi tool lấy số mới; mỗi tin báo chi là khoản mới).
  Phía C2A có thể cân nhắc không lưu / không tóm tắt câu trả lời chứa số liệu lấy từ
  tool dữ liệu sống.
- **Model không gọi tool vẫn nói "đã ghi"** (Gemini Web; ChatGPT Free khi payload vượt
  trần hoặc bỏ qua lời dặn gọi tool) → mất khoản chi. Xem bản vá.
- **Từ khoá nhánh "auto"** — xem điểm nối 3.

## Bot cần gì ở C2A

- `auth_key` admin tĩnh (Cài đặt → Bảo mật).
- Tài khoản Zalo Cá Nhân đã đăng nhập (để gửi cảnh báo).
- Ít nhất 1 model gọi được tool thật trong combo `auto/chat`.
