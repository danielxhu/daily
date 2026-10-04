"""M1A.10 — DeepSeek client wrapper: flash default + pro escalation, JSON mode +
thinking disabled, retries, JSON-parse failure handling. Offline via a fake client."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APIConnectionError, BadRequestError

from app.clients.base import LLMClient
from app.clients.deepseek import (
    DeepSeekClient,
    LLMError,
    LLMJSONError,
    call_with_escalation,
)
from app.core.config import Settings
from app.db.credential_store import ApiCredential


def _resp(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class _FakeCreate:
    """Fake `chat.completions.create`: content chosen per model; records calls."""

    def __init__(self, by_model: dict[str, str]) -> None:
        self.by_model = by_model
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return _resp(self.by_model[kwargs["model"]])


def _fake_openai(create: Any) -> SimpleNamespace:
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _settings() -> Settings:
    return Settings(_env_file=None, deepseek_api_key="test-key")  # type: ignore[call-arg]


def test_satisfies_llm_client_protocol() -> None:
    client = DeepSeekClient(settings=_settings(), openai_client=_fake_openai(_FakeCreate({})))
    assert isinstance(client, LLMClient)


def test_flash_default_with_json_mode_and_thinking_disabled() -> None:
    create = _FakeCreate({"deepseek-v4-flash": json.dumps({"ok": True})})
    client = DeepSeekClient(settings=_settings(), openai_client=_fake_openai(create))
    out = client.complete_json(system="s", user="u")
    assert out == {"ok": True}
    call = create.calls[0]
    assert call["model"] == "deepseek-v4-flash"  # cheap default
    assert call["response_format"] == {"type": "json_object"}  # JSON mode
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}  # thinking off
    assert call["temperature"] == 0


def test_escalate_selects_pro() -> None:
    create = _FakeCreate({"deepseek-v4-pro": json.dumps({"strong": 1})})
    client = DeepSeekClient(settings=_settings(), openai_client=_fake_openai(create))
    out = client.complete_json(system="s", user="u", escalate=True)
    assert out == {"strong": 1}
    assert create.calls[0]["model"] == "deepseek-v4-pro"


def test_non_json_content_raises_llm_json_error() -> None:
    create = _FakeCreate({"deepseek-v4-flash": "not json at all"})
    client = DeepSeekClient(settings=_settings(), openai_client=_fake_openai(create))
    with pytest.raises(LLMJSONError):
        client.complete_json(system="s", user="u")


def test_json_array_is_rejected_as_non_object() -> None:
    create = _FakeCreate({"deepseek-v4-flash": "[1, 2, 3]"})
    client = DeepSeekClient(settings=_settings(), openai_client=_fake_openai(create))
    with pytest.raises(LLMJSONError):
        client.complete_json(system="s", user="u")


def test_flash_to_pro_escalation_on_parse_failure() -> None:
    create = _FakeCreate(
        {"deepseek-v4-flash": "broken json", "deepseek-v4-pro": json.dumps({"recovered": True})}
    )
    client = DeepSeekClient(settings=_settings(), openai_client=_fake_openai(create))
    out = call_with_escalation(client, system="s", user="u")
    assert out == {"recovered": True}
    assert [c["model"] for c in create.calls] == ["deepseek-v4-flash", "deepseek-v4-pro"]


def test_escalation_reraises_when_pro_also_fails() -> None:
    create = _FakeCreate({"deepseek-v4-flash": "broken", "deepseek-v4-pro": "also broken"})
    client = DeepSeekClient(settings=_settings(), openai_client=_fake_openai(create))
    with pytest.raises(LLMJSONError):
        call_with_escalation(client, system="s", user="u")


def test_retries_on_transient_api_error_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.clients.deepseek.time.sleep", lambda _s: None)  # no real backoff
    calls = {"n": 0}

    def flaky(**kwargs: Any) -> SimpleNamespace:
        calls["n"] += 1
        if calls["n"] < 3:
            raise APIConnectionError(request=httpx.Request("POST", "https://api.deepseek.com"))
        return _resp(json.dumps({"ok": 1}))

    client = DeepSeekClient(settings=_settings(), openai_client=_fake_openai(flaky))
    assert client.complete_json(system="s", user="u") == {"ok": 1}
    assert calls["n"] == 3  # 2 retries then success


def test_gives_up_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.clients.deepseek.time.sleep", lambda _s: None)

    def always_fail(**kwargs: Any) -> SimpleNamespace:
        raise APIConnectionError(request=httpx.Request("POST", "https://api.deepseek.com"))

    client = DeepSeekClient(settings=_settings(), openai_client=_fake_openai(always_fail))
    with pytest.raises(LLMError):
        client.complete_json(system="s", user="u")


def test_lazy_client_bounds_timeout_and_disables_sdk_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M14.7: the SDK defaults (600s timeout, 2 internal retries) can pin a worker
    thread for many minutes on one hung call. Retries are `_create_with_retries`'s
    job (§10), so the lazily-built client must set a bounded timeout and no SDK
    retries."""
    captured: dict[str, Any] = {}

    class _FakeOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    import openai

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    DeepSeekClient(settings=_settings())._get_client()
    assert captured["timeout"] == 60.0
    assert captured["max_retries"] == 0


# --- the text slot accepts any OpenAI-compatible provider -----------------------


def _third_party_credential() -> ApiCredential:
    return ApiCredential(
        slot="text",
        base_url="https://api.vendor.example/v1",
        model="vendor-model-1",
        api_key="user-key",
    )


def _bad_request() -> BadRequestError:
    return BadRequestError(
        "unknown parameter: response_format",
        response=httpx.Response(400, request=httpx.Request("POST", "https://api.vendor.example")),
        body=None,
    )


def test_custom_endpoint_never_receives_the_deepseek_thinking_knob() -> None:
    create = _FakeCreate({"vendor-model-1": json.dumps({"ok": True})})
    client = DeepSeekClient(
        settings=_settings(),
        openai_client=_fake_openai(create),
        credential=_third_party_credential(),
    )
    assert client.complete_json(system="s", user="u") == {"ok": True}
    call = create.calls[0]
    assert "extra_body" not in call  # DeepSeek-V4-specific; strict endpoints would 400
    assert call["response_format"] == {"type": "json_object"}  # still tried first


def test_custom_endpoint_rejecting_json_mode_degrades_and_remembers() -> None:
    calls: list[dict[str, Any]] = []

    def picky(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        if "response_format" in kwargs:
            raise _bad_request()
        return _resp(json.dumps({"ok": True}))

    client = DeepSeekClient(
        settings=_settings(),
        openai_client=_fake_openai(picky),
        credential=_third_party_credential(),
    )
    # first call: tries JSON mode, gets the 400, drops it, succeeds
    assert client.complete_json(system="s", user="u") == {"ok": True}
    assert [("response_format" in c) for c in calls] == [True, False]
    # second call: the rejection is remembered — no wasted 400 round-trip
    assert client.complete_json(system="s", user="u") == {"ok": True}
    assert "response_format" not in calls[-1]


def test_deepseek_endpoint_bad_request_raises_instead_of_degrading() -> None:
    # on OUR own request shape a 400 is a bug to surface, not a param to drop
    def reject(**kwargs: Any) -> SimpleNamespace:
        raise _bad_request()

    client = DeepSeekClient(settings=_settings(), openai_client=_fake_openai(reject))
    with pytest.raises(LLMError, match="rejected"):
        client.complete_json(system="s", user="u")
