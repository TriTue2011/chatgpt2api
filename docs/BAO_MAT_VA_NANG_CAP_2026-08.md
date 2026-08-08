# Đợt vá bảo mật & hướng dẫn nâng cấp — 08/2026

Tài liệu này ghi lại **đợt rà soát bảo mật 07–08/08/2026**: những lỗ hổng đã vá,
**biến môi trường mới bắt buộc**, cấu hình `docker-compose.yml` + `.env` chuẩn,
các bước nâng cấp từ bản cũ, và cách xử lý những sự cố hay gặp khi nâng cấp.

> **Đọc mục [4. Nâng cấp từ bản cũ](#4-nâng-cấp-từ-bản-cũ) trước khi redeploy.**
> Bản mới thêm biến môi trường và đổi cách seed tài khoản admin của zalo-server;
> bỏ qua bước này có thể làm bot Zalo không đăng nhập được.

---

## 1. Thay đổi ảnh hưởng tới vận hành

| Thay đổi | Ảnh hưởng | Bắt buộc làm gì |
|---|---|---|
| Bỏ secret mặc định trong compose (`your_secret_key_here`, `changeme…`) | Deploy **dừng ngay** nếu thiếu biến | Khai 5 biến bắt buộc (mục 2) |
| zalo-server không còn seed `admin/admin` | Cài mới sinh mật khẩu **ngẫu nhiên** nếu thiếu env | Đặt `ZALO_SERVER_ADMIN_PASSWORD` |
| `SESSION_SECRET` không còn giá trị mặc định | Thiếu → sinh ngẫu nhiên mỗi lần chạy → **mất session sau restart** | Đặt một chuỗi cố định |
| Chạy code do LLM sinh: **mặc định TẮT** | Pipeline code chỉ soi tĩnh, không chạy thật | Bật lại bằng `pipeline_chay_thu=true` nếu thực sự cần |
| Key vai `user` không còn chạm được Home Assistant / SSH / thiết bị | Tích hợp dùng key `user` mất quyền điều khiển nhà | Dùng khoá admin (`CHATGPT2API_AUTH_KEY`) cho HA |
| WebSocket zalo-server yêu cầu đăng nhập **admin** | Trang chat cũ không nhận tin nếu chưa đăng nhập | Đăng nhập dashboard trước khi mở chat |
| CORS đọc từ `cors_allow_origins` (mặc định vẫn `*`) | Không đổi hành vi nếu chưa cấu hình | Nên khai domain thật (mục 6) |
| `ZALO_SERVER_API_KEY` chỉ dùng được cho **route gửi tin** | Key này không còn mở dashboard / lịch sử chat / quản lý người dùng (trả 403 `API_KEY_OUT_OF_SCOPE`) | Home Assistant không bị ảnh hưởng; script nào dùng key để đọc dashboard phải chuyển sang đăng nhập tài khoản |
| Dashboard và chat zalo-server yêu cầu vai **admin** | Tài khoản vai `user` bị 403 ở mọi trang trừ đổi mật khẩu | Dùng tài khoản admin. Cần nhiều người dùng thì phải làm ACL trước (mục 8) |
| Tool đọc web của MCP Hub chặn địa chỉ **nội bộ** | `read_url`, `get_law_detail`, ingest theo URL không còn đọc được `127.0.0.1`, `192.168.*`, `169.254.169.254` | Không cần làm gì. Muốn nạp tài liệu nội bộ thì tải file lên thay vì đưa URL |
| `vn_law` chỉ đọc được các cổng văn bản pháp luật | URL ngoài `thuvienphapluat.vn`, `vbpl.vn`, `chinhphu.vn`, `moj.gov.vn` bị từ chối | Dùng `read_url` cho trang khác |
| SSH của MCP Hub ghi nhớ khoá máy chủ | Khoá máy chủ đổi (cài lại OS) → lệnh SSH bị **từ chối** | Xoá dòng host đó trong `/app/data/ssh_known_hosts` rồi chạy lại |

---

## 2. Biến môi trường

### Bắt buộc — thiếu là deploy dừng

| Biến | Dùng để làm gì |
|---|---|
| `CHATGPT2API_AUTH_KEY` | Khoá admin của API + dashboard |
| `CAPTCHA_SOLVER_API_KEY` | Xác thực nội bộ tới captcha-solver (Flow/Gemini web login) |
| `ZALO_SERVER_API_KEY` | Bearer cho HA/API gọi zalo-server (:3001) |
| `VNC_PASSWORD` | Mật khẩu noVNC (:6080) |
| `DB_PASSWORD` | Chỉ khi `STORAGE_BACKEND=postgres` |

### Khuyến nghị cho production

| Biến | Không đặt thì sao |
|---|---|
| `SESSION_SECRET` | App tự sinh ngẫu nhiên mỗi lần chạy → **mọi phiên đăng nhập zalo-server mất sau mỗi restart**. Tạo bằng `openssl rand -base64 48` |
| `ZALO_SERVER_ADMIN_PASSWORD` | Khi seed lần đầu (chưa có `users.json`) sẽ sinh mật khẩu **ngẫu nhiên**, và **bot Python không đăng nhập được** vì nó đọc cùng biến này |

### Tuỳ chọn

| Biến | Mặc định | Ghi chú |
|---|---|---|
| `ZALO_SERVER_ADMIN_USERNAME` | `admin` | Tên đăng nhập dashboard zalo-server |
| `ZALO_COOKIE_SECURE` | `0` | **Chỉ đặt `1` khi zalo-server chỉ truy cập qua HTTPS.** Bot Python gọi `http://127.0.0.1:3001` và giữ session cookie — đặt `1` là bot mất phiên, kênh Zalo chết |
| `ZALO_WS_ALLOWED_ORIGINS` | trống | Danh sách origin (phẩy) được mở WebSocket zalo-server. Để trống = dùng luật same-host. **Chỉ khai origin của chính zalo-server**, không phải domain của app chính, kẻo chặn nhầm trang chat |
| `ZALO_DEV_ENDPOINTS` | không đặt | `1` mới bật các endpoint debug (`/api/test-login`, `/api/test-json`, `/api/debug-users-file`, `/api/debug-webhook-config`, `/api/reset-admin-password`). **Production đừng đặt** |
| `CHATGPT2API_BASE_URL` | — | URL công khai để dựng link ảnh (khi chạy sau tunnel) |

> `MCP_HUB_INTERNAL_URL`, `ACCOUNTS_DB`, `CAPTCHA_SOLVER_DATA_DIR`… đã có sẵn
> trong image — **không cần khai lại** trong compose.

---

## 3. Cấu hình chuẩn

### 3.1. `.env`

```bash
# ── BẮT BUỘC ──────────────────────────────────────────────────────────
CHATGPT2API_AUTH_KEY=khoa_admin_manh
CAPTCHA_SOLVER_API_KEY=khoa_captcha_manh
ZALO_SERVER_API_KEY=khoa_zalo_api_manh
VNC_PASSWORD=mat_khau_vnc_manh
# Chỉ cần khi STORAGE_BACKEND=postgres
DB_PASSWORD=mat_khau_postgres_manh

# ── KHUYẾN NGHỊ (production) ──────────────────────────────────────────
# openssl rand -base64 48
SESSION_SECRET=chuoi_ngau_nhien_toi_thieu_32_byte
ZALO_SERVER_ADMIN_PASSWORD=mat_khau_admin_zalo_manh

# ── TUỲ CHỌN ──────────────────────────────────────────────────────────
ZALO_SERVER_ADMIN_USERNAME=admin
```

> **Không** khai `ZALO_WS_ALLOWED_ORIGINS` trừ khi zalo-server có domain HTTPS
> riêng — để trống là an toàn và không phá WebSocket của trang chat.

### 3.2. `docker-compose.yml`

```yaml
services:
  c2a:
    image: ghcr.io/tritue2011/chatgpt2api:latest
    container_name: c2a
    restart: unless-stopped

    ulimits:
      nofile:
        soft: 65536
        hard: 65536

    # Chỉ cần khi dùng Postgres chạy trên host
    extra_hosts:
      - "host.docker.internal:host-gateway"

    ports:
      - "3030:80"                # API + dashboard
      - "127.0.0.1:6080:6080"    # noVNC — chỉ localhost (bỏ 127.0.0.1 nếu cần LAN)
      - "3001:3001"              # zalo-server — chỉ giữ nếu HA ở máy khác
      - "10600:10600"            # Wyoming TTS/STT
      - "10700:10700"            # WhisperLive

    volumes:
      - /opt/c2a/data:/app/data
      - /etc/localtime:/etc/localtime:ro
      - /etc/timezone:/etc/timezone:ro

    environment:
      TZ: Asia/Ho_Chi_Minh
      STORAGE_BACKEND: json      # hoặc postgres (kèm DATABASE_URL bên dưới)
      # DATABASE_URL: "postgresql://c2a_user:${DB_PASSWORD:?required}@host.docker.internal:5432/c2a_db"
      # CHATGPT2API_BASE_URL: https://your-domain.com

      # Bắt buộc — thiếu là deploy dừng
      CHATGPT2API_AUTH_KEY: ${CHATGPT2API_AUTH_KEY:?required}
      CAPTCHA_SOLVER_API_KEY: ${CAPTCHA_SOLVER_API_KEY:?required}
      ZALO_SERVER_API_KEY: ${ZALO_SERVER_API_KEY:?required}
      VNC_PASSWORD: ${VNC_PASSWORD:?required}

      # zalo-server. Image TRƯỚC hotfix 6d8c039 đòi các biến này phải TỒN TẠI
      # (dù rỗng) — thiếu là supervisord không parse được config → crash loop.
      SESSION_SECRET: ${SESSION_SECRET:-}
      ZALO_SERVER_ADMIN_PASSWORD: ${ZALO_SERVER_ADMIN_PASSWORD:-}
      ZALO_SERVER_ADMIN_USERNAME: ${ZALO_SERVER_ADMIN_USERNAME:-admin}
      ZALO_COOKIE_SECURE: "0"    # PHẢI là "0" — xem mục 2
      ZALO_WS_ALLOWED_ORIGINS: ${ZALO_WS_ALLOWED_ORIGINS:-}

    security_opt:
      - no-new-privileges:true

    healthcheck:
      test:
        - CMD
        - python3
        - -c
        - "import urllib.request; urllib.request.urlopen('http://localhost:80/version', timeout=5)"
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

---

## 4. Nâng cấp từ bản cũ

**Bước 1 — Tạo `.env`** theo mục 3.1 (đặt giá trị thật, không dùng ví dụ).

**Bước 2 — Cập nhật `docker-compose.yml`** theo mục 3.2.

> Portainer: dán `.env` vào phần **Environment variables** của stack (mỗi biến
> **đúng một lần**, khai trùng sẽ báo *"This environment variable is already
> defined"*), còn compose để trong **Web editor**.

**Bước 3 — Deploy lại** (Portainer: Update stack, bật **Re-pull image**).

**Bước 4 — Nếu bot Zalo báo `đăng nhập bot server thất bại (401)`:**

Xảy ra khi `users.json` đã tồn tại từ trước với mật khẩu khác giá trị
`ZALO_SERVER_ADMIN_PASSWORD` hiện tại. Xử lý:

```bash
docker stop c2a
cd /opt/c2a/data/zalo_bot
mv cookies/users.json cookies/users.json.bak   # tài khoản dashboard
mv sessions sessions.bak && mkdir -p sessions  # session cũ ký bằng secret cũ
docker start c2a
```

> ⚠️ **Chỉ đụng `users.json` và `sessions/`.** File `cookies/cred_*.json` là
> credential tài khoản Zalo cá nhân — xoá là phải quét QR đăng nhập lại.

Sau khi khởi động, log sẽ ghi
`Đã tạo users.json với admin 'admin' (mật khẩu từ ZALO_SERVER_ADMIN_PASSWORD)`.
Đăng nhập lại dashboard tại `http://<IP>:3001/admin-login`.

**Bước 5 — Đồng bộ khoá captcha-solver.** Nếu log có
`invalid api key` hoặc `auto-login-status ... 401`: vào **Settings → Flow**, đặt
`captcha_solver_api_key` **bằng đúng** giá trị `CAPTCHA_SOLVER_API_KEY` trong
`.env`. (Bản cũ dùng chung một giá trị cho cả hai khoá; tách ra thì phải sửa.)

**Bước 6 — Siết CORS và host tin cậy** (không bắt buộc, nên làm khi chạy sau
domain công khai) — xem mục 6.

---

## 5. Danh sách lỗ hổng đã vá

### Xác thực & phân quyền

| Lỗi | Sửa |
|---|---|
| Telegram webhook chấp nhận **mọi secret sai/rỗng** khi chỉ có 1 bot (auth bypass) | Bỏ fallback single-bot, so sánh `hmac.compare_digest` |
| Key vai `user` điều khiển được Home Assistant / SSH / thiết bị qua `/v1/chat` | Trần quyền theo vai: `user` không có `homeassistant`/`device`/`server`/`code` |
| Fast-path HA chạy **trước** khi kiểm quyền → vẫn bật/tắt được thiết bị | 5 fast-path gác chung `_thread_denies("homeassistant")` + trần 8 lệnh/lượt |
| zalo-server ghi **mật khẩu thô + salt + full hash** ra log mỗi lượt đăng nhập | Xoá toàn bộ log nhạy cảm, so hash bằng `timingSafeEqual` |
| `/reset-admin-password` đặt lại mật khẩu về `admin` cố định (backdoor) | Bịt ở production, mật khẩu ngẫu nhiên + PBKDF2 600.000 vòng |
| Tài khoản mặc định `admin/admin` | Seed từ env hoặc sinh ngẫu nhiên; PBKDF2 1.000 → 600.000 vòng (tương thích ngược) |
| `SESSION_SECRET` mặc định đoán được | Bỏ default, sinh ngẫu nhiên nếu thiếu env |
| Không giới hạn số lần đăng nhập sai | Rate-limit theo IP (10 lần/15 phút → khoá 15 phút) |
| Giả IP bằng `X-Forwarded-For` để né khoá brute-force | Mặc định dùng `request.client.host`; chỉ tin XFF khi `security.trust_forwarded_for` |
| Client tự gắn cờ `x_agent_internal` để né nhật ký kiểm toán | Chỉ tin khi có header nội bộ khớp `auth_key` |
| WebSocket zalo-server phát **toàn bộ tin nhắn** cho mọi client, không xác thực | `noServer` + xác thực session **admin** + kiểm Origin + `maxPayload` 1MB + giới hạn 50 kết nối |
| API key tích hợp (`ZALO_SERVER_API_KEY`) đi qua middleware chung → mở được cả dashboard, lịch sử chat, quản lý người dùng | Allowlist: key chỉ dùng cho route gửi tin/tra cứu tích hợp; ngoài đó trả 403 |
| Route UI/chat chỉ kiểm "đã đăng nhập", không kiểm vai → tài khoản vai `user` đọc toàn bộ hội thoại và gửi tin thay mọi tài khoản Zalo | Thêm cổng vai `dashboardRoleMiddleware`: dashboard/chat cần vai `admin`; chỉ chừa đổi mật khẩu và đăng xuất |
| Header `Host` / `X-Forwarded-Host` giả mạo được (allowlist chỉ dùng lúc dựng URL ảnh) | `TrustedHostMiddleware` thật, bật khi khai `security.trusted_hosts`; luôn cho `localhost` để healthcheck nội bộ không gãy |

### Thực thi mã & truy cập hệ thống

| Lỗi | Sửa |
|---|---|
| Chạy Python do LLM sinh, mặc định **bật**, không có sandbox thật | **Mặc định TẮT**; chỉ soi tĩnh. Bật lại bằng `pipeline_chay_thu=true` |
| Bộ chạy code không giới hạn RAM/CPU | `setrlimit`: RAM 1GB, CPU, file 64MB |
| SSH dùng `AutoAddPolicy` (nhận mọi host key → MITM lấy mật khẩu) | Trust-on-first-use qua `known_hosts`, fail khi host key đổi (2 vị trí) |
| MCP Hub vẫn dùng `AutoAddPolicy` **không** đọc/ghi `known_hosts` → mọi lần kết nối đều là "lần đầu", khoá đổi cũng không ai biết | TOFU ghi ra `/app/data/ssh_known_hosts`, từ chối khi khoá đổi; `ssh_list_servers` in vân tay SHA256 để đối chiếu |
| SSRF: tải `image_url` bằng `urlopen` thẳng | Qua `net_guard.fetch_media` + kiểm magic bytes |
| SSRF ở MCP Hub: `read_url`, `read_url_rendered`, `extract_text`, `get_law_detail`, ingest theo URL nhận URL tự do — prompt injection đọc được `169.254.169.254` (credential cloud) hay `127.0.0.1:3001` (API nội bộ) | Module chung `src/url_guard.py`: chỉ `http`/`https`, phân giải DNS rồi chặn loopback/private/link-local (kể cả IPv6 bọc IPv4), **kiểm lại từng chặng redirect**, trần 5MB + timeout. Trình duyệt render chặn ở tầng request nên bắt cả subresource và điều hướng nội bộ |
| `vn_law` nhận URL bất kỳ dù chỉ có nghĩa với site pháp luật | Allowlist domain (`thuvienphapluat.vn`, `vbpl.vn`, `chinhphu.vn`, `moj.gov.vn`) |
| Webhook/MCP URL cho phép `file://`, `gopher://` | Chỉ `http`/`https` (vẫn cho LAN) |
| Path traversal khi xoá backup | `resolve().relative_to(BACKUP_DIR)` |
| Token/mật khẩu lọt access-log qua query string | Tắt `--access-log` của uvicorn, bỏ `?password=` |
| `gitpython 3.1.57` — 5 CVE đã công bố (backend lưu trữ `git`) | Nâng lockfile lên `3.1.58`; `pyproject.toml` không đổi vì đã là `>=3.1.57` |

### DoS & ổn định

| Lỗi | Sửa |
|---|---|
| Webhook tạo thread xử lý AI **không giới hạn** (Telegram, Zalo Bot, Zalo Personal) | Worker pool có semaphore, giữ slot tới khi xử lý xong |
| Body webhook nạp vô hạn vào RAM (kể cả `chunked`) | `read_json_limited` đọc theo chunk, dừng ở 2MB |
| Upload không giới hạn (audio, ảnh, PDF, proxy MCP hub) | Trần 50MB (upload) / 100MB (proxy, ingest) |
| Model phát 100 tool call → 100 thread | Trần 32 tool/lượt, tối đa 8 worker |
| Đọc backup TAR không giới hạn | Trần số file, kích thước mỗi file và tổng |
| Ghi config đồng thời ghi đè nhau (mất cấu hình MCP, undo rotate token) | `ConfigStore.mutate()` khoá cả đọc-sửa-ghi |
| `/v1/images/edits` đọc `await upload.read()` không trần, không giới hạn số ảnh | Trần 20MB/ảnh, 8 ảnh, tổng 48MB |
| Proxy captcha đọc `await request.body()` không trần | `read_body_limited` 32MB, trả 413 |
| Proxy có cap request nhưng **buffer response upstream vô hạn** (`upstream.content`) | `read_upstream_limited` — cắt response ở đúng trần, trả 502 |
| Hub `/api/studio/convert` đọc `await file.read()` không trần | Dùng chung `read_upload_limited` (100MB) như `analyze_source` |
| Cache tool MCP đóng băng kết quả **rỗng** 15 phút khi hub chưa kịp lên → bot mất sạch tool sau mỗi lần khởi động | Phân biệt "server không có tool" với "không nối được"; chưa nối được thì TTL rút còn 30 giây |

### XSS & rò rỉ dữ liệu

| Lỗi | Sửa |
|---|---|
| Nội dung tin nhắn Zalo nhét thẳng vào `innerHTML` (stored XSS) | Escape ở `messages.ejs`, `webhooks.ejs`, `account-webhook-manager.ejs`, `user-management.ejs` |
| URL avatar/ảnh/tệp phá vỡ attribute, cho `javascript:` | `utils.safeUrl()` — chỉ `http`/`https`/`data:image` |
| Endpoint debug công khai (`/api/debug-users-file`…) | Bịt sau `ZALO_DEV_ENDPOINTS`, gỡ khỏi route công khai |
| TLS verify tắt toàn bộ luồng đăng ký (gửi mật khẩu/OTP/OAuth code) | Bật lại mặc định; tắt được qua `security.register_tls_verify=false` |
| Allowlist email khớp chuỗi con (`admin` khớp `admin@evil.com`) | Khớp chính xác hoặc theo `@domain`; agent email mất quyền HA/SSH/device/code |

---

## 6. Cấu hình nên siết thêm (không bắt buộc)

Trong **Settings** của dashboard (hoặc `config.json`):

```jsonc
{
  // Chỉ cho phép domain thật gọi API từ trình duyệt (mặc định là "*")
  "cors_allow_origins": ["https://your-domain.com", "http://192.168.1.10:3030"],

  "security": {
    // Domain/IP hợp lệ cho header Host. Khai vào đây là BẬT TrustedHostMiddleware:
    // request có Host ngoài danh sách bị trả 400 (localhost luôn được phép để
    // healthcheck nội bộ không gãy). Cũng dùng để chặn X-Forwarded-Host giả khi
    // dựng URL ảnh. Khai THIẾU một domain đang dùng = tự khoá mình ra ngoài,
    // nên liệt kê đủ mọi đường vào: domain public, IP LAN, tên container.
    "trusted_hosts": ["your-domain.com", "192.168.1.10"],

    // Chỉ bật khi CÓ reverse proxy đặt X-Forwarded-For
    "trust_forwarded_for": false,

    // Đặt false nếu proxy nội bộ cắt TLS (mặc định true - nên giữ)
    "register_tls_verify": true
  }
}
```

Ngoài ra:
- Đừng mở `3001` (zalo-server) và `6080` (noVNC) ra Internet. HA cùng máy thì
  bind `127.0.0.1:3001:3001`.
- Giữ `reply_enabled = false` cho kênh email tới khi có xác thực người gửi
  (SPF/DKIM/DMARC) — header `From` giả mạo được.

---

## 7. Xử lý sự cố

**Container restart liên tục, log ghi `Error: Format string ... ENV_SESSION_SECRET ... cannot be expanded`**
Image trước hotfix `6d8c039` yêu cầu 4 biến zalo-server phải **tồn tại**. Khai
đủ 4 biến trong compose (mục 3.2) hoặc cập nhật image mới nhất.

**Bot Zalo: `đăng nhập bot server thất bại (401)`**
Mật khẩu trong `users.json` khác `ZALO_SERVER_ADMIN_PASSWORD`. Làm theo bước 4
mục 4.

**Log: `invalid api key` / `auto-login-status ... 401`**
`providers.flow.captcha_solver_api_key` lệch `CAPTCHA_SOLVER_API_KEY`. Xem bước 5.

**Trang chat zalo-server không nhận tin realtime**
- Chưa đăng nhập, hoặc đăng nhập bằng tài khoản **không phải admin** (WS yêu cầu admin).
- Hoặc `ZALO_WS_ALLOWED_ORIGINS` khai origin không khớp nơi đang mở trang → để trống.

**MCP tools `count: 0`, log `Connection refused ... 127.0.0.1:8005`**
App dò MCP trước khi hub kịp mở cổng (hub cần ~40 giây để mount hết MCP). Từ bản
này, khi có server chưa nối được thì cache chỉ giữ **30 giây** rồi dò lại — chờ
một lượt là tự khỏi, log ghi `mcp_partial_discovery`. Bản cũ giữ 15 phút; muốn
dò lại ngay thì tắt/bật một MCP trong tab quản trị.

**Tool `read_url` / ingest URL trả `Từ chối đọc URL này: …`**
URL trỏ vào vùng nội bộ (loopback, `192.168.*`, `10.*`, `169.254.*`) — bị chặn có
chủ đích để prompt injection không đọc được service nội bộ hay metadata cloud.
Cần nạp tài liệu nội bộ thì tải file lên, đừng đưa URL.

**Lệnh SSH qua MCP báo `khoá máy chủ ĐÃ ĐỔI`**
Máy đích đổi host key (thường do cài lại OS) — hoặc có người đứng giữa. Nếu chắc
chắn là do cài lại: xoá dòng của host đó trong `/app/data/ssh_known_hosts` rồi
chạy lại. Vân tay đang ghi nhớ xem bằng `ssh_list_servers`.

**Home Assistant / script gọi zalo-server trả 403 `API_KEY_OUT_OF_SCOPE`**
`ZALO_SERVER_API_KEY` giờ chỉ dùng được cho các route gửi tin/tra cứu tích hợp
(`/api/sendmessage`, `/api/sendImageToUser`, `/api/getUserInfo`…). Gọi dashboard,
lịch sử chat hay quản lý người dùng thì phải đăng nhập bằng tài khoản admin.

**Đăng nhập được nhưng mọi trang trả 403 "Chỉ admin mới vào được"**
Tài khoản đang dùng có vai `user`. Dashboard và chat hiện yêu cầu vai `admin` —
xem mục 8 để biết vì sao và cần gì để mở lại cho nhiều người dùng.

**`R2 restore failed: InvalidBucketName`**
Sửa `/opt/c2a/data/studio/r2.json`: `bucket` chỉ là tên trần (không `https://`,
không dấu `/`), `endpoint` dạng `https://<account-id>.r2.cloudflarestorage.com`.

---

## 8. Việc còn lại (chưa làm)

Những mục này cần build frontend/Docker và kiểm thử trên trình duyệt, **chưa
được vá**:

- Token đăng nhập, mật khẩu Gmail app và TOTP seed vẫn lưu trong `localStorage`
  → cần chuyển sang cookie `httpOnly` + CSRF, vault phía server.
- `/api/settings` vẫn trả toàn bộ config (gồm secret) → cần DTO che giá trị,
  trường secret chỉ-ghi.
- Chưa có CSP; `/images/` chưa có URL ký hạn; SSE vẫn nhận `?token=` trên query.
- Dockerfile chưa pin digest/checksum cho binary tải về; container chạy `root`.
- Frontend còn 26 lỗi TypeScript, `ignoreBuildErrors: true` đang che lỗi build.
- Dependency Node: zalo-server 8–9 lỗ hổng mức cao (`axios`, `ws`, `sharp`,
  `image-size`), web 1–2 mức trung bình. **Không** chạy `npm audit fix --force`
  — nâng lockfile ở nhánh riêng rồi build và chạy hồi quy. `image-size` chưa có
  bản vá, nên trước mắt giảm bề mặt xử lý ảnh không tin cậy.
  (Phía Python đã sạch: xem `gitpython` ở mục 5.)
- **ACL nhiều người dùng cho zalo-server.** Hiện dashboard và chat chỉ mở cho vai
  `admin`, vì hệ thống không có cách giới hạn một tài khoản chỉ xem được một số
  tài khoản Zalo hay một số cuộc trò chuyện. Muốn cho vai `user` vào chat thì
  phải làm ACL theo account/conversation **và** lọc cả dữ liệu broadcast qua
  WebSocket — nửa vời là hở đúng chỗ vừa bịt.
- **DNS rebinding.** `url_guard` kiểm địa chỉ trước khi gọi và ở mỗi chặng
  redirect, nhưng giữa lúc kiểm và lúc mở kết nối vẫn còn một khe rất hẹp để
  tên miền đổi bản ghi. Bịt hẳn phải tự nối theo IP đã ghim và tự lo SNI/TLS.

**Nếu đã từng dùng giao diện trước bản vá này**, nên xoay: khoá admin, token
tunnel, mật khẩu Gmail app và TOTP seed.
