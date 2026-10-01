"""Grok web: cookie từ file do Firefox riêng của Grok ghi; chat qua websocket.

Không gọi mạng. Không đọc cookie thật.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth-key")

import api.grok_web as gw  # noqa: E402


class CheDoTests(unittest.TestCase):
    def test_trong_va_auto_ve_fast(self):
        self.assertEqual(gw.che_do(""), "fast")
        self.assertEqual(gw.che_do("auto"), "fast")
        self.assertEqual(gw.che_do("fast"), "fast")

    def test_expert_giu_expert(self):
        self.assertEqual(gw.che_do("expert"), "expert")
        self.assertEqual(gw.che_do("grok-chat-heavy"), "heavy")


class HopVanBanTests(unittest.TestCase):
    def test_ghep_role(self):
        text = gw.hop_van_ban([
            {"role": "user", "content": "xin chao"},
            {"role": "assistant", "content": [{"type": "text", "text": "chao"}]},
        ])
        self.assertIn("[user]\nxin chao", text)
        self.assertIn("[assistant]\nchao", text)


class CookieTests(unittest.TestCase):
    """Grok chỉ đọc file cookie do Firefox riêng của nó ghi — không hỏi captcha-solver, không đụng cấu hình Gemini
    hay Flow (chủ máy 01/10/2026: "chạy đường đăng nhập riêng cho grok, giữ nguyên các chatgpt, gemini, claude,
    flow như cũ")."""

    def test_doc_file(self):
        with mock.patch.object(gw, "_file_cookies", return_value={"sso": "file"}):
            self.assertEqual(gw.tai_cookie()["sso"], "file")

    def test_khong_co_sso_thi_bao(self):
        with mock.patch.object(gw, "_file_cookies", return_value={}):
            with self.assertRaises(RuntimeError):
                gw.tai_cookie()

    def test_khong_con_duong_solver(self):
        for ten in ("_fetch_solver", "_profiles", "_solver_cfg"):
            self.assertFalse(hasattr(gw, ten), ten)


class _SockGia:
    """Socket giả: trả lần lượt các mẩu byte, hết thì b"" (máy chủ đóng); ghi lại mọi thứ client gửi."""

    def __init__(self, manh: list[bytes]):
        self.manh, self.gui = list(manh), []

    def recv(self, n):
        return self.manh.pop(0) if self.manh else b""

    def sendall(self, b):
        self.gui.append(b)


def _khung(opcode: int, payload: bytes, fin: bool = True) -> bytes:
    return bytes([(0x80 if fin else 0) | opcode, len(payload)]) + payload


class WebsocketTests(unittest.TestCase):
    """01/10/2026: các vòng đọc cũ quay vô hạn khi máy chủ đóng; khung phân mảnh bị bỏ; ping không ai đáp."""

    def test_may_chu_dong_giua_khung_khong_treo(self):
        s = _SockGia([bytes([0x81, 126])])          # báo độ dài 2 byte rồi đóng
        self.assertEqual(gw._ws_recv(s, b"")[0], None)

    def test_ghep_khung_phan_manh(self):
        s = _SockGia([_khung(1, b'{"a":', fin=False) + _khung(0, b"1}")])
        (opcode, payload), _ = gw._ws_recv(s, b"")
        self.assertEqual((opcode, payload), (1, b'{"a":1}'))

    def test_ping_duoc_dap_pong(self):
        s = _SockGia([_khung(9, b"hi") + _khung(1, b"x")])
        (opcode, payload), _ = gw._ws_recv(s, b"")
        self.assertEqual((opcode, payload), (1, b"x"))
        self.assertEqual(s.gui[0][0], 0x8A, "pong, FIN")
        self.assertTrue(s.gui[0][1] & 0x80, "client phải che mặt nạ")


class ThuLaiTests(unittest.TestCase):
    def test_da_gui_chu_thi_khong_thu_lai(self):
        """Hết phiên GIỮA câu trả lời: thử lại sẽ gửi lặp đầu câu."""
        def hong(*a):
            yield "Xin "
            raise RuntimeError("Grok web từ chối websocket: 403")

        with mock.patch.object(gw, "_stream_chat", side_effect=hong), \
                mock.patch("api.grok_firefox.lam_moi") as lam_moi:
            ra = []
            with self.assertRaises(RuntimeError):
                for x in gw.stream_chat("p", "fast"):
                    ra.append(x)
            self.assertEqual(ra, ["Xin "])
            lam_moi.assert_not_called()

    def test_chua_gui_gi_thi_lam_moi_roi_thu_lai(self):
        lan = iter([RuntimeError("Grok web từ chối websocket: 403"), None])

        def chay(*a):
            e = next(lan)
            if e:
                raise e
            yield "ok"

        with mock.patch.object(gw, "_stream_chat", side_effect=chay), \
                mock.patch("api.grok_firefox.lam_moi") as lam_moi:
            self.assertEqual(list(gw.stream_chat("p", "fast")), ["ok"])
            lam_moi.assert_called_once()
