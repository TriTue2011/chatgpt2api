"""Test tầng thói quen — chặng 1: bot chọn NGOẠI VI theo khu vực cho từng thiết bị.

Mỗi ca khoá một quyết định nêu lý do trong `services/thoi_quen_nha.py`.
"""

from __future__ import annotations

import json
import time
import unittest
from tempfile import TemporaryDirectory
from unittest import mock

from test.test_hieu_thiet_bi_nha import _nap

#: Sổ khu vực giả, khuôn theo `boi_canh_nha._nap_so_phong`: (mã → khu, tên
#: không dấu → tên gốc). Công tắc "Đèn ban công" nằm ở khu Bếp — đúng ca đo 13/09.
_SO = ({"switch.bep_center": "Bếp", "switch.binh_nong_lanh": "Nhà tắm"},
       {"bep": "Bếp", "ban cong": "Ban công", "nha tam": "Nhà tắm",
        "phong khach": "Phòng khách"})


def _phong(tb: str) -> str:
    from services.boi_canh_nha import _khong_dau
    t = _khong_dau(tb)
    for kd, goc in sorted(_SO[1].items(), key=lambda x: -len(x[0])):
        if kd in t:
            return goc
    return _SO[0].get(tb, "")


class ThoiQuenNhaTest(unittest.TestCase):
    def setUp(self) -> None:
        import services.thoi_quen_nha as tq

        self._tmp = TemporaryDirectory()
        self.ht, self.bc, self.ls = _nap(self._tmp.name)
        self.tq = tq
        mqtt = self.ls.config.data.setdefault("mqtt", {})
        mqtt["lich_su"] = {"bat": True}
        mqtt["hieu_thiet_bi"] = {"bat": True}
        self.ls._db()          # tạo bảng trước khi đọc chỉ-đọc
        for p in (mock.patch.object(self.bc, "_nap_so_phong", return_value=_SO),
                  mock.patch.object(self.bc, "phong_cua", side_effect=_phong)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self) -> None:
        self.ht._reset_for_tests()
        self.ls._reset_for_tests()
        self.bc._reset_for_tests()
        self._tmp.cleanup()

    def _sk(self, thiet_bi: str, gt: str, ts: float, truong: str = "state") -> None:
        with self.ls._khoa_db:
            conn = self.ls._db()
            conn.execute(
                "INSERT INTO su_kien (ts, nguon, thiet_bi, truong, gia_tri,"
                " gia_tri_cu, do_ai, gio, thu) VALUES (?,?,?,?,?,?,0,12,1)",
                (ts, "mqtt" if "/" in thiet_bi else "ha", thiet_bi, truong, gt, ""))
            conn.commit()

    def _sd(self, thiet_bi: str, truong: str, ts: float, gt: float) -> None:
        with self.ls._khoa_db:
            conn = self.ls._db()
            conn.execute("INSERT INTO so_do (o_5p, thiet_bi, truong, nho, lon, tb, n)"
                         " VALUES (?,?,?,?,?,?,1)", (int(ts // 300), thiet_bi, truong, gt, gt, gt))
            conn.commit()

    # ── khu vực liên quan ──────────────────────────────────────────────────
    def test_ten_noi_khu_khac_khu_HA_thi_bay_CA_HAI(self) -> None:
        self.assertEqual(self.tq._khu_vuc_lien_quan("switch.bep_center", "Đèn ban công", []),
                         ["Bếp", "Ban công"])

    def test_du_kien_nhac_ten_thiet_bi_thi_bay_khu_trong_dong_do(self) -> None:
        """"Bình nóng lạnh lấy theo … cảm biến nhiệt ẩm ban công" (11/09/2026)."""
        du_kien = [{"id": 2, "noi_dung":
                    "Bình nóng lạnh lấy theo thời tiết, cảm biến nhiệt ẩm ban công\n"
                    "Cảm biến phòng khách là cảm biến, làm điều kiện cho đèn trần"}]
        self.assertEqual(
            self.tq._khu_vuc_lien_quan("switch.binh_nong_lanh", "Bình nóng lạnh", du_kien),
            ["Nhà tắm", "Ban công"],
            "dòng thứ hai không nhắc bình nóng lạnh — không được kéo Phòng khách vào")

    # ── đề ─────────────────────────────────────────────────────────────────
    def test_de_chi_co_ngoai_vi_khu_lien_quan_va_bo_dung_hai_thu_do_duoc(self) -> None:
        now = time.time()
        for i in range(10):
            t = now - 86400 + i * 3600
            self._sk("switch.bep_center", "on" if i % 2 == 0 else "off", t)
            self._sk("zigbee2mqtt/Bếp#state_center", "ON" if i % 2 == 0 else "OFF", t)
            self._sk("zigbee2mqtt/Hiện diện ban công", "True" if i % 2 == 0 else "False",
                     t - 30, truong="presence")
            self._sk("binary_sensor.hien_dien_bep", "on" if i % 3 else "off", t + 5)
            self._sk("sensor.phong_khach_person_count", str(i % 3), t)
        self._sk("switch.ban_cong_motion", "on", now - 5000)          # MỘT giá trị
        self._sk("camera.rtsp_tk_mk_ban_cong", "idle", now - 4000)    # không còn trong HA
        self._sk("camera.rtsp_tk_mk_ban_cong", "streaming", now - 3000)
        self._sd("zigbee2mqtt/Hiện diện ban công", "illuminance", now - 7200, 12.0)
        self._sd("zigbee2mqtt/Hiện diện ban công", "illuminance", now - 3600, 480.0)

        kho = self.tq._doc_kho(now - 2 * 86400, now + 1)
        uv = self.tq.ung_vien(
            "switch.bep_center", kho, ten_ha={"switch.bep_center": "Đèn ban công"},
            du_kien=[], bo_ma={"switch.bep_center", "zigbee2mqtt/Bếp#state_center"},
            con_trong_ha={"switch.bep_center", "binary_sensor.hien_dien_bep",
                          "switch.ban_cong_motion", "sensor.phong_khach_person_count"})
        self.assertEqual(uv["khu_vuc"], ["Bếp", "Ban công"])
        self.assertEqual(sorted(uv["ngoai_vi"]), [
            "binary_sensor.hien_dien_bep",
            "zigbee2mqtt/Hiện diện ban công#illuminance",
            "zigbee2mqtt/Hiện diện ban công#presence"])
        self.assertEqual(uv["so_bat"], 5)
        self.assertEqual(uv["ngoai_vi"]["zigbee2mqtt/Hiện diện ban công#presence"]["quanh"], "100%")
        de = self.tq.de_bai(uv, [])
        self.assertIn("NGOẠI VI — khu vực Ban công:", de)
        self.assertNotIn("person_count", de, "khu Phòng khách không liên quan")
        self.assertNotIn("rtsp", de, "mã HA vắng khỏi HA có thể mang mật khẩu camera")

    # ── kiểm ở biên ────────────────────────────────────────────────────────
    UV = {"ma": "switch.bep_center", "khu_vuc": ["Bếp", "Ban công"],
          "ngoai_vi": {"a#presence": {"ten": "Hiện diện ban công · presence"},
                       "b": {"ten": "Hiện diện bếp"}}}

    def test_kiem_nhan_bai_dung_va_gan_ten_do_code(self) -> None:
        kq = self.tq.kiem({"khu_vuc": "Ban công", "chac": 0.8, "vi_sao": "tên nói ban công",
                           "ngoai_vi": [{"ma": "a#presence", "vai_tro": "hien_dien"}]}, self.UV)
        self.assertEqual(kq["ngoai_vi"], [{"ma": "a#presence", "vai_tro": "hien_dien",
                                          "ten": "Hiện diện ban công · presence"}])

    def test_kiem_loai_bai_pham_luat(self) -> None:
        tot = {"khu_vuc": "Ban công", "ngoai_vi": [{"ma": "b", "vai_tro": "hien_dien"}]}
        for sai, ly_do in (
                ({**tot, "khu_vuc": "Phòng ngủ"}, "khu vực không có trong đề"),
                ({**tot, "ngoai_vi": [{"ma": "bia", "vai_tro": "hien_dien"}]}, "mã không có"),
                ({**tot, "ngoai_vi": [{"ma": "b", "vai_tro": "doan_mo"}]}, "vai trò lạ"),
                ({**tot, "ngoai_vi": [{"ma": "b", "vai_tro": "khac"}] * 2}, "mã lặp"),
                ({**tot, "ngoai_vi": [{"ma": "b", "vai_tro": "khac"}] * 6}, "tối đa 5")):
            with self.subTest(ly_do):
                self.assertIsInstance(self.tq.kiem(sai, self.UV), str)

    def test_de_dinh_mat_khau_thi_KHONG_goi_model(self) -> None:
        with mock.patch.object(self.ht, "thiet_bi_hoc", return_value=["switch.x"]), \
             mock.patch.object(self.ht, "_ten_ha",
                               return_value={"switch.x": "Cam rtsp://tk:mk@10.0.0.2:8554"}), \
             mock.patch("services.ha_client.get_states",
                        return_value=[{"entity_id": "switch.x", "attributes": {}}]), \
             mock.patch.object(self.ht, "huong_dan", return_value=("hd", "ban")), \
             mock.patch.object(self.ht, "_model", return_value="m"), \
             mock.patch.object(self.ht, "_goi_model") as goi:
            kq = self.tq.giai()
        goi.assert_not_called()
        self.assertEqual(len(kq["loi"]), 1)

    # ── lưu sổ ─────────────────────────────────────────────────────────────
    def _ket_luan(self, **doi) -> dict:
        k = {"ma_hoc": "switch.bep_left", "khu_vuc": "Bếp", "chac": 0.9, "vi_sao": "cùng bếp",
             "ngoai_vi": [{"ma": "binary_sensor.hien_dien_bep", "vai_tro": "hien_dien",
                           "ten": "Hiện diện bếp"}]}
        k.update(doi)
        return k

    def test_luot_HIEU_THIET_BI_hang_ngay_KHONG_xoa_ket_luan_ngoai_vi(self) -> None:
        """`ghi_ket_qua` vô hiệu mọi câu có chung mã — trước đây kể cả câu của tầng khác."""
        self.ht.ghi_ngoai_vi(self.ht._ghi_lan("b", "m", 1, 1, 0, 0, ""), [self._ket_luan()])
        g = {"ma": ["switch.bep_left"], "ma_hoc": "switch.bep_left", "nguon_nhanh": "",
             "loai": "bat_tat", "hoc": True, "chac": 0.9, "vi_sao": "", "dieu_kien": ["buoi"]}
        self.ht.ghi_ket_qua(self.ht._ghi_lan("b", "m", 1, 1, 0, 0, ""), [g])
        con = [d for d in self.ht.dang_hieu_luc() if d["loai_cau_hoi"] == "ngoai_vi"]
        self.assertEqual(len(con), 1)

    def test_luot_CHON_NGOAI_VI_khong_nuot_du_kien_moi_cua_luot_hieu_thiet_bi(self) -> None:
        """Hai việc chung bảng lượt giải: lượt của việc này không được làm việc kia
        tưởng dữ kiện mới đã được xem."""
        self.ht._ghi_lan("b", "m", 1, 1, 0, 0, "")                       # hiểu thiết bị
        self.ht.ghi_du_kien("Đèn hiên theo cảm biến hiên")
        self.ht._ghi_lan("b", "m", 1, 1, 0, 0, "", viec="ngoai_vi")      # chọn ngoại vi
        self.assertTrue(self.ht.co_du_kien_moi(), "lượt hiểu thiết bị chưa xem dữ kiện này")
        self.assertFalse(self.ht.co_du_kien_moi("ngoai_vi"))
        self.assertEqual(len(self.ht.lich_su_giai()), 1, "lịch sử giải chỉ kể lượt hiểu thiết bị")

    def test_ngoai_vi_hoc_chi_lay_thiet_bi_duoc_hoc_va_bo_cau_sai(self) -> None:
        ghi = self.ht.ghi_ngoai_vi(self.ht._ghi_lan("b", "m", 1, 1, 0, 0, ""), [self._ket_luan()])
        with mock.patch.object(self.ht, "thiet_bi_hoc", return_value=["switch.bep_left"]):
            self.assertEqual(self.ht.ngoai_vi_hoc()["switch.bep_left"]["khu_vuc"], "Bếp")
            self.ht.cham(ghi["moi"][0]["id"], False, cham_boi="claude")
            self.assertEqual(self.ht.ngoai_vi_hoc(), {})

    def test_cau_hoi_doc_duoc_ten_ngoai_vi(self) -> None:
        ghi = self.ht.ghi_ngoai_vi(self.ht._ghi_lan("b", "m", 1, 1, 0, 0, ""), [self._ket_luan()])
        d = next(x for x in self.ht.dang_hieu_luc() if x["id"] == ghi["moi"][0]["id"])
        cau = self.ht._cau_doc(d, {"switch.bep_left": "Đèn bếp"})
        self.assertEqual(cau, "Đèn bếp [switch] ở Bếp, đi theo: Hiện diện bếp (hiện diện)")
        self.assertNotIn("binary_sensor", cau)

    def test_luu_lai_y_het_thi_khong_hoi_lai(self) -> None:
        lan = self.ht._ghi_lan("b", "m", 1, 1, 0, 0, "")
        self.assertEqual(len(self.ht.ghi_ngoai_vi(lan, [self._ket_luan()])["moi"]), 1)
        self.assertEqual(self.ht.ghi_ngoai_vi(lan, [self._ket_luan(vi_sao="khác chữ")])["moi"], [])
        doi = self._ket_luan(khu_vuc="Ban công")
        self.assertEqual(len(self.ht.ghi_ngoai_vi(lan, [doi])["moi"]), 1)


if __name__ == "__main__":
    unittest.main()
