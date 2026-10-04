#!/usr/bin/env bash
# Offline full test matrix (M9.1).
#
# Runs the entire backend + frontend + e2e suite with ZERO network and ZERO API
# spend, so a change can be regressed in one command:
#   - backend pytest bans sockets (NFR-3) and uses LLM/VL/transcriber mocks;
#   - frontend vitest mocks fetch; the Playwright e2e runs against a mock build
#     (MSW, NEXT_PUBLIC_API_MOCK=1) with no backend and no real API key;
#   - Next telemetry is disabled so even `next build` makes no network call.
#
# It does NOT install anything (installing would need the network). Run the one-time
# setup first (see README): backend `pip install -e '.[dev]'`, frontend
# `npm install` + `npx playwright install chromium`.
#
# Usage:
#   scripts/test-all.sh            # full matrix (incl. Playwright e2e)
#   scripts/test-all.sh --no-e2e   # skip the browser e2e (faster regression)

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv/bin"

export NEXT_TELEMETRY_DISABLED=1  # keep `next build` offline

RUN_E2E=1
for arg in "$@"; do
  case "$arg" in
    --no-e2e) RUN_E2E=0 ;;
    -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown arg: $arg (try --no-e2e)" >&2; exit 2 ;;
  esac
done

PASS=()
FAIL=()

step() {
  # step "<label>" <command...>
  local label="$1"; shift
  echo ""
  echo "──────────────────────────────────────────────────────────"
  echo "▶ $label"
  echo "──────────────────────────────────────────────────────────"
  if "$@"; then
    PASS+=("$label")
  else
    FAIL+=("$label")
    echo "✗ FAILED: $label"
  fi
}

# --- prerequisites (no install here; just a clear message if missing) ---
if [ ! -x "$VENV/python" ]; then
  echo "backend venv missing at $VENV" >&2
  echo "  run: cd backend && python3.11 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'" >&2
  exit 2
fi
if [ ! -d "$FRONTEND/node_modules" ]; then
  echo "frontend deps missing — run: cd frontend && npm install" >&2
  exit 2
fi

# --- backend (offline: sockets banned in tests, NFR-3) ---
step "backend · ruff check"        bash -c "cd '$BACKEND' && '$VENV/ruff' check ."
step "backend · ruff format check" bash -c "cd '$BACKEND' && '$VENV/ruff' format --check ."
step "backend · mypy (strict)"     bash -c "cd '$BACKEND' && '$VENV/mypy' app tests"
step "backend · pytest"            bash -c "cd '$BACKEND' && '$VENV/pytest'"

# --- frontend (offline: component tests + production build) ---
step "frontend · typecheck"        bash -c "cd '$FRONTEND' && npm run typecheck"
step "frontend · vitest"           bash -c "cd '$FRONTEND' && npm run test"
step "frontend · build"            bash -c "cd '$FRONTEND' && npm run build"

# --- e2e (offline: mock build via MSW, no backend) ---
if [ "$RUN_E2E" -eq 1 ]; then
  step "frontend · playwright e2e" bash -c "cd '$FRONTEND' && npx playwright test"
fi

# --- summary ---
echo ""
echo "=========================================================="
echo "Test matrix summary"
echo "=========================================================="
for s in "${PASS[@]:-}"; do [ -n "$s" ] && echo "  ✓ $s"; done
for s in "${FAIL[@]:-}"; do [ -n "$s" ] && echo "  ✗ $s"; done
echo ""
if [ "${#FAIL[@]}" -gt 0 ]; then
  echo "RESULT: FAIL (${#FAIL[@]} failed, ${#PASS[@]} passed)"
  exit 1
fi
echo "RESULT: PASS (${#PASS[@]} passed)"
