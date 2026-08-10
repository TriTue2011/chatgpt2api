"""Ảnh Flow phải ra ĐÚNG khung hình đã xin, hoặc dừng — không im lặng ra ảnh dọc.

Lỗi đo được 10/08/2026: người dùng xin 16:9 nhưng nhận ảnh 9:16. Nguyên nhân là
một chuỗi im lặng, không lỗi nào nổi lên:

  1. Flow NHỚ lựa chọn theo từng hồ sơ trình duyệt. Một lượt tạo VIDEO dọc để
     dropdown khung hình lại ở 9:16.
  2. Lượt tạo ẢNH sau đó gọi `_set_dropdown(page, "16:9", "aspect")`. Hàm này
     có nhánh trả về "đã bấm một cái gì đó" chứ không phải "đã chọn đúng mục",
     và khi không tìm ra trigger thì chỉ ghi log rồi trả False.
  3. Người gọi KHÔNG đọc kết quả, cũng không đọc ngược chip đang hiện — mã cũ
     ghi thẳng lý lẽ "bấm hụt tỷ lệ chỉ ra ảnh sai kích thước, khó chịu nhưng
     rẻ". Nên Flow dựng bằng 9:16 còn sót lại của lượt trước.

Bước model ngay bên dưới đã kiểm chứng kiểu này từ 02/08 (xem
`test_flow_dung_dung_model.py`); tỷ lệ thì không, và đó là toàn bộ khoảng trống.

Test đọc mã nguồn, bỏ dòng chú thích trước khi soi — chú thích bản vá có nhắc
lại hành vi cũ để giải thích, soi cả chú thích là đo nhầm.
"""
from __future__ import annotations

import pathlib
import unittest

GOC = pathlib.Path(__file__).resolve().parents[1]


def _code(p: pathlib.Path) -> str:
    return "\n".join(l for l in p.read_text("utf-8").splitlines()
                     if not l.lstrip().startswith("#"))


class TyLeKhungHinhPhaiDuocKiemChung(unittest.TestCase):
    def setUp(self):
        self.code = _code(GOC / "captcha-solver" / "src" / "solvers" / "flow_google.py")

    def test_co_doc_nguoc_ty_le_dang_chon(self):
        """Đặt xong phải ĐỌC LẠI chip, không tin vào giá trị trả về của hàm bấm."""
        self.assertIn("async def _doc_ty_le_dang_chon", self.code)
        self.assertIn("_ty_le_that = await _doc_ty_le_dang_chon()", self.code)

    def test_bam_hut_thi_bam_lai_truoc_khi_chiu_thua(self):
        """Một lần trượt thường do menu chưa render xong — thử lại rẻ hơn là hỏng."""
        i = self.code.index("_ty_le_that = await _doc_ty_le_dang_chon()")
        khuc = self.code[i - 400:i + 200]
        self.assertIn("for _lan in range(2):", khuc)
        self.assertIn('await _set_dropdown(page, aspect_label, "aspect")', khuc)

    def test_lech_ty_le_thi_dung_TRUOC_khi_bam_tao(self):
        """Bấm Tạo rồi mới phát hiện sai là đã tiêu tín dụng cho ảnh bỏ đi."""
        i = self.code.index("if _ty_le_that and _ty_le_that != aspect_label:")
        self.assertIn("raise RuntimeError", self.code[i:i + 400])
        self.assertLess(i, self.code.index("await _click_generate()"))

    def test_doc_khong_ra_thi_van_di_tiep(self):
        """Giao diện đổi làm đọc hụt chip thì không được chặn cả tính năng —
        chỉ chặn khi ĐỌC ĐƯỢC và thấy lệch, y như nhánh model."""
        i = self.code.index("if not _ty_le_that or _ty_le_that == aspect_label:")
        self.assertIn("break", self.code[i:i + 120])
        # Điều kiện chặn phải có vế `_ty_le_that and` — thiếu nó là chuỗi rỗng
        # cũng bị coi là lệch, và mọi lượt tạo ảnh chết theo.
        self.assertIn("if _ty_le_that and _ty_le_that != aspect_label:", self.code)

    def test_khong_con_ly_le_bo_qua_ty_le(self):
        """Câu 'tỷ lệ bấm hụt thì rẻ' từng là lý do bỏ kiểm — nó sai, và đã sửa."""
        self.assertNotIn("chỉ ra ảnh sai kích thước — khó chịu nhưng rẻ", self.code)


class GhiLaiModelThatDaDung(unittest.TestCase):
    """Combo 'AI image' gồm nhiều model chênh nhau xa; nhật ký phải ghi model
    THẬT đã dựng, không phải mỗi tên combo."""

    def setUp(self):
        self.code = _code(GOC / "services" / "protocol" / "openai_v1_image_generations.py")

    def test_moi_luot_tao_anh_deu_khai_provider_va_model(self):
        self.assertIn("note_provider_account(route.provider, model=route.model)",
                      self.code)

    def test_khai_TRUOC_khi_goi_adapter(self):
        """Khai sau khi adapter chạy thì lượt nào hỏng giữa chừng sẽ mất dấu —
        mà đó đúng là những lượt cần truy nhất."""
        i = self.code.index("note_provider_account(route.provider, model=route.model)")
        j = self.code.index("def _handle_single_image")
        self.assertLess(j, i)
        self.assertLess(i, self.code.index("prompt = str(body.get(\"prompt\")", i))


if __name__ == "__main__":
    unittest.main()
