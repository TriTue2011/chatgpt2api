# Kho thuật ngữ (glossary) cho dịch lồng tiếng

Đường dịch phụ đề/lồng tiếng gồm ba bước, cắm ở
[services/video_dich.py](../services/video_dich.py) trong `_dich_va_dong_goi`:

1. **NLLB** (CTranslate2) dịch thô từng câu.
2. **Hậu kỳ thay thuật ngữ** — tất định, KHÔNG LLM
   ([services/thuat_ngu.py](../services/thuat_ngu.py), hàm `hau_ky_glossary`):
   đoán lĩnh vực rồi thay thuật ngữ NLLB dịch sai/đời-thường bằng thuật ngữ VI
   chuẩn trong kho. Đây là thứ sửa lỗi *dùng từ không đúng chuyên ngành*.
3. **LLM chỉnh nghĩa + mượt câu** — TÙY CHỌN, **mặc định TẮT**
   ([services/dich_llm.py](../services/dich_llm.py)). Xem mục *Bước LLM* dưới.

Tại sao bước 2 xử lý phía đích: NLLB **không nhận glossary** (đã có tiền lệ hỏng
trong repo — `video_dich.py`, CTranslate2 #1798), nên phải thay chuỗi SAU dịch
bằng kho thuật ngữ dựng sẵn.

## Dữ liệu sinh ra

`data/glossary/<tiếng>.json` (tiếng = `en`/`ja`/`zh`/`ko`), dạng:

```json
{ "cong_nghe": { "cache": "bộ nhớ đệm", "algorithm": "thuật toán" },
  "y_khoa":   { "cell": "tế bào" } }
```

Ngoài bản **curated** `<tiếng>.json` còn có bản **tự học** `<tiếng>.hoc.json`
cùng dạng: thuật ngữ do bước LLM chắt lọc (xem mục *Bước LLM*). Khi đọc,
`thuat_ngu` GỘP hai file — **curated luôn thắng** khi trùng, bản học chỉ bổ sung
term chưa có. Có thể xem/tỉa `.hoc.json` bằng tay; nó cũng được commit vào repo.

Sinh bằng [scripts/build_glossary.py](../scripts/build_glossary.py). **Không tải
tệp nguồn vào repo** — chúng lớn (GB) và có giấy phép riêng; tải ngoài theo bảng
dưới rồi chạy trình nạp trên **server** (.38, nơi tải/chạy được).

## Nguồn tải NGOÀI (phải tự tải, không nằm trong repo)

| Nguồn | Cho | Tải ở | Giấy phép |
|---|---|---|---|
| **Wiktextract (kaikki, English Wiktionary)** | EN→VI + lĩnh vực (nguồn CHÍNH, và là cầu pivot) | https://kaikki.org/dictionary/English/ → tệp `kaikki.org-dictionary-English.jsonl(.gz)` | CC BY-SA (Wiktionary) |
| **CC-CEDICT** | ZH→EN (pivot ra VI qua glossary EN) | https://www.mdbg.net/chinese/dictionary?page=cc-cedict → `cedict_1_0_ts_utf-8_mdbg.txt(.gz)` | CC BY-SA 4.0 |
| **FreeDict `jpn-eng`** (TEI) | JA→EN (pivot) | https://download.freedict.org/dictionaries/jpn-eng/ → tệp `.tei` | GPL/khác (xem trong bản phát hành) |
| **OMW — Open Multilingual Wordnet** | JA/ZH/KO/VI gióng theo synset (KO + gia cố) | https://github.com/globalwordnet/OMW ; dữ liệu qua `pip install wn` → `python -m wn download omw` | Theo từng wordnet |

> Pivot: JA/ZH/KO không có termbase sang thẳng tiếng Việt, nên đi vòng qua tiếng
> Anh — term nguồn → nghĩa Anh → tra trong glossary EN ra (lĩnh vực, thuật ngữ
> VI). Chỉ term có nghĩa Anh TRÙNG một thuật ngữ EN đã biết mới vào, nên tự lọc
> còn đúng từ chuyên ngành.

### Nguồn bổ sung (tuỳ chọn — bước sau, coverage VI mỏng)

| Nguồn | Cho | Ở đâu | Ghi chú |
|---|---|---|---|
| **Apertium** | Từ điển song ngữ `.dix` nhiều cặp | https://github.com/apertium | Ít cặp gắn thẳng tiếng Việt; dùng cho chặng pivot (X↔EN) hoặc cặp có VI khi có. |
| **OPUS — Helsinki-NLP** | Kho SONG NGỮ căn câu (không phải từ điển) | https://github.com/Helsinki-NLP/OPUS-translator ; https://opus.nlpl.eu | Muốn thành glossary phải rút lexicon bằng word-alignment — nặng; hoặc dùng model Opus-MT như bộ dịch thay thế NLLB cho vài cặp. |

## Cách dựng (chạy trên server)

Dựng EN TRƯỚC (mọi pivot cần `en.json` làm cầu):

```bash
# 1) EN — nguồn chính. Thêm --noi-long để HẠ NGƯỠNG LỌC nhưng GIỮ CHÍNH XÁC:
#    chỉ nhận thêm CỤM NHIỀU TỪ đa lĩnh vực dịch không sense ('artificial
#    intelligence') — cụm dài gần như luôn là thuật ngữ thật. TỪ ĐƠN đa lĩnh
#    vực ('account', 'bear') nhập nhằng nặng nên VẪN BỎ (tránh thay 'tài khoản'
#    thành nghĩa đời thường). Kèm lọc rác 'no exact matching verb'.
python scripts/build_glossary.py \
    --kaikki-en kaikki.org-dictionary-English.jsonl.gz \
    --noi-long --out data/glossary

# 2) ZH — pivot qua en.json vừa dựng
python scripts/build_glossary.py \
    --cc-cedict cedict_1_0_ts_utf-8_mdbg.txt --out data/glossary

# 3) JA — pivot qua en.json
python scripts/build_glossary.py \
    --freedict-jpn jpn-eng.tei --out data/glossary

# 4) KO — OMW gióng synset nguồn↔VI, lĩnh vực theo từ VI. Chạy lần lượt cho
#    từng tiếng. Với ja/zh, OMW GỘP vào file pivot sẵn có (không ghi đè) → gia cố.
python scripts/build_glossary.py \
    --omw-src wn-data-kor.tab --omw-vi wn-data-vie.tab --omw-lang ko \
    --out data/glossary
# gia cố JA/ZH (chạy SAU bước 2/3, cần ja.json/zh.json đã có):
python scripts/build_glossary.py \
    --omw-src wn-data-jpn.tab --omw-vi wn-data-vie.tab --omw-lang ja --out data/glossary
python scripts/build_glossary.py \
    --omw-src wn-data-cmn.tab --omw-vi wn-data-vie.tab --omw-lang zh --out data/glossary
```

## Bước LLM (tùy chọn) + tự chắt lọc từ điển

Mặc định **TẮT** để giữ tự chủ (không gọi bên thứ ba). Bật ở **web UI → tab Dịch
→ hộp "Chỉnh nghĩa chuyên ngành bằng LLM"**: một công tắc + ô chọn model (list
lấy từ `/api/v1/available-models`, **gồm cả model cục bộ**). Lưu vào config:

```json
{ "dich_llm": { "bat": true, "model": "<model id>" } }
```

Backend ([services/dich_llm.py](../services/dich_llm.py), gọi từ
`video_dich._chinh_llm_neu_bat`):

- **Chỉnh**: sau hậu kỳ glossary, gửi từng lô câu (gốc + bản nháp) cho model,
  yêu cầu chỉnh đúng nghĩa-ngữ-cảnh + mượt, **giữ nguyên thuật ngữ đã chuẩn**.
  Lệch số dòng / model lỗi → **giữ nguyên bản nháp** (LLM chỉ được làm tốt hơn).
- **Tự học**: hỏi model liệt kê thuật ngữ (nguồn → VI) rồi ghi vào
  `<src>.hoc.json` (chỉ term CHƯA có ở curated/đã học). Lần sau bước 2 tất định
  lo được, LLM bớt việc → **tiến tới bỏ hẳn LLM**. Đặc biệt đáng dùng khi model
  là **online** (giảm phụ thuộc bên thứ ba); dùng model cục bộ vẫn học để sau
  này tắt cả LLM cục bộ cho nhanh.

> **Card GPU (2026-08-25)**: máy .220 là **RTX 2060 Super 8 GB**, đã xếp hàng
> chung cho Whisper/Qwen-VL/NLLB ([services/gpu_queue.py](../services/gpu_queue.py)).
> Chạy LLM **mỗi câu** trên card này sẽ tranh VRAM → chậm. Nếu bật, nên trỏ model
> nhẹ qua Ollama (.220:11434) và chấp nhận chậm, hoặc dùng model online. Để đúng
> lỗi thuật ngữ thì **bước 2 (glossary) đã đủ**, không cần bật LLM.

## Trạng thái (2026-08-25)

- **XONG — dữ liệu thật đã commit vào repo**: `data/glossary/{en,zh,ja}.json`
  (EN 305, ZH 1546, JA 2343 thuật ngữ / 20 lĩnh vực), dựng trên .38. Runtime
  KHÔNG tải lại bên thứ 3.
- **XONG — nối vào `video_dich`**: `NLLB → hậu kỳ glossary` cắm ở
  `services.video_dich.hau_ky_glossary`, chạy trong nhánh dịch-sang-`vi`. Đoán
  lĩnh vực một lần trên toàn transcript rồi thay thuật ngữ từng câu; hàm render
  là chính máy dịch, gọi đơn từng thuật ngữ + nhớ đệm (mỗi thuật ngữ dịch một
  lần cho cả phim). Test: `test/test_video_dich_glossary.py`.
- **XONG — bước LLM tùy chọn** (mặc định TẮT): công tắc + chọn model ở web UI
  tab Dịch; backend `services/dich_llm.py`, tự chắt lọc thuật ngữ vào
  `<src>.hoc.json`. Test: `test/test_dich_llm.py`. Xem mục *Bước LLM* trên.
- **XONG — nới trình nạp + dựng lại dữ liệu**: cờ `--noi-long` (chỉ nhận CỤM
  nhiều từ, giữ chính xác) + lọc rác + OMW gộp. Dữ liệu commit lại:
  **EN 377, ZH 1715, JA 2570** thuật ngữ (từ 305/1546/2343). Thử bản nới toàn bộ
  (từ đơn) cho ~2288/16691/25720 nhưng BỎ vì kéo từ sai nghĩa ('account→chuyện
  kể') — hại hơn lợi. Test bổ sung trong `test/test_build_glossary.py`.

## Còn thiếu (chạy trên SERVER, máy dev không làm được)

- **Chạy lại trình nạp với `--noi-long` + OMW (ko/ja/zh)** trên .38 để phủ rộng
  EN và thêm KO, rồi commit lại `data/glossary/*.json`. Kho làm việc để ở
  **`/opt`** (đã chuyển khỏi `/root`).
- **Test đầu-cuối thật** một video chuyên ngành: .38 điều phối, .220 NLLB (và
  LLM nếu bật) — đo hậu kỳ thay đúng chỗ, và nếu bật LLM thì xem `.hoc.json` có
  lớn dần không.

OMW dùng tệp `.tab` per-ngôn-ngữ (vie/kor/jpn/cmn); tải từ OMW / omwn.
