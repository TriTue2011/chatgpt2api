"""Báo ngã — đợt thu dữ liệu (28/09/2026): giờ canh, góc thân, lần chuyển sang nằm, theo dõi, ghi sổ."""
from __future__ import annotations

import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import numpy as np
import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import bao_nga as bn  # noqa: E402

_TZ = timezone(timedelta(hours=7))


def _luc(gio: str) -> float:
    h, m = map(int, gio.split(":"))
    return datetime(2026, 9, 28, h, m, tzinfo=_TZ).timestamp()        # thứ 2


def _kp(goc_do: float, cx=500.0, hong_y=600.0, dai=150.0, tin=0.9):
    """17 điểm khớp: vai lệch khỏi phương đứng `goc_do` độ so với hông."""
    kp = np.zeros((17, 3), np.float32)
    r = np.radians(goc_do)
    vai = (cx + dai * np.sin(r), hong_y - dai * np.cos(r))
    kp[5] = kp[6] = (*vai, tin)
    kp[11] = kp[12] = (cx, hong_y, tin)
    return kp


def _nguoi(goc_do: float, cao_anh=1080):
    return ((400.0, 300.0, 600.0, 700.0), 0.9, _kp(goc_do))


class GioCanhTests(unittest.TestCase):
    def _c(self, **kw):
        return {"che_do": "nep", "khung": [], **kw}

    def test_24_24_va_khung_gio_THANG_nep_sinh_hoat(self):
        vang = [{"loai": "vang", "tu": "08:00", "den": "17:00", "thu": list(range(7))}]
        with mock.patch("services.lich_sinh_hoat.dang", lambda luc: vang):
            self.assertFalse(bn.dang_canh(self._c(), _luc("10:00")), "nếp: cả nhà vắng thì không canh")
            self.assertTrue(bn.dang_canh(self._c(che_do="24"), _luc("10:00")))
            k = self._c(che_do="khung", khung=[{"tu": "09:00", "den": "11:00"}])
            self.assertTrue(bn.dang_canh(k, _luc("10:00")))
            self.assertFalse(bn.dang_canh(k, _luc("12:00")))

    def test_nep_sinh_hoat_khong_vang_thi_canh(self):
        with mock.patch("services.lich_sinh_hoat.dang", lambda luc: [{"loai": "ngu"}]):
            self.assertTrue(bn.dang_canh(self._c(), _luc("02:00")))


class GocThanTests(unittest.TestCase):
    def test_dung_nam_va_cham_mep_duoi(self):
        self.assertLess(bn.goc_than(_kp(0), (400, 300, 600, 700), 1080), 5)
        self.assertGreater(bn.goc_than(_kp(90), (400, 300, 600, 700), 1080), 85)
        self.assertIsNone(bn.goc_than(_kp(90), (400, 300, 600, 1079), 1080),
                          "người chạm mép dưới — thân bị cắt, góc không tin được")
        self.assertIsNone(bn.goc_than(_kp(90, tin=0.2), (400, 300, 600, 700), 1080))


class ChuyenSangNamTests(unittest.TestCase):
    def test_thang_roi_nam_moi_tinh_va_mot_lan_cho_toi_khi_day(self):
        v = bn.Vet(0.0, (0, 0, 1, 1), 10.0)
        self.assertTrue(bn.vua_nam(v, 1.0, 80.0))
        self.assertFalse(bn.vua_nam(v, 1.5, 85.0), "đang nằm tiếp — không ghi lần hai")
        v.lich_su.append((2.0, 10.0))
        self.assertFalse(bn.vua_nam(v, 2.0, 10.0))           # dậy
        v.lich_su.append((3.0, 80.0))
        self.assertTrue(bn.vua_nam(v, 3.0, 80.0))

    def test_nam_san_tu_lau_khong_tinh(self):
        v = bn.Vet(0.0, (0, 0, 1, 1), 80.0)
        self.assertFalse(bn.vua_nam(v, 10.0, 80.0), "không thấy lúc thẳng trong 4 giây trước")


class XetKhungTests(unittest.TestCase):
    def setUp(self):
        pytest.importorskip("cv2")
        self.chot: list = []
        self.cam = bn._Camera("Cam bếp", "phu")
        self.anh = np.zeros((1080, 1920, 3), np.uint8)

    def _chay(self, chuoi):
        # chot chạy trong luồng riêng lúc thật; ở đây gọi thẳng để đếm
        with mock.patch.object(bn.threading, "Thread",
                               lambda target, args, **kw: mock.Mock(start=lambda: target(*args))):
            for t, goc in chuoi:
                bn.xet_khung(self.cam, t, self.anh, [_nguoi(goc)], "",
                             chot_fn=lambda cam, lan, model: self.chot.append(lan))

    def test_nga_roi_nam_im_ghi_mot_lan_sau_20_giay(self):
        self._chay([(i * 0.5, 5.0) for i in range(6)] +
                   [(3.0 + i * 0.5, 85.0) for i in range(50)])
        self.assertEqual(len(self.chot), 1)
        lan = self.chot[0]
        self.assertGreaterEqual(lan["nam_giay"], 19.0)
        self.assertIsNone(lan["dung_day_sau"])
        self.assertEqual(len(lan["khung"]), 6)

    def test_nam_roi_day_ghi_thoi_gian_day(self):
        self._chay([(i * 0.5, 5.0) for i in range(6)] + [(3.0 + i * 0.5, 85.0) for i in range(6)] +
                   [(6.0 + i * 0.5, 5.0) for i in range(40)])
        self.assertEqual(len(self.chot), 1)
        self.assertAlmostEqual(self.chot[0]["dung_day_sau"], 3.0, delta=0.6)

    def test_hai_lan_nam_sat_nhau_chi_ghi_mot(self):
        chuoi = []
        for k in range(3):                    # 3 lần nằm–dậy trong 30 giây (trẻ lăn chơi)
            b = k * 9.0
            chuoi += [(b + i * 0.5, 5.0) for i in range(4)] + [(b + 2 + i * 0.5, 85.0) for i in range(4)] + \
                     [(b + 4 + i * 0.5, 5.0) for i in range(10)]
        chuoi += [(30 + i * 0.5, 5.0) for i in range(50)]
        self._chay(chuoi)
        self.assertEqual(len(self.chot), 1)


class GhiSoTests(unittest.TestCase):
    def test_doc_tra_loi_da_bi_loc_ngoac(self):
        # đúng dạng cổng c2a trả (đo 28/09/2026): mất { } và dấu nháy
        s = "nga true, chac 95, ly do Người đàn ông mất thăng bằng ngã từ ghế xuống sàn."
        self.assertEqual(bn.doc_tra_loi(s)["nga"], True)
        self.assertEqual(bn.doc_tra_loi(s)["chac"], 95)
        self.assertIn("mất thăng bằng", bn.doc_tra_loi(s)["ly_do"])
        self.assertIs(bn.doc_tra_loi("ngafalse,chac75,ly doNằm nghỉ")["nga"], False)

    def test_chot_luu_anh_va_so_khong_bao_tin(self):
        pytest.importorskip("cv2")
        with TemporaryDirectory() as tmp, \
                mock.patch.object(bn, "THU_MUC", Path(tmp)), \
                mock.patch.object(bn, "hoi_model", lambda m, a: {"nga": False, "chac": 80, "model": m}), \
                mock.patch("services.thong_bao.gui") as gui:
            lan = {"t": time.time(), "khung": [np.zeros((360, 640, 3), np.uint8)] * 6,
                   "nam_giay": 12.0, "dung_day_sau": None, "goc": 88.0}
            muc = bn.chot("Cam bếp", lan, "gemini_free/gemini-3.5-flash")
            self.assertTrue((Path(tmp) / muc["anh"]).is_file())
            with mock.patch.object(bn, "THU_MUC", Path(tmp)):
                self.assertEqual(bn.nhat_ky()[-1]["model"]["chac"], 80)
            gui.assert_not_called()


if __name__ == "__main__":
    unittest.main()
