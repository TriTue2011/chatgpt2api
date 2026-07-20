[🇺🇸 English](README_VN_MCP_HUB.md) | [🇻🇳 Tiếng Việt](README_VN_MCP_HUB.vi.md)

**[🔙 Quay lại Trang Chủ (Main README)](README.vi.md)**

# 📖 Hướng Dẫn Sử Dụng & Cấu Hình VN MCP Hub

Tài liệu này hướng dẫn chi tiết cách cấu hình Docker **VN MCP Hub** để mở rộng bộ não cho AI (Search, RAG, Công cụ).

---

## 🎛️ Chi Tiết Cách Cài Đặt Từng Tab VN MCP Hub Studio

Sau khi cài đặt xong, mở dashboard `http://[IP_MÁY_CHỦ]:3030` → vào **Tab MCP** (Studio đã tích hợp tại đây, không còn trang `:8005/studio` riêng) để bắt đầu thêm tính năng cho AI.

### 1. Tab Knowledge Base (Trí Nhớ Cục Bộ - RAG)
- **Công dụng**: RAG (Retrieval-Augmented Generation) là kho kiến thức bạn tự dạy cho AI. Thay vì AI phải lên mạng tìm kiếm, nó sẽ đọc trực tiếp tài liệu bạn cung cấp để trả lời.
- **Cách sử dụng**:
  - Tại giao diện, có sẵn một số kho mẫu như: Điện nước, Sơ cứu y tế, Luật.
  - Bấm nút **Create New KB**.
  - Dán nội dung (copy & paste) từ tài liệu công ty, quy trình làm việc, hoặc hướng dẫn sinh hoạt gia đình (dưới dạng văn bản hoặc Markdown) vào ô nội dung. 
  - Đặt tên cho kho kiến thức.
  - Bấm Save. Hub sẽ tự động băm nhỏ (chunking) văn bản và nhét vào Chroma DB (Vector Database). AI sau này sẽ tự ưu tiên tìm trong kho này trước.
  - **Lưu ý**: Hãy dùng định dạng Markdown với các thẻ Heading (`#`, `##`) để Hub cắt chunk một cách chính xác nhất theo từng phần.

### 2. Tab Multi-Search (Cấu Hình Tìm Kiếm)
- **Công dụng**: Chọn và cấu hình các Search Engine quốc tế để AI có thể quét dữ liệu thời gian thực trên mạng.
- **Cách sử dụng**: 
  - Mở tab Multi-Search, bạn sẽ thấy danh sách các cỗ máy tìm kiếm.
  - Bật/tắt các nguồn bằng nút công tắc: 
    - **DuckDuckGo**: Mặc định ngon nhất, không bị giới hạn và không cần API Key.
    - **Brave Search**: Cần dán API Key lấy từ trang developer của Brave. Rất tốt cho tin tức.
    - **Wikipedia**: Tốt cho các định nghĩa và lịch sử.
  - Khi AI được người dùng hỏi một thông tin mà RAG cục bộ không có đáp án, Hub sẽ âm thầm gọi Search.
  - **Ghi chú Quan Trọng**: Không nên bật quá nhiều nguồn (trên 5 nguồn) cùng lúc vì sẽ làm tăng thời gian chờ (latency) của AI.

### 3. Tab Cloud Storage (Đồng Bộ Đám Mây)
- **Công dụng**: Nếu ổ cứng máy chủ hỏng hoặc bạn chuyển VPS, bạn sẽ mất công sức dạy AI trong Tab Knowledge Base. Tab này dùng Cloudflare R2 (hoặc AWS S3) để tự động sao lưu toàn bộ Chroma DB lên mây.
- **Cách cấu hình**: 
  - Nhập Endpoint URL (Ví dụ: `https://<account_id>.r2.cloudflarestorage.com`).
  - Nhập Access Key và Secret Key của bucket R2/S3.
  - Nhập Tên Bucket.
  - Bật chế độ tự động đồng bộ (Auto Sync). Hệ thống sẽ tự động snapshot và up lên Cloud vào lúc 2h sáng mỗi ngày.
  - Bạn cũng có thể bấm **Force Sync Now** để đồng bộ ngay lập tức.
