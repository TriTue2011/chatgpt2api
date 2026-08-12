# vn-translate — máy dịch tự chủ, thuật ngữ chuyên ngành

Máy dịch chạy trong Docker của chính bạn: **không LLM, không token, không bên
thứ ba**. API **giống LibreTranslate** nên client nào nói chuyện được với
LibreTranslate là dùng được ngay — với gateway chatgpt2api chỉ cần đổi
`TRANSLATE_URL`.

## Hơn LibreTranslate/Argos ở đâu (đo thật 12/08/2026, CPU)

| | Argos (LibreTranslate) | vn-translate (NLLB-200) |
|---|---|---|
| "Hôm nay Hà Nội thời tiết thế nào ạ?" → en | "How are the weather today?" — **mất "Hà Nội"** | "How's the weather in Hanoi today?" |
| vi→ja/ko/zh | bắc cầu 2 lần qua tiếng Anh | dịch **thẳng** một lượt |
| Thuật ngữ "circuit breaker" | dịch bậy theo nghĩa phổ thông | **"áp-tô-mát"** — tra bảng, đúng 100% |
| Model | 8 gói, 756 MB cho 5 thứ tiếng | 1 model ~600 MB, 200 ngôn ngữ |
| Tốc độ câu ngắn | ~0,3–1s | ~0,5s |

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
# lần đầu tải model ~600 MB vào volume; /health sống ngay, /translate sẵn sàng sau vài phút
curl -s -X POST http://127.0.0.1:5000/translate -H 'Content-Type: application/json' \
  -d '{"q":"xin chào","source":"vi","target":"en"}'
```

Biến môi trường: `TT_LANGS` (mặc định `en,vi,ja,ko,zh-Hans` — thêm mã có trong
`app/engine.py::ISO2FLORES` là xong, không tải thêm gì), `TT_MODELS`,
`TT_THREADS`, `TT_GLOSSARY=0` để tắt tầng thuật ngữ.

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

Giấy phép model NLLB: CC-BY-NC-4.0 — dùng cá nhân/nội bộ, không bán dịch vụ dịch.
