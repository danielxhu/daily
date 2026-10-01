"""Summary cost knobs (ENRICH_BRIEF / ENRICH_MAX_INPUT_CHARS): the GitHub Pages
run trades the long bilingual briefing for one paragraph from a capped excerpt."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.clients.mock import MockLLMClient
from app.core import config
from app.tracking.summarize import _BRIEF_PLAN, enrich_fetched_item

_REPLY = {"summary_zh": "摘要。", "summary_en": "Summary.", "tags": ["x"]}
_TEXT = "word " * 4000  # 20k chars: the typical-article tier (15k excerpt, 4-5 paragraphs)


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def _call(llm: MockLLMClient) -> dict[str, str]:
    assert enrich_fetched_item(_TEXT, title="t", domain="d.example", llm=llm) is not None
    return llm.calls[0]


def test_defaults_keep_the_full_briefing() -> None:
    call = _call(MockLLMClient([_REPLY]))
    assert _BRIEF_PLAN not in call["system"]
    assert len(call["user"]) > 10_000


def test_brief_mode_and_input_cap_shrink_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENRICH_BRIEF", "true")
    monkeypatch.setenv("ENRICH_MAX_INPUT_CHARS", "4000")
    call = _call(MockLLMClient([_REPLY]))
    assert _BRIEF_PLAN in call["system"]
    assert "4-5 paragraphs" not in call["system"]
    assert len(call["user"]) < 4_200  # header + the 4000-char excerpt
