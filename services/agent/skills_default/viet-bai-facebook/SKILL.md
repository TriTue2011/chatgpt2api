---
name: Viết bài Facebook tự nhiên
description: Soạn/viết lại bài đăng Facebook nghe như người thật, bớt giọng AI. Dùng khi nhờ AI soạn bài, viết caption, hay chỉnh bài tự nhiên hơn.
group: Nội dung
---

# Viết bài Facebook tự nhiên

Phỏng theo rulebook `harshaneel/humanize` (MIT), đã CHUYỂN sang tiếng Việt —
danh sách từ máy móc tiếng Anh của repo vô dụng ở đây, phần dưới là bản Việt.
Mục tiêu: bài đọc ra **chất người, thật và cụ thể**, KHÔNG phải "qua mặt máy
chấm AI".

## Khi nào dùng
- "Nhờ AI soạn bài đăng Facebook", "viết caption", "viết status/bài bán hàng".
- Menu `/facebook` mục "✨ Nhờ AI soạn bài".
- "Làm bài này đọc tự nhiên hơn / bớt giọng máy / bớt AI".

## Khi nào KHÔNG dùng
- Người dùng đã tự gõ nội dung và chỉ muốn đăng y nguyên — đừng sửa văn của họ.
- Bài kỹ thuật/pháp lý cần đúng thuật ngữ chuẩn — giữ nguyên, đừng "tự nhiên hoá".
- Không phải văn cho người đọc (mã, bảng số liệu thô).

## Các bước
1. Hỏi gọn (vài câu/lượt): **chủ đề**, **ý chính**, **giọng** (vui / nghiêm /
   bán hàng), **có số liệu / tên / giá / ngày thật nào không**. Nếu người dùng đã
   đưa bài gốc để viết lại thì bỏ qua bước hỏi, lấy nội dung từ bài đó.
2. Viết nháp: rút NỘI DUNG ra rồi viết văn MỚI từ đó — đừng tráo từ câu gốc.
   Áp 9 đòn bẩy bên dưới ngay khi viết.
3. Tự soát theo mục "Trước khi trình" — **đếm thật**, sửa hết dấu hiệu máy.
4. Đọc lại bản nháp cho người dùng **DUYỆT**. Không tự đăng.
5. Khi họ đồng ý → gọi tool **`dang_facebook`**: `loai=chu`,
   `message=<bài>` (kèm `link` hoặc `media_urls` nếu có). `message` CHỈ chứa nội
   dung thật của bài — bỏ từ khung như "đăng bài", "caption là". Tool tự đưa qua
   cổng duyệt trước khi đăng thật.

## 9 đòn bẩy hành văn giống người (bản tiếng Việt)
1. **Từ có sức nặng.** Chọn động từ/danh từ cụ thể thay từ chung chung. Mỗi đoạn
   một, hai từ "đắt" nhưng đúng. Một danh từ chính + đại từ; đừng xoay vòng từ
   đồng nghĩa cho "sang". VD "sử dụng"→"xài/dùng", "mang lại trải nghiệm"→việc
   cụ thể người đọc làm được.
2. **Câu dài ngắn xen kẽ.** Cứ 3–4 câu chèn một câu cụt (≤6 từ). Câu dài nhất hơn
   câu ngắn nhất tầm 15+ từ. Không quá 3 câu liền nhau dài xấp xỉ.
3. **Bỏ rào đón.** Cắt "thường thì", "nhìn chung", "có thể nói", "phần lớn",
   "khá là", "đôi khi". Nói thẳng. Có ngoại lệ thì nêu đích danh.
4. **Phá khung liệt kê.** Bỏ "gồm 3 điều sau:", "Thứ nhất… Thứ hai…". Viết văn
   xuôi liền mạch. Đừng nhắc lại ý vừa nói. Dùng "là/có" thay "đóng vai trò là",
   "được xem là".
5. **Chi tiết cụ thể.** Mỗi ý trừu tượng phải có neo: số, tên, ngày, giá, ví dụ.
   "Bán rất chạy" → "Tuần trước hết 200 suất trong 2 ngày". Không có số thật thì
   dùng khung "khoảng…", "như mình thấy" — **KHÔNG bịa**.
6. **Có giọng người.** Ngôi thứ nhất khi hợp. Thi thoảng hỏi thẳng người đọc.
   Tự ngắt mạch ("mà thật ra…"). Dùng khẩu ngữ tự nhiên.
7. **Từ nối của người.** "Hơn nữa / Bên cạnh đó / Ngoài ra" (thừa) → bỏ hẳn hoặc
   "Còn", "Với lại", "Mà". "Có thể thấy rằng" → nói thẳng. "Như đã nói ở trên" →
   đừng nhắc lại.
8. **Dấu câu tự nhiên.** Người Việt viết Facebook hiếm dùng gạch ngang "—" và
   chấm phẩy ";" — thấy chúng là dấu hiệu máy, đổi thành chấm/phẩy hoặc tách câu.
   Đừng đặt dấu hai chấm giữa câu để "hé lộ".
9. **Bỏ giọng trợ lý.** Cắt "Xin chào các bạn, hôm nay mình…", "Hy vọng bài viết
   hữu ích", "Chúc các bạn…", "Đừng quên like share nhé" (khi gượng). Đừng cân
   bằng hai chiều cho an toàn — chọn một hướng. Bỏ tóm tắt cuối, bỏ khen xã giao.

## Từ / cụm máy móc tiếng Việt — BỎ hoặc thay
- **Từ nối máy:** Hơn nữa, Bên cạnh đó, Ngoài ra (thừa), Thêm vào đó, Đồng thời
  (nối gượng), Có thể thấy rằng, Điều này cho thấy, Rõ ràng là, Như đã đề cập,
  Nhìn chung, Về cơ bản.
- **Rào đón:** thường thì, trong nhiều trường hợp, có thể nói, phần lớn, khá là,
  tương đối, đôi khi (thừa).
- **Mở bài sáo:** "Trong thời đại số ngày nay", "Trong cuộc sống hiện đại",
  "Ngày nay,", "Trong bối cảnh…", "Bạn đã bao giờ tự hỏi…".
- **Kết bài sáo:** "Tóm lại", "Hy vọng bài viết hữu ích", "Cảm ơn đã đọc",
  "Chúc các bạn…", "Đừng quên like và share", "Hãy để lại bình luận nhé".
- **Tính từ thổi phồng rỗng:** tuyệt vời, vô cùng, cực kỳ, đa dạng và phong phú,
  chất lượng hàng đầu, uy tín, đẳng cấp, hoàn hảo, khó quên, không thể bỏ lỡ,
  đắm chìm, trọn vẹn, ấn tượng, nổi bật, đặc sắc, thăng hoa, bùng nổ, đóng vai
  trò then chốt.
- **Cấu trúc làm màu:** "không chỉ… mà còn…", "vừa… vừa…" (lạm dụng), hỏi tu từ
  sáo "Liệu rằng…?".

## Riêng cho Facebook
- **Emoji:** dùng vừa, đúng cảm xúc. KHÔNG rải một emoji ở đầu mỗi dòng — đó là
  dấu hiệu bài AI dễ nhận nhất.
- **Hashtag:** tối đa 2–3 cái thật sự liên quan, đặt cuối. Đừng nhồi.
- **Kêu gọi hành động:** cụ thể. "Ghé shop 12 Lê Lợi trước thứ 7" hơn "Nhanh tay
  đặt hàng ngay hôm nay".
- Đoạn ngắn 1–3 câu, xuống dòng thoáng. Có ít nhất một chi tiết thật (giá, giờ,
  địa điểm, con số) để bài có sức nặng.

## Trước khi trình (tự soát — ĐẾM, đừng "cảm giác")
- Câu dài nhất hơn câu ngắn nhất ≥ ~15 từ; có ≥1 câu cụt ≤6 từ.
- Không 3 câu liền nhau dài xấp xỉ.
- Không còn từ nối máy thừa; không mở "Trong thời đại…"; không kết "Hy vọng…/Chúc…".
- Không "không chỉ… mà còn…", không "vừa… vừa…" làm màu.
- Không "—" và ";" trừ khi thật cần; emoji không rải đều đầu dòng.
- Mỗi đoạn có ≥1 chi tiết cụ thể; đã bỏ tính từ thổi phồng rỗng.
- Xưng hô nhất quán từ đầu đến cuối.

## Cạm bẫy
- **Đừng bịa** số/tên/giá để "cụ thể hoá". Không có dữ liệu thật thì dùng khung
  "khoảng/ví dụ" hoặc hỏi người dùng.
- "Tự nhiên" không phải cẩu thả: vẫn đúng chính tả, đúng thông tin.
- Viết lại là đổi CÁCH DIỄN ĐẠT, không đổi sự thật người dùng cung cấp.
- Đây không phải công cụ né máy chấm AI. Bài hay đến từ chi tiết thật và giọng
  riêng, không phải từ mẹo dấu câu.
