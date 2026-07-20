"""HA service catalog helpers — offline unit tests (no live HA)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import ha_client as hc  # noqa: E402


class ServiceCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        hc._services_catalog = {}
        hc._services_catalog_ts = 0.0

    def tearDown(self) -> None:
        hc._services_catalog = {}
        hc._services_catalog_ts = 0.0

    def test_get_services_names_from_catalog(self) -> None:
        sample = [
            {
                "domain": "light",
                "services": {
                    "turn_on": {
                        "name": "Turn on",
                        "description": "Turn on light",
                        "fields": {
                            "brightness_pct": {
                                "required": False,
                                "description": "Brightness percent",
                                "example": 50,
                                "selector": {"number": {}},
                            },
                            "color_temp_kelvin": {
                                "description": "Color temperature",
                            },
                        },
                    },
                    "turn_off": {"name": "Turn off", "fields": {}},
                },
            },
            {
                "domain": "climate",
                "services": {
                    "set_temperature": {
                        "fields": {
                            "temperature": {"required": True, "description": "Target"},
                            "hvac_mode": {"description": "Mode"},
                        },
                    },
                },
            },
        ]

        class _Resp:
            def read(self):
                import json
                return json.dumps(sample).encode()

        with mock.patch.object(hc, "_get_ha_config", return_value={
            "url": "http://ha.local:8123", "token": "t",
        }):
            with mock.patch("urllib.request.urlopen", return_value=_Resp()):
                cat = hc.get_service_catalog(use_cache=False)

        self.assertIn("light", cat)
        self.assertIn("brightness_pct", cat["light"]["turn_on"]["fields"])
        names = hc._get_services()
        self.assertEqual(names["light"], ["turn_off", "turn_on"])

        fields = hc.get_service_fields("light", "turn_on")
        self.assertIn("color_temp_kelvin", fields)

        text = hc.format_service_fields("light", "turn_on")
        self.assertIn("brightness_pct", text)
        self.assertIn("light.turn_on", text)

    def test_describe_entity_actions_offline(self) -> None:
        hc._services_catalog = {
            "light": {
                "turn_on": {
                    "description": "Turn on",
                    "fields": {
                        "brightness_pct": {"description": "%"},
                        "rgb_color": {"description": "RGB"},
                    },
                },
                "turn_off": {"fields": {}},
            },
        }
        hc._services_catalog_ts = 1e18  # never expire in test
        state = {
            "entity_id": "light.living",
            "state": "on",
            "attributes": {
                "friendly_name": "Đèn khách",
                "supported_color_modes": ["brightness", "color_temp"],
                "min_color_temp_kelvin": 2700,
                "max_color_temp_kelvin": 6500,
            },
        }
        with mock.patch.object(hc, "get_state", return_value=state):
            text = hc.describe_entity_actions("light.living", state=state)
        self.assertIn("Đèn khách", text)
        self.assertIn("turn_on", text)
        self.assertIn("brightness_pct", text)
        self.assertTrue("kelvin" in text.lower() or "2700" in text)


class ControlNormalizeTests(unittest.TestCase):
    def test_normalize_light_opts(self) -> None:
        self.assertEqual(
            hc.normalize_control_service("light", "set_brightness", has_light_opts=True),
            "turn_on",
        )
        self.assertEqual(
            hc.normalize_control_service("cover", "set_position"),
            "set_cover_position",
        )
        self.assertEqual(
            hc.normalize_control_service("climate", "set_temp"),
            "set_temperature",
        )
        self.assertEqual(
            hc.normalize_control_service("light", "tắt"),
            "turn_off",
        )


if __name__ == "__main__":
    unittest.main()
