"""DecisionAuditorAgent — self-healing. Deterministic checks first (cheap, catch most
problems), then one LLM critique call. If a deterministic check already failed, the score
is capped at 0.5 before the LLM runs.
"""

import json
import re
from typing import Any

from app.agents.base import BaseAgent
from app.agents.prompts.audit_critique import build_audit_messages
from app.core.agent_config import get_agent_config
from app.core.llm_factory import get_llm

_ALLOWED_STATUSES = {"APPROVE", "PARTIAL", "DENY", "MANUAL_REVIEW"}
_CLAUSE_SUFFIX = re.compile(r"\[clause: (\S+)\]")
_AMOUNT_TOLERANCE = 0.01


def _cited_clause_ids(retrieved_context: dict[str, Any]) -> set[str]:
    clause_ids = set()
    for triple in retrieved_context.get("graph_triples", []):
        if match := _CLAUSE_SUFFIX.search(triple):
            clause_ids.add(match.group(1))
    for chunk in retrieved_context.get("vector_chunks", []):
        if chunk.get("clause_id"):
            clause_ids.add(chunk["clause_id"])
    return clause_ids


def _has_exclusion_or_waiting_citation(
    citations: list[str], retrieved_context: dict[str, Any]
) -> bool:
    triples = retrieved_context.get("graph_triples", [])
    return any(
        (" —excludes→ " in triple or " —requires_waiting→ " in triple)
        and any(citation in triple for citation in citations)
        for triple in triples
    )


def run_deterministic_checks(
    decision: dict[str, Any], retrieved_context: dict[str, Any]
) -> list[str]:
    issues: list[str] = []

    # MANUAL_REVIEW legitimately has no computed decision (e.g. a fallback-recovered claim
    # too unreliable to adjudicate) — the null-field check only applies when a decision was
    # actually supposed to be computed.
    if decision.get("status") != "MANUAL_REVIEW":
        for field in ("status", "payable_amount", "currency", "citations"):
            if decision.get(field) is None:
                issues.append(f"required field '{field}' is null")

    if decision.get("status") not in _ALLOWED_STATUSES:
        issues.append(f"status '{decision.get('status')}' is not in the allowed enum")

    available_clause_ids = _cited_clause_ids(retrieved_context)
    for clause_id in decision.get("citations") or []:
        if clause_id not in available_clause_ids:
            issues.append(f"citation '{clause_id}' does not appear in retrieved_context")

    per_line = decision.get("per_line") or []
    payable_amount = decision.get("payable_amount")
    if payable_amount is not None and per_line:
        line_sum = sum(line["payable"] for line in per_line)
        if abs(line_sum - payable_amount) > _AMOUNT_TOLERANCE:
            issues.append("payable_amount does not equal the sum of per_line.payable")
        claimed_sum = sum(line["claimed"] for line in per_line)
        if payable_amount > claimed_sum + _AMOUNT_TOLERANCE:
            issues.append("payable_amount exceeds the claimed amount")

    if decision.get("status") == "DENY":
        citations = decision.get("citations") or []
        # a DENY with no citations at all is a structural-ineligibility denial (e.g. the
        # service date falls outside the policy validity period) — there is no specific
        # benefit clause to cite for that. Only flag citations that exist but don't ground
        # the denial in an exclusion or waiting period.
        if citations and not _has_exclusion_or_waiting_citation(citations, retrieved_context):
            issues.append("DENY status is not backed by an exclusion or waiting-period citation")

    return issues


class DecisionAuditorAgent(BaseAgent):
    name = "DecisionAuditorAgent"

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm

    def run(self, decision: dict[str, Any], retrieved_context: dict[str, Any]) -> dict[str, Any]:
        deterministic_issues = run_deterministic_checks(decision, retrieved_context)

        llm = self._llm if self._llm is not None else get_llm("auditor_agent")
        messages = build_audit_messages(decision, retrieved_context, deterministic_issues)
        response = llm.invoke(messages)
        critique_result = json.loads(str(response.content))

        quality_score = float(critique_result["quality_score"])
        if deterministic_issues:
            quality_score = min(quality_score, 0.5)

        model_extra = get_agent_config("auditor_agent").model_extra or {}
        threshold = model_extra.get("healing", {}).get("quality_threshold", 0.75)
        all_issues = deterministic_issues + list(critique_result.get("issues", []))

        return {
            "quality_score": quality_score,
            "passed": quality_score >= threshold,
            "issues": all_issues,
            "suggested_fix": critique_result.get("suggested_fix", ""),
        }
