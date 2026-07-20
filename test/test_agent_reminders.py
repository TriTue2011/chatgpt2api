"""Unit tests for agent reminders parse + store + fire (no live bots)."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import reminders as rem  # noqa: E402
from services.config import config  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:
    _TZ = timezone(timedelta(hours=7))


class ParseWhenTests(unittest.TestCase):
    def setUp(self) -> None:
        # Fixed "now": 2026-07-18 10:00 VN
        self.now = datetime(2026, 7, 18, 10, 0, 0, tzinfo=_TZ)

    def test_in_minutes_structured(self) -> None:
        s = rem.parse_when("", in_minutes=30, now=self.now)
        assert s is not None
        self.assertEqual(s["kind"], "once")
        due = datetime.fromtimestamp(s["next_run_at"], _TZ)
        self.assertEqual(due.hour, 10)
        self.assertEqual(due.minute, 30)

    def test_after_30_phut_text(self) -> None:
        s = rem.parse_when("sau 30 phút", now=self.now)
        assert s is not None
        self.assertEqual(s["kind"], "once")
        delta = s["next_run_at"] - self.now.timestamp()
        self.assertAlmostEqual(delta, 30 * 60, delta=2)

    def test_after_2_gio(self) -> None:
        s = rem.parse_when("sau 2 giờ", now=self.now)
        assert s is not None
        delta = s["next_run_at"] - self.now.timestamp()
        self.assertAlmostEqual(delta, 2 * 3600, delta=2)

    def test_every_minutes(self) -> None:
        s = rem.parse_when("mỗi 15 phút kiểm tra", now=self.now)
        assert s is not None
        self.assertEqual(s["kind"], "interval")
        self.assertEqual(s["interval_min"], 15)

    def test_every_minutes_floor_5(self) -> None:
        s = rem.parse_when("", every_minutes=2, now=self.now)
        assert s is not None
        self.assertEqual(s["interval_min"], 5)

    def test_daily_7h(self) -> None:
        s = rem.parse_when("mỗi ngày 7h", now=self.now)
        assert s is not None
        self.assertEqual(s["kind"], "daily")
        self.assertEqual(s["hour"], 7)
        # 10:00 now → next is tomorrow 07:00
        due = datetime.fromtimestamp(s["next_run_at"], _TZ)
        self.assertEqual(due.day, 19)
        self.assertEqual(due.hour, 7)

    def test_every_day_at_structured(self) -> None:
        s = rem.parse_when("", every_day_at="07:30", now=self.now)
        assert s is not None
        self.assertEqual(s["kind"], "daily")
        self.assertEqual(s["hour"], 7)
        self.assertEqual(s["minute"], 30)

    def test_absolute_tonight(self) -> None:
        s = rem.parse_when("19:30", now=self.now)
        assert s is not None
        due = datetime.fromtimestamp(s["next_run_at"], _TZ)
        self.assertEqual(due.hour, 19)
        self.assertEqual(due.minute, 30)
        self.assertEqual(due.day, 18)

    def test_mai_7h(self) -> None:
        s = rem.parse_when("mai 7h sáng", now=self.now)
        assert s is not None
        due = datetime.fromtimestamp(s["next_run_at"], _TZ)
        self.assertEqual(due.day, 19)
        self.assertEqual(due.hour, 7)

    def test_unparseable(self) -> None:
        self.assertIsNone(rem.parse_when("khi nào rảnh", now=self.now))


class ReminderStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        db = Path(self._tmp.name) / "reminders.sqlite"
        rem._reset_for_tests(db)
        self._cfg = mock.patch.dict(
            config.data, {"agent_reminders": {"enabled": True, "tick_seconds": 5}},
        )
        self._cfg.start()

    def tearDown(self) -> None:
        self._cfg.stop()
        rem._reset_for_tests()
        self._tmp.cleanup()

    def test_channel_of(self) -> None:
        self.assertEqual(rem.channel_of("12345"), ("tg", "12345"))
        self.assertEqual(rem.channel_of("zalo_99"), ("zalo", "99"))
        self.assertEqual(rem.channel_of("zalop_abc"), ("zalop", "abc"))

    def test_create_list_cancel(self) -> None:
        now = datetime(2026, 7, 18, 10, 0, tzinfo=_TZ)
        sched = rem.parse_when("sau 10 phút", now=now)
        assert sched is not None
        row = rem.create("zalo_42", "Uống thuốc", sched, mode="notify")
        self.assertEqual(row["channel"], "zalo")
        self.assertEqual(row["chat_id"], "42")
        rows = rem.list_for("zalo_42")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rem.cancel("zalo_42", row["id"]))
        self.assertEqual(rem.list_for("zalo_42"), [])

    def test_fire_notify_once(self) -> None:
        # due in the past
        sched = {
            "kind": "once",
            "due_at": time.time() - 5,
            "next_run_at": time.time() - 5,
        }
        row = rem.create("999", "Gọi khách A", sched, mode="notify")
        sent: list[tuple] = []

        def fake_send(channel, chat_id, text, meta=None):
            sent.append((channel, chat_id, text))

        with mock.patch.object(rem, "_send", side_effect=fake_send):
            n = rem.tick_once()
        self.assertEqual(n, 1)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], "tg")
        self.assertEqual(sent[0][1], "999")
        self.assertIn("Gọi khách A", sent[0][2])
        # once → disabled
        self.assertEqual(rem.list_for("999"), [])

    def test_fire_interval_reschedules(self) -> None:
        sched = {
            "kind": "interval",
            "interval_min": 10,
            "next_run_at": time.time() - 1,
        }
        rem.create("u_int", "ping", sched, mode="notify")
        with mock.patch.object(rem, "_send"):
            rem.tick_once()
        rows = rem.list_for("u_int")
        self.assertEqual(len(rows), 1)
        self.assertGreater(rows[0]["next_run_at"], time.time())

    def test_fire_task_mode_calls_orchestrate(self) -> None:
        sched = {
            "kind": "once",
            "due_at": time.time() - 1,
            "next_run_at": time.time() - 1,
        }
        rem.create("u_task", "Báo nhiệt độ nhà", sched, mode="task")
        sent: list[str] = []

        with mock.patch.object(
            rem, "_run_task", return_value="Nhiệt độ 28 độ."
        ), mock.patch.object(
            rem, "_send", side_effect=lambda c, i, t, m=None: sent.append(t)
        ):
            rem.tick_once()
        self.assertTrue(sent)
        self.assertIn("28 độ", sent[0])

    def test_handler_create_via_capability(self) -> None:
        from services.agent import capabilities as caps

        with mock.patch.object(
            rem, "parse_when",
            return_value={"kind": "once", "due_at": time.time() + 60,
                          "next_run_at": time.time() + 60},
        ):
            out = caps._h_schedule(
                {"op": "create", "text": "test", "in_minutes": 1},
                {"user_id": "tg_user"},
            )
        self.assertIn("đã đặt", out["text"].lower())


if __name__ == "__main__":
    unittest.main()
