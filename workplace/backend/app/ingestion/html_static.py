"""HTML static extraction (M1A.4, SSOT §FR-2 tier 1).

The first real network fetcher: `httpx` (built from the X0.8 fetch policy — no
cookies/proxy, `trust_env=False`, timeout) + `trafilatura` main-content extraction.
On a clean article this yields `raw_text` with `extraction_method="static_html"`.
When the static body is empty / too short, it returns an `empty` result — the
caller then tries the Stage 1B structured/render fallbacks, or (at 1A) typed-skips
with `parse_empty`. Tests replay fixtures from vcrpy cassettes (offline, NFR-3).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx
import trafilatura

from app.ingestion.domains import normalize_domain
from app.ingestion.fetch_policy import httpx_client_kwargs
from app.schemas.models import ExtractionMethod, NormalizedSource

# Below this many characters of extracted main text, treat the static parse as
# empty/too-short (heuristic) → fallback (1B) or typed-skip (parse_empty).
MIN_MAIN_TEXT_LEN = 200


def build_client() -> httpx.Client:
    """An httpx client bound to the X0.8 fetch policy (no cookies/proxy, timeout)."""
    return httpx.Client(**httpx_client_kwargs())  # type: ignore[arg-type]


def fetch_html(url: str, *, client: httpx.Client) -> tuple[str, str]:
    """Fetch a URL → (decoded body, content-type). Redirects already followed by
    the policy client."""
    resp = client.get(url)
    resp.raise_for_status()
    return resp.text, resp.headers.get("content-type", "")


def extract_main_text(html: str) -> str | None:
    """trafilatura main-content extraction; `None` when empty or too short."""
    text = trafilatura.extract(html)
    if text is None:
        return None
    text = text.strip()
    return text if len(text) >= MIN_MAIN_TEXT_LEN else None


def build_webpage_source(url: str, text: str, method: ExtractionMethod) -> NormalizedSource:
    """Assemble a webpage `NormalizedSource` for any HTML tier (static M1A.4 /
    structured M1B.1 / rendered M1B.2) — one place so domain/type stay consistent."""
    return NormalizedSource(
        source_id=uuid.uuid4().hex,
        type="webpage",
        origin="user",
        url=url,
        domain=normalize_domain(url),
        raw_text=text,
        extraction_method=method,
        segments=[],
        frame_annotations=[],
    )


@dataclass(frozen=True)
class StaticResult:
    source: NormalizedSource | None  # set on success
    empty: bool  # True → static body empty/too-short (→ 1B fallback or parse_empty)


def ingest_html_static(url: str, *, client: httpx.Client) -> StaticResult:
    html, _content_type = fetch_html(url, client=client)
    text = extract_main_text(html)
    if text is None:
        return StaticResult(source=None, empty=True)
    source = build_webpage_source(url, text, "static_html")
    return StaticResult(source=source, empty=False)
