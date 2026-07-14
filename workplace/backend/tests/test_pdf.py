"""M1B.3 — public text-PDF extraction.

A PDF with a text layer → text (`pdf_text`); a scanned / image-only PDF (no text
layer) → `None`, so the caller typed-skips it as `unsupported_file` rather than
OCR'ing a multi-page filing (FR-2 / FR-10)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.pdf import (
    PdfParseError,
    build_pdf_source,
    extract_pdf_text,
    is_pdf_bytes,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _pdf_bytes(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def test_text_layer_pdf_extracts_text() -> None:
    text = extract_pdf_text(_pdf_bytes("text_sample.pdf"))
    assert text is not None
    assert "FY2025" in text or "revenue" in text.lower()


def test_scanned_pdf_has_no_text_layer() -> None:
    # no text layer → None → caller will typed-skip as unsupported_file (not OCR'd)
    assert extract_pdf_text(_pdf_bytes("scanned_sample.pdf")) is None


def test_malformed_pdf_raises_parse_error() -> None:
    # %PDF- header but structurally broken (truncated/corrupt) → typed error, not crash
    with pytest.raises(PdfParseError):
        extract_pdf_text(b"%PDF-1.4\nnot actually a valid pdf")


def test_is_pdf_bytes_checks_magic() -> None:
    assert is_pdf_bytes(_pdf_bytes("text_sample.pdf")) is True
    assert is_pdf_bytes(b"<html>not a pdf</html>") is False


def test_build_pdf_source_shape() -> None:
    source = build_pdf_source("https://sec.example.com/filing.pdf", "Some filing text.")
    assert source.type == "pdf"
    assert source.extraction_method == "pdf_text"
    assert source.domain == "sec.example.com"
    assert source.raw_text == "Some filing text."
