"""P3 'done when': the graph runs end to end on CLM-001, and checkpoints are written.
P4 'done when': CLM-006 recovers in one loop; CLM-007 falls back; CLM-014 is not repaired.
P7 'done when': CLM-012 triggers exactly one heal loop and improves.
"""

import asyncio
import json
import uuid
from typing import Any

import pytest

from app.core.settings import Settings
from app.graph.build_graph import build_graph
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


async def _run_async(
    tmp_path,
    graph_store,
    vector_store,
    pdf_name: str,
    adjudicator_llm: Any = None,
    memory_store: Any = None,
):
    settings = Settings(sqlite_path=str(tmp_path / "checkpoints.sqlite"))
    ocr_provider = FixtureOCRProvider(FIXTURE_DIR)
    run_id = str(uuid.uuid4())
    resolved_adjudicator_llm = (
        adjudicator_llm if adjudicator_llm is not None else FakeAdjudicatorLLM()
    )

    async with get_checkpointer(settings) as checkpointer:
        graph = build_graph(
            checkpointer,
            ocr_provider,
            graph_store,
            vector_store,
            intake_llm=FakeCopyIntakeLLM(),
            repair_llm=FakeRepairLLM(),
            adjudicator_llm=resolved_adjudicator_llm,
            auditor_llm=FakeAuditLLM(),
            embeddings_client=FakeEmbeddingsClient(),
            memory_store=memory_store,
        )
        config = {"configurable": {"thread_id": run_id}}
        final_state = await graph.ainvoke(
            {
                "run_id": run_id,
                "source_uri": f"tests/fixtures/claims/{pdf_name}.pdf",
                "domain": "claims",
            },
            config=config,
        )
        checkpoints = [c async for c in checkpointer.alist(config)]
        return final_state, checkpoints


def _run(
    tmp_path, graph_store, vector_store, pdf_name: str, adjudicator_llm: Any = None,
    memory_store: Any = None,
):
    return asyncio.run(
        _run_async(tmp_path, graph_store, vector_store, pdf_name, adjudicator_llm, memory_store)
    )


def test_clm001_runs_end_to_end_and_writes_checkpoints(tmp_path, graph_store, vector_store) -> None:
    final_state, checkpoints = _run(tmp_path, graph_store, vector_store, "CLM-001")
    assert final_state["extracted_fields"]["member_id"] == "MEM1001"
    assert final_state["validation"]["is_valid"] is True
    assert final_state["decision"]["status"] == "APPROVE"
    assert final_state.get("heal_attempts", 0) == 0
    assert len(checkpoints) > 0


def test_clm014_runs_end_to_end_and_is_not_repaired(tmp_path, graph_store, vector_store) -> None:
    final_state, _ = _run(tmp_path, graph_store, vector_store, "CLM-014")
    assert final_state["validation"]["is_valid"] is False
    codes = {e["code"] for e in final_state["validation"]["errors"]}
    assert "POLICY_WINDOW" in codes
    assert final_state.get("retry_count", 0) == 0  # unrepairable — never sent to repair_node


def test_clm006_recovers_in_one_repair_loop(tmp_path, graph_store, vector_store) -> None:
    final_state, _ = _run(tmp_path, graph_store, vector_store, "CLM-006")
    assert final_state["retry_count"] == 1
    assert final_state["validation"]["is_valid"] is True
    assert final_state["extraction_source"] == "fewshot_repair"
    assert final_state["extracted_fields"]["member_id"] == "MEM1001"


def test_clm007_exhausts_repair_and_falls_back(tmp_path, graph_store, vector_store) -> None:
    final_state, _ = _run(tmp_path, graph_store, vector_store, "CLM-007")
    assert final_state["retry_count"] == 2
    assert final_state["fallback_used"] is True
    assert final_state["needs_human_review"] is True
    assert final_state["extraction_source"] == "heuristic_fallback"


@pytest.mark.parametrize(
    "scenario_id", ["CLM-001", "CLM-002", "CLM-003", "CLM-004", "CLM-005", "CLM-013"]
)
def test_p6_scenarios_still_pass_through_the_full_graph_with_audit(
    scenario_id, tmp_path, graph_store, vector_store
) -> None:
    expected = json.loads(open(f"tests/fixtures/expected/{scenario_id}.expected.json").read())
    final_state, _ = _run(tmp_path, graph_store, vector_store, scenario_id)

    assert final_state["decision"]["status"] == expected["decision"]["status"]
    assert final_state["decision"]["payable_amount"] == pytest.approx(
        expected["decision"]["payable_amount"]
    )
    assert final_state.get("heal_attempts", 0) == 0
    assert final_state.get("degraded", False) is False


def test_clm012_heals_exactly_once_and_improves(tmp_path, graph_store, vector_store) -> None:
    from ..conftest import FlakyOnceAdjudicatorLLM

    flaky_llm = FlakyOnceAdjudicatorLLM(FakeAdjudicatorLLM())
    final_state, _ = _run(tmp_path, graph_store, vector_store, "CLM-012", adjudicator_llm=flaky_llm)

    assert final_state["heal_attempts"] == 1
    assert final_state["decision"]["status"] == "APPROVE"
    assert final_state["decision"]["payable_amount"] == 5000
    assert "EX-7.1" not in final_state["decision"]["citations"]
    assert final_state.get("degraded", False) is False


def test_clm010_gets_a_memory_hit_after_clm001(tmp_path, graph_store, vector_store) -> None:
    """P8 'done when': CLM-010 gets a memory hit."""
    from app.memory.long_term import SqliteMemoryStore

    memory_store = SqliteMemoryStore(str(tmp_path / "memory.sqlite"))

    first_state, _ = _run(
        tmp_path, graph_store, vector_store, "CLM-001", memory_store=memory_store
    )
    assert first_state["decision"]["status"] == "APPROVE"

    facts = memory_store.query_facts("member_id", "MEM1001", fact_type="decision")
    assert len(facts) == 1  # the memory write actually happened after CLM-001's final decision

    second_state, _ = _run(
        tmp_path, graph_store, vector_store, "CLM-010", memory_store=memory_store
    )
    assert second_state["decision"]["status"] == "MANUAL_REVIEW"
    assert second_state["needs_human_review"] is True
    assert second_state["decision"]["payable_amount"] == 1200
