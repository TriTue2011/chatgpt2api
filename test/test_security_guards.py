"""Test lớp bảo mật P0: SSRF net_guard + vault không rò cross-session."""
import unittest

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


if __name__ == "__main__":
    unittest.main()
