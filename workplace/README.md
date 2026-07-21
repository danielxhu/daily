# daily

Continuous source tracking + a multi-level, user-owned knowledge base.
New items from your sources become visible, summarized, searchable knowledge the
moment a poll finds them — carrying honest context (source tier, provenance,
duplicate/repost hints, typed statuses) and an AI summary that only restates what
the source says. The product surface is **tracking + knowledge** (Today / Sources /
Knowledge): no scores or verdicts anywhere — daily tells you what's new and where
it came from, and answers only from what it has stored.

Knowledge search runs two channels: deterministic keyword matching, plus a
**local semantic recall layer** — multilingual sentence-transformers embeddings
in a persistent **Chroma** collection, maintained incrementally by the
background worker — so a Chinese query finds an English-summarized item and
vice versa. Local-first like everything else (no external vector service); if
the index is unavailable, search degrades to keyword-only.

## Layout

```
backend/    Python (FastAPI app; tracking/knowledge API)
  app/        ingestion · tracking · knowledge · boards · clients (LLM/STT real + mocks)
  tests/      offline test suite (network-banned) — see tests/README.md
frontend/   Next.js + Tailwind UI (today · sources · knowledge · digest · trace)
scripts/    dev.sh · serve.sh · test-all.sh · reset_local.py
docker-compose.yml   local containerized run (backend + frontend)
```

## Backend dev commands

Requires **Python 3.11+**. If 3.11 isn't on your machine, `uv` can
fetch a standalone build: `uv python install 3.11 && uv venv -p 3.11 .venv`.

```bash
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # core + dev tools (incl. vcrpy for cassettes)

pytest                          # offline test suite (zero network, zero API spend)
ruff check .                    # lint
ruff format --check .           # format check
mypy                            # type check (strict)
```

Copy `backend/.env.example` → `backend/.env` and add a DeepSeek key only when
running the app with real AI summaries and discussion; the test suite needs no
keys and makes no network calls (see `backend/tests/README.md` for the offline
strategy).

## Run the app locally

After the one-time setup (backend venv + `pip install -e '.[dev]'`; frontend
`npm install`), start the whole app — backend (FastAPI :8000) + frontend (Next.js
:3000), with local SQLite + Chroma under `backend/data/` — with:

```bash
scripts/dev.sh          # starts both; open http://localhost:3000 ; Ctrl-C stops both
```

For everyday use, `scripts/serve.sh` runs the same app in **production mode**
(`next build` once, then `next start`) — page navigation is near-instant. Use
`dev.sh` only when actively changing frontend code (it hot-reloads; `serve.sh`
doesn't).

The optional **ml** extra (`pip install -e '.[ml]'` — faster-whisper for real
audio transcription) uses Metal locally on a Mac. The app boots without a key;
real AI summaries need `DEEPSEEK_API_KEY` in `backend/.env`.

`dev.sh` sets `ENABLE_TRACKING_SCHEDULER=true`, so tracked sources are polled on
their interval (hourly by default) while the app runs — polling, not push; only
while your machine is on. The **Check for new items** button on the Sources view (or
`POST /tracking/poll`) forces an immediate check; new items run the same pipeline
into the knowledge base and the digest. A plain `uvicorn app.main:app` leaves the
scheduler off.

**Containerized alternative** — `docker compose up` builds and runs both services
(backend on :8000, frontend on :3000; data bind-mounted to `backend/data/`). Pass a
key through the host shell when you want real AI summaries (`export DEEPSEEK_API_KEY=...`);
it is never baked into an image. The backend image is the lean base install (no `ml`),
so audio transcription typed-skips — use the local path above for the full feature set.

For the browser e2e (`scripts/test-all.sh`, Playwright), install the browser once:
`cd frontend && npx playwright install chromium`.

**Reset local data** — wipe the local SQLite DB, Chroma store, and derived data
to start a trial clean (destructive, no backup; asks to confirm unless `--yes`):

```bash
cd backend && .venv/bin/python ../scripts/reset_local.py        # prompts
cd backend && .venv/bin/python ../scripts/reset_local.py --yes  # no prompt
```

## Offline test matrix

One command runs the whole offline suite (backend ruff/format/mypy/pytest +
frontend typecheck/vitest/build + Playwright mock e2e) — zero network, zero API
spend, exits non-zero on any failure:

```bash
scripts/test-all.sh            # full matrix (incl. browser e2e)
scripts/test-all.sh --no-e2e   # faster regression (skip the browser e2e)
```

It installs nothing; run the one-time setup first (`pip install -e '.[dev]'` in
`backend/`, `npm install` + `npx playwright install chromium` in `frontend/`).

## Fixtures (offline by design)

The whole test suite runs with **no network and no API spend**, driven by
committed fixtures:

- **Backend tests** mock the LLM / transcriber / browser-render clients, replay
  recorded HTTP with `vcrpy` cassettes, and ban sockets via an autouse fixture
  (`backend/tests/conftest.py`); a real whisper / embedding model is never loaded.
  See `backend/tests/README.md` for the strategy.
- **Frontend** runs against a mock API (MSW): component tests mock `fetch`; the
  Playwright e2e runs a mock build (`NEXT_PUBLIC_API_MOCK=1`), no backend needed.
  The e2e suite owns **port 3100** and **never reuses an existing
  server** (`reuseExistingServer: false`) — a stale/non-mock server can no longer
  be silently reused (every spec used to time out on `html[data-msw-ready]`).
  Reproducible local run: `cd frontend && npm run e2e` — no port cleanup needed.
  Caveat: `build:mock` replaces `.next`, so a dev server sharing this checkout
  needs a restart (`scripts/dev.sh`) after an e2e run.

## How a source is read (coverage & limits)

Ingestion is **best-effort**: a source that can't be fetched is typed-skipped with a
reason + a next step, and the rest of the batch still completes. What's
supported:

- **Web page** — static HTML, then a structured-extraction pass, then a headless
  browser render fallback (when enabled). **Paywalls / anti-bot / login walls are
  not bypassed** (red line): they typed-skip (`paywall` / `anti_bot` /
  `login_required`) and tell you to paste the text.
- **PDF** — text-layer extraction (`pdf_text`); scanned/image-only PDFs aren't OCR'd.
- **Podcast** — an RSS `<enclosure>` or a direct audio URL → local whisper; arbitrary
  Apple/Spotify episode *pages* aren't promised.
- **YouTube** — captions via `yt-dlp`, audio→whisper fallback when there are none.
  **No video is downloaded**, so on-screen charts aren't read — paste the key
  chart text instead.
- **Pasted text** — the universal fallback (below).

**Pasted-text fallback.** When a URL won't fetch (paywall, anti-bot, login, no
captions), or when you simply have the text — copy the article / transcript / key
chart numbers and submit them as a **pasted-text** source. Add its **domain** so
it still counts toward source tiering.

## Troubleshooting

- **AI summaries show a placeholder** — real summaries need `DEEPSEEK_API_KEY` in
  `backend/.env`; the offline tests need no key.
- **Podcast / caption-less YouTube items typed-skip** — real transcription needs
  the optional ML extra: `cd backend && pip install -e '.[ml]'` (the lean Docker
  image omits it; it degrades gracefully without it).
- **Port already in use (8000 / 3000)** — stop a prior `scripts/dev.sh` /
  `docker compose up`, or free the port; `dev.sh` releases both on Ctrl-C.
- **Playwright e2e fails to launch a browser** — install it once:
  `cd frontend && npx playwright install chromium`.
- **A source shows "Could not use"** — that's a typed skip (paywall / anti-bot / no
  captions / …), not a crash; follow the on-screen next step (usually: paste the
  text). The run still completes for the other sources.
- **Start over** — `scripts/reset_local.py` wipes local data (above).

## Out of scope (V1)

Deliberately **not** in V1: multi-user accounts / auth / billing, a mobile or
browser-extension client, real-time push (tracking is hourly polling, only while
your machine is on), automatic "true/false" fact verdicts, topic-wide
auto-discovery of sources (you choose the sources), and native video
understanding / frame sampling. Requests to add these are declined for V1.
