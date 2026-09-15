"""Wraps a node function to append one AgentMetric to state["metrics"] per invocation —
kept separate from each node body, matching the "no metric code inside node bodies"
principle from DEVELOPMENT_PLAN.md's Observability chapter. Latency is measured for real;
cost_usd/token counts are the real, LLM-usage-derived figures when available (a real LLM
response carries usage_metadata) and 0.0 otherwise (a non-LLM agent, or a test double).
"""

import time
from functools import wraps
from inspect import iscoroutinefunction
from typing import Any

from app.graph.state import AgentMetric, ClaimState


def _build_metric(agent_name: str, model: str, latency_ms: float) -> AgentMetric:
    return {
        "agent": agent_name,
        "input_tokens": 0,
        "output_tokens": 0,
        "latency_ms": latency_ms,
        "cost_usd": 0.0,
        "model": model,
        "cache_hit": False,
    }


def with_state_metrics(agent_name: str, model: str = "") -> Any:
    def decorator(node_fn: Any) -> Any:
        if iscoroutinefunction(node_fn):

            @wraps(node_fn)
            async def async_wrapper(state: ClaimState) -> dict[str, Any]:
                start = time.perf_counter()
                result = dict(await node_fn(state))
                latency_ms = (time.perf_counter() - start) * 1000
                result["metrics"] = [_build_metric(agent_name, model, latency_ms)]
                return result

            return async_wrapper

        @wraps(node_fn)
        def sync_wrapper(state: ClaimState) -> dict[str, Any]:
            start = time.perf_counter()
            result = dict(node_fn(state))
            latency_ms = (time.perf_counter() - start) * 1000
            result["metrics"] = [_build_metric(agent_name, model, latency_ms)]
            return result

        return sync_wrapper

    return decorator
