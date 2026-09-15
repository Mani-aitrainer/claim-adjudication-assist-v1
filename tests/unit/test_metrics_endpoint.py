"""P9 'done when': running fixtures populates metrics that /metrics actually serves.

Runs every claims-domain fixture directly through the graph (the HTTP submission endpoint
is P10) in-process, then confirms GET /metrics on the same FastAPI app reflects them —
proving the whole path from agent instrumentation to the scrape endpoint works together.
"""

import glob
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.graph.build_graph import build_graph, run_graph
from app.main import create_app
from app.memory.long_term import SqliteMemoryStore
from app.ocr.fixture_provider import FixtureOCRProvider
from app.persistence.checkpointer import get_checkpointer

from ..conftest import (
    FakeAdjudicatorLLM,
    FakeAuditLLM,
    FakeCopyIntakeLLM,
    FakeEmbeddingsClient,
    FakeRepairLLM,
)

FIXTURE_DIR = "tests/fixtures/textract"


async def test_metrics_endpoint_reflects_a_full_fixture_run(
    tmp_path, graph_store, vector_store
) -> None:
    settings = Settings(
        vector_backend="numpy",
        documents_dir=str(tmp_path / "documents"),
        sqlite_path=str(tmp_path / "checkpoints.sqlite"),
    )
    memory_store = SqliteMemoryStore(str(tmp_path / "memory.sqlite"))
    claim_ids = sorted(Path(p).stem for p in glob.glob("tests/fixtures/claims/CLM-*.pdf"))

    async with get_checkpointer(settings) as checkpointer:
        graph = build_graph(
            checkpointer,
            FixtureOCRProvider(FIXTURE_DIR),
            graph_store,
            vector_store,
            intake_llm=FakeCopyIntakeLLM(),
            repair_llm=FakeRepairLLM(),
            adjudicator_llm=FakeAdjudicatorLLM(),
            auditor_llm=FakeAuditLLM(),
            embeddings_client=FakeEmbeddingsClient(),
            memory_store=memory_store,
        )
        for claim_id in claim_ids:
            run_id = str(uuid.uuid4())
            initial_state = {
                "run_id": run_id,
                "source_uri": f"tests/fixtures/claims/{claim_id}.pdf",
                "domain": "claims",
            }
            await run_graph(graph, initial_state, {"configurable": {"thread_id": run_id}})

    metrics_app = create_app(
        settings=Settings(
            vector_backend="numpy",
            documents_dir=str(tmp_path / "documents2"),
            sqlite_path=str(tmp_path / "checkpoints2.sqlite"),
        )
    )
    with TestClient(metrics_app) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text

    for metric_name in [
        "agent_invocations_total",
        "agent_latency_seconds",
        "graph_runs_total",
        "validation_failures_total",
        "repair_attempts_total",
        "healing_loops_total",
        "quality_score",
        "context_tokens_used",
        "textract_pages_total",
    ]:
        assert metric_name in body, f"{metric_name} missing from /metrics output"

    assert 'agent="PolicyAdjudicatorAgent"' in body
    assert 'outcome="error"' in body  # CLM-011's simulated OCR failure
