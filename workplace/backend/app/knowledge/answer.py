"""Knowledge answer synthesis (M13.5, owner 2026-07-06 — beta P1-3; on-demand
since M16.2).

The Knowledge ask-surface promised "It answers" while returning bare search hits.
One light synthesis pass — a flash call answering the user's question over the
user's own knowledge base, never the open web. This is the fifth bounded LLM
exception NFR-7 allows (alongside digest categorization, knowledge distillation,
the per-item summary, and evidence-bounded discussion). M16.2 moved it out of the
search request path: `GET /knowledge/search` is deterministic SQLite only, and
the synthesis runs only when the user explicitly asks (`POST /knowledge/answer`).

Owner 2026-07-19 ("太保守了"), matching the item-discussion rewrite of
2026-07-13: the answer genuinely ANSWERS — analysis and inference are welcome
and labeled — and it grounds on BOTH layers of the knowledge base: the user's
saved notes AND the tracked items' AI summaries (which are most of the corpus).

Honesty rules that survive the rewrite:
* the given notes/items stay the factual anchor — never contradict them, never
  fabricate specifics that are in neither the material nor common knowledge;
* saved notes are cited as the user's own content, tracked items as what the
  sources say;
* no concrete buy/sell or investment instructions;
* presentation only: any failure degrades to None and the hit cards render as
  before. Nothing is ever written or cached (a question is not deterministic
  input; a single-operator surface doesn't need answer caching).
"""

from __future__ import annotations

import re

from app.clients.base import LLMClient
from app.schemas.models import KnowledgeNote, TrackedItemCard

_ANSWER_SYSTEM = (
    # owner 2026-07-19: "太保守了" — same posture as the item discussion: answer
    # the question, don't hide behind 证据不足.
    "You answer the user's question over their personal knowledge base; the "
    "search hits below are the user's own saved notes and AI summaries of items "
    "their tracked sources published. Genuinely ANSWER the question — do not "
    "merely recite the hits.\n"
    "- Lead with a direct answer, then the support for it.\n"
    "- Reason, infer, connect dots across hits, and draw out implications; that "
    "analysis is welcome.\n"
    "- You may use general background knowledge to explain and contextualize, "
    "but the hits stay the factual anchor: never contradict them, and never "
    "fabricate specifics (numbers, quotes, events) that are in neither the "
    "hits nor common knowledge.\n"
    "- Keep attribution natural: the user's own notes vs what tracked sources "
    "say vs your inference (e.g. 「你的笔记提到…;来源称…;由此推断,…」). "
    "Never refuse to analyze.\n"
    "- If the hits say nothing directly relevant, say so in ONE short clause, "
    "then still give your best reasoned take, labeled as going beyond them.\n"
    "- No concrete buy/sell or investment instructions.\n"
    "- Reply in the user's language, concise but complete. "
    'Output JSON only: {"answer": "<your answer>"}.'
)

_MAX_ANSWER_CHARS = 2600  # far beyond a substantive answer → rambling, drop it
MAX_ANSWER_ITEMS = 8  # flash-cheap: the top keyword hits, not the whole corpus
_ITEM_SUMMARY_CHARS = 900  # the lede carries the substance; cap the tail


def _item_line(item: TrackedItemCard, question: str) -> str:
    """One grounding line per tracked item: title + the AI summary in the
    question's language (both exist since M16.3; the model may translate)."""
    zh = bool(re.search(r"[一-鿿]", question))
    e = item.enrichment
    summary = (e.summary_zh if zh else e.summary_en) if e else None
    parts = [item.title or item.url or "untitled"]
    if item.domain:
        parts.append(f"({item.domain})")
    line = " ".join(parts)
    if summary:
        line += f": {summary[:_ITEM_SUMMARY_CHARS]}"
    return line


def _hits_block(question: str, saved: list[KnowledgeNote], items: list[TrackedItemCard]) -> str:
    """The factual anchor: the user's saved notes + tracked-item summaries."""
    lines = []
    for i, note in enumerate(saved, start=1):
        lines.append(f"User's saved note {i}: {note.content}")
    for i, item in enumerate(items[:MAX_ANSWER_ITEMS], start=1):
        lines.append(f"Tracked item {i}: {_item_line(item, question)}")
    return "\n".join(lines)


def answer_from_hits(
    question: str,
    saved: list[KnowledgeNote],
    items: list[TrackedItemCard],
    *,
    llm: LLMClient,
) -> str | None:
    """One flash call (no escalation) answering the question over the hits.
    Callers must skip the call entirely when there are no hits; any failure or
    unusable output degrades to None — the answer is presentation, never a gate."""
    user = f"{_hits_block(question, saved, items)}\n\nQuestion: {question}"
    try:
        data = llm.complete_json(system=_ANSWER_SYSTEM, user=user, escalate=False)
    except Exception:
        return None
    answer = data.get("answer")
    if not isinstance(answer, str):
        return None
    cleaned = answer.strip()
    if not cleaned or len(cleaned) > _MAX_ANSWER_CHARS:
        return None
    return cleaned
