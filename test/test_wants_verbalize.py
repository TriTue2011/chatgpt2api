"""AI text combo phải GIỮ ký tự (không verbalize) khi mọi bước có :text."""
from __future__ import annotations

import unittest
from unittest import mock

from services.protocol import openai_v1_chat_complete as chat


class WantsVerbalizeTests(unittest.TestCase):
    def test_explicit_text_marker(self) -> None:
        self.assertFalse(chat._wants_verbalize("cx/auto:text", []))
        self.assertFalse(chat._wants_verbalize("gma/auto:text", []))

    def test_explicit_tts_marker(self) -> None:
        self.assertTrue(chat._wants_verbalize("cx/auto:tts", []))

    def test_plain_model_defaults_verbalize(self) -> None:
        self.assertTrue(chat._wants_verbalize("cx/auto", []))

    def test_ai_text_combo_keeps_literal(self) -> None:
        """Tên combo 'AI text' (không có :text) nhưng steps đều :text → giữ ký tự."""
        combos = {
            "AI text": ["cx/auto:text", "gma/auto:text"],
            "AI voice": ["cx/auto:tts"],
        }
        with mock.patch.object(chat, "_combo_wants_keep_literal", wraps=chat._combo_wants_keep_literal):
            # inject config via mock of config module used inside _wants_verbalize
            class _Cfg:
                data = {"combo_models": combos, "pipeline_models": {}}

            with mock.patch.dict("sys.modules", {}):
                with mock.patch("services.config.config", _Cfg(), create=True):
                    # Patch the import path used inside function
                    import services.config as cfg_mod
                    old = getattr(cfg_mod, "config", None)
                    cfg_mod.config = _Cfg()  # type: ignore[assignment]
                    try:
                        self.assertFalse(chat._wants_verbalize("AI text", []))
                        self.assertTrue(chat._wants_verbalize("AI voice", []))
                    finally:
                        if old is not None:
                            cfg_mod.config = old

    def test_combo_helper_direct(self) -> None:
        combos = {
            "AI text": ["cx/auto:text", "gma/auto:text"],
            "mixed": ["cx/auto:text", "gma/auto"],
            "voice": ["cx/auto:tts"],
        }
        self.assertTrue(chat._combo_wants_keep_literal("AI text", combos))
        self.assertFalse(chat._combo_wants_keep_literal("mixed", combos))
        self.assertFalse(chat._combo_wants_keep_literal("voice", combos))
        self.assertIsNone(chat._combo_wants_keep_literal("unknown", combos))


if __name__ == "__main__":
    unittest.main()
