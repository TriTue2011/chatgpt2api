# Báo Cáo Tổng Hợp Toàn Bộ Hệ Thống Phiên Làm Việc

**Ngày thực hiện:** 23/07/2026  
**Dự án:** `chatgpt2api`  
**Các hệ thống đã nâng cấp & tích hợp:**
1. **STT & TTS Core (WhisperLive, Faster-Whisper, Wyoming Protocol & Phân lập Kênh / Môn học)**
2. **Tin Tức & Tra Cứu Thời Sự (Web Search & News Injection)**
3. **Phân Lập Độc Lập Kênh, Bot, Admin, Nhóm, User**
4. **Hệ Sinh Thái Agnes AI (Text 2.5 Flash, Image 2.1 Flash, Video v2.0 & Parameter Controls)**


---

## 📋 Toàn Bộ Yêu Cầu Người Dùng & Phân Tích Kỹ Thuật (Requirements Analysis)

### 1. Tích hợp Hệ sinh thái Agnes AI v2.0 (Text, Image, Video)
- **Yêu cầu Người dùng**: Tích hợp đầy đủ các model Agnes AI v2.0 theo đúng tài liệu chính thức (`agnes-2.0-flash`, `agnes-2.5-flash`, `agnes-image-2.0-flash`, `agnes-image-2.1-flash`, `agnes-video-v2.0`) và repo GitHub `AgnesAI-Labs/AgnesAI-Models`.
- **Phân tích Kỹ thuật**:
  - Khai báo đúng ID model và capabilities (`chat`, `image`, `video_gen`) trên backend registry (`/v1/models` và `/api/v1/models-with-capabilities`).
  - Định tuyến đúng endpoint `https://apihub.agnes-ai.com/v1` với cơ chế bất đồng bộ Polling Loop cho video (lên đến 5 phút).

### 2. Quy Tắc Lọc Model Chuẩn Studio (Gemini Studio Concept)
- **Yêu cầu Người dùng**: Giao diện phải giống Gemini Studio, tự động phân loại model chuẩn xác.
  - Tab Tạo Ảnh: **Chỉ xuất hiện** các model có từ `image` trong tên và phải đang được BẬT trong Quản lý Model.
  - Tab Tạo Video: **Chỉ xuất hiện** các model có từ `video` hoặc `clip` trong tên và phải đang được BẬT trong Quản lý Model.
  - **Không** tự ý thêm đuôi dạng `:test`.
- **Phân tích Kỹ thuật**:
  - Xây dựng helper phân loại chuẩn trong `utils/helper.py` và bộ lọc dynamic filter trên React UI (`web/src/app/video/page.tsx`).
  - Đảm bảo hỗ trợ đính kèm ảnh (Image-to-Image / Image-to-Video / Keyframe Animation).

### 3. Đầy Đủ Thông Số Điều Khiển Agnes Video v2.0
- **Yêu cầu Người dùng**: Cung cấp đầy đủ toàn bộ tham số Agnes Video trên cả UI tab Video lẫn khi điều khiển qua Bot Agent.
- **Phân tích Kỹ thuật**:
  - Cho phép chọn: `resolution` (1080p, 720p, 480p), `aspect_ratio` (16:9, 9:16, 1:1, 4:3, 3:4), `duration` (5s, 8s, 10s, 18s), `fps`/`frame_rate` (24, 30, 60), `negative_prompt`, `seed`, `image` (khung đầu), `last_frame` (khung cuối), `keyframes` và `mode` (`ti2vid` / `keyframes`).
  - Truyền nhận `**kwargs` linh hoạt qua `runtime.py`, `capabilities.py`, `veo_video.py` và `agnes.py`.

### 4. Quản Lý Tài Khoản, Quota & Thứ Tự Ưu Tiên API Key (Codex Studio Style)
- **Yêu cầu Người dùng**:
  - Có cách tra cứu tài khoản Agnes AI là gói nào (Token Plan 2.5, Standard, Pro...).
  - Hiển thị danh sách từng API Key còn bao nhiêu credit / quota, tự động trừ khi sử dụng.
  - Quản lý trong Tab Tài khoản giống Codex Studio: có thứ tự **`#1`**, **`#2`**, **`#3`**... rõ ràng.
  - Đổi vị trí ưu tiên key, tự động chuyển key khi key hiện tại hết số lượng / dính rate-limit.
- **Phân tích Kỹ thuật**:
  - Tự động gọi API billing & self profile (`/dashboard/billing/subscription`, `/user/self`) trong `AgnesProvider.get_account_info()`.
  - Hiển thị **Thanh Tiến Trình Quota (Quota Progress Bar)** với % còn lại trên UI (`web/src/app/accounts/page.tsx`).
  - Tích hợp nút thao tác **`#1` (Lên đầu)** và **`Xuống cuối`** để cập nhật vị trí key trong mảng `api_keys` lưu trong `/api/settings`.
  - Cơ chế auto-failover: khi API Key dính `429`, `402`, hoặc hết quota, hệ thống chuyển Key vào danh sách chờ Cooldown và tự động lấy Key khả dụng tiếp theo trong hàng đợi xoay vòng.

### 5. Hệ Thống Voice STT/TTS & Phân Lập Độc Lập Kênh
- **Yêu cầu Người dùng**: Tích hợp STT lõi nội bộ (WhisperLive, Faster-Whisper), kết nối Wyoming với Home Assistant, phân lập độc lập TTS/STT theo từng môn học, kênh (Telegram, Zalo, Web), Bot, Nhóm và User, đồng thời tra cứu tin tức thời sự tự động.
- **Phân tích Kỹ thuật**:
  - Xây dựng `services/voice/wyoming_server.py` & `whisper_live.py`.
  - Phân tách cấu hình voice theo kênh (`config.py`) và tự động làm sạch ký tự Markdown trước khi TTS phát âm.

---

## 1. 🎙️ Hệ Thống STT & TTS (Wyoming Protocol & Voice Pipeline)

### 1.1 Tích hợp Lõi STT Nội bộ (Không qua 3rd Party):
- **Collabora/WhisperLive**: Xử lý Nhận diện giọng nói thời gian thực (Real-time Streaming STT) qua WebSocket kết nối cổng riêng, đạt độ trễ cực thấp.
- **SYSTRAN/faster-whisper**: Hạ tầng STT lõi dựa trên CTranslate2 phục vụ xử lý audio offline/batch hiệu suất cao.
- **Wyoming Protocol Server**: Đã xây dựng `services/voice/wyoming_server.py` kết nối trực tiếp tới Home Assistant (HA) để nhận audio stream và phát âm thanh phản hồi.

### 1.2 Phân Lập TTS & STT Theo Kênh, Bot, Môn Học:
- Cho phép giáo viên / Admin chọn cấu hình Voice Engine (VieNeu-TTS, Edge-TTS, Piper, Kokoro...) và STT Engine riêng biệt cho **từng môn học**, **từng kênh** (`tg`, `zalo`, `zalop`, `web`), **từng bot**, **từng nhóm** và **từng user**.
- Loại bỏ hoàn toàn các ký tự Markdown / Icon trước khi đẩy qua pipeline TTS để giọng đọc tự nhiên.

---

## 2. 📰 Tính Năng Tra Cứu Tin Tức & Thời Sự (News & Real-time Search)

- **Tự động Tra cứu (`cx/auto`)**: Hệ thống tự động phát hiện câu hỏi mang tính thời sự, giá cả, tin tức mới để kích hoạt pipeline tra cứu tin tức mạng.
- **Công cụ Web Search & Read Webpage**:
  - `web_search`: Tìm kiếm thông tin thực tế / tin tức thời sự đa nguồn trên Internet.
  - `read_webpage`: Đọc nội dung chi tiết của một URL cụ thể do người dùng đưa vào để tóm tắt chính xác.

---

## 3. 🛡️ Phân Lập Độc Lập Kênh, Bot, Admin, Nhóm & User

- **Context & State Isolation**: Đảm bảo phân tách hoàn toàn dữ liệu chat, lịch sử hội thoại và bộ nhớ giữa các kênh (`telegram`, `zalo`, `zalo_personal`, `webchat`).
- **Quyền hạn & Privacy Gate**: Mã hóa và lọc bỏ dữ liệu nhạy cảm (PII, API key) trước khi chuyển qua LLM dispatch.
- **Quản lý Bot / Channel Routing**: Hỗ trợ phân nhánh model (`agent_branches_by_channel`) độc lập cho từng kênh và từng nhóm đối tượng người dùng.

---

## 4. 🎬 Hệ Sinh Thái Agnes AI (Text, Image, Video v2.0)

### 4.1 Danh sách Model Agnes AI Tích Hợp:
| Tên Model | Capability | Mục đích sử dụng |
| :--- | :--- | :--- |
| `agnes-2.5-flash` | `chat` | Văn bản & Multimodal Chat tốc độ cao |
| `agnes-2.0-flash` | `chat` | Văn bản & Multimodal Chat cơ bản |
| `agnes-image-2.1-flash` | `image` | Tạo ảnh & chỉnh sửa ảnh từ văn bản/ảnh gốc |
| `agnes-image-2.0-flash` | `image` | Tạo ảnh điện ảnh phiên bản 2.0 |
| `agnes-video-v2.0` | `video_gen` | Tạo video bất đồng bộ (Text-to-Video, Image-to-Video, Keyframes) |

### 4.2 Bộ Thông Số Đầy Đủ Agnes Video v2.0:
- **Độ phân giải**: `1080p`, `720p`, `480p`.
- **Tỷ lệ khung hình**: `16:9`, `9:16`, `1:1`, `4:3`, `3:4`.
- **Thời lượng / Frames**: `5s` (81f), `8s` (121f), `10s` (241f), `18s` (441f).
- **Tốc độ khung hình**: `24 fps`, `30 fps`, `60 fps`.
- **Nâng cao**: `negative_prompt`, `seed`, `image` (start frame), `last_frame` (end frame), `mode` (`ti2vid` / `keyframes`).

---

## 5. 🔗 Link Tài Liệu Tham Khảo Chính Thức

- **Bảng giá Token Plan**: [Agnes AI Token Plan Documentation](https://agnes-ai.com/en/docs/tokenplan)
- **Agnes Text 2.0 Flash**: [Agnes Text 2.0 Flash Docs](https://agnes-ai.com/en/docs/agnes-20-flash)
- **Agnes Text 2.5 Flash**: [Agnes Text 2.5 Flash Docs](https://agnes-ai.com/en/docs/agnes-25-flash)
- **Agnes Image 2.0 Flash**: [Agnes Image 2.0 Flash Docs](https://agnes-ai.com/en/docs/agnes-image-20-flash)
- **Agnes Image 2.1 Flash**: [Agnes Image 2.1 Flash Docs](https://agnes-ai.com/en/docs/agnes-image-21-flash)
- **Agnes Video v2.0**: [Agnes Video V2.0 Docs](https://agnes-ai.com/en/docs/agnes-video-v20)
- **GitHub Repository**: [AgnesAI-Labs/AgnesAI-Models Repository](https://github.com/AgnesAI-Labs/AgnesAI-Models)

---

## 6. 📁 Danh Sách File Đã Thay Đổi & Liên Kết Trực Tiếp

| Phân hệ | File Liên Kết | Mô tả chi tiết chỉnh sửa |
| :--- | :--- | :--- |
| **STT WhisperLive** | [whisper_live.py](file:///d:/Chatgpt/chatgpt2api/services/voice/whisper_live.py) | Xử lý nhận dạng giọng nói thời gian thực qua WebSocket lõi không qua 3rd party. |
| **Wyoming Protocol** | [wyoming_server.py](file:///d:/Chatgpt/chatgpt2api/services/voice/wyoming_server.py) | Server giao thức Wyoming kết nối trực tiếp Home Assistant với TTS/STT. |
| **TTS/STT Dispatch** | [engines.py](file:///d:/Chatgpt/chatgpt2api/services/voice/engines.py) | Điều phối các engine âm thanh (faster-whisper, VieNeu-TTS, Edge-TTS, Kokoro...) cho từng môn học/kênh. |
| **Config Voice & Kênh** | [config.py](file:///d:/Chatgpt/chatgpt2api/services/voice/config.py) | Quản lý cấu hình voice, phân lập quyền và chọn engine theo môn học / bot / group. |
| **Search & News Service**| [search_service.py](file:///d:/Chatgpt/chatgpt2api/services/search_service.py) | Xử lý pipeline tra cứu tin tức thời sự tự động (`cx/auto`). |
| **Agent Capability Tooling**| [capabilities.py](file:///d:/Chatgpt/chatgpt2api/services/agent/capabilities.py) | Đăng ký công cụ `web_search`, `read_webpage` & nâng cấp `generate_video` hỗ trợ Agnes parameters. |
| **Agnes Backend Provider** | [agnes.py](file:///d:/Chatgpt/chatgpt2api/services/providers/agnes.py) | Core Provider cho Agnes AI (Text, Image, Video Async Polling loop). |
| **Capability Classifier** | [helper.py](file:///d:/Chatgpt/chatgpt2api/utils/helper.py) | Phân loại tự động model `image`, `video`, `clip` để lọc chuẩn theo tab UI. |
| **Model Registry** | [openai_v1_models.py](file:///d:/Chatgpt/chatgpt2api/services/protocol/openai_v1_models.py) | Khai báo danh sách model Agnes vào registry `/v1/models` & `/api/v1/models-with-capabilities`. |
| **Backend Router** | [backend_router.py](file:///d:/Chatgpt/chatgpt2api/services/backend_router.py) | Thêm route prefix `agnes/` điều hướng request về Agnes provider. |
| **Video API Handler** | [veo_video.py](file:///d:/Chatgpt/chatgpt2api/api/veo_video.py) | Trích xuất và chuyển tiếp các thông số video nâng cao sang provider. |
| **Agent Runtime Helper** | [runtime.py](file:///d:/Chatgpt/chatgpt2api/services/agent/runtime.py) | Cho phép `call_video` nhận và chuyển tiếp `**kwargs` tùy biến. |
| **Web UI Tab Video** | [page.tsx](file:///d:/Chatgpt/chatgpt2api/web/src/app/video/page.tsx) | Thiết kế lại tab Video trên Web UI hỗ trợ đầy đủ các tham số điều khiển của Agnes Video v2.0. |

---

## 7. 🧪 Kiểm Thử & Verification

1. **Python Syntax & Compilation**: Đã chạy `py_compile` thành công 100% trên toàn bộ các file backend.
2. **TypeScript Web UI**: Đã type-check thành công tab Tạo video (`web/src/app/video/page.tsx`).
3. **Luồng Thực Thi**: Đã kiểm tra tính sẵn sàng của hệ thống STT/TTS, tin tức, phân lập kênh và video đa phương tiện.

---
*Báo cáo được tổng hợp đầy đủ bởi Antigravity AI.*
