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

    def test_mat_sach_noi_dung_thi_giu_ban_goc(self):
        """Model trả về một chữ "ok" = mất sạch. Phải giữ bản gốc."""
        with _voi_tri_nho("- Trình bày ngắn gọn giúp anh."), \
             patch.object(orch, "call_model",
                          return_value={"choices": [{"message": {"content": "ok"}}]}):
            self.assertEqual(
                orch._ap_so_thich(self.GOC, "tin tức", lambda k: "m"), self.GOC)

    def test_giu_du_noi_dung_thi_dung_ban_moi(self):
        """Bày lại mà giữ nguyên hai tin → dùng bản mới."""
        moi = ("**Thể thao**\n- Tin một — tóm tắt một.\n"
               "**Kinh tế**\n- Tin hai — tóm tắt hai.")
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


class TestChotMatTin(unittest.TestCase):
    """Chốt an toàn phải đo MẤT TIN, không đo độ dài.

    Bản đầu tôi chặn theo độ dài ("ngắn hơn một nửa thì bỏ") và nó chặn OAN đúng
    thứ người dùng xin: đo thật 01/08, bản tin có tóm tắt 4762 ký tự, bỏ tóm tắt
    còn 1718 — dưới ngưỡng 2381 nên yêu cầu "bỏ tóm tắt đi" bị vô hiệu hoá trong
    im lặng. Rút gọn là việc HỢP LỆ; mất tin mới là lỗi.
    """

    GOC = ("**⚽ Thể thao**\n"
           "- **Đình Bắc nói về trận Singapore** — Tiền đạo thừa nhận chơi tệ.\n"
           "- **Lịch thi đấu bảng B ASEAN Cup** — Thái Lan gặp Malaysia lúc 20h.\n"
           "\n**💼 Kinh tế**\n"
           "- **Giá vàng thế giới giảm mạnh** — Mất 61,5 USD một ounce.\n"
           "- **SCG tăng doanh thu ở Việt Nam** — Đạt 37.120 tỷ đồng nửa đầu năm.")

    def _chay(self, moi: str) -> str:
        with _voi_tri_nho("- Bỏ tóm tắt đi, chỉ ghi tiêu đề."), \
             patch.object(orch, "call_model",
                          return_value={"choices": [{"message": {"content": moi}}]}):
            return orch._ap_so_thich(self.GOC, "tin tức hôm nay", lambda k: "m")

    def test_bo_tom_tat_thi_CHO_QUA(self):
        """Việc người dùng vừa xin — ngắn đi nhiều nhưng giữ đủ tiêu đề."""
        moi = ("**⚽ Thể thao**\n- **Đình Bắc nói về trận Singapore**\n"
               "- **Lịch thi đấu bảng B ASEAN Cup**\n"
               "\n**💼 Kinh tế**\n- **Giá vàng thế giới giảm mạnh**\n"
               "- **SCG tăng doanh thu ở Việt Nam**")
        self.assertEqual(self._chay(moi), moi)

    def test_mat_bot_tin_thi_CHAN(self):
        moi = "**⚽ Thể thao**\n- **Đình Bắc nói về trận Singapore**"
        self.assertEqual(self._chay(moi), self.GOC)

    def test_ban_mau_rong_thi_CHAN(self):
        """Đúng thứ bot đã trả lời lúc 08:33 — mẫu có chỗ trống, không tin nào."""
        moi = "Thể thao\n- Tin 1\n- Tin 2\n- Tin 3\n\nKinh tế\n- Tin 1\n- Tin 2"
        self.assertEqual(self._chay(moi), self.GOC)

    def test_neo_lay_tu_tieu_de_in_dam(self):
        neo = orch._neo_noi_dung(self.GOC)
        self.assertIn("Đình Bắc nói về trận Singapore", neo)
        self.assertTrue(all(len(n) <= 40 for n in neo))

    def test_van_ban_mot_khoi_thi_neo_theo_dong(self):
        """Không có `**…**` thì lấy từng dòng, để vẫn có gì mà đối chiếu."""
        neo = orch._neo_noi_dung("Dòng thứ nhất khá dài.\nDòng thứ hai cũng vậy.")
        self.assertEqual(len(neo), 2)


class TestTranDoDai(unittest.TestCase):
    """Văn bản dài thì KHÔNG nhờ model bày lại.

    Đo thật 01/08: bản tin 4819 ký tự không kịp xong trong hạn 20 giây, hết giờ
    100% số lần rồi rơi về bản gốc — tốn 20 giây chờ để nhận đúng thứ cũ. Nội
    dung dài phải định dạng bằng code ở nơi sinh ra nó.
    """

    def test_qua_dai_thi_khong_goi_model(self):
        goi = []
        with _voi_tri_nho("- Trình bày ngắn gọn giúp anh."), \
             patch.object(orch, "call_model", side_effect=lambda *a, **k: goi.append(1)):
            goc = "x" * (orch._TRAN_BAY_LAI + 1)
            self.assertEqual(orch._ap_so_thich(goc, "hỏi gì", lambda k: "m"), goc)
        self.assertEqual(goi, [], "văn bản quá dài mà vẫn gọi model = chờ vô ích")

    def test_du_ngan_thi_van_bay_lai(self):
        moi = "Bản đã bày lại, giữ nguyên nội dung gốc bên trong."
        with _voi_tri_nho("- Trình bày ngắn gọn giúp anh."), \
             patch.object(orch, "call_model",
                          return_value={"choices": [{"message": {"content": moi}}]}):
            ra = orch._ap_so_thich("nội dung gốc", "hỏi gì", lambda k: "m")
        self.assertEqual(ra, moi)


class TestDichTieuDeTiengAnh(unittest.TestCase):
    """Người dùng dặn 01/08: "có nguồn tiếng anh nhưng chuyển sang tiếng việt".

    Bản tin lấy từ nhiều báo; BBC News và World Monitor trả tiêu đề tiếng Anh —
    đo thật: 4 trong 24 tin. Chỉ dịch ĐÚNG mấy tiêu đề đó, không đưa cả bản tin
    cho model: bài học từ lần trước, gửi cả 4819 ký tự thì model hết giờ 100% số
    lần và tốn 20 giây vô ích.
    """

    ANH = ("**⚽ Thể thao**\n"
           "- **Đội tuyển Việt Nam hòa Singapore**\n"
           "- **Snapchat joins fight against AI slop**\n")

    def test_toan_tieng_viet_thi_KHONG_goi_model(self):
        goi = []
        with patch.object(orch, "call_model", side_effect=lambda *a, **k: goi.append(1)):
            viet = "**⚽ Thể thao**\n- **Đội tuyển Việt Nam hòa Singapore**\n"
            self.assertEqual(orch._dich_tieu_de_tieng_anh(viet, lambda k: "m"), viet)
        self.assertEqual(goi, [], "không có tiêu đề tiếng Anh mà vẫn gọi model")

    def test_thay_dung_tieu_de_tieng_anh(self):
        with patch.object(orch, "call_model", return_value={"choices": [{"message": {
                "content": "1. Snapchat tham gia cuộc chiến chống rác AI"}}]}):
            ra = orch._dich_tieu_de_tieng_anh(self.ANH, lambda k: "m")
        self.assertIn("Snapchat tham gia cuộc chiến chống rác AI", ra)
        self.assertNotIn("joins fight against", ra)
        self.assertIn("Đội tuyển Việt Nam hòa Singapore", ra, "không được đụng dòng tiếng Việt")

    def test_lech_so_dong_thi_giu_ban_goc(self):
        """Model trả sai số dòng → không biết dòng nào ứng dòng nào, giữ bản gốc
        thay vì ghép lệch tiêu đề sang tin khác."""
        with patch.object(orch, "call_model", return_value={"choices": [{"message": {
                "content": "1. Một\n2. Hai\n3. Ba"}}]}):
            self.assertEqual(orch._dich_tieu_de_tieng_anh(self.ANH, lambda k: "m"), self.ANH)

    def test_model_loi_thi_giu_ban_goc(self):
        with patch.object(orch, "call_model", return_value={"error": "hỏng"}):
            self.assertEqual(orch._dich_tieu_de_tieng_anh(self.ANH, lambda k: "m"), self.ANH)

    def test_ban_dich_van_khong_dau_thi_bo_qua(self):
        """Model "dịch" mà vẫn ra tiếng Anh → không thay, kẻo đổi vô nghĩa."""
        with patch.object(orch, "call_model", return_value={"choices": [{"message": {
                "content": "1. Snapchat joins the fight"}}]}):
            ra = orch._dich_tieu_de_tieng_anh(self.ANH, lambda k: "m")
        self.assertIn("Snapchat joins fight against AI slop", ra)


class TestDangBayTinTheoThuTuMoiCu(unittest.TestCase):
    """Lời dặn NGƯỢC NHAU về cùng một mặt: dòng MỚI NHẤT phải thắng.

    Đo thật 01/08: 10:13 người dùng dặn "không in đậm, không emoji rườm rà";
    10:16 đổi ý "bổ sung icon các đầu mục, đầu mục tô màu và in đậm". Bản đầu dò
    bằng `any()` trên toàn bộ lời dặn gộp lại nên cụm phủ định của dòng CŨ luôn
    thắng — người dùng đổi ý mà bản tin không đổi.
    """

    CU = ("Khi hỏi Tin tức hôm nay: không in đậm, không emoji rườm rà, "
          "không tóm tắt, không link.")
    MOI = ("Khi hỏi Tin tức hôm nay: mỗi đầu mục có icon, tên mục tô màu và "
           "in đậm; không tóm tắt, không link.")

    def _dang(self, ds: list[str]) -> dict:
        with patch.object(orch, "_so_thich_trinh_bay", return_value=ds):
            return orch._dang_bay_tin()

    def test_dong_moi_thang_dong_cu(self):
        self.assertEqual(self._dang([self.CU, self.MOI]),
                         {"tom_tat": False, "in_dam": True, "emoji": True})

    def test_dao_thu_tu_thi_dao_ket_qua(self):
        """Chứng minh thứ tự THẬT SỰ được dùng, không phải trùng hợp."""
        self.assertEqual(self._dang([self.MOI, self.CU]),
                         {"tom_tat": False, "in_dam": False, "emoji": False})

    def test_mat_khong_ai_noi_toi_thi_giu_mac_dinh(self):
        self.assertEqual(self._dang(["Anh tên là Việt, ở Hà Nội."]),
                         {"tom_tat": True, "in_dam": True, "emoji": True})

    def test_khong_co_loi_dan_nao(self):
        self.assertEqual(self._dang([]),
                         {"tom_tat": True, "in_dam": True, "emoji": True})

    def test_moi_mat_xet_doc_lap(self):
        """Dòng mới chỉ nói về emoji thì KHÔNG được đổi luôn mặt in đậm."""
        ds = [self.CU, "Khi hỏi tin tức thì thêm icon cho các đầu mục nhé."]
        ra = self._dang(ds)
        self.assertTrue(ra["emoji"], "emoji phải theo dòng mới")
        self.assertFalse(ra["in_dam"], "in đậm chưa ai đổi thì vẫn theo dòng cũ")


if __name__ == "__main__":
    unittest.main()
