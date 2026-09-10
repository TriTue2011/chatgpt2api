"""Nghe thiết bị Tuya thẳng trong mạng nhà — không qua đám mây, không cần HA."""

from __future__ import annotations

import unittest
from unittest import mock


class TuyaLocalTest(unittest.TestCase):
    def setUp(self) -> None:
        import services.tuya_local as m
        self.m = m
        m.config.data.setdefault("tuya", {})["local"] = {}

    def tearDown(self) -> None:
        self.m._reset_for_tests()
        self.m.config.data.get("tuya", {}).pop("local", None)

    # ── trạng thái thật của nhà hiện tại ───────────────────────────────────
    def test_KHONG_CO_THIET_BI_thi_nam_im_KHONG_LOI(self) -> None:
        """Đo thật 10/09/2026: nghe UDP có giải mã 30 giây → 0 thiết bị; quét
        cổng 6668 trên 20 máy đang sống → 0 máy mở. Đây là đường đi BÌNH
        THƯỜNG, không phải lỗi — nhà chỉ có gateway Zigbee và khoá cửa chạy
        pin, cả hai đều không nói chuyện local được.
        """
        # Gọi thẳng `_noi_that`: `start()` chỉ khởi luồng nền rồi trả về ngay
        # (để không làm bot khởi động chậm 8 giây vì nghe UDP).
        with mock.patch.object(self.m, "do_thiet_bi", return_value=[]):
            self.assertFalse(self.m._noi_that())
        t = self.m.trang_thai()
        self.assertFalse(t["dang_chay"])
        self.assertEqual(t["so_thiet_bi"], 0)
        self.assertIn("chưa có thiết bị", t["loi"])

    def test_tat_trong_cau_hinh_thi_khong_chay(self) -> None:
        self.m.config.data["tuya"]["local"] = {"bat": False}
        self.assertFalse(self.m.is_enabled())
        self.assertFalse(self.m.start())

    def test_mac_dinh_la_BAT(self) -> None:
        self.assertTrue(self.m.is_enabled())

    # ── dò thiết bị ────────────────────────────────────────────────────────
    def test_do_thiet_bi_loc_cai_thieu_ip(self) -> None:
        from tinytuya import scanner
        gia = {"abc123": {"ip": "192.168.1.5", "version": "3.3"},
               "khong_ip": {"version": "3.3"}}
        with mock.patch.object(scanner, "devices", return_value=gia):
            ra = self.m.do_thiet_bi(1)
        self.assertEqual(len(ra), 1)
        self.assertEqual(ra[0]["ip"], "192.168.1.5")

    def test_DO_HONG_thi_tra_RONG_khong_nem_loi(self) -> None:
        from tinytuya import scanner
        with mock.patch.object(scanner, "devices",
                               side_effect=RuntimeError("mạng hỏng")):
            self.assertEqual(self.m.do_thiet_bi(1), [])

    # ── nhận đẩy ───────────────────────────────────────────────────────────
    def test_thiet_bi_doi_thi_GHI_LICH_SU(self) -> None:
        from services import lich_su_nha
        dev = mock.Mock(id="abc123")
        with mock.patch.object(lich_su_nha, "ghi") as g:
            self.m._khi_doi(dev, {"dps": {"1": True, "9": 30}})
        self.assertEqual(g.call_count, 2)
        self.assertEqual(g.call_args_list[0][0][0], "tuya_local")

    def test_BO_QUA_do_dien_lien_tuc(self) -> None:
        """Công suất/điện áp đo liên tục, không nói lên hành vi người — cùng
        nguyên tắc với bộ lọc của `ha_live`."""
        from services import lich_su_nha
        dev = mock.Mock(id="abc123")
        with mock.patch.object(lich_su_nha, "ghi") as g:
            self.m._khi_doi(dev, {"dps": {"cur_power": 120, "cur_voltage": 230}})
        g.assert_not_called()

    def test_GHI_HONG_khong_lam_chet_luong_nghe(self) -> None:
        from services import lich_su_nha
        dev = mock.Mock(id="abc123")
        with mock.patch.object(lich_su_nha, "ghi",
                               side_effect=RuntimeError("đĩa đầy")):
            try:
                self.m._khi_doi(dev, {"dps": {"1": True}})
            except Exception as exc:
                self.fail(f"không được ném lỗi: {exc}")

    def test_du_lieu_la_thi_bo_qua(self) -> None:
        dev = mock.Mock(id="abc")
        for xau in (None, {}, {"dps": None}, {"dps": {}}, "chuỗi"):
            try:
                self.m._khi_doi(dev, xau)
            except Exception as exc:
                self.fail(f"{xau!r}: {exc}")

    # ── mất kết nối ────────────────────────────────────────────────────────
    def test_LOI_GIAI_MA_hieu_la_KHOA_DOI(self) -> None:
        """Bài học từ code localtuya: lỗi giải mã nghĩa là `local_key` đã đổi
        (Tuya đổi khoá khi ghép nối lại), không phải mạng hỏng. Nối lại với
        khoá cũ là vô ích — phải quên thiết bị đi để vòng sau lấy khoá mới."""
        self.m._thiet_bi["abc"] = {"ip": "1.2.3.4", "version": "3.3"}
        self.m._khi_dut(mock.Mock(id="abc"), "UnicodeDecodeError: utf-8")
        self.assertNotIn("abc", self.m._thiet_bi, "phải quên để lấy khoá mới")

    def test_dut_mang_thuong_thi_GIU_thiet_bi(self) -> None:
        """Mạng chập chờn thì Monitor tự nối lại, không cần lấy khoá mới."""
        self.m._thiet_bi["abc"] = {"ip": "1.2.3.4", "version": "3.3"}
        self.m._khi_dut(mock.Mock(id="abc"), "Connection reset by peer")
        self.assertIn("abc", self.m._thiet_bi)

    # ── không kéo sập bot ──────────────────────────────────────────────────
    def test_MONITOR_HONG_thi_tat_phan_local_thoi(self) -> None:
        """`Monitor` là lớp thực nghiệm (chính docstring tinytuya ghi vậy) —
        hỏng thì phần còn lại của bot vẫn phải chạy."""
        import tinytuya
        with mock.patch.object(self.m, "do_thiet_bi",
                               return_value=[{"id": "a", "ip": "1.2.3.4",
                                              "version": "3.3"}]), \
             mock.patch.object(tinytuya, "Monitor",
                               side_effect=RuntimeError("lớp thực nghiệm hỏng")):
            self.assertFalse(self.m._noi_that())
        self.assertIn("Monitor", self.m.trang_thai()["loi"])

    def test_khong_lay_duoc_khoa_thi_bo_qua_thiet_bi_do(self) -> None:
        with mock.patch.object(self.m, "do_thiet_bi",
                               return_value=[{"id": "a", "ip": "1.2.3.4",
                                              "version": "3.3"}]), \
             mock.patch.object(self.m, "_lay_khoa", return_value=""):
            self.assertFalse(self.m._noi_that())

    def test_START_KHONG_LAM_CHAM_KHOI_DONG(self) -> None:
        """`do_thiet_bi` nghe UDP 8 giây. Làm thẳng trong `api/app.py` là bot
        khởi động chậm thêm 8 giây mỗi lần, cho một tính năng hôm nay nhà chưa
        dùng tới."""
        import time
        with mock.patch.object(self.m, "do_thiet_bi",
                               side_effect=lambda *a, **k: time.sleep(2) or []):
            t0 = time.time()
            self.m.start()
            mat = time.time() - t0
        self.assertLess(mat, 0.5, "start() phải trả về ngay, không chờ dò")

    def test_stop_goi_nhieu_lan_khong_sao(self) -> None:
        self.m.stop()
        self.m.stop()
        self.assertFalse(self.m.trang_thai()["dang_chay"])

    # ── bí mật ─────────────────────────────────────────────────────────────
    def test_TRANG_THAI_KHONG_LO_local_key(self) -> None:
        """`local_key` cho phép điều khiển thiết bị trong mạng — không được
        lọt ra web hay log."""
        self.m._thiet_bi["abc"] = {"ip": "1.2.3.4", "version": "3.3",
                                   "ten": "ổ cắm"}
        t = self.m.trang_thai()
        self.assertNotIn("local_key", str(t))
        self.assertNotIn("khoa", str(t.get("thiet_bi")))


if __name__ == "__main__":
    unittest.main()
