"""Test tầng bối cảnh — "lúc ấy trong nhà thế nào".

Mỗi ca dưới đây khoá một quyết định thiết kế đã nêu rõ lý do trong
`services/boi_canh_nha.py`, không phải khoá cách viết.
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock


def _nap(thu_muc: str):
    import services.boi_canh_nha as bc
    import services.lich_su_nha as ls

    ls._reset_for_tests()
    ls._DB_PATH = Path(thu_muc) / "lich_su_nha.sqlite"
    ls._conn = None
    bc._reset_for_tests()
    return bc, ls


class BoiCanhNhaTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.bc, self.ls = _nap(self._tmp.name)
        self.ls.config.data.setdefault("mqtt", {})["lich_su"] = {"bat": True}
        # Không gọi Home Assistant thật trong test.
        self._p = mock.patch.object(
            self.bc, "phong_cua",
            side_effect=lambda tb: "bep" if "bep" in tb.lower() else "phong_khach")
        self._p.start()
        self.addCleanup(self._p.stop)

    def tearDown(self) -> None:
        self.ls._reset_for_tests()
        self.bc._reset_for_tests()
        self._tmp.cleanup()

    def _do_so_do(self, thiet_bi: str, truong: str, gt: float, ts: float) -> None:
        with self.ls._khoa_db:
            conn = self.ls._db()
            conn.execute(
                "INSERT OR REPLACE INTO so_do (o_5p, thiet_bi, truong, nho, lon, tb, n)"
                " VALUES (?,?,?,?,?,?,1)",
                (int(ts // 300), thiet_bi, truong, gt, gt, gt))
            conn.commit()

    def _do_su_kien(self, thiet_bi: str, truong: str, gt: str, ts: float) -> None:
        with self.ls._khoa_db:
            conn = self.ls._db()
            conn.execute(
                "INSERT INTO su_kien (ts, nguon, thiet_bi, truong, gia_tri,"
                " gia_tri_cu, do_ai, gio, thu) VALUES (?,?,?,?,?,?,0,12,1)",
                (ts, "mqtt", thiet_bi, truong, gt, ""))
            conn.commit()

    # ── thiếu dữ liệu phải NÓI RÕ, không được bịa ──────────────────────────
    def test_THIEU_thi_VANG_MAT_khong_co_mac_dinh(self) -> None:
        """Tầng xác suất phải phân biệt "trời tối" với "không biết trời thế
        nào". Trộn hai cái đó là học nhầm, và học nhầm kiểu này không báo lỗi."""
        r = self.bc.boi_canh(time.time())
        self.assertEqual(r["lux"], {})
        self.assertIn("lux", r["thieu"])
        self.assertIn("nhiet_do", r["thieu"])

    def test_co_du_lieu_thi_KHONG_nam_trong_thieu(self) -> None:
        t = time.time()
        self._do_so_do("sensor.bep_illuminance", "illuminance", 12.0, t)
        r = self.bc.boi_canh(t)
        self.assertNotIn("lux", r["thieu"])
        self.assertEqual(r["lux"]["bep"]["gt"], 12.0)
        self.assertEqual(r["lux"]["bep"]["tin"], 1.0)

    # ── rò rỉ tương lai ────────────────────────────────────────────────────
    def test_MOC_QUA_KHU_khong_duoc_dung_bang_TUOI(self) -> None:
        """Bẫy nguy hiểm nhất của tầng này.

        `tuoi` giữ giá trị MỚI NHẤT. Đem nó trả lời "8 giờ trước lux bao
        nhiêu" thì mô hình học được "lux lúc bật đèn = lux bây giờ" — đúng gần
        100% trên dữ liệu cũ và vô dụng ngoài đời.
        """
        now = time.time()
        with self.ls._khoa_db:
            conn = self.ls._db()
            conn.execute(
                "INSERT INTO tuoi (thiet_bi, truong, gia_tri, ts) VALUES (?,?,?,?)",
                ("sensor.bep_illuminance", "illuminance", "999", now))
            conn.commit()
        r = self.bc.boi_canh(now - 8 * 3600)
        self.assertEqual(r["lux"], {}, "mốc quá khứ không được lấy từ `tuoi`")

    def test_HIEN_TAI_thi_duoc_dung_tuoi(self) -> None:
        now = time.time()
        with self.ls._khoa_db:
            conn = self.ls._db()
            conn.execute(
                "INSERT INTO tuoi (thiet_bi, truong, gia_tri, ts) VALUES (?,?,?,?)",
                ("sensor.bep_illuminance", "illuminance", "42", now))
            conn.commit()
        r = self.bc.hien_tai()
        self.assertEqual(r["lux"]["bep"]["gt"], 42.0)
        self.assertEqual(r["lux"]["bep"]["nguon"], "tuoi")

    # ── độ tin giảm theo khoảng cách ───────────────────────────────────────
    def test_SO_DO_GAN_thi_do_tin_GIAM(self) -> None:
        t = time.time()
        self._do_so_do("sensor.bep_illuminance", "illuminance", 12.0, t - 20 * 60)
        r = self.bc.boi_canh(t)
        self.assertEqual(r["lux"]["bep"]["nguon"], "so_do_gan")
        self.assertLess(r["lux"]["bep"]["tin"], 1.0)
        self.assertGreaterEqual(r["lux"]["bep"]["tin"], 0.5)

    def test_QUA_XA_thi_coi_nhu_KHONG_BIET(self) -> None:
        """Không nội suy giữa hai ô cách nhau hàng tiếng — ra số bịa."""
        t = time.time()
        self._do_so_do("sensor.bep_illuminance", "illuminance", 12.0, t - 3 * 3600)
        r = self.bc.boi_canh(t)
        self.assertEqual(r["lux"], {})
        self.assertIn("lux", r["thieu"])

    # ── có người ───────────────────────────────────────────────────────────
    def test_CO_NGUOI_lay_ban_ghi_cuoi_TRUOC_moc(self) -> None:
        t = time.time()
        self._do_su_kien("binary_sensor.bep_occupancy", "state", "on", t - 600)
        r = self.bc.boi_canh(t)
        self.assertTrue(r["nguoi"]["bep"]["gt"])

    def test_TAT_roi_thi_la_KHONG_co_nguoi(self) -> None:
        t = time.time()
        self._do_su_kien("binary_sensor.bep_occupancy", "state", "on", t - 600)
        self._do_su_kien("binary_sensor.bep_occupancy", "state", "off", t - 60)
        r = self.bc.boi_canh(t)
        self.assertFalse(r["nguoi"]["bep"]["gt"])

    def test_dau_hieu_QUA_CU_thi_het_hieu_luc(self) -> None:
        t = time.time()
        self._do_su_kien("binary_sensor.bep_occupancy", "state", "on", t - 4000)
        r = self.bc.boi_canh(t)
        self.assertEqual(r["nguoi"], {})

    # ── rời rạc hoá ────────────────────────────────────────────────────────
    def test_NGUONG_theo_PHAN_VI_cua_chinh_nha_nay(self) -> None:
        """Không đặt cứng "dưới 50 lux là tối": cảm biến báo 0–10 thì mọi lúc
        đều tối, cảm biến báo 0–20.000 thì mọi lúc đều sáng."""
        t = time.time()
        for i in range(30):          # thang đo 0..29
            self._do_so_do("sensor.bep_illuminance", "illuminance",
                           float(i), t - i * 400)
        self._do_so_do("sensor.bep_illuminance", "illuminance", 1.0, t)
        nhan = self.bc.roi_rac(self.bc.boi_canh(t))
        self.assertEqual(nhan["lux_bep"], "toi", "1 lux trên thang 0–29 là tối")

    def test_THIEU_thi_KHONG_co_nhan_khong_biet(self) -> None:
        """Có nhãn "không biết" thì mô hình học được "khi không biết lux thì
        hay bật đèn" — thật ra là "hồi tháng 8 nhà chưa có cảm biến"."""
        nhan = self.bc.roi_rac(self.bc.boi_canh(time.time()))
        self.assertNotIn("lux_bep", nhan)
        self.assertFalse(any("khong_biet" in v for v in nhan.values()))

    def test_luon_co_gio_thu_mua(self) -> None:
        nhan = self.bc.roi_rac(self.bc.boi_canh(time.time()))
        for k in ("buoi", "thu", "mua"):
            self.assertIn(k, nhan)

    def test_NGUOI_TRONG_NHA_gop_moi_phong(self) -> None:
        t = time.time()
        self._do_su_kien("binary_sensor.bep_occupancy", "state", "off", t - 60)
        self._do_su_kien("binary_sensor.pk_occupancy", "state", "on", t - 60)
        nhan = self.bc.roi_rac(self.bc.boi_canh(t))
        self.assertEqual(nhan["nguoi_trong_nha"], "co")

    # ── mùa ────────────────────────────────────────────────────────────────
    def test_mua_theo_thang(self) -> None:
        self.assertEqual(self.bc.mua(1), "lanh")
        self.assertEqual(self.bc.mua(12), "lanh")
        self.assertEqual(self.bc.mua(7), "nong")
        self.assertEqual(self.bc.mua(4), "chuyen")

    # ── khớp phòng ─────────────────────────────────────────────────────────
    def test_SO_HA_thang_moi_thu(self) -> None:
        """Chủ nhà đã xếp phòng trong HA thì đó là câu trả lời đúng."""
        self._p.stop()
        self.bc._reset_for_tests()
        try:
            self.bc._cache_phong = {"light.abc": "Bếp"}
            self.bc._cache_ten_phong = {"phong ngu": "Phòng ngủ"}
            self.bc._cache_phong_luc = 9e18
            # Tên chứa "phòng ngủ" nhưng sổ HA nói Bếp → nghe sổ.
            self.bc._cache_phong["light.den_phong_ngu"] = "Bếp"
            self.assertEqual(self.bc.phong_cua("light.den_phong_ngu"), "Bếp")
        finally:
            self._p.start()

    def test_MQTT_khop_theo_TEN_PHONG_CO_THAT(self) -> None:
        """36/38 thiết bị trong kho số đo là MQTT thuần, không có trong sổ HA.

        Chỉ dựa vào sổ thì gần hết số đo rơi vào "phòng khác" và bot mất khả
        năng phân biệt bếp tối với phòng ngủ tối.
        """
        self._p.stop()
        self.bc._reset_for_tests()
        try:
            self.bc._cache_phong = {}
            self.bc._cache_ten_phong = {
                "ban cong": "Ban công", "bep": "Bếp",
                "phong khach": "Phòng khách", "phong ngu": "Phòng ngủ"}
            self.bc._cache_phong_luc = 9e18
            self.assertEqual(
                self.bc.phong_cua("zigbee2mqtt/Nhiệt ẩm phòng ngủ"), "Phòng ngủ")
            # Dấu gạch ngang của Frigate phải khớp như dấu cách.
            self.assertEqual(self.bc.phong_cua("frigate/ban-cong"), "Ban công")
            # Tên phòng DÀI thắng: "phòng khách" không được thua "bếp".
            self.assertEqual(
                self.bc.phong_cua("zigbee2mqtt/Quạt phòng khách"), "Phòng khách")
            # Không thuộc phòng nào thì nói thẳng là không biết.
            self.assertEqual(self.bc.phong_cua("zigbee2mqtt/Aptomat tổng"), "")
        finally:
            self._p.start()

    # ── không được kéo sập tầng gọi nó ─────────────────────────────────────
    def test_KHO_HONG_thi_tra_ve_RONG_khong_nem_loi(self) -> None:
        with mock.patch.object(self.ls, "doc_cua_so",
                               side_effect=RuntimeError("đĩa hỏng")):
            r = self.bc.boi_canh(time.time())
        self.assertEqual(r["nguoi"], {})
        self.assertIn("buoi", r)

    def test_HA_HONG_thi_phong_rong_khong_nem_loi(self) -> None:
        self._p.stop()
        self.bc._reset_for_tests()
        try:
            from services import ha_client
            with mock.patch.object(ha_client, "get_ha_area_index",
                                   side_effect=RuntimeError("HA sập")):
                self.assertEqual(self.bc.phong_cua("light.bep"), "")
        finally:
            self._p.start()


if __name__ == "__main__":
    unittest.main()
