"""MCP Client — connects to MCP servers, fetches tools, proxies tool calls.

Used by the chat completion handler to inject MCP tools into LLM requests
and relay tool calls back to the MCP server.

Session management: each unique (url, api_key) pair gets one persistent
client that reuses the MCP session across requests.

Performance:
- Per-session circuit breaker: a failed init is remembered for 60s so we
  don't retry a dead MCP on every chat request (saves 15s × N every time).
- Module-level tools cache: `get_enabled_mcp_tools()` is called multiple
  times per chat (inject + tool-result loop). Cache the merged list for
  30s so we don't iterate 20+ servers on each call.
- Parallel discovery: tools/list across all enabled MCP servers runs in
  a thread pool, so total cold-start time is max(server) not sum(servers).
"""

from __future__ import annotations

import base64, hashlib, json, logging, re, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
import urllib.request
import urllib.error
import urllib.parse

from services.config import config
from utils.log import logger


# Per-call HTTP timeouts (seconds).
_INIT_TIMEOUT = 5      # initialize / tools/list — keep short so dead MCPs don't block chat
_NOTIFY_TIMEOUT = 2    # fire-and-forget notification
_TOOL_CALL_TIMEOUT = 30  # actual tool execution — user-visible work, allow longer

# Circuit breaker: after a failed init, skip this MCP for this long.
_FAILURE_COOLDOWN = 60.0

# After this many consecutive failures, lengthen the cooldown exponentially so
# permanently dead servers stop costing us a probe every minute.
_MAX_FAST_RETRIES = 3
_LONG_COOLDOWN = 1800.0  # 30 min

_MODERN_PROTOCOL = "2026-07-28"
_LEGACY_PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
# Mã lỗi CHỈ server đời 2026 mới phát ra (dải -32020..-32099 dành riêng cho
# spec). Nhận ra chúng là nhận ra "server này nói MCP mới" — spec bắt client
# ĐỌC THÂN của phản hồi 400 trước khi tụt về bắt tay `initialize`, vì server
# mới cũng trả 400 cho lỗi phiên bản và lỗi header.
_LOI_MCP_MOI = {-32020, -32021, -32022}
_LOI_KHONG_CO_METHOD = -32601
# MRTR: server đòi thêm dữ liệu giữa chừng. Chặn số vòng để một server hỏi vòng
# tròn không giữ luôn lượt chat.
_MRTR_TOI_DA = 3
# Tiền tố của thông báo do CHÍNH gateway dựng khi tool hỏng. Model cần đọc được
# nó, nhưng các nhánh lấy dữ liệu (prefetch, search, KB) thì phải bỏ qua — nhét
# một câu báo lỗi vào ngữ cảnh dưới danh nghĩa "kết quả" là mời model bịa tiếp.
LOI_MCP = "[MCP lỗi]"
CAN_THEM_TT = "[MCP cần thêm thông tin]"


def la_loi_mcp(text: Any) -> bool:
    """Chuỗi này là thông báo lỗi của gateway chứ không phải dữ liệu tool trả về."""
    return isinstance(text, str) and text.startswith((LOI_MCP, CAN_THEM_TT))
_CLIENT_INFO = {"name": "chatgpt2api", "version": "1.5.0"}
_RESERVED_HEADERS = {
    "host", "content-length", "transfer-encoding", "connection",
    "content-type", "accept", "mcp-session-id", "mcp-protocol-version",
    "mcp-method", "mcp-name",
}


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urllib.parse.urlsplit(url)
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme.lower() == "https" else 80
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


def _url_for_log(url: str) -> str:
    """Keep endpoint identity in logs without query credentials/fragments."""
    try:
        parsed = urllib.parse.urlsplit(url)
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except Exception:
        return "[invalid MCP URL]"


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    """Follow path redirects, but never forward MCP credentials cross-origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if _origin(req.full_url) != _origin(newurl):
            raise urllib.error.HTTPError(
                newurl, code, "Cross-origin MCP redirect blocked", headers, fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_MCP_OPENER = urllib.request.build_opener(_SameOriginRedirect())


def _open_url(request: urllib.request.Request, timeout: float):
    return _MCP_OPENER.open(request, timeout=timeout)


def _clean_custom_headers(headers: dict[str, str]) -> dict[str, str]:
    """Keep custom auth/routing headers without allowing HTTP smuggling."""
    clean: dict[str, str] = {}
    for raw_name, raw_value in headers.items():
        name = str(raw_name or "").strip()
        value = str(raw_value or "").strip()
        if not name or not value or name.lower() in _RESERVED_HEADERS:
            continue
        if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
            continue
        clean[name] = value
    return clean


def _encode_mcp_header_value(value: Any) -> str:
    """Encode SEP-2243 header values, including its Base64 sentinel rule."""
    if isinstance(value, bool):
        raw = "true" if value else "false"
    else:
        raw = str(value)
    sentinel = raw.startswith("=?base64?") and raw.endswith("?=")
    unsafe = (
        raw != raw.strip()
        or sentinel
        or any(ord(char) < 0x20 or ord(char) > 0x7E for char in raw)
    )
    if not unsafe:
        return raw
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return f"=?base64?{encoded}?="


_HEADER_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}")
# `number` cố ý KHÔNG có mặt: spec cấm ánh xạ số thực vào header.
_HEADER_TYPES = {"string", "integer", "boolean", "null"}


def _header_annotations(schema: Any, _sau: int = 0) -> list[tuple[list[str], str]] | None:
    """Các tham số được ``x-mcp-header`` ánh xạ thành header ``Mcp-Param-*``.

    Trả danh sách (đường dẫn property, tên header) — hoặc None khi tool khai
    sai. Hai điểm bản cũ bỏ sót:

    · Chỉ đọc property ở TẦNG ĐẦU. Server gắn annotation vào property lồng
      trong object con thì gateway không gửi header, mà spec buộc server đối
      chiếu header với thân request rồi từ chối bằng HeaderMismatch (-32020) —
      tool đó không bao giờ gọi được và lỗi không nói vì sao.
    · Khai sai (tên header trùng nhau, sai token, gắn vào kiểu `number`) thì
      spec buộc client LOẠI tool khỏi danh sách. Giữ lại chỉ tạo ra một tool
      mà mọi lượt gọi đều bị server từ chối.

    Chỉ đi theo chuỗi `properties`; annotation nằm dưới items/oneOf/$ref là
    không hợp lệ theo spec và cũng không có đường lấy giá trị chắc chắn.
    """
    if _sau > 8 or not isinstance(schema, dict):
        return []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    found: list[tuple[list[str], str]] = []
    for name, definition in properties.items():
        if not isinstance(definition, dict):
            continue
        nested = _header_annotations(definition, _sau + 1)
        if nested is None:
            return None
        found.extend(([str(name), *path], header) for path, header in nested)
        raw = definition.get("x-mcp-header")
        if raw is None:
            continue
        if not isinstance(raw, str) or not _HEADER_TOKEN.fullmatch(raw):
            return None
        declared = definition.get("type")
        types = {declared} if isinstance(declared, str) else set(declared or [])
        if types and not types <= _HEADER_TYPES:
            return None
        found.append(([str(name)], raw))
    if len({header.lower() for _path, header in found}) != len(found):
        return None
    return found


class MCPSession:
    """One connected MCP server session. Auto-reconnects on expiry."""

    def __init__(
        self,
        url: str,
        api_key: str = "",
        *,
        headers: dict[str, str] | None = None,
        transport: str = "auto",
    ) -> None:
        self.url = url
        self.api_key = api_key
        self.headers = self._clean_headers(headers or {})
        self.transport = transport if transport in ("auto", "streamable_http", "sse") else "auto"
        self.session_id: str | None = None
        self.server_name: str = ""
        self.server_version: str = ""
        self.server_capabilities: dict[str, Any] = {}
        self.server_instructions: str = ""
        self.protocol_version: str | None = None
        self.protocol_era: str = ""
        self.tools: list[dict[str, Any]] = []
        self.tools_ttl_ms: int | None = None
        self._tools_loaded_at = 0.0
        # RLock chứ không phải Lock: khoá này bảo vệ MỌI hoạt động mạng của một
        # session, mà call_tool() lại gọi ensure_connected() bên trong — Lock
        # thường sẽ tự khoá chính mình. Serialize là BẮT BUỘC: FastMCP không
        # phục vụ được nhiều tools/call đồng thời trên cùng một mcp-session-id
        # (đo thực tế: 8 request song song cùng 1 session → 1 cái về, 7 cái treo
        # vĩnh viễn). Khoá theo TỪNG session nên các MCP server khác nhau vẫn
        # chạy song song bình thường.
        self._lock = threading.RLock()
        self._last_init = 0.0
        # Circuit breaker state
        self._last_failure = 0.0
        self._failure_count = 0

        self._connected = False
        self._request_id = 0
        self._last_http_status: int | None = None
        self._last_error: str = ""
        self._active_transport = "streamable_http"
        self._sse_endpoint: str | None = None
        self._sse_condition = threading.Condition()
        self._sse_responses: dict[int | str, dict[str, Any]] = {}
        self._sse_reader: threading.Thread | None = None
        # Cờ riêng chứ không hỏi `Thread.is_alive()`: luồng kết thúc SẠCH (server
        # đóng dòng) không đánh thức ai, nên người đang chờ phản hồi sẽ nằm chờ
        # đủ timeout dù biết chắc không còn gì để đợi. Cờ này được đặt trong
        # `finally` kèm notify_all nên mọi bên chờ tỉnh dậy ngay.
        self._sse_reader_alive = False
        self._sse_reader_error = ""

    @staticmethod
    def _clean_headers(headers: dict[str, str]) -> dict[str, str]:
        """Keep custom auth/routing headers without allowing HTTP smuggling.

        Protocol-owned headers are generated from the JSON-RPC message and
        cannot be overridden by stored configuration.
        """
        return _clean_custom_headers(headers)

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _modern_meta(self) -> dict[str, Any]:
        return {
            "io.modelcontextprotocol/protocolVersion": _MODERN_PROTOCOL,
            "io.modelcontextprotocol/clientInfo": dict(_CLIENT_INFO),
            "io.modelcontextprotocol/clientCapabilities": {},
        }

    def _tool_argument_headers(self, name: str, arguments: dict[str, Any]) -> dict[str, str]:
        """Dựng header ``Mcp-Param-*`` từ schema mới nhất của tool."""
        native = next((tool for tool in self.tools if tool.get("name") == name), None)
        annotations = _header_annotations((native or {}).get("inputSchema"))
        if not annotations:
            return {}
        result: dict[str, str] = {}
        for path, header_name in annotations:
            value: Any = arguments
            for step in path:
                value = value.get(step) if isinstance(value, dict) else None
            # Thiếu giá trị thì PHẢI bỏ header (spec), và kiểu `number` không
            # được phép mang header nên float cũng bỏ.
            if not isinstance(value, (str, int, bool)):
                continue
            encoded = _encode_mcp_header_value(value)
            if len(encoded) <= 8192:
                result[f"Mcp-Param-{header_name}"] = encoded
        return result

    @staticmethod
    def _doc_sse_stream(response: Any, request_id: int | str | None) -> dict | None:
        """Đọc dòng SSE tới đúng phản hồi của request này rồi ĐÓNG luôn stream.

        Không chờ tới lúc server đóng: 2026-07-28 chỉ KHUYẾN NGHỊ đóng stream
        sau phản hồi cuối, và còn cho phép chèn dòng keep-alive (`: ...`) mà
        client bắt buộc phải bỏ qua. Bản cũ gọi `resp.read()` nên gặp server
        giữ stream mở là mọi lượt gọi treo tới hết timeout rồi trả về rỗng —
        phản hồi ĐÃ VỀ nằm trong buffer nhưng bị vứt cùng ngoại lệ timeout.
        Đóng sớm cũng đúng chuẩn: đóng stream chính là tín hiệu huỷ request.
        """
        ket_qua: dict | None = None
        du_phong: dict | None = None
        data_lines: list[str] = []

        def _nap(khoi: list[str]) -> bool:
            """Nạp một sự kiện SSE. True khi đã đúng phản hồi cần tìm."""
            nonlocal ket_qua, du_phong
            if not khoi:
                return False
            try:
                envelope = json.loads("\n".join(khoi))
            except json.JSONDecodeError:
                return False
            if not isinstance(envelope, dict):
                return False
            if request_id is not None and envelope.get("id") == request_id:
                ket_qua = envelope
                return True
            if du_phong is None and envelope.get("id") != "server-error" and (
                "result" in envelope or "error" in envelope
            ):
                du_phong = envelope
            return False

        for raw_line in response:
            line = raw_line.decode("utf-8", errors="ignore").rstrip("\r\n")
            if line.startswith(":"):
                continue                 # comment/keep-alive
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
                continue
            if line:
                continue                 # event:/id:/retry: — JSON-RPC không cần
            if _nap(data_lines):
                return ket_qua
            data_lines = []
        if _nap(data_lines):
            return ket_qua
        return du_phong

    @staticmethod
    def _error_of(response: dict | None) -> dict[str, Any]:
        error = (response or {}).get("error")
        return error if isinstance(error, dict) else {}

    def _era_tu_phien_ban(self, versions: Any) -> str:
        """Chọn đời giao thức từ danh sách phiên bản server công bố."""
        if not isinstance(versions, list) or not versions:
            return "modern"
        if _MODERN_PROTOCOL in versions:
            return "modern"
        if any(v in versions for v in _LEGACY_PROTOCOLS):
            return "legacy"
        self._last_error = (
            "Server chỉ hỗ trợ MCP " + ", ".join(str(v)[:20] for v in versions[:5])
        )
        return "unsupported"

    def _doc_era(self, discover: dict | None) -> str:
        """Server này nói MCP đời mới (2026) hay đời bắt tay `initialize`?

        Spec 2026-07-28 nói rõ: gặp 400/404 thì phải NGÓ THÂN phản hồi trước
        khi tụt về `initialize`, vì server đời mới cũng dùng đúng những mã HTTP
        đó cho lỗi phiên bản (-32022), lỗi header (-32020) và method lạ
        (-32601). Đoán nhầm thành "legacy" là hỏng hẳn: server chỉ nói đời mới
        sẽ từ chối `initialize`, và bản cũ coi như MCP chết.
        """
        result = (discover or {}).get("result")
        if isinstance(result, dict):
            return self._era_tu_phien_ban(result.get("supportedVersions"))
        error = self._error_of(discover)
        code = error.get("code")
        if code == -32022:
            data = error.get("data")
            supported = data.get("supported") if isinstance(data, dict) else None
            return self._era_tu_phien_ban(supported)
        if code in _LOI_MCP_MOI:
            return "modern"
        # `server/discover` là BẮT BUỘC với server đời mới, nhưng bản cài thiếu
        # nó vẫn còn nói được phần còn lại — thử tiếp bằng tools/call đời mới,
        # hỏng nữa thì nhánh legacy bên dưới vẫn chạy.
        if code == _LOI_KHONG_CO_METHOD and self._last_http_status in (400, 404):
            return "modern"
        return "legacy"

    def _doc_thong_tin_server(self, result: dict[str, Any]) -> None:
        """Lấy tên/phiên bản/capabilities từ kết quả `server/discover`."""
        # isinstance chứ không `dict(... or {})`: server trả `capabilities` là
        # một mảng thì `dict()` ném ValueError ngay giữa lúc nối, và endpoint
        # kiểm tra MCP trả 500 thay vì một câu báo lỗi đọc được.
        caps = result.get("capabilities")
        self.server_capabilities = dict(caps) if isinstance(caps, dict) else {}
        self.server_instructions = str(result.get("instructions") or "")
        info = result.get("serverInfo")
        if not isinstance(info, dict):
            meta = result.get("_meta")
            meta = meta if isinstance(meta, dict) else {}
            info = meta.get("io.modelcontextprotocol/serverInfo")
        if isinstance(info, dict):
            self.server_name = str(info.get("name") or "")
            self.server_version = str(info.get("version") or "")

    def _khong_co_tool(self, response: dict | None) -> bool:
        """`tools/list` trượt vì server này KHÔNG có tool, chứ không phải hỏng.

        MCP cho phép server chỉ có resources/prompts. Coi đó là "chết" thì
        circuit breaker bật, cache tool tụt xuống 30 giây và cả bộ MCP bị dò
        lại liên tục — trong khi server vẫn khoẻ, chỉ là không có tool nào.
        """
        if self.server_capabilities and "tools" not in self.server_capabilities:
            return True
        return self._error_of(response).get("code") == _LOI_KHONG_CO_METHOD

    @staticmethod
    def _response_from_raw(raw: str, request_id: int | str | None) -> dict | None:
        """Decode JSON or request-scoped SSE and select the matching response."""
        candidates: list[Any] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped.startswith("data:"):
                continue
            try:
                candidates.append(json.loads(stripped[5:].strip()))
            except json.JSONDecodeError:
                continue
        if not candidates:
            try:
                candidates.append(json.loads(raw))
            except json.JSONDecodeError:
                return None
        for item in candidates:
            if isinstance(item, dict) and (request_id is None or item.get("id") == request_id):
                return item
        return next((item for item in candidates if isinstance(item, dict)), None)

    def _connect_legacy_sse(self, timeout: float = _INIT_TIMEOUT) -> bool:
        """Open the deprecated HTTP+SSE GET stream and learn its POST URL."""
        with self._sse_condition:
            con_song = self._sse_reader_alive
            if self._sse_endpoint and con_song:
                self._active_transport = "sse"
                return True
            if not con_song:
                # Luồng GET chết (server đóng, hoặc 30 giây không có byte nào)
                # thì endpoint cũ thành vô dụng: POST vẫn gửi được nhưng phản
                # hồi đi trên dòng SSE đã đứt nên không bao giờ về. Bản cũ thấy
                # `_sse_endpoint` còn giá trị là trả True ngay, nên session hỏng
                # VĨNH VIỄN — mọi lần thử lại sau đều rơi đúng vào nhánh đó.
                self._sse_endpoint = None
                self._sse_responses.clear()
                self._sse_reader_error = ""

                def _read_stream() -> None:
                    headers = dict(self.headers)
                    headers["Accept"] = "text/event-stream"
                    if self.api_key:
                        headers["Authorization"] = f"Bearer {self.api_key}"
                    request = urllib.request.Request(self.url, headers=headers, method="GET")
                    event_name = ""
                    data_lines: list[str] = []
                    try:
                        with _open_url(request, timeout=_TOOL_CALL_TIMEOUT) as response:
                            for raw_line in response:
                                line = raw_line.decode("utf-8", errors="ignore").rstrip("\r\n")
                                if line.startswith("event:"):
                                    event_name = line[6:].strip()
                                elif line.startswith("data:"):
                                    data_lines.append(line[5:].lstrip())
                                elif not line:
                                    data = "\n".join(data_lines)
                                    if event_name == "endpoint" and data:
                                        endpoint = urllib.parse.urljoin(self.url, data)
                                        if _origin(endpoint) != _origin(self.url):
                                            raise ValueError("Cross-origin legacy SSE endpoint blocked")
                                        with self._sse_condition:
                                            self._sse_endpoint = endpoint
                                            self._active_transport = "sse"
                                            self._sse_condition.notify_all()
                                    elif data:
                                        try:
                                            envelope = json.loads(data)
                                        except json.JSONDecodeError:
                                            envelope = None
                                        if isinstance(envelope, dict) and "id" in envelope:
                                            with self._sse_condition:
                                                self._sse_responses[envelope["id"]] = envelope
                                                self._sse_condition.notify_all()
                                    event_name = ""
                                    data_lines = []
                    except Exception as exc:
                        with self._sse_condition:
                            self._sse_reader_error = str(exc).replace(
                                self.url, _url_for_log(self.url),
                            )[:500]
                    finally:
                        with self._sse_condition:
                            self._sse_reader_alive = False
                            self._sse_condition.notify_all()

                self._sse_reader = threading.Thread(
                    target=_read_stream,
                    name="mcp-legacy-sse",
                    daemon=True,
                )
                self._sse_reader_alive = True
                self._sse_reader.start()

            deadline = time.monotonic() + timeout
            while (
                not self._sse_endpoint
                and not self._sse_reader_error
                and self._sse_reader_alive
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._sse_condition.wait(remaining)
            if self._sse_endpoint:
                self._active_transport = "sse"
                return True
            self._last_error = self._sse_reader_error or "Timed out waiting for SSE endpoint"
            return False

    def _call_legacy_sse(
        self,
        body: dict[str, Any],
        headers: dict[str, str],
        request_id: int | None,
        notification: bool,
        timeout: float,
    ) -> dict | None:
        endpoint = self._sse_endpoint
        if not endpoint:
            self._last_error = "Legacy SSE endpoint is not connected"
            return None
        if not self._sse_reader_alive:
            # Luồng GET đã đứt: POST vẫn được nhận (202) nhưng phản hồi đi trên
            # dòng đã chết nên không bao giờ về. Báo hỏng ngay để người gọi nối
            # lại từ đầu, thay vì đứng chờ đủ 30 giây rồi mới chịu thua.
            self._connected = False
            self._last_error = "Dòng SSE đã đứt, cần nối lại"
            return None
        post_headers = dict(headers)
        post_headers["Accept"] = "application/json"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode(),
            headers=post_headers,
            method="POST",
        )
        try:
            with _open_url(request, timeout=timeout) as response:
                self._last_http_status = getattr(response, "status", 202)
                raw = response.read().decode("utf-8", errors="ignore")
            if raw.strip():
                direct = self._response_from_raw(raw, request_id)
                if direct:
                    return direct
        except urllib.error.HTTPError as exc:
            self._last_http_status = exc.code
            try:
                raw = exc.read().decode("utf-8", errors="ignore")
            finally:
                exc.close()
            self._last_error = f"HTTP {exc.code}: {raw[:300]}"
            return None
        except Exception as exc:
            self._last_error = str(exc).replace(
                endpoint, _url_for_log(endpoint),
            )[:500]
            return None
        if notification:
            return {}
        if request_id is None:
            return None
        deadline = time.monotonic() + timeout
        with self._sse_condition:
            while (
                request_id not in self._sse_responses
                and not self._sse_reader_error
                and self._sse_reader_alive
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._sse_condition.wait(remaining)
            response = self._sse_responses.pop(request_id, None)
            con_song = self._sse_reader_alive
        if response and response.get("error"):
            self._last_error = str(response["error"])[:500]
        elif response is None:
            if not con_song:
                # Server đóng dòng SSE giữa chừng — không phải hết giờ.
                self._connected = False
            self._last_error = self._sse_reader_error or (
                "Dòng SSE đứt giữa chừng" if not con_song
                else "Timed out waiting for SSE response"
            )
        return response

    def _call(self, method: str, params: dict | None = None, timeout: float | None = None) -> dict | None:
        # NOTIFICATION thì KHÔNG được có `id` — JSON-RPC phân biệt request và
        # notification bằng đúng chỗ đó. Gắn `id` vào `notifications/initialized`
        # là server phải đem nó đi so với cả 28 kiểu ClientRequest rồi trượt hết,
        # đẻ ra một khối 28 lỗi validate MỖI LẦN nối MCP (đo 01/08: 54 khối trong
        # 45 phút log). Bắt tay vẫn xong nên không ai thấy, nhưng log thật bị vùi
        # dưới đống cảnh báo vô nghĩa — đúng thứ làm lỗi thật khó tìm.
        la_thong_bao = method.startswith("notifications/")
        self._last_http_status = None
        self._last_error = ""
        request_id: int | None = None if la_thong_bao else self._next_id()
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not la_thong_bao:
            body["id"] = request_id

        call_params = dict(params or {})
        modern = self.protocol_era == "modern" or method == "server/discover"
        if modern:
            meta = dict(call_params.get("_meta") or {})
            meta.update(self._modern_meta())
            call_params["_meta"] = meta
        if call_params:
            body["params"] = call_params

        headers = dict(self.headers)
        headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Mcp-Method": method,
        })
        if method in ("tools/call", "resources/read", "prompts/get"):
            target = call_params.get("name") if "name" in call_params else call_params.get("uri")
            mcp_name = str(target) if target is not None else ""
            if mcp_name != "":
                headers["Mcp-Name"] = _encode_mcp_header_value(mcp_name)
        if modern and method == "tools/call":
            tool_name = str(call_params.get("name") or "")
            arguments = call_params.get("arguments") or {}
            if tool_name and isinstance(arguments, dict):
                headers.update(self._tool_argument_headers(tool_name, arguments))
        if self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        if self.session_id and not modern:
            headers["mcp-session-id"] = self.session_id
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        effective_timeout = timeout if timeout is not None else _INIT_TIMEOUT
        if self._active_transport == "sse":
            return self._call_legacy_sse(
                body, headers, request_id, la_thong_bao, effective_timeout,
            )

        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=headers)
        try:
            # `with` là bắt buộc: không đóng tường minh thì socket chỉ được thu
            # khi GC chạy. Dưới tải cao (autofill SGK bắn hàng nghìn lượt) fd
            # dồn lại tới mức cả tiến trình chết vì [Errno 24] Too many open
            # files — hỏng luôn mọi thứ khác chứ không riêng khâu gọi MCP.
            with _open_url(
                req, timeout=effective_timeout
            ) as resp:
                sid = resp.getheader("mcp-session-id")
                if sid:
                    self.session_id = sid
                self._last_http_status = getattr(resp, "status", 200)
                # Streamable HTTP cho server chọn: một JSON gọn, hoặc một dòng
                # SSE. Dòng SSE phải đọc dần rồi đóng ngay khi có phản hồi.
                la_sse = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower() == "text/event-stream"
                if la_sse:
                    d = self._doc_sse_stream(resp, request_id)
                    raw = ""
                else:
                    # Read response - FastMCP can return plain JSON or SSE
                    raw = resp.read().decode('utf-8', errors='ignore')
                    d = None
            if la_sse:
                if isinstance(d, dict):
                    if d.get("error"):
                        self._last_error = str(d.get("error"))[:500]
                    return d
                if la_thong_bao:
                    return {}
                self._last_error = "Dòng SSE kết thúc mà không có phản hồi JSON-RPC"
                return None
            if la_thong_bao and not raw.strip():
                return {}
            d = self._response_from_raw(raw, request_id)
            if isinstance(d, dict) and d.get("id") != "server-error":
                if d.get("error"):
                    self._last_error = str(d.get("error"))[:500]
                return d
        except urllib.error.HTTPError as e:
            self._last_http_status = e.code
            sid = e.getheader("mcp-session-id")
            if sid:
                self.session_id = sid
            try:
                # errors="ignore": thân lỗi của server lạ có thể không phải
                # UTF-8; để nó ném ra thì cả `_call` chết vì một câu báo lỗi.
                raw = e.read().decode("utf-8", errors="ignore")
            finally:
                e.close()  # HTTPError cũng giữ một socket — đóng luôn
            d = self._response_from_raw(raw, request_id)
            if isinstance(d, dict):
                self._last_error = str(d.get("error") or f"HTTP {e.code}")[:500]
                return d
            self._last_error = f"HTTP {e.code}: {raw[:300]}"
        except Exception as exc:
            safe_error = str(exc).replace(self.url, _url_for_log(self.url))
            self._last_error = safe_error[:500]
            if self._chi_la_hub_chua_len(exc):
                logger.info({"event": "mcp_hub_chua_len", "url": _url_for_log(self.url),
                             "error": safe_error})
            else:
                logger.warning({"event": "mcp_call_failed", "url": _url_for_log(self.url),
                                "error": safe_error})
        return None

    def _load_tools(self, *, allow_missing: bool = False) -> bool:
        """Fetch every ``tools/list`` page advertised by the server.

        ``allow_missing`` chỉ bật khi đã biết chắc đời giao thức (discover hoặc
        initialize thành công): lúc đó `tools/list` bị từ chối nghĩa là server
        không có tool, không phải nối hỏng.
        """
        collected: list[dict[str, Any]] = []
        ttl_values: list[int] = []
        cursor: str | None = None
        for _page in range(100):
            params = {"cursor": cursor} if cursor else None
            response = self._call("tools/list", params, timeout=_INIT_TIMEOUT)
            if not response or response.get("error") or not isinstance(response.get("result"), dict):
                if allow_missing and cursor is None and self._khong_co_tool(response):
                    self.tools = []
                    self.tools_ttl_ms = None
                    self._tools_loaded_at = time.monotonic()
                    return True
                return False
            result = response["result"]
            try:
                ttl_ms = int(result.get("ttlMs") or 0)
            except (TypeError, ValueError):
                ttl_ms = 0
            if ttl_ms > 0:
                ttl_values.append(ttl_ms)
            page_tools = result.get("tools") or []
            if isinstance(page_tools, list):
                for tool in page_tools:
                    if not isinstance(tool, dict):
                        continue
                    if self.protocol_era == "modern" and _header_annotations(
                        tool.get("inputSchema"),
                    ) is None:
                        logger.warning({
                            "event": "mcp_tool_schema_invalid",
                            "url": _url_for_log(self.url),
                            "tool": str(tool.get("name") or "")[:80],
                            "reason": "x-mcp-header khai sai",
                        })
                        continue
                    collected.append(tool)
            nxt = result.get("nextCursor")
            if not nxt:
                self.tools = collected
                self.tools_ttl_ms = min(ttl_values) if ttl_values else None
                self._tools_loaded_at = time.monotonic()
                return True
            cursor = str(nxt)
        self._last_error = "tools/list exceeded 100 pages"
        return False

    def _la_hub_cung_container(self) -> bool:
        """MCP này có nằm cùng container với gateway không (loopback)."""
        u = self.url or ""
        return "127.0.0.1" in u or "localhost" in u or "://[::1]" in u

    def _chi_la_hub_chua_len(self, exc: Exception) -> bool:
        """Lần dò ĐẦU tới hub cùng container bị từ chối = hub chưa lắng nghe.

        Cùng nhận định mà `_current_cooldown` đã dựa vào để rút cooldown xuống
        8 giây; ở đây áp nốt cho MỨC LOG. Đo trên máy chủ 22/08 sau một lần
        khởi động lại: 26 dòng WARNING `mcp_call_failed` dồn trong 17 mili
        giây, rồi 26 dòng `mcp_tools_loaded` — tức đã nạp đủ cả 26 công cụ.

        Vì sao đáng sửa chứ không chỉ là ồn: một chùm 26 dòng lúc khởi động
        trông Y HỆT một lần hub chết thật, nên cảnh báo này vừa kêu oan vừa che
        mất tín hiệu thật. Hạ lần đầu xuống INFO thì hub chết thật vẫn kêu, chỉ
        chậm 8 giây (một nhịp cooldown) — đổi lại cảnh báo trở lại có nghĩa.

        `_failure_count` là 0 khi và chỉ khi đây là lần hỏng đầu kể từ lần nối
        thành công gần nhất (xem `ensure_connected`), nên không cần thêm trạng
        thái mới.
        """
        if self._failure_count:
            return False
        if not isinstance(getattr(exc, "reason", None), ConnectionRefusedError):
            return False
        return self._la_hub_cung_container()

    def _current_cooldown(self) -> float:
        """Cooldown grows after repeated failures so a permanently dead MCP
        only costs us a probe every 30 min instead of every minute.

        Exception: an in-container hub MCP (127.0.0.1/localhost) that refuses
        the connection is almost always just still starting up, not dead — the
        gateway and hub boot together and the hub takes ~40s to mount all MCPs.
        Keep its cooldown short so tools self-heal within a minute of boot
        instead of being circuit-broken for 30 min."""
        if self._la_hub_cung_container():
            return 8.0
        if self._failure_count >= _MAX_FAST_RETRIES:
            return _LONG_COOLDOWN
        return _FAILURE_COOLDOWN

    def ensure_connected(self) -> bool:
        """Initialize session if not connected. Returns True on success.

        Circuit-breaker: if a previous init failed within the cooldown window,
        return False immediately so a single dead MCP can't add 15s × N to
        every chat request. Repeated failures lengthen the cooldown.
        """
        now = time.time()
        # Fast path check for session validity (5 min TTL)
        if self._connected and (now - self._last_init) < 300:
            return True

        # Circuit breaker: don't retry a dead MCP within current cooldown
        if self._last_failure and (now - self._last_failure) < self._current_cooldown():
            return False

        with self._lock:
            now = time.time()
            if self._connected and (now - self._last_init) < 300:
                return True
            if self._last_failure and (now - self._last_failure) < self._current_cooldown():
                return False

            # MCP 2026 is stateless and starts with server/discover.  Probe it
            # first, then fall back to the initialize/session era used by older
            # n8n and FastMCP servers.
            if self.transport != "sse":
                self._active_transport = "streamable_http"
                self.protocol_era = "modern"
                self.protocol_version = _MODERN_PROTOCOL
                discover = self._call("server/discover", timeout=_INIT_TIMEOUT)
                era = self._doc_era(discover)
                if era == "unsupported":
                    # Server đời mới nhưng không có phiên bản nào nói chung được.
                    # Tụt xuống `initialize` chỉ đổi một lỗi rõ ràng thành một
                    # lỗi khó hiểu, nên dừng luôn và giữ nguyên `_last_error`.
                    self._connected = False
                    self._last_failure = now
                    self._failure_count += 1
                    return False
                if era == "modern":
                    discover_result = (discover or {}).get("result")
                    da_discover = isinstance(discover_result, dict)
                    if da_discover:
                        self._doc_thong_tin_server(discover_result)
                    if self._load_tools(allow_missing=da_discover):
                        self._connected = True
                        self._last_init = now
                        self._last_failure = 0.0
                        self._failure_count = 0
                        return True

            self.protocol_era = "legacy"
            self.protocol_version = None
            self.session_id = None
            if self.transport == "sse" and not self._connect_legacy_sse():
                self._connected = False
                self._last_failure = now
                self._failure_count += 1
                return False
            init: dict | None = None
            for offered_version in _LEGACY_PROTOCOLS:
                candidate = self._call("initialize", {
                    "protocolVersion": offered_version,
                    "capabilities": {},
                    "clientInfo": dict(_CLIENT_INFO),
                }, timeout=_INIT_TIMEOUT)
                if candidate and isinstance(candidate.get("result"), dict):
                    init = candidate
                    break
                if candidate is None and self._last_http_status is None:
                    break
                self.session_id = None
            # Old HTTP+SSE servers reject POST on the GET stream URL (usually
            # 404/405). In auto mode, only those transport-shaped failures
            # trigger a legacy GET stream probe; auth failures never do.
            if (
                not init
                and self.transport == "auto"
                and self._last_http_status in (400, 404, 405)
                and self._connect_legacy_sse()
            ):
                self.protocol_version = None
                self.session_id = None
                for offered_version in _LEGACY_PROTOCOLS:
                    candidate = self._call("initialize", {
                        "protocolVersion": offered_version,
                        "capabilities": {},
                        "clientInfo": dict(_CLIENT_INFO),
                    }, timeout=_INIT_TIMEOUT)
                    if candidate and isinstance(candidate.get("result"), dict):
                        init = candidate
                        break
                    if candidate is None and self._last_http_status is None:
                        break
            if not init:
                self.session_id = None
                self._connected = False
                self._last_failure = now
                self._failure_count += 1
                return False

            init_result = init.get("result", {})
            self.protocol_version = str(init_result.get("protocolVersion") or _LEGACY_PROTOCOLS[-1])
            caps = init_result.get("capabilities")
            self.server_capabilities = dict(caps) if isinstance(caps, dict) else {}
            self.server_instructions = str(init_result.get("instructions") or "")
            info = init_result.get("serverInfo")
            info = info if isinstance(info, dict) else {}
            self.server_name = str(info.get("name") or "")
            self.server_version = str(info.get("version") or "")

            # This is the first request after initialize, so it already carries
            # the negotiated MCP-Protocol-Version header required by HTTP MCP.
            try:
                self._call("notifications/initialized", timeout=_NOTIFY_TIMEOUT)
            except Exception:
                pass

            if not self._load_tools(allow_missing=True):
                self.session_id = None
                self._connected = False
                self._last_failure = now
                self._failure_count += 1
                return False
            self._connected = True
            self._last_init = now
            self._last_failure = 0.0
            self._failure_count = 0
            return True

    def get_tools(self) -> list[dict[str, Any]]:
        """Return OpenAI-format tools list for injection into chat completions."""
        if not self.ensure_connected():
            return []
        if (
            self.tools_ttl_ms
            and self._tools_loaded_at
            and (time.monotonic() - self._tools_loaded_at) * 1000 >= self.tools_ttl_ms
        ):
            with self._lock:
                if (time.monotonic() - self._tools_loaded_at) * 1000 >= self.tools_ttl_ms:
                    self._load_tools()
        openai_tools: list[dict[str, Any]] = []
        for t in self.tools:
            name = str(t.get("name") or "")
            desc = str(t.get("description") or "")
            # `or` chứ không phải giá trị mặc định của `.get`: server gửi
            # `"inputSchema": null` là khoá CÓ mặt với giá trị None, nên bản cũ
            # đưa `parameters: null` vào định nghĩa tool. Nhà cung cấp model từ
            # chối cả request đó — hỏng nguyên lượt chat chứ không riêng tool này.
            schema = t.get("inputSchema")
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": schema,
                },
            })
        return openai_tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str | None:
        """Call an MCP tool and return the text result.

        Toàn bộ thân hàm nằm trong self._lock: session_id là trạng thái CHUNG,
        mà nhánh thử-lại bên dưới xoá nó giữa chừng. Không khoá thì thread A
        xoá session_id đúng lúc thread B đang gửi dở → B mất session, server
        treo request của B, và cả hai cùng chết.
        """
        with self._lock:
            if not self.ensure_connected():
                return None
            params = {"name": name, "arguments": arguments}
            result = self._call("tools/call", params, timeout=_TOOL_CALL_TIMEOUT)
            if self._phien_co_the_chet(result):
                # Session co the da CHET (vd MCP server vua restart nhung gateway con
                # trong 5-min TTL nen tuong con song) -> vo hieu, ket noi lai, thu LAI
                # 1 lan. Khong co buoc nay thi moi lan redeploy MCP la chat roi xuong
                # model (codex) cham + dai dong.
                self.session_id = None
                self._connected = False
                self._last_init = 0.0
                self._last_failure = 0.0
                if self.ensure_connected():
                    result = self._call("tools/call", params, timeout=_TOOL_CALL_TIMEOUT)
            return self._ket_qua_tool(name, params, result)

    def _phien_co_the_chet(self, result: dict | None) -> bool:
        """Có đáng nối lại rồi gọi lại tool một lần nữa không.

        Chỉ hỏng ở tầng vận chuyển mới đáng: không có phản hồi nào, hoặc server
        trả 400/404/409 — dấu hiệu session đã bị thu hồi. Bản cũ nối lại cho
        MỌI phản hồi thiếu `result`, nên một lỗi nghiệp vụ bình thường (sai
        tham số) phải trả giá bằng một vòng nối lại cộng một lần gọi lại, rồi
        vẫn hỏng. Mà `{}` cũng là giá trị giả nên tool trả kết quả rỗng hợp lệ
        cũng bị coi là session chết.
        """
        if result is None:
            return True
        if not self._error_of(result):
            return False
        return self._last_http_status in (400, 404, 409)

    def _ket_qua_tool(
        self,
        name: str,
        params: dict[str, Any],
        result: dict | None,
        vong: int = 0,
    ) -> str | None:
        """Đổi phản hồi `tools/call` thành văn bản cho model."""
        if result is None:
            return None
        error = self._error_of(result)
        if error:
            # Nói thẳng lỗi cho model thay vì trả None. None chỉ cho model biết
            # "tool hỏng" — nó đoán bừa hoặc bỏ cuộc; còn "thiếu tham số x" thì
            # nó gọi lại đúng ngay lượt sau.
            message = str(error.get("message") or "").strip() or f"mã {error.get('code')}"
            return f"{LOI_MCP} {name}: {message}"[:2000]
        payload = result.get("result")
        if not isinstance(payload, dict):
            return None
        loai = payload.get("resultType")
        if loai == "input_required":
            return self._tra_loi_input_required(name, params, payload, vong)
        if loai not in (None, "complete"):
            # Spec: resultType lạ PHẢI coi là không hợp lệ (thường là extension
            # ta chưa nói được), đừng đọc bừa phần content bên trong.
            return f"{LOI_MCP} {name}: server trả resultType lạ '{str(loai)[:40]}'"
        content = payload.get("content")
        content = content if isinstance(content, list) else []
        texts = [str(c.get("text") or "") for c in content
                 if isinstance(c, dict) and c.get("type") == "text"]
        if texts:
            return "\n".join(texts)
        if "structuredContent" in payload:
            return json.dumps(payload["structuredContent"], ensure_ascii=False)
        return json.dumps(content, ensure_ascii=False)

    def _tra_loi_input_required(
        self,
        name: str,
        params: dict[str, Any],
        payload: dict[str, Any],
        vong: int,
    ) -> str | None:
        """MRTR (MCP 2026): server dừng giữa chừng để xin thêm dữ liệu.

        Server không giữ trạng thái nữa, nên thay vì mở stream chờ, nó trả
        `resultType: "input_required"` kèm `requestState` để client gửi lại.
        Bản cũ không biết kiểu kết quả này: nó đọc `content` (rỗng) rồi trả về
        `"[]"` — model tưởng tool chạy xong và trả lời bịa.

        Gateway khai `clientCapabilities` rỗng nên server đúng chuẩn KHÔNG được
        hỏi elicitation/sampling; chỉ có `requestState` thì gửi lại được ngay.
        Server nào vẫn hỏi thì nói thật là ở đây không có ai để hỏi.
        """
        yeu_cau = payload.get("inputRequests")
        if isinstance(yeu_cau, dict) and yeu_cau:
            can = ", ".join(
                str((v.get("method") or k) if isinstance(v, dict) else k)
                for k, v in list(yeu_cau.items())[:5]
            )
            return (
                f"{CAN_THEM_TT} {name}: server đòi {can}. "
                "Gateway không hỏi lại người dùng giữa một lượt gọi tool được — "
                "hãy nói người dùng cấu hình sẵn thông tin đó ở phía MCP server."
            )
        state = payload.get("requestState")
        if state is None:
            return None
        if vong >= _MRTR_TOI_DA:
            return (
                f"{CAN_THEM_TT} {name}: server xin thêm dữ liệu quá "
                f"{_MRTR_TOI_DA} vòng mà chưa xong, gateway dừng lại."
            )
        tiep = dict(params)
        tiep["requestState"] = state
        result = self._call("tools/call", tiep, timeout=_TOOL_CALL_TIMEOUT)
        return self._ket_qua_tool(name, tiep, result, vong + 1)


def validate_mcp_server(
    url: str,
    api_key: str = "",
    *,
    headers: dict[str, str] | None = None,
    transport: str = "auto",
) -> dict[str, Any]:
    """Negotiate with an MCP server and return a credential-safe report."""
    safe_headers = _clean_custom_headers(headers or {})
    session = MCPSession(
        url,
        api_key,
        headers=safe_headers,
        transport=transport,
    )
    if not session.ensure_connected():
        error = (session._last_error or "MCP negotiation failed").replace(
            url, _url_for_log(url),
        )
        for secret in [api_key, *safe_headers.values()]:
            if secret:
                error = error.replace(secret, "[REDACTED]")
        return {
            "ok": False,
            "name": "",
            "version": "",
            "protocol_version": session.protocol_version or "",
            "transport": session._active_transport,
            "tools": [],
            "capabilities": {},
            "errors": [error[:500]],
        }
    tools = [{
        "name": str(tool.get("name") or ""),
        "description": str(tool.get("description") or ""),
    } for tool in session.tools if isinstance(tool, dict) and tool.get("name")]
    return {
        "ok": True,
        "name": session.server_name or "MCP Server",
        "version": session.server_version,
        "protocol_version": session.protocol_version or "",
        "transport": session._active_transport,
        "tools": tools,
        "capabilities": session.server_capabilities,
        "errors": [],
    }


# ── Global session pool ─────────────────────────────────────────────────────

_sessions: dict[str, MCPSession] = {}
_sessions_lock = threading.Lock()

# Tools cache: shared across the request pipeline so we don't iterate 20+
# servers three times per chat completion. The tool schemas almost never
# change at runtime — bump to 15 min so the first request after the previous
# 5-min TTL doesn't pay a 2.5s re-discovery cost (visible in chat traces).
# A new MCP server appearing in config still triggers an immediate re-probe
# via invalidate_tools_cache().
_TOOLS_CACHE_TTL = 900.0
# TTL rút ngắn khi có server dò KHÔNG NỐI ĐƯỢC. Hub trong cùng container khởi
# động sau gateway ~40s; lần dò đầu gặp "connection refused" và bản cũ đóng băng
# kết quả RỖNG suốt 15 phút — bot mất sạch tool dù hub đã lên từ lâu.
_TOOLS_CACHE_FAIL_TTL = 30.0
_tools_cache: list[dict[str, Any]] | None = None
_tools_cache_ts: float = 0.0
_tools_cache_ttl: float = _TOOLS_CACHE_TTL
_tools_cache_signature: str = ""
_tools_cache_lock = threading.Lock()
# Public OpenAI tool name -> (pooled session key, native MCP tool name).
# MCP permits multiple servers to publish the same tool name; OpenAI function
# calls do not carry a server id, so the merged namespace needs an explicit,
# stable route instead of silently dropping the later server's tool.
_tool_routes: dict[str, tuple[str, str]] = {}

# Concurrency for parallel MCP probing
_PROBE_WORKERS = 16


def _configured_servers() -> list[dict[str, Any]]:
    raw = config.data.get("mcp_servers") or []
    if isinstance(raw, dict):
        result: list[dict[str, Any]] = []
        for server_id, value in raw.items():
            if not isinstance(value, dict):
                continue
            item = dict(value)
            item.setdefault("id", str(server_id))
            result.append(item)
        return result
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _connection_options(info: dict) -> tuple[str, str, dict[str, str], str]:
    url = str(info.get("url") or "").strip()
    api_key = str(info.get("api_key") or "")
    raw_headers = info.get("headers") or {}
    headers = raw_headers if isinstance(raw_headers, dict) else {}
    transport = str(info.get("transport") or "auto")
    if transport not in ("auto", "streamable_http", "sse"):
        transport = "auto"
    return url, api_key, _clean_custom_headers(headers), transport


def _session_key(
    url: str,
    api_key: str,
    headers: dict[str, str] | None = None,
    transport: str = "auto",
) -> str:
    """Return a secret-safe identity for every connection-affecting option."""
    identity = json.dumps(
        {
            "api_key": api_key,
            "headers": headers or {},
            "transport": transport,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(identity.encode()).hexdigest()[:20]
    return f"{url}::{digest}"


def _enabled_signature(installed: list[dict]) -> str:
    """A short string that changes whenever the enabled-MCP set changes,
    so we invalidate the cache on config edits."""
    parts: list[dict[str, Any]] = []
    for info in installed:
        if not info.get("enabled", True):
            continue
        url, api_key, headers, transport = _connection_options(info)
        if not url:
            continue
        parts.append({
            "id": str(info.get("id") or info.get("name") or ""),
            "url": url,
            "api_key": api_key,
            "headers": headers,
            "transport": transport,
        })
    canonical = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _collect_tools_one(info: dict) -> tuple[str, str, list[dict[str, Any]], bool, int | None]:
    """Worker: probe one MCP → (name, session key, tools, nối_được).

    `get_tools()` trả [] cho CẢ hai trường hợp "server không có tool" và "không
    nối được", nên phải hỏi `ensure_connected()` riêng: chỉ có nó phân biệt được
    hub chưa lên với hub rỗng, và người gọi cần biết để đừng cache lâu.
    """
    name = info.get("name", "unknown")
    url, api_key, headers, transport = _connection_options(info)
    if not url:
        return name, "", [], True, None
    key = _session_key(url, api_key, headers, transport)
    with _sessions_lock:
        if key not in _sessions:
            _sessions[key] = MCPSession(
                url, api_key, headers=headers, transport=transport,
            )
        session = _sessions[key]
    try:
        if not session.ensure_connected():
            return name, key, [], False, None
        tools = session.get_tools()
        return name, key, tools, True, getattr(session, "tools_ttl_ms", None)
    except Exception as exc:
        logger.warning({"event": "mcp_session_failed", "name": name, "error": str(exc)})
        return name, key, [], False, None


def _safe_tool_name(raw: str, *, prefix: str = "") -> str:
    """Map arbitrary MCP names into OpenAI's portable function-name subset."""
    base = f"{prefix}__{raw}" if prefix else raw
    clean = re.sub(r"[^A-Za-z0-9_-]+", "_", base).strip("_") or "mcp_tool"
    if len(clean) <= 64:
        return clean
    suffix = hashlib.sha256(base.encode()).hexdigest()[:8]
    return f"{clean[:55]}_{suffix}"


def _unique_tool_name(raw: str, server_id: str, used: set[str]) -> str:
    direct = _safe_tool_name(raw)
    if direct not in used:
        return direct
    prefixed = _safe_tool_name(raw, prefix=_safe_tool_name(server_id).lower())
    if prefixed not in used:
        return prefixed
    digest = hashlib.sha256(f"{server_id}\0{raw}".encode()).hexdigest()[:8]
    candidate = _safe_tool_name(f"{prefixed}_{digest}")
    counter = 2
    while candidate in used:
        candidate = _safe_tool_name(f"{prefixed}_{digest}_{counter}")
        counter += 1
    return candidate


def get_enabled_mcp_tools() -> list[dict[str, Any]]:
    """Collect OpenAI-format tools from all enabled MCP servers in config.

    Cached for _TOOLS_CACHE_TTL seconds and discovered in parallel across
    servers. A single dead MCP (circuit-broken) costs ~0ms; a healthy MCP
    only pays the one-time cold-start cost.
    """
    global _tools_cache, _tools_cache_ts, _tools_cache_ttl, _tools_cache_signature, _tool_routes

    installed = _configured_servers()
    if not installed:
        return []

    enabled = [i for i in installed if i.get("enabled", True) and i.get("url")]
    signature = _enabled_signature(enabled)
    now = time.time()

    # Fast path: cache hit
    if (
        _tools_cache is not None
        and signature == _tools_cache_signature
        and (now - _tools_cache_ts) < _tools_cache_ttl
    ):
        return list(_tools_cache)

    with _tools_cache_lock:
        now = time.time()
        if (
            _tools_cache is not None
            and signature == _tools_cache_signature
            and (now - _tools_cache_ts) < _tools_cache_ttl
        ):
            return list(_tools_cache)

        logger.info({
            "event": "mcp_debug_v2",
            "total": len(installed),
            "enabled_count": len(enabled),
            "urls": [_url_for_log(str(i.get("url", "")))[:60] for i in enabled[:3]],
        })

        # Probe all enabled MCPs in parallel.
        seen_names: set[str] = set()
        all_tools: list[dict[str, Any]] = []
        routes: dict[str, tuple[str, str]] = {}
        unreachable: list[str] = []
        results: list[tuple[str, str, list[dict[str, Any]], bool, int | None] | None] = [None] * len(enabled)
        advertised_ttls: list[float] = []
        workers = min(_PROBE_WORKERS, max(1, len(enabled)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_collect_tools_one, info): (index, info)
                for index, info in enumerate(enabled)
            }
            for fut in as_completed(futures):
                index, info = futures[fut]
                try:
                    results[index] = fut.result()
                except Exception as exc:
                    logger.warning({"event": "mcp_session_failed", "name": info.get("name", "unknown"), "error": str(exc)})
                    unreachable.append(info.get("name", "unknown"))
        # Preserve config order even though discovery itself is parallel. This
        # keeps aliases stable across process starts and network timing changes.
        for index, result in enumerate(results):
            if result is None:
                continue
            name, key, tools, connected, ttl_ms = result
            info = enabled[index]
            server_id = str(info.get("id") or name or "mcp")
            if not connected:
                unreachable.append(name)
            elif ttl_ms and ttl_ms > 0:
                advertised_ttls.append(max(5.0, ttl_ms / 1000.0))
            for tool in tools:
                function = tool.get("function", {}) or {}
                native_name = str(function.get("name") or "")
                if not native_name:
                    continue
                exposed_name = _unique_tool_name(native_name, server_id, seen_names)
                seen_names.add(exposed_name)
                # JSON round-trip is a compact deep copy for these JSON schemas.
                exposed = json.loads(json.dumps(tool, ensure_ascii=False))
                exposed["function"]["name"] = exposed_name
                if exposed_name != native_name:
                    desc = str(exposed["function"].get("description") or "").strip()
                    suffix = f"MCP server: {name}"
                    exposed["function"]["description"] = f"{desc}\n\n{suffix}".strip()
                routes[exposed_name] = (key, native_name)
                all_tools.append(exposed)
            logger.info({"event": "mcp_tools_loaded", "name": name, "count": len(tools)})

        _tools_cache = all_tools
        _tool_routes = routes
        _tools_cache_ts = now
        # Có server chưa nối được → giữ kết quả này rất ngắn để lần sau dò lại,
        # thay vì đóng băng danh sách thiếu tool suốt 15 phút.
        if unreachable:
            _tools_cache_ttl = _TOOLS_CACHE_FAIL_TTL
        elif advertised_ttls:
            _tools_cache_ttl = min(_TOOLS_CACHE_TTL, *advertised_ttls)
        else:
            _tools_cache_ttl = _TOOLS_CACHE_TTL
        _tools_cache_signature = signature
        if unreachable:
            logger.warning({
                "event": "mcp_partial_discovery",
                "unreachable": unreachable[:5],
                "retry_in_s": _TOOLS_CACHE_FAIL_TTL,
            })
        return list(all_tools)


def invalidate_tools_cache() -> None:
    """Force `get_enabled_mcp_tools()` to re-probe on its next call.

    Call this after editing the MCP server list (install / uninstall / toggle).
    """
    global _tools_cache, _tools_cache_ts, _tools_cache_ttl, _tools_cache_signature, _tool_routes
    with _tools_cache_lock:
        _tools_cache = None
        _tools_cache_ts = 0.0
        _tools_cache_ttl = _TOOLS_CACHE_TTL
        _tools_cache_signature = ""
        _tool_routes = {}


def prewarm_tools_cache() -> None:
    """Fire-and-forget background prewarm so the first chat request doesn't
    pay the cold-start probe cost. Safe to call multiple times.
    """
    def _run() -> None:
        try:
            get_enabled_mcp_tools()
        except Exception as exc:
            logger.warning({"event": "mcp_prewarm_failed", "error": str(exc)})
    threading.Thread(target=_run, daemon=True, name="mcp-prewarm").start()


# Catch-all search/encyclopedia tools — kept for EVERY info query so anything
# stays answerable even when no specialized server matches.
_MCP_GENERIC_NAMES = {
    "search_web", "search_all", "get_search_sources",
    "web_search_exa", "web_fetch_exa",
    "search", "get_summary", "get_full_article",  # Wikipedia
}
# Specialized servers: (folded query keywords) -> (tool-name substrings to keep).
# Each entry: (keywords, tool-name substrings, replaces_search).
# A query only pulls in the tools it actually needs (instead of all 43 schemas).
# replaces_search=True → câu này có nguồn REALTIME/chuyên dụng tốt hơn web search
# (giá vàng, thời tiết, cổ phiếu…) → bỏ web search, gọi thẳng tool. False → kho
# kiến thức RAG (y tế, giáo dục…) → vẫn chạy search để bổ sung.
_MCP_INTENT_MAP: tuple[tuple[tuple[str, ...], tuple[str, ...], bool], ...] = (
    # NB: weather (get_current_weather/wttr.in) geocode SAI tên tiếng Việt có dấu
    # ("Vũng Tàu" → ra Brazil) → để câu thời tiết dùng auto-search (đúng + 5.5s),
    # KHÔNG đưa vào đây. Sửa tận gốc thuộc MCP server weather, không phải gateway.
    (("am lich", "duong lich", "ngay am", "can chi", "hoang dao", "gio tot", "ngay tot", "ram", "mong mot", "giap ty"), ("lunar", "can_chi", "hoang_dao"), True),
    (("luat", "nghi dinh", "thong tu", "phap luat", "bo luat", "dieu khoan", "quy dinh phap"), ("law",), True),
    # NB: bỏ get_market_overview ("market") — trả VN-Index=0 (endpoint hỏng);
    # để câu chỉ-số/tổng-quan rơi xuống search. get_stock_price/info vẫn realtime.
    (("co phieu", "chung khoan", "vn-index", "vnindex", "niem yet", "hose", "hnx", "upcom"), ("stock",), True),
    (("dien nuoc", "dieu hoa", "chiller", "mcb", "mccb", "aptomat", "cong suat dien"), ("dien_nuoc",), False),
    (("tin tuc", "thoi su", "bao moi", "tin moi", "diem tin"), ("news",), True),
    (("y te", "suc khoe", "so cuu", "trieu chung", "benh "), ("y_te",), False),
    (("arxiv", "paper", "bai bao khoa hoc", "cong trinh nghien cuu"), ("paper",), True),
    (("vang", "gia vang", "ty gia", "ngoai te", "usd", "do la", "euro", "sjc", "doji", "ngoai hoi"), ("gold", "exchange", "vcb_rates"), True),
    (("giao duc", "phuong phap hoc", "chuong trinh hoc"), ("giao_duc",), False),
    (("ngoai ngu", "ngu phap", "tu dien", "luyen thi", "tieng anh"), ("ngoai_ngu",), False),
    (("vat ly", "hoa hoc", "sinh hoc", "thien van", "khoa hoc"), ("khoa_hoc",), False),
    (("dong vat", "thuc vat", "he sinh thai", "dia ly", "tu nhien"), ("tu_nhien",), False),
    (("lich su", "van hoa", "dan toc", "xa hoi", "kinh te viet"), ("xa_hoi",), False),
    (("youtube", "transcript", "phu de video"), ("transcript", "languages"), True),
    (("xang", "gia dau", "petrol", "nhien lieu"), ("petrol",), True),
)


# ── Server-admin intent (ssh_exec / fs_remote) ──────────────────────────────
# These MCPs run commands / read-write files on declared servers. They aren't
# keyword-mappable like weather/gold, so we detect them by (a) a declared server
# name appearing in the query, or (b) explicit sysadmin keywords. When matched,
# we inject ONLY the ssh_*/fs_* tools (a server op never needs web search).

_ssh_names_cache: set[str] = set()
_ssh_names_ts = 0.0
_SSH_NAMES_TTL = 30.0

_SERVER_ADMIN_KEYWORDS = (
    "ssh", " server", "may chu", "vps", "o dia", "o cung", "dung luong", "disk",
    "docker", "container", "systemctl", "uptime", "df -h", "log server",
    "restart dich vu", "khoi dong lai dich vu", "cpu load", "ram con",
)


def _ssh_server_names() -> set[str]:
    """Declared server names from the shared registry (cached ~30s).

    The gateway and vn-mcp-hub share /app/data, so we read ssh_servers.json
    directly instead of round-tripping through the hub on every chat request.
    """
    global _ssh_names_cache, _ssh_names_ts
    now = time.time()
    if _ssh_names_ts > 0 and (now - _ssh_names_ts) < _SSH_NAMES_TTL:
        return _ssh_names_cache
    names: set[str] = set()
    candidates: list[Path] = []
    try:
        from services.config import DATA_DIR
        candidates.append(Path(DATA_DIR) / "ssh_servers.json")
    except Exception:
        pass
    candidates.append(Path("/app/data/ssh_servers.json"))  # hub default (all-in-one)
    for p in candidates:
        try:
            if not p.exists():
                continue
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for e in data:
                    n = str((e or {}).get("name", "")).strip().lower()
                    if n:
                        names.add(n)
            if names:
                break
        except Exception:
            continue
    _ssh_names_cache = names
    _ssh_names_ts = now
    return names


def _ssh_server_entries() -> list[dict[str, Any]]:
    """Full registry entries (name/host/username) — no passwords. For the hint."""
    candidates: list[Path] = []
    try:
        from services.config import DATA_DIR
        candidates.append(Path(DATA_DIR) / "ssh_servers.json")
    except Exception:
        pass
    candidates.append(Path("/app/data/ssh_servers.json"))
    for p in candidates:
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list) and data:
                    return data
        except Exception:
            continue
    return []


def server_admin_system_hint() -> str:
    """Context telling the model that the named servers are SSH-reachable and it
    must use ssh_run/fs_* to answer instead of asking the user. Empty if no
    servers are declared (nothing useful to say)."""
    entries = _ssh_server_entries()
    if not entries:
        return ""
    lines = []
    for e in entries:
        name = str((e or {}).get("name", "")).strip()
        host = str((e or {}).get("host", "")).strip()
        user = str((e or {}).get("username", "")).strip()
        if name:
            lines.append(f"- {name} ({user}@{host})")
    if not lines:
        return ""
    return (
        "[SERVER ĐÃ KHAI BÁO — truy cập được qua SSH]\n"
        "Các tên dưới đây là MÁY CHỦ bạn ĐƯỢC PHÉP điều khiển qua SSH, KHÔNG phải "
        "thiết bị nhà hay đầu ghi camera cần hỏi người dùng:\n"
        + "\n".join(lines) + "\n"
        "Khi người dùng hỏi về một trong các máy này (ổ đĩa, log, dịch vụ, file...), "
        "BẮT BUỘC dùng tool `ssh_run` (vd command \"df -h\", \"uptime\", \"docker ps\") "
        "hoặc các tool `fs_*` để LẤY DỮ LIỆU THẬT rồi trả lời. "
        "TUYỆT ĐỐI KHÔNG yêu cầu người dùng gửi ảnh chụp hay khai báo hãng/model — "
        "bạn tự chạy lệnh được.\n"
        "Nếu người dùng hỏi về một CONTAINER / DỊCH VỤ (vd \"frigate\", \"compreface\", "
        "\"double-take\") mà KHÔNG nói rõ máy nào: ĐỪNG hỏi lại và ĐỪNG chạy docker ps "
        "từng máy. Gọi MỘT lần `ssh_locate(\"<tên>\")` — nó quét song song mọi server và "
        "trả về container đó nằm ở máy nào. Sau đó chạy `ssh_run(server, \"docker ...\")` "
        "(vd \"docker stats --no-stream <ten>\", \"docker logs --tail 50 <ten>\", "
        "\"docker inspect <ten>\") hoặc fs_* trên ĐÚNG máy vừa tìm được."
    )


def _text_is_server_admin(text: str) -> bool:
    """Single-string check: names a declared server (≥3-char whole token) or hits
    a sysadmin keyword. Short names like "ha" don't false-trigger on VN words."""
    if not text:
        return False
    try:
        from services.ha_client import _fold_diacritics
        folded = _fold_diacritics(text)
    except Exception:
        folded = text.lower()
    folded = folded.replace("đ", "d")
    toks = set(re.sub(r"[^\w]", " ", folded).split())
    for name in _ssh_server_names():
        nf = name.replace("đ", "d")
        if len(nf) >= 3 and nf in toks:
            return True
    return any(k in folded for k in _SERVER_ADMIN_KEYWORDS)


def _msg_text(m: dict) -> str:
    c = m.get("content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(str(p.get("text", "")) for p in c if isinstance(p, dict))
    return ""


# ── Device intent (device_fs) ────────────────────────────────────────────────
# MCP `device_fs` điều khiển MÁY của người dùng (Windows/Android/VPS đã cài
# c2a-agent). Nó cùng loại với ssh_exec/fs_remote: không map được bằng từ khoá
# chủ đề như thời tiết/vàng, mà nhận ra qua (a) TÊN THIẾT BỊ đã khai, hoặc
# (b) từ ngữ nói về máy của mình.
#
# Vì sao phải có khối này (đo thật 2026-07-29, 8 câu điều khiển thiết bị):
#   · `get_relevant_mcp_tools` trả 0/8 câu có tool device_* — tên tool là
#     `device_*`, không khớp `sub` nào trong `_MCP_INTENT_MAP`, nên rơi hết về
#     bộ catch-all (search_web/web_search_exa);
#   · nhánh server-admin chỉ trả tool bắt đầu `ssh_`/`fs_` → lọc luôn device_*,
#     nên câu "ổ D còn bao nhiêu dung lượng" (khớp keyword "dung luong") lại
#     càng chắc chắn mất tool thiết bị.
# Hệ quả: bot trả lời "tôi không truy cập được máy của bạn" dù agent đang nối.

_device_names_cache: set[str] = set()
_device_names_ts = 0.0
_DEVICE_NAMES_TTL = 30.0

# Từ dài → so bằng chuỗi con. Từ NGẮN (pc, may) dễ khớp bừa trong tiếng Việt
# nên để ở `_DEVICE_TOKENS` và so theo TOKEN nguyên.
_DEVICE_KEYWORDS = (
    "may tinh", "may cua toi", "may minh", "thiet bi cua toi", "tren may",
    "chup man hinh", "man hinh may", "screenshot",
    "tien trinh", "tat may", "khoa may", "ngu may", "khoi dong lai may",
    "dang xuat", "shutdown", "o dia c", "o dia d", "o dia e",
    "dien thoai cua toi", "may android",
    # "kiểm tra tài nguyên <tên máy>" là câu người dùng hỏi thật và bản cũ trả
    # False → rơi sang nhánh Home Assistant, bot đi tìm cảm biến tên "case KT"
    # rồi kết luận "không thấy thiết bị nào", còn đòi IP + SSH + mật khẩu trong
    # khi agent đang nối sẵn. Ba cụm dưới đây là cách gọi tài nguyên máy, không
    # phải cách gọi thiết bị nhà thông minh, nên không lấn sân HA.
    "tai nguyen", "danh sach thiet bi", "thiet bi nao",
    # "Mở khóa màn hình" (log chat 30/07, thread zalop) trả False → không tool
    # thiết bị nào được nạp, model kết luận chức năng bị tắt và trả "[BLOCKED]",
    # còn orchestrator thấy [BLOCKED] thì IM LẶNG TUYỆT ĐỐI. Người dùng gửi tin
    # và không nhận được gì — không phải câu từ chối, mà là không có phản hồi.
    #
    # KHÔNG thêm "mo khoa" trơn: "mở khoá cửa" là lệnh Home Assistant thật
    # (domain lock). Chỉ nhận cụm có nói rõ MÀN HÌNH / MÁY.
    "mo khoa man hinh", "mo khoa may", "khoa man hinh", "unlock man hinh",
    "mo khoa windows",
)
_DEVICE_TOKENS = ("laptop", "pc", "desktop", "c2a-agent", "cpu", "ram")


def _device_names() -> set[str]:
    """Tên thiết bị đã khai trong config (cache ~30s) — GỒM CẢ NHÃN.

    Đọc từ `config.data["device_agents"]` — cùng nguồn mà `/api/devices` dùng,
    nên khai thêm thiết bị là hỏi được ngay, không cần sửa từ khoá.

    PHẢI lấy cả `label`, không chỉ khoá: người dùng gọi máy bằng cái tên họ thấy
    trên giao diện. Đo thật (log chat 2026-07-29 10:09): thiết bị khoá là
    `case-win`, nhãn là "Case KT"; câu "kiểm tra tài nguyên case KT" cho ra
    False vì bản cũ chỉ so với khoá — bot bèn đi tìm cảm biến Home Assistant
    tên "case KT", không thấy, rồi xin IP và mật khẩu SSH trong khi agent đang
    nối sẵn. Không ai đọc log để biết mình phải gọi bằng khoá `case-win`.
    """
    global _device_names_cache, _device_names_ts
    now = time.time()
    if _device_names_ts > 0 and (now - _device_names_ts) < _DEVICE_NAMES_TTL:
        return _device_names_cache
    names: set[str] = set()
    try:
        from services.config import config
        for key, info in (config.data.get("device_agents") or {}).items():
            for raw in (key, (info or {}).get("label") if isinstance(info, dict) else ""):
                s = str(raw or "").strip().lower()
                if s:
                    names.add(s)
    except Exception:
        pass
    _device_names_cache = names
    _device_names_ts = now
    return names


def _text_is_device(text: str) -> bool:
    """Một chuỗi có nói tới thiết bị của người dùng không.

    Tên thiết bị so theo TOKEN và đòi ≥3 ký tự — tên ngắn (vd "pi") không được
    phép khớp bừa vào từ tiếng Việt. Tên có dấu gạch (case-win) cũng tách ra
    thành token nên vẫn bắt được.
    """
    if not text:
        return False
    try:
        from services.ha_client import _fold_diacritics
        folded = _fold_diacritics(text)
    except Exception:
        folded = text.lower()
    folded = folded.replace("đ", "d")
    toks = set(re.sub(r"[^\w-]", " ", folded).split())
    for name in _device_names():
        try:
            from services.ha_client import _fold_diacritics as _fd
            nf = _fd(name)
        except Exception:
            nf = name.lower()
        nf = nf.replace("đ", "d").strip()
        if len(nf) < 3:
            continue          # tên quá ngắn (vd "pi") dễ khớp bừa vào từ tiếng Việt
        # Nhãn NHIỀU TỪ ("case kt") không bao giờ là một token, phải so chuỗi con.
        # Bản cũ chỉ so token nên nhãn có dấu cách không bắt được câu nào —
        # chính là ca "kiểm tra tài nguyên case KT" trả về False.
        if " " in nf:
            if nf in folded:
                return True
            continue
        if nf in toks:
            return True
        # Tên một từ có dấu gạch (case-win) — chú thích cũ bảo là "tách ra thành
        # token nên vẫn bắt được", nhưng chỉ VĂN BẢN được tách, còn tên thì không.
        # Cho khớp khi mọi phần ≥3 ký tự của tên đều xuất hiện trong câu.
        phan = [p for p in re.split(r"[-_]+", nf) if len(p) >= 3]
        if phan and all(p in toks for p in phan):
            return True
    if any(t in toks for t in _DEVICE_TOKENS):
        return True
    return any(k in folded for k in _DEVICE_KEYWORDS)


def is_device_query(text: str, messages: list | None = None) -> bool:
    """True khi câu nhắm vào MÁY của người dùng qua c2a-agent.

    Giữ chế độ ở lượt sau giống `is_server_admin_query`: đã gọi tool `device_*`
    trong hội thoại thì câu tiếp ("có file nào nữa không") vẫn còn tool, chứ
    không rơi về catch-all rồi bot bảo không truy cập được.
    """
    if _text_is_device(text):
        return True
    if not messages:
        return False
    for m in messages:
        if not isinstance(m, dict):
            continue
        for tc in (m.get("tool_calls") or []):
            if ((tc.get("function") or {}).get("name") or "").startswith("device_"):
                return True
        if m.get("role") == "tool" and str(m.get("name") or "").startswith("device_"):
            return True
    for m in messages[-8:]:
        if isinstance(m, dict) and m.get("role") == "user" and _text_is_device(_msg_text(m)):
            return True
    return False


def device_system_hint() -> str:
    """Nói cho model biết các thiết bị này ĐIỀU KHIỂN ĐƯỢC, đừng hỏi lại.

    Không có câu này thì model thấy "máy tính của tôi" và trả lời theo bản năng
    — "bạn hãy tự mở File Explorer…" — dù đang có tool trong tay. Rỗng nếu chưa
    khai thiết bị nào (không có gì đáng nói).
    """
    names = sorted(_device_names())
    if not names:
        return ""
    return (
        "[THIẾT BỊ ĐÃ KHAI — điều khiển được qua c2a-agent]\n"
        "Các tên sau là MÁY của người dùng, bạn ĐƯỢC PHÉP đọc/ghi file và xem "
        "thông tin máy qua tool `device_*`: " + ", ".join(names) + "\n"
        "Khi người dùng nói \"máy tính\", \"laptop\", \"máy của tôi\" mà không nêu tên: "
        "gọi `device_list()` để biết máy nào đang kết nối rồi dùng tên đó.\n"
        "BẮT BUỘC dùng tool để LẤY DỮ LIỆU THẬT (`device_ls`, `device_read`, "
        "`device_sysinfo`, `device_resources`, `device_processes`, `device_screen`…) "
        "rồi trả lời. TUYỆT ĐỐI KHÔNG bảo người dùng tự mở File Explorer, tự chụp "
        "màn hình, hay nói rằng bạn không truy cập được máy của họ.\n"
        "Quyền ghi/chạy lệnh/tắt máy do người dùng cấp riêng từng máy và được "
        "kiểm ở phía server: nếu tool trả về thông báo thiếu quyền thì nói lại "
        "đúng thông báo đó, đừng thử đường khác.\n"
        "ĐÂY LÀ THÔNG TIN NỀN, KHÔNG PHẢI VIỆC CẦN LÀM: tuyệt đối không gọi "
        "`remember`/ghi nhớ để lưu lại đoạn này — nó đã có sẵn ở mỗi lượt. "
        "Người dùng hỏi \"danh sách thiết bị của tôi\" là muốn XEM MÁY ĐANG NỐI: "
        "gọi `device_list()` rồi đọc kết quả ra, không phải ghi nhớ điều gì."
    )


def is_server_admin_query(text: str, messages: list | None = None) -> bool:
    """True when the query targets a declared SSH server or is a sysadmin op.

    With conversation `messages`, a follow-up STAYS in server-admin mode when an
    earlier turn named a server or already used an ssh_/fs_ tool — so
    "trong config có file nào" after "ổ đĩa nvr còn bao nhiêu" keeps the tools
    instead of the model claiming it has no SSH access.
    """
    if _text_is_server_admin(text):
        return True
    if not messages:
        return False
    # Already ran a server tool earlier in this conversation → stay in mode.
    for m in messages:
        if not isinstance(m, dict):
            continue
        for tc in (m.get("tool_calls") or []):
            nm = ((tc.get("function") or {}).get("name") or "")
            if nm.startswith(("ssh_", "fs_")):
                return True
        if m.get("role") == "tool" and str(m.get("name") or "").startswith(("ssh_", "fs_")):
            return True
    # A declared server named in any recent user turn.
    for m in messages[-8:]:
        if isinstance(m, dict) and m.get("role") == "user" and _text_is_server_admin(_msg_text(m)):
            return True
    return False


def get_relevant_mcp_tools(query: str, _relevant_messages: list | None = None) -> list[dict[str, Any]]:
    """Return only the MCP tools relevant to `query` (+ the generic search/
    encyclopedia catch-all), instead of all ~43 schemas. Specialized servers are
    pulled in only when the query keywords match → much smaller payload, faster
    first token. If nothing matches, just the catch-all (web/wiki) is returned —
    the model can still search for anything.
    """
    all_tools = get_enabled_mcp_tools()
    if not all_tools:
        return all_tools

    # Thiết bị của người dùng (c2a-agent) → chỉ tool device_*, không web search.
    # PHẢI xét TRƯỚC server-admin: "ổ đĩa", "dung luong", "cpu load", "ram con"
    # đều là `_SERVER_ADMIN_KEYWORDS`, nên "ổ D trên máy tính còn bao nhiêu" mà
    # xét sau thì rơi vào nhánh ssh_/fs_ và mất sạch tool thiết bị.
    _dev = is_device_query(query, _relevant_messages)
    if _dev:
        sel = [t for t in all_tools
               if (t.get("function", {}) or {}).get("name", "").startswith("device_")]
        # Câu vừa nêu tên thiết bị vừa nêu tên server (vd "copy từ nvr sang máy
        # tính") → đưa cả hai họ tool, để model tự chọn thay vì thiếu một bên.
        if is_server_admin_query(query, _relevant_messages):
            sel += [t for t in all_tools
                    if (t.get("function", {}) or {}).get("name", "").startswith(("ssh_", "fs_"))]
        if sel:
            logger.info({"event": "mcp_device_tools", "count": len(sel)})
            return sel
        # Không có tool device_* nào = MCP "Thiết bị của tôi" chưa bật. Nói rõ ở
        # log, vì biểu hiện bên ngoài y như model không chịu gọi tool.
        logger.warning({"event": "mcp_device_intent_no_tools",
                        "hint": "bật MCP device_fs ở tab MCP → Thiết bị của tôi"})

    # Server-admin query → ship only the ssh_/fs_ tools (no web search).
    if is_server_admin_query(query, _relevant_messages):
        sel = [t for t in all_tools
               if (t.get("function", {}) or {}).get("name", "").startswith(("ssh_", "fs_"))]
        if sel:
            logger.info({"event": "mcp_server_admin_tools", "count": len(sel)})
            return sel

    try:
        from services.ha_client import _fold_diacritics
        qf = _fold_diacritics(query or "")
    except Exception:
        qf = (query or "").lower()

    wanted: set[str] = set()
    realtime = False
    for kws, subs, replaces_search in _MCP_INTENT_MAP:
        if any(k in qf for k in kws):
            wanted.update(subs)
            if replaces_search:
                realtime = True

    def _generic() -> list[dict[str, Any]]:
        return [t for t in all_tools
                if (t.get("function", {}) or {}).get("name", "") in _MCP_GENERIC_NAMES]

    # Realtime/authoritative intent (giá vàng/thời tiết/cổ phiếu…) → ship ONLY
    # that tool, NOT the generic web-search set. Otherwise the model calls the
    # dedicated tool AND then loops web_search to "verify" — each extra agentic
    # round is a slow codex round-trip. One tool → one call → answer.
    if realtime:
        sel = [t for t in all_tools
               if any(sub in (t.get("function", {}) or {}).get("name", "").lower() for sub in wanted)]
        return sel or _generic()

    # Knowledge store (y tế/giáo dục…) or no match → dedicated (if any) + generic
    # catch-all, so web search stays available to complement the RAG answer.
    selected: list[dict[str, Any]] = []
    for t in all_tools:
        nl = (t.get("function", {}) or {}).get("name", "").lower()
        if (t.get("function", {}) or {}).get("name", "") in _MCP_GENERIC_NAMES or (wanted and any(sub in nl for sub in wanted)):
            selected.append(t)
    return selected or _generic()


def query_has_specialized_mcp(query: str) -> bool:
    """True if the query matches a dedicated MCP server (weather/gold/stock/
    news/law/lunar…). Caller skips the slow web-search injection and lets the
    model call that tool directly — realtime + accurate. The model still keeps
    web_search_exa/search_web as fallback tools if the dedicated one falls short.
    """
    try:
        from services.ha_client import _fold_diacritics
        qf = _fold_diacritics(query or "")
    except Exception:
        qf = (query or "").lower()
    return any(any(k in qf for k in kws)
               for kws, _, replaces_search in _MCP_INTENT_MAP if replaces_search)


def call_mcp_tool(tool_name: str, arguments: dict[str, Any], server_id: str = "") -> str | None:
    """Find which MCP session owns this tool and call it.

    Args:
        tool_name: Ten MCP tool can goi (vi du: 'search_web', 'get_news')
        arguments: Tham so truyen vao tool
        server_id: (Optional) ID cua MCP server cu the trong config (vi du: 'vn_search').
                   Neu cung cap, se goi thang server nay thay vi tim kiem toan bo.
    """
    installed = _configured_servers()
    if not installed:
        return None

    def _try_call(info: dict) -> str | None:
        if not info.get("enabled", True):
            return None
        url, api_key, headers, transport = _connection_options(info)
        if not url:
            return None
        key = _session_key(url, api_key, headers, transport)
        with _sessions_lock:
            if key not in _sessions:
                _sessions[key] = MCPSession(
                    url, api_key, headers=headers, transport=transport,
                )
            session = _sessions[key]
        if not session.ensure_connected():
            return None
        # Neu co server_id cu the: goi tool khong can kiem tra ten tool trong tool list
        # (vi IntentRouter da biet chinh xac tool nao dung cho server nay)
        if server_id:
            return session.call_tool(tool_name, arguments)
        # Khong co server_id: tim tool theo ten nhu cu
        for t in session.tools:
            if t.get("name") == tool_name:
                result = session.call_tool(tool_name, arguments)
                if result is not None:
                    return result
        return None

    # Neu co server_id: chi goi server do
    if server_id:
        for info in installed:
            # Match theo id field hoac theo url chua server_id
            info_id = str(info.get("id") or info.get("name", "")).lower()
            if info_id == server_id.lower() or server_id.lower() in info.get("url", "").lower():
                result = _try_call(info)
                if result is not None:
                    return result
        return None

    # The merged OpenAI namespace may contain aliases for duplicate/invalid MCP
    # names. Resolve those aliases directly to the owning session and native
    # name. Populate the routing table lazily for callers that skipped tool
    # discovery before executing a function call.
    if tool_name not in _tool_routes:
        get_enabled_mcp_tools()
    route = _tool_routes.get(tool_name)
    if route:
        key, native_name = route
        with _sessions_lock:
            session = _sessions.get(key)
        if session and session.ensure_connected():
            return session.call_tool(native_name, arguments)

    # Compatibility fallback for old caches/callers using the native name.
    for info in installed:
        result = _try_call(info)
        if result is not None:
            return result
    return None


# Realtime intents whose tool takes NO required args → the gateway can call it
# server-side BEFORE the model, inject the result as context, and let the model
# answer in ONE round-trip (vs decide-tool then read-tool = two codex calls).
# Folded keywords → tool names to call with {} (current data). First match wins.
_PREFETCH_MAP: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("gia vang", "vang sjc", "vang doji", "vang mieng", "vang nhan", "gia vang hom nay"),
     ("get_gold_prices",)),
    (("ty gia", "ngoai te", "ngoai hoi", "ty gia usd", "ty gia vcb", "do la", "dola", "euro", "yen nhat"),
     ("get_vcb_rates",)),
    (("gia xang", "gia dau", "xang dau", "gia nhien lieu", "gia xang dau"),
     ("get_petrol_prices",)),
    # NB: âm lịch xử lý local bằng services/lunar_vn.py (canonicalizer), KHÔNG prefetch MCP.
)


def prefetch_realtime_context(query: str) -> str | None:
    """If `query` matches a no-arg realtime intent, call the tool(s) NOW and
    return the combined result text (or None). Caller injects it as context so
    the model answers in one round-trip instead of two."""
    try:
        from services.ha_client import _fold_diacritics
        qf = _fold_diacritics(query or "")
    except Exception:
        qf = (query or "").lower()
    names: tuple[str, ...] = ()
    for kws, tools in _PREFETCH_MAP:
        if any(k in qf for k in kws):
            names = tools
            break
    if not names:
        return None
    parts: list[str] = []
    for tn in names:
        try:
            res = call_mcp_tool(tn, {})
        except Exception as exc:
            logger.warning({"event": "prefetch_tool_error", "tool": tn, "error": str(exc)[:120]})
            res = None
        if res and str(res).strip() and not la_loi_mcp(res):
            parts.append(str(res).strip()[:8000])  # head-cap; gold can be ~118KB
    if not parts:
        return None
    logger.info({"event": "prefetch_ok", "tools": list(names), "chars": sum(len(p) for p in parts)})
    return "\n\n".join(parts)[:12000]


# Kho tri thức (RAG) có tool ask_<kho>(question). Khi câu hỏi khớp chủ đề kho,
# gateway gọi THẲNG tool đó server-side rồi nhét kết quả vào ngữ cảnh → model chỉ
# format 1 lượt (nhanh, không cần reasoning) + kho TỰ HỌC (kb_ask write-back chạy).
_KB_ASK_TOPICS = {"dien_nuoc", "y_te", "giao_duc", "ngoai_ngu", "khoa_hoc", "tu_nhien", "xa_hoi"}


def prefetch_kb_context(query: str) -> str | None:
    """Nếu câu hỏi khớp một kho tri thức (điện nước/y tế/giáo dục…), gọi
    ask_<kho>(question) server-side và trả về văn bản kết quả (hoặc None).

    Tái dùng _MCP_INTENT_MAP (keyword đã tinh chỉnh) — entry nào có substring là
    tên kho thì prefetch kho đó. First match wins.
    """
    try:
        from services.ha_client import _fold_diacritics
        qf = _fold_diacritics(query or "")
    except Exception:
        qf = (query or "").lower()

    topic: str | None = None
    for kws, subs, _replaces in _MCP_INTENT_MAP:
        kb = next((s for s in subs if s in _KB_ASK_TOPICS), None)
        if kb and any(k in qf for k in kws):
            topic = kb
            break
    if not topic:
        return None

    try:
        res = call_mcp_tool(f"ask_{topic}", {"question": query})
    except Exception as exc:
        logger.warning({"event": "kb_prefetch_error", "topic": topic, "error": str(exc)[:120]})
        return None
    if res and str(res).strip() and not la_loi_mcp(res):
        logger.info({"event": "kb_prefetch_ok", "topic": topic, "chars": len(str(res))})
        return str(res).strip()[:8000]
    return None
