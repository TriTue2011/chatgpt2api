"""Các provider OpenAI-compatible phải cooldown ĐÚNG key vừa nhận 429."""

from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.config import config  # noqa: E402
from services.providers import agnes, custom_openai, nvidia_nim  # noqa: E402
from services.image_providers import get_image_adapter  # noqa: E402
from services.image_providers.custom_openai_image import CustomOpenAIImageAdapter  # noqa: E402
from services.image_providers.fal_ai import FalAIAdapter  # noqa: E402
from services.image_providers.nvidia_nim_image import NvidiaNimImageAdapter  # noqa: E402
from services.net_guard import BlockedURL  # noqa: E402


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self.text = "rate limited" if status_code == 429 else ""
        self._payload = payload or {"choices": [{"message": {"content": "ok"}}]}
        self.closed = False

    def json(self):
        return self._payload

    def close(self):
        self.closed = True


class _Requests:
    class RequestsError(Exception):
        pass

    def __init__(self, status_by_key: dict[str, int]):
        self.status_by_key = status_by_key
        self.calls: list[str] = []
        self.responses: list[_Response] = []

    def post(self, _url, *, headers=None, **_kwargs):
        key = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
        self.calls.append(key)
        response = _Response(self.status_by_key.get(key, 200))
        self.responses.append(response)
        return response


class _AgnesRequests:
    def __init__(self):
        self.calls: list[str] = []
        self.responses: list[_Response] = []

    def post(self, _url, *, headers=None, **_kwargs):
        self.calls.append((headers or {}).get("Authorization", "").removeprefix("Bearer "))
        response = _Response(429)
        self.responses.append(response)
        return response


class ProviderKeyRotationTests(unittest.TestCase):
    def setUp(self):
        self._custom_requests = custom_openai.requests
        self._nvidia_requests = nvidia_nim.requests

    def tearDown(self):
        custom_openai.requests = self._custom_requests
        nvidia_nim.requests = self._nvidia_requests

    def test_custom_provider_marks_the_key_sent_in_429(self):
        fake = _Requests({"first": 429})
        custom_openai.requests = fake
        provider = custom_openai.CustomOpenAIProvider({
            "name": "test", "base_url": "https://example.test", "api_keys": ["first", "second"],
        })

        response = provider.chat_completions([{"role": "user", "content": "hi"}])

        self.assertEqual(fake.calls, ["first", "second"])
        self.assertIn("first", provider._rate_limited)
        self.assertNotIn("second", provider._rate_limited)
        self.assertTrue(fake.responses[0].closed)
        self.assertTrue(fake.responses[1].closed)
        self.assertEqual(response["choices"][0]["message"]["content"], "ok")

    def test_custom_provider_stops_after_each_key_and_endpoint_once(self):
        fake = _Requests({"first": 429, "second": 429})
        custom_openai.requests = fake
        provider = custom_openai.CustomOpenAIProvider({
            "name": "test", "base_url": "https://one.example.test",
            "base_urls": ["https://two.example.test"],
            "api_keys": ["first", "second"],
        })

        with self.assertRaisesRegex(RuntimeError, "All API keys"):
            provider.chat_completions([{"role": "user", "content": "hi"}])

        self.assertEqual(fake.calls, ["first", "second", "first", "second"])

    def test_nvidia_provider_marks_the_key_sent_in_429(self):
        fake = _Requests({"first": 429})
        nvidia_nim.requests = fake
        provider = nvidia_nim.NvidiaNimProvider()
        with mock.patch.dict(config.data, {
            "providers": {"nvidia_nim": {"api_keys": ["first", "second"]}},
        }):
            response = provider.chat_completions([{"role": "user", "content": "hi"}])

        self.assertEqual(fake.calls, ["first", "second"])
        self.assertIn("first", provider._rate_limited)
        self.assertNotIn("second", provider._rate_limited)
        self.assertTrue(fake.responses[0].closed)
        self.assertTrue(fake.responses[1].closed)
        self.assertEqual(response["choices"][0]["message"]["content"], "ok")

    def test_nvidia_retry_state_does_not_poison_next_request(self):
        fake = _Requests({"first": 429, "second": 429})
        nvidia_nim.requests = fake
        provider = nvidia_nim.NvidiaNimProvider()
        with mock.patch.dict(config.data, {
            "providers": {"nvidia_nim": {"api_keys": ["first", "second"]}},
        }):
            with self.assertRaisesRegex(RuntimeError, "All NVIDIA"):
                provider.chat_completions([{"role": "user", "content": "hi"}])
            provider._rate_limited.clear()
            fake.status_by_key = {"first": 200, "second": 200}
            response = provider.chat_completions([{"role": "user", "content": "hi"}])

        self.assertEqual(response["choices"][0]["message"]["content"], "ok")

    def test_sdwebui_adapter_is_not_shared_across_concurrent_requests(self):
        """Một lượt edit không được đổi endpoint của lượt generate khác."""
        edit = get_image_adapter("sdwebui")
        generate = get_image_adapter("sdwebui")
        self.assertIsNot(edit, generate)
        edit._use_img2img = True
        self.assertTrue(edit.build_url("", {}).endswith("/img2img"))
        self.assertTrue(generate.build_url("", {}).endswith("/txt2img"))

    def test_flow_adapter_is_not_shared_across_concurrent_requests(self):
        first = get_image_adapter("flow")
        second = get_image_adapter("flow")
        self.assertIsNot(first, second)

    def test_nvidia_image_header_uses_the_retry_key_index(self):
        adapter = NvidiaNimImageAdapter()
        headers = adapter.build_headers(
            {"apiKeys": ["first", "second"], "_key_index": 1}, {}, "model", {}
        )
        self.assertEqual(headers["Authorization"], "Bearer second")

    def test_nvidia_image_edit_uses_uploaded_images(self):
        body = NvidiaNimImageAdapter().build_body(
            "black-forest-labs/flux.2-klein-4b",
            {"prompt": "edit", "images": [(b"raw-image", "a.png", "image/png")]},
        )
        self.assertEqual(body["image"], ["data:image/png;base64,cmF3LWltYWdl"])

    def test_custom_image_adapter_rotates_configured_keys(self):
        with mock.patch.dict(config.data, {
            "custom_providers": {
                "test-image": {"base_url": "https://example.test", "api_keys": ["first", "second"]},
            },
        }, clear=False):
            adapter = CustomOpenAIImageAdapter("test-image")
            self.assertEqual(adapter.get_key_count({}), 2)
            headers = adapter.build_headers({"_key_index": 1}, {}, "model", {})
        self.assertEqual(headers["Authorization"], "Bearer second")

    def test_fal_rejects_untrusted_polling_url(self):
        response = _Response(200, {"status_url": "http://127.0.0.1:8005/internal"})
        with self.assertRaises(BlockedURL):
            FalAIAdapter().parse_response(response)

    def test_agnes_stops_when_every_key_is_in_cooldown(self):
        provider = agnes.AgnesProvider()
        fake = _AgnesRequests()
        with mock.patch.object(agnes, "requests", fake), \
                mock.patch.object(provider, "_get_keys", return_value=["first", "second"]):
            with self.assertRaisesRegex(RuntimeError, "cooldown"):
                provider._post_with_failover("https://agnes.example.test/chat", {"model": "x"})

        self.assertEqual(fake.calls, ["first", "second"])
        self.assertTrue(all(response.closed for response in fake.responses))


if __name__ == "__main__":
    unittest.main()
