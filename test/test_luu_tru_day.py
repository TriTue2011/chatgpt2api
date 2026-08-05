"""Luồng hỏi admin trước khi đẩy tệp lên kho đám mây.

Chủ máy chốt 05/08: "xoá là không đẩy lên online vì không muốn lưu file cục bộ".
Nên thứ tự bắt buộc là HỎI TRƯỚC ĐẨY SAU — chọn "Xoá" thì tệp không được có mặt
ở bất kỳ đâu, kể cả trên mây.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import luu_tru_day as ld  # noqa: E402
from services.agent import luu_tru_online as lt  # noqa: E402


class _CauHinhGia:
    def __init__(self, data):
        self.data = data

    def get(self):
        return self.data

    def update(self, moi):
        self.data.update(moi)


class _Nen:
    """Bắt lời gọi đẩy nền, chạy thẳng thay vì mở luồng — test khỏi phải chờ."""

    def __init__(self):
        self.da_day = []

    def __call__(self, tep, cd, nhat_ky=False):
        if not (cd or {}).get("enabled"):
            return False
        self.da_day.append((tep, lt.duong_dan_dich(cd, Path(tep).name, nhat_ky=nhat_ky)))
        return True


class _Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tep = Path(self.tmp.name) / "bao-cao.pdf"
        self.tep.write_bytes(b"noi dung")

        self._cfg_goc = lt.config
        lt.config = _CauHinhGia({"luu_tru_online": {
            "zalop:nhom1": {"enabled": True, "kho": "drive",
                            "thu_muc": "Gia đình", "hoi_truoc": True}}})
        self.addCleanup(setattr, lt, "config", self._cfg_goc)

        self.nen = _Nen()
        self._day_goc = ld.day_nen
        ld.day_nen = self.nen
        self.addCleanup(setattr, ld, "day_nen", self._day_goc)

        ld._cho.clear()
        ld.dat_cho("admin1", tep=str(self.tep), kenh="zalop", chat="nhom1")


class ChonXoaTests(_Base):

    def test_xoa_thi_khong_day_len_dau_ca(self):
        kq = ld.tra_loi("admin1", 3)
        self.assertTrue(kq["ok"])
        self.assertEqual(self.nen.da_day, [], "chọn Xoá mà vẫn đẩy lên mây")

    def test_xoa_thi_bo_luon_ban_cuc_bo(self):
        ld.tra_loi("admin1", 3)
        self.assertFalse(self.tep.exists(), "chọn Xoá mà tệp cục bộ vẫn còn")


class ChonLuuTests(_Base):

    def test_luu_thi_day_dung_thu_muc_theo_loai(self):
        ld.tra_loi("admin1", 1)
        self.assertEqual(len(self.nen.da_day), 1)
        self.assertEqual(self.nen.da_day[0][1], "drive:Gia đình/PDF")

    def test_luu_thi_khong_xoa_ban_cuc_bo(self):
        ld.tra_loi("admin1", 1)
        self.assertTrue(self.tep.exists())

    def test_luu_mot_lan_khong_tat_hoi_lai(self):
        ld.tra_loi("admin1", 1)
        self.assertTrue(lt.cai_dat("zalop", "nhom1")["hoi_truoc"])


class ChonLuonLuonLuuTests(_Base):

    def test_tat_hoi_lai_cho_pham_vi_do(self):
        ld.tra_loi("admin1", 2)
        self.assertFalse(lt.cai_dat("zalop", "nhom1")["hoi_truoc"])

    def test_van_day_tep_dang_cho(self):
        ld.tra_loi("admin1", 2)
        self.assertEqual(len(self.nen.da_day), 1)


class BanChoTests(_Base):

    def test_tra_loi_hai_lan_thi_lan_sau_bao_khong_con(self):
        ld.tra_loi("admin1", 1)
        kq = ld.tra_loi("admin1", 1)
        self.assertFalse(kq["ok"])

    def test_ban_cho_het_han_thi_bi_don(self):
        ld._cho["admin1"]["luc"] -= ld._HAN_CHO_S + 10
        self.assertEqual(ld.lay_cho("admin1"), {})

    def test_moi_admin_mot_ban_cho_rieng(self):
        tep2 = Path(self.tmp.name) / "khac.docx"
        tep2.write_bytes(b"x")
        ld.dat_cho("admin2", tep=str(tep2), kenh="zalop", chat="nhom1")
        ld.tra_loi("admin1", 3)
        self.assertTrue(tep2.exists(), "trả lời của admin này đụng tệp của admin kia")


class CauHoiTests(unittest.TestCase):
    """Đúng ba lựa chọn, đánh số, nằm trong khối bấm chọn được."""

    def test_dung_dinh_dang_khoi_lua_chon(self):
        s = ld.cau_hoi("bao-cao.pdf")
        self.assertIn("<<<ASK>>>", s)
        self.assertIn("<<<END>>>", s)
        than = s.split("<<<ASK>>>")[1].split("<<<END>>>")[0].strip()
        self.assertEqual(len(than.splitlines()), 3)

    def test_moi_dong_co_nhan_va_lenh(self):
        than = ld.cau_hoi("a.pdf").split("<<<ASK>>>")[1].split("<<<END>>>")[0]
        for dong in than.strip().splitlines():
            self.assertIn("|", dong)

    def test_co_duong_thoat_khoi_bi_hoi_mai(self):
        self.assertIn("khỏi hỏi lại", ld.cau_hoi("a.pdf"))


if __name__ == "__main__":
    unittest.main()
