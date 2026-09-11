"""Runs the same claim at three budget profiles — lean / balanced / generous — and prints
tokens, cost, latency and quality score side by side. CLM-005 is the right fixture: its
co-pay calculation needs enough retrieved context to get right, so `lean` visibly degrades.

    python scripts/tradeoff_demo.py --file tests/fixtures/claims/CLM-005.pdf \
        --profiles lean,balanced,generous
"""

import argparse
import asyncio
import copy
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.agents.claim_intake_agent import ClaimIntakeAgent  # noqa: E402
from app.agents.decision_auditor_agent import DecisionAuditorAgent  # noqa: E402
from app.agents.policy_adjudicator_agent import PolicyAdjudicatorAgent  # noqa: E402
from app.core.agent_config import get_agent_config  # noqa: E402
from app.core.settings import Settings, get_settings  # noqa: E402
from app.memory.long_term import get_memory_store  # noqa: E402
from app.memory.policy import load_tradeoff_config  # noqa: E402
from app.ocr.fixture_provider import FixtureOCRProvider  # noqa: E402
from app.rag.graph_store import get_graph_store  # noqa: E402
from app.rag.vector_store import get_vector_store  # noqa: E402


def _profile(base: dict[str, Any], **overrides: dict[str, Any]) -> dict[str, Any]:
    profile = copy.deepcopy(base)
    for section, values in overrides.items():
        profile[section].update(values)
    return profile


def build_profiles() -> dict[str, dict[str, Any]]:
    balanced = load_tradeoff_config()
    lean = _profile(
        balanced,
        context={"max_context_tokens": 400, "min_vector_chunks": 1},
        history={"window_turns": 1, "max_history_tokens": 200},
        memory={"top_k": 1},
    )
    generous = _profile(
        balanced,
        context={"max_context_tokens": 8000, "min_vector_chunks": 4},
        history={"window_turns": 8, "max_history_tokens": 4000},
        memory={"top_k": 10},
    )
    return {"lean": lean, "balanced": balanced, "generous": generous}


def estimate_cost_usd(
    token_budget_report: dict[str, int], agent_key: str = "adjudicator_agent"
) -> float:
    """Input cost from the actual prompt token budget; output cost estimated at the
    agent's configured max_tokens (a worst-case bound, not a billing-accurate figure)."""
    config = get_agent_config(agent_key)
    input_tokens = sum(token_budget_report.values())
    output_tokens = config.max_tokens
    return (
        input_tokens / 1e6 * config.pricing["input_per_1m"]
        + output_tokens / 1e6 * config.pricing["output_per_1m"]
    )


async def run_demo(
    file_path: str,
    profile_names: list[str],
    settings: Settings,
    intake_llm: Any = None,
    adjudicator_llm: Any = None,
    auditor_llm: Any = None,
    embeddings_client: Any = None,
    graph_store: Any = None,
    vector_store: Any = None,
    memory_store: Any = None,
) -> list[dict[str, Any]]:
    """graph_store / vector_store / memory_store default to settings-derived singletons —
    tests inject their own already-ingested instances instead."""
    ocr_provider = FixtureOCRProvider(settings.fixture_dir)
    intake_result = ClaimIntakeAgent(ocr_provider, llm=intake_llm).run(file_path)
    extracted_fields = intake_result["extracted_fields"]

    graph_store = graph_store if graph_store is not None else get_graph_store(settings)
    vector_store = vector_store if vector_store is not None else get_vector_store(settings)
    memory_store = memory_store if memory_store is not None else get_memory_store(settings)
    profiles = build_profiles()

    rows: list[dict[str, Any]] = []
    for name in profile_names:
        profile_config = profiles[name]
        agent = PolicyAdjudicatorAgent(
            graph_store,
            vector_store,
            llm=adjudicator_llm,
            embeddings_client=embeddings_client,
            memory_store=memory_store,
            tradeoff_config=profile_config,
        )
        start = time.perf_counter()
        result = await agent.run(extracted_fields)
        audit = DecisionAuditorAgent(llm=auditor_llm).run(
            result["decision"], result["retrieved_context"]
        )
        latency_ms = (time.perf_counter() - start) * 1000

        report = result["token_budget_report"]
        rows.append(
            {
                "profile": name,
                "context_tokens": report["context_tokens"],
                "history_tokens": report["history_tokens"],
                "memory_tokens": report["memory_tokens"],
                "total_tokens": sum(report.values()),
                "estimated_cost_usd": round(estimate_cost_usd(report), 5),
                "latency_ms": round(latency_ms, 1),
                "quality_score": audit["quality_score"],
                "status": result["decision"]["status"],
                "payable_amount": result["decision"]["payable_amount"],
            }
        )
    return rows


def print_rows(rows: list[dict[str, Any]]) -> None:
    headers = list(rows[0].keys())
    widths = [max(len(h), *(len(str(r[h])) for r in rows)) for h in headers]
    print(" | ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(" | ".join(str(row[h]).ljust(w) for h, w in zip(headers, widths, strict=True)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--profiles", default="lean,balanced,generous")
    args = parser.parse_args()

    settings = get_settings()
    rows = asyncio.run(run_demo(args.file, args.profiles.split(","), settings))
    print_rows(rows)


if __name__ == "__main__":
    main()
