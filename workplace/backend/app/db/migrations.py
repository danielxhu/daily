"""SQLite migration discipline (X0.6).

Migrations are grouped by **domain** (`memory` / `tracking` / `board`) so each
schema area can evolve independently — a domain only applies its own pending
versions. Applied migrations are recorded in a `schema_migrations(domain, version)`
ledger, so `migrate()` is idempotent: re-running applies nothing.

X0.6 ships a minimal **baseline** per domain; the full schemas are added as
additive migrations (v2+) by their stages — memory M5.1, board M6.1, tracking M7.1.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]  # applied in order within one transaction


# Per-domain, version-ordered migration lists. Keep each migration's statements
# additive — later stages append higher versions, never edit shipped ones.
MIGRATIONS: dict[str, list[Migration]] = {
    "board": [
        Migration(
            1,
            "create_boards",
            (
                "CREATE TABLE boards ("
                "  id TEXT PRIMARY KEY,"
                "  name TEXT NOT NULL,"
                "  created_at TEXT NOT NULL"
                ")",
            ),
        ),
        # M6.3 — knowledge layer (FR-15): per-board notes. `pinned_fact` / `user_note`
        # are explicit human input (M6.3); `ai_distilled` is generated only from
        # verified facts and must cite them (M6.4). `citations` holds claim_ids.
        Migration(
            2,
            "create_knowledge_notes",
            (
                "CREATE TABLE knowledge_notes ("
                "  id TEXT PRIMARY KEY,"
                "  board_id TEXT NOT NULL,"
                "  kind TEXT NOT NULL,"
                "  content TEXT NOT NULL,"
                "  citations_json TEXT NOT NULL DEFAULT '[]',"
                "  is_synthesized INTEGER NOT NULL DEFAULT 0,"
                "  regenerable INTEGER NOT NULL DEFAULT 0,"
                "  created_at TEXT NOT NULL,"
                # board-private notes: deleting a board removes its notes (the shared
                # fact store is separate, linked only by a board_ids tag — never FK'd)
                "  FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE"
                ")",
                "CREATE INDEX idx_notes_board ON knowledge_notes (board_id)",
            ),
        ),
        # M12.1 — preset topic boards (owner 2026-07-03): 政治 / 经济 / 科技. Seeded as
        # a DATA migration so they appear exactly once per database — the ledger
        # guarantees a user who renames or deletes them never sees them resurrect.
        # Fixed ids so the static source-pack recommendations can reference them.
        Migration(
            3,
            "seed_default_boards",
            (
                "INSERT INTO boards (id, name, created_at) VALUES "
                "('b_politics', '政治', '2026-07-03T00:00:00+00:00')",
                "INSERT INTO boards (id, name, created_at) VALUES "
                "('b_economy', '经济', '2026-07-03T00:00:00+00:00')",
                "INSERT INTO boards (id, name, created_at) VALUES "
                "('b_tech', '科技', '2026-07-03T00:00:00+00:00')",
            ),
        ),
    ],
    "reputation": [
        # M5.7 — human source-reputation overrides (FR-12 / FR-17). A persistent
        # domain → tier map the OPERATOR sets explicitly; tiering reads it so an
        # override survives across runs. This is the ONLY way reputation changes
        # besides the static tier table — it is **never** written from the system's
        # own verdicts (FR-9 anti-self-learning red line).
        Migration(
            1,
            "create_source_tier_overrides",
            (
                "CREATE TABLE source_tier_overrides ("
                "  domain TEXT PRIMARY KEY,"
                "  tier TEXT NOT NULL,"
                "  note TEXT,"
                "  created_at TEXT NOT NULL"
                ")",
            ),
        ),
    ],
    "tracking": [
        Migration(
            1,
            "create_seen_items",
            (
                "CREATE TABLE seen_items ("
                "  subscription_id TEXT NOT NULL,"
                "  item_key TEXT NOT NULL,"
                "  first_seen TEXT NOT NULL,"
                "  PRIMARY KEY (subscription_id, item_key)"
                ")",
            ),
        ),
        # M7.1 — subscriptions (FR-3): a pollable source (feed / homepage / channel
        # URL) attached to a board. CRUD only here; the poll machinery fills the
        # runtime/health fields later (M7.6 dedup, M7.7 scheduler, M7.8 health).
        # `board_id` is a plain nullable column, NOT a DB foreign key: it would be a
        # cross-domain reference (tracking → board) and a DB FK breaks the
        # domain-independent migration rule (X0.6 — each domain must migrate AND work
        # on its own; with foreign_keys=ON even a board-less insert resolves the
        # parent table). The subscription→board relationship is kept at the app layer:
        # `POST /subscriptions` validates the board exists, and `delete_board`
        # defensively removes a board's subscriptions. A board-less subscription
        # (board_id NULL) is a standalone tracked source.
        Migration(
            2,
            "create_subscriptions",
            (
                "CREATE TABLE subscriptions ("
                "  id TEXT PRIMARY KEY,"
                "  board_id TEXT,"
                "  input_url TEXT NOT NULL,"
                "  feed_url TEXT,"
                "  mode TEXT NOT NULL,"
                "  interval_minutes INTEGER NOT NULL DEFAULT 60,"
                "  last_polled TEXT,"
                "  last_seen_item_key_for_display TEXT,"
                "  consecutive_failures INTEGER NOT NULL DEFAULT 0,"
                "  health TEXT NOT NULL DEFAULT 'ok',"
                "  last_error TEXT,"
                "  subscription_failure_kind TEXT"
                ")",
                "CREATE INDEX idx_subscriptions_board ON subscriptions (board_id)",
            ),
        ),
        # M7.9 — rolling-window pending claims (§6.3). A tracked claim that is lone +
        # non-T1 + uncorroborated (even after CASR) is held here, NOT in the fact
        # layer / Chroma, until a later independent source corroborates it or it
        # expires from the window. `claim_json` / `source_json` keep the full claim +
        # normalized source so the window can re-cluster on the next poll. board_id is
        # a plain nullable column (cross-domain, no FK), like subscriptions.
        Migration(
            3,
            "create_pending_claims",
            (
                "CREATE TABLE pending_claims ("
                "  claim_id TEXT PRIMARY KEY,"
                "  board_id TEXT,"
                "  first_seen TEXT NOT NULL,"
                "  expires_at TEXT NOT NULL,"
                "  claim_json TEXT NOT NULL,"
                "  source_json TEXT NOT NULL"
                ")",
                "CREATE INDEX idx_pending_board ON pending_claims (board_id)",
                "CREATE INDEX idx_pending_expires ON pending_claims (expires_at)",
            ),
        ),
        # M12.2 — per-item digest summary cache (AIHOT-informed briefing line, owner
        # 2026-07-03). One flash summary per (fact, version): re-rendering the digest
        # must not re-bill the LLM. Presentation-only — never feeds scoring/memory.
        Migration(
            4,
            "create_digest_summaries",
            (
                "CREATE TABLE digest_summaries ("
                "  claim_id TEXT NOT NULL,"
                "  version INTEGER NOT NULL,"
                "  summary TEXT NOT NULL,"
                "  created_at TEXT NOT NULL,"
                "  PRIMARY KEY (claim_id, version)"
                ")",
            ),
        ),
        # M14.1 — one-time app flags (owner 2026-07-06 Day-1 auto-fill). The seeding
        # marker must survive the user deleting every subscription: an empty list
        # after a deliberate clean-out is the user's choice, never re-filled.
        Migration(
            5,
            "create_app_flags",
            (
                "CREATE TABLE app_flags ("
                "  key TEXT PRIMARY KEY,"
                "  value TEXT NOT NULL,"
                "  created_at TEXT NOT NULL"
                ")",
            ),
        ),
        # M14.7 — per-item digest category cache (owner 2026-07-07 "为什么这么慢").
        # Categorization used to be re-derived on EVERY digest render, serially
        # calling the LLM for each fact no keyword rule matched. Same shape and
        # lifecycle as digest_summaries: keyed by (fact, version), filled write-side
        # by the poll's enrichment backfill, read-only at render time.
        Migration(
            6,
            "create_digest_categories",
            (
                "CREATE TABLE digest_categories ("
                "  claim_id TEXT NOT NULL,"
                "  version INTEGER NOT NULL,"
                "  category TEXT NOT NULL,"
                "  created_at TEXT NOT NULL,"
                "  PRIMARY KEY (claim_id, version)"
                ")",
            ),
        ),
        # M15.1a — tracked items as first-class knowledge (v0.12 P0 / Stage 15).
        # Before this, a tracked item had NO persistent entity: seen_items keeps
        # only a dedup fingerprint, so an item that failed anywhere in the deep
        # pipeline (extraction/stance/scoring) simply vanished. This table makes
        # discovery itself the visibility gate. Keyed like seen_items so a
        # re-discovered (deferred) item updates its row instead of duplicating.
        Migration(
            7,
            "create_tracked_items",
            (
                "CREATE TABLE tracked_items ("
                "  subscription_id TEXT NOT NULL,"
                "  item_key TEXT NOT NULL,"
                "  id TEXT NOT NULL UNIQUE,"
                "  board_id TEXT,"
                "  url TEXT,"
                "  title TEXT,"
                "  domain TEXT,"
                "  published TEXT,"
                "  first_seen TEXT NOT NULL,"
                "  last_status_at TEXT NOT NULL,"
                "  status TEXT NOT NULL,"
                "  failure_kind TEXT,"
                "  degraded_reason TEXT,"
                "  PRIMARY KEY (subscription_id, item_key)"
                ")",
                "CREATE INDEX idx_tracked_items_first_seen ON tracked_items (first_seen)",
            ),
        ),
        # M15.1 — knowledge modules + item↔fact lineage (v0.12 / FR-15). The
        # hierarchy is board → module → source → item → fact/note/saved_check:
        # `knowledge_modules` is the user-named grouping inside a board (deleting
        # one only un-groups); `module_id` on subscriptions/tracked_items is the
        # membership (NULL = ungrouped — all pre-v8 rows stay readable as such);
        # `tracked_item_facts` links a tracked item to the verified facts its
        # content contributed to (deep-check verdicts become enrichment REFERENCES
        # on items, never the only knowledge entity).
        Migration(
            8,
            "create_knowledge_modules_and_lineage",
            (
                "CREATE TABLE knowledge_modules ("
                "  id TEXT PRIMARY KEY,"
                "  board_id TEXT NOT NULL,"
                "  name TEXT NOT NULL,"
                "  created_at TEXT NOT NULL"
                ")",
                "CREATE TABLE tracked_item_facts ("
                "  item_id TEXT NOT NULL,"
                "  claim_id TEXT NOT NULL,"
                "  PRIMARY KEY (item_id, claim_id)"
                ")",
                "ALTER TABLE subscriptions ADD COLUMN module_id TEXT",
                "ALTER TABLE tracked_items ADD COLUMN module_id TEXT",
            ),
        ),
        # M15.2 — per-item briefing summary (v0.12 P0: "summarized" is part of the
        # product skeleton). Generated AT POLL TIME while the fetched content is in
        # hand (raw text is never persisted), one flash call per new item under
        # NFR-7 exception (3); NULL = not generated (failed or content-less item) —
        # the UI renders nothing rather than a fake line.
        Migration(
            9,
            "add_tracked_item_summary",
            ("ALTER TABLE tracked_items ADD COLUMN summary TEXT",),
        ),
        # M16.3 — bilingual enrichment (owner 2026-07-08: locale must follow the
        # language toggle) + a persisted content excerpt. `enrichment` is the
        # ItemEnrichment JSON (ensure_ascii=False); `content_excerpt` (capped in
        # code) grounds the per-item discussion and the manual re-enrich. Legacy
        # rows stay NULL — honest pending, no offline backfill (no stored text).
        Migration(
            10,
            "add_tracked_item_enrichment",
            (
                "ALTER TABLE tracked_items ADD COLUMN enrichment TEXT",
                "ALTER TABLE tracked_items ADD COLUMN content_excerpt TEXT",
            ),
        ),
        # M16.4 — how the content was obtained (trafilatura / caption / whisper /
        # …), recorded when the excerpt lands; shown as provenance on the item
        # detail page. NULL for legacy rows and fetch-failed items.
        Migration(
            11,
            "add_tracked_item_extraction_method",
            ("ALTER TABLE tracked_items ADD COLUMN extraction_method TEXT",),
        ),
        # owner 2026-07-19 "全是url不知道哪个是哪个": a user-given display name per
        # source. NULL = unnamed (all pre-v12 rows) — the UI falls back to the URL.
        Migration(
            12,
            "add_subscription_name",
            ("ALTER TABLE subscriptions ADD COLUMN name TEXT",),
        ),
        # owner 2026-07-21 — per-domain risk-control circuit breaker (audit: bilibili
        # 412 bans are HOUR-scale and IP-wide; per-item retries just deepened them).
        # Persistent so a restart's fresh in-memory budgets never re-hammer a domain
        # that banned us an hour ago. One row per blocked domain; success deletes.
        Migration(
            13,
            "create_domain_backoff",
            (
                "CREATE TABLE domain_backoff ("
                "  domain TEXT PRIMARY KEY,"
                "  blocked_until TEXT NOT NULL,"
                "  consecutive INTEGER NOT NULL DEFAULT 1,"
                "  last_reason TEXT,"
                "  updated_at TEXT NOT NULL"
                ")",
            ),
        ),
    ],
    "events": [
        # Beta usage/feedback signals (X0.9, FR-17 / §8.2): local-only, no external
        # analytics. `feedback` is explicit human input — NEVER auto-learned into
        # reputation (FR-9 red line).
        Migration(
            1,
            "create_event_log",
            (
                "CREATE TABLE usage_events ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  type TEXT NOT NULL,"
                "  ref TEXT,"
                "  user TEXT,"
                "  created_at TEXT NOT NULL"
                ")",
                "CREATE TABLE feedback ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  target_id TEXT NOT NULL,"
                "  kind TEXT NOT NULL,"
                "  note TEXT,"
                "  created_at TEXT NOT NULL"
                ")",
            ),
        ),
    ],
    "trace": [
        # Run trace (X0.7, §4/§7): a flat per-run debug record, NOT a telemetry
        # platform. `pipeline_runs` + ordered `step_traces` (FK to the run).
        Migration(
            1,
            "create_run_trace",
            (
                "CREATE TABLE pipeline_runs ("
                "  id TEXT PRIMARY KEY,"
                "  trigger TEXT NOT NULL,"
                "  inputs_json TEXT NOT NULL,"
                "  prompt_version TEXT,"
                "  started_at TEXT NOT NULL,"
                "  finished_at TEXT"
                ")",
                "CREATE TABLE step_traces ("
                "  run_id TEXT NOT NULL,"
                "  seq INTEGER NOT NULL,"
                "  step TEXT NOT NULL,"
                "  status TEXT NOT NULL,"
                "  fallback_used TEXT,"
                "  counts_json TEXT NOT NULL,"
                "  error TEXT,"
                "  duration_ms INTEGER,"
                "  PRIMARY KEY (run_id, seq),"
                "  FOREIGN KEY (run_id) REFERENCES pipeline_runs(id)"
                ")",
            ),
        ),
    ],
    "memory": [
        # Minimal bi-temporal anchor (FR-9); M5.1 extends it with the full
        # MemoryItem columns + history. The PRIMARY KEY is (claim_id, version),
        # NOT claim_id alone, so a fact's superseded v1 (valid_to/invalidated_by
        # set) and current v2 coexist — invalidate-don't-delete lineage (FR-9).
        Migration(
            1,
            "create_memory_items_baseline",
            (
                "CREATE TABLE memory_items ("
                "  claim_id TEXT NOT NULL,"
                "  canonical_text TEXT NOT NULL,"
                "  version INTEGER NOT NULL DEFAULT 1,"
                "  is_current INTEGER NOT NULL DEFAULT 1,"
                "  valid_from TEXT NOT NULL,"
                "  valid_to TEXT,"
                "  ingested_at TEXT NOT NULL,"
                "  invalidated_by TEXT,"
                "  PRIMARY KEY (claim_id, version)"
                ")",
            ),
        ),
        # M5.1 — the full §7 MemoryItem. Additive ADD COLUMNs (the table is empty
        # before the memory store exists): the verdict + sources + entities +
        # board_ids + version_history are stored as JSON, plus the system-time and
        # heat fields. NOT NULL defaults are syntactic only (no pre-existing rows);
        # `memory_store` always writes real values.
        Migration(
            2,
            "extend_memory_items_full",
            (
                "ALTER TABLE memory_items ADD COLUMN verdict_json TEXT NOT NULL DEFAULT '{}'",
                "ALTER TABLE memory_items ADD COLUMN sources_json TEXT NOT NULL DEFAULT '[]'",
                "ALTER TABLE memory_items ADD COLUMN entities_json TEXT NOT NULL DEFAULT '[]'",
                "ALTER TABLE memory_items ADD COLUMN board_ids_json TEXT NOT NULL DEFAULT '[]'",
                "ALTER TABLE memory_items ADD COLUMN version_history_json "
                "TEXT NOT NULL DEFAULT '[]'",
                "ALTER TABLE memory_items ADD COLUMN first_seen TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE memory_items ADD COLUMN last_updated TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE memory_items ADD COLUMN heat REAL NOT NULL DEFAULT 0",
                # current-version lookups (get_current, M5.5) and the Chroma
                # current-only adapter (M5.2) filter on is_current.
                "CREATE INDEX idx_memory_current ON memory_items (claim_id, is_current)",
            ),
        ),
        # M5.1 — the load-bearing FR-9 invariant: a claim has AT MOST
        # ONE current version (SSOT §7 `is_current` is singular; §89 "Only the
        # current version is embedded in Chroma"). A PARTIAL UNIQUE INDEX enforces it
        # in the DB, so inserting a second current without superseding the old one
        # fails instead of leaving two — the foundation M5.2's current-only adapter
        # relies on. Additive v3 (v2 was already handed off).
        Migration(
            3,
            "memory_items_single_current_unique",
            (
                "CREATE UNIQUE INDEX idx_memory_one_current "
                "ON memory_items (claim_id) WHERE is_current = 1",
            ),
        ),
    ],
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def ensure_ledger(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  domain TEXT NOT NULL,"
        "  version INTEGER NOT NULL,"
        "  name TEXT NOT NULL,"
        "  applied_at TEXT NOT NULL,"
        "  PRIMARY KEY (domain, version)"
        ")"
    )
    conn.commit()


def applied_versions(conn: sqlite3.Connection, domain: str) -> set[int]:
    rows = conn.execute(
        "SELECT version FROM schema_migrations WHERE domain = ?", (domain,)
    ).fetchall()
    return {int(r[0]) for r in rows}


def migrate(conn: sqlite3.Connection, domains: list[str] | None = None) -> list[tuple[str, int]]:
    """Apply pending migrations for the given domains (default: all). Returns the
    (domain, version) pairs actually applied this call. Idempotent.

    Each migration runs in an explicit transaction (schema change + ledger row
    together). We force explicit BEGIN/COMMIT/ROLLBACK because Python's `sqlite3`
    runs DDL in autocommit under the default isolation level — so a plain
    `with conn:` would NOT roll back a half-applied `CREATE TABLE`. On any failure
    the whole migration is rolled back and no ledger row is written."""
    targets = domains if domains is not None else list(MIGRATIONS)
    # Validate domains before touching the database.
    for domain in targets:
        if domain not in MIGRATIONS:
            raise KeyError(f"unknown migration domain: {domain!r}")

    ensure_ledger(conn)
    applied: list[tuple[str, int]] = []
    prev_isolation = conn.isolation_level
    conn.isolation_level = None  # take manual control of transaction boundaries
    try:
        for domain in targets:
            done = applied_versions(conn, domain)
            for m in sorted(MIGRATIONS[domain], key=lambda x: x.version):
                if m.version in done:
                    continue
                conn.execute("BEGIN")
                try:
                    for stmt in m.statements:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT INTO schema_migrations (domain, version, name, applied_at)"
                        " VALUES (?, ?, ?, ?)",
                        (domain, m.version, m.name, _now()),
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                applied.append((domain, m.version))
    finally:
        conn.isolation_level = prev_isolation
    return applied
