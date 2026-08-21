"""Trần body phải chặn ở ASGI, trước khi route nạp request vào RAM."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from services.ingress_guard import RequestBodyLimitMiddleware


LIMIT = 100


def _app(*, limit: int = LIMIT, cors: bool = False) -> FastAPI:
    app = FastAPI()

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"received": len(await request.body())}

    app.add_middleware(RequestBodyLimitMiddleware, max_body_bytes=limit)
    if cors:
        # Middleware thêm sau nằm ngoài, nên 413 vẫn phải có CORS.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    return app


def _chunks(total: int, size: int = 40):
    sent = 0
    while sent < total:
        step = min(size, total - sent)
        yield b"x" * step
        sent += step


def test_body_duoi_va_bang_tran_di_qua() -> None:
    with TestClient(_app()) as client:
        assert client.post("/echo", content=b"x" * (LIMIT - 1)).json() == {
            "received": LIMIT - 1,
        }
        assert client.post("/echo", content=b"x" * LIMIT).status_code == 200


def test_content_length_qua_tran_bi_tu_choi_som() -> None:
    with TestClient(_app()) as client:
        response = client.post("/echo", content=b"x" * (LIMIT + 1))
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "request_body_too_large"


def test_chunked_khong_content_length_van_bi_dem() -> None:
    with TestClient(_app()) as client:
        response = client.post("/echo", content=_chunks(LIMIT * 5))
    assert response.status_code == 413
    assert response.json()["detail"]["max_bytes"] == LIMIT


def test_413_van_di_qua_cors() -> None:
    with TestClient(_app(cors=True)) as client:
        response = client.post(
            "/echo",
            content=b"x" * (LIMIT + 1),
            headers={"Origin": "https://example.com"},
        )
    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "*"


def test_tran_zero_tat_middleware() -> None:
    with TestClient(_app(limit=0)) as client:
        response = client.post("/echo", content=b"x" * (LIMIT * 10))
    assert response.status_code == 200


def test_full_va_lite_app_deu_gan_middleware() -> None:
    full = __import__("api.app", fromlist=["create_app"]).create_app()
    lite = __import__("api.app_lite", fromlist=["create_app"]).create_app()
    assert any(m.cls is RequestBodyLimitMiddleware for m in full.user_middleware)
    assert any(m.cls is RequestBodyLimitMiddleware for m in lite.user_middleware)
