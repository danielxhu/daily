"""X0.4 — shared schema contract: snapshot + frontend-sync + field assertions.

The snapshot/TS-sync tests are the drift guard (backend↔frontend contract test).
The targeted assertions pin the specific fields the tracker calls out, so a §7
change that drops one fails here, not silently downstream.
"""

from __future__ import annotations

import json
import typing
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas import codegen
from app.schemas.models import (
    ALL_MODELS,
    Board,
    IngestionResult,
    NormalizedSource,
    Source,
    SourceFailure,
    SourceFailureKind,
    SourceRequest,
    SubscriptionFailureKind,
)


def _normalized_source() -> NormalizedSource:
    return NormalizedSource(
        source_id="s1",
        type="text",
        url=None,
        domain=None,
        raw_text="hello",
        segments=[],
        frame_annotations=[],
    )


def _source_failure() -> SourceFailure:
    return SourceFailure(requested_url=None, type=None, kind="timeout", reason="timed out")


def _regen_hint(artifact: str) -> str:
    return (
        f"{artifact} is stale — run `python -m app.schemas.codegen` after intentional §7 changes."
    )


# --- drift guards -----------------------------------------------------------


def test_json_schema_snapshot_in_sync() -> None:
    committed = json.loads(codegen.SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert committed == codegen.build_schema_document(), _regen_hint("schema.json")


def test_typescript_in_sync() -> None:
    committed = codegen.TS_PATH.read_text(encoding="utf-8")
    assert committed == codegen.generate_typescript(), _regen_hint("contract.ts")


def test_every_model_has_a_ts_interface() -> None:
    ts = codegen.generate_typescript()
    for model in ALL_MODELS:
        assert f"export interface {model.__name__} {{" in ts


# --- called-out fields (tracker X0.4) ---------------------------------------


def test_origin_user_fetched() -> None:
    for model in (Source, NormalizedSource):
        assert typing.get_args(model.model_fields["origin"].annotation) == ("user", "fetched")


def test_failure_kind_enums() -> None:
    assert "paywall" in typing.get_args(SourceFailureKind)
    assert "parse_empty" in typing.get_args(SourceFailureKind)
    # distinct taxonomy from source-side failures
    assert "system_anomaly" in typing.get_args(SubscriptionFailureKind)
    assert set(typing.get_args(SourceFailureKind)).isdisjoint(
        typing.get_args(SubscriptionFailureKind)
    )


def test_source_failure_has_next_action() -> None:
    assert "next_action" in SourceFailure.model_fields


def test_source_request_label_vs_declared_domain() -> None:
    assert "source_label" in SourceRequest.model_fields
    assert "declared_domain" in SourceRequest.model_fields


def test_normalized_source_extraction_methods() -> None:
    # annotation is Optional[Literal[...]]: unwrap the union, then read the Literal.
    union_args = typing.get_args(NormalizedSource.model_fields["extraction_method"].annotation)
    (literal,) = [a for a in union_args if a is not type(None)]
    members = set(typing.get_args(literal))
    assert {
        "static_html",
        "rendered_html",
        "pdf_text",
        "caption",
        "whisper",
        "frame_ocr",
    } <= members


def test_board_is_minimal_topic_collection() -> None:
    # FR-15: single-operator topic collection, NOT a user account.
    assert set(Board.model_fields) == {"id", "name", "created_at"}


# --- contract invariants (§7) -----------------------------------------------


def test_source_request_kind_payload_consistency() -> None:
    # missing matching payload
    with pytest.raises(ValidationError):
        SourceRequest(kind="url")
    with pytest.raises(ValidationError):
        SourceRequest(kind="text")
    # opposite payload present (§7 "iff" — both directions)
    with pytest.raises(ValidationError):
        SourceRequest(kind="url", url="https://x.test", text="should-not-be-here")
    with pytest.raises(ValidationError):
        SourceRequest(kind="text", text="body", url="https://x.test")
    # valid forms
    assert SourceRequest(kind="url", url="https://x.test").url == "https://x.test"
    assert SourceRequest(kind="text", text="pasted").text == "pasted"


def test_ingestion_result_outcome_consistency() -> None:
    req = SourceRequest(kind="text", text="hello")
    ns = _normalized_source()
    sf = _source_failure()

    # valid forms
    assert IngestionResult(requested=req, status="ok", source=ns, failure=None).source is ns
    assert IngestionResult(requested=req, status="failed", source=None, failure=sf).failure is sf

    # §7 "iff": every invalid status/payload combination is rejected
    with pytest.raises(ValidationError):  # ok without source
        IngestionResult(requested=req, status="ok", source=None, failure=None)
    with pytest.raises(ValidationError):  # ok with failure
        IngestionResult(requested=req, status="ok", source=ns, failure=sf)
    with pytest.raises(ValidationError):  # failed without failure
        IngestionResult(requested=req, status="failed", source=None, failure=None)
    with pytest.raises(ValidationError):  # failed with source
        IngestionResult(requested=req, status="failed", source=ns, failure=sf)


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        Board(id="b1", name="finance", created_at=datetime(2026, 6, 1), bogus=1)  # type: ignore[call-arg]
