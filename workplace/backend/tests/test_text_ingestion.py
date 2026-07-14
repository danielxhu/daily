"""M1A.2 — pasted-text ingestion: extraction_method, declared_domain rules,
source_label display-only, domain=None doesn't crash."""

from __future__ import annotations

import pytest

from app.ingestion.text_source import ingest_text
from app.schemas.models import NormalizedSource, SourceRequest


def test_pasted_text_basic_shape() -> None:
    src = ingest_text(SourceRequest(kind="text", text="hello world"))
    assert isinstance(src, NormalizedSource)
    assert src.type == "text"
    assert src.extraction_method == "pasted_text"
    assert src.url is None
    assert src.raw_text == "hello world"
    assert src.origin == "user"
    assert src.domain is None  # no declared_domain → excluded from K/N (FR-7)


def test_validated_declared_domain_sets_domain() -> None:
    src = ingest_text(
        SourceRequest(kind="text", text="body", declared_domain="https://www.reuters.com/x")
    )
    assert src.domain == "reuters.com"  # normalized


def test_invalid_declared_domain_leaves_domain_none() -> None:
    # bad domain must NOT crash and must NOT count — domain stays None
    src = ingest_text(SourceRequest(kind="text", text="body", declared_domain="not a domain"))
    assert src.domain is None


def test_source_label_is_display_only_not_a_domain() -> None:
    # a human label never becomes a domain / never adds independence credit
    src = ingest_text(
        SourceRequest(kind="text", text="body", source_label="A friend's WeChat forward")
    )
    assert src.domain is None


def test_source_label_with_declared_domain() -> None:
    req = SourceRequest(
        kind="text", text="body", source_label="Reuters (pasted)", declared_domain="reuters.com"
    )
    src = ingest_text(req)
    assert src.domain == "reuters.com"  # only the declared_domain counts
    # the label stays on the request (display/provenance), not on the source
    assert not hasattr(src, "source_label")
    assert req.source_label == "Reuters (pasted)"


def test_rejects_non_text_request() -> None:
    with pytest.raises(ValueError):
        ingest_text(SourceRequest(kind="url", url="https://x.test"))
