---
name: Điều khiển nhà đúng cách
description: Dùng đúng tool HA (home_status/describe_device/control_home/create_automation), tránh bẫy entity bịa.
group: Nhà thông minh
---

# Điều khiển nhà thông minh

Bổ sung cho skill `ha-device-troubleshoot` (đọc skill đó trước nếu thiết bị đang BÁO HỎNG/mất kết nối). Skill này là cách điều khiển ĐÚNG khi thiết bị đang hoạt động bình thường.

## Khi nào dùng
- "bật/tắt đèn…", "chỉnh điều hoà…", "đặt màu/độ sáng…", "tạo cảnh/quy tắc tự động…"

## Tool thật có
- **home_status**(query) — đọc trạng thái, lọc theo tên thiết bị/phòng.
- **describe_device**(entity_id|name) — tra schema THẬT từ HA (service, field, dải nhiệt độ/màu, preset…). Dùng TRƯỚC khi chỉnh tham số lạ (kelvin, hvac_mode, preset) — đừng đoán mò.
- **control_home**(command) — câu lệnh tự nhiên ("bật đèn phòng khách"). risk=CHANGE → chờ chủ nhà duyệt trừ khi đã cho phép "luôn luôn".
- **create_automation**(request) — tạo automation từ mô tả tự nhiên, tự viết cấu hình + nạp + tự sửa nếu lỗi. LUÔN cần chủ nhà xác nhận, kể cả khi mọi việc CHANGE khác đã set "luôn luôn" — vì ảnh hưởng lâu dài (chạy tự động về sau), không phải 1 lần.

## Bẫy thật đã gặp — entity bịa
Model từng gọi `light.ban_cong` (đèn ban công) trong khi entity thật là `light.bep_center` — HA **không báo lỗi**, vẫn trả "thành công" dù entity không tồn tại → điều khiển nhầm hoặc im lặng thiết bị mà không ai biết. Vì vậy hệ thống tự soi entity qua danh sách thiết bị thật của HA trước khi gọi:
- Đúng 1 ứng viên khớp tên → tự thay, chạy tiếp.
- Mơ hồ hoặc không thấy ứng viên → **không gọi HA**, trả lại "entity không tồn tại + gợi ý gần nhất".

→ Việc của em: khi thấy phản hồi kiểu "KHÔNG tồn tại trong HA — CHƯA gọi…", **hỏi lại chủ nhà đúng tên thiết bị**, đừng tự thử entity khác hay suy đoán tiếp.

## Phòng/khu vực
Không cần tự tra entity_id theo phòng — cứ nêu tên tự nhiên chủ nhà dùng ("đèn ban công", "quạt phòng ngủ"); hệ thống tự khớp theo tên hiển thị và bản đồ khu vực lấy từ HA (làm mới định kỳ).

## Đừng nhầm với system_status
**home_status** đọc cảm biến/thiết bị trong NHÀ (kể cả cảm biến phần cứng của máy đang chạy HA). **system_status** đọc phần cứng của máy chủ BOT đang chạy — hai máy khác nhau. "Nhà nóng không" → home_status; "server có nóng không / còn RAM không" → system_status. Hỏi nhầm tool sẽ trả lời sai máy.

## Không làm
- Không tự bịa/đoán entity_id khi không chắc — để hệ thống soi hoặc hỏi lại chủ nhà.
- Không gọi describe_device cho lệnh bật/tắt đơn giản — chỉ dùng khi tham số lạ.
- Không tự tạo automation khi chỉ được nhờ làm 1 lần ("bật đèn bây giờ" ≠ "cứ 18h bật đèn").
- Không tự thử lệnh khác khi control_home báo lỗi/không tìm thấy thiết bị — báo lại và hỏi.
