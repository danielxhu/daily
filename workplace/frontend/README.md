# daily — frontend

Next.js 14 (App Router) + Tailwind CSS 3 + TypeScript. React 18.

The frontend is a thin UI over the backend tracking/knowledge API (the check
surface was retired in v0.13 — M16.1); it talks to the stable API contract (`src/types/contract.ts`, codegen'd from the backend) and is
built fixture/mock-first so it never depends on live network during tests.

## Current surface (v0.13 — Stage 16)

Three primary destinations (`Today` / `Sources` / `Knowledge`) plus detail pages;
no `/check` or `/memory` routes (the check surface is retired; its components and
message keys stay in the tree frozen + fenced as DORMANT).

- **Today** (`/`) — date + latest-poll header ("polling is periodic, not
  real-time"), the briefing grouped by board → module, source health.
- **Item detail** (`/items/[id]`) — bilingual AI summary (labeled as restating
  the source), "Source says" excerpt, provenance, related items, an item-bounded
  discussion, fetch-&-summarize for legacy items, and a note into the board's
  Knowledge.
- **Digest** (`/digest`) — the grouped read surface with per-group stats
  (items / sources / latest / tier spread), 7/30/90-day window.
- **Knowledge** (`/knowledge`) — the board-card map (counts per board), module
  drill-down, layered search (tracked items / your notes / distilled AI
  summaries as display-only), and the on-demand AI answer grounded in your own
  notes only.
- **Sources** (`/tracking`) — subscriptions, health, typed failures, starter pack.

Bilingual (en/zh) via `src/lib/messages.ts` — the locale toggle switches
instantly (bilingual enrichment rides in the API payload, no refetch). API
client in `src/lib/api.ts` (typed against the codegen'd `src/types/contract.ts`);
component tests (Vitest) under `src/__tests__/`, browser E2E (Playwright,
desktop + mobile, dedicated port 3100) under `e2e/`.

## Mock mode (no backend)

`npm run dev:mock` sets `NEXT_PUBLIC_API_MOCK=1`, which starts a Mock Service
Worker (`src/mocks/`) that intercepts the whole tracking/knowledge API (digest,
tracked items + detail/refresh/discuss, boards/modules/notes, knowledge
search/answer, subscriptions, runs) with deterministic fixtures — so the UI
develops/demos without the backend running, and the Playwright E2E suite runs
against exactly this build (`npm run e2e` → `build:mock` on port 3100). The same
handlers back the Node test `src/__tests__/mock-api.test.ts`. In a normal `npm run dev` /
`npm run build` the env is unset and the worker never loads.

## Commands

```bash
npm install
npm test            # vitest run (component + unit tests)
npm run typecheck   # tsc --noEmit
npm run build       # next build
npm run dev         # next dev (http://localhost:3000)
```
