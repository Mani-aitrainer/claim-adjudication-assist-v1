"""adjudicate_node — adapts ClaimState <-> PolicyAdjudicatorAgent.

Widens graph_hops to graph_hops_on_heal when a critique is present (a heal loop from
audit_node), per config/agents.yaml[agents.adjudicator_agent.retrieval]. Emits
context_tokens_used{agent,bucket} from the token budget report memory/policy.py computed.
"""

from typing import Any

from app.agents.policy_adjudicator_agent import PolicyAdjudicatorAgent
from app.graph.state import ClaimState
from app.observability.metrics import context_tokens_used


def make_adjudicate_node(
    agent: PolicyAdjudicatorAgent,
    graph_hops: int = 2,
    graph_hops_on_heal: int = 3,
    vector_top_k: int = 6,
) -> Any:
    async def adjudicate_node(state: ClaimState) -> dict[str, Any]:
        critique = state.get("critique")
        hops = graph_hops_on_heal if critique else graph_hops
        result = await agent.run(
            state.get("extracted_fields", {}),
            graph_hops=hops,
            vector_top_k=vector_top_k,
            critique=critique,
            reasoning_traces=state.get("reasoning_traces", []),
            fallback_used=state.get("fallback_used", False),
        )
        for bucket, tokens in result["token_budget_report"].items():
            context_tokens_used.labels(
                agent="PolicyAdjudicatorAgent", bucket=bucket.removesuffix("_tokens")
            ).observe(tokens)

        update: dict[str, Any] = {
            "retrieved_context": result["retrieved_context"],
            "decision": result["decision"],
            "reasoning_trace": result["reasoning_trace"],
            "reasoning_traces": [result["reasoning_trace"]],
            "token_budget_report": result["token_budget_report"],
        }
        if result["decision"].get("status") == "MANUAL_REVIEW":
            update["needs_human_review"] = True
        return update

    return adjudicate_node
