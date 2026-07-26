"""Net guard — chặn SSRF + egress allowlist cho MỌI fetch URL không tin cậy.

Bối cảnh (OWASP A01:2025 — SSRF): gateway hay phải fetch URL đến từ nguồn ngoài
(attachment_url trong webhook Zalo, image_url do client/model trả về…). Kẻ tấn
công có thể nhét ``http://192.168.x.x`` / ``http://169.254.169.254`` để mượn tay
gateway gọi vào mạng nội bộ (HA, router, metadata). Quy tắc:

  - URL từ nguồn KHÔNG tin cậy → bắt buộc qua ``check_url``/``safe_fetch``:
    chỉ http/https, cấm IP private/loopback/link-local (kể cả sau khi resolve
    DNS), tuỳ chọn allowlist host. Redirect được follow thủ công và **mỗi hop
    đều check lại** (chặn redirect → private IP).
  - Gọi nội bộ CHỦ ĐÍCH (self-call 127.0.0.1 gateway, HA đã cấu hình) thì
    KHÔNG đi qua guard này — đó là đường tin cậy do admin đặt.

Config (tuỳ chọn, top-level ``security``)::

    {"egress_allow_hosts": ["extra-cdn.example.com"]}
"""
from __future__ import annotations

import http.client
import ipaddress
import logging
import socket
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

# Host được coi là tin cậy sẵn cho từng kênh (nền tảng chính chủ).
TELEGRAM_HOSTS = {"api.telegram.org"}
ZALO_HOSTS = {"openapi.zalo.me", "api.zalo.me"}

_DEFAULT_MAX_BYTES = 50 * 1024 * 1024
_DEFAULT_MAX_REDIRECTS = 3


class BlockedURL(ValueError):
    """URL bị chặn bởi net guard (SSRF/egress)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Không follow redirect tự động — caller re-check từng Location."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


# ── DNS-rebinding TOCTOU (P0 SSRF) ───────────────────────────────────────────
# check_url() ở trên resolve DNS (getaddrinfo) một lần để validate IP, nhưng
# urlopen bên dưới tự resolve LẠI, độc lập, khi connect() thật sự chạy — nếu
# attacker set TTL thấp, bản ghi A có thể đổi giữa 2 lần resolve, trỏ sang
# 169.254.169.254/127.0.0.1/10.x SAU KHI đã "qua" check_url. Cách vá: không
# so khớp lại IP đã check ở bước 1 (dễ vỡ với dịch vụ multi-IP hợp lệ — IP có
# thể khác mà vẫn public, không phải lỗi) mà RE-VALIDATE chính IP vừa connect
# thật, ngay sau khi TCP/TLS xong và TRƯỚC KHI đọc bất kỳ byte response nào.
# Không đổi Host header/SNI (self.host giữ nguyên hostname gốc) nên tương
# thích mọi virtual-host/cert hiện có — đổi ít nhất so với phương án "pin
# thẳng vào IP + tự set SNI/Host".
def _assert_peer_ip_safe(sock: socket.socket) -> None:
    """An toàn trước: không lấy được peer IP (hiếm, socket lỗi) cũng chặn
    luôn thay vì bỏ qua — mất khả năng verify coi như đáng ngờ."""
    try:
        peer_ip = sock.getpeername()[0].split("%", 1)[0]
        ip_obj = ipaddress.ip_address(peer_ip)
    except (OSError, ValueError, IndexError, AttributeError) as exc:
        raise BlockedURL(f"Không xác định được peer IP sau khi kết nối: {exc}") from exc
    if not ip_obj.is_global:
        raise BlockedURL(f"DNS-rebinding phát hiện: peer thực tế {peer_ip} là private/nội bộ")


class _PeerCheckedHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection verify lại peer IP ngay sau khi TCP connect xong."""

    def connect(self) -> None:  # type: ignore[override]
        super().connect()
        _assert_peer_ip_safe(self.sock)


class _PeerCheckedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection verify lại peer IP ngay sau khi TLS handshake xong."""

    def connect(self) -> None:  # type: ignore[override]
        super().connect()
        _assert_peer_ip_safe(self.sock)


class _PeerCheckedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):  # type: ignore[no-untyped-def]
        return self.do_open(_PeerCheckedHTTPConnection, req)


class _PeerCheckedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):  # type: ignore[no-untyped-def]
        return self.do_open(_PeerCheckedHTTPSConnection, req, context=self._context)


def host_is_private(host: str) -> bool:
    """True nếu host là IP private/loopback/link-local/reserved — hoặc resolve
    DNS ra một IP như vậy. Lỗi resolve → coi là private (an toàn trước)."""
    host = (host or "").strip("[]").lower()
    if not host:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return not ip.is_global
    except ValueError:
        pass          # là hostname → resolve
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return True
        if not ip.is_global:
            return True
    return False


def _extra_allow() -> set[str]:
    try:
        from services.config import config
        sec = config.get().get("security")
        hosts = (sec or {}).get("egress_allow_hosts") if isinstance(sec, dict) else None
        return {str(h).strip().lower() for h in hosts if str(h).strip()} \
            if isinstance(hosts, list) else set()
    except Exception:
        return set()


def check_url(url: str, *, allow_hosts: set[str] | None = None) -> str:
    """Kiểm URL không tin cậy trước khi fetch. Trả lại url nếu hợp lệ.

    Ném BlockedURL nếu: scheme khác http/https, thiếu host, host nằm dải
    private (trực tiếp hoặc sau resolve), và — khi ``allow_hosts`` đặt —
    host không thuộc allowlist (cộng thêm ``security.egress_allow_hosts``)."""
    raw = str(url or "").strip()
    u = urlparse(raw)
    if u.scheme not in ("http", "https"):
        raise BlockedURL(f"Scheme không cho phép: {u.scheme or '(trống)'}")
    host = (u.hostname or "").lower()
    if not host:
        raise BlockedURL("URL thiếu host")
    if allow_hosts is not None:
        allowed = {h.lower() for h in allow_hosts} | _extra_allow()
        if host not in allowed and not any(host.endswith("." + h) for h in allowed):
            raise BlockedURL(f"Host ngoài allowlist: {host}")
    if host_is_private(host):
        raise BlockedURL(f"Host nội bộ/private bị chặn: {host}")
    return raw


def is_self_images_url(url: str) -> bool:
    """True nếu URL trỏ media nội bộ ``/images/`` (gateway tự phục vụ)."""
    raw = str(url or "").strip()
    if "/images/" not in raw:
        return False
    try:
        u = urlparse(raw)
    except Exception:
        return False
    host = (u.hostname or "").lower()
    # Relative path or localhost/self host only — external host + /images/ still untrusted.
    if not host or host in ("127.0.0.1", "localhost", "::1"):
        return True
    try:
        from services.config import config
        base = str(getattr(config, "base_url", None) or config.get().get("base_url") or "")
        if base:
            bh = (urlparse(base).hostname or "").lower()
            if bh and host == bh:
                return True
    except Exception:
        pass
    return False


def self_images_fetch(url: str, *, timeout: float = 30,
                      max_bytes: int = _DEFAULT_MAX_BYTES) -> bytes:
    """Fetch media ``/images/…`` qua loopback (tránh hairpin CF 403)."""
    path = str(url).split("/images/", 1)[1]
    local = f"http://127.0.0.1:80/images/{path}"
    with urllib.request.urlopen(local, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise BlockedURL(f"Nội dung vượt trần {max_bytes} byte")
    return data


def safe_fetch(url: str, *, allow_hosts: set[str] | None = None,
               timeout: float = 30, max_bytes: int = _DEFAULT_MAX_BYTES,
               max_redirects: int = _DEFAULT_MAX_REDIRECTS) -> bytes:
    """Fetch URL không tin cậy sau check_url. Mỗi redirect hop được check lại.

    Không dùng urllib follow-redirect mặc định (tránh SSRF qua Location → private).
    """
    current = check_url(url, allow_hosts=allow_hosts)
    # _PeerCheckedHTTP(S)Handler chặn DNS-rebinding TOCTOU giữa check_url()
    # (resolve #1) và connect() thật của urlopen (resolve #2) — xem docstring
    # _assert_peer_ip_safe().
    opener = urllib.request.build_opener(
        _NoRedirect(), _PeerCheckedHTTPHandler(), _PeerCheckedHTTPSHandler()
    )
    last_err: Exception | None = None
    for hop in range(max_redirects + 1):
        try:
            req = urllib.request.Request(
                current,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; chatgpt2api-net-guard/1.0)"
                    ),
                    "Accept": "*/*",
                },
            )
            with opener.open(req, timeout=timeout) as resp:
                final = str(resp.geturl() or current)
                if final != current:
                    check_url(final, allow_hosts=allow_hosts)
                data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise BlockedURL(f"Nội dung vượt trần {max_bytes} byte")
            return data
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (301, 302, 303, 307, 308) and hop < max_redirects:
                loc = e.headers.get("Location") if e.headers else None
                if not loc:
                    raise BlockedURL(f"Redirect {e.code} không có Location") from e
                nxt = urljoin(current, loc)
                current = check_url(nxt, allow_hosts=allow_hosts)
                logger.info("net_guard redirect hop=%s → %s", hop + 1, current[:160])
                continue
            # 4xx/5xx: surface as BlockedURL only for security-ish; else re-raise
            raise
        except BlockedURL:
            raise
        except Exception as e:
            last_err = e
            raise
    raise BlockedURL(
        f"Quá số lần redirect ({max_redirects})"
        + (f": {last_err}" if last_err else "")
    )


def fetch_media(url: str, *, timeout: float = 60,
                max_bytes: int = _DEFAULT_MAX_BYTES) -> bytes:
    """Fetch media từ client/LLM: self ``/images/`` → loopback; còn lại safe_fetch."""
    if is_self_images_url(url):
        try:
            return self_images_fetch(url, timeout=timeout, max_bytes=max_bytes)
        except Exception as exc:
            logger.warning("self_images_fetch fail, fallback safe_fetch: %s", exc)
            # fall through only if public URL might work — still guard
            if not str(url).startswith(("http://", "https://")):
                raise
    return safe_fetch(url, timeout=timeout, max_bytes=max_bytes)


# ── P0#5: LLM / agent output = untrusted ──────────────────────────────────
# Model/tool có thể nhét image_url/video_url trỏ LAN/metadata. Bot KHÔNG được
# fetch/forward URL đó (SSRF + data exfil qua Telegram/Zalo server-side fetch).

_MEDIA_URL_KEYS = (
    "image_url", "video_url", "audio_url", "photo_url",
    "thumbnail_url", "file_url", "media_url",
)
_MEDIA_PATH_KEYS = ("video_path", "audio_path", "image_path", "file_path")


def is_allowed_egress_url(url: str | None) -> bool:
    """True nếu bot được phép fetch/forward URL (public http(s), data:, self /images/)."""
    raw = str(url or "").strip()
    if not raw:
        return False
    if raw.startswith("data:"):
        # data URI — không phải SSRF network; caller tự giới hạn size
        return True
    if not raw.startswith(("http://", "https://")):
        return False
    if is_self_images_url(raw):
        return True
    try:
        check_url(raw)
        return True
    except BlockedURL:
        return False


def is_allowed_media_path(path: str | None) -> bool:
    """True nếu path local media nằm dưới data/tmp (chống path traversal từ model)."""
    raw = str(path or "").strip()
    if not raw or raw.startswith(("http://", "https://", "data:")):
        return False
    try:
        from pathlib import Path
        p = Path(raw).resolve()
        roots: list = []
        try:
            from services.config import DATA_DIR, config
            roots.append(Path(DATA_DIR).resolve())
            try:
                roots.append(Path(config.images_dir).resolve())
            except Exception:
                pass
        except Exception:
            pass
        roots.extend([Path("/app/data").resolve(), Path("/tmp").resolve(),
                      Path("/var/tmp").resolve()])
        # Windows temp when developing
        import tempfile
        roots.append(Path(tempfile.gettempdir()).resolve())
        sp = str(p)
        for r in roots:
            try:
                if sp == str(r) or sp.startswith(str(r) + "/") or sp.startswith(str(r) + "\\"):
                    return True  # under trusted root (file may be written just-in-time)
            except Exception:
                continue
        return False
    except Exception:
        return False


def filter_agent_output(out: dict | None, *, scrub_text_urls: bool = False) -> dict:
    """Lọc output agent/model trước khi kênh bot fetch/gửi.

    - Drop media URL trỏ private/metadata/non-http
    - Drop media path ngoài data/tmp
    - (tuỳ chọn) thay URL private trong text bằng ``[url_blocked]``

    Trả dict mới (shallow); ``None``/không-dict → ``{"text": ""}``.
    """
    if not isinstance(out, dict):
        return {"text": str(out or "")}
    cleaned = dict(out)
    blocked: list[str] = []

    for key in _MEDIA_URL_KEYS:
        if key not in cleaned or cleaned[key] in (None, ""):
            continue
        url = str(cleaned[key])
        if is_allowed_egress_url(url):
            continue
        logger.warning("filter_agent_output blocked %s=%s", key, url[:160])
        cleaned.pop(key, None)
        blocked.append(key)

    for key in _MEDIA_PATH_KEYS:
        if key not in cleaned or cleaned[key] in (None, ""):
            continue
        path = str(cleaned[key])
        if is_allowed_media_path(path):
            continue
        logger.warning("filter_agent_output blocked %s=%s", key, path[:160])
        cleaned.pop(key, None)
        blocked.append(key)

    if scrub_text_urls and isinstance(cleaned.get("text"), str):
        cleaned["text"] = scrub_private_urls_in_text(cleaned["text"])

    if blocked:
        note = "(media bị chặn bởi security: " + ", ".join(blocked) + ")"
        t = str(cleaned.get("text") or "").strip()
        cleaned["text"] = f"{t}\n{note}".strip() if t else note
    return cleaned


def scrub_private_urls_in_text(text: str) -> str:
    """Thay http(s) URL private/blocked trong text bằng placeholder (không đụng public)."""
    import re
    if not text:
        return text

    def _sub(m: re.Match[str]) -> str:
        raw = m.group(0)
        # trim trailing punctuation often stuck to URLs
        core = raw.rstrip(").,;]>\"'")
        suffix = raw[len(core):]
        if is_allowed_egress_url(core):
            return raw
        return "[url_blocked]" + suffix

    return re.sub(r"https?://[^\s<>\"']+", _sub, text)


def assert_egress_or_raise(url: str) -> str:
    """Helper call-site: ném BlockedURL nếu URL không được egress."""
    if is_allowed_egress_url(url):
        return str(url).strip()
    raise BlockedURL(f"Egress URL bị chặn: {str(url)[:160]}")
