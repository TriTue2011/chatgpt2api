import unittest
from types import SimpleNamespace
from unittest import mock

import api.support as api_support


class ImageBaseUrlApiTests(unittest.TestCase):
    def setUp(self) -> None:
        # `trusted_hosts` rỗng = chưa bật allowlist, đúng mặc định của
        # `config.trusted_hosts`. Thiếu thuộc tính này thì `resolve_image_base_url`
        # ném AttributeError trước cả khi tới phần đang muốn kiểm.
        self.fake_config = SimpleNamespace(base_url="https://public.example.com",
                                           trusted_hosts=[])
        patcher = mock.patch.object(api_support, "config", self.fake_config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_base_url_chi_dung_khi_request_khong_co_host(self) -> None:
        """`base_url` là đường lui cuối, KHÔNG còn được ưu tiên trước host.

        Đổi từ 31/07: trả `config.base_url` trước (thường là http://<IP LAN>)
        nghĩa là mở trang qua domain HTTPS thì mọi ảnh trỏ http://IP — trình
        duyệt chặn Mixed Content và IP LAN không tới được từ ngoài. Xem
        docstring của `resolve_image_base_url`.
        """
        co_host = SimpleNamespace(
            url=SimpleNamespace(scheme="http", netloc="127.0.0.1:8000"),
            headers={"host": "127.0.0.1:8000"},
        )
        self.assertEqual(api_support.resolve_image_base_url(co_host),
                         "http://127.0.0.1:8000")

        khong_host = SimpleNamespace(
            url=SimpleNamespace(scheme="http", netloc="127.0.0.1:8000"),
            headers={},
        )
        self.assertEqual(api_support.resolve_image_base_url(khong_host),
                         "https://public.example.com")

    def test_falls_back_to_request_host(self) -> None:
        self.fake_config.base_url = ""
        request = SimpleNamespace(
            url=SimpleNamespace(scheme="http", netloc="127.0.0.1:8000"),
            headers={"host": "internal.example:9000"},
        )

        self.assertEqual(api_support.resolve_image_base_url(request), "http://internal.example:9000")

    def test_falls_back_to_request_netloc_when_host_missing(self) -> None:
        self.fake_config.base_url = ""
        request = SimpleNamespace(
            url=SimpleNamespace(scheme="https", netloc="public.example.com"),
            headers={},
        )

        self.assertEqual(api_support.resolve_image_base_url(request), "https://public.example.com")


if __name__ == "__main__":
    unittest.main()
