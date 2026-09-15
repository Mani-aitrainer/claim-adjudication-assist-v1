





"""observability/cost.py, metrics.py, agents/base.py's auto-instrumentation."""

import asyncio

import pytest
from prometheus_client import REGISTRY

from app.agents.base import BaseAgent
from app.observability.cost import compute_cost_usd


def test_compute_cost_usd() -> None:
    pricing = {"input_per_1m": 0.40, "output_per_1m": 1.60}
    cost = compute_cost_usd(input_tokens=1_000_000, output_tokens=1_000_000, pricing=pricing)
    assert cost == pytest.approx(2.00)


def test_compute_cost_usd_zero_tokens() -> None:
    assert compute_cost_usd(0, 0, {"input_per_1m": 1.0, "output_per_1m": 1.0}) == 0.0


def _counter_value(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


class _SyncProbeAgent(BaseAgent):
    name = "SyncProbeAgent"

    def run(self, should_fail: bool = False) -> str:
        if should_fail:
            raise ValueError("boom")
        return "ok"


class _AsyncProbeAgent(BaseAgent):
    name = "AsyncProbeAgent"

    async def run(self) -> str:
        return "ok"


def test_sync_agent_run_is_instrumented() -> None:
    labels = {"agent": "SyncProbeAgent", "status": "success"}
    before = _counter_value("agent_invocations_total", labels)
    _SyncProbeAgent().run()
    after = _counter_value("agent_invocations_total", labels)
    assert after == before + 1


def test_sync_agent_run_records_error_status_and_reraises() -> None:
    labels = {"agent": "SyncProbeAgent", "status": "error"}
    before = _counter_value("agent_invocations_total", labels)
    with pytest.raises(ValueError):
        _SyncProbeAgent().run(should_fail=True)
    after = _counter_value("agent_invocations_total", labels)
    assert after == before + 1


def test_async_agent_run_is_instrumented() -> None:
    labels = {"agent": "AsyncProbeAgent", "status": "success"}
    before = _counter_value("agent_invocations_total", labels)
    asyncio.run(_AsyncProbeAgent().run())
    after = _counter_value("agent_invocations_total", labels)
    assert after == before + 1
