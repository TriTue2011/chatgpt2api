"""Hai lỗ leo thang quyền, dựng lại đúng cách khai thác.

Rà soát 04/08 dựng được cả hai trên mã đang chạy:

1. Telegram xác định admin CHỈ bằng `chat_id`. Khai một NHÓM làm admin thread là
   cấp quyền admin cho MỌI THÀNH VIÊN nhóm đó — thành viên 99 trong nhóm -100
   nhận `is_admin: True`. Quyền đó mở ra chụp webcam, chụp màn hình, tắt máy từ
   xa, xem cả kho media.

2. Đường xử lý Codex `account_deactivated` chạy KHÔNG xét quyền. Bất kỳ ai gõ
   đúng "xóa <email>" khi đang có pending đều kích hoạt được đường xoá thật —
   nó gỡ tài khoản khỏi pool và khỏi danh sách đăng nhập.
"""
from __future__ import annotations

import os
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.telegram_bot as tg  # noqa: E402

NHOM_ADMIN = "-100"
NGUOI_LA = "99"
ADMIN_THAT = "555"


class AdminTheoNGUOIKhongTheoNHOM(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(tg, "_admin_ids_for_bot",
                                   return_value=[NHOM_ADMIN, ADMIN_THAT])
        self.p.start()
        self.addCleanup(self.p.stop)

    def test_thanh_vien_thuong_trong_nhom_admin_KHONG_phai_admin(self):
        """Đây là ca đã dựng lại được: thành viên 99 trong nhóm -100."""
        self.assertFalse(tg._is_admin_chat(NHOM_ADMIN, NGUOI_LA))

    def test_admin_that_trong_nhom_admin_van_la_admin(self):
        self.assertTrue(tg._is_admin_chat(NHOM_ADMIN, ADMIN_THAT))

    def test_nhom_admin_ma_khong_biet_nguoi_gui_thi_TU_CHOI(self):
        """Thiếu thông tin thì fail-closed, không đoán theo hướng cấp quyền."""
        self.assertFalse(tg._is_admin_chat(NHOM_ADMIN, ""))

    def test_chat_1_1_cua_admin_van_la_admin(self):
        """Chat 1-1: chat_id CHÍNH LÀ người dùng nên so chat_id là đủ."""
        self.assertTrue(tg._is_admin_chat(ADMIN_THAT))
        self.assertTrue(tg._is_admin_chat(ADMIN_THAT, ADMIN_THAT))

    def test_chat_la_thi_khong_phai_admin(self):
        for cid in ("-777", "12345", "", None):
            self.assertFalse(tg._is_admin_chat(cid, ADMIN_THAT), cid)

    def test_moi_noi_goi_deu_truyen_nguoi_gui(self):
        """Sửa hàm mà nơi gọi quên truyền người gửi là lỗ mở lại y như cũ."""
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "services" / "telegram_bot.py").read_text("utf-8")
        for dong in src.splitlines():
            if "_is_admin_chat(" in dong and "def _is_admin_chat" not in dong:
                self.assertIn("user_id", dong, dong.strip())


class XoaCodexChiADMIN(unittest.TestCase):
    """Đường xoá tài khoản Codex phải nằm sau chốt quyền."""

    def test_ma_nguon_dat_sau_chot_is_admin(self):
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "services" / "agent" / "orchestrator.py").read_text("utf-8")
        i = src.index("try_resolve_admin_reply")
        truoc = src[max(0, i - 900):i]
        self.assertIn("if is_admin:", truoc)

    def test_nguoi_thuong_khong_cham_toi_resolver(self):
        from services.agent import orchestrator as orch
        goi: list[str] = []

        def _gia(text):
            goi.append(text)
            return "MOCK_DELETED"

        mod = mock.MagicMock()
        mod.try_resolve_admin_reply = _gia
        # Không giả lập vòng model: chỉ cần biết resolver CÓ bị chạm hay không.
        # Lượt có thể hỏng ở bước sau — không sao, chốt quyền nằm ở đầu hàm.
        with mock.patch.dict(sys.modules, {"services.codex_deactivated": mod}), \
             mock.patch.object(orch, "_get_history", return_value=[]), \
             mock.patch.object(orch, "_persist_history"), \
             mock.patch.object(orch.run_journal, "log_run"):
            try:
                orch._orchestrate_locked("xóa a@b.com", "u_thuong", is_admin=False)
            except Exception:
                pass
        self.assertEqual(goi, [], "người thường vẫn chạm được vào đường xoá")


if __name__ == "__main__":
    unittest.main()
