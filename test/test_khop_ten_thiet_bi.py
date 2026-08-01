"""Khớp tên thiết bị khi chụp webcam/màn hình — CHẶT trước, chỉ NỚI khi cần.

Lỗi thật 01/08: người dùng nói "chụp laptop của tôi", model truyền
device="laptop cua toi", máy đăng ký tên "laptop" → khớp cứng trượt → bot báo
"'laptop cua toi' đang không kết nối" dù máy ĐANG nối.

Nhưng nới quá tay cũng sai (người dùng chỉ ra): hai máy "laptop của tôi" và
"laptop của vợ" mà bỏ "của tôi" thì cả hai về "laptop" → mập mờ dù đã nói rõ.
Nên phải khớp theo cụm đầy đủ trước, chỉ bỏ từ sở hữu khi không còn cách phân
biệt; nhiều máy khớp → trả '' để bot HỎI LẠI, không đoán bừa.
"""
from __future__ import annotations

import unittest

from services.agent import capabilities as caps


def _may(name, connected=True, label=None):
    d = {"name": name, "connected": connected}
    if label:
        d["label"] = label
    return d


class TestMotMay(unittest.TestCase):
    DS = [_may("laptop"), _may("case-win", connected=False)]

    def test_lay_nguyen_cum_van_ra_may_tron(self):
        self.assertEqual(caps._tim_thiet_bi("laptop cua toi", self.DS), "laptop")

    def test_co_dau_van_khop(self):
        self.assertEqual(caps._tim_thiet_bi("laptop của tôi", self.DS), "laptop")

    def test_them_tu_may(self):
        self.assertEqual(caps._tim_thiet_bi("máy laptop", self.DS), "laptop")

    def test_ten_chung_chung_mot_may_dang_noi(self):
        self.assertEqual(caps._tim_thiet_bi("máy tính", self.DS), "laptop")

    def test_may_khac_khong_khop_bay(self):
        # 'case-win' không nối; hỏi 'case-win' → không tự nhận nhầm sang laptop.
        self.assertEqual(caps._tim_thiet_bi("case-win", self.DS), "case-win")


class TestHaiMayTrungTen(unittest.TestCase):
    """Ca người dùng hỏi: 'laptop của tôi' và 'laptop của vợ' cùng nối."""

    DS = [_may("laptop của tôi"), _may("laptop của vợ")]

    def test_cua_toi_ra_dung_may_cua_toi(self):
        self.assertEqual(caps._tim_thiet_bi("laptop của tôi", self.DS),
                         "laptop của tôi")

    def test_khong_dau_van_phan_biet_dung(self):
        self.assertEqual(caps._tim_thiet_bi("laptop cua toi", self.DS),
                         "laptop của tôi")

    def test_cua_vo_ra_dung_may_cua_vo(self):
        self.assertEqual(caps._tim_thiet_bi("laptop của vợ", self.DS),
                         "laptop của vợ")

    def test_laptop_tron_thi_map_mo_tra_rong(self):
        # Không đủ để phân biệt → '' → handler hỏi lại, KHÔNG đoán bừa.
        self.assertEqual(caps._tim_thiet_bi("laptop", self.DS), "")


class TestUuTienMayDangNoi(unittest.TestCase):
    def test_chi_lay_may_dang_noi_khi_trung_ten(self):
        ds = [_may("laptop", connected=False), _may("laptop", connected=True)]
        # Hai máy tên 'laptop', chỉ một đang nối → không mập mờ ở nhóm đang nối.
        self.assertEqual(caps._tim_thiet_bi("laptop", ds), "laptop")


if __name__ == "__main__":
    unittest.main()
