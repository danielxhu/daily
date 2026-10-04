"""Per-source ingestion outcome envelope (M1A.1).

The schemas (`SourceRequest` / `SourceFailure` / `IngestionResult`) come from X0.4
and the deterministic `kind → next_action` map + `typed_skip` from X0.8 (fetch
policy). M1A.1 adds the canonical constructors every fetcher/orchestrator uses to
report a per-source outcome, so a batch serializes to JSON showing each source's
ok/failed status and — on failure — its typed kind + user-facing next step (FR-1
partial batch / FR-2 typed failure).
"""

from __future__ import annotations

from app.ingestion.fetch_policy import typed_skip
from app.schemas.models import (
    IngestionResult,
    NormalizedSource,
    SourceFailure,
    SourceFailureKind,
    SourceRequest,
    SourceType,
)


def ok_result(requested: SourceRequest, source: NormalizedSource) -> IngestionResult:
    return IngestionResult(requested=requested, status="ok", source=source, failure=None)


def failed_result(requested: SourceRequest, failure: SourceFailure) -> IngestionResult:
    return IngestionResult(requested=requested, status="failed", source=None, failure=failure)


def failed_from(
    requested: SourceRequest,
    kind: SourceFailureKind,
    *,
    reason: str,
    requested_url: str | None = None,
    source_type: SourceType | None = None,
) -> IngestionResult:
    """One-liner for a fetcher: turn a failure kind into a typed `IngestionResult`
    carrying the deterministic `next_action` (§6.6). Falls back to the request's
    own URL when `requested_url` is not given."""
    failure = typed_skip(
        kind,
        reason=reason,
        requested_url=requested_url if requested_url is not None else requested.url,
        source_type=source_type if source_type is not None else requested.declared_type,
    )
    return failed_result(requested, failure)
