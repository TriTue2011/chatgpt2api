"""Tệp tài liệu trong mail gửi kèm bản tóm tắt tới kênh nhận (chủ máy 29/09/2026: "File trong
mail check có thể tải về và gửi qua kênh cài đặt" — chọn "chỉ tài liệu", link tải 24 giờ)."""

from __future__ import annotations

import os
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import digest, email_channel  # noqa: E402


def _thu() -> bytes:
    m = EmailMessage()
    m["From"], m["Subject"], m["Message-ID"] = "a@b.test", "Hợp đồng", "<tl@b.test>"
    m.set_content("xem tệp")
    m.add_attachment(b"%PDF-1.4 hop dong", maintype="application", subtype="pdf", filename="hop_dong.pdf")
    m.add_attachment(b"\x89PNG logo", maintype="image", subtype="png", filename="logo.png")
    return m.as_bytes()


class GuiTaiLieuTest(unittest.TestCase):
    def _acc(self) -> dict:
        return {"id": "tl", "allowed_senders": ["*"], "max_body_chars": 6000, "summarize_files": False,
                "notify_targets": ["zalo:bot1:chat9", "tg:77"], "notify_on_new": True,
                "notify_times": [], "reply_enabled": False}

    def test_chi_gui_tai_lieu_sau_khi_tom_tat_da_toi(self) -> None:
        gui: list = []
        with mock.patch.object(digest, "seen", return_value=False), \
                mock.patch.object(digest, "mark_seen"), \
                mock.patch.object(digest, "summarize", return_value="tóm tắt"), \
                mock.patch.object(digest, "notify", return_value={"sent_now": 2, "queued": False}), \
                mock.patch.object(digest, "send_file_target",
                                  side_effect=lambda t, b, ten, ghi: gui.append((t, ten, b[:4])) or True):
            self.assertEqual(email_channel._process_message(self._acc(), _thu()), "processed")
        self.assertEqual(gui, [("zalo:bot1:chat9", "hop_dong.pdf", b"%PDF"), ("tg:77", "hop_dong.pdf", b"%PDF")],
                         "ảnh logo không gửi — chỉ tài liệu")

    def test_chi_xep_lich_thi_chua_gui_tep(self) -> None:
        with mock.patch.object(digest, "seen", return_value=False), \
                mock.patch.object(digest, "mark_seen"), \
                mock.patch.object(digest, "summarize", return_value="tóm tắt"), \
                mock.patch.object(digest, "notify", return_value={"sent_now": 0, "queued": True}), \
                mock.patch.object(digest, "send_file_target") as gui:
            email_channel._process_message(self._acc(), _thu())
        gui.assert_not_called()

    def test_bot_zalo_nhan_link_tai_co_chu_ky_con_telegram_nhan_tep(self) -> None:
        from services import telegram_bot as tg, zalo_bot as zb
        from services.config import config
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(type(config), "images_dir", new=Path(d), create=True), \
                mock.patch.object(zb, "_public_base", return_value="https://nha.test"), \
                mock.patch.object(zb, "send_message", return_value={"ok": True}) as zmsg, \
                mock.patch.object(tg, "send_document", return_value={"ok": True}) as tdoc, \
                mock.patch.object(digest.threading, "Timer"):
            self.assertTrue(digest.send_file_target("zalo:chat9", b"%PDF", "Hợp đồng.pdf", "Hợp đồng"))
            chu = zmsg.call_args.args[1]
            self.assertIn("https://nha.test/images/docs/", chu)
            self.assertIn("sig=", chu)
            self.assertIn("24 giờ", chu)
            tep = [p for p in Path(d, "docs").rglob("*.pdf")]
            self.assertEqual(len(tep), 1)
            self.assertTrue((tep[0].parent / ".expire-24h").is_file())
            self.assertTrue(digest.send_file_target("tg:77", b"%PDF", "Hợp đồng.pdf", "x"))
            self.assertEqual(tdoc.call_args.args[1:3], (b"%PDF", "Hợp đồng.pdf"))
