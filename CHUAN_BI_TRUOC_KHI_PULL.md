# Chuẩn bị trước khi tải image về

Tài liệu này trả lời đúng một câu hỏi: **máy của tôi cần có sẵn những gì trước khi
gõ `docker pull`?** Các bước cấu hình và sử dụng nằm ở [HUONG_DAN.md](HUONG_DAN.md).

Đọc mục 1 và 2 là đủ để chạy. Mục 3 trở đi chỉ cần khi bạn dùng tới giọng nói,
GPU, hoặc gặp trục trặc.

---

## 1. Máy chủ cần có gì

| Thứ | Mức tối thiểu | Ghi chú |
|---|---|---|
| Docker Engine | 20.10 trở lên | Kèm plugin `docker compose` (v2). Bản Docker Desktop cũng được |
| Kiến trúc CPU | x86-64 (amd64) hoặc ARM64 | Image có sẵn cả hai. Xem mục 5 để biết khác nhau chỗ nào |
| RAM | 2 GB để chạy API; 4 GB nếu bật giọng nói | Dưới 2 GB thì trình duyệt tự động hoá sẽ bị hệ điều hành giết |
| Đĩa trống | **12 GB** | Xem bảng phân tách ngay dưới |
| Kết nối Internet | có | Image kéo từ `ghcr.io`, model giọng nói kéo từ GitHub/HuggingFace |

### Đĩa trống 12 GB là gồm những gì

| Khoản | Cần bao nhiêu | Bắt buộc? |
|---|---|---|
| Image sau khi giải nén | **5,7 GB** (tải về qua mạng: 1,4 GB) | ✅ |
| Thư mục dữ liệu (`/app/data`) khi mới chạy | dưới 500 MB | ✅ |
| Model giọng nói tiếng Việt (đọc + nghe) | khoảng 2 GB | ❌ chỉ khi bật giọng nói |
| Model các tiếng khác (Anh, Trung, Nhật, Hàn) | mỗi tiếng 0,5–1,5 GB | ❌ |
| Chỗ thở cho log, ảnh, hồ sơ trình duyệt | 2–3 GB | nên có |

Con số image đo trên bản dựng thật ngày 24/08/2026 (`docker images`). Mạng
truyền bản nén 1,4 GB, nhưng đĩa phải đủ chỗ cho 5,7 GB sau khi giải nén — đó
mới là thứ `docker images` báo và là thứ chiếm đĩa.

> Bản trước ngày này nặng 10,8 GB giải nén / 2,71 GB tải về. Nếu bạn đang thấy
> hơn 10 GB thì đó là image cũ; kéo lại `:latest` là xuống còn một nửa.

**Thư mục dữ liệu phình theo thời gian.** Nó giữ tài khoản, cấu hình, cơ sở tri
thức, hồ sơ đăng nhập trình duyệt và toàn bộ model giọng nói bạn tải về. Đây mới
là thứ chiếm đĩa về lâu dài, không phải image.

---

## 2. Cài Docker trên nền tảng của bạn

### 2a. Linux thường (Ubuntu, Debian, Raspberry Pi OS)

```bash
curl -fsSL https://get.docker.com | sh      # cài Docker Engine + compose plugin
sudo usermod -aG docker "$USER"             # để không phải gõ sudo; đăng xuất rồi vào lại
docker compose version                      # phải in ra "Docker Compose version v2..."
```

Nếu `docker compose version` báo không tìm thấy lệnh, bạn đang có bản Docker cũ
chỉ kèm `docker-compose` (dấu gạch nối). Cài thêm plugin:
`sudo apt install docker-compose-plugin`.

### 2b. Portainer (bảng điều khiển web)

Portainer **không thay thế** Docker — nó là giao diện chạy trên nền Docker, nên
bạn vẫn phải cài Docker ở mục 2a trước. Cách dựng Portainer và tạo Stack đã có
đầy đủ ở [HUONG_DAN.md mục 1.3](HUONG_DAN.md).

Hai điều dễ vấp khi dùng Portainer:

- Portainer không có mã nguồn để build. Trong Stack phải dùng
  `image: ghcr.io/tritue2011/chatgpt2api:latest`, đừng dùng khối `build:`.
- Khi cập nhật, **bật "Re-pull image"** lúc bấm Update the stack. Không bật thì
  Portainer dựng lại container bằng đúng image cũ và bạn sẽ tưởng bản vá không
  ăn.

### 2c. NAS

Image chạy được trên NAS, nhưng NAS là nơi hay thiếu RAM và thiếu đĩa nhất, nên
kiểm tra bảng ở mục 1 trước khi bắt đầu.

| Hãng | Ứng dụng cần cài | Lưu ý |
|---|---|---|
| Synology | **Container Manager** (DSM 7.2 trở lên; DSM cũ gọi là **Docker**) | Vào Package Center cài. Container Manager có sẵn phần "Project" để dán `docker-compose.yml` |
| QNAP | **Container Station** | Cài từ App Center. Phần "Applications" nhận file compose |
| TrueNAS SCALE | Docker có sẵn | Dùng **Apps → Discover → Custom App**, hoặc chạy compose qua shell |
| Unraid | Plugin **Community Applications** + tab **Docker** | Thêm container thủ công, hoặc dùng plugin Compose Manager |

Ba điều cần chuẩn bị riêng cho NAS:

1. **Tạo sẵn thư mục dữ liệu** trên một share có nhiều chỗ trống, ví dụ
   `/volume1/docker/c2a-data` (Synology) hay `/share/Container/c2a-data` (QNAP),
   rồi trỏ volume vào đó. Đừng để nó nằm trên phân vùng hệ thống của NAS.
2. **Kiểm tra RAM thật sự còn trống.** NAS đời rẻ thường chỉ có 2 GB và đã dùng
   quá nửa cho dịch vụ của hãng.
3. **Đừng mở cổng 6080 ra Internet.** Đó là màn hình trình duyệt điều khiển từ
   xa; nếu NAS của bạn đang mở cổng ra ngoài thì phải đặt `VNC_PASSWORD`.

---

## 3. Những thứ KHÔNG nằm trong image

Đây là phần hay gây hiểu nhầm nhất: image cố tình **không** đóng gói model giọng
nói, vì mỗi thứ tiếng nặng thêm cả gigabyte và phần lớn người dùng chỉ cần một
hai tiếng. Chạy container xong, giọng nói vẫn im cho tới khi bạn tải model về.

Tải bằng cách chạy script **bên trong container** (đường ngắn nhất):

```bash
# Đọc + nghe tiếng Việt — đủ để dùng ngay
docker exec -it c2a /app/.venv/bin/python scripts/download_piper_voices.py --pack minimal
docker exec -it c2a /app/.venv/bin/python scripts/download_stt_model.py

# Tuỳ chọn: giọng chất lượng cao hơn, và các tiếng khác
docker exec -it c2a /app/.venv/bin/python scripts/download_vieneu_model.py
docker exec -it c2a /app/.venv/bin/python scripts/download_stt_en_model.py
docker exec -it c2a /app/.venv/bin/python scripts/download_tts_da_ngu.py
docker exec -it c2a /app/.venv/bin/python scripts/download_stt_da_ngu.py
```

> Gõ đủ đường dẫn `/app/.venv/bin/python`, đừng gõ tắt `python`. Trong container
> có hai bản Python: bản hệ thống (`/usr/local/bin/python`, là thứ `python` trỏ
> tới) và bản của ứng dụng ở `/app/.venv` — chỉ bản sau mới có `huggingface_hub`.
> Gõ tắt thì `download_vieneu_model.py` sẽ đổ `ModuleNotFoundError: huggingface_hub`.

Model rơi vào thư mục dữ liệu đã gắn (`/app/data`), nên nó **sống qua mọi lần cập
nhật image** — tải một lần là xong. Chi tiết từng giọng, từng cổng Wyoming cho
Home Assistant nằm ở [HUONG_DAN.md mục 4](HUONG_DAN.md).

Ngoài model, image cũng không kèm: tài khoản AI (bạn tự đăng nhập trong giao
diện), chứng chỉ HTTPS (dùng Cloudflare Tunnel nếu cần), và PostgreSQL (mặc định
lưu bằng JSON, chỉ cần Postgres khi đổi `STORAGE_BACKEND`).

---

## 4. Nếu bạn dùng GPU

Image thường **không** chứa PyTorch/CUDA — đó là gần 6 GB mà đa số người dùng
không đụng tới. Bản GPU là một tag riêng:

```bash
docker pull ghcr.io/tritue2011/chatgpt2api:gpu
```

Máy chủ phải chuẩn bị thêm, theo đúng thứ tự:

1. Driver NVIDIA cho Linux (kiểm tra bằng `nvidia-smi`).
2. `nvidia-container-toolkit` — cầu nối cho Docker thấy card.
3. Thêm `gpus: all` vào phần dịch vụ trong `docker-compose.yml`.

Bản GPU chỉ có cho amd64 và nặng hơn bản thường rất nhiều. Không có card thì
đừng kéo nó về.

---

## 5. Khác nhau giữa bản amd64 và bản ARM64

Cùng một tag `latest` phục vụ cả hai kiến trúc, Docker tự chọn đúng bản. Khác
biệt duy nhất đáng kể nằm ở trình duyệt tự động hoá: bản amd64 dùng Google
Chrome thật, bản ARM64 dùng Chromium của Debian (Google không phát hành Chrome
cho ARM Linux). Việc đăng nhập web tự động vẫn chạy trên cả hai, nhưng vài trang
siết chống bot có thể khó hơn một chút trên ARM64.

---

## 6. Vài thứ đã được gỡ khỏi image để nhẹ hơn

Từ bản dựng ngày 24/08/2026, ba thứ dưới đây không còn nằm sẵn trong image. Gần
như chắc chắn bạn không cần chúng — ghi ra đây để nếu có cần thì biết đường lấy
lại.

**Trình duyệt Firefox tự động hoá.** Trước đây image tải sẵn cả Firefox lẫn hai
bản Chromium riêng. Nay chỉ giữ CloakBrowser (đường chính, vượt Cloudflare) và
Chrome/Chromium hệ thống. Nếu Google chặn đăng nhập và bạn muốn thử qua Firefox:

```bash
docker exec c2a /app/.venv/bin/patchright install firefox
# rồi đặt CAPTCHA_SOLVER_BROWSER=firefox trong compose và khởi động lại
```

Lưu ý bản Firefox tải theo cách này nằm trong lớp ghi của container, nên **mất
sau mỗi lần cập nhật image** — phải cài lại.

**Bộ phông chữ Trung – Nhật – Hàn.** Ảnh chụp màn hình trang web tiếng Việt và
tiếng Anh hiển thị bình thường; chỉ khi chụp trang chữ Hán/Kana/Hangul mới thấy
ô vuông trống. Cần thì cài thêm trong container:
`apt-get update && apt-get install -y fonts-noto-cjk` (cũng mất sau khi cập nhật
image — nếu dùng thường xuyên thì nên thêm hẳn vào `Dockerfile`).

**Thư viện `ddddocr`.** Không còn được gọi ở bất kỳ đâu trong mã nguồn; captcha
ảnh đang giải bằng đường khác.

---

## 7. Kiểm tra sau khi chạy

```bash
docker compose ps            # cột STATUS phải là "Up ... (healthy)"
curl http://localhost:3030/version
```

Cổng đang dùng: `3030` giao diện + API, `6080` màn hình trình duyệt (noVNC),
`3001` máy chủ Zalo, `10600-10604` đọc và `10700-10704` nghe cho Home Assistant.

Nếu container lên rồi tắt ngay, xem log trước khi làm gì khác:
`docker compose logs c2a | tail -50`.
