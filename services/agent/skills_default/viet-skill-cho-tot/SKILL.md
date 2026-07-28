---
name: Viết skill cho tốt
description: Nguyên tắc viết skill mới đúng chuẩn — dùng khi được nhờ ghi lại một quy trình, hoặc khi tự thấy nên lưu cách làm thành skill.
group: Chung
---

# Viết skill cho tốt

Phỏng theo `writing-great-skills` (mattpocock). Dùng cùng capability
**"Học cách làm một việc (kỹ năng)"**.

Skill tồn tại để **ép một hệ thống ngẫu nhiên làm việc có quy trình ổn định**.
Ổn định ở đây là *cùng một cách làm* mỗi lần, không phải *cùng một câu trả lời*.

## Trước khi viết: có đáng thành skill không?

Đáng, khi việc đó **lặp lại** và **dễ làm sai theo cùng một kiểu**. Không đáng, khi
chỉ làm một lần, hoặc khi việc đó đã nằm trong capability sẵn có — viết skill mô tả
lại thứ tool đã tự làm chỉ tổ tốn chỗ.

## Cái giá phải trả: mỗi skill chiếm chỗ MỌI lượt chat

Phần `description` của mọi skill đang bật đều nằm trong context ở **mỗi lượt**
người dùng nhắn. Thêm một skill là làm loãng khả năng chọn đúng skill của những cái
còn lại. Nên thà có 10 skill sắc còn hơn 30 skill mờ.

Hệ quả thực tế: skill nào chỉ dùng khi người dùng gọi đích danh thì **không cần
description giàu từ khoá** — viết ngắn gọn một dòng.

## Viết description

Đây là chỗ quyết định skill có được gọi đúng lúc hay không.

- **Chữ đầu tiên phải là chữ đắt nhất.** Nói ngay skill làm gì.
- **Mỗi tình huống kích hoạt viết MỘT lần.** "dạy lớp 4 … hướng dẫn học sinh tiểu
  học" là một tình huống viết hai lần — bỏ bớt.
- **Đừng lặp lại thân bài.** Description chỉ để *chọn*, không phải để *hướng dẫn*.
- **Trần 150 ký tự.** Dài hơn sẽ bị cắt, và câu bị cắt thường mất đúng phần quan
  trọng nhất.
- **Đừng mở đầu bằng sáo ngữ** ("Skill này giúp bạn…") — vừa tốn chỗ vừa bị chặn.

## Viết thân bài

Xếp theo thứ tự người đọc cần: **khi nào dùng** → **khi nào KHÔNG dùng** → **các
bước** → **cạm bẫy**.

- **"Khi nào KHÔNG dùng" quan trọng ngang "khi nào dùng".** Thiếu nó, skill sẽ nhảy
  vào cả những việc nó làm hỏng.
- **Câu lệnh, đừng kể chuyện.** "Hỏi mỗi lượt một câu" tốt hơn "nên cân nhắc việc
  hỏi từng câu một".
- **Nêu lý do cho những chỗ phản trực giác.** Chỗ nào người đọc dễ nghĩ "làm ngược
  lại cũng được" thì phải nói vì sao không.
- **Gọi đúng tên tool của bot** (`control_home`, `search_sgk`, `teacher_grade`,
  `create_automation`…). Skill chép từ nguồn ngoài hay ghi tên tool của công cụ
  khác — sửa hết trước khi lưu.
- **Ví dụ thật, ngắn.** Một ví dụ đúng bối cảnh hơn ba đoạn giải thích.

## Sau khi viết

Đọc lại và cắt. Câu nào bỏ đi mà skill vẫn chạy đúng thì bỏ. Skill dài không làm
bot giỏi hơn, chỉ làm nó đọc lâu hơn.
