"""On-device OCR seam (owner 2026-07-23): config-driven selection, lazy pyobjc,
and the real Vision framework is never invoked in tests (NFR-3)."""

from __future__ import annotations

from app.clients.base import VisionClient
from app.core.config import Settings
from app.ingestion import ocr as mod


def test_vision_client_selection_is_config_driven(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(mod, "get_settings", lambda: Settings.model_construct(image_ocr="off"))
    assert mod.get_vision_client() is None

    monkeypatch.setattr(mod, "get_settings", lambda: Settings.model_construct(image_ocr="auto"))
    monkeypatch.setattr(mod, "_apple_vision_available", lambda: False)
    assert mod.get_vision_client() is None  # not macOS / extra not installed → skip
    monkeypatch.setattr(mod, "_apple_vision_available", lambda: True)
    client = mod.get_vision_client()
    assert isinstance(client, mod.AppleVisionOCR)
    assert isinstance(client, VisionClient)
