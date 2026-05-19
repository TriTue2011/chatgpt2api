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
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
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
            "mcps": [
                "vn_weather", "vn_news", "vn_currency", "vn_lunar",
                "vn_search", "vn_law", "vn_phat_nguoi", "vn_stock",
                "youtube", "wikipedia", "arxiv",
                "kb_dien_nuoc", "kb_y_te", "kb_giao_duc", "kb_ngoai_ngu",
                "ha_helper",
            ],
            "endpoint_pattern": "/<name>/mcp",
        })

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    _mount_mcps(app)
    return app


def _mount_mcps(app: FastAPI) -> None:
    """Import each MCP module and mount its FastMCP HTTP app under /<name>/mcp.

    Failures during import are logged but do not abort startup — partial hub
    is better than no hub. Modules that haven't been written yet (during
    incremental build) simply skip.
    """
    mounts = [
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
        ("ha_helper", "src.ha.helper"),
    ]
    for name, module_path in mounts:
        try:
            module = __import__(module_path, fromlist=["mcp"])
            mcp_instance = getattr(module, "mcp", None)
            if mcp_instance is None:
                logger.warning("Module %s has no 'mcp' attribute, skipping", module_path)
                continue
            sub_app = mcp_instance.streamable_http_app()
            app.mount(f"/{name}", sub_app)
            logger.info("Mounted %s at /%s/mcp", module_path, name)
        except ImportError as exc:
            logger.warning("Skipping %s (not built yet): %s", module_path, exc)
        except Exception as exc:
            logger.error("Failed to mount %s: %s", module_path, exc, exc_info=True)


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8005,
        log_level="info",
        reload=False,
    )
