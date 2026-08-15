"""`/images` không còn là kho mở.

Trước đây đó là một mount `StaticFiles` thuần: ai đoán hoặc dò được tên file là
tải được MỌI ảnh, video và tài liệu từng đi qua hệ thống — ảnh camera, ảnh chụp
màn hình, PDF người dùng tải lên. Tên file thì nằm sẵn trong log, trong lịch sử
chat và trong mọi URL đã chia sẻ.

Vì sao kiểm ở MỘT CỬA chứ không ký ở từng nơi phát: có 76 chỗ trong mã dựng URL
`/images/…`. Sửa từng chỗ là diff khổng lồ, và sót một chỗ là có một đường vòng
mà không ai biết cho tới khi có người tìm ra.

Hai đường vào hợp lệ, vì hai loại người dùng khác hẳn nhau: CHỮ KÝ cho nơi
không gửi được header (Zalo/Telegram tự đi tải URL), và PHIÊN COOKIE cho trình
duyệt admin (thẻ `<img>` không gửi được Authorization, nhưng cookie thì có).
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.signed_url import kiem_chu_ky, ky_duong_dan, ky_url  # noqa: E402


class KhongConStaticFilesTests(unittest.TestCase):
    def test_app_khong_con_mount_images(self):
        src = (GOC / "api/app.py").read_text(encoding="utf-8")
        self.assertNotIn('app.mount("/images"', src,
                         "StaticFiles phục vụ mọi file cho mọi người, "
                         "không cắm được phép kiểm nào")
        self.assertIn("media_api.create_router()", src)

    def test_route_kiem_ca_chu_ky_LAN_phien(self):
        # Luật giờ nằm trong `require_image_access` để thumbnail đi CHUNG một
        # cửa với ảnh gốc; route ảnh chỉ còn việc gọi nó.
        src = (GOC / "api/media.py").read_text(encoding="utf-8")
        route = src[src.index("async def phuc_vu_anh"):]
        self.assertIn("require_image_access(", route)
        cua = src[src.index("def require_image_access"):src.index("def create_router")]
        self.assertIn("kiem_chu_ky", cua)
        self.assertIn("danh_tinh_cookie", cua,
                      "`<img>` không gửi được Authorization — thiếu đường cookie "
                      "thì bật cờ lên là trang admin trắng ảnh")

    def test_bat_buoc_nam_sau_co_mac_dinh_TAT(self):
        src = (GOC / "api/media.py").read_text(encoding="utf-8")
        i = src.index("def bat_buoc_ky")
        than = src[i:i + 500]
        self.assertIn("signed_media_required", than)
        self.assertIn("return False", than)


class ChanDiRaNgoaiThuMucTests(unittest.TestCase):
    """`StaticFiles` tự chặn `..`; route thường thì phải tự làm."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        goc = Path(self._tmp.name) / "images"
        goc.mkdir()
        (goc / "that.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (Path(self._tmp.name) / "bi_mat.txt").write_text("khong duoc doc")
        self.goc = goc
        self.addCleanup(self._tmp.cleanup)

    def _duong_that(self, rel: str):
        from services.media_path import duong_an_toan
        return duong_an_toan(self.goc, rel)

    def test_file_trong_thu_muc_thi_doc_duoc(self):
        self.assertIsNotNone(self._duong_that("that.png"))

    def test_di_len_thu_muc_cha_bi_chan(self):
        for xau in ("../bi_mat.txt", "a/../../bi_mat.txt", "./../bi_mat.txt"):
            self.assertIsNone(self._duong_that(xau), f"{xau!r} lọt ra ngoài")

    def test_duong_tuyet_doi_bi_chan(self):
        self.assertIsNone(self._duong_that("/etc/passwd"))

    def test_file_khong_ton_tai_tra_None(self):
        self.assertIsNone(self._duong_that("khong-co.png"))

    def test_thu_muc_khong_phai_file(self):
        (self.goc / "mot_thu_muc").mkdir()
        self.assertIsNone(self._duong_that("mot_thu_muc"))


class ChuKyAnhTests(unittest.TestCase):
    DUONG = "/images/2026/08/abc123.png"

    def _tach(self, q: str) -> dict:
        return dict(p.split("=", 1) for p in q.split("&"))

    def test_chu_ky_pham_vi_images_hop_le(self):
        q = self._tach(ky_duong_dan(self.DUONG, pham_vi="images"))
        self.assertTrue(kiem_chu_ky(self.DUONG, q["exp"], q["sig"], pham_vi="images"))

    def test_chu_ky_cua_voice_KHONG_mo_duoc_anh(self):
        q = self._tach(ky_duong_dan(self.DUONG, pham_vi="voice"))
        self.assertFalse(kiem_chu_ky(self.DUONG, q["exp"], q["sig"], pham_vi="images"))

    def test_doi_ten_file_thi_chu_ky_hong(self):
        q = self._tach(ky_duong_dan(self.DUONG, pham_vi="images"))
        self.assertFalse(kiem_chu_ky("/images/2026/08/anh_khac.png",
                                     q["exp"], q["sig"], pham_vi="images"))

    def test_het_han_thi_tu_choi(self):
        import time
        q = self._tach(ky_duong_dan(self.DUONG, pham_vi="images", song_giay=1))
        self.assertFalse(kiem_chu_ky(self.DUONG, str(int(time.time()) - 5),
                                     q["sig"], pham_vi="images"))


class KyUrlDayDuTests(unittest.TestCase):
    """Zalo/Telegram nhận URL rồi TỰ đi tải — không cookie, không header."""

    def test_noi_chu_ky_vao_url_day_du(self):
        ra = ky_url("https://vidu.com/images/a/b.png")
        self.assertTrue(ra.startswith("https://vidu.com/images/a/b.png?"))
        q = dict(p.split("=", 1) for p in ra.split("?", 1)[1].split("&"))
        self.assertTrue(kiem_chu_ky("/images/a/b.png", q["exp"], q["sig"],
                                    pham_vi="images"))

    def test_url_da_co_query_thi_noi_bang_dau_va(self):
        ra = ky_url("https://vidu.com/images/a.png?v=2")
        self.assertIn("?v=2&exp=", ra)

    def test_url_rong_khong_lam_sap(self):
        self.assertEqual(ky_url(""), "")


if __name__ == "__main__":
    unittest.main()
