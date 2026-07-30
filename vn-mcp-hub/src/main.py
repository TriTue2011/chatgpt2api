"""VN MCP Hub — entry point.

Mounts 16 custom MCP servers under one FastAPI app on port 8005.

Each MCP exposes its own JSON-RPC endpoint at /<name>/mcp using the
Streamable HTTP transport. chatgpt2api connects to these endpoints
exactly like any other public HTTP MCP.

URLs (replace <host> with your server IP and <port> with mapped host port):
- VN core:        http://<host>:<port>/vn_weather/mcp
                  http://<host>:<port>/vn_news/mcp
                  http://<host>:<port>/vn_currency/mcp
                  http://<host>:<port>/vn_lunar/mcp
- VN extended:    http://<host>:<port>/vn_search/mcp
                  http://<host>:<port>/vn_law/mcp
                  http://<host>:<port>/vn_stock/mcp
- General:        http://<host>:<port>/youtube/mcp
                  http://<host>:<port>/wikipedia/mcp
                  http://<host>:<port>/arxiv/mcp
- Knowledge:      http://<host>:<port>/kb_dien_nuoc/mcp
                  http://<host>:<port>/kb_y_te/mcp
                  http://<host>:<port>/kb_giao_duc/mcp
                  http://<host>:<port>/kb_ngoai_ngu/mcp
- HA helper:      http://<host>:<port>/ha_helper/mcp
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager, AsyncExitStack
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("vn-mcp-hub")


# MCP app instances collected during mount — their lifespans are entered
# in the parent FastAPI lifespan so FastMCP's session manager initializes.
_mcp_sub_apps: list = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting VN MCP Hub on port 8005")
    async with AsyncExitStack() as stack:
        for _mcp_app in _mcp_sub_apps:
            if hasattr(_mcp_app, "lifespan"):
                try:
                    await stack.enter_async_context(_mcp_app.lifespan(_mcp_app))
                except Exception:
                    pass
        # Auto-ingest synchronously before yielding
        if not os.environ.get("SKIP_AUTO_INGEST"):
            try:
                from src.rag import ingest
                ingest.main()
            except Exception as exc:
                logger.warning("Auto-ingest failed (non-fatal): %s", exc)
        # Restore RAG data from R2 (if configured) — pulls latest KB collections
        try:
            from src.rag.cloud import restore_all_from_r2
            restored = restore_all_from_r2()
            if restored > 0:
                logger.info("R2: restored %d chunks from cloud", restored)
        except Exception as exc:
            logger.warning("R2 restore failed (non-fatal): %s", exc)
        # Start background auto-update scheduler
        _scheduler_stop = None
        try:
            from src.rag.scheduler import start_scheduler
            _scheduler_stop = start_scheduler()
        except Exception as exc:
            logger.warning("Scheduler failed to start: %s", exc)
        # Register Telegram webhook if token configured
        try:
            from src.rag.telegram_bot import register_webhook
            register_webhook()
        except Exception as exc:
            logger.warning("Telegram webhook register failed: %s", exc)
        yield
        if _scheduler_stop is not None:
            _scheduler_stop.set()
    logger.info("Shutting down VN MCP Hub")


def create_app() -> FastAPI:
    """Build the parent FastAPI app with all 16 MCPs mounted as sub-apps."""
    app = FastAPI(
        title="VN MCP Hub",
        version="0.1.0",
        description="16 custom MCP servers for Vietnamese chatgpt2api users",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def index():
        mcps = []
        for name, _ in MOUNTS:
            label, desc, *rest = MCP_LABELS.get(name, (name, "", ""))
            cat = rest[0] if rest else "general"
            mcps.append({"id": name, "label": label, "description": desc,
                         "category": cat, "url": f"/{name}/mcp"})
        return JSONResponse({
            "name": "VN MCP Hub",
            "version": "0.1.0",
            "mcps": [name for name, _ in MOUNTS],
            "mcp_details": mcps,
            "endpoint_pattern": "/<name>/mcp",
        })

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # ── Studio endpoints ────────────────────────────────────────────────
    # The standalone /studio HTML page has been retired: its settings now live
    # in the chatgpt2api web MCP tab, which drives these /api/studio/* +
    # /api/rag/* endpoints via the in-container proxy (/api/mcp/hub/...).

    @app.get("/api/studio/mcps")
    async def studio_list_mcps():
        try:
            from src.studio import list_dynamic_mcps as _ldm
            dynamic = _ldm()
        except Exception:
            dynamic = []
        all_mcps = []
        for name, _ in MOUNTS:
            all_mcps.append({"name": name, "builtin": True})
        for d in dynamic:
            all_mcps.append({**d, "builtin": False})
        return {"mcps": all_mcps}

    @app.post("/api/studio/kb")
    async def studio_create_kb(request: Request):
        try:
            body = await request.json()
            from src.studio import create_kb as _create
            return _create(
                name=str(body.get("name", "")),
                label=str(body.get("label", "")),
                markdown_content=str(body.get("content", "")),
            )
        except Exception as exc:
            return {"ok": False, "errors": [str(exc)]}

    @app.get("/api/studio/sources")
    async def studio_get_sources():
        """Return per-MCP source toggle config with help text."""
        from src.sources_config import get_all_with_help
        return {"sources": get_all_with_help()}

    @app.post("/api/studio/sources/{mcp_name}")
    async def studio_toggle_source(mcp_name: str, request: Request):
        """Toggle one source for a MCP. Body: {source_name: true/false}"""
        body = await request.json()
        from src.sources_config import set_source as _set
        for src, enabled in (body or {}).items():
            if isinstance(src, str) and isinstance(enabled, bool):
                return {"ok": True, "mcp": mcp_name, "sources": _set(mcp_name, src, enabled)}
        return {"ok": False, "error": "Invalid body"}

    @app.get("/api/studio/collection/{name}/meta")
    async def studio_collection_meta(name: str):
        """Get collection metadata (timestamp, interval, auto_update)."""
        from src.rag.meta import read_meta, get_age_str
        meta = read_meta(name)
        return {"name": name, "meta": meta, "age": get_age_str(name)}

    @app.get("/api/rag/export/{collection}")
    async def rag_export(collection: str):
        """Export a Chroma collection as JSON (for n8n, external apps)."""
        from src.rag.meta import read_meta
        from src.rag.retriever import RAGRetriever
        retriever = RAGRetriever.get()
        if not retriever._ensure_loaded():
            return {"error": "Chroma not loaded"}
        col = retriever._get_collection(collection)
        if col is None or col.count() == 0:
            return {"collection": collection, "chunks": [], "count": 0}
        data = col.get()
        chunks = []
        for i, doc in enumerate(data.get("documents") or []):
            meta = (data.get("metadatas") or [{}])[i]
            chunks.append({"id": (data.get("ids") or [""])[i], "text": doc,
                          "source": (meta or {}).get("source", "")})
        meta = read_meta(collection)
        return {"collection": collection, "count": len(chunks),
                "last_updated": meta.get("last_updated"), "chunks": chunks}

    @app.post("/api/rag/upload/{collection}")
    async def rag_upload_r2(collection: str):
        """Upload a collection to Cloudflare R2 (Using 2-Way Sync)."""
        from src.rag.cloud import sync_collection_2way
        ok = sync_collection_2way(collection)
        return {"ok": ok, "collection": collection}

    @app.post("/api/rag/refresh/{collection}")
    async def rag_force_refresh(collection: str):
        """Force manual AI refresh for a specific collection."""
        from src.rag.scheduler import _run_refresh, _get_refresh_queries
        from src.rag.meta import read_meta, touch
        import threading
        
        def _do_refresh():
            meta = read_meta(collection)
            queries = _get_refresh_queries(collection, meta)
            total = _run_refresh(collection, queries)
            if total > 0:
                from datetime import datetime, timezone
                touch(collection, chunks=total, source=f"manual_ai/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
                try:
                    from src.rag.cloud import sync_collection_2way
                    sync_collection_2way(collection)
                except Exception:
                    pass

        threading.Thread(target=_do_refresh, daemon=True).start()
        return {"ok": True, "message": "Dang chay ngam qua trinh AI tong hop..."}

    @app.get("/api/rag/models")
    async def rag_get_models():
        """Fetch available models from the configured API Base URL."""
        from src.rag.settings import read as read_settings
        import urllib.request
        import json
        
        from src.rag.settings import DEFAULT_API_BASE_URL
        settings = read_settings()
        base_url = settings.get("api_base_url", DEFAULT_API_BASE_URL).rstrip("/")
        api_key = settings.get("api_key", "")
        
        url = f"{base_url}/models"

        # Threadpool: urlopen là lời gọi CHẶN. Hub phục vụ TOÀN BỘ MCP tool
        # trên cùng một event loop, nên chặn ở đây là bot mất sạch tool trong
        # lúc chờ, chỉ vì một API base URL không phản hồi.
        def _fetch() -> bytes:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
            return urllib.request.urlopen(req, timeout=5).read()

        try:
            from fastapi.concurrency import run_in_threadpool
            data = json.loads((await run_in_threadpool(_fetch)).decode())
            models = [m["id"] for m in data.get("data", []) if "id" in m]
            return {"ok": True, "models": models}
        except Exception as e:
            return {"ok": False, "error": str(e), "models": ["cx/auto", "chatgpt/auto"]}

    from fastapi import Request
    import urllib.request
    import io


    def _ocr_pdf(filepath: str, max_pages: int = 0, dpi: int = 150) -> str:
        """Try OCR on a PDF using pytesseract + pdf2image. Returns empty string on failure.

        max_pages=0 means all pages.
        """
        try:
            from pdf2image import convert_from_path
            import pytesseract
        except ImportError:
            return ""

        try:
            if max_pages > 0:
                images = convert_from_path(filepath, first_page=1, last_page=max_pages, dpi=dpi)
            else:
                images = convert_from_path(filepath, dpi=dpi)
        except Exception:
            return ""

        if not images:
            return ""

        texts = []
        for i, img in enumerate(images):
            try:
                text = pytesseract.image_to_string(img, lang="vie+eng")
                if text.strip():
                    texts.append(f"[Trang {i+1}]\n{text.strip()}")
            except Exception:
                pass

        return "\n\n".join(texts)

    def _ocr_pdf_pages(filepath: str, first_page: int, last_page: int, dpi: int = 130) -> str:
        """OCR a specific page range. Returns text with page markers."""
        try:
            from pdf2image import convert_from_path
            import pytesseract
        except ImportError:
            return ""

        try:
            images = convert_from_path(filepath, first_page=first_page, last_page=last_page, dpi=dpi)
        except Exception:
            return ""

        texts = []
        for i, img in enumerate(images):
            page_num = first_page + i
            try:
                text = pytesseract.image_to_string(img, lang="vie+eng")
                if text.strip():
                    texts.append(f"[Trang {page_num}]\n{text.strip()}")
            except Exception:
                pass
        return "\n\n".join(texts)


    # ── Sổ job phân tích nguồn ────────────────────────────────────────────────
    # Vì sao cần job thay vì chờ trong một request: gateway proxy tới hub chỉ
    # chờ 180s (api/mcp_admin.py) và Cloudflare còn cắt sớm hơn (~100s). Một
    # quyết định 60 trang cần ~9 lượt gọi AI, tổng vài phút — chờ đồng bộ là
    # chắc chắn 504/524 rồi mất trắng công đã làm. Job cho phép trả job_id
    # ngay, UI hỏi thăm tiến độ, và kết quả không bị mất vì đường truyền.
    import threading as _threading
    import time as _time
    import uuid as _uuid

    _ANALYZE_JOBS: dict[str, dict] = {}
    _ANALYZE_LOCK = _threading.Lock()
    _JOBS_KEEP = 20
    # Giữ tham chiếu task đang chạy — asyncio chỉ giữ weakref, task bị GC giữa
    # đường thì job đứng mãi ở "running" mà không ai biết vì sao.
    _ANALYZE_TASKS: set = set()
    # Chờ trong request bao lâu trước khi chuyển sang chế độ hỏi thăm. Phải nằm
    # dưới cả hai trần: proxy gateway 180s và Cloudflare ~100s.
    _ANALYZE_WAIT_S = 45.0

    def _job_new() -> str:
        job_id = _uuid.uuid4().hex[:16]
        with _ANALYZE_LOCK:
            _ANALYZE_JOBS[job_id] = {
                "status": "running", "started": _time.time(),
                "batches_done": 0, "batches_total": 0, "stage": "đang trích văn bản",
            }
            # Giữ số job có hạn — job xong vẫn giữ markdown trong RAM.
            if len(_ANALYZE_JOBS) > _JOBS_KEEP:
                old = sorted(_ANALYZE_JOBS, key=lambda k: _ANALYZE_JOBS[k].get("started", 0))
                for k in old[:-_JOBS_KEEP]:
                    _ANALYZE_JOBS.pop(k, None)
        return job_id

    def _job_set(job_id: str, **kw) -> None:
        with _ANALYZE_LOCK:
            job = _ANALYZE_JOBS.get(job_id)
            if job is not None:
                job.update(kw)

    def _job_get(job_id: str) -> dict | None:
        with _ANALYZE_LOCK:
            job = _ANALYZE_JOBS.get(job_id)
            return dict(job) if job else None

    def _pdf_page_count(path: str) -> int:
        """Số trang PDF (best-effort) — để báo độ phủ thật, 0 nếu không đọc được."""
        try:
            from pypdf import PdfReader
            return len(PdfReader(path).pages)
        except Exception:
            pass
        try:
            from pdfminer.pdfpage import PDFPage
            with open(path, "rb") as fh:
                return sum(1 for _ in PDFPage.get_pages(fh))
        except Exception:
            return 0

    # Trần số lượt: 60 × 12000 ≈ 720k ký tự (~400 trang). Vượt thì báo THẲNG
    # trong kết quả kèm số ký tự đã/chưa xử lý — không bao giờ cắt im lặng nữa.
    _AI_MAX_BATCHES = 60

    def _studio_analyze_source_sync(url_str: str, has_file: bool,
                                    content: bytes, filename_raw: str,
                                    job_id: str = ""):
        """Thân CHẶN của analyze_source — chạy trong threadpool.

        Hub phục vụ TOÀN BỘ MCP tool trên một event loop; hàm này tải URL,
        chạy markitdown/OCR rồi gọi AI tổng hợp — nhiều phút. Bản cũ chạy
        thẳng trong `async def` nên suốt thời gian đó hub đứng hình: bot mất
        sạch tool, y hệt vụ import-url làm treo gateway. Route async bên dưới
        chỉ đọc form (việc bắt buộc phải await) rồi đẩy hết sang đây.

        job_id: có thì ghi tiến độ từng lượt vào sổ job để UI hỏi thăm được.
        """
        def _tick(**kw):
            if job_id:
                _job_set(job_id, **kw)

        n_pages = 0
        try:
            url_str = str(url_str or "")
            filename = (filename_raw or "").lower()

            raw_text = ""
            source_type = "unknown"
            ext = ""
            # Khởi tạo TRƯỚC mọi nhánh: bản cũ chỉ gán trong nhánh markitdown,
            # nên nguồn URL / file text thường chết NameError ở khúc tổng hợp
            # (lỗi có sẵn từ trước, lộ ra khi đọc lại toàn hàm để tách luồng).
            _used_ocr = False

            if url_str and url_str.strip():
                source_type = "url"
                try:
                    from bs4 import BeautifulSoup
                except ImportError:
                    return {"ok": False, "error": "Thiếu thư viện beautifulsoup4. Vui lòng build lại Docker."}

                req = urllib.request.Request(url_str, headers={"User-Agent": "Mozilla/5.0"})
                resp = urllib.request.urlopen(req, timeout=10)
                html = resp.read().decode("utf-8", errors="ignore")
                soup = BeautifulSoup(html, "html.parser")
                raw_text = soup.get_text(separator="\n", strip=True)
                if not raw_text.strip():
                    return {"ok": False, "error": "URL cung cấp không chứa nội dung văn bản (có thể là trang web trống, chống bot, hoặc chỉ chứa hình ảnh)."}

            elif has_file:
                source_type = "file"
                # content đã được await file.read() ở tầng async trước khi vào đây
                if not content:
                    return {"ok": False, "error": "File bạn tải lên rỗng (0 bytes)."}

                ext = filename.rsplit(".", 1)[-1] if "." in filename else ""

                import logging
                logger = logging.getLogger("vn-mcp-hub")
                logger.info("RAG upload: file=%s size=%d", filename, len(content))

                if filename.endswith((".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".csv", ".epub")):
                    try:
                        from markitdown import MarkItDown
                        import tempfile
                        import os as _os
                    except ImportError:
                        return {"ok": False, "error": "Thiếu thư viện markitdown. Vui lòng chạy lệnh: docker compose up -d --build"}

                    suffix = _os.path.splitext(filename)[1]
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(content)
                        tmp_path = tmp.name

                    # Đếm trang TRƯỚC khi xoá file tạm — số này để đối chiếu
                    # "PDF n trang" với lượng chữ trích được, nếu lệch nhiều
                    # thì biết ngay là tài liệu nhiều hình/bảng ảnh.
                    if filename.endswith(".pdf"):
                        n_pages = _pdf_page_count(tmp_path)

                    _used_ocr = False
                    try:
                        md = MarkItDown()
                        result = md.convert(tmp_path)
                        raw_text = result.text_content
                        if not raw_text or not raw_text.strip():
                            raw_text = ""
                            # Try OCR fallback for scanned/image-based PDFs
                            if filename.endswith(".pdf"):
                                logger.info("MarkItDown returned empty text, trying OCR for scanned PDF...")
                                ocr_text = _ocr_pdf(tmp_path)
                                if ocr_text and ocr_text.strip():
                                    raw_text = ocr_text
                                    _used_ocr = True
                                    logger.info("OCR extracted %d chars from scanned PDF", len(raw_text))
                    except Exception as e:
                        raw_text = ""
                        if filename.endswith(".pdf"):
                            logger.warning("MarkItDown failed for PDF (%s), trying OCR fallback", e)
                            try:
                                ocr_text = _ocr_pdf(tmp_path)
                                if ocr_text and ocr_text.strip():
                                    raw_text = ocr_text
                                    _used_ocr = True
                                    logger.info("OCR extracted %d chars from scanned PDF (fallback)", len(raw_text))
                            except Exception as ocr_e:
                                logger.warning("OCR also failed: %s", ocr_e)
                        if not raw_text:
                            return {"ok": False, "error": f"Lỗi phân tích định dạng file: {str(e)} (Có thể cần cài đặt thêm thư viện cho định dạng này)"}
                    finally:
                        if _os.path.exists(tmp_path):
                            _os.remove(tmp_path)

                    if not raw_text or not raw_text.strip():
                        if filename.endswith(".pdf"):
                            return {"ok": False, "error": "Đây là file PDF dạng ảnh chụp (scanned) không có lớp văn bản. Hãy dùng tính năng lưu file Word dưới dạng PDF hoặc dùng bản PDF gốc (không phải bản in ra rồi scan lại)."}
                        return {"ok": False, "error": "Không thể trích xuất văn bản từ file này."}
                else:
                    try:
                        raw_text = content.decode("utf-8", errors="ignore")
                    except Exception:
                        raw_text = content.decode("latin-1", errors="ignore")
                    if not raw_text.strip():
                        return {"ok": False, "error": "File văn bản không hợp lệ hoặc không có nội dung chữ."}
            else:
                return {"ok": False, "error": "Không nhận được URL hay File hợp lệ từ trình duyệt."}

            if not raw_text.strip():
                return {"ok": False, "error": "Lỗi không xác định: Không thể trích xuất văn bản từ nguồn."}

            from src.rag.scheduler import _synthesize_with_ai
            title_hint = filename_raw if has_file else (url_str or "unknown")

            import logging as _logging
            logger = _logging.getLogger("vn-mcp-hub")
            logger.info("Analyzing source: %s, extracted length: %d, pages: %d, ocr: %s",
                        title_hint, len(raw_text), n_pages, _used_ocr)

            # ── Tổng hợp: dài thì chia lượt, KHÔNG cắt ────────────────────────
            #
            # Bản cũ có hai nhánh và nhánh chạy nhiều lượt bị khoá sau điều kiện
            # `_used_ocr` — tức CHỈ PDF scan mới được xử lý đủ. PDF có lớp chữ
            # (markitdown đọc được → _used_ocr=False) rơi xuống nhánh dưới và bị
            # cắt còn `raw_text[:30000]`. Một quyết định 60 trang trích ra ~100k
            # ký tự thì mất ~70% tài liệu — im lặng, không cảnh báo, và mất đúng
            # phần cuối là các Phụ lục chứa toàn bộ giải pháp kỹ thuật.
            #
            # Giờ: dài là chia lượt, bất kể nguồn chữ đến từ đâu.
            from src.rag.ingest import split_for_ai
            segments = split_for_ai(raw_text)
            over_cap = len(segments) > _AI_MAX_BATCHES
            if over_cap:
                segments = segments[:_AI_MAX_BATCHES]
            chars_processed = sum(len(s) for s in segments)
            coverage = {
                "pages": n_pages,
                "chars_extracted": len(raw_text),
                "chars_processed": chars_processed,
                "batches_total": len(segments),
                "used_ocr": _used_ocr,
                "truncated": over_cap,
            }
            _tick(batches_total=len(segments), stage="đang tổng hợp", coverage=coverage)

            if len(segments) <= 1:
                query = (f"Phân tích và trình bày lại TOÀN BỘ nội dung nguồn "
                         f"({title_hint}) thành Markdown có cấu trúc.")
                synthesized = _synthesize_with_ai(query, raw_text, mode="document")
                _tick(batches_done=1)
                if synthesized and len(synthesized) >= 50:
                    return {"ok": True, "markdown": synthesized, "source_type": source_type,
                            "raw_fallback": False, **coverage}
                logger.warning("AI synthesis failed for '%s', giữ văn bản gốc", title_hint)
                # Giữ TRỌN văn bản gốc, không cắt 10k như trước: AI lỗi là lý do
                # để không cô đọng, chứ không phải lý do để mất tài liệu.
                return {"ok": True, "markdown": f"# {title_hint}\n\n{raw_text}",
                        "source_type": source_type, "raw_fallback": True,
                        "warning": ("AI tổng hợp thất bại. Kiểm tra Cài đặt RAG → "
                                    "AI tổng hợp RAG: API Base URL phải là "
                                    "http://127.0.0.1:80/v1 và API Key là khoá admin. "
                                    "Nội dung dưới đây là văn bản gốc chưa qua AI."),
                        **coverage}

            logger.info("Chia %d lượt AI cho tài liệu %d ký tự", len(segments), len(raw_text))
            parts: list[str] = []
            failed = 0
            for idx, seg in enumerate(segments):
                label = f"{title_hint} — phần {idx + 1}/{len(segments)}"
                out = _synthesize_with_ai(label, seg, mode="document")
                if out and len(out) >= 30:
                    parts.append(out)
                else:
                    # Lượt này AI trượt → giữ NGUYÊN đoạn gốc. Bản cũ giữ
                    # `chunk[:2000]` tức tự bỏ thêm phần còn lại của đoạn.
                    failed += 1
                    parts.append(f"<!-- AI trượt phần {idx + 1}, giữ văn bản gốc -->\n\n{seg}")
                _tick(batches_done=idx + 1)
                logger.info("Lượt %d/%d: %d ký tự", idx + 1, len(segments), len(parts[-1]))

            combined = f"# {title_hint}\n\n" + "\n\n".join(parts)
            warn = ""
            if failed == len(segments):
                # MỌI lượt trượt thì gần như chắc chắn không phải tại tài liệu:
                # sai API Base URL hoặc thiếu API Key ở Cài đặt RAG. Không nói
                # thẳng thì người dùng vẫn thấy "nạp xong, có chunks" và tưởng
                # bình thường, trong khi cả kho là văn bản thô chưa qua AI.
                warn = ("KHÔNG lượt nào gọi được AI (0/%d). Kiểm tra Cài đặt RAG → "
                        "AI tổng hợp RAG: API Base URL phải là http://127.0.0.1:80/v1 "
                        "và API Key là khoá admin. Nội dung dưới đây là văn bản gốc "
                        "chưa qua AI." % len(segments))
            elif over_cap:
                warn = (f"Tài liệu quá dài: chỉ xử lý {chars_processed}/{len(raw_text)} ký tự "
                        f"({_AI_MAX_BATCHES} lượt). Hãy tách file rồi nạp tiếp phần sau.")
            elif failed:
                warn = f"{failed}/{len(segments)} phần AI trượt — giữ văn bản gốc cho các phần đó."
            logger.info("Xong %d lượt, tổng %d ký tự markdown", len(parts), len(combined))
            return {"ok": True, "markdown": combined, "source_type": source_type,
                    "raw_fallback": False, "batches": len(parts), "batches_failed": failed,
                    **({"warning": warn} if warn else {}), **coverage}
        except Exception as exc:
            import logging as _logging
            _logging.getLogger("vn-mcp-hub").exception("analyze_source failed")
            return {"ok": False, "error": str(exc)}

    @app.post("/api/studio/analyze_source")
    async def studio_analyze_source(request: Request):
        """Read a file or URL, extract text, and use AI to synthesize it into Markdown for RAG.

        Tầng async CHỈ đọc form/file (việc bắt buộc phải await) — mọi việc
        nặng nằm ở _studio_analyze_source_sync chạy trong threadpool.
        """
        try:
            form = await request.form()
        except ImportError:
            return {"ok": False, "error": "Thiếu thư viện python-multipart. Vui lòng rebuild Docker: docker compose up -d --build"}
        except Exception as e:
            return {"ok": False, "error": f"Lỗi parse form data: {str(e)}"}

        file = form.get("file")
        url = form.get("url")
        url_str = str(url) if url else ""
        has_file = bool(file is not None and hasattr(file, "read"))
        content = b""
        filename_raw = ""
        if has_file:
            content = await file.read()
            filename_raw = file.filename or ""

        # Chạy nền + chờ có giới hạn. Tài liệu ngắn xong trong ngưỡng chờ thì
        # trả kết quả luôn (UI cũ vẫn dùng được y như trước). Tài liệu dài thì
        # trả job_id để UI hỏi thăm — thay vì chết ở proxy 180s / Cloudflare
        # ~100s rồi mất trắng mấy phút AI đã chạy.
        import asyncio

        job_id = _job_new()

        async def _run():
            try:
                res = await run_in_threadpool(
                    _studio_analyze_source_sync, url_str, has_file, content,
                    filename_raw, job_id,
                )
            except Exception as exc:  # threadpool có thể chết vì lý do ngoài hàm
                res = {"ok": False, "error": str(exc)}
            _job_set(job_id, status="done" if res.get("ok") else "error", result=res,
                     stage="hoàn tất" if res.get("ok") else "lỗi")

        task = asyncio.create_task(_run())
        # Giữ tham chiếu: task bị GC giữa đường là job treo ở "running" mãi.
        _ANALYZE_TASKS.add(task)
        task.add_done_callback(_ANALYZE_TASKS.discard)

        done, _ = await asyncio.wait({task}, timeout=_ANALYZE_WAIT_S)
        job = _job_get(job_id) or {}
        if done and isinstance(job.get("result"), dict):
            return {**job["result"], "job_id": job_id}
        return {"ok": True, "pending": True, "job_id": job_id,
                "stage": job.get("stage") or "đang xử lý",
                "batches_total": job.get("batches_total") or 0,
                "batches_done": job.get("batches_done") or 0}

    @app.get("/api/studio/analyze_job/{job_id}")
    async def studio_analyze_job(job_id: str):
        """Tiến độ / kết quả của một job phân tích nguồn."""
        job = _job_get(job_id)
        if job is None:
            return {"ok": False, "error": "job không tồn tại hoặc đã hết hạn"}
        status = job.get("status") or "running"
        out = {
            "ok": True, "status": status, "stage": job.get("stage") or "",
            "batches_done": job.get("batches_done") or 0,
            "batches_total": job.get("batches_total") or 0,
            "elapsed": round(_time.time() - float(job.get("started") or 0), 1),
        }
        if isinstance(job.get("coverage"), dict):
            out.update(job["coverage"])
        if status in {"done", "error"} and isinstance(job.get("result"), dict):
            out["result"] = job["result"]
        return out

    @app.post("/api/studio/convert")
    async def studio_convert_file(request: Request):
        """Convert an uploaded file straight to Markdown (markitdown, no AI).

        Fast path for the KB-create form: PDF/DOCX/PPTX/XLSX/HTML/CSV/EPUB →
        markdown text the user can review before ingesting. Scanned PDFs fall
        back to OCR like analyze_source does.
        """
        try:
            form = await request.form()
        except Exception as e:
            return {"ok": False, "error": f"Lỗi parse form data: {e}"}
        file = form.get("file")
        if not (file and hasattr(file, "read")):
            return {"ok": False, "error": "Không nhận được file hợp lệ."}
        content = await file.read()
        if not content:
            return {"ok": False, "error": "File bạn tải lên rỗng (0 bytes)."}
        filename = (file.filename or "").lower()
        if filename.endswith((".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".csv", ".epub")):
            import os as _os
            import tempfile
            try:
                from markitdown import MarkItDown
            except ImportError:
                return {"ok": False, "error": "Thiếu thư viện markitdown. Vui lòng rebuild Docker."}
            with tempfile.NamedTemporaryFile(delete=False, suffix=_os.path.splitext(filename)[1]) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                text = MarkItDown().convert(tmp_path).text_content or ""
                if not text.strip() and filename.endswith(".pdf"):
                    text = _ocr_pdf(tmp_path)
            except Exception as e:
                text = ""
                if filename.endswith(".pdf"):
                    try:
                        text = _ocr_pdf(tmp_path)
                    except Exception:
                        pass
                if not text.strip():
                    return {"ok": False, "error": f"Lỗi chuyển đổi file: {e}"}
            finally:
                if _os.path.exists(tmp_path):
                    _os.remove(tmp_path)
        else:
            text = content.decode("utf-8", errors="ignore")
        if not text.strip():
            return {"ok": False, "error": "Không trích xuất được văn bản từ file này."}
        return {"ok": True, "filename": file.filename, "markdown": text}

    @app.post("/api/rag/forget/{collection}")
    async def rag_forget(collection: str, request: Request):
        """Xoá chunk theo TIỀN TỐ source — để "ghi đè" là ghi đè THẬT ở RAG.

        Vì sao cần: đường nạp mode=replace chỉ ghi đè file .md; chunk cũ trong
        Chroma nằm lại vĩnh viễn, nên thay sách (năm học mới đổi SGK) xong bot
        trộn sách cũ với sách mới. Chroma không lọc được prefix trong `where`,
        nên quét metadata theo lô rồi xoá theo id.

        Body: {source_prefix, where?}. Prefix PHẢI ≥ 8 kí tự — chặn lời gọi cụt
        tay ("t", "") quét bay cả kho.

        `where` (tuỳ chọn) THU HẸP thêm theo metadata, và mọi khoá trong đó phải
        khớp. Cần cho việc ghi đè MỘT TẬP: kho gộp cả hai tập của một môn dưới
        cùng tiền tố `teacher_sgk/lop4/toan/`, nên xoá theo prefix là xoá luôn
        tập kia — nạp lại tập hai làm mất tập một, im lặng, không gì báo. Có
        `where={"volume": "tập hai"}` thì chỉ đúng tập đó bay.
        """
        from src.rag.retriever import RAGRetriever

        body = await request.json()
        prefix = str(body.get("source_prefix") or "")
        if len(prefix) < 8:
            return {"ok": False, "error": f"source_prefix quá ngắn: {prefix!r}"}
        loc = body.get("where")
        loc = loc if isinstance(loc, dict) else {}
        # Chỉ nhận giá trị vô hướng: so khớp dict/list vừa vô nghĩa vừa dễ thành
        # "khớp mọi thứ" rồi xoá sạch kho.
        loc = {k: v for k, v in loc.items()
               if isinstance(k, str) and isinstance(v, (str, int, float, bool))}
        r = RAGRetriever.get()
        if not r._ensure_loaded():
            return {"ok": False, "error": "Chroma not loaded"}
        try:
            col = r._client.get_collection(name=collection)
        except Exception:
            return {"ok": True, "deleted": 0, "note": "collection chưa tồn tại"}
        deleted, offset = 0, 0
        while True:
            got = col.get(limit=500, offset=offset, include=["metadatas"])
            ids = got.get("ids") or []
            if not ids:
                break
            hit = [i for i, m in zip(ids, got.get("metadatas") or [])
                   if str((m or {}).get("source") or "").startswith(prefix)
                   and all((m or {}).get(k) == v for k, v in loc.items())]
            if hit:
                col.delete(ids=hit)
                deleted += len(hit)
                # KHÔNG tăng offset sau khi xoá: các dòng sau dồn lên chỗ vừa
                # trống, tăng offset là nhảy cóc qua chunk chưa xét.
                continue
            offset += len(ids)
        return {"ok": True, "collection": collection, "deleted": deleted,
                "source_prefix": prefix, "where": loc or None}

    @app.get("/api/rag/thong-ke/{collection}")
    async def rag_thong_ke(collection: str):
        """Đếm chunk theo LỚP – MÔN – TẬP của một kho.

        Vì sao cần: bảng "Toàn bộ SGK trên server" đếm theo file .md, mà .md chỉ
        được ghi cho sách HỌC SINH — nên sách giáo viên, vở bài tập, tài liệu tập
        huấn nạp vào rồi vẫn không hiện ở đâu cả, người dùng tưởng bốn loại bị
        gộp làm một. Đếm thẳng trên metadata của từng kho thì mỗi loại hiện riêng,
        và thấy rõ lớp–môn nào đang có tập nào.
        """
        from src.rag.retriever import RAGRetriever

        r = RAGRetriever.get()
        if not r._ensure_loaded():
            return {"ok": False, "error": "Chroma not loaded"}
        try:
            col = r._client.get_collection(name=collection)
        except Exception:
            return {"ok": True, "collection": collection, "tong": 0, "rows": []}
        dem: dict[tuple, int] = {}
        tong, offset = 0, 0
        while True:
            got = col.get(limit=1000, offset=offset, include=["metadatas"])
            ids = got.get("ids") or []
            if not ids:
                break
            for m in got.get("metadatas") or []:
                m = m or {}
                key = (m.get("grade") or 0, str(m.get("subject") or ""),
                       str(m.get("volume") or ""))
                dem[key] = dem.get(key, 0) + 1
                tong += 1
            offset += len(ids)
        rows = [{"grade": g, "subject": s, "volume": v, "chunks": n}
                for (g, s, v), n in sorted(dem.items(), key=lambda x: (x[0][0], x[0][1]))]
        return {"ok": True, "collection": collection, "tong": tong, "rows": rows}

    @app.post("/api/rag/curate/{collection}")
    async def rag_curate(collection: str, request: Request):
        """Add curated content to a RAG collection + upload to R2.

        Body: {title, text, source}
        - Splits text into chunks, ingests into Chroma, uploads to R2.
        """
        from src.rag.ingest import chunk_text
        from src.rag.retriever import RAGRetriever
        from src.rag.meta import touch
        from src.rag.cloud import upload_collection

        body = await request.json()
        title = str(body.get("title") or "")
        text = str(body.get("text") or "")
        source = str(body.get("source") or "curated")

        if not text.strip():
            return {"ok": False, "error": "No text provided"}

        chunks = chunk_text(f"# {title}\n\n{text}" if title else text)
        if not chunks:
            return {"ok": False, "error": "No chunks produced"}

        retriever = RAGRetriever.get()
        if not retriever._ensure_loaded():
            return {"ok": False, "error": "Chroma not loaded"}

        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        col = retriever._client.get_or_create_collection(
            name=collection, embedding_function=retriever._embed_fn
        )
        ids = [f"curated::{ts}::{i}" for i in range(len(chunks))]
        # grade/subject suy từ source `teacher_sgk/lop{n}/{mon}/...` để chunk mới
        # LỌC ĐƯỢC theo lớp–môn ngay khi nạp. Nếu chỉ có {source, chunk} như bản
        # cũ thì mọi lượt tra có lọc sẽ BỎ QUA sách vừa nạp — im lặng, không lỗi,
        # nhìn như "chưa nạp". Kho SGK gộp 12 lớp mà tra thuần ngữ nghĩa chỉ đúng
        # lớp–môn 4/12 lần (đo 2026-07-29), nên đường lọc là đường chính, không
        # phải tuỳ chọn.
        extra: dict[str, Any] = {}
        # Hai tiền tố, không phải một: `teacher_sgk/` là đường nạp của dự án,
        # `tay/` là đường nạp tay. Bản cũ chỉ khớp `teacher_sgk` nên 18 đoạn SGK
        # Tiếng Việt lớp 1–2 nạp tay không có nhãn — đếm thì thấy tăng, hỏi theo
        # lớp thì không ra. Sai âm thầm, chỉ lộ khi soi metadata.
        # `_tailieu` PHẢI có trong danh sách. Thiếu nó thì mọi đoạn tài liệu tập
        # huấn nằm đúng kho `kb_giao_duc_tailieu` nhưng tự khai `kind="sgk"` —
        # đúng cái đo được ở phía client ngày 2026-07-30 (nạp một quyển mỗi loại
        # rồi đọc lại metadata: sgv và tap_huan đều ra "sgk"). Không lỗi nào báo,
        # số đếm vẫn đẹp; chỉ lộ khi có chỗ lọc theo `kind` và thấy kho rỗng.
        extra_kind = ("vbt" if collection.endswith("_vbt")
                      else "slide" if collection.endswith("_slide")
                      else "sgv" if collection.endswith("_sgv")
                      else "tap_huan" if collection.endswith("_tailieu")
                      else "sgk")
        mt = re.match(r"^(?:teacher_sgk|tay)/lop(\d{1,2})/([a-z_]+)/", source)
        if mt:
            g = int(mt.group(1))
            if 1 <= g <= 12:
                extra["grade"] = g
            extra["subject"] = mt.group(2)
            extra["kind"] = extra_kind
        # Client gửi kèm metadata tường minh thì ưu tiên — đường nạp biết rõ
        # lớp–môn hơn là đoán từ chuỗi source. Chỉ nhận kiểu vô hướng: Chroma
        # không lưu được dict/list lồng nhau và sẽ ném lỗi giữa lúc nạp.
        raw_meta = body.get("metadata")
        if isinstance(raw_meta, dict):
            for k, v in raw_meta.items():
                if k in ("source", "chunk") or not isinstance(k, str):
                    continue  # không cho ghi đè hai khoá xương sống
                if isinstance(v, bool) or isinstance(v, (int, float, str)):
                    if v != "" and v is not None:
                        extra[k] = v
        metas = [{"source": source, "chunk": i, **extra} for i in range(len(chunks))]
        batch = 100
        for i in range(0, len(chunks), batch):
            col.upsert(ids=ids[i:i+batch], documents=chunks[i:i+batch], metadatas=metas[i:i+batch])

        touch(collection, chunks=len(chunks), source=f"curated/{source}")

        # Upload to R2
        r2_ok = upload_collection(collection)

        return {"ok": True, "collection": collection, "chunks_added": len(chunks), "r2_uploaded": r2_ok}

    @app.get("/api/studio/settings")
    async def studio_get_settings():
        """Get RAG lifecycle settings (sync interval, storage mode)."""
        from src.rag.settings import read as _read_settings
        return _read_settings()

    @app.post("/api/studio/settings")
    async def studio_save_settings(request: Request):
        """Save RAG lifecycle settings."""
        from src.rag.settings import write as _write_settings
        body = await request.json()
        _write_settings(body)
        return {"ok": True}

    @app.post("/api/studio/key/{source_key}")
    async def studio_save_key(source_key: str, request: Request):
        """Save an API key for a source. Body: {api_key: '...'}"""
        from src.sources_config import save_api_key
        body = await request.json()
        key = str(body.get("api_key") or "").strip()
        ok = save_api_key(source_key, key)
        return {"ok": ok, "source": source_key}

    @app.post("/api/studio/validate-mcp")
    async def studio_validate_mcp(request: Request):
        """Test an MCP server URL. Body: {url, api_key?}"""
        from src.mcp_validator import validate_mcp
        body = await request.json()
        url = str(body.get("url") or "").strip()
        api_key = str(body.get("api_key") or "").strip()
        if not url:
            return {"ok": False, "errors": ["URL is required"]}
        return validate_mcp(url, api_key)

    @app.get("/api/studio/external-mcps")
    async def studio_list_external():
        """List external MCPs from registry."""
        import json
        reg = Path("/app/data/studio/external_mcps.json")
        if reg.exists():
            return {"mcps": json.loads(reg.read_text(encoding="utf-8")) or []}
        return {"mcps": []}

    @app.post("/api/studio/external-mcp")
    async def studio_add_external(request: Request):
        """Add an external MCP. Body: {name, url, description, api_key?}"""
        import json
        body = await request.json()
        name = str(body.get("name") or "").strip()
        url = str(body.get("url") or "").strip()
        desc = str(body.get("description") or "").strip()
        api_key = str(body.get("api_key") or "").strip()
        if not name or not url:
            return {"ok": False, "errors": ["Name and URL are required"]}

        reg = Path("/app/data/studio/external_mcps.json")
        reg.parent.mkdir(parents=True, exist_ok=True)
        entries = json.loads(reg.read_text(encoding="utf-8")) if reg.exists() else []
        if any(e["name"] == name for e in entries):
            return {"ok": False, "errors": [f"MCP '{name}' already exists"]}
        entries.append({"name": name, "url": url, "description": desc, "api_key": api_key,
                        "added_at": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()})
        reg.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "name": name}

    @app.delete("/api/studio/external-mcp/{name}")
    async def studio_delete_external(name: str):
        """Remove an external MCP."""
        import json
        reg = Path("/app/data/studio/external_mcps.json")
        if not reg.exists():
            return {"ok": True}
        entries = json.loads(reg.read_text(encoding="utf-8")) or []
        entries = [e for e in entries if e["name"] != name]
        reg.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True}

    @app.get("/api/studio/r2")
    async def studio_get_r2():
        """Get R2 config (masked secret)."""
        import json
        r2_file = Path("/app/data/studio/r2.json")
        if r2_file.exists():
            cfg = json.loads(r2_file.read_text(encoding="utf-8"))
            return {"configured": True, "config": cfg}
        return {"configured": False, "config": {}}

    @app.post("/api/studio/r2")
    async def studio_save_r2(request: Request):
        """Save R2 credentials. Body: {endpoint, access_key_id, secret_access_key, bucket}"""
        import json
        body = await request.json()
        r2_file = Path("/app/data/studio/r2.json")
        r2_file.parent.mkdir(parents=True, exist_ok=True)
        cfg = {
            "endpoint": str(body.get("endpoint") or "").strip(),
            "access_key_id": str(body.get("access_key_id") or "").strip(),
            "secret_access_key": str(body.get("secret_access_key") or "").strip(),
            "bucket": str(body.get("bucket") or "vn-mcp-hub-rag").strip(),
        }
        r2_file.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True}

    @app.get("/api/rag/list")
    async def rag_list():
        """Liệt kê MỌI kho RAG dùng được, không chỉ kho đã có meta.json.

        Bản cũ chỉ nhận thư mục có `meta.json`. Nhưng meta.json chỉ sinh ra khi
        `touch()` chạy — tức sau lần nạp/refresh đầu tiên. 7 kho gốc trong repo
        (dien_nuoc, y_te, giao_duc, ngoai_ngu, khoa_hoc, tu_nhien, xa_hoi) chỉ
        có sẵn file .md, KHÔNG có meta.json, nên biến mất khỏi danh sách —
        người dùng mở ô "chọn KB để nạp vào" thì thiếu kho, tưởng là chưa có.

        Giờ hợp ba nguồn: thư mục có .md, sổ KB động của Studio, và collection
        thật trong Chroma (nguồn sự thật về cái gì hỏi được).
        """
        from pathlib import Path

        from src.rag.meta import get_age_str, read_meta
        data_dir = Path("/app/data")
        names: set[str] = set()

        # 1) Thư mục kho: có meta.json HOẶC có file .md để nạp.
        if data_dir.exists():
            for folder in sorted(data_dir.iterdir()):
                if not folder.is_dir() or folder.name.startswith("."):
                    continue
                # `studio` là thư mục CHỨA các kho động, bản thân nó không phải kho.
                if folder.name == "studio":
                    continue
                if (folder / "meta.json").exists() or any(folder.glob("*.md")):
                    names.add(folder.name)

        # 2) Sổ KB động của Studio — kho mới tạo có thể chưa kịp có .md ở data/.
        try:
            from src.studio import list_dynamic_mcps
            for e in list_dynamic_mcps():
                if e.get("name"):
                    names.add(str(e["name"]))
        except Exception as exc:
            logging.getLogger("vn-mcp-hub").debug("rag_list: studio registry: %s", exc)

        # 3) Collection thật trong Chroma + số chunk thật (meta có thể lệch).
        live: dict[str, int] = {}
        try:
            from src.rag.retriever import RAGRetriever
            r = RAGRetriever.get()
            if r._ensure_loaded():
                for col in r._client.list_collections():
                    # chromadb ≥0.6 trả về tên (str); bản cũ trả về object.
                    cname = getattr(col, "name", None) or str(col)
                    names.add(cname)
                    # Dùng đúng đường của retriever (kèm embedding function) thay
                    # vì get_collection() trần — tránh lệch hành vi giữa hai lối.
                    stats = r.collection_stats(cname)
                    if stats.get("available") and stats.get("count", -1) >= 0:
                        live[cname] = stats["count"]
        except Exception as exc:
            logging.getLogger("vn-mcp-hub").debug("rag_list: chroma: %s", exc)

        result = []
        for name in sorted(names):
            meta = read_meta(name)
            result.append({
                "name": name,
                # Số chunk thật ưu tiên hơn meta: meta chỉ đúng tới lần touch cuối.
                "chunks": live.get(name, meta.get("chunks_count", 0)),
                "indexed": name in live,
                "last_updated": meta.get("last_updated"),
                "age": get_age_str(name),
                "auto_update": meta.get("auto_update", False),
            })
        return {"collections": result}

    @app.post("/api/studio/collection/{name}/settings")
    async def studio_collection_settings(name: str, request: Request):
        """Update collection settings. Body may carry:
            update_interval_hours: int    (how many hours before forced refresh)
            soft_notify_days:      int    (when to show "refresh hint" to user)
            auto_update:           bool   (let the scheduler refresh this KB)
        """
        from src.rag.meta import read_meta, write_meta
        body = await request.json()
        meta = read_meta(name)
        if "update_interval_hours" in body:
            meta["update_interval_hours"] = max(1, int(body["update_interval_hours"]))
        if "soft_notify_days" in body:
            meta["soft_notify_days"] = max(1, int(body["soft_notify_days"]))
        if "auto_update" in body:
            meta["auto_update"] = bool(body["auto_update"])
        write_meta(name, meta)
        return {"ok": True, "name": name, "meta": meta}

    @app.delete("/api/studio/kb/{name}")
    async def studio_delete_kb(name: str):
        from src.studio import delete_kb as _delete
        return _delete(name)

    # ── SSH server registry (cho ssh_exec MCP) ───────────────────────────
    @app.get("/api/ssh/servers")
    async def ssh_list():
        from src.general.ssh_exec import list_servers_safe
        return {"servers": list_servers_safe()}

    @app.post("/api/ssh/servers")
    async def ssh_add(request: Request):
        from src.general.ssh_exec import add_server
        body = await request.json()
        return add_server(
            name=str(body.get("name", "")), host=str(body.get("host", "")),
            username=str(body.get("username", "")), password=str(body.get("password", "")),
            port=int(body.get("port", 22) or 22), key_path=str(body.get("key_path", "")),
            allow_dangerous=bool(body.get("allow_dangerous", False)),
        )

    @app.delete("/api/ssh/servers/{name}")
    async def ssh_del(name: str):
        from src.general.ssh_exec import remove_server
        return remove_server(name)

    @app.post("/api/ssh/servers/{name}/paths")
    async def ssh_set_paths(name: str, request: Request):
        """Cấp/đổi thư mục đọc-ghi cho fs_remote. Body: {add_read?, add_write?, read_paths?, write_paths?}"""
        from src.general.ssh_exec import set_paths
        body = await request.json()
        return set_paths(
            name,
            add_read=str(body.get("add_read", "")), add_write=str(body.get("add_write", "")),
            read_paths=body.get("read_paths"), write_paths=body.get("write_paths"),
        )

    @app.post("/api/ssh/run")
    async def ssh_run_api(request: Request):
        from src.general.ssh_exec import run_command
        body = await request.json()
        return {"result": run_command(
            server=str(body.get("server", "")), command=str(body.get("command", "")),
            timeout=int(body.get("timeout", 30) or 30),
        )}

    # ── Telegram webhook endpoint ─────────────────────────────────────────
    @app.post("/telegram/webhook")
    async def telegram_webhook(request: Request):
        """Receive Telegram messages via webhook."""
        from src.rag.telegram_bot import handle_webhook
        return await handle_webhook(request)

    @app.get("/api/telegram/status")
    async def telegram_status():
        """Get Telegram bot status."""
        from src.rag.telegram_bot import _get_settings
        s = _get_settings()
        return {
            "configured": bool(s["bot_token"]),
            "webhook_url": s["webhook_url"],
            "model": s["ai_model"],
            "chat_ids_count": len(s["chat_ids"]),
        }

    @app.post("/api/telegram/test")
    async def telegram_test(request: Request):
        """Send a test message to the first allowed chat_id."""
        body = await request.json()
        msg = str(body.get("message", "Test từ chatgpt2api"))
        from src.rag.telegram_bot import _get_settings, send_message
        s = _get_settings()
        ids = s["chat_ids"]
        if not ids:
            return {"ok": False, "error": "Chưa cấu hình chat_ids"}
        result = send_message(ids[0], msg)
        return {"ok": result.get("ok", False)}

    _mount_mcps(app)
    _mount_dynamic_mcps(app)
    return app


MCP_LABELS = {
    "vn_weather": ("Thời tiết VN", "Thời tiết 63 tỉnh thành, 4 nguồn (Open-Meteo, AccuWeather, NWS, wttr)", "weather"),
    "vn_news": ("Tin tức VN", "Tin mới nhất từ VnExpress, Tuổi Trẻ, Thanh Niên, Dân Trí, BBC, Google News", "news"),
    "vn_currency": ("Tỷ giá & Vàng", "Tỷ giá Vietcombank, giá vàng SJC, ngoại tệ", "finance"),
    "vn_petrol": ("Giá xăng dầu", "Giá bán lẻ xăng RON 95/E5, dầu DO/hỏa/Mazút Petrolimex (Vùng 1 + 2)", "finance"),
    "vn_lunar": ("Lịch Âm", "Đổi dương sang âm, can chi, ngày hoàng đạo", "vn_other"),
    "vn_search": ("Tìm kiếm Web", "Tìm web qua DuckDuckGo, hỗ trợ tiếng Việt", "search"),
    "vn_law": ("Tra cứu Luật", "Văn bản pháp luật Việt Nam từ thuvienphapluat.vn", "search"),
    "vn_stock": ("Cổ phiếu VN", "Giá cổ phiếu, VN-Index, HNX từ VNDirect", "finance"),
    "youtube": ("YouTube Transcript", "Lấy transcript video YouTube, hỗ trợ tiếng Việt", "general"),
    "wikipedia": ("Wikipedia", "Bách khoa toàn thư đa ngôn ngữ (mặc định tiếng Việt)", "search"),
    "arxiv": ("arXiv Paper", "Tìm paper khoa học trên arXiv", "search"),
    "kb_dien_nuoc": ("Kho Điện Nước", "Kiến thức điện, nước, điều hòa, chiller (MCB, MCCB...)", "knowledge"),
    "kb_y_te": ("Kho Y Tế", "Y tế cơ bản, sơ cứu, bệnh thường gặp", "knowledge"),
    "kb_giao_duc": ("Kho Giáo Dục", "Chương trình giáo dục VN, phương pháp học tập", "knowledge"),
    "kb_giao_vien": ("Kho Giáo Viên (5 kho)",
                     "Tra 5 kho dạy học tách riêng: SGK (nội dung học sinh) · SGV/kế hoạch "
                     "bài dạy (cách dạy) · vở & sách bài tập (mẫu ra đề) · tài liệu tập huấn · "
                     "phân bổ tuần–tiết. Hỏi 'bài 3 dạy gì' vào SGK, 'dạy bài 3 thế nào' vào SGV",
                     "knowledge"),
    "kb_ngoai_ngu": ("Kho Ngoại Ngữ", "Từ điển, dịch thuật, ngữ pháp, luyện phát âm", "knowledge"),
    "kb_khoa_hoc": ("Kho Khoa Học", "Vật lý, hóa học, sinh học, toán cơ bản", "knowledge"),
    "kb_tu_nhien": ("Kho Tự Nhiên", "Động vật, thực vật, hệ sinh thái, khí hậu, địa lý VN", "knowledge"),
    "kb_xa_hoi": ("Kho Xã Hội", "Lịch sử VN, văn hóa, kinh tế, chính trị, 54 dân tộc", "knowledge"),
    "ha_helper": ("HA Helper", "Giờ hoàng đạo, gợi ý ngữ pháp lệnh Home Assistant", "ha"),
    "federated_search": ("Multi-Search", "Tìm kiếm đồng thời 9 nguồn quốc tế (DDG, Brave, PubMed...)", "search"),
    "web_reader": ("Đọc Web", "Đọc bất kỳ URL → Markdown sạch (Scrapling stealth + markitdown), cho RAG/tóm tắt", "search"),
    "web_agent": ("Web Agent", "AI tự điều khiển trình duyệt làm tác vụ web nhiều bước (browser-use)", "general"),
    "ssh_exec": ("SSH Server", "Chạy lệnh SSH trên nhiều server đã khai báo (Linux/NAS/NVR): xem trạng thái, đọc log, restart dịch vụ", "general"),
    "fs_remote": ("File Server (an toàn)", "Đọc/ghi file trên server từ xa qua SFTP, giới hạn theo thư mục — ghi bị cấm mặc định, cấp quyền từng thư mục qua chat", "general"),
    "device_fs": ("Thiết bị của tôi", "Đọc/sửa file trên máy tính, điện thoại Android, VPS đã cài c2a-agent — agent tự quay ra nên máy sau NAT/4G vẫn dùng được", "general"),
}

MOUNTS = [
    ("vn_weather", "src.vn.weather"),
    ("vn_news", "src.vn.news"),
    ("vn_currency", "src.vn.currency"),
    ("vn_petrol", "src.vn.petrol"),
    ("vn_lunar", "src.vn.lunar"),
    ("vn_search", "src.vn.search"),
    ("vn_law", "src.vn.law"),
    ("vn_stock", "src.vn.stock"),
    ("youtube", "src.general.youtube"),
    ("wikipedia", "src.general.wikipedia"),
    ("arxiv", "src.general.arxiv"),
    ("kb_dien_nuoc", "src.kb.dien_nuoc"),
    ("kb_y_te", "src.kb.y_te"),
    ("kb_giao_duc", "src.kb.giao_duc"),
    ("kb_giao_vien", "src.kb.giao_vien"),
    ("kb_ngoai_ngu", "src.kb.ngoai_ngu"),
    ("kb_khoa_hoc", "src.kb.khoa_hoc"),
    ("kb_tu_nhien", "src.kb.tu_nhien"),
    ("kb_xa_hoi", "src.kb.xa_hoi"),
    ("ha_helper", "src.ha.helper"),
    ("federated_search", "src.search.orchestrator_mcp"),
    ("web_reader", "src.general.web_reader"),
    ("web_agent", "src.general.web_agent"),
    ("ssh_exec", "src.general.ssh_exec"),
    ("fs_remote", "src.general.fs_remote"),
    ("device_fs", "src.general.device_fs"),
]


def _get_http_app(mcp):
    """Return the MCP's ASGI app, compatible with fastmcp 2.x and 3.x."""
    if hasattr(mcp, "http_app"):
        return mcp.http_app()  # fastmcp >= 3.0
    return mcp.streamable_http_app()  # fastmcp 2.x


def _mount_mcps(app: FastAPI) -> None:
    """Import each MCP module and mount its FastMCP HTTP app under /<name>/mcp.

    Failures during import are logged but do not abort startup — partial hub
    is better than no hub. Modules that haven't been written yet (during
    incremental build) simply skip.
    """
    for name, module_path in MOUNTS:
        try:
            module = __import__(module_path, fromlist=["mcp"])
            mcp_instance = getattr(module, "mcp", None)
            if mcp_instance is None:
                logger.warning("Module %s has no 'mcp' attribute, skipping", module_path)
                continue
            sub_app = _get_http_app(mcp_instance)
            _mcp_sub_apps.append(sub_app)
            app.mount(f"/{name}", sub_app)
            logger.info("Mounted %s at /%s/mcp", module_path, name)
        except ImportError as exc:
            logger.warning("Skipping %s (not built yet): %s", module_path, exc)
        except Exception as exc:
            logger.error("Failed to mount %s: %s", module_path, exc, exc_info=True)


def _mount_dynamic_mcps(app: FastAPI) -> None:
    """Mount studio-created dynamic KB MCPs from data/studio/dynamic.json."""
    try:
        from src.studio import load_dynamic_mcps
        for name, mcp in load_dynamic_mcps():
            try:
                sub_app = _get_http_app(mcp)
                _mcp_sub_apps.append(sub_app)
                app.mount(f"/{name}", sub_app)
                logger.info("Studio: mounted dynamic MCP at /%s/mcp", name)
            except Exception as exc:
                logger.warning("Studio: failed to mount dynamic MCP '%s': %s", name, exc)
    except Exception as exc:
        logger.warning("Studio: load_dynamic_mcps failed: %s", exc)


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8005,
        log_level="info",
        reload=False,
    )
