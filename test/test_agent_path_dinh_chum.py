"""Device agent: --path bị dính chùm bởi lỗi quoting Windows phải tự tách lại.

Lỗi thật, người dùng báo 30/07 (case-win, khai ``-Paths "D:\\","E:\\"``):

    ngoài phạm vi cho phép của thiết bị này (D:\\" --path E:")

Installer sinh ``--path "D:\\" --path "E:\\"``, nhưng quy tắc dòng lệnh Windows
(MSVCRT) coi ``\\"`` là escape dấu nháy → argv nhận MỘT giá trị rác
``D:" --path E:"``. Guard không khớp gì, mọi lệnh bị chặn, còn thông báo lỗi thì
in nguyên chuỗi rác làm người đọc tưởng cấu hình "lệch giữa D:\\ và E:\\".

Chỉ path kết thúc bằng backslash (gốc ổ đĩa) dính — ``D:\\Data`` không sao, nên
bug nằm im tới khi có người khai đúng gốc ổ.

Hai tầng vá, khoá cả hai:
  · installer nhân đôi backslash cuối (``"D:\\\\"`` → parse đúng ``D:\\``);
  · agent tự tách giá trị dính chùm — máy ĐÃ CÀI bản hỏng tự lành khi agent
    được tải bản mới, không cần cài lại.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
                       / "deploy" / "device_agent"))
import c2a_agent as ag  # noqa: E402


class TestTachPathDinhChum(unittest.TestCase):
    def test_ca_that_tu_case_win(self):
        """Đúng chuỗi rác đã đo được — phải tách lại thành D:\\ và E:\\."""
        self.assertEqual(ag._sua_path_dinh_chum(['D:" --path E:"']),
                         ["D:\\", "E:\\"])

    def test_goc_o_dia_khong_co_backslash_van_chuan_hoa(self):
        """`D:` trần là đường dẫn TƯƠNG ĐỐI theo CWD của ổ D trên Windows —
        resolve ra sai chỗ, phải thành `D:\\`."""
        self.assertEqual(ag._sua_path_dinh_chum(["D:"]), ["D:\\"])

    def test_path_binh_thuong_giu_nguyen(self):
        self.assertEqual(
            ag._sua_path_dinh_chum(["D:\\Data", "/home/me/project"]),
            ["D:\\Data", "/home/me/project"])

    def test_ba_path_dinh_chum(self):
        self.assertEqual(
            ag._sua_path_dinh_chum(['C:" --path D:" --path E:"']),
            ["C:\\", "D:\\", "E:\\"])

    def test_rong_va_khoang_trang_bi_bo(self):
        self.assertEqual(ag._sua_path_dinh_chum(["", "  "]), [])

    def test_installer_nhan_doi_backslash_cuoi(self):
        src = (pathlib.Path(__file__).resolve().parents[1] / "deploy"
               / "device_agent" / "install-windows.ps1").read_text("utf-8")
        self.assertIn(r"-replace '(\\+)$', '$1$1'", src)

    def test_main_co_goi_ham_tach(self):
        src = (pathlib.Path(__file__).resolve().parents[1] / "deploy"
               / "device_agent" / "c2a_agent.py").read_text("utf-8")
        i = src.index("def main()")
        self.assertIn("_sua_path_dinh_chum(a.path)", src[i:])


if __name__ == "__main__":
    unittest.main()
