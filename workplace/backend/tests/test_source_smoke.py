"""M13.6 — seed-source smoke check (go-live hygiene, beta P2).

Offline (NFR-3): fetch/probe are injected fakes. Covers the typed outcomes the
operator needs before handing daily to a friend — the anti-bot Fed case, the
missing yt-dlp case, homepage candidates, and the never-crashes guarantee."""

from __future__ import annotations

from app.ingestion.result import failed_from, ok_result
from app.schemas.models import (
    IngestionResult,
    NormalizedSource,
    SourcePackEntry,
    SourceRequest,
)
from app.source_pack import default_source_pack
from app.tracking.source_smoke import smoke_entry, smoke_source_pack
from tests.fixtures_loader import fixture_path

RSS = fixture_path("feeds/rss_sample.xml").read_bytes()
HOMEPAGE = fixture_path("feeds/homepage_t0.html").read_bytes()


def _entry(mode: str = "direct", category: str = "rss") -> SourcePackEntry:
    return SourcePackEntry(
        label="Test source",
        url="https://ex.com/feed",
        mode=mode,  # type: ignore[arg-type]
        category=category,  # type: ignore[arg-type]
        board_id="b_economy",
    )


def _ok_probe(req: SourceRequest) -> IngestionResult:
    return ok_result(
        req,
        NormalizedSource(
            source_id="s",
            type="webpage",
            url=req.url,
            domain="ex.com",
            raw_text="…",
            segments=[],
            frame_annotations=[],
        ),
    )


def _anti_bot_probe(req: SourceRequest) -> IngestionResult:
    return failed_from(req, "anti_bot", reason="blocked", requested_url=req.url)


def test_feed_entry_probes_the_first_article_and_reports_ok() -> None:
    r = smoke_entry(_entry(), fetch=lambda _u: RSS, probe=_ok_probe, ytdlp=True)
    assert r.ok and "3 items" in r.note and "article fetchable" in r.note


def test_anti_bot_article_is_a_typed_failure_the_fed_case() -> None:
    # the exact beta scenario: feed fine, article pages bot-blocked — the smoke
    # must surface the typed kind BEFORE a friend hits it on Day-1
    r = smoke_entry(_entry(), fetch=lambda _u: RSS, probe=_anti_bot_probe, ytdlp=True)
    assert not r.ok and "anti_bot" in r.note


def test_missing_ytdlp_fails_youtube_entries_with_a_clear_note() -> None:
    r = smoke_entry(
        _entry(mode="platform", category="youtube"),
        fetch=lambda _u: b"",
        probe=_ok_probe,
        ytdlp=False,
    )
    assert not r.ok and "yt-dlp" in r.note
    # with yt-dlp present + channel reachable, the entry passes (no caption probe)
    ok = smoke_entry(
        _entry(mode="platform", category="youtube"),
        fetch=lambda _u: b"<html></html>",
        probe=_ok_probe,
        ytdlp=True,
    )
    assert ok.ok


def test_homepage_entry_counts_candidate_links() -> None:
    r = smoke_entry(
        _entry(mode="homepage_diff", category="company_ir"),
        fetch=lambda _u: HOMEPAGE,
        probe=_ok_probe,
        ytdlp=True,
    )
    assert r.ok and "candidate links" in r.note


def test_smoke_never_raises_on_broken_sources() -> None:
    def boom(_url: str) -> bytes:
        raise ConnectionError("dns failure")

    r = smoke_entry(_entry(), fetch=boom, probe=_ok_probe, ytdlp=True)
    assert not r.ok and "feed fetch/parse failed" in r.note


def test_whole_default_pack_reports_one_typed_row_per_entry() -> None:
    # every one of the 13 seed entries produces a row — a smoke that skips entries
    # would defeat its purpose (fetch fails everywhere; still one row each)
    def refuse(_url: str) -> bytes:
        raise ConnectionError("offline")

    results = smoke_source_pack(fetch=refuse, probe=_ok_probe, ytdlp=False)
    assert len(results) == len(default_source_pack())
    assert all(not r.ok for r in results)
    assert all(r.note for r in results)  # every failure is explained, never blank


OLD_TO_NEW_RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><link>https://ex.com/old</link><pubDate>Tue, 01 Jul 2026 00:00:00 GMT</pubDate></item>
<item><link>https://ex.com/mid</link><pubDate>Wed, 02 Jul 2026 00:00:00 GMT</pubDate></item>
<item><link>https://ex.com/new</link><pubDate>Thu, 03 Jul 2026 00:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_smoke_probes_the_newest_article_by_date_not_feed_order() -> None:
    """M13.6 review blocker (same class as M13.4): an old→new feed must get its
    NEWEST article probed — probing the oldest would misstate the anti-bot risk of
    exactly what a real poll fetches next."""
    probed: list[str | None] = []

    def recording_probe(req: SourceRequest) -> IngestionResult:
        probed.append(req.url)
        return _ok_probe(req)

    r = smoke_entry(_entry(), fetch=lambda _u: OLD_TO_NEW_RSS, probe=recording_probe, ytdlp=True)
    assert r.ok
    assert probed == ["https://ex.com/new"]  # by pubDate — NOT feed-order first
