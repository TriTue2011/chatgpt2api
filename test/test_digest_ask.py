"""Tin THÔNG BÁO có khối <<<ASK>>> (vd người lạ ở camera) — 24/09/2026.

Chủ máy chụp tin người lạ hiện nguyên "<<<ASK>>> … <<<END>>>" trên Zalo: đường
thông báo gửi thẳng văn bản, không qua ask_choices như đường trả lời chat.
"""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import digest  # noqa: E402
from services.agent import ask_choices  # noqa: E402

TIN = "\n".join([
    "👤 Người lạ ở Cam cửa lúc 13:56.",
    "Đây là ai ạ?",
    "<<<ASK>>>",
    "Là vợ tôi | mặt lạ 3816b235ad0b là vợ tôi",
    "Để sau | để sau hỏi lại về mặt lạ 3816b235ad0b",
    "<<<END>>>",
])


def setup_function(_f):
    ask_choices._reset_for_tests()


def test_zalo_bot_so_thu_tu_va_tra_loi_so_thanh_dung_lenh():
    from services import zalo_bot as zb

    gui: list[str] = []
    with mock.patch.object(zb, "send_photo", lambda chat, url, cap: gui.append(cap) or {"ok": True}):
        assert digest.send_target("zalo::12345", TIN, "http://x/a.jpg")
    assert "<<<" not in gui[0] and "1. Là vợ tôi" in gui[0]
    khoa = zb._skey_zalo("12345", "12345", False)
    assert ask_choices.resolve_reply(khoa, "1") == "mặt lạ 3816b235ad0b là vợ tôi"


def test_telegram_gan_nut_va_chu_di_tin_rieng_khi_co_anh():
    from services import telegram_bot as tg

    anh: list[str] = []
    tin: list[tuple[str, dict]] = []
    with mock.patch.object(tg, "_fetch_image_bytes", lambda url: b"jpg"), \
            mock.patch.object(tg, "send_photo", lambda chat, b, cap: anh.append(cap) or {"ok": True}), \
            mock.patch.object(tg, "send_message",
                              lambda chat, text, reply_markup=None: tin.append((text, reply_markup)) or {"ok": True}):
        assert digest.send_target("tg::777", TIN, "http://x/a.jpg")
    assert anh == [""]                                  # ảnh không kèm chú thích
    text, nut = tin[0]
    assert "<<<" not in text and nut["inline_keyboard"][0][0]["callback_data"] == "ask:0"
    assert ask_choices.resolve_reply(tg.khoa_phien("777", ""), "2") == \
        "để sau hỏi lại về mặt lạ 3816b235ad0b"


def test_tin_khong_co_ask_giu_nguyen():
    from services import zalo_bot as zb

    gui: list[str] = []
    with mock.patch.object(zb, "send_message", lambda chat, text: gui.append(text) or {"ok": True}):
        assert digest.send_target("zalo::12345", "🏠 Vợ tôi vừa về.")
    assert gui == ["🏠 Vợ tôi vừa về."]
