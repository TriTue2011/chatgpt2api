# Quy tắc làm việc chung

- Khi không chắc chắn về yêu cầu, hỏi lại thay vì đoán.
- Thay đổi lớn luôn lên kế hoạch và xem xét các vấn đề trước khi code.

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

# Máy chủ chạy thật

- Host `172.16.10.38`, stack quản lý bằng **Portainer** (không phải `docker compose` trên
  host — `/root/c2a-build` KHÔNG phải bản git). Sửa compose trong Portainer → Stacks →
  Editor, và phải bật **Re-pull image** khi Update, nếu không nó dùng lại image cũ.
- Web UI là **static export nằm trong image**: sửa `.tsx` mà không build lại image thì
  giao diện không đổi.
- Sau khi khởi động lại máy, tường lửa có thể dựng lại iptables SAU Docker và xoá mất luật
  NAT của mạng `c2a_default` (`172.19.0.0/16`) → container mất đường ra Internet. Chữa:
  `systemctl restart docker`.
