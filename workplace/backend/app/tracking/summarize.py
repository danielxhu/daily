"""Per-item bilingual enrichment — this module's only job since the
verification engine's removal (2026-07-13; the verified-fact digest briefing
and its `digest_summaries` cache path were deleted with it, and the leftover
`_SUMMARIZE_SYSTEM` prompt was removed 2026-07-23).

`enrich_fetched_item` briefs ONE just-fetched tracked item from its content
excerpt: one cheapest-tier (flash, no escalation) LLM call producing the
bilingual summaries, faithful title translations, and topic tags that the
whole knowledge surface is built from (cards, search, the corpus-wide
answer). Grounded ONLY in the given excerpt/title/domain — the content is
unverified, so the summary describes what the source SAYS (claims attributed
to it), never a truth verdict. Best-effort: any failure degrades to None —
a summary is presentation, it never blocks the item's lifecycle.

Generation runs write-side (M14.7, owner 2026-07-07 "为什么这么慢"): the poll
dispatch, the background worker, a manual refresh, and the backfill call this;
read surfaces only render what was stored. Summary length scales with content
length (owner 2026-07-21) — see `_ENRICH_TIERS` below.
"""

from __future__ import annotations

from app.clients.base import LLMClient
from app.schemas.models import ItemEnrichment

_ITEM_ENRICH_BASE = (
    "You brief ONE source item a tracking tool just fetched (a news article, "
    "transcript, or page text; topics span politics, economics, and technology). "
    "Ground EVERYTHING only in the given content excerpt, title, and source "
    "domain — never add outside knowledge, numbers, names, or speculation. The "
    "content is NOT verified: describe what the source SAYS (attribute claims to "
    "it), never assert truth yourself, never judge credibility, never give "
    "investment advice. Neutral, plain language, no hype. Produce BOTH languages "
    "regardless of the source language. "
)

_ITEM_ENRICH_JSON = (
    " Information-dense, no padding. Output JSON only: "
    '{"summary_zh": "<中文综述,按上述段落规划,段落间以空行分隔,仍是来源口吻,不加外部知识>", '
    '"summary_en": "<the summary in English, same paragraph plan, blank lines '
    'between paragraphs, still attributed to the source, no outside knowledge>", '
    '"title_zh": "<原标题的中文版:忠实翻译,原文已是中文则原样保留,不改写不美化>", '
    '"title_en": "<the title in English: faithful translation, keep as-is if already English>", '
    '"tags": ["<2-6 short lowercase topic tags>"]}'
)

# owner 2026-07-21 ("综述长度根据内容长度来"): the paragraph plan AND how much
# source material the model sees both scale with the content. Three tiers keyed
# on the full text length; each tuple = (excerpt chars fed to the LLM, plan).
# owner 2026-07-24 "综述再长一点": every tier bumped one notch, and the top
# tier now reads the full stored excerpt (40k, the DB cap) instead of 30k.
_ENRICH_TIERS: list[tuple[int, int, str]] = [
    # short pieces: fuller than before, but still no padding beyond the material
    (
        3_000,
        10_000,
        "Each summary is 2-3 substantial paragraphs separated by blank lines: "
        "the core event with the key figures/dates and actors; the substantive "
        "detail — arguments, evidence, and numbers as the source gives them; "
        "then any background or next steps the source mentions. Draw on "
        "everything the source offers, but never pad beyond it.",
    ),
    # the typical article (owner 2026-07-17 '三段左右'; 2026-07-24 longer still)
    (
        15_000,
        15_000,
        "Each summary is 4-5 paragraphs separated by blank lines (\\n\\n): "
        "① the core event with the key figures/dates and actors; ②-④ the "
        "substantive detail — arguments, evidence, positions, and numbers as the "
        "source gives them, in the source's own order; ⑤ the background and "
        "next steps the source mentions. Be generous with detail — the reader "
        "wants the summary to stand in for the article.",
    ),
    # hours-long transcripts / long reports: cover the whole arc, not the lede
    (
        2**63,
        40_000,
        "The material is LONG (an hours-long talk, stream, or report). Each "
        "summary is 6-10 paragraphs separated by blank lines, organized by theme "
        "in the source's order: open with the core message, then walk EVERY "
        "major section/argument with its figures and positions as the source "
        "gives them, and close with the background and next steps it mentions. "
        "Cover the WHOLE excerpt — the later parts matter as much as the start, "
        "and the reader wants the summary to stand in for the source.",
    ),
]

# sanity guard against runaway output, not a style control (style = the plan)
_MAX_SUMMARY = 8000


def _enrich_plan(text_len: int) -> tuple[int, str]:
    """(excerpt chars to feed, paragraph plan) for this content length."""
    for cutoff, excerpt_chars, plan in _ENRICH_TIERS:
        if text_len <= cutoff:
            return excerpt_chars, plan
    raise AssertionError("unreachable — the last tier cutoff is unbounded")


def _opt_str(value: object, cap: int) -> str | None:
    """A secondary field: keep it only when it is a sane string — a bad optional
    field never sinks the enrichment (the summaries are the contract)."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned and len(cleaned) <= cap else None


def _str_list(value: object, *, cap: int, item_cap: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for v in value:
        if isinstance(v, str):
            cleaned = v.strip()
            if cleaned and len(cleaned) <= item_cap:
                out.append(cleaned)
        if len(out) == cap:
            break
    return out


def enrich_fetched_item(
    text: str,
    *,
    title: str | None,
    domain: str | None,
    llm: LLMClient,
    errors: list[str] | None = None,
) -> ItemEnrichment | None:
    """M16.3 (owner 2026-07-08): ONE flash call (no escalation) producing the
    BILINGUAL enrichment for a just-fetched tracked item — zh + en summaries in
    the same response, so the locale toggle switches instantly without another
    call. Same NFR-7 exception (3) as the M15.2 single-language briefing it
    replaces. None on any failure or unusable summaries (both languages are the
    contract; optional fields degrade individually); the caller persists nothing
    on None — the UI shows an honest pending state, never a fabricated line."""
    stripped = text.strip()
    if not stripped:
        return None
    # summary length follows content length (owner 2026-07-21): a 2h transcript
    # gets a wider excerpt AND a longer paragraph plan than a short article
    excerpt_chars, plan = _enrich_plan(len(stripped))
    excerpt = stripped[:excerpt_chars]
    user = (
        f"Title: {title or 'unknown'}\nSource domain: {domain or 'unknown'}\n"
        f"Content excerpt:\n{excerpt}"
    )
    try:
        data = llm.complete_json(
            system=_ITEM_ENRICH_BASE + plan + _ITEM_ENRICH_JSON, user=user, escalate=False
        )
    except Exception as exc:
        # degrade to None (poll path), but let a manual caller see WHY — e.g. an
        # API-balance error must reach the user, not hide behind "failed"
        if errors is not None:
            errors.append(str(exc))
        return None
    summary_zh = data.get("summary_zh")
    summary_en = data.get("summary_en")
    if not isinstance(summary_zh, str) or not isinstance(summary_en, str):
        return None
    summary_zh = summary_zh.strip()
    summary_en = summary_en.strip()
    if not summary_zh or not summary_en:
        return None
    if len(summary_zh) > _MAX_SUMMARY or len(summary_en) > _MAX_SUMMARY:
        return None
    return ItemEnrichment(
        summary_zh=summary_zh,
        summary_en=summary_en,
        title_zh=_opt_str(data.get("title_zh"), 300),
        title_en=_opt_str(data.get("title_en"), 300),
        tags=_str_list(data.get("tags"), cap=8, item_cap=40),
    )
