"""Windowing + rolling summary for the "history" bucket.

In this single-request agentic pipeline, "history" is the sequence of reasoning traces
from earlier attempts within the *same* run's heal loop — exactly the failure mode
DEVELOPMENT_PLAN.md calls out: "Heal loop 2 replays loop 1, cost doubles." Windowing this
is what keeps that replay bounded.
"""


def build_history_block(
    reasoning_traces: list[str],
    window_turns: int = 4,
    summary_after_turns: int = 6,
) -> str:
    if not reasoning_traces:
        return ""

    if len(reasoning_traces) <= window_turns:
        return "\n".join(reasoning_traces)

    recent = reasoning_traces[-window_turns:]
    older = reasoning_traces[:-window_turns]

    block = "\n".join(recent)
    if len(reasoning_traces) > summary_after_turns:
        summary = "; ".join(trace[:80] for trace in older if trace)
        block = f"[{len(older)} earlier attempt(s) summarized: {summary}]\n{block}"
    return block
