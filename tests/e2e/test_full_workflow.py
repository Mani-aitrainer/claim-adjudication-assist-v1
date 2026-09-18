"""E2E: parametrises over testdata/manifest.yaml, so every scenario in the matrix is a
case here — adding a scenario means adding one YAML block, no test code changes. Runs
under a deterministic set of fake LLM/embeddings doubles (tests/conftest.py). No network,
no OpenAI spend, CI-safe.

Scoped to the claims domain, consistent with every earlier phase: the pharmacy domain pack
was explicitly deferred ("drops in later without refactoring") and was never wired into the
graph, validator, or adjudicator.
"""

import asyncio
import re
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.graph.build_graph import build_graph
from app.memory.long_term import SqliteMemoryStore
from app.ocr.fixture_provider import FixtureOCRProvider
from app.persistence.checkpointer import get_checkpointer

from ..conftest import (
    FakeAdjudicatorLLM,
    FakeAuditLLM,
    FakeCopyIntakeLLM,
    FakeEmbeddingsClient,
    FakeRepairLLM,
    FlakyOnceAdjudicatorLLM,
)

MANIFEST_PATH = Path("testdata/manifest.yaml")
NODE_NAMES = {"intake", "validate", "repair", "fallback", "adjudicate", "audit"}


def _load_claim_scenarios() -> list[dict[str, Any]]:
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)
    return list(manifest["claims"])


CLAIM_SCENARIOS = _load_claim_scenarios()


async def _run_scenario_async(
    scenario_id: str, graph_store, vector_store, settings, memory_store=None, adjudicator_llm=None
) -> tuple[dict[str, Any], list[str]]:
    async with get_checkpointer(settings) as checkpointer:
        graph = build_graph(
            checkpointer,
            FixtureOCRProvider(settings.fixture_dir),
            graph_store,
            vector_store,
            intake_llm=FakeCopyIntakeLLM(),
            repair_llm=FakeRepairLLM(),
            adjudicator_llm=adjudicator_llm or FakeAdjudicatorLLM(),
            auditor_llm=FakeAuditLLM(),
            embeddings_client=FakeEmbeddingsClient(),
            memory_store=memory_store,
        )
        run_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": run_id}}
        initial_state = {
            "run_id": run_id,
            "source_uri": f"tests/fixtures/claims/{scenario_id}.pdf",
            "domain": "claims",
        }

        node_path: list[str] = []
        async for event in graph.astream_events(initial_state, config=config, version="v2"):
            if event["event"] == "on_chain_start" and event.get("name") in NODE_NAMES:
                node_path.append(event["name"])

        checkpoint_tuple = await checkpointer.aget_tuple(config)
        final_state = (
            dict(checkpoint_tuple.checkpoint["channel_values"]) if checkpoint_tuple else {}
        )
        return final_state, node_path


def _run_scenario(scenario_id: str, graph_store, vector_store, settings, **kwargs):
    return asyncio.run(
        _run_scenario_async(scenario_id, graph_store, vector_store, settings, **kwargs)
    )


def _cited_clause_ids(retrieved_context: dict[str, Any]) -> set[str]:
    clause_ids = set()
    suffix_re = re.compile(r"\[clause: (\S+)\]")
    for triple in retrieved_context.get("graph_triples", []):
        if match := suffix_re.search(triple):
            clause_ids.add(match.group(1))
    for chunk in retrieved_context.get("vector_chunks", []):
        if chunk.get("clause_id"):
            clause_ids.add(chunk["clause_id"])
    return clause_ids


@pytest.mark.parametrize(
    "scenario", CLAIM_SCENARIOS, ids=lambda s: s["id"]
)
def test_scenario(scenario, temp_sqlite_settings, graph_store, vector_store, tmp_path) -> None:
    scenario_id = scenario["id"]
    expected = scenario["expected"]

    # CLM-012 and CLM-010 need setup a generic single-scenario run can't provide on its
    # own: CLM-012's heal loop needs a first attempt that cites something ungrounded, and
    # CLM-010's duplicate detection needs a prior decision already in memory. The literal
    # "run CLM-001 then CLM-010" cross-scenario sequencing is covered separately by
    # test_build_graph.py::test_clm010_gets_a_memory_hit_after_clm001 (suite assertion #12).
    adjudicator_llm = None
    memory_store = None
    if scenario_id == "CLM-012":
        adjudicator_llm = FlakyOnceAdjudicatorLLM(FakeAdjudicatorLLM())
    if scenario_id == "CLM-010":
        memory_store = SqliteMemoryStore(str(tmp_path / "memory.sqlite"))
        memory_store.write_fact(
            scope_key="member_id",
            scope_value="MEM1001",
            fact_type="decision",
            fact_json={
                "service_start_date": "2024-03-05",
                "service_end_date": "2024-03-05",
                "claimed_amount": 1200.0,
                "decision_status": "APPROVE",
                "payable_amount": 1200.0,
            },
            source_run_id="prior-run",
            ttl_days=90,
        )

    final_state, node_path = _run_scenario(
        scenario_id,
        graph_store,
        vector_store,
        temp_sqlite_settings,
        memory_store=memory_store,
        adjudicator_llm=adjudicator_llm,
    )

    # 1. the graph completes and returns a terminal state
    assert final_state, f"{scenario_id}: graph produced no final state"

    # 2. the node visit order matches the expected path for that scenario
    assert node_path == expected["node_path"], scenario_id

    # 3. retry_count, heal_attempts, fallback_used and extraction_source match expectations
    assert final_state.get("retry_count", 0) == expected["retry_count"], scenario_id
    assert final_state.get("heal_attempts", 0) == expected["heal_attempts"], scenario_id
    assert final_state.get("fallback_used", False) == expected["fallback_used"], scenario_id
    assert final_state.get("extraction_source") == expected["extraction_source"], scenario_id

    decision = final_state.get("decision", {})
    expected_decision = expected["decision"]

    # 4. decision.status matches, payable_amount matches to the rupee
    assert decision.get("status") == expected_decision["status"], scenario_id
    if expected_decision["payable_amount"] is not None:
        assert decision.get("payable_amount") == pytest.approx(
            expected_decision["payable_amount"], abs=0.5
        ), scenario_id

    # 5. payable_amount == sum(per_line.payable) and <= claimed_amount
    per_line = decision.get("per_line") or []
    if per_line:
        line_sum = sum(line["payable"] for line in per_line)
        assert decision["payable_amount"] == pytest.approx(line_sum, abs=0.01), scenario_id
        claimed_sum = sum(line["claimed"] for line in per_line)
        assert decision["payable_amount"] <= claimed_sum + 0.01, scenario_id

    # 6. every id in citations[] resolves inside retrieved_context, and the expected
    #    clause ids are present
    retrieved_context = final_state.get("retrieved_context", {})
    available = _cited_clause_ids(retrieved_context)
    for clause_id in decision.get("citations", []) or []:
        assert clause_id in available, f"{scenario_id}: cited '{clause_id}' not in context"
    assert set(expected_decision["citations"]) <= set(decision.get("citations", [])), scenario_id

    # 7. metrics has one entry per executed agent, each with non-zero latency and a
    #    computed cost_usd
    metrics = final_state.get("metrics", [])
    executed_agents = {"intake": "ClaimIntakeAgent", "validate": "ClaimValidatorAgent",
                        "repair": "FieldRepairAgent", "fallback": "HeuristicFallbackAgent",
                        "adjudicate": "PolicyAdjudicatorAgent", "audit": "DecisionAuditorAgent"}
    metric_agents = [m["agent"] for m in metrics]
    for node in node_path:
        assert executed_agents[node] in metric_agents, scenario_id
    for metric in metrics:
        assert metric["latency_ms"] > 0, scenario_id
        assert metric["cost_usd"] >= 0, scenario_id  # computed — 0.0 with our fake LLMs
