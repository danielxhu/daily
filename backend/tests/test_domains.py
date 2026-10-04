"""M1A.2 — domain normalization helper."""

from __future__ import annotations

import pytest

from app.ingestion.domains import normalize_domain


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("reuters.com", "reuters.com"),
        ("www.reuters.com", "reuters.com"),
        ("Reuters.COM", "reuters.com"),
        ("https://www.reuters.com/article/x?y=1", "reuters.com"),
        ("http://sec.gov/", "sec.gov"),
        ("news.bbc.co.uk", "news.bbc.co.uk"),
        ("  reuters.com  ", "reuters.com"),
        ("user@reuters.com", "reuters.com"),
        ("reuters.com:443", "reuters.com"),
    ],
)
def test_normalize_valid(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", None, "not a domain", "localhost", "foo", "http://", "...", "a..b"],
)
def test_normalize_invalid_returns_none(raw: str | None) -> None:
    assert normalize_domain(raw) is None
