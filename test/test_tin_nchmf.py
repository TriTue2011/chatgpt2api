"""Nguồn NCHMF trong bản tin: bóc từ TRANG CHỦ, không phải RSS.

Trang có quảng cáo một đường RSS (`/kttv/vi-VN/1/homerss.html`) nhưng đường đó
trả 404 — đo 25/08/2026, cả bốn biến thể đường dẫn đều 404. Nên nguồn này bóc
HTML trang chủ, và mọi thứ dưới đây khoá đúng những chỗ dễ hỏng của việc đó:

  * cùng một bản tin xuất hiện ở nhiều khối trên trang, phải bỏ trùng;
  * trang KHÔNG xếp sẵn theo giờ (khối tin nổi bật nằm trước), phải tự xếp;
  * hai dạng mốc giờ cùng tồn tại: có giờ phút giây và chỉ có ngày;
  * mục "thoi_tiet" phải CHỈ có NCHMF — đó là chỗ đặt tiếng nói chính thức,
    không để tin báo chí trộn vào.

Không gọi mạng: `httpx.Client` được thay bằng bản giả trả đúng khuôn HTML thật.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_HUB = Path(__file__).resolve().parents[1] / "vn-mcp-hub"
if str(_HUB) not in sys.path:
    sys.path.insert(0, str(_HUB))

try:
    from src.vn import news
except Exception:                    # thiếu feedparser/fastmcp ở môi trường test
    news = None


def _muc(link: str, tieu_de: str, moc: str) -> str:
    """Đúng khuôn một mục trên trang chủ NCHMF, đo 25/08/2026."""
    return (f'<li><a href="{link}" alt="{tieu_de}">{tieu_de}'
            f"<label>({moc})</label><img src=\"x.jpg\" /></a></li>")


TRANG = "<ul class=\"uk-list list-news\">" + "".join([
    _muc("https://www.nchmf.gov.vn/kttv/vi-VN/1/tin-bien-post53385.html",
         "TIN DỰ BÁO GIÓ MẠNH, SÓNG LỚN VÀ MƯA DÔNG TRÊN BIỂN",
         "25/08/2026 16:00:00"),
    _muc("https://www.nchmf.gov.vn/kttv/vi-VN/1/tin-lu-quet-post53447.html",
         "TIN CẢNH BÁO LŨ QUÉT SẠT LỞ ĐẤT", "25/08/2026 16:28:01"),
    # Trùng với mục đầu — trang chủ thật lặp lại bản tin giữa các khối.
    _muc("https://www.nchmf.gov.vn/kttv/vi-VN/1/tin-bien-post53385.html",
         "TIN DỰ BÁO GIÓ MẠNH, SÓNG LỚN VÀ MƯA DÔNG TRÊN BIỂN",
         "25/08/2026 16:00:00"),
    # Bản tin định kỳ: chỉ có ngày, không có giờ.
    _muc("https://www.nchmf.gov.vn/kttv/vi-VN/1/ban-tin-song-post53098.html",
         "Bản tin dự báo sóng 10 ngày tới", "25/08/2026"),
]) + "</ul>"


class _PhanHoi:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code, self.text = status_code, text


class _ClientGia:
    """Thay `httpx.Client` — không mở kết nối nào."""

    def __init__(self, phan_hoi: _PhanHoi) -> None:
        self._phan_hoi = phan_hoi

    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        return self._phan_hoi


@unittest.skipIf(news is None, "vn-mcp-hub chưa cài phụ thuộc trong môi trường này")
class TestBocTrangChuNCHMF(unittest.TestCase):
    def _lay(self, status: int = 200, text: str = TRANG):
        with mock.patch.object(news.httpx, "Client", _ClientGia(_PhanHoi(status, text))):
            return news._fetch_nchmf("NCHMF")

    def test_bo_ban_tin_trung_lap(self):
        self.assertEqual(len(self._lay()), 3)

    def test_xep_moi_truoc_cu_sau(self):
        moc = [it["published"] for it in self._lay()]
        self.assertEqual(moc[0], "25/08/2026 16:28:01")
        self.assertEqual(moc[1], "25/08/2026 16:00:00")

    def test_ban_tin_chi_co_ngay_van_giu_lai(self):
        """Không đọc được giờ thì đẩy xuống cuối, KHÔNG loại khỏi bản tin."""
        tieu_de = [it["title"] for it in self._lay()]
        self.assertIn("Bản tin dự báo sóng 10 ngày tới", tieu_de)
        self.assertEqual(tieu_de[-1], "Bản tin dự báo sóng 10 ngày tới")

    def test_tieu_de_sach_va_co_lien_ket(self):
        it = self._lay()[0]
        self.assertNotIn("<", it["title"])
        self.assertTrue(it["link"].endswith("post53447.html"))
        self.assertEqual(it["source"], "NCHMF")

    def test_khong_de_lot_khoa_phu_ra_ngoai(self):
        """`_moc` chỉ để xếp thứ tự; lọt ra ngoài là rác trong bản tin."""
        self.assertNotIn("_moc", self._lay()[0])

    def test_trang_hong_thi_tra_rong_chu_khong_no(self):
        self.assertEqual(self._lay(status=503), [])
        self.assertEqual(self._lay(text="<html>đổi rồi</html>"), [])

    def test_muc_thoi_tiet_chi_lay_nguon_nha_nuoc(self):
        """Tin báo chí trộn vào đây thì mục mất ý nghĩa 'bản tin chính thức'."""
        feeds = news._get_feeds("thoi_tiet")
        self.assertEqual([ten for ten, _ in feeds], ["NCHMF"])

    def test_co_mat_trong_tin_moi_nhat(self):
        """Hỏi 'tin tức hôm nay' phải chạm tới nguồn này."""
        urls = [u for _, u in news._get_feeds("moi_nhat")]
        self.assertIn(news._NCHMF_URL, urls)

    def test_co_muc_rieng_trong_ban_tin_chia_muc(self):
        ma = [m[0] for m in news.MUC_BAN_TIN]
        self.assertIn("thoi_tiet", ma)


@unittest.skipIf(news is None, "vn-mcp-hub chưa cài phụ thuộc trong môi trường này")
class TestMocGio(unittest.TestCase):
    def test_hai_dang_moc_gio_deu_doc_duoc(self):
        co_gio = news._nchmf_moc_gio("25/08/2026 16:28:01")
        chi_ngay = news._nchmf_moc_gio("25/08/2026")
        self.assertEqual((co_gio.day, co_gio.hour), (25, 16))
        self.assertEqual((chi_ngay.day, chi_ngay.hour), (25, 0))
        self.assertGreater(co_gio, chi_ngay)

    def test_moc_gio_hong_thi_xuong_cuoi(self):
        from datetime import datetime
        self.assertEqual(news._nchmf_moc_gio("hôm nọ"), datetime.min)
        self.assertEqual(news._nchmf_moc_gio(""), datetime.min)


if __name__ == "__main__":
    unittest.main()
