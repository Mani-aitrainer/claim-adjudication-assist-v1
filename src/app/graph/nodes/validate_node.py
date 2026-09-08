"""validate_node — adapts ClaimState <-> ClaimValidatorAgent. Deterministic, no LLM.

Emits validation_failures_total{rule} and, when this validation follows a repair attempt,
repair_attempts_total{outcome}.
"""

from typing import Any

from app.agents.claim_validator_agent import ClaimValidatorAgent
from app.graph.state import ClaimState
from app.observability.metrics import repair_attempts_total, validation_failures_total


def make_validate_node(agent: ClaimValidatorAgent) -> Any:
    def validate_node(state: ClaimState) -> dict[str, Any]:
        result = agent.run(state.get("extracted_fields", {}))

        for error in result.get("errors", []):
            validation_failures_total.labels(rule=error["code"]).inc()

        if state.get("extraction_source") == "fewshot_repair":
            outcome = "success" if result["is_valid"] else "failure"
            repair_attempts_total.labels(outcome=outcome).inc()

        return {"validation": dict(result)}

    return validate_node
