"""Conditional edge functions.

`retry_count` in state (not the LangGraph recursion limit) is what stops the repair loop —
see FieldRepairAgent's docstring and DEVELOPMENT_PLAN.md's guardrail note.
"""

from app.core.agent_config import get_agent_config
from app.graph.state import ClaimState
from app.validation.rules import is_repairable


def route_after_intake(state: ClaimState) -> str:
    if state.get("errors"):
        return "fallback"
    return "validate"


def route_after_validate(state: ClaimState) -> str:
    validation = state.get("validation", {})
    if validation.get("is_valid"):
        return "done"

    errors = validation.get("errors", [])
    if not is_repairable(errors):
        return "done"  # unrepairable (e.g. POLICY_WINDOW) -> straight through for a proper denial

    model_extra = get_agent_config("repair_agent").model_extra or {}
    max_attempts = model_extra.get("retry", {}).get("max_attempts", 2)
    if state.get("retry_count", 0) < max_attempts:
        return "repair"
    return "fallback"


def route_after_audit(state: ClaimState) -> str:
    """audit_node always clears `critique` to None except when it wants another heal
    loop — see its docstring — so this check alone is enough to route correctly."""
    if state.get("critique"):
        return "heal"
    return "done"
