"""Local data reset (engine removed 2026-07-13): SQLite only; idempotent;
returns what it removed. No backup, no multi-user."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.config import Settings
from app.reset import reset_local_data


def _settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, sqlite_path=str(tmp_path / "daily.db"))  # type: ignore[call-arg]


def test_reset_removes_the_db_and_reports_it(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite3.connect(settings.sqlite_path).close()
    assert Path(settings.sqlite_path).exists()
    removed = reset_local_data(settings)
    assert removed == [settings.sqlite_path]
    assert not Path(settings.sqlite_path).exists()


def test_reset_is_idempotent_on_clean_dir(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert reset_local_data(settings) == []
    assert reset_local_data(settings) == []


def test_reset_only_touches_configured_paths(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    bystander = tmp_path / "keep.txt"
    bystander.write_text("keep", encoding="utf-8")
    sqlite3.connect(settings.sqlite_path).close()
    reset_local_data(settings)
    assert bystander.exists()
