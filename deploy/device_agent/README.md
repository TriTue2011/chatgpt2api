# c2a-agent — cho dự án đọc/sửa file trên máy của bạn

Cài **một lệnh** lên máy tính / điện thoại Android / VPS / server. Agent tự
quay ra kết nối tới gateway, sau đó bot đọc/sửa file trên máy đó qua chat.

Vì agent **gọi ra** chứ không chờ ai gọi vào: máy sau NAT, wifi nhà, 4G điện
thoại đều dùng được. Không mở cổng, không cần IP tĩnh, không cần SSH.

> **Dùng Windows?** Có hướng dẫn từng bước riêng, chi tiết hơn:
> [HUONG_DAN_WINDOWS.md](HUONG_DAN_WINDOWS.md)

## 1. Khai báo thiết bị ở dự án

Cách nhanh nhất — gọi API, token tự sinh (thay `<KHOA_ADMIN>` bằng auth_key):

```bash
curl -X POST https://gpt.vhtatn.io.vn/api/devices \
  -H "Authorization: Bearer <KHOA_ADMIN>" -H "Content-Type: application/json" \
  -d '{"name":"laptop","label":"Laptop","paths":["/home/me/project"],"can_write":false}'
```

Trả về `token` — **copy ngay, không hiện lại lần nào nữa**.

Xem danh sách / xoá:

```bash
curl https://gpt.vhtatn.io.vn/api/devices -H "Authorization: Bearer <KHOA_ADMIN>"
curl -X DELETE https://gpt.vhtatn.io.vn/api/devices/laptop -H "Authorization: Bearer <KHOA_ADMIN>"
```

Đổi thư mục hoặc bật quyền ghi: xoá rồi thêm lại (token mới).

Hoặc sửa tay trong config (`device_agents`) — mỗi thiết bị một token riêng:

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
| `can_write` | `false` (mặc định) = chỉ đọc file. Bật `true` mới cho ghi/xoá. |
| `can_exec` | `false` (mặc định). Bật mới cho **chạy lệnh** PowerShell/cmd/sh + tắt tiến trình. |
| `can_power` | `false` (mặc định). Bật mới cho **khoá/ngủ/đăng xuất/tắt/khởi động lại**. |

Đổi quyền của thiết bị đã có mà **giữ nguyên token** (không phải chạy lại agent
để lấy token mới):

```bash
curl -X PATCH https://gpt.vhtatn.io.vn/api/devices/laptop \
  -H "Authorization: Bearer <KHOA_ADMIN>" -H "Content-Type: application/json" \
  -d '{"can_exec":true}'
```

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

### Bốn nhóm quyền — mỗi nhóm phải bật ở CẢ HAI phía

| Cờ khi chạy agent | Khoá ở dự án | Cho làm gì |
|---|---|---|
| *(không cần)* | *(không cần)* | Đọc file trong `--path`; tra cứu máy: thông tin, CPU/RAM/ổ đĩa, tiến trình, service, màn hình |
| `--allow-write` | `can_write` | Thêm · xoá · sửa file **trong `--path`** |
| `--allow-exec` | `can_exec` | Chạy lệnh PowerShell / cmd / sh; tắt ứng dụng; cài phần mềm bằng CLI |
| `--allow-power` | `can_power` | Khoá màn hình · ngủ · đăng xuất · **tắt máy** · khởi động lại |

Thiếu **một** phía là bị chặn — cố ý như vậy để sơ suất ở một chỗ không mở quyền.

> **`--allow-exec` nói thẳng:** bật cờ này là **allowlist thư mục hết ý nghĩa**.
> Một lệnh shell đọc/ghi/xoá được mọi thứ mà tài khoản đang chạy agent với tới,
> kể cả ngoài `--path`. Đừng chạy agent bằng quyền admin/root nếu không cần.
>
> Muốn hẹp lại: `--exec-allow` chỉ cho phép lệnh bắt đầu bằng tiền tố đã khai.
> ```bash
> python3 c2a_agent.py ... --allow-exec --exec-allow systemctl --exec-allow apt
> ```
> Đây là **hàng rào tiện dụng, KHÔNG phải hàng rào an ninh**: shell vẫn còn `;`,
> `&&`, backtick… Ai cần chặt thật thì đừng bật `--allow-exec`.

Nhóm tra cứu (`sysinfo`/`resources`/`processes`/`services`/`screen`) **không**
cần `--allow-exec`: agent chỉ chạy các lệnh **cố định do chính nó chọn**
(`tasklist`, `ps`, `systemctl list-units`…), mô hình không chèn được chữ nào vào
đó, và tất cả đều chỉ đọc. Bắt nhóm này đòi quyền exec thì muốn xem RAM cũng
phải mở quyền chạy lệnh tuỳ ý — đánh đổi ngược.

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

| Tool | Việc | Cần quyền |
|---|---|---|
| `device_list` | Thiết bị nào online, phạm vi, quyền gì | – |
| `device_ls` | Liệt kê thư mục | – |
| `device_read` | Đọc file (trần 200KB) | – |
| `device_find` | Tìm file theo mẫu tên | – |
| `device_stat` | Dung lượng, lần sửa cuối | – |
| `device_sysinfo` | Hệ điều hành, tên máy, CPU, người đăng nhập, uptime | – |
| `device_resources` | CPU % · RAM · ổ đĩa · load average | – |
| `device_processes` | Tiến trình đang chạy, sắp theo RAM, lọc theo tên | – |
| `device_services` | Danh sách service/daemon, hoặc trạng thái một service | – |
| `device_screen` | Màn hình sáng/tắt · đang khoá · bao lâu không ai chạm | – |
| `device_write` | Ghi đè file (tự sao lưu `.c2a.bak`) | `can_write` |
| `device_append` | Ghi thêm cuối file | `can_write` |
| `device_mkdir` | Tạo thư mục | `can_write` |
| `device_exec` | Chạy lệnh PowerShell/cmd/sh, cài phần mềm bằng CLI | `can_exec` |
| `device_kill` | Tắt ứng dụng theo pid hoặc tên | `can_exec` |
| `device_power` | Khoá · ngủ · đăng xuất · tắt máy · khởi động lại | `can_power` |

Ví dụ: *"xem thư mục /var/log trên VPS Sài Gòn có gì"*, *"đọc file config.yaml
trên laptop"*, *"sửa dòng port trong app.conf thành 8080"*, *"laptop còn bao
nhiêu RAM"*, *"Chrome trên máy tôi đang ăn bao nhiêu bộ nhớ"*, *"máy ở nhà có
đang khoá màn hình không"*, *"cài git trên VPS bằng apt"*, *"tắt Zoom trên
laptop"*, *"khoá màn hình máy công ty"*.

## An toàn

**Ba lớp chặn, cố ý trùng nhau** — hỏng một lớp vẫn còn hai lớp:

1. **Gateway**: token → đúng thiết bị + allowlist đường dẫn.
2. **Gateway**: chặn mọi thao tác ghi nếu thiết bị không bật `can_write`.
3. **Agent**: tự giữ allowlist của chính nó, **không tin gateway**. Gateway bị
   chiếm cũng không đọc/ghi được ra ngoài thư mục bạn cho phép.

Thêm:
- Symlink được resolve **trước** khi kiểm — link trỏ ra ngoài bị chặn.
- `..` bị chặn ở cả hai phía.
- Mọi lệnh đều được **in ra console của agent** kèm nội dung lệnh — chủ máy luôn
  thấy được cái gì vừa chạy trên máy mình, để `--allow-exec` không thành hộp đen.
- Trần đầu ra một lệnh 100KB; timeout mặc định 30s, tối đa 300s.
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
