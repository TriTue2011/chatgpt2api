"""Xoay API key của provider gemini_free khi dính 429.

Bản cũ retry bằng cách gọi ĐỆ QUY chính chat_completions(): đầu hàm xoá
_attempted_keys nên bộ đếm reset về 0 sau mỗi vòng, và self.api_key là
property TỰ XOAY mỗi lần đọc (bị đọc 4 lần trong một nhánh retry) nên mọi
sổ sách rơi vào key sai. Đo được trên production: MỘT request nã Google 981
lượt trong ~150 giây rồi chết bằng "maximum recursion depth exceeded", còn
caller thì treo tới timeout.

Các test dưới đây chốt: mỗi key thử tối đa MỘT lần, đánh dấu limited đúng
key vừa lỗi, và key đang trong cooldown bị bỏ qua.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.config import config  # noqa: E402
from services.providers import gemini_free  # noqa: E402

_KEYS = ["key-a", "key-b", "key-c", "key-d", "key-e", "key-f"]


class _FakeResp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeRequests:
    """Thế chỗ module curl_cffi.requests ở phạm vi module gemini_free."""

    class RequestsError(Exception):
        pass

    def __init__(self, status_by_key: dict[str, int]):
        self.status_by_key = status_by_key
        self.calls: list[str] = []          # key của từng lượt gọi, theo thứ tự

    def post(self, url, headers=None, json=None, timeout=None, stream=None):
        key = (headers or {}).get("x-goog-api-key", "")
        self.calls.append(key)
        return _FakeResp(self.status_by_key.get(key, 200))


class GeminiKeyRotationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._requests = gemini_free.requests
        self._parse = gemini_free._parse_gemini_stream
        gemini_free._parse_gemini_stream = lambda resp, model: {"ok": True}
        self._cfg = mock.patch.dict(
            config.data,
            {"providers": {"gemini_free": {"enabled": True, "api_key": "",
                                           "api_keys": list(_KEYS)}}})
        self._cfg.start()

    def tearDown(self) -> None:
        gemini_free.requests = self._requests
        gemini_free._parse_gemini_stream = self._parse
        self._cfg.stop()

    def _provider(self) -> gemini_free.GeminiProvider:
        return gemini_free.GeminiProvider()

    def test_all_keys_429_fails_after_one_pass(self) -> None:
        """6 key đều 429 → đúng 6 lượt gọi rồi lỗi sạch — không phải 981."""
        fake = _FakeRequests({k: 429 for k in _KEYS})
        gemini_free.requests = fake
        with self.assertRaises(RuntimeError):
            self._provider().chat_completions([{"role": "user", "content": "hi"}])
        self.assertEqual(len(fake.calls), len(_KEYS),
                         "mỗi key thử đúng MỘT lần, không đệ quy")
        self.assertEqual(sorted(set(fake.calls)), sorted(_KEYS),
                         "phải thử đủ cả 6 key, không lặp key nào")

    def test_429_marks_the_failed_key_then_next_key_succeeds(self) -> None:
        first, second = _KEYS[0], _KEYS[1]
        fake = _FakeRequests({first: 429})           # các key khác trả 200
        gemini_free.requests = fake
        p = self._provider()
        out = p.chat_completions([{"role": "user", "content": "hi"}])
        self.assertEqual(out, {"ok": True})
        self.assertEqual(fake.calls, [first, second], "429 → sang đúng key kế")
        self.assertIn(first, p._rate_limited, "key VỪA LỖI phải bị đánh dấu")
        self.assertNotIn(second, p._rate_limited, "key thành công không bị vạ lây")

    def test_cooldown_keys_are_skipped(self) -> None:
        import time
        fake = _FakeRequests({})
        gemini_free.requests = fake
        p = self._provider()
        p._rate_limited = {k: time.time() + 60 for k in _KEYS[:5]}
        out = p.chat_completions([{"role": "user", "content": "hi"}])
        self.assertEqual(out, {"ok": True})
        self.assertEqual(fake.calls, [_KEYS[5]], "chỉ gọi key còn sống duy nhất")

    def test_all_keys_in_cooldown_fails_without_any_call(self) -> None:
        import time
        fake = _FakeRequests({})
        gemini_free.requests = fake
        p = self._provider()
        p._rate_limited = {k: time.time() + 60 for k in _KEYS}
        with self.assertRaises(RuntimeError):
            p.chat_completions([{"role": "user", "content": "hi"}])
        self.assertEqual(fake.calls, [], "đang cooldown cả loạt thì đừng nã thêm")


if __name__ == "__main__":
    unittest.main()
