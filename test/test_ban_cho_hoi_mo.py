"""Bot vừa hỏi một câu MỞ thì câu trả lời không được coi là "yêu cầu mới".

Lỗi thật (chủ máy, Zalo Bot 04/09 10:38, có ảnh chụp màn hình):

  1. Người dùng gửi ảnh → bot hiện menu 1–7.
  2. Gõ "3" (Phân tích ảnh) → bot hỏi «em cần câu hỏi/yêu cầu cụ thể — ví dụ
     `mô tả ảnh` · `đọc chữ trong ảnh`».
  3. Trả lời «Mô tả ảnh và tìm kiếm thông tin» → chữ "tìm kiếm" khớp `_MENH_LENH`
     nên `la_yeu_cau_moi` trả True, bản chờ bị vứt, ẢNH MẤT, model quay ra bảo
     "Dạ anh gửi ảnh lên đây giúp em nhé".

Trớ trêu: câu trả lời chứa đúng ví dụ bot vừa gợi ý. Docstring của
`yeu_cau_moi` đã nói kiểu hỏng này khó chịu hơn hẳn bỏ sót, và
`facebook_page.py` đã né bằng cách không dùng cổng này — chỉ luồng ảnh/PDF là
còn sót.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.yeu_cau_moi import (  # noqa: E402
    la_yeu_cau_moi,
    nen_dong_ban_cho,
)

#: Đúng câu chủ máy đã gõ lúc 10:38.
CAU_THAT = "Mô tả ảnh và tìm kiếm thông tin"


class BuocHoiMoTests(unittest.TestCase):
    """Ở bước hỏi mở, MỌI câu tới đều là câu trả lời."""

    def test_cau_that_khong_lam_mat_ban_cho(self):
        self.assertFalse(nen_dong_ban_cho(CAU_THAT, "need_prompt"),
                         "câu trả lời cho câu hỏi mở không được đóng bản chờ")

    def test_teacher_meta_cung_duoc_bao_ve(self):
        self.assertFalse(nen_dong_ban_cho("gửi file cho nhóm A", "teacher_meta"))

    def test_cac_vi_du_bot_tu_goi_y_deu_an_toan(self):
        """Bot gợi ý gì thì người dùng gõ nấy — không câu nào được làm mất ảnh."""
        for c in ("mô tả ảnh", "đọc chữ trong ảnh", "ảnh có mấy người?",
                  "mô tả ảnh và tra cứu thêm", "đọc chữ trong ảnh rồi dịch giúp em",
                  "tóm tắt bài trong ảnh"):
            with self.subTest(c=c):
                self.assertFalse(nen_dong_ban_cho(c, "need_prompt"))


class BuocChonVanGiuCongTests(unittest.TestCase):
    """Ở bước `choose` cổng vẫn phải chạy — đừng sửa lỗi này thành lỗi kia."""

    def test_yeu_cau_moi_that_van_dong_ban_cho(self):
        self.assertTrue(nen_dong_ban_cho(CAU_THAT, "choose"))
        self.assertTrue(nen_dong_ban_cho("gửi file cho nhóm A", "choose"))
        self.assertTrue(nen_dong_ban_cho("bật đèn phòng khách giúp anh", "choose"))

    def test_khong_truyen_stage_thi_giu_hanh_vi_cu(self):
        """Mặc định (stage rỗng) phải y hệt `la_yeu_cau_moi` — không đổi ngầm."""
        for c in (CAU_THAT, "gửi file cho nhóm A", "1", "mô tả ảnh", ""):
            with self.subTest(c=c):
                self.assertEqual(nen_dong_ban_cho(c), la_yeu_cau_moi(c))

    def test_chon_so_van_khong_bi_coi_la_yeu_cau_moi(self):
        self.assertFalse(nen_dong_ban_cho("3", "choose"))


class MuiGioTrichDanTests(unittest.TestCase):
    """Giờ trong câu trích dẫn phải là giờ Việt Nam, không phụ thuộc TZ máy."""

    def test_ghim_gio_viet_nam(self):
        from services.agent import trich_dan as td
        # 2025-09-04 15:33:20 UTC = 22:33 giờ VN.
        self.assertEqual(td._luc(1757000000), " lúc 22:33 04/09/2025")

    def test_khong_co_moc_thi_rong(self):
        from services.agent import trich_dan as td
        self.assertEqual(td._luc(0), "")
        self.assertEqual(td._luc(None), "")


class LenhTrongTanNguTests(unittest.TestCase):
    """Zalo Bot không gửi trích dẫn → mệnh lệnh trống tân ngữ là manh mối duy nhất.

    Đo trên máy chủ 04/09 (cả webhook lẫn getUpdates): payload chỉ có
    ['date','chat','message_id','from','text'] — bot KHÔNG biết người dùng có
    bấm trích dẫn hay không. Nên khi họ trích một tin rồi gõ "dịch sang tiếng
    Anh", thứ duy nhất còn lại để suy ra "dịch CÁI GÌ" là chính dạng câu đó.
    Trước bản này `_la_mo_ho` trả False nên bot trả lời trong mù.
    """

    def test_menh_lenh_trong_tan_ngu_duoc_bat(self):
        from services.agent import tham_chieu as tc
        for c in ("dịch sang tiếng Anh", "tóm tắt giúp anh", "giải thích thêm",
                  "dịch giúp em", "tóm tắt lại", "phân tích giúp anh"):
            with self.subTest(c=c):
                self.assertTrue(tc._la_mo_ho(c))

    def test_dai_tu_tro_van_bat_nhu_cu(self):
        from services.agent import tham_chieu as tc
        for c in ("cái này sao rồi", "vụ đó dập chưa", "tin này nói gì"):
            with self.subTest(c=c):
                self.assertTrue(tc._la_mo_ho(c))

    def test_cau_tu_neu_doi_tuong_thi_khong_doan(self):
        """Câu dài tự nêu đối tượng rồi — đoán thêm chỉ tổ nhiễu."""
        from services.agent import tham_chieu as tc
        for c in ("tóm tắt bài báo VnExpress hôm nay giúp anh",
                  "dịch câu sau sang tiếng Anh: hello world",
                  "Nghị định 105 quy định gì về người kiểm tra",
                  "thời tiết Hà Nội hôm nay",
                  "bật đèn phòng khách"):
            with self.subTest(c=c):
                self.assertFalse(tc._la_mo_ho(c))

    def test_lenh_trong_thi_lay_TIN_BOT_gan_nhat_khong_tra_FTS(self):
        """Chữ còn lại là ngôn ngữ đích/lời đệm, đem tra toàn văn chỉ vớ về rác."""
        from services.agent import tham_chieu as tc
        hist = [{"role": "assistant", "content": "U20 Việt Nam đi tiếp trong trường hợp nào?"}]
        ra = tc.doan("u-test", "dịch sang tiếng Anh", hist)
        self.assertIn("U20 Việt Nam", ra)
        self.assertIn("PHỎNG ĐOÁN", ra, "phải đánh dấu là phỏng đoán, không nói chắc")

    def test_cau_thuong_khong_sinh_khoi_doan(self):
        from services.agent import tham_chieu as tc
        hist = [{"role": "assistant", "content": "abc"}]
        self.assertEqual(tc.doan("u-test", "xin chào em", hist), "")

    def test_lenh_trong_dan_THUC_HIEN_tren_noi_dung_khong_dich_cau_lenh(self):
        """Đo 05/09 (cả 2 kênh): "Dịch sang tiếng anh" trên tin được nhắc bị dịch
        CHÍNH câu lệnh → "Translate into English". Khối phỏng đoán phải dặn model
        THỰC HIỆN lệnh TRÊN nội dung, kèm ví dụ phủ định."""
        from services.agent import tham_chieu as tc
        hist = [{"role": "assistant", "content": "U20 Việt Nam đi tiếp trong trường hợp nào?"}]
        ra = tc.doan("u-test", "dịch sang tiếng Anh", hist)
        self.assertIn("THỰC HIỆN", ra)
        self.assertIn("Translate into English", ra, "phải có ví dụ phủ định")

    def test_khoi_trich_dan_that_orchestrator_co_chi_dan_menh_lenh(self):
        """Kênh cá nhân có TRÍCH DẪN THẬT: khối chèn trich_dan trong orchestrator
        cũng phải dặn thực hiện mệnh lệnh trên đoạn trích (không dịch câu lệnh)."""
        from pathlib import Path
        src = (Path(__file__).resolve().parents[1]
               / "services/agent/orchestrator.py").read_text(encoding="utf-8")
        self.assertIn("Translate into English", src)
        self.assertIn("THỰC HIỆN mệnh lệnh", src)


class GiuTronTinKhiLenhTrongTests(unittest.TestCase):
    """Mệnh lệnh trống tân ngữ thì phải đưa TRỌN tin cho model, không cắt.

    Lỗi thật 04/09 13:28 (chủ máy phát hiện): bot trả lời ngày âm lịch dài 445
    ký tự (ngày tháng + việc nên/tránh + giờ hoàng đạo), người dùng gõ "Dịch
    sang tiếng anh" thì bản dịch chỉ ra 129 ký tự — đúng MỘT câu đầu, hai đoạn
    sau mất sạch. Vì khối phỏng đoán cắt ứng viên ở 200 ký tự.

    Cắt là đúng khi đang ĐOÁN giữa nhiều tin (chỉ cần đủ nhận ra tin nào), nhưng
    sai khi model phải LÀM VIỆC TRÊN chính tin đó.
    """

    TIN = ("Hôm nay là Thứ Sáu, ngày 4 tháng 9 năm 2026 dương lịch, nhằm ngày 23 "
           "tháng 7 năm Bính Ngọ âm lịch. Đây là ngày Tân Tỵ, tháng Bính Thân, năm "
           "Bính Ngọ, đang tiết Xử thử, trực Thu.\n\nNên thu hoạch, cầu tài, nhập "
           "kho, mua sắm; nên tránh an táng, xuất hành xa và khởi sự lớn.\n\nGiờ "
           "hoàng đạo gồm: giờ Sửu từ 1 đến 3 giờ, giờ Thìn từ 7 đến 9 giờ, giờ Ngọ "
           "từ 11 đến 13 giờ, giờ Mùi từ 13 đến 15 giờ, giờ Tuất từ 19 đến 21 giờ "
           "và giờ Hợi từ 21 đến 23 giờ.")

    def _hist(self):
        return [{"role": "assistant", "content": self.TIN}]

    def test_giu_ca_doan_cuoi(self):
        from services.agent import tham_chieu as tc
        ra = tc.doan("u-test", "Dịch sang tiếng anh", self._hist())
        self.assertIn("giờ Hợi từ 21 đến 23 giờ", ra, "đoạn CUỐI bị cắt mất")

    def test_giu_du_ba_doan(self):
        from services.agent import tham_chieu as tc
        ra = tc.doan("u-test", "tóm tắt giúp anh", self._hist())
        for moc in ("Xử thử", "Nên thu hoạch", "Giờ hoàng đạo"):
            with self.subTest(moc=moc):
                self.assertIn(moc, ra)

    def test_cau_dai_tu_tro_van_cat_ngan(self):
        """Không nới đại trà: đoán giữa nhiều tin thì đoạn ngắn là đủ."""
        from services.agent import tham_chieu as tc
        ra = tc.doan("u-test", "cái này sao rồi", self._hist())
        self.assertLess(len(ra), 700, "nới cả nhánh đoán thì tốn token mỗi lượt")


class LenhTrongKhongCoNoiDungTests(unittest.TestCase):
    """Lệnh trống tân ngữ mà không tìm được tin nào → HỎI LẠI, đừng dịch câu lệnh.

    Zalo Bot 05/09: người dùng trích một THÔNG BÁO ADMIN ('ChatGPT free: …') rồi
    gõ 'Dịch sang tiếng anh'. Zalo Bot không gửi trích dẫn, và thông báo admin
    không nằm trong lịch sử hội thoại → không đoán được. Bot dịch CHÍNH câu lệnh:
    'Dịch sang tiếng anh' → 'Translate into English'. Guard bắt nó hỏi lại.
    """

    def test_khong_co_lich_su_thi_bao_hoi_lai(self):
        from services.agent import tham_chieu as tc
        r = tc.doan("u", "Dịch sang tiếng anh", [])
        self.assertIn("HỎI LẠI", r)
        self.assertIn("đừng dịch", r.lower())
        self.assertIn("Translate into English", r)   # nêu đúng cái KHÔNG được làm

    def test_co_tin_bot_thi_van_doan_nhu_cu(self):
        from services.agent import tham_chieu as tc
        r = tc.doan("u", "dịch sang tiếng anh",
                    [{"role": "assistant", "content": "Tin cháy ở Lê Quang Đạo"}])
        self.assertIn("Lê Quang Đạo", r)
        self.assertIn("PHỎNG ĐOÁN", r)

    def test_cau_thuong_van_rong(self):
        from services.agent import tham_chieu as tc
        self.assertEqual(tc.doan("u", "xin chào em", []), "")


if __name__ == "__main__":
    unittest.main()
