"""fallback_node — adapts ClaimState <-> HeuristicFallbackAgent."""

from typing import Any

from app.agents.heuristic_fallback_agent import HeuristicFallbackAgent
from app.graph.state import ClaimState


def make_fallback_node(agent: HeuristicFallbackAgent) -> Any:
    def fallback_node(state: ClaimState) -> dict[str, Any]:
        result = agent.run(state.get("ocr_result"), state.get("extracted_fields", {}))
        fields = {
            k: v
            for k, v in result.items()
            if k not in ("fallback_used", "needs_human_review", "confidence", "extraction_source")
        }
        return {
            "extracted_fields": fields,
            "fallback_used": result["fallback_used"],
            "needs_human_review": result["needs_human_review"],
            "confidence": result["confidence"],
            "extraction_source": result["extraction_source"],
        }

    return fallback_node
