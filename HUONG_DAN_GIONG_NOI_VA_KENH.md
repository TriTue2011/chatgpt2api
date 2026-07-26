# Hướng dẫn: Giọng nói (TTS/STT) + Cài đặt kênh Telegram / Zalo

> Tài liệu thực dụng cho người mới: tải model giọng, bật STT tiếng Anh, và cài
> từng kênh chat từ đầu đến cuối. Phần phân quyền chuyên sâu xem thêm
> [HUONG_DAN.md](HUONG_DAN.md) mục 6.

---

## 1. Giọng nói — model nằm NGOÀI image

Nguyên tắc: **code trong image, model trên volume `data/`** — image không phình,
model tải một lần là giữ qua mọi lần update container.

| Model | Dùng cho | Thư mục | Script tải |
|---|---|---|---|
| **VieNeu-TTS v3 Turbo** | Giọng đọc chính (48 kHz, đọc được câu trộn Anh–Việt) | `data/hf` | `download_vieneu_model.py` |
| Piper | Giọng đọc nhẹ, nhanh | `data/piper` | `download_piper_voices.py` |
| Kokoro | Giọng đọc thay thế | `data/kokoro` | `download_kokoro_model.py` |
| **Zipformer tiếng Việt** | STT — nghe tin nhắn thoại tiếng Việt | `data/stt` | `download_stt_model.py` |
| **Parakeet-TDT 0.6B v2** | STT — nghe **tiếng Anh** (CPU, nhanh hơn Whisper) | `data/stt-en` | `download_stt_en_model.py` |

### 1.1. Tải model trên server (Docker)

```bash
# SSH vào server rồi chạy TRONG container c2a.
# DÙNG /app/.venv/bin/python (python hệ thống thiếu thư viện):
docker exec c2a /app/.venv/bin/python /app/scripts/download_stt_model.py --hf   # STT tiếng Việt
docker exec c2a /app/.venv/bin/python /app/scripts/download_stt_en_model.py     # STT tiếng Anh
docker exec c2a /app/.venv/bin/python /app/scripts/download_vieneu_model.py     # TTS VieNeu (tự chọn int8/fp32 theo CPU)
```

Ghi chú:
- Model nằm trên volume `data/` nên **không mất** khi container recreate — tải
  một lần là xong.
- Piper/STT-vi tải từ GitHub Release của repo — repo private thì cần
  `GH_TOKEN`; dùng `--hf` (STT-vi) để tải thẳng HuggingFace không cần token.
- Kiểm tra đã đủ chưa:
  `docker exec c2a /app/.venv/bin/python /app/scripts/download_stt_en_model.py --check`
  và `…/download_vieneu_model.py --check`.
- Lỗi `import sherpa_onnx … VERS_1.27.0 not found` = onnxruntime lệch ABI —
  image mới đã ghim `onnxruntime<1.28` trong `deploy/extra-requirements.txt`;
  gặp trên image cũ thì update image.

> **Server 172.16.10.38 (2026-07-26): đã tải đủ VieNeu (14 giọng) + STT tiếng
> Việt + STT tiếng Anh, và đã bật sẵn `en_enabled` — chỉ cần tick 🎙️ theo phạm
> vi là dùng được ngay.**

### 1.2. Bật STT tiếng Anh (mặc định TẮT)

Model tải xong **chưa đủ** — phải bật cờ trong config (`data/config.json`, khối
`voice`):

```json
"voice": {
  "stt": {
    "backend": "auto",
    "language": "vi",
    "en_enabled": true
  }
}
```

- `en_enabled: true` — cho phép dùng Parakeet English. Không bật → mọi yêu cầu
  `en` tự rơi về tiếng Việt.
- `language`: `vi` (mặc định) · `en` (ép tiếng Anh toàn hệ thống) · `auto`
  (dual VI+EN — cần đủ cả 2 model).
- **Cách dùng đúng**: để `language: vi` toàn hệ thống, rồi bật 🎙️ **STT tiếng
  Anh** theo TỪNG phạm vi trong UI (mục 1.3) — ai hay gửi voice tiếng Anh thì
  bật riêng người đó.

### 1.3. Cài giọng đọc / tắt TTS / STT-EN theo phạm vi (UI)

`Cài đặt → Kênh chat → [kênh] → 🎚️ Lọc thread` — dưới mỗi **thread**, mỗi
**🧵 Topic** (nhóm Telegram bật Topics) và mỗi **👤 User** có khối giọng riêng:

- **🔊 Giọng đọc** — chỉ hiện khi phạm vi đó tick quyền `🔉 Trả lời bằng giọng
  nói`. Trống = đọc theo persona; chọn giọng = ép giọng đó.
- **🔇 Tắt giọng nói (TTS)** — chặn đọc thành tiếng cho phạm vi này.
- **🎙️ STT tiếng Anh** — tick = voice note của phạm vi này nghe bằng model
  tiếng Anh (cần mục 1.2 bật `en_enabled` + đã tải model `data/stt-en`).

Thứ tự thắng (hẹp → rộng): **User trong topic → User cả nhóm → Topic → Nhóm →
Bot → Kênh**.

---

## 2. Telegram — cài từ đầu

### 2.1. Tạo bot + nối vào hệ thống

1. Chat với **@BotFather** → `/newbot` → lấy **token** (`123456:ABC…`).
2. `Cài đặt → Kênh chat → Telegram` → **+ Thêm bot** → dán token, đặt tên gợi
   nhớ (label). Thêm được **nhiều bot**.
3. Webhook (nhận tin): cấu hình **một lần** ở card **Cloudflare (hạ tầng
   chung)**: điền `Public base URL` (domain HTTPS — Cloudflare Tunnel) — hệ
   thống tự đăng ký `/telegram/webhook` cho **mọi** bot, phân biệt bằng secret.
   Không có domain → bot tự **long-polling**, không cần cài gì thêm.

### 2.2. Admin — nơi nhận thông báo

Mỗi bot có danh sách **Admin** (Chat ID). Admin = **chỉ nhận thông báo** (log
tài khoản, cảnh báo, người lạ nhắn…) với các công tắc bật/tắt loại tin.
**Muốn admin chat được với AI** → thêm Chat ID admin thành một dòng trong
**Lọc thread** như người thường (tick đủ nhóm chức năng).

### 2.3. Lọc thread — trái tim phân quyền (3 cấp)

Lấy ID: gõ `/id` trong chat/nhóm — bot trả Chat ID + User ID + **🧵 Topic ID**
(nếu gõ trong topic).

- **Cấp Nhóm**: chọn bot → nhập Chat ID → Nhận diện → tick nhóm chức năng
  (🏠 Nhà · 🎨 Ảnh · ⏰ Nhắc hẹn · 🔉 Trả lời giọng nói…). Chat **không có**
  trong danh sách = cho phép tất cả; có = chỉ được mục đã tick; tick rỗng =
  chỉ chat.
- **Cấp 🧵 Topic** (nhóm bật Topics): "+ Thêm topic" → nhập Topic ID → tick
  **tập con** quyền của nhóm. Mỗi topic có riêng: 🤖 model, ⚡ đường tắt nhà,
  🏷️ bắt tag, 🔗 webhook (mỗi topic một loại log), 🎭 persona, 🔊 giọng nói.
  Nhóm không có topic → bỏ qua mục này, vẫn 2 cấp như cũ.
- **Cấp 👤 User**: trong nhóm hoặc trong topic — "+ Thêm user" → giới hạn
  riêng từng người (tập con của cấp trên). **Không thêm user nào = ai nhắn
  cũng được** với full quyền của cấp trên.

Mỗi thread còn cài được: 🤖 **Model AI riêng** · ⚡ **Đường tắt điều khiển
nhà** · 🏷️ **Bắt buộc tag** (@bot mới trả lời) · 🔗 **Webhook chuyển tiếp**
(HA/n8n — bật là ChatGPT im lặng, trừ chế độ "chỉ chuyển khi tag") ·
🎭 **Persona** · 🔊 **Giọng nói** (mục 1.3).

### 2.4. Nhóm bật Topics — lưu ý nhanh

- Bot trả lời **đúng topic** đã nhận tin (chữ + ảnh + file + voice).
- `/id` gõ **trong topic** mới có Topic ID; topic "General" không có ID (tính
  như nhóm thường).
- Tên topic phải gõ tay (Bot API không trả tên topic).
- Bảng quyền chi tiết: [HUONG_DAN.md](HUONG_DAN.md) mục 6.3b.

---

## 3. Zalo Bot (OA) — cài từ đầu

1. Lấy **token** bot Zalo → `Cài đặt → Kênh chat → Zalo Bot` → **+ Thêm bot**.
2. Nhận tin bằng **long-polling** (mặc định, không cần domain). Nền tảng Zalo
   Bot **không chạy webhook và polling cùng lúc** — hệ thống tự `deleteWebhook`
   trước khi poll.
3. Trong **nhóm**, nền tảng chỉ đẩy tin khi người dùng **@tag bot** → mọi tin
   nhóm tới bot đều coi là đã tag (bộ lọc tag tự hiểu điều này).
4. Admin + Lọc thread: **giống hệt Telegram** (2 cấp Nhóm → User; Zalo không có
   khái niệm topic). Khóa thread: `zalo:<bot_id>:<chat_id>`.
5. Muốn đẩy tin nhóm sang HA/n8n: bật 🔗 webhook chuyển tiếp trong Lọc thread
   (nhận bằng polling, chuyển tiếp bằng webhook — chạy đồng thời được).

---

## 4. Zalo Cá Nhân — cài từ đầu

1. `Cài đặt → Kênh chat → Zalo Cá Nhân → 🔑 Tài khoản & QR` → **Đăng nhập QR**
   bằng app Zalo trên điện thoại. Thêm được **nhiều tài khoản**.
2. Mỗi tài khoản có khối **Webhook**: URL nội bộ theo từng loại event (tin
   nhắn, nhóm…) + secret; có domain thì hiện thêm URL public. Tự đăng ký = ô
   chỉ-đọc kèm nút copy; tự điền = sửa tay.
3. **Event & Blacklist**: xem hoạt động gần đây, chặn người/nhóm.
4. Lọc thread: khóa `zalop:<ownId>:<thread_id>` — 2 cấp như Zalo Bot. Bắt tag
   trong nhóm: bấm `@` chọn bot trong danh sách nhóm (khớp theo UID tài khoản —
   mỗi người lưu tên bot khác nhau vẫn nhận đúng).
5. Gửi/nhận hoạt động cả khi web UI đóng — zca-js chạy nền trong container.

---

## 5. Email & Lịch báo về kênh chat (liên quan)

`Cài đặt → Email · Lịch`: thêm **nhiều hộp mail** (IMAP + **App Password** —
Gmail lấy tại <https://myaccount.google.com/apppasswords>, KHÔNG dùng mật khẩu
đăng nhập) và **nhiều lịch** (link ICS bí mật). Mỗi nguồn chọn **kênh nhận**
(các thread đã đặt trong Lọc thread — chọn nhiều, gửi được vào đúng topic),
kiểu gửi: **cứ có mới là gửi** và/hoặc **mốc giờ định kỳ** (`07:00, 18:30`).
Email tóm tắt **cả tệp đính kèm** (PDF/Word/Excel). Nút **Test IMAP** /
**Kiểm tra lịch** báo lỗi bằng tiếng Việt kèm cách sửa.

Lịch còn có **⏰ Mốc nhắc trước sự kiện** (`7d, 1d, 2h, 30m` — d=ngày, h=giờ,
m=phút): mỗi sự kiện được nhắc một lần ở TỪNG mốc vào các kênh đã chọn; sự kiện
phát hiện muộn chỉ nhắc mốc sát nhất (không dội nhiều tin một lúc).

**Yêu cầu TỪ Home Assistant dùng tool** (vẽ ảnh qua Assist/loa…): card
`Cài đặt → Home Assistant` → khối **«Giới hạn chức năng cho yêu cầu TỪ HA»**.
Không bật = mở hết như cũ; bật + tick 🎨 Ảnh → nói "vẽ con mèo" với Assist là
tạo ảnh; bỏ tick → chỉ trả lời chữ. Cùng card có nút **Test kết nối** và
**Làm mới thiết bị ngay**.

---

## 6. Sự cố thường gặp

| Triệu chứng | Nguyên nhân → cách sửa |
|---|---|
| Bot không đọc voice note | Chưa tải model STT (mục 1.1) — kiểm tra `data/stt` có `encoder*.onnx` |
| Voice tiếng Anh nghe ra tiếng Việt sai | Chưa bật `en_enabled` (1.2) hoặc chưa tick 🎙️ STT tiếng Anh cho phạm vi đó (1.3) |
| Bot không gửi giọng nói dù đã tick 🔉 | Chưa tải model TTS (VieNeu — 1.1); hoặc phạm vi đang bật 🔇 Tắt TTS |
| Email báo `Application-specific password required` | Dùng nhầm mật khẩu đăng nhập → tạo App Password (mục 5) |
| Trả lời rơi vào topic General | Bản cũ — update image; bản mới trả lời đúng topic |
| Nhóm Zalo Bot im lặng | Chưa @tag bot (nền tảng chỉ đẩy tin khi tag) |
