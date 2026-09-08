"""StateGraph wiring.

    START -> intake -> [validate | fallback]        (route_after_intake)
             validate -> [repair | fallback | done]  (route_after_validate)
             repair -> validate
             fallback -> adjudicate
             done -> adjudicate
             adjudicate -> audit
             audit -> [heal (-> adjudicate) | done (-> END)]  (route_after_audit)
"""

import time
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.claim_intake_agent import ClaimIntakeAgent
from app.agents.claim_validator_agent import ClaimValidatorAgent
from app.agents.decision_auditor_agent import DecisionAuditorAgent
from app.agents.field_repair_agent import FieldRepairAgent
from app.agents.heuristic_fallback_agent import HeuristicFallbackAgent
from app.agents.policy_adjudicator_agent import PolicyAdjudicatorAgent
from app.cache.base import CacheProvider
from app.core.agent_config import get_agent_config
from app.graph.nodes.adjudicate_node import make_adjudicate_node
from app.graph.nodes.audit_node import make_audit_node
from app.graph.nodes.fallback_node import make_fallback_node
from app.graph.nodes.intake_node import make_intake_node
from app.graph.nodes.metrics_wrapper import with_state_metrics
from app.graph.nodes.repair_node import make_repair_node
from app.graph.nodes.validate_node import make_validate_node
from app.graph.routers import route_after_audit, route_after_intake, route_after_validate
from app.graph.state import ClaimState
from app.memory.long_term import LongTermMemoryStore
from app.observability.metrics import graph_run_duration_seconds, graph_runs_total
from app.ocr.base import OCRProvider
from app.rag.graph_store import PolicyGraphStore
from app.rag.vector_store import VectorStore


def build_graph(
    checkpointer: Any,
    ocr_provider: OCRProvider,
    graph_store: PolicyGraphStore,
    vector_store: VectorStore,
    domain: str = "claims",
    intake_llm: Any = None,
    repair_llm: Any = None,
    adjudicator_llm: Any = None,
    auditor_llm: Any = None,
    embeddings_client: Any = None,
    memory_store: LongTermMemoryStore | None = None,
    cache: CacheProvider | None = None,
) -> Any:
    """*_llm / embeddings_client override the real OpenAI clients — used by tests."""
    graph = StateGraph(ClaimState)
    graph.add_node(
        "intake",
        with_state_metrics("ClaimIntakeAgent", get_agent_config("intake_agent").model)(
            make_intake_node(ClaimIntakeAgent(ocr_provider, llm=intake_llm, cache=cache))
        ),
    )
    graph.add_node(
        "validate",
        with_state_metrics("ClaimValidatorAgent")(make_validate_node(ClaimValidatorAgent())),
    )
    graph.add_node(
        "repair",
        with_state_metrics("FieldRepairAgent", get_agent_config("repair_agent").model)(
            make_repair_node(FieldRepairAgent(llm=repair_llm))
        ),
    )
    graph.add_node(
        "fallback",
        with_state_metrics("HeuristicFallbackAgent")(
            make_fallback_node(HeuristicFallbackAgent())
        ),
    )
    graph.add_node(
        "adjudicate",
        with_state_metrics("PolicyAdjudicatorAgent", get_agent_config("adjudicator_agent").model)(
            make_adjudicate_node(
                PolicyAdjudicatorAgent(
                    graph_store,
                    vector_store,
                    domain=domain,
                    llm=adjudicator_llm,
                    embeddings_client=embeddings_client,
                    memory_store=memory_store,
                )
            )
        ),
    )
    graph.add_node(
        "audit",
        with_state_metrics("DecisionAuditorAgent", get_agent_config("auditor_agent").model)(
            make_audit_node(DecisionAuditorAgent(llm=auditor_llm), memory_store=memory_store)
        ),
    )

    graph.add_edge(START, "intake")
    graph.add_conditional_edges(
        "intake", route_after_intake, {"validate": "validate", "fallback": "fallback"}
    )
    graph.add_conditional_edges(
        "validate",
        route_after_validate,
        {"repair": "repair", "fallback": "fallback", "done": "adjudicate"},
    )
    graph.add_edge("repair", "validate")
    graph.add_edge("fallback", "adjudicate")
    graph.add_edge("adjudicate", "audit")
    graph.add_conditional_edges(
        "audit", route_after_audit, {"heal": "adjudicate", "done": END}
    )

    return graph.compile(checkpointer=checkpointer)


async def run_graph(
    graph: Any, initial_state: dict[str, Any] | None, config: dict[str, Any]
) -> Any:
    """Thin wrapper the API (P10) and any direct caller uses to invoke a compiled graph —
    records graph_runs_total{outcome} and graph_run_duration_seconds{domain} in one place.
    initial_state=None resumes an existing thread_id from its last checkpoint."""
    domain = (initial_state or {}).get("domain", "claims")
    start = time.perf_counter()
    try:
        final_state = await graph.ainvoke(initial_state, config=config)
    except Exception:
        graph_runs_total.labels(outcome="error").inc()
        raise
    finally:
        graph_run_duration_seconds.labels(domain=domain).observe(time.perf_counter() - start)

    if final_state.get("degraded"):
        outcome = "degraded"
    else:
        outcome = str(final_state.get("decision", {}).get("status", "unknown")).lower()
    graph_runs_total.labels(outcome=outcome).inc()
    return final_state
