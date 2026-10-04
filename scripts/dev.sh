#!/usr/bin/env bash
# Run daily locally (M9.4): backend (FastAPI / uvicorn on :8000) + frontend
# (Next.js on :3000), with local SQLite + Chroma + frames under backend/data.
# Ctrl-C stops both. This is the recommended local path (esp. on a Mac, where the
# optional ML extra uses Metal) — `docker compose up` is the containerized alternative.
#
# One-time setup (see README):
#   backend:  cd backend && python3.11 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'
#             (add the 'ml' extra for clustering / memory / whisper: pip install -e '.[ml]')
#   frontend: cd frontend && npm install
#
# A real verify needs a DeepSeek key in backend/.env (the offline test suite does not).

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

if [ ! -x "$BACKEND/.venv/bin/uvicorn" ]; then
  echo "backend venv/uvicorn missing — run: cd backend && python3.11 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'" >&2
  exit 2
fi
if [ ! -d "$FRONTEND/node_modules" ]; then
  echo "frontend deps missing — run: cd frontend && npm install" >&2
  exit 2
fi

export NEXT_TELEMETRY_DISABLED=1

# self-heal: kill any stale daily processes from a previous run that didn't shut
# down cleanly — orphaned uvicorn/next processes keep polling the same SQLite DB
# (and hold the poll mutex), which surfaces as stuck refreshes and 409s.
pkill -f "uvicorn app.main:app" 2>/dev/null
pkill -f "next dev" 2>/dev/null
sleep 1

pids=()
cleanup() {
  for p in "${pids[@]:-}"; do
    [ -n "$p" ] && kill "$p" 2>/dev/null
  done
}
trap cleanup EXIT INT TERM

# backend: the frontend reaches it at NEXT_PUBLIC_API_BASE_URL (default :8000).
# ENABLE_TRACKING_SCHEDULER turns on the in-process hourly poll (§6.4): tracked
# sources are polled on their interval while this app runs (polling, not push; no
# always-on server). The "Poll now" button / POST /tracking/poll work regardless.
(cd "$BACKEND" && ENABLE_TRACKING_SCHEDULER=true \
  exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000) &
pids+=($!)
# frontend: real (non-mock) dev server against the live backend
(cd "$FRONTEND" && exec npm run dev) &
pids+=($!)

echo ""
echo "daily is starting:"
echo "  backend  → http://localhost:8000  (/health · /config · /verify)"
echo "  frontend → http://localhost:3000  ← open this in your browser"
echo ""
echo "Ctrl-C to stop both."
wait
