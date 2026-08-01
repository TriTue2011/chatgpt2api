"""Lịch nghỉ VN (`le_tet_vn`) + bộ tính lần-kế-tiếp (`lich_lap`).

Hai module thuần (chỉ datetime + đổi âm–dương), tách khỏi DB nên test được độc
lập. Khoá lại đúng ca người dùng cần 01/08: nhắc check-in/check-out lặp theo thứ
trong tuần, BỎ ngày lễ / Tết / nghỉ bù — thứ mà công cụ nhắc cũ không làm được
(chỉ có once/interval/daily), khiến bot phải trả lời "hệ thống chưa nhận đúng
lịch lặp hằng tuần/trừ lễ Tết".
"""
from __future__ import annotations

import datetime as dt
import unittest
from zoneinfo import ZoneInfo

from services import le_tet_vn as le
from services import lich_lap as L

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def _d(y, m, d, h=0, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=TZ)


class TestLichNghi(unittest.TestCase):
    def test_tet_binh_ngo_mung_1(self):
        # Tết 2026 mùng 1 = 17/2/2026 (đã kiểm với lịch thật).
        self.assertTrue(le.la_ngay_nghi(dt.date(2026, 2, 17)))
        self.assertEqual(le.ten_ngay_nghi(dt.date(2026, 2, 17)), "Mùng 1 Tết")

    def test_le_duong_co_dinh(self):
        for d in (dt.date(2026, 1, 1), dt.date(2026, 4, 30),
                  dt.date(2026, 5, 1), dt.date(2026, 9, 2)):
            self.assertTrue(le.la_ngay_nghi(d), d)

    def test_gio_to_roi_cuoi_tuan_thi_nghi_bu(self):
        # Giỗ Tổ (10/3 âm) 2026 = CN 26/4 → nghỉ bù T2 27/4.
        self.assertTrue(le.la_ngay_nghi(dt.date(2026, 4, 26)))
        self.assertTrue(le.la_ngay_nghi(dt.date(2026, 4, 27), {le.BU}))
        self.assertIn("Nghỉ bù", le.ten_ngay_nghi(dt.date(2026, 4, 27)))

    def test_ngay_thuong_khong_nghi(self):
        self.assertFalse(le.la_ngay_nghi(dt.date(2026, 8, 15)))

    def test_loc_theo_danh_muc(self):
        # 30/4 là lễ dương, KHÔNG thuộc Tết.
        self.assertTrue(le.la_ngay_nghi(dt.date(2026, 4, 30), {le.LE}))
        self.assertFalse(le.la_ngay_nghi(dt.date(2026, 4, 30), {le.TET}))


class TestLichLap(unittest.TestCase):
    def _lan_ke(self, spec, after):
        return L.next_run(spec, after, TZ)

    def test_duoi_mot_ngay_la_khoang_deu(self):
        n = self._lan_ke({"unit": "hour", "n": 2}, _d(2026, 8, 1, 10, 0))
        self.assertEqual(n, _d(2026, 8, 1, 12, 0))

    def test_check_out_t2_t6_tru_le(self):
        """Ca người dùng thật: T2–T6 17:30, bỏ lễ. Sau 29/4 (T4) phải nhảy qua
        30/4, 1/5 (lễ) và cuối tuần → 4/5 (T2)."""
        spec = {"unit": "week", "hour": 17, "minute": 30,
                "weekdays": [0, 1, 2, 3, 4], "skip": ["le", "tet", "bu"]}
        n = self._lan_ke(spec, _d(2026, 4, 29, 18, 0))
        self.assertEqual(n.date(), dt.date(2026, 5, 4))
        self.assertEqual((n.hour, n.minute), (17, 30))

    def test_check_in_gom_thu_bay(self):
        spec = {"unit": "week", "hour": 7, "minute": 58,
                "weekdays": [0, 1, 2, 3, 4, 5]}
        n = self._lan_ke(spec, _d(2026, 8, 1, 12, 0))  # 1/8 là T7
        self.assertEqual(n.date(), dt.date(2026, 8, 3))  # T7 1/8 đã 12h > 7:58 → T2 3/8

    def test_moi_2_tuan_dung_cach_14_ngay(self):
        spec = {"unit": "week", "n": 2, "hour": 9, "weekdays": [0],
                "anchor": "2026-08-03"}
        a = self._lan_ke(spec, _d(2026, 8, 1))
        b = self._lan_ke(spec, a)
        self.assertEqual(a.date(), dt.date(2026, 8, 3))
        self.assertEqual((b.date() - a.date()).days, 14)

    def test_hang_thang_ngay_31_kep_cuoi_thang(self):
        n = self._lan_ke({"unit": "month", "day": 31, "hour": 8}, _d(2026, 2, 1))
        self.assertEqual(n.date(), dt.date(2026, 2, 28))

    def test_hang_nam_giu_thang_ngay(self):
        spec = {"unit": "year", "day": 2, "month": 9, "hour": 8}
        a = self._lan_ke(spec, _d(2026, 1, 1))
        b = self._lan_ke(spec, a)
        self.assertEqual(a.date(), dt.date(2026, 9, 2))
        self.assertEqual(b.date(), dt.date(2027, 9, 2))

    def test_bo_loc_qua_hep_khong_treo(self):
        """weekdays rỗng-nghĩa + skip mọi ngày không được lặp vô hạn."""
        # thứ không tồn tại → dò hết trần rồi trả None, không treo.
        spec = {"unit": "week", "hour": 9, "weekdays": [9]}
        self.assertIsNone(self._lan_ke(spec, _d(2026, 8, 1)))

    def test_don_vi_la_thi_None(self):
        self.assertIsNone(self._lan_ke({"unit": "thap_ky"}, _d(2026, 8, 1)))


if __name__ == "__main__":
    unittest.main()
