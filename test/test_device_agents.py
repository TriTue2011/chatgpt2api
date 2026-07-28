"""Sổ đăng ký device agent + allowlist đường dẫn.

Đây là mặt an toàn quan trọng nhất của tính năng: agent chạy trên máy thật của
người dùng, rò quyền ở lớp này là đọc/ghi được ngoài phạm vi đã cho phép. Các
test dưới đây chốt hành vi FAIL-CLOSED: thiếu cấu hình, token ngắn, leo thư
mục, hay tiền tố khớp nửa vời đều phải bị TỪ CHỐI.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import device_agents as da  # noqa: E402
from services.config import config  # noqa: E402

_TOKEN = "tok_" + "x" * 28


def _reg(**over):
    base = {"laptop": {"token": _TOKEN, "paths": ["/home/me/project"],
                       "can_write": False, "enabled": True, "label": "Laptop"}}
    base["laptop"].update(over)
    return mock.patch.dict(config.data, {"device_agents": base})


class _FakeSession:
    """Đủ dùng cho path_allowed — không cần WebSocket thật."""

    def __init__(self, paths, can_write=False):
        self._paths = paths
        self._cw = can_write

    @property
    def allowed_paths(self):
        return self._paths

    @property
    def can_write(self):
        return self._cw


class TokenResolveTests(unittest.TestCase):
    def test_valid_token_resolves(self) -> None:
        with _reg():
            got = da.resolve_token(_TOKEN)
        self.assertIsNotNone(got)
        self.assertEqual(got[0], "laptop")

    def test_wrong_token_rejected(self) -> None:
        with _reg():
            self.assertIsNone(da.resolve_token("tok_" + "y" * 28))

    def test_short_token_rejected_outright(self) -> None:
        """Token ngắn là đoán được — chặn ngay, đừng để lọt vào so sánh."""
        with _reg(token="abc"):
            self.assertIsNone(da.resolve_token("abc"))

    def test_disabled_device_rejected(self) -> None:
        with _reg(enabled=False):
            self.assertIsNone(da.resolve_token(_TOKEN))

    def test_empty_registry_rejects_everything(self) -> None:
        with mock.patch.dict(config.data, {"device_agents": {}}):
            self.assertIsNone(da.resolve_token(_TOKEN))


class PathAllowlistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.s = _FakeSession(["/home/me/project", "/var/log"])

    def test_exact_root_allowed(self) -> None:
        self.assertTrue(da.path_allowed(self.s, "/home/me/project"))

    def test_child_allowed(self) -> None:
        self.assertTrue(da.path_allowed(self.s, "/home/me/project/src/app.py"))
        self.assertTrue(da.path_allowed(self.s, "/var/log/syslog"))

    def test_outside_denied(self) -> None:
        for p in ("/etc/passwd", "/home/me/secrets", "/", "/home"):
            self.assertFalse(da.path_allowed(self.s, p), p)

    def test_sibling_prefix_not_confused_with_root(self) -> None:
        """'/home/me/project-secret' KHÔNG được coi là con của '/home/me/project'."""
        self.assertFalse(da.path_allowed(self.s, "/home/me/project-secret/x"))
        self.assertFalse(da.path_allowed(self.s, "/var/logs/other"))

    def test_traversal_denied(self) -> None:
        for p in ("/home/me/project/../../etc/passwd",
                  "/home/me/project/..",
                  "/var/log/../../etc/shadow"):
            self.assertFalse(da.path_allowed(self.s, p), p)

    def test_windows_separator_normalised(self) -> None:
        s = _FakeSession(["C:/Users/me/proj"])
        self.assertTrue(da.path_allowed(s, "C:\\Users\\me\\proj\\a.txt"))
        self.assertFalse(da.path_allowed(s, "C:\\Users\\me\\other\\a.txt"))

    def test_empty_allowlist_denies_all(self) -> None:
        """Chưa khai thư mục nào ⇒ KHÔNG mở gì — không bao giờ mở toàn máy."""
        s = _FakeSession([])
        for p in ("/", "/home/me/project", "/etc/passwd"):
            self.assertFalse(da.path_allowed(s, p), p)

    def test_empty_path_denied(self) -> None:
        self.assertFalse(da.path_allowed(self.s, ""))

    def test_trailing_slash_tolerated(self) -> None:
        self.assertTrue(da.path_allowed(self.s, "/home/me/project/"))


class ListDevicesTests(unittest.TestCase):
    def test_offline_device_still_listed(self) -> None:
        """Thiết bị chưa kết nối vẫn phải hiện — để biết mà chờ, không tưởng mất."""
        with _reg():
            rows = da.list_devices()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "laptop")
        self.assertFalse(rows[0]["connected"])
        self.assertEqual(rows[0]["paths"], ["/home/me/project"])

    def test_can_write_default_is_false(self) -> None:
        """Ghi/xoá không hoàn tác được ⇒ mặc định phải TẮT."""
        with mock.patch.dict(config.data, {"device_agents": {
                "vps": {"token": _TOKEN, "paths": ["/srv"]}}}):
            rows = da.list_devices()
        self.assertFalse(rows[0]["can_write"])


if __name__ == "__main__":
    unittest.main()
