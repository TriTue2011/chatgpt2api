# Máy GPU — stack phụ của c2a (nghe + dịch theo lô)

Hai dịch vụ dùng chung một card NVIDIA, chạy **ngoài** stack c2a; gateway ở máy
khác gọi sang qua LAN. Ở nhà: máy NVR `172.16.10.220`, RTX 2060 Super 8 GB.

| Dịch vụ | Cổng | Việc | Tài liệu riêng |
|---|---|---|---|
| `fw-nghe` | 5002 | Nghe phụ đề bằng faster-whisper large-v3 | [`fw-nghe/README.md`](../../fw-nghe/README.md), [`docs/NGHE_GPU.md`](../../docs/NGHE_GPU.md) |
| `vn-translate-gpu` | 5001 | Dịch theo **lô** (phụ đề phim, tài liệu dài) | [`vn-translate/README.md`](../../vn-translate/README.md), [`docs/DICH_MAY_TU_CHU.md`](../../docs/DICH_MAY_TU_CHU.md) |
| `fw-vision` | 5003 | Qwen3-VL 2B Q4, 1–2 frame/cảnh | phần bên dưới |

Cả hai đều là **tuỳ chọn**: không dựng máy này thì bot vẫn nghe và vẫn dịch, chỉ
là bằng model tại chỗ trên máy c2a.

## Cần sẵn trên máy

Driver NVIDIA + `nvidia-container-toolkit` — compose không cài hộ được. Kiểm
nhanh: `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`
ra được bảng là đủ điều kiện.

Card cần compute capability ≥ 7.0 để chạy `float16` (2060S = 7.5). Card cũ hơn
(GTX 10xx, CC 6.1) phải đổi `FW_COMPUTE` sang `int8` và `TT_KIEU_TINH` sang
`int8` trong compose.

## Chạy

```bash
cd deploy/gpu-box
docker compose up -d
curl -s http://127.0.0.1:5002/health    # nghe:  {"status":"ok","model":"large-v3",…}
curl -s http://127.0.0.1:5001/health    # dịch:  {"status":"ok"}
```

Vision là profile riêng, chỉ bật sau khi kiểm VRAM Frigate:

```bash
docker compose --profile vision up -d
curl -s http://127.0.0.1:5003/health
```

Runtime dùng đúng GGUF Q4 chính thức của Qwen và `llama-server`: Qwen công bố
model tương thích llama.cpp/CUDA, còn llama.cpp nhận ảnh qua API
`/v1/chat/completions` và có `--sleep-idle-seconds` để tự unload model khi rảnh.
Xem [Qwen3-VL 2B GGUF](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF),
[multimodal llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md)
và [sleeping on idle](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#sleeping-on-idle).

Không build gì — hai image lấy từ ghcr. Lần đầu `fw-nghe` còn tải model
large-v3 (~3 GB) vào volume `fw-nghe-data` rồi mới mở cổng, nên `/health` có thể
im vài phút; `docker compose logs -f fw-nghe` xem tiến độ.

**Cập nhật**: máy này không có watchtower (khác stack c2a) —
`docker compose pull && docker compose up -d`.

## Dựng bằng Portainer (cách đang dùng ở nhà)

Stacks → **Add stack** → **Repository**:

| Ô | Điền |
|---|---|
| Repository URL | `https://github.com/TriTue2011/chatgpt2api` |
| Reference | `refs/heads/main` |
| Compose path | `deploy/gpu-box/docker-compose.yml` |

Repo công khai nên không cần khai thông tin đăng nhập, và hai image trên ghcr
cũng kéo được ẩn danh — không phải `docker login`.

**Muốn bật Qwen3-VL thì phải thêm biến môi trường của stack:**

```
COMPOSE_PROFILES=vision
```

Portainer không có nút `--profile`. Nó ghi biến môi trường của stack ra `.env`
cạnh file compose, mà `docker compose` đọc `COMPOSE_PROFILES` từ đúng file đó —
đã kiểm bằng `docker compose config --services`: không có biến thì ra hai dịch
vụ, có biến thì ra ba (thêm `fw-vision`). Không đặt biến này thì stack vẫn chạy
bình thường, chỉ là không có vision.

Khi Update stack nhớ bật **Re-pull image**: image gắn thẻ `:latest`, không bật
thì Portainer dùng lại bản đã có trong máy.

Endpoint phải trỏ đúng máy có card. Phần cấp GPU nằm ở khối `deploy.resources`
trong compose — đó là thứ có tác dụng khi triển khai bằng stack.

## Khai ở gateway

Trong Portainer → Stacks → env của service `c2a`:

```
NGHE_URL_GPU=http://172.16.10.220:5002
TRANSLATE_URL_LO=http://172.16.10.220:5001
VISION_URL_GPU=http://172.16.10.220:5003
# fw-nghe /health trả nvidia-smi để gateway tránh khởi động Qwen lúc Frigate bận
VISION_GPU_STATUS_URL=http://172.16.10.220:5002
```

Chỉ cần **Update stack** (container c2a khởi động lại vài giây), *không* cần
build lại image c2a — đây là biến môi trường, không phải code.

Sau khi bật, tin báo phụ đề của bot sẽ ghi rõ nguồn nghe: `• Whisper GPU`,
`• STT local`, hay `• STT local (GPU lỗi)`. Vision chạy được sẽ thêm
`• Qwen3-VL GPU (N cảnh)`; Qwen lỗi/OOM/Frigate thiếu VRAM thì SRT vẫn xuất,
kèm cảnh báo chất lượng.

Mặc định chỉ **`en` và `ko`** đi máy nghe GPU — đúng hai tiếng mà model tại chỗ
bỏ trắng đoạn (đo FLEURS 14/08: en 7%, ko 45%); tiếng Việt giữ tại chỗ. Máy dịch
GPU chỉ nhận **lô đủ lớn**; câu lẻ vẫn đi bản CPU vì GPU thua CPU ở câu lẻ.

## Tắt máy này thì sao

Không đứt gì cả — đó là điều kiện thiết kế:

- Máy nghe lỗi → rơi ngay về model STT tại chỗ, phụ đề vẫn ra.
- Máy dịch lỗi → rơi về bản CPU trong stack c2a.
- Cả hai đều có **cầu dao nghỉ 5 phút**: máy treo mà không tắt hẳn thì mỗi lượt
  gọi phải chờ trọn timeout, một phim chia trăm lượt là cộng dồn hàng giờ.

Muốn tắt hẳn: xoá hai biến môi trường ở trên rồi Update stack.

## Chia card với thứ khác

Đo trên máy NVR 15/08/2026, lúc chỉ có Frigate chạy:

```
gpu 6,0% · dec 1,0% · enc 0% · mem 44,42%
detectors: coral1, coral2 (9,1 ms/lượt)
```

Frigate nhận diện vật thể bằng **hai thanh Coral TPU**, GPU chỉ dùng để giải mã
luồng camera — nên nó gần như không tranh sức tính toán với hai dịch vụ ở đây.
Sức ép thật nằm ở **VRAM**. Gateway dùng một hàng đợi file-lock chung cho
Whisper, Qwen và dịch GPU; Whisper có `/unload` sau mỗi tệp, còn `fw-vision`
được llama.cpp tự unload sau 2 giây rảnh. Trước khi gọi Qwen, gateway đọc
`/health` của fw-nghe và bỏ vision nếu VRAM trống dưới `VISION_MIN_FREE_MB`
(mặc định 3500 MB). Frigate không tham gia hàng đợi, nên check này là chốt bảo
vệ thứ hai; không đủ VRAM thì giảm chất lượng, không làm mất SRT.

Qwen mặc định là model chính thức `Qwen/Qwen3-VL-2B-Instruct-GGUF:Q4_K_M`.
Không đổi sang 4B cho đến khi benchmark thực tế còn ít nhất 3.5 GB VRAM trống
trong lúc Frigate đang hoạt động.

`fw-nghe` cố ý chỉ giải mã **một request một lúc**: quá tải VRAM là CUDA OOM,
chết cả tiến trình chứ không phải hỏng một lượt.

## Image

`ghcr.io/tritue2011/fw-nghe` và `ghcr.io/tritue2011/vn-translate-gpu`, dựng bởi
[`fw-nghe-build.yml`](../../.github/workflows/fw-nghe-build.yml) và
[`translate-build.yml`](../../.github/workflows/translate-build.yml) mỗi khi
`fw-nghe/**` hoặc `vn-translate/**` đổi trên `main`.

Lần publish đầu tiên phải vào **Packages → đổi visibility sang Public**; để
private thì máy này phải `docker login ghcr.io` mới pull được.
