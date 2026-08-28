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
| **OMW — Open Multilingual Wordnet** | (⚠️ xem cảnh báo dưới — KHÔNG dùng được cho VI) | https://github.com/globalwordnet/OMW | Theo từng wordnet |

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
#
#    --chat BẮT BUỘC từ 28/08/2026 (xem "Vì sao --chat" bên dưới).
python scripts/build_glossary.py \
    --kaikki-en kaikki.org-dictionary-English.jsonl.gz \
    --chat --noi-long --out data/glossary

# 2) ZH — pivot qua en.json vừa dựng
python scripts/build_glossary.py \
    --cc-cedict cedict_1_0_ts_utf-8_mdbg.txt --out data/glossary

# 3) JA — pivot qua en.json
python scripts/build_glossary.py \
    --freedict-jpn jpn-eng.tei --out data/glossary

# 4) OMW / KO — ⚠️ KHÔNG KHẢ THI với dữ liệu công khai (đã dò 2026-08-25):
#    OMW (bản NLTK omw-1.4 lẫn chỉ mục `wn`) gồm 32 tiếng nhưng KHÔNG có
#    wordnet TIẾNG VIỆT lẫn TIẾNG HÀN → không gióng synset sang VI được, và
#    KO không có nguồn nào khác (FreeDict không có cặp kor, CC-CEDICT chỉ ZH,
#    Wiktextract chỉ EN). Code OMW (--omw-src/--omw-vi/--omw-lang) VẪN GIỮ và
#    có test — chạy được NGAY khi có `wn-data-vie.tab` + `wn-data-<src>.tab`.
#    Muốn thêm KO: cần một từ điển Hàn→Anh (pivot như JA) hoặc Hàn→Việt.
```

## Vì sao `--chat` (thêm 28/08/2026)

Kho dựng 25/08 **có dữ liệu phá bản dịch**. Lĩnh vực y khoa chứa `region → tỉnh`,
`purple → tía`, `failure → thất bại`, `terror → sự khiếp`; âm nhạc chứa
`kitchen → nhà bếp`. Hậu quả không phải là "thiếu thuật ngữ" mà là **dịch sai
thêm**: một video y tế nhắc "region" bị thay thành "tỉnh".

Cơ chế sinh ra chúng, đo trên kaikki 28/08:

| từ | topics của cả MỤC | sense của BẢN DỊCH | gloss khớp | topics của gloss đó |
|---|---|---|---|---|
| region | anatomy, medicine | "an administrative subdivision" | "An administrative subdivision of a city…" | *(rỗng)* |
| kitchen | entertainment, music | "room" | "A room or area for preparing food." | *(rỗng)* |
| neurosurgery | medicine, neurology, surgery | "surgical discipline focused on…" | "The surgical discipline focused on…" | medicine, neurology… |

Luật 2 cũ hỏi *"TỪ này có nghĩa nào thuộc chuyên ngành không?"* — mục "region"
có một nghĩa giải phẫu nên MỌI bản dịch trong mục, kể cả "tỉnh", bị gán vào y
khoa.

`--chat` hỏi đúng câu hỏi: *"NGHĨA này có thuộc chuyên ngành không?"* — ghép
chuỗi `sense` của bản dịch với `glosses` của từng nghĩa (theo số từ nội dung
trùng nhau), rồi lấy `topics` của đúng nghĩa khớp. Cùng một luật bỏ được
`region`/`kitchen` mà vẫn giữ `neurosurgery`. Không nghĩa nào trùng lấy một từ
thì bỏ, không đoán.

Từ đơn còn thêm một rào: phải có tín hiệu lĩnh vực ở sense bản dịch mới được
nhận. Cụm nhiều từ vẫn hưởng luật cũ vì cụm dài gần như luôn là thuật ngữ thật.

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

## Sửa thuật ngữ tay (web) — thắng cả từ điển gốc

Tab **Dịch** có hộp *"Sửa thuật ngữ dịch"*: chọn tiếng gốc + lĩnh vực, gõ
`từ gốc → từ Việt đúng`, Lưu. Ghi vào `<src>.sua.json`, **hiệu lực ngay lượt
dịch sau** (không phải dựng lại từ điển). API: `GET/POST /api/dich/glossary`,
`POST /api/dich/glossary/xoa`.

Ba tầng khi đọc glossary (`thuat_ngu.nap`): **curated `<src>.json`** (nền) <
**`<src>.hoc.json`** (LLM tự học, chỉ lấp chỗ trống) < **`<src>.sua.json`**
(người dùng sửa, ĐÈ tất cả). Sửa lỗi thì bản tay phải thắng.

Cạnh hộp đó có ô **tra từ điển** (Anh–Việt tại chỗ, xem [`TU_DIEN.md`](TU_DIEN.md)):
gõ một từ ra hết các nghĩa kèm IPA và ví dụ, bấm *Dùng nghĩa này* là đổ xuống
hai ô bên dưới để sửa cho gọn rồi Lưu. Nhật/Trung/Hàn chưa có từ điển tại chỗ —
bật Google Dịch thì ô này hỏi Google thay.

### Bản sửa tay chạy ở ĐÂU (sửa 28/08/2026)

Trước 28/08 nó **chỉ có tác dụng với phụ đề**, và ngay cả ở đó cũng phải đoán
được lĩnh vực (≥ `NGUONG_LINH_VUC` = 3 thuật ngữ cùng ngành) mới được áp. Hệ quả
đúng như báo lỗi thật: thêm `stroke → đột quỵ` rồi dán mỗi chữ "stroke" vào tab
Dịch, máy vẫn trả nghĩa phổ thông.

Nay thuật ngữ người dùng tự thêm được **CẮT khỏi câu trước khi gửi đi máy dịch**
rồi ghép lại sau (`translate_service._cat_thuat_ngu`, cùng cách DeepL glossary
làm) — máy dịch không nhìn thấy nó nên không thể đoán sai. Hai điểm quan trọng:

- **Không qua đoán lĩnh vực.** Tự tay thêm là đã nói rõ ý; không có lý do bắt
  chờ đủ 3 thuật ngữ cùng ngành.
- **Mọi lối vào đều ăn**: tab Dịch, `/dich` của bot, dịch tệp, dịch ảnh (qua
  `translate`), và **phụ đề + lồng tiếng** (qua `translate_giu_thuat_ngu`, gộp
  cả lô vào một lượt gọi để không mất lợi ích của máy dịch GPU).

Tầng hậu kỳ theo lĩnh vực (`hau_ky_thuat_ngu`) vẫn giữ nguyên cho thuật ngữ
CURATED — hai tầng không giẫm chân nhau: thuật ngữ tay đã được thay từ trước nên
bước hậu kỳ không còn gì để sửa.

## Triển khai lên server — DATA KHÔNG đi qua git

⚠️ `.dockerignore` loại `/data` khỏi image, và `/app/data` bị **bind-mount đè**
bởi volume host. Nên **commit `data/glossary/*.json` vào git KHÔNG deploy** tới
bot đang chạy. Đường thật:

- Bot c2a chạy trên **.38**, mount thật (theo `docker inspect c2a`, do Portainer
  quản, KHÁC git compose): **`/opt/c2a/data` → `/app/data`**.
- Runtime đọc `/app/data/glossary/*.json` = **host `/opt/c2a/data/glossary/`**.
- Deploy dữ liệu = **copy JSON vào `/opt/c2a/data/glossary/` trên .38** rồi
  `docker restart c2a` (tiến trình nhớ đệm glossary, phải restart để nạp lại).
- `<src>.hoc.json` (LLM học) và `<src>.sua.json` (người sửa) ghi thẳng vào
  `/app/data/glossary` = cùng volume → **bền qua cập nhật image**.

> Code (services/api/web) VẪN deploy qua image như thường (git push → build →
> watchtower). Chỉ DỮ LIỆU glossary mới cần copy tay vào volume.

## Trạng thái (2026-08-28) — dựng lại vì kho cũ PHÁ bản dịch

`data/glossary/{en,zh,ja}.json` = **EN 312, ZH 936, JA 1538** thuật ngữ / 21
lĩnh vực. Kho nhỏ đi so với bản 25/08 (377/1715/2570) và đó là **chủ đích**:
bản cũ chứa hàng trăm cặp làm bản dịch XẤU ĐI, không phải chỉ vô dụng.

Ba lớp lọc, theo đúng thứ tự:

1. **`--chat`** — lĩnh vực lấy từ đúng nghĩa bản dịch trỏ tới. Bỏ `region→tỉnh`,
   `purple→tía`, `failure→thất bại`, `kitchen→nhà bếp`, `house→nhà`, `tea→trà`,
   `police→cảnh sát`, `and→và`… (xem mục *Vì sao `--chat`*).
2. **Ngưỡng ghép nghĩa = 1 từ nội dung.** Đã đo cả mức 2 trên kaikki 28/08: mức
   2 kéo về `kitchen`, `purple`, `terror`, `silly→ngu`, `murder→giết` mà lại mất
   `photosynthesis→quang hợp`, `derivative→đạo hàm`, `ecliptic→hoàng đạo`. Giữ 1.
3. **`_DA_SOAT_LA_SAI`** — 21 cặp soát tay, mỗi cặp ghi lý do. Chúng được gắn
   ĐÚNG lĩnh vực nên hai lớp trên không bắt được, ví dụ `tenant→chủ sở hữu`
   (ngược nghĩa), `angle→gốc` (sai dấu), `account→chuyện kể`, `cent→phần trăm`.

Đã thử và **BỎ** một hướng: thẩm định lại bằng từ điển Anh–Việt 104k mục. Nó
bắt đúng rác nhưng giết nhầm `neurosurgery`, `theorem`, `pandemic`, `diarrhea`
— từ điển diễn đạt khác chữ ("Khoa giải phẫu thần kinh", "Định lý"). Với danh
sách ngắn thế này, soát tay trung thực hơn.

ZH/JA nhỏ theo vì chúng **pivot qua `en.json`** — bỏ nguồn rác thì bản pivot
sạch theo.

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

- **KO / OMW**: bị chặn vì thiếu dữ liệu công khai (không có wordnet VI/KO —
  xem bước 4). Cần tìm từ điển Hàn→Anh (hoặc Hàn→Việt) mới thêm được KO. Kho
  dựng để ở **`/opt/glossary-build`** trên .38 (đã rời `/root`).
- **Test đầu-cuối thật** một video chuyên ngành: .38 điều phối, .220 NLLB (và
  LLM nếu bật) — đo hậu kỳ thay đúng chỗ, và nếu bật LLM thì xem `.hoc.json` có
  lớn dần không.

OMW dùng tệp `.tab` per-ngôn-ngữ (vie/kor/jpn/cmn); tải từ OMW / omwn.
