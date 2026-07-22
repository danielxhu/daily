"""Local transcription adapter (M1A.6, SSOT §10).

A `faster-whisper` implementation of the X0.3 `Transcriber` interface. Since the
verification engine left (2026-07-13) nothing consumes word-level timestamps, so
they are OFF; the transcript feeds the item excerpt + bilingual summary only.

Speed (owner 2026-07-20 "为什么这三个还是这么慢"): long caption-less videos
(hours of forum replay) used to be transcribed sequentially, window by window.
We now run faster-whisper's `BatchedInferencePipeline` — VAD splits the audio at
silence, segments are batched through the model, non-speech (music/applause) is
skipped — with `cpu_threads` pinned to the performance cores. Same model, same
output shape, several times faster on long audio.

`faster-whisper` is heavy and downloads models, so it is **lazy-imported and the
model is loaded only on first `transcribe()`** — never at import, never in the
offline suite. Tests inject a fake model loader, so the real model is never built
(NFR-3). A real model is never loaded in CI (§9.2).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from app.clients.base import Transcriber, TranscriptResult, TranscriptSegment
from app.core.config import get_settings
from app.ingestion import progress

# segments batched through the model per step — 8 is the faster-whisper default
# sweet spot on CPU; raising it mostly raises memory, not speed
_BATCH_SIZE = 8


def _ms(seconds: float) -> int:
    return int(round(seconds * 1000))


def _to_transcript(
    segments: Iterable[Any], language: str | None, *, duration_s: float = 0.0
) -> TranscriptResult:
    """Map faster-whisper segments/words → `TranscriptResult` (ms timestamps).
    Segments stream in order, so seg.end / duration is live progress (2026-07-21)."""
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
        if duration_s > 0:
            progress.update("transcribing", float(seg.end) / duration_s)
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
        self._cpu_threads = settings.whisper_cpu_threads
        self._model_loader = model_loader  # injectable for tests
        self._model: Any | None = None  # lazy

    def _load_model(self) -> Any:
        # Imported here, not at module top, so importing this module never pulls
        # faster-whisper and the offline suite stays light.
        from faster_whisper import BatchedInferencePipeline, WhisperModel

        model = WhisperModel(
            self._model_size,
            compute_type=self._compute_type,
            cpu_threads=self._cpu_threads,
        )
        return BatchedInferencePipeline(model)

    def _get_model(self) -> Any:
        if self._model is None:
            self._model = (self._model_loader or self._load_model)()
        return self._model

    def transcribe(self, audio_path: str) -> TranscriptResult:
        model = self._get_model()
        # VAD is what makes batching possible (and skips silence/music); word
        # timestamps stay off — nothing consumes them since the engine removal
        segments, info = model.transcribe(audio_path, batch_size=_BATCH_SIZE, vad_filter=True)
        return _to_transcript(
            segments,
            getattr(info, "language", None),
            duration_s=float(getattr(info, "duration", 0.0) or 0.0),
        )


class MlxWhisperTranscriber:
    """Apple-GPU whisper via mlx-whisper + large-v3-turbo (owner 2026-07-22).

    Runs the model on the M-chip GPU (Metal): measured 5.7x realtime on real
    forum speech vs 2.3x for the batched CPU path — a 3h video in ~half an
    hour — with BETTER accuracy than medium (turbo distils large-v3). Two
    gaps of mlx-whisper are closed here:
    * no built-in VAD → it hallucinates on music/silence ("Thank you." loops
      on a livestream opening, measured). We pre-filter with the Silero VAD
      already bundled in faster-whisper and feed speech-only audio.
    * no progress callback → we chunk the speech audio (~5 min a piece) and
      report chunk-level progress, so the detail-page bar keeps working.
    Audio decode goes through faster-whisper's PyAV decoder — no ffmpeg
    binary needed. Everything heavy is lazy + injectable (NFR-3).
    """

    _CHUNK_SECONDS = 300
    _SAMPLE_RATE = 16000

    def __init__(
        self,
        *,
        model: str | None = None,
        transcribe_fn: Callable[..., dict[str, Any]] | None = None,  # injectable
        decode_fn: Callable[[str], Any] | None = None,  # injectable
        vad_fn: Callable[[Any], list[dict[str, int]]] | None = None,  # injectable
    ) -> None:
        settings = get_settings()
        self._model = model or settings.whisper_mlx_model
        self._transcribe_fn = transcribe_fn
        self._decode_fn = decode_fn
        self._vad_fn = vad_fn

    def _decode(self, audio_path: str) -> Any:
        if self._decode_fn is not None:
            return self._decode_fn(audio_path)
        from faster_whisper.audio import decode_audio  # lazy: heavy

        return decode_audio(audio_path, sampling_rate=self._SAMPLE_RATE)

    def _speech_regions(self, audio: Any) -> list[dict[str, int]]:
        if self._vad_fn is not None:
            return self._vad_fn(audio)
        try:
            from faster_whisper.vad import get_speech_timestamps  # lazy: heavy

            return list(get_speech_timestamps(audio))
        except Exception:
            # VAD is protection, not a requirement — degrade to "all speech"
            return [{"start": 0, "end": len(audio)}]

    def _mlx_transcribe(self, chunk: Any) -> dict[str, Any]:
        if self._transcribe_fn is not None:
            return self._transcribe_fn(chunk, path_or_hf_repo=self._model)
        import mlx_whisper  # lazy: heavy (ml/mlx extra)

        return dict(
            mlx_whisper.transcribe(chunk, path_or_hf_repo=self._model, word_timestamps=False)
        )

    def transcribe(self, audio_path: str) -> TranscriptResult:
        import numpy as np  # transitively present via faster-whisper

        audio = self._decode(audio_path)
        regions = self._speech_regions(audio)
        if not regions:
            return TranscriptResult(language=None, segments=[])
        speech = np.concatenate([audio[r["start"] : r["end"]] for r in regions])
        chunk_len = self._CHUNK_SECONDS * self._SAMPLE_RATE
        language: str | None = None
        segments: list[TranscriptSegment] = []
        for start in range(0, len(speech), chunk_len):
            chunk = speech[start : start + chunk_len]
            out = self._mlx_transcribe(chunk)
            language = language or out.get("language")
            offset_s = start / self._SAMPLE_RATE
            for seg in out.get("segments", []):
                text = str(seg.get("text", "")).strip()
                if not text:
                    continue
                segments.append(
                    TranscriptSegment(
                        text=text,
                        start_ms=_ms(float(seg["start"]) + offset_s),
                        end_ms=_ms(float(seg["end"]) + offset_s),
                        words=[],
                    )
                )
            done = min(start + chunk_len, len(speech))
            progress.update("transcribing", done / len(speech))
        return TranscriptResult(language=language, segments=segments)


def _mlx_available() -> bool:
    try:
        import mlx_whisper  # noqa: F401 — probe only

        return True
    except Exception:
        return False


def get_transcriber() -> Transcriber:
    """Factory for the real transcriber (monkeypatched to a mock in tests).
    Backend selection (owner 2026-07-22): "auto" uses the Apple-GPU mlx path
    when mlx-whisper is importable (Apple Silicon), else the portable CPU
    faster-whisper path — the same code deploys unchanged to a Linux server."""
    backend = get_settings().whisper_backend
    if backend == "mlx" or (backend == "auto" and _mlx_available()):
        return MlxWhisperTranscriber()
    return FasterWhisperTranscriber()
