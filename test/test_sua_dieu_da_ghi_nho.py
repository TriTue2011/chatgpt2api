"""Người dùng phải SỬA ĐƯỢC điều bot đã ghi nhớ.

Bộ chặn trùng của trí nhớ so theo độ giống token (Jaccard, ngưỡng 0,82). Nhưng
một lời dặn ĐƯỢC SỬA luôn gần trùng với chính lời dặn nó thay thế — càng nhắc
lại trung thực thì càng chắc bị coi là trùng rồi bỏ đi TRONG IM LẶNG. Hệ quả:
người dùng không thể đổi điều bot đã nhớ, mà bot vẫn đáp "Dạ được anh".

Đo thật 01/08: sau khi nhận bản tin, người dùng nói "Bỏ tóm tắt đi". Câu bot định
lưu giống dòng cũ (dòng có "có tóm tắt ngắn") tới 0,955 — vượt 0,82 nên KHÔNG
lưu gì. Lượt tin tức sau đó vẫn còn tóm tắt, và không ai biết vì sao.

Cách chữa: tách TRÙNG khỏi CẬP NHẬT.
  * ≥ 0,97  → trùng y nguyên, không lưu lại.
  * 0,82–0,97 → bản CẬP NHẬT: xoá dòng cũ, ghi dòng mới.
  * < 0,82  → điều mới, ghi thêm.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from services.agent import state


class _TriNhoTam(unittest.TestCase):
    """Mỗi test chạy trên MỘT file trí nhớ riêng — không đụng dữ liệu thật."""

    def setUp(self) -> None:
        self.thu_muc = Path(tempfile.mkdtemp())
        self.tep = self.thu_muc / "MEMORY.md"
        self.tep.write_text("", encoding="utf-8")
        self._goc = (state._MEMORY_FILE, state._MEMORY_DB_PATH, state._mem_conn)
        state._MEMORY_FILE = self.tep
        state._MEMORY_DB_PATH = self.thu_muc / "m.sqlite"
        # `_mem_conn` là DICT (đường dẫn index → connection) từ khi trí nhớ tách
        # theo phạm vi — mỗi phạm vi một index riêng. Gán None ở đây thì mọi lời
        # gọi FTS ném AttributeError và bị try/except nuốt: test vẫn xanh mà
        # nhánh index không còn được chạy lần nào.
        state._mem_conn = {}

    def tearDown(self) -> None:
        state._MEMORY_FILE, state._MEMORY_DB_PATH, state._mem_conn = self._goc
        shutil.rmtree(self.thu_muc, ignore_errors=True)

    def _dong(self) -> list[str]:
        return [d for d in self.tep.read_text(encoding="utf-8").splitlines() if d.strip()]


class TestSuaLoiDan(_TriNhoTam):
    CU = ("Khi người dùng hỏi Tin tức hôm nay, trình bày không link, không ảnh; "
          "chia các mục Thể thao, Kinh tế, Xã hội, Giáo dục, Y tế; "
          "mỗi mục đúng 3 tin dạng gạch đầu dòng, có tóm tắt ngắn.")

    def test_cap_nhat_thi_THAY_dong_cu(self):
        """Ca thật: đổi 'có tóm tắt' thành 'không tóm tắt'."""
        self.assertEqual(state.nho_hoac_cap_nhat(self.CU), "them")
        moi = self.CU.replace("có tóm tắt ngắn", "KHÔNG tóm tắt, chỉ tiêu đề")
        self.assertEqual(state.nho_hoac_cap_nhat(moi), "cap_nhat")
        dong = self._dong()
        self.assertEqual(len(dong), 1, "cập nhật không được làm phình trí nhớ")
        self.assertIn("KHÔNG tóm tắt", dong[0])
        self.assertNotIn("có tóm tắt ngắn", dong[0])

    def test_trung_y_nguyen_thi_khong_luu_lai(self):
        state.nho_hoac_cap_nhat(self.CU)
        self.assertEqual(state.nho_hoac_cap_nhat(self.CU), "trung")
        self.assertEqual(len(self._dong()), 1)

    def test_dieu_hoan_toan_moi_thi_ghi_them(self):
        state.nho_hoac_cap_nhat(self.CU)
        self.assertEqual(
            state.nho_hoac_cap_nhat("Anh thích uống cà phê sữa đá buổi sáng."),
            "them")
        self.assertEqual(len(self._dong()), 2, "điều mới không được thay điều cũ")

    def test_rong_thi_khong_ghi_gi(self):
        self.assertEqual(state.nho_hoac_cap_nhat("   "), "trung")
        self.assertEqual(self._dong(), [])

    def test_tri_nho_trong_thi_ghi_binh_thuong(self):
        self.assertEqual(state.nho_hoac_cap_nhat("Anh tên là Việt."), "them")
        self.assertEqual(len(self._dong()), 1)


class TestXoaDongGiuFtsKhop(_TriNhoTam):
    """Xoá dòng phải xoá cả trong FTS index, không thì tra cứu trí nhớ vẫn ra
    dòng đã bị thay — tệ hơn cả không xoá, vì hai nguồn nói khác nhau."""

    def test_fts_khong_con_dong_da_thay(self):
        # Câu phải ĐỦ DÀI như lời dặn thật. Với câu ngắn, đổi 3 từ trong 13 làm
        # độ giống tụt dưới 0,82 nên hệ thống coi là điều MỚI và giữ cả hai dòng
        # — chấp nhận được (dòng mới nằm sau nên thắng trong prompt), nhưng không
        # phải ca cần kiểm ở đây.
        cu = ("Khi người dùng hỏi Tin tức hôm nay, trình bày không link, không "
              "ảnh; chia các mục Thể thao, Kinh tế, Xã hội, Giáo dục, Y tế; mỗi "
              "mục đúng 3 tin dạng gạch đầu dòng, có tóm tắt ngắn.")
        state.nho_hoac_cap_nhat(cu)
        moi = cu.replace("có tóm tắt ngắn", "bỏ tóm tắt")
        self.assertEqual(state.nho_hoac_cap_nhat(moi), "cap_nhat")
        try:
            db = state._mem_db()
            con = [r[0] for r in db.execute("SELECT line FROM memory_lines").fetchall()]
        except Exception as exc:                       # pragma: no cover
            self.skipTest(f"không mở được FTS: {exc}")
        self.assertFalse(any("có tóm tắt ngắn" in x for x in con),
                         "dòng cũ vẫn còn trong FTS")
        self.assertTrue(any("bỏ tóm tắt" in x for x in con))


class TestDoGiong(_TriNhoTam):
    def test_tra_ve_dong_khop_nhat(self):
        state.nho_hoac_cap_nhat("Anh thích cà phê sữa đá vào buổi sáng sớm.")
        state.nho_hoac_cap_nhat("Con trai anh đang học lớp hai ở Hà Nội.")
        ti_le, dong = state._do_giong("Anh thích cà phê sữa đá buổi sáng.")
        self.assertGreater(ti_le, 0.5)
        self.assertIn("cà phê", dong)

    def test_tri_nho_trong_thi_khong_vo(self):
        self.assertEqual(state._do_giong("gì đó"), (0.0, ""))


if __name__ == "__main__":
    unittest.main()
