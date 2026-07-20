"""Listen on localhost:1455 for Codex CLI OAuth callbacks.

OpenAI only whitelists http://localhost:1455/auth/callback. When the user
finishes login, the browser navigates there (often with connection-refused
if nothing listens). This tiny HTTP server:

1. Receives GET /auth/callback?code=&state=
2. Exchanges the code into the account pool
3. Shows a success HTML page

Also keeps the last result so the Accounts UI can poll and auto-close.
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from utils.log import logger

_PORT = 1455
_server: HTTPServer | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()
_last_result: dict[str, Any] | None = None


def get_last_result() -> dict[str, Any] | None:
    with _lock:
        return dict(_last_result) if _last_result else None


def clear_last_result() -> None:
    global _last_result
    with _lock:
        _last_result = None


def _set_last(result: dict[str, Any]) -> None:
    global _last_result
    with _lock:
        _last_result = result


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # quieter
        logger.info({"event": "codex_callback_http", "msg": fmt % args})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in ("/auth/callback", "/callback", "/"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return

        qs = parse_qs(parsed.query)
        code = (qs.get("code") or [""])[0]
        state = (qs.get("state") or [""])[0]
        full_url = f"http://localhost:{_PORT}{self.path}"

        if not code or not state:
            body = (
                "<html><body style='font-family:sans-serif;padding:40px;text-align:center'>"
                "<h2>Thiếu code/state</h2>"
                f"<p>Copy URL này vào form dán callback:</p>"
                f"<code style='word-break:break-all'>{full_url}</code>"
                "</body></html>"
            ).encode()
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            _set_last({"ok": False, "error": "missing code/state", "redirect_url": full_url})
            return

        try:
            from services.oauth_service import exchange_codex_code

            result = exchange_codex_code(code, state)
            email = ""
            try:
                # pull latest codex with this token prefix if any
                email = str(result.get("access_token_prefix") or "")
            except Exception:
                pass
            _set_last({
                "ok": True,
                "message": result.get("message") or "OK",
                "has_refresh_token": result.get("has_refresh_token"),
                "redirect_url": full_url,
                "email_hint": email,
            })
            body = (
                "<html><body style='font-family:sans-serif;padding:40px;text-align:center'>"
                f"<h2 style='color:green'>{result.get('message') or 'Đăng nhập Codex thành công'}</h2>"
                "<p>Token đã được lưu vào pool. Bạn có thể đóng tab này.</p>"
                "<script>setTimeout(function(){window.close()},2500)</script>"
                "</body></html>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            logger.info({"event": "codex_callback_exchanged", "ok": True})
        except Exception as exc:
            err = str(exc)[:300]
            _set_last({"ok": False, "error": err, "redirect_url": full_url})
            body = (
                "<html><body style='font-family:sans-serif;padding:40px;text-align:center'>"
                f"<h2 style='color:red'>Lỗi exchange: {err}</h2>"
                f"<p>Copy URL sau vào form dán callback:</p>"
                f"<code style='word-break:break-all'>{full_url}</code>"
                "</body></html>"
            ).encode()
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            logger.warning({"event": "codex_callback_exchange_failed", "error": err})


def start() -> None:
    """Idempotent start of the :1455 listener."""
    global _server, _thread
    if _thread and _thread.is_alive():
        return

    def _run() -> None:
        global _server
        try:
            _server = HTTPServer(("0.0.0.0", _PORT), _Handler)
            logger.info({"event": "codex_callback_listener_started", "port": _PORT})
            _server.serve_forever()
        except OSError as exc:
            # Port in use (another process) — manual paste still works
            logger.warning({
                "event": "codex_callback_listener_bind_failed",
                "port": _PORT,
                "error": str(exc)[:160],
            })
        except Exception as exc:
            logger.warning({"event": "codex_callback_listener_crashed", "error": str(exc)[:160]})

    _thread = threading.Thread(target=_run, daemon=True, name="codex-callback-1455")
    _thread.start()


def stop() -> None:
    global _server
    try:
        if _server is not None:
            _server.shutdown()
    except Exception:
        pass
