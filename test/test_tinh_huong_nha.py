"""Test nhận ra tình huống trong nhà."""

from __future__ import annotations

import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

TZ = timezone(timedelta(hours=7))


class TinhHuongTest(unittest.TestCase):
    def setUp(self) -> None:
        import services.tinh_huong_nha as m
        self.m = m
        self._tmp = tempfile.mkdtemp()
        m._reset_for_tests()
        m._DB_PATH = Path(self._tmp) / "th.sqlite"
        m._conn = None
        m.config.data.setdefault("mqtt", {})["tinh_huong"] = {"bat": True}

    def tearDown(self) -> None:
        self.m._reset_for_tests()

    def _sk(self, moc):
        """moc: [(ngày lùi, giờ, phút, thiết_bị)] → bản ghi kiểu lich_su_nha."""
        ra = []
        now = datetime.now(TZ)
        for lui, gio, phut, tb in moc:
            t = (now - timedelta(days=lui)).replace(hour=gio, minute=phut,
                                                    second=0, microsecond=0)
            ra.append({"ts": t.timestamp(), "thiet_bi": tb, "truong": "state",
                       "gia_tri": "on"})
        return ra

    def _voi(self, sk):
        from services import lich_su_nha
        return mock.patch.object(lich_su_nha, "doc_cua_so", return_value=sk)

    # ── phân loại nguồn ────────────────────────────────────────────────────
    def test_cam_bien_hien_dien_la_LOI(self) -> None:
        """Lõi ổn định 77%, đèn chỉ 9% — phải phân biệt đúng."""
        self.assertEqual(
            self.m._phan_loai("state", "binary_sensor.bep_person_occupancy"), "loi")
        self.assertEqual(self.m._phan_loai("presence", "cb_bep"), "loi")

    def test_den_cong_tac_la_KEM_THEO(self) -> None:
        self.assertEqual(self.m._phan_loai("state", "light.bep_left"), "kem")
        self.assertEqual(self.m._phan_loai("state", "switch.nha_tam_l1"), "kem")

    def test_cam_bien_khac_thi_BO_QUA(self) -> None:
        """Cửa mở, báo khói không nói lên nếp sinh hoạt."""
        self.assertEqual(self.m._phan_loai("state", "binary_sensor.cua_contact"), "")
        self.assertEqual(self.m._phan_loai("state", "binary_sensor.bao_khoi_smoke"), "")

    def test_chua_co_khuon_mat_va_yolo_van_nhan_ra(self) -> None:
        """Chừa chỗ sẵn: thêm khuôn mặt sau này không phải sửa gì."""
        self.assertEqual(self.m._phan_loai("khuon_mat", "cam_cua"), "loi")
        self.assertEqual(self.m._phan_loai("yolo", "frigate/bep"), "loi")

    # ── gom cửa sổ ─────────────────────────────────────────────────────────
    def _nep(self, gio, tb_list, ngay=5):
        moc = []
        for i in range(1, ngay + 1):
            for tb in tb_list:
                moc.append((i, gio, 0, tb))
        return moc

    def test_KHONG_phai_moi_o_deu_la_tinh_huong(self) -> None:
        """Lỗi thật đã gặp: cảm biến báo suốt ngày đêm nên CẢ 48 Ô đều qua
        ngưỡng, rồi bước gộp nuốt trọn 24 tiếng thành một 'tình huống'.

        Phải so với mức nền: chỉ ô nhộn nhịp hơn thường mới tính.
        """
        moc = []
        # nền: 1 cảm biến mọi giờ
        for i in range(1, 6):
            for g in range(24):
                moc.append((i, g, 0, "binary_sensor.nen_occupancy"))
        # cao điểm 19h: thêm 4 nguồn
        for i in range(1, 6):
            for tb in ("binary_sensor.bep_occupancy", "binary_sensor.pk_occupancy",
                       "light.bep", "light.pk"):
                moc.append((i, 19, 0, tb))
        with self._voi(self._sk(moc)):
            o = self.m.gom_cua_so(7)
        self.assertLess(len(o), 24, f"không được nhận cả ngày, nhận {len(o)} ô")
        self.assertTrue(any(abs(m["gio_tb"] - 19) < 1 for m in o),
                        "phải nhận ra khung 19h")

    def test_o_khong_co_nguoi_thi_khong_tinh(self) -> None:
        """Chỉ đèn bật mà không ai ở nhà → không phải tình huống sinh hoạt."""
        with self._voi(self._sk(self._nep(14, ["light.a", "light.b"]))):
            self.assertEqual(self.m.gom_cua_so(7), [])

    def test_it_ngay_thi_khong_thanh_nep(self) -> None:
        with self._voi(self._sk(self._nep(19, ["binary_sensor.a_occupancy"], ngay=2))):
            self.assertEqual(self.m.gom_cua_so(7), [])

    # ── MẤU CHỐT: đổi phòng vẫn là một tình huống ──────────────────────────
    def test_DOI_PHONG_VAN_LA_MOT_TINH_HUONG(self) -> None:
        """Chủ máy hỏi: "nếu ngồi ăn ở phòng khách thì sao".

        Ăn ở bếp 5 ngày rồi ăn phòng khách 2 ngày. Nếu định nghĩa bằng đèn thì
        thành hai tình huống khác nhau; định nghĩa bằng hiện diện thì vẫn một.
        """
        moc = []
        for i in range(1, 6):        # 5 ngày ăn ở bếp
            moc += [(i, 19, 0, "binary_sensor.nguoi_bep_occupancy"),
                    (i, 19, 0, "binary_sensor.chung_occupancy"),
                    (i, 19, 0, "light.den_bep")]
        for i in range(6, 8):        # 2 ngày ăn ở phòng khách
            moc += [(i, 19, 0, "binary_sensor.nguoi_pk_occupancy"),
                    (i, 19, 0, "binary_sensor.chung_occupancy"),
                    (i, 19, 0, "light.den_phong_khach")]
        # nền thấp để khung 19h vượt ngưỡng
        for i in range(1, 8):
            for g in (3, 4):
                moc.append((i, g, 0, "binary_sensor.nen_occupancy"))
        with self._voi(self._sk(moc)):
            uv = self.m.hoc(10)
        khung19 = [m for m in uv if abs(m["gio_tb"] - 19) < 1]
        self.assertEqual(len(khung19), 1,
                         f"đổi phòng vẫn phải là MỘT tình huống, nhận {len(khung19)}")

    def test_o_ke_nhau_gop_lam_mot(self) -> None:
        """19h00, 19h30, 20h00 là MỘT bữa tối, không phải ba tình huống."""
        moc = []
        for i in range(1, 6):
            for g, p in ((19, 0), (19, 30), (20, 0)):
                moc += [(i, g, p, "binary_sensor.bep_occupancy"),
                        (i, g, p, "binary_sensor.pk_occupancy"),
                        (i, g, p, "light.a")]
            moc.append((i, 3, 0, "binary_sensor.nen_occupancy"))
        with self._voi(self._sk(moc)):
            uv = self.m.hoc(7)
        toi = [m for m in uv if 18.5 <= m["gio_tb"] <= 20.5]
        self.assertEqual(len(toi), 1, f"phải gộp thành 1, nhận {len(toi)}")

    # ── đặt tên ────────────────────────────────────────────────────────────
    def _uv(self):
        return {"gio_tb": 19.5, "do_lech": 0.3, "so_ngay": 6,
                "loi_cot": ["binary_sensor.bep_occupancy"], "kem_theo": ["light.bep"]}

    def test_dat_ten_model_hong_thi_tra_rong(self) -> None:
        from services.agent import runtime
        with mock.patch.object(runtime, "call_model", return_value={"error": "sập"}):
            self.assertEqual(self.m.de_xuat_ten(self._uv()), "")

    def test_dat_ten_model_ném_loi_cung_khong_raise(self) -> None:
        from services.agent import runtime
        with mock.patch.object(runtime, "call_model", side_effect=RuntimeError("x")):
            self.assertEqual(self.m.de_xuat_ten(self._uv()), "")

    def test_dat_ten_doc_dung_khuon(self) -> None:
        from services.agent import runtime
        with mock.patch.object(runtime, "call_model",
                               return_value={"choices": [{"message": {
                                   "content": "## TÊN\n- giờ ăn tối"}}]}):
            self.assertEqual(self.m.de_xuat_ten(self._uv()), "giờ ăn tối")

    def test_KHONG_RO_thi_tra_rong(self) -> None:
        from services.agent import runtime
        with mock.patch.object(runtime, "call_model",
                               return_value={"choices": [{"message": {
                                   "content": "## TÊN\n- KHÔNG RÕ"}}]}):
            self.assertEqual(self.m.de_xuat_ten(self._uv()), "")

    def test_ten_chua_chu_khong_ro_van_hop_le(self) -> None:
        """So NGUYÊN DÒNG: "lúc không rõ ai về" là tên hợp lệ."""
        from services.agent import runtime
        with mock.patch.object(runtime, "call_model",
                               return_value={"choices": [{"message": {
                                   "content": "## TÊN\n- lúc không rõ ai về"}}]}):
            self.assertEqual(self.m.de_xuat_ten(self._uv()), "lúc không rõ ai về")

    def test_bo_den_bep_khoi_phan_dat_ten(self) -> None:
        """Đèn bếp nhấp nháy 905 lần/7 ngày — để nguyên thì mọi tên đều là 'bếp'."""
        uv = {**self._uv(), "kem_theo": ["light.bep_left", "light.phong_khach"]}
        mo_ta = self.m._mo_ta_ung_vien(uv)
        self.assertNotIn("bep_left", mo_ta)
        self.assertIn("phong_khach", mo_ta)

    # ── duyệt ──────────────────────────────────────────────────────────────
    def test_chua_duyet_thi_KHONG_nhan_ra(self) -> None:
        """Model đặt tên sai là chuyện thường — chưa người duyệt thì chưa dùng."""
        self.m.luu_cho_duyet(self._uv(), "giờ ăn tối")
        t = datetime.now(TZ).replace(hour=19, minute=30).timestamp()
        self.assertIsNone(self.m.nhan_ra(t))

    def test_duyet_roi_thi_nhan_ra(self) -> None:
        """Đặt nếp ở ĐÚNG giờ-phút hiện tại, không phải đầu giờ.

        Dùng `.hour` trơn thì nếp rơi vào 7h00 trong khi chạy lúc 7h50 — lệch
        50 phút, quá cửa sổ 45 phút của nhan_ra() nên test hỏng theo giờ chạy.
        """
        now = datetime.now(TZ)
        uv = {**self._uv(), "gio_tb": now.hour + now.minute / 60}
        i = self.m.luu_cho_duyet(uv, "thử nghiệm")
        self.m.duyet(i)
        self.assertIsNotNone(self.m.nhan_ra())

    def test_duyet_doi_ten_duoc(self) -> None:
        i = self.m.luu_cho_duyet(self._uv(), "model đặt")
        self.m.duyet(i, "tên chủ nhà đặt")
        ds = self.m.danh_sach("da_duyet")
        self.assertEqual(ds[0]["ten"], "tên chủ nhà đặt")

    def test_luu_trung_ten_thi_bo_qua(self) -> None:
        self.assertTrue(self.m.luu_cho_duyet(self._uv(), "giờ ăn"))
        self.assertEqual(self.m.luu_cho_duyet(self._uv(), "giờ ăn"), 0)

    def test_hai_tinh_huong_sat_nhau_thi_KHONG_doan(self) -> None:
        """Khuôn ha_intent_rank: không có biên cách biệt thì trả None."""
        g = datetime.now(TZ).hour + 0.0
        for ten in ("A", "B"):
            i = self.m.luu_cho_duyet({**self._uv(), "gio_tb": g}, ten)
            self.m.duyet(i)
        self.assertIsNone(self.m.nhan_ra())

    # ── chấm điểm ──────────────────────────────────────────────────────────
    def test_chua_co_du_lieu_thi_diem_la_0_5(self) -> None:
        i = self.m.luu_cho_duyet(self._uv(), "x")
        self.assertAlmostEqual(self.m.diem(i), 0.5)

    def test_diem_len_khi_dung(self) -> None:
        i = self.m.luu_cho_duyet(self._uv(), "x")
        for _ in range(5):
            self.m.ghi_dung(i)
        self.assertGreater(self.m.diem(i), 0.7)

    def test_NGUOI_BO_QUA_khong_tinh_la_sai(self) -> None:
        """skill_quality._KHONG_TINH: người từ chối là quyết định của người."""
        i = self.m.luu_cho_duyet(self._uv(), "x")
        self.m.bo(i)
        self.assertAlmostEqual(self.m.diem(i), 0.5, msg="bỏ qua KHÔNG được tính là sai")

    def test_tat_thi_khong_lam_gi(self) -> None:
        self.m.config.data["mqtt"]["tinh_huong"] = {"bat": False}
        self.assertEqual(self.m.chay_mot_lan()["moi"], 0)

    def test_doc_lich_su_loi_thi_khong_raise(self) -> None:
        from services import lich_su_nha
        with mock.patch.object(lich_su_nha, "doc_cua_so",
                               side_effect=RuntimeError("DB hỏng")):
            self.assertEqual(self.m.gom_cua_so(), [])


if __name__ == "__main__":
    unittest.main()
