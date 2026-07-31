"""Chia việc cho nhiều con + vai tra cứu.

Tài liệu cảnh báo rõ: chia SAI thì phần lợi bị ăn hết ở bước GHÉP — "trông như
song song" rồi vỡ khi ghép (blog.appxlab.io về git worktree; tổng quan
arXiv 2604.16321). Nên test ở đây nặng về phía TỪ CHỐI CHIA: mặc định không
chia, chỉ chia khi chính bố đánh dấu phần và tự khai độc lập.
"""
from __future__ import annotations

import unittest
from unittest import mock

from services import code_pipeline as cp


KE_HOACH_CHIA = """- Làm ba hàm rời nhau.

### PHẦN 1: chuẩn hoá tên
- bỏ khoảng trắng, viết hoa chữ đầu

### PHẦN 2: kiểm tra số điện thoại
- regex 10 số, bắt đầu bằng 0

### PHẦN 3: đổi ngày sang dd/mm/yyyy
- nhận yyyy-mm-dd

ĐỘC LẬP: có
CẦN TRA CỨU: không
"""

KE_HOACH_DINH_NHAU = KE_HOACH_CHIA.replace("ĐỘC LẬP: có", "ĐỘC LẬP: không")


class TestTachPhan(unittest.TestCase):
    def test_chia_khi_bo_khai_doc_lap(self):
        phan = cp.tach_phan(KE_HOACH_CHIA)
        self.assertEqual(len(phan), 3)
        self.assertEqual(phan[0]["ten"], "chuẩn hoá tên")
        self.assertIn("regex", phan[1]["viec"])

    def test_khong_chia_khi_bo_khai_dinh_nhau(self):
        self.assertEqual(cp.tach_phan(KE_HOACH_DINH_NHAU), [])

    def test_khong_chia_khi_bo_khong_khai_gi(self):
        """Không có dòng ĐỘC LẬP → mặc định KHÔNG chia. An toàn là mặc định."""
        self.assertEqual(cp.tach_phan(KE_HOACH_CHIA.replace("ĐỘC LẬP: có", "")), [])

    def test_khong_chia_khi_it_hon_nguong(self):
        """2 phần thì gọi song song 2 model tốn gần bằng 1 model làm cả, mà thêm
        rủi ro ghép — không đáng."""
        hai = """### PHẦN 1: a
- x
### PHẦN 2: b
- y
ĐỘC LẬP: có
"""
        self.assertEqual(cp.tach_phan(hai), [])

    def test_gach_dau_dong_thuong_khong_bi_coi_la_phan(self):
        """Kế hoạch thường (chỉ gạch đầu dòng) tuyệt đối không được tự chia."""
        thuong = "- bước 1\n- bước 2\n- bước 3\n- bước 4\nĐỘC LẬP: có\n"
        self.assertEqual(cp.tach_phan(thuong), [])

    def test_chan_so_phan_toi_da(self):
        nhieu = "".join(f"### PHẦN {i}: p{i}\n- viec {i}\n" for i in range(1, 9))
        phan = cp.tach_phan(nhieu + "ĐỘC LẬP: có\n")
        self.assertLessEqual(len(phan), cp.TRAN_PHAN)


class TestGopCode(unittest.TestCase):
    def test_gop_bo_import_trung(self):
        a = "import re\n\ndef f():\n    return re.escape('a')"
        b = "import re\n\ndef g():\n    return 2"
        ra = cp.gop_code([a, b])
        self.assertEqual(ra.count("import re"), 1, ra)
        self.assertIn("def f()", ra)
        self.assertIn("def g()", ra)

    def test_import_len_dau(self):
        ra = cp.gop_code(["def f():\n    return 1", "import math\ndef g():\n    return math.pi"])
        self.assertTrue(ra.lstrip().startswith("import math"), ra)

    def test_bo_khoi_rong(self):
        ra = cp.gop_code(["", "   ", "def f():\n    return 1"])
        self.assertIn("def f", ra)

    def test_code_gop_lai_chay_duoc(self):
        """Chốt bằng cách CHẠY THẬT code sau khi ghép — ghép sai thì lộ ngay."""
        from services import code_runner
        ra = cp.gop_code([
            "import re\ndef ten(s):\n    return re.sub(r'\\s+', ' ', s).strip()",
            "import re\ndef sdt(s):\n    return bool(re.fullmatch(r'0\\d{9}', s))",
            "def cong(a, b):\n    return a + b",
        ])
        kq = code_runner.chay(ra + "\nassert ten('  a   b ') == 'a b'\n"
                                   "assert sdt('0912345678')\nassert cong(1, 2) == 3\n")
        self.assertTrue(kq["ok"], kq)


class TestCanTraCuu(unittest.TestCase):
    def test_lay_duoc_truy_van(self):
        self.assertEqual(cp.can_tra_cuu("CẦN TRA CỨU: cách dùng httpx timeout"),
                         "cách dùng httpx timeout")

    def test_bo_khai_khong_thi_khong_tra(self):
        for c in ("CẦN TRA CỨU: không", "CẦN TRA CỨU: no", "CẦN TRA CỨU: -"):
            self.assertEqual(cp.can_tra_cuu(c), "", c)

    def test_khong_khai_thi_khong_tra(self):
        self.assertEqual(cp.can_tra_cuu("- bước 1\n- bước 2"), "")


class TestTraCuuKeHoach(unittest.TestCase):
    def test_khong_can_tra_thi_khong_goi_search(self):
        with mock.patch("services.search_service.search_service") as ss:
            ra = cp.tra_cuu_ke_hoach("- bước 1", "yêu cầu", luu_wiki=False)
        self.assertEqual(ra, "")
        ss.search_all.assert_not_called()

    def test_co_ket_qua_thi_tra_ghi_chu(self):
        gia = [{"title": "httpx timeout", "snippet": "dùng timeout=10", "url": "https://x.tld/a"}]
        with mock.patch("services.search_service.search_service") as ss:
            ss.search_all.return_value = gia
            ra = cp.tra_cuu_ke_hoach("CẦN TRA CỨU: httpx timeout", "yêu cầu", luu_wiki=False)
        self.assertIn("httpx timeout", ra)
        self.assertIn("https://x.tld/a", ra)

    def test_search_loi_thi_tra_rong_khong_nem(self):
        """Tra cứu lỗi KHÔNG được làm chết cả lượt viết code."""
        with mock.patch("services.search_service.search_service") as ss:
            ss.search_all.side_effect = RuntimeError("mạng chết")
            ra = cp.tra_cuu_ke_hoach("CẦN TRA CỨU: abc", "yêu cầu", luu_wiki=False)
        self.assertEqual(ra, "")

    def test_khong_ket_qua_thi_tra_rong(self):
        with mock.patch("services.search_service.search_service") as ss:
            ss.search_all.return_value = []
            self.assertEqual(
                cp.tra_cuu_ke_hoach("CẦN TRA CỨU: abc", "yêu cầu", luu_wiki=False), "")


if __name__ == "__main__":
    unittest.main()
