"""Bot gửi NHIỀU ẢNH trong MỘT lượt — 3, 10, tối đa 50.

Hai lỗi gốc được khoá lại ở đây:

1. `produced_media` là dict MỘT khoá và bị GHI ĐÈ mỗi lần gọi tool, nên model vẽ
   3 ảnh thì chỉ tấm CUỐI tới — hai tấm kia đã tốn phí sinh ra rồi bị bỏ im lặng.
2. "Gửi 3 ảnh gần nhất trong thư viện" dễ gửi LẪN: thư viện chứa ảnh của lượt
   khác và tệp TRÙNG NỘI DUNG khác tên (đo thật 30/07: `1785379635_2a6363b6…` và
   `1785379627_2a6363b6…` cùng nội dung). Lấy theo thời gian mà không lọc trùng
   là người dùng thấy ảnh lặp và tưởng bot gửi sai.

Giới hạn mỗi kênh KHÁC nhau và phải giữ đúng số của chính nó:
  Zalo Cá Nhân 50/tin (đọc từ phiên) · Telegram 10/album · Zalo Bot không có album.
"""
from __future__ import annotations

import unittest

from services.agent import capabilities as caps
from services.agent import orchestrator as orch


class TestSoLuongAnh(unittest.TestCase):
    def test_khong_truyen_thi_mot_anh(self):
        self.assertEqual(caps._so_luong_anh({}), 1)

    def test_doc_nhieu_ten_tham_so(self):
        for k in ("so_luong", "count", "n", "so"):
            with self.subTest(k):
                self.assertEqual(caps._so_luong_anh({k: 3}), 3)

    def test_kep_tran_50(self):
        self.assertEqual(caps._so_luong_anh({"so_luong": 999}), 50)
        self.assertEqual(caps._so_luong_anh({"so_luong": 50}), 50)

    def test_kep_san_1(self):
        self.assertEqual(caps._so_luong_anh({"so_luong": 0}), 1)
        self.assertEqual(caps._so_luong_anh({"so_luong": -5}), 1)

    def test_gia_tri_la_thi_ve_1_chu_khong_no(self):
        """Model đôi khi truyền rác. Trả 1 tấm còn dùng được; báo lỗi là mất lượt.

        "ba" KHÔNG còn nằm ở đây: nó là chữ số viết bằng lời và nay được hiểu
        thành 3 (xem TestDocSoAnhTuCauNoi). Chỉ những giá trị thật sự không đọc
        được mới về 1.
        """
        for v in (None, "", {}, [1], "abc", "nhiều"):
            with self.subTest(v):
                self.assertEqual(caps._so_luong_anh({"so_luong": v}), 1)


class TestDanhSachChiKhiNhieu(unittest.TestCase):
    def test_mot_anh_thi_khong_them_khoa(self):
        """Một ảnh đã nằm ở image_url — thêm danh sách 1 phần tử là mời mọi kênh
        đi đường chia lô cho đúng một tấm."""
        self.assertEqual(orch._nhieu_anh(["a"]), {})
        self.assertEqual(orch._nhieu_anh([]), {})

    def test_tu_hai_anh_thi_co_khoa(self):
        self.assertEqual(orch._nhieu_anh(["a", "b"]), {"image_urls": ["a", "b"]})

    def test_giu_dung_thu_tu(self):
        self.assertEqual(orch._nhieu_anh(["c", "a", "b"])["image_urls"],
                         ["c", "a", "b"])


class TestThuVienLocTrung(unittest.TestCase):
    """Ảnh trùng NỘI DUNG khác tên không được tính là hai ảnh."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = Path(tempfile.mkdtemp())
        # save_image_bytes đặt tên "<epoch>_<md5>.png" → trùng nội dung là trùng
        # phần sau dấu gạch dưới.
        (self.tmp / "1000_aaa.png").write_bytes(b"A" * 100)
        (self.tmp / "1001_aaa.png").write_bytes(b"A" * 100)   # TRÙNG nội dung
        (self.tmp / "1002_bbb.png").write_bytes(b"B" * 200)
        (self.tmp / "1003_ccc.png").write_bytes(b"C" * 300)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _goi(self, so: int) -> dict:
        from unittest import mock
        with mock.patch.object(type(caps.config), "images_dir",
                               property(lambda _s: self.tmp)):
            return caps._h_library_media({"kind": "image", "so_luong": so}, {})

    def test_xin_3_thi_ra_3_anh_KHAC_NHAU(self):
        r = self._goi(3)
        ds = r.get("image_urls") or []
        self.assertEqual(len(ds), 3, r)
        self.assertEqual(len(set(ds)), 3)
        # tệp trùng nội dung chỉ được lấy MỘT lần
        self.assertEqual(sum(1 for u in ds if "aaa" in u), 1, ds)

    def test_xin_nhieu_hon_kho_thi_noi_ro_thieu(self):
        r = self._goi(10)
        self.assertEqual(len(r.get("image_urls") or []), 3)
        self.assertIn("không đủ", r.get("text", ""))

    def test_xin_1_thi_van_dung_khoa_cu(self):
        r = self._goi(1)
        self.assertIn("image_url", r)
        self.assertNotIn("image_urls", r)


class TestGioiHanTungKenh(unittest.TestCase):
    """Mỗi kênh phải dùng con số CỦA MÌNH, không dùng chung."""

    def test_telegram_album_toi_da_10(self):
        import inspect
        from services import telegram_bot as tg
        src = inspect.getsource(tg._gui_album)
        self.assertIn("urls[:10]", src)

    def test_telegram_tu_choi_khi_duoi_2_anh(self):
        from services import telegram_bot as tg
        self.assertFalse(tg._gui_album(1, ["http://x/a.png"]))

    def test_zalo_ca_nhan_di_endpoint_mang(self):
        import inspect
        from services import zalo_personal as zp
        src = inspect.getsource(zp._gui_nhieu_anh)
        self.assertIn("sendImagesToUserByAccount", src)
        self.assertIn("sendImagesToGroupByAccount", src)
        self.assertIn("imagePaths", src)

    def test_zalo_bot_gui_lan_luot_vi_khong_co_album(self):
        import inspect
        from services import zalo_bot as zb
        src = inspect.getsource(zb)
        i = src.index('image_urls = out.get("image_urls")')
        khuc = src[i:i + 1200]
        self.assertIn("KHÔNG có album", khuc)
        self.assertIn("send_photo", khuc)



class TestAnhCuaChinhNguoiDo(unittest.TestCase):
    """"3 ảnh gần nhất TÔI tạo" phải là ảnh của CHÍNH người hỏi.

    `save_image_bytes` đặt tên `<epoch>_<md5>.png` và KHÔNG ghi ai tạo, nên
    `data/images` là rổ CHUNG: có ảnh của người dùng khác, ảnh snapshot camera do
    Home Assistant đẩy lên, và ảnh test. Lấy "N tệp mới nhất" là gửi ảnh người
    khác cho người này — sai cả đúng đắn lẫn riêng tư, mà nhìn từ ngoài y như
    đang chạy đúng.
    """

    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from services.agent import anh_cua_toi
        self.tmp = Path(tempfile.mkdtemp())
        self.p = mock.patch.object(anh_cua_toi, "_duong",
                                   lambda: self.tmp / "so.json")
        self.p.start()
        self.mod = anh_cua_toi

    def tearDown(self):
        import shutil
        self.p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_moi_nguoi_chi_thay_anh_cua_minh(self):
        self.mod.ghi("zalop_A", ["a1", "a2"])
        self.mod.ghi("zalop_B", ["b1"])
        self.assertEqual(self.mod.gan_nhat("zalop_A", 5), ["a1", "a2"])
        self.assertEqual(self.mod.gan_nhat("zalop_B", 5), ["b1"])

    def test_anh_moi_len_dau_va_giu_thu_tu(self):
        self.mod.ghi("u", ["cu1", "cu2"])
        self.mod.ghi("u", ["moi"])
        self.assertEqual(self.mod.gan_nhat("u", 3), ["moi", "cu1", "cu2"])

    def test_ghi_lai_anh_cu_khong_nhan_ban(self):
        self.mod.ghi("u", ["x", "y"])
        self.mod.ghi("u", ["y"])
        self.assertEqual(self.mod.gan_nhat("u", 5), ["y", "x"])

    def test_nguoi_chua_tao_anh_thi_rong_chu_khong_muon_cua_nguoi_khac(self):
        self.mod.ghi("khac", ["z"])
        self.assertEqual(self.mod.gan_nhat("chua_co", 3), [])

    def test_khong_co_user_id_thi_khong_ghi(self):
        self.mod.ghi("", ["x"])
        self.assertEqual(self.mod.gan_nhat("", 3), [])

    def test_chan_so_muc_moi_nguoi(self):
        self.mod.ghi("u", [f"a{i}" for i in range(500)])
        self.assertLessEqual(len(self.mod.gan_nhat("u", 999)), self.mod._MOI_NGUOI)

    def test_handler_uu_tien_anh_cua_nguoi_hoi(self):
        self.mod.ghi("zalop_9", ["http://x/1.png", "http://x/2.png"])
        r = caps._h_library_media({"kind": "image", "so_luong": 2},
                                  {"user_id": "zalop_9"})
        self.assertEqual(r.get("image_urls"), ["http://x/1.png", "http://x/2.png"])
        self.assertIn("anh/chị tạo", r.get("text", ""))

class TestDocSoAnhTuCauNoi(unittest.TestCase):
    """Model KHÔNG truyền `so_luong` — phải đọc số từ chính câu người dùng.

    Đo thật 30/07: gọi handler với so_luong=3 ra đúng 3 ảnh, nhưng người dùng
    nhắn "gửi 3 ảnh mới nhất" thì chỉ nhận 1 ảnh — model bỏ qua tham số dù mô tả
    tool đã ghi rõ phải truyền. Không ép được model, nên đọc từ câu nói: đó là
    nguồn gần nhất với ý người dùng.
    """

    def _n(self, cau: str) -> int:
        return caps._so_luong_anh({}, {"user_message": cau})

    def test_so_bang_chu_so(self):
        self.assertEqual(self._n("gửi 3 ảnh mới nhất trong thư viện ảnh"), 3)
        self.assertEqual(self._n("gửi cho tôi 3 ảnh mới nhất tôi tạo"), 3)
        self.assertEqual(self._n("cho xem 10 hình mới nhất"), 10)

    def test_so_viet_bang_lo(self):
        """Người Việt nói "ba ảnh" nhiều hơn "3 ảnh"."""
        self.assertEqual(self._n("gửi ba tấm ảnh gần nhất"), 3)
        self.assertEqual(self._n("gửi hai ảnh"), 2)
        self.assertEqual(self._n("gửi vài ảnh"), 3)

    def test_khong_neu_so_thi_mot_anh(self):
        self.assertEqual(self._n("gửi ảnh mới nhất"), 1)

    def test_khong_lan_so_cua_viec_khac(self):
        """Bắt buộc có danh từ chỉ ảnh, kẻo "3 bài toán" cũng thành 3 ảnh."""
        self.assertEqual(self._n("giải 3 bài toán giúp tôi"), 1)
        self.assertEqual(self._n("nhắc tôi sau 3 phút"), 1)
        self.assertEqual(self._n("đọc 5 trang đầu"), 1)

    def test_tham_so_cua_model_thang_cau_noi(self):
        """Model có truyền thì tin model — nó thấy cả hội thoại."""
        self.assertEqual(caps._so_luong_anh({"so_luong": 5},
                                           {"user_message": "gửi 2 ảnh"}), 5)

    def test_model_truyen_chu_van_hieu(self):
        self.assertEqual(caps._so_luong_anh({"so_luong": "ba"}, {}), 3)

    def test_van_kep_tran_50(self):
        self.assertEqual(self._n("gửi 99 ảnh"), 50)


if __name__ == "__main__":
    unittest.main()
