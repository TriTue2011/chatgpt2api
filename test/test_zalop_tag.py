"""Zalo Personal group tag gate — native mention + keyword."""
from __future__ import annotations

import unittest

from services.zalo_personal import _parse_event, is_bot_tagged


class ZalopTagTests(unittest.TestCase):
    OWN = "475796162066271393"

    def test_native_mention_without_keyword(self) -> None:
        ev = {
            "account_id": self.OWN,
            "text": "@Botmitbap xin chào",
            "mentions": [{"uid": self.OWN, "pos": 0, "len": 10}],
        }
        self.assertTrue(is_bot_tagged(ev, ""))
        self.assertTrue(is_bot_tagged(ev, "@anything-else"))  # native still wins

    def test_no_mention_no_keyword(self) -> None:
        ev = {"account_id": self.OWN, "text": "xin chào", "mentions": []}
        self.assertFalse(is_bot_tagged(ev, ""))

    def test_keyword_match(self) -> None:
        ev = {"account_id": self.OWN, "text": "hey @Bot please help", "mentions": []}
        self.assertTrue(is_bot_tagged(ev, "@Bot"))
        self.assertFalse(is_bot_tagged(ev, "@Other"))

    def test_parse_event_keeps_mentions(self) -> None:
        body = {
            "_accountId": self.OWN,
            "type": "1",
            "threadId": "6683680861034270202",
            "data": {
                "idTo": "6683680861034270202",
                "uidFrom": "u1",
                "msgType": "webchat",
                "content": "@Botmitbap xin chào",
                "mentions": [{"uid": self.OWN, "pos": 0, "len": 10}],
            },
        }
        ev = _parse_event(body)
        self.assertEqual(ev["account_id"], self.OWN)
        self.assertTrue(ev["mentions"])
        self.assertTrue(is_bot_tagged(ev, ""))

    def test_parse_event_prefers_template_safe_thread_contract(self) -> None:
        body = {
            "_accountId": self.OWN,
            "_threadRef": "zalo:2036121378794772276",
            "_threadType": 1,
            # Truong cu co tinh de sai: contract moi phai duoc uu tien.
            "threadId": "999",
            "type": 0,
            "data": {
                "uidFrom": "6683680861034270202",
                "content": "xin chao",
            },
        }
        ev = _parse_event(body)
        self.assertEqual(ev["thread_id"], "2036121378794772276")
        self.assertEqual(ev["thread_type"], 1)


if __name__ == "__main__":
    unittest.main()
