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

    def test_auto_la_fast_roi_ha_sang_auto_cua_grok(self):
        self.assertEqual(gw.chuoi_che_do("auto"), ["fast", "auto"])
        self.assertEqual(gw.chuoi_che_do("fast"), ["fast"])

    def test_het_luot_fast_moi_tai_khoan_thi_ha_mode(self):
        """Đo 02/10/2026: fast 0/30 lượt mà mode auto của Grok vẫn trả lời."""
        def chay(prompt, mode, cookies, anh=None):
            if mode == "fast":
                raise RuntimeError("Grok web: usage_limit_reached: You've reached your usage limit.")
            yield f"{mode}:{cookies['sso']}"

        a, b = _vas_tk()
        with a, b, mock.patch.object(gw, "_stream_chat", side_effect=chay):
            self.assertEqual(list(gw.stream_theo_chuoi("p", ["fast", "auto"])), ["auto:grok-1"])

    def test_loi_khac_het_luot_thi_khong_ha_mode(self):
        def chay(prompt, mode, cookies, anh=None):
            raise RuntimeError("Grok web từ chối websocket: 500")
            yield ""

        a, b = _vas_tk()
        with a, b, mock.patch.object(gw, "_stream_chat", side_effect=chay) as sc, \
                mock.patch("api.grok_firefox.lam_moi"):
            with self.assertRaises(RuntimeError):
                list(gw.stream_theo_chuoi("p", ["fast", "auto"]))
            self.assertTrue(all(c.args[1] == "fast" for c in sc.call_args_list))

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
        with mock.patch("api.grok_firefox.doc_cookie_file", return_value={"sso": "file"}):
            self.assertEqual(gw.tai_cookie("grok-1")["sso"], "file")

    def test_khong_co_sso_thi_bao(self):
        with mock.patch("api.grok_firefox.doc_cookie_file", return_value={}):
            with self.assertRaises(RuntimeError):
                gw.tai_cookie("grok-1")

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
    """Khung máy chủ → client (RFC 6455): độ dài 7 bit, hoặc 126 + 16 bit khi dài hơn."""
    dau = bytes([(0x80 if fin else 0) | opcode])
    n = len(payload)
    return dau + (bytes([n]) if n < 126 else bytes([126]) + n.to_bytes(2, "big")) + payload


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


HAI_TK = [{"profile": "grok-1", "label": "Main"}, {"profile": "grok-2", "label": "Backup"}]


def _vas_tk(ds=HAI_TK):
    return (mock.patch("api.grok_firefox.dang_bat", return_value=ds),
            mock.patch.object(gw, "tai_cookie", side_effect=lambda p: {"sso": p}))


class ThuLaiTests(unittest.TestCase):
    def test_da_gui_chu_thi_khong_thu_lai(self):
        """Hết phiên GIỮA câu trả lời: thử lại / đổi tài khoản sẽ gửi lặp đầu câu."""
        def hong(*a):
            yield "Xin "
            raise RuntimeError("Grok web từ chối websocket: 403")

        a, b = _vas_tk()
        with a, b, mock.patch.object(gw, "_stream_chat", side_effect=hong), \
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

        a, b = _vas_tk()
        with a, b, mock.patch.object(gw, "_stream_chat", side_effect=chay), \
                mock.patch("api.grok_firefox.lam_moi") as lam_moi:
            self.assertEqual(list(gw.stream_chat("p", "fast")), ["ok"])
            lam_moi.assert_called_once_with("grok-1")

    def test_tai_khoan_dau_hong_thi_sang_tai_khoan_ke(self):
        """Như Flow: tài khoản #1 hỏng (làm mới phiên cũng không cứu) thì sang #2."""
        def chay(prompt, mode, cookies, anh=None):
            if cookies["sso"] == "grok-1":
                raise RuntimeError("Grok web từ chối websocket: 403")
            yield "từ #2"

        a, b = _vas_tk()
        with a, b, mock.patch.object(gw, "_stream_chat", side_effect=chay), \
                mock.patch("api.grok_firefox.lam_moi", side_effect=RuntimeError("chưa tự mới")):
            self.assertEqual(list(gw.stream_chat("p", "fast")), ["từ #2"])

    def test_khong_tai_khoan_nao_bat(self):
        a, b = _vas_tk([])
        with a, b, self.assertRaises(RuntimeError) as e:
            list(gw.stream_chat("p", "fast"))
        self.assertIn("Cài đặt › Grok", str(e.exception))


class HienModelTests(unittest.TestCase):
    """Như mọi provider: model grok/ gw/ chỉ hiện khi có tài khoản Grok đang bật đã đăng nhập."""

    def _loc(self, ds, cookie):
        from services.protocol import openai_v1_models as om
        with mock.patch("api.grok_firefox.dang_bat", return_value=ds), \
                mock.patch("api.grok_firefox.doc_cookie_file", return_value=cookie), \
                mock.patch.object(om.account_service, "list_accounts", return_value=[]):
            return [m["id"] for m in om._drop_unavailable([{"id": "grok/fast"}, {"id": "gw/fast"}, {"id": "oc/auto"}])]

    def test_co_tai_khoan_dang_nhap_thi_hien(self):
        self.assertEqual(self._loc([{"profile": "grok-1"}], {"sso": "x"}), ["grok/fast", "gw/fast", "oc/auto"])

    def test_chua_dang_nhap_hoac_khong_tai_khoan_thi_an(self):
        self.assertEqual(self._loc([{"profile": "grok-1"}], {}), ["oc/auto"])
        self.assertEqual(self._loc([], {"sso": "x"}), ["oc/auto"])


class AnhTests(unittest.TestCase):
    """Đo 01/10/2026: ảnh Grok vẽ nằm ở chunk.render_generated_image.image_chunk; hỏng thì mang systemErrCode."""

    def _ev(self, ic):
        return {"type": "response.chunk", "chunk": {"render_generated_image": {"image_chunk": ic}}}

    def test_chi_lay_anh_da_xong(self):
        self.assertEqual(gw._anh_xong(self._ev({"imageUrl": "users/u/generated/a/image.jpg", "progress": 100})),
                         "users/u/generated/a/image.jpg")
        self.assertEqual(gw._anh_xong(self._ev({"imageUrl": "users/u/generated/a/image.jpg", "progress": 40})), "")
        self.assertEqual(gw._anh_xong({"type": "response.chunk", "chunk": {"text": {"text": "x"}}}), "")

    def test_ve_hong_thi_bao_ma_loi(self):
        with self.assertRaises(RuntimeError) as e:
            gw._anh_xong(self._ev({"imageUuid": "a", "progress": 100, "systemErrCode": 7}))
        self.assertIn("systemErrCode=7", str(e.exception))

    def test_grok_imagine_la_model_anh_cua_grok(self):
        from services.backend_router import BackendRouter
        from utils.helper import classify_model_capability
        r = BackendRouter().route("grok/imagine")
        self.assertEqual((r.provider, r.is_image), ("grok_web", True))
        self.assertEqual(classify_model_capability("grok/imagine"), ["image"])


class KetThucDoDangTests(unittest.TestCase):
    """Đo 02/10/2026: tài khoản hết lượt → Grok gửi stream_error rồi response.done «incomplete»; mã cũ trả nửa câu
    như đã xong («3+4» → «5»)."""

    def _chay(self, su_kien):
        import json as _j

        khung = b"".join(_khung(1, _j.dumps({"event": e}).encode()) for e in su_kien)
        dau = (b"HTTP/1.1 101 Switching Protocols\r\n\r\n")
        sock = _SockGia([dau, khung])
        with mock.patch.object(gw.socket, "create_connection", return_value=sock), \
                mock.patch.object(gw.ssl, "create_default_context") as ctx, \
                mock.patch.object(gw, "_user_id", return_value="u1"):
            ctx.return_value.wrap_socket.return_value = sock
            sock.settimeout = lambda *_: None
            sock.close = lambda: None
            return list(gw._stream_chat("p", "fast", {"sso": "x"}))

    MO = [{"type": "session.created", "client_event_id": ""}, {"type": "conversation.attached", "conversation": {"id": "c"}}]

    def test_het_luot_bao_loi_khong_tra_nua_cau(self):
        ev = self.MO + [{"type": "response.chunk", "chunk": {"text": {"text": "5"}}},
                        {"type": "response.grok.output", "output": {"stream_error": {
                            "kind": "usage_limit_reached", "message": "You've reached your usage limit."}}},
                        {"type": "response.done", "response": {"status": "incomplete",
                                                               "status_details": {"reason": "stream_error"}}}]
        with self.assertRaises(RuntimeError) as e:
            self._chay(ev)
        self.assertIn("usage_limit_reached", str(e.exception))

    def test_ket_thuc_khong_completed_cung_bao_loi(self):
        with self.assertRaises(RuntimeError):
            self._chay(self.MO + [{"type": "response.done", "response": {"status": "incomplete"}}])

    def test_completed_tra_du_chu(self):
        ev = self.MO + [{"type": "response.chunk", "chunk": {"text": {"text": "3"}}},
                        {"type": "response.chunk", "chunk": {"text": {"text": "6"}}},
                        {"type": "response.done", "response": {"status": "completed"}}]
        self.assertEqual("".join(self._chay(ev)), "36")
