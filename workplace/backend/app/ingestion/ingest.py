"""Per-source ingestion dispatcher (M1A.14, SSOT §FR-1 / FR-2).

`ingest_one` turns one `SourceRequest` into one `IngestionResult` by routing to
the per-type ingesters built earlier in Stage 1A (text M1A.2, static HTML M1A.4,
podcast M1A.5/6, YouTube M1A.7/8) and normalizing transcripts to a
`NormalizedSource` (M1A.9). Known problems come back as a typed `SourceFailure`
with a next step (FR-2); the batch orchestrator (`app.run`) catches anything
unexpected so one bad source never crashes the run.

Routing (Stage 1A; structured/render HTML fallbacks + PDF are Stage 1B):
- `kind="text"`            → pasted text
- YouTube URL             → captions, then audio fallback
- Apple/Spotify page      → unsupported (paste text / use RSS)
- direct audio / `declared_type="podcast"` → audio (direct URL or RSS enclosure)
- everything else         → static HTML

Network deps are injectable so the offline suite never fetches or imports heavy
libs (NFR-3): an `httpx` client, a `Transcriber`, the YouTube caption `extractor`
and audio `downloader`.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from app.clients.base import RenderClient, Transcriber, VisionClient
from app.ingestion.hostile import classify_hostile
from app.ingestion.html_render import render_main_text
from app.ingestion.html_static import (
    build_client,
    build_webpage_source,
    extract_main_text,
)
from app.ingestion.html_structured import extract_structured
from app.ingestion.normalize import normalize_transcript
from app.ingestion.pdf import PdfParseError, build_pdf_source, extract_pdf_text, is_pdf_bytes
from app.ingestion.podcast import is_direct_audio_url, is_unsupported_podcast_page, resolve_audio
from app.ingestion.result import failed_from, failed_result, ok_result
from app.ingestion.router import is_video_platform, is_xiaohongshu_note, normalize_url
from app.ingestion.text_source import ingest_text
from app.ingestion.xiaohongshu import fetch_note, read_note_images
from app.ingestion.youtube_audio import ingest_youtube
from app.schemas.models import (
    ExtractionMethod,
    IngestionResult,
    SourceFailureKind,
    SourceRequest,
)


def _get_transcriber(transcriber: Transcriber | None) -> Transcriber:
    if transcriber is not None:
        return transcriber
    from app.ingestion.transcribe import FasterWhisperTranscriber  # heavy: lazy

    return FasterWhisperTranscriber()


def _download_audio(audio_url: str, *, out_dir: str, client: httpx.Client) -> str:
    """Fetch a direct audio URL into `out_dir` for local transcription. The caller
    owns `out_dir` (a `TemporaryDirectory`) so the file is always cleaned up."""
    resp = client.get(audio_url)
    resp.raise_for_status()
    suffix = Path(urlsplit(audio_url).path).suffix or ".audio"
    path = os.path.join(out_dir, f"audio{suffix}")
    Path(path).write_bytes(resp.content)
    return path


# the injectable per-source ingestion seam (tests pass fakes; NFR-3)
IngestFn = Callable[[SourceRequest], IngestionResult]


def ingest_one(
    req: SourceRequest,
    *,
    http_client: httpx.Client | None = None,
    transcriber: Transcriber | None = None,
    caption_extractor: Callable[[str], dict[str, Any]] | None = None,
    audio_downloader: Callable[[str, str], str] | None = None,
    render_client: RenderClient | None = None,
    vision_client: VisionClient | None = None,
    allow_transcription: bool = True,
) -> IngestionResult:
    """Ingest one source. Returns a typed `IngestionResult` (ok or failed).

    `allow_transcription=False` (M14.5): the caller is a FIRST tracked check and
    wants a fast answer — anything that would need local whisper (podcast audio, a
    caption-less video) returns the typed `transcription_deferred` skip instead of
    minutes of transcription. The fast caption path still runs. The poll runtime
    re-queues deferred items so the NEXT check processes them normally."""
    if req.kind == "text":
        return ok_result(req, ingest_text(req))

    assert req.url is not None  # SourceRequest validator guarantees url iff kind=="url"
    url = normalize_url(req.url)
    created_client = http_client is None
    client = http_client or build_client()
    try:
        if is_xiaohongshu_note(url):
            # Peek at the page before committing to yt-dlp (owner 2026-07-23):
            # an image/text note has no video — yt-dlp fails deterministically —
            # but its body is embedded in the page HTML, and most of the note's
            # information sits in its text screenshots, which the local OCR
            # reads for free. Video notes and any fetch/parse miss fall through
            # to the yt-dlp path unchanged.
            note = fetch_note(url, client=client)
            if note is not None and not note.is_video:
                vision = vision_client if vision_client is not None else _default_vision()
                image_text = read_note_images(note.image_urls, client=client, vision=vision)
                parts = [p for p in (note.title, note.desc, image_text) if p]
                if parts:
                    method: ExtractionMethod = "frame_ocr" if image_text else "structured_html"
                    return ok_result(req, build_webpage_source(url, "\n\n".join(parts), method))
                return failed_from(
                    req,
                    "parse_empty",
                    reason="Xiaohongshu image note has no text body and no readable image text.",
                    requested_url=url,
                    source_type="webpage",
                )
        if is_video_platform(url):
            return _ingest_youtube(
                req,
                url,
                client,
                transcriber,
                caption_extractor,
                audio_downloader,
                allow_transcription=allow_transcription,
            )
        if is_unsupported_podcast_page(url):
            # resolve_audio returns the typed unsupported failure for these pages.
            return failed_result(req, _require_failure(resolve_audio(url).failure))
        if is_direct_audio_url(url) or req.declared_type == "podcast":
            if not allow_transcription:  # audio ALWAYS needs whisper — defer whole item
                return _audio_fail(
                    req,
                    url,
                    "transcription_deferred",
                    "first check defers transcription; the next check processes this item",
                )
            return _ingest_podcast(req, url, client, transcriber)
        if _looks_like_pdf(url) or req.declared_type == "pdf":
            return _ingest_pdf(req, url, client)
        return _ingest_webpage(req, url, client, render_client)
    finally:
        if created_client:
            client.close()


def _ingest_webpage(
    req: SourceRequest, url: str, client: httpx.Client, render_client: RenderClient | None
) -> IngestionResult:
    # One fetch drives everything. First classify hostility (M1B.4): a
    # paywall / login / anti-bot / blocked response is a typed skip — we NEVER
    # bypass it (no cookies/proxy/archive, §2.2); the user pastes the text. A
    # clean response then runs the FR-2 HTML tier chain: tier 1 static
    # main-content (M1A.4); tier 2 structured metadata (M1B.1, JSON-LD body =
    # success, a bare og/meta blurb = partial, which does NOT count); tier 3
    # headless render (M1B.2), reached only when static is empty AND structured is
    # not `ok` (so a partial blurb still falls through to render).
    try:
        resp = client.get(url)
    except httpx.TimeoutException as exc:
        return _webpage_fail(req, url, "timeout", f"webpage fetch timed out: {exc}")
    except httpx.RequestError as exc:  # DNS / connection / transport — not a bypass target
        return _webpage_fail(req, url, "fetch_blocked", f"webpage fetch failed: {exc}")

    hostile = classify_hostile(status_code=resp.status_code, body=resp.text)
    if hostile is not None:
        return _webpage_fail(
            req, url, hostile, f"hostile source ({hostile}); not bypassed — paste the text."
        )

    html = resp.text
    text = extract_main_text(html)
    if text is not None:
        return ok_result(req, build_webpage_source(url, text, "static_html"))

    structured = extract_structured(html)
    if structured.status == "ok" and structured.text is not None:
        return ok_result(req, build_webpage_source(url, structured.text, "structured_html"))

    rc = render_client if render_client is not None else _default_render_client()
    try:
        rendered = render_main_text(url, render_client=rc)
    except Exception as exc:  # render timeout / nav / launch error → typed-skip
        return failed_from(
            req,
            "js_render_failed",
            reason=f"headless render failed: {exc}",
            requested_url=url,
            source_type="webpage",
        )
    if rendered is not None:
        return ok_result(req, build_webpage_source(url, rendered, "rendered_html"))

    return failed_from(
        req,
        "parse_empty",
        reason="Static, structured, and rendered HTML extraction were all empty or too short.",
        requested_url=url,
        source_type="webpage",
    )


def _webpage_fail(
    req: SourceRequest, url: str, kind: SourceFailureKind, reason: str
) -> IngestionResult:
    return failed_from(req, kind, reason=reason, requested_url=url, source_type="webpage")


def _default_render_client() -> RenderClient:
    from app.ingestion.html_render import PlaywrightRenderClient  # lazy: bundles a browser

    return PlaywrightRenderClient()


def _default_vision() -> VisionClient | None:
    from app.ingestion.ocr import get_vision_client  # lazy: pyobjc probe

    return get_vision_client()


def _looks_like_pdf(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(".pdf")


def _ingest_pdf(req: SourceRequest, url: str, client: httpx.Client) -> IngestionResult:
    # Public PDFs only (no paywall/login bypass, §2.2). Text layer → pdf_text;
    # scanned/image-only (no text layer) → unsupported_file, never OCR'd (M1B.3).
    try:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.content
    except httpx.TimeoutException as exc:
        return failed_from(
            req,
            "timeout",
            reason=f"PDF download timed out: {exc}",
            requested_url=url,
            source_type="pdf",
        )
    except Exception as exc:
        return failed_from(
            req,
            "fetch_blocked",
            reason=f"PDF download failed: {exc}",
            requested_url=url,
            source_type="pdf",
        )
    if not is_pdf_bytes(data):
        return failed_from(
            req,
            "unsupported_file",
            reason="URL did not return a PDF (no %PDF- header).",
            requested_url=url,
            source_type="pdf",
        )
    try:
        text = extract_pdf_text(data)
    except PdfParseError as exc:  # truncated / corrupt / encrypted → typed-skip, no crash
        return failed_from(
            req,
            "unsupported_file",
            reason=f"PDF could not be parsed (truncated/corrupt/encrypted): {exc}",
            requested_url=url,
            source_type="pdf",
        )
    if text is None:
        return failed_from(
            req,
            "unsupported_file",
            reason="Scanned / image-only PDF has no text layer; it is not OCR'd — paste the text.",
            requested_url=url,
            source_type="pdf",
        )
    return ok_result(req, build_pdf_source(url, text))


def _ingest_podcast(
    req: SourceRequest, url: str, client: httpx.Client, transcriber: Transcriber | None
) -> IngestionResult:
    if is_direct_audio_url(url):
        resolution = resolve_audio(url)
    else:  # treat as an RSS feed URL → first audio enclosure
        try:
            feed_text = client.get(url).text
        except httpx.TimeoutException as exc:
            return _audio_fail(req, url, "timeout", f"feed fetch timed out: {exc}")
        except Exception as exc:
            return _audio_fail(req, url, "fetch_blocked", f"feed fetch failed: {exc}")
        resolution = resolve_audio(url, feed_text=feed_text)
    if resolution.failure is not None:
        return failed_result(req, resolution.failure)
    assert resolution.audio_url is not None

    # TemporaryDirectory cleans up the downloaded audio on every path (success,
    # download failure, transcription failure) — no temp leak (M1A.14).
    with tempfile.TemporaryDirectory(prefix="daily_pod_") as tmp:
        try:
            audio_path = _download_audio(resolution.audio_url, out_dir=tmp, client=client)
        except httpx.TimeoutException as exc:
            return _audio_fail(req, url, "timeout", f"audio download timed out: {exc}")
        except Exception as exc:  # HTTP / status / IO → a fetch problem, not a model one
            return _audio_fail(req, url, "fetch_blocked", f"audio download failed: {exc}")
        try:
            # import / model-load / decode errors all surface here → transcribe_failed
            transcript = _get_transcriber(transcriber).transcribe(audio_path)
        except Exception as exc:
            return _audio_fail(req, url, "transcribe_failed", f"transcription failed: {exc}")

    source = normalize_transcript(
        transcript,
        source_id=uuid4().hex,
        type="podcast",
        extraction_method="whisper",
        url=url,
    )
    return ok_result(req, source)


def _audio_fail(
    req: SourceRequest, url: str, kind: SourceFailureKind, reason: str
) -> IngestionResult:
    return failed_from(req, kind, reason=reason, requested_url=url, source_type="podcast")


def _ingest_youtube(
    req: SourceRequest,
    url: str,
    client: httpx.Client,
    transcriber: Transcriber | None,
    caption_extractor: Callable[[str], dict[str, Any]] | None,
    audio_downloader: Callable[[str, str], str] | None,
    *,
    allow_transcription: bool = True,
) -> IngestionResult:
    # Give the audio fallback a controlled tempdir so a downloaded file never
    # leaks (M1A.8 left cleanup to the orchestrator). On the caption path nothing
    # is written here. ingest_youtube already types its own download/transcribe
    # failures (fetch_blocked / transcribe_failed) and — M14.5 — the
    # transcription_deferred skip when a first check disallows the whisper fallback.
    with tempfile.TemporaryDirectory(prefix="daily_yt_") as tmp:
        yt = ingest_youtube(
            url,
            client=client,
            transcriber=_get_transcriber(transcriber),
            extractor=caption_extractor,
            downloader=audio_downloader,
            out_dir=tmp,
            allow_transcription=allow_transcription,
        )
    if yt.failure is not None:
        return failed_result(req, yt.failure)
    assert yt.transcript is not None
    method: ExtractionMethod = "caption" if yt.used == "caption" else "whisper"
    source = normalize_transcript(
        yt.transcript,
        source_id=uuid4().hex,
        type="youtube",
        extraction_method=method,
        url=url,
    )
    return ok_result(req, source)


def _require_failure(failure: Any) -> Any:
    # Narrowing helper: these branches only run when a failure is guaranteed set.
    assert failure is not None
    return failure
