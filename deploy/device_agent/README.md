# c2a-agent — cho dự án đọc/sửa file trên máy của bạn

Cài **một lệnh** lên máy tính / điện thoại Android / VPS / server. Agent tự
quay ra kết nối tới gateway, sau đó bot đọc/sửa file trên máy đó qua chat.

Vì agent **gọi ra** chứ không chờ ai gọi vào: máy sau NAT, wifi nhà, 4G điện
thoại đều dùng được. Không mở cổng, không cần IP tĩnh, không cần SSH.

## 1. Khai báo thiết bị ở dự án

Thêm vào config (`device_agents`) — mỗi thiết bị một token riêng:

```json
"device_agents": {
  "laptop": {
    "label": "Laptop của Việt",
    "token": "<chuỗi ngẫu nhiên ≥16 ký tự>",
    "paths": ["/home/viet/project", "/var/log"],
    "can_write": true,
    "enabled": true
  }
}
```

| Khoá | Ý nghĩa |
|---|---|
| `token` | Bí mật để agent tự nhận diện. Tối thiểu 16 ký tự — token ngắn bị từ chối ngay. |
| `paths` | **Chỉ** những thư mục này được đọc/sửa. Để rỗng = không cho gì cả. |
| `can_write` | `false` (mặc định) = chỉ đọc. Bật `true` mới cho ghi/xoá. |

Sinh token: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`

## 2. Chạy agent trên thiết bị

Chỉ cần Python 3.8+. **Không cài thêm gói nào** — thuần stdlib.

```bash
python3 c2a_agent.py \
  --url wss://gpt.vhtatn.io.vn/api/devices/agent \
  --token <TOKEN> \
  --path /home/viet/project \
  --path /var/log \
  --allow-write \
  --label "Laptop của Việt"
```

Bỏ `--allow-write` là thiết bị **chỉ đọc**, kể cả khi config bật `can_write`.

### Android (Termux)

```bash
pkg install python
python3 c2a_agent.py --url wss://... --token <TOKEN> --path /sdcard/Documents
```

Điện thoại hay ngủ làm đứt kết nối — giữ tỉnh bằng:
```bash
termux-wake-lock
nohup python3 c2a_agent.py ... > ~/c2a.log 2>&1 &
```

### Linux/VPS — chạy nền vĩnh viễn (systemd)

`/etc/systemd/system/c2a-agent.service`:

```ini
[Unit]
Description=c2a device agent
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 /opt/c2a/c2a_agent.py \
  --url wss://gpt.vhtatn.io.vn/api/devices/agent \
  --path /srv/app --allow-write --label "VPS Sài Gòn"
Environment=C2A_TOKEN=<TOKEN>
Restart=always
RestartSec=10
User=c2a

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now c2a-agent
```

Dùng `C2A_TOKEN` thay vì `--token` để token không lộ trong `ps aux`.

### Windows / macOS

Chạy y như Linux. Muốn tự khởi động thì Windows dùng Task Scheduler, macOS
dùng `launchd`.

### iPhone/iOS — không hỗ trợ

iOS không cho app nền giữ kết nối lâu dài. Không có cách nào làm kiểu "cài
một lệnh rồi để đó" trên iPhone.

## 3. Dùng qua chat

Bot có các tool (MCP `device_fs`, bật ở Cài đặt → MCP):

| Tool | Việc |
|---|---|
| `device_list` | Xem thiết bị nào online, phạm vi, có quyền ghi không |
| `device_ls` | Liệt kê thư mục |
| `device_read` | Đọc file (trần 200KB) |
| `device_write` | Ghi đè file (tự sao lưu `.c2a.bak`) |
| `device_append` | Ghi thêm cuối file |
| `device_find` | Tìm file theo mẫu tên |
| `device_stat` | Xem dung lượng, lần sửa cuối |
| `device_mkdir` | Tạo thư mục |

Ví dụ: *"xem thư mục /var/log trên VPS Sài Gòn có gì"*, *"đọc file
config.yaml trên laptop"*, *"sửa dòng port trong app.conf thành 8080"*.

## An toàn

**Ba lớp chặn, cố ý trùng nhau** — hỏng một lớp vẫn còn hai lớp:

1. **Gateway**: token → đúng thiết bị + allowlist đường dẫn.
2. **Gateway**: chặn mọi thao tác ghi nếu thiết bị không bật `can_write`.
3. **Agent**: tự giữ allowlist của chính nó, **không tin gateway**. Gateway bị
   chiếm cũng không đọc/ghi được ra ngoài thư mục bạn cho phép.

Thêm:
- Symlink được resolve **trước** khi kiểm — link trỏ ra ngoài bị chặn.
- `..` bị chặn ở cả hai phía.
- **Không có lệnh shell.** Chỉ thao tác file.
- Ghi đè luôn sao lưu `.c2a.bak` và thay file **nguyên tử** (không để lại
  file nửa vời nếu mất điện giữa lúc ghi).
- Xoá: chỉ xoá file lẻ và thư mục **rỗng** — không xoá cây thư mục.
- Trần: đọc 200KB, ghi 500KB, liệt kê 500 mục, tìm 200 kết quả.

Đã kiểm chứng đầu-cuối (19/19): chặn đọc ngoài allowlist, chặn leo `..`, chặn
ghi `/etc/passwd`, chặn thao tác lạ, và thiết bị chỉ-đọc vẫn đọc được nhưng
không ghi được.

## Sự cố thường gặp

| Triệu chứng | Nguyên nhân → cách sửa |
|---|---|
| `gateway từ chối handshake` | Sai `--url`. Phải có đuôi `/api/devices/agent` |
| `gateway không chấp nhận: token không hợp lệ` | Token lệch config, hoặc `enabled: false`, hoặc token < 16 ký tự |
| `thiếu --path` | Fail-closed cố ý: không khai thư mục nào thì không mở gì |
| `ngoài phạm vi cho phép` | Đường dẫn ngoài `--path`. Đây là chặn đúng, không phải lỗi |
| `chế độ CHỈ ĐỌC` | Thiếu `--allow-write` ở agent, hoặc `can_write: false` ở config |
| `thiết bị 'x' chưa kết nối` | Agent chưa chạy / mất mạng. Agent tự nối lại sau 5→120s |
