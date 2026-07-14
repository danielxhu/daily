"""M1A.8 — YouTube audio fallback: no captions → download audio → transcribe
(M1A.6); download/transcribe failures are typed-skips; opts obey the fetch policy."""

from __future__ import annotations

from typing import Any

import pytest

from app.clients.base import TranscriptResult, TranscriptSegment
from app.clients.mock import MockTranscriber
from app.ingestion.html_static import build_client
from app.ingestion.youtube_audio import (
    YoutubeIngest,
    ingest_youtube,
    yt_dlp_audio_opts,
)

_NO_CAPTIONS: dict[str, Any] = {"subtitles": {}, "automatic_captions": {}}
_HAS_CAPTION: dict[str, Any] = {
    "subtitles": {"en": [{"ext": "vtt", "url": "https://yt.example/cap/en.vtt"}]}
}


def test_audio_opts_obey_fetch_policy_and_download_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://evil.proxy:8080")
    opts = yt_dlp_audio_opts("/tmp/daily_dl")
    # inherited red lines
    assert opts["proxy"] == "" and opts["cookiefile"] is None
    assert opts["usenetrc"] is False and opts["geo_bypass"] is False
    assert opts["noplaylist"] is True
    assert opts["cookiesfrombrowser"] is None
    assert isinstance(opts["socket_timeout"], (int, float)) and opts["socket_timeout"] > 0
    # download settings
    assert opts["skip_download"] is False  # we download now
    assert opts["format"] == "bestaudio/best"
    assert opts["paths"] == {"home": "/tmp/daily_dl"}
    assert opts["outtmpl"] == "%(id)s.%(ext)s"
    assert opts["overwrites"] is True


def test_caption_present_skips_audio_download() -> None:
    def _boom(url: str, out_dir: str) -> str:
        raise AssertionError("must not download when captions exist")

    with build_client() as client:
        # caption path needs the VTT fetch; use a cassette
        from tests.http_cassette import replay

        with replay("caption_en.yaml"):
            out = ingest_youtube(
                "https://youtu.be/x",
                client=client,
                transcriber=MockTranscriber(),
                extractor=lambda u: _HAS_CAPTION,
                downloader=_boom,
            )
    assert isinstance(out, YoutubeIngest)
    assert out.used == "caption"
    assert out.transcript is not None and out.failure is None


def test_no_caption_falls_back_to_audio() -> None:
    fake_transcript = TranscriptResult(
        language="en",
        segments=[TranscriptSegment(text="from audio fallback.", start_ms=0, end_ms=1000)],
    )
    with build_client() as client:
        out = ingest_youtube(
            "https://youtu.be/x",
            client=client,
            transcriber=MockTranscriber(result=fake_transcript),
            extractor=lambda u: _NO_CAPTIONS,
            downloader=lambda url, out_dir: f"{out_dir}/x.m4a",
            out_dir="/tmp/daily_dl",
        )
    assert out.used == "audio"
    assert out.transcript is not None
    assert out.transcript.text == "from audio fallback."
    assert out.failure is None


def test_download_failure_is_fetch_blocked() -> None:
    def _fail(url: str, out_dir: str) -> str:
        raise RuntimeError("network down")

    with build_client() as client:
        out = ingest_youtube(
            "https://youtu.be/x",
            client=client,
            transcriber=MockTranscriber(),
            extractor=lambda u: _NO_CAPTIONS,
            downloader=_fail,
            out_dir="/tmp/daily_dl",
        )
    assert out.transcript is None and out.used is None
    assert out.failure is not None
    assert out.failure.kind == "fetch_blocked"
    assert out.failure.type == "youtube"
    assert out.failure.next_action


def test_caption_path_exception_does_not_crash_falls_back_to_audio() -> None:
    # caption path (yt-dlp metadata / HTTP) errors must not crash the batch
    def _boom_extractor(url: str) -> dict[str, Any]:
        raise RuntimeError("yt-dlp metadata failed")

    fake = TranscriptResult(
        language="en", segments=[TranscriptSegment(text="audio.", start_ms=0, end_ms=500)]
    )
    with build_client() as client:
        out = ingest_youtube(
            "https://youtu.be/x",
            client=client,
            transcriber=MockTranscriber(result=fake),
            extractor=_boom_extractor,
            downloader=lambda url, out_dir: f"{out_dir}/x.m4a",
            out_dir="/tmp/daily_dl",
        )
    assert out.used == "audio"  # recovered via fallback, no exception raised
    assert out.transcript is not None


def test_caption_and_audio_both_fail_reports_both() -> None:
    def _boom_extractor(url: str) -> dict[str, Any]:
        raise RuntimeError("metadata boom")

    def _boom_downloader(url: str, out_dir: str) -> str:
        raise RuntimeError("download boom")

    with build_client() as client:
        out = ingest_youtube(
            "https://youtu.be/x",
            client=client,
            transcriber=MockTranscriber(),
            extractor=_boom_extractor,
            downloader=_boom_downloader,
            out_dir="/tmp/daily_dl",
        )
    assert out.failure is not None and out.failure.kind == "fetch_blocked"
    assert "caption path failed" in out.failure.reason
    assert "audio download failed" in out.failure.reason


def test_transcribe_failure_is_transcribe_failed() -> None:
    class _BoomTranscriber:
        def transcribe(self, audio_path: str) -> TranscriptResult:
            raise RuntimeError("whisper exploded")

    with build_client() as client:
        out = ingest_youtube(
            "https://youtu.be/x",
            client=client,
            transcriber=_BoomTranscriber(),
            extractor=lambda u: _NO_CAPTIONS,
            downloader=lambda url, out_dir: f"{out_dir}/x.m4a",
            out_dir="/tmp/daily_dl",
        )
    assert out.transcript is None
    assert out.failure is not None and out.failure.kind == "transcribe_failed"
