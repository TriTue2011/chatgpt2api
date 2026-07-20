---
name: HA device troubleshoot
description: Khắc phục thiết bị HA hỏng/mất kết nối (camera, đèn, cảm biến).
group: Nhà
---

# Khắc phục thiết bị nhà thông minh

## Khi nào dùng
- "camera không hoạt động", "đèn không bật", "cảm biến mất kết nối", "thiết bị unavailable"

## Các bước
1. **home_status** với query = tên thiết bị/phòng user nêu.
2. Phân loại:
   - `unavailable` / `unknown` → mất kết nối / tích hợp
   - `off` khi user muốn on → dùng **control_home** (CHANGE — chờ duyệt nếu chưa always)
   - Không thấy tên gần đúng → hỏi lại tên hoặc liệt kê 3 gợi ý gần nhất
3. Trả lời: nguyên nhân khả dĩ + bước user kiểm tra (nguồn, Wi-Fi, pin) + em có thể thử gì tiếp.
4. Chỉ đề xuất **create_automation** khi user muốn quy tắc lâu dài, không phải sửa sự cố tức thì.

## Không làm
- Không khẳng định đã sửa nếu control/home_status chưa xác nhận
- Không SSH / system_status trừ khi user hỏi máy chủ bot
