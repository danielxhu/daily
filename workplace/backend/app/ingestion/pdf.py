"""Public text-PDF extraction (M1B.3, SSOT §FR-2 / §10).

A public PDF with a real **text layer** (filings, press releases, IR decks) →
text via `pypdf`, `extraction_method="pdf_text"`. A **scanned / image-only** PDF
has no text layer; we deliberately do NOT OCR it — a multi-page filing would blow
FR-10's ≤2-frame vision budget — so it is a typed `unsupported_file` skip and the
user pastes the text instead (§FR-2 / §6.6).

We do NOT bypass paywalls or login (§2.2): only already-public PDFs. `pypdf` is
imported lazily; tests feed raw fixture bytes (offline, NFR-3).
"""

from __future__ import annotations

import io
import uuid

from app.ingestion.domains import normalize_domain
from app.schemas.models import NormalizedSource

# Below this many characters across all pages, treat the PDF as having no usable
# text layer (scanned / image-only) → unsupported_file, never OCR'd.
MIN_PDF_TEXT_LEN = 40


class PdfParseError(RuntimeError):
    """The bytes start with `%PDF-` but pypdf could not parse them — a truncated /
    corrupt / encrypted PDF. Distinct from a scanned PDF (which parses but has no
    text layer); the caller typed-skips both, with different reasons."""


def extract_pdf_text(data: bytes) -> str | None:
    """Concatenated text-layer text of a PDF, or `None` when there is no usable
    text layer (a scanned / image-only PDF). Raises `PdfParseError` if pypdf
    cannot parse the bytes — never let a broken PDF crash the batch (FR-2)."""
    from pypdf import PdfReader  # lazy

    try:
        reader = PdfReader(io.BytesIO(data))
        parts = [t.strip() for page in reader.pages if (t := page.extract_text() or "").strip()]
    except Exception as exc:  # pypdf raises many (PdfStreamError/PdfReadError/…) — all → typed skip
        raise PdfParseError(str(exc)) from exc
    text = "\n\n".join(parts).strip()
    return text if len(text) >= MIN_PDF_TEXT_LEN else None


def is_pdf_bytes(data: bytes) -> bool:
    """Magic-byte check: a real PDF starts with `%PDF-` (don't trust extension /
    content-type alone, §FR-2)."""
    return data[:5] == b"%PDF-"


def build_pdf_source(url: str, text: str) -> NormalizedSource:
    return NormalizedSource(
        source_id=uuid.uuid4().hex,
        type="pdf",
        origin="user",
        url=url,
        domain=normalize_domain(url),
        raw_text=text,
        extraction_method="pdf_text",
        segments=[],
        frame_annotations=[],
    )
