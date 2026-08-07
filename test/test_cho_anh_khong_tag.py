"""Bot xin ảnh xong thì ảnh gửi sau đó phải qua được cổng chặn-nếu-không-tag.

Đo thật trên máy chủ 06/08 lúc 07:07: chủ máy tag bot hỏi "phân tích ảnh", bot
trả lời xin ảnh, rồi gửi ảnh KHÔNG tag. Log bot server có `msgType: 'chat.photo'`
kèm đường dẫn ảnh — tức ảnh TỚI NƠI — rồi im bặt, không lời gọi vision nào. Cổng
"trong nhóm chỉ trả lời khi được tag" loại nó ngay trước khi tới phần nhận ảnh.
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


class NhanRaCauXinAnhTests(unittest.TestCase):

    def setUp(self):
        phi._cho_anh.clear()

    def test_cac_cach_bot_xin_anh(self):
        for r in ("Anh vui lòng gửi ảnh hoặc link ảnh muốn em xem nhé",
                  "Anh có thể gửi ảnh muốn em phân tích ạ?",
                  "Anh cho em xin hình cần xem với ạ",
                  "Anh gui anh len giup em nhe"):
            with self.subTest(r=r):
                phi._cho_anh.clear()
                self.assertTrue(phi.danh_dau_neu_xin_anh("k", r), f"bỏ sót: {r}")

    def test_cau_thuong_khong_bat_co(self):
        """Bật nhầm thì cổng tag mở oan, ai nói gì bot cũng trả lời."""
        for r in ("Hôm nay trời đẹp ạ",
                  "Em đã lưu tài liệu vào kho rồi ạ",
                  "Dạ vâng ạ"):
            with self.subTest(r=r):
                phi._cho_anh.clear()
                self.assertFalse(phi.danh_dau_neu_xin_anh("k", r))


class CoChoAnhTests(unittest.TestCase):

    def setUp(self):
        phi._cho_anh.clear()

    def test_bat_roi_thi_dang_cho(self):
        phi.danh_dau_neu_xin_anh("k", "gửi ảnh giúp em")
        self.assertTrue(phi.dang_cho_anh("k"))

    def test_chi_dung_dung_nguoi(self):
        """Chờ theo từng người — người khác trong nhóm không dùng ké được."""
        phi.danh_dau_neu_xin_anh("zalop:acc:nhom:userA", "gửi ảnh giúp em")
        self.assertTrue(phi.dang_cho_anh("zalop:acc:nhom:userA"))
        self.assertFalse(phi.dang_cho_anh("zalop:acc:nhom:userB"))

    def test_het_han_thi_thoi(self):
        phi.danh_dau_neu_xin_anh("k", "gửi ảnh giúp em")
        phi._cho_anh["k"] -= phi._CHO_ANH_TTL + 1
        self.assertFalse(phi.dang_cho_anh("k"))

    def test_dung_mot_lan_roi_dong(self):
        phi.danh_dau_neu_xin_anh("k", "gửi ảnh giúp em")
        phi.het_cho_anh("k")
        self.assertFalse(phi.dang_cho_anh("k"),
                         "cờ không được mở cổng mãi sau khi đã dùng")

    def test_chua_bat_thi_khong_cho(self):
        self.assertFalse(phi.dang_cho_anh("chua-co"))


class CongTagCoNgoaiLeTests(unittest.TestCase):
    """Cổng tag phải tra bản chờ TRƯỚC khi loại tin."""

    def test_khoa_cho_tinh_truoc_cong_tag(self):
        src = (GOC / "services" / "zalo_personal.py").read_text("utf-8")
        i_pkey = src.index("pkey = f\"zalop:")
        i_cong = src.index("Bộ lọc TAG (nhóm)")
        self.assertLess(i_pkey, i_cong,
                        "pkey phải tính TRƯỚC cổng tag, không thì cổng không tra được bản chờ")

    def test_cong_tag_mo_khi_dang_cho(self):
        src = (GOC / "services" / "zalo_personal.py").read_text("utf-8")
        self.assertIn("dang_cho_anh(pkey)", src)
        self.assertIn("het_cho_anh(pkey)", src, "phải đóng cờ sau khi dùng")

    def test_co_dat_khi_bot_xin_anh(self):
        src = (GOC / "services" / "zalo_personal.py").read_text("utf-8")
        self.assertIn("danh_dau_neu_xin_anh(pkey, reply)", src)


if __name__ == "__main__":
    unittest.main()


class MenuAnhCoMucLuuKhoTests(unittest.TestCase):
    """Menu ảnh phải có mục «Lưu lên kho đám mây» khi phạm vi đã khai kho.

    Bỏ câu hỏi lưu lúc vừa nhận ảnh (07/08) CHỈ đúng khi menu còn đường lưu.
    Mất cả hai là không còn cách nào đưa ảnh lên kho — nên hai điều đó buộc
    phải đi cùng nhau, và bài này giữ chúng lại với nhau.
    """

    def test_khai_kho_thi_menu_co_muc_luu(self):
        from unittest import mock
        from services import photo_intent as pi
        with mock.patch("services.agent.luu_tru_online.cai_dat",
                        return_value={"enabled": True}):
            ds = pi.them_luu_online({pi.ANALYZE}, "zalop", "g1")
        self.assertIn(pi.LUU_ONLINE, ds)
        self.assertIn("kho đám mây", pi.ask_text(ds).lower())

    def test_CHUA_khai_kho_thi_khong_bay_muc_vo_dung(self):
        from unittest import mock
        from services import photo_intent as pi
        with mock.patch("services.agent.luu_tru_online.cai_dat",
                        return_value={"enabled": False}):
            ds = pi.them_luu_online({pi.ANALYZE}, "zalop", "g1")
        self.assertNotIn(pi.LUU_ONLINE, ds)

    def test_khong_nam_trong_ALL_INTENTS(self):
        """Nằm trong ALL_INTENTS là mọi phạm vi đều thấy, kể cả nơi chưa khai
        kho — bấm vào không ra gì."""
        from services import photo_intent as pi
        self.assertNotIn(pi.LUU_ONLINE, pi.ALL_INTENTS)

    def test_tu_khoa_luu_khong_bi_nhanh_phan_tich_nuot(self):
        """Nhánh phân tích bắt cụm "ảnh này", nên "lưu ảnh này lên kho" phải
        được xét TRƯỚC, không thì rơi vào phân tích."""
        from services import photo_intent as pi
        cho = {pi.ANALYZE, pi.GENERATE, pi.LUU_ONLINE}
        self.assertEqual(pi.parse_intent("lưu ảnh này lên kho", cho), pi.LUU_ONLINE)
        self.assertEqual(pi.parse_intent("phân tích ảnh này", cho), pi.ANALYZE)
