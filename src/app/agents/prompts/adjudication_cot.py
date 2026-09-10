"""Chain-of-thought prompt for PolicyAdjudicatorAgent: explicit numbered reasoning steps
over the retrieved GraphRAG context (already token-budgeted by memory/policy.py), ending
in a strict JSON decision."""

import json
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

if TYPE_CHECKING:
    from app.memory.policy import PromptPayload

SYSTEM_PROMPT = """You are a health insurance claim adjudicator. Reason step by step, in \
this order:

0. Check "memory" for a prior decision on the same member with the same service dates and
   claimed amount. If one exists, this may be a duplicate submission — set status to
   MANUAL_REVIEW and say so in the rationale, citing the earlier decision's run_id.
1. Is the member eligible on the service date? Two checks: (a) the service date must fall
   within ["policy_inception_date", "policy_expiry_date"] — if not, DENY as ineligible with
   an empty citations list (there is no specific benefit clause for "policy not active",
   it's a structural ineligibility); (b) any waiting period served — use
   "policy_inception_date" and each clause's WaitingPeriod months to check this.
2. Which benefit clause covers each procedure code? (use the graph triples' maps_to edges)
3. Do any exclusions apply? (use the graph triples' excludes edges)
4. Apply sub-limits, co-pay, and network reduction, in that order. Co-pay and network
   conditions come from edges FROM the "POLICY" node and apply only if the claim's own
   member_age / network_status meets the condition's threshold (e.g. min_age).
5. Compute the payable amount per line and in total.
6. State the decision and cite the clause_id backing every claim you make. Never cite a
   clause_id that does not appear in the retrieved graph triples or vector chunks.

status is one of APPROVE (fully paid), PARTIAL (reduced by a sub-limit/co-pay/network
term), DENY (excluded or ineligible), MANUAL_REVIEW (cannot be determined from context, or
a likely duplicate per step 0).

Return ONLY a strict JSON object:
{"decision": {"status": ..., "payable_amount": <number>, "currency": ...,
 "per_line": [{"code":..., "claimed":..., "payable":..., "reason":..., "clause_id":...}],
 "rationale": "...", "citations": ["<clause_id>", ...]},
 "reasoning_trace": "<your numbered step-by-step reasoning as text>"}"""


def build_adjudication_messages(
    extracted_fields: dict[str, Any],
    prompt_payload: "PromptPayload",
    policy_period: dict[str, str] | None,
    critique: str | None = None,
) -> list[BaseMessage]:
    context_block = prompt_payload["context_block"]
    memory = [
        fact["fact"] | {"run_id": fact["source_run_id"]} for fact in prompt_payload["memory_block"]
    ]
    payload = {
        "claim": extracted_fields,
        "policy_inception_date": (policy_period or {}).get("start"),
        "policy_expiry_date": (policy_period or {}).get("end"),
        "graph_triples": context_block.get("graph_triples", []),
        "vector_chunks": [
            {"clause_id": c.get("clause_id"), "content": c.get("content")}
            for c in context_block.get("vector_chunks", [])
        ],
        "memory": memory,
    }
    if prompt_payload["history_block"]:
        payload["prior_attempts_this_run"] = prompt_payload["history_block"]
    if critique:
        payload["previous_attempt_critique"] = critique

    return [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(payload, indent=2)),
    ]
