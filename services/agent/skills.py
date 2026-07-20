"""Markdown skills (procedural playbooks) for the agent.

Canonical layout (under DATA_DIR so it survives restarts)::

    data/agent/skills/<slug>/SKILL.md
    data/agent/skills/.disabled/<slug>/SKILL.md   # turned off

Package defaults in ``services/agent/skills_default/`` are seeded into the
data dir on first use (never overwrite an existing slug).

Frontmatter (YAML-lite, no PyYAML dependency)::

    ---
    name: Morning home brief
    description: Báo cáo nhà buổi sáng — trạng thái + thời tiết (trigger).
    group: Nhà
    enabled: true
    ---
    # body with steps the model should follow...

Description is capped at ``SKILL_DESC_MAX`` (150) in the router index so
routing stays reliable (same idea as Javis skill_router).

Config (``agent_skills``, all optional)::

    enabled: bool (default True)
    max_list: int (default 20)
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR, config

logger = logging.getLogger(__name__)

SKILL_DESC_MAX = 150
SKILL_LIST_MAX = 20
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_DESC_BOILERPLATE_RE = re.compile(
    r"^\s*(kích\s+hoạt\s+khi|sử\s+dụng\s+skill\s+này\s+khi|"
    r"dùng\s+skill\s+này\s+khi|use\s+this\s+skill\s+when)",
    re.I,
)

_SKILLS_DIR = Path(DATA_DIR) / "agent" / "skills"
_DEFAULTS_DIR = Path(__file__).with_name("skills_default")
_lock = threading.RLock()
_seeded = False


def _cfg() -> dict[str, Any]:
    raw = config.get().get("agent_skills")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def max_list() -> int:
    try:
        return max(1, min(int(_cfg().get("max_list") or SKILL_LIST_MAX), 50))
    except (TypeError, ValueError):
        return SKILL_LIST_MAX


def valid_slug(slug: str) -> bool:
    s = str(slug or "").strip()
    return bool(s) and ".." not in s and bool(_SLUG_RE.match(s))


def skills_root() -> Path:
    return _SKILLS_DIR


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse simple YAML-like frontmatter. No PyYAML required."""
    text = text or ""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            meta[key] = val
    return meta, parts[2]


def validate_description(desc: str) -> Optional[str]:
    """None = ok; string = reason rejected (Vietnamese)."""
    d = (desc or "").strip()
    if not d:
        return None
    if len(d) > SKILL_DESC_MAX:
        return (
            f"description dài {len(d)} ký tự, vượt trần {SKILL_DESC_MAX}. "
            "Đưa ví dụ trigger xuống mục '## Khi nào dùng' trong thân file."
        )
    if _DESC_BOILERPLATE_RE.match(d):
        return (
            "description mở đầu bằng cụm sáo rỗng. "
            "Nêu thẳng năng lực, vd 'Báo cáo nhà buổi sáng (HA + thời tiết).'"
        )
    return None


def _ensure_seeded() -> None:
    """Copy package default skills into data dir once (never overwrite)."""
    global _seeded
    if _seeded:
        return
    with _lock:
        if _seeded:
            return
        try:
            _SKILLS_DIR.mkdir(parents=True, exist_ok=True)
            if _DEFAULTS_DIR.is_dir():
                for d in sorted(_DEFAULTS_DIR.iterdir()):
                    if not d.is_dir() or not (d / "SKILL.md").is_file():
                        continue
                    dest = _SKILLS_DIR / d.name
                    if dest.exists():
                        continue
                    shutil.copytree(d, dest)
                    logger.info("agent.skills: seeded default skill %s", d.name)
        except Exception as exc:
            logger.warning("agent.skills: seed failed: %s", exc)
        _seeded = True


@dataclass
class SkillMeta:
    slug: str
    name: str
    description: str
    group: str
    enabled: bool
    path: Path

    def router_line(self) -> str:
        desc = (self.description or self.name or self.slug).strip()
        if len(desc) > SKILL_DESC_MAX:
            desc = desc[: SKILL_DESC_MAX - 1] + "…"
        return f"- `{self.slug}`: {desc}"


def _meta_of(slug: str, smd: Path, *, enabled: bool) -> SkillMeta:
    try:
        text = smd.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    meta, body = split_frontmatter(text)
    body = (body or "").strip()
    desc = (meta.get("description") or "").strip()
    if not desc and body:
        desc = body.split("\n")[0].lstrip("# ").strip()[:SKILL_DESC_MAX]
    en = enabled
    if str(meta.get("enabled", "true")).strip().lower() in ("0", "false", "no", "off"):
        en = False
    return SkillMeta(
        slug=slug,
        name=(meta.get("name") or slug).strip(),
        description=desc,
        group=(meta.get("group") or "Chung").strip() or "Chung",
        enabled=en,
        path=smd,
    )


def list_skills(*, enabled_only: bool = False) -> list[SkillMeta]:
    """Discover skills under data/agent/skills (+ .disabled/)."""
    if not is_enabled():
        return []
    _ensure_seeded()
    out: list[SkillMeta] = []
    seen: set[str] = set()

    def add(folder: Path, enabled: bool) -> None:
        smd = folder / "SKILL.md"
        slug = folder.name
        if not valid_slug(slug) or slug in seen or not smd.is_file():
            return
        seen.add(slug)
        m = _meta_of(slug, smd, enabled=enabled)
        if enabled_only and not m.enabled:
            return
        out.append(m)

    try:
        if _SKILLS_DIR.is_dir():
            for d in sorted(_SKILLS_DIR.iterdir()):
                if d.is_dir() and d.name != ".disabled":
                    add(d, True)
            dis = _SKILLS_DIR / ".disabled"
            if dis.is_dir():
                for d in sorted(dis.iterdir()):
                    if d.is_dir():
                        add(d, False)
    except OSError as exc:
        logger.warning("agent.skills: list failed: %s", exc)
    return out


def list_enabled() -> list[SkillMeta]:
    return [s for s in list_skills(enabled_only=False) if s.enabled][: max_list()]


def resolve(slug: str) -> Optional[Path]:
    if not valid_slug(slug):
        return None
    _ensure_seeded()
    p = _SKILLS_DIR / slug / "SKILL.md"
    try:
        if p.is_file():
            return p
    except OSError:
        pass
    return None


def load_body(slug: str) -> Optional[str]:
    """Return skill body (without frontmatter) or full text if no FM."""
    path = resolve(slug)
    if not path:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    _meta, body = split_frontmatter(text)
    body = (body or "").strip()
    return body or text.strip()


def router_block() -> str:
    """Short index for the system prompt (description only, capped)."""
    skills = list_enabled()
    if not skills:
        return ""
    lines = [
        "## Playbook / skill (gọi tool use_skill khi khớp trigger)",
        "Skill là hướng dẫn quy trình — KHÔNG thay tool cứng (HA, vẽ, search…). "
        "Khi tình huống khớp description, gọi use_skill(slug=…) rồi làm theo thân skill.",
    ]
    for s in skills:
        lines.append(s.router_line())
    return "\n".join(lines)


def _reset_for_tests(skills_dir: Path | None = None) -> None:
    """Test helper: repoint skills root and clear seed flag."""
    global _SKILLS_DIR, _seeded
    with _lock:
        if skills_dir is not None:
            _SKILLS_DIR = Path(skills_dir)
        _seeded = False
