"""Domain normalization (M1A.2).

Turns a user-supplied `declared_domain` (or, later, a URL host — M1A.3 reuses
this) into a normalized host, or `None` when it isn't a plausible domain. Only a
normalized, validated domain may count toward independence N/K (FR-7); a `None`
domain (pasted text, unclassifiable host) is excluded.

V1 uses a stdlib host + shape check. Registrable-domain collapsing (public-suffix
via `tldextract`, §6.1) is layered on when the URL router (M1A.3) / independence
(M3.10) need it — without changing this signature.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# A hostname: dot-separated labels + a 2–63 char alpha TLD, total ≤ 253 chars.
_HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def normalize_domain(raw: str | None) -> str | None:
    """Normalize a declared domain / URL to a bare lowercased host, or `None`.

    Accepts `reuters.com`, `www.reuters.com`, `https://www.reuters.com/a?b=1`;
    rejects `not a domain`, `localhost`, empty/None."""
    if not raw:
        return None
    s = raw.strip().lower()
    if "://" in s:
        s = urlsplit(s).netloc
    s = s.split("/", 1)[0]  # drop any path
    s = s.split("@")[-1]  # drop userinfo
    s = s.split(":", 1)[0]  # drop port
    if s.startswith("www."):
        s = s[4:]
    if not _HOST_RE.match(s):
        return None
    return s
