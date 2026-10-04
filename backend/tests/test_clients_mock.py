"""X0.3 — mock clients satisfy the interfaces and show the monkeypatch pattern."""

from __future__ import annotations

import pytest

from app.clients.base import (
    LLMClient,
    RenderClient,
    Transcriber,
    TranscriptResult,
)
from app.clients.mock import (
    MockLLMClient,
    MockRenderClient,
    MockTranscriber,
)


def test_mock_llm_replays_in_order_and_records_escalation() -> None:
    client = MockLLMClient([{"a": 1}, {"b": 2}])
    assert isinstance(client, LLMClient)  # runtime_checkable Protocol
    assert client.complete_json(system="s", user="u1") == {"a": 1}
    assert client.complete_json(system="s", user="u2", escalate=True) == {"b": 2}
    assert client.calls[0]["escalate"] is False
    assert client.calls[1]["escalate"] is True


def test_mock_llm_raises_when_exhausted() -> None:
    client = MockLLMClient([{"only": 1}])
    client.complete_json(system="s", user="u")
    with pytest.raises(AssertionError):
        client.complete_json(system="s", user="u")


def test_mock_transcriber() -> None:
    t = MockTranscriber()
    assert isinstance(t, Transcriber)
    result = t.transcribe("/tmp/audio.wav")
    assert isinstance(result, TranscriptResult)
    assert result.text == "mock transcript."
    assert t.calls == ["/tmp/audio.wav"]


def test_mock_render_returns_html_without_a_browser() -> None:
    r = MockRenderClient(html="<html><body>rendered</body></html>")
    assert isinstance(r, RenderClient)
    result = r.render("https://example.test/js-heavy")
    assert "rendered" in result.html
    assert result.final_url == "https://example.test/js-heavy"
    assert r.calls == ["https://example.test/js-heavy"]


def get_llm_client() -> LLMClient:  # stand-in for the real factory (M1A.10)
    raise AssertionError("real client must never be constructed in tests")


def test_monkeypatch_factory_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    """How real code will be tested: the client factory is monkeypatched on its
    module to return a mock, so the unit under test never reaches the network."""
    import tests.test_clients_mock as mod

    monkeypatch.setattr(mod, "get_llm_client", lambda: MockLLMClient([{"claims": []}]))
    client = mod.get_llm_client()
    assert client.complete_json(system="s", user="u") == {"claims": []}
