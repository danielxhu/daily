"""M1A.9 — source normalization: transcripts → NormalizedSource; char-offset
back-mapping to audio time; all source types converge to one shape."""

from __future__ import annotations

from app.clients.base import TranscriptResult, TranscriptSegment
from app.ingestion.normalize import (
    SEGMENT_JOINER,
    char_span_to_time,
    normalize_transcript,
    segment_char_spans,
)
from app.ingestion.text_source import ingest_text
from app.schemas.models import NormalizedSource, SourceRequest


def _transcript() -> TranscriptResult:
    return TranscriptResult(
        language="en",
        segments=[
            TranscriptSegment(
                text="NVIDIA posted record revenue.",
                start_ms=0,
                end_ms=2500,
                words=[{"text": "NVIDIA", "start_ms": 0, "end_ms": 500}],
            ),
            TranscriptSegment(text="Demand stayed strong.", start_ms=2500, end_ms=4000),
        ],
    )


def test_transcript_becomes_normalized_source() -> None:
    src = normalize_transcript(
        _transcript(),
        source_id="p1",
        type="podcast",
        extraction_method="whisper",
        url="https://cdn.example.com/ep1.mp3",
        domain="example.com",
    )
    assert src.extraction_method == "whisper"
    assert src.type == "podcast"
    assert src.tier == "T2"  # default until tiering (M3.6)
    assert len(src.segments) == 2
    # second timestamps from ms
    assert src.segments[0].start_ts == 0.0 and src.segments[0].end_ts == 2.5
    # raw_text is the canonical join
    assert (
        src.raw_text == "NVIDIA posted record revenue." + SEGMENT_JOINER + "Demand stayed strong."
    )
    # word timestamps carried through (whisper); cue-only segs have none
    assert src.segments[0].words[0]["text"] == "NVIDIA"
    assert src.segments[1].words == []


def test_domain_derived_from_url_when_not_given() -> None:
    # a normal podcast/YouTube URL must set a domain, else FR-7 would drop it from K/N
    src = normalize_transcript(
        _transcript(),
        source_id="p1",
        type="podcast",
        extraction_method="whisper",
        url="https://cdn.example.com/ep1.mp3",
    )
    assert src.domain == "cdn.example.com"


def test_explicit_domain_is_normalized_and_wins() -> None:
    src = normalize_transcript(
        _transcript(),
        source_id="p1",
        type="podcast",
        extraction_method="whisper",
        url="https://cdn.example.com/ep1.mp3",
        domain="https://www.Reuters.com/x",
    )
    assert src.domain == "reuters.com"  # explicit declared domain, normalized


def test_youtube_url_sets_domain() -> None:
    src = normalize_transcript(
        _transcript(),
        source_id="y1",
        type="youtube",
        extraction_method="caption",
        url="https://youtu.be/abc",
    )
    assert src.domain == "youtu.be"


def test_no_url_no_domain_stays_none() -> None:
    src = normalize_transcript(
        _transcript(), source_id="p1", type="podcast", extraction_method="whisper"
    )
    assert src.domain is None


def test_char_span_round_maps_to_segment_time() -> None:
    # offset back-mapping (FR-8): a char span in raw_text → its segment's audio time
    src = normalize_transcript(
        _transcript(), source_id="p1", type="podcast", extraction_method="whisper"
    )
    raw = src.raw_text
    start = raw.index("record revenue")
    end = start + len("record revenue")
    assert char_span_to_time(src, start, end) == (0.0, 2.5)  # within segment 0

    # a span in the second segment maps to its later time
    s2 = raw.index("Demand")
    assert char_span_to_time(src, s2, s2 + len("Demand")) == (2.5, 4.0)


def test_segment_char_spans_are_contiguous() -> None:
    src = normalize_transcript(
        _transcript(), source_id="p1", type="youtube", extraction_method="caption"
    )
    spans = segment_char_spans(src)
    # each span slices raw_text back to the segment text
    for s, e, seg in spans:
        assert src.raw_text[s:e] == seg.text


def test_text_source_has_no_segment_time() -> None:
    src = ingest_text(SourceRequest(kind="text", text="pasted body"))
    assert char_span_to_time(src, 0, 5) is None  # no segments → no audio time


def test_all_source_types_share_one_shape() -> None:
    # webpage (constructed like M1A.4 output), pasted text, podcast, youtube
    webpage = NormalizedSource(
        source_id="w1",
        type="webpage",
        url="https://news.example.com/x",
        domain="news.example.com",
        raw_text="article body",
        extraction_method="static_html",
        segments=[],
        frame_annotations=[],
    )
    pasted = ingest_text(SourceRequest(kind="text", text="pasted"))
    podcast = normalize_transcript(
        _transcript(),
        source_id="p1",
        type="podcast",
        extraction_method="whisper",
        url="https://cdn.example.com/ep1.mp3",
    )
    youtube = normalize_transcript(
        _transcript(),
        source_id="y1",
        type="youtube",
        extraction_method="caption",
        url="https://youtu.be/abc",
    )
    for src in (webpage, pasted, podcast, youtube):
        assert isinstance(src, NormalizedSource)
        assert src.extraction_method is not None
        assert src.tier == "T2"
        assert src.origin == "user"
    # URL-bearing sources resolve a domain (counts toward K/N); pasted text doesn't
    assert webpage.domain == "news.example.com"
    assert podcast.domain == "cdn.example.com"
    assert youtube.domain == "youtu.be"
    assert pasted.domain is None
