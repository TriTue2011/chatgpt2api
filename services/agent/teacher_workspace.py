"""Workspace + KB SGK (Toán · Văn · Anh) — lớp 1–12 (tiểu học · THCS · THPT).

Layout (volume, seed 1 lần từ package)::

    data/agent/teacher/
      sgk/lop{1..12}/{toan,van,anh}.md
      workspaces.json
      memory/{workspace}/{student}.json
      imports/...

Retrieval: chunk theo ``##``, chấm điểm từ khoá (offline).
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR

logger = logging.getLogger(__name__)

SUBJECTS = ("toan", "van", "anh")
SUBJECT_LABEL = {"toan": "Toán", "van": "Ngữ văn / TV", "anh": "Tiếng Anh"}
# Tiểu học 1–5 · THCS 6–9 · THPT 10–12
GRADES = tuple(range(1, 13))


def level_of(grade: int) -> str:
    if grade <= 5:
        return "tieu_hoc"
    if grade <= 9:
        return "thcs"
    return "thpt"


def level_label(grade: int) -> str:
    return {"tieu_hoc": "Tiểu học", "thcs": "THCS", "thpt": "THPT"}.get(
        level_of(grade), "")

_ROOT = Path(DATA_DIR) / "agent" / "teacher"
_SGK = _ROOT / "sgk"
_WS_PATH = _ROOT / "workspaces.json"
_DEFAULTS = Path(__file__).with_name("teacher_default")
_lock = threading.RLock()
_seeded = False

_HEADING = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_WORD = re.compile(r"[0-9A-Za-zÀ-ỹà-ỹ]+", re.UNICODE)


@dataclass
class Chunk:
    grade: int
    subject: str
    title: str
    text: str
    source: str

    def label(self) -> str:
        return f"Lớp {self.grade} · {SUBJECT_LABEL.get(self.subject, self.subject)} · {self.title}"


def _ensure_seeded() -> None:
    global _seeded
    if _seeded:
        return
    with _lock:
        if _seeded:
            return
        try:
            _SGK.mkdir(parents=True, exist_ok=True)
            src_sgk = _DEFAULTS / "sgk"
            if src_sgk.is_dir():
                for g in GRADES:
                    for sub in SUBJECTS:
                        rel = Path(f"lop{g}") / f"{sub}.md"
                        dest = _SGK / rel
                        src = src_sgk / rel
                        if dest.exists() or not src.is_file():
                            continue
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dest)
                        logger.info("teacher.sgk: seeded %s", rel)
            # Seed / merge workspaces (bổ sung lớp 6–12 nếu file cũ chỉ có 1–5)
            defaults = _default_workspaces()
            if not _WS_PATH.exists():
                _WS_PATH.write_text(
                    json.dumps(defaults, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info("teacher.workspaces: seeded defaults")
            else:
                try:
                    cur = json.loads(_WS_PATH.read_text(encoding="utf-8"))
                    if not isinstance(cur, dict):
                        cur = {}
                    added = 0
                    for k, v in defaults.items():
                        if k not in cur:
                            cur[k] = v
                            added += 1
                    if added:
                        _WS_PATH.write_text(
                            json.dumps(cur, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        logger.info("teacher.workspaces: merged %d new", added)
                except Exception as exc:
                    logger.warning("teacher.workspaces merge: %s", exc)
        except Exception as exc:
            logger.warning("teacher seed failed: %s", exc)
        _seeded = True


def _default_workspaces() -> dict[str, dict[str, Any]]:
    """36 workspace: mỗi (lớp 1–12 × môn)."""
    out: dict[str, dict[str, Any]] = {}
    for g in GRADES:
        for sub in SUBJECTS:
            wid = f"lop{g}-{sub}"
            out[wid] = {
                "id": wid,
                "name": f"Lớp {g} ({level_label(g)}) · {SUBJECT_LABEL[sub]}",
                "grade": g,
                "level": level_of(g),
                "subjects": [sub],
                "description": f"SGK {level_label(g)} lớp {g} — {SUBJECT_LABEL[sub]}",
            }
    return out


def list_workspaces() -> list[dict[str, Any]]:
    _ensure_seeded()
    try:
        data = json.loads(_WS_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = _default_workspaces()
    if not isinstance(data, dict):
        data = {}
    rows = [v for v in data.values() if isinstance(v, dict)]
    rows.sort(key=lambda r: (int(r.get("grade") or 0), str(r.get("subjects") or [""])[0]))
    return rows


def get_workspace(workspace_id: str) -> Optional[dict[str, Any]]:
    wid = str(workspace_id or "").strip()
    if not wid:
        return None
    for w in list_workspaces():
        if str(w.get("id")) == wid:
            return w
    return None


def save_workspaces(rows: list[dict[str, Any]]) -> None:
    """Ghi lại workspaces từ Settings (admin)."""
    _ensure_seeded()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        wid = str(r.get("id") or "").strip()
        if not wid:
            continue
        grade = int(r.get("grade") or 0)
        subjects = [str(s).strip() for s in (r.get("subjects") or []) if str(s).strip() in SUBJECTS]
        if grade not in GRADES or not subjects:
            continue
        out[wid] = {
            "id": wid,
            "name": str(r.get("name") or wid).strip(),
            "grade": grade,
            "subjects": subjects,
            "description": str(r.get("description") or "").strip(),
        }
    with _lock:
        _WS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _WS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_chunks(grade: int | None = None, subject: str | None = None) -> list[Chunk]:
    _ensure_seeded()
    chunks: list[Chunk] = []
    grades = [grade] if grade in GRADES else list(GRADES)
    subjects = [subject] if subject in SUBJECTS else list(SUBJECTS)
    for g in grades:
        for sub in subjects:
            path = _SGK / f"lop{g}" / f"{sub}.md"
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            parts = _HEADING.split(text)
            # parts: [preamble, title1, body1, title2, body2, ...]
            if len(parts) < 3:
                body = text.strip()
                if body:
                    chunks.append(Chunk(g, sub, path.stem, body, path.name))
                continue
            # preamble ignored if no ##
            i = 1
            while i + 1 < len(parts):
                title = parts[i].strip()
                body = parts[i + 1].strip()
                if body:
                    chunks.append(Chunk(g, sub, title or "Mục", body, f"lop{g}/{sub}.md"))
                i += 2
    return chunks


def _tokens(s: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(s or "") if len(w) > 1}


def _score(query: str, chunk: Chunk) -> float:
    q = _tokens(query)
    if not q:
        return 0.0
    blob = _tokens(chunk.title + " " + chunk.text)
    if not blob:
        return 0.0
    hit = q & blob
    # title hits weight more
    title_hit = q & _tokens(chunk.title)
    return len(hit) + 1.5 * len(title_hit) + (0.1 if chunk.grade else 0)


def search_sgk(
    query: str,
    *,
    grade: int | None = None,
    subject: str | None = None,
    workspace_id: str = "",
    top_k: int = 4,
) -> str:
    """Tìm đoạn SGK liên quan. Trả markdown có cite lớp–môn–mục."""
    q = (query or "").strip()
    if not q:
        return "Cần câu hỏi / từ khoá để tìm trong SGK tiểu học."

    g = grade
    sub = (subject or "").strip().lower() or None
    if sub == "tieng_viet" or sub == "tiếng việt":
        sub = "van"
    if sub == "tieng_anh" or sub == "english":
        sub = "anh"
    if sub and sub not in SUBJECTS:
        sub = None

    ws = get_workspace(workspace_id) if workspace_id else None
    if ws:
        g = int(ws.get("grade") or g or 0) or None
        subs = ws.get("subjects") or []
        if len(subs) == 1:
            sub = str(subs[0])
        elif subs and sub not in subs:
            # workspace multi-subject: keep sub if in list else search all workspace subjects
            if sub not in subs:
                sub = None

    chunks = _load_chunks(g if g in GRADES else None, sub if sub in SUBJECTS else None)
    if ws and ws.get("subjects") and sub is None:
        allow = set(ws["subjects"])
        chunks = [c for c in chunks if c.subject in allow]
        if g in GRADES:
            chunks = [c for c in chunks if c.grade == g]

    if not chunks:
        return (
            "Chưa có tài liệu SGK khớp (seed data/agent/teacher/sgk). "
            "Kiểm tra Settings → Giáo viên hoặc chạy seed."
        )

    ranked = sorted(chunks, key=lambda c: _score(q, c), reverse=True)
    top_k = max(1, min(int(top_k or 4), 8))
    picked = [c for c in ranked if _score(q, c) > 0][:top_k]
    if not picked:
        # fallback: still return best even if score 0
        picked = ranked[: min(2, top_k)]

    lines = [f"**KB SGK tiểu học** (truy vấn: {q[:80]})", ""]
    for i, c in enumerate(picked, 1):
        body = c.text.strip()
        if len(body) > 900:
            body = body[:900] + "…"
        lines.append(f"### {i}. {c.label()}")
        lines.append(f"_Nguồn: `{c.source}`_")
        lines.append(body)
        lines.append("")
    lines.append(
        "_Dùng làm gợi ý giảng dạy — kiểm tra lại nếu cần đúng từng trang SGK năm học cụ thể._"
    )
    return "\n".join(lines)


def list_sgk_index() -> str:
    """Liệt kê file SGK đã seed."""
    _ensure_seeded()
    lines = ["**SGK tiểu học (Toán · Văn · Anh)**", ""]
    for g in GRADES:
        row = []
        for sub in SUBJECTS:
            p = _SGK / f"lop{g}" / f"{sub}.md"
            row.append(f"{SUBJECT_LABEL[sub]}{'✓' if p.is_file() else '✗'}")
        lines.append(f"- Lớp {g}: " + ", ".join(row))
    lines.append("")
    lines.append(f"Thư mục: `{_SGK}`")
    return "\n".join(lines)


def status_public() -> dict[str, Any]:
    _ensure_seeded()
    files = 0
    for g in GRADES:
        for sub in SUBJECTS:
            if (_SGK / f"lop{g}" / f"{sub}.md").is_file():
                files += 1
    imports_dir = _ROOT / "imports"
    n_imp = 0
    try:
        n_imp = len(list(imports_dir.glob("**/*"))) if imports_dir.is_dir() else 0
    except Exception:
        pass
    mem_dir = _ROOT / "memory"
    n_mem = 0
    try:
        n_mem = len(list(mem_dir.glob("**/*.json"))) if mem_dir.is_dir() else 0
    except Exception:
        pass
    return {
        "sgk_files": files,
        "sgk_expected": len(GRADES) * len(SUBJECTS),
        "workspaces": len(list_workspaces()),
        "subjects": list(SUBJECTS),
        "grades": list(GRADES),
        "path": str(_SGK),
        "import_files": n_imp,
        "student_memory_files": n_mem,
    }


# ── Import PDF SGK → markdown lớp–môn ───────────────────────────────────────


def _normalize_subject(subject: str) -> str | None:
    s = (subject or "").strip().lower()
    aliases = {
        "toan": "toan", "toán": "toan", "math": "toan",
        "van": "van", "văn": "van", "tieng_viet": "van", "tiếng việt": "van",
        "tv": "van", "ngu_van": "van",
        "anh": "anh", "english": "anh", "tieng_anh": "anh", "tiếng anh": "anh", "en": "anh",
    }
    return aliases.get(s) or (s if s in SUBJECTS else None)


def _md_from_pdf_text(raw: str, *, title: str) -> str:
    """Làm sạch text PDF → markdown có ## (tách theo trang / dòng in hoa ngắn)."""
    t = (raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not t:
        return ""
    # Tách theo phân trang OCR (---) nếu có.
    pages = re.split(r"\n\s*---\s*\n", t)
    parts: list[str] = [f"# {title}", ""]
    for pi, page in enumerate(pages):
        page = page.strip()
        if not page:
            continue
        lines = page.split("\n")
        buf: list[str] = []
        for ln in lines:
            s = ln.strip()
            if not s:
                if buf:
                    parts.append(" ".join(buf))
                    buf = []
                continue
            # Dòng ngắn + (toàn hoa hoặc kết thúc :) → coi heading
            if len(s) < 80 and (
                s.isupper()
                or s.endswith(":")
                or re.match(r"^(Bài|Chương|Phần|Unit|Lesson)\b", s, re.I)
            ):
                if buf:
                    parts.append(" ".join(buf))
                    buf = []
                parts.append(f"## {s.rstrip(':')}")
                parts.append("")
            else:
                buf.append(s)
        if buf:
            parts.append(" ".join(buf))
            parts.append("")
        if len(pages) > 1 and pi < len(pages) - 1:
            parts.append(f"## Trang {pi + 2}")
            parts.append("")
    # Đảm bảo có ít nhất một ## để search chunk
    body = "\n".join(parts).strip()
    if "## " not in body:
        body = f"# {title}\n\n## Nội dung nhập từ PDF\n\n{t[:50000]}"
    return body + "\n"


def import_sgk_pdf(
    pdf_path: str | Path,
    *,
    grade: int,
    subject: str,
    mode: str = "append",
    title: str = "",
    source_name: str = "",
) -> dict[str, Any]:
    """Import 1 file PDF SGK → data/agent/teacher/sgk/lop{N}/{mon}.md.

    mode:
      - append  — nối vào file lớp–môn (giữ seed + import cũ)
      - replace — ghi đè toàn bộ file lớp–môn bằng nội dung PDF

    Trả {ok, path, chars, mode, grade, subject, error}.
    """
    _ensure_seeded()
    g = int(grade)
    sub = _normalize_subject(subject)
    if g not in GRADES:
        return {"ok": False, "error": f"grade phải 1–12, nhận {grade}"}
    if not sub:
        return {"ok": False, "error": f"subject phải toan|van|anh, nhận {subject}"}
    path = Path(pdf_path)
    if not path.is_file():
        return {"ok": False, "error": f"không thấy file PDF: {path}"}

    mode = (mode or "append").strip().lower()
    if mode not in {"append", "replace"}:
        mode = "append"

    # Trích text/markdown (PDF số hoặc scan OCR).
    try:
        from services.pdf_intent import extract_markdown
        raw = extract_markdown(str(path))
    except Exception as exc:
        return {"ok": False, "error": f"trích PDF lỗi: {exc}"}
    if not (raw or "").strip():
        return {"ok": False, "error": "PDF không trích được chữ (scan cần OCR/gateway vision)"}

    src = source_name or path.name
    head = title.strip() or f"SGK lớp {g} · {SUBJECT_LABEL[sub]} · {src}"
    md = _md_from_pdf_text(raw, title=head)
    stamp = __import__("time").strftime("%Y-%m-%d %H:%M")
    banner = f"\n\n<!-- import {stamp} from {src} mode={mode} -->\n\n"

    dest = _SGK / f"lop{g}" / f"{sub}.md"
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Lưu bản PDF gốc (audit).
    imp_dir = _ROOT / "imports" / f"lop{g}" / sub
    imp_dir.mkdir(parents=True, exist_ok=True)
    try:
        safe = re.sub(r"[^\w.\-]+", "_", src)[:80]
        shutil.copy2(path, imp_dir / f"{stamp.replace(':', '').replace(' ', '_')}_{safe}")
    except Exception as exc:
        logger.warning("teacher import: copy pdf failed: %s", exc)

    with _lock:
        if mode == "replace" or not dest.exists():
            dest.write_text(md, encoding="utf-8")
        else:
            old = dest.read_text(encoding="utf-8")
            dest.write_text(old.rstrip() + banner + md, encoding="utf-8")

    return {
        "ok": True,
        "path": str(dest),
        "chars": len(md),
        "mode": mode,
        "grade": g,
        "subject": sub,
        "workspace": f"lop{g}-{sub}",
        "source": src,
    }


def import_sgk_bytes(
    data: bytes,
    filename: str,
    *,
    grade: int,
    subject: str,
    mode: str = "append",
    title: str = "",
) -> dict[str, Any]:
    """Import từ bytes upload (ghi temp rồi gọi import_sgk_pdf)."""
    import tempfile
    import os

    if not data:
        return {"ok": False, "error": "file rỗng"}
    suffix = ".pdf" if not str(filename).lower().endswith(".pdf") else ""
    fd, tmp = tempfile.mkstemp(suffix=suffix or ".pdf")
    try:
        os.write(fd, data)
        os.close(fd)
        return import_sgk_pdf(
            tmp, grade=grade, subject=subject, mode=mode,
            title=title, source_name=filename or "upload.pdf",
        )
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


# ── Memory học sinh theo workspace ───────────────────────────────────────────


def _mem_path(workspace_id: str, student_key: str) -> Path:
    ws = re.sub(r"[^\w.\-]+", "_", (workspace_id or "general").strip())[:64]
    st = re.sub(r"[^\w.\-]+", "_", (student_key or "anon").strip())[:64]
    return _ROOT / "memory" / ws / f"{st}.json"


def _load_mem(workspace_id: str, student_key: str) -> dict[str, Any]:
    p = _mem_path(workspace_id, student_key)
    if not p.is_file():
        return {
            "workspace_id": workspace_id,
            "student_key": student_key,
            "weak_topics": [],
            "strong_topics": [],
            "notes": [],
            "updated": "",
        }
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"workspace_id": workspace_id, "student_key": student_key, "notes": []}


def _save_mem(data: dict[str, Any]) -> None:
    import time
    ws = str(data.get("workspace_id") or "general")
    st = str(data.get("student_key") or "anon")
    p = _mem_path(ws, st)
    p.parent.mkdir(parents=True, exist_ok=True)
    data["updated"] = time.strftime("%Y-%m-%d %H:%M")
    with _lock:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def memory_get(workspace_id: str, student_key: str = "") -> str:
    """Đọc memory học sinh trong workspace (markdown)."""
    _ensure_seeded()
    wid = (workspace_id or "").strip()
    if not wid:
        return "Cần workspace_id (vd lop2-toan)."
    sk = (student_key or "default").strip() or "default"
    m = _load_mem(wid, sk)
    ws = get_workspace(wid)
    title = (ws or {}).get("name") or wid
    lines = [
        f"**Memory học sinh** · {title}",
        f"Học sinh key: `{sk}`",
        f"Cập nhật: {m.get('updated') or '(chưa có)'}",
        "",
    ]
    weak = m.get("weak_topics") or []
    strong = m.get("strong_topics") or []
    notes = m.get("notes") or []
    if weak:
        lines.append("**Điểm yếu / cần ôn:**")
        lines.extend(f"- {x}" for x in weak[-20:])
        lines.append("")
    if strong:
        lines.append("**Đã vững:**")
        lines.extend(f"- {x}" for x in strong[-15:])
        lines.append("")
    if notes:
        lines.append("**Ghi chú:**")
        for n in notes[-15:]:
            if isinstance(n, dict):
                lines.append(f"- [{n.get('ts', '')}] {n.get('text', '')}")
            else:
                lines.append(f"- {n}")
    if not weak and not strong and not notes:
        lines.append("_Chưa có ghi nhận — sau buổi học dùng teacher_memory op=add._")
    return "\n".join(lines)


def memory_add(
    workspace_id: str,
    student_key: str = "",
    *,
    note: str = "",
    weak_topic: str = "",
    strong_topic: str = "",
) -> str:
    """Thêm ghi chú / điểm yếu / điểm mạnh cho học sinh trong workspace."""
    import time
    _ensure_seeded()
    wid = (workspace_id or "").strip()
    if not wid:
        return "Cần workspace_id (vd lop3-van)."
    if not get_workspace(wid) and not re.match(
        r"^lop([1-9]|1[0-2])-(toan|van|anh)$", wid
    ):
        if not re.match(r"^lop([1-9]|1[0-2])-", wid):
            return f"Workspace `{wid}` không hợp lệ. Dùng list_teacher_workspaces."
    sk = (student_key or "default").strip() or "default"
    m = _load_mem(wid, sk)
    m["workspace_id"] = wid
    m["student_key"] = sk
    if weak_topic.strip():
        weak = list(m.get("weak_topics") or [])
        t = weak_topic.strip()
        if t not in weak:
            weak.append(t)
        m["weak_topics"] = weak[-40:]
    if strong_topic.strip():
        strong = list(m.get("strong_topics") or [])
        t = strong_topic.strip()
        if t not in strong:
            strong.append(t)
        m["strong_topics"] = strong[-40:]
    if note.strip():
        notes = list(m.get("notes") or [])
        notes.append({"ts": time.strftime("%Y-%m-%d %H:%M"), "text": note.strip()[:500]})
        m["notes"] = notes[-50:]
    if not (weak_topic or strong_topic or note):
        return "Cần note và/hoặc weak_topic / strong_topic."
    _save_mem(m)
    return memory_get(wid, sk)
