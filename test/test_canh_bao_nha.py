"""Test cảnh báo thiết bị hỏng — nhịp báo lại và cơ chế «tôi biết rồi»."""

from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock


class CanhBaoTest(unittest.TestCase):
    def setUp(self) -> None:
        import services.canh_bao_nha as m

        self._tmp = TemporaryDirectory()
        self.m = m
        m._FILE = Path(self._tmp.name) / "canh_bao.json"
        m.config.data.setdefault("mqtt", {})["canh_bao"] = {"bat": True}

    def tearDown(self) -> None:
        self.m._reset_for_tests()
        self._tmp.cleanup()

    def _hong(self, ten="cb_bep", loai="do", truong="illuminance"):
        return [{"thiet_bi": ten, "truong": truong, "loai": loai,
                 "chi_tiet": "chỉ một giá trị 86 suốt 3 ngày"}]

    def _quet(self, hong):
        from services import lich_su_nha
        with mock.patch.object(lich_su_nha, "soi_hong", return_value=hong):
            return self.m.quet(7)

    # ── nhịp báo lại ───────────────────────────────────────────────────────
    def test_lan_dau_bao_ngay(self) -> None:
        kq = self._quet(self._hong())
        self.assertEqual(len(kq["can_bao"]), 1)

    def test_bao_xong_thi_im_cho_du_5_phut(self) -> None:
        """Bậc 0 = 5 phút. Quét lại ngay sau đó KHÔNG được báo tiếp."""
        kq = self._quet(self._hong())
        self.m._len_bac(kq["khoa"])
        self.assertEqual(len(self._quet(self._hong())["can_bao"]), 0)

    def test_nhip_dung_5_30_60_6h_roi_hang_ngay(self) -> None:
        """Đúng thứ tự chủ máy chốt: 5p → 30p → 60p → 6h → mỗi ngày."""
        self.assertEqual(self.m._NHIP,
                         (5 * 60, 30 * 60, 60 * 60, 6 * 3600, 24 * 3600))

    def test_qua_moc_thi_bao_lai(self) -> None:
        now = time.time()
        for bac, cho in enumerate((5 * 60, 30 * 60, 60 * 60, 6 * 3600)):
            bg = {"bac": bac, "bao_cuoi": now - cho - 1,
                  "lan_hong": 1, "im_lan": None}
            self.assertTrue(self.m._den_han(bg, now),
                            f"bậc {bac}: qua {cho}s rồi phải báo lại")
            bg["bao_cuoi"] = now - cho + 30
            self.assertFalse(self.m._den_han(bg, now),
                             f"bậc {bac}: chưa đủ {cho}s thì chưa báo")

    def test_bac_cuoi_bao_dung_gio_nguoi_dung_chon(self) -> None:
        """Mỗi ngày phải báo vào GIỜ đã chọn, không phải đúng 24h sau lần trước.

        Nếu cứ +24h thì giờ báo trôi dần mỗi ngày, cuối cùng báo lúc nửa đêm.
        """
        self.m.config.data["mqtt"]["canh_bao"] = {"bat": True, "gio_hang_ngay": 8}
        tz = timezone(timedelta(hours=7))
        bg = {"bac": 4, "lan_hong": 1, "im_lan": None}

        t8 = datetime(2026, 9, 10, 8, 30, tzinfo=tz).timestamp()
        bg["bao_cuoi"] = t8 - 25 * 3600
        self.assertTrue(self.m._den_han(bg, t8), "8h sáng, quá 24h → phải báo")

        t15 = datetime(2026, 9, 10, 15, 0, tzinfo=tz).timestamp()
        bg["bao_cuoi"] = t15 - 25 * 3600
        self.assertFalse(self.m._den_han(bg, t15), "15h không phải giờ đã chọn")

    def test_nhip_day_du_dung_thu_tu_chu_may_yeu_cau(self) -> None:
        """5p → 30p → 60p → 6h. Lần báo ĐẦU không được tiêu mất mốc 5 phút.

        Lỗi đã gặp: nâng bậc ngay lần đầu thì nhịp thành ngay→30p→60p→6h,
        mốc 5 phút biến mất.
        """
        def tua(giay: float) -> None:
            so = self.m._doc()
            k = next(iter(so["muc"]))
            so["muc"][k]["bao_cuoi"] = time.time() - giay
            self.m._ghi(so)

        kq = self._quet(self._hong())
        self.assertEqual(len(kq["can_bao"]), 1, "lần đầu phải báo ngay")
        self.m._len_bac(kq["khoa"])

        for nhan, giay in (("5 phút", 301), ("30 phút", 1801),
                           ("60 phút", 3601), ("6 giờ", 6 * 3600 + 1)):
            tua(giay)
            kq = self._quet(self._hong())
            self.assertEqual(len(kq["can_bao"]), 1, f"mốc {nhan} phải báo lại")
            self.m._len_bac(kq["khoa"])

    def test_bac_khong_vuot_qua_hang_ngay(self) -> None:
        kq = self._quet(self._hong())
        for _ in range(10):
            self.m._len_bac(kq["khoa"])
        bg = next(iter(self.m._doc()["muc"].values()))
        self.assertEqual(bg["bac"], len(self.m._NHIP) - 1)

    # ── «tôi biết rồi» ─────────────────────────────────────────────────────
    def test_im_di_thi_thoi_bao(self) -> None:
        self._quet(self._hong())
        self.m.im_di("cb_bep")
        self.assertEqual(len(self._quet(self._hong())["can_bao"]), 0)

    def test_SUA_XONG_HONG_LAI_VAN_BAO(self) -> None:
        """Mấu chốt của cả module.

        Tắt theo TÊN thiết bị thì sau khi sửa xong hỏng lại sẽ im luôn — mà đó
        đúng là lúc cần biết nhất. Phải phân biệt bằng lượt hỏng.
        """
        self._quet(self._hong())
        self.m.im_di("cb_bep")
        self.assertEqual(len(self._quet(self._hong())["can_bao"]), 0, "đã tắt")

        self._quet([])                                    # thiết bị KHỎI
        kq = self._quet(self._hong())                     # rồi HỎNG LẠI
        self.assertEqual(len(kq["can_bao"]), 1,
                         "sửa xong hỏng lại PHẢI báo — đây là lượt hỏng mới")

    def test_im_mot_loi_khong_lam_im_loi_khac(self) -> None:
        hai = self._hong("cb_bep") + self._hong("cb_phong_khach", loai="chet")
        self._quet(hai)
        self.m.im_di("cb_bep")
        con = self._quet(hai)["can_bao"]
        self.assertEqual([h["thiet_bi"] for h in con], ["cb_phong_khach"])

    def test_im_theo_dung_loai_hong(self) -> None:
        """Cùng thiết bị, hai loại hỏng khác nhau là hai lỗi riêng."""
        hai = (self._hong("cb", loai="do", truong="illuminance")
               + self._hong("cb", loai="chap_chon", truong="illuminance"))
        self._quet(hai)
        self.m.im_di("cb", truong="illuminance", loai="do")
        con = self._quet(hai)["can_bao"]
        self.assertEqual([h["loai"] for h in con], ["chap_chon"])

    def test_bo_im_bat_bao_lai(self) -> None:
        self._quet(self._hong())
        self.m.im_di("cb_bep")
        self.m.bo_im()
        self.assertEqual(len(self._quet(self._hong())["can_bao"]), 1)

    # ── gửi ────────────────────────────────────────────────────────────────
    def test_khong_gui_khi_chua_khai_nguoi_nhan(self) -> None:
        from services import lich_su_nha
        self.m.config.data["mqtt"]["canh_bao"] = {"bat": True, "nguoi_nhan": []}
        with mock.patch.object(lich_su_nha, "soi_hong", return_value=self._hong()), \
             mock.patch.object(self.m, "_nguoi_nhan", return_value=[]):
            kq = self.m.chay_mot_lan()
        self.assertEqual(kq["gui"], 0)
        self.assertIn("người nhận", kq.get("ly_do", ""))

    def test_gui_toi_tung_nguoi_nhan(self) -> None:
        from services import lich_su_nha
        with mock.patch.object(lich_su_nha, "soi_hong", return_value=self._hong()), \
             mock.patch.object(self.m, "_nguoi_nhan", return_value=["u1", "u2"]), \
             mock.patch.object(self.m, "_gui") as g:
            kq = self.m.chay_mot_lan()
        self.assertEqual(kq["gui"], 2)
        self.assertEqual(g.call_count, 2)

    def test_gui_hong_van_khong_raise(self) -> None:
        from services import lich_su_nha
        with mock.patch.object(lich_su_nha, "soi_hong", return_value=self._hong()), \
             mock.patch.object(self.m, "_nguoi_nhan", return_value=["u1"]), \
             mock.patch.object(self.m, "_gui", side_effect=RuntimeError("mất mạng")):
            kq = self.m.chay_mot_lan()
        self.assertEqual(kq["gui"], 0)

    def test_khong_len_bac_khi_gui_that_bai(self) -> None:
        """Gửi hỏng mà vẫn lên bậc thì lần sau phải chờ lâu hơn — mất tin."""
        from services import lich_su_nha
        with mock.patch.object(lich_su_nha, "soi_hong", return_value=self._hong()), \
             mock.patch.object(self.m, "_nguoi_nhan", return_value=["u1"]), \
             mock.patch.object(self.m, "_gui", side_effect=RuntimeError("x")):
            self.m.chay_mot_lan()
        bg = next(iter(self.m._doc()["muc"].values()))
        self.assertEqual(bg["bac"], 0, "gửi hỏng thì KHÔNG được lên bậc")

    def test_tin_gon_khong_do_156_loi_mot_luc(self) -> None:
        """Nhà thật có 156 lỗi — dội hết một lượt là người dùng tắt thông báo."""
        nhieu = [{"thiet_bi": f"cb{i}", "truong": "state", "loai": "do",
                  "chi_tiet": "x"} for i in range(156)]
        tin = self.m._soan_tin(nhieu, 156)
        self.assertLessEqual(tin.count("\n   "), self.m._toi_da_moi_lan())
        self.assertIn("156", tin)
        self.assertIn("tôi biết rồi", tin)

    def test_soi_hong_loi_thi_khong_raise(self) -> None:
        from services import lich_su_nha
        with mock.patch.object(lich_su_nha, "soi_hong",
                               side_effect=RuntimeError("DB hỏng")):
            kq = self.m.quet()
        self.assertEqual(kq["can_bao"], [])
        self.assertIn("loi", kq)

    def test_tat_trong_cau_hinh_thi_khong_lam_gi(self) -> None:
        self.m.config.data["mqtt"]["canh_bao"] = {"bat": False}
        self.assertEqual(self.m.chay_mot_lan()["gui"], 0)

    def test_trang_thai_dem_dung(self) -> None:
        hai = self._hong("a") + self._hong("b")
        self._quet(hai)
        self.m.im_di("a")
        t = self.m.trang_thai()
        self.assertEqual(t["dang_hong"], 2)
        self.assertEqual(t["dang_im"], 1)


if __name__ == "__main__":
    unittest.main()
