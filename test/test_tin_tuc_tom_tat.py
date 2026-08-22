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


@unittest.skipIf(news is None, "vn-mcp-hub chưa cài phụ thuộc trong môi trường này")
class TestBanTinChiaMuc(unittest.TestCase):
    """Người dùng yêu cầu 01/08: chia 8 mục, mỗi mục 3 tin gạch đầu dòng.

    Trước đó bot "ghi nhớ" đúng yêu cầu này nhưng KHÔNG làm được, vì đường tắt
    tin tức trả nguyên văn kết quả MCP — model không chạm vào định dạng.
    """

    MUC_YEU_CAU = ["Thể thao", "Kinh tế", "Xã hội", "Công nghệ thông tin",
                   "Giáo dục", "Y tế", "Giải trí", "Thế giới"]

    def test_du_8_muc_dung_thu_tu(self):
        nhan = [t for _, _, t in news.MUC_BAN_TIN]
        self.assertEqual(len(nhan), 8)
        for mong, that in zip(self.MUC_YEU_CAU, nhan):
            self.assertIn(mong, that, f"mục '{mong}' sai chỗ hoặc thiếu")

    def test_moi_muc_tro_toi_chu_de_co_that(self):
        """Sai một mã chủ đề là mục đó im lặng rỗng mãi mãi."""
        for tid, _emo, ten in news.MUC_BAN_TIN:
            self.assertIn(tid, news.TOPICS, f"mục '{ten}' trỏ tới chủ đề lạ: {tid}")

    @staticmethod
    def _goi_duoc():
        """`@mcp.tool()` tuỳ phiên bản fastmcp: có bản bọc thành FunctionTool
        (hàm thật nằm ở `.fn`), có bản trả về nguyên hàm. Lấy đúng cái gọi được
        thay vì đoán một kiểu rồi vỡ khi nâng phiên bản."""
        t = news.get_news_sections
        return getattr(t, "fn", t)

    def _gia_lap(self, ket: dict) -> str:
        from unittest.mock import patch
        with patch.object(news, "_lay_mot_muc",
                          side_effect=lambda tid, n, *a: ket.get(tid, [])):
            return self._goi_duoc()(3)

    def test_dinh_dang_gach_dau_dong(self):
        """`in_dam=True` chỉ tô đậm TÊN MỤC, KHÔNG tô từng tiêu đề.

        Đây là chủ ý, không phải sót: tô cả 24 tiêu đề thì một bản tin có 32
        vùng định dạng, mức đó bị Zalo từ chối (đo 01/08) rồi rơi về bản thô
        còn nguyên dấu sao — người dùng thấy `**` giữa câu. Xem chú thích tại
        `news.get_news_sections`. Test này chốt lại đúng ranh giới đó, nếu
        không thì lần "sửa cho nhất quán" sau sẽ mở lại lỗi cũ.
        """
        ket = {"the_thao": [{"title": "Tin A", "summary": "Tóm A.",
                             "source": "X", "link": "https://x/1"}]}
        ra = self._gia_lap(ket)
        self.assertIn("**⚽ Thể thao**", ra, "tên mục phải in đậm")
        self.assertIn("- Tin A — Tóm A.", ra)
        self.assertNotIn("**Tin A**", ra, "tiêu đề phải để trơn")
        self.assertNotIn("http", ra)          # không dán link

    def test_noi_ro_muc_nao_trong(self):
        """Mục rỗng phải được NÊU TÊN. Lặng lẽ bỏ bớt thì người dùng tưởng hôm
        nay không có tin, chứ không biết là nguồn hỏng."""
        ra = self._gia_lap({"the_thao": [{"title": "T", "summary": "",
                                          "source": "X", "link": ""}]})
        self.assertIn("Chưa lấy được tin cho mục:", ra)
        self.assertIn("Kinh tế", ra)

    def test_khong_lay_duoc_gi_thi_noi_that(self):
        self.assertEqual(self._gia_lap({}), "Không lấy được tin tức nào lúc này.")

    def test_bo_tom_tat_bang_code(self):
        """`kem_tom_tat=False` phải bỏ tóm tắt NGAY trong code.

        Trước đây việc này nhờ model bày lại: đo thật 01/08, bản tin 4819 ký tự
        không kịp xong trong 20 giây nên lần nào cũng hết giờ rồi rơi về bản gốc
        — người dùng chờ thêm 20 giây để nhận đúng thứ cũ.
        """
        from unittest.mock import patch
        ket = {"the_thao": [{"title": "Tin A", "summary": "Tóm tắt A.",
                             "source": "X", "link": ""}]}
        goi = self._goi_duoc()
        with patch.object(news, "_lay_mot_muc",
                          side_effect=lambda tid, n, *a: ket.get(tid, [])):
            co = goi(3, True)
            khong = goi(3, False)
        self.assertIn("Tóm tắt A.", co)
        self.assertNotIn("Tóm tắt A.", khong)
        self.assertIn("Tin A", khong, "bỏ tóm tắt không được bỏ luôn tiêu đề")

    def test_bo_in_dam_va_emoji(self):
        """Người dùng nói "trình bày xấu quá" và lời dặn lưu lại là "không in
        đậm/không emoji rườm rà". Trước đó bản tin vẫn đậm và vẫn emoji — lời dặn
        lưu được mà không ai thực hiện."""
        from unittest.mock import patch
        ket = {"the_thao": [{"title": "Tin A", "summary": "Tóm A.",
                             "source": "X", "link": ""}]}
        with patch.object(news, "_lay_mot_muc",
                          side_effect=lambda tid, n, *a: ket.get(tid, [])):
            gon = self._goi_duoc()(3, False, False, False)
        self.assertNotIn("**", gon)
        self.assertNotIn("⚽", gon)
        self.assertIn("Thể thao", gon)
        self.assertIn("- Tin A", gon)

    def test_mac_dinh_van_dam_va_emoji(self):
        """Không truyền gì thì giữ dáng cũ — không đổi ngầm."""
        from unittest.mock import patch
        ket = {"the_thao": [{"title": "Tin A", "summary": "Tóm A.",
                             "source": "X", "link": ""}]}
        with patch.object(news, "_lay_mot_muc",
                          side_effect=lambda tid, n, *a: ket.get(tid, [])):
            ra = self._goi_duoc()(3)
        self.assertIn("**", ra)
        self.assertIn("⚽", ra)

    def test_mac_dinh_van_co_tom_tat(self):
        """Không truyền gì thì giữ hành vi cũ — không đổi ngầm."""
        from unittest.mock import patch
        ket = {"the_thao": [{"title": "Tin A", "summary": "Tóm tắt A.",
                             "source": "X", "link": ""}]}
        with patch.object(news, "_lay_mot_muc",
                          side_effect=lambda tid, n, *a: ket.get(tid, [])):
            self.assertIn("Tóm tắt A.", self._goi_duoc()(3))



@unittest.skipIf(news is None, "vn-mcp-hub chưa cài phụ thuộc trong môi trường này")
class TestChiTinTiengViet(unittest.TestCase):
    """LỌC tin tiếng Anh, không dịch.

    Đường dịch bằng model không đáng tin — đo thật 01/08: một lần xong trong 7,9
    giây, lần sau HẾT GIỜ ở 15 giây và tiêu đề vẫn nguyên tiếng Anh, mà bản tin
    phải chờ đủ 15 giây đó. Đo thêm: mọi mục đều có tối thiểu 4 tin tiếng Việt
    trong 12 tin lấy về, nên lọc vẫn đủ 3 tin mỗi mục — chắc chắn và tức thì.
    """

    def test_nhan_dang_tieng_viet(self):
        self.assertTrue(news._la_tieng_viet("Đội tuyển Việt Nam hòa Singapore"))
        self.assertTrue(news._la_tieng_viet("Lãi suất ngân hàng còn 0,7%/năm"))
        self.assertFalse(news._la_tieng_viet("Snapchat joins fight against AI slop"))
        self.assertFalse(news._la_tieng_viet(""))

    def test_loc_bo_tin_tieng_anh(self):
        from unittest.mock import patch
        ds = ([{"title": f"Tin Việt số {i}", "summary": "", "source": "VN", "link": ""}
               for i in range(3)]
              + [{"title": "English headline here", "summary": "", "source": "BBC",
                  "link": ""}])
        with patch.object(news, "_get_feeds", return_value=[("X", "u")]), \
             patch.object(news, "_fetch_feed", return_value=ds):
            ra = news._lay_mot_muc("the_thao", 3, chi_tieng_viet=True)
        self.assertEqual(len(ra), 3)
        self.assertFalse(any("English" in x["title"] for x in ra))

    def test_thieu_tin_viet_thi_van_lay_tin_anh(self):
        """Thà có tin tiếng Anh hơn là mục RỖNG."""
        from unittest.mock import patch
        ds = [{"title": "Tin Việt duy nhất", "summary": "", "source": "VN", "link": ""},
              {"title": "English one", "summary": "", "source": "BBC", "link": ""},
              {"title": "English two", "summary": "", "source": "BBC", "link": ""}]
        with patch.object(news, "_get_feeds", return_value=[("X", "u")]), \
             patch.object(news, "_fetch_feed", return_value=ds):
            ra = news._lay_mot_muc("the_thao", 3, chi_tieng_viet=True)
        self.assertEqual(len(ra), 3, "không đủ tin Việt thì không được bỏ trống mục")

    def test_mac_dinh_khong_loc(self):
        from unittest.mock import patch
        ds = [{"title": "English headline", "summary": "", "source": "BBC", "link": ""}]
        with patch.object(news, "_get_feeds", return_value=[("X", "u")]), \
             patch.object(news, "_fetch_feed", return_value=ds):
            ra = news._lay_mot_muc("the_thao", 1)
        self.assertEqual(len(ra), 1)


if __name__ == "__main__":
    unittest.main()
