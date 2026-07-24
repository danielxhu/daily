"""Fetch policy guard (X0.8, SSOT §2.2 / FR-2 / FR-16 / §6.6).

The single place that encodes *how daily is allowed to fetch*. Every fetcher
(static HTML M1A.4, render M1B.2, feed/poll Stage 7, CASR M4.12) builds its client
from here, so the red lines hold **by construction**:

- no user cookies / no stored session, no proxy, no archive-site bypass, no
  login-breaking — paywalled/login/anti-bot content is a typed skip, not a fight;
- a navigation timeout always exists and downloads are disabled;
- CASR fetches are **claim-anchored + whitelist-only**, never topic browsing;
- Scrapling is used **parser-only** (`pip install scrapling`); its `StealthyFetcher`
  / Cloudflare-bypass / proxy-rotation extras (`scrapling[fetchers]`) are NEVER
  installed — the guard holds because that code never enters the environment.

On any fetch failure the caller produces a typed `SourceFailure` whose
`next_action` comes from the deterministic `NEXT_ACTION` map (§6.6 / FR-2).
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.core.config import CASR_WHITELIST
from app.schemas.models import SourceFailure, SourceFailureKind, SourceType

# --- hard policy switches (all OFF; §2.2 red lines) ---
ALLOW_COOKIES = False
ALLOW_PROXY = False
ALLOW_ARCHIVE_BYPASS = False
ALLOW_LOGIN = False

# An honest, static user agent — NOT fingerprint/stealth evasion (§2.2).
FETCH_USER_AGENT = "daily/0.1 (+verification bot; contact via repo)"
FETCH_TIMEOUT_MS = 15000

# Hosts that answer the bot UA with a verification wall but serve the SAME
# server-rendered article to a plain browser UA — no cookies, no login, no
# captcha solving (owner 2026-07-24, WeChat articles: measured 环境异常 wall vs
# 3.3MB full text on one UA string). A static browser UA is the stance the
# yt-dlp video path already takes; a wall that still appears stays a typed
# failure, never bypassed (§2.2).
_BROWSER_UA_HOSTS = ("mp.weixin.qq.com",)
BROWSER_FETCH_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def fetch_headers(url: str) -> dict[str, str] | None:
    """Per-request header override for `client.get`, or None (client defaults)."""
    host = urlsplit(url).netloc.lower()
    if host in _BROWSER_UA_HOSTS:
        return {"User-Agent": BROWSER_FETCH_USER_AGENT}
    return None


class FetchPolicyError(RuntimeError):
    """Raised when a fetch would violate the policy (e.g. CASR off-whitelist)."""


def httpx_client_kwargs() -> dict[str, object]:
    """Shared `httpx` client config: redirects on, honest UA, timeout, and
    explicitly no cookies / no proxy.

    `trust_env=False` is load-bearing: httpx defaults to `trust_env=True`, which
    would pick up `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` from the environment
    and silently route through a proxy — violating the §2.2 no-proxy red line.
    Turning it off also stops env-driven `.netrc`/SSL-cert pickup."""
    return {
        "follow_redirects": True,
        "timeout": FETCH_TIMEOUT_MS / 1000,
        "headers": {"User-Agent": FETCH_USER_AGENT},
        "trust_env": False,
        # no `cookies=`, no `proxy=` — policy: never sent.
    }


def playwright_context_kwargs() -> dict[str, object]:
    """Safe Playwright `new_context()` kwargs for the render fallback (M1B.2):
    downloads disabled, no stored session/cookies, no proxy. The caller also sets
    a default navigation timeout of `FETCH_TIMEOUT_MS`."""
    return {
        "accept_downloads": False,
        # deliberately NO `storage_state` (no cookies/session) and NO `proxy`.
    }


# --- CASR guard (FR-16): claim-anchored + whitelist-only, never topic browsing ---


def casr_domain_allowed(domain: str, *, whitelist: frozenset[str] = CASR_WHITELIST) -> bool:
    """True if `domain` is an authoritative-whitelist host or a subdomain of one.
    `whitelist` defaults to the config `CASR_WHITELIST`; M4.12 retrieval passes the
    per-call whitelist so the same matcher governs both the policy guard and the
    fetched-evidence filter (one source of truth, FR-16)."""
    host = domain.lower().strip().rstrip(".")
    return any(host == wl or host.endswith("." + wl) for wl in whitelist)


def assert_casr_allowed(*, domain: str, claim_anchored: bool) -> None:
    """Raise unless a CASR fetch is both claim-anchored and on the whitelist."""
    if not claim_anchored:
        raise FetchPolicyError(
            "CASR is claim-anchored only; topic browsing is forbidden (FR-16 / §2.2)."
        )
    if not casr_domain_allowed(domain):
        raise FetchPolicyError(
            f"CASR domain {domain!r} is not on the authoritative whitelist (FR-16)."
        )


# --- typed failure → next action (§6.6 / FR-2), deterministic kind→action map ---

NEXT_ACTION: dict[str, str] = {
    "paywall": "Paste the article text and a source label/domain.",
    "login_required": "Paste the article text and a source label/domain.",
    "anti_bot": "Paste the article text and a source label/domain.",
    "js_render_failed": "Retry, or paste the text.",
    "parse_empty": "Retry, or paste the text.",
    "unsupported_file": "Format not supported (e.g. a scanned PDF) — paste the text.",
    "no_captions": "Transcription failed — try another source or paste the text.",
    "transcribe_failed": "Transcription failed — try another source or paste the text.",
    "timeout": "Retry.",
    "fetch_blocked": "Retry.",
    # M14.5: not a failure — the first check skips slow transcription; the item
    # re-queues and the next check processes it.
    "transcription_deferred": "No action needed — the next check transcribes this item.",
}


def next_action_for(kind: SourceFailureKind) -> str:
    return NEXT_ACTION[kind]


def typed_skip(
    kind: SourceFailureKind,
    *,
    reason: str,
    requested_url: str | None = None,
    source_type: SourceType | None = None,
) -> SourceFailure:
    """Build the typed `SourceFailure` a fetcher returns instead of fighting a
    blocked source — carries the user-facing next step (FR-2)."""
    return SourceFailure(
        requested_url=requested_url,
        type=source_type,
        kind=kind,
        next_action=next_action_for(kind),
        reason=reason,
    )
