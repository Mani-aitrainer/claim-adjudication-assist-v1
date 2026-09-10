"""P5 'done when': ingest of the generated policy PDFs populates chunks and graph;
the retriever returns triples with clause ids. Uses VECTOR_BACKEND=numpy — zero Docker.
"""

import asyncio
from pathlib import Path

from app.core.settings import Settings
from app.rag.graph_store import PolicyGraphStore
from app.rag.hybrid_retriever import retrieve
from app.rag.vector_store import get_vector_store
from pipelines import data_pipeline

from ..conftest import FakeEmbeddingsClient, FakeGraphExtractionLLM

POLICY_DIR = Path("data/policies")


def _settings(tmp_path: Path) -> Settings:
    return Settings(vector_backend="numpy", documents_dir=str(tmp_path / "documents"))


def _ingest(settings: Settings) -> dict:
    return data_pipeline.ingest(
        POLICY_DIR,
        "claims",
        True,
        settings,
        embeddings_client=FakeEmbeddingsClient(),
        graph_llm=FakeGraphExtractionLLM(),
    )


def test_ingest_populates_chunks_and_graph(tmp_path: Path) -> None:
    result = _ingest(_settings(tmp_path))
    assert result["chunks_inserted"] > 0
    assert result["chunks_total"] == result["chunks_inserted"]
    assert result["graph_nodes"] > 0
    assert result["graph_edges"] > 0


def test_ingest_is_idempotent_by_content_hash(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = _ingest(settings)
    second = _ingest(settings)
    assert second["chunks_inserted"] == 0
    assert second["chunks_total"] == first["chunks_total"]


def test_annexure_and_clause_edges_are_both_present(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _ingest(settings)
    graph_store = PolicyGraphStore()
    graph_store.load(data_pipeline.graph_pickle_path(settings))
    triples = graph_store.ego_subgraph_triples(["CPT-99213"], hops=2)
    assert any("maps_to" in t and "OP-3.2" in t for t in triples)
    assert any("has_sublimit" in t for t in triples)


def test_verify_reports_counts_and_a_sample_similarity_hit(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _ingest(settings)
    result = data_pipeline.verify("claims", settings, embeddings_client=FakeEmbeddingsClient())
    assert result["chunk_count"] > 0
    assert result["graph_nodes"] > 0
    assert result["sample_similarity_hit"] == "OP-3.2"


def test_purge_removes_chunks_and_graph(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _ingest(settings)
    data_pipeline.purge("claims", settings)
    result = data_pipeline.verify("claims", settings, embeddings_client=FakeEmbeddingsClient())
    assert result["chunk_count"] == 0
    assert result["graph_nodes"] == 0


def test_hybrid_retriever_returns_triples_with_clause_ids(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _ingest(settings)

    graph_store = PolicyGraphStore()
    graph_store.load(data_pipeline.graph_pickle_path(settings))
    vector_store = get_vector_store(settings)

    result = asyncio.run(
        retrieve(
            seed_codes=["CPT-99213"],
            query_text="outpatient consultation sub-limit",
            graph_store=graph_store,
            vector_store=vector_store,
            domain="claims",
            graph_hops=2,
            vector_top_k=3,
            embeddings_client=FakeEmbeddingsClient(),
        )
    )

    assert any("OP-3.2" in triple for triple in result["graph_triples"])
    assert len(result["vector_chunks"]) > 0
    assert any(chunk["clause_id"] == "OP-3.2" for chunk in result["vector_chunks"])
