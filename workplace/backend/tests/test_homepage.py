"""M7.5 — homepage-diff fallback (SSOT §6.1 step 4 / §6.4).

Extracts candidate article links from a homepage and diffs successive polls. Scope:
extraction + link-set diff only — no network (M7.7), no link-set persistence /
SeenItem dedup (M7.6), no ingestion dispatch. Heuristic + best-effort; the tests
assert it does NOT over-detect nav/footer/external/section links."""

from __future__ import annotations

from app.tracking.homepage import diff_new_links, extract_candidate_links
from tests.fixtures_loader import fixture_path

BASE = "https://news.example.com/"


def _t0() -> bytes:
    return fixture_path("feeds/homepage_t0.html").read_bytes()


def _t1() -> bytes:
    return fixture_path("feeds/homepage_t1.html").read_bytes()


def test_extracts_only_in_domain_article_links() -> None:
    links = extract_candidate_links(_t0(), BASE)
    assert links == [
        "https://news.example.com/2026/06/fed-holds-rates-steady",
        "https://news.example.com/2026/06/nvidia-tops-q2-estimates",
    ]


def test_does_not_over_detect_nav_footer_external_or_section_links() -> None:
    # the false-positive guard: nav (Home/About), sections (category/tag/author),
    # footer (privacy/terms), mailto, fragments, and external domains are all excluded
    links = extract_candidate_links(_t0(), BASE)
    joined = " ".join(links)
    for excluded in (
        "/about",
        "/category/",
        "/tag/",
        "/author/",
        "/privacy",
        "/terms",
        "mailto:",
        "other-site.com",
        "#top",
    ):
        assert excluded not in joined
    assert "https://news.example.com/" not in links  # the homepage itself


def test_diff_returns_only_the_new_article() -> None:
    before = extract_candidate_links(_t0(), BASE)
    after = extract_candidate_links(_t1(), BASE)
    assert diff_new_links(before, after) == [
        "https://news.example.com/2026/06/markets-rally-on-cpi"
    ]


def test_diff_is_empty_when_unchanged() -> None:
    links = extract_candidate_links(_t0(), BASE)
    assert diff_new_links(links, links) == []


def test_diff_preserves_current_order_and_ignores_removed() -> None:
    previous = ["https://x/a-1", "https://x/b-2"]
    current = ["https://x/c-3", "https://x/a-1", "https://x/d-4"]
    # only genuinely new links, in current order; a dropped link (b-2) is not "new"
    assert diff_new_links(previous, current) == ["https://x/c-3", "https://x/d-4"]


def test_relative_links_resolved_and_deduped() -> None:
    html = (
        '<a href="/2026/06/story-one">one</a>'
        '<a href="/2026/06/story-one#section">dup w/ fragment</a>'
        '<a href="/p/12345">numeric id slug</a>'
        '<a href="/news/plainword">no slug-like segment</a>'
    )
    links = extract_candidate_links(html, BASE)
    assert links == [
        "https://news.example.com/2026/06/story-one",  # fragment dropped → deduped
        "https://news.example.com/p/12345",
    ]
    # a path with no hyphen/date/id segment is not treated as an article
    assert "https://news.example.com/news/plainword" not in links
