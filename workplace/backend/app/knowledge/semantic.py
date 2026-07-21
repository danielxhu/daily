"""Semantic recall over the knowledge base (owner 2026-07-21).

Keyword search cannot bridge the bilingual gap: a Chinese query ("美联储利率")
never matches an item whose stored summary is English ("the Fed held rates").
This layer fixes exactly that — local multilingual sentence-transformers
embeddings in a persistent local Chroma collection, same local-first stance as
whisper (no external service, no cost).

Discipline:
* WRITE path = the background worker tick only (`index_pending`), never a
  request — it self-backfills, a few entries per tick, until the whole base is
  indexed. IDs are namespaced ("item:<id>" / "note:<id>") in ONE collection.
* READ path = one query embedding inside /knowledge/search (~ms on CPU),
  merged AFTER the keyword hits, deduped.
* Fails soft everywhere: any Chroma/model error degrades to keyword-only
  results and the poll/worker never breaks on the index.
* The heavy libs (chromadb / sentence-transformers, `ml` extra) are
  lazy-imported; the offline suite injects a fake embedder + ephemeral client
  and never downloads a model (NFR-3).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings
from app.db.knowledge_store import _row_to_note
from app.db.tracked_item_store import tracked_item_card_by_id
from app.schemas.models import KnowledgeNote, TrackedItemCard

EmbedFn = Callable[[list[str]], list[list[float]]]

# worker-tick indexing budget: small enough to never crowd a tick, large enough
# that a few hundred backlog items drain in minutes
_INDEX_BATCH = 24
_SEARCH_K = 8


class SemanticIndex:
    """Persistent local Chroma collection + lazy multilingual embedder."""

    def __init__(
        self,
        *,
        path: str,
        model_name: str,
        embed_fn: EmbedFn | None = None,  # injectable: tests never load a model
        client: Any | None = None,  # injectable: tests use an ephemeral client
    ) -> None:
        self._path = path
        self._model_name = model_name
        self._embed_fn = embed_fn
        self._client = client
        self._collection: Any | None = None

    # -- lazy plumbing ---------------------------------------------------------

    def _get_collection(self) -> Any:
        if self._collection is None:
            if self._client is None:
                import chromadb  # heavy: lazy (ml extra)

                self._client = chromadb.PersistentClient(path=self._path)
            self._collection = self._client.get_or_create_collection(
                "knowledge", metadata={"hnsw:space": "cosine"}
            )
        return self._collection

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embed_fn is None:
            from sentence_transformers import SentenceTransformer  # heavy: lazy

            model = SentenceTransformer(self._model_name)
            self._embed_fn = lambda batch: [list(map(float, v)) for v in model.encode(batch)]
        return self._embed_fn(texts)

    # -- write side (worker tick) ----------------------------------------------

    def index_pending(self, conn: sqlite3.Connection) -> int:
        """Index up to `_INDEX_BATCH` enriched items + saved notes that are not
        in the collection yet. Called from the worker tick; returns the count
        indexed. Never raises — an index problem must not break the tick."""
        try:
            candidates = _candidates(conn)
            if not candidates:
                return 0
            col = self._get_collection()
            known: set[str] = set(col.get(ids=[cid for cid, _ in candidates])["ids"])
            missing = [(cid, text) for cid, text in candidates if cid not in known]
            batch = missing[:_INDEX_BATCH]
            if not batch:
                return 0
            col.upsert(
                ids=[cid for cid, _ in batch],
                embeddings=self._embed([text for _, text in batch]),
                documents=[text[:2000] for _, text in batch],
            )
            return len(batch)
        except Exception as exc:  # degrade soft — but say WHY, once per tick
            print(f"semantic index degraded (keyword search unaffected): {exc!r}", flush=True)
            return 0

    # -- read side (search request) ---------------------------------------------

    def search(self, query: str, k: int = _SEARCH_K) -> list[str]:
        """Namespaced ids ("item:…"/"note:…") of the k nearest entries; [] on
        any failure (the caller falls back to keyword hits alone)."""
        try:
            col = self._get_collection()
            if col.count() == 0:
                return []
            res = col.query(query_embeddings=self._embed([query]), n_results=k)
            return [str(i) for i in res["ids"][0]]
        except Exception:
            return []


def _candidates(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Everything worth semantic recall: enriched tracked items (title + both
    summaries — the multilingual model makes zh/en interchangeable) and the
    user's saved notes."""
    out: list[tuple[str, str]] = []
    items = conn.execute(
        "SELECT id, title,"
        " json_extract(enrichment, '$.title_zh') AS tz,"
        " json_extract(enrichment, '$.title_en') AS te,"
        " json_extract(enrichment, '$.summary_zh') AS sz,"
        " json_extract(enrichment, '$.summary_en') AS se"
        " FROM tracked_items WHERE enrichment IS NOT NULL"
        " ORDER BY first_seen DESC"
    ).fetchall()
    for r in items:
        text = "\n".join(str(p) for p in (r["title"], r["tz"], r["te"], r["sz"], r["se"]) if p)
        if text:
            out.append((f"item:{r['id']}", text))
    notes = conn.execute("SELECT id, content FROM knowledge_notes").fetchall()
    for r in notes:
        if r["content"]:
            out.append((f"note:{r['id']}", str(r["content"])))
    return out


def resolve_hits(
    conn: sqlite3.Connection, ids: list[str]
) -> tuple[list[KnowledgeNote], list[TrackedItemCard]]:
    """Namespaced index ids → live rows (rows deleted since indexing drop out)."""
    notes: list[KnowledgeNote] = []
    items: list[TrackedItemCard] = []
    for nid in ids:
        kind, _, raw = nid.partition(":")
        if kind == "item":
            card = tracked_item_card_by_id(conn, raw)
            if card is not None:
                items.append(card)
        elif kind == "note":
            row = conn.execute("SELECT * FROM knowledge_notes WHERE id = ?", (raw,)).fetchone()
            if row is not None:
                notes.append(_row_to_note(row))
    return notes, items


_INDEX: SemanticIndex | None = None


def get_semantic_index() -> SemanticIndex | None:
    """Process-wide index when ENABLE_SEMANTIC_SEARCH is on; None = feature off
    (search stays keyword-only, exactly the pre-2026-07-21 behavior)."""
    global _INDEX
    settings = get_settings()
    if not settings.enable_semantic_search:
        return None
    if _INDEX is None:
        _INDEX = SemanticIndex(
            path=settings.chroma_knowledge_path, model_name=settings.semantic_model
        )
    return _INDEX
