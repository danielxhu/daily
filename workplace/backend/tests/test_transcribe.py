"""M1A.6 — local transcription adapter: batched+VAD segments, lazy model load,
and the real faster-whisper model is never loaded in tests (NFR-3)."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from app.clients.base import Transcriber, TranscriptResult
from app.ingestion.transcribe import FasterWhisperTranscriber, _to_transcript


def _fake_segments() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            start=0.0,
            end=2.5,
            text=" NVIDIA posted record revenue.",
            words=[
                SimpleNamespace(word="NVIDIA", start=0.0, end=0.5),
                SimpleNamespace(word=" posted", start=0.5, end=1.0),
            ],
        ),
        SimpleNamespace(start=2.5, end=4.0, text=" Demand stayed strong.", words=[]),
    ]


class _FakeModel:
    def transcribe(self, audio_path: str, *, batch_size: int, vad_filter: bool):  # type: ignore[no-untyped-def]
        # 2026-07-20: batched + VAD replaces the sequential word-timestamp run
        assert batch_size >= 1 and vad_filter is True
        return _fake_segments(), SimpleNamespace(language="en")


def test_mapping_produces_ms_segments_and_word_timestamps() -> None:
    result = _to_transcript(_fake_segments(), language="en")
    assert isinstance(result, TranscriptResult)
    assert result.language == "en"
    assert [s.start_ms for s in result.segments] == [0, 2500]
    assert result.segments[0].end_ms == 2500
    # text is stripped; words carry ms timestamps
    assert result.segments[0].text == "NVIDIA posted record revenue."
    assert result.segments[0].words[0] == {"text": "NVIDIA", "start_ms": 0, "end_ms": 500}
    assert result.text.startswith("NVIDIA posted record revenue.")


def test_adapter_satisfies_transcriber_protocol() -> None:
    assert isinstance(FasterWhisperTranscriber(model_loader=_FakeModel), Transcriber)


def test_model_is_lazy_not_loaded_at_init() -> None:
    t = FasterWhisperTranscriber(model_loader=_FakeModel)
    assert t._model is None  # constructing must not load a model


def test_transcribe_uses_injected_model_without_loading_faster_whisper() -> None:
    t = FasterWhisperTranscriber(model_loader=_FakeModel)
    result = t.transcribe("/tmp/audio.mp3")
    assert [s.text for s in result.segments] == [
        "NVIDIA posted record revenue.",
        "Demand stayed strong.",
    ]
    assert t._model is not None  # loaded on first use
    # the real heavy library was never imported (NFR-3)
    assert "faster_whisper" not in sys.modules


def test_importing_module_does_not_import_faster_whisper() -> None:
    assert "faster_whisper" not in sys.modules
