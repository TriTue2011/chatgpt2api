# Kho thuật ngữ (glossary) cho dịch lồng tiếng

Glossary giúp bước **hậu kỳ thay thuật ngữ** trong dịch phụ đề/lồng tiếng
([services/thuat_ngu.py](../services/thuat_ngu.py)): NLLB dịch thô → thay thuật
ngữ theo lĩnh vực cho đúng chuyên ngành → (bước sau) LLM chỉnh nghĩa + mượt.

Tại sao cần: NLLB **không nhận glossary** (đã có tiền lệ hỏng trong repo —
`video_dich.py`, CTranslate2 #1798), nên phải xử lý PHÍA ĐÍCH bằng kho thuật ngữ
dựng sẵn.

## Dữ liệu sinh ra

`data/glossary/<tiếng>.json` (tiếng = `en`/`ja`/`zh`/`ko`), dạng:

```json
{ "cong_nghe": { "cache": "bộ nhớ đệm", "algorithm": "thuật toán" },
  "y_khoa":   { "cell": "tế bào" } }
```

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
# 1) EN — nguồn chính
python scripts/build_glossary.py \
    --kaikki-en kaikki.org-dictionary-English.jsonl.gz \
    --out data/glossary

# 2) ZH — pivot qua en.json vừa dựng
python scripts/build_glossary.py \
    --cc-cedict cedict_1_0_ts_utf-8_mdbg.txt --out data/glossary

# 3) JA — pivot qua en.json
python scripts/build_glossary.py \
    --freedict-jpn jpn-eng.tei --out data/glossary

# 4) KO (và gia cố JA/ZH) — OMW gióng synset nguồn↔VI, lĩnh vực theo từ VI
python scripts/build_glossary.py \
    --omw-src wn-data-kor.tab --omw-vi wn-data-vie.tab --omw-lang ko \
    --out data/glossary
```

## Trạng thái (2026-08-25)

- **XONG — dữ liệu thật đã commit vào repo**: `data/glossary/{en,zh,ja}.json`
  (EN 305, ZH 1546, JA 2343 thuật ngữ / 20 lĩnh vực), dựng trên .38. Runtime
  KHÔNG tải lại bên thứ 3.
- **XONG — nối vào `video_dich`**: `NLLB → hậu kỳ glossary` cắm ở
  `services.video_dich.hau_ky_glossary`, chạy trong nhánh dịch-sang-`vi`. Đoán
  lĩnh vực một lần trên toàn transcript rồi thay thuật ngữ từng câu; hàm render
  là chính máy dịch, gọi đơn từng thuật ngữ + nhớ đệm (mỗi thuật ngữ dịch một
  lần cho cả phim). Test: `test/test_video_dich_glossary.py`.
- **KHÔNG làm bước LLM** — quyết định 2026-08-25: card GPU là **RTX 2060 Super
  8 GB** (máy NVR .220) và đã xếp hàng chung cho Whisper + Qwen-VL + NLLB
  (`services/gpu_queue.py`). Nhét LLM vào path lồng tiếng = chạy mỗi câu một
  lần, tranh 8 GB → chậm hơn nhiều, mà glossary hậu kỳ đã sửa đúng lỗi thuật
  ngữ. Khi có card to hơn mới cân nhắc, và nên chạy MỘT lượt gộp cả transcript
  qua Ollama (.220:11434) chứ không từng câu.

## Còn thiếu (bước sau)

- **Nới coverage EN** (đang mỏng — vài ngành < 10 term): thêm OMW/KO, hạ ngưỡng
  lọc, mở rộng bản đồ lĩnh vực trong trình nạp.
- **Test đầu-cuối thật** một video chuyên ngành trên server (.38 điều phối,
  .220 NLLB) để đo hậu kỳ thay đúng chỗ.

OMW dùng tệp `.tab` per-ngôn-ngữ (vie/kor/jpn/cmn); tải từ OMW / omwn.
