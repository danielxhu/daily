"""DeepSeek text-LLM client (M1A.10, SSOT §10 / NFR-7).

OpenAI-compatible wrapper (DeepSeek speaks the OpenAI API) implementing the X0.3
`LLMClient` interface. Per §10:

- default model is `deepseek-v4-flash` (cheap); `escalate=True` selects
  `deepseek-v4-pro` (strong) — used only on complexity / low confidence / parse
  failure (NFR-7);
- JSON output mode ON, `temperature=0`, **thinking disabled** via
  `extra_body={"thinking": {"type": "disabled"}}` (V4 has thinking on by default;
  leaving it on ignores temperature and raises cost);
- 2 retries with exponential backoff on transient API errors;
- JSON-mode is not server-schema-enforced → always parse + validate; a parse
  failure raises `LLMJSONError` so the caller can escalate to pro or typed-skip.

The underlying network call goes through the injectable OpenAI client, so the
offline suite passes a fake (NFR-3) and never hits the API.
"""

from __future__ import annotations

import json
import time
from typing import Any

from openai import APIError

from app.clients.base import LLMClient
from app.core.config import Settings, get_settings
from app.db.credential_store import ApiCredential

_MAX_ATTEMPTS = 3  # 1 initial + 2 retries (§10)
_BACKOFF_BASE_S = 0.5
_THINKING_DISABLED = {"thinking": {"type": "disabled"}}


class LLMError(RuntimeError):
    """Base error for the LLM client."""


class LLMJSONError(LLMError):
    """The model did not return a parseable JSON object."""


class DeepSeekClient:
    """DeepSeek implementation of `LLMClient`. A user-saved "text" credential
    (settings page, 2026-07-23) points the same OpenAI-compatible wrapper at a
    different endpoint/model; escalation then reuses that single model (a custom
    endpoint has no pro tier of ours to climb to)."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        openai_client: Any | None = None,
        credential: ApiCredential | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = openai_client  # injectable; lazily built if None
        self._credential = credential

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            if self._credential is not None:
                api_key, base_url = self._credential.api_key, self._credential.base_url
            else:
                api_key = self._settings.require_deepseek_key()
                base_url = self._settings.deepseek_base_url
            # M14.7: bound every call. The SDK defaults are timeout=600s with 2
            # internal retries — one hung DeepSeek round-trip could pin a worker
            # thread for many minutes (owner-visible as "为什么这么慢"). Retries
            # are OUR loop's job (_create_with_retries, §10), so the SDK's are off.
            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=60.0,
                max_retries=0,
            )
        return self._client

    def _create_with_retries(self, *, model: str, system: str, user: str) -> Any:
        client = self._get_client()
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0,
                    response_format={"type": "json_object"},  # JSON mode
                    extra_body=_THINKING_DISABLED,
                )
            except APIError as exc:  # transient API/network error → backoff + retry
                last_exc = exc
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_BACKOFF_BASE_S * (2**attempt))
        raise LLMError(f"DeepSeek call failed after {_MAX_ATTEMPTS} attempts: {last_exc}")

    def complete_json(self, *, system: str, user: str, escalate: bool = False) -> dict[str, Any]:
        if self._credential is not None:
            model = self._credential.model
        else:
            model = (
                self._settings.deepseek_pro_model
                if escalate
                else self._settings.deepseek_flash_model
            )
        resp = self._create_with_retries(model=model, system=system, user=user)
        content = resp.choices[0].message.content
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError) as exc:
            raise LLMJSONError(f"DeepSeek returned non-JSON content: {content!r}") from exc
        if not isinstance(data, dict):
            raise LLMJSONError(f"DeepSeek returned a non-object JSON value: {type(data).__name__}")
        return data


def call_with_escalation(client: LLMClient, *, system: str, user: str) -> dict[str, Any]:
    """flash first; on a JSON parse failure escalate to pro once (§10 / NFR-7). If
    pro also fails, the `LLMJSONError` propagates so the caller can typed-skip."""
    try:
        return client.complete_json(system=system, user=user, escalate=False)
    except LLMJSONError:
        return client.complete_json(system=system, user=user, escalate=True)


def _load_text_credential() -> ApiCredential | None:
    """The user-saved "text" credential, or None (env default). Best-effort —
    a missing/old database must never break LLM construction."""
    from app.db.credential_store import get_credential
    from app.db.engine import init_db

    try:
        conn = init_db(get_settings().sqlite_path)
        try:
            return get_credential(conn, "text")
        finally:
            conn.close()
    except Exception:
        return None


def get_llm_client() -> DeepSeekClient:
    """Factory for the real client (monkeypatched to a mock in tests). A
    user-saved text-model credential (settings page) overrides the .env
    DeepSeek default; no saved row = unchanged env behavior."""
    return DeepSeekClient(credential=_load_text_credential())
