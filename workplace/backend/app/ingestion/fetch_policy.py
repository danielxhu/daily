"""Fetch policy (X0.8, SSOT FR-2 / §6.6).

The single place that encodes *how daily fetches*. Every fetcher (static HTML
M1A.4, render M1B.2, feed/poll Stage 7) builds its client from here, so fetch
behaviour changes in one spot.

daily is a personal, non-commercial tool, so there are no fetch red lines: the
environment's proxy settings are honoured, and cookies/sessions, login, archive
fallbacks, browser impersonation or Scrapling's fetchers (`scrapling[fetchers]`)
may be added wherever they help a source read. What is still fixed here:

- a navigation timeout always exists and render downloads are disabled;
- when a fetch still fails, the caller produces a typed `SourceFailure` whose
  `next_action` comes from the deterministic `NEXT_ACTION` map (§6.6 / FR-2).
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.schemas.models import SourceFailure, SourceFailureKind, SourceType

# Default user agent; hosts that wall it get a browser UA via `fetch_headers`.
FETCH_USER_AGENT = "daily/0.1 (+source tracker; contact via repo)"
FETCH_TIMEOUT_MS = 15000

# Listing pages often inject their article grid after `load`. Bounded wait: heavy
# pages never fully idle, so a timeout still yields what rendered.
RENDER_SETTLE_MS = 5000

# Hosts that answer the bot UA with a verification wall but serve the SAME
# server-rendered article to a plain browser UA (WeChat articles: measured
# 环境异常 wall vs 3.3MB full text on one UA string).
_BROWSER_UA_HOSTS = (
    "mp.weixin.qq.com",
    # consulting-firm sites that serve their pages to a browser UA but wall the
    # bot UA (Accenture article bodies return the full text; others may still
    # time out / disconnect — a wall that persists stays a typed failure)
    "www.accenture.com",
    "accenture.com",
    "www.mckinsey.com",
    "mckinsey.com",
    "www.bcg.com",
    "bcg.com",
)
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


def httpx_client_kwargs() -> dict[str, object]:
    """Shared `httpx` client config: redirects on, default UA, timeout.

    `trust_env=True` lets `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` (and the
    environment's SSL-cert settings) apply, so a proxy is configured the usual
    way — in the shell that starts the backend."""
    return {
        "follow_redirects": True,
        "timeout": FETCH_TIMEOUT_MS / 1000,
        "headers": {"User-Agent": FETCH_USER_AGENT},
        "trust_env": True,
    }


def playwright_context_kwargs() -> dict[str, object]:
    """Playwright `new_context()` kwargs for the render fallback (M1B.2):
    downloads disabled. The caller also sets a default navigation timeout of
    `FETCH_TIMEOUT_MS`."""
    return {
        "accept_downloads": False,
    }


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
    """Build the typed `SourceFailure` a fetcher returns when a source could not
    be read — carries the user-facing next step (FR-2)."""
    return SourceFailure(
        requested_url=requested_url,
        type=source_type,
        kind=kind,
        next_action=next_action_for(kind),
        reason=reason,
    )
