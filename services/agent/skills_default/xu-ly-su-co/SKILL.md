---
name: Xử lý sự cố hệ thống
description: Playbook chẩn đoán — container không lên, MCP mất tool, quota hết, giọng chưa tải, đầy đĩa.
group: Hệ thống
---

# Xử lý sự cố hệ thống

## Khi nào dùng
- "sao bot không chạy", "restart xong mất tool", "báo lỗi hết quota", "đọc không ra tiếng", "server đầy đĩa"
- Trước khi kết luận "lỗi lạ", đối chiếu đúng nguyên nhân bên dưới thay vì đoán bừa.

## 1. Container không lên (cứ Restarting)
- Xác nhận: `/version` không phản hồi. Nếu container đã sập hẳn, em KHÔNG tự đọc log của chính nó được (bot cũng nằm trong container đó) — cần chủ nhà tự chạy `docker logs <container> --tail 50` trên server rồi dán lại. **remote_system_status** KHÔNG dùng được ở đây: nó chỉ đọc phần cứng cố định (OS/uptime/CPU/RAM/ổ đĩa/tiến trình), không đọc log.
- Nguyên nhân hay gặp nhất: thiếu/sai `CHATGPT2API_AUTH_KEY` (env) hoặc `auth-key` trong `config.json` — app raise lỗi ngay lúc nạp cấu hình, container thoát ngay, không kịp lắng nghe cổng.
- Xử lý: chỉnh đúng biến môi trường hoặc `auth-key` trong `data/config.json` rồi khởi động lại.

## 2. Vừa restart xong, tool MCP (vn_weather, tìm kiếm, SSH…) không thấy
- Nguyên nhân: vn-mcp-hub cần khoảng nửa phút để nạp xong các MCP con; gateway chính khởi động gần như cùng lúc nên vài chục giây đầu coi hub "chưa vào" được. Vì đây là hub nội bộ (không phải MCP ngoài), thời gian chờ trước khi thử lại chỉ vài giây — tự hồi phục nhanh, không cần can thiệp.
- Xử lý: đợi khoảng 1 phút rồi thử lại. Còn mất sau vài phút, cần chủ nhà tự xem log tiến trình vn-mcp-hub trên server (`docker exec -it <container> supervisorctl tail vn-mcp-hub`) có lỗi thật không — em không tự làm được việc này với chính container của mình.

## 3. Model/tài khoản báo hết quota, bị cooldown
- Xác nhận: cần admin xem `/api/v1/health` — mục accounts (active/limited/error theo từng nhóm provider) và model_cooldown.
- Nguyên nhân: pool tài khoản đánh dấu "limited" khi provider trả lỗi giới hạn, tự hồi theo mốc reset provider trả về; "disabled" tự thử lại sau vài tiếng. Ngoài ra hệ thống còn chặn riêng theo từng cặp (tài khoản, model) khi gặp lỗi quota/không có quyền/hết hạn thanh toán/lỗi server — không phải cứ 1 tài khoản lỗi là toàn bộ model đó chết.
- Xử lý: báo chủ nhà provider nào đang hạn chế và ước khi nào tự hồi; nếu cần dùng ngay, đề xuất đổi qua provider khác hoặc xin thêm tài khoản/API key.

## 4. Đọc loa/gửi voice báo "model chưa tải"
- Xác nhận: đúng thông báo kiểu "Model VieNeu/Kokoro chưa tải (chạy scripts/download_..._model.py)".
- Nguyên nhân: giọng TTS không nằm sẵn trong image (để ảnh nhẹ) — phải tải riêng vào `data/piper` (Piper), `data/hf` (VieNeu), `data/kokoro` (Kokoro).
- Xử lý: báo đúng script cần chạy trên server (`scripts/download_vieneu_model.py` / `download_kokoro_model.py` / `download_piper_voices.py`); đây là việc THAY ĐỔI trên server — hỏi chủ nhà trước khi tự SSH chạy.

## 5. Ổ đĩa server đầy
- Xác nhận: **system_status** (đọc dung lượng `/app/data` của chính máy chủ bot) hoặc **remote_system_status** chạy `df -h /` (máy khác, có mật khẩu ngay lúc hỏi).
- Nguyên nhân hay gặp: ảnh Docker cũ tích luỹ qua mỗi lần deploy (ảnh khá nặng vì kèm trình duyệt/model).
- Xử lý: đề xuất chủ nhà dọn `docker image prune -af` + `docker container prune -f` trên server (hoặc qua `ssh_run` nếu server đó đã khai báo trước) — đây là việc THAY ĐỔI, luôn xin phép trước.

## 6. Container chạy bình thường nhưng 1 tính năng im lặng không hoạt động
- (Cloudflare tunnel không lên, HA không tự nạp, nhắc lịch không chạy, webhook Telegram/Zalo không đăng ký…)
- Nguyên nhân: mỗi bước khởi động phụ được bọc riêng — lỗi 1 bước KHÔNG làm sập cả container, chỉ ghi lại rồi bỏ qua.
- Xác nhận: dòng "STARTUP HEALTH SUMMARY" / "startup_step_failed" trong log cho biết đúng bước nào hỏng và lỗi gì (thường do thiếu cấu hình/token cho tính năng đó) — cần chủ nhà tự xem log server vì đây là log của chính container bot.
- Xử lý: báo đúng tên bước + lỗi, hỏi chủ nhà có muốn cấu hình thêm không — không đoán bừa nguyên nhân.

## Không làm
- Không khẳng định "đã sửa xong" khi chưa xác nhận lại (gọi lại system_status/health hoặc xem log mới).
- Không tự SSH chạy lệnh dọn/tải model/deploy khi chưa được đồng ý — đều là việc THAY ĐỔI trên server thật.
