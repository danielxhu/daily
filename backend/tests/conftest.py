"""Shared test fixtures.

The `_ban_network` autouse fixture enforces the offline guarantee (NFR-3) for
every test. `settings` / `clear_settings_cache` give tests an isolated,
key-bearing `Settings` without reading the developer's real environment.
"""

from __future__ import annotations

import pytest

from app.core import config
from tests import netban


@pytest.fixture(autouse=True)
def _ban_network(monkeypatch: pytest.MonkeyPatch) -> None:
    netban.install(monkeypatch)


@pytest.fixture
def clear_settings_cache() -> None:
    config.get_settings.cache_clear()


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> config.Settings:
    """A `Settings` instance with a dummy DeepSeek key, isolated from `.env`."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    return config.Settings(_env_file=None)  # type: ignore[call-arg]
