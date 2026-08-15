# vn-translate — máy dịch tự chủ, thuật ngữ chuyên ngành

Máy dịch chạy trong Docker của chính bạn: **không LLM, không token, không bên
thứ ba**. API **giống LibreTranslate** nên client nào nói chuyện được với
LibreTranslate là dùng được ngay — với gateway chatgpt2api chỉ cần đổi
`TRANSLATE_URL`.

## Hai máy dịch, chọn theo CẶP ngôn ngữ

| Cặp | Engine | Vì sao |
|---|---|---|
| **en↔vi** | **EnViT5** (VietAI, 275M, nhúng sẵn trong image) | Model chuyên một cặp thắng đậm model đa ngữ — số đo ở dưới |
| ja / ko / zh… | NLLB-200 (tải về volume lần đầu) | EnViT5 chỉ biết en và vi |

EnViT5 hỏng thì lượt đó tự rơi xuống NLLB, người dùng không thấy lỗi.

### Số đo FLORES-200 devtest (300 câu, CPU 4 nhân, 13/08/2026)

Đã chuẩn hoá NFC + thống nhất vị trí dấu thanh trước khi chấm — bỏ bước này
thì BLEU tụt từ 100 xuống 5,5 dù bản dịch giống hệt bản mẫu. chrF++ đáng tin
hơn BLEU với tiếng Việt vì không phụ thuộc cách tách từ.

| Hướng | Engine | BLEU | chrF++ | ms/câu |
|---|---|---|---|---|
| en→vi | NLLB-200-600M | 38,45 | 57,54 | 1255 |
| en→vi | **EnViT5** | **42,95** | **61,22** | **422** |
| en→vi | OPUS-MT tc-bible-big 2024 | 42,07 | 60,42 | 373 |
| vi→en | NLLB-200-600M | 36,32 | 59,59 | 1017 |
| vi→en | **EnViT5** | 38,44 | **62,36** | 376 |
| vi→en | OPUS-MT tc-bible-big 2024 | 38,78 | 62,35 | 302 |

Chữ ký chấm điểm: `chrF2++ nrefs:1|case:mixed|eff:yes|nc:6|nw:2|space:no|version:2.6.0`,
`BLEU nrefs:1|case:mixed|eff:no|tok:13a|smooth:exp|version:2.6.0`. Cả EnViT5 lẫn
OPUS-MT hơn NLLB có ý nghĩa thống kê (paired bootstrap, p ≤ 0,004). Giữa hai
model đó thì chênh lệch nằm trong sai số; chọn EnViT5 vì **một model chạy được
cả hai chiều** (OPUS-MT cần hai model, gấp đôi RAM và đĩa).

### So với LibreTranslate/Argos (đo 12/08/2026)

| | Argos (LibreTranslate) | vn-translate |
|---|---|---|
| "Hôm nay Hà Nội thời tiết thế nào ạ?" → en | "How are the weather today?" — **mất "Hà Nội"** | "How's the weather in Hanoi today?" |
| vi→ja/ko/zh | bắc cầu 2 lần qua tiếng Anh | dịch **thẳng** một lượt |
| Thuật ngữ "circuit breaker" | dịch bậy theo nghĩa phổ thông | **"áp-tô-mát"** — tra bảng, đúng 100% |
| Model | 8 gói, 756 MB cho 5 thứ tiếng | EnViT5 265 MB sẵn trong image + NLLB tải khi cần |

**Tầng thuật ngữ chuyên ngành**: 5 bảng mẫu (điện tử, y tế, xây dựng, CNTT,
pháp lý). Văn bản khớp ≥2 thuật ngữ của một ngành thì bảng ngành đó được áp;
thuật ngữ được dịch bằng **bảng tra, không bao giờ đưa cho engine đoán** (cơ chế
kiểu DeepL glossary). Phản hồi kèm trường `nganh`.

Thêm/đè thuật ngữ: bỏ file JSON vào volume `/data/glossary/<nganh>.json`:
```json
{"ten": "Y tế", "cap": [{"en": "sepsis", "vi": "nhiễm khuẩn huyết"}]}
```
(hiệu lực trong ≤5 phút, không cần khởi động lại). Nguồn nuôi bảng tốt: ICD-10
song ngữ Bộ Y tế (icd.kcb.vn), English-Vietnamese Legal Glossary (toà
Sacramento), corpus MTet/PhoMT.

**Tự chuyển model khi lỗi**: `TT_MODELS` là thang xếp hạng; model tải hỏng hoặc
dịch lỗi 2 lần liên tiếp thì tự nhảy sang model kế.

## Chạy

```bash
docker compose up -d          # trong thư mục vn-translate/
# en↔vi dịch được NGAY (EnViT5 nằm trong image); lần đầu dịch ja/ko/zh mới tải
# NLLB ~600 MB vào volume
curl -s -X POST http://127.0.0.1:5000/translate -H 'Content-Type: application/json' \
  -d '{"q":"xin chào","source":"vi","target":"en"}'
```

Biến môi trường: `TT_LANGS` (mặc định `en,vi,ja,ko,zh-Hans` — thêm mã có trong
`app/engine.py::ISO2FLORES` là xong, không tải thêm gì), `TT_MODELS` (thang model
NLLB), `TT_THREADS`, `TT_GLOSSARY=0` để tắt tầng thuật ngữ, `TT_ENVIT5_DIR=""`
để tắt EnViT5 và cho mọi cặp quay về NLLB, `TT_LO_MODEL` (lô đưa vào model mỗi
lượt decode — 16 trên CPU, 64 trên GPU).

## Bản GPU (tuỳ chọn) — cho việc theo LÔ

Đo thật 14/08 trên RTX 2060 Super, lô 120 câu en→vi qua đúng đường HTTP:
**CPU 54,4 giây · GPU 0,84 giây (~65 lần)**. Nhưng GPU **thua** CPU với câu lẻ
(overhead khởi động lô), nên gateway chạy **song song hai máy** và định tuyến
theo cỡ lô — xem `docs/DICH_MAY_TU_CHU.md` mục 2c.

Image dựng sẵn trên ghcr — **không phải build, không phải chép tay gì**:

```bash
# TRÊN MÁY CÓ CARD NVIDIA (không cần cùng máy với gateway)
cd deploy/gpu-box && docker compose up -d     # kèm luôn fw-nghe
```

Hoặc chỉ một container:

```bash
docker run -d --name vn-translate-gpu --gpus all --restart unless-stopped \
  -p 5001:5000 -v vn-translate-gpu-data:/data \
  -e TT_KIEU_TINH=float16 ghcr.io/tritue2011/vn-translate-gpu:latest
```

Rồi khai ở gateway: `TRANSLATE_URL_LO: http://<ip-máy-gpu>:5001`.

Build tay (khi sửa `app/`): `docker build -f Dockerfile.gpu -t vn-translate-gpu .`
— Dockerfile.gpu tự lấy EnViT5 đã convert từ image CPU trên ghcr, không cần
kéo torch 800 MB về máy GPU và cũng không còn bước `docker exec … tar` như bản
trước.

| Cần biết | Chi tiết |
|---|---|
| Nền image | CUDA 12.4 + cuDNN 9 (ctranslate2 ≥ 4.5 đòi đúng cặp này) |
| Card | Compute Capability ≥ 7.0 cho `float16` (2060S = 7.5); CC 6.1 chỉ int8 |
| VRAM | ~2 GB — chạy chung máy với camera/AI khác được |
| `TT_THIET_BI` | `cuda` (Dockerfile.gpu đặt sẵn) |
| `TT_KIEU_TINH` | `float16` nhanh nhất trên card này; `int8_float16` là mặc định của mã |
| Cập nhật | Máy đó **không có watchtower** — `docker compose pull && docker compose up -d` |

## Nối vào chatgpt2api

Trong compose của stack c2a, thay service `libretranslate` bằng:
```yaml
  vn-translate:
    image: ghcr.io/tritue2011/vn-translate:latest
    container_name: vn-translate
    restart: unless-stopped
    environment: {TT_LANGS: "en,vi,ja,ko,zh-Hans"}
    volumes: [vn_translate_data:/data]
```
và đổi biến của service c2a: `TRANSLATE_URL: http://vn-translate:5000`. Xong —
lệnh /dich, dịch tệp/ảnh của bot chạy như cũ, chất lượng mới. (`/translate_file`
chưa có ở v1: gateway tự rơi về đường trích-chữ, docx sẽ trả bản dịch dạng chữ/.docx
do gateway tự dựng.)

Giấy phép model: EnViT5 **OpenRAIL** (thương mại được, trừ danh sách mục đích bị
cấm); NLLB **CC-BY-NC-4.0** — cá nhân/nội bộ, không bán dịch vụ dịch. Muốn sạch
hoàn toàn về giấy phép thì tắt nhánh NLLB (`TT_LANGS="en,vi"`), khi đó chỉ còn
EnViT5.
