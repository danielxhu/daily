"""Local data reset (single-operator, §2.2).

Wipe the local SQLite DB (+ WAL/SHM sidecars) so a trial can start clean.
Single-operator local wipe by design: NO backup/restore, NO multi-user/auth.
Idempotent: it silently skips whatever isn't there."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.db.engine import reset_db


def reset_local_data(settings: Settings) -> list[str]:
    """Delete the local SQLite DB (+ sidecars) for the configured `Settings`.
    Returns the paths actually removed (for reporting)."""
    removed: list[str] = []
    sqlite = settings.sqlite_path
    if any(Path(sqlite + suffix).exists() for suffix in ("", "-wal", "-shm")):
        reset_db(sqlite)  # deletes the db file + its WAL/SHM sidecars
        removed.append(sqlite)
    return removed
