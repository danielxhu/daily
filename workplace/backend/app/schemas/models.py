"""Shared schema contract (X0.4) — the field-level data models from SSOT §7.

This is the single source of truth for the API/pipeline data shapes; the JSON-Schema
snapshot and the generated frontend TypeScript types (see `codegen.py`) both derive
from these classes, so backend and frontend cannot silently drift. Field names,
types, defaults, and the documented invariants mirror §7 exactly — when §7 changes,
this file changes first.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

# --- shared enum aliases (§7) ---
SourceFailureKind = Literal[
    "fetch_blocked",
    "paywall",
    "login_required",
    "anti_bot",
    "no_captions",
    "transcribe_failed",
    "js_render_failed",
    "parse_empty",
    "unsupported_file",
    "timeout",
    # M14.5: a FIRST check defers whisper transcription (delayed processing, not a
    # failure) — the item re-queues and the next check transcribes it. Captions
    # still process on the first check; only the slow local-whisper path defers.
    "transcription_deferred",
]

SubscriptionFailureKind = Literal[
    "gone",
    "rate_limited",
    "parse_or_render_unfit",
    "network",
    "system_anomaly",
    # M13.1: the feed itself is fine but the listed articles can't be fetched
    # (anti-bot / paywall on the article pages) — the Fed-feed silent-failure case.
    "items_unfetchable",
]

SourceType = Literal["webpage", "podcast", "youtube", "text", "pdf"]
Origin = Literal["user", "fetched"]
CitationType = Literal["primary", "cited", "republished"]
Tier = Literal["T1", "T1.5", "T2"]
ExtractionMethod = Literal[
    "static_html",
    "structured_html",
    "rendered_html",
    "pdf_text",
    "caption",
    "whisper",
    "pasted_text",
    "frame_ocr",
]


class Schema(BaseModel):
    """Shared base: forbid unknown fields so contract drift fails loudly."""

    model_config = ConfigDict(extra="forbid")


class Source(Schema):
    id: str
    type: SourceType
    # "fetched" = CASR authoritative evidence (FR-16); excluded from K_raw/N_counted
    origin: Origin = "user"
    url: str | None
    domain: str | None  # URL host or validated declared_domain; independence input
    raw_text: str
    fetched_at: datetime
    reputation_prior: float = 0.5  # SCALE [0,1]; static tier + human only (FR-9)
    citation_type: CitationType = "primary"
    tier: Tier = "T2"  # deterministic; feeds reputation + independence


class Subscription(Schema):
    id: str
    board_id: str | None = None  # which board this subscription feeds (FR-15)
    # M15.1 (v0.12): which module WITHIN the board this source belongs to —
    # board → module → source → item is the knowledge hierarchy; None = ungrouped.
    module_id: str | None = None
    input_url: str
    feed_url: str | None  # None => homepage-diff mode
    mode: Literal["direct", "autodiscover", "platform", "homepage_diff"]
    interval_minutes: int = 60
    last_polled: datetime | None
    # DISPLAY ONLY. New-vs-old is decided solely by the SeenItem table (§6.3),
    # never by this cursor.
    last_seen_item_key_for_display: str | None
    consecutive_failures: int = 0  # health: reset on success
    health: Literal["ok", "unhealthy"] = "ok"
    last_error: str | None = None
    subscription_failure_kind: SubscriptionFailureKind | None = None


class SeenItem(Schema):
    subscription_id: str
    item_key: str  # guid | canonical url | content hash
    first_seen: datetime


class SourcePackEntry(Schema):
    """One seed source in the built-in editable default pack (FR-3). The default
    pack seeds a board's subscriptions on cold start; the operator trims/edits it,
    then subscribes (Stage 7). A fixed starter list — NOT auto web-discovery by
    topic (§2.2)."""

    label: str
    url: str
    mode: Literal["direct", "autodiscover", "platform", "homepage_diff"]
    category: Literal["central_bank", "regulator", "company_ir", "rss", "youtube"]
    # M12.1: which preset topic board this recommendation belongs to (fixed board id
    # such as "b_politics"; None = unassigned). Stable across board renames.
    board_id: str | None = None


class Segment(Schema):
    text: str
    start_ts: float | None  # video/podcast only
    end_ts: float | None
    # [{text, start_ms, end_ms}] word-level timestamps (whisperX-style); lets a
    # claim map to char-span + audio time + vision-anchor frame (FR-8)
    words: list[dict[str, Any]] = []


class FrameAnnotation(Schema):
    source_id: str
    timestamp: float
    anchor_text: str
    vision_description: str
    image_path: str


class NormalizedSource(Schema):
    """Full ingestion output; carries independence + tier metadata. This is what
    the whole pipeline operates on. When reduced to `Source`, domain/citation_type/
    tier MUST be copied across (independence/tiering/scoring all read them)."""

    source_id: str
    type: SourceType
    origin: Origin = "user"
    url: str | None
    domain: str | None  # from URL host or validated declared_domain
    raw_text: str
    extraction_method: ExtractionMethod | None = None  # how raw_text was obtained
    segments: list[Segment]
    frame_annotations: list[FrameAnnotation]
    citation_type: CitationType = "primary"  # set by independence_detect
    tier: Tier = "T2"  # set by tiering


class SourceRequest(Schema):
    """One input item to /verify (FR-1) or one item a poll emits (FR-3)."""

    kind: Literal["url", "text"]
    url: str | None = None  # set iff kind == "url"
    text: str | None = None  # set iff kind == "text" (pasted)
    # human-readable label only; never independence credit by itself
    source_label: str | None = None
    # optional user-supplied domain; normalize/validate before it may count (FR-7)
    declared_domain: str | None = None
    declared_type: SourceType | None = None  # optional hint; else inferred

    @model_validator(mode="after")
    def _kind_payload_consistent(self) -> SourceRequest:
        # §7 contract: `url` set IFF kind == "url"; `text` set IFF kind == "text".
        # Enforce both directions — the opposite payload must be absent — so
        # /verify routing and pasted-text independence semantics stay unambiguous.
        if self.kind == "url":
            if not self.url:
                raise ValueError("SourceRequest(kind='url') requires `url`")
            if self.text is not None:
                raise ValueError("SourceRequest(kind='url') must not carry `text`")
        if self.kind == "text":
            if not self.text:
                raise ValueError("SourceRequest(kind='text') requires `text`")
            if self.url is not None:
                raise ValueError("SourceRequest(kind='text') must not carry `url`")
        return self


class SourceFailure(Schema):
    """FR-2 typed failure (shown in UI)."""

    requested_url: str | None
    type: SourceType | None  # inferred source type; None if unresolved
    kind: SourceFailureKind
    next_action: str | None = None  # user-facing next step (FR-2 / §6.6)
    reason: str  # human-readable


class IngestionResult(Schema):
    """Per-source outcome of ingest_all (FR-1 partial batch / FR-2 typed failure)."""

    requested: SourceRequest
    status: Literal["ok", "failed"]
    source: NormalizedSource | None  # set iff ok
    failure: SourceFailure | None  # set iff failed

    @model_validator(mode="after")
    def _outcome_consistent(self) -> IngestionResult:
        # §7 contract: `source` set IFF status == "ok"; `failure` set IFF "failed".
        # This is what keeps FR-1 partial-batch success/failure honest.
        if self.status == "ok":
            if self.source is None:
                raise ValueError("IngestionResult(status='ok') requires `source`")
            if self.failure is not None:
                raise ValueError("IngestionResult(status='ok') must not carry `failure`")
        if self.status == "failed":
            if self.failure is None:
                raise ValueError("IngestionResult(status='failed') requires `failure`")
            if self.source is not None:
                raise ValueError("IngestionResult(status='failed') must not carry `source`")
        return self


class Board(Schema):
    """A personal knowledge base = topic collection (FR-15); single operator,
    NOT a user account. Sources & facts link by board_id / board_ids — the fact
    store itself stays single, shared, deduped."""

    id: str
    name: str  # e.g. "finance" / "semiconductors" / "policy"
    created_at: datetime


class KnowledgeNote(Schema):
    """The knowledge layer (FR-15). `saved_check` (M13.2): the user-curated text of
    a /verify result, negotiated with the model and saved by the user — labeled as
    the user's own saved content, never presented as a pipeline-verified fact."""

    id: str
    board_id: str
    kind: Literal["pinned_fact", "user_note", "ai_distilled", "saved_check"]
    content: str  # user text, or LLM-distilled theme-level synthesis
    citations: list[str] = []  # claim_ids; REQUIRED (non-empty) when ai_distilled
    is_synthesized: bool = False  # True for ai_distilled → UI labels + separates it
    regenerable: bool = True  # ai_distilled is a cache, never the source of truth
    created_at: datetime

    @model_validator(mode="after")
    def _ai_distilled_must_cite(self) -> KnowledgeNote:
        # §7 / FR-15 / NFR-7 contract: a distilled note must cite verified facts.
        if self.kind == "ai_distilled" and not self.citations:
            raise ValueError("KnowledgeNote(kind='ai_distilled') requires non-empty citations")
        return self


class KnowledgeModule(Schema):
    """A user-named grouping INSIDE a board (M15.1, v0.12 / FR-15): the knowledge
    hierarchy is board → module → source → item → fact/note/saved_check. Modules
    organize sources (and their items); deleting one only un-groups — it never
    deletes sources, items, facts, or notes."""

    id: str
    board_id: str
    name: str
    created_at: datetime


class ItemEnrichment(Schema):
    """M16.3: bilingual, source-attributed enrichment for ONE tracked item — a
    single flash call at poll/refresh time (NFR-7 exception (3), broadened to
    bilingual output so the locale toggle follows instantly; owner 2026-07-08:
    "中英切换时 AI 生成内容语言不跟随"). Every field restates or annotates the
    SOURCE — attributed claims, never asserted truth, never outside knowledge,
    never a score, never investment advice. A failed generation is None at the
    card level; nothing here is ever fabricated."""

    summary_zh: str  # 1-2 句中文综述(来源口吻)
    summary_en: str  # 1-2 sentence English summary (source-attributed)
    # the source's own title rendered in each language (owner 2026-07-10: the
    # locale toggle must carry the TITLE too, not just the summary) — a faithful
    # translation, never a rewrite; optional so older cached enrichments degrade
    # to the original title
    title_zh: str | None = None
    title_en: str | None = None
    # one source-grounded sentence on why this matters to a reader tracking the
    # topic — still ONLY from the content, never analysis from outside knowledge
    why_zh: str | None = None
    why_en: str | None = None
    entities: list[str] = []  # proper nouns AS WRITTEN in the source — not translated
    tags: list[str] = []  # 2-6 short lowercase topic slugs
    # honest caveats about the enrichment itself (e.g. "仅基于正文前 4000 字符")
    limitations_zh: str | None = None
    limitations_en: str | None = None


class TrackedItemCard(Schema):
    """One tracked source item as first-class knowledge (M15.1a, v0.12 P0).

    Deliberately carries NO credibility: an item that has not been deeply checked
    must never fake a score (§2.4 — the UI says "not deeply checked" instead).
    `status` is the item's own lifecycle, decoupled from deep verification:
    new (discovered, being processed) / fetched (content in hand — visible even
    when claim extraction or scoring failed; `degraded_reason` says so) /
    failed (typed ingestion failure — still visible, with the failure kind) /
    deferred (M14.5 first-check transcription deferral; the next check processes)."""

    id: str
    board_id: str | None
    # M15.1: the source's module at discovery time (board → module → source → item)
    module_id: str | None = None
    url: str | None
    title: str | None
    domain: str | None
    tier: Tier | None  # P1 lite signal, code-first (assign_tier), never an LLM
    published: datetime | None
    first_seen: datetime
    status: Literal["new", "fetched", "failed", "deferred"]
    failure_kind: SourceFailureKind | None = None  # set iff status == "failed"/"deferred"
    degraded_reason: str | None = None  # deep-check degradation note (item stays visible)
    # DEPRECATED (M16.3): the M15.2 single-language briefing — locale-blind, so it
    # was the owner's "language doesn't follow" complaint. No writer since v0.13;
    # the UI must never consume it (M16.1 pins this). Kept nullable for contract
    # compatibility only; `enrichment` below is the live field.
    summary: str | None = None
    # M16.3: bilingual enrichment generated at poll/refresh time (ONE flash call,
    # NFR-7 exception (3)); None = pending — the UI shows an honest pending state,
    # never a fabricated line.
    enrichment: ItemEnrichment | None = None
    # M16.3: a content excerpt (capped) is persisted for this item — it grounds
    # the per-item discussion (M16.5) and the manual re-enrich (M16.4). Legacy
    # items discovered before v0.13 have none until manually refreshed.
    content_available: bool = False
    # M15.1: deep-check results as ENRICHMENT REFERENCES (v0.12 — the verdict is a
    # M15.4 (P1 lite signal, code-first — §2.4): how many OTHER domains in the same
    # view window carry an item with the same normalized title — a duplicate/repost
    # HINT for triage, computed by code (never an LLM, never NLI), and explicitly
    # NOT a corroboration verdict (that is the deep path's K_effective).
    similar_count: int = 0


class TrackedItemDetail(Schema):
    """`GET /tracked-items/{id}` (M16.4): the item detail page payload — the card
    plus what only the detail view needs. Everything stays in tracking language:
    no score, no verdict, no stance (v0.13)."""

    item: TrackedItemCard
    # "Source says": the stored content excerpt, truncated for display (the full
    # capped excerpt still grounds discussion/refresh server-side). None = no
    # stored text (legacy pre-v0.13 row or fetch-failed item).
    excerpt_preview: str | None


class DailyDigest(Schema):
    date: date
    generated_at: datetime
    # M15.1a (v0.12 P0): tracked items as first-class knowledge, independent of the
    # deep-verification path — visible even when extraction/stance/scoring failed.
    tracked: list[TrackedItemCard] = []


class DiscussMessage(Schema):
    """One turn in an evidence-bounded digest-item discussion (M12.3)."""

    role: Literal["user", "assistant"]
    content: str


class ItemDiscussRequest(Schema):
    """`POST /tracked-items/{id}/discuss` body (M16.5): the chat so far (oldest →
    newest; the last message must be the user's turn) about ONE tracked item.
    Grounding is the item's PERSISTED material only — its stored content excerpt
    plus its bilingual enrichment and card metadata. No cluster_id / evidence /
    draft here: a tracked-item discussion never touches the (dormant) fact layer."""

    messages: list[DiscussMessage]


class ItemDiscussReply(Schema):
    """`POST /tracked-items/{id}/discuss` reply (M16.5). Source-bounded: grounded
    ONLY in the item's stored excerpt + AI enrichment; beyond them the model
    answers 证据不足. Source-attributed tone — never a truth verdict, never a
    score, never investment advice. READ-ONLY and never cached (NFR-7 exc. (4))."""

    reply: str


class ItemNoteDraftRequest(Schema):
    """`POST /tracked-items/{id}/note-draft` body (2026-07-13): notes saved to
    Knowledge are LLM-curated first. Empty messages = ask for the initial draft;
    otherwise the revision chat so far (assistant turns are earlier drafts, the
    last message must be the user's revision instruction). READ-ONLY: drafting
    never writes — the user saves the final text via the notes endpoint."""

    messages: list[DiscussMessage] = []
    # the UI locale the initial draft should be written in (a user instruction
    # in another language overrides it)
    locale: Literal["zh", "en"] = "zh"


class ItemNoteDraftReply(Schema):
    """`POST /tracked-items/{id}/note-draft` reply: the current draft note text,
    grounded in the item's stored excerpt + enrichment. Never auto-saved."""

    draft: str


class KnowledgeSearchResult(Schema):
    """`GET /knowledge/search`: deterministic SQLite keyword matching only — zero
    LLM and zero embedding in the request path (M16.2, the owner's "search is
    very slow" fix). Two labeled layers: the user's own notes and tracked items.
    Tracked items are NEVER fed into the on-demand answer synthesis."""

    saved: list[KnowledgeNote]
    items: list[TrackedItemCard] = []


class KnowledgeAnswerRequest(Schema):
    """`POST /knowledge/answer` body (M16.2): the question to answer on demand."""

    q: str


class KnowledgeAnswer(Schema):
    """`POST /knowledge/answer` (M16.2): the on-demand AI answer — ONE flash call
    (NFR-7 exception (5)) grounded ONLY in the user's saved notes matching the
    question. Tracked items are never fed in; the fact layer is dormant (v0.13).
    No matching notes → answer=None with zero LLM spend; an LLM failure is a 502
    (the user explicitly asked — a typed error beats a silent null)."""

    answer: str | None
    based_on: int  # how many hits (saved notes + tracked items) grounded the answer (0 = no call)


class StepTrace(Schema):
    """One pipeline step's outcome within a run. A FLAT per-run record — NOT a
    telemetry/tracing platform."""

    step: Literal[
        "ingestion",
        "vision",
        "extraction",
        "alignment",
        "retrieval",
        "verification",
        "scoring",
        "memory",
        "digest",
    ]
    status: Literal["ok", "skipped", "failed"]
    fallback_used: str | None = None  # e.g. "yt-dlp captions failed → local whisper"
    counts: dict[str, Any] = {}  # e.g. {"claims": 8, "clusters": 3}
    error: str | None = None
    duration_ms: int | None = None


class PipelineRun(Schema):
    """One verify/poll run, persisted to SQLite; visible in logs + UI."""

    id: str
    trigger: Literal["verify", "poll", "digest"]
    inputs: list[SourceRequest]
    steps: list[StepTrace]
    prompt_version: str | None = None  # for NFR-4 reproducibility
    started_at: datetime
    finished_at: datetime | None = None


class UsageEvent(Schema):
    """FR-17 beta usage signal — local only, no external analytics (§8.2)."""

    type: Literal["digest_open", "evidence_click", "verdict_save", "verdict_share", "helped_judge"]
    ref: str | None = None  # what was opened / clicked / saved
    user: str | None = None  # beta user (operator-run)
    created_at: datetime


# --- API envelopes (M2.2 / M2.4): the /verify request + thin-report response. ---


class TraceSummary(Schema):
    """Condensed run trace for the report (M2.4): the run id + ordered steps."""

    run_id: str
    steps: list[StepTrace]


ALL_MODELS: list[type[Schema]] = [
    Source,
    Subscription,
    SeenItem,
    SourcePackEntry,
    Segment,
    FrameAnnotation,
    NormalizedSource,
    SourceRequest,
    SourceFailure,
    IngestionResult,
    Board,
    KnowledgeModule,
    KnowledgeNote,
    TrackedItemDetail,
    ItemEnrichment,
    TrackedItemCard,
    DailyDigest,
    DiscussMessage,
    ItemDiscussRequest,
    ItemDiscussReply,
    ItemNoteDraftRequest,
    ItemNoteDraftReply,
    KnowledgeAnswer,
    KnowledgeAnswerRequest,
    KnowledgeSearchResult,
    StepTrace,
    PipelineRun,
    UsageEvent,
    TraceSummary,
]
