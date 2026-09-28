# daily

**A local-first tracker for the sources you choose.** Hand it a feed, homepage, podcast, or channel; it polls them on a schedule, turns new items into summarized, searchable knowledge that keeps its provenance, and says out loud when it could not read something.

- **Honest by construction.** AI summaries only restate the source — they never score or rank it. A failed fetch becomes a typed status with a next step, not a silent gap.
- **676 tests, all offline.** 499 backend (the suite bans sockets), 119 component, 58 browser end-to-end against a mocked build. One command runs the whole matrix with zero network and zero API spend.
- **Deterministic code wherever code will do.** Source tiering, duplicate detection, feed recovery, and search are plain Python and SQL. The model writes summaries, drafts notes, and answers questions — it never decides a status.

Everything runs on your own machine: FastAPI, Next.js, SQLite, and a local Chroma index, no account and no cloud. The only paid dependency is the LLM API key you supply.

daily is a personal, non-commercial project. It has no fetch red lines: proxies, cookies and logged-in sessions, archive fallbacks, browser impersonation, and stealth fetchers such as Scrapling's are all fair game wherever they help a source read. Respecting each site's terms and copyright is up to whoever runs it.

Three primary pages carry it — **Today** (what your sources published, on a timeline), **Sources** (what is tracked and how healthy it is), **Knowledge** (your saved notes, and questions answered only from what daily has stored) — with detail pages behind them for a single item, a single note, and the run trace.

---

## Requirements

| | |
|---|---|
| Python | 3.11 or newer. No 3.11 on the machine? `uv python install 3.11` fetches a standalone build. |
| Node | 18 or newer (Next.js 14). |
| Disk | ~2 GB for the Python environment; more if you install the optional audio-transcription extra. |
| An LLM key | Optional to boot, required for real summaries. DeepSeek by default; any OpenAI-compatible endpoint works. |

Everything else — SQLite, the embedding model, Chroma, the scheduler — is local and free.

## Setup

Four steps, two of them one-time installs. **Each block starts from the repository root** — open a fresh shell or `cd` back if you followed the previous one.

**1. Backend**

```bash
cd workplace/backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

**2. Frontend**

```bash
cd workplace/frontend
npm install
npx playwright install chromium   # only needed to run the browser tests
```

**3. Verify the install before adding any key**

```bash
cd workplace
scripts/test-all.sh --no-e2e
```

This runs the whole offline matrix — lint, types, backend tests, component tests, a production build — with no network and no API spend. It should end in `RESULT: PASS`. If it does, the install is sound.

**4. Add your model key**

```bash
cd workplace/backend
cp .env.example .env
```

Put your key in `DEEPSEEK_API_KEY`. The app boots without one; summaries, note drafting, and answers then show a placeholder instead of real text. You can also enter a key in the app's **Settings** page, which stores it in the local database and overrides the file — useful for trying another provider without editing anything.

Optional extras, all off by default:

| Setting | What it buys | Cost |
|---|---|---|
| `pip install -e ".[ml]"` | Real audio transcription (faster-whisper; Metal-accelerated on a Mac). Without it, podcast and caption-less YouTube items typed-skip. | Local only, ~2 GB |
| `ENABLE_HTML_RENDER=true` | A headless-browser fallback for JavaScript-only pages. Needs `npx playwright install chromium`. | Local only, slower polls |
| `pip install -e ".[stealth]" && scrapling install`, then `ENABLE_STEALTH_FETCH=true` | Scrapling's stealth browser as the last web-page tier: gets past Cloudflare challenges, anti-bot 403s, and headless detection. | Local only; up to ~60 s per blocked page |
| `VL_*` | Reading images in a post. Any pluggable vision model, including a local one that needs no key. | Optional |

## Running

```bash
cd workplace
scripts/serve.sh
```

Open **http://localhost:3000**. This is the mode to use day to day: it builds the frontend once and serves it, so navigation is instant. Ctrl-C stops both processes; the script also clears stale ones from an earlier run.

```bash
cd workplace
scripts/dev.sh
```

Use this only while changing frontend code — it hot-reloads, at the cost of a slow first visit to each page.

Either way the backend is on `:8000` (`/docs` for the API), the frontend on `:3000`, and all data lives in `workplace/backend/data/`.

**Containers instead:** `docker compose up` from `workplace/` runs both services with `backend/data/` bind-mounted. Export `DEEPSEEK_API_KEY` in the host shell to pass a key through — it is never baked into an image. The image is the lean install, so audio transcription typed-skips; use the local path above for the full feature set.

## First run

1. Open **Sources** and paste a URL — a feed, a site's homepage, a podcast, or a YouTube channel. daily works out which it is; leave the mode on **auto**.
2. Press **Check for new items**. The first check picks up the latest few items per source rather than the whole archive.
3. Open **Today**. New items appear on a timeline by real publish time, each with its source, tier, and AI summary.
4. Click an item, then **Draft a note** to keep what matters. Saved notes live on **Knowledge**, where you can ask questions that are answered only from your own sources and notes.

While the app runs, sources are re-checked on their own interval (hourly by default). This is polling, not push: close the laptop and it stops. A plain `uvicorn app.main:app` leaves the scheduler off entirely.

## How a source is read, and where it stops

Ingestion is best-effort. A source that cannot be fetched is typed-skipped with a reason and a next step, and the rest of the batch still completes.

- **Web page** — static HTML, then a structured-extraction pass, then a headless render when enabled, then Scrapling's stealth browser when `ENABLE_STEALTH_FETCH` is on. The stealth tier runs whenever the earlier ones hit an anti-bot wall, paywall, login wall, blocked request, or empty page, and its text is labeled `stealth_html`. A wall that survives it typed-skips as `paywall` / `anti_bot` / `login_required` and asks you to paste the text. Hard paywalls usually survive: the article simply is not in the page.
- **Proxy** — the backend honours `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` from the shell that starts it, for page fetches, feeds, and yt-dlp alike.
- **PDF** — text-layer extraction. Scanned, image-only PDFs are not OCR'd.
- **Podcast** — an RSS `<enclosure>` or a direct audio URL, transcribed locally. Arbitrary Apple or Spotify episode *pages* are not promised.
- **YouTube** — captions via `yt-dlp`, falling back to local transcription when there are none. No video is downloaded, so on-screen charts are not read.
- **Pasted text** — the universal fallback. When a URL will not fetch, paste the article, transcript, or key figures yourself; add the domain so it still counts toward source tiering.

## Tests

```bash
cd workplace
scripts/test-all.sh            # everything, including the browser e2e
scripts/test-all.sh --no-e2e   # faster regression
```

Zero network, zero API spend, non-zero exit on any failure. It installs nothing — run the setup above first.

The suite is offline by construction, not by convention: backend tests mock the LLM, transcriber, and browser clients, replay recorded HTTP through `vcrpy` cassettes, and ban sockets in an autouse fixture, so a test that reaches for the network fails loudly. The frontend runs against a mocked API (MSW); the Playwright suite builds in mock mode, owns port 3100, and never reuses an existing server — a stale one used to make every spec time out with no explanation.

Individual tools, from `workplace/backend` with the venv active: `pytest`, `ruff check .`, `ruff format --check .`, `mypy`. From `workplace/frontend`: `npm test`, `npm run typecheck`, `npm run e2e`.

One caveat: `build:mock` replaces `.next`, so restart `scripts/dev.sh` after an e2e run.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Summaries show a placeholder | No model key. Add `DEEPSEEK_API_KEY` to `backend/.env`, or enter one in Settings. |
| Podcast or caption-less YouTube items typed-skip | Transcription needs the optional extra: `pip install -e ".[ml]"`. |
| A source reads "Could not use" | A typed skip, not a crash — paywall, anti-bot, no captions. Follow the on-screen next step; the run completed for every other source. |
| Port 8000 or 3000 in use | An earlier `scripts/dev.sh` or `docker compose up` is still running. Both scripts release their ports on Ctrl-C. |
| Playwright cannot launch a browser | `cd workplace/frontend && npx playwright install chromium`. |
| A source's feed is found but its articles are not | The feed is fine and the article pages refuse automated access. daily falls back to the description the source publishes in its own feed and labels it. |
| Want to start clean | `cd workplace/backend && .venv/bin/python ../scripts/reset_local.py` wipes the local database, the Chroma store, and derived data. Destructive, no backup; `--yes` skips the prompt. |

## Repository layout

```
workplace/
  backend/     FastAPI app — ingestion · tracking · knowledge · LLM and STT clients
    tests/       offline suite (sockets banned); see tests/README.md
    data/        SQLite + Chroma, created on first run
  frontend/    Next.js + Tailwind — today · sources · knowledge · digest · trace
  scripts/     serve.sh · dev.sh · test-all.sh · reset_local.py
  docker-compose.yml
```

Knowledge search runs two channels: deterministic keyword matching, plus a local semantic layer — multilingual sentence-transformers embeddings in a persistent Chroma collection, maintained incrementally by the background worker — so a Chinese query finds an English-summarized item and the reverse. No external vector service; if the index is unavailable, search degrades to keyword-only.

## Out of scope

Deliberately not built: multi-user accounts, auth, or billing; a mobile or browser-extension client; real-time push; automatic true/false verdicts on claims; topic-wide auto-discovery of sources (you choose them); native video understanding.
