#!/usr/bin/env bash
# Run daily in PRODUCTION mode (owner 2026-07-10 "太卡太慢"): `next build` once,
# then `next start` — page navigation drops from seconds (the dev compiler builds
# every route on first visit) to near-instant. Use scripts/dev.sh only when
# actively changing frontend code (it hot-reloads; this doesn't).

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

if [ ! -x "$BACKEND/.venv/bin/uvicorn" ]; then
  echo "backend venv/uvicorn missing — see scripts/dev.sh header for setup" >&2
  exit 2
fi
if [ ! -d "$FRONTEND/node_modules" ]; then
  echo "frontend deps missing — run: cd frontend && npm install" >&2
  exit 2
fi

export NEXT_TELEMETRY_DISABLED=1

# self-heal: clear stale daily processes (orphans keep polling the same SQLite
# DB and hold the poll mutex — stuck refreshes and 409s)
pkill -f "uvicorn app.main:app" 2>/dev/null
pkill -f "next dev" 2>/dev/null
pkill -f "next start" 2>/dev/null
sleep 1

echo "building the frontend (production, ~30-60s once)…"
(cd "$FRONTEND" && npm run build) || exit 1

pids=()
cleanup() {
  for p in "${pids[@]:-}"; do
    [ -n "$p" ] && kill "$p" 2>/dev/null
  done
}
trap cleanup EXIT INT TERM

(cd "$BACKEND" && ENABLE_TRACKING_SCHEDULER=true \
  exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000) &
pids+=($!)
(cd "$FRONTEND" && exec npm run start) &
pids+=($!)

echo ""
echo "daily is running (production mode):"
echo "  backend  → http://localhost:8000"
echo "  frontend → http://localhost:3000  ← open this in your browser"
echo ""
echo "Ctrl-C to stop both."
wait
