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

## Tiến độ (cập nhật 30/07/2026)

Khảo sát VBT (`vbt_khao_sat.json`): 70 tài liệu · 626 trang, lớp 1–3 và 5–12
(lớp 4 đã nạp trọn trước đó qua đường server, đã soát).

- Lớp 1: 6/6 ✓ (VBT Toán ×2, VBT Tiếng Việt ×2, Tập viết ×2 — 57 trang)
- Lớp 2: 2/6 (VBT Toán ×2 ✓; còn VBT Tiếng Việt ×2, Tập viết ×2 — đã tải trang)
- Lớp 3, 5–12: chưa bắt đầu
- SGV + tài liệu tập huấn các lớp: chưa khảo sát chi tiết (SGV Toán 4 = 290 trang)
