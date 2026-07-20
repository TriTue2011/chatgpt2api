"""Test verbalize — nhất là nhánh keep_edges cho stream TTS (chống dính chữ
và chống emoji lọt qua khi emoji là một delta chunk riêng)."""
import unittest

from services.verbalize import verbalize


class VerbalizeTests(unittest.TestCase):
    def test_strips_emoji_whole_text(self) -> None:
        self.assertEqual(verbalize("Xin chào 😊"), "Xin chào")

    def test_percent_becomes_words(self) -> None:
        out = verbalize("Độ ẩm 50%")
        self.assertIn("phần trăm", out)
        self.assertNotIn("%", out)

    def test_keep_edges_preserves_boundary_spaces(self) -> None:
        # "Xin " + "chào" stream thành 2 chunk — mất dấu cách biên là dính chữ.
        self.assertEqual(verbalize("Xin ", keep_edges=True), "Xin ")
        self.assertEqual(verbalize("chào anh", keep_edges=True), "chào anh")

    def test_keep_edges_emoji_only_chunk_is_stripped(self) -> None:
        # Model hay tách emoji thành delta riêng → chunk toàn emoji phải bị xoá,
        # chỉ giữ khoảng trắng biên (regression cho bug trả nguyên văn text).
        self.assertEqual(verbalize("😊", keep_edges=True), "")
        self.assertEqual(verbalize(" 😊 ", keep_edges=True), "  ")

    def test_keep_edges_whitespace_only_unchanged(self) -> None:
        self.assertEqual(verbalize("   ", keep_edges=True), "   ")


if __name__ == "__main__":
    unittest.main()
