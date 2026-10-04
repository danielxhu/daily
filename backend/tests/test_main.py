"""M2.1 — FastAPI app shell: health, non-secret config, CORS, config injection."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def _client(settings: Settings | None = None) -> TestClient:
    return TestClient(create_app(settings or _settings()))


def test_health_ok() -> None:
    resp = _client().get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_config_exposes_operational_fields() -> None:
    body = _client().get("/config").json()
    assert body["prompt_version"]
    assert body["models"]["text_flash"] == "deepseek-v4-flash"
    assert body["features"]["pdf_text"] is True


def test_config_never_leaks_api_keys() -> None:
    resp = _client(_settings(deepseek_api_key="SECRET-DS")).get("/config")
    assert "SECRET-DS" not in resp.text
    assert "api_key" not in resp.text.lower()


def test_config_reflects_injected_settings() -> None:
    body = _client(_settings(deepseek_flash_model="custom-flash")).get("/config").json()
    assert body["models"]["text_flash"] == "custom-flash"  # config injection works


def test_cors_allows_configured_origin() -> None:
    client = _client(_settings(cors_origins=["http://localhost:3000"]))
    resp = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_omits_header_for_unlisted_origin() -> None:
    client = _client(_settings(cors_origins=["http://localhost:3000"]))
    resp = client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in resp.headers
