---
name: Morning brief pipeline
description: Thu thập bối cảnh nhà/ngày rồi viết báo cáo sáng ngắn
verify: true
---

## Bước 1: Khung nội dung
Dựa trên yêu cầu ({{input}}), lập dàn ý báo cáo sáng gồm:
- Việc cần kiểm tra ở nhà (đèn, cửa, cảm biến, thiết bị bất thường)
- Thời tiết / lịch nếu user có nhắc
- Giọng điệu: ấm, xưng em, 5–8 dòng

Nếu input đã có số liệu nhà, giữ nguyên số liệu đó.

## Bước 2: Viết báo cáo
Dùng dàn ý / dữ liệu bước trước:
{{prev}}

Viết BẢN BÁO CÁO SÁNG hoàn chỉnh tiếng Việt (không meta, không "bước 1/2").
Có greeting ngắn + điểm cần chú ý + 1 gợi ý hành động (không tự điều khiển thiết bị).

## Bước 3: Làm gọn
Rút gọn bản sau cho dễ đọc trên chat (giữ đủ ý):
{{prev}}
