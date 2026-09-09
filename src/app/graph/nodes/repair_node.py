"""repair_node — adapts ClaimState <-> FieldRepairAgent. Increments retry_count."""

from typing import Any

from app.agents.field_repair_agent import FieldRepairAgent
from app.graph.state import ClaimState


def make_repair_node(agent: FieldRepairAgent) -> Any:
    def repair_node(state: ClaimState) -> dict[str, Any]:
        corrected = agent.run(
            state["ocr_result"],
            state.get("extracted_fields", {}),
            state.get("validation", {}).get("errors", []),
        )
        return {
            "extracted_fields": corrected,
            "extraction_source": "fewshot_repair",
            "retry_count": state.get("retry_count", 0) + 1,
        }

    return repair_node
