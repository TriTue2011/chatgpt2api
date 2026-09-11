"""Hộp thư hai chiều Claude giám sát ↔ chủ máy qua Zalo."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path


class HoiGiamSatTest(unittest.TestCase):
    def setUp(self) -> None:
        import services.hoi_giam_sat as m
        self.m = m
        self._tmp = tempfile.mkdtemp()
        self._duong_that = m._duong
        m._duong = lambda: Path(self._tmp) / "hoi.json"

    def tearDown(self) -> None:
        self.m._duong = self._duong_that

    # ── đặt câu hỏi ────────────────────────────────────────────────────────
    def test_soan_tin_co_danh_so(self) -> None:
        t = self.m.dat_cau_hoi("Sửa file cấm?", ["Cho sửa", "Đừng sửa"])
        self.assertIn("1. Cho sửa", t)
        self.assertIn("2. Đừng sửa", t)
        self.assertIn("cl 1", t, "phải chỉ rõ cách trả lời")

    def test_thieu_lua_chon_thi_khong_soan(self) -> None:
        self.assertEqual(self.m.dat_cau_hoi("Sửa không?", []), "")
        self.assertEqual(self.m.dat_cau_hoi("", ["a", "b"]), "")

    # ── trả lời ────────────────────────────────────────────────────────────
    def test_khong_co_tien_to_thi_KHONG_NHAN(self) -> None:
        """Câu chat thường phải đi tiếp tới bot, không bị module này nuốt."""
        self.m.dat_cau_hoi("Sửa file cấm?", ["Cho sửa", "Đừng sửa"])
        self.assertIsNone(self.m.tra_loi("1"))
        self.assertIsNone(self.m.tra_loi("bật đèn phòng khách"))

    def test_tra_loi_bang_so(self) -> None:
        self.m.dat_cau_hoi("Sửa file cấm?", ["Cho sửa", "Đừng sửa"])
        r = self.m.tra_loi("cl 2")
        self.assertIn("Đừng sửa", r)
        self.assertEqual(self.m.doc_tra_loi()["tra_loi"], "Đừng sửa")

    def test_tra_loi_bang_chu(self) -> None:
        """Gõ thẳng nội dung cũng được, khỏi phải đếm số."""
        self.m.dat_cau_hoi("Sửa file cấm?", ["Cho sửa", "Đừng sửa"])
        self.m.tra_loi("claude cho sửa")
        self.assertEqual(self.m.doc_tra_loi()["tra_loi"], "Cho sửa")

    def test_so_ngoai_pham_vi_thi_hoi_lai(self) -> None:
        self.m.dat_cau_hoi("Sửa file cấm?", ["Cho sửa", "Đừng sửa"])
        r = self.m.tra_loi("cl 9")
        self.assertIn("chưa hiểu", r.lower())
        self.assertEqual(self.m.doc_tra_loi(), {}, "không được ghi bừa")

    def test_CHUA_HOI_ma_tra_loi_thi_IM(self) -> None:
        """Chưa xin ý thì module này không nhận — trả None, KHÔNG đáp lại.

        Chủ máy chốt 10/09/2026: *"chỉ nhận yêu cầu và phản hồi của tôi nếu
        trước đó Claude gửi xin, không phải tôi nhắn tin nào cũng nhận"*. Bản
        cũ đáp "hiện không có câu hỏi nào" — tức bot tự lên tiếng ở kênh chủ
        máy cố ý để im.
        """
        self.assertIsNone(self.m.tra_loi("cl 1"))
        self.assertIsNone(self.m.tra_loi("claude 2"))

    def test_da_tra_loi_roi_thi_thoi_khong_nhan_nua(self) -> None:
        """Trả lời xong là hộp thư hết việc; gõ `cl` lần nữa phải im."""
        self.m.dat_cau_hoi("Sửa file cấm?", ["Cho sửa", "Đừng sửa"])
        self.assertIn("ghi nhận", str(self.m.tra_loi("cl 1")).lower())
        self.m.xoa()
        self.assertIsNone(self.m.tra_loi("cl 1"))

    # ── quá hạn ────────────────────────────────────────────────────────────
    def test_QUA_HAN_thi_bo(self) -> None:
        """Đừng để chủ máy trả lời câu từ hôm kia rồi Claude làm theo bối cảnh cũ."""
        self.m.dat_cau_hoi("Sửa file cấm?", ["Cho sửa", "Đừng sửa"])
        d = self.m._doc()
        d["ts"] = time.time() - self.m._HAN - 60
        self.m._ghi(d)
        r = self.m.tra_loi("cl 1")
        self.assertIn("quá hạn", r.lower())
        self.assertEqual(self.m.doc_tra_loi(), {})

    def test_doc_tra_loi_khi_chua_ai_tra(self) -> None:
        self.m.dat_cau_hoi("Sửa file cấm?", ["Cho sửa", "Đừng sửa"])
        self.assertEqual(self.m.doc_tra_loi(), {})

    # ── một câu một lúc ────────────────────────────────────────────────────
    def test_CAU_MOI_DE_CAU_CU(self) -> None:
        """Hai câu cùng chờ thì trả lời '1' không biết là '1' của câu nào."""
        self.m.dat_cau_hoi("Câu cũ?", ["A", "B"])
        self.m.dat_cau_hoi("Câu mới?", ["X", "Y"])
        self.m.tra_loi("cl 1")
        self.assertEqual(self.m.doc_tra_loi()["cau_hoi"], "Câu mới?")
        self.assertEqual(self.m.doc_tra_loi()["tra_loi"], "X")

    def test_xoa_thi_sach_hop_thu(self) -> None:
        self.m.dat_cau_hoi("Sửa?", ["A", "B"])
        self.m.tra_loi("cl 1")
        self.m.xoa()
        self.assertEqual(self.m.doc_tra_loi(), {})

    # ── không bao giờ ném lỗi ──────────────────────────────────────────────
    def test_ghi_hong_khong_raise(self) -> None:
        # Thư mục cha là một TỆP có sẵn: kể cả root cũng không tạo được thư mục
        # ở đó. "/khong/ton/tai/" thì root tạo được, nên nhánh ghi hỏng không hề
        # được thử (đo 11/09/2026: tệp hoi.json nằm sẵn ở đó trên máy chủ).
        self.m._duong = lambda: Path(__file__) / "hoi.json"
        try:
            self.m.dat_cau_hoi("Sửa?", ["A", "B"])
            self.m.tra_loi("cl 1")
        except Exception as exc:
            self.fail(f"không được ném lỗi: {exc}")


if __name__ == "__main__":
    unittest.main()
