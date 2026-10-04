"""Pasted-text ingestion (M1A.2).

A `SourceRequest(kind="text")` becomes a `NormalizedSource(extraction_method=
"pasted_text")` — the escape hatch for when a URL can't be fetched (FR-1/FR-2).

Independence rules (FR-7):
- `source_label` is **display-only** and lives on the request; it never becomes a
  domain and never adds N/K credit, so it is not copied onto the source.
- `declared_domain` counts toward N/K only after normalization/validation; an
  absent or invalid one leaves `domain=None` (excluded from K/N downstream, M3.10).
Pasted text has no URL and no time segments.
"""

from __future__ import annotations

import uuid

from app.ingestion.domains import normalize_domain
from app.schemas.models import NormalizedSource, SourceRequest


def ingest_text(req: SourceRequest) -> NormalizedSource:
    if req.kind != "text" or not req.text:
        raise ValueError("ingest_text requires SourceRequest(kind='text', text=...)")
    return NormalizedSource(
        source_id=uuid.uuid4().hex,
        type="text",
        origin="user",
        url=None,  # pasted text has no URL
        domain=normalize_domain(req.declared_domain),  # None unless validated
        raw_text=req.text,
        extraction_method="pasted_text",
        segments=[],
        frame_annotations=[],
        # citation_type / tier keep §7 defaults (primary / T2); set later by
        # independence_detect (M3.7) / tiering (M3.6).
    )
