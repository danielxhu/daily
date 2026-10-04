"""X0.3 — PDF fixture strategy.

Text-layer PDFs are represented by a real, valid fixture carrying known text, so
M1B.3 (`pypdf`/`pdfplumber` text extraction) has a deterministic input. Scanned /
image-only PDFs (no text layer) are NOT shipped as binaries here; per FR-2 they map
to a typed `unsupported_file` skip (taxonomy lands in M1A.1, extraction in M1B.3).
This test only asserts the fixture is a genuine text-layer PDF — extraction itself
is exercised in M1B.3.
"""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
KNOWN_TEXT = b"Total revenue was 1.2B"


def test_text_pdf_fixture_is_a_valid_text_layer_pdf() -> None:
    pdf = FIXTURES / "text_sample.pdf"
    assert pdf.exists(), "text-layer PDF fixture missing"
    data = pdf.read_bytes()
    assert data.startswith(b"%PDF-"), "not a PDF"
    assert data.rstrip().endswith(b"%%EOF"), "PDF not terminated"
    # The text lives literally in an uncompressed content stream → text-layer,
    # extractable downstream (M1B.3), unlike a scanned/image PDF.
    assert KNOWN_TEXT in data
