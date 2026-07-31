"""Lệnh lấy media trong thư viện của MÁY không được đem đi tra web.

Lỗi thật 31/07/2026 (log máy chủ 06:17): người dùng gõ "Gửi 3 ảnh mới nhất
trong thư viện ảnh". Cụm "mới nhất" khớp SEARCH_INTENT_PATTERNS nên `needs_search`
trả True ⇒ cả câu lệnh bị đem đi tìm trên Internet: DuckDuckGo, federated search
(12 kết quả) và cả CrossRef — kho báo khoa học. Rồi bot trả lời:

  "Dạ em không truy cập được thư viện ảnh cá nhân của anh nên chưa thể tự lấy
   3 ảnh mới nhất để gửi được ạ. Anh mở Google Photos / Ảnh iCloud…"

Trong khi hệ thống CÓ tool `library_media` đúng để làm việc đó, mô tả tool còn
ghi rõ "TUYỆT ĐỐI KHÔNG trả lời là không có quyền/tool".
"""
from __future__ import annotations

import unittest


def _hoi(text: str) -> bool:
    from services.search_service import needs_search
    return needs_search([{"role": "user", "content": text}])


class TestKhongTraWebLenhThuVien(unittest.TestCase):
    def test_dung_cau_gay_loi_that(self):
        self.assertFalse(_hoi("Gửi 3 ảnh mới nhất trong thư viện ảnh"),
                         "lệnh lấy ảnh trong thư viện KHÔNG được kích hoạt tra web")

    def test_cac_cach_noi_khac(self):
        for cau in (
            "gửi lại ảnh vừa tạo cho anh",
            "cho xem lại video mới nhất",
            "gửi ảnh trong thư viện",
            "mở lại bài hát vừa tạo",
            "ảnh vừa vẽ đâu rồi",
        ):
            self.assertFalse(_hoi(cau), f"không được tra web: {cau!r}")


class TestVanTraWebNhuCu(unittest.TestCase):
    """Chặn phải HẸP — câu hỏi thật sự cần Internet vẫn phải tra."""

    def test_tim_anh_tren_mang_van_tra_web(self):
        self.assertTrue(_hoi("tìm ảnh cầu Long Biên mới nhất"))

    def test_tin_tuc_van_tra_web(self):
        self.assertTrue(_hoi("tin tức Việt Nam mới nhất hôm nay"))

    def test_gia_ca_van_tra_web(self):
        self.assertTrue(_hoi("giá xăng RON 95 hôm nay bao nhiêu"))

    def test_thoi_tiet_van_tra_web(self):
        self.assertTrue(_hoi("thời tiết Hà Nội ngày mai"))

    def test_tu_media_mot_minh_khong_chan(self):
        """Chỉ có từ chỉ media mà không có dấu hiệu 'kho của mình' thì vẫn tra."""
        self.assertTrue(_hoi("clip trận đấu tối qua kết quả thế nào"))


if __name__ == "__main__":
    unittest.main()
