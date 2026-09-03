"""Mỗi bot Zalo tự chọn webhook hay long-polling, không dùng chung một công tắc.

Một tài khoản có thể nuôi nhiều bot cho nhiều việc (trợ lý, n8n, thử nghiệm) mà
chỉ MỘT trong số đó có URL webhook công khai hợp lệ. Ép chung một công tắc thì
hoặc bot kia im, hoặc phải hạ cả nhà xuống long-polling.

Bộ test giữ bốn tính chất:

  1. Bot không khai gì thì KẾ THỪA công tắc chung — cấu hình đang chạy không đổi
     hành vi, người dùng một bot khỏi phải khai thêm.
  2. Bot có khai thì cờ riêng THẮNG công tắc chung, cả hai chiều.
  3. `apply_mode` chia hai nhóm: đặt webhook cho nhóm này, bật poll cho nhóm kia,
     và chỉ rút poll của đúng mấy bot chuyển sang webhook.
  4. `start_polling` bỏ qua đúng bot đang webhook, không bỏ qua cả nhà.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import zalo_bot as zb


def _bot(token: str, **kw) -> dict:
    return {"token": token, "enabled": True, **kw}


class KeThuaCongTacChungTests(unittest.TestCase):
    def test_khong_khai_thi_theo_cong_tac_chung(self):
        with mock.patch.object(zb, "webhook_enabled", return_value=True):
            self.assertTrue(zb.bot_webhook_enabled(_bot("a")))
        with mock.patch.object(zb, "webhook_enabled", return_value=False):
            self.assertFalse(zb.bot_webhook_enabled(_bot("a")))

    def test_co_khai_thi_thang_cong_tac_chung(self):
        with mock.patch.object(zb, "webhook_enabled", return_value=False):
            self.assertTrue(zb.bot_webhook_enabled(_bot("a", webhook=True)))
        with mock.patch.object(zb, "webhook_enabled", return_value=True):
            self.assertFalse(zb.bot_webhook_enabled(_bot("a", webhook=False)))

    def test_gia_tri_khong_phai_bool_thi_coi_nhu_chua_khai(self):
        # Config chỉnh tay có thể lọt chuỗi "true"; đừng đoán, cứ kế thừa.
        with mock.patch.object(zb, "webhook_enabled", return_value=False):
            self.assertFalse(zb.bot_webhook_enabled(_bot("a", webhook="true")))


class ApplyModeChiaHaiNhomTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bots = [_bot("wh111:x", webhook=True), _bot("poll222:y", webhook=False)]
        self.da_set: list[str] = []
        self.da_delete: list[str] = []
        self.da_stop: list[list[str] | None] = []

    def _chay(self, **kw):
        with mock.patch.object(zb, "_bots", return_value=self.bots), \
             mock.patch.object(zb, "_enabled_bots", return_value=self.bots), \
             mock.patch.object(zb, "webhook_enabled", return_value=False), \
             mock.patch.object(zb, "webhook_url", return_value="https://x/y"), \
             mock.patch.object(zb, "set_webhook",
                               side_effect=lambda b: (self.da_set.append(b["token"]),
                                                      {"ok": True})[1]), \
             mock.patch.object(zb, "delete_webhook",
                               side_effect=lambda b: (self.da_delete.append(b["token"]),
                                                      {"ok": True})[1]), \
             mock.patch.object(zb, "stop_polling",
                               side_effect=lambda *a, tokens=None, **k: (
                                   self.da_stop.append(tokens), 0)[1]), \
             mock.patch.object(zb, "start_polling", return_value=True):
            return zb.apply_mode(**kw)

    def test_moi_bot_di_mot_duong(self):
        out = self._chay()
        self.assertEqual(self.da_set, ["wh111:x"])       # chỉ bot khai webhook
        self.assertEqual(self.da_delete, ["poll222:y"])  # chỉ bot khai polling
        self.assertEqual(out["mode"], "hỗn hợp")
        self.assertTrue(out["polling"])

    def test_chi_rut_poll_cua_bot_chuyen_sang_webhook(self):
        # Rút hết thì bot đang long-polling ở nhóm kia bị vạ lây, ngưng nhận tin.
        self._chay()
        self.assertEqual(self.da_stop, [["wh111:x"]])

    def test_ca_nha_webhook_thi_bao_dung_che_do(self):
        self.bots = [_bot("a:1", webhook=True), _bot("b:2", webhook=True)]
        out = self._chay()
        self.assertEqual(out["mode"], "webhook")
        self.assertFalse(out["polling"])

    def test_ca_nha_polling_thi_bao_dung_che_do(self):
        self.bots = [_bot("a:1", webhook=False), _bot("b:2", webhook=False)]
        out = self._chay()
        self.assertEqual(out["mode"], "long-polling")
        self.assertEqual(self.da_set, [])


class StartPollingBoQuaDungBotTests(unittest.TestCase):
    def test_chi_bo_qua_bot_dang_webhook(self):
        bots = [_bot("wh:1", webhook=True), _bot("poll:2", webhook=False)]
        chay: list[str] = []

        class _Th:
            def __init__(self, **kw): self.kw = kw
            def start(self): chay.append(self.kw["args"][0]["token"])
            def is_alive(self): return False

        with mock.patch.object(zb, "_bots", return_value=bots), \
             mock.patch.object(zb, "webhook_enabled", return_value=False), \
             mock.patch.object(zb.threading, "Thread", _Th):
            zb._poll_threads.clear()
            self.assertTrue(zb.start_polling())
        self.assertEqual(chay, ["poll:2"])
        zb._poll_threads.clear()


if __name__ == "__main__":
    unittest.main()
