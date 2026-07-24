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

Owner 2026-07-23 ("做方案0"): grounding is the WHOLE knowledge base, not the
top search hits. At this product's scale (≤~200 items, each already a compact
summary) the full corpus fits one flash call — synthesis questions ("综合这些
信息我该往哪个方向创业") see everything, and there is no query router to
misroute. The search hits (keyword + semantic) become a relevance HINT
appended after the corpus; the corpus itself is ordered newest-first and
truncated at a char budget (oldest dropped, honestly marked). The corpus
block precedes the hint + question so consecutive questions share a stable
prompt prefix (provider-side context caching).

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
    "You answer the user's question over their PERSONAL KNOWLEDGE BASE, given "
    "in full below, newest first: the user's own saved notes and AI summaries "
    "of items their tracked sources published. Genuinely ANSWER the question — "
    "do not merely recite the entries.\n"
    "- Lead with a direct answer, then the support for it.\n"
    "- Reason, infer, connect dots across entries, and draw out implications; "
    "for a broad or synthesis question, survey the WHOLE base; for a specific "
    "one, focus on the relevant entries (a search may flag likely matches after "
    "the entries) and ignore the rest.\n"
    "- You may use general background knowledge to explain and contextualize, "
    "but the entries stay the factual anchor: never contradict them, and never "
    "fabricate specifics (numbers, quotes, events) that are in neither the "
    "entries nor common knowledge.\n"
    "- Keep attribution natural: the user's own notes vs what tracked sources "
    "say vs your inference (e.g. 「你的笔记提到…;来源称…;由此推断,…」). "
    "Never refuse to analyze.\n"
    "- If the entries say nothing directly relevant, say so in ONE short clause, "
    "then still give your best reasoned take, labeled as going beyond them.\n"
    "- No concrete buy/sell or investment instructions.\n"
    "- Reply in the user's language, concise but complete. "
    'Output JSON only: {"answer": "<your answer>"}.'
)

_MAX_ANSWER_CHARS = 2600  # far beyond a substantive answer → rambling, drop it
# ~200 compact summaries; well inside the flash context window. Oldest entries
# beyond the budget are dropped with an honest marker line.
_CORPUS_CHAR_BUDGET = 100_000
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


def _corpus_block(
    question: str,
    saved: list[KnowledgeNote],
    items: list[TrackedItemCard],
    hit_ids: set[str],
) -> tuple[str, int, str]:
    """The factual anchor: the WHOLE knowledge base, newest first, capped at the
    char budget (oldest items dropped with a marker). Returns (block, how many
    entries were fed, the search-hint line — empty when nothing matched)."""
    lines: list[str] = []
    used = 0
    fed = 0
    hit_labels: list[str] = []
    for i, note in enumerate(saved, start=1):
        line = f"User's saved note {i}: {note.content}"
        if used + len(line) > _CORPUS_CHAR_BUDGET:
            break
        lines.append(line)
        used += len(line)
        fed += 1
        if note.id in hit_ids:
            hit_labels.append(f"note {i}")
    for i, item in enumerate(items, start=1):
        line = f"Tracked item {i}: {_item_line(item, question)}"
        if used + len(line) > _CORPUS_CHAR_BUDGET:
            lines.append(f"(… {len(items) - i + 1} older items omitted for length)")
            break
        lines.append(line)
        used += len(line)
        fed += 1
        if item.id in hit_ids:
            hit_labels.append(f"item {i}")
    hint = (
        "A keyword/semantic search over this knowledge base matched: " + ", ".join(hit_labels)
        if hit_labels
        else ""
    )
    return "\n".join(lines), fed, hint


def answer_over_knowledge(
    question: str,
    saved: list[KnowledgeNote],
    items: list[TrackedItemCard],
    hit_ids: set[str],
    *,
    llm: LLMClient,
) -> tuple[str, int] | None:
    """One flash call (no escalation) answering the question over the whole
    knowledge base; `hit_ids` marks the entries the search surface matched (a
    relevance hint, never a filter). Callers must skip the call entirely when
    the base is empty; any failure or unusable output degrades to None — the
    answer is presentation, never a gate. Returns (answer, entries fed)."""
    corpus, fed, hint = _corpus_block(question, saved, items, hit_ids)
    # corpus first, hint + question last: consecutive questions over the same
    # base share a stable prefix for provider-side context caching
    user = (
        f"{corpus}\n\n{hint}\n\nQuestion: {question}"
        if hint
        else (f"{corpus}\n\nQuestion: {question}")
    )
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
    return cleaned, fed
