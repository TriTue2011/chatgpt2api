"""A failed notification must leave the email eligible for the next IMAP poll."""

from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import digest, email_channel  # noqa: E402


_RAW = (
    b"From: sender@example.test\r\n"
    b"Subject: hello\r\n"
    b"Message-ID: <retry-test@example.test>\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
    b"hello from the test\r\n"
)


class EmailDeliveryRetryTests(unittest.TestCase):
    def _account(self) -> dict:
        return {
            "id": "retry", "allowed_senders": ["*"], "max_body_chars": 6000,
            "summarize_files": False, "notify_targets": ["tg:123"],
            "notify_on_new": True, "notify_times": [], "reply_enabled": False,
        }

    def test_failed_notification_does_not_consume_message_id(self) -> None:
        with mock.patch.object(digest, "seen", return_value=False), \
                mock.patch.object(digest, "mark_seen") as mark, \
                mock.patch.object(digest, "notify", side_effect=RuntimeError("network down")):
            result = email_channel._process_message(self._account(), _RAW)
        self.assertEqual(result, "error")
        mark.assert_not_called()

    def test_successful_notification_consumes_message_id(self) -> None:
        with mock.patch.object(digest, "seen", return_value=False), \
                mock.patch.object(digest, "mark_seen") as mark, \
                mock.patch.object(digest, "notify", return_value={"sent_now": 1, "queued": False}):
            result = email_channel._process_message(self._account(), _RAW)
        self.assertEqual(result, "processed")
        # Hai mốc: bước THÔNG BÁO xong, rồi cả lá thư xong.
        self.assertEqual(
            [c.args for c in mark.call_args_list],
            [("email:retry", "<retry-test@example.test>:notify"),
             ("email:retry", "<retry-test@example.test>")],
        )

    def test_khong_bao_lai_khi_luot_truoc_da_bao_duoc(self) -> None:
        """Bước sau hỏng thì mail ở lại hộp UNSEEN — không được báo trùng.

        Bỏ mốc chung để mail không mất là đúng, nhưng nếu THÔNG BÁO đã tới nơi
        rồi mà bước trả lời còn hỏng thì mỗi lượt poll lại bắn thêm một tin cho
        cùng lá thư. Mốc riêng cho bước thông báo cắt đúng chuyện đó.
        """
        da_bao = "<retry-test@example.test>:notify"

        with mock.patch.object(digest, "seen", side_effect=lambda _s, u: u == da_bao), \
                mock.patch.object(digest, "mark_seen") as mark, \
                mock.patch.object(digest, "notify") as notify:
            result = email_channel._process_message(self._account(), _RAW)

        notify.assert_not_called()
        self.assertEqual(result, "processed")
        mark.assert_called_once_with("email:retry", "<retry-test@example.test>")


if __name__ == "__main__":
    unittest.main()
