# Gỡ Grok Web + Phạt nguội — nhật ký cho agent / Claude

**Ngày:** 2026-07-17  
**Lý do:** Grok Web không vượt Cloudflare managed challenge trên VPS; user yêu cầu xóa code Grok. Sau đó yêu cầu gỡ luôn Phạt nguội.  
**Trạng thái code local (Windows `d:\Chatgpt\chatgpt2api`):** đã commit `d8915274` và push `origin/main`.  
**Trạng thái server Ubuntu `192.168.1.10`:** **ĐÃ deploy** 2026-07-17 — image `c2a:latest` rebuild, container healthy, `/version` = `1.2.14`.

---

## 1. Server đã có chưa?

| Hạng mục | Server `c2a` (2026-07-17) | Local workspace |
|----------|---------------------------|-----------------|
| Image container | `c2a:latest`, healthy, Created ~08:16 UTC | N/A |
| Source `/root/chatgpt2api` | Vẫn có `grok/` prefix, `vn_phat_nguoi`, file `grok_web.py`, `phat_nguoi.py` | Đã gỡ |
| Trong container `c2a` | `captcha/src/solvers/grok_web.py`, `phatnguoi.py`; `mcp_hub/src/vn/phat_nguoi.py` còn | Đã gỡ |
| Git server | `9236fdd8…` — branch lệch origin (ahead 19 / behind 315) | `68fa75e0` + uncommitted removals |
| Deploy | **Chưa rebuild/push image, chưa sync source** | Cần `git commit` → build → deploy |

**Kết luận:** Server **chưa** chạy bản gỡ Grok/Phạt nguội. Muốn áp dụng: commit local → push/build GHCR hoặc rsync + `docker compose build/up` trên server.

---

## 2. Phạm vi đã gỡ

### A. Grok Web (`grok.com` reverse / captcha-solver)

**Không gỡ:** preset custom OpenAI-compatible **xAI official API** (`https://api.x.ai/v1`, prefix `xai`) trong Settings → Custom providers. Đó là API key chính thức, không phải browser scrape.

**Đã gỡ / unwire:**

| Loại | Chi tiết |
|------|----------|
| Provider key | `grok_web` |
| Model prefix | `grok/`, `grok_web/` (router); catalog `grok/*`, `gw` pool group |
| Captcha API | `/v1/grok-web/*` (chat, models, cookies, login/onboard…) |
| UI | Grok Web card, reuse Grok trong Google providers, nhánh Accounts/Models |
| Infra Grok-only | Theyka Turnstile (nếu còn local uncommitted: Dockerfile clone, supervisord `theyka`, env `CAPTCHA_SOLVER_THEYKA_*`) — **file `external_turnstile.py` / `theyka-start.sh` không có trong HEAD git** (chỉ từng tồn tại working tree / image build thử) |

### B. Phạt nguội

| Loại | Chi tiết |
|------|----------|
| MCP | `vn_phat_nguoi` (mount, label, preset UI) |
| Captcha API | `POST /v1/forms/phatnguoi` |
| Routing chat | keyword MCP `phat nguoi` / `bien so xe`; domain tool `phạt nguội`, `biển số` |
| Profile filter UI | `phatnguoi`, `phatnguoi-manual` |

---

## 3. File đã XÓA (delete)

Khôi phục từ git: `git show HEAD:<path>` hoặc `git checkout HEAD -- <path>`.

| File | Vai trò (tóm tắt) | ~dòng (HEAD) |
|------|-------------------|--------------|
| `captcha-solver/src/solvers/grok_web.py` | Chat/list models grok.com qua Playwright + bridge JS intercept API | ~505 |
| `captcha-solver/src/grok_web_login.py` | Login/onboard Grok (Google OAuth / session) | ~472 |
| `captcha-solver/src/solvers/phatnguoi.py` | Submit form phatnguoi.vn + Turnstile + scrape kết quả | ~201 |
| `vn-mcp-hub/src/vn/phat_nguoi.py` | MCP tra cứu phạt nguội (checkphatnguoi + phatnguoi API + fallback captcha-solver) | ~480 |
| `web/src/app/settings/components/grok-web-card.tsx` | UI card onboard/config Grok Web | ~471 |

**Tổng file xóa tracked:** ~2.1k+ LOC (cộng edits unwire ≈ −2.4k net trong working tree).

---

## 4. File đã SỬA (unwire, không xóa cả file)

### Gateway / protocol

| File | Gỡ gì |
|------|--------|
| `services/backend_router.py` | Prefix `"grok/"` → `grok_web`, `"grok_web/"` → `grok_web`; docstring |
| `services/providers/web_proxy.py` | Toàn bộ `handle_grok_web_chat()` (~50 dòng) |
| `services/protocol/openai_v1_chat_complete.py` | Branch `route.provider == "grok_web"`; keyword `phạt nguội`/`biển số` |
| `services/protocol/openai_v1_models.py` | Fallback models `grok_web`, `_fetch_grok_web_models`, pool `"gw"`, always_allow `grok/*`, static list gw_models, `_DYNAMIC_PREFIXES` bỏ `gw/` |
| `api/accounts.py` | `_WEB_PROVIDER_KEYS` bỏ `grok_web`; excluded_types; nhánh provider-tree Grok |
| `services/mcp_presets.py` | Preset `vn_phat_nguoi` |
| `services/mcp_client.py` | Intent keyword tuple phạt nguội |

### Captcha-solver

| File | Gỡ gì |
|------|--------|
| `captcha-solver/src/main.py` | Import + models + endpoints Grok Web + PhatNguoi; multi-service onboard `grok_web`; message/sync-cookies grok |
| `captcha-solver/src/accounts_db.py` | Prefix profile `grok-web-` / `grok-` |
| `captcha-solver/src/browser_pool.py` | Comment Grok proxy (giữ proxy generic) |
| `captcha-solver/src/settings.py` | (nếu dirty) bỏ Theyka/odell env defaults gắn Grok |
| `captcha-solver/README.md`, `README.vi.md` | Section phatnguoi + mention grok/CF |

### VN MCP Hub

| File | Gỡ gì |
|------|--------|
| `vn-mcp-hub/src/main.py` | `MCP_LABELS` + `MOUNTS` `vn_phat_nguoi`; docstring URL |
| `vn-mcp-hub/src/rag/telegram_bot.py` | Prompt/help bỏ “phạt nguội” |
| `vn-mcp-hub/README.md` | Danh sách MCP 8→7, bỏ hàng `vn_phat_nguoi` |

### Web UI

| File | Gỡ gì |
|------|--------|
| `web/src/app/settings/components/google-providers-card.tsx` | State/reuseGrok/card Grok; reuse-all bỏ Grok |
| `web/src/app/accounts/page.tsx` | Branch tree `grok_web`; type unions; render instances |
| `web/src/app/models/page.tsx` | Label `grok_web`; `CORE_MODELS` bỏ `grok/auto` |
| `web/src/app/mcp/page.tsx` | MCP `vn_phat_nguoi` khỏi nhóm Tìm kiếm |
| `web/src/app/settings/components/reuse-profile-picker.tsx` | Filter `phatnguoi*` |

### Deploy / docs

| File | Gỡ gì |
|------|--------|
| `Dockerfile` | Theyka clone/deps/env (nếu có trong dirty tree) |
| `deploy/supervisord.conf` | `[program:theyka]`, env THEYKA |
| `deploy/extra-requirements.txt` | `quart`, `camoufox` (Theyka) |
| `docker-compose.yml` | Env Theyka |
| `README.md`, `README.vi.md` | Theyka / MCP count / Phạt nguội |

### Cache / data (local)

| File | Gỡ gì |
|------|--------|
| `data/models_cache.json` | ~10 entry model `grok/*` / owned_by grok |

---

## 5. API / endpoint đã xóa (không còn route)

### Captcha-solver (trước đây)

- `POST /v1/forms/phatnguoi`
- `POST /v1/grok-web/chat` (và các route login/onboard/2fa nếu có trong HEAD)
- `GET /v1/grok-web/{profile}/models`
- `GET /v1/grok-web/{profile}/cookies`
- (các route sync-cookies / import cookies Grok nếu từng thêm ngoài HEAD)

### MCP Hub

- `http://…:8005/vn_phat_nguoi/mcp` — **không mount**

### Gateway chat

- Model id `grok/...` **không còn route** tới provider (sẽ fail prefix / unknown provider)

---

## 6. Symbol / hàm đã xóa (tham chiếu)

| Symbol | File cũ |
|--------|---------|
| `handle_grok_web_chat` | `services/providers/web_proxy.py` |
| `_fetch_grok_web_models` | `services/protocol/openai_v1_models.py` |
| `lookup_phatnguoi` | `captcha-solver/src/solvers/phatnguoi.py` |
| `grok_web_chat` / `list_models` (solver) | `captcha-solver/src/solvers/grok_web.py` |
| `start_grok_web_login`, `get_session`, … | `captcha-solver/src/grok_web_login.py` |
| MCP tools trong `vn_phat_nguoi` (`check_traffic_violation`, …) | `vn-mcp-hub/src/vn/phat_nguoi.py` |
| `GrokWebCard` | `web/.../grok-web-card.tsx` |
| `reuseGrok` | `google-providers-card.tsx` |

---

## 7. Còn lại cố ý

- `utils/turnstile.py` + captcha `solve/turnstile` — OpenAI Sentinel / generic CF, **không** phải Grok.
- Custom provider preset **xAI (Grok)** → API chính thức.
- Turnstile solver browser + 2captcha — dùng chỗ khác nếu cần.
- Profile Chrome `google-*` trên disk — không xóa data server.

---

## 8. Việc còn lại khi deploy server

1. Commit working tree local (tránh commit `data/logs.jsonl`, `check.sh` rác nếu không cần).
2. Sync `/root/chatgpt2api` hoặc build image từ commit mới.
3. Rebuild `c2a:latest`, recreate container.
4. Runtime config (nếu còn):
   - Xóa `providers.grok_web` trong `config.json` / storage.
   - Gỡ MCP server `vn_phat_nguoi` đã install trong UI (nếu có).
5. Không cần Theyka process nếu image mới không embed.

---

## 9. Cho Claude / agent sau

- **Đọc file này trước** khi ai hỏi “Grok đâu rồi / phạt nguội đâu rồi”.
- **Không** thêm lại Grok Web scrape / Theyka-for-Grok trừ khi user yêu cầu rõ + có residential proxy / profile desktop-warmed.
- **Không** thêm lại `vn_phat_nguoi` trừ khi user yêu cầu.
- Muốn xem code cũ: `git show HEAD:<path-file-đã-xóa>` (trước khi commit xóa; sau commit xóa dùng parent commit).

**Evidence server chưa deploy (snippet 2026-07-17):**

```
# /root/chatgpt2api/services/backend_router.py vẫn:
"grok/": "grok_web",
"grok_web/": "grok_web",

# container c2a vẫn có:
captcha/src/solvers/grok_web.py
captcha/src/solvers/phatnguoi.py
mcp_hub/src/vn/phat_nguoi.py
```
