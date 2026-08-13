# Dịch máy tự chủ — LibreTranslate trong stack

Không qua bên thứ ba. Không Google, không Azure, không `libretranslate.com`.
Máy dịch là một container trong chính stack của mình; nhân dịch là
[Argos Translate](https://github.com/argosopentech/argos-translate) chạy trong
container đó. Sau khi model đã tải xong, không lượt dịch nào ra Internet.

## 1. Cài: chỉ cần chạy compose

```bash
docker compose up -d
```

Không có bước hai. `libretranslate` là một service trong chính
[`docker-compose.yml`](../docker-compose.yml) (cùng nếp SearXNG: nằm trong stack,
không publish cổng), và service `c2a` đã được khai
`TRANSLATE_URL=http://libretranslate:5000` sẵn — **không phải sửa `config.json`
hay bấm gì trên web UI**. Dựng xong là bot có lệnh `/dich` và mục 🌐 khi gửi
tệp/ảnh.

Muốn tắt hẳn: xoá biến `TRANSLATE_URL` khỏi service `c2a`, hoặc đặt
`TRANSLATE_URL=` (rỗng) trong `.env`.

### Lần đầu `up` tải 756 MB model

Đo thật 12/08 qua `Content-Length` của `argos-net.com`, với
`LT_LOAD_ONLY="en,vi,ja,ko,zh"` (mặc định). **Mỗi chiều là một model riêng**, và
Nhật/Hàn nặng gấp đôi Việt:

| gói | MB | gói | MB |
|---|---|---|---|
| `en→ja` | 120,5 | `ja→en` | 117,2 |
| `en→ko` | 120,8 | `ko→en` | 118,9 |
| `en→zh` | 70,7 | `zh→en` | 74,5 |
| `en→vi` | 67,8 | `vi→en` | 65,9 |

Trong lúc tải, `/health` đã trả 200 nhưng `/translate` còn báo lỗi. Model nằm
trong volume `libretranslate-models` nên các lần sau **không** tải lại.

`c2a` **không** chờ tải xong mới lên (cố ý không `depends_on: service_healthy`):
trục dịch fail-open, máy dịch chưa sẵn sàng thì bot chạy y như chưa có tính năng
này.

Chỉ cần Anh⇄Việt thôi thì đặt `LT_LOAD_ONLY=en,vi` trong `.env` → 134 MB.

## 2. Các nút điều chỉnh

Biến môi trường (khai trong compose / `.env` / Portainer → Environment) được ưu
tiên hơn `config.json`, cùng nếp `CHATGPT2API_BASE_URL`:

| Biến env | Khoá config.json | Mặc định | Nghĩa |
|---|---|---|---|
| `TRANSLATE_URL` | `translate_url` | compose đặt `http://libretranslate:5000` | Rỗng = tắt hẳn mọi tính năng dịch. |
| `TRANSLATE_PIVOT` | `translate_pivot_enabled` | `0` | Dịch sang tiếng Anh trước khi gửi LLM. Xem mục 5 **trước khi** bật. |
| `TRANSLATE_API_KEY` | `translate_api_key` | `""` | Chỉ cần khi máy chủ bật `LT_API_KEYS=true`. |
| — | `translate_timeout` | `120` | Giây chờ máy chủ dịch. Đặt cho vn-translate/NLLB chạy CPU: khối vài chục dòng mất 10–30 giây trên máy 4 nhân. |
| — | `translate_docx_threshold` | `3000` | Bản dịch dài hơn ngần này ký tự thì gửi bằng `.docx` thay vì tin nhắn. `0` = luôn gửi tin nhắn. |
| `LT_LOAD_ONLY` | — | `en,vi,ja,ko,zh` | Ngôn ngữ máy chủ nạp. Xem mục 2b. |

## 2b. Ngôn ngữ nào — và vì sao danh sách có "en"

Compose ở đây đặt:

```yaml
LT_LOAD_ONLY: "en,vi,ja,ko,zh"
```

Đủ đúng bốn cặp cần dùng, cả hai chiều: **Anh⇄Việt, Việt⇄Nhật, Việt⇄Hàn,
Việt⇄Trung**.

**`en` phải có mặt dù không ai xin cặp Anh–Nhật.** Trong 100 gói model của Argos,
98 gói có tiếng Anh ở một đầu; cặp trực tiếp duy nhất không qua tiếng Anh là
`pt↔es`. Nghĩa là **không tồn tại model `vi↔ja`** — Argos dựng đường bắc cầu
`vi→en→ja` lúc nạp (`CompositeTranslation` trong
`argostranslate/translate.py::get_installed_languages`). Bỏ `en` ra khỏi danh
sách là ba cặp Nhật/Hàn/Trung **chết theo**, không phải chậm hơn mà là không có.

Hệ quả cần biết: Việt⇄Nhật/Hàn/Trung dịch **hai lần** (qua tiếng Anh) nên kém
hơn Anh⇄Việt một bậc rõ rệt. Đó là giới hạn của Argos, không phải của cách đấu
nối ở đây.

`LT_LOAD_ONLY` lọc theo **cả hai đầu** (`init.py`: `pack.from_code in load_only
and pack.to_code in load_only`), nên danh sách 5 mã trên tải 8 gói: `en⇄vi`,
`en⇄ja`, `en⇄ko`, `en⇄zh`.

**`zh` là chữ Hán giản thể**, và LibreTranslate khai nó ra ngoài dưới tên
`zh-Hans` (bảng `aliases` trong `libretranslate/language.py`: `zh→zh-Hans`,
`zt→zh-Hant`, `pb→pt-BR`). Muốn cả phồn thể thì thêm `zt`. Client có
`_BI_DANH_MA` để chuẩn hoá — thiếu nó thì `/dich tiếng trung xin chào` so mã
`zh` với `/languages` (chỉ có `zh-Hans`) sẽ trượt và dịch luôn cả cụm "tiếng
trung" như nội dung.

### Còn nếu muốn thêm ngôn ngữ khác

Kho Argos có **50 ngôn ngữ** — đọc từ
[argospm-index](https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json):

```
ar az bg bn ca cs da de el en eo es et eu fa fi fr ga gl he hi hu id it ja ko
ky lt lv ms nb nl pb pl pt ro ru sk sl sq sv sw th tl tr uk ur vi zh zt
```

Thêm mã vào `LT_LOAD_ONLY` rồi dựng lại container. Bỏ hẳn biến đó = nạp cả 50
(vài GB model, khởi động rất lâu).

Gateway **không đoán** danh sách: `_phan_giai_dich` chỉ nhận mã có trong
`/languages` của chính máy chủ. Gõ `/dich th …` khi máy chủ không nạp tiếng Thái
thì `th` được hiểu là **nội dung cần dịch**, không phải ngôn ngữ đích — không có
chuyện bot nhận lệnh rồi trả về lỗi từ máy chủ.

Bảng tên tiếng Việt (`/dich tiếng nhật …`) phủ 22 ngôn ngữ với 40 cách gọi;
ngoài đó thì dùng mã ISO (`/dich sv …`).

## 3. Lệnh `/dich` của bot

Có trên **Telegram** và **Zalo Bot**, do code làm, không qua LLM (hỏi model dịch
thì tốn hạn mức và trả về lời rào đón).

```
/dich xin chào cả nhà          → tiếng Việt thì dịch sang tiếng Anh
/dich good morning             → thứ khác thì dịch sang tiếng Việt
/dich en xin chào              → chỉ định bằng mã ngôn ngữ
/dich tiếng anh xin chào       → hoặc bằng tên tiếng Việt
/dich                          → hướng dẫn + danh sách ngôn ngữ máy chủ đang nạp
```

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

Bộ xương Markdown quan trọng hơn nó trông: không chừa ra thì Argos ăn luôn cấu
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
| `.docx` `.pptx` `.odt` `.odp` `.txt` `.epub` `.html` | `POST /translate_file` — LibreTranslate dựng lại chính tệp đó | tệp **cùng định dạng**, tên `<gốc>.vi.docx` |
| `.pdf` | pdf-inspector / OCR vision → dịch chữ | tin nhắn, hoặc `.docx` nếu dài |
| `.xlsx` `.doc` `.ppt` | markitdown → dịch chữ | tin nhắn, hoặc `.docx` nếu dài |
| ảnh | OCR bằng model vision → dịch chữ | tin nhắn, hoặc `.docx` nếu dài |

PDF và Excel **không** quay lại đúng định dạng vì `argos-translate-files` không
dựng lại được hai định dạng đó — danh sách định dạng thật lấy từ
`/frontend/settings` của chính máy chủ, không đoán.

Bản dịch dài hơn `translate_docx_threshold` (mặc định 3000 ký tự) được đóng
thành `.docx` bằng đúng bộ dựng docx của dự án. Lý do: Telegram chặn một tin ở
4096 ký tự, nên bản dịch một tài liệu vài trang gửi bằng tin nhắn sẽ bị cắt
thành một chuỗi tin vụn. Zalo Bot không gửi được tệp nên ở đó luôn là tin nhắn.

Ảnh: câu neo "trả lời hoàn toàn bằng tiếng Việt" của `analyze_photo` bị **tắt**
cho riêng việc này (`neo_tieng_viet=False`) — để nguyên thì model tự dịch ảnh
sang tiếng Việt và máy dịch nhận vào một bản đã Việt hoá, không còn gì để dịch.

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

**Chất lượng.** Argos không mạnh bằng model lớn ở cặp Việt–Anh. Câu hỏi của người
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
# Máy chủ sống chưa
curl -s http://libretranslate:5000/health          # {"status":"ok"}
curl -s http://libretranslate:5000/languages       # [{"code":"en",…},{"code":"vi",…}]

# Dịch thử
curl -s -X POST http://libretranslate:5000/translate \
  -H 'Content-Type: application/json' \
  -d '{"q":"xin chào","source":"vi","target":"en","format":"text"}'
```

Từ trong dự án:

```python
from services import translate_service as ts
ts.health()                      # {"configured": True, "ok": True, "url": …}
ts.translate("xin chào", "en")   # "hello"
```

Test:

```bash
pytest test/test_translate_service.py test/test_translate_tep.py \
       test/test_translate_pivot.py -q
```

## 7. Mã nguồn

| Việc | Ở đâu |
|---|---|
| Client LibreTranslate, bảo vệ khối mã, bộ đệm, lệnh `/dich` | `services/translate_service.py` |
| Dịch tệp / ảnh, ngưỡng `.docx` | `services/translate_service.py` |
| Trục dịch quanh LLM | `services/translate_pivot.py` |
| Điểm đấu trục | `services/protocol/openai_v1_chat_complete.py::_dispatch` |
| Mục 🌐 Dịch trong menu tệp | `services/pdf_intent.py`, `services/photo_intent.py` |
| Bộ thực thi từng kênh | `services/telegram_bot.py`, `services/zalo_bot.py`, `services/zalo_personal.py` |
| Cấu hình | `services/config.py` (`translate_*`) |
| Service trong stack | `docker-compose.yml` (`libretranslate` + `TRANSLATE_URL`) |
