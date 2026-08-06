"""Tag bot xong thì bot chờ người đó gửi tiếp — áp cho cả ba kênh.

Chủ máy chốt 06/08: "khi user tag tên bot mà không có yêu cầu cụ thể thì cần chờ
đợi user gửi thông tin gì rồi mới phản hồi; gửi ảnh thì đưa ra các lựa chọn, gửi
file đưa ra các lựa chọn. Việc chờ phản hồi thực hiện trên TOÀN CỤC khi có việc
tag tên bot."

Cảnh có thật (máy chủ 06/08 11:43–11:45, nhóm Homeassistant):

    11:43:32  @BenBap             → bot chào
    11:43:49  [Hình ảnh]          → KHÔNG tag, bị cổng tag loại im lặng
    11:45:04  @BenBap mô tả ảnh   → bot chào tiếp, vì chẳng còn ảnh nào

Zalo không cho vừa tag vừa đính ảnh trong một tin, nên "tag trước, gửi ảnh sau"
là cách người ta buộc phải làm.
"""
import os
import sys
import time
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import cho_sau_tag as cst  # noqa: E402


class MoVaDongTests(unittest.TestCase):

    KHOA = "zalop:acc:nhom1:userA"

    def setUp(self):
        cst._reset_for_tests()

    def test_chua_tag_thi_khong_cho(self):
        self.assertFalse(cst.dang_cho(self.KHOA))

    def test_tag_roi_thi_dang_cho(self):
        cst.mo(self.KHOA)
        self.assertTrue(cst.dang_cho(self.KHOA))

    def test_het_han_thi_tro_lai_nep_phai_tag(self):
        """Không có hạn thì một lần tag mở cổng vĩnh viễn."""
        cst.mo(self.KHOA)
        cst._cho[self.KHOA] -= cst.TTL_S + 1
        self.assertFalse(cst.dang_cho(self.KHOA))

    def test_tag_lai_thi_gia_han(self):
        cst.mo(self.KHOA)
        cst._cho[self.KHOA] -= cst.TTL_S - 1
        cst.mo(self.KHOA)
        self.assertTrue(cst.dang_cho(self.KHOA))

    def test_dong_duoc_bang_tay(self):
        cst.mo(self.KHOA)
        cst.dong(self.KHOA)
        self.assertFalse(cst.dang_cho(self.KHOA))

    def test_khoa_rong_khong_lam_gi(self):
        cst.mo("")
        self.assertFalse(cst.dang_cho(""))


class ChoTheoTungNguoiTests(unittest.TestCase):
    """Chủ máy chốt 05/08: "chờ là chờ theo từng người chứ không phải chờ xong
    có người xen vào thành câu phản hồi được"."""

    A = "zalop:acc:nhom1:userA"
    B = "zalop:acc:nhom1:userB"

    def setUp(self):
        cst._reset_for_tests()

    def test_nguoi_khac_khong_di_ke(self):
        cst.mo(self.A)
        self.assertTrue(cst.dang_cho(self.A))
        self.assertFalse(cst.dang_cho(self.B), "B nói ké vào cửa sổ của A")

    def test_thread_khac_khong_di_ke(self):
        cst.mo(self.A)
        self.assertFalse(cst.dang_cho("zalop:acc:nhom2:userA"))

    def test_dong_cua_nguoi_nay_khong_dung_nguoi_kia(self):
        cst.mo(self.A)
        cst.mo(self.B)
        cst.dong(self.A)
        self.assertTrue(cst.dang_cho(self.B))


class DonHetHanTests(unittest.TestCase):

    def setUp(self):
        cst._reset_for_tests()

    def test_ban_ghi_qua_han_bi_don_khoi_bo_nho(self):
        cst.mo("cu")
        cst._cho["cu"] -= cst.TTL_S + 10
        cst.mo("moi")
        self.assertNotIn("cu", cst._cho, "bản ghi hết hạn nằm lại làm phình bộ nhớ")


class NoiVaoBaKenhTests(unittest.TestCase):
    """Chủ máy nói rõ "trên TOÀN CỤC" — thiếu kênh nào là kênh đó vẫn nuốt ảnh."""

    KENH = (("zalo_personal.py", "zalop"), ("telegram_bot.py", "tg"),
            ("zalo_bot.py", "zalo"))

    def _src(self, ten):
        return (GOC / "services" / ten).read_text("utf-8")

    def test_moi_kenh_deu_mo_cua_so_khi_bi_tag(self):
        for ten, _ in self.KENH:
            with self.subTest(ten=ten):
                self.assertIn("_cst.mo(", self._src(ten))

    def test_moi_kenh_deu_tra_cua_so_TRUOC_cong_chan(self):
        """Tra sau khi cổng đã loại tin thì tra để làm gì.

        Chỉ xét lời gọi tag_gate_allows THẬT SỰ CHẶN (`if _req and not …`) —
        Zalo Bot còn hai lời gọi khác chỉ để tính cờ `tagged`, không chặn ai.
        """
        for ten, _ in self.KENH:
            with self.subTest(ten=ten):
                src = self._src(ten)
                self.assertIn("_cst.dang_cho(", src)
                i_chan = src.index("if _req and not _caps.tag_gate_allows(")
                self.assertLess(src.index("_cst.dang_cho("), i_chan)

    def test_khoa_kem_NGUOI_GUI(self):
        """Thiếu người gửi là A tag bot rồi B nói gì trong nhóm cũng lọt."""
        for ten, tien_to in self.KENH:
            with self.subTest(ten=ten):
                src = self._src(ten)
                i = src.index("_cst.mo(")
                khoi = src[max(0, i - 500):i + 60]
                self.assertTrue(
                    "user_id" in khoi or "sender_id" in khoi or "pkey" in khoi,
                    f"{ten}: khoá cửa sổ chờ không kèm người gửi")

    def test_zalop_dung_lai_dung_khoa_theo_nguoi_da_co(self):
        """Đẻ khoá mới cạnh `pkey` là nguồn của lỗi lệch khoá đã gặp 05/08."""
        src = self._src("zalo_personal.py")
        self.assertIn("_cst.mo(pkey)", src)
        self.assertIn("{ev.get('sender_id') or ''}", src)


class BaKenhPhaiGIONG_NHAUTests(unittest.TestCase):
    """Chủ máy hỏi 06/08: "tele và zalo bot đã làm giống zalo cá nhân chưa".

    Lúc hỏi thì CHƯA: hai kênh kia thiếu ba ngoại lệ ở cổng tag. Hậu quả: cửa sổ
    sau-tag sống 5 phút còn bản chờ "chọn 1/2/3" sống 10 phút, nên đúng 5 phút
    giữa hai mốc đó người dùng bấm số mà không có gì xảy ra. Bài này chốt lại sự
    đồng đều để lần sau thêm ngoại lệ cho một kênh mà quên hai kênh kia thì đỏ.
    """

    KENH = ("zalo_personal.py", "telegram_bot.py", "zalo_bot.py")

    #: Việc nào cũng phải có ở CẢ BA kênh.
    CHUNG = (
        ("mở cửa sổ chờ khi bị tag", "_cst.mo("),
        ("tra cửa sổ chờ ở cổng tag", "_cst.dang_cho("),
        ("ngoại lệ: bot đang xin ảnh", "dang_cho_anh("),
        ("đánh dấu khi bot xin ảnh", "danh_dau_neu_xin_anh("),
        ("ngoại lệ: đang chờ chọn ảnh", "_phi_cho.has_pending("),
        ("ngoại lệ: đang chờ chọn tệp", "_pi_cho.has_pending("),
        ("hỏi lưu online khi nhận tệp", "_moi_luu_online("),
        ("đọc trả lời 1/2/3 của admin", "chon_tu_tra_loi("),
        ("mục «Lưu lên kho đám mây»", "them_luu_online("),
    )

    def _src(self, ten):
        return (GOC / "services" / ten).read_text("utf-8")

    def test_ba_kenh_deu_co_du_cac_viec_chung(self):
        for ten in self.KENH:
            src = self._src(ten)
            for nhan, dau in self.CHUNG:
                with self.subTest(kenh=ten, viec=nhan):
                    self.assertIn(dau, src, f"{ten} thiếu: {nhan}")

    def test_ngoai_le_ban_cho_dung_khoa_KEM_NGUOI(self):
        """Khoá thiếu người gửi thì A gửi tệp, B bấm "1" là cướp mất lượt của A."""
        for ten, tien_to in (("telegram_bot.py", "tg"), ("zalo_bot.py", "zalo")):
            with self.subTest(kenh=ten):
                src = self._src(ten)
                self.assertIn(
                    '_ckey = f"' + tien_to + ':{_bot_id()}:{chat_id}:'
                    "{user_id or ''}\"", src)
                # Ngoại lệ phải tra bằng CHÍNH khoá đó, không tự dựng khoá khác.
                self.assertIn("_phi_cho.has_pending(_ckey)", src)
                self.assertIn("_pi_cho.has_pending(_ckey)", src)

    def test_hai_viec_chi_co_o_kenh_gui_duoc_tep(self):
        """Zalo Bot không gửi được Word/Excel nên không có gì để hỏi sau đó."""
        for ten in ("zalo_personal.py", "telegram_bot.py"):
            with self.subTest(kenh=ten):
                src = self._src(ten)
                self.assertIn("moi_luu_sau_chuyen_doi(", src)
                self.assertIn("moi_luu_tom_tat(", src)
        self.assertNotIn("moi_luu_sau_chuyen_doi(", self._src("zalo_bot.py"))


if __name__ == "__main__":
    unittest.main()
