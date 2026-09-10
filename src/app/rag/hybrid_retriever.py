"""Graph ego-graph subgraph UNION vector top-k -> merged context for PolicyAdjudicatorAgent.
Graph and vector legs run concurrently via asyncio.gather.
"""

import asyncio
from typing import Any

from app.rag.embeddings import embed_texts
from app.rag.graph_store import PolicyGraphStore
from app.rag.vector_store import VectorStore


async def retrieve(
    seed_codes: list[str],
    query_text: str,
    graph_store: PolicyGraphStore,
    vector_store: VectorStore,
    domain: str,
    graph_hops: int = 2,
    vector_top_k: int = 6,
    embeddings_client: Any = None,
) -> dict[str, Any]:
    """embeddings_client overrides the real OpenAI client — used by tests."""

    async def graph_leg() -> list[str]:
        return await asyncio.to_thread(graph_store.ego_subgraph_triples, seed_codes, graph_hops)

    async def vector_leg() -> list[dict[str, Any]]:
        embedding = await asyncio.to_thread(embed_texts, [query_text], embeddings_client)
        return await asyncio.to_thread(
            vector_store.similarity_search, embedding[0], vector_top_k, domain
        )

    graph_triples, vector_chunks = await asyncio.gather(graph_leg(), vector_leg())
    return {"graph_triples": graph_triples, "vector_chunks": vector_chunks}
