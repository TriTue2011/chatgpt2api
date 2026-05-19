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
