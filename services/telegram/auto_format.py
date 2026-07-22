"""Auto-select optimal Telegram send mode for AI replies.

Modes (best → simplest):

- **rich**   — Bot API Rich Messages (tables, multi-heading, long structured)
- **html**   — sendMessage + HTML (bold/code/links; robust for LLM)
- **plain**  — no parse_mode (always works)

Decision is content-heuristic; send path always falls back rich → html → plain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

FormatMode = Literal["rich", "html", "plain"]

_TABLE_ROW = re.compile(r"^\s*\|.+\|\s*$", re.MULTILINE)
_TABLE_SEP = re.compile(r"^\s*\|?[\s:-]+\|[\s:|\-]+\s*$", re.MULTILINE)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+\S", re.MULTILINE)
_FENCE = re.compile(r"```")
_LIST = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+\S", re.MULTILINE)
_BOLD = re.compile(r"\*\*[^*\n].+?[^*\n]\*\*|__[^_\n].+?[^_\n]__")
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_LINK = re.compile(r"\[[^\]]+\]\([^)]+\)")
_LATEX = re.compile(r"\\\(|\\\[|\$\$")
_HTML_TAG = re.compile(r"</?(?:b|i|u|s|code|pre|a)\b", re.I)

# Soft thresholds
RICH_MIN_LEN = 500
RICH_LONG_LEN = 1200
HTML_MIN_MARKERS = 1


@dataclass(frozen=True)
class FormatChoice:
    mode: FormatMode
    reason: str
    score_rich: int = 0
    score_html: int = 0


def analyze(text: str) -> dict[str, int | bool]:
    """Feature flags for tests / debugging."""
    t = text or ""
    fences = len(_FENCE.findall(t)) // 2
    return {
        "len": len(t),
        "table_rows": len(_TABLE_ROW.findall(t)),
        "table_seps": len(_TABLE_SEP.findall(t)),
        "headings": len(_HEADING.findall(t)),
        "fences": fences,
        "lists": len(_LIST.findall(t)),
        "bolds": len(_BOLD.findall(t)),
        "codes": len(_INLINE_CODE.findall(t)),
        "links": len(_LINK.findall(t)),
        "latex": len(_LATEX.findall(t)),
        "has_html": bool(_HTML_TAG.search(t)),
    }


def choose_format(text: str, *, allow_rich: bool = True) -> FormatChoice:
    """Pick optimal mode for this body of text."""
    t = (text or "").strip()
    if not t:
        return FormatChoice("plain", "empty")

    f = analyze(t)
    n = int(f["len"])
    tables = int(f["table_rows"]) >= 2 and int(f["table_seps"]) >= 1
    headings = int(f["headings"])
    fences = int(f["fences"])
    lists = int(f["lists"])
    latex = int(f["latex"]) > 0

    # Score "wants structure"
    score_rich = 0
    if tables:
        score_rich += 50
    if headings >= 2:
        score_rich += 25
    elif headings == 1 and n >= RICH_MIN_LEN:
        score_rich += 12
    if fences >= 2:
        score_rich += 15
    elif fences == 1 and n >= RICH_MIN_LEN:
        score_rich += 8
    if lists >= 5:
        score_rich += 12
    elif lists >= 3 and n >= RICH_MIN_LEN:
        score_rich += 8
    if latex:
        score_rich += 20
    if n >= RICH_LONG_LEN and (headings or lists >= 2 or fences):
        score_rich += 15
    if n >= 2500:
        score_rich += 10

    score_html = 0
    score_html += min(20, int(f["bolds"]) * 4)
    score_html += min(12, int(f["codes"]) * 3)
    score_html += min(12, int(f["links"]) * 4)
    if fences:
        score_html += 8
    if lists:
        score_html += min(10, lists * 2)
    if headings:
        score_html += 6
    if f["has_html"]:
        score_html += 15
    # Any markdown-ish marker
    if score_html == 0 and (_BOLD.search(t) or "*" in t or "`" in t or "_" in t):
        score_html += 3

    # Prefer rich when clearly structured
    if allow_rich and score_rich >= 25:
        return FormatChoice(
            "rich",
            f"structured(score={score_rich},tables={tables},h={headings},lists={lists})",
            score_rich=score_rich,
            score_html=score_html,
        )

    if score_html >= HTML_MIN_MARKERS or score_rich > 0:
        return FormatChoice(
            "html",
            f"formatted(score_html={score_html},score_rich={score_rich})",
            score_rich=score_rich,
            score_html=score_html,
        )

    # Short plain chat
    return FormatChoice("plain", "no_markup", score_rich=score_rich, score_html=score_html)


def strip_for_plain(text: str) -> str:
    """Light cleanup when falling back to plain (keep readability)."""
    t = text or ""
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t, flags=re.DOTALL)
    t = re.sub(r"__(.+?)__", r"\1", t, flags=re.DOTALL)
    t = re.sub(r"~~(.+?)~~", r"\1", t, flags=re.DOTALL)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"```(?:\w+)?\n?(.*?)```", r"\1", t, flags=re.DOTALL)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", t)
    t = re.sub(r"^\s{0,3}#{1,6}\s+", "", t, flags=re.MULTILINE)
    return t.strip()
