# Test OWNERS — 1 concern = 1 file (chống chồng chéo)

**Quy tắc:** Hành vi đã có owner → file khác **không** assert lại logic đó; chỉ dùng fake/fixture và kiểm concern riêng của mình.

**Seam:** mock thế giới ngoài chỉ qua [`_fakes.py`](_fakes.py) (S1…S8). Xem conftest markers: `pure` | `adapter` | `integration` | `e2e`.

CI gợi ý: `pytest -m "pure or adapter" -q`  
E2E: `pytest -m e2e --run-e2e`

---

## Sổ SEAM (8 ranh giới)

| ID | Biên | Fake trong `_fakes.py` |
|----|------|------------------------|
| S1 | Provider HTTP | `FakeProviderHttp`, `install_provider_http` |
| S2 | Home Assistant | `FakeHA`, `install_ha` |
| S3 | Loa socket | `FakeSocket`, `install_socket` |
| S4 | `call_model` | `FakeCallModel`, `install_call_model` |
| S5 | Storage / DATA_DIR | `tmp_data_dir`, `install_data_dir` |
| S6 | Bot Telegram/Zalo | `FakeBotAPI`, `install_bot_api` |
| S7 | MCP | `FakeMCP`, `install_mcp` |
| S8 | Doc/media (fitz…) | `FakeFitzDoc`, `install_fitz` (ưu tiên lib thật khi rẻ) |

---

## Sổ OWNER — concern → file test

| Concern | Owner DUY NHẤT | Ghi chú |
|---------|----------------|---------|
| Verbalize / emoji / đơn vị TTS | `test_verbalize.py` | |
| STT normalize (ALLCAPS, noise) | `test_voice_engines.py` | |
| Wyoming STT routing / lang | `test_voice_wyoming.py` | |
| Marker `image://` / PDF token gate / parse 1·2 | `test_pdf_intent.py` | |
| Privacy redact / vault / secret_ref | `test_privacy_gate.py` | |
| Auth key / roles (hash logic) | `test_auth_service.py` | Endpoint chỉ 401/200 |
| Backend route + circuit/cooldown | `test_backend_router.py`, `test_provider_circuit.py`, `test_session_affinity.py` | |
| `response_format` / vision JSON repair | `test_response_format.py`, `test_ha_json_strip.py` | |
| Channel contacts / alias / new-chat | `test_channel_contacts.py` | |
| Agent phases / session / skills / reminders / wiki | `test_agent_phase_*`, `test_agent_session.py`, … | |
| Teacher (tạm gộp; sẽ tách sau) | `test_teacher.py` | Đợt sau: assess/classroom/… |
| Image tasks / v1 images | `test_image_*`, `test_v1_images_*` | |
| Config load/merge | `test_config.py` | |
| Account image capabilities | `test_account_image_capabilities.py` | |
| HA service schema | `test_ha_service_schema.py` | |
| HA/GMA pool helpers | `test_ha_gma_optimize.py` | |
| **Fake registry smoke** | `test_fakes_smoke.py` | Đợt 0 |

### Owner dự kiến (chưa có file — Đợt 1+)

| Concern | Owner tương lai | Seam |
|---------|-----------------|------|
| Approval CHANGE gate | `test_approval_gate.py` | S4, S2 |
| Injection guard (prompt PDF) | `test_injection_guard.py` | S4 |
| Content filter | `test_content_filter.py` | — |
| Per-bot notify toggle | `test_notifier.py` | S6 |
| Photo caption intent | `test_photo_intent.py` | S4 |
| Thread filters | `test_thread_filter.py` | S5 |
| TG / Zalo / Zalop transport | `test_channel_telegram.py` / `_zalo` / `_zalop` | S6, S4 |
| Agent channel prefix / branches | `test_agent_channel.py`, `test_branches.py` | S4 |
| ha_client | `test_ha_client.py` | S2 |
| Speakers / R1 / announce | `test_speakers.py`, `test_r1.py`, `test_announce.py` | S3 |
| MCP client | `test_mcp_client.py` | S7 |
| Provider per-name | `test_provider_<name>.py` | S1 |

---

## Ranh giới bot (Tele / Zalo / Tiểu Vi)

| Lớp | Owner | Không kiểm |
|-----|--------|------------|
| Transport kênh | `test_channel_*` | intent PDF, approval gate |
| Intent chung | `test_pdf_intent`, `test_photo_intent`, `test_notifier`, `test_thread_filter` | send API Zalo/TG |
| Agent Tiểu Vi | `test_agent_*`, `test_approval_gate`, `test_branches` | webhook/send |

---

## Khi thêm test mới

1. Concern đã có trong bảng? → dùng lại owner / fixture.  
2. Cần mạng/HA/bot? → seam S1–S8, đánh dấu `adapter`.  
3. Pure function? → `pure`, không patch.  
4. PR description: nêu owner concern + seam dùng.
