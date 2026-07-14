"""Mock client implementations (X0.3).

These satisfy the `LLMClient` / `VLClient` / `Transcriber` interfaces with canned,
deterministic outputs and call recording, so the offline suite (NFR-3) can drive
the pipeline without network or API spend. Tests monkeypatch the real client
factory with one of these (see `tests/test_clients_mock.py`).
"""

from __future__ import annotations

import math
import threading
from collections import deque
from typing import Any

from app.clients.base import (
    RenderResult,
    TranscriptResult,
    TranscriptSegment,
)


class MockLLMClient:
    """Replays canned JSON responses in order. Records every call for assertions.

    `responses` is consumed FIFO; if exhausted, raises so a test never silently
    gets stale data. Each recorded call notes whether escalation was requested.
    Thread-safe (a lock guards the FIFO + call log) because M2.3 runs extraction
    concurrently across sources — note FIFO order across *concurrent* sources is
    nondeterministic, so multi-source tests should use content-keyed fakes."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses: deque[dict[str, Any]] = deque(responses)
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def complete_json(self, *, system: str, user: str, escalate: bool = False) -> dict[str, Any]:
        with self._lock:
            self.calls.append({"system": system, "user": user, "escalate": escalate})
            if not self._responses:
                raise AssertionError(
                    "MockLLMClient ran out of canned responses; add one per expected call."
                )
            return self._responses.popleft()


class MockTranscriber:
    def __init__(self, result: TranscriptResult | None = None) -> None:
        self.result = result or TranscriptResult(
            language="en",
            segments=[TranscriptSegment(text="mock transcript.", start_ms=0, end_ms=1000)],
        )
        self.calls: list[str] = []

    def transcribe(self, audio_path: str) -> TranscriptResult:
        self.calls.append(audio_path)
        return self.result


class MockRenderClient:
    """Returns canned rendered HTML without launching a browser (NFR-3)."""

    def __init__(self, html: str = "<html><body>mock rendered</body></html>") -> None:
        self.html = html
        self.calls: list[str] = []

    def render(self, url: str) -> RenderResult:
        self.calls.append(url)
        return RenderResult(html=self.html, final_url=url)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0.0 or nb == 0.0 else dot / (na * nb)
