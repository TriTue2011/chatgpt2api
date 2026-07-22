"""Đợt 0 — smoke: sổ SEAM import được và fake hoạt động cơ bản."""

from __future__ import annotations

import os
import unittest

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from test._fakes import (  # noqa: E402
    SEAM_IDS,
    SEAM_INSTALLERS,
    FakeBotAPI,
    FakeCallModel,
    FakeHA,
    FakeHttpResponse,
    FakeMCP,
    FakeProviderHttp,
    FakeSocket,
    install_bot_api,
    install_call_model,
    install_ha,
    install_mcp,
    install_provider_http,
    install_socket,
    reset_seam_log,
    tmp_data_dir,
)


@pytest.mark.pure
class TestSeamRegistry(unittest.TestCase):
    def test_eight_seams_registered(self) -> None:
        self.assertEqual(set(SEAM_IDS), set(SEAM_INSTALLERS.keys()))
        self.assertEqual(len(SEAM_IDS), 8)


@pytest.mark.adapter
class TestFakeCallModel(unittest.TestCase):
    def test_install_returns_fixed_text(self) -> None:
        reset_seam_log()
        fake = FakeCallModel(text="xin chào")
        with install_call_model(fake):
            from services.agent import runtime

            out = runtime.call_model("cx/auto", [{"role": "user", "content": "hi"}])
        content = out["choices"][0]["message"]["content"]
        self.assertEqual(content, "xin chào")
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0]["model"], "cx/auto")


@pytest.mark.adapter
class TestFakeBotAndHA(unittest.TestCase):
    def test_bot_records_message(self) -> None:
        fake = FakeBotAPI()
        with install_bot_api(fake):
            fake.send_message(chat_id="1", text="ping")
            fake.send_photo(chat_id="1", photo="http://x/a.jpg", caption="c")
        self.assertEqual(len(fake.messages), 1)
        self.assertEqual(fake.messages[0]["text"], "ping")
        self.assertEqual(len(fake.photos), 1)

    def test_ha_service_call(self) -> None:
        fake = FakeHA(states={"light.x": {"state": "on", "attributes": {}}})
        self.assertEqual(fake.get_state("light.x")["state"], "on")
        fake.call_service("light", "turn_off", {"entity_id": "light.x"})
        self.assertEqual(fake.service_calls[0]["service"], "turn_off")


@pytest.mark.adapter
class TestProviderHttpAndMcp(unittest.TestCase):
    def test_provider_queue(self) -> None:
        fake = FakeProviderHttp(
            queue=[
                FakeHttpResponse(status_code=429, text='{"error":"limit"}', _json={"error": "limit"}),
                FakeHttpResponse(status_code=200, _json={"id": "1"}),
            ]
        )
        r1 = fake.get("https://example.com/a")
        self.assertEqual(r1.status_code, 429)
        with self.assertRaises(RuntimeError):
            r1.raise_for_status()
        r2 = fake.post("https://api.example/v1/chat", json={})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["id"], "1")

    def test_mcp_tools(self) -> None:
        mcp = FakeMCP(results={"demo_tool": {"ok": 1}})
        self.assertEqual(len(mcp.list_tools()), 1)
        self.assertEqual(mcp.call_tool("demo_tool", {}), {"ok": 1})


@pytest.mark.adapter
class TestStorageAndSocket(unittest.TestCase):
    def test_tmp_data_dir(self) -> None:
        with tmp_data_dir() as d:
            p = d / "hello.txt"
            p.write_text("x", encoding="utf-8")
            self.assertTrue(p.is_file())
            self.assertTrue(d.is_dir())
        self.assertFalse(p.exists())

    def test_fake_socket(self) -> None:
        with install_socket() as socks:
            import socket

            s = socket.socket()
            s.connect(("127.0.0.1", 8082))
            s.send(b"ping")
            s.close()
        self.assertEqual(len(socks), 1)
        self.assertEqual(socks[0].sent[0], b"ping")
        self.assertTrue(socks[0].closed)


if __name__ == "__main__":
    unittest.main()
