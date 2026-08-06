"""Cấu hình lưu trữ online — mặc định tắt, kế thừa hẹp→rộng, xếp thư mục theo loại.

Đi cùng nếp «Nhật ký nhóm»: mặc định TẮT vì đây là đem tài liệu người khác gửi
trong nhóm bỏ vào tài khoản đám mây riêng của chủ máy.
"""
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import luu_tru_online as lt  # noqa: E402


class _CauHinhGia:
    """Thay `config` bằng dict trong bộ nhớ — không đụng config.json thật."""

    def __init__(self, data):
        self.data = data
        self.da_ghi = None

    def get(self):
        return self.data

    def update(self, moi):
        self.da_ghi = moi
        self.data.update(moi)


def _gan(du_lieu):
    goc = lt.config
    lt.config = _CauHinhGia(du_lieu)
    return goc


class MacDinhTatTests(unittest.TestCase):

    def tearDown(self):
        lt.config = self._goc

    def setUp(self):
        self._goc = _gan({})

    def test_khong_cau_hinh_thi_tat(self):
        cd = lt.cai_dat("zalop", "nhom123")
        self.assertFalse(cd["enabled"])

    def test_bat_nhung_chua_khai_kho_thi_van_tat(self):
        """Bật mà không có kho thì đẩy đi đâu — phải coi như chưa bật."""
        lt.config = _CauHinhGia({"luu_tru_online": {
            "zalop:nhom123": {"enabled": True, "kho": ""}}})
        self.assertFalse(lt.cai_dat("zalop", "nhom123")["enabled"])

    def test_bat_va_co_kho_thi_bat(self):
        lt.config = _CauHinhGia({"luu_tru_online": {
            "zalop:nhom123": {"enabled": True, "kho": "drive"}}})
        cd = lt.cai_dat("zalop", "nhom123")
        self.assertTrue(cd["enabled"])
        self.assertEqual(cd["kho"], "drive")


class KeThuaHepThangRongTests(unittest.TestCase):

    def setUp(self):
        self._goc = _gan({"luu_tru_online": {
            "zalop": {"enabled": True, "kho": "kho-chung"},
            "zalop:nhom123": {"enabled": True, "kho": "kho-nhom"},
            "zalop:nhom123:userA": {"enabled": True, "kho": "kho-rieng"},
        }})

    def tearDown(self):
        lt.config = self._goc

    def test_nguoi_thang_nhom(self):
        self.assertEqual(lt.cai_dat("zalop", "nhom123", user="userA")["kho"], "kho-rieng")

    def test_nhom_thang_kenh(self):
        self.assertEqual(lt.cai_dat("zalop", "nhom123", user="userB")["kho"], "kho-nhom")

    def test_khong_khop_thi_ve_muc_kenh(self):
        self.assertEqual(lt.cai_dat("zalop", "nhom-khac")["kho"], "kho-chung")

    def test_kenh_khac_thi_tat(self):
        self.assertFalse(lt.cai_dat("tg", "nhom123")["enabled"])


class ThuMucTheoLoaiTests(unittest.TestCase):
    """Chủ máy nêu rõ: mỗi loại một thư mục riêng để tìm cho dễ."""

    def test_moi_loai_mot_thu_muc(self):
        cap = [("bao-cao.pdf", "PDF"), ("bao-cao.docx", "Word"),
               ("bang-luong.xlsx", "Excel"), ("slide.pptx", "PowerPoint"),
               ("cu.doc", "Word"), ("cu.xls", "Excel"), ("cu.ppt", "PowerPoint")]
        for ten, mong in cap:
            with self.subTest(ten=ten):
                self.assertEqual(lt.thu_muc_loai(ten), mong)

    def test_anh_co_thu_muc_rieng(self):
        for ten in ("hinh.jpg", "chup.PNG", "cu.heic", "dong.gif"):
            with self.subTest(ten=ten):
                self.assertEqual(lt.thu_muc_loai(ten), "Ảnh")

    def test_loai_la_thi_vao_khac(self):
        self.assertEqual(lt.thu_muc_loai("ghi-am.mp3"), "Khác")

    def test_khong_phan_biet_hoa_thuong(self):
        self.assertEqual(lt.thu_muc_loai("BAO-CAO.PDF"), "PDF")


class DuongDanDichTests(unittest.TestCase):

    def setUp(self):
        self._goc = _gan({})

    def tearDown(self):
        lt.config = self._goc

    def test_ghep_du_kho_thu_muc_goc_va_loai(self):
        cd = {"enabled": True, "kho": "drive", "thu_muc": "Gia đình"}
        self.assertEqual(lt.duong_dan_dich(cd, "bao-cao.docx"), "drive:Gia đình/Word")

    def test_khong_co_thu_muc_goc_thi_chi_co_loai(self):
        cd = {"enabled": True, "kho": "drive", "thu_muc": ""}
        self.assertEqual(lt.duong_dan_dich(cd, "a.pdf"), "drive:PDF")

    def test_nhat_ky_di_thu_muc_rieng(self):
        cd = {"enabled": True, "kho": "drive", "thu_muc": "Nhóm A"}
        self.assertEqual(lt.duong_dan_dich(cd, "2026-08.jsonl", nhat_ky=True),
                         "drive:Nhóm A/Nhật ký")

    def test_chua_bat_thi_khong_co_dich(self):
        self.assertEqual(lt.duong_dan_dich({"enabled": False, "kho": "drive"}, "a.pdf"), "")


class LuonLuonLuuTests(unittest.TestCase):
    """Admin chọn "Luôn luôn lưu" → tắt hỏi lại ĐÚNG phạm vi, không đẻ khoá mới."""

    def setUp(self):
        self._goc = _gan({"luu_tru_online": {
            "zalop:nhom123": {"enabled": True, "kho": "drive", "hoi_truoc": True}}})

    def tearDown(self):
        lt.config = self._goc

    def test_ghi_vao_khoa_da_co_chu_khong_tao_khoa_moi(self):
        self.assertTrue(lt.dat_luon_luon_luu("zalop", "nhom123", user="userA"))
        ghi = lt.config.da_ghi["luu_tru_online"]
        self.assertIn("zalop:nhom123", ghi)
        self.assertNotIn("zalop:nhom123:userA", ghi)
        self.assertFalse(ghi["zalop:nhom123"]["hoi_truoc"])

    def test_giu_nguyen_cac_truong_khac(self):
        lt.dat_luon_luon_luu("zalop", "nhom123")
        self.assertEqual(lt.config.da_ghi["luu_tru_online"]["zalop:nhom123"]["kho"], "drive")

    def test_khong_co_ban_ghi_nao_thi_bao_that_bai(self):
        lt.config = _CauHinhGia({"luu_tru_online": {}})
        self.assertFalse(lt.dat_luon_luon_luu("zalop", "nhom-la"))


class HanGiuVaGioDongBoTests(unittest.TestCase):

    def setUp(self):
        self._goc = _gan({})

    def tearDown(self):
        lt.config = self._goc

    def test_gio_sai_dinh_dang_thi_ve_mac_dinh(self):
        for xau in ("25:00", "ba giờ", "3h", "", "12:99"):
            with self.subTest(xau=xau):
                lt.config = _CauHinhGia({"luu_tru_online": {
                    "zalop": {"enabled": True, "kho": "d", "gio_dong_bo": xau}}})
                self.assertEqual(lt.cai_dat("zalop", "n")["gio_dong_bo"],
                                 lt.MAC_DINH_GIO_DONG_BO)

    def test_gio_hop_le_thi_giu(self):
        lt.config = _CauHinhGia({"luu_tru_online": {
            "zalop": {"enabled": True, "kho": "d", "gio_dong_bo": "02:30"}}})
        self.assertEqual(lt.cai_dat("zalop", "n")["gio_dong_bo"], "02:30")

    def test_han_giu_am_thi_ve_khong(self):
        lt.config = _CauHinhGia({"luu_tru_online": {
            "zalop": {"enabled": True, "kho": "d", "giu_ngay": {"PDF": -5}}}})
        self.assertEqual(lt.cai_dat("zalop", "n")["giu_ngay"]["PDF"], 0)

    def test_han_giu_online_mac_dinh_dai_hon_cuc_bo(self):
        """Cục bộ 30 ngày; online phải dài hơn, không thì đám mây vô nghĩa."""
        self.assertGreater(lt.MAC_DINH_GIU_NGAY, 30)


class HanGiuTachTheoMucTests(unittest.TestCase):
    """Hạn giữ online đặt RIÊNG từng mục — ảnh có thể giữ ngắn, nhật ký giữ dài."""

    def setUp(self):
        self._goc = _gan({"luu_tru_online": {"zalop": {
            "enabled": True, "kho": "drive",
            "giu_ngay": {"PDF": 400, "Ảnh": 60, "Nhật ký": 730}}}})

    def tearDown(self):
        lt.config = self._goc

    def test_moi_muc_lay_dung_han_cua_no(self):
        cd = lt.cai_dat("zalop", "n")
        self.assertEqual(lt.han_giu(cd, "a.pdf"), 400)
        self.assertEqual(lt.han_giu(cd, "hinh.jpg"), 60)
        self.assertEqual(lt.han_giu(cd, "2026-08.jsonl", nhat_ky=True), 730)

    def test_muc_khong_khai_thi_ve_mac_dinh(self):
        self.assertEqual(lt.han_giu(lt.cai_dat("zalop", "n"), "a.docx"),
                         lt.MAC_DINH_GIU_NGAY)

    def test_du_moi_muc_trong_ket_qua(self):
        giu = lt.cai_dat("zalop", "n")["giu_ngay"]
        for m in lt.CAC_MUC:
            self.assertIn(m, giu)

    def test_cau_hinh_dang_cu_mot_so_van_hieu(self):
        """Cấu hình viết trước lúc tách mục: một số = mọi mục cùng hạn đó."""
        lt.config = _CauHinhGia({"luu_tru_online": {
            "zalop": {"enabled": True, "kho": "d", "giu_ngay": 90}}})
        giu = lt.cai_dat("zalop", "n")["giu_ngay"]
        self.assertEqual(set(giu.values()), {90})



class ThreadAdminNhanTests(unittest.TestCase):
    """Nhiều admin thì phải chỉ rõ ai nhận câu hỏi xác nhận."""

    def setUp(self):
        self._goc = _gan({"luu_tru_online": {
            "zalop": {"enabled": True, "kho": "d", "thread_admin": "zalop:admin-chung"},
            "zalop:nhom1": {"enabled": True, "kho": "d", "thread_admin": "zalop:admin-nhom1"},
            "zalop:nhom2": {"enabled": True, "kho": "d"},
        }})

    def tearDown(self):
        lt.config = self._goc

    def test_lay_admin_cua_dung_pham_vi(self):
        self.assertEqual(lt.thread_admin_nhan("zalop", "nhom1"), "zalop:admin-nhom1")

    def test_khong_khai_thi_ke_thua_muc_rong_hon(self):
        self.assertEqual(lt.thread_admin_nhan("zalop", "nhom2"), "zalop:admin-chung")

    def test_khong_co_gi_thi_tra_rong_chu_khong_doan(self):
        """Đoán bừa một admin là gửi tài liệu nhóm này sang admin nhóm khác."""
        self.assertEqual(lt.thread_admin_nhan("tg", "nhom-la"), "")

if __name__ == "__main__":
    unittest.main()
