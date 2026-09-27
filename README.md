# c2a — trợ lý AI tiếng Việt cho gia đình, chạy trên máy nhà

c2a (tên repo: `chatgpt2api`) là **một container** gom mọi thứ một ngôi nhà cần từ AI:

| Mảng | Làm được gì |
|---|---|
| **Bot chat** | Trợ lý tiếng Việt trên **Zalo** (bot + tài khoản cá nhân) và **Telegram**: hỏi đáp, tìm web, nhắc hẹn, đọc ảnh/tệp, trả lời bằng giọng nói, phân quyền theo từng nhóm/người |
| **Nhà thông minh** | Điều khiển **Home Assistant** bằng lời; tự học thói quen (bật gì, lúc nào, trong điều kiện nào) rồi hỏi hoặc tự làm |
| **Giọng nói tại chỗ** | Đọc (TTS) và nghe (STT) tiếng Việt ngay trên máy, không gửi tiếng ra ngoài; cổng **Wyoming** cho HA Assist; phát ra loa Google Cast / HA |
| **Nhìn nhà (camera)** | Nhận người/vật bằng YOLO26, nhận **khuôn mặt** người nhà, canh cửa, tìm người, **trông xe** (báo động khoảng 2 giây sau khi có người đụng vào xe) — không cần Frigate |
| **Dịch** | Máy dịch tự dựng trong stack (không tốn lượt AI): chữ, ảnh, tài liệu, phụ đề video, phiên dịch qua mic |
| **Nhạc & video** | Tìm YouTube / Zing MP3 rồi phát ra loa, tivi trong nhà |
| **Cổng AI** | Biến tài khoản ChatGPT, Codex, Gemini, Claude… thành API chuẩn OpenAI, có chuỗi dự phòng khi một nhà cung cấp chết; kèm hơn 20 máy chủ MCP (thời tiết, tin tức, giá vàng, luật, RAG…) |

Tài liệu chi tiết từng tab, từng ô cài đặt: **[HUONG_DAN.md](HUONG_DAN.md)**.

---

## Cài lần đầu — tóm tắt

Làm đủ năm bước dưới đây là chạy được. Giải thích từng bước nằm ở
[HUONG_DAN.md, Phần 1](HUONG_DAN.md#1-chạy-lần-đầu).

### Bước 0 — Máy cần có

| Thứ | Mức tối thiểu |
|---|---|
| Docker Engine + plugin `docker compose` v2 | 20.10 trở lên |
| CPU | x86-64 hoặc ARM64 |
| RAM | 4 GB; bật giọng nói và camera thì nên 8 GB |
| Đĩa trống | 15 GB: ảnh c2a 5,8 GB, còn lại cho dữ liệu và model |

Cài Docker trên NAS, Portainer, GPU: [CHUAN_BI_TRUOC_KHI_PULL.md](CHUAN_BI_TRUOC_KHI_PULL.md).

### Bước 1 — Lấy mã nguồn

```bash
git clone https://github.com/TriTue2011/chatgpt2api.git /opt/c2a
cd /opt/c2a
```

Cần bản git vì compose đọc `deploy/searxng/settings.yml` từ đây.

### Bước 2 — Tạo tệp `.env` với năm khoá bắt buộc

Thiếu khoá nào thì `docker compose` **dừng ngay** và báo tên khoá đó. Lệnh dưới sinh
sẵn chuỗi ngẫu nhiên:

```bash
cat > .env <<EOF
CHATGPT2API_AUTH_KEY=$(openssl rand -hex 24)
CAPTCHA_SOLVER_API_KEY=$(openssl rand -hex 24)
ZALO_SERVER_API_KEY=$(openssl rand -hex 24)
VNC_PASSWORD=$(openssl rand -hex 8)
SEARXNG_SECRET=$(openssl rand -hex 32)
VAULT_MASTER_KEY=$(openssl rand -base64 32)
VAULT_REQUIRE_ENCRYPTION=1
EOF
chmod 600 .env
grep CHATGPT2API_AUTH_KEY .env      # đây là MẬT KHẨU đăng nhập web
```

| Khoá | Dùng để làm gì |
|---|---|
| `CHATGPT2API_AUTH_KEY` | Mật khẩu đăng nhập web và API key (`Authorization: Bearer …`) |
| `CAPTCHA_SOLVER_API_KEY` | Khoá nội bộ của bộ giải captcha khi đăng nhập web ChatGPT/Gemini/Claude |
| `ZALO_SERVER_API_KEY` | Khoá nội bộ của máy chủ Zalo trong container |
| `VNC_PASSWORD` | Mật khẩu noVNC (cổng 6080) — trình duyệt để đăng nhập tay |
| `SEARXNG_SECRET` | Khoá của máy tìm kiếm SearXNG đi kèm |
| `VAULT_MASTER_KEY` (nên có) | Mã hoá mật khẩu và mã TOTP đã lưu. **Mất khoá là phải nhập lại hết** — chép một bản ra ngoài máy |

### Bước 3 — Dùng ảnh dựng sẵn rồi chạy

`docker-compose.yml` mặc định dựng ảnh từ mã nguồn, mất 15–30 phút và tốn nhiều RAM.
Dùng ảnh dựng sẵn trên GHCR thì chỉ cần tải về:

```bash
# Thay khối build: … image: c2a:latest bằng ảnh dựng sẵn
sed -i '/^  c2a:$/,/^    image: c2a:latest$/{/build:/d;/context: \./d;/dockerfile: Dockerfile/d;s|image: c2a:latest|image: ghcr.io/tritue2011/chatgpt2api:latest|}' docker-compose.yml
grep -n "image: ghcr.io/tritue2011/chatgpt2api" docker-compose.yml   # phải in ra một dòng

mkdir -p /opt/c2a-data
docker compose up -d
docker compose ps            # c2a phải "Up … (healthy)" sau khoảng 1 phút
```

Dữ liệu nằm ở `/opt/c2a-data` (dòng `volumes:` của service `c2a`) — đổi chỗ khác thì
sửa dòng đó **trước** khi chạy.

### Bước 4 — Đăng nhập và thêm tài khoản AI

Mở `http://<IP-máy>:3030`, đăng nhập bằng `CHATGPT2API_AUTH_KEY`. Sau đó:

1. `▸ AI Core → Tài khoản`: thêm ít nhất một tài khoản AI.
2. `▸ Studio → Chat`: gõ thử một câu — có trả lời là đường ống thông.
3. `▸ Hệ thống → Cài đặt → Cấu hình chung`: điền **Địa chỉ truy cập hình ảnh** =
   `http://<IP-máy>:3030`, thiếu thì ảnh/âm thanh gửi ra Zalo là link hỏng.

### Bước 5 — Tải model (chỉ làm một lần)

**Ảnh Docker không kèm model** — model nằm trong thư mục dữ liệu để cập nhật ảnh không
mất và ảnh không phình. Vào **`▸ Hệ thống → Cài đặt → Model cần tải`**: thẻ này kiểm
từng model đã có chưa, đánh dấu cái nào **Cần** cho tính năng bạn đang bật, và cho
lệnh tải để bấm «Chép» rồi dán vào máy chủ.

Bộ khởi đầu cho tiếng Việt (nghe + đọc + camera), khoảng 300 MB:

```bash
docker exec c2a /app/.venv/bin/python scripts/download_stt_model.py                 # nghe tiếng Việt ~100 MB
docker exec c2a /app/.venv/bin/python scripts/download_silero_vad.py                # cắt đoạn lời nói 0,6 MB
docker exec c2a /app/.venv/bin/python scripts/download_piper_voices.py --pack minimal   # giọng đọc mặc định ~64 MB
docker exec c2a /app/.venv/bin/python scripts/download_nhin_nha.py                  # YOLO + khuôn mặt ~140 MB, chỉ khi dùng camera
```

Gọi đúng `/app/.venv/bin/python` — lệnh `python` trần trong container là Python hệ
thống, thiếu thư viện nên vài script tải sẽ lỗi. Model nạp ở lần dùng đầu, không cần
khởi động lại — trừ cổng Wyoming cho Home Assistant: cổng chỉ mở lúc c2a khởi động, nên
tải model nghe/đọc của một tiếng mới xong thì `docker compose restart c2a` một lần.

Danh sách đủ mọi model (giọng hay hơn, tiếng Anh/Trung/Nhật/Hàn, từ điển):
[HUONG_DAN.md, mục 1.6](HUONG_DAN.md#16-tải-model--bảng-đầy-đủ).

---

## Tiếp theo đọc gì

| Muốn | Đọc |
|---|---|
| Bật bot Zalo / Telegram | [HUONG_DAN.md, Phần 5](HUONG_DAN.md#5-kết-nối-bot-telegram--zalo), [docs/ZALO.md](docs/ZALO.md) |
| Nối Home Assistant, camera, nhận mặt | [HUONG_DAN.md, mục 3.7](HUONG_DAN.md#37-home-assistant) |
| Giọng nói, loa, HA Assist qua Wyoming | [HUONG_DAN.md, Phần 4](HUONG_DAN.md#4-bật-giọng-nói-ttsstt-và-phát-ra-loa) |
| Phân quyền theo nhóm / người | [HUONG_DAN.md, Phần 6](HUONG_DAN.md#6-lọc-chức-năng-theo-thread) |
| Dịch máy tự chủ, GPU | [docs/DICH_MAY_TU_CHU.md](docs/DICH_MAY_TU_CHU.md), [docs/NGHE_GPU.md](docs/NGHE_GPU.md) |
| Dùng như API OpenAI, đăng nhập ChatGPT | [README_ChatGPT2API.vi.md](README_ChatGPT2API.vi.md) |
| Máy chủ MCP và RAG | [README_VN_MCP_HUB.vi.md](README_VN_MCP_HUB.vi.md) |
| Biến môi trường mới, bảo mật khi nâng cấp | [docs/BAO_MAT_VA_NANG_CAP_2026-08.md](docs/BAO_MAT_VA_NANG_CAP_2026-08.md) |

## Cập nhật lên bản mới

```bash
cd /opt/c2a && git pull && docker compose pull && docker compose up -d
```

Dữ liệu và model giữ nguyên. Muốn tự cập nhật thì chạy thêm
[Watchtower](https://containrrr.dev/watchtower/): nó kéo ảnh `:latest` mới rồi khởi động
lại c2a.

Dọn đĩa: `docker image prune -f` (**không** thêm `-a` — cờ đó xoá luôn ảnh cũ bạn cần để
lùi khi bản mới hỏng).

## Sự cố

Bảng hiện tượng → cách xử lý: [HUONG_DAN.md, Phần 7](HUONG_DAN.md#7-sự-cố-thường-gặp).
Bot trả lời lạ thì xem trước ở `▸ Hệ thống → Agent runs` — mỗi lượt ghi nó đã gọi công
cụ nào.
