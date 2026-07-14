"""Deterministic source tiering (M3.6, SSOT FR-12 / NFR-7).

Maps a source's domain to a tier — T1 (primary/official) · T1.5 (official social)
· T2 (media / aggregator / KOL / unknown) — via a config table + heuristics, in
code, never an LLM (NFR-7). A source with no resolvable domain is T2 (FR-7). A
caller-supplied `overrides` map applies a human tier override first (FR-17). Tier
maps to a static `reputation_prior`; reputation comes only from this static tier
plus explicit human input — never self-learned from the system's own verdicts (FR-9).
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

from app.core.config import (
    IR_PATH_SEGMENTS,
    IR_SUBDOMAIN_PREFIXES,
    TIER1_DOMAINS,
    TIER1_IR_PATH_DOMAINS,
    TIER15_OFFICIAL_ACCOUNTS,
    TIER_REPUTATION_PRIOR,
)
from app.schemas.models import NormalizedSource, Tier


def _path_segments(url: str | None) -> list[str]:
    if not url:
        return []
    path = urlsplit(url if "://" in url else f"https://{url}").path
    return [seg.lower() for seg in path.split("/") if seg]


def _is_tier1_domain(domain: str) -> bool:
    # exact host or any subdomain of a T1 registrable domain
    return domain in TIER1_DOMAINS or any(domain.endswith(f".{d}") for d in TIER1_DOMAINS)


def _is_company_ir(domain: str, url: str | None) -> bool:
    """Company investor-relations source → T1 (FR-12): an `ir.`/`investor(s).`
    subdomain, or an allowlisted company apex domain with an IR path segment. The
    path rule is gated so a generic `/investor` path on a social/media/unknown host
    does NOT reach T1."""
    first_label = domain.split(".", 1)[0]
    if "." in domain and first_label in IR_SUBDOMAIN_PREFIXES:
        return True
    if domain in TIER1_IR_PATH_DOMAINS:
        return any(seg in IR_PATH_SEGMENTS for seg in _path_segments(url))
    return False


def _social_handle(url: str | None) -> str | None:
    """First path segment of a social URL as a lowercased handle (no leading @)."""
    segments = _path_segments(url)
    return segments[0].lstrip("@") if segments else None


def assign_tier(
    domain: str | None,
    *,
    url: str | None = None,
    overrides: Mapping[str, Tier] | None = None,
) -> Tier:
    """Deterministic tier for a (normalized) domain. `url` supplies the social
    handle for T1.5 detection; `overrides[domain]` (human) wins over heuristics."""
    if domain is None:
        return "T2"  # no resolvable domain → T2 (FR-7)
    if overrides and domain in overrides:
        return overrides[domain]
    if _is_tier1_domain(domain) or _is_company_ir(domain, url):
        return "T1"
    official_handles = TIER15_OFFICIAL_ACCOUNTS.get(domain)
    if official_handles is not None:
        handle = _social_handle(url)
        if handle is not None and handle in official_handles:
            return "T1.5"  # official account on its own platform
        return "T2"  # a non-official account on a social host is T2
    return "T2"


def reputation_for_tier(tier: Tier) -> float:
    """Static reputation prior for a tier (FR-12; never self-learned)."""
    return TIER_REPUTATION_PRIOR[tier]


def tier_source(
    source: NormalizedSource, *, overrides: Mapping[str, Tier] | None = None
) -> NormalizedSource:
    """Return a copy of `source` with its `tier` set deterministically."""
    tier = assign_tier(source.domain, url=source.url, overrides=overrides)
    return source.model_copy(update={"tier": tier})
