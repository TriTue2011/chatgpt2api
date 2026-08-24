"""Tiêu đề mục model viết chữ trơn thì bot tự làm nổi — không phụ thuộc màu.

Yêu cầu 24/08/2026: "kể cả không tô màu nhưng những tiêu đề nổi bật vẫn in đậm
hoặc in nghiêng tùy vào phản hồi".

Model chia câu trả lời dài thành mục bằng một dòng ngắn có emoji hoặc kết thúc
bằng dấu hai chấm, nhưng viết CHỮ TRƠN. Bộ chuyển sang định dạng Zalo/Telegram
chỉ tô thứ đã được đánh dấu, nên mấy dòng đó tới nơi phẳng lì như phần thân.
Đo thật trên tin bão Narra gửi 09:58 cùng ngày: bốn dòng tiêu đề đều chữ trơn.

Đậm hay nghiêng tuỳ loại dòng: tiêu đề mục là cấu trúc → đậm; dòng ghi chú /
nguồn là phần phụ → nghiêng.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth-key")

from services.telegram.emphasis import emphasize_text  # noqa: E402
from services.zalo_markdown import markdown_to_zalo_message  # noqa: E402

BAT = {"enabled": True, "numbers": True, "units": True, "key_info": True,
       "style": "bold"}


def _nhan(text: str, **doi) -> str:
    return emphasize_text(text, settings={**BAT, **doi})


class TieuDeThanhDamTests(unittest.TestCase):
    def test_dong_mo_dau_bang_emoji(self):
        ra = _nhan("🌧️ Ảnh hưởng chính hiện nay:\nMưa lớn ở Đông Bắc Bộ.")
        self.assertIn("**🌧️ Ảnh hưởng chính hiện nay:**", ra)
        self.assertNotIn("**Mưa lớn", ra, "thân bài không được đậm")

    def test_dong_ket_thuc_bang_hai_cham(self):
        ra = _nhan("Dự báo tiếp theo:\nBão đi chậm.")
        self.assertIn("**Dự báo tiếp theo:**", ra)

    def test_cau_van_dai_ket_thuc_hai_cham_thi_khong_dam(self):
        """Dài là câu văn dẫn dắt, không phải tiêu đề."""
        dai = ("Các chuyên gia khí tượng vừa đưa ra nhận định mới nhất về hướng "
               "đi của cơn bão trong những giờ tới như sau:")
        self.assertNotIn("**", _nhan(dai + "\nNội dung."))

    def test_muc_danh_sach_khong_bi_dam_ca_dong(self):
        """Bọc cả dòng sẽ nuốt dấu đầu dòng, làm vỡ danh sách."""
        ra = _nhan("- Quảng Ninh:\n- Hải Phòng:")
        self.assertNotIn("**- ", ra)

    def test_dong_danh_so_khong_bi_dam_ca_dong(self):
        ra = _nhan("1. Bước một:\n2. Bước hai:")
        self.assertNotIn("**1.", ra)


class GhiChuThanhNghiengTests(unittest.TestCase):
    def test_luu_y_thanh_nghieng_chu_khong_dam(self):
        ra = _nhan("Lưu ý: mưa lớn vẫn còn.")
        self.assertIn("*Lưu ý: mưa lớn vẫn còn.*", ra)
        self.assertNotIn("**Lưu ý", ra)

    def test_nguon_cung_nghieng(self):
        self.assertIn("*Nguồn: VnExpress*", _nhan("Nguồn: VnExpress"))


class KhongDungVaoChoKhacTests(unittest.TestCase):
    def test_trong_khoi_code_giu_nguyen(self):
        goc = "Chạy:\n```bash\ncd /app:\nls\n```"
        ra = _nhan(goc)
        self.assertIn("cd /app:", ra)
        self.assertNotIn("**cd /app:**", ra)

    def test_tieu_de_da_dam_san_khong_boc_hai_lan(self):
        ra = _nhan("**Dự báo tiếp theo:**\nNội dung.")
        self.assertNotIn("****", ra)

    def test_so_lieu_trong_tieu_de_khong_bi_boc_long_nhau(self):
        """Lồng `**` là cách chắc chắn để bộ chuyển đọc lệch."""
        ra = _nhan("📍 Dự báo 24 giờ tới:\nGió cấp 9.")
        self.assertNotIn("****", ra)
        self.assertIn("**📍 Dự báo 24 giờ tới:**", ra)

    def test_tat_nhan_manh_y_chinh_thi_thoi(self):
        ra = _nhan("📍 Dự báo tiếp theo:\nNội dung.", key_info=False)
        self.assertNotIn("**📍", ra)


class KhongPhuThuocMauTests(unittest.TestCase):
    """Chốt chính của yêu cầu: tắt màu thì vẫn còn đậm/nghiêng."""

    GOC = ("🌧️ Ảnh hưởng chính hiện nay:\nMưa lớn ở Đông Bắc Bộ.\n"
           "Lưu ý: còn ngập úng.")

    def _kieu(self, mau: str) -> list[str]:
        ra = markdown_to_zalo_message(_nhan(self.GOC), color=mau, size="normal")
        return [s["st"] for s in ra["styles"]]

    def test_tat_mau_van_con_dam_va_nghieng(self):
        kieu = self._kieu("none")
        self.assertIn("b", kieu, "tắt màu là mất luôn in đậm")
        self.assertIn("i", kieu)
        self.assertFalse([k for k in kieu if "c_" in k], "đã tắt mà vẫn tô màu")

    def test_bat_mau_thi_dam_di_kem_mau(self):
        kieu = self._kieu("orange")
        self.assertTrue(any("c_f27806" in k and "b" in k.split(",") for k in kieu))

    def test_vung_dinh_dang_trum_dung_dong_tieu_de(self):
        ra = markdown_to_zalo_message(_nhan(self.GOC), color="none", size="normal")
        u16 = ra["msg"].encode("utf-16-le")
        dam = next(s for s in ra["styles"] if s["st"] == "b")
        doan = u16[dam["start"] * 2:(dam["start"] + dam["len"]) * 2].decode("utf-16-le")
        self.assertEqual(doan, "🌧️ Ảnh hưởng chính hiện nay:")


class KhongAnSangDongSauTests(unittest.TestCase):
    r"""Lỗi có sẵn: dòng kết thúc bằng ':' ăn luôn DÒNG SAU làm "giá trị".

    `_KEY_VALUE` dùng `\s*` quanh dấu hai chấm, mà `\s` nuốt cả dấu xuống dòng.
    Đo thật 24/08/2026: "- Quảng Ninh:\n- Hải Phòng:" ra
    "- Quảng Ninh:\n**- Hải Phòng:**" — đậm sai dòng và nuốt dấu đầu dòng. Câu
    trả lời chia mục thì mục nào cũng dính, vì tiêu đề mục nào cũng kết thúc
    bằng dấu hai chấm.
    """

    def test_tieu_de_khong_keo_dong_than_bai_vao(self):
        ra = _nhan("Ảnh hưởng chính hiện nay:\nMưa lớn ở Đông Bắc Bộ.")
        self.assertNotIn("**Mưa lớn ở Đông Bắc Bộ.**", ra)

    def test_nhan_gia_tri_cung_dong_van_duoc_dam_nhu_cu(self):
        """Đúng công dụng ban đầu của luật này thì phải giữ."""
        self.assertIn("**28°C**", _nhan("Nhiệt độ: 28°C"))



class TelegramCungHieuNghiengTests(unittest.TestCase):
    """Dòng ghi chú in nghiêng phải hiện đúng trên CẢ Telegram.

    Đường "rich message" của Telegram dựng entity riêng và bản cũ chỉ biết
    `**đậm**` với `` `mã` `` — thiếu nhánh nghiêng thì người dùng Telegram nhận
    nguyên hai dấu sao quanh câu ghi chú.
    """

    def _spans(self, text: str):
        from services.telegram.rich import _inline_rich_text
        return _inline_rich_text(text)

    def test_nghieng_thanh_entity_chu_khong_lot_dau_sao(self):
        ra = self._spans("*Lưu ý: mưa lớn.*")
        self.assertEqual(ra, [{"type": "italic", "text": "Lưu ý: mưa lớn."}])

    def test_dam_van_dung_khi_di_chung_voi_nghieng(self):
        ra = self._spans("Có **đậm** và *nghiêng*")
        kieu = [p["type"] for p in ra if isinstance(p, dict)]
        self.assertEqual(kieu, ["bold", "italic"])

    def test_chu_thuong_van_tra_ve_chuoi_khong_boc_gi(self):
        self.assertEqual(self._spans("Bình thường"), "Bình thường")

if __name__ == "__main__":
    unittest.main()
