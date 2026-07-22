"""Markdown → Zalo RTF styles (P0 markdown color for Zalo personal + parity HA)."""
import unittest

from services.zalo_markdown import markdown_to_zalo_message


class ZaloMarkdownTests(unittest.TestCase):
    def test_bold_gets_style(self) -> None:
        out = markdown_to_zalo_message("Xin **chào** bạn", color="orange")
        self.assertEqual(out["msg"], "Xin chào bạn")
        self.assertTrue(out["styles"])
        st = out["styles"][0]
        self.assertIn("b", st["st"])
        self.assertIn("c_f27806", st["st"])  # orange
        self.assertEqual(st["len"], 4)  # chào

    def test_none_color_no_c_token(self) -> None:
        out = markdown_to_zalo_message("**hi**", color="none")
        self.assertEqual(out["msg"], "hi")
        self.assertTrue(out["styles"])
        self.assertEqual(out["styles"][0]["st"], "b")

    def test_heading(self) -> None:
        out = markdown_to_zalo_message("# Tiêu đề\nbody", color="gold")
        self.assertIn("Tiêu đề", out["msg"])
        self.assertTrue(any("f_20" in s["st"] or "b" in s["st"] for s in out["styles"]))

    def test_plain_no_styles(self) -> None:
        out = markdown_to_zalo_message("chỉ chữ thường", color="orange")
        self.assertEqual(out["msg"], "chỉ chữ thường")
        self.assertEqual(out["styles"], [])


if __name__ == "__main__":
    unittest.main()
