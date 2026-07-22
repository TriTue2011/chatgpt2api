"""Sổ SEAM — fake chuẩn cho 8 ranh giới ra thế giới ngoài.

Đợt 0: mọi test adapter CHỈ mock qua đây (hoặc fixture conftest bọc sẵn).
Không ``unittest.mock.patch("requests.get")`` / ``call_model`` tùy hứng.

Seams
-----
S1 Provider HTTP   — OpenAI/Codex/Gemini/httpx/requests ra ngoài
S2 HA              — ha_client HTTP/WS
S3 Loa socket      — Cast 8009 / R1 8082 / SSDP
S4 Model nội bộ    — agent.runtime.call_model / self-call gateway
S5 Storage         — DATA_DIR tmp (accounts, config, workspace)
S6 Bot API         — telegram/zalo send_message / send_photo / _api_call
S7 MCP             — mcp_client transport
S8 Doc/media libs  — fitz/docx/tesseract (thật hoặc stub nhẹ)

Usage
-----
::

    from test._fakes import FakeCallModel, install_call_model, tmp_data_dir

    @pytest.mark.adapter
    def test_x(tmp_data_dir):
        with install_call_model(FakeCallModel(text="ok")) as fake:
            ...
            assert fake.calls
"""

from __future__ import annotations

import json
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional
from unittest import mock

# ── Shared call log ─────────────────────────────────────────────────────────


@dataclass
class CallRecord:
    """One outbound seam invocation (for assertions)."""

    seam: str
    name: str
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    result: Any = None


class CallLog:
    """Thread-safe list of CallRecord."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.records: list[CallRecord] = []

    def add(self, seam: str, name: str, *args: Any, result: Any = None, **kwargs: Any) -> None:
        with self._lock:
            self.records.append(
                CallRecord(seam=seam, name=name, args=args, kwargs=dict(kwargs), result=result)
            )

    def clear(self) -> None:
        with self._lock:
            self.records.clear()

    def by_seam(self, seam: str) -> list[CallRecord]:
        with self._lock:
            return [r for r in self.records if r.seam == seam]

    def names(self, seam: str | None = None) -> list[str]:
        with self._lock:
            if seam is None:
                return [r.name for r in self.records]
            return [r.name for r in self.records if r.seam == seam]


# Global log (tests can also use a private CallLog instance)
SEAM_LOG = CallLog()


# ═══════════════════════════════════════════════════════════════════════════
# S1 — Provider HTTP
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class FakeHttpResponse:
    status_code: int = 200
    text: str = "{}"
    headers: dict = field(default_factory=dict)
    _json: Any = None

    def json(self) -> Any:
        if self._json is not None:
            return self._json
        return json.loads(self.text or "{}")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text[:200]}")


class FakeProviderHttp:
    """Queue of responses for provider HTTP (S1).

    ``queue`` items: FakeHttpResponse | Exception | callable(method, url, **kw) -> FakeHttpResponse
    """

    def __init__(self, queue: list[Any] | None = None) -> None:
        self.queue: list[Any] = list(queue or [])
        self.calls: list[dict[str, Any]] = []

    def _next(self, method: str, url: str, **kwargs: Any) -> FakeHttpResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        SEAM_LOG.add("S1", method.lower(), url, **{k: v for k, v in kwargs.items() if k != "headers"})
        if not self.queue:
            return FakeHttpResponse(status_code=200, text='{"ok":true}', _json={"ok": True})
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item) and not isinstance(item, FakeHttpResponse):
            out = item(method, url, **kwargs)
            return out if isinstance(out, FakeHttpResponse) else FakeHttpResponse(_json=out)
        if isinstance(item, FakeHttpResponse):
            return item
        if isinstance(item, dict):
            return FakeHttpResponse(text=json.dumps(item), _json=item)
        if isinstance(item, tuple) and len(item) == 2:
            code, body = item
            if isinstance(body, dict):
                return FakeHttpResponse(status_code=int(code), text=json.dumps(body), _json=body)
            return FakeHttpResponse(status_code=int(code), text=str(body))
        return FakeHttpResponse(text=str(item))

    def get(self, url: str, **kwargs: Any) -> FakeHttpResponse:
        return self._next("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> FakeHttpResponse:
        return self._next("POST", url, **kwargs)

    def request(self, method: str, url: str, **kwargs: Any) -> FakeHttpResponse:
        return self._next(method.upper(), url, **kwargs)


@contextmanager
def install_provider_http(fake: FakeProviderHttp | None = None) -> Iterator[FakeProviderHttp]:
    """Patch common HTTP entry points used by providers (best-effort)."""
    fake = fake or FakeProviderHttp()
    patches = []
    targets = [
        "requests.get",
        "requests.post",
        "requests.request",
        "httpx.get",
        "httpx.post",
        "httpx.request",
    ]
    for t in targets:
        try:
            mod, _, attr = t.rpartition(".")
            __import__(mod)
            p = mock.patch(t, side_effect=getattr(fake, attr if attr != "request" else "request"))
            p.start()
            patches.append(p)
        except Exception:
            continue
    try:
        yield fake
    finally:
        for p in patches:
            try:
                p.stop()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════
# S2 — Home Assistant
# ═══════════════════════════════════════════════════════════════════════════


class FakeHA:
    """In-memory HA states/services (S2)."""

    def __init__(self, states: dict[str, Any] | None = None) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        for eid, val in (states or {}).items():
            if isinstance(val, dict):
                self.states[eid] = dict(val)
            else:
                self.states[eid] = {"state": str(val), "attributes": {}}
        self.service_calls: list[dict[str, Any]] = []

    def get_state(self, entity_id: str) -> dict[str, Any] | None:
        SEAM_LOG.add("S2", "get_state", entity_id)
        return self.states.get(entity_id)

    def get_states(self) -> list[dict[str, Any]]:
        SEAM_LOG.add("S2", "get_states")
        return [
            {"entity_id": k, **v} if "entity_id" not in v else v
            for k, v in self.states.items()
        ]

    def call_service(
        self,
        domain: str,
        service: str,
        data: dict | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        rec = {"domain": domain, "service": service, "data": data or {}, **kwargs}
        self.service_calls.append(rec)
        SEAM_LOG.add("S2", "call_service", domain, service, **(data or {}))
        return {"ok": True}


@contextmanager
def install_ha(fake: FakeHA | None = None) -> Iterator[FakeHA]:
    """Patch services.ha_client hot paths when module is importable."""
    fake = fake or FakeHA()
    patches = []
    for target, attr in [
        ("services.ha_client.get_states", "get_states"),
        ("services.ha_client.call_service", "call_service"),
    ]:
        try:
            p = mock.patch(target, side_effect=getattr(fake, attr))
            p.start()
            patches.append(p)
        except Exception:
            continue
    try:
        yield fake
    finally:
        for p in patches:
            try:
                p.stop()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════
# S3 — Speaker sockets
# ═══════════════════════════════════════════════════════════════════════════


class FakeSocket:
    """Record send/recv without real network (S3)."""

    def __init__(self, recv_queue: list[bytes] | None = None) -> None:
        self.sent: list[bytes] = []
        self.recv_queue = list(recv_queue or [])
        self.closed = False
        self.connected: tuple | None = None

    def connect(self, address: tuple) -> None:
        self.connected = address
        SEAM_LOG.add("S3", "connect", address)

    def send(self, data: bytes) -> int:
        self.sent.append(data if isinstance(data, (bytes, bytearray)) else bytes(data))
        SEAM_LOG.add("S3", "send", len(self.sent[-1]))
        return len(self.sent[-1])

    def sendall(self, data: bytes) -> None:
        self.send(data)

    def recv(self, n: int = 4096) -> bytes:
        if self.recv_queue:
            return self.recv_queue.pop(0)
        return b""

    def close(self) -> None:
        self.closed = True
        SEAM_LOG.add("S3", "close")

    def settimeout(self, *_a: Any, **_k: Any) -> None:
        return None

    def setsockopt(self, *_a: Any, **_k: Any) -> None:
        return None


@contextmanager
def install_socket(factory: Callable[[], FakeSocket] | None = None) -> Iterator[list[FakeSocket]]:
    """Patch socket.socket to return FakeSocket instances."""
    created: list[FakeSocket] = []

    def _factory(*_a: Any, **_k: Any) -> FakeSocket:
        sock = factory() if factory else FakeSocket()
        created.append(sock)
        return sock

    with mock.patch("socket.socket", side_effect=_factory):
        yield created


# ═══════════════════════════════════════════════════════════════════════════
# S4 — Internal model (call_model)
# ═══════════════════════════════════════════════════════════════════════════


class FakeCallModel:
    """Fixed replies for services.agent.runtime.call_model (S4).

    ``replies``: str | dict | list | Exception | callable(model, messages, **kw)
    If list, pop left each call.
    """

    def __init__(self, text: str = "ok", replies: Any = None) -> None:
        self.default_text = text
        self.replies: list[Any] = (
            list(replies) if isinstance(replies, list) else ([] if replies is None else [replies])
        )
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append({"model": model, "messages": messages, **kwargs})
        item: Any
        if self.replies:
            item = self.replies.pop(0)
        else:
            item = self.default_text
        if isinstance(item, Exception):
            SEAM_LOG.add("S4", "call_model", model, result="error")
            raise item
        if callable(item) and not isinstance(item, dict):
            out = item(model, messages, **kwargs)
            SEAM_LOG.add("S4", "call_model", model, result=type(out).__name__)
            return out if isinstance(out, dict) else self._wrap(str(out), model)
        if isinstance(item, dict):
            SEAM_LOG.add("S4", "call_model", model, result="dict")
            return item
        SEAM_LOG.add("S4", "call_model", model, result="text")
        return self._wrap(str(item), model)

    @staticmethod
    def _wrap(text: str, model: str = "fake") -> dict[str, Any]:
        return {
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }


@contextmanager
def install_call_model(fake: FakeCallModel | None = None) -> Iterator[FakeCallModel]:
    fake = fake or FakeCallModel()
    patches: list[Any] = []
    for target in (
        "services.agent.runtime.call_model",
        "services.agent.orchestrator.call_model",
    ):
        try:
            p = mock.patch(target, side_effect=fake)
            p.start()
            patches.append(p)
        except Exception:
            continue
    try:
        yield fake
    finally:
        for p in patches:
            try:
                p.stop()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════
# S5 — Storage / DATA_DIR
# ═══════════════════════════════════════════════════════════════════════════


@contextmanager
def tmp_data_dir() -> Iterator[Path]:
    """Temporary DATA_DIR for tests that write accounts/config/workspace (S5)."""
    with tempfile.TemporaryDirectory(prefix="c2a_test_data_") as td:
        root = Path(td)
        (root / "agent").mkdir(parents=True, exist_ok=True)
        SEAM_LOG.add("S5", "tmp_data_dir", str(root))
        yield root


@contextmanager
def install_data_dir(path: Path | None = None) -> Iterator[Path]:
    """Point services.config.DATA_DIR (and common aliases) at a temp dir."""
    with tempfile.TemporaryDirectory(prefix="c2a_data_") as td:
        root = Path(path) if path else Path(td)
        root.mkdir(parents=True, exist_ok=True)
        patches = []
        for target in (
            "services.config.DATA_DIR",
            "services.agent.teacher_workspace.DATA_DIR",
        ):
            try:
                p = mock.patch(target, root)
                p.start()
                patches.append(p)
            except Exception:
                continue
        SEAM_LOG.add("S5", "install_data_dir", str(root))
        try:
            yield root
        finally:
            for p in patches:
                try:
                    p.stop()
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════════════════════
# S6 — Bot API (Telegram / Zalo)
# ═══════════════════════════════════════════════════════════════════════════


class FakeBotAPI:
    """Record outbound bot sends without network (S6)."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.photos: list[dict[str, Any]] = []
        self.api_calls: list[dict[str, Any]] = []

    def send_message(self, chat_id: Any = None, text: str = "", **kwargs: Any) -> dict[str, Any]:
        rec = {"chat_id": chat_id, "text": text, **kwargs}
        self.messages.append(rec)
        SEAM_LOG.add("S6", "send_message", chat_id=chat_id, text=(text or "")[:80])
        return {"ok": True, "message_id": len(self.messages)}

    def send_photo(
        self,
        chat_id: Any = None,
        photo: Any = None,
        caption: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        rec = {"chat_id": chat_id, "photo": photo, "caption": caption, **kwargs}
        self.photos.append(rec)
        SEAM_LOG.add("S6", "send_photo", chat_id=chat_id, caption=(caption or "")[:80])
        return {"ok": True, "message_id": len(self.photos)}

    def api_call(self, method: str, **kwargs: Any) -> dict[str, Any]:
        rec = {"method": method, **kwargs}
        self.api_calls.append(rec)
        SEAM_LOG.add("S6", "api_call", method, **{k: str(v)[:40] for k, v in kwargs.items()})
        return {"ok": True, "result": {}}


@contextmanager
def install_bot_api(fake: FakeBotAPI | None = None) -> Iterator[FakeBotAPI]:
    """Patch telegram/zalo send helpers when importable."""
    fake = fake or FakeBotAPI()
    patches = []
    targets = [
        ("services.telegram_bot._api_call", "api_call"),
        ("services.notifier.notify_admin", None),  # special
    ]
    # send_message style
    for mod_path in (
        "services.telegram_bot.send_message",
        "services.zalo_bot.send_message",
        "services.zalo_personal.send_message",
    ):
        try:
            p = mock.patch(mod_path, side_effect=fake.send_message)
            p.start()
            patches.append(p)
        except Exception:
            continue
    for mod_path in (
        "services.telegram_bot.send_photo",
        "services.zalo_bot.send_photo",
        "services.zalo_personal.send_photo",
    ):
        try:
            p = mock.patch(mod_path, side_effect=fake.send_photo)
            p.start()
            patches.append(p)
        except Exception:
            continue
    try:
        p = mock.patch("services.telegram_bot._api_call", side_effect=fake.api_call)
        p.start()
        patches.append(p)
    except Exception:
        pass
    try:
        yield fake
    finally:
        for p in patches:
            try:
                p.stop()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════
# S7 — MCP
# ═══════════════════════════════════════════════════════════════════════════


class FakeMCP:
    """Fake MCP tool list + call (S7)."""

    def __init__(
        self,
        tools: list[dict[str, Any]] | None = None,
        results: dict[str, Any] | None = None,
    ) -> None:
        self.tools = tools or [
            {"name": "demo_tool", "description": "demo", "inputSchema": {"type": "object"}},
        ]
        self.results = results or {}
        self.calls: list[dict[str, Any]] = []

    def list_tools(self) -> list[dict[str, Any]]:
        SEAM_LOG.add("S7", "list_tools")
        return list(self.tools)

    def call_tool(self, name: str, arguments: dict | None = None) -> Any:
        self.calls.append({"name": name, "arguments": arguments or {}})
        SEAM_LOG.add("S7", "call_tool", name)
        if name in self.results:
            return self.results[name]
        return {"content": [{"type": "text", "text": f"fake:{name}"}]}


@contextmanager
def install_mcp(fake: FakeMCP | None = None) -> Iterator[FakeMCP]:
    fake = fake or FakeMCP()
    patches = []
    for target, attr in [
        ("services.mcp_client.get_enabled_mcp_tools", "list_tools"),
        ("services.mcp_client.call_mcp_tool", "call_tool"),
    ]:
        try:
            p = mock.patch(target, side_effect=getattr(fake, attr))
            p.start()
            patches.append(p)
        except Exception:
            continue
    try:
        yield fake
    finally:
        for p in patches:
            try:
                p.stop()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════
# S8 — Doc / media libs (lightweight stubs)
# ═══════════════════════════════════════════════════════════════════════════


class FakeFitzDoc:
    """Minimal fitz-like document for PDF tests that don't need real files."""

    def __init__(self, pages: list[str] | None = None) -> None:
        self._pages = pages or ["page1"]

    def __len__(self) -> int:
        return len(self._pages)

    def load_page(self, i: int) -> Any:
        text = self._pages[i]

        class _Page:
            def get_text(self, *_a: Any, **_k: Any) -> str:
                return text

        return _Page()

    def close(self) -> None:
        SEAM_LOG.add("S8", "fitz_close")


@contextmanager
def install_fitz(pages: list[str] | None = None) -> Iterator[FakeFitzDoc]:
    """Optional: patch fitz.open to return FakeFitzDoc (prefer real fitz when cheap)."""
    doc = FakeFitzDoc(pages)

    def _open(*_a: Any, **_k: Any) -> FakeFitzDoc:
        SEAM_LOG.add("S8", "fitz_open")
        return doc

    try:
        with mock.patch("fitz.open", side_effect=_open):
            yield doc
    except Exception:
        yield doc


# ═══════════════════════════════════════════════════════════════════════════
# Registry helpers
# ═══════════════════════════════════════════════════════════════════════════

SEAM_IDS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")

SEAM_INSTALLERS = {
    "S1": install_provider_http,
    "S2": install_ha,
    "S3": install_socket,
    "S4": install_call_model,
    "S5": install_data_dir,
    "S6": install_bot_api,
    "S7": install_mcp,
    "S8": install_fitz,
}


def reset_seam_log() -> None:
    SEAM_LOG.clear()
