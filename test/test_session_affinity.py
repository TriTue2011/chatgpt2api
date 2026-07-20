from __future__ import annotations

import os
import time
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.config import config  # noqa: E402
from services.session_affinity import SessionAffinity  # noqa: E402


def _sp(**over):
    base = {"enabled": True, "weighted": True, "sticky_ttl_seconds": 900,
            "circuit_threshold": 3, "circuit_open_seconds": 60}
    base.update(over)
    return mock.patch.dict(config.data, {"smart_pool": base})


class SessionKeyTests(unittest.TestCase):
    def test_user_field_wins(self) -> None:
        key = SessionAffinity.session_key({"user": "alice"}, [{"role": "user", "content": "hi"}])
        self.assertEqual(key, "u:alice")

    def test_fallback_hashes_model_plus_first_user_message(self) -> None:
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "câu hỏi đầu"}]
        k1 = SessionAffinity.session_key({"model": "cx/auto"}, msgs)
        k2 = SessionAffinity.session_key({"model": "cx/auto"}, msgs + [{"role": "user", "content": "lượt sau"}])
        self.assertTrue(k1 and k1.startswith("h:"))
        self.assertEqual(k1, k2)  # message đầu ổn định suốt hội thoại
        k3 = SessionAffinity.session_key({"model": "oc/auto"}, msgs)
        self.assertNotEqual(k1, k3)  # model khác → phiên khác

    def test_multimodal_content_and_empty(self) -> None:
        msgs = [{"role": "user", "content": [{"type": "text", "text": "mô tả ảnh"}]}]
        self.assertTrue(SessionAffinity.session_key({}, msgs))
        self.assertIsNone(SessionAffinity.session_key({}, []))


class StickyMapTests(unittest.TestCase):
    def test_bind_get_roundtrip_and_ttl(self) -> None:
        sa = SessionAffinity()
        with _sp(sticky_ttl_seconds=900):
            sa.bind("free", "u:alice", "tok-1")
            self.assertEqual(sa.get("free", "u:alice"), "tok-1")
            self.assertIsNone(sa.get("codex", "u:alice"))  # pool khác không dính
            # Hết TTL → mất
            sa._map["free|u:alice"] = ("tok-1", time.time() - 1)
            self.assertIsNone(sa.get("free", "u:alice"))

    def test_evict_token_removes_all_sessions_of_token(self) -> None:
        sa = SessionAffinity()
        with _sp():
            sa.bind("free", "u:a", "tok-x")
            sa.bind("free", "u:b", "tok-x")
            sa.bind("free", "u:c", "tok-y")
            sa.evict_token("tok-x")
            self.assertIsNone(sa.get("free", "u:a"))
            self.assertIsNone(sa.get("free", "u:b"))
            self.assertEqual(sa.get("free", "u:c"), "tok-y")

    def test_disabled_or_zero_ttl_is_noop(self) -> None:
        sa = SessionAffinity()
        with _sp(enabled=False):
            sa.bind("free", "u:a", "tok-1")
            self.assertIsNone(sa.get("free", "u:a"))
        with _sp(sticky_ttl_seconds=0):
            sa.bind("free", "u:a", "tok-1")
            self.assertIsNone(sa.get("free", "u:a"))

    def test_lru_cap(self) -> None:
        sa = SessionAffinity()
        with _sp():
            for i in range(2005):
                sa.bind("free", f"u:{i}", f"tok-{i}")
            self.assertLessEqual(len(sa._map), 2000)
            self.assertIsNone(sa.get("free", "u:0"))       # mục cũ nhất bị đẩy
            self.assertEqual(sa.get("free", "u:2004"), "tok-2004")


if __name__ == "__main__":
    unittest.main()
