"""Pinned configuration for daily (X0.2).

Two kinds of config live here:

1. **Code-pinned constants** — scoring weights/formula constants, CASR guardrails,
   reproducibility seed, prompt version. These are NOT environment-driven; they are
   part of the engineering contract (SSOT §3.1.1 / FR-7 / FR-16 / NFR-4) and are
   covered by unit tests so nobody silently invents incompatible scoring behavior.

2. **Environment-driven settings** (`Settings`) — API keys, base URLs, model ids,
   feature toggles, local model names, data paths. Loaded from process env / `.env`.

Constants trace to the engineering design doc (v0.11).
Section references in comments point there.
"""

from __future__ import annotations

import functools

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised when required runtime configuration is missing or invalid."""


# ---------------------------------------------------------------------------
# Reproducibility / prompt versioning (NFR-4)
# ---------------------------------------------------------------------------

# Bump when any LLM prompt changes; recorded on every LLM call + report (NFR-4).
PROMPT_VERSION: str = "2026-06-22.v1"

# Fixed seed wherever the stack allows deterministic behavior (NFR-4).
SEED: int = 42


# ---------------------------------------------------------------------------
# Scoring contract — SSOT §3.1.1 (FR-7). Code combines sub-scores; the LLM
# never emits the final credibility (NFR-7). Re-calibration only under §8's
# no-leakage rules; `calibrated_at` is stamped by M4.6 when that happens.
# ---------------------------------------------------------------------------


class ScoringWeights(BaseModel):
    """§3.1.1 credibility sub-score weights. CALIBRATED in M4.6 by grid-search on the
    `train` split of `eval/calibration_set.json` (no-leakage, §8) — the committed
    result is `eval/weight_calibration.json`. The §3.1.1 *init* values were
    w1=0.30, w2=0.40, w3=0.15, w4=0.15; they are re-calibrated again in M4.11 on the
    full labeled set. (Drift between these and the record is guarded in tests.)"""

    model_config = ConfigDict(frozen=True)

    w1_sources: float = 0.35
    w2_agreement: float = 0.45
    w3_reputation: float = 0.20
    w4_conflict: float = 0.10


class ScoringConstants(BaseModel):
    """All scalar constants of the §3.1.1 credibility formula. Frozen on purpose:
    these are an engineering contract, asserted in `tests/test_config.py`."""

    model_config = ConfigDict(frozen=True)

    weights: ScoringWeights = Field(default_factory=ScoringWeights)

    # sources_score = min(100, SOURCES_SCORE_PER_K * K_effective)
    sources_score_per_k: float = 25.0

    # independence_factor = clamp(BASE + PER_K*K_eff - PER_R*R, MIN, MAX)
    # …unless authoritative_anchor and K_eff <= 1 → independence_factor = 1.0
    independence_base: float = 0.5
    independence_per_k: float = 0.125
    independence_per_r: float = 0.05
    independence_min: float = 0.5
    independence_max: float = 1.0

    score_min: float = 0.0
    score_max: float = 100.0

    # Stamped (ISO date string) when weights are calibrated. Set in M4.6 from the
    # train-split grid-search; must match `eval/weight_calibration.json` (guarded).
    calibrated_at: str | None = "2026-06-24"


SCORING = ScoringConstants()


# ---------------------------------------------------------------------------
# Alignment threshold — calibrated in M3.3 (FR-5 / §8). Swept on the `train`
# split of `eval/alignment_pairs.json` with the real `embedding_model` and picked
# by max F1 (tie-break favors the higher threshold = precision-leaning); reported
# on the heldout split (no leakage). Re-derive with `eval/calibrate_alignment.py`;
# the full record (candidates + train/heldout metrics) is `eval/alignment_calibration.json`.
# ---------------------------------------------------------------------------

ALIGNMENT_COSINE_THRESHOLD: float = 0.71
ALIGNMENT_THRESHOLD_CALIBRATED: bool = True


# ---------------------------------------------------------------------------
# Rolling window (SSOT §6.2 / §223 / FR-11c) — the recent pool used to pair
# independent sources for one claim AND to bound the global (topic) memory query
# to recent activity. The global query filters by entity tag over this window; it
# is NOT a full memory scan (§224).
# ---------------------------------------------------------------------------

ROLLING_WINDOW_DAYS: int = 7

# Heat decay half-life (FR-14): a cluster's counted-source momentum loses half its
# heat per this many days without new corroboration. Heat is a SECONDARY badge,
# never the digest sort key (§11.2); computed at digest time, never an LLM (NFR-7).
HEAT_HALF_LIFE_DAYS: float = 7.0

# M14.6 (owner 2026-07-06): the digest/Today VIEW window — "不是今天,我要看近期的
# 所有变化,默认一个月,后续用户可以调整时长". Distinct from ROLLING_WINDOW_DAYS
# (the 7-day corroboration-pairing window, an engineering bound): this is how far
# back the briefing looks by default; the user adjusts it per request (?window_days).
DIGEST_WINDOW_DAYS: int = 30

# M13.4 (beta P1-2): a NEVER-polled subscription's first check picks up only the
# latest N items — the older backlog is marked seen and skipped for good, so a
# fresh source answers in ~one item's pipeline time instead of a minutes-long
# synchronous drain of the whole feed. Later polls are genuinely incremental.
FIRST_POLL_ITEM_CAP: int = 5

# M14.7 (owner 2026-07-07 "为什么这么慢"): the per-poll LLM-call budget for the
# digest enrichment backfill (summaries + categories, write-side). Bounds the
# poll's tail cost while the backlog warms; must stay ≥ DRAIN_MAX_CLAIMS so
# enrichment keeps pace with facts graduating from the pending pool. The digest
# READ path never calls the LLM — misses render as placeholders until the next
# poll fills them in.
DIGEST_BACKFILL_MAX: int = 80


# ---------------------------------------------------------------------------
# CASR guardrails — SSOT §3.1.1 / FR-16. Claim-anchored, whitelist-only,
# ≤3 lookups/claim, never topic browsing. The whitelist is the V1 seed of
# T1 authoritative domains; per-board extension happens in M4.12.
# ---------------------------------------------------------------------------

CASR_MAX_LOOKUPS_PER_CLAIM: int = 3

# CASR fires ONLY on weak corroboration (FR-16): no authoritative anchor AND at
# most this many counted independent SUPPORT domains. A claim already anchored to a
# primary source, or corroborated by >= 2 independent sources, needs no fetch.
CASR_WEAK_K_THRESHOLD: int = 1

CASR_WHITELIST: frozenset[str] = frozenset(
    {
        # SEC EDGAR (full-text API + on-site)
        "sec.gov",
        "www.sec.gov",
        "efts.sec.gov",
        # Central banks / regulators
        "federalreserve.gov",
        "www.federalreserve.gov",
        "ecb.europa.eu",
        "bankofengland.co.uk",
        "treasury.gov",
        "bls.gov",
        "bea.gov",
        # Exchanges
        "nasdaq.com",
        "nyse.com",
    }
)


# ---------------------------------------------------------------------------
# Source tiering — SSOT FR-12 / §3.1.1. Deterministic config table + heuristics
# (code, not LLM — NFR-7). T1 = primary/official (regulators, central banks,
# exchanges, gov statistics, company IR); T1.5 = official social handles; T2 =
# everyone else (media / aggregator / KOL / unknown) and any source with no
# resolvable domain (FR-7). Tier maps to a static `reputation_prior`; reputation
# is static tier + explicit human input only, NEVER self-learned (FR-9).
# ---------------------------------------------------------------------------

TIER1_DOMAINS: frozenset[str] = frozenset(
    {
        # regulators / central banks / government statistics
        "sec.gov",
        "federalreserve.gov",
        "ecb.europa.eu",
        "bankofengland.co.uk",
        "treasury.gov",
        "bls.gov",
        "bea.gov",
        "cftc.gov",
        "occ.gov",
        "imf.org",
        "worldbank.org",
        # exchanges
        "nasdaq.com",
        "nyse.com",
        "londonstockexchange.com",
        "hkex.com.hk",
    }
)

# Host-bound official social accounts → T1.5. A handle is official ONLY on its own
# platform; the same handle on a different host is NOT treated as official (stays
# T2), so a look-alike account on another platform can't inherit T1.5.
TIER15_OFFICIAL_ACCOUNTS: dict[str, frozenset[str]] = {
    "twitter.com": frozenset({"federalreserve", "secgov", "ecb", "bankofengland", "cftc"}),
    "x.com": frozenset({"federalreserve", "secgov", "ecb", "bankofengland", "cftc"}),
}

# Company IR (investor relations) → T1 (FR-12 "company IR"). Deterministic:
#  - an `ir.`/`investor.`/`investors.` host first-label (corporate-specific), OR
#  - a company apex domain in `TIER1_IR_PATH_DOMAINS` *and* an investor-relations
#    path segment. The path rule is gated to that allowlist so a generic
#    `/investor` path on a social / media / unknown host can NOT reach T1.
IR_SUBDOMAIN_PREFIXES: frozenset[str] = frozenset({"ir", "investor", "investors"})
IR_PATH_SEGMENTS: frozenset[str] = frozenset({"investor", "investors", "investor-relations"})

# Company apex domains that host IR under a URL path (not a subdomain). V1 seed —
# extend per the finance source-pack. Path-based IR → T1 only for these.
TIER1_IR_PATH_DOMAINS: frozenset[str] = frozenset({"microsoft.com", "abc.xyz"})

# tier → static reputation prior (scale [0,1]); cold-start baseline is T2 = 0.5
TIER_REPUTATION_PRIOR: dict[str, float] = {"T1": 0.9, "T1.5": 0.75, "T2": 0.5}


# ---------------------------------------------------------------------------
# Near-duplicate collapse — SSOT FR-7. Verbatim / near-verbatim reposts of one
# story collapse to ONE independent source before K is counted, so syndicating a
# wire story across many sites cannot inflate independence. MinHash over character
# shingles (local & free, NFR-2) with deterministic salted hashing (NFR-4). The
# threshold is a conservative *near-identical* bar (NOT a calibrated parameter);
# reworded reposts (low overlap, shared rare value) are handled by copy edges (M3.9).
# ---------------------------------------------------------------------------

NEAR_DUP_JACCARD_THRESHOLD: float = 0.85
MINHASH_PERMUTATIONS: int = 128
MINHASH_SHINGLE_CHARS: int = 5


# ---------------------------------------------------------------------------
# Copy-edge (reworded repost) detection — SSOT FR-7. Two NON-T1 sources are
# dependent if they share a rare/idiosyncratic value — a high-precision number or
# a distinctive verbatim quote — that NO T1 source carries. Common official
# figures (round numbers, a rate also present in a T1 filing) never trigger it, to
# avoid false positives. Heuristic V1; full statistical model deferred to V2.
# ---------------------------------------------------------------------------

COPY_EDGE_MIN_SIGNIFICANT_DIGITS: int = 4
COPY_EDGE_MIN_QUOTE_WORDS: int = 6


# ---------------------------------------------------------------------------
# Environment-driven settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Runtime settings from process env / `.env`. Secrets are Optional so the
    offline test suite (NFR-3) imports cleanly without any key; the real LLM/VL
    clients call `require_*_key()` and fail with a clear message if used unset."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- DeepSeek (text LLM; the only paid text provider — §10) ---
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_flash_model: str = "deepseek-v4-flash"  # default for ALL steps
    deepseek_pro_model: str = "deepseek-v4-pro"  # escalation only (NFR-7)

    # --- Local models (free; NFR-2) ---
    whisper_model_size: str = "medium"  # multilingual, NOT the .en variant
    whisper_compute_type: str = "int8"
    # ctranslate2 intra-op threads — pin to the performance-core count (owner
    # 2026-07-20: long-video transcription was leaving cores idle)
    whisper_cpu_threads: int = 4
    # Semantic recall over the knowledge base (owner 2026-07-21): local
    # sentence-transformers embeddings + a persistent local Chroma collection.
    # OFF by default — fresh installs and the offline suite never download an
    # embedding model; the local runtime opts in via ENABLE_SEMANTIC_SEARCH.
    enable_semantic_search: bool = False
    semantic_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    chroma_knowledge_path: str = "data/chroma_knowledge"

    # --- Coverage toggles (best-effort, degradable) ---
    enable_pdf_text: bool = True  # text-layer PDF extraction (M1B.3)
    enable_html_render: bool = False  # Playwright render fallback (M1B.2)
    # In-process hourly poll scheduler (FR-3 / §6.4): OFF by default so tests and a
    # plain `uvicorn app.main:app` never spawn a background scheduler. The local dev
    # runtime (`scripts/dev.sh`) opts in by setting ENABLE_TRACKING_SCHEDULER=true so
    # tracked sources are polled on their interval while the machine is on (polling,
    # not push — no always-on server). The manual POST /tracking/poll works regardless.
    enable_tracking_scheduler: bool = False
    # Scheduler heartbeat: how often the single recurring tick re-reads the current
    # subscriptions and polls the ones whose interval has elapsed. A source is polled
    # on the first tick at/after its own `interval_minutes` (default hourly) elapses,
    # so this only bounds latency, not frequency. Keep it ≤ the smallest interval.
    poll_tick_minutes: int = 5

    # --- Local data paths (Chroma + SQLite; NFR-2) ---
    data_dir: str = "data"
    sqlite_path: str = "data/daily.db"

    # --- API (M2.1) --- local single-operator app; CORS allows the local frontend
    cors_origins: list[str] = ["http://localhost:3000"]

    def require_deepseek_key(self) -> str:
        if not self.deepseek_api_key:
            raise ConfigError(
                "DEEPSEEK_API_KEY is not set. Copy backend/.env.example to "
                "backend/.env and fill in your DeepSeek API key, or export "
                "DEEPSEEK_API_KEY in the environment."
            )
        return self.deepseek_api_key


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton. Tests that need different values
    construct `Settings(...)` directly or clear this cache."""
    return Settings()
