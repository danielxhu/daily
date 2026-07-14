"""Run-trace writer (X0.7, SSOT §4/§7).

Every verify/poll/digest run records a flat `PipelineRun` + ordered `StepTrace`
rows to SQLite, so a half-failed run ("captions failed → whisper ok; 8 claims;
stance #3 failed") is inspectable in logs and the UI. This is a **debug trace,
deliberately not a telemetry/tracing platform**.

Each step is committed as it is recorded, so a crash mid-run still leaves the
trace-so-far on disk. `load_run` reconstructs a `PipelineRun` (schema X0.4 §7).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Literal

from app.schemas.models import PipelineRun, SourceRequest, StepTrace

RunTrigger = Literal["verify", "poll", "digest"]  # mirrors PipelineRun.trigger (§7)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RunTrace:
    """Writer for one pipeline run's debug trace."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        trigger: RunTrigger,
        inputs: list[SourceRequest],
        prompt_version: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.conn = conn
        self.run_id = run_id or uuid.uuid4().hex
        self._seq = 0
        conn.execute(
            "INSERT INTO pipeline_runs (id, trigger, inputs_json, prompt_version,"
            " started_at, finished_at) VALUES (?, ?, ?, ?, ?, NULL)",
            (
                self.run_id,
                trigger,
                json.dumps([i.model_dump() for i in inputs]),
                prompt_version,
                _now(),
            ),
        )
        conn.commit()

    def record(self, step: StepTrace) -> StepTrace:
        """Persist one step's outcome (ok / skipped / failed) in run order."""
        self.conn.execute(
            "INSERT INTO step_traces (run_id, seq, step, status, fallback_used,"
            " counts_json, error, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.run_id,
                self._seq,
                step.step,
                step.status,
                step.fallback_used,
                json.dumps(step.counts),
                step.error,
                step.duration_ms,
            ),
        )
        self._seq += 1
        self.conn.commit()
        return step

    def finish(self) -> None:
        self.conn.execute(
            "UPDATE pipeline_runs SET finished_at = ? WHERE id = ?", (_now(), self.run_id)
        )
        self.conn.commit()


def list_runs(conn: sqlite3.Connection, *, limit: int = 50) -> list[PipelineRun]:
    """The most recent pipeline runs (with their ordered steps), newest first — the
    debug trace list (§4/§7). A half-failed run is fully reconstructed so the UI can
    show where the pipeline got stuck."""
    rows = conn.execute(
        "SELECT id FROM pipeline_runs ORDER BY started_at DESC, rowid DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [load_run(conn, r[0]) for r in rows]


def load_run(conn: sqlite3.Connection, run_id: str) -> PipelineRun:
    """Reconstruct a persisted run (with its ordered steps) as a `PipelineRun`."""
    row = conn.execute(
        "SELECT id, trigger, inputs_json, prompt_version, started_at, finished_at"
        " FROM pipeline_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"no pipeline run {run_id!r}")
    step_rows = conn.execute(
        "SELECT step, status, fallback_used, counts_json, error, duration_ms"
        " FROM step_traces WHERE run_id = ? ORDER BY seq",
        (run_id,),
    ).fetchall()
    steps = [
        StepTrace(
            step=r[0],
            status=r[1],
            fallback_used=r[2],
            counts=json.loads(r[3]),
            error=r[4],
            duration_ms=r[5],
        )
        for r in step_rows
    ]
    inputs = [SourceRequest.model_validate(d) for d in json.loads(row[2])]
    return PipelineRun(
        id=row[0],
        trigger=row[1],
        inputs=inputs,
        steps=steps,
        prompt_version=row[3],
        started_at=row[4],
        finished_at=row[5],
    )
