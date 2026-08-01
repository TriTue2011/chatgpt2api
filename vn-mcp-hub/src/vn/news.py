"""vn_news — multi-source news aggregator (VN + international).

Sources (togglable in Studio UI):
- VnExpress, Tuoi Tre, Thanh Nien, Dan Tri (VN)
- BBC News (UK, free RSS)
- Google News (global, free RSS)

Tools:
- list_topics: show available topics
- get_news: fetch news by topic
- search_news: keyword search across feeds
"""

from __future__ import annotations

import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import feedparser
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("vn_news")

# (source_name, rss_url) — each topic has feeds from multiple sources
_VI_SOURCES = [
    ("VnExpress", "vnexpress"),
    ("Tuoi Tre", "tuoitre"),
    ("Thanh Nien", "thanhnien"),
    ("Dan Tri", "dantri"),
]
_INTL_SOURCES = [
    ("BBC News", "bbc_news"),
    ("Google News", "google_news"),
    ("World Monitor", "worldmonitor"),
]

_RSS_URLS: dict[str, dict[str, str]] = {
    "vnexpress": {
        "moi_nhat": "https://vnexpress.net/rss/tin-moi-nhat.rss",
        "thoi_su": "https://vnexpress.net/rss/thoi-su.rss",
        "kinh_doanh": "https://vnexpress.net/rss/kinh-doanh.rss",
        "the_thao": "https://vnexpress.net/rss/the-thao.rss",
        "giai_tri": "https://vnexpress.net/rss/giai-tri.rss",
        "phap_luat": "https://vnexpress.net/rss/phap-luat.rss",
        "giao_duc": "https://vnexpress.net/rss/giao-duc.rss",
        "suc_khoe": "https://vnexpress.net/rss/suc-khoe.rss",
        "khoa_hoc": "https://vnexpress.net/rss/khoa-hoc.rss",
        "so_hoa": "https://vnexpress.net/rss/so-hoa.rss",
        "du_lich": "https://vnexpress.net/rss/du-lich.rss",
    },
    "tuoitre": {
        "moi_nhat": "https://tuoitre.vn/rss/tin-moi-nhat.rss",
        "thoi_su": "https://tuoitre.vn/rss/thoi-su.rss",
        "kinh_doanh": "https://tuoitre.vn/rss/kinh-doanh.rss",
    },
    "thanhnien": {
        "moi_nhat": "https://thanhnien.vn/rss/home.rss",
        "the_thao": "https://thanhnien.vn/rss/the-thao.rss",
    },
    "dantri": {
        "moi_nhat": "https://dantri.com.vn/rss/home.rss",
        "thoi_su": "https://dantri.com.vn/rss/xa-hoi.rss",
        "kinh_doanh": "https://dantri.com.vn/rss/kinh-doanh.rss",
        "the_thao": "https://dantri.com.vn/rss/the-thao.rss",
        "giao_duc": "https://dantri.com.vn/rss/giao-duc.rss",
        "suc_khoe": "https://dantri.com.vn/rss/suc-khoe.rss",
    },
    "bbc_news": {
        "moi_nhat": "https://feeds.bbci.co.uk/news/rss.xml",
        "the_gioi": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "kinh_doanh": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "khoa_hoc": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        "cong_nghe": "https://feeds.bbci.co.uk/news/technology/rss.xml",
    },
    "google_news": {
        "moi_nhat": "https://news.google.com/rss?hl=vi&gl=VN&ceid=VN:vi",
        "the_gioi": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=vi&gl=VN&ceid=VN:vi",
        "kinh_doanh": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=vi&gl=VN&ceid=VN:vi",
        "cong_nghe": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=vi&gl=VN&ceid=VN:vi",
        "suc_khoe": "https://news.google.com/rss/headlines/section/topic/HEALTH?hl=vi&gl=VN&ceid=VN:vi",
    },
    "worldmonitor": {
        "moi_nhat": "https://raw.githubusercontent.com/koala73/worldmonitor/main/rss.xml",
        "the_gioi": "https://raw.githubusercontent.com/koala73/worldmonitor/main/rss.xml",
        "thoi_su": "https://raw.githubusercontent.com/koala73/worldmonitor/main/rss.xml",
        "kinh_doanh": "https://aljazeera.com/xml/rss/all.xml",
        "cong_nghe": "https://feeds.feedburner.com/TechCrunch/",
        "khoa_hoc": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    },
}



def _is_source_enabled(source_key: str) -> bool:
    try:
        from src.sources_config import is_enabled as _chk
        return _chk("vn_news", source_key)
    except Exception:
        return True


def _get_feeds(topic: str) -> list[tuple[str, str]]:
    """Get RSS feed URLs for a topic, filtering by user's Studio toggle config."""
    feeds: list[tuple[str, str]] = []
    # VN sources
    for name, key in _VI_SOURCES:
        if _is_source_enabled(key) and topic in _RSS_URLS.get(key, {}):
            feeds.append((name, _RSS_URLS[key][topic]))
    # International sources
    for name, key in _INTL_SOURCES:
        if _is_source_enabled(key) and topic in _RSS_URLS.get(key, {}):
            feeds.append((name, _RSS_URLS[key][topic]))
    return feeds


# ── Topic list ────────────────────────────────────────────────────────────

TOPICS = {
    "moi_nhat": "Tin moi nhat",
    "thoi_su": "Thoi su",
    "the_gioi": "The gioi",
    "kinh_doanh": "Kinh doanh",
    "the_thao": "The thao",
    "giai_tri": "Giai tri",
    "phap_luat": "Phap luat",
    "giao_duc": "Giao duc",
    "suc_khoe": "Suc khoe",
    "khoa_hoc": "Khoa hoc",
    "cong_nghe": "Cong nghe",
    "so_hoa": "So hoa",
    "du_lich": "Du lich",
}


_THE_HTML = re.compile(r"<[^>]+>")
_KHOANG_TRANG = re.compile(r"\s+")


def _lam_sach_tom_tat(raw: str, tran: int = 280) -> str:
    """Bóc HTML khỏi phần mô tả RSS để còn lại CHỮ đọc được.

    Vì sao cần: RSS báo Việt nhồi ảnh đại diện vào ô mô tả dưới dạng
    ``<a href="…"><img src="…"></a>`` rồi mới tới câu tóm tắt. Trước đây ô này
    được nhét NGUYÊN XI vào bản tin, nên người dùng nhận về một đống thẻ HTML
    thay cho tóm tắt — và vì bị cắt ở 300 ký tự, riêng cái thẻ ảnh đã ăn hết chỗ
    nên câu tóm tắt thật KHÔNG BAO GIỜ xuất hiện.

    Đo thật 01/08 (VnExpress, tin-moi-nhat.rss): cả 3 tin đầu đều mở đầu bằng
    ``<a href="https://vnexpress.net/…"><img src="https://i1-vnexpress…"``.
    Người dùng phản hồi đúng hiện tượng đó: "trình bày xấu, không có tóm tắt".
    """
    s = html.unescape(_THE_HTML.sub(" ", raw or ""))
    s = _KHOANG_TRANG.sub(" ", s).strip()
    if len(s) <= tran:
        return s
    # Cắt ở khoảng trắng gần nhất để không đứt giữa từ.
    cat = s[:tran].rsplit(" ", 1)[0]
    return (cat or s[:tran]).rstrip(" ,;:-") + "…"


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
            # TIÊU ĐỀ cũng phải làm sạch, không riêng tóm tắt: Thanh Niên trả
            # tiêu đề còn nguyên thực thể HTML (`dự đo&aacute;n`, `L&agrave;o`)
            # nên người dùng đọc được đúng chuỗi rác đó giữa câu tiếng Việt.
            # Đo thật 01/08, feed the-thao.rss.
            "title": _lam_sach_tom_tat(entry.get("title", ""), tran=200),
            "link": entry.get("link", "").strip(),
            "summary": _lam_sach_tom_tat(
                entry.get("summary") or entry.get("description") or ""),
            "published": entry.get("published", "") or entry.get("updated", ""),
        })
    return items


def _tron_theo_nguon(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Trộn ĐỀU tin giữa các báo (vòng tròn), thay vì cắt N tin đầu.

    Vì sao: `all_items` được nối theo THỨ TỰ FEED (VnExpress 47 tin, rồi Tuổi Trẻ
    50, Thanh Niên 60, Dân Trí 100, BBC, Google News). Cắt thẳng items[:10] thì
    10 tin đều của VnExpress — mang tiếng "tổng hợp nhiều báo" mà người dùng chỉ
    thấy một tờ. Đo thật 31/07: get_news(limit=12) trả 12/12 tin VnExpress dù cả
    6 nguồn đều fetch thành công.

    Vòng tròn theo nguồn: mỗi lượt lấy 1 tin của mỗi báo, nên limit=10 với 6 báo
    ra ~2 tin/báo — đúng nghĩa tổng hợp.
    """
    theo_nguon: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        theo_nguon.setdefault(str(it.get("source") or "?"), []).append(it)
    ra: list[dict[str, Any]] = []
    while len(ra) < limit:
        them = False
        for ds in theo_nguon.values():
            if ds:
                ra.append(ds.pop(0))
                them = True
                if len(ra) >= limit:
                    break
        if not them:            # hết tin ở mọi nguồn
            break
    return ra


def _format_items(items: list[dict[str, Any]], limit: int) -> str:
    items = _tron_theo_nguon(items, limit)
    if not items:
        return "Không có tin tức nào."
    # KHÔNG dán link vào bản tin đọc trên chat: một URL trần dài hơn cả câu tóm
    # tắt, và kênh chat không rút gọn nó. `link` vẫn còn trong dữ liệu cho
    # search_news và các nơi cần mở bài. Người dùng nói thẳng 01/08:
    # "trình bày xấu, không có tóm tắt, tôi không cần link".
    lines = []
    for i, it in enumerate(items, 1):
        tt = str(it.get("summary") or "").strip()
        # Tên báo để CHỮ TRƠN, không bọc `_..._`. Bộ chuyển markdown→Zalo chỉ
        # hiểu `**đậm**`; `_nghiêng_` đi qua nguyên xi nên người dùng thấy đúng
        # hai dấu gạch dưới quanh tên báo (đo thật 01/08:
        # markdown_to_zalo_message giữ lại '_VnExpress_').
        khoi = f"{i}. **{it['title']}** · {it['source']}"
        if tt:
            khoi += f"\n   {tt}"
        lines.append(khoi)
    return "\n\n".join(lines)


@mcp.tool()
def list_topics() -> str:
    """Liet ke cac chu de tin tuc co san.

    Returns:
        Danh sach topic IDs (vd: moi_nhat, thoi_su, kinh_doanh...).
    """
    lines = []
    for tid, label in TOPICS.items():
        feeds = _get_feeds(tid)
        lines.append(f"- `{tid}` ({label}, {len(feeds)} nguon)")
    return "**Chu de tin tuc:**\n" + "\n".join(lines)


@mcp.tool()
def get_news(topic: str = "moi_nhat", limit: int = 10) -> str:
    """Lay tin tuc moi nhat theo chu de.

    Args:
        topic: Ma chu de (vd: moi_nhat, thoi_su, kinh_doanh, the_gioi...).
               Mac dinh: moi_nhat.
        limit: So bai toi da (1-30, mac dinh 10).

    Returns:
        Danh sach tin tuc: tieu de, tom tat, link, nguon.
    """
    limit = max(1, min(30, limit))
    feeds = _get_feeds(topic.lower())
    if not feeds:
        available = ", ".join(TOPICS.keys())
        return f"Chu de '{topic}' khong co hoac tat ca nguon bi tat. Chu de kha dung: {available}"

    all_items: list[dict[str, Any]] = []
    for source, url in feeds:
        all_items.extend(_fetch_feed(source, url))
    return _format_items(all_items, limit)


# Bản tin CHIA MỤC — thứ tự và nhãn đúng như người dùng yêu cầu 01/08:
# "chia thành các mục: thể thao, kinh tế, xã hội, công nghệ thông tin, giáo dục,
#  y tế, giải trí, thế giới. mỗi mục trình bày - Tin 1 - Tin 2 - Tin 3".
# Nhãn ở đây CÓ DẤU (khác TOPICS vốn viết ASCII) vì đây là chữ người dùng đọc.
MUC_BAN_TIN: list[tuple[str, str]] = [
    ("the_thao", "⚽ Thể thao"),
    ("kinh_doanh", "💼 Kinh tế"),
    ("thoi_su", "🏙️ Xã hội"),
    ("cong_nghe", "💻 Công nghệ thông tin"),
    ("giao_duc", "🎓 Giáo dục"),
    ("suc_khoe", "🩺 Y tế"),
    ("giai_tri", "🎬 Giải trí"),
    ("the_gioi", "🌍 Thế giới"),
]

_TRAN_TOM_TAT_MUC = 140     # 8 mục × 3 tin: tóm tắt dài thành bức tường chữ


def _lay_mot_muc(topic: str, so_tin: int) -> list[dict[str, Any]]:
    """Tin của MỘT mục, đã trộn vòng tròn theo báo."""
    feeds = _get_feeds(topic)
    if not feeds:
        return []
    items: list[dict[str, Any]] = []
    for source, url in feeds:
        items.extend(_fetch_feed(source, url))
    return _tron_theo_nguon(items, so_tin)


@mcp.tool()
def get_news_sections(per_section: int = 3, kem_tom_tat: bool = True) -> str:
    """Ban tin CHIA MUC: the thao, kinh te, xa hoi, CNTT, giao duc, y te,
    giai tri, the gioi. Moi muc lay `per_section` tin.

    Dung cho cau hoi kieu "tin tuc hom nay" khi nguoi dung muon ban tin day du
    chia theo linh vuc, thay vi mot danh sach phang.

    Args:
        per_section: So tin moi muc (1-5, mac dinh 3).
        kem_tom_tat: True (mac dinh) = moi tin kem mot cau tom tat.
                     False = CHI tieu de, dung khi nguoi dung xin bo tom tat.

    Returns:
        Ban tin nhieu muc, moi tin mot dong gach dau dong kem tom tat ngan.
        Khong co link, khong co HTML.
    """
    so_tin = max(1, min(5, int(per_section or 3)))
    # Lấy 8 mục SONG SONG: tuần tự mất ~9,8s (đo thật 01/08) — quá lâu cho một
    # lượt chat. Song song thì tổng ≈ mục chậm nhất.
    ket: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=len(MUC_BAN_TIN)) as pool:
        tuong_lai = {pool.submit(_lay_mot_muc, tid, so_tin): tid
                     for tid, _ in MUC_BAN_TIN}
        for f in as_completed(tuong_lai):
            tid = tuong_lai[f]
            try:
                ket[tid] = f.result()
            except Exception as exc:
                logger.warning("muc tin %s loi: %s", tid, exc)
                ket[tid] = []

    khoi: list[str] = []
    thieu: list[str] = []
    for tid, nhan in MUC_BAN_TIN:
        ds = ket.get(tid) or []
        if not ds:
            thieu.append(nhan)
            continue
        dong = [f"**{nhan}**"]
        for it in ds:
            d = f"- **{it['title']}**"
            # Bỏ tóm tắt phải làm ở ĐÂY, bằng code. Trước đây việc này được nhờ
            # model bày lại: đo thật 01/08, gửi bản tin 4819 ký tự cho model thì
            # nó KHÔNG kịp xong trong 20 giây, lần nào cũng hết giờ rồi rơi về
            # bản gốc — người dùng chờ thêm 20 giây để nhận đúng thứ cũ.
            if kem_tom_tat:
                tt = _lam_sach_tom_tat(str(it.get("summary") or ""),
                                       tran=_TRAN_TOM_TAT_MUC)
                if tt:
                    d += f" — {tt}"
            dong.append(d)
        khoi.append("\n".join(dong))

    if not khoi:
        return "Không lấy được tin tức nào lúc này."
    ra = "\n\n".join(khoi)
    # Nói THẲNG mục nào trống, thay vì lặng lẽ bỏ bớt: thiếu mục mà không nói
    # thì người dùng tưởng hôm nay không có tin, chứ không biết là nguồn hỏng.
    if thieu:
        ra += "\n\n(Chưa lấy được tin cho mục: " + ", ".join(thieu) + ")"
    return ra


@mcp.tool()
def search_news(keyword: str, topic: str = "moi_nhat", limit: int = 10) -> str:
    """Tim tin tuc chua tu khoa.

    Args:
        keyword: Tu khoa can tim trong tieu de/tom tat.
        topic: Chu de gioi han (mac dinh moi_nhat).
        limit: So bai toi da (mac dinh 10).

    Returns:
        Tin tuc khop keyword, sap xep theo moi nhat.
    """
    limit = max(1, min(30, limit))
    feeds = _get_feeds(topic.lower()) or _get_feeds("moi_nhat")
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
