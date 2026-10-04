"""M6.7 — built-in default source-pack template (SSOT FR-3).

A fixed, editable starter pack of seed sources seeds a board's subscriptions on
cold start so day one isn't empty. The pack is static — it is NOT topic-wide web
discovery. `default_source_pack()` hands out a fresh copy so an operator's edits
never mutate the shared constant."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.models import SourcePackEntry
from app.source_pack import DEFAULT_SOURCE_PACK, default_source_pack


def test_every_entry_is_a_usable_subscription_seed() -> None:
    assert len(DEFAULT_SOURCE_PACK) >= 3  # a real starter list, not a token entry
    for entry in DEFAULT_SOURCE_PACK:
        assert entry.url.startswith("http")
        assert entry.mode in {"direct", "autodiscover", "platform", "homepage_diff"}
        # the label becomes the source's display name when the pack is adopted, so
        # an empty one would seed a list of bare URLs
        assert entry.label


def test_entries_are_tagged_to_preset_boards_that_exist() -> None:
    """A pack entry's board is written straight onto the subscription, so a tag
    that no migration creates would seed sources into a board the UI cannot show."""
    preset = {"b_politics", "b_economy", "b_tech"}
    for entry in DEFAULT_SOURCE_PACK:
        assert entry.board_id in preset


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
    assert [e.url for e in entries] == [e.url for e in DEFAULT_SOURCE_PACK]


def test_get_source_pack_is_deterministic() -> None:
    client = TestClient(create_app())
    assert client.get("/source-pack").json() == client.get("/source-pack").json()
