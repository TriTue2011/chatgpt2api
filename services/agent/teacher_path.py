"""Kiểm tra đầu vào (placement) + lộ trình học cá nhân theo từng học sinh.

Tham chiếu sư phạm (từ thực hành & nghiên cứu):

  **Toán** — knowledge-state / mastery + spiral
  - Chẩn đoán theo *mảng kiến thức* (strands), không chỉ 1 điểm tổng
    (tương tự ALEKS knowledge space: biết / chưa biết từng skill).
  - Mastery: mảng < 6/10 → remediate đến ≥7 trước khi nhảy mảng mới.
  - Spiral (Bruner): mảng đã vững vẫn ôn nhẹ (review) để giữ kiến thức.
  - Buổi học: I do → We do → You do + gợi ý bậc thang + CFU cuối buổi.
  - Feedback (Hattie): HS biết đang ở đâu, mục tiêu, và cách thu hẹp khoảng cách.

  **Văn / Tiếng Việt** — kỹ năng ngôn ngữ tuần tự
  - Diagnostic skills: chính tả → dấu câu → từ loại → đọc hiểu → viết đoạn.
  - Nền tảng ngôn ngữ trước; viết đoạn sau (formative loops, không “làm văn mẫu”
    khi còn lỗi chính tả/câu).
  - Lộ trình: remediate skill yếu → practice → checkpoint.

  **Anh** — CEFR multi-skill placement
  - 5 kỹ năng: grammar · listening · speaking · reading · writing.
  - Placement đa kỹ năng → mức Pre-A1…B1+ (ngữ cảnh lớp phổ thông VN).
  - Ưu tiên skill yếu nhất trước, rồi tích hợp communicative (form + meaning).
  - Model LLM riêng từng skill (teacher.english.models.*) khi dạy sâu.

Lưu ĐỘC LẬP theo học sinh (không gộp chung workspace)::

    data/agent/teacher/students/{student_key}/
      profile.json
      placement/{subject}.json      # kết quả placement mới nhất
      placement/history/{id}.json
      roadmap/{subject}.json        # lộ trình hiện tại
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR

_ROOT = Path(DATA_DIR) / "agent" / "teacher" / "students"
_lock_note = None  # file ops are small; rely on atomic write


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def _safe(s: str, n: int = 64) -> str:
    return re.sub(r"[^\w.\-]+", "_", (s or "anon").strip())[:n] or "anon"


def _student_dir(student_key: str) -> Path:
    return _ROOT / _safe(student_key)


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Student profile (độc lập) ───────────────────────────────────────────────


def get_or_create_profile(
    student_key: str,
    *,
    display_name: str = "",
    grade: int = 0,
    notes: str = "",
) -> dict[str, Any]:
    sk = _safe(student_key or "default")
    path = _student_dir(sk) / "profile.json"
    cur = _read_json(path)
    if cur:
        if display_name:
            cur["display_name"] = display_name.strip()[:80]
        if grade and 1 <= int(grade) <= 12:
            cur["grade"] = int(grade)
        if notes:
            cur["notes"] = notes.strip()[:500]
        cur["updated"] = _now()
        _write_json(path, cur)
        return cur
    profile = {
        "student_key": sk,
        "display_name": (display_name or sk).strip()[:80],
        "grade": int(grade) if grade and 1 <= int(grade) <= 12 else 0,
        "notes": (notes or "").strip()[:500],
        "created": _now(),
        "updated": _now(),
        "subjects_tracked": [],
    }
    _write_json(path, profile)
    return profile


def list_students() -> list[dict[str, Any]]:
    _ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    for d in sorted(_ROOT.iterdir() if _ROOT.is_dir() else []):
        if not d.is_dir():
            continue
        p = _read_json(d / "profile.json")
        if not p:
            p = {"student_key": d.name, "display_name": d.name}
        # summary roadmaps / placement
        placements = []
        for sub in ("toan", "van", "anh"):
            pl = _read_json(d / "placement" / f"{sub}.json")
            if pl:
                placements.append({
                    "subject": sub,
                    "level": pl.get("level_label") or pl.get("level"),
                    "score_pct": pl.get("score_pct"),
                    "date": pl.get("submitted") or pl.get("created"),
                })
        roadmaps = []
        for sub in ("toan", "van", "anh"):
            rm = _read_json(d / "roadmap" / f"{sub}.json")
            if rm:
                roadmaps.append({
                    "subject": sub,
                    "focus": rm.get("current_focus"),
                    "steps_done": rm.get("steps_done", 0),
                    "steps_total": len(rm.get("steps") or []),
                })
        rows.append({
            **{k: p.get(k) for k in (
                "student_key", "display_name", "grade", "notes", "updated", "created",
            )},
            "placements": placements,
            "roadmaps": roadmaps,
        })
    return rows


def get_profile(student_key: str) -> Optional[dict[str, Any]]:
    return _read_json(_student_dir(student_key) / "profile.json")


def delete_student(student_key: str, *, wipe_memory: bool = True) -> dict[str, Any]:
    """Xóa toàn bộ hồ sơ độc lập của 1 HS (profile + placement + roadmap).

    Tùy chọn xóa luôn memory/adaptive theo student_key trong các workspace.
    """
    import shutil

    sk = _safe(student_key or "")
    if not sk or sk in {".", ".."}:
        return {"ok": False, "error": "student_key không hợp lệ"}
    d = _student_dir(sk)
    if not d.is_dir():
        return {"ok": False, "error": f"Không thấy học sinh «{sk}»"}
    try:
        shutil.rmtree(d)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}

    cleaned_mem = 0
    cleaned_adapt = 0
    if wipe_memory:
        mem_root = Path(DATA_DIR) / "agent" / "teacher" / "memory"
        if mem_root.is_dir():
            for p in mem_root.glob(f"*/{sk}.json"):
                try:
                    p.unlink(missing_ok=True)
                    cleaned_mem += 1
                except OSError:
                    pass
        adapt_root = Path(DATA_DIR) / "agent" / "teacher" / "classroom" / "adaptive"
        if adapt_root.is_dir():
            for p in adapt_root.glob(f"*/{sk}.json"):
                try:
                    p.unlink(missing_ok=True)
                    cleaned_adapt += 1
                except OSError:
                    pass
    return {
        "ok": True,
        "student_key": sk,
        "removed_dir": str(d),
        "memory_files_removed": cleaned_mem,
        "adaptive_files_removed": cleaned_adapt,
    }


# ── Curriculum strands (diagnostic domains) ─────────────────────────────────

# Toán: mảng kiến thức theo lớp (đơn giản hóa spiral curriculum)
MATH_STRANDS: dict[str, list[dict[str, Any]]] = {
    "1-2": [
        {"id": "cong", "label": "Cộng trong phạm vi 100", "topics": ["cộng", "cộng có nhớ"]},
        {"id": "tru", "label": "Trừ / trừ có mượn", "topics": ["trừ", "trừ có mượn"]},
        {"id": "so_hoc", "label": "Số và so sánh", "topics": ["số", "so sánh"]},
    ],
    "3-5": [
        {"id": "nhan", "label": "Nhân / bảng cửu chương", "topics": ["nhân", "cửu chương"]},
        {"id": "chia", "label": "Chia", "topics": ["chia"]},
        {"id": "cong_tru", "label": "Cộng trừ nâng cao", "topics": ["cộng", "trừ"]},
        {"id": "do_luong", "label": "Đo lường / đồng hồ", "topics": ["độ dài", "đồng hồ"]},
    ],
    "6-9": [
        {"id": "phan_so", "label": "Phân số / số thập phân", "topics": ["phân số", "thập phân"]},
        {"id": "pt", "label": "Phương trình cơ bản", "topics": ["phương trình"]},
        {"id": "hinh", "label": "Hình học cơ bản", "topics": ["hình", "chu vi", "diện tích"]},
        {"id": "ty_le", "label": "Tỷ lệ / phần trăm", "topics": ["phần trăm", "tỷ lệ"]},
    ],
    "10-12": [
        {"id": "ham_so", "label": "Hàm số / đồ thị", "topics": ["hàm số"]},
        {"id": "luong_giac", "label": "Lượng giác cơ bản", "topics": ["lượng giác"]},
        {"id": "tich_phan", "label": "Tích phân / đạo hàm (khung)", "topics": ["đạo hàm", "tích phân"]},
        {"id": "hinh_khong_gian", "label": "Hình không gian", "topics": ["thể tích", "diện tích"]},
    ],
}

VAN_STRANDS = [
    {"id": "chinhta", "label": "Chính tả (hỏi/ngã, ch/tr)", "topics": ["chính tả", "hỏi", "ngã"]},
    {"id": "daucau", "label": "Dấu câu", "topics": ["dấu câu"]},
    {"id": "doc", "label": "Đọc hiểu", "topics": ["đọc hiểu"]},
    {"id": "tuloai", "label": "Từ loại", "topics": ["từ loại"]},
    {"id": "viet", "label": "Viết câu / đoạn", "topics": ["viết", "đoạn văn"]},
]

# Anh: 5 kỹ năng CEFR-aligned
EN_STRANDS = [
    {"id": "grammar", "label": "Grammar (ngữ pháp)", "topics": ["grammar", "present", "past"]},
    {"id": "listening", "label": "Listening (nghe)", "topics": ["listening"]},
    {"id": "speaking", "label": "Speaking (nói)", "topics": ["speaking", "greet"]},
    {"id": "reading", "label": "Reading (đọc)", "topics": ["reading"]},
    {"id": "writing", "label": "Writing (viết)", "topics": ["writing"]},
]


def _math_band(grade: int) -> str:
    g = int(grade or 5)
    if g <= 2:
        return "1-2"
    if g <= 5:
        return "3-5"
    if g <= 9:
        return "6-9"
    return "10-12"


def strands_for(subject: str, grade: int) -> list[dict[str, Any]]:
    sub = (subject or "toan").lower()
    if sub == "van":
        return list(VAN_STRANDS)
    if sub == "anh":
        return list(EN_STRANDS)
    return list(MATH_STRANDS.get(_math_band(grade), MATH_STRANDS["3-5"]))


# ── Placement test ──────────────────────────────────────────────────────────


def start_placement(
    *,
    student_key: str,
    subject: str,
    grade: int = 0,
    display_name: str = "",
    n_per_strand: int = 2,
) -> dict[str, Any]:
    """Tạo đề placement: mỗi strand vài câu (diagnostic multi-domain)."""
    from services.agent import teacher_assess as ta
    from services.agent import teacher_workspace as tw

    sk = _safe(student_key or "default")
    profile = get_or_create_profile(sk, display_name=display_name, grade=grade)
    g = int(grade) if grade and 1 <= int(grade) <= 12 else int(profile.get("grade") or 5)
    if g < 1 or g > 12:
        g = 5
    sub = tw._normalize_subject(subject) or "toan"
    strands = strands_for(sub, g)
    n_ps = max(1, min(int(n_per_strand or 2), 3))

    questions: list[dict[str, Any]] = []
    qid = 0
    for st in strands:
        topics = st.get("topics") or [st["id"]]
        for j in range(n_ps):
            topic = topics[j % len(topics)]
            items = ta._generate_practice_items(
                grade=g, subject=sub, topic=str(topic), n=1, difficulty="medium",
            )
            if not items:
                continue
            item = dict(items[0])
            qid += 1
            item["id"] = f"q{qid}"
            item["strand_id"] = st["id"]
            item["strand_label"] = st["label"]
            item["difficulty"] = "medium"
            questions.append(item)

    pid = uuid.uuid4().hex[:12]
    placement = {
        "id": pid,
        "student_key": sk,
        "subject": sub,
        "grade": g,
        "created": _now(),
        "created_ts": time.time(),
        "status": "open",
        "strands": [{"id": s["id"], "label": s["label"]} for s in strands],
        "questions": questions,
        "n_questions": len(questions),
        "pedagogy": _pedagogy_blurb(sub),
    }
    # temporary open file (until submit)
    path = _student_dir(sk) / "placement" / f"_open_{pid}.json"
    _write_json(path, placement)
    # student-facing: hide answer_hint
    public_q = []
    for q in questions:
        public_q.append({
            "id": q.get("id"),
            "prompt": q.get("prompt"),
            "type": q.get("type"),
            "strand_id": q.get("strand_id"),
            "strand_label": q.get("strand_label"),
        })
    return {
        "ok": True,
        "placement_id": pid,
        "student_key": sk,
        "subject": sub,
        "grade": g,
        "strands": placement["strands"],
        "questions": public_q,
        "n_questions": len(public_q),
        "pedagogy": placement["pedagogy"],
        "instructions": _placement_instructions(sub, g),
    }


def _placement_instructions(subject: str, grade: int) -> str:
    if subject == "anh":
        return (
            f"Kiểm tra đầu vào Tiếng Anh (lớp {grade}, khung CEFR). "
            "Làm hết các câu: ngữ pháp · nghe/nói (viết lời) · đọc · viết. "
            "Không dùng từ điển. Kết quả → lộ trình 5 kỹ năng riêng cho em."
        )
    if subject == "van":
        return (
            f"Kiểm tra đầu vào Tiếng Việt / Ngữ văn (lớp {grade}). "
            "Gồm chính tả, dấu câu, đọc hiểu, từ loại, viết. "
            "Kết quả → lộ trình kỹ năng còn yếu."
        )
    return (
        f"Kiểm tra đầu vào Toán (lớp {grade}). "
        "Gồm các mảng kiến thức (cộng/trừ/nhân/chia… tùy lớp). "
        "Làm từng câu; kết quả → lộ trình ôn theo mảng chưa vững."
    )


# Mô tả phương pháp dạy dùng trong UI / API (tiếng Việt, cho phụ huynh & GV)
PEDAGOGY: dict[str, dict[str, str]] = {
    "toan": {
        "name": "Mastery + spiral theo mảng kiến thức",
        "diagnostic": (
            "Test đầu vào chia theo mảng (cộng/trừ/nhân/chia/phân số… tùy lớp). "
            "Mỗi mảng có điểm riêng — giống chẩn đoán knowledge-state."
        ),
        "path": (
            "Mảng yếu (<6/10) học trước, đạt ≥7 mới sang mảng khác. "
            "Mảng đã vững ôn nhẹ (spiral). Buổi học: I do → We do → You do + CFU."
        ),
        "session": (
            "1) Ôn 2 phút  2) GV làm mẫu  3) Làm cùng  4) Tự làm  "
            "5) Gợi ý bậc thang nếu kẹt  6) 1 câu kiểm tra nhanh (CFU)."
        ),
    },
    "van": {
        "name": "Kỹ năng ngôn ngữ tuần tự (TV/Ngữ văn)",
        "diagnostic": (
            "Chính tả · dấu câu · từ loại · đọc hiểu · viết câu/đoạn — chấm từng skill."
        ),
        "path": (
            "Củng cố nền (chính tả/dấu câu) trước khi viết đoạn dài. "
            "Đọc hiểu gắn chủ đề lớp; viết có rubric rõ."
        ),
        "session": (
            "1) Warm-up chính tả  2) Mẫu câu/đoạn  3) Luyện có scaffold  "
            "4) Tự viết ngắn  5) Sửa theo checklist."
        ),
    },
    "anh": {
        "name": "CEFR multi-skill (form + meaning)",
        "diagnostic": (
            "5 skill: grammar, listening, speaking, reading, writing. "
            "Quy ra mức Pre-A1 → B1+ theo % và lớp."
        ),
        "path": (
            "Skill yếu nhất trước, rồi ghép communicative task. "
            "Grammar gắn ngữ cảnh; speaking/writing có rubric."
        ),
        "session": (
            "1) Input ngắn (nghe/đọc)  2) Notice form  3) Controlled practice  "
            "4) Free production (nói/viết)  5) Feedback 1–2 điểm."
        ),
    },
}


def _pedagogy_blurb(subject: str) -> str:
    p = PEDAGOGY.get(subject) or PEDAGOGY["toan"]
    return f"{p['name']}. {p['diagnostic']} {p['path']}"


def _open_placement_path(student_key: str, placement_id: str) -> Path:
    return _student_dir(student_key) / "placement" / f"_open_{_safe(placement_id, 32)}.json"


def submit_placement(
    placement_id: str,
    answers: dict[str, str],
    *,
    student_key: str = "",
) -> dict[str, Any]:
    """Chấm placement → lưu kết quả + sinh lộ trình cá nhân."""
    from services.agent import teacher_assess as ta

    # find open placement
    sk = _safe(student_key) if student_key else ""
    pl: Optional[dict[str, Any]] = None
    if sk:
        pl = _read_json(_open_placement_path(sk, placement_id))
    if not pl:
        # search all students
        if _ROOT.is_dir():
            for d in _ROOT.iterdir():
                cand = d / "placement" / f"_open_{_safe(placement_id, 32)}.json"
                pl = _read_json(cand)
                if pl:
                    sk = str(pl.get("student_key") or d.name)
                    break
    if not pl:
        return {"ok": False, "error": f"Không thấy đề placement {placement_id} (hết hạn hoặc đã nộp)"}

    sk = str(pl.get("student_key") or sk or "default")
    sub = str(pl.get("subject") or "toan")
    g = int(pl.get("grade") or 5)
    details = []
    by_strand: dict[str, list[dict[str, Any]]] = {}

    for q in pl.get("questions") or []:
        qid = str(q.get("id"))
        ans = str(answers.get(qid) or answers.get(qid.upper()) or "")
        r = ta.grade_answer(
            question=str(q.get("prompt") or ""),
            student_answer=ans,
            answer_hint=str(q.get("answer_hint") or ""),
            subject=sub,
            grade=g,
            use_llm=False,  # placement nhanh, khách quan trước
        )
        sid = str(q.get("strand_id") or "general")
        row = {
            "id": qid,
            "strand_id": sid,
            "strand_label": q.get("strand_label"),
            "score_0_10": r.get("score_0_10"),
            "correct": r.get("correct"),
            "feedback": r.get("feedback"),
            "prompt": q.get("prompt"),
            "answer": ans,
            "answer_hint": q.get("answer_hint"),
        }
        details.append(row)
        by_strand.setdefault(sid, []).append(row)

    strand_scores = []
    weak, strong = [], []
    for sid, rows in by_strand.items():
        avg = sum(int(x.get("score_0_10") or 0) for x in rows) / max(1, len(rows))
        label = next(
            (x.get("strand_label") for x in rows if x.get("strand_label")), sid,
        )
        entry = {
            "strand_id": sid,
            "label": label,
            "score_0_10": round(avg, 1),
            "n": len(rows),
            "mastered": avg >= 7,
        }
        strand_scores.append(entry)
        if avg < 6:
            weak.append(label)
        elif avg >= 8:
            strong.append(label)

    total = sum(int(d.get("score_0_10") or 0) for d in details)
    n = max(1, len(details))
    avg = round(total / n, 1)
    pct = int(round(avg * 10))
    level_label = _level_from_score(sub, g, pct, strand_scores)

    result = {
        "ok": True,
        "id": pl.get("id"),
        "student_key": sk,
        "subject": sub,
        "grade": g,
        "submitted": _now(),
        "submitted_ts": time.time(),
        "score_0_10": avg,
        "score_pct": pct,
        "level_label": level_label,
        "strand_scores": strand_scores,
        "weak_strands": weak,
        "strong_strands": strong,
        "details": details,
        "summary": _placement_summary(sub, avg, pct, level_label, weak, strong),
        "pedagogy": pl.get("pedagogy"),
    }

    # persist latest + history
    _write_json(_student_dir(sk) / "placement" / f"{sub}.json", result)
    _write_json(
        _student_dir(sk) / "placement" / "history" / f"{pl.get('id')}.json", result,
    )
    # remove open
    try:
        _open_placement_path(sk, str(pl.get("id"))).unlink(missing_ok=True)
    except Exception:
        pass

    # update profile subjects
    profile = get_or_create_profile(sk, grade=g)
    tracked = list(profile.get("subjects_tracked") or [])
    if sub not in tracked:
        tracked.append(sub)
    profile["subjects_tracked"] = tracked
    profile["grade"] = g
    _write_json(_student_dir(sk) / "profile.json", profile)

    # also mirror weak/strong into workspace memory (optional link)
    try:
        from services.agent import teacher_workspace as tw
        ws = f"lop{g}-{sub}"
        for w in weak[:5]:
            tw.memory_add(ws, sk, weak_topic=f"[placement] {w}", note=result["summary"][:200])
        for s in strong[:3]:
            tw.memory_add(ws, sk, strong_topic=f"[placement] {s}")
    except Exception:
        pass

    roadmap = build_roadmap(sk, sub, grade=g, placement=result)
    result["roadmap"] = roadmap
    return result


def _level_from_score(
    subject: str, grade: int, pct: int, strand_scores: list[dict],
) -> str:
    if subject == "anh":
        # map % → CEFR-ish for school context
        if pct >= 85:
            return "B1+" if grade >= 9 else "A2+"
        if pct >= 70:
            return "A2–B1" if grade >= 6 else "A2"
        if pct >= 50:
            return "A2" if grade >= 6 else "A1"
        if pct >= 30:
            return "A1"
        return "Pre-A1"
    if pct >= 85:
        return f"Vững lớp {grade}"
    if pct >= 65:
        return f"Đạt lớp {grade} (cần ôn mảng yếu)"
    if pct >= 40:
        return f"Cận lớp {grade} — ưu tiên nền tảng"
    return f"Cần củng cố dưới lớp {grade}"


def _placement_summary(
    subject: str, avg: float, pct: int, level: str,
    weak: list[str], strong: list[str],
) -> str:
    parts = [
        f"Điểm TB {avg}/10 ({pct}%). Mức: {level}.",
    ]
    if weak:
        parts.append("Cần ưu tiên: " + "; ".join(weak) + ".")
    if strong:
        parts.append("Đã vững: " + "; ".join(strong) + ".")
    parts.append("Lộ trình cá nhân đã được tạo — học theo từng bước.")
    return " ".join(parts)


# ── Roadmap ─────────────────────────────────────────────────────────────────


def build_roadmap(
    student_key: str,
    subject: str,
    *,
    grade: int = 0,
    placement: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Sinh lộ trình từ placement (hoặc đọc placement đã lưu)."""
    from services.agent import teacher_workspace as tw

    sk = _safe(student_key)
    sub = tw._normalize_subject(subject) or "toan"
    pl = placement or _read_json(_student_dir(sk) / "placement" / f"{sub}.json")
    profile = get_or_create_profile(sk)
    g = int(grade or (pl or {}).get("grade") or profile.get("grade") or 5)

    steps: list[dict[str, Any]] = []
    # 1) intro
    steps.append({
        "id": "s0",
        "phase": "orientation",
        "title": "Làm quen mục tiêu & quy ước học",
        "description": (
            "Xác nhận lớp–môn, cách nộp bài, khi nào hỏi gợi ý (teacher_hint). "
            "Học sinh hiểu: sai là cơ hội sửa, không bị mắng."
        ),
        "topic": "orientation",
        "skill": "meta",
        "status": "pending",
        "estimated_sessions": 1,
    })

    strand_scores = list((pl or {}).get("strand_scores") or [])
    # sort weak first
    strand_scores_sorted = sorted(
        strand_scores, key=lambda x: float(x.get("score_0_10") or 0),
    )

    if strand_scores_sorted:
        for i, st in enumerate(strand_scores_sorted):
            score = float(st.get("score_0_10") or 0)
            if score >= 8:
                # review light
                steps.append({
                    "id": f"s{i + 1}",
                    "phase": "review",
                    "title": f"Ôn nhanh: {st.get('label')}",
                    "description": "Đã vững — 1 phiên ôn + 3 câu để giữ kiến thức.",
                    "topic": st.get("strand_id"),
                    "skill": st.get("strand_id"),
                    "status": "pending",
                    "priority": "low",
                    "estimated_sessions": 1,
                    "placement_score": score,
                })
            elif score >= 6:
                ped = PEDAGOGY.get(sub) or PEDAGOGY["toan"]
                steps.append({
                    "id": f"s{i + 1}",
                    "phase": "practice",
                    "title": f"Luyện: {st.get('label')}",
                    "description": (
                        "I do → We do → You do; 1 phiên gợi ý bậc thang + "
                        "bài tập 5 câu; CFU cuối buổi."
                    ),
                    "session_recipe": ped.get("session", ""),
                    "topic": st.get("strand_id"),
                    "skill": st.get("strand_id"),
                    "status": "pending",
                    "priority": "medium",
                    "estimated_sessions": 2,
                    "placement_score": score,
                })
            else:
                ped = PEDAGOGY.get(sub) or PEDAGOGY["toan"]
                steps.append({
                    "id": f"s{i + 1}",
                    "phase": "remediate",
                    "title": f"Củng cố nền: {st.get('label')}",
                    "description": (
                        "Quay lại khái niệm cơ bản + ví dụ đời sống; "
                        "hint level 1–3; không nhảy bước. "
                        "Mục tiêu đạt ≥7/10 trước khi sang mảng khác."
                    ),
                    "session_recipe": ped.get("session", ""),
                    "topic": st.get("strand_id"),
                    "skill": st.get("strand_id"),
                    "status": "pending",
                    "priority": "high",
                    "estimated_sessions": 3,
                    "placement_score": score,
                })
    else:
        # no placement yet — default path by subject
        for i, st in enumerate(strands_for(sub, g)):
            steps.append({
                "id": f"s{i + 1}",
                "phase": "learn",
                "title": f"Học: {st['label']}",
                "description": "Chưa có placement — lộ trình mặc định theo chương trình lớp.",
                "topic": st["id"],
                "skill": st["id"],
                "status": "pending",
                "priority": "medium",
                "estimated_sessions": 2,
            })

    # final checkpoint
    steps.append({
        "id": f"s{len(steps)}",
        "phase": "checkpoint",
        "title": "Kiểm tra giữa lộ trình (mini placement)",
        "description": "Làm lại 1 đề ngắn để cập nhật lộ trình.",
        "topic": "checkpoint",
        "skill": "meta",
        "status": "pending",
        "estimated_sessions": 1,
    })

    # reorder: high priority remediate first (already weak-first for scored)
    high = [s for s in steps if s.get("priority") == "high"]
    mid = [s for s in steps if s.get("priority") == "medium"]
    low = [s for s in steps if s.get("priority") == "low"]
    meta = [s for s in steps if s.get("skill") == "meta"]
    ordered = [meta[0]] if meta else []
    ordered += high + mid + low
    ordered += [m for m in meta[1:]]
    for i, s in enumerate(ordered):
        s["id"] = f"s{i}"
        s["order"] = i

    current = next(
        (s for s in ordered if s.get("priority") == "high"),
        ordered[1] if len(ordered) > 1 else ordered[0],
    )

    roadmap = {
        "student_key": sk,
        "subject": sub,
        "grade": g,
        "created": _now(),
        "updated": _now(),
        "source_placement_id": (pl or {}).get("id"),
        "level_label": (pl or {}).get("level_label"),
        "current_focus": current.get("title"),
        "current_step_id": current.get("id"),
        "current_topic": current.get("topic") or current.get("skill") or "",
        "steps": ordered,
        "steps_done": 0,
        "method": _pedagogy_blurb_path(sub),
        "practice_history": [],
    }
    _write_json(_student_dir(sk) / "roadmap" / f"{sub}.json", roadmap)
    return roadmap


def _pedagogy_blurb_path(subject: str) -> str:
    p = PEDAGOGY.get(subject) or PEDAGOGY["toan"]
    return f"{p['name']}: {p['path']}"


def pedagogy_for(subject: str) -> dict[str, str]:
    """API helper — phương pháp dạy theo môn (cho UI / phụ huynh)."""
    from services.agent import teacher_workspace as tw
    sub = tw._normalize_subject(subject) or "toan"
    return dict(PEDAGOGY.get(sub) or PEDAGOGY["toan"])


def get_roadmap(student_key: str, subject: str) -> Optional[dict[str, Any]]:
    from services.agent import teacher_workspace as tw
    sub = tw._normalize_subject(subject) or "toan"
    return _read_json(_student_dir(student_key) / "roadmap" / f"{sub}.json")


def get_placement(student_key: str, subject: str) -> Optional[dict[str, Any]]:
    from services.agent import teacher_workspace as tw
    sub = tw._normalize_subject(subject) or "toan"
    return _read_json(_student_dir(student_key) / "placement" / f"{sub}.json")


def advance_roadmap_step(
    student_key: str, subject: str, step_id: str, *, done: bool = True,
) -> dict[str, Any]:
    rm = get_roadmap(student_key, subject)
    if not rm:
        return {"ok": False, "error": "Chưa có lộ trình — chạy placement trước."}
    steps = list(rm.get("steps") or [])
    found = False
    for s in steps:
        if s.get("id") == step_id:
            s["status"] = "done" if done else "pending"
            if done:
                s["done_at"] = _now()
            found = True
            break
    if not found:
        return {"ok": False, "error": f"Không thấy bước {step_id}"}
    done_n = sum(1 for s in steps if s.get("status") == "done")
    rm["steps_done"] = done_n
    # next pending
    nxt = next((s for s in steps if s.get("status") != "done"), None)
    if nxt:
        rm["current_step_id"] = nxt.get("id")
        rm["current_focus"] = nxt.get("title")
        rm["current_topic"] = nxt.get("topic") or nxt.get("skill") or ""
    else:
        rm["current_focus"] = "Hoàn thành lộ trình hiện tại"
        rm["current_topic"] = ""
        rm["current_step_id"] = ""
    rm["updated"] = _now()
    from services.agent import teacher_workspace as tw
    sub = tw._normalize_subject(subject) or "toan"
    _write_json(_student_dir(student_key) / "roadmap" / f"{sub}.json", rm)
    return {"ok": True, "roadmap": rm}


def current_focus(
    student_key: str,
    subject: str,
    *,
    grade: int = 0,
    ensure: bool = False,
) -> dict[str, Any]:
    """Chủ đề đang học theo lộ trình (để sinh buổi học / bài tập).

    Trả về::
        ok, topic, title, step_id, phase, skill, grade, source
    """
    from services.agent import teacher_workspace as tw

    sk = _safe(student_key or "default")
    sub = tw._normalize_subject(subject) or "toan"
    rm = get_roadmap(sk, sub)
    if not rm and ensure:
        pl = get_placement(sk, sub)
        g = int(grade or (pl or {}).get("grade") or 0)
        if not g:
            prof = get_profile(sk) or {}
            g = int(prof.get("grade") or 5)
        rm = build_roadmap(sk, sub, grade=g, placement=pl)
    if not rm:
        return {
            "ok": False,
            "error": "Chưa có lộ trình — làm test đầu vào trước.",
            "topic": "",
            "title": "",
            "step_id": "",
            "source": "none",
        }
    steps = list(rm.get("steps") or [])
    step = None
    sid = str(rm.get("current_step_id") or "")
    if sid:
        step = next((s for s in steps if s.get("id") == sid), None)
    if not step:
        step = next((s for s in steps if s.get("status") != "done"), None)
    if not step and steps:
        step = steps[-1]
    if not step:
        return {
            "ok": False,
            "error": "Lộ trình trống",
            "topic": "",
            "title": "",
            "step_id": "",
            "source": "roadmap_empty",
        }
    # meta steps (orientation/checkpoint) → next content step if available
    if step.get("skill") == "meta" or step.get("phase") in ("orientation", "checkpoint"):
        alt = next(
            (
                s for s in steps
                if s.get("status") != "done"
                and s.get("skill") != "meta"
                and s.get("phase") not in ("orientation", "checkpoint")
            ),
            None,
        )
        if alt:
            step = alt
    topic = str(
        step.get("topic") or step.get("skill") or rm.get("current_topic") or ""
    ).strip()
    title = str(step.get("title") or rm.get("current_focus") or topic)
    if not topic or topic in ("orientation", "checkpoint", "meta"):
        # fallback: strip phase prefix from title
        topic = re.sub(
            r"^(Củng cố nền|Luyện|Ôn nhanh|Học):\s*",
            "",
            title,
            flags=re.I,
        ).strip() or topic
    return {
        "ok": True,
        "topic": topic,
        "title": title,
        "step_id": str(step.get("id") or ""),
        "phase": str(step.get("phase") or ""),
        "skill": str(step.get("skill") or ""),
        "priority": step.get("priority"),
        "session_recipe": step.get("session_recipe") or "",
        "grade": int(rm.get("grade") or grade or 5),
        "subject": sub,
        "student_key": sk,
        "current_focus": rm.get("current_focus"),
        "source": "roadmap",
        "roadmap_steps_done": rm.get("steps_done", 0),
        "roadmap_steps_total": len(steps),
    }


def apply_practice_result(
    student_key: str,
    subject: str,
    *,
    average_0_10: float,
    topic: str = "",
    step_id: str = "",
    assignment_id: str = "",
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Sau mỗi lần làm bài: điều chỉnh lộ trình cho phù hợp.

    Quy tắc:
      - TB ≥ 7.5 trên bước hiện tại → đánh dấu xong, chuyển focus bước kế
      - 5 ≤ TB < 7.5 → giữ bước, +1 buổi luyện, ghi lịch sử
      - TB < 5 → giữ bước, nâng priority high, +2 buổi, có thể chèn bước củng cố
    """
    from services.agent import teacher_workspace as tw

    sk = _safe(student_key or "default")
    sub = tw._normalize_subject(subject) or "toan"
    rm = get_roadmap(sk, sub)
    if not rm:
        # auto-create minimal roadmap if HS already has profile
        g = 0
        prof = get_profile(sk) or {}
        g = int(prof.get("grade") or 5)
        rm = build_roadmap(sk, sub, grade=g)

    steps = list(rm.get("steps") or [])
    sid = (step_id or rm.get("current_step_id") or "").strip()
    step = next((s for s in steps if s.get("id") == sid), None) if sid else None
    if not step:
        # match by topic
        tnorm = (topic or "").strip().lower()
        if tnorm:
            step = next(
                (
                    s for s in steps
                    if s.get("status") != "done"
                    and (
                        str(s.get("topic") or "").lower() == tnorm
                        or str(s.get("skill") or "").lower() == tnorm
                        or tnorm in str(s.get("title") or "").lower()
                    )
                ),
                None,
            )
    if not step:
        step = next((s for s in steps if s.get("status") != "done"), None)

    avg = float(average_0_10 or 0)
    action = "hold"
    message = ""
    old_focus = rm.get("current_focus")

    hist = list(rm.get("practice_history") or [])
    hist.append({
        "ts": _now(),
        "average_0_10": avg,
        "topic": (topic or "")[:80],
        "step_id": (step or {}).get("id"),
        "assignment_id": (assignment_id or "")[:32],
        "n_items": len(details or []),
    })
    rm["practice_history"] = hist[-40:]

    if not step:
        message = "Đã ghi kết quả nhưng không khớp bước lộ trình."
        action = "logged"
    elif avg >= 7.5:
        # master → advance
        step["status"] = "done"
        step["done_at"] = _now()
        step["last_score"] = avg
        action = "advance"
        message = (
            f"Đạt {avg}/10 — hoàn thành «{step.get('title')}», "
            "chuyển sang bước kế tiếp."
        )
        # next pending content step
        nxt = next((s for s in steps if s.get("status") != "done"), None)
        if nxt:
            rm["current_step_id"] = nxt.get("id")
            rm["current_focus"] = nxt.get("title")
            rm["current_topic"] = nxt.get("topic") or nxt.get("skill") or ""
        else:
            rm["current_step_id"] = ""
            rm["current_focus"] = "Hoàn thành lộ trình — có thể placement lại"
            rm["current_topic"] = ""
    elif avg >= 5.0:
        step["last_score"] = avg
        step["status"] = "in_progress"
        est = int(step.get("estimated_sessions") or 2)
        step["estimated_sessions"] = min(est + 1, 8)
        attempts = int(step.get("attempts") or 0) + 1
        step["attempts"] = attempts
        action = "practice_more"
        message = (
            f"Đạt {avg}/10 — cần luyện thêm «{step.get('title')}» "
            f"(≈{step['estimated_sessions']} buổi, lần {attempts})."
        )
        rm["current_step_id"] = step.get("id")
        rm["current_focus"] = step.get("title")
        rm["current_topic"] = step.get("topic") or step.get("skill") or ""
    else:
        step["last_score"] = avg
        step["status"] = "in_progress"
        step["priority"] = "high"
        step["phase"] = "remediate"
        est = int(step.get("estimated_sessions") or 2)
        step["estimated_sessions"] = min(est + 2, 10)
        attempts = int(step.get("attempts") or 0) + 1
        step["attempts"] = attempts
        action = "remediate"
        message = (
            f"Đạt {avg}/10 — quay lại củng cố «{step.get('title')}» "
            f"(ưu tiên cao, ≈{step['estimated_sessions']} buổi)."
        )
        # insert extra scaffold step once if struggling repeatedly
        if attempts >= 2 and not step.get("scaffold_added"):
            step["scaffold_added"] = True
            insert_at = next(
                (i for i, s in enumerate(steps) if s.get("id") == step.get("id")),
                0,
            )
            scaffold = {
                "id": f"sc_{step.get('id')}_{int(time.time()) % 10000}",
                "phase": "remediate",
                "title": f"Nền tảng trước: {step.get('title')}",
                "description": (
                    "Bước chèn sau khi làm bài yếu: ví dụ đời sống + "
                    "hint level 1–2, 3–4 câu rất dễ trước khi quay lại bài chính."
                ),
                "topic": step.get("topic") or step.get("skill"),
                "skill": step.get("skill"),
                "status": "pending",
                "priority": "high",
                "estimated_sessions": 2,
                "scaffold_for": step.get("id"),
            }
            steps.insert(insert_at, scaffold)
            rm["current_step_id"] = scaffold["id"]
            rm["current_focus"] = scaffold["title"]
            rm["current_topic"] = scaffold.get("topic") or ""
            message += " Đã chèn bước nền tảng ngắn."
        else:
            rm["current_step_id"] = step.get("id")
            rm["current_focus"] = step.get("title")
            rm["current_topic"] = step.get("topic") or step.get("skill") or ""

    # re-number order only (keep ids)
    for i, s in enumerate(steps):
        s["order"] = i
    rm["steps"] = steps
    rm["steps_done"] = sum(1 for s in steps if s.get("status") == "done")
    rm["updated"] = _now()
    rm["last_practice"] = {
        "ts": _now(),
        "average_0_10": avg,
        "action": action,
        "message": message,
        "old_focus": old_focus,
        "new_focus": rm.get("current_focus"),
    }
    _write_json(_student_dir(sk) / "roadmap" / f"{sub}.json", rm)

    # mirror into workspace memory for PH dashboard
    try:
        g = int(rm.get("grade") or 5)
        ws = f"lop{g}-{sub}"
        if avg < 6:
            tw.memory_add(
                ws, sk,
                weak_topic=f"[lộ trình] {rm.get('current_focus')}",
                note=message[:200],
            )
        elif avg >= 8:
            tw.memory_add(
                ws, sk,
                strong_topic=f"[lộ trình] {old_focus or topic}",
                note=message[:200],
            )
        else:
            tw.memory_add(ws, sk, note=message[:200])
    except Exception:
        pass

    return {
        "ok": True,
        "action": action,
        "message": message,
        "roadmap": rm,
        "average_0_10": avg,
        "old_focus": old_focus,
        "new_focus": rm.get("current_focus"),
        "current_topic": rm.get("current_topic"),
    }


def student_dashboard(student_key: str) -> dict[str, Any]:
    """Tổng hợp 1 học sinh: profile + placement + roadmap mọi môn."""
    sk = _safe(student_key)
    profile = get_or_create_profile(sk) if sk else None
    if not profile and sk:
        profile = get_profile(sk)
    out = {
        "ok": True,
        "profile": profile or {"student_key": sk},
        "by_subject": {},
    }
    for sub in ("toan", "van", "anh"):
        rm = get_roadmap(sk, sub)
        pl = get_placement(sk, sub)
        focus = None
        if rm:
            focus = {
                "title": rm.get("current_focus"),
                "topic": rm.get("current_topic"),
                "step_id": rm.get("current_step_id"),
                "steps_done": rm.get("steps_done", 0),
                "steps_total": len(rm.get("steps") or []),
                "last_practice": rm.get("last_practice"),
                "level_label": rm.get("level_label") or (pl or {}).get("level_label"),
            }
        out["by_subject"][sub] = {
            "placement": pl,
            "roadmap": rm,
            "focus": focus,
        }
    return out
