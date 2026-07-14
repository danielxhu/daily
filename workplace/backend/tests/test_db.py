"""X0.6 — SQLite init + migration discipline.

Each test gets its own temp DB (isolation); none touch the real `data/` dir.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.db import applied_versions, connect, init_db, migrate, reset_db
from app.db.migrations import MIGRATIONS, Migration


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r[0] for r in rows}


def test_init_creates_data_dir_and_all_tables(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "daily.db"
    conn = init_db(str(db))
    assert db.exists()  # data dir was created
    tables = _tables(conn)
    assert {"boards", "seen_items", "memory_items", "schema_migrations"} <= tables


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    db = str(tmp_path / "daily.db")
    conn = init_db(db)
    before = conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]
    second = migrate(conn)  # re-run
    after = conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]
    assert second == []  # nothing applied the second time
    assert before == after


def test_domains_migrate_independently(tmp_path: Path) -> None:
    conn = connect(str(tmp_path / "daily.db"))
    applied = migrate(conn, domains=["board"])
    # all of the board domain's pending migrations apply (derived, not hard-coded, so
    # adding a board migration like M6.3's knowledge_notes doesn't break this test)
    expected = [("board", m.version) for m in sorted(MIGRATIONS["board"], key=lambda m: m.version)]
    assert applied == expected
    tables = _tables(conn)
    assert "boards" in tables
    assert "seen_items" not in tables  # tracking not migrated
    assert "memory_items" not in tables  # memory not migrated
    # other domains are still pending and can be applied later
    assert applied_versions(conn, "tracking") == set()


def test_ledger_records_domain_and_version(tmp_path: Path) -> None:
    conn = init_db(str(tmp_path / "daily.db"))
    rows = conn.execute("SELECT domain, version FROM schema_migrations").fetchall()
    recorded = {(r[0], r[1]) for r in rows}
    expected = {(d, m.version) for d, ms in MIGRATIONS.items() for m in ms}
    assert recorded == expected


def test_unknown_domain_rejected(tmp_path: Path) -> None:
    conn = connect(str(tmp_path / "daily.db"))
    with pytest.raises(KeyError):
        migrate(conn, domains=["nope"])


def test_foreign_keys_pragma_on(tmp_path: Path) -> None:
    conn = connect(str(tmp_path / "daily.db"))
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_reset_db_removes_file(tmp_path: Path) -> None:
    db = tmp_path / "daily.db"
    init_db(str(db)).close()
    assert db.exists()
    reset_db(str(db))
    assert not db.exists()
    reset_db(str(db))  # idempotent: no error when already gone


def test_migrations_versions_are_unique_and_ordered() -> None:
    for domain, ms in MIGRATIONS.items():
        versions = [m.version for m in ms]
        assert versions == sorted(versions), f"{domain} migrations not version-ordered"
        assert len(versions) == len(set(versions)), f"{domain} has duplicate versions"


def test_memory_baseline_keeps_multiple_versions_of_one_claim(tmp_path: Path) -> None:
    # FR-9: invalidate-don't-delete — superseded v1 and current v2 of the same
    # claim_id must coexist (PK is (claim_id, version), not claim_id alone).
    conn = init_db(str(tmp_path / "daily.db"))
    conn.execute(
        "INSERT INTO memory_items (claim_id, canonical_text, version, is_current,"
        " valid_from, valid_to, ingested_at, invalidated_by)"
        " VALUES ('c1', 'rumor', 1, 0, '2026-06-01', '2026-06-05', '2026-06-01', 'c1@2')"
    )
    conn.execute(
        "INSERT INTO memory_items (claim_id, canonical_text, version, is_current,"
        " valid_from, valid_to, ingested_at, invalidated_by)"
        " VALUES ('c1', 'confirmed', 2, 1, '2026-06-05', NULL, '2026-06-05', NULL)"
    )
    conn.commit()
    rows = conn.execute(
        "SELECT version, is_current FROM memory_items WHERE claim_id = 'c1' ORDER BY version"
    ).fetchall()
    assert [(r[0], r[1]) for r in rows] == [(1, 0), (2, 1)]


def test_failed_migration_rolls_back_and_writes_no_ledger_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A migration whose 2nd statement is invalid: the 1st CREATE TABLE must be
    # rolled back and no ledger row written (transactional migration discipline).
    bad = Migration(1, "boom", ("CREATE TABLE tmp_boom (x)", "THIS IS NOT SQL"))
    monkeypatch.setitem(MIGRATIONS, "test_fail", [bad])
    conn = connect(str(tmp_path / "daily.db"))
    with pytest.raises(sqlite3.OperationalError):
        migrate(conn, domains=["test_fail"])
    tables = _tables(conn)
    assert "tmp_boom" not in tables  # CREATE TABLE rolled back
    assert applied_versions(conn, "test_fail") == set()  # no ledger row
