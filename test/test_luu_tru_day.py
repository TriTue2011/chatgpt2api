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

    def __call__(self, tep, cd, nhat_ky=False, pham_vi=None):
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


class DocTraLoiCuaAdminTests(_Base):
    """Admin gõ "1" phải ra đúng lệnh, và tra nhiều lần vẫn ra cùng kết quả."""

    KHOA = "zalop:acc:admin1"

    def setUp(self):
        super().setUp()
        ld._cho.clear()
        ld.dat_cho(self.KHOA, tep=str(self.tep), kenh="zalop", chat="nhom1")

    def test_go_so_ra_dung_lua_chon(self):
        for so in (1, 2, 3):
            with self.subTest(so=so):
                self.assertEqual(ld.chon_tu_tra_loi(self.KHOA, str(so)), so)

    def test_go_dung_nhan_cung_ra_lua_chon(self):
        self.assertEqual(ld.chon_tu_tra_loi(self.KHOA, ld.LUA_CHON[2]), 3)
        self.assertEqual(ld.chon_tu_tra_loi(self.KHOA, ld.LENH[0]), 1)

    def test_khong_phan_biet_hoa_thuong(self):
        self.assertEqual(ld.chon_tu_tra_loi(self.KHOA, "XOÁ"), 3)

    def test_cau_thuong_khong_bi_nhan_vo(self):
        for t in ("hôm nay trời đẹp", "gửi file cho nhóm A", "", "4", "10"):
            with self.subTest(t=t):
                self.assertEqual(ld.chon_tu_tra_loi(self.KHOA, t), 0)

    def test_khong_co_tep_cho_thi_so_khong_co_nghia(self):
        """Nhóm admin nói chuyện bình thường: mọi câu "1" không được thành lệnh."""
        ld.bo_cho(self.KHOA)
        self.assertEqual(ld.chon_tu_tra_loi(self.KHOA, "1"), 0)

    def test_tra_hai_lan_van_ra_ket_qua(self):
        """Cổng tag tra một lần, phần xử lý tra lần nữa — tra là mất thì hỏng."""
        self.assertEqual(ld.chon_tu_tra_loi(self.KHOA, "1"), 1)
        self.assertEqual(ld.chon_tu_tra_loi(self.KHOA, "1"), 1)

    def test_chi_tra_loi_moi_tieu_ban_cho(self):
        ld.chon_tu_tra_loi(self.KHOA, "1")
        self.assertTrue(ld.lay_cho(self.KHOA))
        ld.tra_loi(self.KHOA, 1)
        self.assertFalse(ld.lay_cho(self.KHOA))

    def test_cau_hoi_da_danh_so_cho_admin_doc(self):
        s = ld.chuan_bi_hoi("bao-cao.pdf", ten_nhom="Nhóm A")
        self.assertNotIn("<<<ASK>>>", s, "khối điều khiển phải bóc trước khi gửi")
        self.assertIn("bao-cao.pdf", s)
        self.assertIn("Nhóm A", s)
        for i, nhan in enumerate(ld.LUA_CHON, 1):
            self.assertIn(f"{i}. {nhan}", s)


class SauChuyenDoiTests(unittest.TestCase):
    """Chủ máy chốt: chuyển đổi xong → ba lựa chọn (bản đã chuyển / cả hai /
    không lưu). Khác hẳn ba lựa chọn lúc mới nhận tệp."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        goc = Path(self.tmp.name)
        self.goc_pdf = goc / "bao-cao.pdf"
        self.goc_pdf.write_bytes(b"pdf goc")

        from services import rclone_service as rcl
        self._ws = rcl.workspace_dir
        rcl.workspace_dir = lambda: goc
        self.addCleanup(setattr, rcl, "workspace_dir", self._ws)

        self.nen = _Nen()
        self._day_goc = ld.day_nen
        ld.day_nen = self.nen
        self.addCleanup(setattr, ld, "day_nen", self._day_goc)

        self.da_gui = []
        self._gui_goc = ld.gui_toi_admin
        ld.gui_toi_admin = lambda khoa, text, dinh_danh="": (
            self.da_gui.append((khoa, text)) or True)
        self.addCleanup(setattr, ld, "gui_toi_admin", self._gui_goc)

        self._cfg_goc = lt.config
        lt.config = _CauHinhGia({"luu_tru_online": {"zalop:nhom1": {
            "enabled": True, "kho": "drive", "thu_muc": "GD",
            "thread_admin": "zalop:admin9"}}})
        self.addCleanup(setattr, lt, "config", self._cfg_goc)
        ld._cho.clear()

    KHOA = "zalop:acc1:admin9"

    def _hoi(self):
        ld.moi_luu_sau_chuyen_doi(
            "zalop", "nhom1", tep_goc=str(self.goc_pdf), ten_goc="bao-cao.pdf",
            du_lieu_moi=b"docx moi", ten_moi="bao-cao.docx", dinh_danh="acc1")

    def test_hoi_dung_ba_lua_chon_cua_loi_chuyen_doi(self):
        self._hoi()
        self.assertEqual(len(self.da_gui), 1)
        text = self.da_gui[0][1]
        for i, nhan in enumerate(ld.LUA_CHON_CD, 1):
            self.assertIn(f"{i}. {nhan}", text)
        self.assertNotIn("Luôn luôn lưu", text,
                         "chuyển đổi là việc gọi từng lần, không có 'luôn luôn'")

    def test_chua_tra_loi_thi_chua_day_gi(self):
        self._hoi()
        self.assertEqual(self.nen.da_day, [])

    def test_chon_1_chi_day_ban_da_chuyen(self):
        self._hoi()
        ld.tra_loi(self.KHOA, 1)
        self.assertEqual([Path(t).name for t, _ in self.nen.da_day],
                         ["bao-cao.docx"])
        self.assertEqual(self.nen.da_day[0][1], "drive:GD/Word")

    def test_chon_2_day_ca_hai_vao_dung_thu_muc_loai(self):
        self._hoi()
        ld.tra_loi(self.KHOA, 2)
        dich = {Path(t).name: d for t, d in self.nen.da_day}
        self.assertEqual(dich["bao-cao.docx"], "drive:GD/Word")
        self.assertEqual(dich["bao-cao.pdf"], "drive:GD/PDF")

    def test_chon_3_khong_day_gi_va_don_sach(self):
        self._hoi()
        ld.tra_loi(self.KHOA, 3)
        self.assertEqual(self.nen.da_day, [])
        con = list((Path(self.tmp.name) / "da_nhan").glob("*"))
        self.assertEqual(con, [], "không lưu mà vẫn để lại bản tạm")

    def test_chon_1_thi_ban_goc_tam_khong_nam_lai(self):
        self._hoi()
        ld.tra_loi(self.KHOA, 1)
        con = sorted(p.name for p in (Path(self.tmp.name) / "da_nhan").glob("*"))
        self.assertEqual(con, ["bao-cao.docx"])

    def test_go_nhan_cua_loi_chuyen_doi_ra_dung_so(self):
        self._hoi()
        self.assertEqual(ld.chon_tu_tra_loi(self.KHOA, ld.LUA_CHON_CD[1]), 2)

    def test_nhan_cua_loi_NHAN_TEP_khong_khop_o_day(self):
        """Hai bảng lựa chọn khác nhau — không được lẫn."""
        self._hoi()
        self.assertEqual(ld.chon_tu_tra_loi(self.KHOA, "Luôn luôn lưu (khỏi hỏi lại)"), 0)

    def test_chua_bat_pham_vi_thi_khong_hoi(self):
        lt.config = _CauHinhGia({"luu_tru_online": {}})
        self._hoi()
        self.assertEqual(self.da_gui, [])

    def test_chua_chon_admin_thi_khong_hoi(self):
        lt.config = _CauHinhGia({"luu_tru_online": {"zalop:nhom1": {
            "enabled": True, "kho": "drive", "thu_muc": "GD"}}})
        self._hoi()
        self.assertEqual(self.da_gui, [])

    def test_gui_hong_thi_don_sach(self):
        ld.gui_toi_admin = lambda khoa, text, dinh_danh="": False
        self._hoi()
        self.assertFalse(ld.lay_cho(self.KHOA))
        con = list((Path(self.tmp.name) / "da_nhan").glob("*"))
        self.assertEqual(con, [])


class SauTomTatTests(unittest.TestCase):
    """Chủ máy chốt: "tóm tắt → chỉ hỏi có lưu tệp không" — hai lựa chọn.

    Lưu BẢN TÓM TẮT chứ không phải tệp gốc: tệp gốc đã được hỏi ngay lúc nhận,
    hỏi lại là hỏi hai lần về cùng một tệp.
    """

    KHOA = "zalop:acc1:admin9"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        goc = Path(self.tmp.name)

        from services import rclone_service as rcl
        self._ws = rcl.workspace_dir
        rcl.workspace_dir = lambda: goc
        self.addCleanup(setattr, rcl, "workspace_dir", self._ws)

        self.nen = _Nen()
        self._day_goc = ld.day_nen
        ld.day_nen = self.nen
        self.addCleanup(setattr, ld, "day_nen", self._day_goc)

        self.da_gui = []
        self._gui_goc = ld.gui_toi_admin
        ld.gui_toi_admin = lambda khoa, text, dinh_danh="": (
            self.da_gui.append((khoa, text)) or True)
        self.addCleanup(setattr, ld, "gui_toi_admin", self._gui_goc)

        self._cfg_goc = lt.config
        lt.config = _CauHinhGia({"luu_tru_online": {"zalop:nhom1": {
            "enabled": True, "kho": "drive", "thu_muc": "GD",
            "thread_admin": "zalop:admin9"}}})
        self.addCleanup(setattr, lt, "config", self._cfg_goc)
        ld._cho.clear()

    def _hoi(self, tom_tat="Nội dung chính: họp thứ ba."):
        ld.moi_luu_tom_tat("zalop", "nhom1", ten_goc="bao-cao.pdf",
                           tom_tat=tom_tat, dinh_danh="acc1")

    def test_chi_hai_lua_chon(self):
        self._hoi()
        text = self.da_gui[0][1]
        self.assertIn("1. Lưu bản tóm tắt", text)
        self.assertIn("2. Không lưu", text)
        self.assertNotIn("3.", text, "tóm tắt không có lựa chọn thứ ba")

    def test_go_3_khong_duoc_nhan(self):
        """Bảng chỉ có hai mục — nhận "3" là nhận một lựa chọn không tồn tại."""
        self._hoi()
        self.assertEqual(ld.chon_tu_tra_loi(self.KHOA, "3"), 0)
        self.assertEqual(ld.chon_tu_tra_loi(self.KHOA, "2"), 2)

    def test_chon_1_thi_day_ban_tom_tat(self):
        self._hoi()
        ld.tra_loi(self.KHOA, 1)
        self.assertEqual(len(self.nen.da_day), 1)
        tep, dich = self.nen.da_day[0]
        self.assertTrue(Path(tep).name.endswith("-tom-tat.md"))
        self.assertIn("bao-cao", Path(tep).name)
        self.assertEqual(dich, "drive:GD/Khác")

    def test_noi_dung_tom_tat_duoc_ghi_ra_tep(self):
        self._hoi("Họp lúc 9 giờ thứ ba.")
        tep = Path(ld.lay_cho(self.KHOA)["tep"])
        self.assertEqual(tep.read_text("utf-8"), "Họp lúc 9 giờ thứ ba.")

    def test_chon_2_thi_khong_day_va_don_sach(self):
        self._hoi()
        ld.tra_loi(self.KHOA, 2)
        self.assertEqual(self.nen.da_day, [])
        self.assertEqual(list((Path(self.tmp.name) / "da_nhan").glob("*")), [])

    def test_tom_tat_rong_thi_khong_hoi(self):
        self._hoi("   ")
        self.assertEqual(self.da_gui, [])

    def test_chua_bat_pham_vi_thi_khong_hoi(self):
        lt.config = _CauHinhGia({"luu_tru_online": {}})
        self._hoi()
        self.assertEqual(self.da_gui, [])

    def test_gui_hong_thi_don_sach(self):
        ld.gui_toi_admin = lambda khoa, text, dinh_danh="": False
        self._hoi()
        self.assertFalse(ld.lay_cho(self.KHOA))
        self.assertEqual(list((Path(self.tmp.name) / "da_nhan").glob("*")), [])

    def test_ba_loi_dung_ba_bang_khac_nhau(self):
        """Lẫn bảng là admin bấm "2" ở lối này ra việc của lối kia."""
        self.assertEqual(len(ld._bang(ld.KIEU_NHAN)[0]), 3)
        self.assertEqual(len(ld._bang(ld.KIEU_CHUYEN_DOI)[0]), 3)
        self.assertEqual(len(ld._bang(ld.KIEU_TOM_TAT)[0]), 2)
        nhan = [ld._bang(k)[0] for k in
                (ld.KIEU_NHAN, ld.KIEU_CHUYEN_DOI, ld.KIEU_TOM_TAT)]
        self.assertEqual(len({tuple(n) for n in nhan}), 3)


class TachThreadAdminTests(unittest.TestCase):

    def test_khoa_nhom(self):
        self.assertEqual(ld.tach_thread_admin("zalop:nhom9"), ("zalop", "nhom9", ""))

    def test_khoa_co_topic(self):
        self.assertEqual(ld.tach_thread_admin("tg:-100123#7"), ("tg", "-100123", "7"))

    def test_khoa_cap_nguoi_van_ra_thread(self):
        self.assertEqual(ld.tach_thread_admin("zalop:nhom9:userA"),
                         ("zalop", "nhom9", ""))
        self.assertEqual(ld.tach_thread_admin("tg:-100123#7:9"),
                         ("tg", "-100123", "7"))

    def test_khoa_ca_kenh_khong_gui_duoc(self):
        """'zalop' là cả kênh — không có thread nào để gửi tới."""
        self.assertEqual(ld.tach_thread_admin("zalop"), ("", "", ""))


class DuoiAnhTests(unittest.TestCase):
    """Đặt sai đuôi là trên đám mây mở ra bằng ứng dụng sai."""

    def test_nhan_theo_byte_dau(self):
        for dau, mong in ((b"\xff\xd8\xff\xe0", ".jpg"), (b"\x89PNG\r\n", ".png"),
                          (b"GIF89a", ".gif"), (b"RIFF\x00\x00\x00\x00WEBP", ".webp")):
            with self.subTest(mong=mong):
                self.assertEqual(ld.duoi_anh(dau), mong)

    def test_khong_nhan_ra_thi_ve_jpg(self):
        self.assertEqual(ld.duoi_anh(b"khong ro"), ".jpg")

    def test_ten_anh_vao_dung_muc_anh(self):
        self.assertEqual(lt.thu_muc_loai(ld.ten_anh(b"\x89PNG\r\n")), "Ảnh")


class MoiLuuTests(unittest.TestCase):
    """Cổng vào: tệp vừa nhận có được hỏi/đẩy hay không."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Khoá phía cục bộ của rclone: ép thư mục làm việc về thư mục tạm.
        from services import rclone_service as rcl
        self._ws_goc = rcl.workspace_dir
        rcl.workspace_dir = lambda: Path(self.tmp.name)
        self.addCleanup(setattr, rcl, "workspace_dir", self._ws_goc)

        self.nen = _Nen()
        self._day_goc = ld.day_nen
        ld.day_nen = self.nen
        self.addCleanup(setattr, ld, "day_nen", self._day_goc)

        self.da_gui = []
        self._gui_goc = ld.gui_toi_admin
        ld.gui_toi_admin = lambda khoa, text, dinh_danh="": (
            self.da_gui.append((khoa, text)) or True)
        self.addCleanup(setattr, ld, "gui_toi_admin", self._gui_goc)

        self._cfg_goc = lt.config
        self.addCleanup(setattr, lt, "config", self._cfg_goc)
        ld._cho.clear()

    def _cau_hinh(self, **them):
        goc = {"enabled": True, "kho": "drive", "thu_muc": "GD",
               "hoi_truoc": True, "thread_admin": "zalop:admin9"}
        lt.config = _CauHinhGia({"luu_tru_online": {"zalop:nhom1": {**goc, **them}}})

    def _goi(self):
        ld.moi_luu("zalop", "nhom1", ten_tep="bao-cao.pdf", du_lieu=b"x",
                   dinh_danh="acc1")

    def test_pham_vi_tat_thi_khong_dong_gi(self):
        self._cau_hinh(enabled=False)
        self._goi()
        self.assertEqual(self.da_gui, [])
        self.assertEqual(self.nen.da_day, [])

    def test_bat_thi_hoi_dung_thread_admin(self):
        self._cau_hinh()
        self._goi()
        self.assertEqual(len(self.da_gui), 1)
        self.assertEqual(self.da_gui[0][0], "zalop:admin9")
        self.assertIn("bao-cao.pdf", self.da_gui[0][1])

    def test_hoi_xong_moi_day_chu_khong_day_truoc(self):
        """Chủ máy chốt: xoá là KHÔNG lên mây — nên không được đẩy lúc hỏi."""
        self._cau_hinh()
        self._goi()
        self.assertEqual(self.nen.da_day, [], "đẩy lên trước khi admin trả lời")

    def test_ban_cho_dat_dung_khoa_thread_admin(self):
        self._cau_hinh()
        self._goi()
        self.assertTrue(ld.lay_cho("zalop:acc1:admin9"),
                        "khoá bản chờ phải khớp khoá kênh dựng lúc đọc trả lời")

    def test_tat_hoi_truoc_thi_day_thang(self):
        self._cau_hinh(hoi_truoc=False)
        self._goi()
        self.assertEqual(self.da_gui, [])
        self.assertEqual(len(self.nen.da_day), 1)
        self.assertEqual(self.nen.da_day[0][1], "drive:GD/PDF")

    def test_chua_chon_admin_thi_khong_hoi_va_khong_luu(self):
        self._cau_hinh(thread_admin="")
        self._goi()
        self.assertEqual(self.da_gui, [])
        self.assertEqual(self.nen.da_day, [])

    def test_admin_khac_kenh_thi_bo_qua_chu_khong_hoi_hong(self):
        """Gửi được sang kênh khác nhưng trả lời tra không ra — đừng hỏi nửa vời."""
        self._cau_hinh(thread_admin="tg:-100999")
        self._goi()
        self.assertEqual(self.da_gui, [])
        self.assertEqual(self.nen.da_day, [])

    def test_gui_hong_thi_don_sach_chu_khong_de_ban_cho_chet(self):
        """Admin không nhận được câu hỏi thì không ai trả lời được nó."""
        ld.gui_toi_admin = lambda khoa, text, dinh_danh="": False
        self._cau_hinh()
        self._goi()
        self.assertFalse(ld.lay_cho("zalop:acc1:admin9"),
                         "để lại bản chờ mà không ai trả lời được")
        con = list((Path(self.tmp.name) / "da_nhan").glob("*"))
        self.assertEqual(con, [], "tệp nằm lại trong thư mục làm việc")

    def test_tep_nam_trong_thu_muc_lam_viec(self):
        """rclone bị khoá trong workspace — ngoài đó là không gửi lên được."""
        self._cau_hinh()
        self._goi()
        tep = Path(ld.lay_cho("zalop:acc1:admin9")["tep"])
        self.assertTrue(tep.exists())
        self.assertIn(Path(self.tmp.name), tep.parents)

    def test_trung_ten_khong_ghi_de_tep_truoc(self):
        self._cau_hinh()
        self._goi()
        t1 = ld.lay_cho("zalop:acc1:admin9")["tep"]
        ld.moi_luu("zalop", "nhom1", ten_tep="bao-cao.pdf", du_lieu=b"khac",
                   dinh_danh="acc1")
        t2 = ld.lay_cho("zalop:acc1:admin9")["tep"]
        self.assertNotEqual(t1, t2)
        self.assertEqual(Path(t1).read_bytes(), b"x")

    def test_ten_tep_co_ky_tu_thoat_thu_muc(self):
        self._cau_hinh()
        ld.moi_luu("zalop", "nhom1", ten_tep="../../etc/passwd", du_lieu=b"x",
                   dinh_danh="acc1")
        tep = Path(ld.lay_cho("zalop:acc1:admin9")["tep"])
        self.assertIn(Path(self.tmp.name), tep.parents)


class NoiVaoKenhTests(unittest.TestCase):
    """Ba kênh phải THẬT SỰ gọi vào — làm module xong mà không cắm là vô dụng.

    Giao diện «Lưu trữ online» cho chọn cả ba kênh, nên kênh nào không cắm là ô
    tích ở đó bật lên mà không có gì xảy ra, và không có lỗi nào để lần ra.
    """

    KENH = ("zalo_personal.py", "telegram_bot.py", "zalo_bot.py")

    def _src(self, ten):
        return (GOC / "services" / ten).read_text("utf-8")

    def test_moi_kenh_moi_luu_ca_tep_va_anh(self):
        for ten in self.KENH:
            with self.subTest(ten=ten):
                src = self._src(ten)
                self.assertIn("_ltd.moi_luu(", src)
                self.assertGreaterEqual(
                    src.count("_moi_luu_online("), 3,
                    "cần gọi ở cả nhánh nhận tệp và nhánh nhận ảnh")

    def test_hai_kenh_co_chuyen_doi_deu_hoi_sau_khi_xong(self):
        """Zalo Bot không chuyển Word/Excel nên không có gì để hỏi ở đó."""
        for ten in ("zalo_personal.py", "telegram_bot.py"):
            with self.subTest(ten=ten):
                src = self._src(ten)
                self.assertIn("moi_luu_sau_chuyen_doi(", src)
                self.assertGreaterEqual(
                    src.count("_moi_luu_sau_chuyen_doi("), 3,
                    "phải hỏi ở CẢ nhánh Word và nhánh Excel")

    def test_hoi_truoc_khi_xoa_ban_da_chuyen(self):
        """Bản đã chuyển bị xoá ngay sau khi gửi — hỏi sau đó là không còn tệp."""
        src = self._src("telegram_bot.py")
        i_hoi = src.index("_moi_luu_sau_chuyen_doi(chat_id, user_id, path, name,")
        i_xoa = src.index("os.unlink(docx_path)")
        self.assertLess(i_hoi, i_xoa)

    def test_hai_kenh_co_tom_tat_deu_hoi_sau_khi_xong(self):
        for ten in ("zalo_personal.py", "telegram_bot.py"):
            with self.subTest(ten=ten):
                src = self._src(ten)
                self.assertIn("moi_luu_tom_tat(", src)
                self.assertIn("_moi_luu_tom_tat(", src)

    def test_moi_kenh_deu_doc_tra_loi_admin(self):
        for ten in self.KENH:
            with self.subTest(ten=ten):
                src = self._src(ten)
                self.assertIn("_ltd.khoa_cho_thread(", src)
                self.assertIn("chon_tu_tra_loi(", src)
                self.assertIn("_ltd.tra_loi(", src)

    def test_cong_tag_mo_cho_cau_tra_loi_cua_admin(self):
        """Nhóm admin bắt buộc tag: gõ "1" mà bị cổng tag loại là bot tự bịt tai."""
        for ten in self.KENH:
            with self.subTest(ten=ten):
                src = self._src(ten)
                i_cong = src.index("Bộ lọc TAG")
                i_doc = src.index("_ltd_cho.chon_tu_tra_loi(")
                i_xu_ly = src.index("_ltd.tra_loi(")
                self.assertLess(i_doc, i_xu_ly,
                                "cổng tag phải tra bản chờ TRƯỚC phần xử lý")
                self.assertLess(abs(i_doc - i_cong), 2000,
                                "lời tra phải nằm trong khối cổng tag")

    def test_khoa_dat_va_khoa_doc_dung_MOT_ham(self):
        """Dựng khoá một đằng tra một nẻo là lỗi đã gặp — ép cả hai qua một hàm."""
        for ten in self.KENH:
            with self.subTest(ten=ten):
                self.assertIn("_ltd.khoa_cho_thread(", self._src(ten))

    def test_kenh_dung_dung_tien_to_cua_no(self):
        """Sai tiền tố là bản chờ đặt một chỗ, tra một chỗ khác."""
        for ten, tien_to in (("zalo_personal.py", '"zalop"'),
                             ("telegram_bot.py", '"tg"'),
                             ("zalo_bot.py", '"zalo"')):
            with self.subTest(ten=ten):
                import re
                src = self._src(ten)
                self.assertIn(f"khoa_cho_thread({tien_to}", src)
                self.assertRegex(src, re.compile(r"moi_luu\(\s*" + tien_to))


if __name__ == "__main__":
    unittest.main()
