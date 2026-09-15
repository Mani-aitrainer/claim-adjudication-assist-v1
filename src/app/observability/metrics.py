"""Every Prometheus metric the system emits, defined once. All instrumentation reads from
this module — no metric is ever created ad hoc inside a node body.
"""

from prometheus_client import Counter, Histogram

agent_invocations_total = Counter(
    "agent_invocations_total", "Agent run() calls", ["agent", "status"]
)
agent_latency_seconds = Histogram(
    "agent_latency_seconds", "Agent run() latency", ["agent"]
)
agent_tokens_total = Counter(
    "agent_tokens_total", "Tokens consumed per agent", ["agent", "model", "token_type"]
)
agent_cost_usd_total = Counter(
    "agent_cost_usd_total", "Estimated USD cost per agent", ["agent", "model"]
)
llm_calls_total = Counter(
    "llm_calls_total", "LLM calls, including retries and failures", ["agent", "model", "outcome"]
)
graph_runs_total = Counter("graph_runs_total", "Completed graph runs", ["outcome"])
graph_run_duration_seconds = Histogram(
    "graph_run_duration_seconds", "End-to-end graph run duration", ["domain"]
)
validation_failures_total = Counter(
    "validation_failures_total", "ClaimValidatorAgent rule failures", ["rule"]
)
repair_attempts_total = Counter(
    "repair_attempts_total", "FieldRepairAgent attempts", ["outcome"]
)
healing_loops_total = Counter(
    "healing_loops_total", "DecisionAuditorAgent heal loops", ["outcome"]
)
quality_score = Histogram("quality_score", "DecisionAuditorAgent quality score", ["domain"])
cache_operations_total = Counter(
    "cache_operations_total", "Cache operations", ["namespace", "result"]
)
context_tokens_used = Histogram(
    "context_tokens_used", "Tokens per context/history/memory bucket", ["agent", "bucket"]
)
textract_pages_total = Counter("textract_pages_total", "Textract pages processed", ["outcome"])
