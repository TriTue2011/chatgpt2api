"""Tag bot → gửi ảnh (không tag) → tag hỏi "mô tả ảnh" thì phải xem được ảnh đó.

Đo thật trên máy chủ 06/08 lúc 11:43–11:45, nhóm Homeassistant:

    11:43:32  Nguyễn Việt: @BenBap
    11:43:43  Botmitbap:   Dạ em đây ạ 😊 Anh cần em giúp việc gì hôm nay?
    11:43:49  Nguyễn Việt: [Hình ảnh]          ← KHÔNG tag
    11:44:35  Nguyễn Việt: @BenBap ảnh
    11:45:04  Nguyễn Việt: @BenBap mô tả ảnh
    11:45:09  Botmitbap:   Dạ em đây ạ 😊 …    ← vẫn chỉ chào

Log bot server có đủ `msgType: 'chat.photo'` kèm `href`, tức ảnh TỚI NƠI. Cổng
"trong nhóm phải tag bot" loại nó, và loại IM LẶNG: dòng log báo điều đó nằm ở
mức INFO trong khi logger của `services.zalo_personal` đang ở mức WARNING.

Zalo không cho vừa tag vừa đính ảnh trong một tin, nên đây là cách người ta buộc
phải làm — không thể bắt họ đổi thói quen.
"""
import os
import sys
import time
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import photo_intent as phi  # noqa: E402


class NhoAnhGanDayTests(unittest.TestCase):

    KHOA = "zalop:acc:nhom1"

    def setUp(self):
        phi._anh_gan_day.clear()

    def test_nho_roi_lay_lai_duoc(self):
        phi.nho_anh_gan_day(self.KHOA, "https://photo/x.jpg")
        self.assertEqual(phi.lay_anh_gan_day(self.KHOA), "https://photo/x.jpg")

    def test_thread_khac_khong_dung_ke(self):
        phi.nho_anh_gan_day(self.KHOA, "https://photo/x.jpg")
        self.assertEqual(phi.lay_anh_gan_day("zalop:acc:nhom2"), "")

    def test_het_han_thi_thoi(self):
        phi.nho_anh_gan_day(self.KHOA, "https://photo/x.jpg")
        phi._anh_gan_day[self.KHOA] = ("https://photo/x.jpg",
                                       time.time() - phi._ANH_GAN_DAY_TTL - 1)
        self.assertEqual(phi.lay_anh_gan_day(self.KHOA), "")

    def test_anh_moi_de_len_anh_cu(self):
        phi.nho_anh_gan_day(self.KHOA, "https://photo/cu.jpg")
        phi.nho_anh_gan_day(self.KHOA, "https://photo/moi.jpg")
        self.assertEqual(phi.lay_anh_gan_day(self.KHOA), "https://photo/moi.jpg")

    def test_dung_xong_thi_quen(self):
        phi.nho_anh_gan_day(self.KHOA, "https://photo/x.jpg")
        phi.quen_anh_gan_day(self.KHOA)
        self.assertEqual(phi.lay_anh_gan_day(self.KHOA), "")

    def test_chua_co_gi_thi_tra_rong(self):
        self.assertEqual(phi.lay_anh_gan_day("chua-co"), "")


class NhanRaCauHoiVeAnhTests(unittest.TestCase):
    """Nhận rộng quá thì mọi câu có chữ 'ảnh' đều lôi tấm ảnh cũ ra phân tích."""

    def test_cac_cach_hoi_ve_anh(self):
        for t in ("mô tả ảnh", "@BenBap mô tả ảnh", "phân tích ảnh giúp em",
                  "xem ảnh này", "ảnh này là gì", "ảnh vừa gửi có gì",
                  "đọc hình giúp anh", "mo ta anh", "dịch ảnh này",
                  "kiểm tra tấm ảnh", "bức ảnh trên là gì"):
            with self.subTest(t=t):
                self.assertTrue(phi.hoi_ve_anh(t), f"bỏ sót: {t}")

    def test_cau_khong_hoi_ve_anh(self):
        for t in ("", "hôm nay trời đẹp", "gửi file cho nhóm A",
                  "tạo ảnh con mèo đang bay", "bật đèn phòng khách",
                  "mấy giờ rồi", "ảnh"):
            with self.subTest(t=t):
                self.assertFalse(phi.hoi_ve_anh(t), f"nhận nhầm: {t}")


class NoiVaoZaloCaNhanTests(unittest.TestCase):

    def _src(self):
        return (GOC / "services" / "zalo_personal.py").read_text("utf-8")

    def test_nho_anh_TRUOC_cong_tag(self):
        """Nhớ sau cổng tag thì đúng tấm ảnh bị loại lại là tấm không được nhớ."""
        src = self._src()
        i_nho = src.index("nho_anh_gan_day(tkey")
        i_cong = src.index("Bộ lọc TAG (nhóm)")
        self.assertLess(i_nho, i_cong)

    def test_khoa_la_cap_THREAD_khong_kem_nguoi(self):
        """Ảnh gửi trong nhóm là của cả nhóm — ai hỏi về nó cũng phải dùng được."""
        src = self._src()
        self.assertIn('tkey = f"zalop:{ev.get(\'account_id\')}:{thread_id}"', src)

    def test_co_duong_dung_lai_anh_khi_co_nguoi_hoi(self):
        src = self._src()
        self.assertIn("hoi_ve_anh(text)", src)
        self.assertIn("lay_anh_gan_day(tkey)", src)
        self.assertIn("_do_photo_request(", src)

    def test_ban_cho_cua_nguoi_do_duoc_uu_tien_truoc(self):
        src = self._src()
        self.assertIn("not _phi.has_pending(pkey) and _phi.hoi_ve_anh(text)", src)

    def test_anh_di_duong_chinh_thi_quen_di(self):
        src = self._src()
        self.assertIn("quen_anh_gan_day(tkey)", src)

    def test_chi_nho_DUONG_DAN_khong_tai_ve(self):
        """Tải mọi ảnh trong nhóm về là tốn băng thông và giữ ảnh người lạ."""
        src = self._src()
        i = src.index("nho_anh_gan_day(tkey")
        khoi = src[i - 400:i + 120]
        self.assertNotIn("_download(", khoi)


if __name__ == "__main__":
    unittest.main()
