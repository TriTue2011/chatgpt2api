"""Bộ chạy thử code — chốt cả tính đúng lẫn ranh giới an toàn.

Đây là thứ THỰC THI code do model sinh, nên test phải khoá được ba điều:
1. Chạy đúng: code tốt thì ok, code sai thì báo lỗi chỉ đúng dòng.
2. Bỏ qua đúng: code không tự đủ (import services/…) KHÔNG được coi là lỗi —
   nếu coi là lỗi thì con sẽ bị bắt sửa một ImportError giả và làm hỏng code
   đang đúng.
3. KHÔNG rò secret: tiến trình con không được thấy biến môi trường của bot
   (API key Gemini/Agnes/NVIDIA, mật khẩu Postgres).
"""
from __future__ import annotations

import os
import unittest

from services import code_runner as cr


class TestBocCode(unittest.TestCase):
    def test_lay_trong_khoi_ba_dau_nhay(self):
        t = "Đây là code:\n```python\nx = 1\n```\nxong."
        self.assertEqual(cr.boc_code_python(t), "x = 1")

    def test_noi_nhieu_khoi(self):
        """Model hay tách import và hàm thành hai khối — lấy một khối là mất nửa."""
        t = "```python\nimport math\n```\nvà\n```python\ndef f():\n    return math.pi\n```"
        ra = cr.boc_code_python(t)
        self.assertIn("import math", ra)
        self.assertIn("def f()", ra)

    def test_khong_co_fence_van_nhan_ra_code(self):
        self.assertIn("def f", cr.boc_code_python("def f():\n    return 1"))

    def test_van_xuoi_thi_tra_rong(self):
        self.assertEqual(cr.boc_code_python("Em nghĩ nên dùng vòng lặp for ạ."), "")


class TestCoTheChay(unittest.TestCase):
    def test_code_thuong_thi_duoc(self):
        duoc, _ = cr.co_the_chay("def f(x):\n    return x + 1\nassert f(1) == 2")
        self.assertTrue(duoc)

    def test_tu_choi_code_cua_du_an(self):
        for c in ("from services.config import config",
                  "import services.agent",
                  "from utils.log import logger"):
            duoc, ly_do = cr.co_the_chay(c + "\nx = 1")
            self.assertFalse(duoc, c)
            self.assertIn("tự đủ", ly_do)

    def test_tu_choi_cham_he_thong(self):
        for c in ("import subprocess", "os.system('ls')", "shutil.rmtree('/tmp/x')"):
            duoc, _ = cr.co_the_chay(c)
            self.assertFalse(duoc, c)

    def test_tu_choi_cho_nguoi_go(self):
        duoc, _ = cr.co_the_chay("x = input('nhap: ')")
        self.assertFalse(duoc)

    def test_tu_choi_rong(self):
        self.assertFalse(cr.co_the_chay("")[0])
        self.assertFalse(cr.co_the_chay("   ")[0])


class TestChay(unittest.TestCase):
    def test_code_dung_thi_ok(self):
        kq = cr.chay("def f(x):\n    return x + 1\nassert f(1) == 2\nprint('xong')")
        self.assertTrue(kq["da_chay"])
        self.assertTrue(kq["ok"], kq)
        self.assertIn("xong", kq["stdout"])
        self.assertEqual(kq["chan_doan"], "")

    def test_loi_cu_phap_bi_bat(self):
        kq = cr.chay("def f(:\n    return 1")
        self.assertTrue(kq["da_chay"])
        self.assertFalse(kq["ok"])
        self.assertIn("SyntaxError", kq["chan_doan"])

    def test_assert_sai_bi_bat_va_chi_dung_dong(self):
        kq = cr.chay("def f(x):\n    return x + 2\nassert f(1) == 2")
        self.assertFalse(kq["ok"])
        self.assertIn("AssertionError", kq["chan_doan"])
        self.assertIn("dòng 3", kq["chan_doan"])

    def test_name_error_bi_bat(self):
        """Đọc code rất dễ bỏ sót lỗi này — chạy thì thấy ngay."""
        kq = cr.chay("def f():\n    return chua_dinh_nghia\nf()")
        self.assertFalse(kq["ok"])
        self.assertIn("NameError", kq["chan_doan"])

    def test_vong_lap_vo_han_bi_diet(self):
        kq = cr.chay("x = 0\nwhile x >= 0:\n    x += 1", han_giay=3)
        self.assertTrue(kq["da_chay"])
        self.assertFalse(kq["ok"])
        self.assertIn("vòng lặp", kq["chan_doan"])

    def test_bo_qua_thi_khac_voi_that_bai(self):
        """da_chay=False nghĩa là BỎ QUA — bên gọi không được bắt con sửa."""
        kq = cr.chay("from services.config import config\nprint(config)")
        self.assertFalse(kq["da_chay"])
        self.assertEqual(kq["chan_doan"], "")
        self.assertTrue(kq["ly_do_bo_qua"])


class TestKhongRoSecret(unittest.TestCase):
    def test_moi_truong_con_khong_co_bien_cua_bot(self):
        """Một dòng print(os.environ) trong code sinh ra là đủ rò hết key vào
        log rồi vào ngữ cảnh model. Phải chặn từ gốc: không kế thừa môi trường."""
        os.environ["BI_MAT_THU_NGHIEM"] = "khoa-that-cua-bot-12345"
        try:
            kq = cr.chay("import os\nprint(sorted(os.environ.keys()))")
            self.assertTrue(kq["ok"], kq)
            self.assertNotIn("BI_MAT_THU_NGHIEM", kq["stdout"])
            self.assertNotIn("khoa-that-cua-bot-12345", kq["stdout"])
        finally:
            os.environ.pop("BI_MAT_THU_NGHIEM", None)

    def test_moi_truong_sach_khong_chua_key(self):
        env = cr._moi_truong_sach()
        for k in env:
            self.assertNotIn("KEY", k.upper())
            self.assertNotIn("TOKEN", k.upper())
            self.assertNotIn("PASSWORD", k.upper())
        self.assertIn("PATH", env)

    def test_thu_muc_tam_bi_xoa_sau_khi_chay(self):
        kq = cr.chay("import os\nprint(os.getcwd())")
        self.assertTrue(kq["ok"], kq)
        duong_dan = kq["stdout"].strip().splitlines()[-1]
        self.assertFalse(os.path.exists(duong_dan), f"còn sót thư mục {duong_dan}")


if __name__ == "__main__":
    unittest.main()
