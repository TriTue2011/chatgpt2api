# Model phát hiện lửa / khói — `lua26n`

YOLO26n tinh chỉnh cho camera trong nhà. Huấn luyện một lần trên GPU máy .220 (đêm 27–28/09/2026,
3,4 giờ, 30 epoch) — cài chỗ khác thì lấy tệp ở đây, **không cần huấn luyện lại**.

| Tệp | Dùng khi | SHA-256 |
|---|---|---|
| `lua26n.onnx` | Chạy thật: end-to-end, đầu ra `(1, 300, 6)` — `services/yolo_nha.BoPhatHien` đọc thẳng | `92c42378e122958811da40851972a5b787a2eeba5a1e6763787b49c2aac0cd48` |
| `lua26n.pt` | Tinh chỉnh tiếp bằng ultralytics (không phải chạy lại từ đầu) | `9ed625aa4ef5cea5db2f7adba17603f59ca0b42b5d9183c382ffb084d6ddb6d4` |

Lớp: `0 = smoke`, `1 = fire` (giữ như D-Fire). Ảnh vào 640×640.

## Model chỉ ĐỀ XUẤT vùng

Quyết định báo cháy phải là tầng xác minh vật lý (màu, độ rực, nhấp nháy, cạnh), rẽ nhánh theo
**số đo** chứ không theo nhãn model: đo 27/09 bật lửa thật bị model cũ gắn nhãn `smoke`, nhánh khói
bác vì "quá rực" nên lửa không bao giờ được báo.

## Dữ liệu huấn luyện

- D-Fire (`badsaarow/d-fire` trên Hugging Face), phần train: 90% huấn luyện, 10% kiểm. Phần test
  để nguyên để chấm.
- Mẫu âm của nhà: khung ghi hình 4 camera, 2 giờ một khung, 28/08–20/09 (ảnh nền, không nhãn).
  Tuần 21–27/09 giữ riêng để chấm, không huấn luyện.

Tệp này chỉ chứa trọng số, không chứa ảnh.

## Số đo (đề xuất trúng = hộp bất kỳ lớp nào chạm hộp thật, IoU ≥ 0,1)

Chấm trên CPU máy chủ .38 (Xeon E5-2630L v4, 4 luồng), ngưỡng 0,15:

| | `lua26n` (mới) | rabahdev YOLOv8n | YOLO26-S (Roboflow) |
|---|---|---|---|
| D-Fire test — bắt lửa (1.115 ảnh) | **94,7%** | 93,9% | 72,4% |
| D-Fire test — bắt khói (1.186 ảnh) | 91,7% | 92,2% | 30,1% |
| D-Fire test — ảnh trống bị đề xuất nhầm (2.005) | **2,4%** | 2,7% | 14,9% |
| Khung nhà giữ lại 21–27/09 bị đề xuất nhầm (164) | **0/164** | 60/164 | 12/164 |
| Ảnh chụp camera nhà 27/09 tối bị đề xuất nhầm (37) | **0/37** | 21/37 | 0/37 |
| Thời gian / ảnh (trung vị) | **47 ms** | 68 ms | 139 ms |

Bộ khung nhà giữ lại đã **bỏ trước** những khung rabahdev thấy `fire` ≥ 0,3 (có thể là lửa bếp gas
thật), nên số nhầm của rabahdev ở dòng đó còn là số **thấp hơn** thực tế.

**Chưa đo:** lửa thật trước camera nhà. Chưa có clip nào; cần thử (lửa đặt trên bàn, không cầm tay)
trước khi tin.

## Giấy phép

Tinh chỉnh từ trọng số YOLO26 của Ultralytics → theo giấy phép của Ultralytics (AGPL-3.0).
