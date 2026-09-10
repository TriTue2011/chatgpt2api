# Quy tắc làm việc chung

- Khi không chắc chắn về yêu cầu, hỏi lại thay vì đoán.
- Thay đổi lớn luôn lên kế hoạch và xem xét các vấn đề trước khi code.

## Sửa LỚP LỖI, không vá triệu chứng

Chủ máy chốt 10/09/2026: *"như bây giờ khác gì tôi soát lỗi, cần bạn để làm
gì"*. Áp cho mọi phiên làm việc trên repo này, kể cả Claude giám sát trên máy
chủ.

**Trước khi sửa, trả lời ba câu — viết vào commit:**

1. Lỗi này thuộc **lớp** nào? (khớp chuỗi bắt nhầm / đọc sai kho dữ liệu /
   không kiểm chứng kết quả / …)
2. Còn chỗ nào cùng lớp? **Đo bằng `grep`, đừng đoán.**
3. Sửa theo **nguyên tắc** hay theo **danh sách**?

**Thêm một danh sách từ khoá là thất bại, không phải giải pháp.** Danh sách
luôn thiếu; mỗi lần thiếu là một lần chủ máy phải làm người soát lỗi. Riêng
`services/` đã có 52 file làm vậy. Chỉ chấp nhận khi đã nêu rõ vì sao không
nguyên tắc nào thay được.

**Tự sinh trường hợp TRƯỚC khi viết code.** Liệt kê các tình huống có thể xảy
ra từ **dữ liệu thật** (`runs.sqlite`, log máy chủ), không từ trí tưởng tượng.

**Đo trên dữ liệu thật trước khi tin bản sửa.** Một bộ dò lỗi từng đạt 13/13
test nhưng bắt 0 ca thật — test chỉ chứng minh code chạy đúng như mình nghĩ,
không chứng minh mình nghĩ đúng.

**Ba lỗi cùng một lớp đã xảy ra trong một buổi sáng** (10/09/2026), cả ba đều
là *khớp chuỗi rồi không ai kiểm chứng kết quả*: bộ lọc cảm biến khớp `power`,
sổ tên khớp `face 17`, đường tắt khớp `mấy giờ`. Cách chữa đúng là
`services/bai_hoc.py` — bot sai một lần thì tự tránh, không cần ai liệt kê
trước.

# Bắt buộc tích hợp & sử dụng (khi phù hợp với dự án)

## 1. Documentation & context (MỌI project)
- Context7 — tài liệu/code example đúng version, tránh bịa API cũ.
  https://github.com/upstash/context7 → gõ `use context7` khi cần tra docs.
- markitdown — chuyển PDF/docx/pptx/xlsx sang Markdown khi cần đọc file không phải code.
  https://github.com/microsoft/markitdown

## 2. Codebase understanding / giảm token khi đọc code
- GitNexus: https://github.com/abhigyanpatwari/GitNexus
- CodeGraph: https://github.com/colbymchenry/codegraph
- Semble: https://github.com/MinishLab/semble
- RTK: https://github.com/rtk-ai/rtk/
- codebase-memory-mcp: https://github.com/DeusData/codebase-memory-mcp
  (chọn 1 công cụ chính, còn lại giữ dự phòng — tránh trùng chức năng)

## 3. Nén context / giảm token tổng thể
- headroom — nén tool output, log, file, RAG chunk trước khi vào context.
  https://github.com/headroomlabs-ai/headroom (dùng song song với nhóm #2, không thay thế)

## 4. Memory xuyên session
- agentmemory — nhớ context/quyết định qua nhiều session, có MCP + skill sẵn cho Claude Code.
  https://github.com/rohitg00/agentmemory

## 5. Skill thực chiến cho coding agent
- agent-skills (addyosmani): code review, TDD, interview requirements...
  https://github.com/addyosmani/agent-skills
- skills (mattpocock): dùng khi cần TỰ VIẾT skill mới đúng chuẩn.
  https://github.com/mattpocock/skills

## 6. Database (chỉ khi project có backend liên quan)
- PostgREST MCP (chỉ khi dùng Supabase/PostgREST):
  https://github.com/supabase/mcp (@supabase/mcp-server-postgrest)
- Postgres MCP Pro (Postgres thuần, cần tuning/EXPLAIN):
  https://github.com/crystaldba/postgres-mcp

## 7. Multi-agent / song song hoá (project lớn)
- orca: https://github.com/stablyai/orca
- agency-agents: https://github.com/msitarzewski/agency-agents

## 8. Research agent (chỉ khi project cần thu thập dữ liệu web)
- Agent-Reach: https://github.com/Panniantong/Agent-Reach
- cloakbrowser (chỉ khi cần crawl có chống fingerprint):
  https://github.com/CloakHQ/cloakbrowser

# Không đưa vào rule bắt buộc (ghi chú tham khảo)
- affaan-m/ecc — framework agent độc lập rất lớn, không phải tool bổ trợ. Chỉ cân nhắc nếu
  muốn thay đổi toàn bộ kiến trúc agent, không nên bật mặc định cho mọi project.
- nousresearch/hermes-agent — agent riêng biệt (không phải plugin Claude Code), có hệ
  memory/skill/learning loop của chính nó. Không tích hợp vào Claude Code, chỉ dùng độc lập
  nếu muốn thử agent khác.

---

# Trạng thái tích hợp trong CHÍNH dự án này (đo 2026-07-28)

Đừng tích hợp lại những thứ đã có. Kiểm chứng trước khi thêm.

| Công cụ | Trạng thái | Ở đâu |
|---|---|---|
| pdf-inspector | ĐÃ CÓ | `services/pdf_intent.py::markdown_pdf_so` — PDF SỐ → Markdown, lõi Rust chạy trong tiến trình, không gọi dịch vụ nào. Đường CHÍNH. |
| markitdown (#1) | ĐÃ CÓ | `services/pdf_intent.py` — nay là fallback thứ ba (sau pdf-inspector và PyMuPDF); vẫn là đường chính cho .docx/.pptx/.xlsx và HTML |
| Context7 (#1) | ĐÃ CÓ | `services/mcp_presets.py` — preset sẵn |
| headroom (#3) | ĐÃ CÓ | `services/protocol/openai_v1_chat_complete.py` |
| cloakbrowser (#8) | ĐÃ CÓ | `captcha-solver/src/browser_pool.py` |
| RTK (#2) | ĐÃ CÓ | hook toàn cục, xem `~/.claude/RTK.md` |
| skills mattpocock (#5) | ĐÃ CÓ | `.agents/skills/` — 38 skill |
| agentmemory (#4) | chưa | — |
| GitNexus / CodeGraph / Semble (#2) | chưa | nhóm này chọn 1, đã có RTK nên cân nhắc kỹ |
| Postgres MCP Pro (#6) | chưa | dự án dùng Postgres (`c2a-db`) nên có thể hợp |
| orca / agency-agents (#7) | chưa | — |
| Agent-Reach (#8) | chưa | đã có `federated_search` + `vn_search` MCP |

# HAI KHO SKILL TÁCH BIỆT — đừng nhầm

- `.agents/skills/` → skill cho **coding agent làm việc trên repo này** (Claude Code).
- `services/agent/skills_default/` + `data/agent/skills/` → skill cho **bot chạy thật**
  (trợ lý tiếng Việt: dạy học, điều khiển nhà, Zalo/Telegram).

Thêm skill vào kho này KHÔNG làm kho kia có. Skill của bot phải viết bằng tiếng Việt và
gọi đúng tên tool của bot (`control_home`, `search_sgk`, `teacher_grade`…), không phải
tool của Claude Code (`Read`, `Edit`, `Bash`).

Mỗi skill của bot tốn context MỖI LƯỢT chat: `services/agent/skills.py` giới hạn
`SKILL_DESC_MAX = 150` ký tự và có `max_list()` chặn số skill vào bộ định tuyến. Thêm
skill không dùng tới sẽ làm bot kém nhạy ở đúng việc nó đang làm.

# Bot tự học — bốn tầng, đừng sửa nhầm tầng

| Tầng | File | Trả lời câu gì |
|---|---|---|
| Ghi | `services/lich_su_nha.py` | chuyện gì đã xảy ra, lúc mấy giờ |
| Bối cảnh | `services/boi_canh_nha.py` | lúc ấy trong nhà thế nào |
| Xác suất | `services/du_doan_nha.py` | có nên bật / có nên báo không |
| Sổ lỗi | `services/bai_hoc.py` | câu nào bot từng trả lời sai |

**Ba bẫy đã đo được, đừng làm hỏng lại:**

1. **Không dùng bảng `tuoi` cho mốc quá khứ** — rò rỉ tương lai. Mô hình sẽ
   học "lux lúc bật đèn = lux bây giờ", đúng gần 100% trên dữ liệu cũ và vô
   dụng ngoài đời. `boi_canh()` cho quá khứ, `hien_tai()` cho bây giờ.
2. **Phải sinh mẫu ÂM** — log chỉ ghi cái đã xảy ra; không có mẫu âm thì mọi
   xác suất bằng 1.
3. **Học phải bỏ `do_ai=1`** — bot bật đèn rồi thấy đèn bật rồi tự khẳng định
   vòng quanh. Dùng `doc_cua_so(..., bo_do_ai=True)`.

**Mức tự chủ tự lên cấp, từng thiết bị**: đúng 19/20 lần VÀ đủ 50 lượt được
chấm thì mới tự làm; sai 2 lần trong 10 lượt gần nhất là tụt về hỏi lại. Khoá
cửa / bếp / bình nóng lạnh không bao giờ tự làm.

**Đo trên dữ liệu thật, đừng tin test suông**: `scripts/do_hoc_nha.py`. Cổng
chặn — tra ngược bối cảnh phải > 60%, kiểm tiến dần phải vượt 58,3%. Đo
10/09/2026: đèn bếp 74,2% so với 62,9% của mốc "luôn đoán không".

# Đưa bản sửa ra máy chủ — DÙNG SCRIPT, đừng gõ tay

```bash
scripts/day_va_dung.sh          # đẩy main → lo trọn vòng tới lúc ảnh lên GHCR
scripts/day_va_dung.sh --chi-dung        # bỏ qua đẩy code, chỉ dựng ảnh
scripts/day_va_dung.sh --khong-day-anh   # dựng thử, không đẩy
```

Script hỏi GitHub Actions trước; Actions dựng xong thì nó không làm gì thêm,
Actions hỏng (hoặc không hỏi được) thì mới dựng tại chỗ, gắn `:latest`, đẩy
GHCR, rồi dọn ảnh cũ giữ 3 bản gần nhất.

**Actions hiện KHÔNG dựng được** — đo 10/09/2026, ba lần gần nhất đều
`failure` vì *"recent account payments have failed or your spending limit needs
to be increased"*. Hết hạn mức tài khoản, không phải lỗi code. Nên đường thực
tế bây giờ luôn là dựng tại chỗ.

**Đẩy ảnh xong thì DỪNG.** Watchtower trên máy chủ quét mỗi 600 giây và tự kéo
về. Đừng thêm bước khởi động lại — hai đường cùng làm một việc là cách sinh ra
tình huống không ai truy được.

**Đĩa máy chủ chật**: mỗi ảnh 5,76 GB, còn 19/99 GB. Cron 0h00 chạy
`docker image prune -f` — **không cờ `-a`**, vì `-a` xoá luôn bản dự phòng để
lùi khi bản mới hỏng.

# Máy chủ chạy thật

- Host `172.16.10.38`, stack quản lý bằng **Portainer** (không phải `docker compose` trên
  host — `/root/c2a-build` KHÔNG phải bản git). Sửa compose trong Portainer → Stacks →
  Editor, và phải bật **Re-pull image** khi Update, nếu không nó dùng lại image cũ.
- Web UI là **static export nằm trong image**: sửa `.tsx` mà không build lại image thì
  giao diện không đổi.
- Sau khi khởi động lại máy, tường lửa có thể dựng lại iptables SAU Docker và xoá mất luật
  NAT của mạng `c2a_default` (`172.19.0.0/16`) → container mất đường ra Internet. Chữa:
  `systemctl restart docker`.
