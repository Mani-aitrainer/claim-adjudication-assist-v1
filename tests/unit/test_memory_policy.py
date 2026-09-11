"""memory/policy.py: context/history/memory budgeting."""

from app.memory.policy import assemble_prompt_payload, build_context_block, count_tokens


def test_vector_chunk_embeddings_are_never_counted_against_the_budget() -> None:
    """Regression: a stored chunk carries its raw 1536-float embedding — that must never
    leak into the token budget or the prompt actually sent to the LLM."""
    retrieved_context = {
        "graph_triples": ["CPT-99213 —maps_to→ OP-3.2  [clause: OP-3.2]"],
        "vector_chunks": [
            {"clause_id": "OP-3.2", "content": "short clause text", "embedding": [0.1] * 1536}
        ],
    }
    context_block = build_context_block(
        retrieved_context, graph_share=0.5, min_vector_chunks=1, max_context_tokens=4000
    )
    assert "embedding" not in context_block["vector_chunks"][0]
    assert count_tokens(str(context_block)) < 100


def test_lean_profile_admits_no_more_context_than_balanced() -> None:
    retrieved_context = {
        "graph_triples": [f"CODE{i} —maps_to→ CLAUSE{i}  [clause: CLAUSE{i}]" for i in range(20)],
        "vector_chunks": [
            {"clause_id": f"CLAUSE{i}", "content": "x" * 200} for i in range(20)
        ],
    }
    lean = assemble_prompt_payload(
        retrieved_context,
        [],
        [],
        {
            "context": {"max_context_tokens": 100, "graph_share": 0.5, "min_vector_chunks": 1},
            "history": {"window_turns": 4, "summary_after_turns": 6, "max_history_tokens": 200},
            "memory": {"enabled": True, "top_k": 3},
        },
    )
    generous = assemble_prompt_payload(
        retrieved_context,
        [],
        [],
        {
            "context": {"max_context_tokens": 4000, "graph_share": 0.5, "min_vector_chunks": 4},
            "history": {"window_turns": 4, "summary_after_turns": 6, "max_history_tokens": 200},
            "memory": {"enabled": True, "top_k": 3},
        },
    )
    lean_tokens = lean["token_budget_report"]["context_tokens"]
    generous_tokens = generous["token_budget_report"]["context_tokens"]
    assert lean_tokens < generous_tokens
