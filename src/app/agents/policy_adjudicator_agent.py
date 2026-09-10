"""PolicyAdjudicatorAgent — chain-of-thought + GraphRAG. Retrieves graph triples and
vector chunks concurrently, then reasons over them to produce a decision.

Retrieval seeds: procedure_codes[] + diagnosis_codes[] + the constant "POLICY" node, which
policy-wide conditions (co-pay, out-of-network reduction) attach to — see graph_builder.py.

Also queries long-term memory (scoped by member_id) so the model can flag likely duplicate
submissions — see memory/policy.py and DecisionAuditorAgent's write-back after a final,
non-degraded decision.
"""

import json
from typing import Any

from app.agents.base import BaseAgent
from app.agents.prompts.adjudication_cot import build_adjudication_messages
from app.core.llm_factory import get_llm
from app.memory.long_term import LongTermMemoryStore
from app.memory.policy import assemble_prompt_payload, load_tradeoff_config
from app.rag.graph_store import PolicyGraphStore
from app.rag.hybrid_retriever import retrieve
from app.rag.vector_store import VectorStore
from app.validation.rules import get_policy_period


def _build_query_text(extracted_fields: dict[str, Any]) -> str:
    descriptions = [item.get("description", "") for item in extracted_fields.get("line_items", [])]
    return ", ".join(descriptions) or "claim"


class PolicyAdjudicatorAgent(BaseAgent):
    name = "PolicyAdjudicatorAgent"

    def __init__(
        self,
        graph_store: PolicyGraphStore,
        vector_store: VectorStore,
        domain: str = "claims",
        llm: Any = None,
        embeddings_client: Any = None,
        memory_store: LongTermMemoryStore | None = None,
        tradeoff_config: dict[str, Any] | None = None,
    ) -> None:
        self._graph_store = graph_store
        self._vector_store = vector_store
        self._domain = domain
        self._llm = llm
        self._embeddings_client = embeddings_client
        self._memory_store = memory_store
        self._tradeoff_config = tradeoff_config or load_tradeoff_config()

    async def run(
        self,
        extracted_fields: dict[str, Any],
        graph_hops: int = 2,
        vector_top_k: int = 6,
        critique: str | None = None,
        reasoning_traces: list[str] | None = None,
        fallback_used: bool = False,
    ) -> dict[str, Any]:
        if fallback_used:
            # a heuristic-fallback-recovered claim is too unreliable to adjudicate
            # normally — flag it for a human rather than computing a number from
            # regex-guessed fields.
            return {
                "retrieved_context": {},
                "decision": {
                    "status": "MANUAL_REVIEW",
                    "payable_amount": None,
                    "currency": extracted_fields.get("currency"),
                    "per_line": [],
                    "rationale": "Fields were recovered via heuristic fallback, not "
                    "reliably extracted — routed for manual review instead of an "
                    "automated decision.",
                    "citations": [],
                },
                "reasoning_trace": "",
                "token_budget_report": {
                    "context_tokens": 0,
                    "history_tokens": 0,
                    "memory_tokens": 0,
                },
            }

        seed_codes = [
            *extracted_fields.get("procedure_codes", []),
            *extracted_fields.get("diagnosis_codes", []),
            "POLICY",
        ]
        retrieved_context = await retrieve(
            seed_codes=seed_codes,
            query_text=_build_query_text(extracted_fields),
            graph_store=self._graph_store,
            vector_store=self._vector_store,
            domain=self._domain,
            graph_hops=graph_hops,
            vector_top_k=vector_top_k,
            embeddings_client=self._embeddings_client,
        )

        memory_facts: list[dict[str, Any]] = []
        member_id = extracted_fields.get("member_id")
        if self._memory_store is not None and member_id:
            memory_facts = self._memory_store.query_facts(
                "member_id",
                member_id,
                fact_type="decision",
                top_k=self._tradeoff_config["memory"]["top_k"],
            )

        prompt_payload = assemble_prompt_payload(
            retrieved_context, reasoning_traces or [], memory_facts, self._tradeoff_config
        )

        policy_period = get_policy_period(extracted_fields.get("policy_no", ""))
        messages = build_adjudication_messages(
            extracted_fields, prompt_payload, policy_period, critique
        )
        llm = self._llm if self._llm is not None else get_llm("adjudicator_agent")
        response = llm.invoke(messages)
        result = json.loads(str(response.content))

        return {
            "retrieved_context": retrieved_context,
            "decision": result["decision"],
            "reasoning_trace": result.get("reasoning_trace", ""),
            "token_budget_report": prompt_payload["token_budget_report"],
        }
