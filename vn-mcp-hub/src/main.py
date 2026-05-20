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
                  http://<host>:<port>/vn_phat_nguoi/mcp
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
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("vn-mcp-hub")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting VN MCP Hub on port 8005")
    # Auto-ingest synchronously before yielding — chromadb/sentence-transformers
    # crash with SIGSEGV when called from a daemon thread in Docker.
    if not os.environ.get("SKIP_AUTO_INGEST"):
        try:
            from src.rag import ingest
            ingest.main()
        except Exception as exc:
            logger.warning("Auto-ingest failed (non-fatal): %s", exc)
    yield
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
        return JSONResponse({
            "name": "VN MCP Hub",
            "version": "0.1.0",
            "mcps": [name for name, _ in MOUNTS],
            "endpoint_pattern": "/<name>/mcp",
        })

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # ── Studio endpoints ────────────────────────────────────────────────
    from src.studio_html import STUDIO_HTML

    @app.get("/studio")
    async def studio_page():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=STUDIO_HTML)

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

    @app.delete("/api/studio/kb/{name}")
    async def studio_delete_kb(name: str):
        from src.studio import delete_kb as _delete
        return _delete(name)

    _mount_mcps(app)
    _mount_dynamic_mcps(app)
    return app


MOUNTS = [
    ("vn_weather", "src.vn.weather"),
    ("vn_news", "src.vn.news"),
    ("vn_currency", "src.vn.currency"),
    ("vn_lunar", "src.vn.lunar"),
    ("vn_search", "src.vn.search"),
    ("vn_law", "src.vn.law"),
    ("vn_phat_nguoi", "src.vn.phat_nguoi"),
    ("vn_stock", "src.vn.stock"),
    ("youtube", "src.general.youtube"),
    ("wikipedia", "src.general.wikipedia"),
    ("arxiv", "src.general.arxiv"),
    ("kb_dien_nuoc", "src.kb.dien_nuoc"),
    ("kb_y_te", "src.kb.y_te"),
    ("kb_giao_duc", "src.kb.giao_duc"),
    ("kb_ngoai_ngu", "src.kb.ngoai_ngu"),
    ("kb_khoa_hoc", "src.kb.khoa_hoc"),
    ("kb_tu_nhien", "src.kb.tu_nhien"),
    ("kb_xa_hoi", "src.kb.xa_hoi"),
    ("ha_helper", "src.ha.helper"),
]


def _get_http_app(mcp):
    """Return the MCP's ASGI app, compatible with fastmcp 2.x and 3.x.

    lifespan="mount" tells FastMCP to register its internal task groups
    with the parent FastAPI app's lifespan, avoiding 'Task group is not
    initialized' errors at request time.
    """
    if hasattr(mcp, "http_app"):
        return mcp.http_app(lifespan="mount")  # fastmcp >= 3.0
    return mcp.streamable_http_app(lifespan="mount")  # fastmcp 2.x


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
