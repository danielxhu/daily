"""HTTP cassette replay helper (X0.3 → SSOT §9.2 / NFR-3).

Real HTTP fetches (static HTML in M1A.4, CASR/official-source fetch in M4.12, feed
polling in Stage 7) go through `httpx` and are **replayed from recorded vcrpy
cassettes** in tests — never live. `replay()` opens a cassette in
`record_mode="none"`: it serves recorded interactions and raises on any
un-recorded request, so the suite physically cannot hit the network or record new
traffic by accident.

Recording a real cassette (done deliberately, outside the offline suite) uses
`record_mode="once"` against the real endpoint; the recorded YAML is then checked
in and replayed here. Cassettes live in `tests/cassettes/`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import vcr

CASSETTE_DIR = Path(__file__).parent / "cassettes"


def replay(cassette_name: str) -> Any:
    """Replay-only cassette context manager (no record, no network)."""
    return vcr.use_cassette(str(CASSETTE_DIR / cassette_name), record_mode="none")
