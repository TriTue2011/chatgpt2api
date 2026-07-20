"""Wiki lite + INGEST — structured notes under DATA_DIR/agent/wiki.

Layout::

    data/agent/wiki/
      index.md                 # auto-maintained list of notes
      notes/<slug>.md          # provenance frontmatter + body
      digests/YYYY-MM-DD.md    # daily digest

Tools:
  - ingest / wiki_search / wiki_read / wiki_digest

Config (``agent_wiki``)::

    enabled: bool (default True)
    also_memory: bool (default True)
    max_note_chars: int (default 8000)
    digest_enabled: bool (default True)
    digest_hour: int 0-23 VN (default 7)
    digest_llm: bool (default False)
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from services.agent.runtime import call_model, content_of
from services.agent.skills import valid_slug, split_frontmatter
from services.config import DATA_DIR, config

logger = logging.getLogger(__name__)

_WIKI_DIR = Path(DATA_DIR) / "agent" / "wiki"
_NOTES_DIR = _WIKI_DIR / "notes"
_DIGEST_DIR = _WIKI_DIR / "digests"
_INDEX = _WIKI_DIR / "index.md"
_lock = threading.RLock()
_WORD_RE = re.compile(r"[\wÀ-ỹ]{2,}", re.UNICODE)

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:
    _TZ = timezone(timedelta(hours=7))


def _cfg() -> dict[str, Any]:
    raw = config.get().get("agent_wiki")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def also_memory() -> bool:
    return bool(_cfg().get("also_memory", True))


def max_note_chars() -> int:
    try:
        return max(500, int(_cfg().get("max_note_chars") or 8000))
    except (TypeError, ValueError):
        return 8000


def digest_enabled() -> bool:
    return bool(_cfg().get("digest_enabled", True))


def digest_hour() -> int:
    try:
        return max(0, min(23, int(_cfg().get("digest_hour") if _cfg().get("digest_hour") is not None else 7)))
    except (TypeError, ValueError):
        return 7


def digest_llm() -> bool:
    return bool(_cfg().get("digest_llm", False))


def _main_model() -> str:
    return str(config.get().get("telegram_ai_model") or "").strip() or "cx/auto"


def _now_vn() -> datetime:
    return datetime.now(_TZ)


def _ensure() -> None:
    _NOTES_DIR.mkdir(parents=True, exist_ok=True)
    _DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    if not _INDEX.exists():
        _INDEX.write_text(
            "# Wiki gia đình\n\nGhi chú do trợ lý thu nạp (INGEST).\n\n",
            encoding="utf-8",
        )


def _content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()[:16]


def _fm_escape(val: str) -> str:
    return str(val or "").replace("\n", " ").replace('"', "'")[:200]


def _build_frontmatter(meta: dict[str, Any]) -> str:
    lines = ["---"]
    for key in (
        "title", "source", "who", "platform", "chat_id",
        "created_at", "tags", "content_hash",
    ):
        v = meta.get(key)
        if v is None or v == "":
            continue
        lines.append(f"{key}: {_fm_escape(str(v))}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def parse_note(path: Path) -> dict[str, Any]:
    """Read note file → {slug, title, body, meta, created_at, mtime}."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    fm, body = split_frontmatter(raw)
    title = str(fm.get("title") or path.stem)
    if not fm.get("title"):
        for line in body.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
    created = str(fm.get("created_at") or "")
    mtime = path.stat().st_mtime if path.exists() else 0.0
    # Prefer frontmatter ISO; fallback mtime
    ts = mtime
    if created:
        try:
            # accept "2026-07-18 07:00" or ISO
            created_norm = created.replace("T", " ").replace("Z", "")[:19]
            dt = datetime.strptime(created_norm, "%Y-%m-%d %H:%M")
            ts = dt.replace(tzinfo=_TZ).timestamp()
        except Exception:
            try:
                dt = datetime.strptime(created[:10], "%Y-%m-%d")
                ts = dt.replace(tzinfo=_TZ).timestamp()
            except Exception:
                pass
    return {
        "slug": path.stem,
        "title": title,
        "body": body,
        "meta": fm,
        "created_at": created,
        "ts": ts,
        "mtime": mtime,
        "path": str(path),
        "snippet": re.sub(r"\s+", " ", body)[:180],
    }


def _slugify(title: str) -> str:
    t = (title or "").strip().lower()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9À-ỹ]+", "-", t, flags=re.I)
    t = re.sub(r"-+", "-", t).strip("-")
    if not t:
        t = f"note-{int(time.time())}"
    # ASCII-ish slug for filesystem safety
    t = re.sub(r"[^a-z0-9\-]+", "", t.lower()) or f"note-{int(time.time())}"
    if not valid_slug(t):
        t = f"note-{int(time.time())}"
    return t[:64]


def _unique_slug(base: str) -> str:
    slug = base
    n = 2
    while (_NOTES_DIR / f"{slug}.md").exists():
        slug = f"{base}-{n}"
        n += 1
        if n > 50:
            slug = f"{base}-{int(time.time())}"
            break
    return slug


def _summarize(raw: str, title_hint: str = "") -> dict[str, str]:
    """LLM → {title, summary, tags, memory_line}."""
    raw = (raw or "").strip()[:6000]
    if not raw:
        return {
            "title": title_hint or "Ghi chú trống",
            "summary": "",
            "tags": "",
            "memory_line": "",
        }
    resp = call_model(
        _main_model(),
        [
            {
                "role": "system",
                "content": (
                    "Bạn thu nạp tri thức vào wiki gia đình. Trả lời ĐÚNG format:\n"
                    "TITLE: (tiêu đề ngắn tiếng Việt, ≤80 ký tự)\n"
                    "TAGS: (3–6 tag, cách nhau bởi dấu phẩy)\n"
                    "SUMMARY: (tóm tắt 5–12 dòng markdown, giữ số liệu/tên quan trọng)\n"
                    "MEMORY: (1 câu fact để ghi nhớ lâu, hoặc để trống nếu không đáng nhớ)"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Gợi ý tiêu đề: {title_hint or '(không)'}\n\n"
                    f"Nội dung thô:\n{raw}"
                ),
            },
        ],
        timeout=90,
        max_tokens=700,
        no_smart_home=True,
    )
    if resp.get("error"):
        # Offline fallback
        title = title_hint or raw.split("\n", 1)[0][:60] or "Ghi chú"
        return {
            "title": title,
            "summary": raw[:1500],
            "tags": "ghi-chu",
            "memory_line": "",
        }
    text = content_of(resp)

    def _field(name: str) -> str:
        m = re.search(rf"{name}\s*:\s*(.+?)(?=\n[A-Z]{{2,}}\:|\Z)", text, re.I | re.S)
        return (m.group(1).strip() if m else "").strip()

    title = _field("TITLE") or title_hint or "Ghi chú"
    tags = _field("TAGS")
    summary = _field("SUMMARY") or raw[:1500]
    memory_line = _field("MEMORY")
    return {
        "title": title[:120],
        "summary": summary[: max_note_chars()],
        "tags": tags[:200],
        "memory_line": memory_line[:300],
    }


def _write_index_entry(slug: str, title: str, tags: str) -> None:
    stamp = time.strftime("%Y-%m-%d")
    line = f"- [{stamp}] [[notes/{slug}|{title}]]"
    if tags:
        line += f" — {tags}"
    line += "\n"
    with _lock:
        _ensure()
        try:
            existing = _INDEX.read_text(encoding="utf-8") if _INDEX.exists() else ""
            if f"notes/{slug}" in existing:
                return
            with _INDEX.open("a", encoding="utf-8") as f:
                f.write(line)
        except OSError as exc:
            logger.warning("agent.wiki: index write failed: %s", exc)


def ingest(
    content: str,
    *,
    title: str = "",
    who: str = "",
    source: str = "",
    platform: str = "",
    chat_id: str = "",
) -> dict[str, Any]:
    """Create a wiki note from raw content. Returns {text, slug, path, meta}."""
    if not is_enabled():
        return {"text": "Wiki đang tắt trên máy chủ ạ.", "ok": False}
    content = (content or "").strip()
    if len(content) < 8:
        return {"text": "Nội dung quá ngắn để thu nạp ạ.", "ok": False}

    _ensure()
    meta = _summarize(content, title_hint=title)
    base = _slugify(meta["title"] or title or "note")
    slug = _unique_slug(base)
    now = _now_vn()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    chash = _content_hash(content)
    # Infer platform from who (orchestrator user_id) when not given
    plat = (platform or "").strip().lower()
    cid = (chat_id or "").strip()
    who_s = (who or "").strip()
    if not plat and who_s:
        if who_s.startswith("zalop_"):
            plat, cid = "zalop", cid or who_s[6:]
        elif who_s.startswith("zalo_"):
            plat, cid = "zalo", cid or who_s[5:]
        else:
            plat, cid = "tg", cid or who_s
    src = (source or "ingest").strip() or "ingest"
    fm = {
        "title": meta["title"],
        "source": src,
        "who": who_s,
        "platform": plat,
        "chat_id": cid,
        "created_at": stamp,
        "tags": meta["tags"] or "",
        "content_hash": chash,
    }
    header_human = (
        f"# {meta['title']}\n\n"
        f"- Ngày: {stamp}\n"
        f"- Tags: {meta['tags'] or '—'}\n"
        f"- Nguồn: {src}\n"
    )
    if who_s:
        header_human += f"- Từ: {who_s}\n"
    if plat:
        header_human += f"- Kênh: {plat}" + (f" / {cid}" if cid else "") + "\n"
    body = (
        f"{_build_frontmatter(fm)}"
        f"{header_human}\n"
        f"## Tóm tắt\n\n{meta['summary']}\n\n"
        f"## Gốc (rút gọn)\n\n"
        f"{content[:2000]}\n"
    )
    path = _NOTES_DIR / f"{slug}.md"
    with _lock:
        try:
            path.write_text(body, encoding="utf-8")
        except OSError as exc:
            return {"text": f"Không ghi được wiki: {exc}", "ok": False}
    _write_index_entry(slug, meta["title"], meta["tags"])

    mem_line = (meta.get("memory_line") or "").strip()
    if also_memory() and mem_line:
        try:
            from services.agent import state
            state.append_memory(mem_line, who=who or "wiki")
        except Exception:
            pass

    return {
        "text": (
            f"Đã thu nạp vào wiki 📚\n"
            f"• Tiêu đề: **{meta['title']}**\n"
            f"• Mã: `{slug}`\n"
            f"• Tags: {meta['tags'] or '—'}\n"
            f"• Provenance: `{src}`"
            + (f" / {plat}" if plat else "")
            + f" / hash=`{chash}`\n"
            + (f"• Ghi nhớ: {mem_line}\n" if mem_line else "")
            + f"\nĐọc lại: wiki_read slug=`{slug}`"
        ),
        "ok": True,
        "slug": slug,
        "title": meta["title"],
        "path": str(path),
        "meta": fm,
    }


def search(query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    if not is_enabled():
        return []
    _ensure()
    words = []
    seen: set[str] = set()
    for w in _WORD_RE.findall((query or "").lower()):
        if w not in seen:
            seen.add(w)
            words.append(w)
        if len(words) >= 12:
            break
    if not words:
        return []
    hits: list[dict[str, Any]] = []
    try:
        for p in sorted(_NOTES_DIR.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            low = text.lower()
            score = sum(1 for w in words if w in low)
            if score <= 0:
                continue
            title = p.stem
            for line in text.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            snippet = text.replace("\n", " ")
            if len(snippet) > 180:
                snippet = snippet[:180] + "…"
            hits.append({
                "slug": p.stem,
                "title": title,
                "score": score,
                "snippet": snippet,
            })
    except OSError:
        return []
    hits.sort(key=lambda h: (-h["score"], h["slug"]))
    return hits[: max(1, min(limit, 20))]


def read(slug: str) -> Optional[str]:
    if not valid_slug(slug):
        return None
    path = _NOTES_DIR / f"{slug}.md"
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")[: max_note_chars()]
    except OSError:
        return None
    return None


def list_recent(limit: int = 15) -> list[dict[str, str]]:
    _ensure()
    out: list[dict[str, str]] = []
    try:
        files = sorted(
            _NOTES_DIR.glob("*.md"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        for p in files[:limit]:
            note = parse_note(p)
            out.append({
                "slug": note.get("slug") or p.stem,
                "title": note.get("title") or p.stem,
                "source": str((note.get("meta") or {}).get("source") or ""),
                "created_at": str(note.get("created_at") or ""),
            })
    except OSError:
        pass
    return out


def notes_for_day(day: str | None = None) -> list[dict[str, Any]]:
    """Notes whose created_at / mtime falls on ``day`` (YYYY-MM-DD, VN)."""
    _ensure()
    if not day:
        day = _now_vn().strftime("%Y-%m-%d")
    day = day.strip()[:10]
    try:
        day_dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=_TZ)
    except ValueError:
        return []
    start = day_dt.timestamp()
    end = (day_dt + timedelta(days=1)).timestamp()
    hits: list[dict[str, Any]] = []
    try:
        for p in _NOTES_DIR.glob("*.md"):
            note = parse_note(p)
            ts = float(note.get("ts") or 0)
            if start <= ts < end:
                hits.append(note)
    except OSError:
        return []
    hits.sort(key=lambda n: float(n.get("ts") or 0), reverse=True)
    return hits


def digest_path(day: str) -> Path:
    return _DIGEST_DIR / f"{day}.md"


def read_digest(day: str | None = None) -> Optional[str]:
    if not day:
        day = _now_vn().strftime("%Y-%m-%d")
    path = digest_path(day[:10])
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")[: max_note_chars()]
    except OSError:
        return None
    return None


def build_daily_digest(
    day: str | None = None,
    *,
    force: bool = False,
    use_llm: bool | None = None,
) -> dict[str, Any]:
    """Write digests/YYYY-MM-DD.md from that day's notes (+ MEMORY tail).

    Returns {ok, day, path, text, note_count, skipped?}.
    """
    if not is_enabled() or not digest_enabled():
        return {"ok": False, "text": "Wiki digest đang tắt.", "day": day or ""}
    _ensure()
    if not day:
        day = _now_vn().strftime("%Y-%m-%d")
    day = day.strip()[:10]
    path = digest_path(day)
    if path.is_file() and not force:
        body = path.read_text(encoding="utf-8", errors="replace")
        return {
            "ok": True,
            "day": day,
            "path": str(path),
            "text": body,
            "note_count": body.count("\n- `") or body.count("\n•"),
            "skipped": True,
        }

    notes = notes_for_day(day)
    mem_lines: list[str] = []
    try:
        from services.agent import state
        mem = state.load_memory(limit_chars=3000)
        for ln in mem.splitlines():
            s = ln.strip()
            if s.startswith("-") and day in s:
                mem_lines.append(s)
        if not mem_lines:
            # recent facts as FYI
            mem_lines = [
                ln.strip() for ln in mem.splitlines()
                if ln.strip().startswith("-")
            ][-5:]
    except Exception:
        pass

    bullets = []
    for n in notes:
        src = (n.get("meta") or {}).get("source") or "?"
        bullets.append(
            f"- `{n.get('slug')}` ({src}) **{n.get('title')}** — "
            f"{(n.get('snippet') or '')[:100]}"
        )
    if not bullets and not mem_lines:
        body = (
            f"# Digest {day}\n\n"
            f"_Không có ghi chú wiki mới trong ngày. Mọi thứ yên ả._\n"
        )
    else:
        sections = [
            f"# Digest {day}\n",
            f"- Tạo lúc: {_now_vn().strftime('%Y-%m-%d %H:%M')} (VN)\n"
            f"- Số ghi chú: {len(notes)}\n",
        ]
        if bullets:
            sections.append("## Wiki trong ngày\n\n" + "\n".join(bullets) + "\n")
        if mem_lines:
            sections.append("## Trí nhớ liên quan\n\n" + "\n".join(mem_lines) + "\n")
        body = "\n".join(sections)

        do_llm = digest_llm() if use_llm is None else bool(use_llm)
        if do_llm and (bullets or mem_lines):
            try:
                resp = call_model(
                    _main_model(),
                    [
                        {
                            "role": "system",
                            "content": (
                                "Viết digest ngày cho gia đình tiếng Việt, xưng em, "
                                "4–8 dòng: Highlights / Việc cần nhớ / FYI. "
                                "Không bịa; chỉ dùng dữ liệu user đưa."
                            ),
                        },
                        {"role": "user", "content": body[:4000]},
                    ],
                    timeout=60,
                    max_tokens=500,
                    no_smart_home=True,
                )
                if not resp.get("error"):
                    polished = content_of(resp).strip()
                    if polished:
                        body = (
                            f"# Digest {day}\n\n"
                            f"{polished}\n\n"
                            f"---\n\n## Chi tiết\n\n"
                            + ("\n".join(bullets) if bullets else "_không có note_")
                            + "\n"
                        )
            except Exception as exc:
                logger.warning("agent.wiki: digest llm failed: %s", exc)

    with _lock:
        try:
            path.write_text(body, encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "text": f"Không ghi digest: {exc}", "day": day}

    return {
        "ok": True,
        "day": day,
        "path": str(path),
        "text": body,
        "note_count": len(notes),
        "skipped": False,
    }


def digest_due_now() -> bool:
    """True when VN hour >= digest_hour and today's digest file is missing."""
    if not is_enabled() or not digest_enabled():
        return False
    now = _now_vn()
    if now.hour < digest_hour():
        return False
    day = now.strftime("%Y-%m-%d")
    return not digest_path(day).is_file()


def _reset_for_tests(wiki_dir: Path | None = None) -> None:
    global _WIKI_DIR, _NOTES_DIR, _INDEX, _DIGEST_DIR
    with _lock:
        if wiki_dir is not None:
            _WIKI_DIR = Path(wiki_dir)
            _NOTES_DIR = _WIKI_DIR / "notes"
            _DIGEST_DIR = _WIKI_DIR / "digests"
            _INDEX = _WIKI_DIR / "index.md"
