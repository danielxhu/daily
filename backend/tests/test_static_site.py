"""GitHub Pages snapshot export (`app/static_site.py`).

Only the export half runs here — against a fresh, empty database through the
in-process `TestClient`, so it stays offline. The refresh half is the real poll
+ worker, covered by their own suites."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.source_pack import default_source_pack
from app.static_site import data_file, export, read_sources_file, sync_subscriptions


def test_data_file_names_match_the_frontend_rule() -> None:
    # same cases as frontend src/__tests__/static-data.test.ts
    assert data_file("/boards") == "boards.json"
    assert data_file("/boards/b_tech/notes") == "boards/b_tech/notes.json"
    assert (
        data_file("/api/digest", {"window_days": "7", "board_id": "b_tech"})
        == "api/digest~board_id-b_tech~window_days-7.json"
    )


def test_read_sources_file(tmp_path: Path) -> None:
    f = tmp_path / "sources.txt"
    f.write_text(
        "# comment\n\nb_tech https://a.example/feed  # trailing\nhttps://b.example/rss\n",
        encoding="utf-8",
    )
    assert read_sources_file(f) == [
        ("b_tech", "https://a.example/feed"),
        (None, "https://b.example/rss"),
    ]
    assert read_sources_file(tmp_path / "missing.txt") == []
    assert read_sources_file(None) == []


def test_export_writes_every_read_endpoint_and_hides_keys(tmp_path: Path) -> None:
    settings: Any = Settings(  # type: ignore[call-arg]
        _env_file=None,
        sqlite_path=str(tmp_path / "daily.db"),
        data_dir=str(tmp_path),
        deepseek_api_key="sk-SECRET-9876",
    )
    out = tmp_path / "out"
    export(TestClient(create_app(settings)), out)

    boards = json.loads((out / "boards.json").read_text(encoding="utf-8"))
    assert {b["id"] for b in boards} >= {"b_tech", "b_economy", "b_politics"}
    for name in (
        "subscriptions.json",
        "subscriptions~board_id-b_tech.json",
        "api/digest.json",
        "api/digest~window_days-7.json",
        "api/digest~board_id-b_tech~window_days-90.json",
        "boards/b_tech/notes.json",
        "boards/b_tech/modules.json",
        "knowledge/notes.json",
        "knowledge/search-corpus.json",
        "api/runs.json",
        "_static-params.json",
    ):
        assert (out / name).exists(), name
    assert json.loads((out / "_static-params.json").read_text()) == {"items": [], "notes": []}
    assert "9876" not in (out / "settings/api.json").read_text()


def test_sync_follows_the_sources_file(tmp_path: Path) -> None:
    settings: Any = Settings(  # type: ignore[call-arg]
        _env_file=None, sqlite_path=str(tmp_path / "daily.db"), data_dir=str(tmp_path)
    )
    client = TestClient(create_app(settings))
    pack = {e.url for e in default_source_pack()}

    def urls() -> set[str]:
        return {s["input_url"] for s in client.get("/subscriptions").json()}

    sync_subscriptions(
        client, [("b_tech", "https://a.example/feed"), (None, "https://b.example/rss")]
    )
    assert urls() == pack | {"https://a.example/feed", "https://b.example/rss"}

    # a line removed from the file is unsubscribed; the pack is never touched
    sync_subscriptions(client, [("b_tech", "https://a.example/feed")])
    assert urls() == pack | {"https://a.example/feed"}
