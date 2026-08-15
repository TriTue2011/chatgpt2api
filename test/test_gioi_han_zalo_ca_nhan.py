"""Giới hạn THẬT của Zalo Cá Nhân: 3.000 ký tự/tin, tệp tới 1 GB.

Chủ máy chốt 16/08/2026. Hai hằng số trong code đang đặt thấp hơn thực tế:
tin nhắn cắt ở 1990 ký tự (chú thích ghi "Zalo giới hạn 2000"), còn đính kèm
video bị chặn ở 250 MB — nên tệp 291,7 MB hợp lệ với Zalo vẫn bị từ chối.

Nới trần tệp thì phải đổi luôn CÁCH tải: `net_guard.safe_fetch` gom cả nội
dung vào RAM, mà máy chủ chỉ còn cỡ 9,7 GB khả dụng. Đường mới ghi thẳng ra
đĩa, vẫn qua đủ phép kiểm SSRF.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import net_guard  # noqa: E402
from services import zalo_personal as zp  # noqa: E402


class TestHangSoGioiHan(unittest.TestCase):
    def test_tin_nhan_theo_muc_3000_ky_tu(self) -> None:
        self.assertGreater(zp._MAX_LEN, 2000, "vẫn đang dùng mức 2000 cũ")
        self.assertLessEqual(zp._MAX_LEN, 3000, "vượt trần thật của Zalo")

    def test_con_cho_cho_hau_to_noi_them(self) -> None:
        """Vài đường gửi nối hậu tố vào bản ĐÃ cắt — cộng vào không được vượt."""
        hau_to = "\n(Fallback admin thread)"
        self.assertLessEqual(zp._MAX_LEN + len(hau_to), 3000)

    def test_tran_tep_dung_1GB(self) -> None:
        self.assertEqual(zp.TRAN_TEP_ZALO, 1024 * 1024 * 1024)

    def test_khuc_cat_ra_khong_khuc_nao_vuot_tran(self) -> None:
        from services.telegram.format import split_message

        dai = ("Câu tiếng Việt có dấu và khoảng trắng. " * 400)
        for khuc in split_message(dai, limit=zp._MAX_LEN, prefer=zp._MAX_LEN):
            self.assertLessEqual(len(khuc), 3000)


class TestTaiThangRaTep(unittest.TestCase):
    """`safe_fetch_to_file` — giữ nguyên phép kiểm, chỉ đổi chỗ chứa."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dest = str(Path(self._tmp.name) / "tai_ve.bin")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _gia_lap(self, noi_dung: bytes):
        """Opener giả trả `noi_dung` — không chạm mạng thật."""
        import io

        class _Resp(io.BytesIO):
            def geturl(self):
                return "https://example.com/a.bin"

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        opener = mock.Mock()
        opener.open = lambda req, timeout=None: _Resp(noi_dung)
        return mock.patch.object(net_guard.urllib.request, "build_opener",
                                 return_value=opener)

    def test_ghi_du_noi_dung_va_tra_so_byte(self) -> None:
        noi_dung = b"x" * (3 << 20)          # 3 MB, đi qua nhiều khúc đọc
        with mock.patch.object(net_guard, "check_url",
                               side_effect=lambda u, **_k: u), self._gia_lap(noi_dung):
            so = net_guard.safe_fetch_to_file("https://example.com/a.bin", self.dest,
                                              max_bytes=10 << 20)
        self.assertEqual(so, len(noi_dung))
        self.assertEqual(Path(self.dest).stat().st_size, len(noi_dung))

    def test_vuot_tran_thi_nem_loi_VA_khong_de_lai_tep_do(self) -> None:
        with mock.patch.object(net_guard, "check_url",
                               side_effect=lambda u, **_k: u), self._gia_lap(b"y" * 4096):
            with self.assertRaises(net_guard.BlockedURL):
                net_guard.safe_fetch_to_file("https://example.com/a.bin", self.dest,
                                             max_bytes=1024)
        self.assertFalse(Path(self.dest).exists(), "còn sót tệp tải dở")

    def test_van_chan_dia_chi_noi_bo_truoc_khi_mo_mang(self) -> None:
        with self.assertRaises(net_guard.BlockedURL):
            net_guard.safe_fetch_to_file("http://127.0.0.1/secret", self.dest)
        self.assertFalse(Path(self.dest).exists())

    def test_wrapper_cua_zalo_tra_0_khi_hong(self) -> None:
        self.assertEqual(
            zp._tai_ra_tep("http://127.0.0.1/secret", self.dest,
                           tran_byte=zp.TRAN_TEP_ZALO), 0)


if __name__ == "__main__":
    unittest.main()
