"""url_guard của MCP Hub: chặn SSRF, allowlist domain, giới hạn dung lượng.

Báo cáo bảo mật 08/08: read_url / get_law_detail / analyze_source nhận URL tự
do, không chặn loopback hay private IP, tự đi redirect, đọc không giới hạn. Một
câu prompt injection là đủ để đọc metadata cloud hoặc gọi API nội bộ.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC / "vn-mcp-hub"))

from src.url_guard import SsrfBlocked, check_url, url_is_internal  # noqa: E402


def _dns(*ips):
    """Giả getaddrinfo trả đúng các IP cho trước."""
    return mock.patch(
        "src.url_guard.socket.getaddrinfo",
        lambda host, port, **kw: [(2, 1, 6, "", (ip, port)) for ip in ips],
    )


class GiaoThucTests(unittest.TestCase):
    def test_chan_scheme_la(self):
        for u in ("file:///etc/passwd", "gopher://x/", "ftp://a/b", "javascript:alert(1)"):
            with self.assertRaises(SsrfBlocked):
                check_url(u)

    def test_thieu_host(self):
        with self.assertRaises(SsrfBlocked):
            check_url("http:///no-host")


class DiaChiNoiBoTests(unittest.TestCase):
    def test_chan_ip_viet_thang(self):
        for u in (
            "http://127.0.0.1:3001/api/accounts",   # zalo-server cùng container
            "http://169.254.169.254/latest/meta-data/",  # metadata cloud
            "http://10.0.0.5/",
            "http://192.168.1.1/",
            "http://172.16.10.38/",
            "http://[::1]/",
            "http://0.0.0.0/",
        ):
            with self.assertRaises(SsrfBlocked, msg=u):
                check_url(u)

    def test_chan_ipv6_boc_ipv4(self):
        """::ffff:127.0.0.1 là loopback trá hình — không bóc ra là lọt sạch."""
        with self.assertRaises(SsrfBlocked):
            check_url("http://[::ffff:127.0.0.1]/")

    def test_chan_ten_mien_tro_ve_noi_bo(self):
        with _dns("127.0.0.1"):
            with self.assertRaises(SsrfBlocked):
                check_url("http://evil.example.com/")

    def test_chan_khi_chi_mot_ban_ghi_noi_bo(self):
        """Trộn một IP public với một IP nội bộ vẫn phải chặn."""
        with _dns("93.184.216.34", "192.168.0.9"):
            with self.assertRaises(SsrfBlocked):
                check_url("http://mixed.example.com/")

    def test_cho_qua_dia_chi_public(self):
        with _dns("93.184.216.34"):
            self.assertEqual(
                check_url("https://example.com/a"), "https://example.com/a"
            )


class AllowlistTests(unittest.TestCase):
    def test_ngoai_allowlist_bi_chan(self):
        with _dns("93.184.216.34"):
            with self.assertRaises(SsrfBlocked):
                check_url("https://example.com/x", ("thuvienphapluat.vn",))

    def test_ten_mien_con_duoc_chap_nhan(self):
        with _dns("93.184.216.34"):
            self.assertTrue(
                check_url("https://vbpl.thuvienphapluat.vn/x", ("thuvienphapluat.vn",))
            )


class UrlIsInternalTests(unittest.TestCase):
    """Bộ lọc request của trình duyệt: không được ném lỗi, chỉ trả True/False."""

    def test_noi_bo_true(self):
        self.assertTrue(url_is_internal("http://127.0.0.1/x"))
        self.assertTrue(url_is_internal("data:text/html,<b>x"))
        self.assertTrue(url_is_internal("khong-phai-url"))

    def test_public_false(self):
        with _dns("93.184.216.34"):
            self.assertFalse(url_is_internal("https://example.com/"))


if __name__ == "__main__":
    unittest.main()
