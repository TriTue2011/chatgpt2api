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
]


def list_presets() -> list[dict[str, Any]]:
    return [p.to_dict() for p in PRESETS]


def get_preset(preset_id: str) -> MCPPreset | None:
    for p in PRESETS:
        if p.id == preset_id:
            return p
    return None
