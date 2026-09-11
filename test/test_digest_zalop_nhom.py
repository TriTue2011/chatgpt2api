"""Gửi vào kênh Zalo Cá Nhân phải đúng kiểu: NHÓM là 1, cá nhân là 0.

Đo 11/09/2026: `digest._zalop_thread_type` đọc trường ``is_group`` trong khi
`channel_contacts.upsert` ghi ``kind``. Mọi nhóm bị gửi như tin cá nhân tới
một mã không tồn tại; Zalo vẫn trả msgId nên cảnh báo nhà, bản tin học hỏi và
gợi ý thiết bị gửi vào nhóm "AI học hỏi" từ sáng không tới tin nào.

Test đi qua CHÍNH chỗ ghi (`upsert`) rồi chỗ đọc (`send_target`) — lệch tên
trường giữa hai bên lần nữa là hỏng ngay ở đây, không phải chờ chủ máy thấy
nhóm im lặng.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock


class DigestZalopNhomTest(unittest.TestCase):
    def setUp(self) -> None:
        from services import channel_contacts as cc

        self.cc = cc
        self._tmp = TemporaryDirectory()
        goc = cc._PATH
        cc._reset_for_tests(Path(self._tmp.name) / "channel_contacts.json")
        self.addCleanup(lambda: cc._reset_for_tests(goc))
        self.addCleanup(self._tmp.cleanup)

    def _gui(self, target: str) -> mock.MagicMock:
        from services import digest

        with mock.patch("services.zalo_personal.send_message",
                        return_value={"ok": True}) as gui:
            self.assertTrue(digest.send_target(target, "chào"))
        return gui

    def test_NHOM_thi_gui_KIEU_NHOM(self) -> None:
        self.cc.upsert("zalop", "tk", "nhom1", user_id="u1",
                       chat_name="AI học hỏi", is_group=True)
        gui = self._gui("zalop:tk:nhom1")
        self.assertEqual(gui.call_args.args[:3], ("nhom1", "chào", 1))
        self.assertEqual(gui.call_args.kwargs.get("account"), "tk")

    def test_CA_NHAN_thi_gui_KIEU_CA_NHAN(self) -> None:
        self.cc.upsert("zalop", "tk", "nguoi1", user_id="nguoi1",
                       display_name="Anh", is_group=False)
        self.assertEqual(self._gui("zalop:tk:nguoi1").call_args.args[2], 0)

    def test_CHUA_THAY_BAO_GIO_thi_doan_CA_NHAN(self) -> None:
        """Không biết thì đoán cá nhân — gửi nhầm vào nhóm là lộ tin."""
        self.assertEqual(self._gui("zalop:tk:la").call_args.args[2], 0)


if __name__ == "__main__":
    unittest.main()
