"""Quyền giọng nói theo từng thread / user — tách khỏi engine cho dễ đọc.

Hai quyền RIÊNG BIỆT, đều nằm trong "Lọc chức năng theo thread" sẵn có:

  tts_reply    Bot TRẢ LỜI bằng file âm thanh trong khung chat này.
               Quy tắc user thắng nhóm: nhóm KHÔNG bật nhưng user bật →
               riêng người đó nhận âm thanh (yêu cầu 2026-07-19).

  tts_speaker  Được RA LỆNH phát ra loa trong nhà. Kèm danh sách loa được
               phép (config `thread_speaker_filters`); trống hoặc ["*"] =
               mọi loa, khi đó bot phải HỎI LẠI user chọn loa nào.

Thread admin mặc định có `tts_speaker` (chủ nhà luôn ra lệnh loa được);
`tts_reply` của admin vẫn theo tick như mọi thread.

Khoá thread giống các bộ lọc khác: 'plat:bot:chat' hoặc 'plat:chat'
(plat = tg | zalo | zalop). Khoá user thêm ':user'.
"""

from __future__ import annotations

from typing import Any

TTS_REPLY = "tts_reply"
TTS_SPEAKER = "tts_speaker"
ALL_SPEAKERS = "*"


def _cfg(key: str) -> dict[str, Any]:
    try:
        from services.config import config
        v = config.get().get(key)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _groups_for(platform: str, bot_id: str, chat_id: str) -> set[str] | None:
    from services.agent import capabilities as caps
    return caps.allowed_groups_for_bot(platform, bot_id, chat_id)


def _user_groups_for(platform: str, bot_id: str, chat_id: str,
                     user_id: str) -> set[str] | None:
    from services.agent import capabilities as caps
    return caps.user_filter_for_bot(platform, bot_id, chat_id, str(user_id or ""))


def wants_voice_reply(platform: str, bot_id: str, chat_id: str,
                      user_id: str = "") -> bool:
    """Tin trả lời cho (thread, user) này có nên gửi kèm âm thanh không?

    - Thread chưa có bản ghi lọc nào → False (không tự ý gửi voice).
    - Thread bật tts_reply → True cho mọi người trong thread.
    - Thread KHÔNG bật nhưng user bật riêng → chỉ user đó True.
    """
    group_allow = _groups_for(platform, bot_id, chat_id)
    if group_allow is not None and TTS_REPLY in group_allow:
        return True
    if user_id:
        user_allow = _user_groups_for(platform, bot_id, chat_id, user_id)
        if user_allow is not None and TTS_REPLY in user_allow:
            return True
    return False


def can_use_speakers(platform: str, bot_id: str, chat_id: str,
                     user_id: str = "", *, is_admin_thread: bool = False) -> bool:
    """Thread/user này được phép ra lệnh phát loa không? Admin thread = có."""
    if is_admin_thread:
        return True
    group_allow = _groups_for(platform, bot_id, chat_id)
    if group_allow is not None and TTS_SPEAKER in group_allow:
        return True
    if user_id:
        user_allow = _user_groups_for(platform, bot_id, chat_id, user_id)
        if user_allow is not None and TTS_SPEAKER in user_allow:
            return True
    return False


def _speaker_keys(platform: str, bot_id: str, chat_id: str,
                  user_id: str = "") -> list[str]:
    keys: list[str] = []
    bid = str(bot_id or "").strip()
    cid = str(chat_id or "").strip()
    uid = str(user_id or "").strip()
    if uid:
        if bid:
            keys.append(f"{platform}:{bid}:{cid}:{uid}")
        keys.append(f"{platform}:{cid}:{uid}")
    if bid:
        keys.append(f"{platform}:{bid}:{cid}")
    keys.append(f"{platform}:{cid}")
    return keys


def allowed_speaker_ids(platform: str, bot_id: str, chat_id: str,
                        user_id: str = "") -> list[str]:
    """Danh sách id loa được phép. ["*"] = tất cả (mặc định khi chưa cấu hình).

    Ưu tiên bản ghi cụ thể nhất: user trong bot → user → bot+chat → chat.
    """
    filters = _cfg("thread_speaker_filters")
    for key in _speaker_keys(platform, bot_id, chat_id, user_id):
        if key in filters:
            val = filters.get(key)
            if isinstance(val, list):
                ids = [str(x).strip() for x in val if str(x).strip()]
                return ids or [ALL_SPEAKERS]
    return [ALL_SPEAKERS]


def visible_speakers(platform: str, bot_id: str, chat_id: str,
                     user_id: str = "") -> list[dict[str, Any]]:
    """Loa mà thread/user này được phép phát (đã lọc theo cấu hình)."""
    from services.voice import speakers as vspk

    allowed = allowed_speaker_ids(platform, bot_id, chat_id, user_id)
    rows = vspk.list_speakers()
    if ALL_SPEAKERS in allowed:
        return rows
    keep = set(allowed)
    return [r for r in rows if str(r.get("id")) in keep]


def can_play_on(speaker_id: str, platform: str, bot_id: str, chat_id: str,
                user_id: str = "") -> bool:
    allowed = allowed_speaker_ids(platform, bot_id, chat_id, user_id)
    return ALL_SPEAKERS in allowed or str(speaker_id) in allowed
