"""In-process poll scheduler (M7.7 / M9.10, SSOT §6.2 / §6.4).

A thin wrapper over APScheduler's in-process scheduler: register ONE recurring
"tick" job. Each tick re-reads the **current** active subscriptions from the DB and
polls the ones whose interval has elapsed — so sources added/removed after startup
are picked up without a restart, and a backed-off interval (§6.6) is honored because
it is read fresh each tick. Polling, not push; runs only while the host is on — no
always-on server (§6.4).

The APScheduler backend is **lazy-imported** and **injectable**, so tests pass a fake
backend and never start a real scheduler (NFR-3). The tick action (`poll_job`) is
also injected. This wires a job to a clock; the poll itself lives in `runtime.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# The scheduler calls this once per tick; it re-reads current subscriptions itself.
PollJob = Callable[[], object]

TICK_JOB_ID = "poll:tick"


class PollScheduler:
    """Registers a single recurring poll tick. `backend` is an APScheduler
    `BackgroundScheduler`-like object (`add_job` / `start` / `shutdown`); when None
    it is lazy-built from APScheduler on first use."""

    def __init__(self, backend: Any | None = None) -> None:
        self._backend = backend

    def _ensure(self) -> Any:
        if self._backend is None:
            from apscheduler.schedulers.background import BackgroundScheduler

            self._backend = BackgroundScheduler()
        return self._backend

    def schedule_enrich_tick(self, job: PollJob, *, seconds: int) -> None:
        """Register the background enrichment worker tick (owner 2026-07-10):
        pending items upgrade themselves while the app runs — no clicks."""
        self._ensure().add_job(
            job,
            "interval",
            seconds=seconds,
            id="enrich:tick",
            max_instances=1,
            coalesce=True,
        )

    def schedule_tick(self, poll_job: PollJob, *, minutes: int) -> None:
        """Register/replace the recurring tick that polls due subscriptions."""
        self._ensure().add_job(
            poll_job,
            "interval",
            minutes=minutes,
            id=TICK_JOB_ID,
            replace_existing=True,
        )

    def start(self) -> None:
        self._ensure().start()

    def shutdown(self) -> None:
        if self._backend is not None:
            self._backend.shutdown()
