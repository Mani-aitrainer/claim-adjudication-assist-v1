"""P6 'done when': CLM-001 through CLM-005 and CLM-013 produce their expected decisions."""

import asyncio
import json

import pytest

from app.agents.policy_adjudicator_agent import PolicyAdjudicatorAgent

from ..conftest import FakeAdjudicatorLLM, FakeEmbeddingsClient

EXPECTED_DIR = "tests/fixtures/expected"


def _adjudicate(graph_store, vector_store, ground_truth: dict) -> dict:
    agent = PolicyAdjudicatorAgent(
        graph_store,
        vector_store,
        llm=FakeAdjudicatorLLM(),
        embeddings_client=FakeEmbeddingsClient(),
    )
    return asyncio.run(agent.run(ground_truth))


@pytest.mark.parametrize(
    "scenario_id",
    ["CLM-001", "CLM-002", "CLM-003", "CLM-004", "CLM-005", "CLM-013"],
)
def test_scenario_produces_expected_decision(scenario_id, graph_store, vector_store) -> None:
    expected = json.loads(open(f"{EXPECTED_DIR}/{scenario_id}.expected.json").read())
    ground_truth = expected["ground_truth"]

    result = _adjudicate(graph_store, vector_store, ground_truth)
    decision = result["decision"]
    expected_decision = expected["decision"]

    assert decision["status"] == expected_decision["status"], scenario_id
    expected_payable = pytest.approx(expected_decision["payable_amount"])
    assert decision["payable_amount"] == expected_payable, scenario_id
    assert set(expected_decision["citations"]) <= set(decision["citations"]), scenario_id
