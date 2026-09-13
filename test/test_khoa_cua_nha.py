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
        import services.so_ten_nha as sn
        self.m = m
        self.sn = sn
        self._tmp = tempfile.mkdtemp()
        m._FILE = Path(self._tmp) / "kc.json"
        # Tên người giờ nằm ở SỔ DÙNG CHUNG, không phải sổ riêng của khoá cửa
        # — đó là điều kiện để thoi_quen_nha đọc được tên chủ máy đã dạy.
        sn._FILE = Path(self._tmp) / "so_ten.json"
        sn.config.data.setdefault("mqtt", {})["so_ten"] = {}
        m.config.data.setdefault("mqtt", {})["khoa_cua"] = {"bat": True}

    def tearDown(self) -> None:
        self.m._reset_for_tests()
        self.sn._reset_for_tests()

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
        with mock.patch.object(
                state, "search_memory",
                return_value=["- [2026-09-09 22:52] (x) fingerprint 11 là bố"]):
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
        """Biết tên rồi thì KHÔNG hỏi nữa — dù trước đó đã hỏi hay chưa."""
        self.m._danh_dau_da_hoi("face#9")
        from services.agent import state
        with mock.patch.object(state, "nho_hoac_cap_nhat"):
            self.m.dat_ten("face#9", "khách")
        self.assertFalse(self.m._nen_hoi("face#9"),
                         "đã biết tên thì thôi hỏi")
        self.assertTrue(self.sn.da_biet(self.m._khoa_so("face#9")))

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

    def test_NEP_NGU_chi_tinh_MOT_LAN_moi_luot(self) -> None:
        """Nếp ngủ là TRUNG VỊ 14 NGÀY — không thể đổi trong vài phút, nên
        đừng đọc lại 14 ngày lịch sử mỗi lần hỏi.

        Đo trên máy chủ 11/09/2026: mỗi lượt đọc 7.498 dòng mất 0,63 giây, mà
        một lượt `chay_mot_lan()` hỏi BA lần (hai qua `soi_bat_thuong`, một
        qua `gio_tom_tat`), lặp mỗi 15 giây. Claude trên máy chủ đo bằng
        py-spy: luồng `khoa-cua-nhip` chiếm 11,9% một lõi liên tục.
        """
        from services import lich_su_nha

        self.m._reset_for_tests()
        dem = {"n": 0}
        that = lich_su_nha.doc_cua_so

        def _dem(*a, **k):
            dem["n"] += 1
            return that(*a, **k)

        with mock.patch.object(lich_su_nha, "doc_cua_so", side_effect=_dem):
            self.m.gio_di_ngu()
            self.m.gio_di_ngu()
            self.m.gio_di_ngu()
        self.assertEqual(dem["n"], 1,
                         "ba lần hỏi trong một lượt chỉ được đọc lịch sử MỘT lần")

    def test_NEP_NGU_reset_thi_tinh_lai(self) -> None:
        """Cache là biến toàn cục — không xoá khi reset là rò sang test khác."""
        from services import lich_su_nha

        self.m._reset_for_tests()
        with mock.patch.object(lich_su_nha, "doc_cua_so", return_value=[]):
            self.m.gio_di_ngu()
        self.assertIsNotNone(self.m._ngu_nho, "phải nhớ lại sau khi tính")
        self.m._reset_for_tests()
        self.assertIsNone(self.m._ngu_nho, "reset phải xoá cache")

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

    def test_chua_chon_kenh_thi_khong_gui(self) -> None:
        """Từ 13/09/2026 ba tin của khoá cửa đi theo sổ đăng ký `thong_bao`.

        Chưa chọn kênh trong Cài đặt → Thông báo thì IM, không rơi về admin —
        chủ máy nêu đích danh "kể cả thông báo khoá cửa hay tương tự"."""
        from services import digest
        with mock.patch.object(digest, "send_targets", return_value=1) as g:
            self.assertEqual(self.m.chay_mot_lan()["gui"], 0)
        g.assert_not_called()

    def test_tat_thi_khong_lam_gi(self) -> None:
        self.m.config.data["mqtt"]["khoa_cua"] = {"bat": False}
        self.assertEqual(self.m.chay_mot_lan()["gui"], 0)


class DocTuHomeAssistantTest(unittest.TestCase):
    """Biết NGAY khi cửa mở, không đợi vòng hỏi Tuya 5 phút một lần."""

    def setUp(self) -> None:
        import services.khoa_cua_nha as m
        import services.so_ten_nha as sn
        self.m, self.sn = m, sn
        self._tmp = tempfile.mkdtemp()
        m._FILE = Path(self._tmp) / "kc.json"
        sn._FILE = Path(self._tmp) / "so_ten.json"
        sn.config.data.setdefault("mqtt", {})["so_ten"] = {}

    def tearDown(self) -> None:
        self.m._reset_for_tests()
        self.sn._reset_for_tests()

    def _su_kien_ha(self, ts: float, cach: str, so: str):
        """Hai bản ghi ha_live sinh ra cho MỘT lần mở cửa."""
        e = f"event.smart_lock_unlock_user_{cach}"
        return [
            {"ts": ts, "thiet_bi": e, "truong": "event_type",
             "gia_tri": f"unlock_{cach}"},
            {"ts": ts, "thiet_bi": e, "truong": "value", "gia_tri": so},
        ]

    def test_DOC_DUOC_tu_su_kien_HA(self) -> None:
        """Ca thật 10/09 08:29: event.smart_lock_unlock_user_face, value 17."""
        from services import lich_su_nha
        now = time.time() - 300
        with mock.patch.object(lich_su_nha, "doc_cua_so",
                               return_value=self._su_kien_ha(now, "face", "17.0")):
            ra = self.m._tu_ha(2)
        self.assertEqual(len(ra), 1)
        self.assertEqual(ra[0]["ma"], "face#17")

    def test_bo_su_kien_thieu_thong_tin(self) -> None:
        """Chỉ có mốc giờ mà không biết ai thì không dựng bản ghi."""
        from services import lich_su_nha
        ds = [{"ts": time.time(), "thiet_bi": "event.smart_lock_unlock_user_face",
               "truong": "state", "gia_tri": "2026-09-10T01:29:26"}]
        with mock.patch.object(lich_su_nha, "doc_cua_so", return_value=ds):
            self.assertEqual(self.m._tu_ha(2), [])

    def test_bo_qua_thuc_the_khong_lien_quan(self) -> None:
        from services import lich_su_nha
        ds = [{"ts": time.time(), "thiet_bi": "light.bep",
               "truong": "state", "gia_tri": "on"}]
        with mock.patch.object(lich_su_nha, "doc_cua_so", return_value=ds):
            self.assertEqual(self.m._tu_ha(2), [])

    def test_HAI_NGUON_TRUNG_thi_giu_MOT(self) -> None:
        """HA và Tuya cùng báo một lần mở cửa, lệch nhau vài giây."""
        from services import lich_su_nha, tuya_nha
        now = time.time() - 300
        with mock.patch.object(lich_su_nha, "doc_cua_so",
                               return_value=self._su_kien_ha(now, "face", "17.0")), \
             mock.patch.object(tuya_nha, "danh_sach_thiet_bi",
                               side_effect=RuntimeError("bỏ qua Tuya")):
            ra = self.m.doc_nhat_ky(2)
        self.assertEqual(len(ra), 1, "một lần mở cửa chỉ được một bản ghi")

    def test_HA_HONG_van_chay(self) -> None:
        """Mất HA thì rơi về Tuya, không được chết cả luồng."""
        from services import lich_su_nha, tuya_nha
        with mock.patch.object(lich_su_nha, "doc_cua_so",
                               side_effect=RuntimeError("mất HA")), \
             mock.patch.object(tuya_nha, "danh_sach_thiet_bi", return_value=[]):
            self.assertEqual(self.m.doc_nhat_ky(2), [])


class NhipNhanhTest(unittest.TestCase):
    """Vòng hỏi riêng 15 giây — heartbeat chung 5 phút là quá chậm."""

    def setUp(self) -> None:
        import services.khoa_cua_nha as m
        self.m = m
        self._tmp = tempfile.mkdtemp()
        m._FILE = Path(self._tmp) / "kc.json"
        m.config.data.setdefault("mqtt", {})["khoa_cua"] = {"bat": True}

    def tearDown(self) -> None:
        self.m.stop()
        self.m._reset_for_tests()

    def test_NHIP_MAC_DINH_15_GIAY(self) -> None:
        """Chủ máy chốt 15 giây: nhanh gấp 20 lần nhịp heartbeat 300 giây, mà
        mỗi ngày chỉ thêm ~5.700 lượt gọi API Tuya."""
        self.assertEqual(self.m._nhip(), 15.0)

    def test_chinh_duoc_nhip(self) -> None:
        self.m.config.data["mqtt"]["khoa_cua"] = {"bat": True, "nhip_giay": 30}
        self.assertEqual(self.m._nhip(), 30.0)

    def test_SAN_5_GIAY_khong_cho_thap_hon(self) -> None:
        """Hỏi dày quá là đốt hạn mức API Tuya mà chẳng nhanh thêm — một lượt
        gọi đã mất 1,2 giây."""
        self.m.config.data["mqtt"]["khoa_cua"] = {"bat": True, "nhip_giay": 1}
        self.assertEqual(self.m._nhip(), 5.0)

    def test_nhip_la_thi_ve_mac_dinh(self) -> None:
        self.m.config.data["mqtt"]["khoa_cua"] = {"bat": True,
                                                  "nhip_giay": "không phải số"}
        self.assertEqual(self.m._nhip(), 15.0)

    def test_TAT_thi_khong_chay_vong(self) -> None:
        self.m.config.data["mqtt"]["khoa_cua"] = {"bat": False}
        self.assertFalse(self.m.start())

    def test_start_idempotent(self) -> None:
        with mock.patch.object(self.m, "chay_mot_lan", return_value={"gui": 0}):
            self.assertTrue(self.m.start())
            self.assertTrue(self.m.start(), "gọi lần hai không được dựng luồng mới")
        self.m.stop()

    def test_KHONG_CON_TRONG_HEARTBEAT(self) -> None:
        """Để cả hai là gọi API Tuya đôi mà chẳng nhanh thêm — nhịp chung tối
        thiểu 60 giây vẫn chậm hơn bốn lần."""
        from services.agent.heartbeat import _parse_tasks
        self.assertNotIn("khoa_cua_nha", [t["id"] for t in _parse_tasks()])

    def test_NHIP_TRU_THOI_GIAN_GOI_API(self) -> None:
        """Một lượt gọi Tuya mất ~4 giây. Cộng thẳng 15 giây nữa thì nhịp THẬT
        thành 19 giây chứ không phải 15 như đã hứa với chủ máy."""
        moc = []

        def cham():
            time.sleep(0.6)
            return {"gui": 0}

        def ghi_roi_dung(t):
            moc.append(t)
            self.m._nhip_dung.set()      # dừng vòng ngay sau lượt đầu
            return True

        with mock.patch.object(self.m, "chay_mot_lan", side_effect=cham), \
             mock.patch.object(self.m, "_nhip", return_value=3.0), \
             mock.patch.object(self.m._nhip_dung, "wait",
                               side_effect=ghi_roi_dung):
            self.m._nhip_dung.clear()
            self.m._chay_mai()
        self.m._nhip_dung.clear()
        self.assertTrue(moc)
        # Nhịp 3 giây, lượt tốn 0,6 giây → phải chờ ~2,4 chứ không phải trọn 3.
        # (Sàn 1 giây trong `max()` chỉ chặn khi nhịp quá nhỏ, không ảnh hưởng
        # con số thật 15 giây.)
        self.assertLess(moc[0], 2.8,
                        "phải trừ thời gian vừa tốn, không chờ trọn nhịp")
        self.assertGreater(moc[0], 2.0)

    def test_MOT_LUOT_HONG_khong_lam_chet_vong(self) -> None:
        goi = []

        def hong():
            goi.append(1)
            raise RuntimeError("Tuya mất mạng")

        # Sàn chờ là 1 giây, nên phải cho vòng đủ thời gian chạy hai lượt.
        with mock.patch.object(self.m, "chay_mot_lan", side_effect=hong), \
             mock.patch.object(self.m, "_nhip", return_value=0.05):
            self.m.start()
            time.sleep(2.2)
            self.m.stop()
        self.assertGreater(len(goi), 1, "hỏng một lượt thì lượt sau vẫn phải chạy")


if __name__ == "__main__":
    unittest.main()
