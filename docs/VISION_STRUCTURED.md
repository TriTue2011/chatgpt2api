# Phân tích ảnh + structured output (HA / chatgpt2api)

Giờ VN (ICT). Server c2a log UTC = ICT − 7h.

## 1) Postmortem sự kiện ~07:14:44 21/07/2026 (VN)

| ICT | UTC (log) | Sự kiện |
|-----|-----------|---------|
| ~07:14:52 | 00:14:52 | Zalo motion photo + HA client `172.16.10.200` → `POST /v1/chat/completions` |
| | | Combo **AI vision** → bước 1 `cx/auto` (openai_oauth / Codex) |
| ~07:14:57 | 00:14:57 | Codex account #1 **429** `usage_limit_reached`, plan **free**, demote |
| ngay sau | | Đổi **account Codex #2** (cùng provider) → **HTTP 200** |
| | | JSON vision: `humans_detected: 2` (mô tả đàn ông + trẻ em…) |

**Kết luận kỹ thuật**

1. **Fallback account Codex đã chạy** (không phải “chưa có fallback”).
2. **Không nhảy sang GMA/ChatGPT** vì account #2 vẫn trả 200 — combo chỉ chuyển provider khi **toàn bộ** bước `cx/auto` fail.
3. Lúc đó **`services.protocol.response_format` thiếu file** → không inject/enforce schema → JSON dễ lệch / parse kém.
4. Pool Codex probe: hầu hết account tag **plan free** → fallback account vẫn free, chất lượng/quota không đổi loại.

## 2) Structured vs câu hỏi thường

| Request | Gateway |
|---------|---------|
| Có `response_format` (`json_schema` / `json_object`) | Inject schema + ép JSON sau model. **Không** strip markdown italic (tránh hỏng key). |
| Không RF, prompt blueprint camera (`humans_detected`, “phân tích chuỗi ảnh”…) | Vẫn ép JSON vision (HA blueprint cũ). |
| Không RF, hỏi thường + ảnh (“Ảnh này là gì?”) | **Văn xuôi** — **không** ép `humans_detected`. |

### Khuyến nghị HA

**Camera / automation (cần parse):**

- Model: `AI vision` (hoặc combo tương đương)
- Gửi `response_format.json_schema` đủ field `humans_detected*` / `animals_detected*`
- Prompt nên nhắc field names (phòng khi RF bị mất ở client)

**Conversation + ảnh (hỏi thường):**

- **Không** gắn `response_format`
- Model text/vision thường — kỳ vọng câu trả lời tự nhiên

## 3) Codex 429 / fallback — hành vi hiện tại

```
cx/auto:
  pick account active (bỏ limited/disabled)
  → 429 usage_limit → mark limited + demote + thử account khác (tối đa ~8)
  → hết account → raise → combo thử bước sau (gma/auto, chatgpt/auto)
```

**Lệch ảnh sau fallback 200:** không phải “fallback hỏng”, mà model (account free) **vẫn trả lời** nhưng có thể ảo. Đã thêm **IMAGE GROUNDING** trong inject schema khi có ảnh.

**Combo vision khuyến nghị (live):**  
`gma/auto` → `chatgpt/auto` → `cx/auto`  
(ưu tiên multimodal GMA trước khi đốt Codex free)

## 4) Log cần xem khi debug

| Event | Ý nghĩa |
|-------|---------|
| `structured_output_active` / `response_format_injected` | HA có gửi RF, inject OK |
| `response_format_enforced` / `vision_json_enforced` | Ép JSON sau model |
| `response_format_inject_skip` | Lỗi import/module |
| `combo_try` (+ `is_vision`, `structured`) | Bước combo |
| `codex_upstream_error` 429 | Hết quota account |
| `codex_account_limited` + demote | Xoay account |
| `combo_fail` | Fail bước combo → bước sau |

## 5) Checklist sau deploy

1. Module `/app/services/protocol/response_format.py` tồn tại  
2. `combo_models["AI vision"]` = `["gma/auto","chatgpt/auto","cx/auto"]`  
3. `agent_branches.vision` = `AI vision`  
4. Test unit: RF / plain / blueprint (xem `_tmp_test_vision_rf.py`)  
