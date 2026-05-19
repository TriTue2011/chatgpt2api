"""Curated list of MCP server presets the UI offers as one-click installs.

Each preset is a remote-hosted MCP — local stdio MCPs are out of scope for
chatgpt2api today. Preset URLs are stable hosted endpoints, not subprocess
commands.

Categories:
    - search: real-time web search
    - knowledge: encyclopedia / docs
    - weather: forecasts and conditions
    - memory: persistent context across sessions
    - calendar: schedules and events
    - dev: developer tooling

The UI calls /api/mcp/presets to render the gallery; clicking a preset
opens the add-server form with `url` and `transport` pre-filled.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any


@dataclass
class MCPPreset:
    """Metadata for a single one-click MCP install."""

    id: str
    name: str
    description: str
    category: str
    url: str
    transport: str = "http"
    icon: str = ""
    homepage: str = ""
    requires_api_key: bool = False
    api_key_help: str = ""
    free_tier: bool = True
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# All hosted via public Smithery / dedicated endpoints.
# `requires_api_key=True` means the preset still installs but the user must
# fill in api_key for the server to work.
PRESETS: list[MCPPreset] = [
    MCPPreset(
        id="memory_official",
        name="Memory (Knowledge Graph)",
        description="Persistent knowledge graph memory across AI sessions. Stores facts, relationships, retrieves context.",
        category="memory",
        url="https://server.smithery.ai/@modelcontextprotocol/memory/mcp",
        transport="http",
        icon="🧠",
        homepage="https://github.com/modelcontextprotocol/servers/tree/main/src/memory",
        requires_api_key=False,
        free_tier=True,
        tags=["official", "anthropic", "long-term memory"],
    ),
    MCPPreset(
        id="weather_openmeteo",
        name="Weather (Open-Meteo)",
        description="Real-time weather, forecasts up to 16 days, historical data since 1940. No API key needed.",
        category="weather",
        url="https://server.smithery.ai/@gbrigandi/mcp-server-openmeteo/mcp",
        transport="http",
        icon="☁️",
        homepage="https://github.com/gbrigandi/mcp-server-openmeteo",
        requires_api_key=False,
        free_tier=True,
        tags=["weather", "no-auth", "free"],
    ),
    MCPPreset(
        id="search_duckduckgo",
        name="Search (DuckDuckGo)",
        description="Privacy-first web search, no API key, no tracking. Returns titles, snippets, URLs.",
        category="search",
        url="https://server.smithery.ai/@nickclyde/duckduckgo-mcp-server/mcp",
        transport="http",
        icon="🦆",
        homepage="https://github.com/nickclyde/duckduckgo-mcp-server",
        requires_api_key=False,
        free_tier=True,
        tags=["search", "privacy", "no-auth"],
    ),
    MCPPreset(
        id="wikipedia_official",
        name="Wikipedia",
        description="Search and fetch articles from Wikipedia in 300+ languages. Vietnamese supported.",
        category="knowledge",
        url="https://server.smithery.ai/@Rudra-ravi/wikipedia-mcp/mcp",
        transport="http",
        icon="📚",
        homepage="https://github.com/Rudra-ravi/wikipedia-mcp",
        requires_api_key=False,
        free_tier=True,
        tags=["wikipedia", "multilingual", "no-auth"],
    ),
    MCPPreset(
        id="arxiv_papers",
        name="ArXiv Papers",
        description="Search 2M+ scientific papers on ArXiv. Physics, math, CS, biology, economics.",
        category="knowledge",
        url="https://server.smithery.ai/@blazickjp/arxiv-mcp-server/mcp",
        transport="http",
        icon="🎓",
        homepage="https://github.com/blazickjp/arxiv-mcp-server",
        requires_api_key=False,
        free_tier=True,
        tags=["academic", "research", "no-auth"],
    ),
    MCPPreset(
        id="reddit_search",
        name="Reddit",
        description="Search Reddit posts, comments, subreddits. Real-time discussions.",
        category="social",
        url="https://server.smithery.ai/@adhikasp/mcp-reddit/mcp",
        transport="http",
        icon="👽",
        homepage="https://github.com/adhikasp/mcp-reddit",
        requires_api_key=False,
        free_tier=True,
        tags=["social", "forums", "no-auth"],
    ),
    MCPPreset(
        id="context7_docs",
        name="Context7 Library Docs",
        description="Latest documentation for any code library. Updated automatically.",
        category="dev",
        url="https://server.smithery.ai/@upstash/context7/mcp",
        transport="http",
        icon="📖",
        homepage="https://github.com/upstash/context7",
        requires_api_key=False,
        free_tier=True,
        tags=["docs", "developer", "no-auth"],
    ),
    MCPPreset(
        id="youtube_transcript",
        name="YouTube Transcript",
        description="Fetch video transcripts and subtitles from YouTube. Useful for summarising videos.",
        category="media",
        url="https://server.smithery.ai/@kimtaeyoon83/mcp-server-youtube-transcript/mcp",
        transport="http",
        icon="📺",
        homepage="https://github.com/kimtaeyoon83/mcp-server-youtube-transcript",
        requires_api_key=False,
        free_tier=True,
        tags=["video", "transcript", "no-auth"],
    ),
    MCPPreset(
        id="brave_search",
        name="Brave Search",
        description="Privacy-first search via Brave. 2K queries/month free.",
        category="search",
        url="https://server.smithery.ai/@modelcontextprotocol/brave-search/mcp",
        transport="http",
        icon="🦁",
        homepage="https://api.search.brave.com",
        requires_api_key=True,
        api_key_help="Đăng ký API key miễn phí tại https://api.search.brave.com (2K req/tháng)",
        free_tier=True,
        tags=["search", "privacy", "free-tier"],
    ),
    MCPPreset(
        id="tavily_search",
        name="Tavily Search",
        description="AI-optimised search results. 1K queries/month free.",
        category="search",
        url="https://server.smithery.ai/@tavily-ai/tavily-mcp/mcp",
        transport="http",
        icon="🔎",
        homepage="https://tavily.com",
        requires_api_key=True,
        api_key_help="Đăng ký miễn phí tại https://tavily.com (1K req/tháng)",
        free_tier=True,
        tags=["search", "ai-optimized", "free-tier"],
    ),
    MCPPreset(
        id="firecrawl_scrape",
        name="Firecrawl Web Scraper",
        description="Crawl and scrape any website. 500 pages/month free.",
        category="web",
        url="https://server.smithery.ai/@mendableai/firecrawl-mcp-server/mcp",
        transport="http",
        icon="🔥",
        homepage="https://firecrawl.dev",
        requires_api_key=True,
        api_key_help="Đăng ký miễn phí tại https://firecrawl.dev (500 trang/tháng)",
        free_tier=True,
        tags=["scraping", "web", "free-tier"],
    ),
    MCPPreset(
        id="deepwiki",
        name="DeepWiki (GitHub Docs)",
        description="Đọc tài liệu mọi GitHub repo. Hỏi về code, README, docs của bất kỳ project mã nguồn mở.",
        category="dev",
        url="https://mcp.deepwiki.com/mcp",
        transport="http",
        icon="📘",
        homepage="https://mcp.deepwiki.com",
        requires_api_key=False,
        free_tier=True,
        tags=["github", "docs", "no-auth"],
    ),
    MCPPreset(
        id="semgrep_security",
        name="Semgrep Security",
        description="Quét lỗi bảo mật code (SAST). Phát hiện vulnerability, code smell trong nhiều ngôn ngữ.",
        category="dev",
        url="https://mcp.semgrep.ai/mcp",
        transport="http",
        icon="🔒",
        homepage="https://semgrep.ai",
        requires_api_key=False,
        free_tier=True,
        tags=["security", "code-analysis", "no-auth"],
    ),
    MCPPreset(
        id="skiplagged_flights",
        name="Skiplagged (Flights)",
        description="Tìm vé máy bay rẻ với hidden city fares. Không cần đăng ký.",
        category="travel",
        url="https://mcp.skiplagged.com/mcp",
        transport="http",
        icon="✈️",
        homepage="https://skiplagged.com",
        requires_api_key=False,
        free_tier=True,
        tags=["flights", "travel", "no-auth"],
    ),
    MCPPreset(
        id="airbnb_search",
        name="Airbnb",
        description="Tìm phòng Airbnb. Search theo địa điểm, ngày, giá, tiện nghi.",
        category="travel",
        url="https://server.smithery.ai/@openbnb-org/mcp-server-airbnb/mcp",
        transport="http",
        icon="🏨",
        homepage="https://github.com/openbnb-org/mcp-server-airbnb",
        requires_api_key=False,
        free_tier=True,
        tags=["airbnb", "travel", "no-auth"],
    ),
    MCPPreset(
        id="openstreetmap",
        name="OpenStreetMap",
        description="Bản đồ mở, tìm địa điểm, geocoding, POI. Không cần API key.",
        category="maps",
        url="https://server.smithery.ai/@jagan-shanmugam/open-streetmap-mcp/mcp",
        transport="http",
        icon="🗺️",
        homepage="https://github.com/jagan-shanmugam/open-streetmap-mcp",
        requires_api_key=False,
        free_tier=True,
        tags=["maps", "geocoding", "no-auth"],
    ),
    MCPPreset(
        id="wikidata",
        name="Wikidata",
        description="Cơ sở dữ liệu tri thức có cấu trúc. Liên kết sự kiện, người, địa điểm lịch sử.",
        category="knowledge",
        url="https://server.smithery.ai/@zzaebok/mcp-wikidata/mcp",
        transport="http",
        icon="🏛️",
        homepage="https://github.com/zzaebok/mcp-wikidata",
        requires_api_key=False,
        free_tier=True,
        tags=["knowledge-graph", "structured", "no-auth"],
    ),
    MCPPreset(
        id="open_library",
        name="Open Library",
        description="20M+ sách. Tìm theo tác giả, tiêu đề, ISBN. Đọc tóm tắt sách miễn phí.",
        category="knowledge",
        url="https://server.smithery.ai/@theRealBitboy/openlibrary-mcp/mcp",
        transport="http",
        icon="📖",
        homepage="https://openlibrary.org",
        requires_api_key=False,
        free_tier=True,
        tags=["books", "library", "no-auth"],
    ),
    MCPPreset(
        id="okx_crypto",
        name="OKX Crypto",
        description="Giá Bitcoin, Ethereum và 600+ crypto thời gian thực. Không cần đăng ký.",
        category="finance",
        url="https://server.smithery.ai/@OKX-MCP/okx-mcp-server/mcp",
        transport="http",
        icon="🪙",
        homepage="https://github.com/OKX-MCP/okx-mcp-server",
        requires_api_key=False,
        free_tier=True,
        tags=["crypto", "finance", "no-auth"],
    ),
    MCPPreset(
        id="pubmed",
        name="PubMed",
        description="36M+ bài báo y học. Tra cứu bệnh, thuốc, nghiên cứu sức khỏe.",
        category="health",
        url="https://server.smithery.ai/@andresayac/pubmed-mcp/mcp",
        transport="http",
        icon="🏥",
        homepage="https://github.com/andresayac/pubmed-mcp",
        requires_api_key=False,
        free_tier=True,
        tags=["medical", "research", "no-auth"],
    ),
    MCPPreset(
        id="courtlistener",
        name="CourtListener (US Law)",
        description="Án lệ, phán quyết tòa án Mỹ. Tra cứu luật pháp, dữ liệu công khai.",
        category="legal",
        url="https://mcp.courtlistener.com",
        transport="http",
        icon="⚖️",
        homepage="https://www.courtlistener.com",
        requires_api_key=False,
        free_tier=True,
        tags=["legal", "us-law", "no-auth"],
    ),
    MCPPreset(
        id="github_official",
        name="GitHub",
        description="Quản lý repo, issue, PR, search code. Cần GitHub Personal Access Token (free).",
        category="dev",
        url="https://api.githubcopilot.com/mcp/",
        transport="http",
        icon="🐙",
        homepage="https://github.com/github/github-mcp-server",
        requires_api_key=True,
        api_key_help="Tạo PAT tại https://github.com/settings/tokens (chọn quyền repo, read:org)",
        free_tier=True,
        tags=["github", "official", "dev"],
    ),
    MCPPreset(
        id="zapier",
        name="Zapier (7000+ apps)",
        description="Kết nối 7000+ apps qua workflow automation. 100 tasks/tháng miễn phí.",
        category="automation",
        url="https://mcp.zapier.com/api/mcp",
        transport="http",
        icon="⚡",
        homepage="https://zapier.com/mcp",
        requires_api_key=True,
        api_key_help="Đăng ký tại https://zapier.com/mcp (100 tasks/tháng free)",
        free_tier=True,
        tags=["automation", "integration", "free-tier"],
    ),
]


def list_presets() -> list[dict[str, Any]]:
    return [p.to_dict() for p in PRESETS]


def get_preset(preset_id: str) -> MCPPreset | None:
    for p in PRESETS:
        if p.id == preset_id:
            return p
    return None
