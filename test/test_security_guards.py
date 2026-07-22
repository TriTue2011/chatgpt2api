"""Test lớp bảo mật: SSRF net_guard + vault isolation + login guard + redirect."""
from __future__ import annotations

import unittest
from unittest import mock
from urllib.parse import urlparse

from services import net_guard
from services.privacy_gate import SessionVault


class NetGuardSSRFTests(unittest.TestCase):
    def test_block_private_ipv4(self) -> None:
        for url in ("http://127.0.0.1/x", "http://192.168.1.10:8123/api",
                    "http://10.0.0.5/", "http://169.254.169.254/latest/meta-data/"):
            with self.assertRaises(net_guard.BlockedURL):
                net_guard.check_url(url)

    def test_block_non_http_scheme(self) -> None:
        for url in ("file:///etc/passwd", "gopher://x/", "ftp://host/f"):
            with self.assertRaises(net_guard.BlockedURL):
                net_guard.check_url(url)

    def test_block_missing_host(self) -> None:
        with self.assertRaises(net_guard.BlockedURL):
            net_guard.check_url("http:///nohost")

    def test_allow_public_host(self) -> None:
        # host public thật (không resolve ra IP private)
        self.assertEqual(net_guard.check_url("https://api.telegram.org/x"),
                         "https://api.telegram.org/x")

    def test_allowlist_rejects_outside_host(self) -> None:
        with self.assertRaises(net_guard.BlockedURL):
            net_guard.check_url("https://evil.example.com/x",
                                allow_hosts={"api.telegram.org"})

    def test_allowlist_accepts_subdomain(self) -> None:
        self.assertEqual(
            net_guard.check_url("https://cdn.telegram.org/f",
                                allow_hosts={"telegram.org"}),
            "https://cdn.telegram.org/f")

    def test_host_is_private_helper(self) -> None:
        self.assertTrue(net_guard.host_is_private("127.0.0.1"))
        self.assertTrue(net_guard.host_is_private("192.168.0.1"))
        self.assertTrue(net_guard.host_is_private(""))       # rỗng = coi private
        self.assertFalse(net_guard.host_is_private("8.8.8.8"))

    def test_is_self_images_url(self) -> None:
        self.assertTrue(net_guard.is_self_images_url(
            "http://127.0.0.1/images/foo.png"))
        self.assertTrue(net_guard.is_self_images_url(
            "http://localhost:80/images/a.jpg"))
        self.assertFalse(net_guard.is_self_images_url(
            "http://evil.com/images/x.png"))
        self.assertFalse(net_guard.is_self_images_url(
            "http://169.254.169.254/latest"))

    def test_safe_fetch_blocks_private_before_network(self) -> None:
        with self.assertRaises(net_guard.BlockedURL):
            net_guard.safe_fetch("http://127.0.0.1/secret")

    def test_safe_fetch_blocks_redirect_to_private(self) -> None:
        """Redirect hop Location → private IP must be blocked (classic SSRF)."""
        import io
        import urllib.error

        public = "https://example.com/start"
        try:
            net_guard.check_url(public)
        except net_guard.BlockedURL:
            self.skipTest("example.com resolved private in this env")

        err = urllib.error.HTTPError(
            public, 302, "Found",
            {"Location": "http://169.254.169.254/latest/meta-data/"},
            io.BytesIO(b""),
        )

        def fake_open(req, timeout=None):  # type: ignore[no-untyped-def]
            raise err

        fake_opener = mock.Mock()
        fake_opener.open = fake_open
        with mock.patch.object(net_guard.urllib.request, "build_opener",
                               return_value=fake_opener):
            with self.assertRaises(net_guard.BlockedURL) as ctx:
                net_guard.safe_fetch(public)
        msg = str(ctx.exception).lower()
        self.assertTrue(
            "169.254" in msg or "private" in msg or "nội bộ" in msg,
            msg,
        )

class VaultSessionIsolationTests(unittest.TestCase):
    def test_get_does_not_leak_across_session(self) -> None:
        v = SessionVault()
        ref = v.put("userA", "password", "secretA")
        # user B KHÔNG được resolve ref của user A dù biết chuỗi ref.
        self.assertIsNone(v.get("userB", ref))
        self.assertEqual(v.get("userA", ref), "secretA")

    def test_resolve_in_text_scoped_to_session(self) -> None:
        v = SessionVault()
        ref = v.put("userA", "token", "tok-123")
        text = f"dùng token {ref} đi"
        # session khác: ref giữ nguyên (không thay bằng plaintext).
        self.assertIn(ref, v.resolve_in_text("userB", text))
        # đúng session: thay ra plaintext.
        self.assertIn("tok-123", v.resolve_in_text("userA", text))

    def test_same_value_reuses_ref(self) -> None:
        v = SessionVault()
        r1 = v.put("s", "password", "p")
        r2 = v.put("s", "password", "p")
        self.assertEqual(r1, r2)


class LoginGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        from services import login_guard
        login_guard.reset_for_tests()
        self.lg = login_guard

    def tearDown(self) -> None:
        self.lg.reset_for_tests()

    def test_lockout_after_max_failures(self) -> None:
        ip = "10.0.0.99"
        # force small threshold via patch
        with mock.patch.object(self.lg, "max_failures", return_value=3):
            with mock.patch.object(self.lg, "window_sec", return_value=900.0):
                with mock.patch.object(self.lg, "lockout_sec", return_value=600.0):
                    for _ in range(3):
                        self.lg.record_failure(ip)
                    with self.assertRaises(Exception) as ctx:
                        self.lg.check_allowed(ip)
                    # FastAPI HTTPException status 429
                    exc = ctx.exception
                    self.assertEqual(getattr(exc, "status_code", None), 429)

    def test_success_clears_failures(self) -> None:
        ip = "10.0.0.50"
        with mock.patch.object(self.lg, "max_failures", return_value=5):
            self.lg.record_failure(ip)
            self.lg.record_failure(ip)
            self.lg.record_success(ip)
            self.lg.check_allowed(ip)  # no raise


class ApprovalAlwaysConfirmTests(unittest.TestCase):
    def test_always_confirm_includes_create_automation(self) -> None:
        from services.agent import approval_gate
        names = approval_gate.always_confirm_names()
        self.assertIn("create_automation", names)
        self.assertIn("send_to_contact", names)


class CaptchaAuthCompareTests(unittest.TestCase):
    def test_const_eq_length_mismatch_false(self) -> None:
        from api import captcha_proxy
        self.assertFalse(captcha_proxy._const_eq("short", "much-longer-key-value"))
        self.assertFalse(captcha_proxy._const_eq("", "x"))
        self.assertTrue(captcha_proxy._const_eq("abc", "abc"))


class AuditLogChangeTests(unittest.TestCase):
    """P2#12 — CHANGE actions get append-only audit rows with hash chain."""

    def test_log_event_writes_hash_chain(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from services.agent import approval_gate
        with tempfile.TemporaryDirectory() as td:
            approval_gate._reset_for_tests(Path(td))
            approval_gate.log_event("execute_change", "u1", "control_home", summary="bật đèn")
            approval_gate.log_event("execute_change", "u1", "create_automation", summary="auto")
            lines = approval_gate._AUDIT_FILE.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            r0 = json.loads(lines[0])
            r1 = json.loads(lines[1])
            self.assertIn("hash", r0)
            self.assertEqual(r1.get("prev"), r0.get("hash"))

class FilterAgentOutputTests(unittest.TestCase):
    """P0#5 — LLM/tool media URLs must not reach bot fetch/send."""

    def test_drops_private_image_url(self) -> None:
        out = net_guard.filter_agent_output({
            "text": "Đây ạ",
            "image_url": "http://169.254.169.254/latest/meta-data/",
        })
        self.assertNotIn("image_url", out)
        self.assertIn("chặn", out.get("text", "").lower() + out.get("text", ""))

    def test_drops_lan_video_url(self) -> None:
        out = net_guard.filter_agent_output({
            "text": "video",
            "video_url": "http://192.168.1.10:8123/local/cam.mp4",
            "audio_url": "http://127.0.0.1/secret.mp3",
        })
        self.assertNotIn("video_url", out)
        self.assertNotIn("audio_url", out)

    def test_keeps_public_and_data_url(self) -> None:
        out = net_guard.filter_agent_output({
            "text": "ok",
            "image_url": "https://api.telegram.org/file/botX/photo.jpg",
        })
        self.assertEqual(out.get("image_url"),
                         "https://api.telegram.org/file/botX/photo.jpg")
        data = "data:image/png;base64,aaa"
        out2 = net_guard.filter_agent_output({"image_url": data})
        self.assertEqual(out2.get("image_url"), data)

    def test_keeps_self_images_url(self) -> None:
        out = net_guard.filter_agent_output({
            "image_url": "http://127.0.0.1/images/gen/foo.png",
        })
        self.assertEqual(out.get("image_url"),
                         "http://127.0.0.1/images/gen/foo.png")

    def test_drops_path_outside_data(self) -> None:
        out = net_guard.filter_agent_output({
            "video_path": "/etc/passwd",
            "text": "x",
        })
        self.assertNotIn("video_path", out)

    def test_is_allowed_egress_url_helper(self) -> None:
        self.assertFalse(net_guard.is_allowed_egress_url(
            "http://169.254.169.254/"))
        self.assertFalse(net_guard.is_allowed_egress_url(
            "http://10.0.0.5/a.png"))
        self.assertTrue(net_guard.is_allowed_egress_url(
            "https://api.telegram.org/x"))
        self.assertTrue(net_guard.is_allowed_egress_url(
            "data:image/jpeg;base64,xx"))

    def test_scrub_private_urls_in_text(self) -> None:
        t = net_guard.scrub_private_urls_in_text(
            "xem http://127.0.0.1/admin và https://api.telegram.org/ok")
        self.assertIn("[url_blocked]", t)
        self.assertIn("https://api.telegram.org/ok", t)


if __name__ == "__main__":
    unittest.main()
