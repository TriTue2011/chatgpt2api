"""Đường tắt phải TÔN TRỌNG sở thích trình bày người dùng đã dặn.

Sở thích ghi nhớ được tiêm vào system prompt, nên mọi lượt DO MODEL trả lời đều
tôn trọng nó. Nhưng các đường tắt (tin tức, lấy media, nhà thông minh) trả về
TRƯỚC KHI model được gọi — chúng bỏ qua sạch mọi thứ người dùng đã dặn.

Hệ quả không nằm riêng ở tin tức: bất kỳ yêu cầu "đổi cách phản hồi" nào cũng bị
đường tắt vô hiệu hoá, mà bot vẫn "ghi nhớ" rồi hứa. Đo thật 01/08: lượt 08:11
bot lưu đúng yêu cầu chia mục, người dùng duyệt, rồi lượt sau vẫn trả danh sách
phẳng. Ghi nhớ một điều mình không làm được thì tệ hơn không nhớ, vì người dùng
tin là xong.

File này khoá ba hành vi:
  * nhận đúng dòng nào là SỞ THÍCH TRÌNH BÀY, bỏ qua dữ kiện thường;
  * nhận cả khi người dùng gõ KHÔNG DẤU;
  * không có sở thích nào thì trả nguyên văn, KHÔNG gọi model (không tốn lượt).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.agent import orchestrator as orch
from services.agent import state

_N = "\n"


def _voi_tri_nho(mem: str):
    return patch.object(state, "load_memory", return_value=mem)


class TestNhanDangSoThich(unittest.TestCase):
    def test_bo_qua_du_kien_thuong(self):
        """Tên, địa chỉ, mật khẩu KHÔNG phải sở thích trình bày — lọt vào là
        nhét thông tin riêng vào prompt diễn đạt một cách vô ích."""
        mem = _N.join(["- Anh tên là Việt, ở Hà Nội.",
                       "- Mật khẩu wifi là 12345678.",
                       "- Con trai học lớp 2."])
        with _voi_tri_nho(mem):
            self.assertEqual(orch._so_thich_trinh_bay(), [])

    def test_nhan_so_thich_co_dau(self):
        with _voi_tri_nho("- Trả lời ngắn gọn thôi, đừng dài dòng."):
            self.assertEqual(len(orch._so_thich_trinh_bay()), 1)

    def test_nhan_so_thich_khong_dau(self):
        """Người dùng gõ nhanh không dấu là chuyện thường."""
        with _voi_tri_nho("- Khi hoi tin tuc thi chia cac muc, khong link."):
            self.assertEqual(len(orch._so_thich_trinh_bay()), 1)

    def test_bo_dong_qua_ngan(self):
        with _voi_tri_nho(_N.join(["- x", "- trình bày", "-"])):
            for d in orch._so_thich_trinh_bay():
                self.assertGreaterEqual(len(d), 8)

    def test_chi_lay_may_dong_gan_nhat(self):
        mem = _N.join([f"- Trình bày kiểu số {i} cho gọn." for i in range(20)])
        with _voi_tri_nho(mem):
            ra = orch._so_thich_trinh_bay(limit=3)
        self.assertEqual(len(ra), 3)
        self.assertIn("số 19", ra[-1])       # gần nhất ở cuối

    def test_tri_nho_loi_thi_khong_vo(self):
        with patch.object(state, "load_memory", side_effect=OSError("đọc lỗi")):
            self.assertEqual(orch._so_thich_trinh_bay(), [])


class TestApSoThich(unittest.TestCase):
    GOC = "1. Tin một — tóm tắt một.\n2. Tin hai — tóm tắt hai."

    def test_khong_co_so_thich_thi_khong_goi_model(self):
        goi = []
        with _voi_tri_nho("- Anh tên là Việt."), \
             patch.object(orch, "call_model", side_effect=lambda *a, **k: goi.append(1)):
            ra = orch._ap_so_thich(self.GOC, "tin tức hôm nay", lambda k: "m")
        self.assertEqual(ra, self.GOC)
        self.assertEqual(goi, [], "không có sở thích mà vẫn gọi model = tốn lượt vô ích")

    def test_van_ban_rong_thi_tra_ngay(self):
        with _voi_tri_nho("- Trình bày ngắn gọn giúp anh."):
            self.assertEqual(orch._ap_so_thich("", "hỏi gì", lambda k: "m"), "")

    def test_model_loi_thi_giu_ban_goc(self):
        with _voi_tri_nho("- Trình bày ngắn gọn giúp anh."), \
             patch.object(orch, "call_model", return_value={"error": "hỏng"}):
            self.assertEqual(
                orch._ap_so_thich(self.GOC, "tin tức", lambda k: "m"), self.GOC)

    def test_ban_moi_ngan_bat_thuong_thi_giu_ban_goc(self):
        """Chốt chống MẤT TIN: model diễn đạt lại có thể lược bớt. Ngắn hơn một
        nửa thì coi như hỏng — thà trình bày chưa đúng ý hơn là mất tin."""
        with _voi_tri_nho("- Trình bày ngắn gọn giúp anh."), \
             patch.object(orch, "call_model",
                          return_value={"choices": [{"message": {"content": "ok"}}]}):
            self.assertEqual(
                orch._ap_so_thich(self.GOC, "tin tức", lambda k: "m"), self.GOC)

    def test_ban_moi_du_dai_thi_dung_ban_moi(self):
        moi = ("**Thể thao**\n- Tin một: tóm tắt một.\n"
               "**Kinh tế**\n- Tin hai: tóm tắt hai.")
        with _voi_tri_nho("- Chia các mục giúp anh, không cần link."), \
             patch.object(orch, "call_model",
                          return_value={"choices": [{"message": {"content": moi}}]}):
            self.assertEqual(
                orch._ap_so_thich(self.GOC, "tin tức", lambda k: "m"), moi)


class TestBoDau(unittest.TestCase):
    def test_bo_dau_tieng_viet(self):
        self.assertEqual(orch._bo_dau("Trình Bày Ngắn Gọn"), "trinh bay ngan gon")

    def test_chu_d_gach_ngang(self):
        self.assertEqual(orch._bo_dau("đừng dài dòng"), "dung dai dong")


if __name__ == "__main__":
    unittest.main()
