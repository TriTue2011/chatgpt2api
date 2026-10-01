# chi-tieu-mcp — bot chi tiêu 6 hũ cho C2A

MCP server quản lý chi tiêu cá nhân theo mô hình **6 Hũ (JARS)**, viết để gắn vào
[C2A (chatgpt2api)](https://github.com/TriTue2011/chatgpt2api). Người dùng nhắn Zalo
kiểu "vừa chi 50k ăn trưa" → AI của C2A gọi tool ghi sổ và trả lời ngay số còn lại.
Bot tự cảnh báo khi hũ sắp cạn, và có trang web `/ui` để xem, sửa, thêm tay.

## Tính năng

- Ghi chi vào 6 hũ. Hũ chi vượt được **tự bù** từ phần dư của hũ khác theo thứ tự ưu
  tiên; khoản chi làm vượt **tổng** ngân sách tháng bị giữ lại cho tới khi người dùng
  xác nhận.
- Chu kỳ lương tuỳ chỉnh (ngày bắt đầu kỳ 1–28). Thu nhập ngoài lương làm tăng hạn mức
  mọi hũ theo tỷ lệ. Chi phí đặc biệt biết trước (học phí…) co hẹp hũ Dự Phòng rồi
  Hưởng Thụ, chỉ trong đúng tháng đó.
- Tách 1 khoản đã ghi gộp thành nhiều dòng đúng hũ.
- Sổ tạm ứng công ty tách biệt khỏi tiền cá nhân; giải chi xuất PDF.
- Cảnh báo chủ động qua **Zalo Cá Nhân** của C2A khi 1 hũ đạt 65/80/100% và khi tổng
  ngân sách tháng sắp cạn hoặc đã vượt (mỗi mốc gửi 1 lần mỗi kỳ).
- Đề xuất % phân bổ theo xu hướng chi 3 tháng; nút "Hỏi AI phân tích" trên `/ui`
  (gọi AI của C2A).
- Trang `/ui` cho điện thoại: 4 tab Tổng quan · Lịch sử · Phân bổ · Công ty, nút +
  thêm nhanh, giao diện sáng/tối.

## 11 tool MCP

| Tool | Việc |
|---|---|
| `ghi_chi_tieu` | Ghi 1 khoản chi vào 1 hũ; trả hạn mức/còn lại, tổng còn lại, số ngày tới kỳ lương |
| `tach_giao_dich` | Tách 1 khoản đã ghi thành nhiều dòng đúng hũ |
| `xem_ngan_sach` | Tổng quan ngân sách kỳ hiện tại của từng hũ |
| `xem_lich_su` | Các khoản chi cá nhân trong 1 tháng, kèm id |
| `de_xuat_dieu_chinh` | Phân tích chi tiêu, đề xuất hũ nên giảm + % phân bổ gợi ý |
| `ghi_thu_nhap_them` | Ghi thu nhập ngoài lương của tháng |
| `khai_bao_chi_phi_dac_biet` | Khai báo khoản chi lớn biết trước, chỉ trong tháng này |
| `ghi_tam_ung_cong_ty` | Ghi tiền công ty tạm ứng |
| `ghi_chi_cong_ty` | Ghi khoản chi công việc cần công ty hoàn |
| `xem_so_du_cong_ty` | Số dư tạm ứng kỳ hiện tại + từng giao dịch |
| `giai_chi_cong_ty` | Đóng kỳ tạm ứng, xuất PDF |

Docstring của tool viết cho model, không chỉ cho người: luôn gọi tool để lấy số mới
(không trả lời bằng số nhớ được), mỗi tin báo chi là 1 khoản mới, hỏi lại khi khoản chi
mô tả chung chung, không tự xác nhận chi vượt tổng thay người dùng. Đọc `app/main.py`
trước khi sửa.

## Cài bằng Docker

```bash
git clone https://github.com/Quiz99/chi-tieu-mcp.git && cd chi-tieu-mcp
cp .env.example .env    # điền C2A_BASE_URL, C2A_AUTH_KEY, C2A_ZALO_PERSONAL_THREAD_ID, SELF_BASE_URL
docker compose up -d --build
docker logs chi-tieu-bot --tail 20    # có dòng "chi-tieu-bot MCP server sẵn sàng tại /mcp"
```

Lần chạy đầu tự tạo `data/jars_config.json` từ `app/jars_config.example.json`: 6 hũ
55/5/10/10/10/10, lương ví dụ 10.000.000đ, kỳ bắt đầu ngày 1. Sửa lương, tỷ lệ, ngày
bắt đầu kỳ trên `/ui` → tab Phân bổ. Mã hũ (`thiet_yeu`, `gia_dinh`, `hoc_tap`,
`du_phong`, `huong_thu`, `tu_do_tai_chinh`) cố định vì code dựa vào chúng; tên và tỷ lệ
đổi tự do.

## Biến môi trường (`.env`)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `C2A_BASE_URL` | `http://127.0.0.1:3030` | URL của C2A. Chạy trong Docker thì phải là IP LAN của máy chạy C2A (127.0.0.1 là chính container bot), hoặc tên service nếu chung network compose |
| `C2A_AUTH_KEY` | (trống) | Admin API key tĩnh của C2A (Cài đặt → Bảo mật). Dùng để gửi cảnh báo, hỏi AI, và là mật khẩu đăng nhập `/ui` |
| `C2A_ZALO_PERSONAL_THREAD_ID` | (trống) | thread_id Zalo Cá Nhân của người nhận cảnh báo |
| `MCP_SERVER_PORT` | `8801` | Cổng HTTP của bot (`/mcp`, `/ui`, `/api`) |
| `SELF_BASE_URL` | `http://localhost:<MCP_SERVER_PORT>` | Gốc URL ghép link PDF giải chi gửi qua chat — đặt IP LAN hoặc tên miền để mở được từ điện thoại |
| `DB_PATH` | `data/chi_tieu.db` | File SQLite |
| `ALERT_CHECK_INTERVAL_SECONDS` | `1800` | Chu kỳ kiểm tra cảnh báo (giây) |

## Đăng ký vào C2A

Cài đặt → MCP Servers → thêm server tuỳ chỉnh, URL `http://<IP-máy-chạy-bot>:8801/mcp`
(streamable HTTP, không cần key). Đặt tên có chữ "Chi tiêu" nếu dùng bản vá model free
trong [docs/c2a-ban-va-model-free/](docs/c2a-ban-va-model-free/README.md) (bản vá nhận
server theo tên). Thử: nhắn bot "vừa chi 50k ăn trưa".

3 điểm nối với C2A, gợi ý preset/compose và các bẫy đã gặp:
[docs/tich-hop-c2a.md](docs/tich-hop-c2a.md).

## Cảnh báo qua Zalo Cá Nhân

C2A có 2 kênh Zalo tách biệt: Bot API chính thức và Zalo Cá Nhân (zca-js). Bot gửi qua
**Zalo Cá Nhân** (`POST /api/zalo-personal/test-send`). Lấy thread_id: nhắn bot 1 tin
qua Zalo Cá Nhân rồi xem `docker logs c2a | grep zalop` — session có dạng
`v1|zalop|<thread_id>||`.

## Bảo mật

- `/mcp` **không có xác thực** (C2A gọi không kèm key) → chỉ mở cổng 8801 trong LAN,
  không đưa ra Internet.
- `/ui` và `/api/*` cần đăng nhập, mật khẩu là `C2A_AUTH_KEY` (cookie `httponly`, giữ
  30 ngày; đổi key là đăng xuất mọi thiết bị).
- Muốn mở `/ui` ra ngoài qua reverse proxy hoặc Cloudflare Tunnel: chỉ cho qua đường dẫn
  `^/(ui|api)(/.*)?$`, chặn `/mcp`.

## Dữ liệu & sao lưu

Tất cả nằm trong `data/` (bind mount): `chi_tieu.db` (SQLite), `jars_config.json` (cấu
hình hũ), `tam_ung_pdf/` (PDF giải chi). Sao lưu = chép thư mục `data/` khi container
đang dừng.

## Chạy test

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

Test PDF cần font DejaVu (`apt install fonts-dejavu-core`). Không cần `.env` hay C2A thật.

## Giấy phép

MIT — xem [LICENSE](LICENSE).
