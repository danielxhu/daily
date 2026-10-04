"""SQLite connection + local-data lifecycle (X0.6).

Connections are local files (NFR-2); tests pass a temp path so they never touch
the real `data/` dir. `reset_db` removes the database so a beta user can safely
wipe local data (no multi-user/auth/backup system — that stays out of scope).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.config import get_settings
from app.db.migrations import migrate


def connect(path: str) -> sqlite3.Connection:
    # check_same_thread=False (M14.1 live-mode fix): FastAPI runs a sync generator
    # dependency's enter and exit on threadpool workers, and under CONCURRENT
    # requests (Today mounts fire digest + subscriptions + boards + adopt at once)
    # the exit's `conn.close()` can land on a different worker thread than the one
    # that opened it — sqlite3's default same-thread guard then raises. Each
    # connection stays per-request and is never used by two threads at once, which
    # is the case the guard exists for; SQLite itself (serialized mode) is safe.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str, domains: list[str] | None = None) -> sqlite3.Connection:
    """Create the data dir if needed, open the DB, and apply migrations."""
    p = Path(path)
    if p.parent != Path(""):
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(str(p))
    migrate(conn, domains)
    return conn


def reset_db(path: str) -> None:
    """Delete the local database (and its WAL/SHM sidecars). Idempotent."""
    for suffix in ("", "-wal", "-shm"):
        f = Path(path + suffix)
        if f.exists():
            f.unlink()


def init_default() -> sqlite3.Connection:
    """Open + migrate the configured local database (`Settings.sqlite_path`)."""
    return init_db(get_settings().sqlite_path)
