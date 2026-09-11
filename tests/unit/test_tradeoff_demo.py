"""P8 'done when': tradeoff_demo.py prints three profiles."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from tradeoff_demo import print_rows, run_demo  # noqa: E402

from app.core.settings import Settings

from ..conftest import FakeAdjudicatorLLM, FakeAuditLLM, FakeCopyIntakeLLM, FakeEmbeddingsClient

FIXTURE_DIR = "tests/fixtures/textract"


def test_run_demo_produces_three_distinct_profiles(tmp_path, graph_store, vector_store) -> None:
    settings = Settings(
        sqlite_path=str(tmp_path / "checkpoints.sqlite"), fixture_dir=FIXTURE_DIR
    )

    rows = asyncio.run(
        run_demo(
            "tests/fixtures/claims/CLM-005.pdf",
            ["lean", "balanced", "generous"],
            settings,
            intake_llm=FakeCopyIntakeLLM(),
            adjudicator_llm=FakeAdjudicatorLLM(),
            auditor_llm=FakeAuditLLM(),
            embeddings_client=FakeEmbeddingsClient(),
            graph_store=graph_store,
            vector_store=vector_store,
        )
    )

    assert [row["profile"] for row in rows] == ["lean", "balanced", "generous"]
    for row in rows:
        assert row["total_tokens"] > 0
        assert row["estimated_cost_usd"] > 0
        assert row["latency_ms"] >= 0
        assert row["status"] == "PARTIAL"  # CLM-005's senior co-pay result, independent of profile

    # the whole point of the demo: a bigger budget can only admit more, never less, context
    assert rows[0]["context_tokens"] <= rows[1]["context_tokens"] <= rows[2]["context_tokens"]


def test_print_rows_does_not_crash(capsys, tmp_path, graph_store, vector_store) -> None:
    settings = Settings(sqlite_path=str(tmp_path / "checkpoints.sqlite"), fixture_dir=FIXTURE_DIR)
    rows = asyncio.run(
        run_demo(
            "tests/fixtures/claims/CLM-005.pdf",
            ["lean", "balanced", "generous"],
            settings,
            intake_llm=FakeCopyIntakeLLM(),
            adjudicator_llm=FakeAdjudicatorLLM(),
            auditor_llm=FakeAuditLLM(),
            embeddings_client=FakeEmbeddingsClient(),
            graph_store=graph_store,
            vector_store=vector_store,
        )
    )
    print_rows(rows)
    captured = capsys.readouterr()
    assert "lean" in captured.out
    assert "balanced" in captured.out
    assert "generous" in captured.out
