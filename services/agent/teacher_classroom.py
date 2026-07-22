"""Lớp học web: bài giảng (text+TTS), giao bài, nộp bài, chấm, adaptive.

Lưu tại data/agent/teacher/classroom/::

    lessons/{id}.json
    assignments/{id}.json
    submissions/{assignment_id}/{student}.json
    adaptive/{workspace}/{student}.json
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR

_ROOT = Path(DATA_DIR) / "agent" / "teacher" / "classroom"
_LESSONS = _ROOT / "lessons"
_ASSIGN = _ROOT / "assignments"
_SUBS = _ROOT / "submissions"
_ADAPT = _ROOT / "adaptive"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def _week_key(ts: float | None = None) -> str:
    """ISO week id YYYY-Www."""
    t = time.localtime(ts if ts is not None else time.time())
    return time.strftime("%G-W%V", t)


def _safe(s: str, n: int = 64) -> str:
    return re.sub(r"[^\w.\-]+", "_", (s or "x").strip())[:n] or "x"


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Lessons (text + TTS script) ─────────────────────────────────────────────


def create_lesson(
    *,
    title: str,
    body_text: str,
    tts_script: str = "",
    grade: int = 5,
    subject: str = "toan",
    workspace_id: str = "",
    student_key: str = "",
) -> dict[str, Any]:
    from services.agent import teacher as teach
    from services.agent import teacher_workspace as tw

    lid = uuid.uuid4().hex[:12]
    sub = tw._normalize_subject(subject) or "toan"
    g = int(grade) if int(grade) in tw.GRADES else 5
    tts = (tts_script or "").strip() or teach.verbalize_for_tts(body_text[:600])
    lesson = {
        "id": lid,
        "title": (title or "Bài học").strip()[:200],
        "body_text": (body_text or "").strip(),
        "tts_script": tts,
        "grade": g,
        "subject": sub,
        "workspace_id": workspace_id or f"lop{g}-{sub}",
        "student_key": (student_key or "").strip(),
        "created": _now(),
        "created_ts": time.time(),
    }
    _write_json(_LESSONS / f"{lid}.json", lesson)
    return lesson


def get_lesson(lesson_id: str) -> Optional[dict[str, Any]]:
    return _read_json(_LESSONS / f"{_safe(lesson_id, 32)}.json")


def list_lessons(limit: int = 50) -> list[dict[str, Any]]:
    _LESSONS.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in sorted(_LESSONS.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        d = _read_json(p)
        if d:
            rows.append({
                "id": d.get("id"),
                "title": d.get("title"),
                "grade": d.get("grade"),
                "subject": d.get("subject"),
                "workspace_id": d.get("workspace_id"),
                "created": d.get("created"),
                "preview": (d.get("body_text") or "")[:160],
            })
        if len(rows) >= limit:
            break
    return rows


def delete_lesson(lesson_id: str) -> dict[str, Any]:
    lid = _safe(lesson_id, 32)
    path = _LESSONS / f"{lid}.json"
    if not path.is_file():
        return {"ok": False, "error": f"Không thấy bài giảng {lesson_id}"}
    try:
        path.unlink()
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "id": lid}


# ── Assignments ─────────────────────────────────────────────────────────────


def resolve_focus_topic(
    *,
    student_key: str = "",
    subject: str = "toan",
    grade: int = 5,
    topic: str = "",
    from_roadmap: bool = False,
) -> dict[str, Any]:
    """Chọn topic: explicit → lộ trình current_focus → topic thô.

    Dùng khi soạn buổi học / bài tập gắn HS có lộ trình.
    """
    topic = (topic or "").strip()
    sk = (student_key or "").strip()
    # explicit topic wins unless caller forces roadmap
    if topic and not from_roadmap and topic.lower() not in {
        "roadmap", "lộ trình", "current_focus", "auto",
    }:
        return {
            "ok": True,
            "topic": topic,
            "title": topic,
            "step_id": "",
            "source": "explicit",
            "grade": grade,
        }
    if not sk:
        return {
            "ok": bool(topic),
            "topic": topic or "ôn tập",
            "title": topic or "ôn tập",
            "step_id": "",
            "source": "default",
            "grade": grade,
        }
    try:
        from services.agent import teacher_path as tp
        focus = tp.current_focus(sk, subject, grade=grade, ensure=False)
        if focus.get("ok") and focus.get("topic"):
            return focus
    except Exception:
        pass
    return {
        "ok": bool(topic),
        "topic": topic or "ôn tập",
        "title": topic or "ôn tập",
        "step_id": "",
        "source": "fallback",
        "grade": grade,
    }


def create_assignment(
    *,
    title: str,
    grade: int = 5,
    subject: str = "toan",
    topic: str = "",
    workspace_id: str = "",
    n: int = 5,
    difficulty: str = "auto",
    student_key: str = "",
    lesson_id: str = "",
    questions: list[dict[str, Any]] | None = None,
    from_roadmap: bool = False,
) -> dict[str, Any]:
    """Tạo bài tập: tự sinh từ KB (adaptive) hoặc dùng questions sẵn.

    Nếu ``from_roadmap`` hoặc topic trống + có student_key → lấy current_focus.
    """
    from services.agent import teacher_assess as ta
    from services.agent import teacher_workspace as tw

    sub = tw._normalize_subject(subject) or "toan"
    g = int(grade) if int(grade) in tw.GRADES else 5
    ws = workspace_id or f"lop{g}-{sub}"
    sk = (student_key or "default").strip() or "default"
    diff = (difficulty or "auto").strip().lower()
    if diff == "auto":
        diff = adaptive_level(ws, sk)

    focus = resolve_focus_topic(
        student_key=sk if sk != "default" else "",
        subject=sub,
        grade=g,
        topic=topic,
        from_roadmap=from_roadmap or not (topic or "").strip(),
    )
    topic_use = str(focus.get("topic") or topic or "ôn tập").strip()
    step_id = str(focus.get("step_id") or "")

    if questions:
        qs = questions
    else:
        quiz = ta.make_quiz_adaptive(
            grade=g, subject=sub, topic=topic_use, n=n,
            workspace_id=ws, difficulty=diff,
        )
        qs = quiz.get("questions") or []

    title_final = (title or "").strip()
    if not title_final:
        if focus.get("source") == "roadmap" and focus.get("title"):
            title_final = f"BT lộ trình: {focus['title']}"[:200]
        else:
            title_final = f"Bài tập {sub} lớp {g}"

    aid = uuid.uuid4().hex[:12]
    asg = {
        "id": aid,
        "title": title_final[:200],
        "grade": g,
        "subject": sub,
        "topic": topic_use,
        "workspace_id": ws,
        "student_key": sk if sk != "default" else "",  # empty = open to all
        "difficulty": diff,
        "lesson_id": (lesson_id or "").strip(),
        "roadmap_step_id": step_id,
        "from_roadmap": focus.get("source") == "roadmap",
        "focus_title": focus.get("title") or "",
        "questions": qs,
        "created": _now(),
        "created_ts": time.time(),
        "status": "open",
    }
    _write_json(_ASSIGN / f"{aid}.json", asg)
    return asg


def get_assignment(assignment_id: str, *, for_student: bool = False) -> Optional[dict[str, Any]]:
    d = _read_json(_ASSIGN / f"{_safe(assignment_id, 32)}.json")
    if not d:
        return None
    if for_student:
        # Ẩn answer_hint khi HS làm bài
        qs = []
        for q in d.get("questions") or []:
            qs.append({
                "id": q.get("id"),
                "type": q.get("type"),
                "prompt": q.get("prompt"),
                "difficulty": q.get("difficulty"),
            })
        out = dict(d)
        out["questions"] = qs
        return out
    return d


def list_assignments(limit: int = 50) -> list[dict[str, Any]]:
    _ASSIGN.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in sorted(_ASSIGN.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        d = _read_json(p)
        if not d:
            continue
        rows.append({
            "id": d.get("id"),
            "title": d.get("title"),
            "grade": d.get("grade"),
            "subject": d.get("subject"),
            "topic": d.get("topic"),
            "difficulty": d.get("difficulty"),
            "n_questions": len(d.get("questions") or []),
            "workspace_id": d.get("workspace_id"),
            "student_key": d.get("student_key"),
            "lesson_id": d.get("lesson_id"),
            "created": d.get("created"),
            "status": d.get("status"),
        })
        if len(rows) >= limit:
            break
    return rows


def delete_assignment(assignment_id: str, *, delete_submissions: bool = True) -> dict[str, Any]:
    aid = _safe(assignment_id, 32)
    path = _ASSIGN / f"{aid}.json"
    if not path.is_file():
        return {"ok": False, "error": f"Không thấy bài tập {assignment_id}"}
    try:
        path.unlink()
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    if delete_submissions:
        import shutil
        sub_dir = _SUBS / aid
        if sub_dir.is_dir():
            try:
                shutil.rmtree(sub_dir)
            except OSError:
                pass
    return {"ok": True, "id": aid}


# ── AI soạn bài giảng / bài tập ─────────────────────────────────────────────


def _teacher_model(mode: str = "write") -> str:
    """Chọn LLM theo văn nói / văn viết (Settings → Giáo viên)."""
    try:
        from services.agent import teacher as teach
        return teach.model_for(mode)
    except Exception:
        return "cx/auto"


def _parse_json_obj(text: str) -> Optional[dict[str, Any]]:
    t = (text or "").strip()
    if not t:
        return None
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    try:
        i, j = t.find("{"), t.rfind("}")
        if i >= 0 and j > i:
            data = json.loads(t[i : j + 1])
            return data if isinstance(data, dict) else None
    except Exception:
        return None
    return None


def ai_draft_lesson(
    *,
    grade: int,
    subject: str,
    topic: str,
    workspace_id: str = "",
    notes: str = "",
    student_key: str = "",
    from_roadmap: bool = False,
) -> dict[str, Any]:
    """AI soạn bài giảng: title + body_text + tts_script. Fallback template nếu LLM lỗi.

    Gắn lộ trình: topic trống / from_roadmap → current_focus của HS.
    """
    from services.agent import teacher as teach
    from services.agent import teacher_workspace as tw

    sub = tw._normalize_subject(subject) or "toan"
    g = int(grade) if int(grade) in tw.GRADES else 5
    path_focus = resolve_focus_topic(
        student_key=student_key,
        subject=sub,
        grade=g,
        topic=topic,
        from_roadmap=from_roadmap or not (topic or "").strip(),
    )
    topic = str(path_focus.get("topic") or topic or "ôn tập").strip()
    mon = tw.SUBJECT_LABEL.get(sub, sub)
    recipe = str(path_focus.get("session_recipe") or "")
    if recipe and recipe not in (notes or ""):
        notes = ((notes or "").strip() + f"\nCấu trúc buổi: {recipe}").strip()

    def _with_focus(d: dict[str, Any]) -> dict[str, Any]:
        d["roadmap_step_id"] = path_focus.get("step_id") or ""
        d["from_roadmap"] = path_focus.get("source") == "roadmap"
        d["focus_title"] = path_focus.get("title") or ""
        d["topic"] = topic
        return d

    kb = ""
    try:
        kb = tw.search_sgk(topic, grade=g, subject=sub, workspace_id=workspace_id, top_k=3)
    except Exception:
        pass

    en_extra = ""
    if sub == "anh":
        try:
            from services.agent import teacher_english as te
            sm = te.english_skill_map(g)
            en_extra = (
                f"\nEnglish band={sm.get('band')} CEFR≈{sm.get('cefr')}. "
                "Soạn song ngữ nhẹ (EN chính, VI gợi ý nếu tiểu học). "
                "Gồm: mục tiêu I can…, 3–5 mẫu câu, 1 dialogue ngắn, "
                "vocab list 5–8 từ, 1 tip phát âm. tts_script bằng English dễ nghe."
            )
        except Exception:
            en_extra = "\nSoạn bài English: samples + dialogue + vocab."
    sys = (
        "Bạn là giáo viên Việt Nam soạn bài giảng lớp học. "
        "Trả JSON thuần (không markdown) đúng schema:\n"
        '{"title":"...","body_text":"...","tts_script":"..."}\n'
        "body_text: bài cho HS đọc, rõ bước, 150–400 từ, có ví dụ. "
        "tts_script: 2–5 câu ngắn để loa đọc, không ký hiệu ×÷=%, không markdown. "
        "Giọng phù hợp cấp học; không bịa trang SGK cụ thể."
        + en_extra
    )
    user = (
        f"Lớp {g} · môn {mon} · chủ đề: {topic}\n"
        f"Ghi chú GV: {(notes or '').strip() or '(không)'}\n"
        f"Gợi ý KB (tham khảo, đừng chép nguyên):\n{(kb or '')[:1200]}"
    )
    try:
        from services.agent.runtime import call_model, content_of
        # Bài giảng EN: model theo skill (speaking/reading/…); khác → speak fallback
        llm = _teacher_model("speak")
        if sub == "anh":
            try:
                from services.agent import teacher as teach_mod
                from services.agent import teacher_english as te
                en_focus = te.detect_focus(topic, g, 0)
                llm = teach_mod.model_for_english_topic(topic, en_focus)
            except Exception:
                llm = _teacher_model("speak")
        resp = call_model(
            llm,
            [{"role": "system", "content": sys}, {"role": "user", "content": user}],
            timeout=120, max_tokens=1200, no_smart_home=True,
        )
        if not resp.get("error"):
            data = _parse_json_obj(content_of(resp))
            if data and (data.get("body_text") or data.get("body")):
                body = str(data.get("body_text") or data.get("body") or "").strip()
                title = str(data.get("title") or f"{mon} lớp {g}: {topic}").strip()
                tts = str(data.get("tts_script") or data.get("tts") or "").strip()
                if not tts:
                    tts = teach.verbalize_for_tts(body[:500])
                else:
                    tts = teach.verbalize_for_tts(tts)
                return _with_focus({
                    "ok": True,
                    "source": "ai",
                    "title": title[:200],
                    "body_text": body,
                    "tts_script": tts,
                    "grade": g,
                    "subject": sub,
                    "topic": topic,
                    "model_used": llm,
                })
    except Exception:
        pass

    # Fallback template (không cần LLM)
    body = (
        f"Bài học lớp {g} — {mon}\n"
        f"Chủ đề: {topic}\n\n"
        f"1) Mục tiêu: Sau bài, em nắm được ý chính về «{topic}».\n"
        f"2) Ví dụ / gợi ý:\n{(kb[:600] if kb else 'Ôn lại kiến thức đã học, làm từng bước.')}\n\n"
        f"3) Luyện: tự lấy 1 ví dụ tương tự và làm.\n"
        f"4) Kiểm tra: nhắc lại 1 câu xem đã hiểu chưa.\n"
    )
    tts = teach.verbalize_for_tts(
        f"Hôm nay lớp {g} học {mon}, chủ đề {topic}. "
        f"Em lắng nghe từng bước, rồi tự làm một bài tương tự. Cố lên nhé."
    )
    return _with_focus({
        "ok": True,
        "source": "template",
        "title": f"{mon} lớp {g}: {topic}",
        "body_text": body,
        "tts_script": tts,
        "grade": g,
        "subject": sub,
        "topic": topic,
    })


def ai_draft_assignment(
    *,
    grade: int,
    subject: str,
    topic: str,
    n: int = 5,
    difficulty: str = "medium",
    workspace_id: str = "",
    notes: str = "",
    use_ai: bool = True,
    student_key: str = "",
    from_roadmap: bool = False,
) -> dict[str, Any]:
    """AI (hoặc generator) soạn danh sách câu hỏi bài tập cụ thể.

    Topic từ lộ trình (current_focus) khi ``from_roadmap`` hoặc topic trống + có HS.
    """
    from services.agent import teacher_assess as ta
    from services.agent import teacher_workspace as tw

    sub = tw._normalize_subject(subject) or "toan"
    g = int(grade) if int(grade) in tw.GRADES else 5
    path_focus = resolve_focus_topic(
        student_key=student_key,
        subject=sub,
        grade=g,
        topic=topic,
        from_roadmap=from_roadmap or not (topic or "").strip(),
    )
    topic = str(path_focus.get("topic") or topic or "ôn tập").strip()
    n = max(1, min(int(n or 5), 10))
    diff = (difficulty or "medium").strip().lower()
    if diff not in {"easy", "medium", "hard", "auto"}:
        diff = "medium"
    if diff == "auto":
        sk = (student_key or "default").strip() or "default"
        ws = workspace_id or f"lop{g}-{sub}"
        diff = adaptive_level(ws, sk)
    mon = tw.SUBJECT_LABEL.get(sub, sub)
    if path_focus.get("source") == "roadmap" and path_focus.get("title"):
        notes = (
            (notes or "").strip()
            + f"\nLộ trình HS: {path_focus.get('title')} (phase={path_focus.get('phase')})."
        ).strip()

    def _asg_focus(d: dict[str, Any]) -> dict[str, Any]:
        d["roadmap_step_id"] = path_focus.get("step_id") or ""
        d["from_roadmap"] = path_focus.get("source") == "roadmap"
        d["focus_title"] = path_focus.get("title") or ""
        d["topic"] = topic
        return d

    questions: list[dict[str, Any]] = []
    if use_ai:
        kb = ""
        try:
            kb = tw.search_sgk(topic, grade=g, subject=sub, workspace_id=workspace_id, top_k=2)
        except Exception:
            pass
        en_req = ""
        if sub == "anh":
            try:
                from services.agent import teacher_english as te
                sm = te.english_skill_map(g)
                skills = ", ".join(s["id"] for s in (sm.get("skills") or [])[:8])
                en_req = (
                    f"\n- English CEFR≈{sm.get('cefr')}; mix skills: {skills}. "
                    "Types: fill grammar, MC vocab, reading Q, short writing, dialogue. "
                    "Prompts in English (short VI gloss OK for grade≤5). "
                    "answer_hint = exact word/phrase to grade."
                )
            except Exception:
                en_req = "\n- English: concrete fill/MC/reading/writing items."
        sys = (
            "Bạn là giáo viên ra đề kiểm tra Việt Nam. "
            "Trả JSON thuần:\n"
            '{"title":"...","questions":[{"id":"q1","prompt":"...","answer_hint":"...","type":"calc|short"}]}\n'
            "YÊU CẦU QUAN TRỌNG:\n"
            "- Mỗi câu là BÀI LÀM ĐƯỢC (phép tính / điền / chọn / viết câu), "
            "KHÔNG dán đoạn lý thuyết SGK.\n"
            f"- Đúng {n} câu, lớp {g}, môn {mon}, chủ đề {topic}, độ khó {diff}.\n"
            "- answer_hint: đáp án ngắn để chấm (số hoặc từ khóa).\n"
            "- Toán: «Tính: a − b = ?». Văn: chính tả/dấu câu/đọc/viết. "
            "Anh: điền ngữ pháp, vocab, đọc hiểu, viết."
            + en_req
        )
        user = (
            f"Ra {n} câu. Ghi chú: {(notes or '').strip() or '(không)'}\n"
            f"KB gợi ý (đừng chép nguyên):\n{(kb or '')[:800]}"
        )
        try:
            from services.agent.runtime import call_model, content_of
            # Tiếng Anh: model theo skill (ngữ pháp/nghe/nói/đọc/viết)
            llm = _teacher_model("write")
            if sub == "anh":
                try:
                    from services.agent import teacher as teach
                    from services.agent import teacher_english as te
                    focus = te.detect_focus(topic, g, 0)
                    llm = teach.model_for_english_topic(topic, focus)
                except Exception:
                    llm = _teacher_model("write")
            resp = call_model(
                llm,
                [{"role": "system", "content": sys}, {"role": "user", "content": user}],
                timeout=120, max_tokens=1600, no_smart_home=True,
            )
            if not resp.get("error"):
                data = _parse_json_obj(content_of(resp))
                raw_qs = (data or {}).get("questions") if data else None
                if isinstance(raw_qs, list) and raw_qs:
                    for i, q in enumerate(raw_qs[:n]):
                        if not isinstance(q, dict):
                            continue
                        prompt = str(q.get("prompt") or q.get("question") or "").strip()
                        if not prompt:
                            continue
                        questions.append({
                            "id": str(q.get("id") or f"q{i + 1}"),
                            "type": str(q.get("type") or "short"),
                            "prompt": prompt,
                            "answer_hint": str(q.get("answer_hint") or q.get("answer") or "")[:400],
                            "source": "ai",
                            "difficulty": diff,
                        })
                    title = str((data or {}).get("title") or f"BT {mon} lớp {g}: {topic}")
                    if len(questions) >= max(1, n // 2):
                        # đủ câu AI — bổ sung generator nếu thiếu
                        while len(questions) < n:
                            extra = ta._generate_practice_items(
                                grade=g, subject=sub, topic=topic, n=1, difficulty=diff,
                            )
                            if not extra:
                                break
                            e = extra[0]
                            e["id"] = f"q{len(questions) + 1}"
                            questions.append(e)
                        return _asg_focus({
                            "ok": True,
                            "source": "ai",
                            "title": title[:200],
                            "questions": questions[:n],
                            "grade": g,
                            "subject": sub,
                            "topic": topic,
                            "difficulty": diff,
                        })
        except Exception:
            pass

    # Fallback deterministic generator (đã có bài thật)
    quiz = ta.make_quiz(
        grade=g, subject=sub, topic=topic, n=n, difficulty=diff,
        workspace_id=workspace_id,
    )
    title_gen = f"BT {mon} lớp {g}: {topic}"
    if path_focus.get("source") == "roadmap" and path_focus.get("title"):
        title_gen = f"BT lộ trình: {path_focus['title']}"[:200]
    return _asg_focus({
        "ok": True,
        "source": "generator",
        "title": title_gen,
        "questions": quiz.get("questions") or [],
        "grade": g,
        "subject": sub,
        "topic": topic,
        "difficulty": diff,
    })


def submit_assignment(
    assignment_id: str,
    answers: dict[str, str],
    *,
    student_key: str = "default",
    use_llm: bool = True,
) -> dict[str, Any]:
    """Nộp bài + chấm + cập nhật adaptive + memory tuần."""
    from services.agent import teacher_assess as ta
    from services.agent import teacher_workspace as tw

    asg = get_assignment(assignment_id, for_student=False)
    if not asg:
        return {"ok": False, "error": f"Không thấy bài tập {assignment_id}"}
    sk = (student_key or "default").strip() or "default"
    details = []
    total = 0
    for q in asg.get("questions") or []:
        qid = str(q.get("id"))
        ans = str(answers.get(qid) or answers.get(qid.upper()) or "")
        r = ta.grade_answer(
            question=str(q.get("prompt") or ""),
            student_answer=ans,
            answer_hint=str(q.get("answer_hint") or ""),
            subject=str(asg.get("subject") or "toan"),
            grade=int(asg.get("grade") or 5),
            use_llm=use_llm,
        )
        # Rubric band cho Văn/Anh
        band = ta.rubric_band(
            int(r.get("score_0_10") or 0),
            subject=str(asg.get("subject") or "toan"),
        )
        r["id"] = qid
        r["band"] = band
        r["answer"] = ans
        details.append(r)
        total += int(r.get("score_0_10") or 0)
        # adaptive streak
        record_answer_result(
            str(asg.get("workspace_id") or ""),
            sk,
            correct=bool(r.get("correct")),
            score=int(r.get("score_0_10") or 0),
            topic=str(asg.get("topic") or q.get("source") or ""),
        )

    n = max(1, len(details))
    avg = round(total / n, 1)
    sub = {
        "ok": True,
        "assignment_id": assignment_id,
        "student_key": sk,
        "submitted": _now(),
        "submitted_ts": time.time(),
        "week": _week_key(),
        "average_0_10": avg,
        "percent": int(round(avg * 10)),
        "details": details,
        "summary": ta._summary_vi(avg, details),
        "adaptive_level": adaptive_level(str(asg.get("workspace_id") or ""), sk),
    }
    _write_json(_SUBS / _safe(assignment_id) / f"{_safe(sk)}.json", sub)

    # Memory + weekly weak topics
    ws = str(asg.get("workspace_id") or "")
    if ws:
        weak_ids = [d["id"] for d in details if int(d.get("score_0_10") or 0) < 5]
        note = f"Bài tập {assignment_id}: TB {avg}/10 ({sub['percent']}%)"
        weak_topic = ""
        if weak_ids:
            weak_topic = f"{asg.get('topic') or 'bài tập'}: {', '.join(weak_ids)}"
        strong = ""
        if avg >= 8:
            strong = str(asg.get("topic") or "bài tập gần đây")
        tw.memory_add(ws, sk, note=note, weak_topic=weak_topic, strong_topic=strong)
        if weak_topic:
            tw.memory_add_weekly_weak(ws, sk, weak_topic, week=_week_key())

    # Điều chỉnh lộ trình theo điểm làm bài (per-student independent)
    roadmap_update: dict[str, Any] = {}
    try:
        from services.agent import teacher_path as tp
        roadmap_update = tp.apply_practice_result(
            sk,
            str(asg.get("subject") or "toan"),
            average_0_10=avg,
            topic=str(asg.get("topic") or ""),
            step_id=str(asg.get("roadmap_step_id") or ""),
            assignment_id=str(assignment_id),
            details=details,
        )
        if roadmap_update.get("ok"):
            sub["roadmap_update"] = {
                "action": roadmap_update.get("action"),
                "message": roadmap_update.get("message"),
                "old_focus": roadmap_update.get("old_focus"),
                "new_focus": roadmap_update.get("new_focus"),
                "current_topic": roadmap_update.get("current_topic"),
                "steps_done": (roadmap_update.get("roadmap") or {}).get("steps_done"),
                "steps_total": len((roadmap_update.get("roadmap") or {}).get("steps") or []),
            }
            # ensure profile exists + grade synced
            tp.get_or_create_profile(
                sk,
                grade=int(asg.get("grade") or 0),
            )
    except Exception as exc:
        sub["roadmap_update"] = {"ok": False, "error": str(exc)[:200]}

    return sub


def get_submission(assignment_id: str, student_key: str = "default") -> Optional[dict[str, Any]]:
    sk = (student_key or "default").strip() or "default"
    return _read_json(_SUBS / _safe(assignment_id) / f"{_safe(sk)}.json")


def list_submissions(assignment_id: str) -> list[dict[str, Any]]:
    d = _SUBS / _safe(assignment_id)
    if not d.is_dir():
        return []
    rows = []
    for p in d.glob("*.json"):
        s = _read_json(p)
        if s:
            rows.append({
                "student_key": s.get("student_key"),
                "average_0_10": s.get("average_0_10"),
                "percent": s.get("percent"),
                "submitted": s.get("submitted"),
                "week": s.get("week"),
            })
    return rows


# ── Adaptive difficulty ─────────────────────────────────────────────────────


def _adapt_path(workspace_id: str, student_key: str) -> Path:
    return _ADAPT / _safe(workspace_id or "general") / f"{_safe(student_key or 'default')}.json"


def _load_adapt(workspace_id: str, student_key: str) -> dict[str, Any]:
    d = _read_json(_adapt_path(workspace_id, student_key))
    if d:
        return d
    return {
        "workspace_id": workspace_id,
        "student_key": student_key,
        "level": "medium",  # easy | medium | hard
        "streak_correct": 0,
        "streak_wrong": 0,
        "history": [],
    }


def adaptive_level(workspace_id: str, student_key: str = "default") -> str:
    d = _load_adapt(workspace_id, student_key)
    lv = str(d.get("level") or "medium")
    return lv if lv in {"easy", "medium", "hard"} else "medium"


def record_answer_result(
    workspace_id: str,
    student_key: str,
    *,
    correct: bool,
    score: int = 0,
    topic: str = "",
) -> dict[str, Any]:
    """Sau 3 đúng liên tiếp → tăng độ khó; 3 sai → giảm."""
    if not workspace_id:
        return {"level": "medium"}
    d = _load_adapt(workspace_id, student_key)
    if correct or score >= 7:
        d["streak_correct"] = int(d.get("streak_correct") or 0) + 1
        d["streak_wrong"] = 0
    else:
        d["streak_wrong"] = int(d.get("streak_wrong") or 0) + 1
        d["streak_correct"] = 0

    level = str(d.get("level") or "medium")
    if int(d["streak_correct"]) >= 3:
        if level == "easy":
            level = "medium"
        elif level == "medium":
            level = "hard"
        d["streak_correct"] = 0
    if int(d["streak_wrong"]) >= 3:
        if level == "hard":
            level = "medium"
        elif level == "medium":
            level = "easy"
        d["streak_wrong"] = 0
    d["level"] = level
    hist = list(d.get("history") or [])
    hist.append({
        "ts": _now(),
        "correct": bool(correct),
        "score": int(score),
        "topic": (topic or "")[:80],
        "level_after": level,
    })
    d["history"] = hist[-100:]
    d["updated"] = _now()
    _write_json(_adapt_path(workspace_id, student_key), d)
    return d


# ── Parent dashboard (weekly weak topics) ───────────────────────────────────


def parent_dashboard(
    *,
    workspace_id: str = "",
    student_key: str = "",
    weeks: int = 4,
) -> dict[str, Any]:
    """Tổng hợp điểm yếu theo tuần + adaptive + memory + profile/lộ trình cho PH."""
    from services.agent import teacher_workspace as tw
    from services.agent import teacher_path as tp

    weeks = max(1, min(int(weeks or 4), 12))
    sk = (student_key or "").strip()
    # Thu thập từ memory files
    students: list[dict[str, Any]] = []
    mem_root = Path(DATA_DIR) / "agent" / "teacher" / "memory"
    targets: list[tuple[str, str]] = []
    seen_students: set[str] = set()
    if workspace_id and sk:
        targets.append((workspace_id, sk))
        seen_students.add(_safe(sk))
    elif workspace_id:
        wdir = mem_root / _safe(workspace_id)
        if wdir.is_dir():
            for p in wdir.glob("*.json"):
                targets.append((workspace_id, p.stem))
                seen_students.add(p.stem)
    else:
        if mem_root.is_dir():
            for wdir in mem_root.iterdir():
                if not wdir.is_dir():
                    continue
                for p in wdir.glob("*.json"):
                    targets.append((wdir.name, p.stem))
                    seen_students.add(p.stem)

    # Gộp HS từ student profiles (placement/roadmap) kể cả chưa có memory
    try:
        for row in tp.list_students():
            key = str(row.get("student_key") or "")
            if not key:
                continue
            if sk and _safe(sk) != _safe(key):
                continue
            if _safe(key) in seen_students:
                continue
            # workspace gợi ý từ grade + subjects
            g = int(row.get("grade") or 0) or 5
            tracked = []
            for p in row.get("placements") or []:
                if p.get("subject"):
                    tracked.append(str(p["subject"]))
            if not tracked:
                tracked = ["toan"]
            for sub in tracked[:3]:
                targets.append((f"lop{g}-{sub}", key))
            seen_students.add(_safe(key))
    except Exception:
        pass

    # week list
    now = time.time()
    week_ids = []
    for i in range(weeks):
        week_ids.append(_week_key(now - i * 7 * 86400))

    # de-dupe targets by (ws, student) but merge profile once per student
    seen_pair: set[tuple[str, str]] = set()
    for ws, st in targets[:120]:
        pair = (_safe(ws), _safe(st))
        if pair in seen_pair:
            continue
        seen_pair.add(pair)
        m = tw._load_mem(ws, st)
        weekly = m.get("weekly_weak") or {}
        if not isinstance(weekly, dict):
            weekly = {}
        by_week = []
        for w in week_ids:
            items = weekly.get(w) or []
            if isinstance(items, list) and items:
                by_week.append({"week": w, "weak_topics": items[-20:]})
        adapt = _load_adapt(ws, st)

        # profile + roadmap multi-subject (độc lập)
        profile = None
        path_by_subject: dict[str, Any] = {}
        try:
            dash = tp.student_dashboard(st)
            profile = dash.get("profile")
            for sub, block in (dash.get("by_subject") or {}).items():
                focus = block.get("focus") or {}
                pl = block.get("placement") or {}
                rm = block.get("roadmap") or {}
                if not focus and not pl and not rm:
                    continue
                path_by_subject[sub] = {
                    "level_label": (pl or {}).get("level_label") or (rm or {}).get("level_label"),
                    "score_pct": (pl or {}).get("score_pct"),
                    "current_focus": (focus or {}).get("title") or (rm or {}).get("current_focus"),
                    "current_topic": (focus or {}).get("topic") or (rm or {}).get("current_topic"),
                    "steps_done": (focus or {}).get("steps_done") or (rm or {}).get("steps_done", 0),
                    "steps_total": (focus or {}).get("steps_total")
                    or len((rm or {}).get("steps") or []),
                    "last_practice": (rm or {}).get("last_practice"),
                    "weak_strands": (pl or {}).get("weak_strands") or [],
                    "strong_strands": (pl or {}).get("strong_strands") or [],
                }
        except Exception:
            profile = tp.get_profile(st)

        students.append({
            "workspace_id": ws,
            "student_key": st,
            "display_name": (profile or {}).get("display_name") or st,
            "grade": (profile or {}).get("grade"),
            "profile": profile,
            "updated": m.get("updated") or (profile or {}).get("updated"),
            "weak_topics": (m.get("weak_topics") or [])[-15:],
            "strong_topics": (m.get("strong_topics") or [])[-10:],
            "weekly": by_week,
            "adaptive_level": adapt.get("level"),
            "streak_correct": adapt.get("streak_correct"),
            "streak_wrong": adapt.get("streak_wrong"),
            "notes_recent": [
                n for n in (m.get("notes") or [])[-5:]
            ],
            "path": path_by_subject,
        })

    return {
        "ok": True,
        "weeks": week_ids,
        "students": students,
        "count": len(students),
    }
