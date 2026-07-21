"""FastAPI app shell (M2.1, SSOT §9.4).

The backend's HTTP entry point: an app factory with injectable `Settings`, a
`/health` probe, a `/config` endpoint exposing only **non-secret** operational
config (model names, prompt version, feature flags — never API keys), and CORS
for the local frontend. Endpoints that surface credibility / memory / boards are
later stages; this shell deliberately exposes none of them.

Run with `uvicorn app.main:app`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal, cast

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from app.clients.base import LLMClient
from app.clients.deepseek import get_llm_client
from app.core.config import (
    DIGEST_WINDOW_DAYS,
    PROMPT_VERSION,
    SEED,
    Settings,
    get_settings,
)
from app.db.board_store import create_board, delete_board, get_board, list_boards
from app.db.engine import init_db
from app.db.knowledge_module_store import (
    create_module,
    delete_module,
    get_module,
    list_modules,
)
from app.db.knowledge_store import (
    HumanNoteKind,
    create_note,
    delete_note,
    list_notes,
    search_saved_notes,
)
from app.db.run_trace import list_runs
from app.db.subscription_store import (
    create_subscription,
    delete_subscription,
    get_subscription,
    list_subscriptions,
    set_subscription_module,
    set_subscription_name,
)
from app.db.tracked_item_store import (
    get_item_excerpt,
    get_tracked_item_row,
    search_tracked_items,
    tracked_item_card_by_id,
)
from app.discuss import DiscussError, discuss_tracked_item, draft_item_note
from app.ingestion import progress as transcribe_progress
from app.ingestion.ingest import IngestFn
from app.knowledge.answer import MAX_ANSWER_ITEMS, answer_from_hits
from app.knowledge.semantic import get_semantic_index, resolve_hits
from app.schemas.models import (
    Board,
    DailyDigest,
    IngestionResult,
    ItemDiscussReply,
    ItemDiscussRequest,
    ItemNoteDraftReply,
    ItemNoteDraftRequest,
    ItemProgress,
    KnowledgeAnswer,
    KnowledgeAnswerRequest,
    KnowledgeModule,
    KnowledgeNote,
    KnowledgeSearchResult,
    PipelineRun,
    SourcePackEntry,
    SourceRequest,
    Subscription,
    TrackedItemCard,
    TrackedItemDetail,
)
from app.source_pack import default_source_pack
from app.tracking.digest import assemble_digest, digest_to_rss
from app.tracking.poll import Fetch
from app.tracking.refresh import RefreshError, RefreshFailedError, refresh_item
from app.tracking.runtime import (
    PollInProgressError,
    PollReport,
    poll_due_subscriptions,
    run_poll,
)
from app.tracking.scheduler import PollScheduler
from app.tracking.seed import adopt_source_pack

DIGEST_WINDOW_MAX_DAYS = 365  # the recent-view window is bounded


class BoardCreateRequest(BaseModel):
    """Create a topic board (M6.1 / FR-15). Request-only (not a §7 contract type)."""

    model_config = ConfigDict(extra="forbid")

    name: str


class NoteCreateRequest(BaseModel):
    """Create a human knowledge note (M6.3 / FR-15). `kind` is restricted to the
    human kinds — `ai_distilled` is generated server-side (M6.4), never posted here.
    Request-only (not a §7 contract type)."""

    model_config = ConfigDict(extra="forbid")

    kind: HumanNoteKind
    content: str
    citations: list[str] = []


class SubscriptionCreateRequest(BaseModel):
    """Create a tracking subscription (M7.1 / FR-3). Request-only (not a §7 contract
    type). Tracking polls operator-given sources — it never discovers sources by
    topic (§2.2). The poll machinery resolves feeds + fills health later."""

    model_config = ConfigDict(extra="forbid")

    input_url: str
    mode: Literal["direct", "autodiscover", "platform", "homepage_diff"]
    board_id: str | None = None
    module_id: str | None = None  # M15.1: the source's module within its board
    name: str | None = None  # user-given display name (2026-07-19); None = unnamed
    feed_url: str | None = None
    interval_minutes: int = Field(default=60, ge=1)


class ModuleCreateRequest(BaseModel):
    """Create a knowledge module inside a board (M15.1 / FR-15). Request-only."""

    model_config = ConfigDict(extra="forbid")

    name: str


class ModuleAssignRequest(BaseModel):
    """Assign a source to a module (M15.1) — None un-groups. Request-only."""

    model_config = ConfigDict(extra="forbid")

    module_id: str | None = None


class SubscriptionRenameRequest(BaseModel):
    """Rename a source (2026-07-19) — None/empty clears back to unnamed."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None


def get_llm() -> LLMClient:
    """LLM dependency (overridden with a mock in tests)."""
    return get_llm_client()


def get_ingest() -> IngestFn:
    """Per-source ingestion dependency (overridden with a fake in tests)."""
    from app.ingestion.ingest import ingest_one

    return ingest_one


def get_ingest_first() -> IngestFn:
    """First-poll ingestion (M14.5): captions process, whisper transcription defers
    (typed `transcription_deferred`, item re-queued) so a subscription's first check
    answers in minutes. Overridden with a fake in tests."""
    from app.ingestion.ingest import ingest_one

    def first(req: SourceRequest) -> IngestionResult:
        return ingest_one(req, allow_transcription=False)

    return first


def get_feed_fetch() -> Fetch:
    """Feed/homepage fetcher dependency for the poll runtime (the real httpx GET).
    Overridden with a fake `(url) -> bytes` in tests so polling stays offline (NFR-3)."""
    from app.tracking.fetch import feed_fetch

    return feed_fetch


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """Per-request SQLite connection over the full local schema (trace + memory +
    boards + tracking + events). Reads the path from the app-injected `Settings`
    (`create_app(settings=...)`, M2.1) — NOT the global settings — so config
    injection holds and tests/local runs don't write the default data dir. Opened on
    the request thread so writes stay single-threaded."""
    settings: Settings = request.app.state.settings
    conn = init_db(settings.sqlite_path)
    try:
        yield conn
    finally:
        conn.close()


def public_config(settings: Settings) -> dict[str, Any]:
    """Non-secret operational config for the UI / debugging. NEVER include the
    DeepSeek / VL API keys."""
    return {
        "prompt_version": PROMPT_VERSION,
        "seed": SEED,
        "models": {
            "text_flash": settings.deepseek_flash_model,
            "text_pro": settings.deepseek_pro_model,
            "whisper": settings.whisper_model_size,
        },
        "features": {
            "pdf_text": settings.enable_pdf_text,
            "html_render": settings.enable_html_render,
        },
    }


# detail-page "Source says" preview — display cut, not the stored cap (M16.4)
_EXCERPT_PREVIEW_CHARS = 2000


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app. `settings` is injectable so tests configure it
    without environment/secrets."""
    settings = settings or get_settings()

    def _real_poll_tick() -> None:
        """One scheduler tick: poll the CURRENTLY-due subscriptions through the live
        runtime with the real clients. Re-reads subscriptions from the DB each tick
        (so sources added/removed after startup are handled). Runs off the request
        thread, so it opens its own SQLite connection. Errors are isolated inside
        `run_poll` (per-source) and never crash the scheduler thread."""
        from app.clients.deepseek import get_llm_client
        from app.ingestion.ingest import ingest_one
        from app.tracking.fetch import feed_fetch

        conn = init_db(settings.sqlite_path)
        try:
            poll_due_subscriptions(
                conn,
                llm=get_llm_client(),
                fetch=feed_fetch,
                ingest=ingest_one,
                ingest_first=get_ingest_first(),
            )
        finally:
            conn.close()

    def _real_enrich_tick() -> None:
        """One background-enrichment tick (owner 2026-07-10): pending items get
        their text/summary WITHOUT the user clicking. Own SQLite connection (off
        the request thread); errors never crash the scheduler."""
        from app.clients.deepseek import get_llm_client
        from app.ingestion.ingest import ingest_one
        from app.tracking.worker import work_once

        conn = init_db(settings.sqlite_path)
        try:
            work_once(
                conn,
                llm=get_llm_client(),
                ingest=get_ingest_first(),  # articles: fast path, whisper deferred
                transcribe_ingest=ingest_one,  # deferred audio/video: full path
                semantic_index=get_semantic_index(),  # None = feature off
            )
        except Exception:  # noqa: BLE001 — a tick must never kill the scheduler
            pass
        finally:
            conn.close()

    @asynccontextmanager
    async def lifespan(app_: FastAPI) -> AsyncIterator[None]:
        """In-process hourly poll scheduler (§6.4): polling, not push — runs only while
        the host is on, no always-on server. ONE recurring tick re-reads the current
        subscriptions and polls the due ones, so sources added/removed in the UI after
        startup are handled without a restart. OFF unless `enable_tracking_scheduler`,
        so a plain `uvicorn`/test never spawns it. The backend + tick runner are read
        from `app.state` so a test injects a fake scheduler backend + runner and drives
        a tick deterministically (the manual POST /tracking/poll is always on)."""
        scheduler: PollScheduler | None = None
        if settings.enable_tracking_scheduler:
            backend = getattr(app_.state, "scheduler_backend", None)
            runner = getattr(app_.state, "poll_runner", None) or _real_poll_tick
            scheduler = PollScheduler(backend=backend)
            scheduler.schedule_tick(runner, minutes=settings.poll_tick_minutes)
            enrich_runner = getattr(app_.state, "enrich_runner", None) or _real_enrich_tick
            scheduler.schedule_enrich_tick(enrich_runner, seconds=30)
            scheduler.start()
            app_.state.scheduler = scheduler
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown()

    app = FastAPI(title="daily", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/config")
    def config() -> dict[str, Any]:
        return public_config(settings)

    @app.get("/source-pack", response_model=list[SourcePackEntry])
    def source_pack() -> list[SourcePackEntry]:
        """The built-in editable default source-pack (FR-3) — seeds a board's
        tracking on cold start. Static; not topic-wide web discovery."""
        return default_source_pack()

    @app.post("/source-pack/adopt")
    def source_pack_adopt(
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> dict[str, Any]:
        # M14.1 (owner 2026-07-06): Day-1 auto-fill — adopt the whole STATIC pack as
        # subscriptions ONCE ever (D8: never topic discovery). The one-time flag, not
        # the subscription count, gates it: a user who deleted everything keeps an
        # empty list. `seeded` False tells the UI this was a deliberate clean slate.
        created = adopt_source_pack(db)
        return {
            "seeded": len(created) > 0,
            "subscriptions": [s.model_dump(mode="json") for s in created],
        }

    @app.get("/boards", response_model=list[Board])
    def boards(db: Annotated[sqlite3.Connection, Depends(get_db)]) -> list[Board]:
        return list_boards(db)

    @app.post(
        "/boards",
        response_model=Board,
        status_code=201,
        responses={400: {"description": "Empty board name."}},
    )
    def create_board_endpoint(
        body: BoardCreateRequest,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> Board:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="board 'name' must be non-empty")
        return create_board(db, name)

    @app.get(
        "/boards/{board_id}",
        response_model=Board,
        responses={404: {"description": "No such board."}},
    )
    def get_board_endpoint(
        board_id: str,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> Board:
        board = get_board(db, board_id)
        if board is None:
            raise HTTPException(status_code=404, detail=f"no such board: {board_id}")
        return board

    @app.delete(
        "/boards/{board_id}",
        status_code=204,
        responses={404: {"description": "No such board."}},
    )
    def delete_board_endpoint(
        board_id: str,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> None:
        # deleting a board removes only the grouping, never the shared facts (M6.2)
        if not delete_board(db, board_id):
            raise HTTPException(status_code=404, detail=f"no such board: {board_id}")

    # --- knowledge modules (M15.1, v0.12 / FR-15): board → module → source → item ---

    @app.get(
        "/boards/{board_id}/modules",
        response_model=list[KnowledgeModule],
        responses={404: {"description": "No such board."}},
    )
    def list_modules_endpoint(
        board_id: str,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> list[KnowledgeModule]:
        if get_board(db, board_id) is None:
            raise HTTPException(status_code=404, detail=f"no such board: {board_id}")
        return list_modules(db, board_id)

    @app.post(
        "/boards/{board_id}/modules",
        response_model=KnowledgeModule,
        status_code=201,
        responses={
            400: {"description": "Empty module name."},
            404: {"description": "No such board."},
        },
    )
    def create_module_endpoint(
        board_id: str,
        body: ModuleCreateRequest,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> KnowledgeModule:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="module 'name' must be non-empty")
        if get_board(db, board_id) is None:
            raise HTTPException(status_code=404, detail=f"no such board: {board_id}")
        return create_module(db, board_id=board_id, name=name)

    @app.delete(
        "/modules/{module_id}",
        status_code=204,
        responses={404: {"description": "No such module."}},
    )
    def delete_module_endpoint(
        module_id: str,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> None:
        # deleting a module only UN-groups its sources/items — content stays (M15.1)
        if not delete_module(db, module_id):
            raise HTTPException(status_code=404, detail=f"no such module: {module_id}")

    @app.put(
        "/subscriptions/{subscription_id}/module",
        response_model=Subscription,
        responses={
            400: {"description": "Module belongs to a different board than the source."},
            404: {"description": "No such subscription or module."},
        },
    )
    def assign_subscription_module(
        subscription_id: str,
        body: ModuleAssignRequest,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> Subscription:
        # assign a source to a module in ITS board (None un-groups); items inherit
        # the module at discovery time, so future items land in the right place
        sub = get_subscription(db, subscription_id)
        if sub is None:
            raise HTTPException(status_code=404, detail=f"no such subscription: {subscription_id}")
        if body.module_id is not None:
            module = get_module(db, body.module_id)
            if module is None:
                raise HTTPException(status_code=404, detail=f"no such module: {body.module_id}")
            if module.board_id != sub.board_id:
                raise HTTPException(
                    status_code=400,
                    detail="module belongs to a different board than this source",
                )
        updated = set_subscription_module(db, subscription_id, body.module_id)
        assert updated is not None  # existence checked above
        return updated

    @app.get(
        "/boards/{board_id}/notes",
        response_model=list[KnowledgeNote],
        responses={404: {"description": "No such board."}},
    )
    def board_notes(
        board_id: str,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> list[KnowledgeNote]:
        if get_board(db, board_id) is None:
            raise HTTPException(status_code=404, detail=f"no such board: {board_id}")
        return list_notes(db, board_id)

    @app.post(
        "/boards/{board_id}/notes",
        response_model=KnowledgeNote,
        status_code=201,
        responses={
            400: {"description": "Empty content, or pinned_fact without a citation."},
            404: {"description": "No such board."},
        },
    )
    def create_board_note(
        board_id: str,
        body: NoteCreateRequest,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> KnowledgeNote:
        if get_board(db, board_id) is None:
            raise HTTPException(status_code=404, detail=f"no such board: {board_id}")
        if not body.content.strip():
            raise HTTPException(status_code=400, detail="note 'content' must be non-empty")
        return create_note(db, board_id, body.kind, body.content, citations=body.citations)

    @app.delete(
        "/boards/{board_id}/notes/{note_id}",
        status_code=204,
        responses={404: {"description": "No such board, or note not in this board."}},
    )
    def delete_board_note(
        board_id: str,
        note_id: str,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> None:
        # the path's board_id is authoritative: a note can only be deleted through its
        # own board (no cross-board / ghost-board deletes).
        if get_board(db, board_id) is None:
            raise HTTPException(status_code=404, detail=f"no such board: {board_id}")
        if not delete_note(db, board_id, note_id):
            raise HTTPException(
                status_code=404, detail=f"no such note in board {board_id}: {note_id}"
            )

    @app.get("/subscriptions", response_model=list[Subscription])
    def subscriptions(
        db: Annotated[sqlite3.Connection, Depends(get_db)],
        board_id: str | None = None,
    ) -> list[Subscription]:
        # all subscriptions, or just one board's when board_id is given
        return list_subscriptions(db, board_id=board_id)

    @app.post(
        "/subscriptions",
        response_model=Subscription,
        status_code=201,
        responses={
            400: {"description": "Empty input_url."},
            404: {"description": "No such board."},
        },
    )
    def create_subscription_endpoint(
        body: SubscriptionCreateRequest,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> Subscription:
        url = body.input_url.strip()
        if not url:
            raise HTTPException(
                status_code=400, detail="subscription 'input_url' must be non-empty"
            )
        # a board-scoped subscription must reference a real board (else the FK would
        # fail at insert); a board_id of None is a standalone tracked source.
        if body.board_id is not None and get_board(db, body.board_id) is None:
            raise HTTPException(status_code=404, detail=f"no such board: {body.board_id}")
        if body.module_id is not None:  # M15.1: module must exist IN the source's board
            module = get_module(db, body.module_id)
            if module is None:
                raise HTTPException(status_code=404, detail=f"no such module: {body.module_id}")
            if module.board_id != body.board_id:
                raise HTTPException(
                    status_code=400,
                    detail="module belongs to a different board than this source",
                )
        return create_subscription(
            db,
            input_url=url,
            mode=body.mode,
            board_id=body.board_id,
            module_id=body.module_id,
            name=(body.name or "").strip() or None,
            feed_url=body.feed_url,
            interval_minutes=body.interval_minutes,
        )

    @app.put(
        "/subscriptions/{subscription_id}/name",
        response_model=Subscription,
        responses={404: {"description": "No such subscription."}},
    )
    def rename_subscription_endpoint(
        subscription_id: str,
        body: SubscriptionRenameRequest,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> Subscription:
        # owner 2026-07-19 "全是url不知道哪个是哪个": a display name per source;
        # empty/None clears back to unnamed (the UI falls back to the URL)
        if get_subscription(db, subscription_id) is None:
            raise HTTPException(status_code=404, detail=f"no such subscription: {subscription_id}")
        updated = set_subscription_name(db, subscription_id, (body.name or "").strip() or None)
        assert updated is not None  # existence checked above
        return updated

    @app.delete(
        "/subscriptions/{subscription_id}",
        status_code=204,
        responses={404: {"description": "No such subscription."}},
    )
    def delete_subscription_endpoint(
        subscription_id: str,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> None:
        if not delete_subscription(db, subscription_id):
            raise HTTPException(status_code=404, detail=f"no such subscription: {subscription_id}")

    @app.post("/tracking/poll", response_model=PollReport)
    def tracking_poll(
        llm: Annotated[LLMClient, Depends(get_llm)],
        fetch: Annotated[Fetch, Depends(get_feed_fetch)],
        ingest: Annotated[IngestFn, Depends(get_ingest)],
        ingest_first: Annotated[IngestFn, Depends(get_ingest_first)],
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> PollReport:
        # FR-3 / §6.2: poll every subscription now — discover, fetch, excerpt,
        # bilingual briefing. The in-process scheduler runs the same `run_poll` on
        # each subscription's interval; this is the manual trigger. One source
        # failing never blocks the others (§6.6). M14.4: one poll at a time — a
        # concurrent trigger gets an honest 409, never a misleading all-0 report.
        try:
            return run_poll(
                db,
                llm=llm,
                fetch=fetch,
                ingest=ingest,
                ingest_first=ingest_first,
            )
        except PollInProgressError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(
        "/tracked-items/{item_id}",
        response_model=TrackedItemDetail,
        responses={404: {"description": "No such tracked item."}},
    )
    def tracked_item_detail(
        item_id: str,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> TrackedItemDetail:
        # M16.4: the item detail page — card + source excerpt preview. Read-only,
        # deterministic, zero LLM. (Provenance/related left the page 2026-07-13.)
        card = tracked_item_card_by_id(db, item_id)
        if card is None:
            raise HTTPException(status_code=404, detail=f"no such tracked item: {item_id}")
        row = get_tracked_item_row(db, item_id)
        assert row is not None
        excerpt = row["content_excerpt"]
        return TrackedItemDetail(
            item=card,
            excerpt_preview=excerpt[:_EXCERPT_PREVIEW_CHARS] if excerpt else None,
        )

    @app.post(
        "/tracked-items/{item_id}/refresh",
        response_model=TrackedItemDetail,
        responses={
            400: {"description": "The item has no URL to re-fetch."},
            404: {"description": "No such tracked item."},
            409: {"description": "A source poll is already running."},
            502: {"description": "Fetch or summary generation failed — retryable."},
        },
    )
    def refresh_endpoint(
        item_id: str,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
        llm: Annotated[LLMClient, Depends(get_llm)],
        # whisper-free ingest (2026-07-19): a manual refresh must return in
        # seconds — caption-less video goes to the background transcribe queue
        ingest: Annotated[IngestFn, Depends(get_ingest_first)],
    ) -> TrackedItemDetail:
        # M16.4: manual fetch-&-summarize — the way a legacy (pre-v0.13) item gets
        # its bilingual enrichment and discussion grounding. NOT a deep check: no
        # claims, no scoring, no memory writes (the engine stays dormant).
        try:
            card = refresh_item(db, item_id, llm=llm, ingest=ingest)
        except RefreshError as exc:
            status = 404 if "no such tracked item" in str(exc) else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except PollInProgressError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RefreshFailedError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if card.status == "deferred":
            # the user explicitly asked — refresh the worker's per-run attempt
            # budget so background transcription retries now, not next restart
            from app.tracking.worker import reset_attempts

            reset_attempts(item_id)
        return tracked_item_detail(item_id, db)

    @app.get(
        "/tracked-items/{item_id}/progress",
        response_model=ItemProgress,
        responses={404: {"description": "No such tracked item."}},
    )
    def item_progress(
        item_id: str,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
    ) -> ItemProgress:
        # owner 2026-07-21 "加个进度条": live download/transcribe progress for
        # THIS item, matched on its URL against the single in-flight job slot.
        # stage None = not being worked on right now (queued / done / restarted).
        card = tracked_item_card_by_id(db, item_id)
        if card is None:
            raise HTTPException(status_code=404, detail=f"no such tracked item: {item_id}")
        snap = transcribe_progress.snapshot(card.url) if card.url else None
        if snap is None:
            return ItemProgress(stage=None, pct=None)
        stage, pct = snap
        if stage in ("downloading", "transcribing"):
            return ItemProgress(stage=cast(Literal["downloading", "transcribing"], stage), pct=pct)
        return ItemProgress(stage=None, pct=None)  # future-proof the Literal

    @app.post(
        "/tracked-items/{item_id}/discuss",
        response_model=ItemDiscussReply,
        responses={
            400: {
                "description": "Messages malformed, or the item has no stored "
                "source text yet (fetch & summarize first)."
            },
            404: {"description": "No such tracked item."},
            502: {"description": "Discussion (LLM) failed."},
        },
    )
    def item_discuss(
        item_id: str,
        body: ItemDiscussRequest,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
        llm: Annotated[LLMClient, Depends(get_llm)],
    ) -> ItemDiscussReply:
        # M16.5: chat about ONE tracked item — the second half of the owner's
        # "点进任何一条信息都可以和 chat 讨论". NFR-7 exception (4): grounded ONLY
        # in the item's persisted excerpt + enrichment + card metadata (the
        # dormant fact layer / scores / other items never enter the prompt),
        # answers 证据不足 beyond them. READ-ONLY: never writes, never cached.
        last = body.messages[-1] if body.messages else None
        if last is None or last.role != "user" or not last.content.strip():
            raise HTTPException(
                status_code=400, detail="messages must end with a non-empty user turn"
            )
        card = tracked_item_card_by_id(db, item_id)
        if card is None:
            raise HTTPException(status_code=404, detail=f"no such tracked item: {item_id}")
        excerpt = get_item_excerpt(db, item_id)
        if excerpt is None:
            raise HTTPException(
                status_code=400,
                detail="this item has no stored source text yet — "
                "run fetch-&-summarize (refresh) first",
            )
        try:
            reply = discuss_tracked_item(card, excerpt, body.messages, llm=llm)
        except DiscussError as exc:
            raise HTTPException(status_code=502, detail=f"discussion failed: {exc}") from exc
        return ItemDiscussReply(reply=reply)

    @app.post(
        "/tracked-items/{item_id}/note-draft",
        response_model=ItemNoteDraftReply,
        responses={
            400: {
                "description": "Messages malformed, or the item has no stored "
                "source text yet (fetch & summarize first)."
            },
            404: {"description": "No such tracked item."},
            502: {"description": "Note drafting (LLM) failed."},
        },
    )
    def item_note_draft(
        item_id: str,
        body: ItemNoteDraftRequest,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
        llm: Annotated[LLMClient, Depends(get_llm)],
    ) -> ItemNoteDraftReply:
        # 2026-07-13 (owner): the note saved to Knowledge is LLM-curated first —
        # the user revises it through chat, then saves the final text via the
        # notes endpoint. Same grounding as /discuss (persisted excerpt +
        # enrichment only). READ-ONLY: drafting never writes anything.
        if body.messages:
            last = body.messages[-1]
            if last.role != "user" or not last.content.strip():
                raise HTTPException(
                    status_code=400,
                    detail="revision messages must end with a non-empty user turn",
                )
        card = tracked_item_card_by_id(db, item_id)
        if card is None:
            raise HTTPException(status_code=404, detail=f"no such tracked item: {item_id}")
        excerpt = get_item_excerpt(db, item_id)
        if excerpt is None:
            raise HTTPException(
                status_code=400,
                detail="this item has no stored source text yet — "
                "run fetch-&-summarize (refresh) first",
            )
        try:
            draft = draft_item_note(card, excerpt, body.messages, locale=body.locale, llm=llm)
        except DiscussError as exc:
            raise HTTPException(status_code=502, detail=f"note drafting failed: {exc}") from exc
        return ItemNoteDraftReply(draft=draft)

    # --- daily digest (FR-13): read-only JSON / RSS over the tracked-items channel ---

    def _digest_response(built: DailyDigest, fmt: str) -> DailyDigest | Response:
        if fmt == "rss":
            return Response(content=digest_to_rss(built), media_type="application/rss+xml")
        return built

    @app.get(
        "/api/digest",
        response_model=None,
        responses={200: {"description": "Source tracking digest (JSON, or RSS with ?format=rss)."}},
    )
    def digest(
        db: Annotated[sqlite3.Connection, Depends(get_db)],
        board_id: str | None = None,
        window_days: int = DIGEST_WINDOW_DAYS,
        format: Literal["json", "rss"] = "json",
    ) -> DailyDigest | Response:
        # the recent-view digest as of now (M14.6: default 30 days, user-adjustable —
        # "近期的所有变化,默认一个月"). Read-only and cache-only (M14.7): a page
        # open never calls the LLM (that work is the poll's / the worker's).
        if not 1 <= window_days <= DIGEST_WINDOW_MAX_DAYS:
            raise HTTPException(
                status_code=400,
                detail=f"window_days must be 1–{DIGEST_WINDOW_MAX_DAYS}, got {window_days}",
            )
        built = assemble_digest(
            db,
            now=datetime.now(UTC),
            board_id=board_id,
            window_days=window_days,
        )
        return _digest_response(built, format)

    @app.get(
        "/api/digest/{digest_date}",
        response_model=None,
        responses={200: {"description": "Source tracking digest for a UTC date (JSON or RSS)."}},
    )
    def digest_for_date(
        digest_date: date,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
        board_id: str | None = None,
        format: Literal["json", "rss"] = "json",
    ) -> DailyDigest | Response:
        # the digest scoped to one UTC date: items discovered within [date, date+1d)
        since = datetime(digest_date.year, digest_date.month, digest_date.day, tzinfo=UTC)
        until = since + timedelta(days=1)
        built = assemble_digest(db, now=until, board_id=board_id, since=since, until=until)
        return _digest_response(built, format)

    @app.get(
        "/knowledge/search",
        response_model=KnowledgeSearchResult,
        responses={400: {"description": "Empty query."}},
    )
    def knowledge_search(
        db: Annotated[sqlite3.Connection, Depends(get_db)],
        q: str,
    ) -> KnowledgeSearchResult:
        # M16.2: no LLM in the request path (the synchronous answer synthesis was
        # the owner's "search is very slow"; the answer moved to POST
        # /knowledge/answer). 2026-07-21: keyword hits first, then semantic
        # recall (one local query embedding, ~ms) merged in — this is what lets
        # a Chinese query find an English-summarized item. facts stays [] (v0.13).
        if not q.strip():
            raise HTTPException(status_code=400, detail="query 'q' must be non-empty")
        saved = search_saved_notes(db, q)
        items = search_tracked_items(db, q)
        saved, items = _merge_semantic_hits(db, q, saved, items)
        return KnowledgeSearchResult(saved=saved, items=items)

    def _merge_semantic_hits(
        db: sqlite3.Connection,
        q: str,
        saved: list[KnowledgeNote],
        items: list[TrackedItemCard],
    ) -> tuple[list[KnowledgeNote], list[TrackedItemCard]]:
        # semantic recall (owner 2026-07-21): local Chroma + multilingual
        # embeddings, feature-gated; keyword hits keep their rank, semantic-only
        # hits are appended. Any index failure = keyword results unchanged.
        index = get_semantic_index()
        if index is None:
            return saved, items
        sem_notes, sem_items = resolve_hits(db, index.search(q))
        seen_notes = {n.id for n in saved}
        seen_items = {i.id for i in items}
        saved = saved + [n for n in sem_notes if n.id not in seen_notes]
        items = items + [i for i in sem_items if i.id not in seen_items]
        return saved, items

    @app.post(
        "/knowledge/answer",
        response_model=KnowledgeAnswer,
        responses={
            400: {"description": "Empty question."},
            502: {"description": "The synthesis call failed — retryable."},
        },
    )
    def knowledge_answer(
        db: Annotated[sqlite3.Connection, Depends(get_db)],
        llm: Annotated[LLMClient, Depends(get_llm)],
        body: KnowledgeAnswerRequest,
    ) -> KnowledgeAnswer:
        # M16.2: the AI answer is an explicit user action (NFR-7 exception (5)).
        # Grounding = the user's saved notes + tracked-item summaries (owner
        # 2026-07-19: notes-only starved the answer of most of the knowledge
        # base). No hits at all → no LLM call; a failed call is a typed 502
        # because the user asked.
        q = body.q.strip()
        if not q:
            raise HTTPException(status_code=400, detail="question 'q' must be non-empty")
        saved = search_saved_notes(db, q)
        items = search_tracked_items(db, q)
        # the answer grounds on the same recall as the search surface (2026-07-21)
        saved, items = _merge_semantic_hits(db, q, saved, items)
        if not saved and not items:
            return KnowledgeAnswer(answer=None, based_on=0)
        answer = answer_from_hits(q, saved, items, llm=llm)
        if answer is None:
            raise HTTPException(status_code=502, detail="answer synthesis failed — try again")
        return KnowledgeAnswer(
            answer=answer, based_on=len(saved) + min(len(items), MAX_ANSWER_ITEMS)
        )

    # --- run trace (§4/§7): read-only debug list of verify/poll/digest runs ---

    @app.get("/api/runs", response_model=list[PipelineRun])
    def runs(
        db: Annotated[sqlite3.Connection, Depends(get_db)],
        limit: int = 50,
    ) -> list[PipelineRun]:
        # newest first, each with its ordered steps — a half-failed run is inspectable
        return list_runs(db, limit=max(1, min(limit, 200)))

    return app


app = create_app()
