# fw-nghe — máy NGHE chạy GPU cho phụ đề (faster-whisper large-v3)

Dịch vụ HTTP nhỏ đặt trước `faster-whisper`, trả **mốc thời gian từng từ** +
`avg_logprob`, nên gateway dùng lại được nguyên bộ gom khung có sẵn
(`services/video_asr.py::gom_khung`) — không có bộ cắt khung thứ hai để hai
đường lệch nhau.

**Vì sao có nó bên cạnh model nghe tại chỗ**: đo trên bộ FLEURS (150 bản thu mỗi
tiếng, 14/08/2026), model tại chỗ **bỏ trắng 7% đoạn tiếng Anh và 45% đoạn tiếng
Hàn** — không trả chữ nào mà cũng không báo lỗi, nên phụ đề mất dòng một cách im
lặng. Số đo đầy đủ và cách đo lại: [`docs/NGHE_GPU.md`](../docs/NGHE_GPU.md).

## Chạy

Cần một máy trong LAN có card NVIDIA (ở nhà: máy NVR `172.16.10.220`, RTX 2060
Super 8 GB) và `nvidia-container-toolkit`.

Image dựng sẵn trên ghcr, **không phải build gì** — cách này dựng luôn cả máy
dịch GPU cùng lúc:

```bash
cd deploy/gpu-box
docker compose up -d
curl -s http://<ip-máy-gpu>:5002/health
```

Đang sửa `app.py` thì build từ nguồn bằng compose trong chính thư mục này:

```bash
cd fw-nghe && docker compose up -d --build
```

Hoặc bằng tay, không cần compose:

```bash
docker build -t fw-nghe .
docker run -d --name fw-nghe --restart unless-stopped --gpus all \
    -p 5002:5000 -v fw-nghe-data:/data fw-nghe
```

Model large-v3 (~3 GB, `Systran/faster-whisper-large-v3` trên Hugging Face, giấy
phép MIT) tải lần đầu vào volume `fw-nghe-data`; lần sau khởi động nhanh. Compose
đã khai đúng tên volume đó nên chuyển từ `docker run` sang compose **không phải
tải lại**.

**Cập nhật**: máy này *không có watchtower* (khác stack c2a). Chạy bằng image
sẵn thì lên bản mới là `docker compose pull && docker compose up -d`; đang build
từ nguồn thì `docker compose up -d --build`. Không có gì tự kéo về.

## Biến môi trường

| Biến | Mặc định | Ghi chú |
|---|---|---|
| `FW_MODEL` | `large-v3` | Tên model faster-whisper. Card yếu hơn có thể dùng `medium`. |
| `FW_COMPUTE` | `int8_float16` | Cần compute capability ≥ 7.0 (2060S = 7.5). Card CC 6.1 (GTX 10xx) phải đổi thành `int8`. |

## API

### `GET /health`

```json
{"status":"ok","model":"large-v3","compute":"int8_float16",
 "gpu":{"nhiet_do_c":63.0,"tai_pct":97.0,"vram_dung_mb":5893.0,
        "vram_tong_mb":8192.0,"dien_w":112.3}}
```

Khối `gpu` đọc bằng `nvidia-smi` — nhìn được nhiệt độ card từ máy khác trong lúc
chạy phép đo dài. Cần thật: card 8 GB này còn gánh camera Frigate, nóng tới
ngưỡng thì nó tự hạ xung và bảng kết quả vẫn ra số bình thường như thể không có
gì. Máy không có `nvidia-smi` thì khoá này là `null`, `/health` vẫn chạy.

### `POST /nghe` (multipart)

| Tham số | Kiểu | Mặc định | Ghi chú |
|---|---|---|---|
| `tep` | file | — | Tệp âm thanh/video. |
| `lang` | chữ | `""` (tự dò) | Mã ISO, vd `en`, `ko`. |
| `batch` | số | `8` | **Xem cảnh báo bên dưới.** `≤1` = đường thường, ít VRAM nhất. |

```bash
curl -s -F "tep=@doan.wav" -F "lang=en" -F "batch=2" \
     http://172.16.10.220:5002/nghe
```

```json
{"lang":"en","xac_suat_lang":0.99,"dai_giay":612.5,"giay_xu_ly":41.2,
 "doan":[{"bat_dau":0.0,"ket_thuc":2.4,"chu":"Hello, Elsa.","tu_tin":-0.21,
          "tu":[{"t":0.0,"k":0.42,"chu":"Hello","p":0.98}]}]}
```

> ⚠️ **`batch` mặc định là 8, nhưng 8 và 4 đều CUDA OOM trên 2060S với video 10
> phút.** Gọi tay thì truyền `batch=2`. Gateway không bao giờ dính vì luôn gửi
> `BATCH = 2` (xem `services/nghe_gpu.py`), `scripts/kiem_nghe.py` cũng vậy —
> nhưng client mới mà quên tham số này sẽ đâm thẳng vào OOM.

Dịch vụ chỉ giải mã **một request một lúc** (khoá trong `app.py`): card 8 GB còn
phải chia cho camera và máy dịch, quá tải VRAM là cả tiến trình chết chứ không
phải chỉ hỏng một lượt. Đừng gọi song song.

### `POST /unload`

Gateway gọi endpoint này ngay sau mỗi tệp phụ đề. Nó xoá Whisper khỏi tiến trình
và dọn cache CUDA nếu có, để Qwen3-VL hoặc máy dịch GPU nhận lượt kế tiếp trên
card 8 GB:

```json
{"status":"ok","loaded":false}
```

## Nối vào gateway

```yaml
# docker-compose.yml của stack c2a, service c2a
environment:
  NGHE_URL_GPU: http://172.16.10.220:5002
```

Hoặc đặt `voice.stt.gpu_url` trong config. Để trống = tắt hẳn, mọi việc nghe đi
model tại chỗ như cũ.

Mặc định chỉ **`en` và `ko`** đi GPU — đúng hai tiếng mà model tại chỗ bỏ trắng
đoạn; tiếng Việt giữ tại chỗ để việc thường ngày không phụ thuộc máy thứ hai.
Đổi qua `voice.stt.gpu_tieng`. Máy GPU lỗi thì rơi ngay về model tại chỗ và nghỉ
GPU 5 phút (cầu dao) — thêm GPU không bao giờ làm đứt phụ đề. Chi tiết đường lui
và cách đo lại: [`docs/NGHE_GPU.md`](../docs/NGHE_GPU.md).
