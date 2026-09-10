"""Test tầng xác suất — "căn cứ điều kiện, có nên bật không".

Mỗi ca khoá một quyết định thiết kế đã nêu lý do trong `du_doan_nha.py`.
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock


def _nap(thu_muc: str):
    import services.boi_canh_nha as bc
    import services.du_doan_nha as dd
    import services.lich_su_nha as ls

    ls._reset_for_tests()
    ls._DB_PATH = Path(thu_muc) / "lich_su_nha.sqlite"
    ls._conn = None
    dd._reset_for_tests()
    dd._DB_PATH = Path(thu_muc) / "du_doan_nha.sqlite"
    dd._conn = None
    bc._reset_for_tests()
    return dd, bc, ls


class DuDoanNhaTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.dd, self.bc, self.ls = _nap(self._tmp.name)
        self.ls.config.data.setdefault("mqtt", {})["lich_su"] = {"bat": True}
        self.ls.config.data["mqtt"]["du_doan"] = {"bat": True}
        self._p = mock.patch.object(self.bc, "phong_cua", return_value="Bếp")
        self._p.start()
        self.addCleanup(self._p.stop)

    def tearDown(self) -> None:
        self.dd._reset_for_tests()
        self.ls._reset_for_tests()
        self.bc._reset_for_tests()
        self._tmp.cleanup()

    def _sk(self, thiet_bi: str, gt: str, ts: float, do_ai: int = 0) -> None:
        with self.ls._khoa_db:
            conn = self.ls._db()
            conn.execute(
                "INSERT INTO su_kien (ts, nguon, thiet_bi, truong, gia_tri,"
                " gia_tri_cu, do_ai, gio, thu) VALUES (?,?,?,?,?,?,?,12,1)",
                (ts, "mqtt", thiet_bi, "state", gt, "", do_ai))
            conn.commit()

    def _nep_toi(self, ngay: int = 14, gio: int = 19) -> None:
        """Dựng nếp: tối nào cũng bật đèn bếp, sáng thì không."""
        from datetime import datetime, timedelta
        now = datetime.now(self.bc._TZ).replace(
            hour=gio, minute=0, second=0, microsecond=0)
        for i in range(ngay):
            d = now - timedelta(days=i)
            self._sk("light.bep", "on", d.timestamp())
            self._sk("light.bep", "off", (d + timedelta(hours=3)).timestamp())
            sang = d.replace(hour=8)
            self._sk("binary_sensor.bep_occupancy", "on", sang.timestamp())

    # ── mẫu âm ─────────────────────────────────────────────────────────────
    def test_PHAI_SINH_MAU_AM(self) -> None:
        """Log chỉ ghi cái ĐÃ xảy ra. Không có mẫu âm thì mọi xác suất bằng 1
        — lỗi kinh điển của hệ học từ log sự kiện."""
        self._nep_toi()
        b = self.dd.hoc(so_ngay=30).get("light.bep")
        self.assertIsNotNone(b)
        self.assertGreater(b["n_khong"], 0, "phải có mẫu âm")
        self.assertGreater(b["n_bat"], 0)

    def test_KHONG_hoc_tu_viec_BOT_lam(self) -> None:
        """Cột `do_ai` sinh ra cho đúng việc này: không có nó, bot bật đèn rồi
        thấy đèn bật rồi kết luận giờ này hay bật đèn."""
        now = time.time()
        for i in range(20):
            self._sk("light.bot_lam", "on", now - i * 3600, do_ai=1)
        self.assertNotIn("light.bot_lam", self.dd.hoc(so_ngay=30))

    def test_it_mau_qua_thi_KHONG_hoc(self) -> None:
        now = time.time()
        self._sk("light.hiem", "on", now - 3600)
        self.assertNotIn("light.hiem", self.dd.hoc(so_ngay=30))

    # ── phân cấp / nội suy lùi ─────────────────────────────────────────────
    def test_MUC_HEP_khong_co_mau_thi_NHUONG_muc_rong(self) -> None:
        """Với 11 ngày dữ liệu, mức riêng nhất thường n=0 và phải nhường hẳn."""
        rong = self.dd.uoc_luong([(8, 10)])
        ca_hai = self.dd.uoc_luong([(0, 0), (8, 10)])
        self.assertAlmostEqual(rong, ca_hai, places=6)

    def test_MUC_HEP_nhieu_mau_thi_NANG_dan(self) -> None:
        """Không nhảy bậc: nhiều mẫu thì nói to dần, không phải bật/tắt."""
        it = self.dd.uoc_luong([(1, 1), (0, 100)])
        nhieu = self.dd.uoc_luong([(50, 50), (0, 100)])
        self.assertGreater(nhieu, it, "mức hẹp nhiều mẫu phải nặng hơn")
        self.assertLess(it, 0.5, "một mẫu không được lấn át 100 mẫu mức rộng")

    def test_uoc_luong_luon_trong_khoang(self) -> None:
        for muc in ([(0, 0)], [(0, 10)], [(10, 10)], []):
            p = self.dd.uoc_luong(muc)
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)

    # ── rò rỉ nhãn ─────────────────────────────────────────────────────────
    def test_KHONG_lay_CHINH_NO_lam_dieu_kien(self) -> None:
        """"Đèn bếp đang bật thì hay bật đèn bếp" — đúng 100% và vô dụng."""
        self._nep_toi()
        b = self.dd.hoc(so_ngay=30).get("light.bep") or {}
        self.assertFalse(
            any(k.startswith("bat_light.bep") for k in (b.get("dk") or {})),
            "không được dùng chính thiết bị đang đoán làm điều kiện")

    # ── thiết bị là điều kiện của nhau (mở rộng 1) ─────────────────────────
    def test_THIET_BI_KHAC_thanh_dieu_kien(self) -> None:
        """Mũi tên trong sơ đồ chủ máy vẽ HAI CHIỀU."""
        self._nep_toi()
        now = time.time()
        for i in range(14):
            self._sk("switch.binh_nong_lanh", "on", now - i * 86400 - 1800)
        b = self.dd.hoc(so_ngay=30).get("light.bep") or {}
        self.assertTrue(
            any("bat_switch.binh_nong_lanh" in k for k in (b.get("dk") or {})),
            "thiết bị khác đang bật phải trở thành một điều kiện")

    # ── cấp tự chủ ─────────────────────────────────────────────────────────
    def _cham(self, ten: str, dung: int, sai: int = 0) -> None:
        for _ in range(dung):
            self.dd.ghi_dung(self.dd.ghi_nhan(ten, "on", 0.9, {}, "goi_y"))
        for _ in range(sai):
            self.dd.ghi_sai(self.dd.ghi_nhan(ten, "on", 0.9, {}, "goi_y"))

    def test_CHUA_DU_50_LUOT_thi_chua_duoc_tu_lam(self) -> None:
        """Chủ máy chốt: ít nhất 50 lượt ĐƯỢC CHẤM."""
        self._cham("light.phong_ngu", dung=49)
        self.assertEqual(self.dd.cap("light.phong_ngu"), 1)

    def test_DU_50_LUOT_va_DUNG_95_thi_LEN_CAP(self) -> None:
        self._cham("light.phong_ngu", dung=50)
        self.assertEqual(self.dd.cap("light.phong_ngu"), 2)

    def test_DU_LUOT_nhung_KHONG_DU_TY_LE_thi_khong_len(self) -> None:
        """Đúng 45/55 = 82%, dưới ngưỡng 95% chủ máy chốt."""
        self._cham("light.phong_ngu", dung=45, sai=10)
        self.assertEqual(self.dd.cap("light.phong_ngu"), 1)

    def test_DANG_TU_LAM_ma_SAI_HAI_LAN_thi_TUT_NGAY(self) -> None:
        """Đường xuống nhạy hơn đường lên: nhà đổi nếp thì bot phải nhận ra
        trong vài ngày chứ không phải vài tuần."""
        self._cham("light.phong_ngu", dung=60)
        self.assertEqual(self.dd.cap("light.phong_ngu"), 2)
        self._cham("light.phong_ngu", dung=0, sai=2)
        self.assertEqual(self.dd.cap("light.phong_ngu"), 1)

    def test_LUOT_LO_khong_tinh_vao_50(self) -> None:
        """Người không trả lời là quyết định của người, không phải bot sai."""
        for _ in range(60):
            self.dd.ghi_lo(self.dd.ghi_nhan("light.x", "on", 0.9, {}, "goi_y"))
        self.assertEqual(self.dd.so_luot("light.x"), 0)
        self.assertEqual(self.dd.cap("light.x"), 1)

    def test_KHOA_CUA_va_BEP_KHONG_BAO_GIO_tu_lam(self) -> None:
        """Không đo được từ dữ liệu rằng "bật nhầm cái này thì cháy nhà"."""
        for ten in ("lock.cua_chinh", "switch.bep_left",
                    "switch.binh_nong_lanh"):
            self._cham(ten, dung=200)
            self.assertEqual(self.dd.cap(ten), 1, ten)

    def test_don_qua_han_thanh_LO_khong_phai_SAI(self) -> None:
        id_ = self.dd.ghi_nhan("light.y", "on", 0.9, {}, "goi_y")
        with self.dd._khoa:
            conn = self.dd._db()
            conn.execute("UPDATE du_doan SET ts=? WHERE id=?",
                         (time.time() - 7200, id_))
            conn.commit()
        self.assertEqual(self.dd.don_qua_han(), 1)
        self.assertEqual(self.dd.so_luot("light.y"), 0)

    def test_cham_HAI_LAN_khong_cong_don(self) -> None:
        id_ = self.dd.ghi_nhan("light.z", "on", 0.9, {}, "goi_y")
        self.assertTrue(self.dd.ghi_dung(id_))
        self.assertFalse(self.dd.ghi_sai(id_))
        self.assertEqual(self.dd.so_luot("light.z"), 1)

    # ── tự chấm khi người làm ngược ────────────────────────────────────────
    def test_BOT_BAT_NGUOI_TAT_NGAY_la_SAI(self) -> None:
        """Tín hiệu mạnh nhất và không tốn của chủ máy câu nào."""
        now = time.time()
        id_ = self.dd.ghi_nhan("light.tu_lam", "on", 0.95, {}, "tu_lam")
        self._sk("light.tu_lam", "off", now + 120)
        self.assertEqual(self.dd.soi_bi_huy(), 1)
        with self.dd._khoa:
            r = self.dd._db().execute(
                "SELECT ket_qua FROM du_doan WHERE id=?", (id_,)).fetchone()
        self.assertEqual(r["ket_qua"], "sai")

    def test_NGUOI_KHONG_LAM_GI_thi_chua_ket_luan(self) -> None:
        self.dd.ghi_nhan("light.yen", "on", 0.95, {}, "tu_lam")
        self.assertEqual(self.dd.soi_bi_huy(), 0)

    # ── giải thích ─────────────────────────────────────────────────────────
    def test_GIAI_THICH_duoc_thi_chu_may_sua_duoc_bot(self) -> None:
        id_ = self.dd.ghi_nhan("light.bep", "on", 0.88,
                               {"buoi": "tối", "lux_bep": "toi"}, "goi_y")
        s = self.dd.giai_thich(id_)
        self.assertIn("light.bep", s)
        self.assertIn("88", s)
        self.assertIn("tối", s)

    # ── không kéo sập ──────────────────────────────────────────────────────
    def test_KHO_HONG_thi_tra_RONG_khong_nem_loi(self) -> None:
        with mock.patch.object(self.ls, "doc_cua_so",
                               side_effect=RuntimeError("đĩa hỏng")):
            self.assertEqual(self.dd.hoc(so_ngay=7), {})

    def test_chua_du_du_lieu_thi_IM(self) -> None:
        d = self.dd.du_doan("light.la_hoac")
        self.assertEqual(d["cach"], "im")
        self.assertEqual(d["p"], 0.0)

    # ── gửi thông báo ──────────────────────────────────────────────────────
    def test_KENH_dung_chung_voi_phan_hoc_tu_loi(self) -> None:
        """Cả hai đều là "phần học hỏi" — chủ máy chọn một lần cho cả hai."""
        self.ls.config.data["mqtt"]["bai_hoc"] = {"kenh_nhan": ["zalo:b:c"]}
        self.assertEqual(self.dd._kenh_nhan(), ["zalo:b:c"])

    def test_KENH_RIENG_thi_thang(self) -> None:
        self.ls.config.data["mqtt"]["bai_hoc"] = {"kenh_nhan": ["zalo:b:c"]}
        self.ls.config.data["mqtt"]["du_doan"] = {
            "bat": True, "kenh_nhan": ["tg:x:y"]}
        self.assertEqual(self.dd._kenh_nhan(), ["tg:x:y"])

    def test_TIN_NHAN_noi_ca_VI_SAO(self) -> None:
        """Không giải thích được thì chủ máy không sửa được bot."""
        tin = self.dd.soan_tin([{
            "ten": "light.bep", "p": 0.88, "cach": "goi_y",
            "bang_chung": [{"dieu_kien": "buoi=tối"},
                           {"dieu_kien": "nguoi_bep=co"}]}])
        self.assertIn("light.bep", tin)
        self.assertIn("88%", tin)
        self.assertIn("tối", tin)

    def test_TU_LAM_thi_bao_DA_LAM_ROI(self) -> None:
        tin = self.dd.soan_tin([{"ten": "light.x", "p": 0.97,
                                 "cach": "tu_lam", "bang_chung": []}])
        self.assertIn("em bật rồi", tin)

    def test_KHONG_CO_GI_thi_KHONG_nhan_tin(self) -> None:
        """Nhắn tin rỗng là làm phiền."""
        kq = self.dd.chay_mot_lan()
        self.assertEqual(kq.get("gui"), 0)

    def test_GUI_XONG_moi_GHI_de_cham(self) -> None:
        """Gợi ý không gửi được thì đừng ghi — chấm cái chủ máy chưa thấy là
        làm hỏng thành tích."""
        self._nep_toi()
        with mock.patch.object(self.dd, "_kenh_nhan", return_value=["zalo:b:c"]), \
             mock.patch("services.digest.send_targets", return_value=0):
            self.dd.chay_mot_lan()
        with self.dd._khoa:
            n = self.dd._db().execute("SELECT COUNT(*) FROM du_doan").fetchone()[0]
        self.assertEqual(n, 0)

    def test_TAT_trong_cau_hinh_thi_khong_chay(self) -> None:
        self.ls.config.data["mqtt"]["du_doan"] = {"bat": False}
        self.assertIn("bo_qua", self.dd.chay_mot_lan())


if __name__ == "__main__":
    unittest.main()
