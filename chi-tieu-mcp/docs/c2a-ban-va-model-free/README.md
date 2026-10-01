# Bản vá C2A: model ChatGPT Free gọi được tool chi tiêu

Đây là **tham khảo, không phải PR**. Bản vá tay trên C2A commit `678285a`
(24/09/2026), chạy thật từ 25/09/2026. Nó nhận server chi tiêu theo **tên** và có câu
cảnh báo viết cứng, nên nếu đưa vào chính thức thì nên viết lại theo kiến trúc C2A.
Diff: [ban-va.diff](ban-va.diff) (2 file: `services/mcp_client.py`,
`services/protocol/openai_v1_chat_complete.py`).

## Triệu chứng

Combo `auto/chat` chỉ còn ChatGPT Free (`cgf/*`) sống (Codex hết quota, chưa có key
Gemini AI Studio…). Người dùng nhắn "ăn sáng 30k" → bot trả lời "đã ghi nhận 30.000đ"
nhưng sổ không có dòng nào. Log không có lỗi.

## Nguyên nhân (3 lớp)

1. Cổng `free_model_no_agentic_loop` không đưa tool MCP cho model free, trừ câu lọt
   `_is_expense_query()`. Bản cũ trượt gần hết câu thật: số bằng chữ ("ba mươi ngàn"),
   số có dấu chấm ("45.000"), "tạm ứng", "nhận tiền từ công ty 5000000"…
2. Trần payload ChatGPT Free ~42 KB. Bước 1 của agent mang ~90 tool (≈104 KB) → cgf bị
   loại. Tin nhắn ≈30 KB + 11 tool chi tiêu đủ mô tả (12,8 KB) vẫn vượt ~500 B. Lượt gọi
   tiếp sau khi chạy tool lại nạp `body["tools"]` (~90 tool) → vượt trần **sau khi** đã
   ghi sổ → agent thử lại → nguy cơ ghi trùng.
3. Với ChatGPT Free, gọi tool chỉ là lời dặn trong prompt (khối XML). Tóm tắt phiên có
   "Đã ghi nhận chi tiêu: ăn sáng 30.000đ" của lần trước → model coi khoản mới giống hệt
   là tin lặp, trả lời bằng chữ, không gọi tool.

## Cách vá

- **v1** — `services/mcp_client.py`: `_is_expense_server` + `get_expense_mcp_tools()`.
  `openai_v1_chat_complete.py`: `_is_expense_query` mở rộng (`_EXPENSE_KEYWORDS`,
  `_MONEY_AMOUNT_RE`); trong `_inject_mcp_tools`, model free + tin chi tiêu → CHỈ kèm
  tool chi tiêu; trong vòng combo, vượt 42 KB mà là tin chi tiêu → rút về tool chi tiêu
  (`_trim_free_expense_tools`) thay vì bỏ qua cgf.
- **v2** — `_compact_expense_tools` (mô tả ≤420 ký tự, bỏ `title`: 12,8 → 7,2 KB);
  `_stash_free_expense_tools` + `_followup_tools`: lượt gọi tiếp dùng lại đúng bộ tool
  đã gửi.
- **v3** — `_free_expense_bat_buoc`: tin ngắn (≤160 ký tự), có số tiền, không phải câu
  hỏi → lượt đầu `tool_choice="required"`. Tin dài hay câu hỏi có số tiền ("giá vàng 12
  triệu à?") thì KHÔNG ép — ép thì model có thể ghi bừa một khoản.
  `_dispatch_free_expense`: trả lời "đã ghi" mà không có lệnh gọi tool → thử lại 1 lần
  → vẫn bịa thì trả cảnh báo "CHƯA ghi được" thay vì xác nhận giả.
- **Phía bot**: docstring `ghi_chi_tieu` mở đầu bằng quy tắc "mỗi tin báo chi là 1 khoản
  MỚI, luôn gọi tool" — nằm trong 420 ký tự mà `_compact_expense_tools` giữ lại.

## Log để theo dõi

`mcp_inject_expense_free`, `combo_free_expense_trimmed` (bytes trước/sau),
`free_expense_tool_required`, `free_expense_fake_confirm` (kèm `lan`), rồi
`mcp_tool_exec ghi_chi_tieu`.

## Thử áp

```bash
git checkout 678285a
git apply --check <đường-dẫn-tới>/ban-va.diff
```

`main` mới hơn có thể lệch dòng — đọc để lấy ý, đừng áp nguyên.

## Hạn chế đã biết

- Nhận server chi tiêu theo tên chứa "chi tiêu"/"chitieu" — nên thay bằng một cờ trong
  cấu hình MCP server.
- `_CANH_BAO_CHUA_GHI` có chỗ `<địa chỉ trang /ui>`: bản chạy thật viết cứng link
  riêng; nên lấy từ cấu hình.
- Từ khoá và regex số tiền chỉ cho tiếng Việt; có thể bắt nhầm câu hỏi giá có số tiền
  (chấp nhận được: model free chỉ được kèm tool chi tiêu).
- Gốc rễ vẫn là thiếu model gọi tool thật: có key Gemini AI Studio thì `gemini_free/*`
  đứng trước cgf trong `auto/chat`.
