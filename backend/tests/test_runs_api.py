"""M7.16 — run-trace list API (SSOT §4 / §7).

Read-only `GET /api/runs` lists recent verify/poll/digest runs, newest first, each
with its ordered steps — so a half-failed run is inspectable (the Trace UI reads
this). Scope: API only."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi.testclient import TestClient

from app.db.engine import init_db
from app.db.run_trace import RunTrace, list_runs
from app.main import create_app, get_db
from app.schemas.models import SourceRequest, StepTrace


def _half_failed_run(conn: sqlite3.Connection) -> str:
    trace = RunTrace(
        conn, trigger="verify", inputs=[SourceRequest(kind="url", url="https://x.example/a")]
    )
    trace.record(StepTrace(step="ingestion", status="ok"))
    trace.record(StepTrace(step="extraction", status="failed", error="extraction failed: boom"))
    trace.finish()
    return trace.run_id


def _db_override(db_path: str) -> Callable[[], Iterator[sqlite3.Connection]]:
    def _get_db() -> Iterator[sqlite3.Connection]:
        conn = init_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    return _get_db


def _client(db_path: str) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = _db_override(db_path)
    return TestClient(app)


def test_list_runs_reconstructs_steps(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    run_id = _half_failed_run(conn)
    conn.close()
    runs = list_runs(init_db(str(tmp_path / "daily.db")))
    assert [r.id for r in runs] == [run_id]
    assert [(s.step, s.status) for s in runs[0].steps] == [
        ("ingestion", "ok"),
        ("extraction", "failed"),
    ]


def test_api_runs_lists_half_failed_run(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    run_id = _half_failed_run(conn)
    conn.close()

    res = _client(db).get("/api/runs")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1 and body[0]["id"] == run_id and body[0]["trigger"] == "verify"
    # the failed step + its error are inspectable
    failed = [s for s in body[0]["steps"] if s["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["step"] == "extraction" and "boom" in failed[0]["error"]


def test_api_runs_newest_first(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    first = RunTrace(conn, trigger="verify", inputs=[])
    first.finish()
    second = RunTrace(conn, trigger="poll", inputs=[])
    second.finish()
    conn.close()

    body = _client(db).get("/api/runs").json()
    assert [r["id"] for r in body] == [second.run_id, first.run_id]


def test_api_runs_empty(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    init_db(db).close()
    assert _client(db).get("/api/runs").json() == []
