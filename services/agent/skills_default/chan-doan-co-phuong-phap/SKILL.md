---
name: Chẩn đoán có phương pháp
description: Lỗi khó, đã thử vài cách vẫn không ra thì dựng tín hiệu đúng/sai trước, rồi mới đoán nguyên nhân — thay vì sửa mò.
group: Hệ thống
---

# Chẩn đoán có phương pháp

Phỏng theo skill `diagnosing-bugs` (mattpocock). Khác `xu-ly-su-co` ở chỗ:
`xu-ly-su-co` là danh sách lỗi ĐÃ BIẾT và cách chữa; skill này dùng khi lỗi
KHÔNG có trong danh sách đó.

## Khi nào dùng
- Đã thử 2–3 cách theo `xu-ly-su-co` mà vẫn hỏng.
- Lỗi lúc có lúc không, hoặc "tự nhiên hỏng" mà không ai đổi gì.
- Chậm bất thường nhưng không biết chậm ở khâu nào.

## Bước 1 — Dựng tín hiệu đúng/sai. ĐÂY MỚI LÀ VIỆC CHÍNH

Trước khi đoán bất cứ điều gì, phải có một cách **bấm phát biết ngay** là còn
hỏng hay đã hết. Có nó thì mọi phép thử sau đều rẻ; không có nó thì nhìn mãi
cũng không ra, và tệ hơn là "sửa xong" mà không biết đã sửa được chưa.

Cách dựng, thử theo thứ tự:
1. Một lệnh chạy lại được lỗi (`curl` đúng endpoint đó, gọi đúng tool đó).
2. Một dòng log xuất hiện đúng lúc hỏng — `docker logs c2a --since 5m | grep …`.
3. Một con số đo được: số fd đang mở, RAM còn trống, mã HTTP trả về.

Bỏ công vào bước này nhiều hơn bạn nghĩ là đáng. Chưa có tín hiệu thì ĐỪNG sửa.

## Bước 2 — Thu nhỏ phạm vi

Bỏ bớt từng phần cho tới khi lỗi biến mất. Hỏng ở container hay ở host? Ở tool
hay ở model? Ở mạng hay ở cấu hình? Mỗi lần bỏ một thứ, hỏi lại tín hiệu ở
bước 1.

## Bước 3 — Đoán, rồi ĐO để bác bỏ

Nêu giả thuyết dạng "nếu X là nguyên nhân thì phải thấy Y". Rồi đi đo Y. Đo để
BÁC BỎ giả thuyết chứ không phải để tìm cái xác nhận điều mình đã tin.

## Bước 4 — Sửa, rồi kiểm bằng đúng tín hiệu ở bước 1

Sửa xong phải thấy tín hiệu chuyển từ đỏ sang xanh. Không kiểm lại thì chưa
được coi là xong.

## Cạm bẫy hay gặp trong hệ thống này

Triệu chứng thường KHÔNG nằm cùng chỗ với nguyên nhân:
- "Không phân giải được tên miền" mà DNS máy vẫn tốt → thường là **hết file
  descriptor** hoặc **hết RAM** nên curl không tạo nổi socket/luồng.
- "Model trả lời sai/rỗng" → kiểm tra model id có thật không (`/v1/models`),
  đừng đoán là model kém.
- "Chạy nhanh bất thường rồi ra kết quả lỗi" → gần như chắc chắn là **đọc từ
  cache**, không phải gọi thật.
- "Nạp xong mà nội dung thiếu" → kiểm tra có khối/trang nào bị bỏ qua im lặng.
