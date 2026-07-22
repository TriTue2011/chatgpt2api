---
name: Bài học đa cấp
description: Dạy 1 ý (tiểu học/THCS/THPT) — giáo án lớp học + CFU + TTS
verify: true
---

## Bước 1: Nhận diện + memory
Từ yêu cầu ({{input}}), ghi:
- Cấp / lớp (1–12) nếu đoán được
- Môn (toan|van|anh)
- Ý kiến thức (1 ý)
- Workspace gợi ý (lopN-mon)
- Mục tiêu "I can…" 1 câu

Nếu có workspace: nhắc gọi **teacher_memory op=get** (agent làm ở runtime).

## Bước 2: Giáo án 6 pha
Dựa trên bước 1:
{{prev}}

Viết giáo án ngắn (như teacher_lesson):
1. Mục tiêu
2. Khởi động (1 câu hỏi)
3. I do → We do (Socratic, chưa full đáp án)
4. You do + gợi ý nếu kẹt (hint level 1–2)
5. CFU 1 câu
6. Kết + TTS 2–4 câu + memory

Style theo cấp:
- Tiểu học: câu rất ngắn, ví dụ đời sống
- THCS: định nghĩa + ví dụ
- THPT: dạng bài + hướng giải

## Bước 3: Đề CFU + bản TTS
Từ giáo án:
{{prev}}

1) In **1 câu kiểm tra hiểu** (exit ticket)
2) In **đoạn TTS 2–4 câu** (không markdown, không ký hiệu toán trần)
3) Nhắc: chấm bằng teacher_grade; ghi teacher_memory khi xong
