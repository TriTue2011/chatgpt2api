---
name: Viết code có kiểm chứng
description: Viết hoặc sửa code thì chạy thử rồi mới báo xong — dẫn chứng bằng kết quả chạy thật, không nói "đã sửa" khi chưa chạy.
group: Chung
---

# Viết code có kiểm chứng

Phỏng theo `tdd` + `verification-before-completion`. Áp cho mọi lần viết/sửa
code, dù là script nhỏ hay sửa file trong dự án.

## Nguyên tắc gốc

**Chạy trước, kết luận sau.** Câu "đã sửa xong" chỉ được nói sau khi đã chạy và
đọc kết quả — không phải sau khi đã gõ xong code. Đây là khác biệt lớn nhất giữa
code dùng được và code trông có vẻ đúng.

## Thứ tự làm

1. **Dựng cách kiểm trước khi sửa.** Một lệnh chạy được, một test, hoặc chí ít
   một câu lệnh in ra kết quả. Chưa có cách kiểm thì chưa biết mình sửa đúng chưa.
2. **Sửa nhỏ nhất có thể** để cách kiểm đó chuyển từ đỏ sang xanh.
3. **Chạy lại.** Đọc output thật, đừng đoán output.
4. **Kiểm cả ca biên**: dữ liệu rỗng, số 0, chuỗi tiếng Việt có dấu, file không
   tồn tại, mạng hỏng giữa chừng.

## Với sửa lỗi

Trước khi sửa, phải **dựng lại được lỗi**. Không dựng lại được thì chưa biết
nguyên nhân, và "sửa" lúc đó chỉ là đoán. Sau khi sửa, chạy lại đúng cách dựng
lỗi ban đầu để chứng minh nó hết.

## Câu không được nói

- "Chắc là được rồi" — chạy đi rồi nói.
- "Đã sửa xong" khi mới chỉ viết code.
- "Test pass" khi chưa chạy test.

Nếu không chạy được (thiếu môi trường, thiếu quyền, thiếu dữ liệu) thì **nói thẳng
là chưa chạy được và vì sao**, đừng lấp liếm. Người dùng cần biết cái gì đã kiểm
và cái gì chưa.

## Báo kết quả

Nói rõ ba phần: **đã sửa gì**, **đã chạy gì để kiểm**, **kết quả ra sao**. Có số
liệu thì đưa số liệu. Còn phần nào chưa kiểm được thì liệt kê ra.
