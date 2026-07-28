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

## Bước 3 — Tải agent về laptop

```powershell
cd $HOME
irm https://raw.githubusercontent.com/TriTue2011/chatgpt2api/main/deploy/device_agent/c2a_agent.py -OutFile c2a_agent.py
```

File nằm ở `C:\Users\<tên>\c2a_agent.py`, khoảng 15KB.

---

## Bước 4 — Chạy agent

```powershell
cd $HOME
python c2a_agent.py `
  --url wss://gpt.vhtatn.io.vn/api/devices/agent `
  --token "<TOKEN_TU_BUOC_2>" `
  --path "C:\Users\Viet\Downloads" `
  --label "Laptop Windows"
```

Dấu **`` ` ``** cuối dòng là ký tự nối dòng của PowerShell (như `\` trên
Linux). Muốn viết một dòng thì bỏ hết dấu đó đi.

Chạy đúng sẽ thấy:

```
[c2a-agent] v1.0.0 — gateway wss://gpt.vhtatn.io.vn/api/devices/agent
[c2a-agent] đã kết nối — thiết bị 'laptop-win'
[c2a-agent] cho phép: C:\Users\Viet\Downloads | ghi: KHÔNG
```

**Cứ để cửa sổ PowerShell đó mở.** Đóng là agent dừng, bot mất kết nối tới
laptop. Mỗi lệnh bot gửi xuống sẽ in một dòng ở đây — bạn luôn thấy bot đang
làm gì trên máy mình.

Dừng agent: `Ctrl-C`.

### Bốn nhóm quyền — mỗi nhóm bật ở CẢ HAI phía

| Muốn bot làm gì | Khoá ở Bước 2 | Cờ ở Bước 4 |
|---|---|---|
| Đọc file · xem thông tin máy, CPU/RAM/ổ đĩa, tiến trình, service, màn hình | *(có sẵn)* | *(có sẵn)* |
| Thêm · xoá · sửa file | `can_write = $true` | `--allow-write` |
| Chạy lệnh PowerShell/cmd · cài phần mềm · tắt ứng dụng | `can_exec = $true` | `--allow-exec` |
| Khoá màn hình · tắt máy · khởi động lại | `can_power = $true` | `--allow-power` |

Thiếu **một** phía là vẫn bị chặn — cố ý như vậy để sơ suất ở một chỗ không mở
quyền. Đổi quyền sau này thì dùng `PATCH` (giữ nguyên token, không phải chạy lại
agent):

```powershell
irm -Method Patch https://gpt.vhtatn.io.vn/api/devices/laptop-win `
  -Headers @{ Authorization = "Bearer $KEY" } `
  -ContentType "application/json" -Body '{"can_exec":true}'
```

Hoặc nhanh hơn: vào **MCP → Thiết bị của tôi**, tích ô ngay trên dòng thiết bị.

> **`--allow-exec` cần biết trước khi bật:** lúc đó danh sách thư mục ở `--path`
> **không còn tác dụng** với lệnh shell. Một lệnh PowerShell đọc/ghi/xoá được mọi
> thứ mà tài khoản Windows của bạn với tới. Muốn hẹp lại thì thêm
> `--exec-allow winget --exec-allow sc` — chỉ cho lệnh bắt đầu bằng tiền tố đó.

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

## Bước 6 — Tự chạy khi mở máy (không bắt buộc)

Để không phải mở PowerShell dán lệnh mỗi lần.

**Cách 1 — Task Scheduler** (khuyến nghị):

1. Mở *Task Scheduler* → **Create Task**
2. Tab *General*: đặt tên `c2a-agent`, tick **Run whether user is logged on or not**
3. Tab *Triggers* → New → **At log on**
4. Tab *Actions* → New:
   - Program/script: `pythonw`
   - Add arguments:
     ```
     C:\Users\Viet\c2a_agent.py --url wss://gpt.vhtatn.io.vn/api/devices/agent --token <TOKEN> --path "C:\Users\Viet\Downloads"
     ```
5. Tab *Settings*: tick **If the task fails, restart every 1 minute**

Dùng `pythonw` (không phải `python`) để không hiện cửa sổ đen. Đổi lại thì
không xem được log — muốn xem thì thêm `> C:\Users\Viet\c2a.log 2>&1`.

**Cách 2 — file .bat trong Startup** (đơn giản hơn):

Tạo `c2a.bat`:

```bat
@echo off
cd /d %USERPROFILE%
python c2a_agent.py --url wss://gpt.vhtatn.io.vn/api/devices/agent --token <TOKEN> --path "%USERPROFILE%\Downloads"
```

Nhấn `Win+R`, gõ `shell:startup`, copy file `.bat` vào thư mục vừa mở.

> **Lưu ý bảo mật:** cả hai cách trên đều để token dạng chữ thường trong file
> hoặc trong tham số (người khác dùng chung máy có thể thấy qua Task Manager).
> Muốn kín hơn thì đặt biến môi trường `C2A_TOKEN` rồi bỏ `--token` đi — agent
> tự đọc biến đó.

---

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
