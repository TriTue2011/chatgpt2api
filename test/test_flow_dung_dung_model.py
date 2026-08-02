"""Flow phải tạo video BẰNG ĐÚNG MODEL người dùng chọn, và tài khoản đã kết
luận là bị xóa thì phải NẰM YÊN ở trạng thái 'deactivated'.

Đo thật 02/08 — hai lỗi riêng biệt, cùng một kiểu: một bước im lặng thất bại
rồi phần sau chạy tiếp như không có chuyện gì.

  A. CHỌN MODEL FLOW. Người dùng chọn `flow/veo-3.1-lite` (10 tín dụng). Cả
     chuỗi phần mềm truyền đúng chuỗi đó xuống solver. Nhưng bước đặt model
     trên giao diện lại bấm THẲNG vào chip cài đặt — mà chip là nút bật/tắt, và
     hàng "số bản ghi" ngay trên đã để bảng ở trạng thái MỞ. Cú bấm đó ĐÓNG bảng
     lại. Log lượt kiểm chứng 12:11:

         12:11:13  đã bấm chuột thật vào chip model (mở bảng)
         12:11:14  DANH SÁCH MODEL + TÍN DỤNG = []
         12:11:14  flow_dropdown_skip model=Veo 3.1 - Lite (Trigger not found)
         12:11:14  bảng cài đặt đã đóng — mở lại (trước khi kiểm chứng)
         12:11:16  ĐANG CHỌN = {... 'thoi_luong': '8s' ...}

     Model không bao giờ được đặt → Flow chạy bằng model còn sót của lượt trước.
     Hàng thời lượng '8s' còn nguyên là dấu vết: CHỈ Omni Flash mới có hàng đó.
     Kết quả: Omni Flash 8 giây, 12 tín dụng, cho một yêu cầu Lite 10 tín dụng.

     Ba chỗ hỏng nối nhau: (1) bấm chip đóng nhầm bảng; (2) `_set_dropdown` không
     trả kết quả nên người gọi không biết nó trượt; (3) bộ kiểm chứng chỉ soi
     thời lượng + số lượng, bỏ qua đúng cái đắt nhất là model.

  B. TRẠNG THÁI 'deactivated'. Đánh dấu tay lúc 12:08 cho benbap2011@gmail.com;
     job refresh_accounts gọi `remove_invalid_token` ghi đè ngược về 'error' rồi
     spawn tiếp một lượt khôi phục. Đánh dấu mà không bền thì vô nghĩa.

Test đọc mã nguồn (bỏ dòng chú thích trước khi soi — chú thích bản vá nhắc lại
hành vi cũ để giải thích): thứ cần khoá là các QUYẾT ĐỊNH rẽ nhánh. Dựng
Playwright + giao diện Flow giả cho việc này là đổi phép đo chắc chắn lấy phép
đo phụ thuộc mock.
"""
from __future__ import annotations

import pathlib
import unittest

GOC = pathlib.Path(__file__).resolve().parents[1]


def _code(p: pathlib.Path) -> str:
    return "\n".join(l for l in p.read_text("utf-8").splitlines()
                     if not l.lstrip().startswith("#"))


def _khuc(code: str, tu: str, den: str) -> str:
    i = code.index(tu)
    return code[i:code.index(den, i)]


class TestFlowDatDungModel(unittest.TestCase):
    def setUp(self):
        self.code = _code(GOC / "captcha-solver" / "src" / "solvers" / "flow_google.py")

    def test_khong_bam_chip_lam_dong_bang(self):
        """Bước model phải dùng _bao_dam_bang_mo (chỉ mở khi đang đóng)."""
        khuc = _khuc(self.code, "_MODEL_LABEL = {", "_set_dropdown(page, model_lbl")
        self.assertIn('_bao_dam_bang_mo("trước khi chọn model")', khuc)
        self.assertNotIn('"chip model (mở bảng)", _JS_CHIP', khuc)

    def test_set_dropdown_bao_duoc_thanh_bai(self):
        """Bản lồng dùng cho video phải trả True/False ở MỌI nhánh."""
        khuc = _khuc(self.code, "async def _set_dropdown(pg: Page",
                     "async def _bao_dam_bang_mo")
        self.assertIn("return False", khuc)       # không tìm thấy trigger / lỗi
        self.assertIn("return True", khuc)        # bấm trúng mục trong menu
        self.assertIn("return clicked", khuc)     # chỉ bấm thẳng ở bước 1
        # Không còn `return` trống — nó chính là chỗ nuốt mất kết quả.
        self.assertNotIn("\n                        return\n", khuc)

    def test_ket_qua_dat_model_duoc_dung(self):
        self.assertIn("_dat_model_ok = await _set_dropdown(page, model_lbl, \"model\")",
                      self.code)

    def test_lech_model_thi_dung_truoc_khi_bam_tao(self):
        i = self.code.index("model_mismatch")
        khuc = self.code[i - 700:i + 400]
        self.assertIn('"state": "failed"', khuc)
        self.assertIn("_chuan(model_lbl) not in _chuan(_model_that)", khuc)
        # Phải dừng TRƯỚC khi bấm Tạo, nếu không thì tín dụng đã tiêu mất rồi.
        self.assertLess(i, self.code.index("flow_video_submit"))

    def test_khong_doc_duoc_model_cung_dung(self):
        """Đặt trượt VÀ không đọc được model đang chọn → dừng, đừng đoán."""
        self.assertIn("model_unverified", self.code)
        i = self.code.index("model_unverified")
        self.assertLess(i, self.code.index("flow_video_submit"))


class TestDeactivatedNamYen(unittest.TestCase):
    def test_khong_ha_deactivated_ve_error(self):
        code = _code(GOC / "services" / "account_service.py")
        khuc = _khuc(code, "def remove_invalid_token", "def _spawn_dead_recovery")
        self.assertIn('== "deactivated"', khuc)
        # Nhánh bỏ qua phải nằm TRƯỚC mọi lệnh hạ status về 'error'.
        self.assertLess(khuc.index('== "deactivated"'),
                        khuc.index('{"status": "error", "quota": 0}'))

    def test_khong_spawn_khoi_phuc_cho_deactivated(self):
        code = _code(GOC / "services" / "codex_error_recovery_scheduler.py")
        khuc = _khuc(code, "def schedule_dead_account_recovery", "def _scan_and_recover")
        self.assertIn('== "deactivated"', khuc)
        self.assertIn("dead_recovery_skip_deactivated", khuc)
        # Bỏ qua TRƯỚC khi dựng thread chạy cả thang T0–T3.
        self.assertLess(khuc.index("dead_recovery_skip_deactivated"),
                        khuc.index("threading.Thread"))


if __name__ == "__main__":
    unittest.main()
