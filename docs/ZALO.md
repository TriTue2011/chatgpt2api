# Zalo trong chatgpt2api

Tài liệu tổng thể: có mấy đường Zalo, đường nào dùng khi nào, định dạng chữ cài
ở đâu. Cách gửi ảnh và nối với Home Assistant nằm riêng ở
[ZALO_ANH_VA_HOME_ASSISTANT.md](ZALO_ANH_VA_HOME_ASSISTANT.md).

## Hai loại tài khoản Zalo, đừng nhầm

| | Zalo cá nhân | Zalo Bot (OA) |
|---|---|---|
| Là gì | Tài khoản Zalo thật của bạn | Tài khoản bot đăng ký ở bot.zapps.me |
| Thư viện | `zca-js` (không chính thức) | REST API chính thức |
| Ai nhắn được | Bất kỳ ai trong danh bạ / nhóm | Chỉ người đã bấm Bắt đầu với bot |
| Mã trong repo | `zalo-server/` (Node.js) + `services/zalo_personal.py` | `services/zalo_bot.py` |
| Định dạng chữ | style theo khoảng ký tự | `parse_mode=markdown` |
| Rủi ro | Zalo có thể khoá tài khoản | Không |

Zalo cá nhân **chỉ cho một kết nối trên mỗi tài khoản**. Đăng nhập cùng một tài
khoản ở nơi thứ hai là nơi thứ nhất bị đá ra, và nó rụng lặng lẽ — chỉ thấy
trong log dòng `Another connection is opened, closing this one`. Dựng bản thử
nghiệm thì phải dùng tài khoản khác.

## Ba mảnh ghép và quan hệ giữa chúng

```
Zalo cá nhân ─┬─ zalo-server (trong repo này, cổng 3001) ─── services/zalo_personal.py
              │
              └─ add-on has-addons/zalo_bot (cổng 3000) ─── tích hợp HACS TriTue2011/zalo_bot
                                                                    │
Zalo Bot OA ────── services/zalo_bot.py ───────────────────────────┘ (Home Assistant)
```

`zalo-server/` trong repo này và add-on `has-addons/zalo_bot` là **hai bản riêng
của cùng một máy chủ Node.js**, đã tách nhánh từ lâu. Chúng không đồng bộ tự
động; sửa lỗi ở một bên phải xem xét chép sang bên kia.

**Khác biệt lớn nhất:** bản trong repo này có `routes/chat.js` (giao diện chat
PWA), `services/messageStore.js`, và được `services/zalo_personal.py` gọi tới để
tự định dạng chữ. Bản add-on gọn hơn, tự đứng một mình, dành cho người ngoài cài
về.

## Định dạng chữ

### Ba tầng, chồng lên nhau

**Tầng 1 — model tự viết.** Câu trả lời sinh ra đã có `**...**`, `*...*`, `#`,
`- ` như bình thường.

**Tầng 2 — engine luật tự tô thêm.**
[`services/telegram/emphasis.py`](../services/telegram/emphasis.py) quét lại câu
trả lời và bọc đậm những thứ model bỏ sót:

- Số kèm đơn vị: `°C`, `%`, `kWh`, `V`, `A`, `lux`, `hPa`, `ppm`, phút/giờ/giây,
  kg/km/m, `₫`/VND/USD
- Cặp *nhãn: giá trị* — Nhiệt độ:, Độ ẩm:, Trạng thái:, Pin:, Điện áp:, Giá:,
  Số dư:, AQI:, PM2.5:
- Từ chỉ trạng thái

Hai lớp chặn để không phá chữ: bỏ qua đoạn đã có markdown, và không bọc giá trị
dài quá 60 ký tự (tránh tô đậm cả một câu văn).

**Tầng 3 — nhớ sở thích từng người.**
[`services/agent/orchestrator.py`](../services/agent/orchestrator.py) nhận ra khi
người dùng nói về *cách bày* chứ không phải nội dung — "chia mục", "gạch đầu
dòng", "ngắn gọn", "bỏ tóm tắt", "đừng dùng emoji", "không cần link" — rồi bắt
buộc gọi `remember` để lưu, và áp cho các lượt sau.

### Đổi bằng lệnh chat

Capability `cai_dat_dinh_dang` nhận các câu như:

> "đừng in đậm nữa" · "in nghiêng thay vì in đậm" · "bỏ gạch chân" ·
> "đừng dùng danh sách" · "bỏ thụt lề"

Hỏi trống không thì bot báo đang để thế nào.

**Màu thì không đổi được bằng lệnh** — cố ý, để tránh bot tự đổi màu giữa chừng.
Màu chỉnh trong Settings.

### Cài đặt cố định — chỉnh ở đâu

| Cài đặt | Khoá | Mặc định | Chỉnh ở |
|---|---|---|---|
| Màu nhấn mạnh | `markdown_color` | `orange` | Settings → panel Zalo cá nhân (theo từng tài khoản) |
| Cỡ chữ | `markdown_size` | `normal` | Settings → thẻ Telegram/Zalo |
| Gạch chân | `markdown_underline` | bật | lệnh chat hoặc khoá config |
| Danh sách | `markdown_list` | bật | lệnh chat hoặc khoá config |
| Thụt lề | `markdown_indent` | bật | lệnh chat hoặc khoá config |

Thứ tự ưu tiên: **admin entry (theo từng người nhận) → bot → cấu hình kênh**.
Xem [`services/zalo_bot_format.py`](../services/zalo_bot_format.py).

Màu nhận `red` · `orange` · `yellow` · `green`, hoặc `none`/`off` để tắt. Cỡ chỉ
có `normal` và `big` — Zalo không có cỡ nào khác.

### Mã style Zalo cá nhân

[`services/zalo_markdown.py`](../services/zalo_markdown.py) đổi markdown thành
style theo khoảng ký tự:

| Mã | Nghĩa |
|---|---|
| `b` · `i` · `u` · `s` | đậm · nghiêng · gạch chân · gạch ngang |
| `f_18` · `f_13` | to · nhỏ — **chỉ có hai cỡ này** |
| `c_db342e` `c_f27806` `c_f7b503` `c_15a85f` | đỏ · cam · vàng · xanh lá |
| `lst_1` · `lst_2` | danh sách chấm đầu dòng · đánh số |
| `ind_10` … `ind_40` | thụt lề bốn cấp |

Khoảng tính theo **đơn vị UTF-16** (emoji đếm là 2) — module đã quy đổi sẵn.

**`f_20` không phải mã hợp lệ.** Bảng `TextStyle` của zca-js chỉ có `f_13` và
`f_18`; gửi `f_20` lên thì Zalo bỏ qua, chữ ra đậm nhưng không to.

## Bảo mật

`zalo-server` chạy ở cổng **3001**, khai trong `docker-compose.yml`. Đừng mở ra
Internet — đây là cổng quản trị một tài khoản Zalo thật.

| Biến môi trường | Việc |
|---|---|
| `ZALO_SERVER_API_KEY` | Khoá cho API gửi tin. Phía Python dùng chính khoá này. |
| `ZALO_SERVER_ADMIN_PASSWORD` | Mật khẩu admin. Để trống thì tự sinh và lưu vào `.admin_password` trong thư mục dữ liệu. |
| `ZALO_SERVER_ADMIN_USERNAME` | Mặc định `admin`. |
| `SESSION_SECRET` | Khoá ký phiên. Để trống thì tự sinh một lần rồi giữ lại. |
| `ZALO_WS_ALLOWED_ORIGINS` | Origin được mở WebSocket. Khai đúng origin của **chính zalo-server**, không phải của app chính. |
| `ZALO_COOKIE_SECURE` | Giữ `0`: bot gọi zalo-server qua HTTP nội bộ. |

Vài điều đáng biết:

- Khoá API **chỉ nhận qua header** `Authorization: Bearer` hoặc `X-Api-Key`.
  Không nhận `?api_key=` trên URL, vì query string rò vào access log của proxy,
  lịch sử trình duyệt và header `Referer`.
- Khoá API chỉ cấp quyền **gửi nội dung**. Đọc lịch sử chat, tra người dùng, tạo
  và sửa nhóm đều phải đăng nhập admin.
- Khi `ZALO_SERVER_ADMIN_PASSWORD` được khai, đổi mật khẩu admin qua giao diện
  web bị chặn (trả `409`) — vì env mới là nguồn credential cho gateway Python,
  đổi riêng một bên sẽ làm hai tiến trình lệch nhau ngay.
- Đăng nhập cấp mã phiên **mới**, chống session fixation.

## Kiểm tra còn sống

```bash
curl -s http://127.0.0.1:3001/api/health
# {"success":true,"status":"ok","uptime":3600,"accounts":1}
```

Không cần đăng nhập, không chạm tới Zalo. `accounts` bằng `0` nghĩa là chưa quét
QR hoặc phiên đã mất.

## Chạy test

```bash
cd zalo-server && node --test test/*.test.js test/*.mjs
```

Chạy từ **thư mục gốc repo** thì `authService` sẽ di trú
`data/cookies/users.json` sẵn có vào thư mục dữ liệu tạm và test đăng nhập sẽ
sai — bộ test tự dựng thư mục riêng, nhưng script thủ công thì nên `cd` sang một
thư mục trung tính trước.

## Có gì mới ở 2026.08.23

- Băm mật khẩu chuyển sang `crypto.pbkdf2` bất đồng bộ. Bản cũ dùng
  `pbkdf2Sync` chặn toàn bộ event loop — đo trên máy ARM là **3,4 giây** cho
  600.000 vòng, và trong lúc đó tiến trình không nhận được tin Zalo nào.
- Khoá API thôi nhận qua query string.
- Đăng nhập cấp mã phiên mới, kèm ghi phiên tường minh trước khi trả lời.

Hai mục **cố ý không đổi**, dù bản add-on đã gỡ: `sharp` được dùng thật để đọc
kích thước ảnh (chọn thay `image-size` vì thư viện kia dính advisory vòng lặp vô
hạn với ICNS/JXL/HEIF), và `ingressPath` được 16 tệp view cùng `routes/chat.js`
dùng thật.
