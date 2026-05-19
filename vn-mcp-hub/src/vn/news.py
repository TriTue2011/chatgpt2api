"""vn_news — tin tức báo Việt Nam qua RSS aggregator.

Aggregates RSS feeds from major Vietnamese news outlets:
- VnExpress: rss.vnexpress.net
- Tuổi Trẻ: tuoitre.vn/rss
- Thanh Niên: thanhnien.vn/rss
- Dân Trí: dantri.com.vn/rss

Tools cho phép LLM:
- list_topics: liệt kê chủ đề có sẵn
- get_news: lấy tin theo chủ đề (limit 10 mặc định)
- search_news: tìm tin chứa keyword
"""

from __future__ import annotations

import logging
from typing import Any

import feedparser
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("vn_news")

# topic -> list of (source_name, rss_url)
FEEDS: dict[str, list[tuple[str, str]]] = {
    "moi_nhat": [
        ("VnExpress", "https://vnexpress.net/rss/tin-moi-nhat.rss"),
        ("Tuổi Trẻ", "https://tuoitre.vn/rss/tin-moi-nhat.rss"),
        ("Thanh Niên", "https://thanhnien.vn/rss/home.rss"),
        ("Dân Trí", "https://dantri.com.vn/rss/home.rss"),
    ],
    "thoi_su": [
        ("VnExpress", "https://vnexpress.net/rss/thoi-su.rss"),
        ("Tuổi Trẻ", "https://tuoitre.vn/rss/thoi-su.rss"),
        ("Dân Trí", "https://dantri.com.vn/rss/xa-hoi.rss"),
    ],
    "kinh_doanh": [
        ("VnExpress", "https://vnexpress.net/rss/kinh-doanh.rss"),
        ("Tuổi Trẻ", "https://tuoitre.vn/rss/kinh-doanh.rss"),
        ("Dân Trí", "https://dantri.com.vn/rss/kinh-doanh.rss"),
    ],
    "the_thao": [
        ("VnExpress", "https://vnexpress.net/rss/the-thao.rss"),
        ("Thanh Niên", "https://thanhnien.vn/rss/the-thao.rss"),
        ("Dân Trí", "https://dantri.com.vn/rss/the-thao.rss"),
    ],
    "giai_tri": [
        ("VnExpress", "https://vnexpress.net/rss/giai-tri.rss"),
        ("Tuổi Trẻ", "https://tuoitre.vn/rss/giai-tri.rss"),
    ],
    "cong_nghe": [
        ("VnExpress", "https://vnexpress.net/rss/so-hoa.rss"),
        ("Dân Trí", "https://dantri.com.vn/rss/suc-manh-so.rss"),
    ],
    "the_gioi": [
        ("VnExpress", "https://vnexpress.net/rss/the-gioi.rss"),
        ("Tuổi Trẻ", "https://tuoitre.vn/rss/the-gioi.rss"),
        ("Dân Trí", "https://dantri.com.vn/rss/the-gioi.rss"),
    ],
    "suc_khoe": [
        ("VnExpress", "https://vnexpress.net/rss/suc-khoe.rss"),
        ("Dân Trí", "https://dantri.com.vn/rss/suc-khoe.rss"),
    ],
    "giao_duc": [
        ("VnExpress", "https://vnexpress.net/rss/giao-duc.rss"),
        ("Tuổi Trẻ", "https://tuoitre.vn/rss/giao-duc.rss"),
        ("Dân Trí", "https://dantri.com.vn/rss/giao-duc.rss"),
    ],
}


def _fetch_feed(source: str, url: str) -> list[dict[str, Any]]:
    try:
        feed = feedparser.parse(url)
    except Exception as exc:
        logger.warning("RSS fetch failed for %s: %s", url, exc)
        return []
    items: list[dict[str, Any]] = []
    for entry in feed.entries:
        items.append({
            "source": source,
            "title": entry.get("title", "").strip(),
            "link": entry.get("link", "").strip(),
            "summary": (entry.get("summary") or entry.get("description") or "").strip()[:300],
            "published": entry.get("published", "") or entry.get("updated", ""),
        })
    return items


def _format_items(items: list[dict[str, Any]], limit: int) -> str:
    items = items[:limit]
    if not items:
        return "Không có tin tức nào."
    lines = []
    for i, it in enumerate(items, 1):
        lines.append(
            f"{i}. **{it['title']}** — _{it['source']}_\n"
            f"   {it['summary']}\n"
            f"   {it['link']}"
        )
    return "\n\n".join(lines)


@mcp.tool()
def list_topics() -> str:
    """Liệt kê các chủ đề tin tức có sẵn từ báo Việt Nam.

    Returns:
        Danh sách topic IDs (vd: moi_nhat, thoi_su, kinh_doanh, the_thao...).
    """
    topics_with_count = [
        f"- `{name}` ({len(feeds)} nguồn)" for name, feeds in FEEDS.items()
    ]
    return "**Chủ đề tin tức có sẵn:**\n" + "\n".join(topics_with_count)


@mcp.tool()
def get_news(topic: str = "moi_nhat", limit: int = 10) -> str:
    """Lấy tin tức mới nhất từ các báo Việt Nam theo chủ đề.

    Args:
        topic: Mã chủ đề (vd: moi_nhat, thoi_su, kinh_doanh, the_thao,
               giai_tri, cong_nghe, the_gioi, suc_khoe, giao_duc).
               Mặc định: moi_nhat.
        limit: Số bài tối đa trả về (1-30, mặc định 10).

    Returns:
        Danh sách tin tức kèm tiêu đề, tóm tắt, link, nguồn.
    """
    limit = max(1, min(30, limit))
    feeds = FEEDS.get(topic.lower())
    if not feeds:
        available = ", ".join(FEEDS.keys())
        return f"Chủ đề '{topic}' không có. Chủ đề khả dụng: {available}"

    all_items: list[dict[str, Any]] = []
    for source, url in feeds:
        all_items.extend(_fetch_feed(source, url))
    return _format_items(all_items, limit)


@mcp.tool()
def search_news(keyword: str, topic: str = "moi_nhat", limit: int = 10) -> str:
    """Tìm tin tức Việt Nam chứa từ khóa.

    Args:
        keyword: Từ khóa cần tìm trong tiêu đề/tóm tắt.
        topic: Chủ đề để giới hạn (mặc định moi_nhat).
        limit: Số bài tối đa trả về (mặc định 10).

    Returns:
        Tin tức khớp keyword, sắp xếp theo thứ tự mới nhất.
    """
    limit = max(1, min(30, limit))
    feeds = FEEDS.get(topic.lower(), FEEDS["moi_nhat"])
    kw = keyword.lower().strip()
    all_items: list[dict[str, Any]] = []
    for source, url in feeds:
        all_items.extend(_fetch_feed(source, url))
    matched = [
        it for it in all_items
        if kw in it["title"].lower() or kw in it["summary"].lower()
    ]
    if not matched:
        return f"Không tìm thấy tin nào chứa '{keyword}' trong chủ đề '{topic}'."
    return _format_items(matched, limit)
