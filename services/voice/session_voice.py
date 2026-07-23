"""Cấu hình STT & TTS độc lập theo từng Kênh, Bot, Admin, Nhóm, User, User-trong-nhóm.

Lưu tại: DATA_DIR/voice_sessions.json
Phân giải theo thứ tự ưu tiên:
  1. Key User-trong-nhóm:  {platform}:{bot_id}:{chat_id}:{user_id}
  2. Key Nhóm / Chat 1-1:  {platform}:{bot_id}:{chat_id}
  3. Key Cấp Bot:          {platform}:{bot_id}
  4. Key Cấp Kênh:         {platform}
  5. Mặc định hệ thống:    config.get("voice")
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from services.config import DATA_DIR, config
from services.voice import config as vcfg

logger = logging.getLogger(__name__)

_PATH = Path(DATA_DIR) / "voice_sessions.json"
_LOCK = threading.Lock()


def _load_data() -> dict[str, dict[str, Any]]:
    try:
        if _PATH.is_file():
            raw = json.loads(_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    except Exception as exc:
        logger.warning("session_voice load: %s", exc)
    return {}


def _save_data(data: dict[str, dict[str, Any]]) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_PATH)
    except Exception as exc:
        logger.warning("session_voice save: %s", exc)


def _candidate_keys(session_id: str) -> list[str]:
    """Tạo danh sách key từ cụ thể nhất đến tổng quát để fallback."""
    sid = str(session_id or "").strip()
    if not sid:
        return []

    keys: list[str] = [sid]
    parts = sid.split(":")

    # Nếu key dạng full: platform:bot_id:chat_id:user_id
    if len(parts) == 4:
        keys.append(f"{parts[0]}:{parts[1]}:{parts[2]}")  # platform:bot_id:chat_id
        keys.append(f"{parts[0]}:{parts[1]}")             # platform:bot_id
        keys.append(parts[0])                              # platform
    elif len(parts) == 3:
        keys.append(f"{parts[0]}:{parts[1]}")             # platform:bot_id
        keys.append(parts[0])                              # platform
    elif len(parts) == 2:
        keys.append(parts[0])                              # platform

    # Uniq preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq


def get_session_voice_config(session_id: str) -> dict[str, Any]:
    """Lấy cấu hình STT & TTS được gán riêng cho session (User / Group / Bot / Channel)."""
    with _LOCK:
        data = _load_data()

    for key in _candidate_keys(session_id):
        if key in data:
            return dict(data[key])
    return {}


def get_tts_voice_for_session(session_id: str, default: str = "") -> str:
    """Trả voice TTS cho session (nếu có riêng, ngược lại trả default/hệ thống)."""
    cfg_s = get_session_voice_config(session_id)
    voice = str(cfg_s.get("tts_voice") or "").strip()
    if voice:
        return voice
    return default or vcfg.tts_voice()


def get_stt_config_for_session(session_id: str) -> dict[str, str]:
    """Trả cấu hình STT cho session: {language, engine, backend}."""
    cfg_s = get_session_voice_config(session_id)
    return {
        "language": str(cfg_s.get("stt_language") or vcfg.stt_language()).strip(),
        "engine": str(cfg_s.get("stt_engine") or "auto").strip(),
        "backend": str(cfg_s.get("stt_backend") or vcfg.stt_backend()).strip(),
    }


def set_session_voice_config(
    session_id: str,
    *,
    tts_voice: str = "",
    tts_backend: str = "",
    stt_language: str = "",
    stt_engine: str = "",
    stt_backend: str = "",
) -> dict[str, Any]:
    """Cài đặt TTS & STT riêng cho 1 session (User/Nhóm/Bot/Kênh)."""
    sid = str(session_id or "").strip()
    if not sid:
        return {"ok": False, "error": "Thiếu session_id"}

    with _LOCK:
        data = _load_data()
        prev = data.get(sid) or {}

        updated = {**prev}
        if tts_voice:
            updated["tts_voice"] = tts_voice.strip()
        if tts_backend:
            updated["tts_backend"] = tts_backend.strip()
        if stt_language:
            updated["stt_language"] = stt_language.strip()
        if stt_engine:
            updated["stt_engine"] = stt_engine.strip()
        if stt_backend:
            updated["stt_backend"] = stt_backend.strip()

        data[sid] = updated
        _save_data(data)

    return {"ok": True, "key": sid, "config": updated}


def clear_session_voice_config(session_id: str) -> bool:
    """Xoá cấu hình riêng của session."""
    sid = str(session_id or "").strip()
    if not sid:
        return False
    with _LOCK:
        data = _load_data()
        had = sid in data
        data.pop(sid, None)
        _save_data(data)
    return had


def list_all_session_voices() -> list[dict[str, Any]]:
    """Liệt kê toàn bộ session có cấu hình TTS/STT riêng."""
    with _LOCK:
        data = _load_data()
    return [{"key": k, "config": v} for k, v in sorted(data.items())]
