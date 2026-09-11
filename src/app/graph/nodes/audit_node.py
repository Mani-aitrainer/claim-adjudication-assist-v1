"""audit_node — adapts ClaimState <-> DecisionAuditorAgent.

Always explicitly sets `critique` (None when passing or exhausted, a string when looping)
so a stale critique from an earlier heal attempt can never linger and mis-route a later,
passing audit. Writes a long-term memory fact after a final, non-degraded pass — write
policy is on_final_decision_only, per config/tradeoff.yaml.
"""

from typing import Any

from app.agents.decision_auditor_agent import DecisionAuditorAgent
from app.core.agent_config import get_agent_config
from app.graph.state import ClaimState
from app.memory.long_term import LongTermMemoryStore
from app.observability.metrics import healing_loops_total
from app.observability.metrics import quality_score as quality_score_metric


def make_audit_node(
    agent: DecisionAuditorAgent, memory_store: LongTermMemoryStore | None = None
) -> Any:
    def audit_node(state: ClaimState) -> dict[str, Any]:
        result = agent.run(state.get("decision", {}), state.get("retrieved_context", {}))
        heal_attempts = state.get("heal_attempts", 0)
        domain = state.get("domain", "claims")
        quality_score_metric.labels(domain=domain).observe(result["quality_score"])

        if result["passed"]:
            healing_loops_total.labels(
                outcome="healed" if heal_attempts > 0 else "not_needed"
            ).inc()
            _write_memory_fact(memory_store, state)
            return {"quality_score": result["quality_score"], "critique": None}

        model_extra = get_agent_config("auditor_agent").model_extra or {}
        max_heal_attempts = model_extra.get("healing", {}).get("max_heal_attempts", 2)

        if heal_attempts < max_heal_attempts:
            critique = result["suggested_fix"] or "; ".join(result["issues"])
            return {
                "quality_score": result["quality_score"],
                "critique": critique,
                "heal_attempts": heal_attempts + 1,
            }

        healing_loops_total.labels(outcome="exhausted").inc()
        return {
            "quality_score": result["quality_score"],
            "critique": None,
            "degraded": True,
            "needs_human_review": True,
        }

    return audit_node


def _write_memory_fact(memory_store: LongTermMemoryStore | None, state: ClaimState) -> None:
    if memory_store is None:
        return
    extracted_fields = state.get("extracted_fields", {})
    member_id = extracted_fields.get("member_id")
    if not member_id:
        return

    decision = state.get("decision", {})
    fact = {
        "service_start_date": extracted_fields.get("service_start_date"),
        "service_end_date": extracted_fields.get("service_end_date"),
        "claimed_amount": extracted_fields.get("claimed_amount"),
        "procedure_codes": extracted_fields.get("procedure_codes"),
        "decision_status": decision.get("status"),
        "payable_amount": decision.get("payable_amount"),
    }
    memory_store.write_fact(
        scope_key="member_id",
        scope_value=member_id,
        fact_type="decision",
        fact_json=fact,
        source_run_id=state.get("run_id", ""),
        ttl_days=90,
    )
