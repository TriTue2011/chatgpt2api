"""Test báo ai mở cửa + bot tự học tên từng người."""

from __future__ import annotations

import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

TZ = timezone(timedelta(hours=7))


class KhoaCuaTest(unittest.TestCase):
    def setUp(self) -> None:
        import services.khoa_cua_nha as m
        self.m = m
        self._tmp = tempfile.mkdtemp()
        m._FILE = Path(self._tmp) / "kc.json"
        m.config.data.setdefault("mqtt", {})["khoa_cua"] = {"bat": True}

    def tearDown(self) -> None:
        self.m._reset_for_tests()

    # ── ba nguồn tên ───────────────────────────────────────────────────────
    def test_uu_tien_ten_tu_TUYA(self) -> None:
        """Chủ nhà đặt tên trong app Smart Life thì khỏi phải dạy bot."""
        self.assertEqual(self.m.ten_cua("fingerprint#11", "Anh Việt"), "Anh Việt")

    def test_chua_ai_dat_thi_RONG(self) -> None:
        """Rỗng = chưa biết → bot sẽ hỏi. Không được bịa tên."""
        from services.agent import state
        with mock.patch.object(state, "search_memory", return_value=[]):
            self.assertEqual(self.m.ten_cua("fingerprint#11"), "")

    def test_dat_ten_roi_thi_nho(self) -> None:
        from services.agent import state
        with mock.patch.object(state, "nho_hoac_cap_nhat"):
            self.assertTrue(self.m.dat_ten("fingerprint#11", "con trai"))
        with mock.patch.object(state, "search_memory", return_value=[]):
            self.assertEqual(self.m.ten_cua("fingerprint#11"), "con trai")

    def test_dat_ten_ghi_ca_vao_TRI_NHO_CHUNG(self) -> None:
        """Để chỗ khác trong bot cũng dùng được, không riêng module này."""
        from services.agent import state
        with mock.patch.object(state, "nho_hoac_cap_nhat") as nho:
            self.m.dat_ten("face#17", "mẹ")
        nho.assert_called_once()
        self.assertIn("mẹ", nho.call_args[0][0])

    def test_doc_duoc_ten_tu_TRI_NHO(self) -> None:
        """Chủ máy từng nói trong chat thì bot nhớ, khỏi hỏi lại."""
        from services.agent import state
        with mock.patch.object(state, "search_memory",
                               return_value=["- [2026-09-09 22:52] (x) vân tay số 11 là bố"]):
            self.assertIn("bố", self.m.ten_cua("fingerprint#11"))

    def test_ten_rong_khong_luu(self) -> None:
        self.assertFalse(self.m.dat_ten("face#1", "   "))

    # ── mô tả mã ───────────────────────────────────────────────────────────
    def test_doc_ma_thanh_tieng_viet(self) -> None:
        self.assertEqual(self.m._mo_ta_ma("fingerprint#11"), "vân tay số 11")
        self.assertEqual(self.m._mo_ta_ma("face#17"), "khuôn mặt số 17")

    def test_cach_mo_la_van_hien_duoc(self) -> None:
        """Tuya thêm cách mở mới thì hiện nguyên mã, KHÔNG bịa."""
        self.assertEqual(self.m._mo_ta_ma("xyz#3"), "xyz số 3")

    # ── hỏi tên: chỉ hỏi có hạn ────────────────────────────────────────────
    def test_hoi_toi_da_3_lan_roi_thoi(self) -> None:
        """Hỏi mãi mà không ai trả lời thì thôi — nài thêm chỉ làm phiền."""
        for _ in range(self.m._HOI_TOI_DA):
            self.assertTrue(self.m._nen_hoi("face#9"))
            self.m._danh_dau_da_hoi("face#9")
        self.assertFalse(self.m._nen_hoi("face#9"))

    def test_dat_ten_roi_thi_THOI_HOI(self) -> None:
        self.m._danh_dau_da_hoi("face#9")
        from services.agent import state
        with mock.patch.object(state, "nho_hoac_cap_nhat"):
            self.m.dat_ten("face#9", "khách")
        self.assertTrue(self.m._nen_hoi("face#9"), "đặt tên xong thì bộ đếm phải reset")

    def test_tin_hoi_ten_co_nut_bam(self) -> None:
        t = self.m.soan_hoi_ten({"ma": "fingerprint#11", "ts": time.time(), "ten": ""})
        self.assertIn("<<<ASK>>>", t)
        self.assertIn("<<<END>>>", t)
        self.assertIn("vân tay số 11", t)

    # ── giờ đi ngủ (chủ máy yêu cầu: không cố định giờ) ─────────────────────
    def _tat_den(self, moc):
        """moc: [(ngày lùi, giờ, phút)] → bản ghi tắt đèn."""
        ra = []
        now = datetime.now(TZ)
        for lui, g, p in moc:
            t = (now - timedelta(days=lui)).replace(hour=g, minute=p,
                                                    second=0, microsecond=0)
            ra.append({"ts": t.timestamp(), "thiet_bi": "light.phong_khach",
                       "truong": "state", "gia_tri": "off"})
        return ra

    def test_hoc_duoc_gio_di_ngu(self) -> None:
        from services import lich_su_nha
        moc = [(i, 23, 30) for i in range(1, 6)]
        with mock.patch.object(lich_su_nha, "doc_cua_so",
                               return_value=self._tat_den(moc)):
            g = self.m.gio_di_ngu()
        self.assertIsNotNone(g)
        self.assertAlmostEqual(g % 24, 23.5, places=1)

    def test_gio_ngu_QUA_NUA_DEM_khong_bi_tinh_nguoc(self) -> None:
        """Tắt đèn 0h22 là đêm HÔM TRƯỚC, không phải sáng sớm hôm đó."""
        from services import lich_su_nha
        moc = [(i, 0, 22) for i in range(1, 6)]
        with mock.patch.object(lich_su_nha, "doc_cua_so",
                               return_value=self._tat_den(moc)):
            g = self.m.gio_di_ngu()
        self.assertGreater(g, 24, "quá nửa đêm phải tính tiếp 24, không quay về 0")

    def test_it_du_lieu_thi_KHONG_doan(self) -> None:
        from services import lich_su_nha
        with mock.patch.object(lich_su_nha, "doc_cua_so",
                               return_value=self._tat_den([(1, 23, 0)])):
            self.assertIsNone(self.m.gio_di_ngu())

    def test_TOM_TAT_TRUOC_GIO_NGU_khong_co_dinh(self) -> None:
        """Chủ máy chốt: giờ tóm tắt bám nếp ngủ, không cố định.

        Nhà này ngủ quanh 0h22 nên gửi lúc 22h là quá sớm.
        """
        from services import lich_su_nha
        moc = [(i, 0, 22) for i in range(1, 6)]
        with mock.patch.object(lich_su_nha, "doc_cua_so",
                               return_value=self._tat_den(moc)):
            moc_gui = self.m.gio_tom_tat()
        self.assertGreater(moc_gui % 24, 22.5,
                           "nhà ngủ 0h22 thì tóm tắt phải sau 22h30")

    def test_chua_hoc_duoc_thi_lay_gio_mac_dinh(self) -> None:
        from services import lich_su_nha
        with mock.patch.object(lich_su_nha, "doc_cua_so", return_value=[]):
            self.assertEqual(self.m.gio_tom_tat(), 22.0)

    def test_chu_may_dat_tay_thi_uu_tien(self) -> None:
        self.m.config.data["mqtt"]["khoa_cua"] = {"bat": True, "gio_tom_tat": 21.5}
        self.assertEqual(self.m.gio_tom_tat(), 21.5)

    # ── bất thường ─────────────────────────────────────────────────────────
    def test_nguoi_chua_biet_ten_la_bat_thuong(self) -> None:
        ds = [{"ma": "face#9", "ten": "", "ts": time.time(), "thiet_bi": "khoá"}]
        with mock.patch.object(self.m, "doc_nhat_ky", return_value=ds), \
             mock.patch.object(self.m, "gio_di_ngu", return_value=None):
            ra = self.m.soi_bat_thuong()
        self.assertEqual(ra[0]["muc"], "hoi_ten")

    def test_nguoi_da_biet_ve_dung_gio_thi_KHONG_bao(self) -> None:
        now = datetime.now(TZ).replace(hour=18, minute=0).timestamp()
        ds = [{"ma": "face#1", "ten": "bố", "ts": now, "thiet_bi": "khoá"}]
        with mock.patch.object(self.m, "doc_nhat_ky", return_value=ds), \
             mock.patch.object(self.m, "gio_di_ngu", return_value=24.4):
            self.assertEqual(self.m.soi_bat_thuong(), [])

    def test_mo_cua_SAU_GIO_NGU_thi_bao(self) -> None:
        now = datetime.now(TZ).replace(hour=2, minute=30).timestamp()
        ds = [{"ma": "face#1", "ten": "bố", "ts": now, "thiet_bi": "khoá"}]
        with mock.patch.object(self.m, "doc_nhat_ky", return_value=ds), \
             mock.patch.object(self.m, "gio_di_ngu", return_value=24.0):
            ra = self.m.soi_bat_thuong()
        self.assertTrue(any(x["muc"] == "khuya" for x in ra))

    # ── tóm tắt ────────────────────────────────────────────────────────────
    def test_tom_tat_gom_theo_nguoi(self) -> None:
        now = datetime.now(TZ)
        ds = [{"ma": "face#1", "ten": "bố",
               "ts": now.replace(hour=8).timestamp(), "thiet_bi": "khoá"},
              {"ma": "face#1", "ten": "bố",
               "ts": now.replace(hour=18).timestamp(), "thiet_bi": "khoá"}]
        with mock.patch.object(self.m, "doc_nhat_ky", return_value=ds):
            t = self.m.soan_tom_tat()
        self.assertIn("bố", t)
        self.assertEqual(t.count("- bố"), 1, "một người một dòng")

    def test_tom_tat_nhac_nguoi_chua_biet_ten(self) -> None:
        now = datetime.now(TZ).replace(hour=9).timestamp()
        ds = [{"ma": "face#9", "ten": "", "ts": now, "thiet_bi": "khoá"}]
        with mock.patch.object(self.m, "doc_nhat_ky", return_value=ds):
            t = self.m.soan_tom_tat()
        self.assertIn("chưa biết tên", t)

    def test_khong_co_gi_thi_khong_soan_tin(self) -> None:
        with mock.patch.object(self.m, "doc_nhat_ky", return_value=[]):
            self.assertEqual(self.m.soan_tom_tat(), "")

    # ── không bao giờ làm chết luồng ───────────────────────────────────────
    def test_tuya_hong_thi_tra_rong(self) -> None:
        from services import tuya_nha
        with mock.patch.object(tuya_nha, "danh_sach_thiet_bi",
                               side_effect=RuntimeError("mất mạng")):
            self.assertEqual(self.m.doc_nhat_ky(), [])

    def test_chua_khai_nguoi_nhan_thi_khong_gui(self) -> None:
        from services import canh_bao_nha
        with mock.patch.object(canh_bao_nha, "_nguoi_nhan", return_value=[]):
            self.assertEqual(self.m.chay_mot_lan()["gui"], 0)

    def test_tat_thi_khong_lam_gi(self) -> None:
        self.m.config.data["mqtt"]["khoa_cua"] = {"bat": False}
        self.assertEqual(self.m.chay_mot_lan()["gui"], 0)


if __name__ == "__main__":
    unittest.main()
