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


# --- MLX (Apple-GPU) adapter (owner 2026-07-22) -------------------------------


def _fake_decode(_path: str):  # type: ignore[no-untyped-def]
    import numpy as np

    return np.zeros(16000 * 20, dtype=np.float32)  # "20 seconds of audio"


def _fake_vad(audio):  # type: ignore[no-untyped-def]
    # two speech regions; the silence between them must be cut before the model
    return [{"start": 0, "end": 16000 * 5}, {"start": 16000 * 15, "end": len(audio)}]


def _fake_mlx(chunk, **_: object):  # type: ignore[no-untyped-def]
    return {
        "language": "zh",
        "segments": [
            {"start": 0.0, "end": 2.0, "text": " 来源说了一件事。"},
            {"start": 2.0, "end": 4.0, "text": ""},  # blank → dropped
        ],
    }


def test_mlx_adapter_vad_filters_then_maps_segments() -> None:
    from app.ingestion import progress
    from app.ingestion.transcribe import MlxWhisperTranscriber

    t = MlxWhisperTranscriber(
        model="unused", transcribe_fn=_fake_mlx, decode_fn=_fake_decode, vad_fn=_fake_vad
    )
    progress.begin("https://v.example/x")
    try:
        result = t.transcribe("/tmp/a.m4a")
        # 10s of speech (5+5) in one chunk → one fake call's worth of segments
        assert [s.text for s in result.segments] == ["来源说了一件事。"]
        assert result.language == "zh"
        assert isinstance(t, Transcriber)
        # chunk-level progress reached 100% of the speech-only audio
        snap = progress.snapshot("https://v.example/x")
        assert snap == ("transcribing", 1.0)
    finally:
        progress.finish()


def test_mlx_adapter_no_speech_returns_empty() -> None:
    from app.ingestion.transcribe import MlxWhisperTranscriber

    t = MlxWhisperTranscriber(
        model="unused", transcribe_fn=_fake_mlx, decode_fn=_fake_decode, vad_fn=lambda _a: []
    )
    result = t.transcribe("/tmp/a.m4a")
    assert result.segments == [] and result.language is None


def test_backend_selection_is_config_driven(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import Settings
    from app.ingestion import transcribe as mod

    monkeypatch.setattr(
        mod, "get_settings", lambda: Settings.model_construct(whisper_backend="faster")
    )
    assert isinstance(mod.get_transcriber(), mod.FasterWhisperTranscriber)
    monkeypatch.setattr(
        mod, "get_settings", lambda: Settings.model_construct(whisper_backend="mlx")
    )
    assert isinstance(mod.get_transcriber(), mod.MlxWhisperTranscriber)
    # auto: probe decides — force the probe both ways
    monkeypatch.setattr(
        mod, "get_settings", lambda: Settings.model_construct(whisper_backend="auto")
    )
    monkeypatch.setattr(mod, "_mlx_available", lambda: True)
    assert isinstance(mod.get_transcriber(), mod.MlxWhisperTranscriber)
    monkeypatch.setattr(mod, "_mlx_available", lambda: False)
    assert isinstance(mod.get_transcriber(), mod.FasterWhisperTranscriber)
