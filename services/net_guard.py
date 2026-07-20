"""Net guard — chặn SSRF + egress allowlist cho MỌI fetch URL không tin cậy.

Bối cảnh (OWASP A01:2025 — SSRF): gateway hay phải fetch URL đến từ nguồn ngoài
(attachment_url trong webhook Zalo, image_url do model trả về…). Kẻ tấn công có
thể nhét ``http://192.168.x.x`` / ``http://169.254.169.254`` để mượn tay gateway
gọi vào mạng nội bộ (HA, router, metadata). Quy tắc:

  - URL từ nguồn KHÔNG tin cậy → bắt buộc qua ``check_url``/``safe_fetch``:
    chỉ http/https, cấm IP private/loopback/link-local (kể cả sau khi resolve
    DNS — chống DNS-rebinding mức cơ bản), tuỳ chọn allowlist host.
  - Gọi nội bộ CHỦ ĐÍCH (self-call 127.0.0.1 gateway, HA đã cấu hình) thì
    KHÔNG đi qua guard này — đó là đường tin cậy do admin đặt.

Config (tuỳ chọn, top-level ``security``)::

    {"egress_allow_hosts": ["extra-cdn.example.com"]}
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import urllib.request
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Host được coi là tin cậy sẵn cho từng kênh (nền tảng chính chủ).
TELEGRAM_HOSTS = {"api.telegram.org"}
ZALO_HOSTS = {"openapi.zalo.me", "api.zalo.me"}


class BlockedURL(ValueError):
    """URL bị chặn bởi net guard (SSRF/egress)."""


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
    u = urlparse(str(url or "").strip())
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
    return url


def safe_fetch(url: str, *, allow_hosts: set[str] | None = None,
               timeout: float = 30, max_bytes: int = 50 * 1024 * 1024) -> bytes:
    """Fetch URL không tin cậy sau khi qua check_url. Trần dung lượng chống bom."""
    check_url(url, allow_hosts=allow_hosts)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise BlockedURL(f"Nội dung vượt trần {max_bytes} byte")
    return data
