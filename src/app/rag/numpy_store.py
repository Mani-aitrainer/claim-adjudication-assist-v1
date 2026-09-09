"""local, zero-Docker: in-memory cosine similarity over a JSON file on disk, so separate
CLI invocations (ingest, then query) share state without needing Postgres running.
"""

import json
from pathlib import Path
from typing import Any

import numpy as np

from app.rag.vector_store import Chunk


class NumpyVectorStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._rows: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if self._path.exists():
            return list(json.loads(self._path.read_text(encoding="utf-8")))
        return []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._rows, indent=2), encoding="utf-8")

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> int:
        existing_hashes = {row["content_hash"] for row in self._rows}
        added = 0
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            if chunk["content_hash"] in existing_hashes:
                continue
            self._rows.append({**chunk, "embedding": embedding})
            existing_hashes.add(chunk["content_hash"])
            added += 1
        if added:
            self._save()
        return added

    def similarity_search(
        self, query_embedding: list[float], top_k: int, domain: str
    ) -> list[dict[str, Any]]:
        candidates = [row for row in self._rows if row["domain"] == domain]
        if not candidates:
            return []
        query = np.array(query_embedding)
        query_norm = np.linalg.norm(query) or 1.0
        scored = []
        for row in candidates:
            vec = np.array(row["embedding"])
            score = float(np.dot(query, vec) / (query_norm * (np.linalg.norm(vec) or 1.0)))
            scored.append((score, row))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [{**row, "score": score} for score, row in scored[:top_k]]

    def count(self, domain: str) -> int:
        return sum(1 for row in self._rows if row["domain"] == domain)

    def purge(self, domain: str) -> None:
        self._rows = [row for row in self._rows if row["domain"] != domain]
        self._save()
