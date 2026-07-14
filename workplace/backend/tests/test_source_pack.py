"""M6.7 — built-in default source-pack template (SSOT FR-3).

A fixed, editable starter pack of seed sources seeds a board's subscriptions on
cold start so day one isn't empty. The pack is static and spans the five FR-3
categories; it is NOT topic-wide web discovery. `default_source_pack()` hands out
a fresh copy so an operator's edits never mutate the shared constant."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.models import SourcePackEntry
from app.source_pack import DEFAULT_SOURCE_PACK, default_source_pack


def test_default_pack_spans_the_five_fr3_categories() -> None:
    categories = {e.category for e in DEFAULT_SOURCE_PACK}
    assert categories == {"central_bank", "regulator", "company_ir", "rss", "youtube"}
    # the spec calls for "a few" RSS + YouTube + IR — the pack is a real starter list
    assert len(DEFAULT_SOURCE_PACK) >= 5


def test_pack_carries_the_anchor_authorities() -> None:
    urls = " ".join(e.url for e in DEFAULT_SOURCE_PACK)
    assert "federalreserve.gov" in urls  # Fed
    assert "sec.gov" in urls  # SEC
    # every entry is a usable subscription seed: a url + a resolved poll mode
    for entry in DEFAULT_SOURCE_PACK:
        assert entry.url.startswith("http")
        assert entry.mode in {"direct", "autodiscover", "platform", "homepage_diff"}
        assert entry.label


def test_default_pack_returns_a_fresh_editable_copy() -> None:
    pack = default_source_pack()
    # the returned entries are NOT the shared constant's objects …
    assert all(a is not b for a, b in zip(pack, DEFAULT_SOURCE_PACK, strict=True))
    # … so editing a field on the operator's copy never pollutes the template
    original_url = DEFAULT_SOURCE_PACK[0].url
    pack[0].url = "https://example.com/mutated"
    assert DEFAULT_SOURCE_PACK[0].url == original_url
    assert default_source_pack()[0].url == original_url
    # and trimming the copy leaves the shared constant intact
    pack.pop()
    assert len(default_source_pack()) == len(DEFAULT_SOURCE_PACK)


def test_get_source_pack_endpoint_returns_the_template() -> None:
    client = TestClient(create_app())
    res = client.get("/source-pack")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == len(DEFAULT_SOURCE_PACK)
    # round-trips through the §7 contract shape
    entries = [SourcePackEntry(**item) for item in body]
    assert {e.category for e in entries} == {
        "central_bank",
        "regulator",
        "company_ir",
        "rss",
        "youtube",
    }


def test_get_source_pack_is_deterministic() -> None:
    client = TestClient(create_app())
    assert client.get("/source-pack").json() == client.get("/source-pack").json()
