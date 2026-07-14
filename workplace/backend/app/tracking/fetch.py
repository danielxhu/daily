"""Feed/homepage fetch for the live poll runtime (M9.10, SSOT §6.2).

The poll loop (`poll.py`) takes an injected `fetch: (url) -> bytes` so it stays
offline in tests (NFR-3). This is the **real** one used by the running app: a single
`httpx` GET bound to the same X0.8 fetch policy as ingestion (no cookies/proxy,
`trust_env=False`, timeout, redirects followed). It returns the raw bytes of a feed
or homepage; per-item content is fetched later by ingestion when each new item is
dispatched into the pipeline.

`raise_for_status()` lets a 404/410/403/429 surface as an `httpx.HTTPStatusError`
whose `.response.status_code` the health classifier (M7.8) reads to back off vs.
mark a source gone. Anti-bot / paywalls are not bypassed (§2.2) — they typed-skip
via that classifier, never special-cased here.
"""

from __future__ import annotations

import httpx

from app.ingestion.fetch_policy import httpx_client_kwargs


def feed_fetch(url: str) -> bytes:
    """Fetch a feed/homepage URL → raw bytes (policy-bound httpx GET)."""
    with httpx.Client(**httpx_client_kwargs()) as client:  # type: ignore[arg-type]
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content
