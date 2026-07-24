"""X0.2 — pinned config contract tests."""

from __future__ import annotations

import pytest

from app.core import config
from app.core.config import ConfigError, Settings


def test_reproducibility_pins_present() -> None:
    assert config.SEED == 42
    assert config.PROMPT_VERSION


def test_settings_parse_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "abc123")
    monkeypatch.setenv("ENABLE_HTML_RENDER", "true")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.deepseek_api_key == "abc123"
    assert s.enable_html_render is True
    # pinned defaults still hold
    assert s.deepseek_flash_model == "deepseek-v4-flash"
    assert s.deepseek_pro_model == "deepseek-v4-pro"


def test_missing_deepseek_key_gives_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.deepseek_api_key is None
    with pytest.raises(ConfigError) as exc:
        s.require_deepseek_key()
    assert "DEEPSEEK_API_KEY" in str(exc.value)


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    config.get_settings.cache_clear()
    a = config.get_settings()
    b = config.get_settings()
    assert a is b
    config.get_settings.cache_clear()
