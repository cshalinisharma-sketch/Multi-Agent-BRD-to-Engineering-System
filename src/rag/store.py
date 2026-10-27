"""Embeddings + vector store.

Embedding backends
------------------
* ``local-lsa`` (default, offline): TF-IDF (1-2 grams, sublinear tf) projected
  with Truncated SVD (Latent Semantic Analysis) into a dense, L2-normalised
  space. Zero cost, deterministic, runs anywhere. Hybrid mode fuses the dense
  cosine with the sparse TF-IDF cosine (keyword precision for IDs, tech names).
* ``openai`` (text-embedding-3-small) when BRD2ENG_EMBEDDINGS=openai and a key
  is present – better semantics at ~$0.02 / 1M tokens.

Vector store
------------
``NumpyVectorStore``: in-process cosine-similarity store with metadata filters,
persisted to .index/ (npz + json). Interface mirrors Chroma's
(add / query(where=...)) so it can be swapped for Chroma/Qdrant when the corpus
grows (see docs/07_decision_justification.md).
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from .chunker import Chunk


class LocalLSAEmbedder:
    name = "local-lsa"

    def __init__(self, dims: int = 96):
        self.dims = dims
        self.tfidf = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english", min_df=1)
        self.svd: Optional[TruncatedSVD] = None

    def fit(self, texts: list[str]):
        x = self.tfidf.fit_transform(texts)
        n = max(2, min(self.dims, x.shape[0] - 1, x.shape[1] - 1))
        self.svd = TruncatedSVD(n_components=n, random_state=42).fit(x)
        return self

    def sparse(self, texts: list[str]):
        return normalize(self.tfidf.transform(texts))

    def dense(self, texts: list[str]) -> np.ndarray:
        return normalize(self.svd.transform(self.tfidf.transform(texts)))


class OpenAIEmbedder:  # optional, only used when explicitly enabled
    name = "openai:text-embedding-3-small"

    def fit(self, texts):
        return self

    def dense(self, texts: list[str]) -> np.ndarray:
        req = urllib.request.Request(
            "https://api.openai.com/v1/embeddings",
            data=json.dumps({"model": "text-embedding-3-small", "input": texts}).encode(),
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())["data"]
        return normalize(np.array([d["embedding"] for d in data]))

    def sparse(self, texts):
        return None


@dataclass
class Hit:
    chunk_id: str
    text: str
    metadata: dict
    score: float


class NumpyVectorStore:
    def __init__(self, embedder):
        self.embedder = embedder
        self.chunks: list[Chunk] = []
        self.dense: Optional[np.ndarray] = None
        self.sparse = None

    def add(self, chunks: list[Chunk]):
        self.chunks = chunks
        texts = [c.text for c in chunks]
        self.embedder.fit(texts)
        self.dense = self.embedder.dense(texts)
        self.sparse = self.embedder.sparse(texts)

    def _match(self, meta: dict, where: Optional[dict]) -> bool:
        if not where:
            return True
        for k, v in where.items():
            if isinstance(v, dict) and "$in" in v:
                if meta.get(k) not in v["$in"]:
                    return False
            elif meta.get(k) != v:
                return False
        return True

    def similarity(self, texts: list[str], hybrid: bool) -> np.ndarray:
        """Similarity matrix (len(texts) x n_chunks)."""
        q = self.embedder.dense(texts)
        s = q @ self.dense.T
        if hybrid and self.sparse is not None:
            sp = (self.embedder.sparse(texts) @ self.sparse.T).toarray()
            s = 0.5 * s + 0.5 * sp
        return s

    def query(self, text: str, top_k: int, where: Optional[dict] = None, hybrid: bool = True,
              threshold: float = 0.0) -> list[Hit]:
        sims = self.similarity([text], hybrid)[0]
        order = np.argsort(-sims)
        hits = []
        for i in order:
            c = self.chunks[i]
            if not self._match(c.metadata, where):
                continue
            if sims[i] < threshold:
                break
            hits.append(Hit(c.chunk_id, c.text, c.metadata, round(float(sims[i]), 4)))
            if len(hits) >= top_k:
                break
        return hits

    def get(self, chunk_id: str) -> Optional[Chunk]:
        return next((c for c in self.chunks if c.chunk_id == chunk_id), None)

    @property
    def version(self) -> str:
        """Content hash of the indexed knowledge base: same chunks and text -> same version (logged per run)."""
        h = hashlib.sha256()
        for c in self.chunks:
            h.update(f"{c.chunk_id}\0{c.text}\0".encode("utf-8"))
        return h.hexdigest()[:12]

    def save(self, d: Path):
        d.mkdir(parents=True, exist_ok=True)
        with (d / "store.pkl").open("wb") as f:
            pickle.dump({"embedder": self.embedder, "chunks": self.chunks, "dense": self.dense, "sparse": self.sparse}, f)
        (d / "manifest.json").write_text(json.dumps({
            "embedder": self.embedder.name, "kb_version": self.version, "n_chunks": len(self.chunks),
            "by_source_type": {t: sum(1 for c in self.chunks if c.metadata.get("source_type") == t)
                               for t in sorted({c.metadata.get("source_type") for c in self.chunks})},
            "chunk_ids": [c.chunk_id for c in self.chunks]}, indent=2))

    @classmethod
    def load(cls, d: Path) -> "NumpyVectorStore":
        with (d / "store.pkl").open("rb") as f:
            blob = pickle.load(f)
        s = cls(blob["embedder"])
        s.chunks, s.dense, s.sparse = blob["chunks"], blob["dense"], blob["sparse"]
        return s
