"""Test 3 bản vá ổn định cookie/client pool GMA (học từ Gemini-FastAPI).

1. _drop_client chỉ xoá cookie cache của RIÊNG profile hỏng (trước: clear cả pool).
2. _get_client init ngoài lock toàn cục — account chết re-init không chặn
   request dùng client đã cache (lock riêng từng client + double-check).
3. Timeout ngoài của _run bao trùm timeout trong của init — không còn init
   "mồ côi" chạy nền xoay 1PSIDTS ngoài kiểm soát.

LƯU Ý: dòng `from __future__ import annotations` ở đầu file là BẮT BUỘC —
compile() trong bệ thử AST thừa hưởng future-flags từ file gọi nó, nhờ vậy
annotation kiểu `str | None` trong code 3.10+ không bị đánh giá trên máy 3.9.
"""
from __future__ import annotations

import ast
import os
import sys
import threading
import time
import types
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from test.test_gma_tiep_noi_hoi_thoai import _nap_tu_gemini_web  # noqa: E402


class DropClientTests(unittest.TestCase):
    def _ns(self):
        ns = _nap_tu_gemini_web("_drop_client")
        ns["threading"] = threading
        ns["_client_lock"] = threading.Lock()
        ns["_clients"] = {"A" * 32: "client-a"}
        ns["_cookie_cache"] = {
            "google-a": (time.time(), {"__Secure-1PSID": "A" * 40}),
            "google-b": (time.time(), {"__Secure-1PSID": "B" * 40}),
        }
        return ns

    def test_biet_profile_chi_xoa_dung_profile(self) -> None:
        ns = self._ns()
        ns["_drop_client"]("A" * 40, "google-a")
        self.assertNotIn("A" * 32, ns["_clients"])
        self.assertNotIn("google-a", ns["_cookie_cache"])
        # profile khoẻ GIỮ NGUYÊN cookie — không phải gọi lại captcha-solver
        self.assertIn("google-b", ns["_cookie_cache"])

    def test_khong_biet_profile_do_theo_psid(self) -> None:
        ns = self._ns()
        ns["_drop_client"]("B" * 40)
        self.assertNotIn("google-b", ns["_cookie_cache"])
        self.assertIn("google-a", ns["_cookie_cache"])


class FakeGeminiClient:
    so_lan_tao = 0

    def __init__(self, **kw):
        FakeGeminiClient.so_lan_tao += 1
        self.kw = kw

    def init(self, **kw):
        return ("init-args", kw)   # _run giả nhận rồi bỏ qua


class GetClientLockTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeGeminiClient.so_lan_tao = 0
        mod = types.ModuleType("gemini_webapi")
        mod.GeminiClient = FakeGeminiClient
        self._mod_cu = sys.modules.get("gemini_webapi")
        sys.modules["gemini_webapi"] = mod

        self.ns = _nap_tu_gemini_web("_get_client")
        self.ns["threading"] = threading
        self.ns["_client_lock"] = threading.Lock()
        self.ns["_clients"] = {}
        self.ns["_init_locks"] = {}
        self.ns["_auth_status"] = {}
        self.ns["_record_auth_status"] = lambda key, cli: None

    def tearDown(self) -> None:
        if self._mod_cu is None:
            sys.modules.pop("gemini_webapi", None)
        else:
            sys.modules["gemini_webapi"] = self._mod_cu

    def test_init_cham_khong_chan_client_da_cache(self) -> None:
        psid_nguoi = "A" * 40   # account nguội, init sẽ treo
        psid_am = "B" * 40      # account đã cache sẵn
        self.ns["_clients"][psid_am[:32]] = "client-am"

        dang_init = threading.Event()
        tha_init = threading.Event()

        def run_treo(coro, timeout=240):
            dang_init.set()
            tha_init.wait(5)

        self.ns["_run"] = run_treo

        t = threading.Thread(target=lambda: self.ns["_get_client"](psid_nguoi, ""),
                             daemon=True)
        t.start()
        self.assertTrue(dang_init.wait(5), "init lượt nguội chưa bắt đầu")

        # Trong lúc account nguội còn đang init: client đã cache phải lấy được NGAY
        # (code cũ giữ _client_lock suốt init → chỗ này kẹt tới 60s).
        bat_dau = time.monotonic()
        cli = self.ns["_get_client"](psid_am, "")
        self.assertEqual(cli, "client-am")
        self.assertLess(time.monotonic() - bat_dau, 2.0,
                        "client cache bị chặn bởi init của account khác")

        tha_init.set()
        t.join(5)
        self.assertIn(psid_nguoi[:32], self.ns["_clients"])
        self.assertEqual(FakeGeminiClient.so_lan_tao, 1)

    def test_hai_thread_cung_account_chi_init_mot_lan(self) -> None:
        psid = "C" * 40
        self.ns["_run"] = lambda coro, timeout=240: time.sleep(0.2)
        ket_qua = []
        luong = [threading.Thread(target=lambda: ket_qua.append(
            self.ns["_get_client"](psid, "")), daemon=True) for _ in range(2)]
        for t in luong: t.start()
        for t in luong: t.join(5)
        self.assertEqual(len(ket_qua), 2)
        self.assertIs(ket_qua[0], ket_qua[1])          # cùng một client
        self.assertEqual(FakeGeminiClient.so_lan_tao, 1)  # double-check chạy đúng


class TimeoutInitTests(unittest.TestCase):
    def test_timeout_ngoai_bao_trum_timeout_trong(self) -> None:
        """_run(cli.init(timeout=T_trong), timeout=T_ngoai) cần T_ngoai >= T_trong,
        nếu không future bị bỏ trước khi init tự kết thúc → init mồ côi chạy nền
        xoay 1PSIDTS song song với lần init sau (race hỏng cookie)."""
        src = open(os.path.join(GOC, "api", "gemini_web.py"), encoding="utf-8").read()
        cay = ast.parse(src)
        ham = next(n for n in cay.body
                   if isinstance(n, ast.FunctionDef) and n.name == "_get_client")
        thay = False
        for node in ast.walk(ham):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_run" and node.args):
                continue
            trong = node.args[0]
            if not (isinstance(trong, ast.Call) and isinstance(trong.func, ast.Attribute)
                    and trong.func.attr == "init"):
                continue
            t_trong = next((k.value.value for k in trong.keywords
                            if k.arg == "timeout"), None)
            t_ngoai = next((k.value.value for k in node.keywords
                            if k.arg == "timeout"), None)
            self.assertIsNotNone(t_trong)
            self.assertIsNotNone(t_ngoai)
            self.assertGreaterEqual(t_ngoai, t_trong)
            thay = True
        self.assertTrue(thay, "_get_client không còn lời gọi _run(cli.init(...))")


if __name__ == "__main__":
    unittest.main()
