"""M1A.14 — per-source ingestion dispatcher routing.

Each `SourceRequest` reaches the right per-type ingester and comes back as a typed
`IngestionResult`. All network is injected/replayed (NFR-3): a fake httpx client
for audio, the M1A.4 HTML cassette, the M1A.7 caption cassette + ytdlp info
fixture, and a `MockTranscriber`."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import httpx

from app.clients.base import RenderResult
from app.clients.mock import MockRenderClient, MockTranscriber
from app.ingestion.html_static import build_client
from app.ingestion.ingest import ingest_one
from app.schemas.models import SourceRequest
from tests import fixtures_loader as fx
from tests.http_cassette import replay


class _FakeAudioClient:
    """Returns canned audio bytes for any GET (podcast download), no network."""

    def get(self, url: str) -> Any:
        return SimpleNamespace(content=b"FAKE_AUDIO_BYTES", raise_for_status=lambda: None)

    def close(self) -> None:
        pass


class _BoomTranscriber:
    """A transcriber whose model blows up (import/load/decode) at transcribe time."""

    def transcribe(self, audio_path: str) -> Any:
        raise RuntimeError("whisper exploded")


class _TimeoutRenderClient:
    """A RenderClient whose render times out / errors (no bypass attempted)."""

    def render(self, url: str) -> RenderResult:
        raise TimeoutError("navigation timeout")


class _FakeBytesClient:
    """Serves fixed bytes for any GET (offline PDF download routing)."""

    def __init__(self, content: bytes) -> None:
        self._content = content

    def get(self, url: str) -> Any:
        return SimpleNamespace(content=self._content, raise_for_status=lambda: None)

    def close(self) -> None:
        pass


class _FakeHtmlClient:
    """Serves a fixed HTML body + status for any GET, recording calls so a test
    can prove no bypass/retry/archive fetch happened."""

    def __init__(self, html: str, status_code: int = 200) -> None:
        self._html = html
        self._status = status_code
        self.calls: list[str] = []

    def get(self, url: str) -> Any:
        self.calls.append(url)
        return SimpleNamespace(
            text=self._html,
            status_code=self._status,
            raise_for_status=lambda: None,
            headers={"content-type": "text/html"},
        )

    def close(self) -> None:
        pass


def test_pasted_text_routes_to_text_ingester() -> None:
    result = ingest_one(SourceRequest(kind="text", text="Some pasted finance note."))
    assert result.status == "ok"
    assert result.source is not None
    assert result.source.type == "text"
    assert result.source.extraction_method == "pasted_text"


def test_apple_podcasts_page_is_typed_unsupported() -> None:
    result = ingest_one(SourceRequest(kind="url", url="https://podcasts.apple.com/us/podcast/x"))
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "unsupported_file"
    assert result.failure.next_action  # FR-2: a next step is shown


def test_webpage_routes_to_static_html() -> None:
    req = SourceRequest(kind="url", url="https://news.example.com/nvda")
    with replay("html_article.yaml"), build_client() as client:
        result = ingest_one(req, http_client=client)
    assert result.status == "ok"
    assert result.source is not None
    assert result.source.type == "webpage"
    assert result.source.extraction_method == "static_html"
    assert "$30.8B" in result.source.raw_text


def test_webpage_falls_through_to_structured_when_static_empty() -> None:
    # JS-only body → static (tier 1) empty → JSON-LD articleBody (tier 2) succeeds.
    html = fx.load_text("html/structured_jsonld.html")
    client = cast(httpx.Client, _FakeHtmlClient(html))
    req = SourceRequest(kind="url", url="https://news.example.com/fed")
    result = ingest_one(req, http_client=client)
    assert result.status == "ok"
    assert result.source is not None
    assert result.source.extraction_method == "structured_html"
    assert "Federal Reserve" in result.source.raw_text


def test_webpage_partial_blurb_falls_through_to_render() -> None:
    # An og:description blurb (partial) is NOT a body → fall through to render
    # (M1B.2), which here returns the real article DOM → rendered_html.
    html = fx.load_text("html/og_description_only.html")
    client = cast(httpx.Client, _FakeHtmlClient(html))
    rendered_dom = fx.load_text("html/static_article.html")  # canned rendered output
    req = SourceRequest(kind="url", url="https://news.example.com/wrap")
    result = ingest_one(req, http_client=client, render_client=MockRenderClient(rendered_dom))
    assert result.status == "ok"
    assert result.source is not None
    assert result.source.extraction_method == "rendered_html"
    assert "$30.8B" in result.source.raw_text


def test_render_failure_is_typed_js_render_failed() -> None:
    # A render exception (timeout / nav / launch) must typed-skip, never bubble or
    # attempt a bypass (M1B.2 guardrail).
    client = cast(httpx.Client, _FakeHtmlClient(fx.load_text("html/render_required.html")))
    req = SourceRequest(kind="url", url="https://spa.example.com/x")
    result = ingest_one(req, http_client=client, render_client=_TimeoutRenderClient())
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "js_render_failed"
    assert "render failed" in result.failure.reason


def test_render_empty_is_typed_parse_empty() -> None:
    # Render succeeds but the DOM still has no main content → parse_empty.
    client = cast(httpx.Client, _FakeHtmlClient(fx.load_text("html/render_required.html")))
    req = SourceRequest(kind="url", url="https://spa.example.com/x")
    rendered_empty = MockRenderClient(fx.load_text("html/empty_body.html"))
    result = ingest_one(req, http_client=client, render_client=rendered_empty)
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "parse_empty"


def test_text_pdf_routes_to_pdf_extraction() -> None:
    pdf = fx.fixture_path("text_sample.pdf").read_bytes()
    client = cast(httpx.Client, _FakeBytesClient(pdf))
    req = SourceRequest(kind="url", url="https://sec.example.com/filing.pdf")
    result = ingest_one(req, http_client=client)
    assert result.status == "ok"
    assert result.source is not None
    assert result.source.type == "pdf"
    assert result.source.extraction_method == "pdf_text"
    assert result.source.raw_text


def test_scanned_pdf_is_typed_unsupported() -> None:
    pdf = fx.fixture_path("scanned_sample.pdf").read_bytes()
    client = cast(httpx.Client, _FakeBytesClient(pdf))
    req = SourceRequest(kind="url", url="https://sec.example.com/scan.pdf")
    result = ingest_one(req, http_client=client)
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "unsupported_file"  # no OCR; paste the text
    assert result.failure.next_action


def test_cloudflare_page_is_anti_bot_and_not_bypassed() -> None:
    # A Cloudflare interstitial → anti_bot, and we fetch exactly once: no cookie /
    # proxy / archive retry to bypass it (M1B.4 guardrail).
    client = _FakeHtmlClient(fx.load_text("html/cloudflare_challenge.html"))
    req = SourceRequest(kind="url", url="https://news.example.com/blocked")
    result = ingest_one(req, http_client=cast(httpx.Client, client))
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "anti_bot"
    assert result.failure.next_action
    assert client.calls == ["https://news.example.com/blocked"]  # single fetch, no bypass


def test_paywall_page_is_typed_paywall() -> None:
    client = _FakeHtmlClient(fx.load_text("html/paywall_bloomberg.html"))
    req = SourceRequest(kind="url", url="https://markets.example.com/story")
    result = ingest_one(req, http_client=cast(httpx.Client, client))
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "paywall"


def test_login_wall_is_typed_login_required() -> None:
    client = _FakeHtmlClient(fx.load_text("html/login_wall.html"))
    req = SourceRequest(kind="url", url="https://members.example.com/x")
    result = ingest_one(req, http_client=cast(httpx.Client, client))
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "login_required"


def test_http_403_with_no_markers_is_fetch_blocked() -> None:
    client = _FakeHtmlClient("<html><body>Forbidden</body></html>", status_code=403)
    req = SourceRequest(kind="url", url="https://news.example.com/403")
    result = ingest_one(req, http_client=cast(httpx.Client, client))
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "fetch_blocked"


def test_malformed_pdf_is_typed_unsupported_not_crash() -> None:
    # bytes start with %PDF- but are corrupt → typed-skip, must not bubble (FR-2).
    client = cast(httpx.Client, _FakeBytesClient(b"%PDF-1.4\nnot actually a valid pdf"))
    req = SourceRequest(kind="url", url="https://sec.example.com/broken.pdf")
    result = ingest_one(req, http_client=client)
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "unsupported_file"
    assert "could not be parsed" in result.failure.reason
    assert result.failure.next_action


def test_direct_audio_routes_to_podcast_transcription() -> None:
    req = SourceRequest(kind="url", url="https://cdn.example.com/ep1.mp3")
    client = cast(httpx.Client, _FakeAudioClient())  # fake: only .get()/.close() used
    result = ingest_one(req, http_client=client, transcriber=MockTranscriber())
    assert result.status == "ok"
    assert result.source is not None
    assert result.source.type == "podcast"
    assert result.source.extraction_method == "whisper"
    assert result.source.raw_text  # transcript text present


def test_direct_audio_transcribe_failure_is_typed_transcribe_failed() -> None:
    # A model import/load/transcribe error must NOT bubble as a generic crash; it
    # is a transcription problem, not a fetch one (M1A.14 blocker 1).
    req = SourceRequest(kind="url", url="https://cdn.example.com/ep1.mp3")
    client = cast(httpx.Client, _FakeAudioClient())
    result = ingest_one(req, http_client=client, transcriber=_BoomTranscriber())
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "transcribe_failed"
    assert "whisper exploded" in result.failure.reason  # specific reason preserved
    assert result.failure.next_action


def test_direct_audio_leaves_no_temp_file(tmp_path: Any, monkeypatch: Any) -> None:
    # Both the success and the transcribe-failure paths must clean up the temp dir.
    import tempfile as _tempfile

    monkeypatch.setattr(_tempfile, "tempdir", str(tmp_path))
    req = SourceRequest(kind="url", url="https://cdn.example.com/ep1.mp3")
    client = cast(httpx.Client, _FakeAudioClient())

    ingest_one(req, http_client=client, transcriber=MockTranscriber())  # success
    ingest_one(req, http_client=client, transcriber=_BoomTranscriber())  # failure
    # no daily_pod_* temp dirs left behind
    assert not list(tmp_path.glob("daily_pod_*"))


def test_youtube_routes_to_caption_path() -> None:
    info = fx.load_json("captions/ytdlp_info.json")
    req = SourceRequest(kind="url", url="https://youtu.be/demo")
    with replay("caption_en.yaml"), build_client() as client:
        result = ingest_one(
            req,
            http_client=client,
            transcriber=MockTranscriber(),  # not used: captions present
            caption_extractor=lambda u: info,
        )
    assert result.status == "ok"
    assert result.source is not None
    assert result.source.type == "youtube"
    assert result.source.extraction_method == "caption"
    assert "record data-center revenue" in result.source.raw_text


# --- M14.5: a first check defers transcription (typed, re-queued — not a failure) --


def test_podcast_defers_when_transcription_disallowed() -> None:
    """`allow_transcription=False` (a first tracked check): audio ALWAYS needs
    whisper, so the item defers before any download — typed as delayed processing,
    and the transcriber is never touched."""
    req = SourceRequest(kind="url", url="https://cdn.example.com/ep1.mp3")
    client = cast(httpx.Client, _FakeAudioClient())
    result = ingest_one(
        req, http_client=client, transcriber=_BoomTranscriber(), allow_transcription=False
    )
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "transcription_deferred"
    assert "next check" in result.failure.reason
    assert result.failure.next_action == "No action needed — the next check transcribes this item."


def test_youtube_captions_still_process_when_transcription_disallowed() -> None:
    # the FAST caption path is exactly what a first check wants — never deferred
    info = fx.load_json("captions/ytdlp_info.json")
    req = SourceRequest(kind="url", url="https://youtu.be/demo")
    with replay("caption_en.yaml"), build_client() as client:
        result = ingest_one(
            req,
            http_client=client,
            transcriber=_BoomTranscriber(),  # would raise if the fallback ran
            caption_extractor=lambda u: info,
            allow_transcription=False,
        )
    assert result.status == "ok"
    assert result.source is not None and result.source.extraction_method == "caption"


def test_youtube_without_captions_defers_instead_of_whisper() -> None:
    def no_captions(_url: str) -> dict[str, Any]:
        raise RuntimeError("no caption track")

    req = SourceRequest(kind="url", url="https://youtu.be/demo")
    client = cast(httpx.Client, _FakeAudioClient())
    result = ingest_one(
        req,
        http_client=client,
        transcriber=_BoomTranscriber(),  # whisper must never run
        caption_extractor=no_captions,
        allow_transcription=False,
    )
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "transcription_deferred"
    assert result.failure.type == "youtube"
