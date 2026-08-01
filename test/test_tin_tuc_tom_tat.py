"""Bản tin phải là CHỮ ĐỌC ĐƯỢC, không phải thẻ HTML của RSS.

RSS báo Việt nhồi ảnh đại diện vào ô mô tả dưới dạng
``<a href="…"><img src="…"></a>`` rồi mới tới câu tóm tắt. Bản cũ nhét ô đó
NGUYÊN XI vào bản tin và cắt ở 300 ký tự — riêng cái thẻ ảnh đã ăn hết chỗ, nên
câu tóm tắt thật KHÔNG BAO GIỜ xuất hiện. Người dùng phản hồi đúng hiện tượng:
"trình bày xấu, không có tóm tắt, tôi không cần link".

Hai thứ nữa được khoá ở đây, đều đo trên đường gửi thật:
  * KHÔNG dán URL trần — dài hơn cả câu tóm tắt, kênh chat không rút gọn nó;
  * KHÔNG dùng ``_nghiêng_`` — bộ chuyển markdown→Zalo chỉ hiểu ``**đậm**``, nên
    gạch dưới đi qua nguyên xi và người dùng thấy ``_VnExpress_`` kèm hai dấu.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HUB = Path(__file__).resolve().parents[1] / "vn-mcp-hub"
if str(_HUB) not in sys.path:
    sys.path.insert(0, str(_HUB))

try:
    from src.vn import news
except Exception as _exc:            # thiếu feedparser/fastmcp ở môi trường test
    news = None
    _LY_DO = str(_exc)


@unittest.skipIf(news is None, "vn-mcp-hub chưa cài phụ thuộc trong môi trường này")
class TestBocHtmlKhoiTomTat(unittest.TestCase):
    # Đúng dạng thật của VnExpress, đo 01/08.
    RSS_THAT = ('<a href="https://vnexpress.net/eu-chi-10-ty-euro-5103526.html">'
                '<img src="https://i1-vnexpress.vnecdn.net/2026/08/01/x.jpg?w=1200&amp;h=0"'
                ' alt="EU"></a>Liên minh châu Âu sẽ tài trợ 10 tỷ euro.')

    def test_bo_het_the_html(self):
        ra = news._lam_sach_tom_tat(self.RSS_THAT)
        for rac in ("<a ", "<img", "href=", "src=", ">"):
            self.assertNotIn(rac, ra, f"còn sót {rac!r}")

    def test_giu_duoc_cau_tom_tat_that(self):
        """Cái quan trọng nhất: câu tóm tắt phải SỐNG SÓT qua việc bóc thẻ."""
        ra = news._lam_sach_tom_tat(self.RSS_THAT)
        self.assertIn("Liên minh châu Âu sẽ tài trợ 10 tỷ euro.", ra)

    def test_giai_ma_thuc_the_html(self):
        self.assertEqual(news._lam_sach_tom_tat("Anh &amp; em &lt;3"), "Anh & em <3")

    def test_gom_khoang_trang_thua(self):
        ra = news._lam_sach_tom_tat("<p>Một</p>\n\n  <p>hai</p>")
        self.assertEqual(ra, "Một hai")

    def test_cat_dai_khong_dut_giua_tu(self):
        """Trần 12 ký tự rơi vào giữa chữ 'bon' → phải lùi về hết chữ 'ba',
        không được để lại mảnh 'b'."""
        ra = news._lam_sach_tom_tat("mot hai ba bon nam sau bay", tran=12)
        self.assertEqual(ra, "mot hai ba…")

    def test_rong_thi_tra_rong(self):
        self.assertEqual(news._lam_sach_tom_tat(""), "")
        self.assertEqual(news._lam_sach_tom_tat("<img src='x'>"), "")


@unittest.skipIf(news is None, "vn-mcp-hub chưa cài phụ thuộc trong môi trường này")
class TestDinhDangBanTin(unittest.TestCase):
    ITEMS = [{"source": "VnExpress", "title": "Tin một",
              "summary": "Tóm tắt một.",
              "link": "https://vnexpress.net/tin-mot.html"},
             {"source": "Tuoi Tre", "title": "Tin hai",
              "summary": "", "link": "https://tuoitre.vn/tin-hai.htm"}]

    def test_khong_dan_url_tran(self):
        ra = news._format_items(list(self.ITEMS), 2)
        self.assertNotIn("http", ra)

    def test_khong_dung_gach_duoi_nghieng(self):
        """`_nghiêng_` không được Zalo chuyển → hiện nguyên dấu."""
        ra = news._format_items(list(self.ITEMS), 2)
        self.assertNotIn("_VnExpress_", ra)
        self.assertIn("VnExpress", ra)

    def test_co_tom_tat_khi_co_du_lieu(self):
        ra = news._format_items(list(self.ITEMS), 2)
        self.assertIn("Tóm tắt một.", ra)

    def test_thieu_tom_tat_thi_khong_de_dong_trong(self):
        """Tin không có mô tả thì bỏ hẳn dòng tóm tắt, không in dòng rỗng."""
        ra = news._format_items([dict(self.ITEMS[1])], 1)
        self.assertNotIn("\n   \n", ra)
        self.assertFalse(ra.rstrip().endswith("\n"))

    def test_khong_co_tin_thi_noi_that(self):
        self.assertEqual(news._format_items([], 5), "Không có tin tức nào.")


if __name__ == "__main__":
    unittest.main()
