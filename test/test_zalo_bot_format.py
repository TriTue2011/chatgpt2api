"""Zalo Bot Platform rich text (parse_mode markdown + color tags)."""
import unittest

from services.zalo_bot_format import (
    build_send_message_payload,
    emphasize_for_zalo_bot,
    resolve_zalo_bot_color,
    resolve_zalo_bot_size,
    styles_personal_to_bot_api,
    wrap_bold_with_md_color,
    wrap_bold_with_md_style,
)


class ZaloBotFormatTests(unittest.TestCase):
    def test_color_wrap_keeps_double_asterisk_bold(self) -> None:
        # Docs: **đậm** — KHÔNG đổi thành * (đó là nghiêng)
        out = wrap_bold_with_md_color("Ngoài trời **29°C**", "orange")
        self.assertIn("{orange}**29°C**{/orange}", out)

    def test_no_color_when_off(self) -> None:
        self.assertEqual(wrap_bold_with_md_color("**hi**", None), "**hi**")

    def test_payload_markdown_mode(self) -> None:
        ps = build_send_message_payload("chat1", "Giá **100** đồng", rich=True, bot={
            "markdown_color": "red",
            "emphasis_enabled": True,
            "emphasis_numbers": True,
        })
        self.assertEqual(ps[0]["parse_mode"], "markdown")
        self.assertEqual(ps[0]["chat_id"], "chat1")
        # emphasis or bold present
        self.assertIn("100", ps[0]["text"])

    def test_payload_plain_no_parse_mode(self) -> None:
        ps = build_send_message_payload("c", "a@b.com _raw_", rich=False)
        self.assertNotIn("parse_mode", ps[0])
        self.assertEqual(ps[0]["text"], "a@b.com _raw_")

    def test_resolve_color_default_orange(self) -> None:
        self.assertEqual(resolve_zalo_bot_color({}), "orange")
        self.assertIsNone(resolve_zalo_bot_color({"markdown_color": "none"}))

    def test_personal_styles_to_bot_api_array(self) -> None:
        bot_st = styles_personal_to_bot_api([
            {"start": 0, "len": 4, "st": "c_f27806,b"},
        ])
        self.assertEqual(bot_st[0]["st"], ["c_f27806", "b"])

    def test_emphasize_numbers_bold(self) -> None:
        out = emphasize_for_zalo_bot(
            "Nhiệt độ: 30°C",
            bot={"emphasis_enabled": True, "emphasis_numbers": True,
                 "emphasis_units": True, "emphasis_key_info": True,
                 "markdown_color": "none"},
        )
        self.assertIn("**", out)

    def test_big_size_wrap(self) -> None:
        out = wrap_bold_with_md_style("**hi**", color="green", size="big")
        self.assertIn("{green}", out)
        self.assertIn("{big}", out)
        self.assertIn("**hi**", out)

    def test_resolve_size_from_admin(self) -> None:
        bot = {
            "admin_entries": [
                {"chat_id": "abc", "markdown_size": "big", "markdown_color": "red"},
            ],
        }
        self.assertEqual(resolve_zalo_bot_size(bot, "abc"), "big")
        self.assertEqual(resolve_zalo_bot_color(bot, "abc"), "red")
        self.assertEqual(resolve_zalo_bot_size(bot, "other"), "normal")


if __name__ == "__main__":
    unittest.main()
