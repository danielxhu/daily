# daily

个人信息追踪 + 知识库：把你自己选定的信息源（网页 / RSS / 播客 / YouTube）持续轮询接入，新内容自动摘要、归档、可搜索，并保留来源出处与诚实的处理状态。

Personal information tracking + knowledge base: polls the sources *you* choose (web / RSS / podcast / YouTube), turns new items into summarized, searchable knowledge with provenance and honest typed statuses.

## Repo layout

All product code lives in [workplace/](workplace/):

- `workplace/backend/` — Python FastAPI API (ingestion, tracking, knowledge base, LLM clients) with a fully offline test suite
- `workplace/frontend/` — Next.js + Tailwind UI (Today / Sources / Knowledge), vitest + playwright tests
- `workplace/scripts/` + `workplace/docker-compose.yml` — local run / test / reset scripts

## Quick start

See [workplace/README.md](workplace/README.md) — everything runs fully local; the only paid dependency is the LLM API key you put in `workplace/backend/.env` (template: `.env.example`).
