"""Item discussion (M16.5; the check-era discussion shapes were removed
2026-07-13 by owner decision).

Chat about ONE tracked item. The item's persisted material — stored content
excerpt, bilingual enrichment, card metadata — is the factual anchor; the
assistant genuinely ANSWERS the question (analysis and inference welcome and
labeled, owner 2026-07-13) instead of merely reciting the source. Flash-only,
READ-ONLY (a discussion writes nothing), never cached.
"""

from __future__ import annotations

from app.clients.base import LLMClient
from app.schemas.models import DiscussMessage, TrackedItemCard


class DiscussError(RuntimeError):
    """The LLM failed or returned an unusable reply — surfaced as HTTP 502."""


_ITEM_DISCUSS_SYSTEM = (
    # owner 2026-07-13: "回答不能只回答来源中的事实信息,而是根据来源中的信息,
    # 回答用户的问题,不要太局限了" — the assistant ANSWERS the question, with the
    # item's material as the factual anchor; analysis and inference are welcome
    # and labeled, instead of hiding behind 证据不足.
    "You are discussing ONE tracked item with the user; its stored source "
    "excerpt and AI summary are given below. Genuinely ANSWER the user's "
    "question — do not merely recite the source.\n"
    "- Lead with a direct answer to what was asked.\n"
    "- Reason, infer, connect dots, and draw out implications beyond the "
    "literal text; that analysis is welcome.\n"
    "- You may use general background knowledge to explain and contextualize, "
    "but the item's material stays the factual anchor: never contradict it, "
    "and never fabricate specifics (numbers, quotes, events) that are in "
    "neither the source nor common knowledge.\n"
    "- Keep attribution natural and honest: distinguish 来源明确提到的 from "
    "你基于来源的分析推断 (e.g. 「来源提到…;由此看,…」). Never refuse to "
    "analyze.\n"
    "- If the source says nothing directly relevant, say so in ONE short "
    "clause, then still give your best reasoned take, labeled as going beyond "
    "the source.\n"
    "- No concrete buy/sell or investment instructions.\n"
    "- Reply in the user's language. "
    'Output JSON only: {"reply": "<your reply>"}'
)

# more generous than the enrichment call's input cap: a discussion is a manual,
# single-item action, and follow-up questions need the source's detail
_DISCUSS_EXCERPT_CHARS = 8_000


def _item_material_block(card: TrackedItemCard, excerpt: str) -> str:
    """The item's material — the factual anchor the discussion reasons from:
    the card metadata, its bilingual enrichment, and the stored source excerpt."""
    lines = [f"Title: {card.title or '(untitled)'}"]
    if card.domain:
        tier = f" (tier {card.tier})" if card.tier else ""
        lines.append(f"Source domain: {card.domain}{tier}")
    if card.published:
        lines.append(f"Published: {card.published}")
    e = card.enrichment
    if e is not None:
        lines.append(f"AI summary (zh): {e.summary_zh}")
        lines.append(f"AI summary (en): {e.summary_en}")
        if e.why_zh:
            lines.append(f"Why it matters (zh): {e.why_zh}")
        if e.why_en:
            lines.append(f"Why it matters (en): {e.why_en}")
        if e.entities:
            lines.append("Entities named in the source: " + ", ".join(e.entities))
        limits = " / ".join(x for x in (e.limitations_zh, e.limitations_en) if x)
        if limits:
            lines.append(f"Summary limitations: {limits}")
    lines.append(f"Source excerpt:\n{excerpt[:_DISCUSS_EXCERPT_CHARS]}")
    return "\n".join(lines)


def discuss_tracked_item(
    card: TrackedItemCard,
    excerpt: str,
    messages: list[DiscussMessage],
    *,
    llm: LLMClient,
) -> str:
    """Discuss a tracked item — one flash call (no escalation) answering the
    latest user turn with the item's persisted material as the anchor. Raises
    DiscussError on any LLM failure or unusable reply."""
    convo = "\n".join(f"{m.role}: {m.content}" for m in messages)
    user = "\n\n".join([_item_material_block(card, excerpt), f"Conversation so far:\n{convo}"])
    try:
        data = llm.complete_json(system=_ITEM_DISCUSS_SYSTEM, user=user, escalate=False)
    except Exception as exc:
        raise DiscussError(str(exc)) from exc
    reply = data.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        raise DiscussError("model returned no usable reply")
    return reply.strip()
