"""X0.3 — HTTP cassette replay strategy (SSOT §9.2). Proves real `httpx` fetches
can be served from a recorded cassette with zero network, and that an un-recorded
request fails closed rather than hitting the wire."""

from __future__ import annotations

import httpx
import pytest
from vcr.errors import CannotOverwriteExistingCassetteException

from tests.http_cassette import replay

_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193"


def test_httpx_get_is_served_from_cassette() -> None:
    with replay("sec_edgar_sample.yaml"):
        resp = httpx.get(_URL, headers={"User-Agent": "daily-test"})
    assert resp.status_code == 200
    assert "Total revenue" in resp.text


def test_unrecorded_request_fails_closed() -> None:
    # No matching interaction → vcrpy raises; it must NOT fall through to network.
    with replay("sec_edgar_sample.yaml"):
        with pytest.raises(CannotOverwriteExistingCassetteException):
            httpx.get("https://www.sec.gov/not-in-cassette")
