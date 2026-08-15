"""Regression tests for the standalone MCP hub security boundaries."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HUB_ROOT = ROOT / "vn-mcp-hub"
sys.path.insert(0, str(HUB_ROOT))


class _FakeMCP:
    """Enough of FastMCP to test registry helpers without the optional package."""

    def __init__(self, *_args, **_kwargs):
        pass

    def tool(self):
        return lambda fn: fn


sys.modules.setdefault("fastmcp", types.SimpleNamespace(FastMCP=_FakeMCP))
ssh_exec = importlib.import_module("src.general.ssh_exec")
fs_remote = importlib.import_module("src.general.fs_remote")
telegram_bot = importlib.import_module("src.rag.telegram_bot")


class _Request:
    def __init__(self, secret: str, body: bytes = b"{}"):
        self.headers = {"X-Telegram-Bot-Api-Secret-Token": secret}
        self._body = body
        self.was_read = False

    async def body(self) -> bytes:
        self.was_read = True
        return self._body


class HubTelegramSecurityTests(unittest.TestCase):
    def _settings(self):
        return {
            "bot_token": "123:telegram-token",
            "chat_ids": ["42"],
            "ai_model": "model",
            "api_key": "",
            "base_url": "http://127.0.0.1:80/v1",
            "system_prompt": "test",
            "webhook_url": "https://example.test",
        }

    def test_registers_a_telegram_webhook_secret(self):
        calls: list[tuple[str, dict]] = []
        with mock.patch.object(telegram_bot, "_get_settings", self._settings), \
                mock.patch.object(telegram_bot, "_api_call", side_effect=lambda method, data: calls.append((method, data)) or {"ok": True}):
            self.assertTrue(telegram_bot.register_webhook())
        self.assertEqual(calls[0][0], "setWebhook")
        self.assertEqual(calls[0][1]["secret_token"], telegram_bot._webhook_secret("123:telegram-token"))

    def test_rejects_bad_secret_before_reading_request_body(self):
        request = _Request("wrong", b"{" + b"x" * 100)
        with mock.patch.object(telegram_bot, "_get_settings", self._settings):
            with self.assertRaises(Exception) as ctx:
                asyncio.run(telegram_bot.handle_webhook(request))
        self.assertEqual(getattr(ctx.exception, "status_code", None), 403)
        self.assertFalse(request.was_read)

    def test_empty_allowlist_fails_closed(self):
        settings = self._settings()
        settings["chat_ids"] = []
        secret = telegram_bot._webhook_secret(settings["bot_token"])
        update = {"message": {"chat": {"id": 42}, "text": "/start"}}
        with mock.patch.object(telegram_bot, "_get_settings", return_value=settings), \
                mock.patch.object(telegram_bot, "send_message") as send:
            result = asyncio.run(telegram_bot.handle_webhook(_Request(secret, json.dumps(update).encode())))
        self.assertEqual(result, {"ok": False})
        send.assert_not_called()


class SshRegistrySecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.registry = Path(self.tmp.name) / "ssh_servers.json"
        self.patch = mock.patch.object(ssh_exec, "REGISTRY", self.registry)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_registry_write_is_private_and_atomic_format_is_valid(self):
        result = ssh_exec.add_server("node", "host.example", "root", "secret", 22)
        self.assertTrue(result["ok"])
        self.assertEqual(stat.S_IMODE(self.registry.stat().st_mode), 0o600)
        self.assertEqual(json.loads(self.registry.read_text())[0]["password"], "secret")

    def test_rejects_invalid_port_and_nonabsolute_file_scope(self):
        self.assertFalse(ssh_exec.add_server("node", "host", "root", port="bad")["ok"])
        self.assertFalse(ssh_exec.add_server("node", "host", "root", read_paths="relative/path")["ok"])

    def test_llm_registry_mutation_requires_explicit_deployment_opt_in(self):
        with mock.patch.dict(os.environ, {"VN_MCP_HUB_ALLOW_AGENT_ADMIN": ""}, clear=False):
            result = ssh_exec.ssh_add_server("node", "host", "root", "secret")
        self.assertIn("Từ chối", result)


class _Attr:
    def __init__(self, mode: int):
        self.st_mode = mode


class _SftpRealpath:
    def __init__(self, mapping: dict[str, str], existing: set[str] | None = None):
        self.mapping = mapping
        self.existing = existing or set()

    def normalize(self, path: str) -> str:
        return self.mapping.get(path, path)

    def lstat(self, path: str):
        if path not in self.existing:
            raise FileNotFoundError(path)
        return _Attr(stat.S_IFREG)


class SftpScopeSecurityTests(unittest.TestCase):
    def test_read_rejects_symlink_that_escapes_allowed_root(self):
        sftp = _SftpRealpath({"/safe/link/passwd": "/etc/passwd", "/safe": "/safe"})
        path, error = fs_remote._resolve_remote_path(sftp, "/safe/link/passwd", ["/safe"])
        self.assertIsNone(path)
        self.assertIn("ngoài phạm vi", error)

    def test_new_write_resolves_symlinked_parent_before_authorizing(self):
        sftp = _SftpRealpath({"/safe/link": "/etc", "/safe": "/safe"})
        path, error = fs_remote._resolve_remote_path(sftp, "/safe/link/new.conf", ["/safe"], write=True)
        self.assertIsNone(path)
        self.assertIn("ngoài phạm vi", error)

    def test_regular_file_inside_real_allowed_root_is_kept(self):
        sftp = _SftpRealpath({"/safe/ok.txt": "/safe/ok.txt", "/safe": "/safe"}, {"/safe/ok.txt"})
        path, error = fs_remote._resolve_remote_path(sftp, "/safe/ok.txt", ["/safe"], write=True)
        self.assertEqual(path, "/safe/ok.txt")
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
