"""Shared tag_gate_allows — required + empty keyword must not mute native tags."""
from __future__ import annotations

import unittest

from services.agent.capabilities import tag_gate_allows


class TagGateTests(unittest.TestCase):
    def test_not_required(self) -> None:
        self.assertTrue(tag_gate_allows(required=False, keyword="", text="hi"))

    def test_required_empty_kw_needs_native_or_platform(self) -> None:
        # Bug cũ: required + kw rỗng → luôn False
        self.assertFalse(tag_gate_allows(
            required=True, keyword="", text="@Bot xin chào", native_tagged=False,
        ))
        self.assertTrue(tag_gate_allows(
            required=True, keyword="", text="@Bot xin chào", native_tagged=True,
        ))
        # Zalo OA group delivery
        self.assertTrue(tag_gate_allows(
            required=True, keyword="", text="xin chào",
            native_tagged=False, platform_group_delivery=True,
        ))

    def test_keyword_match(self) -> None:
        self.assertTrue(tag_gate_allows(
            required=True, keyword="@Bot", text="hey @Bot hi", native_tagged=False,
        ))
        self.assertFalse(tag_gate_allows(
            required=True, keyword="@Bot", text="hey no tag", native_tagged=False,
        ))
        # keyword miss but native ok
        self.assertTrue(tag_gate_allows(
            required=True, keyword="@Other", text="x", native_tagged=True,
        ))


if __name__ == "__main__":
    unittest.main()
