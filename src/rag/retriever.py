"""Retriever = vector store + retrieval profile + per-run provenance registry.

The registry records every chunk each agent retrieved. The hallucination
guardrail later checks that every citation in an artifact refers to a chunk
that the citing agent actually retrieved in this run.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..config import AGENT_SOURCE_FILTERS, INDEX_DIR, KB_DIR, RetrievalProfile
from .chunker import chunk_knowledge_base
from .store import Hit, LocalLSAEmbedder, NumpyVectorStore


def build_index(kb_dir: Path = KB_DIR, index_dir: Path = INDEX_DIR) -> NumpyVectorStore:
    chunks = chunk_knowledge_base(kb_dir)
    store = NumpyVectorStore(LocalLSAEmbedder())
    store.add(chunks)
    store.save(index_dir)
    return store


def load_or_build(kb_dir: Path = KB_DIR, index_dir: Path = INDEX_DIR) -> NumpyVectorStore:
    newest_src = max(p.stat().st_mtime for p in kb_dir.rglob("*") if p.is_file())
    pkl = index_dir / "store.pkl"
    if pkl.exists() and pkl.stat().st_mtime >= newest_src:
        return NumpyVectorStore.load(index_dir)
    return build_index(kb_dir, index_dir)


class Retriever:
    def __init__(self, store: NumpyVectorStore, profile: RetrievalProfile, logger=None):
        self.store = store
        self.profile = profile
        self.logger = logger
        self.registry: dict[str, dict[str, Hit]] = {}

    def search(self, agent: str, query: str, top_k: Optional[int] = None, source_types: Optional[list[str]] = None,
               where: Optional[dict] = None, span: Optional[dict] = None, threshold: Optional[float] = None) -> list[Hit]:
        p = self.profile
        filt = dict(where or {})
        if p.use_metadata_filters:
            types = source_types or AGENT_SOURCE_FILTERS.get(agent)
            if types:
                filt["source_type"] = {"$in": types}
        elif source_types and len(source_types) == 1:
            # even the baseline honours a hard single-source lookup (e.g. timelines table)
            filt["source_type"] = source_types[0]
        hits = self.store.query(query, top_k or p.top_k, filt or None, hybrid=p.hybrid,
                                 threshold=p.sim_threshold if threshold is None else threshold)
        reg = self.registry.setdefault(agent, {})
        for h in hits:
            reg[h.chunk_id] = h
        if span is not None:
            span.setdefault("rag_chunks", []).extend({"id": h.chunk_id, "score": h.score} for h in hits)
        if self.logger:
            self.logger.log("tool_call", tool="kb_search", agent=agent, ok=True, n_hits=len(hits),
                            filters=filt or None, top_k=top_k or p.top_k,
                            chunk_ids=[h.chunk_id for h in hits])
        return hits

    def cite(self, agent: str, item_text: str, candidates: list[Hit], max_n: int = 2) -> list[str]:
        """Attach citations: candidates whose similarity to the item text clears cite_threshold."""
        if not candidates:
            return []
        sims = self.store.similarity([item_text], self.profile.hybrid)[0]
        idx = {c.chunk_id: i for i, c in enumerate(self.store.chunks)}
        scored = sorted(((sims[idx[h.chunk_id]], h.chunk_id) for h in candidates if h.chunk_id in idx), reverse=True)
        return [cid for s, cid in scored[:max_n] if s >= self.profile.cite_threshold]

    def support(self, item_text: str, chunk_ids: list[str]) -> float:
        """Max similarity between a claim and the chunks it cites (hallucination check)."""
        idx = {c.chunk_id: i for i, c in enumerate(self.store.chunks)}
        ids = [idx[c] for c in chunk_ids if c in idx]
        if not ids:
            return 0.0
        sims = self.store.similarity([item_text], True)[0]
        return float(max(sims[i] for i in ids))

    def text_sim(self, texts: list[str], other: str) -> list[float]:
        """Cosine similarity of each text to `other` in the embedding space."""
        e = self.store.embedder
        a, b = e.dense(texts), e.dense([other])
        return [float(x) for x in (a @ b.T)[:, 0]]

    def retrieved(self, agent: str) -> set[str]:
        return set(self.registry.get(agent, {}))
