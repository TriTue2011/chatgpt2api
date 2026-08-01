"""Nhắc hẹn lặp linh hoạt — vòng đời thật: parse → create → describe → advance.

Khoá lại đúng lỗi 01/08: người dùng nhờ đặt nhắc check-in/check-out lặp theo thứ
trong tuần, trừ lễ Tết; công cụ cũ chỉ có once/interval/daily nên bot phải trả
lời "hệ thống chưa nhận đúng lịch lặp hằng tuần/trừ lễ Tết".

Chạy trên DB SQLite tạm (không đụng dữ liệu thật). Cần phụ thuộc của services —
chạy trong container/CI, không chạy được ở môi trường thiếu deps.
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from services.agent import reminders as rem

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class _DBTam(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        rem._reset_for_tests(self.dir / "r.sqlite")
        self.now = dt.datetime(2026, 4, 29, 18, 0, tzinfo=TZ)  # T4 trước dịp 30/4

    def _next_date(self, uid):
        r = rem.list_for(uid)[0]
        return dt.datetime.fromtimestamp(r["next_run_at"], TZ).date()


class TestVongDoiRecur(_DBTam):
    def test_check_out_tru_le_ca_that(self):
        s = rem.parse_when("", unit="week", at="17:30",
                           weekdays=[0, 1, 2, 3, 4], skip=["le", "tet", "bu"],
                           now=self.now)
        self.assertEqual(s["kind"], "recur")
        row = rem.create("u1", "Check-out chấm công", s)
        # Tạo lúc 29/4 18:00 (đã qua 17:30) → 30/4, 1/5 lễ, cuối tuần → 4/5.
        self.assertEqual(self._next_date("u1"), dt.date(2026, 5, 4))
        # Mô tả đọc được cho người dùng.
        d = rem.describe(row)
        self.assertIn("hằng tuần", d)
        self.assertIn("trừ lễ", d)

    def test_advance_giu_dung_lich(self):
        s = rem.parse_when("", unit="week", at="17:30",
                           weekdays=[0, 1, 2, 3, 4], skip=["le", "tet", "bu"],
                           now=self.now)
        row = rem.create("u1", "Check-out", s)
        fire = dt.datetime(2026, 5, 4, 17, 30, tzinfo=TZ).timestamp() + 1
        rem._advance(row, fire)
        self.assertEqual(self._next_date("u1"), dt.date(2026, 5, 5))  # T3

    def test_rrule_luu_va_doc_lai(self):
        s = rem.parse_when("", unit="month", day_of_month=5, at="8:00", now=self.now)
        row = rem.create("u1", "Đóng tiền nhà", s)
        # Đọc lại từ DB → rrule không mất.
        again = rem.list_for("u1")[0]
        spec = rem._load_rrule(again)
        self.assertEqual(spec["unit"], "month")
        self.assertEqual(spec["day"], 5)
        self.assertIn("hằng tháng", rem.describe(again))

    def test_weekdays_bang_chu_tieng_viet(self):
        s = rem.parse_when("", weekdays=["T2", "thứ 4", "T6"], at="8:00", now=self.now)
        self.assertEqual(s["rrule"]["weekdays"], [0, 2, 4])

    def test_hen_mot_ngay_cu_the(self):
        s = rem.parse_when("", on_date="20/8", at="9:30", now=self.now)
        self.assertEqual(s["kind"], "once")
        got = dt.datetime.fromtimestamp(s["next_run_at"], TZ)
        self.assertEqual((got.month, got.day, got.hour, got.minute), (8, 20, 9, 30))

    def test_ngay_da_qua_khong_ghi_nam_thi_sang_nam_sau(self):
        # now = 29/4; '1/1' đã qua → 1/1 năm sau.
        s = rem.parse_when("", on_date="1/1", at="0:00", now=self.now)
        got = dt.datetime.fromtimestamp(s["next_run_at"], TZ)
        self.assertEqual(got.year, self.now.year + 1)

    def test_migration_giu_reminder_cu(self):
        # DB cũ (chưa có cột rrule) vẫn tạo/đọc được sau khi mở qua _db().
        s = rem.parse_when("sau 30 phút", now=self.now)   # kind=once, không rrule
        rem.create("u2", "việc cũ", s)
        self.assertEqual(len(rem.list_for("u2")), 1)
        self.assertIsNone(rem._load_rrule(rem.list_for("u2")[0]))


if __name__ == "__main__":
    unittest.main()
