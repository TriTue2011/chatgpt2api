"""Cấu hình + quyền chế độ Giáo viên tiểu học.

Config key ``teacher`` (Settings → Giáo viên)::

    {
      "enabled": true,
      "voice_vi": "vieneu:Ngọc Linh",
      "voice_en": "kokoro:af_sky",
      "speak_to_speaker": false,
      "default_speaker": "",
      "model_speak": "cx/auto",   # fallback chung (nói / TTS)
      "model_write": "cx/auto",  # fallback chung (viết / chấm)
      "english": {
        "models": {
          "grammar": "",     # ngữ pháp
          "listening": "",   # nghe
          "speaking": "",    # nói
          "reading": "",     # đọc
          "writing": ""      # viết
        }
      }
    }

Tiếng Anh 5 kỹ năng: grammar · listening · speaking · reading · writing
(mỗi skill có thể chọn model LLM riêng trên WebUI).

Quyền thread (cùng bộ lọc Zalo/Telegram)::

  - ``teacher``        — được dùng skill/workflow giáo viên
  - ``tts_speaker``    — được phát loa (chung với hệ loa nhà)
  - ``thread_speaker_filters`` — loa nào cho thread/user nào
    (cùng cấu hình với tab Giọng nói & Loa)

Khi ``speak_to_speaker`` tắt: dạy bình thường, KHÔNG phát loa dù có tts_speaker.
"""
from __future__ import annotations

import re
from typing import Any

TEACHER_GROUP = "teacher"
TEACHER_SKILLS = frozenset({
    "giao-vien-tieu-hoc",
    "giao-vien-thcs",
    "giao-vien-thpt",
})
TEACHER_WORKFLOWS = frozenset({
    "bai-hoc-tieu-hoc",
    "bai-hoc-da-cap",
    "cham-bai",
})

# Heuristic: đoạn có ≥3 từ Latin liền / hoặc đa số ASCII chữ → coi là EN.
_EN_WORD = re.compile(r"\b[a-zA-Z]{3,}\b")
_VI_MARK = re.compile(
    r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"
    r"ÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]"
)


def _cfg() -> dict[str, Any]:
    try:
        from services.config import config
        v = config.get().get("teacher")
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def is_enabled() -> bool:
    """Công tắc tổng — tắt = không dạy / không skill giáo viên."""
    return bool(_cfg().get("enabled", True))


def speak_to_speaker_enabled() -> bool:
    """Bật phát loa khi dạy (vẫn cần quyền tts_speaker + filter loa)."""
    return bool(_cfg().get("speak_to_speaker", False))


def voice_vi() -> str:
    return str(_cfg().get("voice_vi") or "").strip()


def voice_en() -> str:
    return str(_cfg().get("voice_en") or "").strip()


def default_speaker() -> str:
    return str(_cfg().get("default_speaker") or "").strip()


def _fallback_llm_model() -> str:
    """Model hệ thống khi teacher.model_* để trống."""
    try:
        from services.config import config
        cfg = config.get()
        return str(
            cfg.get("telegram_ai_model")
            or cfg.get("openai_default_model")
            or cfg.get("default_model")
            or "cx/auto"
        ).strip() or "cx/auto"
    except Exception:
        return "cx/auto"


def model_speak() -> str:
    """Fallback LLM cho nói / TTS / dialogue (khi skill EN speaking/listening trống)."""
    return str(_cfg().get("model_speak") or "").strip() or _fallback_llm_model()


def model_write() -> str:
    """Fallback LLM cho viết / chấm (khi skill EN writing/reading/grammar trống)."""
    return str(_cfg().get("model_write") or "").strip() or _fallback_llm_model()


# ── Tiếng Anh: 5 kỹ năng (ngữ pháp · nghe · nói · đọc · viết) ───────────────

ENGLISH_SKILLS = ("grammar", "listening", "speaking", "reading", "writing")

ENGLISH_SKILL_LABELS = {
    "grammar": "Ngữ pháp (Grammar)",
    "listening": "Nghe (Listening)",
    "speaking": "Nói (Speaking)",
    "reading": "Đọc (Reading)",
    "writing": "Viết (Writing)",
}

# Map focus generator → skill model
_FOCUS_TO_EN_SKILL = {
    "grammar": "grammar", "present": "grammar", "past": "grammar",
    "future": "grammar", "continuous": "grammar", "perfect": "grammar",
    "compare": "grammar", "modal": "grammar", "conditional": "grammar",
    "passive": "grammar", "reported": "grammar", "preposition": "grammar",
    "exam": "grammar", "vocab": "reading",
    "listening": "listening",
    "speaking": "speaking", "greet": "speaking", "classroom": "speaking",
    "reading": "reading", "animal": "reading", "color": "reading",
    "number": "reading", "family": "reading", "food": "reading", "daily": "reading",
    "writing": "writing",
}


def _english_models() -> dict[str, str]:
    """teacher.english.models → {skill: model_id}."""
    eng = _cfg().get("english")
    if not isinstance(eng, dict):
        eng = {}
    models = eng.get("models")
    if not isinstance(models, dict):
        models = {}
    out: dict[str, str] = {}
    for sk in ENGLISH_SKILLS:
        # flat legacy: model_en_grammar
        flat = str(_cfg().get(f"model_en_{sk}") or "").strip()
        out[sk] = str(models.get(sk) or flat or "").strip()
    return out


def model_for_english_skill(skill: str) -> str:
    """LLM theo kỹ năng EN. Trống → speak (listening/speaking) hoặc write (còn lại)."""
    sk = (skill or "").strip().lower()
    # normalize aliases
    aliases = {
        "nghe": "listening", "listen": "listening",
        "noi": "speaking", "nói": "speaking", "speak": "speaking",
        "doc": "reading", "đọc": "reading", "read": "reading",
        "viet": "writing", "viết": "writing", "write": "writing",
        "ngu_phap": "grammar", "ngữ pháp": "grammar", "grammar": "grammar",
    }
    sk = aliases.get(sk, sk)
    if sk not in ENGLISH_SKILLS:
        sk = _FOCUS_TO_EN_SKILL.get(sk, "writing")
    configured = _english_models().get(sk) or ""
    if configured:
        return configured
    if sk in {"listening", "speaking"}:
        return model_speak()
    return model_write()


def model_for_english_topic(topic: str = "", focus: str = "") -> str:
    """Chọn model EN từ topic/focus (dùng khi soạn đề AI)."""
    if focus:
        return model_for_english_skill(focus)
    try:
        from services.agent import teacher_english as te
        f = te.detect_focus(topic or "", grade=5, i=0)
        return model_for_english_skill(_FOCUS_TO_EN_SKILL.get(f, f))
    except Exception:
        return model_write()


def model_for(mode: str = "write") -> str:
    """mode: speak | write | grammar | listening | speaking | reading | writing."""
    m = (mode or "write").strip().lower()
    if m in ENGLISH_SKILLS or m in {
        "nghe", "noi", "nói", "doc", "đọc", "viet", "viết", "ngữ pháp", "grammar",
    }:
        return model_for_english_skill(m)
    if m in {"speak", "speech", "tts", "van_noi", "văn_nói"}:
        return model_speak()
    return model_write()


def detect_lang(text: str) -> str:
    """'vi' | 'en' — đủ dùng chọn giọng TTS, không phải language-id chuẩn."""
    t = (text or "").strip()
    if not t:
        return "vi"
    if _VI_MARK.search(t):
        return "vi"
    en_words = _EN_WORD.findall(t)
    letters = sum(c.isalpha() for c in t) or 1
    ascii_letters = sum(c.isalpha() and ord(c) < 128 for c in t)
    if len(en_words) >= 3 and ascii_letters / letters > 0.85:
        return "en"
    return "vi"


def voice_for_text(text: str) -> str:
    """Giọng TTS theo ngôn ngữ đoạn; rỗng = dùng giọng mặc định hệ thống."""
    lang = detect_lang(text)
    if lang == "en":
        return voice_en() or voice_vi()
    return voice_vi() or voice_en()


def _ctx_ids(ctx: dict) -> tuple[str, str, str, str]:
    plat = str(ctx.get("platform") or ctx.get("plat") or "").strip()
    bot = str(ctx.get("bot_id") or ctx.get("bot") or "").strip()
    chat = str(ctx.get("chat_id") or ctx.get("thread_id") or ctx.get("chat") or "").strip()
    user = str(ctx.get("user_id") or ctx.get("from_id") or ctx.get("user") or "").strip()
    return plat, bot, chat, user


def can_use_teacher(platform: str = "", bot_id: str = "", chat_id: str = "",
                    user_id: str = "", *, ctx: dict | None = None) -> bool:
    """Thread/user được tick nhóm ``teacher`` (hoặc chưa lọc = cho phép)."""
    if not is_enabled():
        return False
    if ctx:
        platform, bot_id, chat_id, user_id = _ctx_ids(ctx)
    from services.agent import capabilities as caps
    g = caps.allowed_groups_for_bot(platform, bot_id, chat_id)
    if g is None:
        # Chưa có bản ghi lọc thread → cho phép (giống tool khác).
        return True
    if TEACHER_GROUP in g:
        return True
    if user_id:
        ug = caps.user_filter_for_bot(platform, bot_id, chat_id, user_id)
        if ug is not None and TEACHER_GROUP in ug:
            return True
    return False


def can_teacher_speak(platform: str = "", bot_id: str = "", chat_id: str = "",
                      user_id: str = "", *, ctx: dict | None = None,
                      is_admin_thread: bool = False) -> bool:
    """Dạy + bật speak_to_speaker + quyền tts_speaker (filter loa Zalo/Tele)."""
    if not speak_to_speaker_enabled():
        return False
    if not can_use_teacher(platform, bot_id, chat_id, user_id, ctx=ctx):
        return False
    if ctx:
        platform, bot_id, chat_id, user_id = _ctx_ids(ctx)
        is_admin_thread = bool(ctx.get("is_admin_thread") or is_admin_thread)
    from services.voice import permissions as vperm
    return vperm.can_use_speakers(
        platform, bot_id, chat_id, user_id, is_admin_thread=is_admin_thread)


def status_public() -> dict[str, Any]:
    out = {
        "enabled": is_enabled(),
        "voice_vi": voice_vi(),
        "voice_en": voice_en(),
        "speak_to_speaker": speak_to_speaker_enabled(),
        "default_speaker": default_speaker(),
        "model_speak": model_speak(),
        "model_write": model_write(),
        "english_models": _english_models(),
        "english_skills": [
            {"id": sk, "label": ENGLISH_SKILL_LABELS[sk], "model": model_for_english_skill(sk)}
            for sk in ENGLISH_SKILLS
        ],
        "group": TEACHER_GROUP,
        "skills": sorted(TEACHER_SKILLS),
        "workflows": sorted(TEACHER_WORKFLOWS),
        "pedagogy": {
            "method": "socratic_scaffold",
            "phases": list(LESSON_PHASES),
            "hint_levels": 3,
            "no_answer_dump": True,
        },
    }
    try:
        from services.agent import teacher_workspace as tw
        out["kb"] = tw.status_public()
    except Exception:
        out["kb"] = {}
    return out


# ── Sư phạm lớp học (Socratic · scaffold · formative) ──────────────────────
# Tham chiếu: Bloom 1-to-1 tutoring; ITS Socratic (Khanmigo-style); formative CFU.

LESSON_PHASES = (
    "muc_tieu",      # I can… / mục tiêu 1 câu
    "khoi_dong",     # warm-up / nối kiến thức cũ
    "giang",         # I do → We do (Socratic)
    "luyen",         # You do + gợi ý bậc thang
    "kiem_tra",      # CFU / exit ticket
    "ket",           # tóm tắt + về nhà + memory
)

_MATH_VERBAL = (
    (re.compile(r"\s*×\s*|\s*x\s+(?=\d)", re.I), " nhân "),
    (re.compile(r"\s*÷\s*"), " chia "),
    (re.compile(r"\s*=\s*"), " bằng "),
    (re.compile(r"\s*\+\s*"), " cộng "),
    (re.compile(r"\s*−\s*|\s*–\s*|\s*—\s*"), " trừ "),
    (re.compile(r"\s*%\s*"), " phần trăm "),
    (re.compile(r"\s*≠\s*"), " khác "),
    (re.compile(r"\s*≤\s*"), " nhỏ hơn hoặc bằng "),
    (re.compile(r"\s*≥\s*"), " lớn hơn hoặc bằng "),
    (re.compile(r"\s*<\s*"), " nhỏ hơn "),
    (re.compile(r"\s*>\s*"), " lớn hơn "),
    (re.compile(r"\s*²"), " bình phương"),
    (re.compile(r"\s*³"), " lập phương"),
    (re.compile(r"[#*_`]+"), " "),
)


def skill_for_grade(grade: int) -> str:
    g = int(grade or 0)
    if g <= 5:
        return "giao-vien-tieu-hoc"
    if g <= 9:
        return "giao-vien-thcs"
    return "giao-vien-thpt"


def verbalize_for_tts(text: str) -> str:
    """Chuyển ký hiệu toán/markdown thành lời — sẵn sàng đọc loa."""
    t = (text or "").strip()
    if not t:
        return ""
    for pat, rep in _MATH_VERBAL:
        t = pat.sub(rep, t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


def praise_for(score_0_10: int, *, grade: int = 5) -> str:
    """Lời khen ngắn theo điểm — growth mindset, không mắng."""
    s = max(0, min(10, int(score_0_10)))
    if grade <= 5:
        if s >= 9:
            return "Giỏi lắm! Con làm chắc tay rồi."
        if s >= 7:
            return "Tốt lắm! Gần đạt điểm tuyệt đối rồi."
        if s >= 5:
            return "Cố gắng tốt! Cô/thầy cùng con chỉnh chỗ còn lệch nhé."
        return "Không sao, lỗi là bạn của người học. Mình thử lại từng bước nhé."
    if s >= 9:
        return "Rất tốt — nắm vững dạng này."
    if s >= 7:
        return "Khá ổn; còn 1–2 chỗ tinh chỉnh là xuất sắc."
    if s >= 5:
        return "Đã có hướng đúng; cần bổ sung bước / ý cho đủ."
    return "Chưa đạt lần này — mình khoanh lỗi và luyện lại 1 dạng tương tự."


def build_lesson_plan(
    *,
    grade: int,
    subject: str,
    topic: str,
    objective: str = "",
    student_weak: str = "",
    level_note: str = "",
) -> str:
    """Giáo án 6 pha kiểu lớp học (mục tiêu → kết), markdown ngắn cho agent."""
    from services.agent import teacher_workspace as tw

    g = int(grade) if int(grade) in tw.GRADES else 5
    sub = tw._normalize_subject(subject) or "toan"
    topic = (topic or "ôn tập").strip()
    obj = (objective or "").strip() or f"Nắm được ý chính: {topic}"
    skill = skill_for_grade(g)
    level = tw.level_label(g)
    lines = [
        f"**Giáo án lớp học** · Lớp {g} ({level}) · {tw.SUBJECT_LABEL.get(sub, sub)}",
        f"Skill gợi ý: `{skill}`",
        f"**Mục tiêu (I can…):** {obj}",
        f"**Chủ đề:** {topic}",
    ]
    if student_weak:
        lines.append(f"**Lưu ý từ memory HS:** còn yếu — {student_weak}")
    if level_note:
        lines.append(f"**Ghi chú cấp học:** {level_note}")
    lines.extend([
        "",
        "### 1) Mục tiêu (30s)",
        f"- Nói rõ 1 câu: hôm nay em/con sẽ… «{obj}».",
        "- Không nhồi nhiều ý.",
        "",
        "### 2) Khởi động (1–2 phút)",
        "- 1 câu nối kiến thức cũ / ví dụ đời sống gần gũi.",
        "- Hỏi HS nhớ gì liên quan (Socratic, chưa giảng).",
        "",
        "### 3) Giảng — I do → We do",
        "- **I do:** 1 ví dụ mẫu, nêu từng bước (không nhảy bước).",
        "- **We do:** 1 bài cùng làm; hỏi «bước tiếp theo là gì?» trước khi chốt.",
        "- Dùng **search_sgk** lấy khung kiến thức; không bịa trang SGK.",
        "",
        "### 4) Luyện — You do + gợi ý bậc thang",
        "- HS tự làm 1 bài tương tự.",
        "- Kẹt: **teacher_hint** level=1 rồi 2 rồi 3 (không đập đáp án ngay).",
        "",
        "### 5) Kiểm tra hiểu (CFU)",
        "- **teacher_check** 1 câu exit ticket HOẶC 1 câu miệng «nhắc lại giúp…».",
        "- Đúng → khen cụ thể; sai → chỉ lỗi + 1 bài siêu ngắn.",
        "",
        "### 6) Kết · về nhà · memory",
        "- 2–4 câu tóm tắt (TTS-friendly, **verbalize_for_tts**).",
        "- **teacher_memory** add: weak/strong + note buổi học.",
        "- (Tuỳ chọn) schedule nhắc ôn nếu PH nhờ.",
        "",
        "_Nguyên tắc: productive struggle — HS phải nghĩ; AI/coach hỏi trước khi cho đáp án._",
    ])
    return "\n".join(lines)


def format_classroom_reply(
    *,
    phase: str,
    body: str,
    check_question: str = "",
    tts_summary: str = "",
) -> str:
    """Bọc phản hồi 1 lượt dạy: pha + nội dung + CFU + TTS gợi ý."""
    phase = (phase or "").strip() or "giang"
    parts = [f"[{phase}]"]
    if body.strip():
        parts.append(body.strip())
    if check_question.strip():
        parts.append("")
        parts.append(f"**Kiểm tra hiểu:** {check_question.strip()}")
    if tts_summary.strip():
        parts.append("")
        parts.append(f"**Đọc loa (TTS):** {verbalize_for_tts(tts_summary)}")
    return "\n".join(parts)
