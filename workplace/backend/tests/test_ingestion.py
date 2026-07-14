"""M1B.5 — URL robustness pack.

One consolidated, offline regression surface for "paste a URL": short links,
AMP/mobile canonicalization, mislabeled content-type, PDF, JS render, paywall,
scanned PDF, and webpage timeout. Per-component behaviour is unit-tested in
test_router / test_html_* / test_pdf / test_hostile; this pins the end-to-end
contract so URL handling regresses together. No bypass of hostile sources."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import httpx

from app.clients.mock import MockRenderClient
from app.ingestion.ingest import ingest_one
from app.ingestion.router import normalize_url, resolve_url, route
from app.schemas.models import SourceRequest
from tests import fixtures_loader as fx


class _FakeClient:
    """One injectable httpx stand-in: serves text/bytes/status, or raises, and
    records GETs so a test can prove there was no bypass/retry."""

    def __init__(
        self,
        *,
        text: str = "",
        content: bytes = b"",
        status_code: int = 200,
        raise_exc: Exception | None = None,
    ) -> None:
        self._text = text
        self._content = content
        self._status = status_code
        self._raise = raise_exc
        self.calls: list[str] = []

    def get(self, url: str) -> Any:
        self.calls.append(url)
        if self._raise is not None:
            raise self._raise
        return SimpleNamespace(
            text=self._text,
            content=self._content,
            status_code=self._status,
            raise_for_status=lambda: None,
            headers={"content-type": "text/html"},
        )

    def close(self) -> None:
        pass


def _client(**kw: Any) -> httpx.Client:
    return cast(httpx.Client, _FakeClient(**kw))


# --- URL normalization / redirect / content-type sniffing (router anchors) ----


def test_short_link_redirect_resolves_then_normalizes() -> None:
    final = resolve_url("https://bit.ly/xyz", lambda u: "https://www.example.com/a?utm_source=s")
    assert final == "https://www.example.com/a"  # redirect followed, tracking stripped


def test_amp_and_mobile_hosts_and_paths_canonicalize() -> None:
    assert normalize_url("https://amp.example.com/news/story/amp?utm_source=t&id=9#f") == (
        "https://example.com/news/story?id=9"
    )
    assert normalize_url("https://m.example.com/news/story?utm_campaign=x") == (
        "https://example.com/news/story"
    )


def test_mislabeled_content_type_is_sniffed_by_magic_bytes() -> None:
    # servers lie in Content-Type → magic bytes win
    url = "https://x.example/a"
    octet = "application/octet-stream"
    assert route(url, head=b"<html>", declared_content_type=octet).kind == "html"
    assert route(url, head=b"ID3\x03audio", declared_content_type="text/html").kind == "audio"


# --- end-to-end dispatcher outcomes per content type --------------------------


def test_amp_url_ingests_with_canonicalized_source_url() -> None:
    req = SourceRequest(kind="url", url="https://amp.example.com/article/amp?utm_source=x")
    result = ingest_one(req, http_client=_client(text=fx.load_text("html/static_article.html")))
    assert result.status == "ok"
    assert result.source is not None
    assert result.source.url == "https://example.com/article"  # normalized end-to-end
    assert result.source.extraction_method == "static_html"


def test_pdf_url_extracts_text_layer() -> None:
    req = SourceRequest(kind="url", url="https://sec.example.com/filing.pdf")
    pdf = fx.fixture_path("text_sample.pdf").read_bytes()
    result = ingest_one(req, http_client=_client(content=pdf))
    assert result.status == "ok"
    assert result.source is not None and result.source.extraction_method == "pdf_text"


def test_scanned_pdf_url_is_unsupported() -> None:
    req = SourceRequest(kind="url", url="https://sec.example.com/scan.pdf")
    pdf = fx.fixture_path("scanned_sample.pdf").read_bytes()
    result = ingest_one(req, http_client=_client(content=pdf))
    assert result.status == "failed"
    assert result.failure is not None and result.failure.kind == "unsupported_file"


def test_js_heavy_page_uses_render_fallback() -> None:
    req = SourceRequest(kind="url", url="https://spa.example.com/x")
    result = ingest_one(
        req,
        http_client=_client(text=fx.load_text("html/render_required.html")),
        render_client=MockRenderClient(fx.load_text("html/static_article.html")),
    )
    assert result.status == "ok"
    assert result.source is not None and result.source.extraction_method == "rendered_html"


def test_paywall_url_is_typed_and_not_bypassed() -> None:
    client = _FakeClient(text=fx.load_text("html/paywall_bloomberg.html"))
    req = SourceRequest(kind="url", url="https://markets.example.com/story")
    result = ingest_one(req, http_client=cast(httpx.Client, client))
    assert result.status == "failed"
    assert result.failure is not None and result.failure.kind == "paywall"
    assert len(client.calls) == 1  # single fetch — no bypass


def test_webpage_timeout_is_typed_timeout() -> None:
    # M1B.4 follow-up: pin httpx.TimeoutException → timeout end-to-end.
    req = SourceRequest(kind="url", url="https://slow.example.com/x")
    result = ingest_one(req, http_client=_client(raise_exc=httpx.TimeoutException("timed out")))
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.kind == "timeout"
