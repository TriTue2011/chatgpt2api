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

## Máy GPU nghe được bao nhiêu — đo trên ĐÚNG 150 bản thu đó

Cùng ngày 14/08/2026, chạy lại y bộ đo trên đường GPU (faster-whisper large-v3,
int8_float16, RTX 2060 Super). Hai cột đặt cạnh nhau nên so được trực tiếp:

| Tiếng | Sai từ tại chỗ | **Sai từ GPU** | Sai ký tự tại chỗ | **Sai ký tự GPU** | Bỏ trắng tại chỗ | **Bỏ trắng GPU** |
|---|---|---|---|---|---|---|
| Việt | 9,3% | **8,4%** | 6,5% | **5,0%** | 0 | **0** |
| Anh | 16,6% | **4,5%** | 15,0% | **2,7%** | 11/150 | **0** |
| Trung | — | — | 13,6% | **10,0%** | 0 | **0** |
| Nhật | — | — | 9,8% | **5,1%** | 0 | **0** |
| Hàn | — | — | 55,5% | **2,8%** | 67/150 | **0** |

Ba điều đọc ra được từ bảng:

- **Không bản thu nào bị bỏ trắng**, kể cả 67 bản tiếng Hàn mà model tại chỗ trả
  rỗng. Đây mới là lý do dựng đường GPU; tỉ lệ sai chỉ là phần thêm.
- **Tiếng Hàn 55,5% xuống 2,8%** xác nhận chẩn đoán lệch miền: cùng bản thu, một
  model khác nghe gần như trọn vẹn, nên bản thu không có gì khó bất thường.
- **Tiếng Việt gần như hoà** (9,3% so với 8,4% sai từ). Đây là căn cứ để tiếng
  Việt **giữ tại chỗ**: đổi sang GPU đổi lại chưa tới 1 điểm phần trăm, mà phải
  đánh cược việc thường ngày vào máy thứ hai.

Tiếng Trung và tiếng Nhật thì GPU khá hơn rõ (13,6% xuống 10,0%; 9,8% xuống
5,1%) nhưng tại chỗ **không bỏ trắng bản nào**, nên mặc định vẫn để tại chỗ. Ai
dịch nhiều phim Trung/Nhật và chấp nhận phụ thuộc máy GPU thì bật thêm bằng
`voice.stt.gpu_tieng = "en,ko,ja,zh"`.

## Cập nhật 15/08: phía tại chỗ đã khá lên nhiều, GPU vẫn giữ vai

Đổi model nghe tại chỗ của Trung/Nhật/Hàn sang **SenseVoice** (xem mục 4.2f của
`HUONG_DAN.md`) thì bảng trên đổi hẳn ý nghĩa ở tiếng Hàn:

| Tiếng | Tại chỗ trước | Tại chỗ nay | GPU |
|---|---|---|---|
| Hàn | 55,5% · bỏ trắng 67/150 | **6,2% · bỏ trắng 0** | 2,8% |
| Nhật | 9,8% | **7,0%** | 5,1% |
| Trung | 13,6% | **10,2%** | 10,0% |

Vì sao **vẫn giữ tiếng Hàn trong danh sách đi GPU**: 6,2% với 2,8% là hơn gấp
đôi số lỗi, và phim thì đáng dùng đường tốt hơn khi máy GPU đang bật. Nhưng lý
do có mặt của đường GPU đổi từ **"cứu bàn thua"** sang **"nâng chất"** — máy GPU
tắt thì phụ đề tiếng Hàn nay vẫn dùng được, chứ không mất 45% số dòng như trước.

Tiếng Anh thì chưa đổi (vẫn Parakeet, vẫn bỏ trắng 7%), nên với tiếng Anh đường
GPU vẫn đúng nghĩa cứu bàn thua.

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
nhanh.

Gọn hơn, và **không phải build gì**: `cd deploy/gpu-box && docker compose up -d`
— dựng cả máy nghe lẫn máy dịch GPU từ image trên ghcr, khai đúng tên volume
`fw-nghe-data` nên chuyển từ `docker run` sang không phải tải lại model. Xem
[`deploy/gpu-box/README.md`](../deploy/gpu-box/README.md). Hợp đồng API
(`/health`, `/nghe`, cảnh báo tham số `batch`) và hai biến `FW_MODEL` /
`FW_COMPUTE`: xem [`fw-nghe/README.md`](../fw-nghe/README.md).

`/health` khai luôn **nhiệt độ card**, để đứng từ máy khác cũng xem được trong
lúc chạy phép đo dài:

```bash
curl -s http://172.16.10.220:5002/health
# {"status":"ok","model":"large-v3","compute":"int8_float16",
#  "gpu":{"nhiet_do_c":63.0,"tai_pct":97.0,"vram_dung_mb":5893.0,…}}
```

Cần nhìn số này vì card 8 GB đó còn gánh camera Frigate: nóng tới ngưỡng thì nó
tự hạ xung, và bảng kết quả vẫn ra số bình thường như thể không có gì — hoá ra
đo card đang bị bóp chứ không phải đo model. `scripts/kiem_nghe.py` khi chạy
với `--gpu` sẽ in nhiệt độ mỗi 25 bản thu và cảnh báo từ 80°C.

Bản fw-nghe cũ chưa có khoá `gpu` thì mọi thứ vẫn chạy, chỉ là không có số —
dựng lại container để có (`docker build -t fw-nghe . && docker rm -f fw-nghe`
rồi chạy lại lệnh `docker run` ở trên). Card 8 GB còn phải gánh camera và máy dịch nên dịch vụ chỉ giải mã **một
request một lúc** và dùng lô 2 — đo trên 2060S thì lô 8 và lô 4 đều CUDA OOM với
video 10 phút. Gateway gọi `POST /unload` ngay sau mỗi lượt nghe, nên model
Whisper không giữ VRAM giữa hai video. Chạy request tuần tự mà giữ model thường
trú vẫn có thể OOM y như chạy đồng thời khi card còn phải nhận Qwen3-VL.

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
