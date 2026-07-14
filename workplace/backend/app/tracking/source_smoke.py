"""Seed-source smoke check (M13.6, beta go-live hygiene).

A MANUAL operator tool: probe every source-pack entry for real-world fetchability
— the beta test found the pack's #1 source (federalreserve.gov) anti-bot-blocked
in a headless environment, discovered only after a confusing all-green Day-1. Run
this once before handing daily to a friend, so every seed source's typed outcome
is known up front.

What it checks, per entry (best-effort, ZERO LLM spend — ingestion probes only):

* `direct` / `autodiscover` — fetch + parse the feed; then probe the newest item's
  article page through the same typed ingestion as the pipeline (`anti_bot`,
  `paywall`, … exactly what a real poll would hit). Audio/video feeds skip the
  article probe (a smoke must not transcribe a podcast).
* `homepage_diff` — fetch the homepage and count candidate links.
* `platform` / `youtube` — check yt-dlp is importable in THIS venv (the beta found
  it missing) and fetch the channel/feed URL.

Deliberately NOT part of `scripts/test-all.sh` (it needs the network); the report
logic is injectable + offline-tested. Run from `backend/`:

    .venv/bin/python -m app.tracking.source_smoke
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass

from app.schemas.models import IngestionResult, SourcePackEntry, SourceRequest
from app.source_pack import default_source_pack
from app.tracking.feed import parse_feed
from app.tracking.homepage import extract_candidate_links
from app.tracking.poll import newest_first

Fetch = Callable[[str], bytes]
Probe = Callable[[SourceRequest], IngestionResult]  # the pipeline's typed ingestion

# feed enclosure types the smoke must not probe as articles (no transcribing)
_AV_CATEGORIES = {"youtube"}


@dataclass(frozen=True)
class SmokeResult:
    """One entry's typed smoke outcome — printable as a go-live checklist row."""

    label: str
    url: str
    mode: str
    ok: bool
    note: str  # human-readable: item counts, typed failure kind, or skip reason


def ytdlp_available() -> bool:
    """Is yt-dlp importable in THIS venv? (Beta P0 note: the pipeline's YouTube
    path fails on machines where the extra was never installed.)"""
    return importlib.util.find_spec("yt_dlp") is not None


def _probe_note(result: IngestionResult) -> tuple[bool, str]:
    if result.status == "ok":
        return True, "feed + first article fetchable"
    kind = result.failure.kind if result.failure else "unknown"
    action = (result.failure.next_action if result.failure else None) or ""
    return False, f"first article failed: {kind} — {action}".rstrip(" —")


def smoke_entry(
    entry: SourcePackEntry,
    *,
    fetch: Fetch,
    probe: Probe,
    ytdlp: bool,
) -> SmokeResult:
    """Probe ONE pack entry; every failure is typed, nothing raises (a smoke that
    crashes on the exact broken source it exists to find would be useless)."""
    if entry.mode == "platform" or entry.category in _AV_CATEGORIES:
        if not ytdlp:
            return SmokeResult(
                entry.label,
                entry.url,
                entry.mode,
                ok=False,
                note="yt-dlp is NOT importable in this venv — install it before go-live",
            )
        try:
            fetch(entry.url)
        except Exception as exc:
            return SmokeResult(
                entry.label, entry.url, entry.mode, ok=False, note=f"channel fetch failed: {exc}"
            )
        return SmokeResult(
            entry.label,
            entry.url,
            entry.mode,
            ok=True,
            note="yt-dlp present + channel reachable (captions probed only on real polls)",
        )

    if entry.mode == "homepage_diff":
        try:
            links = extract_candidate_links(fetch(entry.url), base_url=entry.url)
        except Exception as exc:
            return SmokeResult(
                entry.label, entry.url, entry.mode, ok=False, note=f"homepage fetch failed: {exc}"
            )
        if not links:
            return SmokeResult(
                entry.label,
                entry.url,
                entry.mode,
                ok=False,
                note="homepage reachable but no candidate links found",
            )
        return SmokeResult(
            entry.label, entry.url, entry.mode, ok=True, note=f"{len(links)} candidate links"
        )

    # direct / autodiscover feeds
    try:
        items = parse_feed(fetch(entry.url))
    except Exception as exc:
        return SmokeResult(
            entry.label, entry.url, entry.mode, ok=False, note=f"feed fetch/parse failed: {exc}"
        )
    if not items:
        return SmokeResult(
            entry.label, entry.url, entry.mode, ok=False, note="feed parsed but lists 0 items"
        )
    # "newest article" means BY DATE (same rule as the first-poll cap, M13.4):
    # feed list order is not guaranteed newest-first, and probing an old article
    # would misstate the anti-bot/paywall risk of what a real poll fetches next
    first_url = next((i.url for i in newest_first(items) if i.url), None)
    if first_url is None:
        return SmokeResult(
            entry.label,
            entry.url,
            entry.mode,
            ok=False,
            note=f"{len(items)} items but none carries a link",
        )
    try:
        ok, note = _probe_note(probe(SourceRequest(kind="url", url=first_url)))
    except Exception as exc:  # a probe must degrade like the pipeline, but belt+braces
        ok, note = False, f"article probe crashed: {exc}"
    return SmokeResult(
        entry.label, entry.url, entry.mode, ok=ok, note=f"{len(items)} items; {note}"
    )


def smoke_source_pack(
    entries: list[SourcePackEntry] | None = None,
    *,
    fetch: Fetch,
    probe: Probe,
    ytdlp: bool | None = None,
) -> list[SmokeResult]:
    """Typed go-live report over the (default) source pack. Injectable fetch/probe
    keep it offline-testable; the CLI below wires the real network."""
    resolved_ytdlp = ytdlp_available() if ytdlp is None else ytdlp
    return [
        smoke_entry(e, fetch=fetch, probe=probe, ytdlp=resolved_ytdlp)
        for e in (entries if entries is not None else default_source_pack())
    ]


def main() -> int:
    """Real-network smoke over the default pack (manual; NO LLM spend)."""
    from app.ingestion.ingest import ingest_one
    from app.tracking.fetch import feed_fetch

    results = smoke_source_pack(fetch=feed_fetch, probe=ingest_one)
    width = max(len(r.label) for r in results)
    for r in results:
        print(f"{'OK ' if r.ok else 'FAIL'}  {r.label.ljust(width)}  {r.note}")
    failed = sum(1 for r in results if not r.ok)
    print(f"\n{len(results) - failed}/{len(results)} seed sources pass; {failed} need a look.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
