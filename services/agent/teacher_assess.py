"""Kiểm tra · chấm bài · sửa lỗi — giáo viên đa cấp.

- make_quiz: lấy gợi ý từ KB SGK + sinh đề theo mẫu (không cần LLM)
- grade_answer: chấm khách quan (số/lựa chọn) + chấm tự luận qua model (nếu có)
- explain_fix: gợi ý sửa lỗi dựa KB + rubric
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR

_ROOT = Path(DATA_DIR) / "agent" / "teacher" / "quizzes"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _extract_numbers(s: str) -> list[float]:
    out: list[float] = []
    for m in re.finditer(r"-?\d+(?:[.,]\d+)?", s or ""):
        try:
            out.append(float(m.group(0).replace(",", ".")))
        except ValueError:
            pass
    return out


def make_quiz(
    *,
    grade: int,
    subject: str,
    topic: str = "",
    n: int = 5,
    workspace_id: str = "",
) -> dict[str, Any]:
    """Sinh đề kiểm tra ngắn từ KB SGK.

    Trả {quiz_id, grade, subject, questions:[{id, prompt, answer_hint, type}]}.
    """
    from services.agent import teacher_workspace as tw

    n = max(1, min(int(n or 5), 10))
    sub = tw._normalize_subject(subject) or "toan"
    g = int(grade) if int(grade) in tw.GRADES else 2
    q = (topic or "").strip() or SUBJECT_HINT.get(sub, "ôn tập")
    # Lấy đoạn KB
    blob = tw.search_sgk(q, grade=g, subject=sub, workspace_id=workspace_id, top_k=6)
    # Tách các mục ### 
    sections = re.findall(
        r"###\s+\d+\.\s+(.+?)\n(?:_Nguồn:.*?\n)?([\s\S]*?)(?=\n###|\n_Dùng làm|\Z)",
        blob,
    )
    questions: list[dict[str, Any]] = []
    for i, (title, body) in enumerate(sections[:n]):
        body = (body or "").strip()
        prompt = _prompt_from_chunk(sub, title.strip(), body)
        questions.append({
            "id": f"q{i + 1}",
            "type": "short",
            "prompt": prompt,
            "answer_hint": _hint_from_body(body)[:400],
            "source": title.strip(),
        })
    # Fallback nếu KB mỏng
    while len(questions) < n:
        i = len(questions) + 1
        questions.append({
            "id": f"q{i}",
            "type": "short",
            "prompt": _fallback_prompt(sub, g, i),
            "answer_hint": "",
            "source": "fallback",
        })

    quiz_id = uuid.uuid4().hex[:12]
    quiz = {
        "quiz_id": quiz_id,
        "grade": g,
        "subject": sub,
        "topic": q,
        "workspace_id": workspace_id or f"lop{g}-{sub}",
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "questions": questions,
    }
    _ROOT.mkdir(parents=True, exist_ok=True)
    (_ROOT / f"{quiz_id}.json").write_text(
        json.dumps(quiz, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return quiz


SUBJECT_HINT = {
    "toan": "phép tính công thức",
    "van": "đọc hiểu nghị luận",
    "anh": "grammar vocabulary",
}


def _prompt_from_chunk(subject: str, title: str, body: str) -> str:
    if subject == "toan":
        return (
            f"[{title}] Dựa trên kiến thức đã học, hãy nêu / tính / giải thích ngắn "
            f"(1–3 câu hoặc phép tính). Gợi ý nội dung: {body[:180]}…"
            if len(body) > 180 else
            f"[{title}] Nêu rõ cách làm và kết quả. Nội dung: {body}"
        )
    if subject == "anh":
        return (
            f"[{title}] Answer in English (1–3 sentences) about: {body[:200]}"
        )
    return (
        f"[{title}] Trả lời ngắn (3–5 câu): nêu ý chính hoặc viết đoạn theo yêu cầu. "
        f"Gợi ý: {body[:200]}"
    )


def _hint_from_body(body: str) -> str:
    lines = [ln.strip() for ln in (body or "").splitlines() if ln.strip()]
    return " ".join(lines[:3])


def _fallback_prompt(subject: str, grade: int, i: int) -> str:
    if subject == "toan":
        return f"Câu {i} (Toán lớp {grade}): Nêu một ví dụ và cách giải ngắn cho bài toán vừa học."
    if subject == "anh":
        return f"Q{i} (English grade {grade}): Write 2 sentences using today's vocabulary."
    return f"Câu {i} (Văn lớp {grade}): Viết 3–5 câu nêu cảm nhận / ý chính bài học."


def load_quiz(quiz_id: str) -> Optional[dict[str, Any]]:
    p = _ROOT / f"{str(quiz_id).strip()}.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def grade_answer(
    *,
    question: str,
    student_answer: str,
    answer_hint: str = "",
    subject: str = "toan",
    grade: int = 5,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Chấm 1 câu. Trả {score_0_10, correct, feedback, fixes}."""
    q = (question or "").strip()
    ans = (student_answer or "").strip()
    hint = (answer_hint or "").strip()
    if not ans:
        return {
            "score_0_10": 0,
            "correct": False,
            "feedback": "Chưa có bài làm.",
            "fixes": ["Hãy viết lại câu trả lời / phép tính."],
        }

    # 1) Chấm số (toán): nếu gợi ý và bài có số khớp
    if subject == "toan" or _extract_numbers(hint):
        hn = _extract_numbers(hint)
        an = _extract_numbers(ans)
        if hn and an and abs(hn[-1] - an[-1]) < 1e-6:
            return {
                "score_0_10": 10,
                "correct": True,
                "feedback": "Kết quả đúng.",
                "fixes": [],
            }
        if hn and an and abs(hn[-1] - an[-1]) < 1e-3 * max(1, abs(hn[-1])):
            return {
                "score_0_10": 9,
                "correct": True,
                "feedback": "Gần đúng / làm tròn chấp nhận được.",
                "fixes": [],
            }

    # 2) Khớp chuỗi gợi ý (ngắn)
    if hint and _norm(hint) in _norm(ans):
        return {
            "score_0_10": 8,
            "correct": True,
            "feedback": "Bài có đủ ý chính theo gợi ý.",
            "fixes": [],
        }

    # 3) LLM chấm tự luận (best-effort)
    if use_llm:
        llm = _llm_grade(q, ans, hint, subject=subject, grade=grade)
        if llm:
            return llm

    # 4) Heuristic độ dài + từ khóa
    keys = set(_norm(hint).split()) | set(_norm(q).split())
    keys = {k for k in keys if len(k) > 2}
    hit = sum(1 for k in keys if k in _norm(ans))
    ratio = hit / max(1, min(8, len(keys)))
    score = int(round(min(7, ratio * 10)))
    return {
        "score_0_10": score,
        "correct": score >= 7,
        "feedback": (
            "Bài đã có một phần ý; cần bổ sung rõ ràng hơn."
            if score >= 4 else
            "Bài còn thiếu ý hoặc lệch yêu cầu."
        ),
        "fixes": [
            "Đọc lại đề, gạch chân yêu cầu.",
            "Viết đủ bước / ý (mở – thân – kết nếu là văn).",
            f"Tham khảo gợi ý: {hint[:200]}" if hint else "Ôn lại bài trong SGK (search_sgk).",
        ],
    }


def _llm_grade(
    question: str, answer: str, hint: str, *, subject: str, grade: int,
) -> Optional[dict[str, Any]]:
    try:
        from services.agent.runtime import call_model, content_of
        from services.config import config
        model = str(config.get().get("telegram_ai_model") or "cx/auto")
        sys = (
            "Bạn là giáo viên chấm bài. Trả về JSON thuần "
            '{"score_0_10":0-10,"correct":bool,"feedback":"...","fixes":["..."]} '
            "Không markdown. Feedback ngắn tiếng Việt (hoặc English nếu môn anh). "
            "Sửa lỗi cụ thể, không mắng học sinh."
        )
        user = (
            f"Lớp {grade}, môn {subject}\n"
            f"Đề: {question[:800]}\n"
            f"Gợi ý đáp án (nếu có): {hint[:400]}\n"
            f"Bài học sinh: {answer[:1200]}"
        )
        resp = call_model(
            model,
            [{"role": "system", "content": sys}, {"role": "user", "content": user}],
            timeout=90, max_tokens=400, no_smart_home=True,
        )
        if resp.get("error"):
            return None
        text = content_of(resp).strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
        score = int(data.get("score_0_10", 0))
        score = max(0, min(10, score))
        fixes = data.get("fixes") or []
        if not isinstance(fixes, list):
            fixes = [str(fixes)]
        return {
            "score_0_10": score,
            "correct": bool(data.get("correct", score >= 7)),
            "feedback": str(data.get("feedback") or "")[:500],
            "fixes": [str(x)[:200] for x in fixes[:5]],
        }
    except Exception:
        return None


def grade_quiz(
    quiz_id: str,
    answers: dict[str, str],
    *,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Chấm cả đề. answers: {q1: "...", q2: "..."}."""
    quiz = load_quiz(quiz_id)
    if not quiz:
        return {"ok": False, "error": f"Không thấy quiz {quiz_id}"}
    details = []
    total = 0
    for q in quiz.get("questions") or []:
        qid = str(q.get("id"))
        r = grade_answer(
            question=str(q.get("prompt") or ""),
            student_answer=str(answers.get(qid) or answers.get(qid.upper()) or ""),
            answer_hint=str(q.get("answer_hint") or ""),
            subject=str(quiz.get("subject") or "toan"),
            grade=int(quiz.get("grade") or 5),
            use_llm=use_llm,
        )
        r["id"] = qid
        details.append(r)
        total += int(r.get("score_0_10") or 0)
    n = max(1, len(details))
    avg = round(total / n, 1)
    return {
        "ok": True,
        "quiz_id": quiz_id,
        "average_0_10": avg,
        "percent": int(round(avg * 10)),
        "details": details,
        "summary": _summary_vi(avg, details),
    }


def _summary_vi(avg: float, details: list[dict]) -> str:
    weak = [d["id"] for d in details if int(d.get("score_0_10") or 0) < 5]
    lines = [
        f"Điểm trung bình: {avg}/10 ({int(round(avg * 10))}%).",
    ]
    if weak:
        lines.append("Cần ôn lại: " + ", ".join(weak) + ".")
    else:
        lines.append("Làm khá đều các câu.")
    lines.append("Xem feedback từng câu để sửa lỗi cụ thể.")
    return " ".join(lines)


def format_quiz_for_student(quiz: dict[str, Any]) -> str:
    lines = [
        f"**Đề kiểm tra** `{quiz.get('quiz_id')}` · "
        f"Lớp {quiz.get('grade')} · {quiz.get('subject')} · chủ đề: {quiz.get('topic')}",
        "",
    ]
    for q in quiz.get("questions") or []:
        lines.append(f"**{q.get('id')}.** {q.get('prompt')}")
        lines.append("")
    lines.append(
        "_Nộp bài: gửi teacher_grade với quiz_id và answers "
        '(vd: {"q1":"...","q2":"..."}) hoặc chấm từng câu._'
    )
    return "\n".join(lines)
