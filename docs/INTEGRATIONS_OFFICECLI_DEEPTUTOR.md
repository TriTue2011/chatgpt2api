# Tích hợp OfficeCLI + DeepTutor vào ChatGPT2API

Hai lớp tích hợp **không merge source** vào monorepo runtime theo kiểu vendor copy; chúng gắn theo chuẩn stack hiện tại.

| Thành phần | Cách gắn | Ảnh hưởng c2a |
|------------|----------|---------------|
| **OfficeCLI** | Binary trong image + capability `office_*` NATIVE trong agent (in-process, KHÔNG MCP) | Rebuild image |
| **DeepTutor** | Container sidecar, LLM trỏ OpenAI API của c2a | Không đụng `/opt/c2a-data` |

---

## 1. OfficeCLI (Word / Excel / PowerPoint cho agent)

**Kiến trúc: tích hợp TRỰC TIẾP** — agent gọi runner in-process
(`services/officecli.py` → subprocess binary), không đi qua vn-mcp-hub,
không cần bật preset MCP, không phụ thuộc dịch vụ ngoài lúc runtime.

### Đã có trong repo

- Runner native: `services/officecli.py` (sandbox path dưới `DATA_DIR/office`)
- Capability agent: `services/agent/capabilities.py` — 10 tool `office_*`, nhóm quyền `office`
- Gửi file thật: key `doc_path` (orchestrator → Telegram `sendDocument`,
  Zalo Cá nhân `sendFileByAccount`; Zalo Bot API không hỗ trợ file → fallback text)
- Dockerfile cài binary `officecli` (pin `OFFICECLI_VERSION`)
- Workspace file: `/app/data/office` (persist theo volume `/opt/c2a-data/office`)

### Deploy

```bash
# Trên host Docker (rebuild để có binary + capability mới)
cd /path/to/chatgpt2api
docker compose up -d --build
```

Không cần bật gì thêm trên dashboard — tool `office_*` có sẵn trong agent.
Thread có bật lọc chức năng: thêm nhóm `office` vào thread_filters.

### Tools chính

| Tool | Việc | Risk |
|------|------|------|
| `office_files` | Liệt kê workspace | read |
| `office_create` | Tạo `.docx` / `.xlsx` / `.pptx` | change |
| `office_view` / `office_query` | Đọc outline/text/issues, soi phần tử | read |
| `office_add` / `office_set` / `office_remove` | Soạn/sửa | change |
| `office_batch` | Nhiều lệnh 1 lần (soạn nội dung dài) | change |
| `office_merge` | Điền data vào template | change |
| `office_send` | GỬI file thật cho người dùng (`doc_path`) | read |

### Ranh giới với code sẵn có

- `pdf_to_word` / `pdf_to_excel`: **convert PDF → file** (giữ nguyên).
- OfficeCLI: **tạo / sửa / merge** Office sau convert hoặc từ đầu.

### Env (optional)

| Biến | Mặc định |
|------|----------|
| `OFFICECLI_BIN` | `/usr/local/bin/officecli` |
| `OFFICECLI_WORKSPACE` | `/app/data/office` |
| `OFFICECLI_SKIP_UPDATE` | `1` |

---

## 2. DeepTutor (app học, sidecar)

### Đã có trong repo

```text
deploy/deeptutor/
  docker-compose.yml
  .env.example
  seed_c2a_model.sh
  seed/README.md
```

### Deploy (cạnh c2a, data riêng)

```bash
cp deploy/deeptutor/.env.example deploy/deeptutor/.env
# Sửa C2A_BASE_URL + C2A_API_KEY (= CHATGPT2API_AUTH_KEY)

# Tạo volume data (không dùng /opt/c2a-data)
sudo mkdir -p /opt/deeptutor-data
sudo chown "$USER" /opt/deeptutor-data   # nếu cần

docker compose -f deploy/deeptutor/docker-compose.yml \
  --env-file deploy/deeptutor/.env up -d

# Seed model profile (chỉ khi chưa có model_catalog.json)
bash deploy/deeptutor/seed_c2a_model.sh
docker restart deeptutor   # nếu container đã chạy
```

Mở **http://\<IP\>:3782** → **Settings → Models** → xác nhận Base URL trỏ c2a và model (vd `cx/auto`).

### Mạng

| Tình huống | `C2A_BASE_URL` |
|------------|----------------|
| Cùng host Docker | `http://host.docker.internal:3030/v1` |
| LAN (c2a `172.16.10.38:3030`) | `http://172.16.10.38:3030/v1` |

DeepTutor **không** thay module Teacher / RAG VN trong c2a — dùng song song khi cần tutor đầy đủ (KB, memory, quiz, Partners).

### Tắt / gỡ

```bash
docker compose -f deploy/deeptutor/docker-compose.yml --env-file deploy/deeptutor/.env down
# Giữ data: không xóa /opt/deeptutor-data
# Xóa hẳn: sudo rm -rf /opt/deeptutor-data
```

---

## 3. Checklist sau deploy

- [ ] Trong container: `officecli --version` chạy được (binary có trong image)
- [ ] Chat bot thử: "tạo file bao_cao.docx" → agent gọi `office_create`, rồi "gửi file" → nhận file thật
- [ ] File xuất hiện dưới `/opt/c2a-data/office`
- [ ] DeepTutor UI `:3782` load
- [ ] DeepTutor chat gọi model qua c2a (quota / log c2a tăng)

---

## 4. Không làm

- Không vendor-merge source DeepTutor / OfficeCLI vào `services/`
- Không force-recreate c2a “cho vui” — chỉ rebuild khi cần binary/MCP mới
- Không trộn volume DeepTutor vào `/opt/c2a-data`
