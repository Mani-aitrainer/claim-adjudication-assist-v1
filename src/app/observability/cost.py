"""cost = in_tok/1e6 * input_per_1m + out_tok/1e6 * output_per_1m, prices from
config/agents.yaml. Attached to each AgentMetric and summed into run_audit.total_cost_usd.
"""


def compute_cost_usd(input_tokens: int, output_tokens: int, pricing: dict[str, float]) -> float:
    return (
        input_tokens / 1e6 * pricing["input_per_1m"]
        + output_tokens / 1e6 * pricing["output_per_1m"]
    )
