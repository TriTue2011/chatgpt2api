"""Google gắn cờ "hoạt động bất thường" thì KHÔNG phải mất đăng nhập.

Đo thật 23–28/09/2026: Flow trả 403 mã 7 (PUBLIC_ERROR_UNUSUAL_ACTIVITY) cho CẢ 4 tài khoản,
mọi đường gọi. Adapter cũ thấy chữ "403" là coi như đăng xuất → chạy khôi phục → thấy phiên
còn sống → báo "✅ Khôi phục xong" suốt 6 ngày trong khi không tạo nổi một ảnh, và vẫn gõ cửa
mỗi giờ trên cả nhóm.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.account_recovery as ar  # noqa: E402
import services.image_providers.flow_google as fg  # noqa: E402

TAI_KHOAN = [{"profile": f"google-{i}", "project_id": f"p{i}"} for i in range(3)]
LOI = '{"detail":"Flow RPC ogiZ0b: HTTP 403 (mã 7: PUBLIC_ERROR_UNUSUAL_ACTIVITY)"}'


class TestBiGanCo(unittest.TestCase):
    def setUp(self):
        fg._account_state.clear()
        self.khoi_phuc: list = []
        self._p = [mock.patch.object(fg, "_pool_config", return_value={"accounts": TAI_KHOAN}),
                   mock.patch.object(fg, "_reorder_flow_account"),
                   mock.patch.object(ar, "flow_recover_and_notify",
                                     side_effect=lambda *a, **k: self.khoi_phuc.append(a))]
        for x in self._p:
            x.start()

    def tearDown(self):
        for x in self._p:
            x.stop()
        fg._account_state.clear()

    def _loi(self, text: str, status: int = 403):
        acc = fg._next_account()
        fg.flow_image_adapter.on_key_failed({"_flow_account": acc}, status, text)
        return acc

    def test_ca_nhom_nghi_va_khong_khoi_phuc_gia(self):
        self._loi(LOI)
        self.assertIsNone(fg._next_account(), "cả nhóm phải nghỉ — cờ không riêng tài khoản nào")
        self.assertEqual(self.khoi_phuc, [], "không phải mất đăng nhập: không chạy khôi phục")

    def test_nghi_dung_do_dai_cau_hinh(self):
        with mock.patch.object(fg, "_pool_config",
                               return_value={"accounts": TAI_KHOAN,
                                             "unusual_activity_pause_seconds": 60}), \
                mock.patch.object(fg.time, "time", return_value=1000.0):
            self._loi(LOI)
            self.assertEqual({round(v["cooldown_until"]) for v in fg._account_state.values()},
                             {1060})

    def test_403_khac_van_di_duong_khoi_phuc_cu(self):
        """Không đụng lớp lỗi khác: 403 không kèm cờ vẫn được coi là có thể mất phiên."""
        with mock.patch("threading.Thread") as t:
            self._loi('{"detail":"Flow RPC ogiZ0b: HTTP 403 (mã 7)"}')
        self.assertTrue(t.called)
        self.assertIsNotNone(fg._next_account())
