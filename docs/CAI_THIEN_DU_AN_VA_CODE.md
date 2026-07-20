# Cải thiện dự án ChatGPT2API — Đề xuất + Code thay đổi

> Brand UI: nền đen–xanh + viền vàng ánh kim (tham chiếu `D:\Chatgpt\cv`).
> File này = **đề xuất toàn dự án** + **code copy/apply**.
> Component mới cũng được tạo riêng dưới `web/src/components/`.

---

# PHẦN A — ĐỀ XUẤT CẢI THIỆN DỰ ÁN

## A1. Web UI

| # | Đề xuất | File |
|---|---------|------|
| 1 | Design system Obsidian Blue + Gold Metal | `web/src/app/globals.css` |
| 2 | Sidebar nhóm mục + active gold | `web/src/components/sidebar.tsx` |
| 3 | Header / avatar gold | `web/src/components/app-shell.tsx` |
| 4 | Login premium gold | `web/src/app/login/page.tsx` |
| 5 | Dashboard KPI + empty + chart palette | `web/src/app/page.tsx` + components mới |
| 6 | Settings nhóm tab (phase sau) | `web/src/app/settings/page.tsx` |

## A2. Backend / sản phẩm

| # | Đề xuất | File |
|---|---------|------|
| 1 | Đồng bộ feature-status (Anthropic `/v1/messages` đã có code) | `docs/feature-status.en.md` |
| 2 | Log startup thay `except: pass` | `api/app.py` |
| 3 | Lỗi not implemented → skip provider + message rõ | `services/openai_backend_api.py` |
| 4 | Token scheduling: weighted pool, circuit-breaker | `services/backend_router.py` |
| 5 | Image size parameters OpenAI-compatible | `services/protocol/openai_v1_image_*` |
| 6 | CORS configurable production | `api/app.py` |

## A3. Chất lượng & ops

1. Unit test `BackendRouter` + `AuthService`
2. CI GitHub Actions (pytest + web build)
3. Đồng bộ `VERSION` ↔ `pyproject.toml`
4. Document Docker lite (2GB) vs full (browser+VNC)
5. noVNC `:6080` không expose public không auth

## A4. Lộ trình

1. **Phase A:** UI tokens + shell + login + dashboard
2. **Phase B:** logging startup + feature-status
3. **Phase C:** tests + CI
4. **Phase D:** settings tabs + scheduling + image size

---

# PHẦN B — CODE ĐÃ ÁP DỤNG (tóm tắt trạng thái)

> Chi tiết code đầy đủ nằm trong chính các file nguồn (đã triển khai 2026-07-17).

| Hạng mục | Trạng thái | Ghi chú |
|----------|-----------|---------|
| B1 `stats-card.tsx` | ✅ | StatsCard 6 tone (gold/blue/emerald/red/violet/amber), loading skeleton, trend |
| B2 `page-header.tsx` | ✅ | eyebrow/title/description/actions |
| B3 `empty-state.tsx` | ✅ | icon + CTA, compact mode |
| B4 `status-pill.tsx` | ✅ | ok/warning/error/off/info theo biến theme |
| B5 `globals.css` | ✅ | :root kem+gold đậm, .dark Obsidian Blue #070b12 + gold #d4af37, viền rgba(212,175,55,0.14), .btn-gold + goldShimmer, .gradient-text gold, bento hover/accent gold |
| B6 `sidebar.tsx` | ✅ | navGroups 5 nhóm (Tổng quan/AI Core/Studio/Kênh/Hệ thống), logo + active gold, hỗ trợ drawer mobile |
| B7 `app-shell.tsx` | ✅ | header viền gold + Sparkles glow + avatar gold; THÊM: health pill (/api/v1/health, 60s), hamburger + backdrop + bottom-nav 5 mục mobile |
| B8 `login/page.tsx` | ✅ | mesh gold+blue, card viền gold, icon khóa gold, nút .btn-gold — logic giữ nguyên |
| B9 `page.tsx` | ✅ | KPI 4 StatsCard (Requests/Tokens/Chi phí/Accounts), NEON_COLORS gold-first, EmptyState có CTA cho 2 chart |
| B10 `api/app.py` logging | ✅ | 13 khối except:pass → logger.warning startup_step_failed |
| B11 `feature-status.en.md` | ✅ | Anthropic /v1/messages + image size → ✅ (khớp code) |

## Ngoài spec — đã làm thêm cùng đợt

- **Smart pool** (`services/provider_circuit.py`, `services/session_affinity.py`, weighted trong
  `account_service`/`openai_oauth`): circuit-breaker per provider + weighted account +
  sticky session; config `smart_pool` (enabled/weighted/sticky_ttl_seconds/circuit_threshold/
  circuit_open_seconds), tắt = hành vi cũ 100%. Expose vào `/api/v1/health`.
- **Tests + CI**: `test/test_backend_router.py`, `test_auth_service.py`, `test_provider_circuit.py`,
  `test_session_affinity.py`; job `test` (uv + pytest + bun tsc informational) chạy TRƯỚC build image.
- **Bảo mật**: CORS config `cors_allow_origins`; noVNC env `VNC_PASSWORD`; backup mã hóa
  Fernet PBKDF2 (passphrase optional ở `/api/v1/backup` + restore).
- **Docs**: README mục Docker Full vs Lite; pyproject version 1.2.14 + description thật;
  backend_router docstring 24KB→100KB.

# PHẦN C — CHECKLIST

```text
[x] Tạo stats-card / page-header / empty-state / status-pill
[x] Sửa globals.css (:root + .dark + utilities)
[x] Sửa sidebar.tsx (nhóm 5 mục + gold)
[x] Sửa app-shell.tsx (gold + health pill + mobile)
[x] Sửa login/page.tsx
[x] Sửa page.tsx (KPI + palette + empty)
[x] api/app.py logging
[x] feature-status.en.md
[x] CI: bun typecheck (informational) + pytest gate
[ ] Settings nhóm tab — phase sau
```

# PHẦN D — PATH

| Hành động | Path |
|-----------|------|
| TÀI LIỆU NÀY | `docs/CAI_THIEN_DU_AN_VA_CODE.md` |
| TẠO | `web/src/components/stats-card.tsx` |
| TẠO | `web/src/components/page-header.tsx` |
| TẠO | `web/src/components/empty-state.tsx` |
| TẠO | `web/src/components/status-pill.tsx` |
| SỬA | `web/src/app/globals.css` |
| SỬA | `web/src/components/sidebar.tsx` |
| SỬA | `web/src/components/app-shell.tsx` |
| SỬA | `web/src/app/login/page.tsx` |
| SỬA | `web/src/app/page.tsx` |
| SỬA (ops) | `api/app.py` |
| SỬA (doc) | `docs/feature-status.en.md` |
