"""Knowledge answer synthesis (M13.5, owner 2026-07-06 — beta P1-3; on-demand
since M16.2).

The Knowledge ask-surface promised "It answers" while returning bare search hits.
Owner's call: make the promise true with ONE light synthesis pass — a flash call
that answers the user's question grounded STRICTLY in the user's own saved notes,
never the open web. This is the fifth bounded LLM exception NFR-7 allows
(alongside digest categorization, knowledge distillation, the per-item summary,
and evidence-bounded discussion). M16.2 moved it out of the search request path:
`GET /knowledge/search` is deterministic SQLite only, and the synthesis runs only
when the user explicitly asks (`POST /knowledge/answer`). The verified-fact layer
is dormant (v0.13) — callers pass `facts=[]`; the parameter stays so a future
iteration can re-enable it without a signature change.

Honesty rules:
* grounded ONLY in the given hits — no outside knowledge, numbers, or names;
* the user's saved notes are cited AS the user's own saved content, never blended
  into "daily verified that";
* if the hits don't answer the question, the model says so (证据不足 style)
  instead of guessing;
* never a truth verdict — credibility stays calibrated support (§2.2);
* presentation only: any failure degrades to None and the hit cards render as
  before. Nothing is ever written or cached (a question is not deterministic
  input; a single-operator surface doesn't need answer caching).
"""

from __future__ import annotations

from app.clients.base import LLMClient
from app.schemas.models import KnowledgeNote

_ANSWER_SYSTEM = (
    "You answer the user's question using ONLY the user's own saved notes given "
    "as search results. Never add outside knowledge, numbers, names, or "
    "speculation. Cite what you rely on and present it as the user's own saved "
    "content. If the notes cannot answer the question, say the evidence is "
    "insufficient (证据不足) and name what is missing instead of guessing. Never "
    "judge whether a claim is true or false. Reply in the user's language, 1-4 "
    'sentences. Output JSON only: {"answer": "<your answer>"}.'
)

_MAX_ANSWER_CHARS = 1200  # far beyond 4 sentences → the model is rambling, drop it


def _hits_block(saved: list[KnowledgeNote]) -> str:
    """The ONLY material the answer may draw on: the user's own saved notes."""
    lines = []
    for i, note in enumerate(saved, start=1):
        lines.append(f"User's saved note {i}: {note.content}")
    return "\n".join(lines)


def answer_from_hits(
    question: str,
    saved: list[KnowledgeNote],
    *,
    llm: LLMClient,
) -> str | None:
    """One flash call (no escalation) answering the question within the hits.
    Callers must skip the call entirely when there are no hits; any failure or
    unusable output degrades to None — the answer is presentation, never a gate."""
    user = f"{_hits_block(saved)}\n\nQuestion: {question}"
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
