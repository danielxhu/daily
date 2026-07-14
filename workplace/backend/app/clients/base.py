"""External-client interfaces (X0.3).

Every call that would touch the network or a paid API in production goes through
one of these thin interfaces, so tests can substitute a mock / cassette and the
suite stays offline and zero-spend (NFR-3). The *real* implementations land with
their stages (DeepSeek → M1A.10, transcriber → M1A.6, VL → M8.3); this module
only defines the seam plus the result types those seams return.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


class TranscriptSegment(BaseModel):
    """One transcript segment with millisecond offsets. `words` holds optional
    word-level timestamps (whisperX-style forced alignment) for char-span ↔
    audio-time mapping (FR-8)."""

    text: str
    start_ms: int
    end_ms: int
    words: list[dict[str, Any]] = []


class TranscriptResult(BaseModel):
    language: str | None = None
    segments: list[TranscriptSegment] = []

    @property
    def text(self) -> str:
        return " ".join(seg.text for seg in self.segments).strip()


@runtime_checkable
class LLMClient(Protocol):
    """Text LLM (DeepSeek). JSON output mode; `escalate=True` selects the strong
    tier (`deepseek-v4-pro`) — used only on complexity / low confidence / parse
    failure (NFR-7). Returns a parsed JSON object; the real client validates with
    Pydantic downstream."""

    def complete_json(
        self, *, system: str, user: str, escalate: bool = False
    ) -> dict[str, Any]: ...


@runtime_checkable
class Transcriber(Protocol):
    """Local speech-to-text (faster-whisper). The real model is never loaded in
    tests — it is mocked (NFR-3)."""

    def transcribe(self, audio_path: str) -> TranscriptResult: ...


class FetchedPassage(BaseModel):
    """One candidate passage from a CASR authoritative fetch (FR-16) — pre-ranking,
    pre-stance. Just the retrieved text plus its provenance, so the caller can
    embedding-rank it to the claim, enforce the whitelist, and judge it with the
    existing NLI step. NOT a §7 contract type (internal client seam, like
    `RenderResult`); never independence credit by itself."""

    domain: str  # the source host; checked against the CASR whitelist by the caller
    url: str
    text: str


class VectorMatch(BaseModel):
    """One nearest-neighbour hit from the vector store. `score` is a similarity
    (higher = closer). NOT a §7 contract type (internal client seam)."""

    id: str
    score: float
    document: str
    metadata: dict[str, Any]


class RenderResult(BaseModel):
    """Output of a headless render (FR-2 tier-3 fallback)."""

    html: str
    final_url: str


@runtime_checkable
class RenderClient(Protocol):
    """Headless-render fallback (Playwright; real impl in M1B.2). Used only when
    static + structured HTML extraction is empty/too short. The real client runs
    with no user cookies, downloads disabled, isolated context, and a timeout
    (asserted in M1B.2). A browser is **never launched in tests** — this seam is
    mocked so render behavior is replayable offline (NFR-3)."""

    def render(self, url: str) -> RenderResult: ...
