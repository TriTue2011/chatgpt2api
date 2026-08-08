"""Nhánh agent không nên ghim MỘT model cụ thể — ghim là không có dự phòng.

Lịch sử đã dính cả hai hướng hỏng (xem chú thích đầu branch_health.py):

  * nhánh `vision` từng đặt là NHÃN `'AI vision'` — không phải model id → nằm
    chết lặng hàng tháng;
  * rồi đổi sang `gma/3.1-pro` — một model cụ thể, KHÔNG có dự phòng. Khi
    Gemini kẹt quota thì hết đường, và request rơi xuống một model chỉ-chữ.
    Đó chính là mắt xích đầu của sự cố camera 08/08.

Đường giữa là `<provider>/auto`: provider tự chọn model khả dụng, tự xoay tài
khoản, và chủ máy đổi được trong Settings mà không phải sửa code.
"""
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent.branch_health import _ghim_mot_model  # noqa: E402
from services.agent.branches import BRANCHES  # noqa: E402

# Nhánh chọn NĂNG LỰC riêng, provider không có dạng 'auto' tương đương.
MIEN_TRU = {"image_gen", "video_gen"}


class MacDinhTests(unittest.TestCase):
    def test_nhanh_chu_luc_dung_auto(self):
        for ten in ("vision", "music_gen", "code"):
            mac_dinh = BRANCHES[ten][1]
            self.assertTrue(
                mac_dinh.endswith("/auto") or mac_dinh == "auto",
                f"nhánh {ten} đang ghim '{mac_dinh}' — hết lượt là không có gì thay thế",
            )

    def test_khong_nhanh_nao_tro_vao_nhan_khong_co_tien_to(self):
        """Tái diễn lỗi 'AI vision': nhãn combo ghim trong code.

        Tên combo do chủ máy tự đặt; bản triển khai khác không có combo đó sẽ
        gọi vào hư không.
        """
        for ten, (_nhan, mac_dinh) in BRANCHES.items():
            if not mac_dinh:
                continue        # trống = tắt nhánh, hợp lệ
            self.assertIn("/", mac_dinh,
                          f"nhánh {ten} mặc định '{mac_dinh}' không có tiền tố backend")


class NhanDangGhimCungTests(unittest.TestCase):
    def test_nhan_dung_model_ghim(self):
        for m in ("gma/3.1-pro", "claude/sonnet-5", "flow/veo-3.1-fast", "gma/image"):
            self.assertTrue(_ghim_mot_model(m), f"{m} là model cụ thể, phải bị cảnh báo")

    def test_khong_canh_bao_auto_va_combo(self):
        for m in ("", None, "auto", "gma/auto", "claude/auto", "cx/auto",
                  "AI vision", "AI text"):
            self.assertFalse(_ghim_mot_model(m), f"{m!r} không phải ghim cứng")

    def test_ghim_cung_KHONG_lam_do_ca_bo_kiem(self):
        """Ghim cứng vẫn CHẠY ĐƯỢC — chỉ là không có dự phòng.

        Cho nó làm `ok=False` là biến cảnh báo hữu ích thành tiếng ồn, rồi người
        ta bỏ qua cả lúc bộ kiểm kêu đúng.
        """
        src = (GOC / "services/agent/branch_health.py").read_text(encoding="utf-8")
        i = src.index('"ok": not bad')
        self.assertNotIn("ghim", src[i:i + 60],
                         "ghim cứng không được tính vào trạng thái ok")
        self.assertIn("canh_bao_ghim_cung", src)


if __name__ == "__main__":
    unittest.main()
