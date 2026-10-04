"""Source normalization (M1A.9, SSOT §5 / §7).

The convergence point: every ingestion path becomes one `NormalizedSource` so the
rest of the pipeline has a single input shape.

- Pasted text (M1A.2) and static HTML (M1A.4) already return `NormalizedSource`.
- Transcripts (podcast M1A.5/M1A.6, YouTube caption M1A.7 / audio M1A.8) are mapped
  here: `TranscriptResult` (ms segments) → §7 `Segment`s (second timestamps, words).

**Char-offset back-mapping (FR-8).** §7 `Segment` carries audio time, not char
spans, so `raw_text` is built as the canonical `SEGMENT_JOINER`-join of segment
texts and each segment's char span is *recomputed* from it. `char_span_to_time`
maps a claim's char span (into `raw_text`) back to audio time — caption cues have
no word timestamps, whisper segments do, and this works for both (it uses
segment-level times).
"""

from __future__ import annotations

from app.clients.base import TranscriptResult
from app.ingestion.domains import normalize_domain
from app.schemas.models import ExtractionMethod, NormalizedSource, Segment, SourceType

SEGMENT_JOINER = "\n"


def normalize_transcript(
    transcript: TranscriptResult,
    *,
    source_id: str,
    type: SourceType,
    extraction_method: ExtractionMethod,
    url: str | None = None,
    domain: str | None = None,
) -> NormalizedSource:
    """Map a `TranscriptResult` to a `NormalizedSource`. `raw_text` is the canonical
    join of segment texts so char offsets map back to segment audio time.

    `domain` is set from a validated explicit `domain` if given, else derived from
    the `url` host (SSOT §7 / §180) — so a normal podcast/YouTube URL is NOT treated
    as an unknown-domain source and excluded from independence K/N (FR-7)."""
    resolved_domain = normalize_domain(domain) or normalize_domain(url)
    segments = [
        Segment(
            text=ts.text,
            start_ts=ts.start_ms / 1000,
            end_ts=ts.end_ms / 1000,
            words=ts.words,
        )
        for ts in transcript.segments
    ]
    raw_text = SEGMENT_JOINER.join(s.text for s in segments)
    return NormalizedSource(
        source_id=source_id,
        type=type,
        origin="user",
        url=url,
        domain=resolved_domain,
        raw_text=raw_text,
        extraction_method=extraction_method,
        segments=segments,
        frame_annotations=[],
        # citation_type / tier keep §7 defaults (primary / T2); set later by
        # independence_detect (M3.7) / tiering (M3.6).
    )


def segment_char_spans(source: NormalizedSource) -> list[tuple[int, int, Segment]]:
    """Each segment's [start, end) char span within `raw_text` (reconstructed from
    the canonical join)."""
    spans: list[tuple[int, int, Segment]] = []
    offset = 0
    for seg in source.segments:
        end = offset + len(seg.text)
        spans.append((offset, end, seg))
        offset = end + len(SEGMENT_JOINER)
    return spans


def char_span_to_time(
    source: NormalizedSource, start: int, end: int
) -> tuple[float | None, float | None] | None:
    """Map a `raw_text` char span back to (start_ts, end_ts) audio time via the
    overlapping segments. `None` when nothing overlaps (e.g. text source)."""
    overlapping = [seg for (s, e, seg) in segment_char_spans(source) if s < end and e > start]
    if not overlapping:
        return None
    return (overlapping[0].start_ts, overlapping[-1].end_ts)
