"""ClaimState — the shared state every node in the LangGraph StateGraph reads from and
writes to. Append-only lists use the operator.add reducer so looping nodes never clobber
each other; everything else is last-write-wins.
"""

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class ValidationIssue(TypedDict):
    field: str
    code: str
    message: str
    severity: Literal["error", "warning"]


class AgentMetric(TypedDict):
    agent: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float
    model: str
    cache_hit: bool


class ClaimState(TypedDict, total=False):
    # identity
    run_id: str
    document_id: str
    source_uri: str
    domain: str  # "claims" | "pharmacy"

    # ClaimIntakeAgent
    ocr_result: dict
    extracted_fields: dict
    extraction_source: str  # intake_llm | fewshot_repair | heuristic_fallback

    # ClaimValidatorAgent / FieldRepairAgent / HeuristicFallbackAgent
    validation: dict
    retry_count: int
    fallback_used: bool
    needs_human_review: bool
    confidence: str  # high | medium | low

    # PolicyAdjudicatorAgent
    retrieved_context: dict
    reasoning_trace: str
    decision: dict

    # DecisionAuditorAgent
    heal_attempts: int
    quality_score: float
    critique: str | None
    degraded: bool

    # context / history / memory tradeoff
    messages: Annotated[list[AnyMessage], add_messages]
    history_summary: str
    long_term_facts: list[dict]
    reasoning_traces: Annotated[list[str], operator.add]  # one per adjudicate attempt, this run
    token_budget_report: dict

    # cross-cutting
    metrics: Annotated[list[AgentMetric], operator.add]
    errors: Annotated[list[dict], operator.add]
