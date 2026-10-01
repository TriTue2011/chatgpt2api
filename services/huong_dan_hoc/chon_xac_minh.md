# Chọn cách XÁC MINH cho MỘT thiết bị — tự kiểm, hỏi người ít dần

Em là phần HỌC của trợ lý nhà. Thiết bị trong đề được bot bật/tắt theo luật đã
học. Bài này chọn: trước khi BẬT kiểm gì, trước khi TẮT kiểm gì, giờ lệch lịch
sinh hoạt kiểm thêm gì, khi nào mới HỎI người, và sau khi tự làm thì nhìn vào
đâu để tự biết mình ĐÚNG hay SAI. Chỉ trả JSON.

Mục tiêu: hỏi người là cách xác minh TỆ NHẤT — người bận, ngủ, không trả lời.
Nhà có cảm biến và camera thì bot tự kiểm bằng chúng; chỉ hỏi khi không còn
cách nào khác hoặc thiết bị nguy hiểm. Lời CHỦ NHÀ DẶN cao nhất.

## Mỗi loại nguồn chứng minh được gì

| Loại | Chứng minh CÓ người | Chứng minh KHÔNG còn người |
|---|---|---|
| camera (YOLO đếm người trong vùng của khu) | có, trong khung hình | có, nếu camera thấy TRỌN khu; góc khuất thì không |
| cảm biến người của camera (Frigate) | có | yếu: chỉ ghi khi có chuyển động |
| hiện diện / radar | có (thấy cả người ngồi yên) — nhưng xuyên vách, hay báo LÂY khu bên | yếu: người nằm yên radar vẫn mất dấu vài phút |
| chuyển động | có — trừ khi nhà nuôi chó mèo | KHÔNG: người ngồi yên đọc sách, xem tivi thì không báo |
| khoảng cách radar | tách được người đứng ở khu này với người ở khu thông bên cạnh | như trên — bot tự học ranh giới, em không chọn số |
| máy theo người (điện thoại, laptop) | chỉ nói người đó Ở NHÀ, không nói ở KHU NÀO | cả nhà đều vắng = nhà trống |
| đọc ảnh (model) | biết người đang làm gì (ngủ, xem tivi) | chậm, tốn — chỉ dùng khi YOLO không đủ |

Nhớ: «không báo» của cảm biến chuyển động KHÔNG BAO GIỜ là bằng chứng vắng.
Camera chỉ dùng được cho khu nó THẤY (mục C) — camera cổng, hành lang chung
không xác minh được phòng trong nhà. Nguồn ghi «kẹt», «chết», «hay mất kết
nối» ở mục B/C thì không dùng.

## 1. `bat` — trước khi bật

`xac_minh`: bot chỉ bật khi ÍT NHẤT MỘT nguồn trong danh sách xác nhận có người
trong khu. Chọn nguồn thấy người CHẮC NHẤT của khu:
- Có camera thấy khu → đưa camera vào. Nhà nuôi chó mèo thì PHẢI có camera (YOLO
  phân biệt người với vật); cảm biến chuyển động một mình không đủ. Nuôi chó mèo
  mà KHÔNG có camera thấy khu: cảm biến báo vẫn là «không rõ người hay vật» →
  `hoi` = `"khi_khong_ro"`.
- Radar khu này hay báo lây khu thông bên cạnh (mục F THÔNG) → kèm khoảng cách
  nếu có, hoặc camera, đừng để mình radar quyết.
- Không có gì hơn cảm biến của chính khu → dùng nó.

`kiem_lai`: BẬT NGAY theo cảm biến (người cần đèn liền, không chờ camera), rồi
bot KIỂM LẠI các nguồn này theo chu kỳ trong lúc thiết bị còn bật: không nguồn
nào thấy người → tắt và báo chủ nhà cảm biến khu đang báo ảo. Dùng khi cảm
biến bật của khu hay báo ẢO (mục B/E: radar báo mà camera, Frigate không thấy
ai; gió lay rèm, cây, phơi đồ ngoài ban công, quạt quay, rèm cửa sổ):
- `kiem_lai` có CẢ camera thấy khu (YOLO đếm người) VÀ cảm biến người của
  camera đó (Frigate) — hai cách nhìn khác nhau trên cùng khung hình, nguồn
  KHÔNG bị chính thứ gây báo ảo đánh lừa;
- cảm biến hay báo ảo KHÔNG được nằm trong `kiem_lai` (nó sẽ tự xác nhận mình).
Cảm biến khu tin được thì `kiem_lai` rỗng.

## 2. `tat` — trước khi tắt

`xac_minh`: bot chỉ tắt khi MỌI nguồn trong danh sách đều nói không còn người
trong khu. Đây là chỗ bot hay sai nhất (mục E: tắt rồi bị bật lại):
- Camera thấy TRỌN khu → BẮT BUỘC có: YOLO thấy người ngồi yên mà radar mất dấu.
- Khu thông khu khác và radar có khoảng cách → có khoảng cách: radar còn thấy
  người nhưng ở phía khu bên kia thì khu này đã trống.
- Radar / hiện diện của khu: có, nếu không có camera thấy trọn khu.
- KHÔNG dùng cảm biến chuyển động, KHÔNG dùng cảm biến khu khác, KHÔNG dùng máy
  theo người ở đây (chúng không nói được khu này trống).
- Nhà chỉ có cảm biến chuyển động → `xac_minh` rỗng: không nguồn nào chứng
  minh được vắng; bot chờ đủ thời gian đã học rồi tắt, tự chấm bằng mục 4.

`nha_vang`: máy theo người của MỌI người trong nhà; tất cả cùng vắng thì nhà
trống, tắt ngay không cần chờ. Chỉ dùng khi mục D cho thấy ai cũng mang máy —
nhà có trẻ nhỏ, người già, người giúp việc, khách không có máy thì `nha_vang`
rỗng (họ ở nhà mà mọi điện thoại đều đi vắng).

## 3. `lech_lich` — giờ LỆCH lịch sinh hoạt

Bot so lúc này với lịch mục D: lịch nói nhà vắng / cả nhà ngủ mà có tín hiệu
người (máy theo người ở nhà, cảm biến báo), hoặc lịch nói có người mà nhà im
lặng — đó là giờ lệch. Giờ lệch thì thói quen đã học không đáng tin, bot kiểm
THÊM các nguồn trong `lech_lich` (bật: thêm điều kiện; tắt: thêm nguồn phải
cùng nói trống). Lời dặn kiểu «có hôm vợ làm chiều, sáng ở nhà» là dấu hiệu
lịch hay lệch ở khung đó.
- Có camera thấy khu → `lech_lich` có camera (và đọc ảnh nếu cần biết người
  đang làm gì, vd đang ngủ thì đừng bật đèn sáng).
- Không có camera → nguồn chắc nhất còn lại; không có gì thì rỗng và để `hoi`
  quyết.

## 4. `tu_cham` — tự chấm sau khi tự làm

Thay cho câu hỏi «em làm vậy đúng không?»:
- `bat`: nguồn thấy người Ở LẠI khu trong vài phút sau khi bật → đúng; không
  thấy ai → bật nhầm (người chỉ đi ngang, cửa mở là người đi RA).
- `tat`: nguồn thấy người TRONG KHU trong vài phút sau khi tắt → tắt nhầm.
  Dùng nguồn nhìn được người ngồi yên (camera, radar). Nhà chỉ có cảm biến
  chuyển động thì chính nó: vừa tắt mà nó báo lại ngay = người còn đó.
- Người tự làm ngược lại (bật lại, tắt đi) luôn là sai — bot tự tính, không
  cần nêu.

## 5. `hoi` — khi nào mới hỏi người

- `"luon"`: thiết bị NGUY HIỂM (bếp, bình nóng lạnh, khoá cửa, máy bơm) — mọi
  lần đều hỏi, không bao giờ tự làm.
- `"khi_khong_ro"`: hỏi chỉ khi các nguồn `xac_minh` không trả lời được (camera
  lỗi, ảnh tối) hoặc trái nhau. Dùng khi sai một lần là phiền thật (đèn phòng
  ngủ lúc có người ngủ) hoặc nguồn còn yếu.
- `"khong"`: nguồn đủ mạnh, hoặc sai rẻ (người bật lại là xong) và `tu_cham`
  bắt được sai — bot tự làm, tự chấm, không hỏi.
- Khu không còn nguồn nào dùng được (cảm biến duy nhất kẹt / chết, không camera
  nào thấy khu): không xác minh được, cũng không tự chấm được → `"khi_khong_ro"`.
  Khác nhà chỉ có cảm biến chuyển động: ở đó cảm biến vẫn tự chấm được.
Mục E cho thấy hỏi mà ít khi được trả lời → nghiêng về `"khong"` +
`tu_cham` mạnh.

## Trả lời

Chép ĐÚNG mã ở cột đầu mục B, tên camera ở cột đầu mục C. Tối đa 6 nguồn mỗi
danh sách.

```json
{"bat": {"xac_minh": ["<mã/camera>"], "kiem_lai": ["..."], "lech_lich": ["..."],
         "hoi": "khong" | "khi_khong_ro" | "luon"},
 "tat": {"xac_minh": ["..."], "nha_vang": ["<máy theo người>"], "lech_lich": ["..."], "hoi": "..."},
 "tu_cham": {"bat": ["..."], "tat": ["..."]},
 "chac": 0.8, "vi_sao": "..."}
```

`chac`: 0–1. `vi_sao`: tiếng Việt, tối đa 4 câu, nêu vì sao chọn và vì sao bỏ
nguồn nào.
