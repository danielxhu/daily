"""In-memory progress for the background transcription job (owner 2026-07-21
"能不能加个进度条").

ONE slot by design: the worker transcribes a single item at a time, so the
current job's URL + stage + percent live in a module-level slot — no table, no
persistence, gone on restart (the honest answer then is "queued"). Written by
the ingestion path (yt-dlp download hook, whisper segment stream); read by
GET /tracked-items/{id}/progress, matched on the item's URL.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_current: dict[str, object] | None = None


def begin(url: str) -> None:
    """The transcription path starts working on `url` (download comes first)."""
    global _current
    with _lock:
        _current = {"url": url, "stage": "downloading", "pct": 0.0}


def update(stage: str, pct: float) -> None:
    """Move the current job to `stage` at `pct` (0..1). No-op without a job —
    a caption-path fetch never begins one."""
    with _lock:
        if _current is not None:
            _current["stage"] = stage
            _current["pct"] = max(0.0, min(float(pct), 1.0))


def finish() -> None:
    """The job ended (success or typed failure) — the slot empties either way."""
    global _current
    with _lock:
        _current = None


def snapshot(url: str) -> tuple[str, float] | None:
    """(stage, pct) if `url` is the job being worked on right now, else None."""
    with _lock:
        if _current is not None and _current["url"] == url:
            return str(_current["stage"]), float(_current["pct"])  # type: ignore[arg-type]
    return None
