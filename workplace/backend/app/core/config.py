"""Pinned configuration for daily (X0.2).

Two kinds of config live here:

1. **Code-pinned constants** — source-tier tables, dedup thresholds,
   reproducibility seed, prompt version. These are NOT environment-driven; they
   are part of the engineering contract (NFR-4) and covered by unit tests.

2. **Environment-driven settings** (`Settings`) — API keys, base URLs, model ids,
   feature toggles, local model names, data paths. Loaded from process env / `.env`.

Constants trace to the engineering design doc (v0.11).
Section references in comments point there.
"""

from __future__ import annotations

import functools
from typing import Literal

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


# M14.6: the digest/Today VIEW window covers recent changes, not just today —
# this is how far back the briefing looks by default; the user adjusts it per
# request (?window_days).
DIGEST_WINDOW_DAYS: int = 30

# M13.4 (beta P1-2): a NEVER-polled subscription's first check picks up only the
# latest N items — the older backlog is marked seen and skipped for good, so a
# fresh source answers in ~one item's pipeline time instead of a minutes-long
# synchronous drain of the whole feed. Later polls are genuinely incremental.
FIRST_POLL_ITEM_CAP: int = 5

# M14.7: the per-poll LLM-call budget for the
# digest enrichment backfill (summaries + categories, write-side). Bounds the
# poll's tail cost while the backlog warms; must stay ≥ DRAIN_MAX_CLAIMS so
# enrichment keeps pace with facts graduating from the pending pool. The digest
# READ path never calls the LLM — misses render as placeholders until the next
# poll fills them in.
DIGEST_BACKFILL_MAX: int = 80


# ---------------------------------------------------------------------------
# Source tiering — SSOT FR-12 / §3.1.1. Deterministic config table + heuristics
# (code, not LLM — NFR-7). T1 = primary/official (regulators, central banks,
# exchanges, gov statistics, company IR); T1.5 = official social handles; T2 =
# everyone else (media / aggregator / KOL / unknown) and any source with no
# resolvable domain (FR-7).
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
    # transcription backend: "auto" picks the Apple-GPU mlx
    # path when mlx-whisper is importable (Apple Silicon), else the portable
    # CPU faster-whisper path — a Linux server deploys with zero changes.
    whisper_backend: Literal["auto", "mlx", "faster"] = "auto"
    # an HF repo id, or a local directory with config.json + weights
    whisper_mlx_model: str = "mlx-community/whisper-large-v3-turbo"
    # ctranslate2 intra-op threads — pin to the performance-core count
    # (long-video transcription was leaving cores idle at the default)
    whisper_cpu_threads: int = 4
    # Semantic recall over the knowledge base: local
    # sentence-transformers embeddings + a persistent local Chroma collection.
    # OFF by default — fresh installs and the offline suite never download an
    # embedding model; the local runtime opts in via ENABLE_SEMANTIC_SEARCH.
    enable_semantic_search: bool = False
    semantic_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    chroma_knowledge_path: str = "data/chroma_knowledge"
    # On-device image OCR for image-note ingestion: "auto" uses Apple Vision
    # when pyobjc is importable ([ocr] extra, macOS-only), else image reading
    # is skipped — free, local, no key.
    image_ocr: Literal["auto", "off"] = "auto"

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
