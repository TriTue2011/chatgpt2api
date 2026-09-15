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


class DigestKemAnhTest(unittest.TestCase):
    """Tin báo kèm ảnh (vd mặt người lạ): gửi ảnh có chú thích; ảnh hỏng thì vẫn gửi chữ."""

    def test_zalop_gui_anh_kem_chu_thich(self) -> None:
        from services import digest
        with mock.patch("services.zalo_personal._send_photo_robust", return_value=True) as anh, \
             mock.patch("services.zalo_personal.send_message") as chu:
            self.assertTrue(digest.send_target("zalop:tk:la", "👤 Người lạ", "http://x/a.jpg"))
        self.assertEqual(anh.call_args.args[:3], ("la", "http://x/a.jpg", "👤 Người lạ"))
        chu.assert_not_called()

    def test_zalop_anh_hong_thi_van_gui_chu(self) -> None:
        from services import digest
        with mock.patch("services.zalo_personal._send_photo_robust", return_value=False), \
             mock.patch("services.zalo_personal.send_message", return_value={"ok": True}) as chu:
            self.assertTrue(digest.send_target("zalop:tk:la", "👤 Người lạ", "http://x/a.jpg"))
        self.assertEqual(chu.call_args.args[1], "👤 Người lạ")

    def test_telegram_chu_dai_qua_chu_thich_thi_gui_anh_roi_gui_chu(self) -> None:
        from services import digest
        dai = "x" * 1500
        with mock.patch("services.telegram_bot._fetch_image_bytes", return_value=b"anh"), \
             mock.patch("services.telegram_bot.send_photo", return_value={"ok": True}) as anh, \
             mock.patch("services.telegram_bot.send_message", return_value={"ok": True}) as chu:
            self.assertTrue(digest.send_target("tg:123", dai, "http://x/a.jpg"))
        self.assertEqual(anh.call_args.args[2], "")
        self.assertEqual(chu.call_args.args[1], dai)

    def test_khong_co_anh_giu_nguyen_duong_chu(self) -> None:
        from services import digest
        with mock.patch("services.zalo_bot.send_photo") as anh, \
             mock.patch("services.zalo_bot.send_message", return_value=True) as chu:
            self.assertTrue(digest.send_target("zalo:9", "chào"))
        anh.assert_not_called()
        chu.assert_called_once()
