"""Giọng cài theo phiên (Cài đặt → Giọng theo phiên) thắng giọng persona.

26/09/2026: persona luôn tự chọn giọng VieNeu theo giới tính và ĐÈ giọng cài theo phiên —
chủ máy muốn Zalo dùng ZeroTTS (nhẹ ~1,5 GB RAM) mà cài đặt không có tác dụng."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import voice as _voice  # noqa: E402
from services.agent import persona as _persona  # noqa: E402
from services.voice import session_voice as _sv  # noqa: E402


def _goi(cau_hinh_phien: dict) -> str:
    dung: list[str] = []
    with mock.patch.object(_sv, "get_session_voice_config", return_value=cau_hinh_phien), \
            mock.patch.object(_persona, "voice_for", return_value={"voice": "vieneu:Trúc Ly", "style": "tu_nhien"}), \
            mock.patch.object(_voice, "speak", lambda text, v, style="": dung.append(v) or b"RIFF"):
        _voice.speak_reply("Chào anh", "zalop_1:u1", session_id="zalop:bot:1:1")
    return dung[0]


def test_giong_phien_thang_persona():
    assert _goi({"tts_voice": "zerotts:maichi"}) == "zerotts:maichi"


def test_khong_cai_phien_thi_theo_persona():
    assert _goi({}) == "vieneu:Trúc Ly"
