"""«Bỏ khỏi c2a» một thiết bị — chủ máy 13/09/2026.

Bỏ nghĩa là c2a coi như không có thiết bị đó: không đọc thấy (HA/MQTT/Tuya),
không ghi lịch sử mới, lịch sử cũ bị xoá — mà KHÔNG đụng thiết bị khác cùng
nhánh chủ đề. Xem `services/thiet_bi_bo.py`.
"""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock


def _so_tam(test: unittest.TestCase):
    """Trỏ sổ bỏ vào thư mục tạm, dọn bộ nhớ đệm trước và sau."""
    from services import thiet_bi_bo

    tmp = TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    vo = mock.patch.object(thiet_bi_bo, "_FILE", Path(tmp.name) / "thiet_bi_da_bo.json")
    vo.start()
    test.addCleanup(vo.stop)
    thiet_bi_bo._reset_for_tests()
    test.addCleanup(thiet_bi_bo._reset_for_tests)
    return thiet_bi_bo


class SoBoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tb = _so_tam(self)

    def test_goc_chu_de_TU_CHOI_goc_mot_doan(self) -> None:
        """Gốc `zigbee2mqtt` là nhánh của MỌI thiết bị Zigbee — bỏ theo nó là bỏ cả nhà."""
        g = self.tb.goc_chu_de
        self.assertEqual(g(["zigbee2mqtt/Hiện diện bếp", "zigbee2mqtt/Hiện diện bếp/set"]),
                         "zigbee2mqtt/Hiện diện bếp")
        self.assertEqual(g(["frigate/bep/person", "frigate/bep/all"]), "frigate/bep")
        self.assertEqual(g(["zigbee2mqtt/A", "zigbee2mqtt/B"]), "")
        # So theo ĐOẠN, không theo ký tự: "bep" và "bep2" không có gốc "frigate/bep".
        self.assertEqual(g(["frigate/bep/person", "frigate/bep2/person"]), "")
        self.assertEqual(g([]), "")

    def test_la_bo_lich_su_khop_HA_Tuya_goc_MQTT_va_chu_de_con(self) -> None:
        self.tb.bo("ha", "light.bep", ten_goc="Đèn bếp")
        self.tb.bo("tuya", "abc123", ten_goc="Ổ cắm", ten_lich_su=["Ổ cắm", "tuya:abc123"])
        self.tb.bo("mqtt", "Camera bep", goc="frigate/bep")
        khop = self.tb.la_bo_lich_su
        for co in ("light.bep", "Ổ cắm", "tuya:abc123", "frigate/bep", "frigate/bep/person"):
            self.assertTrue(khop(co), co)
        for khong in ("light.bep_2", "frigate/bep2/person", "frigate", "zigbee2mqtt/Bếp"):
            self.assertFalse(khop(khong), khong)

    def test_bo_va_bo_lai_LAM_MOI_bo_nho_dem_va_ghi_xuong_dia(self) -> None:
        self.assertFalse(self.tb.la_bo("ha", "light.bep"))   # nạp đệm rỗng trước
        self.tb.bo("ha", "light.bep")
        self.assertTrue(self.tb.la_bo("ha", "light.bep"))
        self.assertTrue(self.tb.co_bo("ha"))
        self.assertFalse(self.tb.co_bo("tuya"))
        so = json.loads(Path(self.tb._FILE).read_text(encoding="utf-8"))
        self.assertIn("ha:light.bep", so)

        self.assertTrue(self.tb.bo_lai("ha", "light.bep"))
        self.assertFalse(self.tb.la_bo("ha", "light.bep"))
        self.assertFalse(self.tb.bo_lai("ha", "light.bep"), "bỏ lại lần hai không có gì để khôi phục")

    def test_MQTT_thieu_goc_thi_khong_ghi(self) -> None:
        with self.assertRaises(ValueError):
            self.tb.bo("mqtt", "Bếp")
        self.assertEqual(self.tb.danh_sach(), [])


class LichSuTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tb = _so_tam(self)
        from test.test_lich_su_nha import _nap_module

        self._tmp = TemporaryDirectory()
        self.m = _nap_module(self._tmp.name)
        self.m.config.data.setdefault("mqtt", {})["lich_su"] = {"bat": True}

    def tearDown(self) -> None:
        self.m._reset_for_tests()
        self._tmp.cleanup()

    def _dem(self, bang: str, tb: str) -> int:
        return self.m._db().execute(f"SELECT COUNT(*) FROM {bang} WHERE thiet_bi=?", (tb,)).fetchone()[0]

    def test_KHONG_GHI_thiet_bi_da_bo_ca_hai_duong(self) -> None:
        self.tb.bo("ha", "light.bep")
        self.tb.bo("mqtt", "Camera bep", goc="frigate/bep")
        self.m.ghi("ha", "light.bep", "state", "on")
        self.m.ghi("frigate", "frigate/bep/person", "state", "1")
        self.assertEqual(self.m._hang.qsize(), 0)

        conn = self.m._db()
        self.m._ghi_thang(conn, "ha", "light.bep", "state", "on", False, time.time())
        self.m._ghi_thang(conn, "ha", "light.khach", "state", "on", False, time.time())
        conn.commit()
        self.assertEqual(self._dem("su_kien", "light.bep"), 0)
        self.assertEqual(self._dem("su_kien", "light.khach"), 1, "thiết bị khác vẫn ghi")

    def test_xoa_thiet_bi_CHI_xoa_dung_thiet_bi_ke_ca_ky_tu_dai_dien(self) -> None:
        now = time.time()
        conn = self.m._db()
        cot = "(ts, nguon, thiet_bi, truong, gia_tri, gia_tri_cu, do_ai, gio, thu)"
        cac_tb = ["light.bep", "light.bep_2", "frigate/bep", "frigate/bep/person",
                  "frigate/bep2/person", "zigbee2mqtt/Khác", "zigbee2mqtt/a_b/x",
                  "zigbee2mqtt/axb/x"]
        for i, tb in enumerate(cac_tb):
            conn.execute(f"INSERT INTO su_kien {cot} VALUES (?,?,?,?,?,?,0,1,1)",
                         (now + i, "mqtt", tb, "state", "1", None))
            conn.execute("INSERT INTO tuoi VALUES (?,?,?,?)", (tb, "state", "1", now + i))
            conn.execute("INSERT INTO so_do (o_5p, thiet_bi, truong, tb, n) VALUES (1,?,?,1,1)",
                         (tb, "lux"))
            conn.execute("INSERT INTO nhip (thiet_bi, truong) VALUES (?,?)", (tb, "state"))
        conn.commit()

        # `_` trong LIKE là ký tự đại diện: gốc `zigbee2mqtt/a_b` không được ăn `zigbee2mqtt/axb/x`.
        kq = self.m.xoa_thiet_bi(["light.bep", "zigbee2mqtt/Khác"], ["frigate/bep", "zigbee2mqtt/a_b"], lo=1)
        self.assertEqual(kq, {"su_kien": 5, "so_do": 5, "tuoi": 5, "nhip": 5})
        con = sorted(r[0] for r in conn.execute("SELECT thiet_bi FROM su_kien"))
        self.assertEqual(con, ["frigate/bep2/person", "light.bep_2", "zigbee2mqtt/axb/x"])

    def test_xoa_thiet_bi_rong_thi_khong_xoa_gi(self) -> None:
        self.assertEqual(self.m.xoa_thiet_bi([], []), {"su_kien": 0, "so_do": 0, "tuoi": 0, "nhip": 0})


class DocTrangThaiTest(unittest.TestCase):
    """Mọi đường đọc thiết bị cùng thấy thiết bị đã bỏ như không có."""

    def setUp(self) -> None:
        self.tb = _so_tam(self)

    def test_GET_STATES_an_ca_luc_tai_VA_luc_tra_bo_dem(self) -> None:
        """Gương `ha_live` bơm hạn bộ đệm theo mỗi sự kiện, nên thực thể vừa bỏ
        nằm lại trong bộ đệm mãi nếu chỉ lọc lúc tải."""
        from services import ha_client

        dem = [{"entity_id": "light.bep", "attributes": {}},
               {"entity_id": "light.khach", "attributes": {}}]
        self.tb.bo("ha", "light.bep")
        with mock.patch.object(ha_client, "_state_cache", dem), \
             mock.patch.object(ha_client, "_state_cache_ts", time.time()), \
             mock.patch.object(ha_client, "_get_cache_ttl", return_value=60):
            ds = ha_client.get_states()
        self.assertEqual([s["entity_id"] for s in ds], ["light.khach"])

        class _Tra:
            def read(self) -> bytes:
                return json.dumps(dem).encode()

        with mock.patch.object(ha_client, "_state_cache", []), \
             mock.patch.object(ha_client, "_state_cache_ts", 0.0), \
             mock.patch.object(ha_client, "_state_fail_ts", 0.0), \
             mock.patch.object(ha_client, "_get_ha_config",
                               return_value={"url": "http://ha", "token": "t"}), \
             mock.patch("urllib.request.urlopen", return_value=_Tra()):
            self.assertEqual([s["entity_id"] for s in ha_client.get_states(use_cache=False)],
                             ["light.khach"])
            self.assertIsNone(ha_client.get_state("light.bep"))

    def test_GUONG_ha_live_go_thuc_the_da_bo_khi_no_doi_trang_thai(self) -> None:
        from services import ha_client as hc
        from services import ha_live

        cu = (hc._state_cache, hc._state_cache_ts)
        self.addCleanup(lambda: setattr(hc, "_state_cache", cu[0]))
        self.addCleanup(lambda: setattr(hc, "_state_cache_ts", cu[1]))
        hc._state_cache = [{"entity_id": "light.bep", "state": "off", "attributes": {}},
                           {"entity_id": "fan.c", "state": "on", "attributes": {}}]
        index = {"light.bep": 0, "fan.c": 1}
        self.tb.bo("ha", "light.bep")
        with mock.patch("services.lich_su_nha.ghi"):
            ha_live._patch_state({"entity_id": "light.bep", "state": "on", "attributes": {}},
                                 "light.bep", index)
        self.assertEqual([s["entity_id"] for s in hc._state_cache], ["fan.c"])

    def test_MQTT_danh_sach_va_dem_nguoi_bo_camera_da_bo(self) -> None:
        from services import mqtt_nha as mq

        mq._reset_for_tests()
        self.addCleanup(mq._reset_for_tests)
        now = time.time()
        with mq._khoa_du_lieu:
            mq._gia_tri["frigate/bep/person"] = ("1", now)
            mq._gia_tri["frigate/khach/person"] = ("2", now)
        mq._stats["last_tin_ts"] = now
        self.tb.bo("mqtt", "Camera bep", goc="frigate/bep")

        self.assertEqual([d["ten"] for d in mq.danh_sach_thiet_bi()], ["Camera khach"])
        self.assertEqual(sorted(mq.dem_nguoi()), ["khach"])
        self.assertEqual(mq._khop_ten("bep"), "", "điều khiển theo tên cũng không thấy")

    def test_TUYA_danh_sach_bo_thiet_bi_da_bo(self) -> None:
        from services import tuya_nha

        tra = {"result": [{"id": "a1", "name": "Ổ cắm"}, {"id": "b2", "name": "Đèn"}]}
        self.tb.bo("tuya", "a1", ten_lich_su=["Ổ cắm"])
        with mock.patch.object(tuya_nha, "goi_api", return_value=tra):
            self.assertEqual([d["id"] for d in tuya_nha.danh_sach_thiet_bi()], ["b2"])


class NhomTest(unittest.TestCase):
    def test_nhom_ha_theo_mien_cam_bien_theo_lop_la_thi_KHAC(self) -> None:
        from api.hoc_hoi import nhom_ha

        self.assertEqual(nhom_ha("switch.bom", {}), "Công tắc")
        self.assertEqual(nhom_ha("automation.sang", {}), "Tự động hóa")
        self.assertEqual(nhom_ha("sensor.lux", {"device_class": "illuminance"}), "Cảm biến ánh sáng")
        self.assertEqual(nhom_ha("binary_sensor.pir", {"device_class": "occupancy"}), "Cảm biến hiện diện")
        self.assertEqual(nhom_ha("sensor.x", {}), "Cảm biến khác")
        self.assertEqual(nhom_ha("mien_moi_la.x", {}), "Khác", "miền chưa có tên không mất khỏi danh sách")

    def test_nhom_mqtt(self) -> None:
        from api.hoc_hoi import nhom_mqtt

        self.assertEqual(nhom_mqtt({"nguon": "frigate"}), "Camera")
        self.assertEqual(nhom_mqtt({"nguon": "tho"}), "Chưa nhận ra")
        self.assertEqual(nhom_mqtt({"nguon": "tu_khai_bao", "dieu_khien": [{"loai": "light"}]}), "Đèn")
        self.assertEqual(nhom_mqtt({"nguon": "tu_khai_bao",
                                    "dieu_khien": [{"loai": "light"}, {"loai": "switch"}]}),
                         "Có điều khiển")
        self.assertEqual(nhom_mqtt({"nguon": "tu_khai_bao", "dieu_khien": []}), "Cảm biến")


class EndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tb = _so_tam(self)
        from test.test_hoc_hoi_api import _app

        self.client, bo_qua = _app()
        self.addCleanup(bo_qua.stop)

    def test_BO_HA_ghi_so_va_xoa_lich_su_roi_KHOI_PHUC(self) -> None:
        st = [{"entity_id": "light.bep", "attributes": {"friendly_name": "Đèn bếp"}}]
        with mock.patch("services.ha_client.get_states", return_value=st), \
             mock.patch("services.lich_su_nha.xoa_thiet_bi",
                        return_value={"su_kien": 3, "so_do": 0, "tuoi": 1, "nhip": 1}) as xoa:
            d = self.client.post("/api/hoc-hoi/thiet-bi/bo",
                                 json={"nguon": "ha", "ma": "light.bep"}).json()
        self.assertTrue(d["ok"], d)
        xoa.assert_called_once_with(["light.bep"], [])
        self.assertTrue(self.tb.la_bo("ha", "light.bep"))
        self.assertEqual(self.tb.danh_sach()[0]["ten_goc"], "Đèn bếp")

        d = self.client.post("/api/hoc-hoi/thiet-bi/bo-lai",
                             json={"nguon": "ha", "ma": "light.bep"}).json()
        self.assertTrue(d["ok"])
        self.assertFalse(self.tb.la_bo("ha", "light.bep"))

    def test_BO_MQTT_goc_mot_doan_thi_TU_CHOI_va_KHONG_XOA(self) -> None:
        tb = {"ten": "zigbee2mqtt", "nguon": "tho",
              "doc": [{"chu_de": "zigbee2mqtt/A"}, {"chu_de": "zigbee2mqtt/B"}], "dieu_khien": []}
        with mock.patch("services.mqtt_nha.danh_sach_thiet_bi", return_value=[tb]), \
             mock.patch("services.lich_su_nha.xoa_thiet_bi") as xoa:
            d = self.client.post("/api/hoc-hoi/thiet-bi/bo",
                                 json={"nguon": "mqtt", "ma": "zigbee2mqtt"}).json()
        self.assertFalse(d["ok"])
        xoa.assert_not_called()
        self.assertEqual(self.tb.danh_sach(), [])

    def test_BO_MQTT_xoa_theo_goc_chu_de(self) -> None:
        tb = {"ten": "Hiện diện bếp", "nguon": "tu_khai_bao",
              "doc": [{"chu_de": "zigbee2mqtt/Hiện diện bếp"}],
              "dieu_khien": [{"chu_de": "zigbee2mqtt/Hiện diện bếp/set"}]}
        with mock.patch("services.mqtt_nha.danh_sach_thiet_bi", return_value=[tb]), \
             mock.patch("services.lich_su_nha.xoa_thiet_bi",
                        return_value={"su_kien": 0, "so_do": 0, "tuoi": 0, "nhip": 0}) as xoa:
            d = self.client.post("/api/hoc-hoi/thiet-bi/bo",
                                 json={"nguon": "mqtt", "ma": "Hiện diện bếp"}).json()
        self.assertTrue(d["ok"], d)
        xoa.assert_called_once_with([], ["zigbee2mqtt/Hiện diện bếp"])

    def test_KHONG_THAY_thiet_bi_hoac_NGUON_LA_thi_khong_ghi_so(self) -> None:
        with mock.patch("services.ha_client.get_states", return_value=[]):
            d = self.client.post("/api/hoc-hoi/thiet-bi/bo", json={"nguon": "ha", "ma": "light.x"}).json()
        self.assertFalse(d["ok"])
        d = self.client.post("/api/hoc-hoi/thiet-bi/bo", json={"nguon": "zigbee", "ma": "x"}).json()
        self.assertFalse(d["ok"])
        self.assertEqual(self.tb.danh_sach(), [])

    def test_BO_NHIEU_bo_muc_duoc_ghi_loi_muc_hong_va_doc_moi_nguon_MOT_lan(self) -> None:
        """Chủ máy 13/09/2026: "hơn 100 cái lâu quá" — bỏ một lượt theo các mục tích."""
        st = [{"entity_id": f"sensor.x{i}", "attributes": {"friendly_name": f"X{i}"}} for i in range(120)]
        mq = [{"ten": "zigbee2mqtt", "nguon": "tho", "doc": [{"chu_de": "zigbee2mqtt/A"},
                                                             {"chu_de": "zigbee2mqtt/B"}]},
              {"ten": "Camera bep", "nguon": "frigate", "doc": [{"chu_de": "frigate/bep/person"},
                                                                {"chu_de": "frigate/bep/all"}]}]
        self.tb.bo("ha", "sensor.da_bo_truoc", ten_goc="cũ")
        muc = ([{"nguon": "ha", "ma": f"sensor.x{i}"} for i in range(120)]
               + [{"nguon": "ha", "ma": "sensor.x0"},                      # lặp
                  {"nguon": "ha", "ma": "sensor.khong_co"},
                  {"nguon": "ha", "ma": "sensor.da_bo_truoc"},
                  {"nguon": "mqtt", "ma": "zigbee2mqtt"},                   # gốc một đoạn
                  {"nguon": "mqtt", "ma": "Camera bep"},
                  {"nguon": "zigbee", "ma": "x"}])
        with mock.patch("services.ha_client.get_states", return_value=st) as doc_ha, \
             mock.patch("services.mqtt_nha.danh_sach_thiet_bi", return_value=mq), \
             mock.patch("services.tuya_nha.danh_sach_thiet_bi") as doc_tuya, \
             mock.patch("services.lich_su_nha.xoa_thiet_bi",
                        return_value={"su_kien": 9, "so_do": 1, "tuoi": 0, "nhip": 0}) as xoa, \
             mock.patch.object(self.tb, "_luu", wraps=self.tb._luu) as luu:
            d = self.client.post("/api/hoc-hoi/thiet-bi/bo-nhieu", json={"muc": muc}).json()
        self.assertTrue(d["ok"], d)
        self.assertEqual(len(d["da_bo"]), 121)
        self.assertEqual(sorted(x["ma"] for x in d["loi"]),
                         ["sensor.da_bo_truoc", "sensor.khong_co", "x", "zigbee2mqtt"])
        doc_ha.assert_called_once()
        doc_tuya.assert_not_called()
        self.assertEqual(luu.call_count, 1, "sổ bỏ ghi đĩa một lần cho cả lượt")
        xoa.assert_called_once()
        self.assertEqual(len(xoa.call_args[0][0]), 120)
        self.assertEqual(xoa.call_args[0][1], ["frigate/bep"])
        self.assertTrue(self.tb.la_bo("mqtt", "Camera bep"))
        self.assertFalse(self.tb.la_bo("mqtt", "zigbee2mqtt"))

    def test_BO_NHIEU_than_sai_dang_thi_khong_lam_gi(self) -> None:
        for than in ({}, {"muc": []}, {"muc": "sensor.x"}, {"muc": ["sensor.x"]},
                     {"muc": [{"nguon": "ha", "ma": "x"}] * 2001}):
            with self.subTest(than=str(than)[:40]), \
                 mock.patch("services.lich_su_nha.xoa_thiet_bi") as xoa:
                d = self.client.post("/api/hoc-hoi/thiet-bi/bo-nhieu", json=than).json()
                self.assertFalse(d["ok"])
                xoa.assert_not_called()
        self.assertEqual(self.tb.danh_sach(), [])

    def test_DANH_SACH_co_nhom_va_KEM_DA_BO_chi_khi_xin(self) -> None:
        self.tb.bo("ha", "light.cu", ten_goc="Đèn cũ")
        st = [{"entity_id": "switch.bom", "attributes": {"friendly_name": "Bơm"}}]
        with mock.patch("services.ha_client.get_states", return_value=st), \
             mock.patch("services.ha_client.get_ha_area_index", return_value={}), \
             mock.patch("services.mqtt_nha.danh_sach_thiet_bi", return_value=[]), \
             mock.patch("services.tuya_nha.danh_sach_thiet_bi", return_value=[]):
            thuong = self.client.get("/api/hoc-hoi/thiet-bi-day-du").json()["danh_sach"]
            kem = self.client.get("/api/hoc-hoi/thiet-bi-day-du?kem_da_bo=1").json()["danh_sach"]
        self.assertEqual([(m["ma"], m["nhom"], m["da_bo"]) for m in thuong],
                         [("switch.bom", "Công tắc", False)])
        self.assertEqual(sorted((m["ma"], m["da_bo"]) for m in kem),
                         [("light.cu", True), ("switch.bom", False)])


if __name__ == "__main__":
    unittest.main()
