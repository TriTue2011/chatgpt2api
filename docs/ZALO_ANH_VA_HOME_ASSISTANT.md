# Zalo: gửi ẢNH và dùng từ Home Assistant

Cài đặt kênh từ đầu xem `HUONG_DAN_GIONG_NOI_VA_KENH.md` mục 3–4. File này chỉ
nói về **gửi ảnh** và **gọi từ Home Assistant** — hai chỗ dễ mất thời gian nhất
vì các giới hạn không nằm trong mã, mà nằm ở nền tảng Zalo.

---

## 0. Chọn kênh nào — đọc bảng này trước

Hai kênh **khác hẳn nhau**, không phải hai chế độ của một thứ. Chọn sai là phải
làm lại từ đầu.

| | **Zalo Cá Nhân** | **Zalo Bot** |
|---|---|---|
| Danh tính | Tài khoản Zalo của **người thật** | Bot riêng, có tên riêng |
| Đăng nhập | Quét mã QR (cookie) | Bot token |
| Thư viện | `zca-js` — **không chính thức** | Zalo Bot API — **chính thức** |
| Gửi nhiều ảnh | ✅ **Album thật**: 1 tin, N ảnh | ❌ Không có. Mỗi ảnh 1 tin |
| Ảnh cục bộ | ✅ Gửi trực tiếp từ đường dẫn tệp | ❌ Phải là **URL công khai** |
| Nhận tin | Listener nền | Long-poll hoặc webhook |
| Rủi ro | Tài khoản có thể bị Zalo **khoá** | Ổn định |
| Tính năng nhóm/kết bạn/reaction | ✅ Có | ❌ Không |

Nói gọn: **cần album ảnh → Zalo Cá Nhân. Cần ổn định lâu dài → Zalo Bot.** Không
có đường nào vừa album vừa chính thức, vì Bot API không có phương thức nào gửi
nhiều ảnh trong một tin.

---

## 1. Zalo Cá Nhân — gửi nhiều ảnh

### Bốn endpoint nhận mảng ảnh

| Đích | Endpoint |
|---|---|
| Người, chọn tài khoản | `POST /api/sendImagesToUserByAccount` |
| Nhóm, chọn tài khoản | `POST /api/sendImagesToGroupByAccount` |
| Người, theo `ownId` | `POST /api/sendImagesToUser` |
| Nhóm, theo `ownId` | `POST /api/sendImagesToGroup` |

```jsonc
// body
{
  "imagePaths": ["/duong/dan/a.jpg", "/duong/dan/b.png"],  // MẢNG
  "threadId": "...",
  "accountSelection": "+84...",   // hoặc "ownId": "..."
  "caption": "Ảnh sân trước",     // không bắt buộc
  "nghiMs": 1500                  // không bắt buộc, nghỉ giữa các lô
}
```

Phản hồi có thêm `soAnh`, `soLo`, `maxFilePerMessage`, `canhBao` — đọc `soLo` để
biết vì sao 30 ảnh lại thành nhiều tin, thay vì tưởng hệ thống gửi lặp.

### Bốn lưu ý bắt buộc biết

**1. Giới hạn số ảnh mỗi tin do SERVER ZALO cấp, không có trong mã.** Nó nằm ở
`settings.features.sharefile.max_file`, lấy lúc đăng nhập, và **đổi theo tài
khoản**. Vượt là `zca-js` ném `Exceed maximum file of N` và **mất cả lô — không
tấm nào tới**. Hệ thống tự đọc giới hạn thật rồi chia lô; đọc không được thì
dùng chốt an toàn 6 ảnh/tin.

**2. Chỉ `jpg` · `jpeg` · `png` · `webp` vào được khối album.** Định dạng khác bị
xếp loại "others" và gửi thành **tệp đính kèm**, không phải ảnh.

**3. GIF đi đường riêng.** `zca-js` lọc GIF ra khỏi khối rồi gửi từng cái, nên
trộn GIF vào là phá album — người nhận thấy ảnh rời rạc. Hệ thống **chặn sớm và
nói rõ**, gửi GIF thì gửi riêng.

**4. Nhiều ảnh + chữ = HAI tin.** `zca-js` chỉ dán chữ làm caption khi gửi **đúng
một** ảnh; từ hai tấm trở lên nó gửi chữ ở một tin riêng TRƯỚC rồi mới tới album.
Đây là hành vi cố ý của thư viện, không phải lỗi.

Thêm một điều không ai biết con số: gửi dồn dễ ăn `Vượt quá số request cho phép,
code 221`. Ba issue của `zca-js` (#114, #223, #325) đều báo lỗi này khi gửi nhiều
ảnh, và **chính người bảo trì trả lời là họ không rõ ngưỡng**, chỉ khuyên tạm
dừng 1–24 giờ. Vì vậy hệ thống **nghỉ giữa các lô** (mặc định 1500 ms). Đừng hạ
`nghiMs` xuống 0 để "cho nhanh".

### Nếu dùng integration HA `zalo_bot` (repo cộng đồng)

Integration đó **là Zalo Cá Nhân** dù tên là "zalo_bot" — nó đăng nhập bằng QR
qua một server `zca-js`, không dùng bot token. Đừng nhầm với mục 2 dưới đây.

Bẫy cú pháp: service `send_images_to_user` khai `image_paths` là **một chuỗi**,
trong code làm `.split(",")`:

```yaml
# ĐÚNG — một chuỗi, các ảnh cách nhau bằng dấu phẩy
service: zalo_bot.send_images_to_user
data:
  thread_id: "123456789"
  account_selection: "+84xxxxxxxxx"
  image_paths: "/config/www/cam1.jpg,/config/www/cam2.jpg"

# SAI — viết kiểu danh sách YAML thì không nhận
  image_paths:
    - /config/www/cam1.jpg
```

Bản gốc của integration đó **không chia lô, không nghỉ, và ảnh lỗi thì âm thầm bỏ
qua** — chỉ báo lỗi khi *tất cả* ảnh đều thất bại. Trỏ nó vào `zalo-server` của
dự án này thì được chia lô và soát định dạng.

---

## 2. Zalo Bot — gửi ảnh

### Giới hạn của nền tảng, không phải của mã

- Chỉ có `sendPhoto` — **một ảnh mỗi lời gọi**. Không có `sendMediaGroup`, không
  có album. N ảnh = N tin rời.
- `photo` phải là **URL http(s) CÔNG KHAI**: Zalo tự đi tải về. Đường dẫn tệp cục
  bộ, `file://`, hay URL trong LAN đều không dùng được.
- `caption` tối đa **2000** ký tự.
- Có `sendVoice` (chỉ 1-1, không dùng cho nhóm). **Không** gửi được file
  Word/PDF/video.

### Vì sao HA phải đi qua server này

Ảnh camera của HA nằm ở `/config/www/...` trong mạng LAN. Zalo ở ngoài Internet
**không tải được**. Server này đã phục vụ `/images/` công khai không cần token,
nên chỗ hợp lý để nối là ở đây: HA đẩy tệp lên, server lưu vào kho công khai rồi
gọi `sendPhoto`. HA **không cần mở ra Internet**.

### `POST /api/zalo-bot/send`

Nhận `multipart/form-data`. Cần `Authorization: Bearer <token admin>`.

| Trường | Ý nghĩa |
|---|---|
| `text` | Câu cảnh báo. Có ảnh thì thành caption |
| `photo` | **Tệp ảnh** upload thẳng từ HA |
| `photo_url` | Dùng khi ảnh đã có URL công khai sẵn |
| `chat_id` | Để trống → gửi cho admin của bot đang hoạt động |

Chỉ có `text` → gửi `sendMessage`. Có ảnh → `sendPhoto` kèm caption.

Ảnh không phải PNG được **chuyển thật** sang PNG (kho ảnh luôn đặt tên `.png`,
nên byte JPEG trong tệp `.png` làm content-type trả về sai). Ảnh hỏng trả **400
và không gửi gì**, thay vì nổ 500 đúng lúc có cảnh báo cần đi.

---

## 3. Dùng Zalo Bot trên Home Assistant

### Bước 0 — hai thứ phải có trước

1. **Bot token**: tạo bot trên `bot.zapps.me`, rồi
   `Cài đặt → Kênh chat → Zalo Bot → + Thêm bot`. Chưa có bot thì mọi lời gọi
   dưới đây trả lỗi "chưa có chat_id".
2. **`chat_id`**: nhắn cho bot **một lần** từ Zalo của bạn để nó biết bạn là ai.
   Sau đó để trống `chat_id` là tự gửi về admin.

### Chỉ gửi chữ — `rest_command`

```yaml
# configuration.yaml
rest_command:
  zalo_canh_bao:
    url: "http://172.16.10.38:3030/api/zalo-bot/send"
    method: POST
    content_type: "application/x-www-form-urlencoded"
    headers:
      authorization: !secret c2a_admin_token
    payload: "text={{ text }}"
```

```yaml
# automation
- alias: Cảnh báo mất điện
  trigger:
    - platform: state
      entity_id: binary_sensor.nguon_dien
      to: "off"
  action:
    - service: rest_command.zalo_canh_bao
      data:
        text: "⚠️ Mất điện lúc {{ now().strftime('%H:%M %d/%m') }}"
```

### Gửi kèm ảnh camera — `shell_command`

`rest_command` **không gửi được multipart**, nên phần ảnh dùng `shell_command`:

```yaml
# configuration.yaml
shell_command:
  zalo_gui_anh: >
    curl -s -m 30 -X POST http://172.16.10.38:3030/api/zalo-bot/send
    -H "authorization: Bearer {{ token }}"
    -F "text={{ text }}"
    -F "photo=@{{ duong_dan }}"
```

```yaml
# automation — chụp ảnh rồi gửi
- alias: Có người ở cửa
  trigger:
    - platform: state
      entity_id: binary_sensor.cua_truoc
      to: "on"
  action:
    - service: camera.snapshot
      target:
        entity_id: camera.cua_truoc
      data:
        filename: /config/www/cua_truoc.jpg
    # Chờ tệp ghi xong — thiếu bước này là gửi ảnh của lần trước.
    - delay: "00:00:02"
    - service: shell_command.zalo_gui_anh
      data:
        token: !secret c2a_admin_token
        text: "🚪 Có người ở cửa {{ now().strftime('%H:%M') }}"
        duong_dan: /config/www/cua_truoc.jpg
```

### Nhiều ảnh

Bot API không có album, nên phải gọi lặp — và mỗi ảnh sẽ là **một tin riêng**:

```yaml
    - repeat:
        for_each:
          - /config/www/cam1.jpg
          - /config/www/cam2.jpg
        sequence:
          - service: shell_command.zalo_gui_anh
            data:
              token: !secret c2a_admin_token
              text: ""
              duong_dan: "{{ repeat.item }}"
          - delay: "00:00:01"   # đừng bắn dồn
```

Muốn **một tin nhiều ảnh** thì phải dùng Zalo Cá Nhân (mục 1) — không có cách nào
làm điều đó bằng Bot API.

### Webhook hai chiều (muốn HA nhận lệnh từ Zalo)

Bot API **không chạy webhook và long-poll cùng lúc** — tài liệu nói thẳng
`getUpdates` sẽ không hoạt động nếu đã `setWebhook`. Hệ thống chốt điều này ở hai
lớp nên không bao giờ chạy song song:

```bash
# bật webhook (tự dừng polling)
curl -X POST http://172.16.10.38:3030/api/zalo-bot/webhook-config \
  -H "authorization: Bearer <token admin>" \
  -H "content-type: application/json" -d '{"enabled":true}'

# tắt (tự deleteWebhook rồi poll lại)
... -d '{"enabled":false}'

# xem trạng thái + phát hiện webhook trỏ URL cũ
curl http://172.16.10.38:3030/api/zalo-bot/status -H "authorization: Bearer <token admin>"
```

Webhook cần **HTTPS** và domain công khai. Đổi domain/`base_url` mà không áp lại
thì webhook trên Zalo vẫn trỏ URL cũ — dùng `POST /api/zalo-bot/apply-mode`, hoặc
xem `expected_webhook_url` trong `/status` để biết đang lệch.

---

## 4. Sự cố hay gặp

| Hiện tượng | Nguyên nhân thật |
|---|---|
| Gửi ảnh qua Bot: **không lỗi mà ảnh không tới** | `photo` là URL trong LAN. Zalo tải không được và **không báo gì**. Phải là URL công khai — dùng `/api/zalo-bot/send` để server tự lo |
| `Exceed maximum file of N` (Cá Nhân) | Vượt `max_file` của phiên. Đã chia lô tự động; nếu tự gọi `sendMessage` thì phải tự chia |
| `Vượt quá số request cho phép, code 221` | Gửi dồn quá nhanh. Nghỉ 1–24 giờ; không ai biết ngưỡng chính xác |
| Ảnh gửi ra thành **tệp đính kèm** | Định dạng ngoài jpg/jpeg/png/webp |
| Album bị vỡ thành nhiều tin rời | Có GIF lẫn trong danh sách |
| Bot trả "chưa có chat_id" | Chưa thêm bot token, hoặc chưa ai nhắn cho bot lần nào |
| Zalo Cá Nhân mất phiên sau mỗi lần deploy | Đã vá: bản cũ **xoá cookie khi lỗi mạng lúc khởi động**. Nay thử lại 3 lần và chỉ xoá khi Zalo từ chối thật |
| Ảnh gửi là ảnh của **lần trước** | `camera.snapshot` chưa ghi xong. Thêm `delay` 1–2 giây |
