"""CLA — the Claim adjudication Assist command-line runner.

Drives the two agents that exist today (ClaimIntakeAgent -> ClaimValidatorAgent, wired in
build_graph.py) end to end against the bundled test fixtures, without needing the FastAPI
server, a database, or a network call.

Usage (see README.md for the full walkthrough):

    python -m app.cli run tests/fixtures/claims/CLM-001.pdf
    python -m app.cli run-all
    python -m app.cli run-all --offline --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from app.cache.memory_cache import InMemoryCache
from app.core.llm_factory import get_llm
from app.core.settings import Settings, get_settings
from app.graph.build_graph import build_graph
from app.graph.build_graph import run_graph as _run_graph
from app.ocr.fixture_provider import FixtureOCRProvider
from app.rag.graph_store import get_graph_store
from app.rag.vector_store import get_vector_store

FIXTURE_CLAIMS_DIR = Path("tests/fixtures/claims")


class CLA:
    """Builds the intake->validate graph once and runs claims through it.

    offline=True (or no OPENAI_API_KEY configured) uses OfflineCopyIntakeLLM instead of a
    real OpenAI call — deterministic, free, and works without any credentials, at the cost
    of not correcting noisy OCR output the way the real model would (see its docstring).
    """

    def __init__(self, settings: Settings | None = None, offline: bool | None = None) -> None:
        self.settings = settings or get_settings()
        self.offline = offline if offline is not None else not bool(self.settings.openai_api_key)
        self._ocr_provider = FixtureOCRProvider(self.settings.fixture_dir)
        self._cache = InMemoryCache()
        self._graph: Any | None = None

    def _intake_llm(self) -> Any:
        if self.offline:
            from app.agents.offline_llm import OfflineCopyIntakeLLM

            return OfflineCopyIntakeLLM()
        return get_llm("intake_agent")

    def _repair_llm(self) -> Any:
        if self.offline:
            from app.agents.offline_llm import OfflineRepairLLM

            return OfflineRepairLLM()
        return get_llm("repair_agent")

    async def _get_graph(self) -> Any:
        if self._graph is None:
            checkpointer = MemorySaver()
            self._graph = build_graph(
                checkpointer,
                self._ocr_provider,
                get_graph_store(self.settings),
                get_vector_store(self.settings),
                intake_llm=self._intake_llm(),
                repair_llm=self._repair_llm(),
                cache=self._cache,
            )
        return self._graph

    async def run(self, source_uri: str, domain: str = "claims") -> dict[str, Any]:
        graph = await self._get_graph()
        run_id = str(uuid.uuid4())
        initial_state = {
            "run_id": run_id,
            "document_id": Path(source_uri).stem,
            "source_uri": source_uri,
            "domain": domain,
        }
        config = {"configurable": {"thread_id": run_id}}
        return await _run_graph(graph, initial_state, config)

    async def run_many(self, source_uris: list[str], domain: str = "claims") -> list[dict[str, Any]]:
        return [await self.run(source_uri, domain=domain) for source_uri in source_uris]

    @staticmethod
    def discover_fixture_claims() -> list[str]:
        if not FIXTURE_CLAIMS_DIR.exists():
            return []
        return sorted(str(p) for p in FIXTURE_CLAIMS_DIR.glob("*.pdf"))


def _summarize(result: dict[str, Any]) -> dict[str, Any]:
    validation = result.get("validation", {})
    return {
        "document_id": result.get("document_id"),
        "extraction_source": result.get("extraction_source"),
        "is_valid": validation.get("is_valid"),
        "errors": [f"{e['code']}: {e['message']}" for e in validation.get("errors", [])],
        "extracted_fields": result.get("extracted_fields"),
    }


def _print_summary(summary: dict[str, Any]) -> None:
    status = "VALID" if summary["is_valid"] else "INVALID"
    print(f"\n[{summary['document_id']}] {status}  (extraction_source={summary['extraction_source']})")
    fields = summary["extracted_fields"] or {}
    if fields:
        print(f"  member_id={fields.get('member_id')!r} policy_no={fields.get('policy_no')!r} "
              f"claimed_amount={fields.get('claimed_amount')!r}")
    for error in summary["errors"]:
        print(f"  - {error}")


def _run_command(args: argparse.Namespace) -> int:
    cla = CLA(offline=args.offline)
    mode = "offline (rule-based copy)" if cla.offline else "OpenAI (config/agents.yaml)"
    print(f"CLA - running intake -> validate  [llm mode: {mode}]")

    source_uris = [args.source_uri] if args.command == "run" else CLA.discover_fixture_claims()
    if not source_uris:
        print(f"No claim fixtures found under {FIXTURE_CLAIMS_DIR}/", file=sys.stderr)
        return 1

    try:
        results = asyncio.run(cla.run_many(source_uris, domain=args.domain))
    except Exception as exc:  # noqa: BLE001 - CLI top level, report and exit cleanly
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summaries = [_summarize(r) for r in results]

    if args.json:
        print(json.dumps(summaries, indent=2, default=str))
    else:
        for summary in summaries:
            _print_summary(summary)
        valid_count = sum(1 for s in summaries if s["is_valid"])
        print(f"\n{valid_count}/{len(summaries)} claims passed validation.")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cla", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--offline",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="force the deterministic offline intake LLM (default: offline unless "
        "OPENAI_API_KEY is set)",
    )
    parser.add_argument("--domain", default="claims", help="domain to run (default: claims)")
    parser.add_argument("--json", action="store_true", help="print raw JSON instead of a summary")

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run a single claim document through the graph")
    run_parser.add_argument("source_uri", help="path to a claim PDF, e.g. tests/fixtures/claims/CLM-001.pdf")

    subparsers.add_parser("run-all", help="run every fixture claim under tests/fixtures/claims/")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return _run_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
