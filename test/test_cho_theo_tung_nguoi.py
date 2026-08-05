"""Bot chờ trả lời thì chờ theo TỪNG NGƯỜI, và tag bot không tính là đã nói gì.

Hai lỗi đo thật ngày 05/08 trên nhóm Zalo cá nhân:

1. Khoá chờ chỉ tới thread. Trong nhóm, A gửi ảnh rồi bot hỏi "muốn làm gì", B
   nói câu bất kỳ là câu đó bị nhận làm trả lời của A — B cướp mất lượt mà không
   ai biết, còn A trả lời sau thì bản chờ đã bị lấy đi.
2. Lời kèm ảnh giữ nguyên chuỗi tag '@TenBot' nên không bao giờ rỗng, khiến
   nhánh "chưa nói gì → hiện menu" không bao giờ chạy. Chủ máy tag bot rồi gửi
   ảnh suông thì bị đoán bừa thành «phân tích ảnh», và hệ thống gửi lên model
   đúng một chuỗi "@Botmitbap" làm yêu cầu.
"""
import os
import re
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class BoTagTests(unittest.TestCase):

    def setUp(self):
        from services import photo_intent as phi
        self.phi = phi

    def test_chi_tag_khong_noi_gi_thi_con_rong(self):
        """Rỗng chính là tín hiệu để hiện menu lựa chọn."""
        for xau in ("@BenBap", "  @Botmitbap  ", "@BenBap @Botmitbap"):
            with self.subTest(xau=xau):
                self.assertEqual(self.phi.bo_tag(xau), "")

    def test_tag_kem_yeu_cau_thi_giu_lai_yeu_cau(self):
        self.assertEqual(self.phi.bo_tag("@BenBap phân tích ảnh"), "phân tích ảnh")
        self.assertEqual(self.phi.bo_tag("nạp rag kiến thức @BenBap"), "nạp rag kiến thức")

    def test_khong_tag_thi_giu_nguyen(self):
        self.assertEqual(self.phi.bo_tag("tóm tắt giúp em"), "tóm tắt giúp em")

    def test_rong_hoac_none_thi_ra_rong(self):
        self.assertEqual(self.phi.bo_tag(""), "")
        self.assertEqual(self.phi.bo_tag(None), "")


class KhoaChoTheoNguoiTests(unittest.TestCase):
    """Đọc thẳng mã nguồn: khoá chờ phải kèm người gửi, không chỉ thread."""

    #: (tệp nguồn, tên biến chat, tên biến người gửi) — cả BA kênh phải giống nhau.
    KENH = (
        ("zalo_personal.py", "thread_id", "sender_id"),
        ("telegram_bot.py", "chat_id", "user_id"),
        ("zalo_bot.py", "chat_id", "user_id"),
    )

    def _dong_khoa(self, tep: str) -> str:
        src = (GOC / "services" / tep).read_text("utf-8")
        m = re.search(r"^\s*_?pkey = f\".+$", src, re.M)
        self.assertIsNotNone(m, f"không tìm thấy chỗ dựng khoá chờ trong {tep}")
        return m.group(0)

    def test_khoa_cho_kem_nguoi_gui(self):
        for tep, _chat, nguoi in self.KENH:
            with self.subTest(tep=tep):
                self.assertIn(nguoi, self._dong_khoa(tep),
                              f"{tep}: khoá chờ thiếu người gửi — người khác "
                              "xen vào là cướp được lượt")

    def test_khoa_cho_van_kem_chat(self):
        """Bỏ chat đi thì hai nhóm khác nhau của cùng một người sẽ lẫn bản chờ."""
        for tep, chat, _nguoi in self.KENH:
            with self.subTest(tep=tep):
                self.assertIn(chat, self._dong_khoa(tep))


class NhanhHienMenuTests(unittest.TestCase):
    """Nhánh 'chưa nói gì → hiện menu' phải xét lời kèm ĐÃ BÓC TAG."""

    def test_caption_boc_tag_truoc_khi_xet_rong(self):
        src = (GOC / "services" / "zalo_personal.py").read_text("utf-8")
        # Neo vào đúng nhánh ẢNH VỪA TỚI (chỗ dựng bản chờ đầu tiên), không phải
        # nhánh xử lý bản chờ đã có ở phía trên.
        i = src.index("_phi.set_pending(pkey, data)")
        truoc = src[max(0, i - 700):i]
        self.assertIn("bo_tag", truoc,
                      "lời kèm ảnh chưa bóc tag — nhánh hiện menu sẽ không bao giờ chạy")


if __name__ == "__main__":
    unittest.main()
