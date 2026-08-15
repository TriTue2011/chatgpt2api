"""Gemini Web vision must not delegate client-controlled URL fetching to solver."""

from __future__ import annotations

import base64
import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import net_guard  # noqa: E402
from services.providers import web_proxy  # noqa: E402


class _Response:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"text": "ok"}


class WebProxyVisionEgressTests(unittest.TestCase):
    def test_gateway_fetches_public_url_then_sends_data_url_to_solver(self) -> None:
        with mock.patch.object(web_proxy, "_captcha_solver_cfg", return_value={"url": "http://solver", "api_key": ""}), \
                mock.patch.object(net_guard, "fetch_media", return_value=b"png-bytes") as fetch, \
                mock.patch.object(web_proxy.httpx, "post", return_value=_Response()) as post:
            text, _meta = web_proxy._call_web_vision(
                "gemini-web", "profile", "https://cdn.example.test/image.png", "describe"
            )

        self.assertEqual(text, "ok")
        fetch.assert_called_once_with(
            "https://cdn.example.test/image.png", timeout=60, max_bytes=25 * 1024 * 1024
        )
        sent = post.call_args.kwargs["json"]["image"]
        self.assertEqual(sent, "data:image/png;base64," + base64.b64encode(b"png-bytes").decode())

    def test_private_url_is_rejected_before_solver_is_called(self) -> None:
        with mock.patch.object(web_proxy, "_captcha_solver_cfg", return_value={"url": "http://solver", "api_key": ""}), \
                mock.patch.object(net_guard, "fetch_media", side_effect=net_guard.BlockedURL("private")), \
                mock.patch.object(web_proxy.httpx, "post") as post:
            with self.assertRaises(net_guard.BlockedURL):
                web_proxy._call_web_vision(
                    "gemini-web", "profile", "http://127.0.0.1/private.png", "describe"
                )
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
