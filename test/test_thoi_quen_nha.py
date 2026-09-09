"""Test học nếp sinh hoạt — cảnh báo lệch giờ và đón đầu việc quen làm."""

from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

TZ = timezone(timedelta(hours=7))


class ThoiQuenTest(unittest.TestCase):
    def setUp(self) -> None:
        import services.thoi_quen_nha as m
        self.m = m
        m.config.data.setdefault("mqtt", {})["thoi_quen"] = {"bat": True}

    def _sk(self, moc):
        """moc: [(ngày lùi, giờ, phút, giá trị)] → bản ghi kiểu lich_su_nha."""
        ra = []
        now = datetime.now(TZ)
        for lui, gio, phut, gt in moc:
            t = (now - timedelta(days=lui)).replace(hour=gio, minute=phut,
                                                    second=0, microsecond=0)
            ra.append({"ts": t.timestamp(), "gia_tri": gt, "thiet_bi": "khoa",
                       "truong": "unlock"})
        return ra

    def _voi(self, sk, hom_nay=None):
        from services import lich_su_nha

        def _doc(tb, tu, den, truong=None):
            # Gọi lần đầu là học (60 ngày), lần sau là hôm nay.
            if den - tu > 2 * 86400:
                return sk
            return hom_nay if hom_nay is not None else []

        return mock.patch.object(lich_su_nha, "doc_su_kien", side_effect=_doc)

    # ── học nếp ────────────────────────────────────────────────────────────
    def test_hoc_duoc_nep_khi_du_mau(self) -> None:
        """4 lần cùng thứ, cùng buổi → thành nếp."""
        moc = [(7 * i, 17, 0, "11") for i in range(1, 5)]   # 4 tuần, cùng thứ
        with self._voi(self._sk(moc)):
            nep = self.m.hoc("khoa")
        self.assertEqual(len(nep), 1)
        v = next(iter(nep.values()))
        self.assertEqual(v["n"], 4)
        self.assertAlmostEqual(v["trung_binh"], 17.0, places=1)

    def test_it_mau_thi_KHONG_coi_la_nep(self) -> None:
        """2 lần chưa đủ nói là thói quen — đoán bừa từ 2 điểm là báo động giả."""
        with self._voi(self._sk([(7, 17, 0, "11"), (14, 17, 0, "11")])):
            self.assertEqual(self.m.hoc("khoa"), {})

    def test_co_SAN_do_lech_khi_nep_qua_deu(self) -> None:
        """σ=0 thì lệch 1 phút cũng thành bất thường — phải có sàn."""
        moc = [(7 * i, 17, 0, "11") for i in range(1, 6)]   # y hệt nhau
        with self._voi(self._sk(moc)):
            v = next(iter(self.m.hoc("khoa").values()))
        self.assertGreaterEqual(v["do_lech"] * 60, self.m._SAN_LECH_PHUT - 0.1)

    def test_tach_theo_BUOI_khong_gop_ca_ngay(self) -> None:
        """Gộp sáng với chiều thì trung bình rơi vào giữa trưa, vô nghĩa.

        Đo thật trên nhật ký nhà: gộp cho ±297 phút, tách buổi còn ±35-60.
        """
        moc = ([(7 * i, 8, 0, "11") for i in range(1, 5)]
               + [(7 * i, 17, 0, "11") for i in range(1, 5)])
        with self._voi(self._sk(moc)):
            nep = self.m.hoc("khoa")
        self.assertEqual(len(nep), 2, "sáng và chiều phải là hai ô riêng")
        tb = sorted(round(v["trung_binh"]) for v in nep.values())
        self.assertEqual(tb, [8, 17])

    def test_gio_dem_khong_bi_tinh_nguoc(self) -> None:
        """23h50 và 0h10 cách nhau 20 phút, KHÔNG phải 23 tiếng rưỡi."""
        t23 = datetime(2026, 9, 9, 23, 50, tzinfo=TZ)
        t00 = datetime(2026, 9, 10, 0, 10, tzinfo=TZ)
        self.assertAlmostEqual(
            self.m._gio_thap_phan(t00) - self.m._gio_thap_phan(t23), 0.333, places=2)

    # ── soi lệch ───────────────────────────────────────────────────────────
    def _nep_chieu(self, gio=17, phut=0, gt="11"):
        """Nếp: cùng thứ với HÔM NAY, buổi chiều."""
        return [(7 * i, gio, phut, gt) for i in range(1, 6)]

    def test_ve_dung_gio_thi_KHONG_bao(self) -> None:
        sk = self._sk(self._nep_chieu())
        hn = self._sk([(0, 17, 5, "11")])
        with self._voi(sk, hn):
            self.assertEqual(self.m.soi_lech("khoa"), [])

    def test_ve_muon_han_thi_bao(self) -> None:
        sk = self._sk(self._nep_chieu())
        hn = self._sk([(0, 18, 30, "11")])       # muộn 90 phút
        with self._voi(sk, hn):
            ds = self.m.soi_lech("khoa")
        self.assertEqual(len(ds), 1)
        self.assertEqual(ds[0]["loai"], "muon")
        self.assertGreater(ds[0]["muon_phut"], 60)

    def test_ve_SOM_thi_khong_bao(self) -> None:
        """Về sớm không phải chuyện đáng lo."""
        sk = self._sk(self._nep_chieu())
        hn = self._sk([(0, 15, 0, "11")])
        with self._voi(sk, hn):
            self.assertEqual(self.m.soi_lech("khoa"), [])

    def test_CHUA_VE_bao_duoc_ma_khong_cho_ve_moi_bao(self) -> None:
        """Thứ chủ máy cần: biết con CHƯA về, không phải đợi về rồi mới báo."""
        now = datetime.now(TZ)
        # nếp là 3 tiếng TRƯỚC bây giờ, hôm nay chưa có gì
        gio_nep = (now - timedelta(hours=3)).hour
        if not (5 <= gio_nep < 29):
            self.skipTest("giờ chạy test rơi vào đêm")
        sk = self._sk([(7 * i, gio_nep, 0, "11") for i in range(1, 6)])
        with self._voi(sk, []):
            ds = self.m.soi_lech("khoa")
        self.assertTrue(any(d["loai"] == "chua_ve" for d in ds),
                        f"phải báo chưa về, nhận được {ds}")

    def test_khong_bao_khi_qua_lau_roi(self) -> None:
        """Quá 6 tiếng thì thôi, không nhắc mãi chuyện sáng nay."""
        now = datetime.now(TZ)
        gio_nep = (now - timedelta(hours=9)).hour
        if not (5 <= gio_nep < 24):
            self.skipTest("giờ chạy test không hợp")
        sk = self._sk([(7 * i, gio_nep, 0, "11") for i in range(1, 6)])
        with self._voi(sk, []):
            ds = [d for d in self.m.soi_lech("khoa") if d["loai"] == "chua_ve"]
        self.assertEqual(ds, [], "quá 6 tiếng thì không nhắc nữa")

    def test_nep_cua_THU_KHAC_khong_bi_xet(self) -> None:
        """Nếp thứ Ba không dùng để phán xét thứ Năm."""
        now = datetime.now(TZ)
        khac = 3 if now.weekday() != 3 else 5
        lui = (now.weekday() - khac) % 7 or 7
        sk = self._sk([(lui + 7 * i, 17, 0, "11") for i in range(5)])
        with self._voi(sk, []):
            self.assertEqual(self.m.soi_lech("khoa"), [])

    # ── đón đầu ────────────────────────────────────────────────────────────
    def test_sap_den_gio_bao_truoc_dung_khoang(self) -> None:
        """Áp cho MỌI việc lặp, không riêng "về nhà" — quản gia không bó hẹp."""
        now = datetime.now(TZ)
        sau = now + timedelta(minutes=20)
        if sau.hour < 5:
            self.skipTest("giờ chạy test rơi vào đêm")
        sk = self._sk([(7 * i, sau.hour, sau.minute, "11") for i in range(1, 6)])
        with self._voi(sk):
            ds = self.m.sap_den_gio("khoa", truoc_phut=30)
        self.assertTrue(ds, "phải báo sắp về")
        self.assertLessEqual(ds[0]["con_phut"], 30)

    def test_sap_den_gio_khong_bao_khi_con_xa(self) -> None:
        now = datetime.now(TZ)
        sau = now + timedelta(hours=3)
        if sau.hour < 5 or sau.day != now.day:
            self.skipTest("giờ chạy test không hợp")
        sk = self._sk([(7 * i, sau.hour, sau.minute, "11") for i in range(1, 6)])
        with self._voi(sk):
            self.assertEqual(self.m.sap_den_gio("khoa", truoc_phut=30), [])

    # ── chống nhiễu do đi chơi ─────────────────────────────────────────────
    def test_MAY_NGAY_DI_CHOI_KHONG_KEO_LECH_NEP(self) -> None:
        """Mấu chốt chủ máy chỉ ra: "đi chơi rất dễ nhiễu".

        15 ngày về đúng 16h30 + 4 ngày đi chơi về 19h. Trung bình bị kéo lên
        gần 17h và độ lệch phình tới ±60 phút — từ đó không báo được ca muộn
        thật. Trung vị giữ đúng 16h30.
        """
        moc = [(7 * i, 16, 30, "11") for i in range(1, 16)]
        moc += [(7 * i, 19, 0, "11") for i in range(16, 20)]
        with self._voi(self._sk(moc)):
            nep = self.m.hoc("khoa")
        v = max(nep.values(), key=lambda x: x["n"])
        self.assertLess(abs(v["trung_binh"] - 16.5), 0.35,
                        "nếp phải bám 16h30, không bị 4 ngày đi chơi kéo lên")

    def test_do_lech_khong_phinh_vi_vai_lan_lac(self) -> None:
        moc = [(7 * i, 16, 30, "11") for i in range(1, 16)]
        moc += [(7 * i, 20, 0, "11") for i in range(16, 19)]
        with self._voi(self._sk(moc)):
            v = max(self.m.hoc("khoa").values(), key=lambda x: x["n"])
        self.assertLess(v["do_lech"] * 60, 45,
                        "MAD phải giữ độ lệch nhỏ dù có giá trị lạc")

    def test_san_lech_dung_10_phut(self) -> None:
        """Chủ máy nêu rõ: con đi học thì 10 phút, không phải 55."""
        self.assertEqual(self.m._SAN_LECH_PHUT, 10.0)

    def test_doi_chung_qua_camera(self) -> None:
        """Camera thấy người thì đừng khẳng định "chưa về"."""
        from services import lich_su_nha
        now = time.time()
        tuoi = [{"thiet_bi": "frigate/phong-khach", "truong": "person",
                 "gia_tri": "1", "ts": now}]
        with mock.patch.object(lich_su_nha, "doc_tuoi", return_value=tuoi):
            bc = self.m.doi_chung(now)
        self.assertTrue(bc, "camera thấy người phải thành bằng chứng")

    def test_doi_chung_bo_qua_moc_qua_xa(self) -> None:
        from services import lich_su_nha
        now = time.time()
        tuoi = [{"thiet_bi": "cb", "truong": "presence", "gia_tri": "on",
                 "ts": now - 7200}]
        with mock.patch.object(lich_su_nha, "doc_tuoi", return_value=tuoi):
            self.assertEqual(self.m.doi_chung(now), [])

    def test_dang_tin_gan_co_bang_chung(self) -> None:
        from services import lich_su_nha
        ds = [{"loai": "chua_ve", "ai": "11", "buoi": "chiều",
               "gio_quen": 17.0, "gio_thuc": None, "muon_phut": 40, "so_lan_hoc": 5}]
        tuoi = [{"thiet_bi": "frigate/phong-khach", "truong": "person",
                 "gia_tri": "2", "ts": time.time()}]
        with mock.patch.object(lich_su_nha, "doc_tuoi", return_value=tuoi):
            ra = self.m.dang_tin(ds)
        self.assertTrue(ra[0].get("nghi_ngo"))
        self.assertIn("có thể đã về", self.m.mo_ta_lech(ra))

    # ── lời văn ────────────────────────────────────────────────────────────
    def test_mo_ta_co_du_thong_tin_can_thiet(self) -> None:
        ds = [{"loai": "chua_ve", "ai": "11", "buoi": "chiều",
               "gio_quen": 17.0, "gio_thuc": None, "muon_phut": 75,
               "so_lan_hoc": 6}]
        t = self.m.mo_ta_lech(ds)
        for phai_co in ("17h00", "75", "6"):
            self.assertIn(phai_co, t)

    def test_doc_loi_thi_khong_raise(self) -> None:
        from services import lich_su_nha
        with mock.patch.object(lich_su_nha, "doc_su_kien",
                               side_effect=RuntimeError("DB hỏng")):
            self.assertEqual(self.m.hoc("khoa"), {})
            self.assertEqual(self.m.soi_lech("khoa"), [])


if __name__ == "__main__":
    unittest.main()
