# Từ điển Anh–Việt tra tại chỗ + Google Dịch đối chiếu

Hai thứ khác hẳn nhau, đừng lẫn:

| | Từ điển tại chỗ | Google Dịch |
|---|---|---|
| Dùng để | tra một từ, xem **mọi nghĩa** rồi tự chọn | đối chiếu bản dịch cả đoạn |
| Chạy ở đâu | trong máy chủ, đọc SQLite | gọi ra máy chủ Google |
| Mặc định | **bật** khi đã cài tệp | **tắt** |
| Chữ có rời máy không | không | **có** |

## 1. Vì sao cần từ điển, khi đã có máy dịch

Máy dịch buộc phải **chọn một nghĩa**. Người tra một từ thường cần **thấy hết
các nghĩa** rồi tự chọn cái đúng ngữ cảnh của mình.

Ví dụ đã gặp thật: chữ `stroke`. Từ điển trả về 12 nghĩa — *cú đánh*, *đột quỵ*,
*nét bút*, *kiểu bơi*, *tiếng chuông đồng hồ*, *vuốt ve*… Không có ngữ cảnh thì
không engine nào chọn đúng được, và khi nó chọn sai thì người dùng cũng không có
cách nào biết nó đã bỏ mất nghĩa nào.

Tra xong bấm **"Dùng nghĩa này"** là chữ được đổ xuống ô sửa thuật ngữ ngay bên
dưới; sửa cho gọn rồi bấm Lưu, từ lượt dịch sau máy luôn ra đúng chữ đó — cả ở
tab Dịch lẫn phụ đề video (xem [`services/thuat_ngu.py`](../services/thuat_ngu.py)).

## 2. Cài từ điển

Tệp ~44 MB nên **không** nằm trong git (`.gitignore` loại `*.db`) và **không**
nằm trong image (`.dockerignore` loại `/data`). Tải thẳng vào volume dữ liệu:

```bash
# trên máy chủ .38 — volume thật của container c2a là /opt/c2a/data
python scripts/tai_tu_dien.py --dich /opt/c2a/data/tudien
```

Không phải dựng lại image, không phải khởi động lại container: module đọc tệp
theo từng lượt tra. Chưa cài thì ô tra cứu tự báo "chưa cài từ điển", mọi thứ
khác chạy như cũ.

Script kiểm tệp tải về bằng chính SQLite (đếm số mục) rồi mới thay tệp cũ — một
proxy chặn giữa đường vẫn trả HTTP 200 kèm trang HTML, ghi đè lên thì mất từ
điển mà không ai biết.

## 3. Ghi nguồn — BẮT BUỘC

Dữ liệu từ điển là **CC BY-SA 4.0**, không phải MIT như phần code của dự án
này. Giấy phép đó buộc phải ghi nguồn và giữ nguyên giấy phép cho bản phái sinh.

- Kho dùng: [skypediacode/english-vietnamese-dictionary](https://github.com/skypediacode/english-vietnamese-dictionary)
  — 104.829 mục Anh, 158.307 nghĩa Việt, IPA và câu ví dụ phủ 100%.
- Kho đó dựng lại từ [MinhQND Dictionary](https://github.com/minhqnd/dictionary)
  (CC BY-SA 4.0), vốn tổng hợp từ Wiktionary, vntk/dictionary và Từ điển tiếng
  Việt của Hồ Ngọc Đức; hiệu đính đầu mục bằng OVDP.
- Code trong repo này vẫn là MIT. **Dữ liệu** từ điển giữ CC BY-SA 4.0.

Kho từng cân nhắc rồi loại:
[thichhoc-dict](https://github.com/thichhoc-org/thichhoc-dict) (155k mục, có cả
dạng biến thể — mạnh hơn nhưng là JSONL chia 93 mảnh, phải tự dựng chỉ mục);
[chuongmep/vi-en-dictionary](https://github.com/chuongmep/vi-en-dictionary)
(repo ghi MIT nhưng dữ liệu gốc AVDict không rõ giấy phép);
[EVBCorpus](https://github.com/qhungngo/EVBCorpus) (kho ngữ liệu song ngữ để
huấn luyện model, không phải từ điển tra cứu, lại không công bố giấy phép).

## 4. Google Dịch — tuỳ chọn, mặc định TẮT

Hai đường, khác nhau ở chỗ **ai** gửi chữ đi:

**a. Mở trang Google Dịch (không cần bật gì).** Các nút *Văn bản / Trang web /
Hình ảnh / Tài liệu* trong tab Dịch mở tab mới sang `translate.google.com` với
`sl`/`tl` và nội dung điền sẵn. Trình duyệt của người dùng tự gọi Google — máy
chủ này không gửi gì cả. Được hơn 130 tiếng, dùng cho những tiếng mà máy dịch
trong stack (vi/en/ja/ko/zh) không có.

Giới hạn có thật: *Văn bản* mang được ~1800 ký tự đầu (URL dài hơn bị cắt);
*Trang web* cần ô chữ đang chứa một link `http(s)://` — Google chuyển hướng
thẳng sang `<tên-miền>.translate.goog`; *Hình ảnh* và *Tài liệu* chỉ mở đúng
chế độ, tệp phải tự chọn bên đó vì URL không đính kèm tệp được (ảnh và tài liệu
thì tab Dịch đã dịch được tại chỗ ở phần tải tệp).

**b. Máy chủ hỏi Google để hiện bản đối chiếu (phải bật tay).** Bật ở tab Dịch →
*Google Dịch (đối chiếu)*. Sau mỗi lần dịch chữ sẽ có nút xem thêm bản của
Google để so với bản của máy trong stack.

Cần biết trước khi bật:

- **Chữ được gửi sang máy chủ Google.** Đó là lý do mặc định tắt — đây là quyết
  định về dữ liệu, không phải về kỹ thuật.
- Endpoint dùng là `translate.googleapis.com/translate_a/single?client=gtx` —
  thứ chính trang web của Google dùng, **không khoá, không tài liệu, không cam
  kết**. Có ngày Google đổi hoặc chặn theo IP.
- Vì vậy nó được cô lập hẳn: đường dịch chính không bao giờ gọi tới nó, lỗi
  không rò ra ngoài, và hỏng một lần thì cầu dao ngắt 5 phút.
