"""Context vs history vs memory: one function every LLM agent calls to build its prompt
inputs, with visible, config-driven budgets — see config/tradeoff.yaml and
DEVELOPMENT_PLAN.md's "Context Versus History Versus Memory" chapter.

Each bucket enforces its own token/item budget independently. Context gets the largest
budget of the three (max_context_tokens=4000 vs history's 1500, memory capped by top_k) —
that ordering is what "evidence for the current step is sacrificed last" means in practice.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, TypedDict

import tiktoken
import yaml

from app.memory.history import build_history_block

TRADEOFF_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "tradeoff.yaml"

_ENCODING = tiktoken.get_encoding("cl100k_base")


class PromptPayload(TypedDict):
    context_block: dict[str, Any]
    history_block: str
    memory_block: list[dict[str, Any]]
    token_budget_report: dict[str, int]


@lru_cache(maxsize=1)
def load_tradeoff_config() -> dict[str, Any]:
    with TRADEOFF_CONFIG_PATH.open("r", encoding="utf-8") as f:
        return dict(yaml.safe_load(f))


def count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def _tokens_of(obj: Any) -> int:
    return count_tokens(json.dumps(obj))


def build_context_block(
    retrieved_context: dict[str, Any],
    graph_share: float,
    min_vector_chunks: int,
    max_context_tokens: int,
) -> dict[str, Any]:
    graph_budget = int(max_context_tokens * graph_share)
    vector_budget = max_context_tokens - graph_budget

    kept_graph: list[str] = []
    used = 0
    for triple in retrieved_context.get("graph_triples", []):
        cost = count_tokens(triple)
        if used + cost > graph_budget and kept_graph:
            break
        kept_graph.append(triple)
        used += cost

    kept_vector: list[dict[str, Any]] = []
    used = 0
    for chunk in retrieved_context.get("vector_chunks", []):
        # project down to what actually reaches the prompt — a stored chunk also carries
        # its embedding vector, which must never be counted against the token budget
        projected = {"clause_id": chunk.get("clause_id"), "content": chunk.get("content")}
        cost = _tokens_of(projected)
        if used + cost > vector_budget and len(kept_vector) >= min_vector_chunks:
            break
        kept_vector.append(projected)
        used += cost

    return {"graph_triples": kept_graph, "vector_chunks": kept_vector}


def assemble_prompt_payload(
    retrieved_context: dict[str, Any],
    reasoning_traces: list[str],
    memory_facts: list[dict[str, Any]],
    tradeoff_config: dict[str, Any] | None = None,
) -> PromptPayload:
    config = tradeoff_config or load_tradeoff_config()
    context_cfg, history_cfg, memory_cfg = config["context"], config["history"], config["memory"]

    context_block = build_context_block(
        retrieved_context,
        context_cfg["graph_share"],
        context_cfg["min_vector_chunks"],
        context_cfg["max_context_tokens"],
    )

    history_block = build_history_block(
        reasoning_traces, history_cfg["window_turns"], history_cfg["summary_after_turns"]
    )
    history_tokens = _ENCODING.encode(history_block)
    if len(history_tokens) > history_cfg["max_history_tokens"]:
        history_block = _ENCODING.decode(history_tokens[: history_cfg["max_history_tokens"]])

    memory_block = memory_facts[: memory_cfg["top_k"]] if memory_cfg.get("enabled") else []

    token_budget_report = {
        "context_tokens": _tokens_of(context_block),
        "history_tokens": count_tokens(history_block),
        "memory_tokens": _tokens_of(memory_block),
    }

    return {
        "context_block": context_block,
        "history_block": history_block,
        "memory_block": memory_block,
        "token_budget_report": token_budget_report,
    }
