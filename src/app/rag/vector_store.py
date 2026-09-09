"""VectorStore protocol + factory. local -> NumpyVectorStore or PgVectorStore (Docker
Postgres) depending on VECTOR_BACKEND. aws -> PgVectorStore on RDS. pgvector_store's psycopg
import only happens when the pgvector backend is actually selected.
"""

from pathlib import Path
from typing import Any, Protocol, TypedDict

from app.core.settings import Settings


class Chunk(TypedDict):
    domain: str
    doc_id: str
    clause_id: str
    page: int | None
    content: str
    content_hash: str
    metadata: dict[str, Any]


class VectorStore(Protocol):
    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> int:
        """Inserts chunks not already present (by content_hash). Returns count inserted."""
        ...

    def similarity_search(
        self, query_embedding: list[float], top_k: int, domain: str
    ) -> list[dict[str, Any]]:
        """Returns the top_k most similar chunks for `domain`, each with a `score` key."""
        ...

    def count(self, domain: str) -> int: ...

    def purge(self, domain: str) -> None: ...


def get_vector_store(settings: Settings) -> VectorStore:
    if settings.vector_backend == "pgvector":
        from app.rag.pgvector_store import PgVectorStore

        return PgVectorStore(settings.postgres_dsn)

    from app.rag.numpy_store import NumpyVectorStore

    # data/graph/ already holds claims.gpickle — keep the zero-Docker vector store beside it.
    graph_dir = Path(settings.documents_dir).parent / "graph"
    return NumpyVectorStore(graph_dir / "numpy_vector_store.json")
