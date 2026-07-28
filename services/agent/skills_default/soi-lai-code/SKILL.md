---
name: Soi lại code trước khi giao
description: Đọc lại code vừa viết để tìm lỗi đúng/sai, ca biên và rò tài nguyên — soi theo danh sách cố định, không đọc lướt.
group: Chung
---

# Soi lại code trước khi giao

Phỏng theo `code-review`. Dùng ngay sau khi viết xong, trước khi báo với người
dùng — và khi được nhờ xem code của người khác.

## Soi theo thứ tự này, đừng đọc lướt

**1. Đúng/sai trước tiên.** Code có làm đúng thứ được yêu cầu không? Đọc lại yêu
cầu gốc rồi đối chiếu, đừng chỉ xem code có chạy.

**2. Ca biên.** Với mỗi hàm, hỏi: đầu vào rỗng thì sao? Số 0, số âm? Danh sách một
phần tử? Chuỗi tiếng Việt có dấu? File không tồn tại? Mạng đứt giữa chừng?

**3. Biến chưa gán trên nhánh rẽ.** Biến gán trong `if` mà dùng ở ngoài là lỗi chỉ
lộ khi đi vào đúng nhánh còn lại — loại lỗi nằm im rất lâu rồi mới nổ.

**4. Vòng lặp có thoát được không.** Mọi `while` phải có đường tiến chắc chắn.
Nhánh `continue` trong `while` mà quên tăng biến đếm là lặp vô hạn.

**5. Tài nguyên có đóng không.** File, socket, kết nối, tiến trình con — mở thì
phải đóng, kể cả khi có lỗi. Dùng `with`/`try-finally`, đừng tin vào dọn rác tự
động.

**6. Lỗi bị nuốt.** `except: pass` giấu mất lỗi thật. Bắt lỗi thì phải hoặc xử lý
được, hoặc ghi log, hoặc ném lại — không im lặng bỏ qua.

**7. Kết quả sai bị nhận là kết quả đúng.** Hàm trả về thông báo lỗi dưới dạng nội
dung, hoặc trả rỗng khi thất bại mà bên gọi tưởng là thành công. Loại này nguy
hiểm nhất vì mọi thứ trông vẫn chạy.

## Phân loại phát hiện

Chỉ nêu thứ đáng sửa, kèm lý do cụ thể:

- **Chặn giao** — sai kết quả, mất dữ liệu, lộ thông tin, treo.
- **Nên sửa** — ca biên chưa xử lý, lỗi bị nuốt, rò tài nguyên.
- **Gợi ý** — đặt tên, trùng lặp, cách viết gọn hơn.

Đừng nêu chuyện thẩm mỹ khi có lỗi đúng/sai chưa xử lý. Và đừng bịa vấn đề cho
đủ danh sách — không thấy gì thì nói không thấy gì.

## Tự soi code mình vừa viết

Khó hơn soi code người khác, vì mình nhớ ý định thay vì đọc cái đã viết. Cách
chữa: đọc từng dòng và tự hỏi *"dòng này làm gì nếu đầu vào không như tôi nghĩ"*,
thay vì đọc lướt để xác nhận điều mình đã tin.
