"""Lệnh admin đặt nhắc vào một Zalo Personal thread khác.

Ca thật 16/08/2026: câu có ``thread ID`` bị đưa vào LLM, rồi bị trả về một
bản tin Home Assistant thay vì tạo lịch cho Mạnh Hùng.  Đây là lệnh có đích
xác định, nên phải được xử lý quyết định (không phụ thuộc model).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import admin_reminders  # noqa: E402
from services.agent import reminders as rem  # noqa: E402
from services.config import config  # noqa: E402


TZ = ZoneInfo("Asia/Ho_Chi_Minh")
TARGET = "2865804596405023486"
NOW = dt.datetime(2026, 8, 16, 0, 41, tzinfo=TZ)


class TestAdminTargetReminder(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        rem._reset_for_tests(Path(self._tmp.name) / "reminders.sqlite")
        self._cfg = mock.patch.dict(
            config.data, {"agent_reminders": {"enabled": True, "tick_seconds": 5}},
        )
        self._cfg.start()

    def tearDown(self) -> None:
        self._cfg.stop()
        rem._reset_for_tests()
        self._tmp.cleanup()

    def test_dat_dung_thread_ba_moc_va_thay_lich_cu_mot_moc(self) -> None:
        """Lệnh thật phải tạo MỘT lịch đúng đích, không qua LLM/HA fast-path."""
        old_schedule = rem.parse_when(
            "", unit="month", day_of_month=1, at="20:10", now=NOW,
        )
        assert old_schedule is not None
        old = rem.create(
            f"zalop_{TARGET}", "Đảo công tơ điện", old_schedule,
            meta_extra={"account": "fw-nghe", "thread_type": 0},
        )

        reply = admin_reminders.handle_zalop_admin_reminder(
            "nhắc Mạnh hùng thread ID 2865804596405023486 3 lần "
            "Mùng 1 hàng tháng vào 10h, 15h và 21h nội dung đảo công tơ điện",
            account_id="fw-nghe", now=NOW,
        )

        self.assertIsNotNone(reply)
        self.assertIn(TARGET, reply or "")
        self.assertIn("10:00, 15:00, 21:00", reply or "")

        active = rem.list_for(f"zalop_{TARGET}")
        self.assertEqual(len(active), 1)
        spec = json.loads(active[0]["rrule"])
        self.assertEqual(spec["unit"], "month")
        self.assertEqual(spec["day"], 1)
        self.assertEqual(spec["times"], [[10, 0], [15, 0], [21, 0]])
        self.assertEqual(json.loads(active[0]["meta"]),
                         {"account": "fw-nghe", "thread_type": 0})

        rows = rem.list_for(f"zalop_{TARGET}", include_disabled=True)
        old_row = next(row for row in rows if row["id"] == old["id"])
        self.assertEqual(old_row["enabled"], 0)

    def test_thread_dich_la_NHOM_thi_luu_thread_type_1(self) -> None:
        """Đóng đinh thread_type=0 là nhắc gửi sai loại thread — chỉ lộ ra lúc bắn."""
        from services import channel_contacts as cc

        key = cc.contact_key("zalop", "fw-nghe", TARGET)
        with mock.patch.object(cc, "get", side_effect=lambda k: (
                {"kind": "group"} if k == key else None)):
            reply = admin_reminders.handle_zalop_admin_reminder(
                "nhắc nhóm Xưởng thread ID 2865804596405023486 mùng 5 hàng tháng "
                "vào 8h nội dung kiểm kho", account_id="fw-nghe", now=NOW)

        self.assertIn("nhóm", reply or "")
        row = rem.list_for(f"zalop_{TARGET}")[0]
        self.assertEqual(json.loads(row["meta"])["thread_type"], 1)

    def test_gio_nam_trong_NOI_DUNG_khong_thanh_moc_nhac(self) -> None:
        """"nội dung: gọi khách lúc 8h" không được đẻ thêm một mốc 8h."""
        admin_reminders.handle_zalop_admin_reminder(
            "nhắc Mạnh Hùng thread ID 2865804596405023486 mùng 1 hàng tháng "
            "vào 10h và 15h nội dung gọi khách lúc 8h",
            account_id="fw-nghe", now=NOW)

        spec = json.loads(rem.list_for(f"zalop_{TARGET}")[0]["rrule"])
        self.assertEqual(spec["times"], [[10, 0], [15, 0]])

    def test_cau_HOI_ve_lich_khong_bi_nhanh_tao_lich_chiem(self) -> None:
        """Nhánh này chỉ biết TẠO; câu xem/huỷ phải để đường cũ xử lý."""
        for cau in ("xem lịch nhắc của thread ID 2865804596405023486",
                    "huỷ lịch nhắc thread ID 2865804596405023486",
                    "liệt kê lịch nhắc thread ID 2865804596405023486"):
            self.assertIsNone(
                admin_reminders.handle_zalop_admin_reminder(
                    cau, account_id="fw-nghe", now=NOW), cau)

    def test_cau_khong_co_thread_id_khong_bi_chiem_lay(self) -> None:
        self.assertIsNone(admin_reminders.handle_zalop_admin_reminder(
            "nhắc Mạnh Hùng mùng 1 hàng tháng lúc 10h", account_id="fw-nghe", now=NOW,
        ))

    def test_ingress_admin_chay_lenh_truoc_khi_goi_llm(self) -> None:
        """Đường webhook không được phép lại rơi xuống Home Assistant/LLM."""
        import services.agent as agent_pkg
        from services import admin_workspace, zalo_personal as zp
        from services.agent import capabilities as caps

        event = {
            "msg_id": "admin-reminder-1", "thread_id": "admin-thread",
            "thread_type": 0,
            "text": ("nhắc Mạnh hùng thread ID 2865804596405023486 3 lần "
                     "Mùng 1 hàng tháng vào 10h, 15h và 21h nội dung đảo công tơ điện"),
            "account_id": "fw-nghe", "sender_id": "admin-user",
            "display_name": "Nguyễn Việt", "mentions": [],
        }
        sent: list[str] = []

        with mock.patch.object(caps, "allowed_groups_for_member", return_value=None), \
             mock.patch.object(caps, "duoc_giao_tiep", return_value=True), \
             mock.patch.object(caps, "mention_required_for", return_value=(False, "")), \
             mock.patch.object(zp, "_chat_ids", return_value=["admin-thread"]), \
             mock.patch.object(zp, "_is_admin_thread", return_value=True), \
             mock.patch.object(zp, "_la_admin_nguoi_gui", return_value=True), \
             mock.patch.object(admin_workspace, "handle_admin_text", return_value=None), \
             mock.patch.object(zp, "send_message",
                               side_effect=lambda _id, text, *_a, **_k: sent.append(text)), \
             mock.patch.object(agent_pkg, "orchestrate",
                               side_effect=AssertionError("lệnh thread ID không được gọi LLM")):
            zp._process_ai(event)

        self.assertTrue(sent)
        self.assertIn("10:00, 15:00, 21:00", sent[0])
        self.assertEqual(len(rem.list_for(f"zalop_{TARGET}")), 1)


if __name__ == "__main__":
    unittest.main()
