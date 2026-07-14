"""SQLite database layer (X0.6): connection lifecycle + per-domain migrations."""

from app.db.engine import connect, init_db, init_default, reset_db
from app.db.migrations import (
    MIGRATIONS,
    Migration,
    applied_versions,
    ensure_ledger,
    migrate,
)
from app.db.run_trace import RunTrace, load_run

__all__ = [
    "MIGRATIONS",
    "Migration",
    "RunTrace",
    "applied_versions",
    "connect",
    "ensure_ledger",
    "feedback_counts",
    "init_db",
    "init_default",
    "list_feedback",
    "list_usage",
    "load_run",
    "migrate",
    "record_feedback",
    "record_usage",
    "reset_db",
    "usage_counts",
]
