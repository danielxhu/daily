"""User-entered model API credentials (owner 2026-07-23): two slots on the
settings page; the "text" slot overrides the .env DeepSeek default; the key is
never echoed back (last 4 characters only)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi.testclient import TestClient

from app.clients.deepseek import DeepSeekClient
from app.db.credential_store import ApiCredential, get_credential
from app.db.engine import init_db
from app.main import create_app, get_db


def _client(db_path: str) -> TestClient:
    app = create_app()

    def _get_db() -> Iterator[sqlite3.Connection]:
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    overrides: Callable[[], Iterator[sqlite3.Connection]] = _get_db
    app.dependency_overrides[get_db] = overrides
    return TestClient(app)


def test_slots_default_to_env_text_and_empty_vision(tmp_path: Path) -> None:
    client = _client(str(tmp_path / "daily.db"))
    slots = {s["slot"]: s for s in client.get("/settings/api").json()["slots"]}
    assert slots["text"]["source"] == "env"
    assert slots["text"]["model"]  # the .env DeepSeek default is shown
    assert slots["text"]["key_last4"] is None  # env key is never surfaced
    assert slots["vision"] == {
        "slot": "vision",
        "source": "empty",
        "base_url": None,
        "model": None,
        "key_last4": None,
    }


def test_save_masks_key_and_clear_restores_the_default(tmp_path: Path) -> None:
    client = _client(str(tmp_path / "daily.db"))
    body = {
        "base_url": "https://api.example.cn/v1",
        "model": "some-model",
        "api_key": "sk-secret9876",
    }
    saved = client.put("/settings/api/text", json=body).json()
    assert saved["source"] == "custom" and saved["model"] == "some-model"
    assert saved["key_last4"] == "9876"
    assert "sk-secret9876" not in client.get("/settings/api").text  # never echoed

    cleared = client.delete("/settings/api/text").json()
    assert cleared["source"] == "env"


def test_bad_slot_and_blank_values_are_rejected(tmp_path: Path) -> None:
    client = _client(str(tmp_path / "daily.db"))
    bad = client.put("/settings/api/nope", json={"base_url": "x", "model": "y", "api_key": "z"})
    assert bad.status_code == 404
    resp = client.put("/settings/api/text", json={"base_url": " ", "model": "y", "api_key": "z"})
    assert resp.status_code == 422


def test_saved_text_credential_reaches_the_llm_factory(tmp_path: Path) -> None:
    db_path = str(tmp_path / "daily.db")
    client = _client(db_path)
    client.put(
        "/settings/api/text",
        json={"base_url": "https://api.example.cn/v1", "model": "their-model", "api_key": "sk-k"},
    )
    conn = init_db(db_path)
    cred = get_credential(conn, "text")
    conn.close()
    assert cred == ApiCredential(
        slot="text", base_url="https://api.example.cn/v1", model="their-model", api_key="sk-k"
    )


def test_credentialed_client_uses_the_custom_model_for_both_tiers() -> None:
    calls: list[str] = []

    class _FakeOpenAI:
        class chat:  # noqa: N801 — mimic the SDK shape
            class completions:  # noqa: N801
                @staticmethod
                def create(**kwargs: object) -> object:
                    calls.append(str(kwargs["model"]))

                    class _Msg:
                        content = "{}"

                    class _Choice:
                        message = _Msg()

                    class _Resp:
                        choices = [_Choice()]

                    return _Resp()

    cred = ApiCredential(slot="text", base_url="https://x/v1", model="their-model", api_key="k")
    llm = DeepSeekClient(openai_client=_FakeOpenAI(), credential=cred)
    llm.complete_json(system="s", user="u", escalate=False)
    llm.complete_json(system="s", user="u", escalate=True)
    # a custom endpoint has no pro tier of ours — escalation reuses its model
    assert calls == ["their-model", "their-model"]
