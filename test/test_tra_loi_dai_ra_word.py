"""Phản hồi dài quá 1.800 ký tự thì đóng Word, trừ thứ bắt buộc ở lại chat.

Chủ máy chốt 16/08/2026 sau khi một bản chép lời dài trôi thành nhiều tin:
"tắt cả các phản hồi quá 1.800 ký tự thì cho vào word, những cái nào cần phải
và nhất thiết dài thì cứ giữ nguyên".

Hai thứ nhất thiết ở lại chat:

- Menu chọn — đóng tệp thì không còn bấm số trả lời được (nơi gọi tách sẵn
  bằng ``has_choices``, không đi qua hàm này).
- Câu có khối mã ```…``` — dán vào Word là hỏng thụt lề, mà người ta cần copy
  chạy được.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import song_ngu as sn  # noqa: E402
from services import zalo_personal as zp  # noqa: E402

NGUONG = sn.NGUONG_DONG_TEP


class TestDongWordCauTraLoiDai(unittest.TestCase):
    def setUp(self) -> None:
        self.tep: list[tuple[str, str]] = []      # (tên tệp, ghi chú)

        def _gia(_tid, _ttype, du_lieu, ten, ghi_chu=""):
            self.tep.append((ten, ghi_chu))
            self.assertTrue(du_lieu, "tệp rỗng")

        self._p = mock.patch.object(zp, "_serve_bytes", side_effect=_gia)
        self._p.start()

    def tearDown(self) -> None:
        self._p.stop()

    def test_ngan_thi_giu_nguyen_trong_chat(self) -> None:
        self.assertFalse(zp._tra_loi_dai_ra_word("t1", 0, "x" * (NGUONG - 100)))
        self.assertEqual(self.tep, [])

    def test_nhinh_hon_nguong_chut_it_van_o_chat(self) -> None:
        """Mở tệp cho một câu 2.000 ký tự còn phiền hơn đọc thẳng."""
        self.assertFalse(zp._tra_loi_dai_ra_word("t1", 0, "x" * (NGUONG + 100)))
        self.assertEqual(self.tep, [])

    def test_dai_han_thi_dong_word(self) -> None:
        # python-docx không có trên máy dev; chỗ cần kiểm là QUYẾT ĐỊNH đóng
        # tệp, không phải bản thân thư viện Word.
        with mock.patch.object(sn, "docx_mot_ban", return_value=b"PK\x03\x04"):
            self.assertTrue(zp._tra_loi_dai_ra_word("t1", 0, "x" * (NGUONG * 3)))
        self.assertEqual(len(self.tep), 1)
        ten, ghi_chu = self.tep[0]
        self.assertTrue(ten.endswith(".docx"), ten)
        self.assertIn("ký tự", ghi_chu)

    def test_khoi_ma_thi_KHONG_dong_tep(self) -> None:
        chu = "Đây là đoạn mã:\n```python\nprint('hi')\n```\n" + "y" * (NGUONG * 3)
        self.assertFalse(zp._tra_loi_dai_ra_word("t1", 0, chu))
        self.assertEqual(self.tep, [])

    def test_dong_tep_hong_thi_tra_False_de_con_nhan_chu(self) -> None:
        """Không được nuốt câu trả lời khi tạo Word hỏng."""
        with mock.patch.object(sn, "docx_mot_ban", side_effect=RuntimeError("thiếu docx")):
            self.assertFalse(zp._tra_loi_dai_ra_word("t1", 0, "z" * (NGUONG * 3)))


class TestDungChungMotNguong(unittest.TestCase):
    def test_lay_theo_song_ngu_khong_tu_dat_so_rieng(self) -> None:
        """Một con số duy nhất để chỉnh, dùng chung với bản chép lời."""
        with mock.patch.object(sn, "NGUONG_DONG_TEP", 200), \
             mock.patch.object(sn, "docx_mot_ban", return_value=b"PK\x03\x04"), \
             mock.patch.object(zp, "_serve_bytes") as gui:
            self.assertTrue(zp._tra_loi_dai_ra_word("t1", 0, "x" * 900))
            self.assertTrue(gui.called)


if __name__ == "__main__":
    unittest.main()
