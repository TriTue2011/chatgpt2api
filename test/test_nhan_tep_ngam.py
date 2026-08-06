"""Thread bot NGỒI IM nhận tệp → vẫn hỏi admin để lưu lên kho đám mây.

Chủ máy 07/08: "nếu kiểu ghi nhận ngầm để tải lên thì sao". Làm được, vì câu hỏi
duyệt KHÔNG gửi vào thread nhận tệp mà sang **thread admin** — bot không phải
nói câu nào ở nhóm im lặng.

Cùng nếp với nhật ký: khối ghi nhật ký cũng nằm TRƯỚC cổng im lặng, vì "chỉ
không phản hồi, nhưng nhật ký vẫn phải có" (`zalo_personal` ~2221).

RÀNG BUỘC SỐNG CÒN, và là lý do bài này tồn tại: nhánh ngầm **tuyệt đối không
được gửi tin vào thread nguồn**. Thêm một `send_message` vào đó là thread người
dùng đã tắt tiếng bỗng lên tiếng — hỏng đúng thứ họ tắt đi, và không có test
nào khác bắt được vì mã vẫn chạy trơn.

Soi bằng AST chứ không phải chuỗi: chính docstring của hàm có nhắc chữ
`send_message` để giải thích điều cấm, nên tìm theo chuỗi sẽ báo đỏ oan (đã
vấp đúng bẫy này lúc viết).
"""
from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

_NGUON = GOC / "services" / "zalo_personal.py"


def _ham(ten: str) -> ast.FunctionDef:
    tree = ast.parse(_NGUON.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == ten:
            return n
    raise AssertionError(f"không tìm thấy hàm {ten}")


def _cac_loi_goi(fn: ast.FunctionDef) -> set[str]:
    ra: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name):
                ra.add(n.func.id)
            elif isinstance(n.func, ast.Attribute):
                ra.add(n.func.attr)
    return ra


class NhanTepNgamTests(unittest.TestCase):
    def test_KHONG_gui_tin_vao_thread_nguon(self) -> None:
        goi = _cac_loi_goi(_ham("_nhan_tep_ngam"))
        self.assertNotIn("send_message", goi, (
            "nhánh nhận tệp ngầm gửi tin vào thread nguồn → thread im lặng bỗng "
            "lên tiếng. Mọi phản hồi phải đi đường thread admin."
        ))

    def test_co_giao_tep_cho_khau_hoi_admin(self) -> None:
        goi = _cac_loi_goi(_ham("_nhan_tep_ngam"))
        self.assertIn("_moi_luu_online", goi,
                      "nhận tệp xong mà không giao cho khâu hỏi admin thì vô ích")

    def test_duoc_goi_NGAY_TRUOC_khi_thoat_im_lang(self) -> None:
        """Đặt sau `return` là không bao giờ chạy; đặt trước cổng lọc khác là
        chạy cả ở thread đang hoạt động (tệp bị hỏi lưu hai lần)."""
        src = _NGUON.read_text(encoding="utf-8").splitlines()
        i_goi = next(i for i, d in enumerate(src) if "_nhan_tep_ngam(ev, thread_id)" in d)
        # Dòng ngay trước phải là cổng im lặng, ngay sau phải là return.
        self.assertIn("duoc_giao_tiep", src[i_goi - 1],
                      "lời gọi không nằm ngay trong nhánh cổng im lặng")
        self.assertIn("return", src[i_goi + 1],
                      "sau khi nhận ngầm phải thoát, không chạy tiếp luồng trả lời")


if __name__ == "__main__":
    unittest.main()
