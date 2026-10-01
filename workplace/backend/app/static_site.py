"""Static snapshot of daily for the GitHub Pages site.

GitHub Pages serves files, not a backend, so a scheduled GitHub Actions job
runs the real pipeline on a persistent SQLite database and freezes the result:

1. `refresh` — adopt the default source pack, subscribe any extra sources from
   a sources file, poll every subscription, then run the background worker until
   the backlog is drained (fetch + AI summaries) or the time budget runs out.
2. `export` — call every read endpoint the frontend uses through the real app
   (FastAPI `TestClient`, so the JSON is exactly what the API returns) and write
   each response to `<out>/<path>[~<query>].json`. The frontend's static-data
   mode (`src/lib/static-data.ts`) reads the same file names.

Run from `workplace/backend`:

    python -m app.static_site --out ../frontend/public/data --sources ../site/sources.txt

`DEEPSEEK_API_KEY` enables real summaries; without it items still appear, with
placeholder summaries. `SQLITE_PATH` / `DATA_DIR` choose the database.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app

# the Today / Digest window choices (frontend `WINDOW_DAY_OPTIONS`) plus the
# Sources page's year view
_WINDOW_DAYS = (7, 30, 90, 365)
_RUNS_LIMITS = (20, 50)


def data_file(path: str, query: dict[str, str] | None = None) -> str:
    """The file a GET `path?query` is frozen to. Mirrors `dataFile` in the
    frontend's `src/lib/static-data.ts` — change both together."""
    name = path.strip("/")
    if query:
        name += "~" + "~".join(f"{k}-{v}" for k, v in sorted(query.items()))
    return name + ".json"


def read_sources_file(path: Path | None) -> list[tuple[str | None, str]]:
    """`[board_id] url` per line; blank lines and `#` comments are skipped."""
    if path is None or not path.exists():
        return []
    out: list[tuple[str | None, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        out.append((parts[0], parts[1]) if len(parts) >= 2 else (None, parts[0]))
    return out


def refresh(
    client: TestClient,
    sources: list[tuple[str | None, str]],
    minutes: float,
    max_summaries: int = 1_000_000,
) -> None:
    from app.clients.deepseek import get_llm_client
    from app.db.engine import init_db
    from app.ingestion.ingest import ingest_one
    from app.knowledge.semantic import get_semantic_index
    from app.main import get_ingest_first
    from app.tracking.worker import work_once

    client.post("/source-pack/adopt").raise_for_status()
    existing = {s["input_url"] for s in client.get("/subscriptions").json()}
    for board_id, url in sources:
        if url in existing:
            continue
        resp = client.post(
            "/subscriptions", json={"input_url": url, "mode": "autodiscover", "board_id": board_id}
        )
        print(f"subscribe {url}: {resp.status_code}")

    report = client.post("/tracking/poll")
    report.raise_for_status()
    body = report.json()
    print(f"poll: {body.get('polled')} sources, {body.get('new_items')} new items")

    conn = init_db(get_settings().sqlite_path)
    deadline = time.monotonic() + minutes * 60
    summarized = 0  # the backlog's LLM calls this run, bounded by max_summaries
    try:
        while time.monotonic() < deadline:
            counts = work_once(
                conn,
                llm=get_llm_client(),
                ingest=get_ingest_first(),
                transcribe_ingest=ingest_one,
                semantic_index=get_semantic_index(),
            )
            print(f"worker: {counts}")
            summarized += counts["summarized"]
            if not any(counts.values()) or summarized >= max_summaries:
                break
    finally:
        conn.close()


def export(client: TestClient, out: Path) -> None:
    written = 0

    def write(name: str, body: Any) -> None:
        nonlocal written
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        written += 1

    def get(path: str, query: dict[str, str] | None = None) -> Any:
        resp = client.get(path, params=query)
        resp.raise_for_status()
        body = resp.json()
        write(data_file(path, query), body)
        return body

    get("/config")
    get("/source-pack")
    get("/knowledge/notes")
    get("/knowledge/chats")
    get("/api/runs")
    for limit in _RUNS_LIMITS:
        get("/api/runs", {"limit": str(limit)})

    settings_api = client.get("/settings/api").json()
    for slot in settings_api.get("slots", []):
        slot["key_last4"] = None  # a public page never shows any part of a key
    write(data_file("/settings/api"), settings_api)

    boards = get("/boards")
    get("/subscriptions")
    get("/api/digest")
    items: dict[str, Any] = {}
    note_params: list[dict[str, str]] = []
    for days in _WINDOW_DAYS:
        for card in get("/api/digest", {"window_days": str(days)})["tracked"]:
            items[card["id"]] = card
    for board in boards:
        bid = board["id"]
        get("/subscriptions", {"board_id": bid})
        get(f"/boards/{bid}/modules")
        for note in get(f"/boards/{bid}/notes"):
            note_params.append({"boardId": bid, "noteId": note["id"]})
        get("/api/digest", {"board_id": bid})
        for days in _WINDOW_DAYS:
            get("/api/digest", {"board_id": bid, "window_days": str(days)})

    for item_id in items:
        get(f"/tracked-items/{item_id}")
        get(f"/tracked-items/{item_id}/progress")

    # Knowledge search runs in the browser over this corpus (static-data.ts).
    corpus = {"saved": client.get("/knowledge/notes").json(), "items": list(items.values())}
    write("knowledge/search-corpus.json", corpus)
    # Detail pages a static export pre-renders (frontend `static-params.ts`).
    params = {"items": list(items), "notes": note_params}
    write("_static-params.json", params)
    print(f"export: {written} responses, {len(items)} items, {len(note_params)} notes -> {out}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, required=True, help="directory for the JSON files")
    parser.add_argument("--sources", type=Path, help="extra sources file ([board_id] url)")
    parser.add_argument("--minutes", type=float, default=10.0, help="worker time budget")
    parser.add_argument(
        "--max-summaries",
        type=int,
        default=1_000_000,
        help="stop the backlog worker after this many AI summaries (caps LLM cost per run)",
    )
    parser.add_argument("--skip-refresh", action="store_true", help="export only")
    args = parser.parse_args(argv)

    client = TestClient(create_app(get_settings()))
    if not args.skip_refresh:
        refresh(client, read_sources_file(args.sources), args.minutes, args.max_summaries)
    args.out.mkdir(parents=True, exist_ok=True)
    export(client, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
