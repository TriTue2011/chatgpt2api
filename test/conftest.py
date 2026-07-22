"""Pytest root conftest — markers + fixtures Đợt 0 (seams / anti-overlap).

Markers
-------
pure         — no network, no I/O outside process (ms)
adapter      — uses test._fakes seams only (no real HA/bot/provider)
integration  — real cheap libs (fitz/tmp disk), no paid API
e2e          — real devices/accounts; not in default CI

CI (recommended)::

    pytest -m "pure or adapter" -q
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Project root on path (same as most test files do ad-hoc)
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Deterministic auth for modules that import config at load time
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "pure: pure unit — no external seams")
    config.addinivalue_line(
        "markers", "adapter: uses shared fakes from test._fakes only"
    )
    config.addinivalue_line(
        "markers", "integration: real cheap libs (fitz/tmp), no paid API"
    )
    config.addinivalue_line(
        "markers", "e2e: real HA/bot/provider/device — manual or nightly only"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Default: do not skip unmarked tests (legacy suite stays green).

    New tests SHOULD set @pytest.mark.pure|adapter|integration|e2e.
    """
    # Optional: skip e2e unless -m e2e or --run-e2e
    run_e2e = config.getoption("--run-e2e", default=False)
    if run_e2e:
        return
    skip_e2e = pytest.mark.skip(reason="e2e: pass --run-e2e to enable")
    for item in items:
        if "e2e" in item.keywords and "pure" not in item.keywords:
            # only skip if exclusively e2e-ish — still allow adapter+e2e dual mark
            if not any(m in item.keywords for m in ("pure", "adapter", "integration")):
                item.add_marker(skip_e2e)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="Run tests marked e2e (real network/devices)",
    )


# ── Shared fixtures (seams) ─────────────────────────────────────────────────


@pytest.fixture
def seam_log():
    """Clear and return global SEAM_LOG for the test."""
    from test._fakes import SEAM_LOG, reset_seam_log

    reset_seam_log()
    yield SEAM_LOG
    reset_seam_log()


@pytest.fixture
def fake_call_model():
    """S4: install FakeCallModel for the duration of the test."""
    from test._fakes import FakeCallModel, install_call_model

    fake = FakeCallModel(text="fake-assistant-ok")
    with install_call_model(fake):
        yield fake


@pytest.fixture
def fake_bot_api():
    """S6: install FakeBotAPI."""
    from test._fakes import FakeBotAPI, install_bot_api

    fake = FakeBotAPI()
    with install_bot_api(fake):
        yield fake


@pytest.fixture
def fake_ha():
    """S2: install FakeHA with a sample light entity."""
    from test._fakes import FakeHA, install_ha

    fake = FakeHA(
        states={
            "light.demo": {"state": "off", "attributes": {"friendly_name": "Demo"}},
        }
    )
    with install_ha(fake):
        yield fake


@pytest.fixture
def fake_provider_http():
    """S1: install FakeProviderHttp."""
    from test._fakes import FakeProviderHttp, install_provider_http

    fake = FakeProviderHttp()
    with install_provider_http(fake):
        yield fake


@pytest.fixture
def tmp_data_dir():
    """S5: temporary directory for DATA_DIR-style writes."""
    from test._fakes import tmp_data_dir as _td

    with _td() as path:
        yield path


@pytest.fixture
def fake_mcp():
    """S7: install FakeMCP."""
    from test._fakes import FakeMCP, install_mcp

    fake = FakeMCP()
    with install_mcp(fake):
        yield fake
