# Nghe phụ đề bằng máy GPU (faster-whisper) — kèm đường lui

## Vì sao có đường này

Model nghe tại chỗ (sherpa-onnx Zipformer/Parakeet) chạy tốt cho tiếng Việt,
nhưng đo trên bộ tiếng người **FLEURS** ngày 14/08/2026 (150 bản thu mỗi tiếng)
thì nó **bỏ trắng cả đoạn** ở hai tiếng:

| Tiếng | Sai từ | Sai ký tự | Bỏ trắng, không trả chữ nào |
|---|---|---|---|
| Việt | 9,3% | 6,5% | 0 |
| Anh | 16,6% | 15,0% | **11/150 — 7%** |
| Trung | — | 13,6% | 0 |
| Nhật | — | 9,8% | 0 |
| Hàn | — | 55,5% | **67/150 — 45%** |

Chỗ nguy là **bỏ trắng không kèm lỗi**: bộ nghe trả về rỗng, đường phụ đề coi như
đoạn đó không có tiếng, và phim thiếu dòng mà không ai biết. Sai chữ thì còn đọc
ra được là sai; mất dòng thì không.

Riêng con số 55,5% của tiếng Hàn là **lệch miền huấn luyện**, không phải model
hỏng — đã kiểm ba đường: model đọc đúng bộ thử của chính nó (3/4 câu khớp từng
chữ), cắt audio còn 10 giây vẫn trả rỗng (nên không phải giới hạn độ dài), và bản
fp32 cho kết quả **y hệt** bản int8 (nên không phải do lượng tử hoá). Nó học trên
KsponSpeech là tiếng nói hội thoại câu ngắn, còn bộ đo là giọng đọc bản tin câu
dài. Thoại phim gần miền huấn luyện hơn nên thực tế khá hơn số này.

## Dựng dịch vụ

Nguồn nằm ở [`fw-nghe/`](../fw-nghe) trong repo này. Cần một máy trong LAN có card
NVIDIA (ở nhà: máy NVR `172.16.10.220`, RTX 2060 Super 8 GB).

```bash
cd fw-nghe
docker build -t fw-nghe .
docker run -d --name fw-nghe --restart unless-stopped --gpus all \
    -p 5002:5000 -v fw-nghe-data:/data fw-nghe
curl -s http://<ip-máy-gpu>:5002/health     # {"status":"ok","model":"large-v3",...}
```

Model large-v3 (~3 GB) tải lần đầu vào volume `fw-nghe-data`, lần sau khởi động
nhanh. Card 8 GB còn phải gánh camera và máy dịch nên dịch vụ chỉ giải mã **một
request một lúc** và dùng lô 2 — đo trên 2060S thì lô 8 và lô 4 đều CUDA OOM với
video 10 phút.

## Bật ở phía gateway

```yaml
# docker-compose.yml, service c2a
environment:
  NGHE_URL_GPU: http://172.16.10.220:5002
```

Hoặc đặt `voice.stt.gpu_url` trong Cài đặt. Trống = tắt hẳn, mọi việc nghe đi
model tại chỗ như cũ.

**Tiếng nào sang GPU**: mặc định `en` và `ko` — đúng hai tiếng mà model tại chỗ bỏ
trắng đoạn. Tiếng Việt **giữ tại chỗ** vì nó đã tốt (9,3% sai từ, không bỏ trắng
bản nào) và việc thường ngày không nên phụ thuộc máy thứ hai. Đổi danh sách qua
`voice.stt.gpu_tieng`, ví dụ `"en,ko,ja"`.

## Đường lui — thêm GPU không bao giờ làm đứt phụ đề

Cùng nguyên tắc với máy dịch GPU:

- Máy GPU lỗi → rơi **ngay** về model tại chỗ, phụ đề vẫn ra.
- **Cầu dao**: lỗi một lần thì nghỉ GPU 5 phút. Bắt buộc phải có, không phải cho
  đẹp: máy GPU **treo mà không tắt hẳn** thì mỗi lượt gọi phải chờ trọn timeout
  mới rơi về đường tại chỗ, một phim chia trăm lượt là cộng dồn hàng giờ.
- Tệp không có tiếng nói thì **không** ngắt cầu dao — máy vẫn tốt, phạt nó 5 phút
  là oan.
- Nhận diện ngôn ngữ vẫn làm **tại chỗ** (rẻ và đang chạy đúng), chỉ phần nghe
  mới đi GPU.

Mốc thời gian từng chữ do faster-whisper trả về được đưa thẳng vào bộ cắt khung
sẵn có (`services/video_asr.py::gom_khung`), nên không có bộ cắt khung thứ hai để
hai đường lệch nhau.

## Đo lại

```bash
# Tải bộ FLEURS (một lần) — xem docstring scripts/kiem_nghe.py
docker exec c2a /app/.venv/bin/python /app/scripts/kiem_nghe.py vi en zh ja ko --so 150
docker exec c2a /app/.venv/bin/python /app/scripts/kiem_nghe.py vi en zh ja ko --so 150 \
    --gpu http://172.16.10.220:5002
```

Hai lệnh chạy trên **cùng** bản thu nên so được trực tiếp. Có `--gpu` thì đo
đường GPU, không có thì đo model tại chỗ.
