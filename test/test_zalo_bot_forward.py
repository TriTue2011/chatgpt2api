"""Zalo Bot: chuyển tiếp tin ĐẾN ra webhook ngoài, và không được tự làm kênh chết.

Kênh Zalo Cá Nhân đã có chuyển tiếp (`zalo_personal_forward_webhooks`); kênh bot
thì chưa, nên Home Assistant / n8n không nghe được tin tới bot. Đây là chiều ĐI
RA nên chạy được với URL LAN http:// — khác chiều Zalo cloud gọi vào vốn đòi
HTTPS công khai.

Hai bất biến quan trọng nhất được khoá ở đây:

  1. `forward_incoming` phải gọi từ ĐIỂM HỢP LƯU của cả hai chế độ nhận tin
     (`_process_message`), không phải từ riêng đường webhook. Bot trên máy chủ
     đang chạy long-polling — móc riêng ở đường webhook thì việc chuyển tiếp
     không bao giờ nổ.

  2. Bật công tắc webhook mà `setWebhook` trượt HẾT thì phải TỰ QUAY VỀ
     long-polling. `apply_mode` dừng poll TRƯỚC khi đăng ký webhook, nên nếu
     đăng ký trượt mà không quay lại thì kênh im lặng hoàn toàn: webhook chưa
     đặt được, poll thì vừa tắt. Ca này rất dễ gặp — docs đòi URL HTTPS công
     khai, mà base_url thực địa đang là http://<IP LAN>:3030 nên `set_webhook`
     từ chối ngay.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import zalo_bot as zb  # noqa: E402


class _ThreadNgay:
    """Thread giả chạy NGAY trong luồng gọi — bỏ tính bất định khỏi phép đo."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self) -> None:
        if self._target:
            self._target(*self._args, **self._kwargs)


def _cfg(enabled: bool, dests: list | None = None) -> dict:
    return {
        "zalo_bot_forward_enabled": enabled,
        "zalo_bot_forward_webhooks": dests if dests is not None else [],
    }


class LocDichTests(unittest.TestCase):
    """`_forward_matches` — hàm thuần, gọi thật."""

    def test_filters_rong_nhan_moi_chat(self):
        self.assertTrue(zb._forward_matches("chat-1", "u-1", []))

    def test_chat_khong_khop_thi_bo(self):
        flt = [{"chat_id": "chat-9", "user_ids": []}]
        self.assertFalse(zb._forward_matches("chat-1", "u-1", flt))

    def test_chat_khop_user_ids_rong_nhan_moi_nguoi(self):
        flt = [{"chat_id": "chat-1", "user_ids": []}]
        self.assertTrue(zb._forward_matches("chat-1", "bat-ky", flt))

    def test_user_ids_co_list_thi_chi_user_do(self):
        flt = [{"chat_id": "chat-1", "user_ids": ["u-1", "u-2"]}]
        self.assertTrue(zb._forward_matches("chat-1", "u-2", flt))
        self.assertFalse(zb._forward_matches("chat-1", "u-9", flt))


class DocCauHinhTests(unittest.TestCase):
    def test_bo_muc_thieu_url_va_sinh_id(self):
        dests = [{"url": "http://a/1"}, {"label": "thieu url"}, {"url": "http://b/2", "id": "x"}]
        with mock.patch.object(zb.config, "get", return_value=_cfg(True, dests)):
            got = zb.forward_destinations()
        self.assertEqual([d["url"] for d in got], ["http://a/1", "http://b/2"])
        self.assertEqual(got[1]["id"], "x")
        self.assertTrue(got[0]["enabled"])  # không ghi enabled → coi như bật

    def test_nhan_ca_khoa_thread_id_cua_zalo_ca_nhan(self):
        """Chép cấu hình từ kênh Zalo Cá Nhân sang không phải sửa tay."""
        dests = [{"url": "http://a", "filters": [{"thread_id": "t-1", "user_ids": ["u-1"]}]}]
        with mock.patch.object(zb.config, "get", return_value=_cfg(True, dests)):
            got = zb.forward_destinations()
        self.assertEqual(got[0]["filters"], [{"chat_id": "t-1", "user_ids": ["u-1"]}])

    def test_cong_tac_tong_mac_dinh_TAT(self):
        """Bật sẵn việc tự POST ra URL ngoài là đổi hành vi sau nâng cấp."""
        with mock.patch.object(zb.config, "get", return_value={}):
            self.assertFalse(zb.forward_enabled())


class ChuyenTiepTests(unittest.TestCase):
    def setUp(self):
        self.da_post: list[tuple] = []

    def _chay(self, cfg: dict, payload: dict) -> None:
        with mock.patch.object(zb.config, "get", return_value=cfg), \
             mock.patch.object(zb, "_post_forward",
                               side_effect=lambda u, p, l: self.da_post.append((u, p, l))), \
             mock.patch.object(zb.threading, "Thread", _ThreadNgay):
            zb.forward_incoming(payload)

    def test_cong_tac_tong_tat_thi_khong_gui_gi(self):
        self._chay(_cfg(False, [{"url": "http://a", "enabled": True}]),
                   {"chat_id": "c1", "text": "hi"})
        self.assertEqual(self.da_post, [])

    def test_bat_thi_gui_dung_url_va_payload(self):
        self._chay(_cfg(True, [{"url": "http://a/hook", "label": "HA"}]),
                   {"chat_id": "c1", "user_id": "u1", "text": "hi"})
        self.assertEqual(len(self.da_post), 1)
        url, payload, label = self.da_post[0]
        self.assertEqual(url, "http://a/hook")
        self.assertEqual(label, "HA")
        self.assertEqual(payload["text"], "hi")
        self.assertEqual(payload["chat_id"], "c1")

    def test_dich_tat_rieng_thi_bo_qua(self):
        self._chay(
            _cfg(True, [{"url": "http://tat", "enabled": False},
                        {"url": "http://bat", "enabled": True}]),
            {"chat_id": "c1", "text": "hi"},
        )
        self.assertEqual([u for u, _, _ in self.da_post], ["http://bat"])

    def test_loc_theo_chat_ap_dung_tung_dich(self):
        self._chay(
            _cfg(True, [
                {"url": "http://moi-chat"},
                {"url": "http://chi-c9", "filters": [{"chat_id": "c9", "user_ids": []}]},
            ]),
            {"chat_id": "c1", "user_id": "u1", "text": "hi"},
        )
        self.assertEqual([u for u, _, _ in self.da_post], ["http://moi-chat"])

    def test_consumer_loi_khong_lam_no(self):
        """URL rác → _post_forward phải nuốt lỗi, không ném lên người gọi."""
        zb._post_forward("http://khong-ton-tai.invalid/hook", {"chat_id": "c1"}, "test")


class GoiTuDiemHopLuuTests(unittest.TestCase):
    def test_process_message_goi_forward_incoming(self):
        """Cả webhook lẫn long-poll đều hợp lưu ở `_process_message`."""
        goi: list[dict] = []
        with mock.patch.object(zb, "forward_incoming", side_effect=goi.append), \
             mock.patch.object(zb, "_process_message_inner"):
            zb._process_message("chao", "chat-1", user_id="u-1", sender="Ai Do",
                                is_group=True, chat_name="Nhom")
        self.assertEqual(len(goi), 1)
        self.assertEqual(goi[0]["chat_id"], "chat-1")
        self.assertEqual(goi[0]["user_id"], "u-1")
        self.assertEqual(goi[0]["text"], "chao")
        self.assertTrue(goi[0]["is_group"])
        self.assertEqual(goi[0]["source"], "zalo_bot")

    def test_forward_loi_khong_chan_xu_ly_AI(self):
        def _no(_payload):
            raise RuntimeError("webhook sap")

        chay_inner: list[int] = []
        with mock.patch.object(zb, "forward_incoming", side_effect=_no), \
             mock.patch.object(zb, "_process_message_inner",
                              side_effect=lambda *a, **k: chay_inner.append(1)):
            zb._process_message("chao", "chat-1")
        self.assertEqual(chay_inner, [1])


class TestForwardKhongPhuThuocCongTacTests(unittest.TestCase):
    def test_test_forward_chay_du_cong_tac_tong_dang_tat(self):
        """Đúng lúc cần thử là lúc CHƯA bật — nút Test không được đòi bật trước."""
        with mock.patch.object(zb.config, "get",
                               return_value=_cfg(False, [{"url": "http://a", "enabled": True}])), \
             mock.patch.object(zb.urllib.request, "urlopen") as mo:
            mo.return_value.__enter__ = lambda s: type("R", (), {"status": 200})()
            mo.return_value.__exit__ = lambda *a: False
            r = zb.test_forward()
        self.assertTrue(r["ok"])
        self.assertEqual(r["url"], "http://a")
        self.assertTrue(r["payload"]["test"])

    def test_khong_co_url_thi_bao_ro(self):
        with mock.patch.object(zb.config, "get", return_value=_cfg(True, [])):
            r = zb.test_forward()
        self.assertFalse(r["ok"])
        self.assertIn("Chưa cấu hình", r["error"])


class QuayVePollingKhiWebhookTruotTests(unittest.TestCase):
    """Bật webhook mà setWebhook trượt hết → kênh KHÔNG được im lặng."""

    def _apply(self, set_ok: bool, mo_ta: str = ""):
        self.da_update: list[dict] = []
        with mock.patch.object(zb, "_bots", return_value=[{"token": "t1", "enabled": True}]), \
             mock.patch.object(zb, "webhook_enabled", return_value=True), \
             mock.patch.object(zb, "webhook_url", return_value="http://172.16.10.38:3030/x"), \
             mock.patch.object(zb, "stop_polling", return_value=0), \
             mock.patch.object(zb, "start_polling", return_value=True), \
             mock.patch.object(zb, "set_webhook",
                               return_value={"ok": set_ok, "description": mo_ta}), \
             mock.patch.object(zb.config, "update", side_effect=self.da_update.append):
            return zb.apply_mode()

    def test_truot_het_thi_quay_ve_polling_va_ha_co(self):
        out = self._apply(False, "webhook url phải là HTTPS, đang là http")
        self.assertTrue(out["fell_back_to_polling"])
        self.assertEqual(out["mode"], "long-polling")
        self.assertTrue(out["polling"])
        self.assertIn("HTTPS", out["fallback_reason"])
        # Hạ cờ để trạng thái chỉ có MỘT nguồn đúng.
        self.assertEqual(self.da_update, [{"zalo_webhook_enabled": False}])

    def test_dat_duoc_thi_khong_quay_ve(self):
        out = self._apply(True)
        self.assertNotIn("fell_back_to_polling", out)
        self.assertEqual(out["mode"], "webhook")
        self.assertFalse(out["polling"])
        self.assertEqual(self.da_update, [])


if __name__ == "__main__":
    unittest.main()
