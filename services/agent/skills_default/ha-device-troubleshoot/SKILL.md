---
name: HA device troubleshoot
description: Thiết bị hỏng, mất kết nối, đơ hay bình thường; xử lý cảnh báo thiết bị và lời chủ nhà «không phải lỗi».
group: Nhà
---

# Thiết bị: lỗi, đơ hay bình thường

## Khi nào dùng
- "camera không hoạt động", "đèn không bật", "cảm biến mất kết nối", "thiết bị unavailable"
- Chủ nhà trả lời tin cảnh báo thiết bị ("tôi không tắt chứ không phải đơ", "cái đó bình thường")

## Hiểu trạng thái (tài liệu Home Assistant, zigbee2mqtt)
- `unavailable` = HA KHÔNG liên lạc được thiết bị/dịch vụ (mất kết nối, tích hợp hỏng).
  Nhưng tivi tắt nguồn, app điện thoại không mở cũng `unavailable` — xem nó có HAY như vậy không.
- `unknown` = có kết nối nhưng CHƯA có giá trị (vừa khởi động). Không phải mất kết nối.
- Thiết bị điều khiển bằng hồng ngoại / Wake-on-LAN đúng ra hiện `off` khi chờ, không `unavailable`.
- Công tắc, đèn, nút bấm, trạng thái bật/tắt đứng yên = không ai bấm → BÌNH THƯỜNG.
- Số đo tức thời (nhiệt độ, độ ẩm, lux, công suất) đứng yên cả ngày mà vẫn gửi tin → ĐƠ.
- Bộ đếm cộng dồn (điện năng, nước — chỉ tăng) đứng yên = máy không chạy → bình thường.
- Zigbee: thiết bị cắm điện báo về ít nhất 10 phút/lần, thiết bị pin có khi 25 giờ mới báo.
- Nhiều thiết bị cùng một tích hợp mất kết nối CÙNG LÚC → thường là tích hợp/cloud hỏng
  (vd sau khi HA khởi động lại), không phải từng thiết bị hỏng.

## Các bước
1. **home_status** với query = tên thiết bị/phòng user nêu; hoặc **canh_bao_nha** viec='xem'.
2. Phân loại theo phần trên, nói rõ vì sao (trạng thái nào, từ bao giờ).
3. Trả lời: nguyên nhân khả dĩ + bước user kiểm tra (nguồn, Wi-Fi, pin, tải lại tích hợp).
4. Chủ nhà nói điều bị báo KHÔNG PHẢI LỖI → **canh_bao_nha** viec='khong_phai_loi' cho TỪNG mã
   trong tin (kèm `truong` sau dấu «·», `ly_do` là lời họ nói). «Tôi biết rồi» → viec='im'.
5. Chỉ đề xuất **create_automation** khi user muốn quy tắc lâu dài.

## Không làm
- Không nói «em sẽ không báo nữa» khi chưa gọi tool ghi xong.
- Không khẳng định đã sửa nếu control/home_status chưa xác nhận.
- Không SSH / system_status trừ khi user hỏi máy chủ bot.
