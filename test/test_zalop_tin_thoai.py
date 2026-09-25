"""Zalo cá nhân: trả lời bằng giọng nói gửi thành TIN THOẠI, không phải tệp đính kèm.

Chủ máy 25/09/2026: "zalo custom có chế độ gửi ghi âm, xem có làm được để gửi TTS
như một bản ghi âm không". Trước đây giọng đọc đi bằng sendFile (tệp WAV đính kèm).
Nay gửi qua ``sendVoiceByAccount`` (zalo-server đổi sang AAC-LC 16 kHz mono như tin
ghi âm thật của Zalo và tải lên máy chủ Zalo), hỏng thì lùi về tệp như cũ.
"""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import zalo_personal as zp  # noqa: E402


def test_send_voice_goi_dung_route_va_than():
    goi = {}

    def gia(method, path, body=None, timeout=30.0):
        goi.update(method=method, path=path, body=body)
        return {"ok": True}

    with mock.patch.object(zp, "_account_for_send", lambda a="": "acc1"), \
            mock.patch.object(zp, "_request", gia), \
            mock.patch.object(zp, "ttl_luot_nay", lambda: 0):
        assert zp.send_voice("t1", "http://127.0.0.1/images/voice/a.wav", 1)["ok"]
    assert (goi["method"], goi["path"]) == ("POST", "/api/sendVoiceByAccount")
    assert goi["body"] == {"options": {"voiceUrl": "http://127.0.0.1/images/voice/a.wav"},
                           "threadId": "t1", "accountSelection": "acc1", "type": "group"}


def _tts_bat():
    from services import voice as _voice
    from services.voice import permissions as _vperm
    from services.voice import session_voice as _sv
    return [mock.patch.object(_vperm, "wants_voice_reply", lambda *a, **k: True),
            mock.patch.object(_voice, "tts_ready", lambda: True),
            mock.patch.object(_sv, "is_tts_enabled_for_session", lambda *a, **k: True),
            mock.patch.object(_voice, "speak_reply", lambda *a, **k: b"RIFFwav"),
            mock.patch.object(_voice, "cleanup_media", lambda: None)]


def _chay(tmp_path, send_voice_kq):
    gui_tep = []
    ps = _tts_bat() + [
        mock.patch.object(type(zp.config), "images_dir", new_callable=mock.PropertyMock,
                          return_value=tmp_path),
        mock.patch.object(zp, "send_voice", lambda *a, **k: send_voice_kq),
        mock.patch.object(zp, "_send_file_robust",
                          lambda *a, **k: gui_tep.append(a) or True),
    ]
    for p in ps:
        p.start()
    try:
        ok = zp._maybe_voice_reply("t1", 0, "acc", "u1", "Bây giờ là 13 giờ 32 phút")
    finally:
        for p in ps:
            p.stop()
    return ok, gui_tep


def test_tra_loi_giong_noi_gui_TIN_THOAI_truoc(tmp_path):
    ok, gui_tep = _chay(tmp_path, {"ok": True})
    assert ok and gui_tep == []            # tin thoại được thì không gửi thêm tệp


def test_tin_thoai_hong_thi_lui_ve_gui_tep(tmp_path):
    ok, gui_tep = _chay(tmp_path, {"ok": False, "error": "upload loi"})
    assert ok and len(gui_tep) == 1
