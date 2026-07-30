"""Kho SÁCH không được tự dày thêm bằng văn bản AI viết.

`kb_ask` gọi `maybe_writeback` sau MỖI câu hỏi: kho miss + có ≥3 kết quả web →
nền tổng hợp một bài rồi nạp vào CHÍNH kho đó. Với kho chủ đề chung thì đó là
tính năng. Với kho sách thì nó phá đúng giá trị duy nhất của kho — "sách viết
đúng như vậy".

Đo thật 2026-07-30 trên máy chủ, đọc lại metadata:

    kb_giao_duc      14 đoạn `user_qa/2026-07-23` — nội dung là HƯỚNG DẪN LẬP
                     BÁO CÁO THI CÔNG ("đổ bê tông sàn tầng 12 – Zone 2"), nằm
                     trong kho sách giáo khoa phổ thông.
    kb_giao_duc_sgv  21 đoạn `user_qa/2026-07-30` — bài soạn "Bài 1 Toán lớp 4"
                     do AI viết, sinh ra từ chính mấy câu hỏi thử `ask_sgv`.

Nghĩa là CHỈ CẦN HỎI là kho sách giáo viên dày thêm bằng thứ không phải sách giáo
viên. Ở tầng truy xuất không phân biệt được: cùng collection, cùng hình thức đoạn
văn. Hiện chúng chưa lọt vào câu trả lời CÓ LỌC vì thiếu `grade`/`subject`, nhưng
đó là may chứ không phải thiết kế — `ask_tai_lieu` không có tham số lọc nào.

Test đọc mã nguồn: điều cần khoá là một quyết định (kho sách thì thoát sớm) và nó
nằm gọn ở đầu `maybe_writeback`. Dựng Chroma + pool tổng hợp giả cho một phép đo
như vậy là đổi phép đo chắc chắn thành phép đo phụ thuộc mock.
"""
from __future__ import annotations

import pathlib
import unittest

HUB = pathlib.Path(__file__).resolve().parents[1] / "vn-mcp-hub"
WB = HUB / "src" / "kb" / "writeback.py"


class TestChanWritebackVaoKhoSach(unittest.TestCase):
    def setUp(self):
        self.src = WB.read_text("utf-8")
        # Bỏ dòng chú thích: chú thích của bản vá NHẮC LẠI tên kho để giải thích,
        # nên tìm chuỗi trên nguyên văn sẽ bắt phải chính chú thích đó.
        self.code = "\n".join(l for l in self.src.splitlines()
                              if not l.lstrip().startswith("#"))

    def test_co_danh_sach_kho_sach(self):
        for kho in ("kb_giao_duc", "kb_giao_duc_sgv", "kb_giao_duc_vbt",
                    "kb_giao_duc_tailieu", "kb_giao_duc_slide"):
            self.assertIn(f'"{kho}"', self.code, f"thiếu {kho}")

    def test_thoat_som_truoc_khi_lam_gi(self):
        """Phải chặn TRƯỚC bước tổng hợp — chặn sau là đã tốn lượt gọi model."""
        i = self.code.index("def maybe_writeback")
        j = self.code.index("def _run")
        than = self.code[i:j]
        self.assertIn("_la_kho_sach(collection)", than)
        # Nằm trước chỗ đọc kết quả web / khởi thread.
        self.assertLess(than.index("_la_kho_sach(collection)"),
                        than.index("hybrid_result.get"))

    def test_bo_sach_khac_cung_duoc_chan(self):
        """`kb_giao_duc_bo2`… là SGK của bộ sách khác — cũng là kho sách."""
        self.assertIn("kb_giao_duc_bo", self.code)

    def test_de_lai_dau_trong_log(self):
        """Bỏ qua im lặng thì sau này không ai biết vì sao kho không dày thêm."""
        self.assertIn("writeback_bo_qua_kho_sach", self.code)

    def test_kho_khac_van_write_back_duoc(self):
        """Chỉ chặn kho SÁCH. Chặn hết là bỏ luôn tính năng của kho chủ đề chung."""
        i = self.code.index("def maybe_writeback")
        than = self.code[i:self.code.index("def _run")]
        # Vẫn còn nhánh chạy thật (khởi thread tổng hợp) sau chốt chặn.
        self.assertIn("threading.Thread", than)


class TestHamNhanKhoSach(unittest.TestCase):
    """Nạp thẳng hàm để đo hành vi, không cần cả hub."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("wb_test", WB)
        self.wb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.wb)

    def test_nhan_dung_kho_sach(self):
        for kho in ("kb_giao_duc", "kb_giao_duc_sgv", "kb_giao_duc_vbt",
                    "kb_giao_duc_tailieu", "kb_giao_duc_slide",
                    "kb_giao_duc_bo2", "kb_giao_duc_bo11"):
            self.assertTrue(self.wb._la_kho_sach(kho), kho)

    def test_khong_chan_kho_khac(self):
        for kho in ("kb_nangcao", "xa_hoi", "dien_nuoc", "kb_gia_dinh", ""):
            self.assertFalse(self.wb._la_kho_sach(kho), kho)

    def test_maybe_writeback_kho_sach_khong_lam_gi(self):
        """Truyền kết quả ĐỦ ĐIỀU KIỆN write-back (rag rỗng, 3 web) — kho sách
        vẫn phải thoát, không khởi thread nào."""
        import threading
        truoc = threading.active_count()
        self.wb.maybe_writeback(
            "kb_giao_duc_sgv", "lớp 4 Toán dạy bài 1 thế nào cho hay",
            {"rag": [], "web": [{"title": f"t{i}", "snippet": "s"} for i in range(3)]})
        self.assertEqual(threading.active_count(), truoc)
        # Và không ghi dấu "đã làm" — để nếu sau này bỏ chặn thì vẫn chạy được.
        self.assertEqual(self.wb._done, {})


if __name__ == "__main__":
    unittest.main()
