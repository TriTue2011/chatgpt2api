# Dịch máy tự chủ — vn-translate trong stack

Không qua bên thứ ba. Không Google, không Azure, không `libretranslate.com`,
**không LLM** (hỏi model dịch thì tốn hạn mức, chậm, và tin dài bị cắt). Máy dịch
là một container trong chính stack của mình; sau khi model tải xong, không lượt
dịch nào ra Internet.

> Tài liệu này thay bản cũ viết cho LibreTranslate/Argos (13/08/2026). Argos vẫn
> còn trong compose sau `--profile libretranslate` cho ai muốn quay lại.

## 1. Cài: chỉ cần chạy compose

```bash
docker compose up -d
```

Không có bước hai. `vn-translate` là một service trong chính
[`docker-compose.yml`](../docker-compose.yml) (cùng nếp SearXNG: nằm trong stack,
không publish cổng), và service `c2a` đã được khai
`TRANSLATE_URL=http://vn-translate:5000` sẵn — **không phải sửa `config.json`
hay bấm gì trên web UI**. Dựng xong là có: lệnh `/dich` của bot, **tab Dịch**
trên web UI, mục 🌐 khi gửi tệp/ảnh.

Muốn tắt hẳn: xoá biến `TRANSLATE_URL` khỏi service `c2a`, hoặc đặt
`TRANSLATE_URL=` (rỗng) trong `.env`.

### Hai engine, chọn theo CẶP ngôn ngữ

| Cặp | Engine | Ở đâu | Vì sao |
|---|---|---|---|
| **en↔vi** | **EnViT5** (VietAI, 275M) | **nhúng sẵn trong image** (~265 MB) | Đo FLORES-200 devtest 13/08 (300 câu, CPU 4 nhân): en→vi **42,95 BLEU / 61,22 chrF++** so với NLLB-600M 38,45 / 57,54; vi→en 38,44 / 62,36 so với 36,32 / 59,59 — và **nhanh gấp ~3 lần**. |
| ja / ko / zh ↔ vi | **NLLB-200 distilled 600M** (int8) | tải về volume lần chạy đầu (~600 MB) | Dịch **thẳng** vi↔ja/ko/zh, không bắc cầu qua tiếng Anh như Argos. |

Vì sao EnViT5 thắng NLLB dù nhỏ hơn: 43% tham số NLLB nằm ở bảng từ vựng 256k
token cho 200 ngôn ngữ — vô ích khi chỉ cần một cặp. Model NLLB to hơn (1.3B)
**không** cứu được, còn tệ hơn ở tên riêng. EnViT5 hỏng thì lượt đó tự rơi xuống
NLLB (người dùng thà nhận bản dịch kém hơn còn hơn nhận thông báo lỗi).

Cả hai đường đều đi qua **tầng thuật ngữ chuyên ngành** (điện tử / y tế / xây
dựng / CNTT / pháp lý) tra bảng trong `vn-translate/app/terms.py`; chủ máy đè
thêm bảng riêng qua volume `/data/glossary/*.json`.

`c2a` **không** chờ tải xong mới lên (cố ý không `depends_on: service_healthy`):
trục dịch fail-open, máy dịch chưa sẵn sàng thì bot chạy y như chưa có tính năng
này.

## 2. Các nút điều chỉnh

Biến môi trường (khai trong compose / `.env` / Portainer → Environment) được ưu
tiên hơn `config.json`, cùng nếp `CHATGPT2API_BASE_URL`:

| Biến env | Khoá config.json | Mặc định | Nghĩa |
|---|---|---|---|
| `TRANSLATE_URL` | `translate_url` | compose đặt `http://vn-translate:5000` | Rỗng = tắt hẳn mọi tính năng dịch. |
| `TRANSLATE_URL_LO` | `translate_url_lo` | `""` | **Máy dịch GPU** nhận việc theo LÔ — xem mục 2c. |
| — | `translate_lo_toi_thieu` | `8` | Lô từ bao nhiêu đoạn trở lên mới đi máy GPU. |
| `TRANSLATE_PIVOT` | `translate_pivot_enabled` | `0` | Dịch sang tiếng Anh trước khi gửi LLM. Xem mục 5 **trước khi** bật. |
| `TRANSLATE_API_KEY` | `translate_api_key` | `""` | Chỉ cần khi máy chủ bật kiểm khoá. |
| — | `translate_timeout` | `120` | Giây chờ máy chủ dịch. NLLB chạy CPU: khối vài chục dòng mất 10–30 giây trên máy 4 nhân. |
| — | `translate_docx_threshold` | `3000` | Bản dịch dài hơn ngần này ký tự thì gửi bằng `.docx` thay vì tin nhắn. `0` = luôn gửi tin nhắn. |

Của riêng service `vn-translate` (khai ở service đó, không phải ở `c2a`):

| Biến | Mặc định | Nghĩa |
|---|---|---|
| `TT_LANGS` | `en,vi,ja,ko,zh-Hans` | Ngôn ngữ khai ra ngoài qua `/languages`. |
| `TT_MODELS` | `…600M-ct2-int8,…1.3B-ct2-int8` | Thang model NLLB: model đầu lỗi 2 lần liên tiếp thì tự chuyển model kế. |
| `TT_THREADS` | `4` | Luồng CPU cho một lượt dịch. |
| `TT_GLOSSARY` | `1` | Bật tầng thuật ngữ chuyên ngành. |
| `TT_ENVIT5_DIR` | `/opt/envit5` | Đặt `""` để tắt EnViT5 (mọi cặp về NLLB). |
| `TT_THIET_BI` | `cpu` | `cuda` cho bản GPU. |
| `TT_KIEU_TINH` | tự chọn | `float16` nhanh nhất trên card CC ≥ 7.0 (đo 14/08 trên RTX 2060S). |
| `TT_LO_MODEL` | `16` (cpu) / `64` (cuda) | Lô đưa vào model mỗi lượt decode. |

## 2b. Ngôn ngữ nào

`TT_LANGS` (mặc định `en,vi,ja,ko,zh-Hans`) là danh sách khai ra ngoài. Đủ bốn
cặp cần dùng, cả hai chiều: **Anh⇄Việt, Việt⇄Nhật, Việt⇄Hàn, Việt⇄Trung**.

Khác Argos ở điểm quan trọng: NLLB dịch **thẳng** vi→ja trong một lượt, không
bắc cầu `vi→en→ja`. Argos trước đây phải bắc cầu vì trong 100 gói model của nó
98 gói có tiếng Anh ở một đầu — nên chất lượng Việt⇄Nhật/Hàn/Trung kém hơn hẳn.

**`zh` là chữ Hán giản thể**, khai ra ngoài dưới tên `zh-Hans` (giữ đúng quy ước
LibreTranslate để client cũ không phải sửa). Client có `_BI_DANH_MA` để chuẩn
hoá — thiếu nó thì `/dich tiếng trung xin chào` so mã `zh` với `/languages` (chỉ
có `zh-Hans`) sẽ trượt và dịch luôn cả cụm "tiếng trung" như nội dung.

Gateway **không đoán** danh sách: `_phan_giai_dich` chỉ nhận mã có trong
`/languages` của chính máy chủ. Gõ `/dich th …` khi máy chủ không khai tiếng
Thái thì `th` được hiểu là **nội dung cần dịch**, không phải ngôn ngữ đích.

Bảng tên tiếng Việt (`/dich tiếng nhật …`) phủ 22 ngôn ngữ với 40 cách gọi;
ngoài đó thì dùng mã ISO.

## 2c. Máy dịch GPU cho việc theo LÔ (tuỳ chọn)

Đo thật 14/08 trên RTX 2060 Super (lô 120 câu en→vi, qua đúng đường HTTP):
**CPU 54,4 giây · GPU 0,84 giây (~65 lần)**. Nhưng GPU **thua** CPU với câu lẻ
(overhead khởi động lô) — nên hệ chạy **song song hai máy**, không thay thế:

- Lô ≥ `translate_lo_toi_thieu` (mặc định 8 đoạn) → máy GPU. Đúng kiểu phụ đề
  phim, tài liệu dài.
- Câu lẻ, đàm thoại, `/dich` một câu → máy CPU trong stack như cũ.
- Máy GPU lỗi/tắt → lô đó **tự rơi về CPU** ngay, và **cầu dao** ngắt GPU 5
  phút (máy GPU treo thì mỗi lô chờ hết timeout, phim trăm lô sẽ cộng dồn hàng
  giờ). Hết 5 phút tự thử lại. Không có tính năng nào đứt khi GPU chết.

Dựng bản GPU trên máy có card NVIDIA (không cần cùng máy với gateway):

```bash
# trên máy có GPU: lấy nguồn + EnViT5 đã convert từ image CPU đang chạy
docker exec vn-translate tar -cC /opt envit5 | tar -x   # → envit5-ct2/
docker build -f Dockerfile.gpu -t vn-translate-gpu .
docker run -d --name vn-translate-gpu --gpus all --restart unless-stopped \
  -p 5001:5000 -v vn-translate-gpu-data:/data \
  -e TT_KIEU_TINH=float16 vn-translate-gpu
```

Rồi khai ở gateway: `TRANSLATE_URL_LO: http://<ip-máy-gpu>:5001`.
Yêu cầu: CUDA 12 + cuDNN 9 (nền image đã lo), card Compute Capability ≥ 7.0 cho
`float16`; VRAM ~2 GB. Xem [`../vn-translate/Dockerfile.gpu`](../vn-translate/Dockerfile.gpu).

## 3. Lệnh `/dich` của bot

Có trên **Telegram**, **Zalo Bot** và **Zalo cá nhân**, do code làm, không qua
LLM (hỏi model dịch thì tốn hạn mức và trả về lời rào đón).

```
/dich xin chào cả nhà          → tiếng Việt thì dịch sang tiếng Anh
/dich good morning             → thứ khác thì dịch sang tiếng Việt
/dich en xin chào              → chỉ định bằng mã ngôn ngữ
/dich tiếng anh xin chào       → hoặc bằng tên tiếng Việt
/dich https://youtu.be/…       → PHỤ ĐỀ video: lấy phụ đề YouTube rồi dịch, trả .srt
/dich                          → hướng dẫn + danh sách ngôn ngữ máy chủ đang nạp
```

Gửi kèm **tệp video / âm thanh** với chú thích `/dich` (hoặc gửi thẳng tệp trên
Zalo cá nhân): máy tự **nghe** rồi trả phụ đề — xem mục 4b.

Nhận cả `/dịch`, `/translate`, `/tr`, và dạng có tag bot trong nhóm
(`/dich@TênBot`, `@TênBot /dich …`).

Tên ngôn ngữ tiếng Việt **chỉ** nhận sau chữ "tiếng". Lý do: gần như mọi tên
ngôn ngữ trong tiếng Việt đều là từ thông dụng, nên `/dich anh ơi giúp em với`
mà hiểu "anh" là tiếng Anh thì mất luôn chữ đầu câu người dùng gõ.

Những thứ sau được **cắt ra khỏi phần gửi đi** rồi ghép lại nguyên văn — không
phải "dặn máy dịch đừng dịch", mà là chúng chưa từng chạm máy chủ dịch:

- khối mã ```` ``` ````, `~~~`, mã trong dòng `` ` ``;
- URL, email, thẻ HTML/XML, `{{biến}}`, marker `image://` của dự án;
- **bộ xương Markdown**: `#` tiêu đề, `-`/`*`/`1.` đầu dòng, `>` trích dẫn,
  đường kẻ `---`, và vách ô bảng `|` (mỗi ô thành một đoạn dịch riêng).

Bộ xương Markdown quan trọng hơn nó trông: không chừa ra thì máy dịch ăn luôn cấu
trúc — `## Tiêu đề` mất dấu thăng, `- mục` mất gạch đầu dòng, bảng mất cột. Bản
dịch vẫn đúng nghĩa nhưng hiện ra là một khối chữ liền, và với câu trả lời có
bảng thì mất sạch thông tin sắp xếp.

## 4. Dịch tệp và ảnh

Mục **🌐 Dịch** xuất hiện trong menu khi gửi tệp/ảnh, ngay khi `translate_url`
đã cấu hình (chưa cấu hình thì không hiện — bày ra một lựa chọn bấm vào chỉ nhận
câu báo lỗi thì tệ hơn là không bày). Có trên cả ba kênh: Telegram, Zalo Bot,
Zalo cá nhân.

| Gửi vào | Đường xử lý | Nhận lại |
|---|---|---|
| `.docx` `.pptx` `.odt` `.odp` `.txt` `.epub` `.html` | `POST /translate_file` — máy dịch dựng lại chính tệp đó | tệp **cùng định dạng**, tên `<gốc>.vi.docx` |
| `.srt` `.vtt` | đọc khung phụ đề → gộp trọn câu → dịch → cắt lại khung đạt chuẩn đọc | `.srt` đã dịch (+ bản chữ-trên, xem 4b) |
| `.pdf` | pdf-inspector / OCR vision → dịch chữ | tin nhắn, hoặc `.docx` nếu dài |
| `.xlsx` `.doc` `.ppt` | markitdown → dịch chữ | tin nhắn, hoặc `.docx` nếu dài |
| ảnh | OCR bằng model vision → dịch chữ | tin nhắn, hoặc `.docx` nếu dài |

PDF và Excel **không** quay lại đúng định dạng (không có bộ dựng lại cho hai
định dạng đó) — danh sách định dạng thật lấy từ `/frontend/settings` của chính
máy chủ, không đoán.

Bản dịch dài hơn `translate_docx_threshold` (mặc định 3000 ký tự) được đóng
thành `.docx` bằng đúng bộ dựng docx của dự án. Lý do: Telegram chặn một tin ở
4096 ký tự, nên bản dịch một tài liệu vài trang gửi bằng tin nhắn sẽ bị cắt
thành một chuỗi tin vụn. Zalo Bot không gửi được tệp nên ở đó luôn là tin nhắn.

Ảnh: câu neo "trả lời hoàn toàn bằng tiếng Việt" của `analyze_photo` bị **tắt**
cho riêng việc này (`neo_tieng_viet=False`) — để nguyên thì model tự dịch ảnh
sang tiếng Việt và máy dịch nhận vào một bản đã Việt hoá, không còn gì để dịch.

## 4b. Phụ đề video (link, tệp video, tệp phụ đề)

Ba đường vào, cùng một dây chuyền phụ đề (`services/video_dich.py`):

| Vào | Cách làm | Trần |
|---|---|---|
| **Link YouTube** | lấy phụ đề có sẵn của video rồi dịch — không tải video, không nghe | 2 giờ |
| **Tệp video / âm thanh** | ffmpeg bóc tiếng → cắt đoạn có tiếng → **nghe tại máy** (sherpa-onnx) → dịch | web 4 GB / 150 phút · Zalo 250 MB |
| **Tệp `.srt` / `.vtt`** | đọc khung có sẵn rồi dịch — **nhanh nhất và chuẩn nhất cho phim** (~1 phút cho phim 2 giờ) | — |

Dây chuyền chung, và vì sao từng bước có mặt:

- **Gộp trọn câu trước khi dịch.** Phụ đề tự sinh cắt 1–2 giây một mảnh, giữa
  câu; dịch từng mảnh thì máy dịch mất ngữ cảnh và nuốt mất mảnh lơ lửng.
- **Máy dịch tách lại từng câu** khi vào model (model học trên cặp câu; đưa 3
  câu một lượt thì nó bỏ câu — đo thật 13/08).
- **Cắt lại khung theo chuẩn hiển thị**: 42 ký tự/dòng, tối đa 2 dòng, 20 ký tự/
  giây, khung 1–7 giây, khe giữa hai khung ≥ 24 ms (Netflix/TED/BBC). Có bộ
  **soát** chạy sau mỗi lần dựng — không đạt thì báo, không lặng lẽ trả tệp lỗi.
- **Bản chữ-trên** `{\an8}` gửi kèm mọi kết quả video: video đã có chữ in cứng ở
  đáy hình thì phụ đề dịch đè lên thành hai lớp không đọc nổi. VLC / MX Player /
  mpv đều hiểu thẻ này.
- **Video dạy ngoại ngữ**: từ đang được giảng được đính từ gốc vào khung ("…đang
  cắt [chopping]") — dịch cả `cut` và `chop` thành "cắt" là bài học biến mất.

Ngôn ngữ nghe: máy tự dò bằng cách **so độ tự tin giải mã** của hai model (tiếng
Việt và tiếng của cặp đã chọn) — model đúng tiếng tự tin ~-0,04, model sai ~-0,5.
Mẫu lấy rải giữa thân video, không lấy 20 giây đầu (video hay mở màn bằng nhạc).

## 4c. Tab Dịch trên web UI

Menu **Studio → Dịch** (chỉ admin). Hai tab con:

**Dịch** — một chỗ cho mọi thứ:
- Dán chữ → dịch ngay; dán **link YouTube** → phụ đề dịch.
- Kéo thả tệp: ảnh (đọc chữ trong ảnh rồi dịch), tài liệu, **phụ đề .srt/.vtt**,
  **video/âm thanh** (≤ 4 GB, ≤ 150 phút).
- Video/âm thanh/phụ đề có **hai kiểu kết quả**: *Phụ đề (.srt)* hoặc *Bản chữ*
  (lời thoại đã dịch, không mốc thời gian).
- Cặp ngôn ngữ: **Việt ↔ Anh / Trung / Nhật / Hàn** — máy tự nhận chiều (nguồn
  tiếng Việt thì dịch sang tiếng kia, ngược lại về tiếng Việt).
- Upload **cắt khúc 25 MB** gửi tuần tự: đường domain qua Cloudflare chặn thân
  request ~100 MB, gửi nguyên khối một video 720p là chết ở proxy chứ chưa tới
  máy. Việc chậm chạy ở luồng nền, trang thăm dò tiến độ (đóng trang không mất
  việc, nhưng mất đường nhận kết quả).

**Đàm thoại** — phiên dịch hai chiều tại chỗ: hai ô cho hai tiếng, bấm mic bên
nào thì máy nghe bằng model tiếng đó (không đoán — người bấm đã khai) rồi dịch
sang bên kia; tuỳ chọn **đọc bản dịch thành tiếng**. Mỗi lượt ≤ 90 giây, kiểu
bấm-nói-bấm dừng (không phải streaming liên tục). Mic cần **HTTPS** — mở bằng IP
LAN thì trình duyệt chặn.

## 5. Trục dịch quanh LLM (mặc định TẮT)

Bật bằng `translate_pivot_enabled: true`. Khi bật, mỗi lượt gọi model sẽ:

1. dịch nội dung mọi tin (system / user / assistant) sang **tiếng Anh**;
2. chèn một tin `system` **tiếng Anh** dặn model *luôn trả lời bằng tiếng Việt*
   (chèn **sau** khi dịch nên bản thân câu dặn không bị dịch);
3. nhận phản hồi, nhận diện ngôn ngữ, **không phải tiếng Việt thì dịch về tiếng
   Việt**. Model tuân lệnh ở bước 2 thì bước này không tốn gì.

### Vì sao trục đặt ở `_dispatch`, không đặt ở `handle`

Trước `_dispatch` là cả một tầng xử lý **tiếng Việt** chạy trên chính chữ người
dùng gõ: lệnh nhà thông minh (`_ha_local_intent`), thời tiết, âm lịch, bão,
định tuyến nhánh Agent, chọn kỹ năng. Dịch sang tiếng Anh trước những bước đó là
tắt sạch chúng — "bật đèn phòng khách" thành "turn on the living room light" thì
không khớp mẫu nào nữa. `_dispatch` là **cửa duy nhất** mà mọi provider đi qua để
chạm model thật, và mọi logic tiếng Việt đã chạy xong trước đó.

### Năm loại request trục KHÔNG đụng tới

Dịch vào là **hỏng**, không phải "kém đi":

- có `tools` — tên hàm/tham số là hợp đồng máy-với-máy, và tên thiết bị Home
  Assistant là tiếng Việt, dịch đi thì gọi hàm trượt entity;
- có `response_format` / JSON schema — khoá JSON bị dịch là client hết parse;
- có tin `role="tool"` hoặc `tool_calls` — cùng lý do;
- có ảnh — đường vision trả JSON cho Home Assistant;
- có cờ `_c2a_noi_bo` — **lượt gọi nội bộ của pipeline code** (architect lập kế
  hoạch, reviewer soi code, editor sửa theo góp ý). Lời nhắc của chúng nhúng code
  **thô**: `_PIPELINE_REVIEWER_PROMPT` ghép thẳng `=== CODE ===\n{code}` không
  bọc ```` ``` ````, mà lớp bảo vệ chỉ chừa khối mã **có** dấu huyền. Thiếu cờ
  này thì bật trục là code bị dịch thành văn xuôi và cả nhánh pipeline hỏng lặng
  lẽ — reviewer vẫn trả lời, chỉ là trả lời về một đoạn không còn là code.

### Cái giá phải biết trước khi bật

**Chất lượng.** Máy dịch trong stack không mạnh bằng model lớn. Câu hỏi của người
dùng đi qua một lần dịch máy trước khi tới model, và câu trả lời có thể đi qua
một lần nữa để về tiếng Việt. Với trợ lý tiếng Việt, đó là hai chỗ mất mát mà
trước đây không có.

Nặng nhất là khi câu trả lời dựa vào **tìm kiếm / RAG**: nội dung lấy về vốn đã
là tiếng Việt, được chèn vào messages **trước** `_dispatch`, nên nó bị dịch sang
tiếng Anh rồi câu trả lời dịch về lại tiếng Việt — hai lần dịch máy trên chính dữ
liệu gốc tiếng Việt. Nếu anh dùng bot để tra tin tức / luật / SGK nhiều thì đây là
chỗ tụt rõ nhất.

**Stream vẫn chạy dần.** Không dịch được theo từng chunk (một chunk là vài ký tự,
dịch máy cần đủ câu), nên phản hồi được dịch theo **từng khối đã hoàn chỉnh** —
ranh giới là dòng trống, tức từng đoạn văn. Chữ vẫn hiện dần chứ không đổ ra một
lượt ở cuối. Khối mã không bao giờ bị cắt ngang (chờ ``` đóng mới dịch), và đoạn
dài liền mạch quá 1200 ký tự thì cắt ở dấu kết câu để không phải chờ tới hết.
Mọi chunk mang `role`/`tool_calls`/`finish_reason`/`usage` được phát lại nguyên
vẹn.

**Fail-open tuyệt đối.** Máy chủ dịch chết, timeout, trả rác → request đi nguyên
văn như khi chưa có tính năng này. Một dịch vụ dịch hỏng không được phép làm trợ
lý câm.

## 6. Kiểm tra

```bash
# Máy chủ sống chưa (từ trong mạng stack)
curl -s http://vn-translate:5000/health       # {"status":"ok"}
curl -s http://vn-translate:5000/languages    # [{"code":"en",…},{"code":"vi",…}]

# Dịch thử
curl -s -X POST http://vn-translate:5000/translate \
  -H 'Content-Type: application/json' \
  -d '{"q":"xin chào","source":"vi","target":"en","format":"text"}'

# Máy GPU (nếu có) — cùng API, cổng do mình publish
curl -s http://<ip-máy-gpu>:5001/health
```

Từ trong dự án:

```python
from services import translate_service as ts
ts.health()                      # {"configured": True, "ok": True, "url": …}
ts.translate("xin chào", "en")   # "hello"
ts.translate_batch([...], "vi", "en")   # lô đủ lớn tự đi máy GPU nếu đã khai
```

Đo hiệu năng **phải đo qua handler HTTP thật**, không chỉ gọi `translate_batch`
trong tiến trình: nút thắt lịch sử nằm ở chỗ handler `/translate` từng dịch TỪNG
phần tử `q` một, nên model luôn nhận lô 1 câu và mọi lợi ích batch bị nuốt sạch
mà benchmark tay không thấy (đo và vá 14/08).

Test:

```bash
pytest test/test_translate_service.py test/test_translate_tep.py \
       test/test_translate_pivot.py test/test_translate_zalop.py \
       test/test_video_dich.py test/test_video_asr.py -q
cd vn-translate && pytest tests/ -q       # engine: khung dòng, định tuyến engine
```

## 7. Mã nguồn

| Việc | Ở đâu |
|---|---|
| Client máy dịch, bảo vệ khối mã, bộ đệm, **định tuyến CPU/GPU + cầu dao**, lệnh `/dich` | `services/translate_service.py` |
| Dịch tệp / ảnh, ngưỡng `.docx` | `services/translate_service.py` |
| **Phụ đề video**: link, tệp phụ đề, khung chuẩn hiển thị, từ khoá giảng dạy | `services/video_dich.py` |
| **Nghe tệp video** (bóc tiếng, cắt đoạn, dò tiếng, mốc token) | `services/video_asr.py` |
| **API tab Dịch** (upload cắt khúc, việc nền, đàm thoại mic) | `api/dich.py` |
| **Tab Dịch + Đàm thoại** (web UI) | `web/src/app/dich/page.tsx` |
| Trục dịch quanh LLM | `services/translate_pivot.py` |
| Điểm đấu trục | `services/protocol/openai_v1_chat_complete.py::_dispatch` |
| Mục 🌐 Dịch trong menu tệp | `services/pdf_intent.py`, `services/photo_intent.py` |
| Bộ thực thi từng kênh | `services/telegram_bot.py`, `services/zalo_bot.py`, `services/zalo_personal.py` |
| Cấu hình | `services/config.py` (`translate_*`) |
| Máy dịch (engine, thuật ngữ, API) | `vn-translate/app/{engine,main,terms}.py` |
| Service trong stack | `docker-compose.yml` (`vn-translate` + `TRANSLATE_URL`) |
| Bản GPU | `vn-translate/Dockerfile.gpu` |
