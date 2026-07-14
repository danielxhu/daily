"""M3.6 — deterministic source tiering (SSOT FR-12 / §8.1 tier-assignment metric).

T1 primary/official · T1.5 official social · T2 everyone else. Config table +
heuristics, code-only; human override hook; static tier → reputation prior."""

from __future__ import annotations

from datetime import UTC, datetime

from app.ingestion.domains import normalize_domain
from app.schemas.models import NormalizedSource
from app.tiering import assign_tier, reputation_for_tier, tier_source

_TS = datetime(2026, 6, 23, tzinfo=UTC)


def _tier_for_url(url: str) -> str:
    return assign_tier(normalize_domain(url), url=url)


def test_official_primary_domains_are_t1() -> None:
    assert _tier_for_url("https://www.sec.gov/cgi-bin/browse-edgar") == "T1"
    assert _tier_for_url("https://www.federalreserve.gov/x") == "T1"
    # subdomains of a T1 registrable domain are T1 too
    assert assign_tier("efts.sec.gov") == "T1"


def test_official_social_handle_is_t15_others_t2() -> None:
    assert _tier_for_url("https://twitter.com/federalreserve") == "T1.5"
    assert _tier_for_url("https://x.com/SecGov") == "T1.5"  # handle match is case-insensitive
    # a non-official account on the same host is just T2
    assert _tier_for_url("https://twitter.com/some_random_kol") == "T2"


def test_official_handle_is_bound_to_its_platform() -> None:
    # the same handle on a host without a verified official account stays T2 —
    # a look-alike account elsewhere must not inherit T1.5
    assert _tier_for_url("https://t.me/federalreserve") == "T2"
    assert _tier_for_url("https://weibo.com/secgov") == "T2"


def test_company_ir_sources_are_t1() -> None:
    # IR subdomains
    assert _tier_for_url("https://investor.nvidia.com/news") == "T1"
    assert _tier_for_url("https://ir.tesla.com/press-release") == "T1"
    assert _tier_for_url("https://investors.apple.com/news-releases") == "T1"
    # apex domain with an investor-relations path segment
    assert _tier_for_url("https://www.microsoft.com/en-us/investor/earnings") == "T1"
    # a non-IR page on the same apex domain is not lifted to T1
    assert _tier_for_url("https://www.microsoft.com/windows") == "T2"


def test_investor_path_on_non_company_hosts_stays_low() -> None:
    # a generic /investor path must NOT reach T1 on social / media / unknown hosts
    assert _tier_for_url("https://twitter.com/investor") == "T2"
    assert _tier_for_url("https://seekingalpha.com/investor/article") == "T2"
    assert _tier_for_url("https://example.com/en-us/investor/news") == "T2"


def test_media_aggregator_and_unknown_are_t2() -> None:
    assert _tier_for_url("https://seekingalpha.com/article/x") == "T2"
    assert _tier_for_url("https://example.com/blog") == "T2"


def test_no_resolvable_domain_is_t2() -> None:
    assert assign_tier(None) == "T2"  # pasted text / unclassifiable (FR-7)


def test_manual_override_wins_both_ways() -> None:
    # promote an aggregator …
    assert assign_tier("seekingalpha.com", overrides={"seekingalpha.com": "T1"}) == "T1"
    # … and demote an official domain (human override beats the table)
    assert assign_tier("sec.gov", overrides={"sec.gov": "T2"}) == "T2"


def test_reputation_prior_is_static_and_ordered() -> None:
    assert reputation_for_tier("T1") == 0.9
    assert reputation_for_tier("T1.5") == 0.75
    assert reputation_for_tier("T2") == 0.5
    assert reputation_for_tier("T1") > reputation_for_tier("T1.5") > reputation_for_tier("T2")


def test_tier_source_sets_tier_without_mutating_original() -> None:
    src = NormalizedSource(
        source_id="s1",
        type="webpage",
        url="https://www.sec.gov/news",
        domain="sec.gov",
        raw_text="body",
        segments=[],
        frame_annotations=[],
    )
    tiered = tier_source(src)
    assert tiered.tier == "T1"
    assert src.tier == "T2"  # default unchanged on the original
