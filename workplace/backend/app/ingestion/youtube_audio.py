"""YouTube audio fallback (M1A.8, SSOT §FR-2).

When a video has no usable caption track (M1A.7 → None), best-effort download the
audio with yt-dlp and reuse the local transcriber (M1A.6). yt-dlp is heavy +
network, so the downloader is lazy-imported and injectable for offline tests; the
download obeys the same X0.8 fetch policy as caption/metadata fetches. Failures are
typed, not fatal: download failure → `fetch_blocked`, transcription → `transcribe_failed`.
This is **best-effort** — V1 does not promise every caption-less video transcribes.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.clients.base import Transcriber, TranscriptResult
from app.ingestion import progress
from app.ingestion.fetch_policy import typed_skip
from app.ingestion.youtube import fetch_captions, yt_dlp_opts
from app.schemas.models import SourceFailure


def yt_dlp_audio_opts(out_dir: str) -> dict[str, object]:
    """Download opts = the X0.8-bound `yt_dlp_opts()` plus audio-download settings.
    Param names verified against yt-dlp's `YoutubeDL` source (format / outtmpl /
    paths / overwrites)."""
    opts = yt_dlp_opts()
    opts.update(
        {
            "skip_download": False,  # now we DO download (audio only)
            "format": "bestaudio/best",
            "outtmpl": "%(id)s.%(ext)s",
            "paths": {"home": out_dir},  # download into our controlled dir
            "overwrites": True,
            # proxy=""/cookiefile=None/usenetrc=False/geo_bypass=False/noplaylist
            # are inherited from yt_dlp_opts() — same red lines as M1A.7.
        }
    )
    return opts


def download_audio(
    url: str, out_dir: str, *, downloader: Callable[[str, str], str] | None = None
) -> str:
    """Download a video's audio → local file path. `downloader` is injectable so
    the offline suite never imports yt-dlp or hits the network."""
    if downloader is not None:
        return downloader(url, out_dir)
    from yt_dlp import YoutubeDL  # lazy: heavy + network

    def _hook(d: dict[str, Any]) -> None:  # live download progress (2026-07-21)
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                progress.update("downloading", float(d.get("downloaded_bytes", 0)) / float(total))

    opts = yt_dlp_audio_opts(out_dir)
    opts["progress_hooks"] = [_hook]
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return str(ydl.prepare_filename(info))


@dataclass(frozen=True)
class YoutubeIngest:
    transcript: TranscriptResult | None
    used: str | None  # "caption" | "audio"
    failure: SourceFailure | None


def ingest_youtube(
    url: str,
    *,
    client: httpx.Client,
    transcriber: Transcriber,
    extractor: Callable[[str], dict[str, Any]] | None = None,
    downloader: Callable[[str, str], str] | None = None,
    out_dir: str | None = None,
    allow_transcription: bool = True,
) -> YoutubeIngest:
    """Caption path first (M1A.7); on no captions, audio fallback (M1A.8). Failures
    are typed and never crash the batch. `allow_transcription=False` (M14.5): a
    first tracked check takes the fast caption path only — a caption-less video
    returns the typed `transcription_deferred` skip (delayed processing, not a
    failure) instead of minutes of download + local whisper."""
    # Caption path is itself a network path (yt-dlp metadata + caption HTTP fetch
    # + VTT parse); any error there must NOT crash the batch — capture it and fall
    # through to the audio fallback (best-effort, FR-2).
    caption_error: Exception | None = None
    try:
        caption = fetch_captions(url, client=client, extractor=extractor)
    except Exception as exc:
        caption, caption_error = None, exc
    if caption is not None:
        return YoutubeIngest(transcript=caption, used="caption", failure=None)

    prefix = f"caption path failed: {caption_error}; " if caption_error else "no captions; "
    if not allow_transcription:
        return YoutubeIngest(
            transcript=None,
            used=None,
            failure=typed_skip(
                "transcription_deferred",
                reason=f"{prefix}first check defers transcription; "
                "the next check processes this item",
                requested_url=url,
                source_type="youtube",
            ),
        )
    target_dir = out_dir or tempfile.mkdtemp(prefix="daily_yt_")
    # the audio path is the slow one — publish live progress for the UI's bar
    # (owner 2026-07-21); the slot ALWAYS empties, success or typed failure
    progress.begin(url)
    try:
        try:
            audio_path = download_audio(url, target_dir, downloader=downloader)
        except Exception as exc:  # best-effort: any download error → typed skip
            return YoutubeIngest(
                transcript=None,
                used=None,
                failure=typed_skip(
                    "fetch_blocked",
                    reason=f"{prefix}audio download failed: {exc}",
                    requested_url=url,
                    source_type="youtube",
                ),
            )
        progress.update("transcribing", 0.0)
        try:
            transcript = transcriber.transcribe(audio_path)
        except Exception as exc:  # best-effort: any transcription error → typed skip
            return YoutubeIngest(
                transcript=None,
                used=None,
                failure=typed_skip(
                    "transcribe_failed",
                    reason=f"{prefix}transcription failed: {exc}",
                    requested_url=url,
                    source_type="youtube",
                ),
            )
        return YoutubeIngest(transcript=transcript, used="audio", failure=None)
    finally:
        progress.finish()
