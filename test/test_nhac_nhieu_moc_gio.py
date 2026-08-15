"""Nhắc NHIỀU LẦN trong ngày, và không tự bịa giờ khi người dùng chưa nói giờ.

Sự cố thật (đoạn chat với bot, 15/08/2026):

    "Mùng 1 hàng tháng nhắc anh đảo công tơ điện"
        → bot đặt lịch mỗi tháng lúc **20:10** — đúng phút đang gõ câu đó, một
          con số người dùng chưa từng nói.
    "Nhắc anh 3 lần vào lúc 10h , 15h và 21h"
        → bot hỏi ngược "cần nhắc việc gì" (nội dung nằm ngay lượt trên), rồi
          chốt bằng "Hiện tại em chưa tạo được lịch nhắc trong phiên này".
          Không lịch nào được đặt.

Hai nguyên nhân rời nhau:

1. Công cụ `schedule` không có đường nào diễn đạt NHIỀU mốc giờ trong một ngày —
   `at` / `every_day_at` đều là một mốc. Model không có tham số để gọi nên loay
   hoay rồi bịa ra lời từ chối.
2. `_build_rrule` thiếu giờ thì lấy `now.hour/now.minute`. Im lặng điền mặc định
   đúng vào chỗ hệ thống tự dặn "THIẾU thì HỎI, không đoán".

Chạy: .venv/bin/python -m unittest test.test_nhac_nhieu_moc_gio
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import lich_lap as L  # noqa: E402
from services.agent import capabilities as caps  # noqa: E402
from services.agent import reminders as rem  # noqa: E402
from services.config import config  # noqa: E402

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def _d(y, m, d, h=0, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=TZ)


class TestCacMocGio(unittest.TestCase):
    """`lich_lap.cac_moc_gio` — đọc mốc giờ từ spec (spec đi qua JSON của DB)."""

    def test_khong_khai_times_thi_giu_mot_moc_nhu_cu(self):
        self.assertEqual(L.cac_moc_gio({"hour": 17, "minute": 30}), [(17, 30)])

    def test_nhan_ca_cap_so_lan_chuoi(self):
        spec = {"times": [[21, 0], "10:00", "15h"], "hour": 21, "minute": 0}
        self.assertEqual(L.cac_moc_gio(spec), [(10, 0), (15, 0), (21, 0)])

    def test_bo_moc_hong_va_moc_trung(self):
        spec = {"times": [[10, 0], [10, 0], [99, 0], "linh tinh"], "hour": 10}
        self.assertEqual(L.cac_moc_gio(spec), [(10, 0)])


class TestLanKeTiepNhieuMoc(unittest.TestCase):
    """Lần bắn kế tiếp phải đi qua ĐỦ các mốc trong ngày rồi mới sang ngày sau."""

    def setUp(self):
        self.spec = {"unit": "day", "n": 1, "hour": 10, "minute": 0,
                     "times": [[10, 0], [15, 0], [21, 0]],
                     "anchor": "2026-08-15"}

    def test_giua_ngay_thi_lay_moc_con_lai_cua_hom_nay(self):
        self.assertEqual(L.next_run(self.spec, _d(2026, 8, 15, 11, 0), TZ),
                         _d(2026, 8, 15, 15, 0))

    def test_dung_ngay_moc_thi_lay_moc_ke(self):
        self.assertEqual(L.next_run(self.spec, _d(2026, 8, 15, 15, 0), TZ),
                         _d(2026, 8, 15, 21, 0))

    def test_qua_moc_cuoi_thi_sang_moc_dau_hom_sau(self):
        self.assertEqual(L.next_run(self.spec, _d(2026, 8, 15, 21, 30), TZ),
                         _d(2026, 8, 16, 10, 0))

    def test_loc_thu_van_hieu_luc(self):
        # T2–T6 ba mốc: sau 21h thứ Sáu 14/8 → 10h thứ Hai 17/8.
        spec = dict(self.spec, unit="week", weekdays=[0, 1, 2, 3, 4],
                    anchor="2026-08-14")
        self.assertEqual(L.next_run(spec, _d(2026, 8, 14, 21, 30), TZ),
                         _d(2026, 8, 17, 10, 0))

    def test_hang_thang_ba_moc(self):
        spec = {"unit": "month", "n": 1, "day": 1, "hour": 10, "minute": 0,
                "times": [[10, 0], [15, 0], [21, 0]], "anchor": "2026-08-15"}
        self.assertEqual(L.next_run(spec, _d(2026, 8, 15, 20, 0), TZ),
                         _d(2026, 9, 1, 10, 0))
        self.assertEqual(L.next_run(spec, _d(2026, 9, 1, 10, 0), TZ),
                         _d(2026, 9, 1, 15, 0))

    def test_lich_mot_moc_khong_doi_hanh_vi(self):
        spec = {"unit": "day", "n": 1, "hour": 7, "minute": 0, "anchor": "2026-08-15"}
        self.assertEqual(L.next_run(spec, _d(2026, 8, 15, 10, 0), TZ),
                         _d(2026, 8, 16, 7, 0))


class TestParseWhen(unittest.TestCase):
    def setUp(self):
        self.now = _d(2026, 8, 15, 20, 10)      # đúng phút của sự cố thật

    def test_ba_moc_gio_ra_lich_lap_hang_ngay(self):
        s = rem.parse_when("", at_times=["10h", "15h", "21h"], now=self.now)
        assert s is not None
        self.assertEqual(s["kind"], "recur")
        self.assertEqual(s["rrule"]["unit"], "day")
        self.assertEqual(s["rrule"]["times"], [[10, 0], [15, 0], [21, 0]])
        # 20:10 hôm nay → mốc 21:00 hôm nay.
        self.assertEqual(dt.datetime.fromtimestamp(s["next_run_at"], TZ),
                         _d(2026, 8, 15, 21, 0))

    def test_ba_moc_gio_hang_thang(self):
        s = rem.parse_when("", unit="month", day_of_month=1,
                           at_times=["10:00", "15:00", "21:00"], now=self.now)
        assert s is not None
        self.assertEqual(s["rrule"]["day"], 1)
        self.assertEqual(dt.datetime.fromtimestamp(s["next_run_at"], TZ),
                         _d(2026, 9, 1, 10, 0))

    def test_moc_gio_viet_kieu_tieng_viet(self):
        s = rem.parse_when("", at_times=["10 giờ", "lúc 15h", "21:00"], now=self.now)
        assert s is not None
        self.assertEqual(s["rrule"]["times"], [[10, 0], [15, 0], [21, 0]])

    def test_mot_moc_duy_nhat_thi_khong_sinh_times(self):
        s = rem.parse_when("", unit="day", at_times=["7:00"], now=self.now)
        assert s is not None
        self.assertNotIn("times", s["rrule"])
        self.assertEqual((s["rrule"]["hour"], s["rrule"]["minute"]), (7, 0))

    def test_thieu_gio_thi_bao_thieu_chu_khong_lay_gio_hien_tai(self):
        """Ca thật: "mùng 1 hàng tháng nhắc anh đảo công tơ điện" (không nói giờ)."""
        s = rem.parse_when("", unit="month", day_of_month=1, now=self.now)
        assert s is not None
        self.assertEqual(s["kind"], "thieu_gio")
        self.assertIsNone(s.get("next_run_at"))

    def test_chu_h_dinh_chu_khong_phai_gio(self):
        """"mùng 1 hàng tháng" KHÔNG được đọc thành 1 giờ — thà hỏi còn hơn nhận nhầm."""
        s = rem.parse_when("mùng 1 hàng tháng nhắc anh đảo công tơ điện",
                           unit="month", day_of_month=1, now=self.now)
        assert s is not None
        self.assertEqual(s["kind"], "thieu_gio")

    def test_gio_nam_trong_cau_tieng_viet_van_lay_duoc(self):
        s = rem.parse_when("mùng 1 hàng tháng lúc 20h", unit="month",
                           day_of_month=1, now=self.now)
        assert s is not None
        self.assertEqual(s["kind"], "recur")
        self.assertEqual(s["rrule"]["hour"], 20)

    def test_lich_lap_co_gio_van_chay_nhu_cu(self):
        s = rem.parse_when("", unit="week", at="17:30", weekdays=[0, 1, 2, 3, 4],
                           now=self.now)
        assert s is not None
        self.assertEqual(s["kind"], "recur")
        self.assertEqual(s["rrule"]["hour"], 17)


class _DBTam(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        rem._reset_for_tests(Path(self._tmp.name) / "reminders.sqlite")
        self._cfg = mock.patch.dict(
            config.data, {"agent_reminders": {"enabled": True, "tick_seconds": 5}})
        self._cfg.start()

    def tearDown(self):
        self._cfg.stop()
        rem._reset_for_tests()
        self._tmp.cleanup()


class TestVongDoiThat(_DBTam):
    """Đặt → mô tả cho người dùng → tới giờ bắn → mốc kế tiếp."""

    def test_ba_moc_di_het_ngay_roi_sang_hom_sau(self):
        s = rem.parse_when("", at_times=["10:00", "15:00", "21:00"],
                           now=_d(2026, 8, 15, 20, 10))
        row = rem.create("u1", "Đảo công tơ điện", s)
        mo_ta = rem.describe(row)
        for moc in ("10:00", "15:00", "21:00"):
            self.assertIn(moc, mo_ta, mo_ta)

        def _ke_tiep():
            r = rem.list_for("u1")[0]
            return dt.datetime.fromtimestamp(r["next_run_at"], TZ)

        self.assertEqual(_ke_tiep(), _d(2026, 8, 15, 21, 0))
        rem._advance(rem.list_for("u1")[0], _d(2026, 8, 15, 21, 0).timestamp())
        self.assertEqual(_ke_tiep(), _d(2026, 8, 16, 10, 0))
        rem._advance(rem.list_for("u1")[0], _d(2026, 8, 16, 10, 0).timestamp())
        self.assertEqual(_ke_tiep(), _d(2026, 8, 16, 15, 0))

    def test_ba_moc_chi_la_MOT_lich_de_huy_mot_lan(self):
        s = rem.parse_when("", at_times=["10:00", "15:00", "21:00"],
                           now=_d(2026, 8, 15, 20, 10))
        rem.create("u2", "Đảo công tơ điện", s)
        self.assertEqual(len(rem.list_for("u2")), 1)
        self.assertEqual(len(rem.tim_theo_ten("u2", "đảo công tơ điện")), 1)


class TestQuaCongCu(_DBTam):
    """Đúng hai câu người dùng đã gõ, đi qua handler thật."""

    def test_cau_mung_1_khong_gio_thi_HOI_gio_chu_khong_dat_lich(self):
        with mock.patch.object(rem, "_now_vn", return_value=_d(2026, 8, 15, 20, 10)):
            out = caps._h_schedule(
                {"op": "create", "text": "Đảo công tơ điện", "unit": "month",
                 "day_of_month": 1}, {"user_id": "u3"})
        self.assertIn("mấy giờ", out["text"].lower())
        self.assertNotIn("20:10", out["text"])
        self.assertEqual(rem.list_for("u3"), [], "chưa hỏi xong đã đặt lịch")

    def test_cau_nhac_3_lan_dat_duoc_lich(self):
        with mock.patch.object(rem, "_now_vn", return_value=_d(2026, 8, 15, 20, 10)):
            out = caps._h_schedule(
                {"op": "create", "text": "Đảo công tơ điện", "unit": "month",
                 "day_of_month": 1, "at_times": ["10:00", "15:00", "21:00"]},
                {"user_id": "u4"})
        self.assertIn("đã đặt", out["text"].lower())
        for moc in ("10:00", "15:00", "21:00"):
            self.assertIn(moc, out["text"], out["text"])
        self.assertEqual(len(rem.list_for("u4")), 1)


class TestCongCuKhaiBao(unittest.TestCase):
    """Model chỉ gọi được tham số nào nó THẤY trong schema."""

    def test_schema_co_at_times(self):
        cap = caps.get("schedule")
        assert cap is not None
        self.assertIn("at_times", cap.parameters["properties"])
        self.assertIn("at_times", cap.description)


if __name__ == "__main__":
    unittest.main()
