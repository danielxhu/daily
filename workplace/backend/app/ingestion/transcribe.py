"""Local transcription adapter (M1A.6, SSOT §10).

A `faster-whisper` implementation of the X0.3 `Transcriber` interface, producing
`TranscriptResult` segments with **word-level timestamps** (whisperX-style forced
alignment) so a claim can later map to char-span + audio time + vision frame (FR-8).

`faster-whisper` is heavy and downloads models, so it is **lazy-imported and the
model is loaded only on first `transcribe()`** — never at import, never in the
offline suite. Tests inject a fake model loader, so the real model is never built
(NFR-3). A real model is never loaded in CI (§9.2).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from app.clients.base import TranscriptResult, TranscriptSegment
from app.core.config import get_settings


def _ms(seconds: float) -> int:
    return int(round(seconds * 1000))


def _to_transcript(segments: Iterable[Any], language: str | None) -> TranscriptResult:
    """Map faster-whisper segments/words → `TranscriptResult` (ms timestamps)."""
    out: list[TranscriptSegment] = []
    for seg in segments:
        words = [
            {"text": w.word, "start_ms": _ms(w.start), "end_ms": _ms(w.end)}
            for w in (getattr(seg, "words", None) or [])
        ]
        out.append(
            TranscriptSegment(
                text=seg.text.strip(),
                start_ms=_ms(seg.start),
                end_ms=_ms(seg.end),
                words=words,
            )
        )
    return TranscriptResult(language=language, segments=out)


class FasterWhisperTranscriber:
    """Lazy faster-whisper adapter. Satisfies the X0.3 `Transcriber` Protocol."""

    def __init__(
        self,
        *,
        model_size: str | None = None,
        compute_type: str | None = None,
        model_loader: Callable[[], Any] | None = None,
    ) -> None:
        settings = get_settings()
        self._model_size = model_size or settings.whisper_model_size
        self._compute_type = compute_type or settings.whisper_compute_type
        self._model_loader = model_loader  # injectable for tests
        self._model: Any | None = None  # lazy

    def _load_model(self) -> Any:
        # Imported here, not at module top, so importing this module never pulls
        # faster-whisper and the offline suite stays light.
        from faster_whisper import WhisperModel

        return WhisperModel(self._model_size, compute_type=self._compute_type)

    def _get_model(self) -> Any:
        if self._model is None:
            self._model = (self._model_loader or self._load_model)()
        return self._model

    def transcribe(self, audio_path: str) -> TranscriptResult:
        model = self._get_model()
        segments, info = model.transcribe(audio_path, word_timestamps=True)
        return _to_transcript(segments, getattr(info, "language", None))


def get_transcriber() -> FasterWhisperTranscriber:
    """Factory for the real transcriber (monkeypatched to a mock in tests)."""
    return FasterWhisperTranscriber()
