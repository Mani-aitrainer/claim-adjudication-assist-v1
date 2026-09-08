"""intake_node — adapts ClaimState <-> ClaimIntakeAgent.

The OCRProvider is injected once when the node is built (see build_graph.py); the node
function itself never constructs one.
"""

from typing import Any

from app.agents.claim_intake_agent import ClaimIntakeAgent
from app.core.exceptions import OCRServiceError
from app.graph.state import ClaimState


def make_intake_node(agent: ClaimIntakeAgent) -> Any:
    def intake_node(state: ClaimState) -> dict[str, Any]:
        try:
            result = agent.run(state["source_uri"])
            return dict(result)
        except OCRServiceError as exc:
            return {
                "errors": [{"stage": "intake", "message": str(exc)}],
                "extraction_source": "ocr_failed",
            }

    return intake_node
