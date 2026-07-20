"""Cấu hình + quyền chế độ Giáo viên tiểu học.

Config key ``teacher`` (Settings → Giáo viên)::

    {
      "enabled": true,
      "voice_vi": "vieneu:Ngọc Linh",
      "voice_en": "kokoro:af_sky",
      "speak_to_speaker": false,
      "default_speaker": ""
    }

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
        "group": TEACHER_GROUP,
        "skills": sorted(TEACHER_SKILLS),
        "workflows": sorted(TEACHER_WORKFLOWS),
    }
    try:
        from services.agent import teacher_workspace as tw
        out["kb"] = tw.status_public()
    except Exception:
        out["kb"] = {}
    return out
