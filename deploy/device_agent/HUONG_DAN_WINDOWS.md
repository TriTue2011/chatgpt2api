# Cài c2a-agent trên laptop Windows — từng bước

Mục tiêu: bot đọc (và nếu muốn, sửa) file trên laptop Windows của bạn, **qua
Internet bằng domain** — không mở cổng, không cần IP tĩnh, laptop nằm sau wifi
nhà hay 4G đều được.

Toàn bộ việc dưới đây bạn tự làm được, không cần ai hỗ trợ.

> **Cách nhanh hơn:** mở web UI → **MCP → tab "Thiết bị của tôi"**. Điền tên +
> thư mục, chọn *Qua Internet* hay *Trong mạng LAN*, chọn *Windows* — nó sinh
> sẵn từng lệnh kèm nút Copy, và hiện trạng thái online/offline của thiết bị.
> Tài liệu này dành cho lúc bạn muốn hiểu rõ từng bước hoặc không mở được UI.

---

## Bước 0 — Cần gì

| Thứ | Cách kiểm |
|---|---|
| Python 3.8+ | Mở PowerShell, gõ `python --version` |
| Laptop có Internet | Không cần cùng mạng LAN với máy chủ |
| Khoá admin của dự án | Cùng khoá bạn dùng đăng nhập web UI (`auth_key`) |

Nếu `python --version` báo lỗi hoặc mở Microsoft Store:

```powershell
winget install Python.Python.3.12
```

Cài xong **đóng PowerShell rồi mở lại** (để `python` vào PATH). Kiểm lại:

```powershell
python --version
```

Agent chỉ dùng thư viện có sẵn của Python — **không phải `pip install` gì cả**.

---

## Bước 1 — Biết đường dẫn thư mục muốn chia sẻ

Chọn một thư mục. Lần đầu nên chọn `Downloads` cho nhẹ đầu.

Mở PowerShell, lấy đường dẫn chính xác:

```powershell
echo $env:USERPROFILE
```

Ví dụ in ra `C:\Users\Viet` → thư mục Downloads của bạn là
`C:\Users\Viet\Downloads`.

> **Quan trọng:** đường dẫn này phải khớp **chính xác** với thứ bạn khai ở
> Bước 2. Khai `C:\Users\Viet\Downloads` mà chạy agent với
> `C:\Users\viet\downloads` vẫn được (không phân biệt hoa/thường trong
> Windows), nhưng đừng khai thiếu/thừa cấp thư mục.

Đừng khai `C:\` hay `C:\Users` — càng hẹp càng an toàn. Mở rộng sau lúc nào
cũng được.

---

## Bước 2 — Khai thiết bị ở dự án (lấy token)

Chạy trên **bất kỳ máy nào** gọi được tới dự án (kể cả chính laptop Win này).

PowerShell:

```powershell
$KEY  = "<KHOA_ADMIN>"
$BODY = @{
  name      = "laptop-win"
  label     = "Laptop Windows"
  paths     = @("C:\Users\Viet\Downloads")
  can_write = $false
} | ConvertTo-Json

irm -Method Post https://gpt.vhtatn.io.vn/api/devices `
  -Headers @{ Authorization = "Bearer $KEY" } `
  -ContentType "application/json" -Body $BODY
```

Trả về:

```json
{
  "ok": true,
  "name": "laptop-win",
  "token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "paths": ["C:\\Users\\Viet\\Downloads"],
  "can_write": false,
  "note": "Giữ token này — nó không hiện lại ở đâu khác."
}
```

**Copy `token` ra chỗ an toàn ngay** — nó chỉ hiện đúng lần này.

Giải thích các tham số:

| Tham số | Ý nghĩa |
|---|---|
| `name` | Tên máy trong dự án. Chỉ `a-z 0-9 _ -`, 2–31 ký tự. Đây là tên bạn gọi khi chat với bot. |
| `label` | Tên dễ đọc, hiện khi bot liệt kê thiết bị. |
| `paths` | Danh sách thư mục **duy nhất** được phép. Nhiều thư mục thì `@("C:\a", "C:\b")`. |
| `can_write` | `$false` = bot chỉ đọc file. `$true` mới cho thêm/xoá/sửa file. |
| `can_exec` | `$false`. `$true` cho bot **chạy lệnh** PowerShell/cmd + tắt ứng dụng. |
| `can_power` | `$false`. `$true` cho bot **khoá màn hình / tắt máy / khởi động lại**. |

Ba khoá `can_*` đều mặc định `$false`. Xem thêm ở Bước 4 — mỗi khoá còn phải kèm
một cờ khi chạy agent.

### Các lệnh quản lý khác

Xem danh sách thiết bị (thấy máy nào đang online):

```powershell
irm https://gpt.vhtatn.io.vn/api/devices -Headers @{ Authorization = "Bearer $KEY" }
```

Xoá thiết bị (token mất hiệu lực ngay, ngắt luôn phiên đang chạy):

```powershell
irm -Method Delete https://gpt.vhtatn.io.vn/api/devices/laptop-win `
  -Headers @{ Authorization = "Bearer $KEY" }
```

Muốn **đổi thư mục hoặc bật quyền ghi**: xoá rồi thêm lại (sẽ có token mới).

---

## Bước 3 — Cài agent: MỘT lệnh, chạy ẨN, tự bật khi mở máy

> Cách cũ (tải file rồi `python c2a_agent.py ...` trong PowerShell) bắt bạn giữ
> cửa sổ mở suốt — **tắt nhầm cửa sổ là bot mất kết nối**. Installer dưới đây
> đăng ký agent vào Task Scheduler chạy bằng `pythonw` (không có cửa sổ nào),
> tự bật lại khi mở máy, tự hồi mỗi phút nếu chết.

Dán vào PowerShell (thay token + thư mục của bạn):

```powershell
irm https://raw.githubusercontent.com/TriTue2011/chatgpt2api/main/deploy/device_agent/install-windows.ps1 -OutFile "$env:TEMP\c2a-install.ps1"
& "$env:TEMP\c2a-install.ps1" `
  -Url wss://gpt.vhtatn.io.vn/api/devices/agent `
  -Token "<TOKEN_TU_BUOC_2>" `
  -Paths "C:\Users\Viet\Downloads"
```

Muốn mở quyền thì thêm cờ — nhớ khoá tương ứng ở Bước 2 cũng phải bật:

| Muốn bot làm gì | Khoá ở Bước 2 | Cờ của installer |
|---|---|---|
| Đọc file · CPU/RAM/ổ đĩa · tiến trình | *(có sẵn)* | *(có sẵn)* |
| Thêm · xoá · sửa file | `can_write = $true` | `-AllowWrite` |
| Chạy lệnh · tắt ứng dụng | `can_exec = $true` | `-AllowExec` |
| Khoá màn hình · tắt máy | `can_power = $true` | `-AllowPower` |

Nhiều thư mục: `-Paths "D:\","E:\"`.

Installer in ra `agent ĐANG CHẠY ẨN (PID ...)` là xong. Những gì nó đã làm:

- agent nằm ở `%LOCALAPPDATA%\c2a-agent\c2a_agent.py`;
- token cất trong **biến môi trường User** `C2A_TOKEN` — không lộ trong cột
  Command line của Task Manager;
- task `c2a-agent` trong Task Scheduler: chạy lúc đăng nhập, ẩn, tự hồi;
- log tại `%LOCALAPPDATA%\c2a-agent\c2a-agent.log`.

Lệnh hay dùng sau khi cài:

```powershell
# Xem agent đang làm gì (log sống)
Get-Content "$env:LOCALAPPDATA\c2a-agent\c2a-agent.log" -Tail 20 -Wait

# Dừng / chạy lại ngay
Stop-ScheduledTask  -TaskName c2a-agent
Start-ScheduledTask -TaskName c2a-agent

# Gỡ sạch (task + file + biến môi trường)
& "$env:TEMP\c2a-install.ps1" -Uninstall
```

> **Đang chạy bản cũ trong cửa sổ PowerShell?** Tắt nó đi sau khi cài, vì hai
> bản cùng token sẽ giành nhau kết nối (phiên nối sau đá phiên trước, lặp mãi):
>
> ```powershell
> Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
>   Where-Object { $_.CommandLine -match 'c2a_agent' } |
>   ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
> ```

### Đổi quyền sau này

`PATCH` ở phía dự án (giữ nguyên token) **và** chạy lại installer với bộ cờ mới
— hai phía phải khớp, thiếu một là vẫn bị chặn:

```powershell
irm -Method Patch https://gpt.vhtatn.io.vn/api/devices/laptop-win `
  -Headers @{ Authorization = "Bearer $KEY" } `
  -ContentType "application/json" -Body '{"can_exec":true}'
& "$env:TEMP\c2a-install.ps1" -Url wss://gpt.vhtatn.io.vn/api/devices/agent -Token "<TOKEN>" -Paths "C:\Users\Viet\Downloads" -AllowExec
```

---

## Bước 5 — Thử qua chat

Nhắn bot (Zalo/Telegram):

- *"liệt kê thiết bị của tôi"* → thấy `laptop-win` 🟢 online
- *"xem thư mục Downloads trên Laptop Windows có gì"*
- *"đọc file C:\Users\Viet\Downloads\ghichu.txt"*
- *"laptop Windows còn bao nhiêu RAM, ổ C còn trống bao nhiêu"*
- *"Chrome trên laptop đang ăn bao nhiêu bộ nhớ"*
- *"laptop có đang khoá màn hình không"*

Có `--allow-exec` thì thêm được:

- *"chạy `ipconfig /all` trên laptop"*
- *"cài git trên laptop bằng winget"*
- *"tắt Zoom trên laptop"*

Có `--allow-power`:

- *"khoá màn hình laptop"* · *"khởi động lại laptop"*

Nếu bot nói không có công cụ đó: vào **Cài đặt → MCP**, bật **"Thiết bị của
tôi"** (`device_fs`), rồi restart container một lần (hub nạp MCP lúc khởi
động).

---

## Bước 6 — Tự chạy khi mở máy

Không cần làm gì — installer ở Bước 3 đã đăng ký sẵn Task Scheduler (chạy lúc
đăng nhập, ẩn, tự hồi mỗi phút nếu chết).

## Sự cố thường gặp

| Thông báo | Nguyên nhân → cách sửa |
|---|---|
| `python : The term 'python' is not recognized` | Chưa cài Python, hoặc cài rồi mà chưa mở lại PowerShell |
| `gateway từ chối handshake` | Sai `--url`. Phải đúng `wss://gpt.vhtatn.io.vn/api/devices/agent` |
| `gateway không chấp nhận: token không hợp lệ` | Token sai/đã xoá, hoặc bạn dán thiếu ký tự |
| `thiếu --path` | Cố ý chặn: không khai thư mục thì agent không chạy (tránh mở toàn máy do quên) |
| Bot bảo `'...' ngoài phạm vi cho phép` | File nằm ngoài `paths`. **Đây là chặn đúng, không phải lỗi.** Muốn mở thì khai lại thiết bị. |
| Bot bảo `chỉ được cấp quyền ĐỌC` | Chưa bật `can_write` ở dự án, hoặc thiếu `--allow-write` ở agent |
| Bot bảo `thiết bị 'x' chưa kết nối` | Agent không chạy / laptop mất mạng / đã đóng cửa sổ. Agent tự nối lại sau 5→120 giây |
| `mất kết nối: ... — thử lại sau 5s` | Bình thường khi mạng chớp. Agent tự nối lại, không cần làm gì |
| Đóng nắp laptop là mất kết nối | Windows ngủ thì mạng ngắt. Mở máy lên agent tự nối lại |

---

## Những giới hạn cần biết trước

- **Lệnh shell chỉ chạy khi bạn bật `--allow-exec`.** Không bật thì bot không
  chạy được chương trình gì trên máy bạn — nhưng vẫn xem được thông tin máy,
  CPU/RAM, tiến trình, service (agent chỉ dùng các lệnh cố định, chỉ đọc).
- Mỗi lệnh bot gửi xuống đều **in ra cửa sổ PowerShell** kèm nội dung lệnh — bạn
  luôn thấy được cái gì vừa chạy trên máy mình.
- **Trần dung lượng**: đọc 200KB, ghi 500KB, liệt kê 500 mục, tìm 200 kết quả
  mỗi lần.
- **Xoá**: chỉ xoá được file lẻ và thư mục **rỗng**. Không xoá cây thư mục.
- **Ghi đè**: luôn tạo bản sao `.c2a.bak` cạnh file gốc trước khi đè.
- **Symlink / shortcut** trỏ ra ngoài `paths` bị chặn.
- **iPhone không dùng được** — iOS không cho ứng dụng nền giữ kết nối lâu dài.
  Android (qua Termux) thì được.

## Ba lớp bảo vệ

Hỏng một lớp vẫn còn hai lớp:

1. **Dự án** kiểm token → ra đúng thiết bị + danh sách thư mục của nó.
2. **Dự án** chặn mọi thao tác ghi nếu thiết bị không bật `can_write`.
3. **Agent trên máy bạn** tự giữ danh sách thư mục và **không tin dự án**. Kể
   cả khi máy chủ bị chiếm, nó cũng không đọc/ghi được ra ngoài thư mục bạn
   khai ở `--path`.

Mặc định luôn nghiêng về phía an toàn: không khai thư mục ⇒ không mở gì;
`can_write` mặc định tắt; thiếu `--path` ⇒ agent từ chối chạy.
