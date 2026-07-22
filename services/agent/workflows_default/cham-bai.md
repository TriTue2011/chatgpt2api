---
name: Chấm bài và sửa lỗi
description: Chấm bài HS như GV trên lớp — điểm, khen, lỗi, scaffold, luyện
verify: true
---

## Bước 1: Tách bài
Từ ({{input}}), xác định:
- Đề / yêu cầu
- Bài làm học sinh
- Lớp–môn / workspace nếu có

Nếu thiếu bài làm, ghi rõ còn thiếu gì (không chấm khống).

## Bước 2: Chấm (formative)
Dùng dữ liệu:
{{prev}}

Cho từng ý/câu:
- Điểm gợi ý 0–10
- Đúng / sai / thiếu
- **Lỗi / misconception** cụ thể (không mắng)
- **Lời khen** ngắn (growth mindset)
- Gợi ý: runtime nên gọi **teacher_grade** khi có số liệu rõ

## Bước 3: Sửa · scaffold · luyện · memory
{{prev}}

Viết:
1) Bản sửa gợi ý (Socratic: chưa full đáp án nếu đang dạy)
2) Nếu còn kẹt: gợi ý level 1–2 (tương đương teacher_hint)
3) 1–2 bài luyện tương tự (dễ hơn nếu điểm < 5)
4) 2–4 câu TTS động viên + việc cần ôn
5) Nhắc **teacher_memory** weak/strong theo workspace
