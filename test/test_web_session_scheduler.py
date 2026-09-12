"""Bộ quét giữ phiên Claude / ChatGPT free / Gemini web — giống Flow nhưng rẻ
hơn (kiểm không mở trình duyệt). Khuôn theo `test_flow_session_scan.py`."""

from __future__ import annotations

import unittest
from unittest import mock

import services.web_session_scheduler as wss


class TatBatTest(unittest.TestCase):
    def tearDown(self) -> None:
        wss._reset_for_tests()

    def test_KHONG_KHAI_CONFIG_thi_TAT(self) -> None:
        with mock.patch.object(wss, "_cfg", return_value={}):
            self.assertFalse(wss.is_enabled())

    def test_BAT_TUONG_MINH_thi_CHAY(self) -> None:
        with mock.patch.object(wss, "_cfg", return_value={"enabled": True}):
            self.assertTrue(wss.is_enabled())

    def test_TAT_thi_KHONG_QUET(self) -> None:
        with mock.patch.object(wss, "is_enabled", return_value=False), \
             mock.patch.object(wss, "_claude_profiles") as cp:
            wss._scan_once()
        cp.assert_not_called()

    def test_APP_GOI_START(self) -> None:
        with mock.patch.object(wss, "is_enabled", return_value=True), \
             mock.patch("threading.Thread") as th:
            wss.start()
        th.assert_called_once()
        self.assertTrue(wss._started)

    def test_TAT_thi_VAN_DUNG_LUONG_de_GAT_CONG_TAC_AN_NGAY(self) -> None:
        """Công tắc tắt vẫn phải dựng luồng — chốt duy nhất nằm trong `_scan_once`.

        Trước 12/09/2026 `start()` thoát ngay khi thấy tắt, nên bật
        `web_session_scan` trên web chỉ LƯU được giá trị: không vòng quét nào
        chạy cho tới lần khởi động lại tiến trình. Đo trên máy chủ hôm đó — bật
        xong mà log vẫn chỉ có `web_session_scheduler_disabled` từ lúc khởi
        động, không một vòng quét nào. Phần "tắt thì không quét" đã do
        `test_TAT_thi_KHONG_QUET` ở trên giữ, nên ở đây chỉ giữ phần "luồng
        luôn có" để gạt công tắc là có tác dụng ngay.
        """
        with mock.patch.object(wss, "is_enabled", return_value=False), \
             mock.patch("threading.Thread") as th:
            wss.start()
        th.assert_called_once()
        self.assertTrue(wss._started)


class QuetMotTangTest(unittest.TestCase):
    def tearDown(self) -> None:
        wss._reset_for_tests()

    def test_OK_thi_KHONG_GOI_KHOI_PHUC(self) -> None:
        mat_fn = mock.Mock()
        da, chet, ban = wss._quet_mot_tang(
            "claude", ["a", "b"], 5, 9_000_000.0, lambda id_: "ok", mat_fn)
        self.assertEqual((da, chet, ban), (2, 0, 0))
        mat_fn.assert_not_called()

    def test_MAT_thi_GOI_KHOI_PHUC_DUNG_ID(self) -> None:
        mat_fn = mock.Mock()
        da, chet, ban = wss._quet_mot_tang(
            "claude", ["a"], 5, 9_000_000.0, lambda id_: "mat", mat_fn)
        self.assertEqual((da, chet, ban), (1, 1, 0))
        mat_fn.assert_called_once_with("a")

    def test_BAN_KHONG_TINH_LA_CHET(self) -> None:
        mat_fn = mock.Mock()
        da, chet, ban = wss._quet_mot_tang(
            "claude", ["a"], 5, 9_000_000.0, lambda id_: "ban", mat_fn)
        self.assertEqual((da, chet, ban), (1, 0, 1))
        mat_fn.assert_not_called()

    def test_TON_TRAN_MOI_VONG(self) -> None:
        da, chet, ban = wss._quet_mot_tang(
            "claude", ["a", "b", "c"], 2, 9_000_000.0, lambda id_: "ok", mock.Mock())
        self.assertEqual(da, 2)

    def test_VUA_KIEM_KHONG_KIEM_LAI_NGAY(self) -> None:
        trang_thai = mock.Mock(return_value="ok")
        wss._quet_mot_tang("claude", ["a"], 5, 9_000_000.0, trang_thai, mock.Mock())
        da, _, _ = wss._quet_mot_tang(
            "claude", ["a"], 5, 9_000_000.0 + 60, trang_thai, mock.Mock())
        self.assertEqual(da, 0, "mới kiểm 60s trước, chưa tới lượt kiểm lại")

    def test_LOI_MOT_ID_KHONG_CHAN_ID_SAU(self) -> None:
        def trang_thai(id_: str) -> str:
            if id_ == "a":
                raise RuntimeError("lỗi mạng")
            return "ok"
        da, chet, ban = wss._quet_mot_tang(
            "claude", ["a", "b"], 5, 9_000_000.0, trang_thai, mock.Mock())
        self.assertEqual(da, 2)


class ScanOnceGoiDungHamTest(unittest.TestCase):
    def tearDown(self) -> None:
        wss._reset_for_tests()

    def test_SCAN_ONCE_GOI_DUNG_HAM_KHOI_PHUC_TUNG_TANG(self) -> None:
        acc = {"email": "a@gmail.com", "id": "eyJabc"}
        with mock.patch.object(wss, "is_enabled", return_value=True), \
             mock.patch.object(wss, "_claude_profiles", return_value=["google-a"]), \
             mock.patch.object(wss, "_gma_profiles", return_value=["google-b"]), \
             mock.patch.object(wss, "_free_accounts", return_value=[acc]), \
             mock.patch("services.account_recovery._claude_session_trang_thai", return_value="mat") as ctt, \
             mock.patch("services.account_recovery.claude_recover_and_notify") as crn, \
             mock.patch("services.account_recovery._gma_session_trang_thai", return_value="ok") as gtt, \
             mock.patch("services.account_recovery.gma_recover_and_notify") as grn, \
             mock.patch("services.account_recovery._cgf_session_trang_thai", return_value="mat") as ftt, \
             mock.patch("services.account_recovery.recover_provider_account") as fpa:
            wss._scan_once()
        ctt.assert_called_once_with("google-a")
        crn.assert_called_once()
        self.assertEqual(crn.call_args.args[0], "google-a")
        gtt.assert_called_once_with("google-b")
        grn.assert_not_called()
        ftt.assert_called_once_with("a@gmail.com")
        fpa.assert_called_once()
        self.assertEqual(fpa.call_args.args[0], acc)
        self.assertEqual(fpa.call_args.args[1], "free")


if __name__ == "__main__":
    unittest.main()
