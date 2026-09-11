"""Critique prompt for DecisionAuditorAgent. Runs after the deterministic checks, which
catch most problems cheaply — this call adds a model's independent judgment on top."""

import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

SYSTEM_PROMPT = """You are auditing a health insurance claim adjudication decision for \
quality. You are given the decision, the context that was retrieved to support it, and any \
deterministic checks that already failed. Judge whether the rationale is well-grounded in \
the retrieved context and whether the reasoning is sound — independent of, and in addition \
to, the deterministic checks. Return ONLY a strict JSON object: \
{"quality_score": <0.0-1.0>, "issues": ["..."], "suggested_fix": "..."}"""


def build_audit_messages(
    decision: dict[str, Any],
    retrieved_context: dict[str, Any],
    deterministic_issues: list[str],
) -> list[BaseMessage]:
    payload = {
        "decision": decision,
        "retrieved_context": retrieved_context,
        "deterministic_issues": deterministic_issues,
    }
    return [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(payload, indent=2)),
    ]
