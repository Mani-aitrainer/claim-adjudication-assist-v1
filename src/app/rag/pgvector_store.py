"""local (Docker Postgres) or aws (RDS): pgvector cosine similarity over policy_chunks.
See persistence/migrations/001_pgvector.sql for the DDL.
"""

from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from app.rag.vector_store import Chunk


class PgVectorStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self._dsn, autocommit=True)
        register_vector(conn)
        return conn

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> int:
        added = 0
        with self._connect() as conn, conn.cursor() as cur:
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                cur.execute(
                    """
                    INSERT INTO policy_chunks
                        (domain, doc_id, clause_id, page, content, content_hash,
                         metadata, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (content_hash) DO NOTHING
                    """,
                    (
                        chunk["domain"],
                        chunk["doc_id"],
                        chunk["clause_id"],
                        chunk.get("page"),
                        chunk["content"],
                        chunk["content_hash"],
                        Jsonb(chunk.get("metadata", {})),
                        embedding,
                    ),
                )
                added += cur.rowcount
        return added

    def similarity_search(
        self, query_embedding: list[float], top_k: int, domain: str
    ) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                """
                SELECT domain, doc_id, clause_id, page, content, metadata,
                       1 - (embedding <=> %s::vector) AS score
                FROM policy_chunks
                WHERE domain = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_embedding, domain, query_embedding, top_k),
            )
            return [dict(row) for row in cur.fetchall()]

    def count(self, domain: str) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM policy_chunks WHERE domain = %s", (domain,))
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def purge(self, domain: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM policy_chunks WHERE domain = %s", (domain,))
            cur.execute("DELETE FROM policy_graph_edges WHERE domain = %s", (domain,))

    def mirror_graph_edges(self, domain: str, edges: list[dict[str, Any]]) -> None:
        """So a fresh pod can rebuild the graph from Postgres without the pickle file."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM policy_graph_edges WHERE domain = %s", (domain,))
            for edge in edges:
                cur.execute(
                    """
                    INSERT INTO policy_graph_edges
                        (domain, src, src_type, relation, dst, dst_type, clause_id, properties)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        domain,
                        edge["src"],
                        edge["src_type"],
                        edge["relation"],
                        edge["dst"],
                        edge["dst_type"],
                        edge.get("clause_id"),
                        Jsonb(edge.get("properties", {})),
                    ),
                )
