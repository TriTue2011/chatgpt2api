---
name: Morning home brief
description: Báo cáo nhà buổi sáng — HA trạng thái, thời tiết, lịch nhắc.
group: Nhà
---

# Báo cáo nhà buổi sáng

## Khi nào dùng
- "báo cáo nhà buổi sáng", "sáng nay nhà thế nào", "tổng hợp sáng"
- Việc định kỳ mode=task: "mỗi sáng 7h báo cáo nhà"

## Các bước
1. Gọi tool **home_status** (query trống hoặc "tổng quan") — tóm tắt đèn/cảm biến bất thường, thiết bị unavailable.
2. Nếu cần thời tiết ngoài trời: **web_search** "thời tiết hôm nay [thành phố]" (chỉ khi user/nhà có nhắc địa điểm; không bịa).
3. Trả lời NGẮN (5–8 dòng), xưng em:
   - Nhà: điểm cần chú ý (thiết bị lỗi / cửa / nhiệt độ nếu có)
   - Việc: nhắc lịch/nhắc hẹn nếu vừa liệt kê được qua ngữ cảnh
   - Gợi ý 1 hành động (vd bật thông gió) nếu hợp lý — **không** tự control_home trừ khi user yêu cầu rõ

## Không làm
- Không liệt kê thô hàng chục entity
- Không bịa số liệu khi home_status lỗi — nói thẳng em chưa đọc được
