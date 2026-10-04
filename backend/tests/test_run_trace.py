"""X0.7 — run-trace writer: ok/skipped/failed steps persist and a half-failed
run is reconstructable (so logs/UI can show *why* a run partly failed)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.db import RunTrace, init_db, load_run
from app.schemas.models import SourceRequest, StepTrace


def _conn(tmp_path: Path) -> sqlite3.Connection:
    return init_db(str(tmp_path / "daily.db"), domains=["trace"])


def test_run_records_each_step_status(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    trace = RunTrace(conn, trigger="verify", inputs=[SourceRequest(kind="text", text="hi")])
    trace.record(StepTrace(step="ingestion", status="ok", counts={"sources": 1}))
    trace.record(StepTrace(step="vision", status="skipped"))
    trace.record(StepTrace(step="extraction", status="failed", error="LLM JSON parse error"))
    trace.finish()

    run = load_run(conn, trace.run_id)
    assert run.trigger == "verify"
    assert [s.status for s in run.steps] == ["ok", "skipped", "failed"]
    assert run.finished_at is not None
    assert run.inputs[0].text == "hi"


def test_half_failed_run_is_inspectable(tmp_path: Path) -> None:
    # The §4 example: captions failed → whisper ok; then a later step fails.
    conn = _conn(tmp_path)
    trace = RunTrace(
        conn, trigger="verify", inputs=[SourceRequest(kind="url", url="https://x.test")]
    )
    trace.record(
        StepTrace(
            step="ingestion",
            status="ok",
            fallback_used="yt-dlp captions failed → local whisper",
            counts={"claims": 8},
        )
    )
    trace.record(StepTrace(step="verification", status="failed", error="stance #3 failed"))
    trace.finish()

    run = load_run(conn, trace.run_id)
    ingestion = run.steps[0]
    assert ingestion.fallback_used == "yt-dlp captions failed → local whisper"
    assert ingestion.counts == {"claims": 8}
    failed = run.steps[1]
    assert failed.status == "failed" and failed.error == "stance #3 failed"


def test_steps_keep_insertion_order(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    trace = RunTrace(conn, trigger="poll", inputs=[])
    for step in ("ingestion", "extraction", "alignment", "scoring"):
        trace.record(StepTrace(step=step, status="ok"))
    run = load_run(conn, trace.run_id)
    assert [s.step for s in run.steps] == ["ingestion", "extraction", "alignment", "scoring"]


def test_unfinished_run_has_no_finished_at(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    trace = RunTrace(conn, trigger="digest", inputs=[])
    trace.record(StepTrace(step="digest", status="ok"))
    # not finished yet
    run = load_run(conn, trace.run_id)
    assert run.finished_at is None


def test_load_unknown_run_raises(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    with pytest.raises(KeyError):
        load_run(conn, "does-not-exist")
