# Sách TỰ ĐỌC từ taphuan.nxbgd.vn — kho chép tay có kiểm chứng

Người vận hành chốt (30/07/2026): "bạn làm trực tiếp lấy dữ liệu, không dùng sv
của tôi" + "sách cả 12 lớp còn thiếu gì thì làm hết, sử dụng taphuan.nxbgd.vn
làm chuẩn, ghi đè nếu đang có".

Nghĩa là: phần ĐỌC TRANG (vision) không chạy trên server (không đốt quota model
của gateway) — agent đọc ảnh trang bằng mắt của chính nó ở máy ngoài, chép thành
các file `.md` trong thư mục này, rồi nạp lên DB qua `scripts/nap_md_tu_doc.py`.

## Quy ước file

- Tên file = slug tài liệu trên taphuan (có ID số): `vbt-toan-1-tap-1-bai-mau.md`.
- Mỗi trang mở đầu bằng `<<<TRANG n>>>` — n là THỨ TỰ ẢNH (bìa = 1); nếu trang
  có số in thì ghi kèm `(số in: k)`, thường k = n − 1. Khớp quy ước sẵn có của
  `sgk_taphuan.book_markdown` để `soat.py` đối chiếu được.
- Bài tập có tranh: chép nguyên phần chữ, TẢ NGẮN nội dung tranh và ghi đáp án
  suy được từ tranh — kho RAG là chữ, giữ được DẠNG ra đề là mục tiêu chính
  (nguồn cho `teacher_bai_tap` sinh bài 3 mức).

## Nạp lên server

```bash
python3 - <<'EOF' > /tmp/payload.json
import json, pathlib
md = pathlib.Path("docs/sgk/tu_doc/vbt/<slug>.md").read_text("utf-8")
meta = {...}   # grade/subject/kind/volume/label/source/page_urls — xem vbt_khao_sat.json
print(json.dumps({**meta, "md": md}, ensure_ascii=False))
EOF
ssh root@172.16.10.38 "docker exec -i c2a sh -c '/app/.venv/bin/python /tmp/nap_md.py'" < /tmp/payload.json
```

`nap_md` (bản trong container = `scripts/nap_md_tu_doc.py`) GHI ĐÈ theo slug tài
liệu: xoá mọi đoạn cũ mà `source` chứa slug (kể cả bản nạp bằng đường khác) rồi
nạp bản mới — chạy lại bao nhiêu lần cũng ra đúng một bản.

## Tiến độ (cập nhật 31/07/2026)

Khảo sát VBT (`vbt_khao_sat.json`): 70 tài liệu · 626 trang, lớp 1–3 và 5–12
(lớp 4 đã nạp trọn trước đó qua đường server, đã soát).

- Lớp 1: 6/6 ✓ (VBT Toán ×2, VBT Tiếng Việt ×2, Tập viết ×2 — 57 trang)
- Lớp 2: 6/6 ✓ (VBT Toán ×2, VBT Tiếng Việt ×2, Tập viết ×2 — 56 trang).
  Nạp 31/07: 30 đoạn, trong đó VBT Tiếng Việt 2 tập một ghi đè 7 đoạn cũ.
- Lớp 3: 6/6 ✓ (VBT Toán ×2, VBT Tiếng Việt ×2, Tập viết ×2 — 52 trang).
  Nạp 31/07: 47 đoạn.
- Lớp 5–12: chưa bắt đầu (còn 43 tài liệu · 461 trang)

Kho `kb_giao_duc_vbt` sau lượt nạp 31/07: 234 đoạn — lớp 1: 45, lớp 2: 48,
lớp 3: 47, lớp 4: 94.

### Kí hiệu Tập viết KHÁC NHAU giữa các lớp — đừng suy từ lớp này sang lớp kia

- Tập viết **2**: ● Tập viết ở lớp · ★ Tập viết chữ nghiêng (tự chọn) ·
  ■ Luyện viết thêm (tự chọn)
- Tập viết **3**: ● Tập viết ở lớp · ■ Tập viết chữ **đứng** (tự chọn) ·
  ★ Tập viết chữ **nghiêng** (tự chọn)

Cùng dấu ■ mà nghĩa khác nhau. Phải đọc trang "Kí hiệu dùng trong vở" của CHÍNH
quyển đang chép.

### Đường nạp: đừng dùng `echo` để đưa JSON vào container

Đo thật 31/07: `echo "$json" | ssh …` làm zsh biến `\n` trong chuỗi JSON thành
dòng mới THẬT ⇒ `json.decoder.JSONDecodeError: Invalid control character`. Ghi
payload ra file rồi `… < file.json`.

Ngoài ra `docker cp` trên máy chủ đang lỗi (`openat etc/localtime: path escapes
from parent`, Docker 29.5.1) — dùng `docker exec -i c2a sh -c 'cat > …'`.
- SGV + tài liệu tập huấn các lớp: chưa khảo sát chi tiết (SGV Toán 4 = 290 trang)

### BẪY SLUG — đọc trước khi nạp lớp 2

Tập viết **lớp 2** tập một có `doc_slug` là **`tap-viet-1-tap-mot.4727277435`** —
chữ "1" trong slug là SAI của taphuan, chỉ ID số phân biệt được nó với Tập viết
lớp 1 tập một (`tap-viet-1-tap-mot.4727066112`). Vì vậy:

- Tên file trong kho này đặt là `tap-viet-2-tap-mot.md` (không theo slug) để
  không đè lên `tap-viet-1-tap-mot.md` của lớp 1.
- Khi nạp phải truyền `source` = `reader_url` đầy đủ (có ID). So khớp bằng phần
  chữ của slug sẽ xoá mất tài liệu lớp 1.
- Đếm tiến độ bằng cách so tên file với slug rút gọn sẽ báo SAI (từng đếm lớp 2
  là 3/6 trong khi thực tế là 2/6).
