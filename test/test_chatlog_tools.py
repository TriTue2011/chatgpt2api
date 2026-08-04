"""Tool ĐỌC nhật ký nhóm cho agent: `tom_tat_hoi_thoai` + `viec_nhac_toi`.

Kiểm: tool có đăng ký + đúng nhóm quyền; đọc đúng phạm vi (cách ly nhóm khác);
tìm "việc nhắc tới tôi" khớp không dấu; và đọc đi theo «Kết nối bộ nhớ».
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import capabilities, chatlog  # noqa: E402

G1 = "zalop_g1:u9"
G1_U10 = "zalop_g1:u10"
TG = "-100:u5"


class _Moi(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="chatlog-tools-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        chatlog._reset_for_tests(self.tmp / "chatlog.sqlite")
        self.addCleanup(chatlog._reset_for_tests, None)
        self.cfg: dict = {}
        p = mock.patch("services.config.config.get", side_effect=lambda: self.cfg)
        p.start()
        self.addCleanup(p.stop)

    def _bat(self, khoa: str, days: int = 30):
        self.cfg.setdefault("chatlog_settings", {})[khoa] = {
            "enabled": True, "retention_days": days}

    def _goi(self, ten: str, args: dict, user_id: str) -> str:
        return capabilities.CAPABILITIES[ten].handler(args, {"user_id": user_id})["text"]


class DangKy(_Moi):
    def test_hai_tool_co_dang_ky_va_dung_nhom(self):
        for ten in ("tom_tat_hoi_thoai", "viec_nhac_toi"):
            self.assertIn(ten, capabilities.CAPABILITIES)
            self.assertEqual(capabilities.group_of(ten), "memory")


class TomTat(_Moi):
    def test_doc_nhat_ky_hom_nay(self):
        self._bat("zalop:g1")
        chatlog.ghi(G1, sender_name="Chín", text="tối nay ăn gì")
        chatlog.ghi(G1_U10, sender_name="Mười", text="ăn phở đi")
        out = self._goi("tom_tat_hoi_thoai", {}, G1)
        self.assertIn("Chín", out)
        self.assertIn("ăn phở", out)

    def test_chua_bat_thi_bao_trong(self):
        out = self._goi("tom_tat_hoi_thoai", {}, G1)
        self.assertIn("Chưa có nhật ký", out)

    def test_nhom_khac_khong_thay(self):
        self._bat("zalop:g1")
        chatlog.ghi(G1, sender_name="A", text="bí mật nhóm g1")
        out = self._goi("tom_tat_hoi_thoai", {}, TG)
        self.assertNotIn("bí mật", out)


class NhacToi(_Moi):
    def test_tim_khong_dau(self):
        self._bat("zalop:g1")
        chatlog.ghi(G1, sender_name="B", text="@Việt mai 8h họp nhé")
        chatlog.ghi(G1, sender_name="C", text="chuyện không liên quan")
        out = self._goi("viec_nhac_toi", {"ten": "viet"}, G1)
        self.assertIn("họp", out)
        self.assertNotIn("không liên quan", out)

    def test_thieu_ten_thi_hoi_lai(self):
        self._bat("zalop:g1")
        out = self._goi("viec_nhac_toi", {}, G1)
        self.assertIn("tên", out.lower())

    def test_khong_khop_bao_khong_thay(self):
        self._bat("zalop:g1")
        chatlog.ghi(G1, sender_name="B", text="xin chào")
        out = self._goi("viec_nhac_toi", {"ten": "Nam"}, G1)
        self.assertIn("Không thấy", out)


class DiTheoKetNoi(_Moi):
    def test_chinh_doc_duoc_nhat_ky_nhom_phu(self):
        # CHÍNH = cá nhân zalop_ca; PHỤ = nhóm g1 (một chiều)
        self.cfg["memory_links"] = [{"id": "1", "kind": "chinh_phu",
            "primary": [{"kenh": "zalop", "chat": "ca"}],
            "secondary": [{"kenh": "zalop", "chat": "g1"}]}]
        self._bat("zalop:g1")
        chatlog.ghi(G1, sender_name="A", text="lịch tiêm phòng thứ Ba")
        out = self._goi("tom_tat_hoi_thoai", {}, "zalop_ca")
        self.assertIn("tiêm phòng", out)


if __name__ == "__main__":
    unittest.main()
