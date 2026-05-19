"""Curated list of MCP server presets the UI offers as one-click installs.

Only includes MCPs with verified public HTTP endpoints (no auth required
or API key handled by the user). Smithery-hosted MCPs need a Smithery API
key + per-user URL pattern, so they're not suitable as one-click installs.

Categories:
    - dev: developer tooling
    - travel: flights and accommodation
    - search: web search
    - knowledge: encyclopedia / docs

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


# Verified working public MCPs. Tested with `tools/list` returning data.
PRESETS: list[MCPPreset] = [
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
        tags=["github", "docs", "no-auth", "verified"],
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
        tags=["flights", "travel", "no-auth", "verified"],
    ),
    MCPPreset(
        id="exa_search",
        name="Exa (AI Web Search)",
        description="Search engine tối ưu cho LLM. Trả về nội dung sạch, không cần API key cho gói cơ bản.",
        category="search",
        url="https://mcp.exa.ai/mcp",
        transport="http",
        icon="🔍",
        homepage="https://exa.ai",
        requires_api_key=False,
        free_tier=True,
        tags=["search", "ai-optimized", "no-auth", "verified"],
    ),
    MCPPreset(
        id="huggingface",
        name="Hugging Face Hub",
        description="Tìm kiếm 1M+ model AI, dataset, paper trên Hugging Face. Hỏi tài liệu, demo, ví dụ.",
        category="dev",
        url="https://huggingface.co/mcp",
        transport="http",
        icon="🤗",
        homepage="https://huggingface.co",
        requires_api_key=False,
        free_tier=True,
        tags=["ai", "models", "datasets", "no-auth", "verified"],
    ),
    MCPPreset(
        id="coingecko",
        name="CoinGecko (Crypto)",
        description="Giá Bitcoin, Ethereum và 17000+ crypto thời gian thực. Volume, market cap, biến động.",
        category="finance",
        url="https://mcp.api.coingecko.com/mcp",
        transport="http",
        icon="🪙",
        homepage="https://www.coingecko.com",
        requires_api_key=False,
        free_tier=True,
        tags=["crypto", "finance", "no-auth", "verified"],
    ),
    MCPPreset(
        id="context7",
        name="Context7 (Library Docs)",
        description="Tài liệu cập nhật cho 9000+ thư viện code. Hỏi cách dùng React, Next.js, FastAPI và mọi framework.",
        category="dev",
        url="https://mcp.context7.com/mcp",
        transport="http",
        icon="📖",
        homepage="https://context7.com",
        requires_api_key=False,
        free_tier=True,
        tags=["docs", "developer", "no-auth", "verified"],
    ),
    MCPPreset(
        id="gitmcp_generic",
        name="GitMCP (Any GitHub Repo)",
        description="Biến mọi GitHub repo thành MCP server để hỏi về code. URL mặc định trỏ đến openai/openai-cookbook — có thể đổi sang repo khác qua nút Sửa.",
        category="dev",
        url="https://gitmcp.io/openai/openai-cookbook",
        transport="http",
        icon="🔗",
        homepage="https://gitmcp.io",
        requires_api_key=False,
        free_tier=True,
        tags=["github", "code-search", "no-auth", "verified"],
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
        id="semgrep_security",
        name="Semgrep Security",
        description="Quét lỗi bảo mật code (SAST). Cần API key Semgrep miễn phí.",
        category="dev",
        url="https://mcp.semgrep.ai/mcp",
        transport="http",
        icon="🔒",
        homepage="https://semgrep.ai",
        requires_api_key=True,
        api_key_help="Đăng ký miễn phí tại https://semgrep.dev và lấy API token",
        free_tier=True,
        tags=["security", "code-analysis"],
    ),
    MCPPreset(
        id="courtlistener",
        name="CourtListener (US Law)",
        description="Án lệ, phán quyết tòa án Mỹ. Cần API token miễn phí từ courtlistener.com.",
        category="legal",
        url="https://mcp.courtlistener.com",
        transport="http",
        icon="⚖️",
        homepage="https://www.courtlistener.com",
        requires_api_key=True,
        api_key_help="Đăng ký miễn phí tại https://www.courtlistener.com/help/api/rest/ để lấy token",
        free_tier=True,
        tags=["legal", "us-law"],
    ),
]


def list_presets() -> list[dict[str, Any]]:
    return [p.to_dict() for p in PRESETS]


def get_preset(preset_id: str) -> MCPPreset | None:
    for p in PRESETS:
        if p.id == preset_id:
            return p
    return None
