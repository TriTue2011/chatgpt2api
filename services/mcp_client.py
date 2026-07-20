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

import json, logging, re, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
import urllib.request
import urllib.error

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


class MCPSession:
    """One connected MCP server session. Auto-reconnects on expiry."""

    def __init__(self, url: str, api_key: str = "") -> None:
        self.url = url
        self.api_key = api_key
        self.session_id: str | None = None
        self.server_name: str = ""
        self.tools: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._last_init = 0.0
        # Circuit breaker state
        self._last_failure = 0.0
        self._failure_count = 0

    def _call(self, method: str, params: dict | None = None, timeout: float | None = None) -> dict | None:
        body = {"jsonrpc": "2.0", "id": "1", "method": method}
        if params:
            body["params"] = params
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=timeout if timeout is not None else _INIT_TIMEOUT)
            sid = resp.getheader("mcp-session-id")
            if sid:
                self.session_id = sid
            # Read response - FastMCP can return plain JSON or SSE
            raw = resp.read().decode('utf-8', errors='ignore')
            # Try SSE format first
            for line in raw.split("\n"):
                line = line.strip()
                if line.startswith("data: "):
                    try:
                        d = json.loads(line[6:])
                        if d.get("id") != "server-error":
                            return d
                    except json.JSONDecodeError:
                        pass
            # Try plain JSON format (FastMCP Streamable HTTP)
            try:
                d = json.loads(raw)
                if isinstance(d, dict) and d.get("id") != "server-error":
                    return d
            except json.JSONDecodeError:
                pass
        except urllib.error.HTTPError as e:
            sid = e.getheader("mcp-session-id")
            if sid:
                self.session_id = sid
            raw = e.read().decode()
            # Try SSE format
            for line in raw.split("\n"):
                line = line.strip()
                if line.startswith("data: "):
                    try:
                        return json.loads(line[6:])
                    except json.JSONDecodeError:
                        pass
            # Try plain JSON format
            try:
                d = json.loads(raw)
                if isinstance(d, dict):
                    return d
            except json.JSONDecodeError:
                pass
        except Exception as exc:
            logger.warning({"event": "mcp_call_failed", "url": self.url, "error": str(exc)})
        return None

    def _current_cooldown(self) -> float:
        """Cooldown grows after repeated failures so a permanently dead MCP
        only costs us a probe every 30 min instead of every minute.

        Exception: an in-container hub MCP (127.0.0.1/localhost) that refuses
        the connection is almost always just still starting up, not dead — the
        gateway and hub boot together and the hub takes ~40s to mount all MCPs.
        Keep its cooldown short so tools self-heal within a minute of boot
        instead of being circuit-broken for 30 min."""
        u = self.url or ""
        if "127.0.0.1" in u or "localhost" in u or "://[::1]" in u:
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
        if self.session_id and (now - self._last_init) < 300:
            return True

        # Circuit breaker: don't retry a dead MCP within current cooldown
        if self._last_failure and (now - self._last_failure) < self._current_cooldown():
            return False

        with self._lock:
            now = time.time()
            if self.session_id and (now - self._last_init) < 300:
                return True
            if self._last_failure and (now - self._last_failure) < self._current_cooldown():
                return False

            init = self._call("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "chatgpt2api", "version": "1.0"},
            }, timeout=_INIT_TIMEOUT)
            if not init:
                self.session_id = None
                self._last_failure = now
                self._failure_count += 1
                return False

            # Send initialized notification (fire-and-forget, short timeout)
            try:
                self._call("notifications/initialized", timeout=_NOTIFY_TIMEOUT)
            except Exception:
                pass

            self.server_name = init.get("result", {}).get("serverInfo", {}).get("name", "")
            # Fetch tools
            tools_resp = self._call("tools/list", timeout=_INIT_TIMEOUT)
            if tools_resp:
                self.tools = tools_resp.get("result", {}).get("tools", [])
            self._last_init = now
            self._last_failure = 0.0
            self._failure_count = 0
            return True

    def get_tools(self) -> list[dict[str, Any]]:
        """Return OpenAI-format tools list for injection into chat completions."""
        if not self.ensure_connected():
            return []
        openai_tools: list[dict[str, Any]] = []
        for t in self.tools:
            name = t.get("name", "")
            desc = t.get("description", "")
            schema = t.get("inputSchema", {"type": "object", "properties": {}})
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
        """Call an MCP tool and return the text result."""
        if not self.ensure_connected():
            return None
        result = self._call("tools/call", {"name": name, "arguments": arguments}, timeout=_TOOL_CALL_TIMEOUT)
        if not (result and result.get("result")):
            # Session co the da CHET (vd MCP server vua restart nhung gateway con
            # trong 5-min TTL nen tuong con song) -> vo hieu, ket noi lai, thu LAI
            # 1 lan. Khong co buoc nay thi moi lan redeploy MCP la chat roi xuong
            # model (codex) cham + dai dong.
            self.session_id = None
            self._last_init = 0.0
            self._last_failure = 0.0
            if self.ensure_connected():
                result = self._call("tools/call", {"name": name, "arguments": arguments}, timeout=_TOOL_CALL_TIMEOUT)
        if not (result and result.get("result")):
            return None
        content = result.get("result", {}).get("content", [])
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(texts) if texts else json.dumps(content, ensure_ascii=False)


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
_tools_cache: list[dict[str, Any]] | None = None
_tools_cache_ts: float = 0.0
_tools_cache_signature: str = ""
_tools_cache_lock = threading.Lock()

# Concurrency for parallel MCP probing
_PROBE_WORKERS = 16


def _session_key(url: str, api_key: str) -> str:
    return f"{url}::{api_key[:8] if api_key else 'noauth'}"


def _enabled_signature(installed: list[dict]) -> str:
    """A short string that changes whenever the enabled-MCP set changes,
    so we invalidate the cache on config edits."""
    parts = []
    for info in installed:
        if not info.get("enabled", True):
            continue
        url = info.get("url", "") or ""
        if not url:
            continue
        api_key = str(info.get("api_key") or "")
        parts.append(f"{url}|{bool(api_key)}")
    return ";".join(sorted(parts))


def _collect_tools_one(info: dict) -> tuple[str, list[dict[str, Any]]]:
    """Worker: probe one MCP and return (name, tools)."""
    url = info.get("url", "")
    api_key = str(info.get("api_key") or "")
    if not url:
        return info.get("name", "unknown"), []
    key = _session_key(url, api_key)
    with _sessions_lock:
        if key not in _sessions:
            _sessions[key] = MCPSession(url, api_key)
        session = _sessions[key]
    try:
        return info.get("name", "unknown"), session.get_tools()
    except Exception as exc:
        logger.warning({"event": "mcp_session_failed", "name": info.get("name", "unknown"), "error": str(exc)})
        return info.get("name", "unknown"), []


def get_enabled_mcp_tools() -> list[dict[str, Any]]:
    """Collect OpenAI-format tools from all enabled MCP servers in config.

    Cached for _TOOLS_CACHE_TTL seconds and discovered in parallel across
    servers. A single dead MCP (circuit-broken) costs ~0ms; a healthy MCP
    only pays the one-time cold-start cost.
    """
    global _tools_cache, _tools_cache_ts, _tools_cache_signature

    installed = config.data.get("mcp_servers") or []
    if isinstance(installed, dict):
        installed = list(installed.values())
    if not isinstance(installed, list) or not installed:
        return []

    enabled = [i for i in installed if i.get("enabled", True) and i.get("url")]
    signature = _enabled_signature(enabled)
    now = time.time()

    # Fast path: cache hit
    if (
        _tools_cache is not None
        and signature == _tools_cache_signature
        and (now - _tools_cache_ts) < _TOOLS_CACHE_TTL
    ):
        return list(_tools_cache)

    with _tools_cache_lock:
        now = time.time()
        if (
            _tools_cache is not None
            and signature == _tools_cache_signature
            and (now - _tools_cache_ts) < _TOOLS_CACHE_TTL
        ):
            return list(_tools_cache)

        logger.info({
            "event": "mcp_debug_v2",
            "total": len(installed),
            "enabled_count": len(enabled),
            "urls": [i.get("url", "")[:60] for i in enabled[:3]],
        })

        # Probe all enabled MCPs in parallel.
        seen_names: set[str] = set()
        all_tools: list[dict[str, Any]] = []
        workers = min(_PROBE_WORKERS, max(1, len(enabled)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_collect_tools_one, info): info for info in enabled}
            for fut in as_completed(futures):
                info = futures[fut]
                try:
                    name, tools = fut.result()
                except Exception as exc:
                    logger.warning({"event": "mcp_session_failed", "name": info.get("name", "unknown"), "error": str(exc)})
                    continue
                for t in tools:
                    fname = t.get("function", {}).get("name", "")
                    if fname and fname not in seen_names:
                        seen_names.add(fname)
                        all_tools.append(t)
                logger.info({"event": "mcp_tools_loaded", "name": name, "count": len(tools)})

        _tools_cache = all_tools
        _tools_cache_ts = now
        _tools_cache_signature = signature
        return list(all_tools)


def invalidate_tools_cache() -> None:
    """Force `get_enabled_mcp_tools()` to re-probe on its next call.

    Call this after editing the MCP server list (install / uninstall / toggle).
    """
    global _tools_cache, _tools_cache_ts, _tools_cache_signature
    with _tools_cache_lock:
        _tools_cache = None
        _tools_cache_ts = 0.0
        _tools_cache_signature = ""


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
    installed = config.data.get("mcp_servers") or []
    if isinstance(installed, dict):
        installed = list(installed.values())
    if not isinstance(installed, list):
        return None

    def _try_call(info: dict) -> str | None:
        if not info.get("enabled", True):
            return None
        url = info.get("url", "")
        api_key = str(info.get("api_key") or "")
        if not url:
            return None
        key = _session_key(url, api_key)
        with _sessions_lock:
            if key not in _sessions:
                _sessions[key] = MCPSession(url, api_key)
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

    # Khong co server_id: duyet tat ca nhu cu
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
        if res and str(res).strip():
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
    if res and str(res).strip():
        logger.info({"event": "kb_prefetch_ok", "topic": topic, "chars": len(str(res))})
        return str(res).strip()[:8000]
    return None
