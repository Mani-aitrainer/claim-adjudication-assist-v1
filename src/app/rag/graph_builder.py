"""Policy chunk -> entities/edges -> networkx. One LLM pass per policy-wording chunk,
against domains/claims/graph_schema.yaml. Not one of the six roster agents — it's an
ingestion-pipeline step — but it still goes through get_llm(...) via the "graph_extraction"
config/agents.yaml entry, so its model choice and cost are tracked the same way.
"""

import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.core.llm_factory import get_llm

SYSTEM_PROMPT_TEMPLATE = """You extract a health insurance policy knowledge graph from one \
clause of policy wording. Use only these node types: {node_types}. Use only these edge \
types: {edge_types}. Every edge must carry the clause_id this clause is about — read it \
from the "[Clause XX-N.N]" marker at the start of the text.

Two kinds of numeric detail:

1. A benefit's OWN sub-limit (e.g. "sub-limit of INR X per visit", "annual sub-limit of \
INR X"): add a SubLimit node (id = "<clause_id>-limit") linked FROM the clause node via \
has_sublimit, with the number(s) in "properties".

2. A policy-WIDE condition that modifies payment regardless of which benefit applies (a \
co-payment by age, or a reimbursement percentage for out-of-network care): add a SubLimit \
node (id = "<clause_id>-limit") linked FROM a constant node named "POLICY" (type Policy) \
via applies_to, with the percentage and any threshold (e.g. "min_age") in "properties".

If the clause states a waiting period in months, add a WaitingPeriod node \
(id = "<clause_id>-wait") linked FROM the clause node via requires_waiting, with \
{{"months": N}} in properties.

Return ONLY a strict JSON list of edges, each \
{{"src", "src_type", "relation", "dst", "dst_type", "clause_id", "properties"}}. Return an \
empty list if the clause has no extractable numeric detail."""


def build_extraction_messages(chunk_text: str, schema: dict[str, Any]) -> list[BaseMessage]:
    system = SYSTEM_PROMPT_TEMPLATE.format(
        node_types=", ".join(schema["node_types"]),
        edge_types=", ".join(schema["edge_types"]),
    )
    return [SystemMessage(content=system), HumanMessage(content=chunk_text)]


def extract_edges_from_chunk(
    chunk_text: str, schema: dict[str, Any], llm: Any = None
) -> list[dict[str, Any]]:
    resolved_llm = llm if llm is not None else get_llm("graph_extraction")
    messages = build_extraction_messages(chunk_text, schema)
    response = resolved_llm.invoke(messages)
    return list(json.loads(str(response.content)))


def build_edges_from_chunks(
    chunks: list[dict[str, Any]], schema: dict[str, Any], llm: Any = None
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for chunk in chunks:
        edges.extend(extract_edges_from_chunk(chunk["content"], schema, llm))
    return edges


def build_edges_from_annexure_table(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """The procedure code annexure is a genuine table with an explicit clause column — no
    LLM needed to interpret unambiguous tabular data. Its "Benefit Category" column marks
    excluded categories with "(Excluded)", which is enough to pick the right edge type
    without needing to read the clause's own prose."""
    edges: list[dict[str, Any]] = []
    for row in rows:
        code, clause_id = row.get("Code"), row.get("Clause")
        category = row.get("Benefit Category", "")
        if not code or not clause_id:
            continue
        is_excluded = "excluded" in category.lower()
        edges.append(
            {
                "src": code,
                "src_type": "ProcedureCode",
                "relation": "excludes" if is_excluded else "maps_to",
                "dst": clause_id,
                "dst_type": "Exclusion" if is_excluded else "Benefit",
                "clause_id": clause_id,
                "properties": {"benefit_category": category},
            }
        )
    return edges
