"""Hostile-source classifier (M1B.4, SSOT §FR-2 / §2.2).

Classifies a fetched response into a typed `SourceFailureKind` —
`paywall` / `login_required` / `anti_bot` / `fetch_blocked` — so the user gets the
right next step ("paste the text + a source label/domain"). We NEVER attempt a
workaround: no cookies, no proxy, no archive-site bypass, no captcha / fingerprint
/ stealth (§2.2). The honest answer to a hostile source is to ask the user to
paste the text.

Pure heuristics over status code + body markers — code, not an LLM (NFR-7). The
markers are deliberately specific so a normal article that merely says
"subscribe" or "sign in" is not misclassified.
"""

from __future__ import annotations

from app.schemas.models import SourceFailureKind

# Cloudflare / captcha interstitials. Body markers, regardless of status code
# (challenge pages are sometimes served with 200).
_ANTI_BOT_MARKERS = (
    "just a moment...",
    "attention required! | cloudflare",
    "checking your browser before accessing",
    "cf-browser-verification",
    "enable javascript and cookies to continue",
    "verify you are human",
    "/cdn-cgi/challenge-platform",
)
_PAYWALL_MARKERS = (
    "subscribe to continue reading",
    "this article is for subscribers",
    "subscribers only",
    "to continue reading, subscribe",
    "you've reached your article limit",
    "metered paywall",
)
_LOGIN_MARKERS = (
    "please log in to continue",
    "sign in to read",
    "you must be logged in",
    "log in to your account to continue",
)


def _has(body: str, markers: tuple[str, ...]) -> bool:
    low = body.lower()
    return any(m in low for m in markers)


def classify_hostile(*, status_code: int, body: str = "") -> SourceFailureKind | None:
    """Return the typed hostile kind for a response, or `None` if it looks
    fetchable. Specific body markers win over generic status codes."""
    # Specific body markers first (a hostile interstitial can be served with 200).
    if _has(body, _ANTI_BOT_MARKERS):
        return "anti_bot"
    if _has(body, _PAYWALL_MARKERS):
        return "paywall"
    if _has(body, _LOGIN_MARKERS):
        return "login_required"
    # Status-code signals.
    if status_code == 402:
        return "paywall"
    if status_code == 401:
        return "login_required"
    if status_code == 429:
        return "anti_bot"  # rate-limited by bot defense
    if status_code >= 400:
        return "fetch_blocked"  # blocked, but no more specific signal
    return None
