"""web_reader — đọc bất kỳ URL thành Markdown sạch cho LLM/RAG.

Ưu tiên Scrapling Fetcher (HTTP + TLS-impersonation, vượt được nhiều lớp
anti-bot mà KHÔNG cần mở browser → nhẹ, không thêm browser engine vào image).
Fallback sang httpx nếu Scrapling chưa cài. HTML được chuyển sang Markdown
bằng markitdown (đã có sẵn trong hub).

Tools:
- read_url(url): URL → Markdown (toàn trang, đã lọc nav/script)
- extract_text(url, selector): lấy text theo CSS selector
"""

from __future__ import annotations

import io
import logging

from fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("web_reader")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _fetch_html(url: str, timeout: float = 20.0) -> tuple[str, str]:
    """Return (html, engine). Try Scrapling (stealth HTTP) then httpx."""
    # 1) Scrapling Fetcher — stealth HTTP (realistic fingerprint headers via
    #    browserforge), no browser engine. Scrapling >=0.4 returns a Response
    #    with .html_content; stealthy headers are on by default.
    try:
        from scrapling.fetchers import Fetcher  # lazy: optional dep
        page = Fetcher.get(url, timeout=int(timeout))
        html = getattr(page, "html_content", None) or getattr(page, "body", None) or ""
        if html:
            return html, "scrapling"
    except Exception as exc:  # not installed or failed → fallback
        logger.info("web_reader: scrapling unavailable/failed (%s), using httpx", exc)
    # 2) httpx fallback
    import httpx
    with httpx.Client(timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": _UA, "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8"}) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.text, "httpx"


def _html_to_markdown(html: str) -> str:
    """HTML → Markdown via markitdown (already a hub dependency)."""
    try:
        from markitdown import MarkItDown
        md = MarkItDown()
        result = md.convert_stream(io.BytesIO(html.encode("utf-8")), file_extension=".html")
        return (result.text_content or "").strip()
    except Exception as exc:
        logger.warning("web_reader: markitdown failed (%s), falling back to bs4 text", exc)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        return soup.get_text("\n", strip=True)


@mcp.tool()
def read_url(url: str, max_chars: int = 12000) -> str:
    """Đọc một URL và trả về nội dung dạng Markdown sạch (đã bỏ script/nav).

    Dùng để AI đọc bài báo, tài liệu, trang web bất kỳ rồi tóm tắt/trích xuất,
    hoặc để nạp vào kho RAG.

    Args:
        url: Địa chỉ trang cần đọc (http/https).
        max_chars: Cắt bớt nếu dài hơn (mặc định 12000 ký tự).

    Returns:
        Nội dung trang dạng Markdown.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        html, engine = _fetch_html(url)
    except Exception as exc:
        return f"Không tải được trang: {exc}"
    md = _html_to_markdown(html)
    if not md:
        return "Trang không có nội dung văn bản."
    if len(md) > max_chars:
        md = md[:max_chars] + f"\n\n…(đã cắt, tổng {len(md)} ký tự)"
    return f"<!-- nguồn: {url} (engine: {engine}) -->\n\n{md}"


@mcp.tool()
async def read_url_rendered(url: str, max_chars: int = 12000) -> str:
    """Đọc URL render bằng JavaScript (SPA, trang động) qua trình duyệt thật.

    Dùng khi read_url trả về trống/thiếu nội dung vì trang cần chạy JS. Chậm
    hơn read_url (mở Chromium headless qua crawl4ai) nên chỉ dùng khi cần.

    Args:
        url: Địa chỉ trang.
        max_chars: Cắt bớt nếu dài hơn (mặc định 12000).

    Returns:
        Nội dung trang dạng Markdown.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    # Render with the patchright Chromium already bundled in the image (the
    # same stealth browser the captcha-solver uses) — no extra dependency.
    try:
        from patchright.async_api import async_playwright  # lazy
    except Exception as exc:
        return f"Trình duyệt render chưa sẵn sàng: {exc}. Hãy thử read_url."
    html = ""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(user_agent=_UA)
                await page.goto(url, wait_until="networkidle", timeout=45000)
                html = await page.content()
            finally:
                await browser.close()
    except Exception as exc:
        return f"Không render được trang: {exc}"
    md = _html_to_markdown(html).strip() if html else ""
    if not md:
        return "Trang không có nội dung."
    if len(md) > max_chars:
        md = md[:max_chars] + f"\n\n…(đã cắt, tổng {len(md)} ký tự)"
    return f"<!-- nguồn: {url} (engine: crawl4ai) -->\n\n{md}"


@mcp.tool()
def extract_text(url: str, selector: str) -> str:
    """Trích text theo CSS selector từ một URL (vd selector 'article', 'h1').

    Args:
        url: Địa chỉ trang.
        selector: CSS selector (vd: 'article', '.content', 'h1').

    Returns:
        Text của các phần khớp selector.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        html, _ = _fetch_html(url)
    except Exception as exc:
        return f"Không tải được trang: {exc}"
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    parts = [el.get_text(" ", strip=True) for el in soup.select(selector)]
    parts = [p for p in parts if p]
    if not parts:
        return f"Không khớp selector '{selector}'."
    return "\n\n".join(parts)
