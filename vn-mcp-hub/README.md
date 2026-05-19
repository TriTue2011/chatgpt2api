# VN MCP Hub

Self-hosted Docker hub chứa **16 MCP servers** custom phục vụ user Việt Nam,
chạy bên cạnh `chatgpt2api`.

## Mục đích

`chatgpt2api` chỉ kết nối được với MCP có HTTP endpoint công khai (~5% trong 8000+
MCPs trên mcpservers.org). Hub này tự host các MCP custom với privacy đảm bảo,
không phụ thuộc third-party như Smithery.

## 16 MCPs có sẵn

### VN core (4)
| MCP | Mô tả | Use case |
|-----|-------|----------|
| `vn_weather` | Thời tiết VN qua wttr.in | "thời tiết Hà Nội" |
| `vn_news` | RSS aggregator báo VN | "tin nóng hôm nay" |
| `vn_currency` | Tỷ giá VCB + giá vàng SJC | "tỷ giá USD", "giá vàng" |
| `vn_lunar` | Lịch âm + can chi | "hôm nay ngày âm bao nhiêu" |

### VN extended (4)
| MCP | Mô tả | Use case |
|-----|-------|----------|
| `vn_search` | DuckDuckGo HTML scrape | tìm web tiếng Việt |
| `vn_law` | thuvienphapluat.vn | "Luật Doanh nghiệp 2020" |
| `vn_phat_nguoi` | csgt.vn (manual capcha) | "biển 30A-12345" |
| `vn_stock` | VNDirect public API | "giá VNM hôm nay" |

### General (3)
| MCP | Mô tả | Use case |
|-----|-------|----------|
| `youtube` | Transcript YouTube | "tóm tắt video X" |
| `wikipedia` | REST API multi-lang | "Albert Einstein là ai" |
| `arxiv` | Paper khoa học | "paper LLM mới nhất" |

### Knowledge base (4 RAG)
| MCP | Mô tả | Source |
|-----|-------|--------|
| `kb_dien_nuoc` | Kỹ thuật điện, nước, điều hòa, chiller | `data/dien_nuoc/*.md` |
| `kb_y_te` | Y tế cơ bản (tham khảo) | `data/y_te/*.md` |
| `kb_giao_duc` | Giáo dục VN | `data/giao_duc/*.md` |
| `kb_ngoai_ngu` | Học ngoại ngữ | `data/ngoai_ngu/*.md` |

### HA helper (1)
| MCP | Mô tả |
|-----|-------|
| `ha_helper` | Giờ hoàng đạo + check format câu lệnh HA voice |

## Triển khai

### 1. Build + run

```bash
cd vn-mcp-hub
docker compose up -d --build
```

Hub chạy ở `http://localhost:8001`. Health check: `curl http://localhost:8001/health`.

### 2. Ingest knowledge base (1 lần)

Sau khi container chạy, embed markdown trong `data/` vào Chroma DB:

```bash
docker exec vn-mcp-hub python -m src.rag.ingest
```

Cập nhật knowledge: thêm/sửa file `.md` trong `data/<collection>/`, chạy lại ingest.

### 3. Test endpoint

```bash
curl -X POST http://localhost:8001/vn_weather/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

### 4. Tích hợp vào chatgpt2api

Trên dashboard chatgpt2api → tab **MCP Servers** → **Thêm MCP server** thủ công:

| Field | Giá trị |
|-------|---------|
| Tên | (tuỳ chọn, vd "Thời tiết VN") |
| URL | `http://172.16.10.200:8001/vn_weather/mcp` |
| Transport | HTTP |
| API key | (để trống — hub không yêu cầu auth) |

Lặp lại cho từng MCP cần dùng (16 endpoints).

## Cấu trúc thư mục

```
vn-mcp-hub/
├── Dockerfile, pyproject.toml, docker-compose.yml
├── src/
│   ├── main.py                # FastAPI hub mount 16 sub-apps
│   ├── vn/                    # 8 MCPs VN
│   ├── general/               # 3 MCPs general
│   ├── kb/                    # 4 MCPs RAG
│   ├── ha/                    # 1 MCP HA
│   └── rag/                   # Chroma helpers + ingest
├── data/                       # Source markdown for RAG
│   ├── dien_nuoc/, y_te/, giao_duc/, ngoai_ngu/
└── chroma_db/                  # Persistent vector store (volume)
```

## Mở rộng knowledge base

1. Tạo file `data/<collection>/<topic>.md` (markdown thuần)
2. Chạy `docker exec vn-mcp-hub python -m src.rag.ingest`
3. Test query: `ask_dien_nuoc(question="...")`

Chunk size mặc định 800 ký tự với overlap 100 — đủ cho hầu hết technical content.

## Risks đã biết

| Risk | Mitigation hiện tại |
|------|---------------------|
| csgt.vn yêu cầu captcha | `vn_phat_nguoi` chỉ trả URL form, không tự bypass |
| VNDirect API đổi schema | `vn_stock` log warning + return friendly error |
| RSS báo VN đổi structure | `vn_news` tách feed, fail soft từng nguồn |
| Chroma khởi động chậm lần đầu | Lazy load, model multi-lang ~120 MB |

## License

Code: MIT. Markdown content trong `data/` là tham khảo, kiểm tra với chuyên gia
trước khi áp dụng (đặc biệt y tế và pháp luật).
