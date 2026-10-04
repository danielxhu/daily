"""M1A.1 — per-source outcome envelope: a mixed batch serializes to JSON showing
each source's ok/failed status and, on failure, its typed kind + next_action."""

from __future__ import annotations

import json

from app.ingestion.fetch_policy import next_action_for, typed_skip
from app.ingestion.result import failed_from, failed_result, ok_result
from app.schemas.models import IngestionResult, NormalizedSource, SourceRequest


def _normalized_source(source_id: str = "s1") -> NormalizedSource:
    return NormalizedSource(
        source_id=source_id,
        type="text",
        url=None,
        domain=None,
        raw_text="hello",
        segments=[],
        frame_annotations=[],
    )


def test_ok_result_shape() -> None:
    req = SourceRequest(kind="text", text="hi")
    r = ok_result(req, _normalized_source())
    assert r.status == "ok" and r.source is not None and r.failure is None


def test_failed_from_carries_next_action() -> None:
    req = SourceRequest(kind="url", url="https://paywall.example/x")
    r = failed_from(req, "paywall", reason="Paywalled; not fetched.")
    assert r.status == "failed"
    assert r.source is None
    assert r.failure is not None
    assert r.failure.kind == "paywall"
    assert r.failure.next_action == next_action_for("paywall")
    # requested_url defaulted from the request
    assert r.failure.requested_url == "https://paywall.example/x"


def test_parse_empty_has_next_action() -> None:
    req = SourceRequest(kind="url", url="https://thin.example/x")
    r = failed_from(req, "parse_empty", reason="Extracted body too short.")
    assert r.failure is not None and r.failure.next_action  # §6.6 incl. parse_empty


def test_mixed_batch_serializes_per_source_status_and_next_action() -> None:
    batch = [
        ok_result(SourceRequest(kind="text", text="pasted"), _normalized_source("s1")),
        failed_from(
            SourceRequest(kind="url", url="https://paywall.example/x"),
            "paywall",
            reason="Paywalled.",
        ),
    ]
    payload = [r.model_dump(mode="json") for r in batch]

    assert [item["status"] for item in payload] == ["ok", "failed"]
    # ok source has a source, no failure
    assert payload[0]["source"]["source_id"] == "s1"
    assert payload[0]["failure"] is None
    # failed source surfaces kind + next_action in the JSON
    assert payload[1]["failure"]["kind"] == "paywall"
    assert "paste" in payload[1]["failure"]["next_action"].lower()

    # round-trips back through the contract
    assert all(IngestionResult.model_validate(item) for item in payload)
    # and is real JSON
    json.dumps(payload)


def test_failed_result_passthrough() -> None:
    req = SourceRequest(kind="url", url="https://x.test")
    failure = typed_skip("timeout", reason="timed out", requested_url="https://x.test")
    r = failed_result(req, failure)
    assert r.failure is failure and r.status == "failed"
