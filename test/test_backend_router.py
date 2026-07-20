from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backend_router import (  # noqa: E402
    _COMBO_MARKER_RE,
    BackendRouter,
    backend_router,
)
from services.account_service import account_service  # noqa: E402
from services.config import config  # noqa: E402


class ResolveModelTests(unittest.TestCase):
    def test_prefix_routes_to_provider(self) -> None:
        self.assertEqual(
            BackendRouter.resolve_model("oc/nemotron-free"), ("opencode", "nemotron-free")
        )
        self.assertEqual(BackendRouter.resolve_model("cx/gpt-5.3"), ("openai_oauth", "gpt-5.3"))

    def test_legacy_codex_prefix_wins_over_chatgpt_prefix(self) -> None:
        # "chatgpt/codex/" phải match TRƯỚC "chatgpt/" (thứ tự dict quan trọng).
        self.assertEqual(
            BackendRouter.resolve_model("chatgpt/codex/gpt-5.3"), ("openai_oauth", "gpt-5.3")
        )
        self.assertEqual(
            BackendRouter.resolve_model("chatgpt/gpt-4"), ("chatgpt_free", "gpt-4")
        )

    def test_bare_prefix_resolves_to_auto(self) -> None:
        self.assertEqual(BackendRouter.resolve_model("cx"), ("openai_oauth", "auto"))
        self.assertEqual(BackendRouter.resolve_model("oc"), ("opencode", "auto"))

    def test_image_prefix(self) -> None:
        self.assertEqual(BackendRouter.resolve_model("sdwebui/sd-v1.5"), ("sdwebui", "sd-v1.5"))

    def test_unprefixed_model_defaults_to_chatgpt(self) -> None:
        with mock.patch.dict(config.data, {"custom_providers": []}):
            self.assertEqual(BackendRouter.resolve_model("gpt-4"), ("chatgpt", "gpt-4"))


class ComboMarkerTests(unittest.TestCase):
    def test_marker_regex_strips_output_format_suffixes(self) -> None:
        self.assertEqual(_COMBO_MARKER_RE.sub("", "auto:text"), "auto")
        self.assertEqual(_COMBO_MARKER_RE.sub("", "auto#raw"), "auto")
        self.assertEqual(_COMBO_MARKER_RE.sub("", "auto:TTS"), "auto")
        # Không strip phần model thật chứa dấu ':' khác marker.
        self.assertEqual(_COMBO_MARKER_RE.sub("", "model:v2"), "model:v2")

    def test_route_combo_strips_markers_before_routing(self) -> None:
        with mock.patch.dict(config.data, {"providers": {}, "model_settings": {}}), \
                mock.patch.object(backend_router, "_get_combo_models",
                                  return_value=["cx/auto:text", "cgf/auto#raw"]):
            routes = backend_router.route_combo("my-combo")
        self.assertEqual(len(routes), 2)
        self.assertEqual(routes[0].provider, "openai_oauth")
        # Marker đã bị strip → không còn ':text' trong model.
        self.assertNotIn(":text", routes[0].model)
        self.assertEqual(routes[1].provider, "chatgpt_free")
        self.assertNotIn("#raw", routes[1].model)


class FreePayloadLimitTests(unittest.TestCase):
    def test_limit_constant_is_100kb(self) -> None:
        self.assertEqual(BackendRouter.FREE_PAYLOAD_LIMIT, 100_000)

    def test_oversized_payload_redirects_to_opencode_when_no_active_accounts(self) -> None:
        big = [{"role": "user", "content": "x" * (BackendRouter.FREE_PAYLOAD_LIMIT + 1)}]
        with mock.patch.dict(config.data, {"providers": {"opencode": {"enabled": True}},
                                           "model_settings": {}, "custom_providers": []}), \
                mock.patch.object(account_service, "_accounts", {}):
            route = backend_router.route("gpt-4", messages=big)
        self.assertEqual(route.provider, "opencode")
        self.assertTrue(route.no_auth)
        self.assertIn("chatgpt", route.fallback_providers)

    def test_small_payload_stays_on_chatgpt(self) -> None:
        small = [{"role": "user", "content": "hello"}]
        with mock.patch.dict(config.data, {"providers": {}, "model_settings": {},
                                           "custom_providers": []}):
            route = backend_router.route("gpt-4", messages=small)
        self.assertEqual(route.provider, "chatgpt")

    def test_oversized_payload_keeps_chatgpt_when_active_account_exists(self) -> None:
        big = [{"role": "user", "content": "x" * (BackendRouter.FREE_PAYLOAD_LIMIT + 1)}]
        with mock.patch.dict(config.data, {"providers": {"opencode": {"enabled": True}},
                                           "model_settings": {}, "custom_providers": []}), \
                mock.patch.object(account_service, "_accounts",
                                  {"tok": {"status": "active"}}):
            route = backend_router.route("gpt-4", messages=big)
        self.assertEqual(route.provider, "chatgpt")


class FallbackDefaultTests(unittest.TestCase):
    def test_auto_resolves_to_provider_default_model(self) -> None:
        with mock.patch.dict(config.data, {"providers": {}, "model_settings": {},
                                           "custom_providers": []}):
            route = backend_router.route("oc/auto")
        self.assertEqual(route.provider, "opencode")
        self.assertEqual(route.model, BackendRouter.PROVIDER_DEFAULT_MODELS["opencode"])

    def test_auto_prefers_user_configured_model(self) -> None:
        with mock.patch.dict(config.data, {
            "providers": {"opencode": {"model": "my-custom"}},
            "model_settings": {}, "custom_providers": [],
        }):
            route = backend_router.route("oc/auto")
        self.assertEqual(route.model, "my-custom")


if __name__ == "__main__":
    unittest.main()
