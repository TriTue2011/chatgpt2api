"""Mắt của nhà: giải mã YOLO26, dò mặt SCRFD, căn mặt, và sổ khuôn mặt.

Không cần model thật: phần giải mã test bằng đầu ra dựng tay, sổ khuôn mặt dùng
bộ máy giả. Phần khớp với model thật đã đo riêng (xem docstring
``services/khuon_mat_nha.py``): lệch 0 px, cosine 0,999999 so với insightface.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import numpy as np
import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import khuon_mat_nha as km  # noqa: E402
from services import yolo_nha as yn  # noqa: E402


class GiaiMaYoloTests(unittest.TestCase):
    TEN = {0: "person", 2: "car", 15: "cat"}

    def test_doi_toa_do_letterbox_ve_anh_goc(self):
        """Ảnh 810×1080 thu vào 640: tỉ lệ 640/1080, lề trái 80 px."""
        ti_le = 640 / 1080
        le_trai = (640 - round(810 * ti_le)) // 2
        # Hộp (100, 200)-(300, 500) của ảnh gốc, đổi sang toạ độ khung 640.
        x1, y1 = 100 * ti_le + le_trai, 200 * ti_le
        x2, y2 = 300 * ti_le + le_trai, 500 * ti_le
        ra = yn.giai_ma(np.array([[x1, y1, x2, y2, 0.9, 0]]), self.TEN, ti_le, le_trai, 0,
                        810, 1080, 0.35)
        self.assertEqual(len(ra), 1)
        self.assertEqual(ra[0].hop, (100, 200, 300, 500))
        self.assertEqual(ra[0].ten, "người")

    def test_loc_nguong_loc_nhan_va_xep_diem(self):
        dau_ra = np.array([[0, 0, 10, 10, 0.2, 0],     # dưới ngưỡng
                           [0, 0, 20, 20, 0.5, 2],
                           [0, 0, 30, 30, 0.8, 15],
                           [0, 0, 40, 40, 0.9, 0]])
        tat_ca = yn.giai_ma(dau_ra, self.TEN, 1.0, 0, 0, 640, 640, 0.35)
        self.assertEqual([v.nhan for v in tat_ca], ["person", "cat", "car"])
        chi_nguoi = yn.giai_ma(dau_ra, self.TEN, 1.0, 0, 0, 640, 640, 0.35, {"person"})
        self.assertEqual([v.nhan for v in chi_nguoi], ["person"])

    def test_hop_tran_ra_ngoai_bi_kep_hop_suy_bien_bi_bo(self):
        dau_ra = np.array([[-50, -50, 700, 700, 0.9, 0],
                           [10, 10, 10, 50, 0.9, 0]])      # rộng 0
        ra = yn.giai_ma(dau_ra, self.TEN, 1.0, 0, 0, 640, 480, 0.35)
        self.assertEqual([v.hop for v in ra], [(0, 0, 640, 480)])

    def test_vi_tri_bang_loi(self):
        self.assertEqual(yn.vi_tri((0, 0, 60, 60), 640, 480), "góc trên bên trái")
        self.assertEqual(yn.vi_tri((280, 200, 360, 280), 640, 480), "giữa khung")
        self.assertEqual(yn.vi_tri((600, 440, 640, 480), 640, 480), "góc dưới bên phải")

    def test_du_ten_viet_cho_80_lop_coco(self):
        self.assertEqual(len(yn.TEN_VIET), 80)

    def test_letterbox_giu_ti_le_va_vien_xam(self):
        pytest.importorskip("cv2")
        anh = np.zeros((1080, 810, 3), np.uint8)
        blob, ti_le, le_trai, le_tren = yn.letterbox(anh)
        self.assertEqual(blob.shape, (1, 3, 640, 640))
        self.assertEqual((le_trai, le_tren), (80, 0))
        self.assertAlmostEqual(float(blob[0, 0, 320, 10]), 114 / 255, places=5)
        self.assertEqual(float(blob[0, 0, 320, 320]), 0.0)


class ScrfdTests(unittest.TestCase):
    def _dau_ra_rong(self):
        ra = []
        for buoc in km._BUOC:
            n = (640 // buoc) ** 2 * km._SO_NEO
            ra.append(np.zeros((n, 1), np.float32))
        for buoc in km._BUOC:
            n = (640 // buoc) ** 2 * km._SO_NEO
            ra.append(np.zeros((n, 4), np.float32))
        for buoc in km._BUOC:
            n = (640 // buoc) ** 2 * km._SO_NEO
            ra.append(np.zeros((n, 10), np.float32))
        return ra

    def test_giai_ma_mot_neo_ra_hop_va_moc(self):
        ra = self._dau_ra_rong()
        # Tầng bước 8, ô (hàng 2, cột 3), neo đầu → tâm (24, 16).
        i = (2 * 80 + 3) * km._SO_NEO
        ra[0][i, 0] = 0.9
        ra[3][i] = [1, 1, 2, 3]                       # × bước 8 → 8, 8, 16, 24
        ra[6][i] = [0, 0, 1, 0, 0, 1, -1, 0, 0, -1]   # × 8
        det, moc = km.giai_ma_scrfd(ra, 640, ti_le=0.5)
        self.assertEqual(det.shape, (1, 5))
        np.testing.assert_allclose(det[0, :4], [(24 - 8) / 0.5, (16 - 8) / 0.5,
                                                (24 + 16) / 0.5, (16 + 24) / 0.5])
        np.testing.assert_allclose(moc[0], np.array([[24, 16], [32, 16], [24, 24],
                                                     [16, 16], [24, 8]]) / 0.5)

    def test_duoi_nguong_khong_ra_gi(self):
        ra = self._dau_ra_rong()
        ra[0][0, 0] = 0.49
        det, moc = km.giai_ma_scrfd(ra, 640, 1.0)
        self.assertEqual(det.shape, (0, 5))
        self.assertEqual(moc.shape, (0, 5, 2))

    def test_nms_bo_hop_trung(self):
        det = np.array([[0, 0, 100, 100, 0.9], [2, 2, 102, 102, 0.8],
                        [300, 300, 400, 400, 0.7]], np.float32)
        self.assertEqual(km._nms(det, 0.4), [0, 2])


class CanMatTests(unittest.TestCase):
    def test_umeyama_tim_lai_phep_dong_dang(self):
        goc = np.array(km._MOC_CHUAN)
        goc_quay = np.deg2rad(20)
        r = 1.7 * np.array([[np.cos(goc_quay), -np.sin(goc_quay)],
                            [np.sin(goc_quay), np.cos(goc_quay)]])
        dich = goc @ r.T + [15, -4]
        t = km._umeyama(goc, dich)
        np.testing.assert_allclose(t[:2, :2], r, atol=1e-9)
        np.testing.assert_allclose(t[:2, 2], [15, -4], atol=1e-9)

    def test_moc_dung_cho_chuan_thi_khong_bien_doi(self):
        pytest.importorskip("cv2")
        rng = np.random.default_rng(1)
        anh = rng.integers(0, 255, (112, 112, 3), dtype=np.uint8)
        ra = km.can_mat(anh, np.array(km._MOC_CHUAN, np.float32))
        np.testing.assert_array_equal(ra, anh)

    def test_do_giong_kep_am_ve_0(self):
        self.assertEqual(km.do_giong(np.array([1.0, 0]), np.array([-1.0, 0])), 0.0)
        self.assertAlmostEqual(km.do_giong(np.array([1.0, 0]), np.array([1.0, 0])), 100.0)


# ── Sổ khuôn mặt với bộ máy giả ─────────────────────────────────────────────

def _don_vi(*x):
    v = np.zeros(512, np.float32)
    v[:len(x)] = x
    return v / np.linalg.norm(v)


class _MayGia:
    """Ảnh một màu; kênh B ở (0,0) chọn kịch bản. Mọi vùng cắt giữ màu đó.

    ``kich_ban[mau] = [(người, rộng, cao), …]`` — mặt đặt giữa ảnh theo tỉ lệ.
    ``vec[bo][người]`` — vector của người đó theo bộ model.
    """

    def __init__(self, bo: str, kich_ban: dict, vec: dict) -> None:
        self.bo = km.get(bo)
        self.kich_ban, self.vec = kich_ban, vec
        self.so_lan_vector = 0

    def do(self, anh, nguong=0.5):
        cao, rong = anh.shape[:2]
        ra = []
        for i, (ai, r, c) in enumerate(self.kich_ban.get(int(anh[0, 0, 0]), [])):
            cx, cy = rong * (0.3 + 0.4 * i), cao / 2
            w, h = r * rong, c * cao
            ra.append(km.Mat((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), 0.9, ai))
        return ra

    def vector(self, anh, mat):
        self.so_lan_vector += 1
        mat.vector = self.vec[self.bo.ma][mat.moc]
        return mat.vector

    def phan_tich(self, anh, nguong=0.5):
        mats = self.do(anh)
        for m in mats:
            self.vector(anh, m)
        return mats


def _anh(mau: int, rong=400, cao=400) -> bytes:
    import cv2
    ok, buf = cv2.imencode(".png", np.full((cao, rong, 3), mau, np.uint8))
    return buf.tobytes()


class SoMatTests(unittest.TestCase):
    def setUp(self):
        pytest.importorskip("cv2")
        from services import nhin_nha
        from services import so_mat_nha as sm

        self.sm, self.nn = sm, nhin_nha
        self._tmp = TemporaryDirectory()
        sm._reset_for_tests()
        self._p = [mock.patch.object(sm, "_DB_PATH", Path(self._tmp.name) / "km.sqlite"),
                   mock.patch.object(sm, "_THU_MUC_ANH", Path(self._tmp.name) / "anh")]
        for p in self._p:
            p.start()
        self.vec = {"buffalo_s": {"viet": _don_vi(1), "lan": _don_vi(0, 1),
                                  "gan_viet": _don_vi(0.47, 0, 0, 0.8826),   # cos 0,47 → 47
                                  "la": _don_vi(0, 0, 1)},
                    "buffalo_l": {"viet": _don_vi(0, 0, 0, 1), "lan": _don_vi(0, 0, 0, 0, 1),
                                  "gan_viet": _don_vi(0, 0, 0, 0, 0, 1), "la": _don_vi(0, 0, 0, 0, 0, 0, 1)}}
        self.kich_ban = {10: [("viet", 0.3, 0.4)], 11: [("lan", 0.3, 0.4)],
                         12: [("viet", 0.2, 0.3), ("lan", 0.2, 0.3)],   # hai mặt ngang cỡ
                         13: [("viet", 0.05, 0.05)],                     # 20 px — quá nhỏ
                         14: [], 15: [("gan_viet", 0.3, 0.4)],
                         16: [("lan", 0.2, 0.3), ("la", 0.2, 0.3)],
                         17: [("viet", 0.4, 0.5), ("lan", 0.1, 0.15)]}  # mặt Việt to rõ
        self.may = _MayGia("buffalo_s", self.kich_ban, self.vec)
        self.cfg = {"khuon_mat": {"bo": "buffalo_s"}}
        self._p2 = [mock.patch.object(nhin_nha, "mat", lambda: self.may),
                    mock.patch.dict(nhin_nha.config.data, {"nhin_nha": self.cfg})]
        for p in self._p2:
            p.start()

    def tearDown(self):
        for p in self._p2 + self._p:
            p.stop()
        self.sm._reset_for_tests()
        self._tmp.cleanup()

    def test_day_nguoi_moi_roi_them_mat_cung_ten_khong_dau(self):
        a = self.sm.day("Việt", _anh(10))
        self.assertTrue(a["nguoi_moi"])
        b = self.sm.day("viet", _anh(10))
        self.assertFalse(b["nguoi_moi"])
        self.assertEqual((b["nguoi_id"], b["so_mat"], b["ten"]), (a["nguoi_id"], 2, "Việt"))

    def test_khong_day_anh_khong_mat_nhieu_mat_ngang_co_hoac_mat_nho(self):
        for mau, chu in ((14, "Không thấy"), (12, "nhiều khuôn mặt"), (13, "nhỏ quá")):
            with self.assertRaises(self.sm.LoiSoMat) as ng:
                self.sm.day("Việt", _anh(mau))
            self.assertIn(chu, str(ng.exception))
        self.assertEqual(self.sm.danh_sach_nguoi(), [])

    def test_anh_nhieu_mat_nhung_mot_mat_to_ro_thi_day_duoc(self):
        self.sm.day("Việt", _anh(17))
        kq = self.sm.nhan_dien(_anh(10))
        self.assertEqual(kq["mat"][0]["ten"], "Việt")

    def test_mat_da_la_nguoi_khac_thi_hoi_lai_tru_khi_ep(self):
        self.sm.day("Việt", _anh(10))
        with self.assertRaises(self.sm.LoiSoMat) as ng:
            self.sm.day("Lan", _anh(10))
        self.assertIn("Việt", str(ng.exception))
        self.assertTrue(self.sm.day("Lan", _anh(10), ep=True)["nguoi_moi"])

    def test_nhan_dien_ba_muc_quen_co_the_la(self):
        self.sm.day("Việt", _anh(10))
        self.sm.day("Lan", _anh(11))
        quen = self.sm.nhan_dien(_anh(10))["mat"][0]
        self.assertEqual((quen["ten"], quen["loai"], quen["do_giong"]), ("Việt", "quen", 100.0))
        co_the = self.sm.nhan_dien(_anh(15))["mat"][0]
        self.assertEqual((co_the["ten"], co_the["loai"]), ("Việt", "co_the"))
        self.assertAlmostEqual(co_the["do_giong"], 47.0, delta=0.1)
        hai = self.sm.nhan_dien(_anh(16))["mat"]
        self.assertEqual([(m["ten"], m["loai"]) for m in hai], [("Lan", "quen"), (None, "la")])

    def test_so_trong_thi_moi_mat_la_nguoi_la(self):
        self.assertEqual(self.sm.nhan_dien(_anh(10))["mat"][0]["loai"], "la")

    def test_doi_bo_model_tinh_lai_vector_tu_anh_da_luu(self):
        self.sm.day("Việt", _anh(10))
        self.may = _MayGia("buffalo_l", self.kich_ban, self.vec)
        self.cfg["khuon_mat"]["bo"] = "buffalo_l"
        kq = self.sm.nhan_dien(_anh(10))["mat"][0]
        self.assertEqual((kq["ten"], kq["loai"]), ("Việt", "quen"))
        bo = self.sm._db().execute("SELECT DISTINCT bo FROM mat").fetchall()
        self.assertEqual([r[0] for r in bo], ["buffalo_l"])

    def test_doi_ten_trung_bi_chan_xoa_nguoi_xoa_ca_anh(self):
        a = self.sm.day("Việt", _anh(10))
        b = self.sm.day("Lan", _anh(11))
        with self.assertRaises(self.sm.LoiSoMat):
            self.sm.doi_ten(b["nguoi_id"], "viet")
        self.assertTrue(self.sm.doi_ten(b["nguoi_id"], "Lan Anh"))
        anh = [self.sm.duong_anh(m["anh"]) for m in self.sm.mat_cua(a["nguoi_id"])]
        self.assertTrue(all(p is not None and p.is_file() for p in anh))
        self.assertTrue(self.sm.xoa_nguoi(a["nguoi_id"]))
        self.assertFalse(any(p.is_file() for p in anh))
        self.assertEqual([n["ten"] for n in self.sm.danh_sach_nguoi()], ["Lan Anh"])
        self.assertEqual(self.sm.nhan_dien(_anh(10))["mat"][0]["loai"], "la")

    def test_duong_anh_chan_thoat_thu_muc(self):
        for xau in ("../km.sqlite", "/etc/passwd", ""):
            self.assertIsNone(self.sm.duong_anh(xau))


class NhinNhaCauHinhTests(unittest.TestCase):
    def test_model_la_hoac_nguong_hong_thi_ve_mac_dinh(self):
        from services import nhin_nha as nn
        with mock.patch.dict(nn.config.data, {"nhin_nha": {
                "yolo": {"model": "yolo99", "nguong": "abc"},
                "khuon_mat": {"bo": "?", "nguong_co_the": 70, "nguong_chac": 50}}}):
            self.assertEqual(nn.model_yolo().ma, yn.MAC_DINH)
            self.assertEqual(nn.bo_mat().ma, km.MAC_DINH)
            self.assertEqual(nn.nguong_yolo(), 0.35)
            self.assertEqual(nn.nguong_mat(), (70.0, 70.0))   # chắc không được thấp hơn có thể

    def test_chua_tai_model_thi_bao_kem_lenh_tai(self):
        from services import nhin_nha as nn
        with TemporaryDirectory() as tmp, mock.patch.object(nn, "THU_MUC", Path(tmp)), \
                mock.patch.object(nn, "_yolo", None), mock.patch.object(nn, "_mat", None):
            with self.assertRaises(nn.ChuaCoModel) as ng:
                nn.yolo()
            self.assertIn("download_nhin_nha.py --yolo yolo26n", str(ng.exception))
            with self.assertRaises(nn.ChuaCoModel) as ng:
                nn.mat()
            self.assertIn("--mat buffalo_s", str(ng.exception))


if __name__ == "__main__":
    unittest.main()
