# daily

**A local-first tracker for the sources you choose.** Hand it a feed, homepage, podcast, or channel; it polls them on a schedule, turns new items into summarized, searchable knowledge that keeps its provenance, and says out loud when it could not read something.

- **Honest by construction.** AI summaries only restate the source — they never score or rank it. Paywalls, logins, and anti-bot walls are never worked around: a failed fetch becomes a typed status with a next step, not a silent gap.
- **676 tests, all offline.** 499 backend (the suite bans sockets), 119 component, 58 browser end-to-end against a mocked build. One command runs the whole matrix with zero network and zero API spend.
- **Deterministic code wherever code will do.** Source tiering, duplicate detection, feed recovery, and search are plain Python and SQL. The model writes summaries, drafts notes, and answers questions — it never decides a status.

Everything runs on your own machine. No account, no cloud; the only paid dependency is the LLM API key you put in `workplace/backend/.env`.

个人信息追踪 + 知识库:把你自己选定的信息源(网页 / RSS / 播客 / YouTube)持续轮询接入,新内容自动摘要、归档、可搜索,并保留来源出处与诚实的处理状态。

## Repo layout

All product code lives in [workplace/](workplace/):

- `workplace/backend/` — Python FastAPI API (ingestion, tracking, knowledge base, LLM clients) with a fully offline test suite
- `workplace/frontend/` — Next.js + Tailwind UI (Today / Sources / Knowledge), vitest + playwright tests
- `workplace/scripts/` + `workplace/docker-compose.yml` — local run / test / reset scripts

## Quick start

See [workplace/README.md](workplace/README.md) — everything runs fully local; the only paid dependency is the LLM API key you put in `workplace/backend/.env` (template: `.env.example`).
