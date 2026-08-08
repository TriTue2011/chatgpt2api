"""url_guard — chặn SSRF cho mọi tool nhận URL do model/người dùng đưa vào.

Vì sao cần: các tool đọc web (`read_url`, `extract_text`, `get_law_detail`,
`analyze_source`) nhận URL tự do. Một câu prompt injection trong trang web hay
trong tin nhắn Zalo đủ để bảo model gọi `read_url("http://169.254.169.254/…")`
lấy credential IAM của cloud, hoặc `http://127.0.0.1:3001/api/...` gọi thẳng
API nội bộ của zalo-server. Hub chạy CÙNG container với gateway nên "nội bộ" ở
đây gồm cả localhost.

Ba lớp chặn:
1. Giao thức: chỉ http/https.
2. Địa chỉ: phân giải DNS rồi từ chối nếu BẤT KỲ IP nào là loopback/private/
   link-local/multicast/reserved (kể cả IPv6 bọc IPv4 như ::ffff:127.0.0.1).
3. Redirect: tự đi từng chặng và kiểm lại địa chỉ ở MỖI chặng — chặn kiểu
   "trang public 302 sang 127.0.0.1".

Cộng thêm giới hạn dung lượng và thời gian để một URL trỏ vào file 10 GB không
làm hub hết RAM.

Hạn chế đã biết: giữa lúc kiểm DNS và lúc httpx mở kết nối vẫn có khe DNS
rebinding (tên miền đổi bản ghi trong mili-giây đó). Bịt hẳn phải tự nối theo IP
đã ghim và tự lo SNI/TLS; chưa làm. Rủi ro còn lại thấp hơn nhiều so với hiện
trạng không kiểm gì.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

# Trang HTML dài nhất còn hợp lý; quá ngưỡng là cắt, không nạp tiếp.
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
DEFAULT_TIMEOUT = 20.0


class SsrfBlocked(Exception):
    """URL trỏ vào vùng mạng nội bộ, dùng giao thức lạ, hoặc ngoài allowlist."""


def _unwrap(ip):
    """Bóc IPv6 bọc IPv4 (::ffff:10.0.0.1, 2002::/16) về IPv4 thật.

    Không bóc thì `is_private` trên bản bọc trả False và cả lớp chặn vô dụng.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return ip.ipv4_mapped
        if ip.sixtofour:
            return ip.sixtofour
        if ip.teredo:
            return ip.teredo[1]
    return ip


def _is_public(ip) -> bool:
    ip = _unwrap(ip)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _domain_allowed(host: str, allowed_domains: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    for d in allowed_domains:
        d = d.lower().lstrip(".")
        if host == d or host.endswith("." + d):
            return True
    return False


def check_url(url: str, allowed_domains: tuple[str, ...] | None = None) -> str:
    """Kiểm một URL, trả lại chính nó nếu an toàn. Ngược lại raise SsrfBlocked.

    allowed_domains: nếu có, host phải nằm trong danh sách này (hoặc là tên miền
    con của một mục) — dùng cho tool chỉ được phép đọc vài site cố định.
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise SsrfBlocked(f"chỉ chấp nhận http/https, không phải '{parsed.scheme or 'rỗng'}'")
    host = parsed.hostname
    if not host:
        raise SsrfBlocked("URL thiếu tên máy chủ")
    if allowed_domains and not _domain_allowed(host, allowed_domains):
        raise SsrfBlocked(
            f"'{host}' không nằm trong danh sách site được phép: {', '.join(allowed_domains)}"
        )

    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    # Host viết thẳng bằng IP: khỏi phân giải, kiểm luôn.
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_public(literal):
            raise SsrfBlocked(f"địa chỉ nội bộ bị chặn: {host}")
        return url

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SsrfBlocked(f"không phân giải được '{host}': {exc}") from exc
    addrs = sorted({info[4][0] for info in infos})
    if not addrs:
        raise SsrfBlocked(f"không phân giải được '{host}'")
    for a in addrs:
        try:
            ip = ipaddress.ip_address(a.split("%")[0])
        except ValueError:
            raise SsrfBlocked(f"địa chỉ không hợp lệ cho '{host}': {a}") from None
        if not _is_public(ip):
            # Chặn cả khi CHỈ MỘT bản ghi trỏ nội bộ: tên miền đa bản ghi có thể
            # cố ý trộn một IP public với một IP nội bộ để lách.
            raise SsrfBlocked(f"'{host}' phân giải ra địa chỉ nội bộ {a}")
    return url


def safe_get(
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_RESPONSE_BYTES,
    allowed_domains: tuple[str, ...] | None = None,
) -> tuple[str, str]:
    """GET có chặn SSRF, tự đi redirect (kiểm lại mỗi chặng), cắt theo dung lượng.

    Trả (nội_dung_text, url_cuối). Raise SsrfBlocked hoặc httpx.HTTPError.
    """
    import httpx

    current = check_url(url, allowed_domains)
    with httpx.Client(timeout=timeout, follow_redirects=False, headers=headers or {}) as client:
        for hop in range(MAX_REDIRECTS + 1):
            with client.stream("GET", current, params=params if hop == 0 else None) as resp:
                if resp.is_redirect:
                    loc = resp.headers.get("location", "")
                    if not loc:
                        resp.raise_for_status()
                        raise SsrfBlocked("máy chủ trả redirect nhưng không kèm Location")
                    current = check_url(urljoin(current, loc), allowed_domains)
                    continue
                resp.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_bytes():
                    remain = max_bytes - total
                    if len(chunk) >= remain:
                        chunks.append(chunk[:remain])
                        total = max_bytes
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                raw = b"".join(chunks)
                enc = resp.encoding or "utf-8"
                return raw.decode(enc, "replace"), str(resp.url)
    raise SsrfBlocked(f"quá {MAX_REDIRECTS} lần chuyển hướng")


def url_is_internal(url: str) -> bool:
    """True nếu URL trỏ vào vùng nội bộ. Dùng cho bộ lọc request của trình duyệt
    (không raise, vì handler của playwright chạy trên mọi subresource)."""
    try:
        check_url(url)
        return False
    except SsrfBlocked:
        return True
    except Exception:
        return True
