"""X0.2 — pinned config contract tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core import config
from app.core.config import (
    CASR_MAX_LOOKUPS_PER_CLAIM,
    CASR_WHITELIST,
    SCORING,
    ConfigError,
    Settings,
)


def test_scoring_weights_are_calibrated_m4_6() -> None:
    # §3.1.1 init was 0.30/0.40/0.15/0.15; M4.6 calibrated these on the train split
    # (eval/weight_calibration.json). Drift vs that record is guarded below.
    w = SCORING.weights
    assert (w.w1_sources, w.w2_agreement, w.w3_reputation, w.w4_conflict) == (
        0.35,
        0.45,
        0.20,
        0.10,
    )


def test_scoring_formula_constants() -> None:
    assert SCORING.sources_score_per_k == 25.0
    assert SCORING.independence_base == 0.5
    assert SCORING.independence_per_k == 0.125
    assert SCORING.independence_per_r == 0.05
    assert (SCORING.independence_min, SCORING.independence_max) == (0.5, 1.0)
    assert (SCORING.score_min, SCORING.score_max) == (0.0, 100.0)


def test_weights_calibrated_at_is_stamped() -> None:
    # M4.6 stamps this (ISO date) after the no-leakage train-split grid-search.
    assert SCORING.calibrated_at == "2026-06-24"


def test_scoring_constants_are_frozen() -> None:
    with pytest.raises(ValidationError):
        SCORING.sources_score_per_k = 99.0


def test_alignment_threshold_is_calibrated() -> None:
    # M3.3 calibrated it on eval/alignment_pairs.json (train sweep, heldout report).
    assert config.ALIGNMENT_THRESHOLD_CALIBRATED is True
    assert 0.5 <= config.ALIGNMENT_COSINE_THRESHOLD <= 0.95


def test_casr_lookup_cap_is_three() -> None:
    assert CASR_MAX_LOOKUPS_PER_CLAIM == 3


def test_casr_whitelist_has_core_authoritative_domains() -> None:
    assert "sec.gov" in CASR_WHITELIST
    assert "federalreserve.gov" in CASR_WHITELIST
    assert isinstance(CASR_WHITELIST, frozenset)


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
