"""BaseAgent — the common shape every agent implements.

All instrumentation lives here, in one place: every concrete agent's `run()` is wrapped
automatically (sync or async, whichever it defines) to record `agent_invocations_total`
and `agent_latency_seconds`, and to open a tracing span. No node body ever calls a metric
or tracer directly.
"""

import time
from abc import ABC, abstractmethod
from functools import wraps
from inspect import iscoroutinefunction
from typing import Any, ClassVar

from app.observability.metrics import agent_invocations_total, agent_latency_seconds
from app.observability.otel_setup import get_tracer

_tracer = get_tracer(__name__)


def _instrument(run_method: Any) -> Any:
    if iscoroutinefunction(run_method):

        @wraps(run_method)
        async def async_wrapper(self: "BaseAgent", *args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            status = "success"
            with _tracer.start_as_current_span(self.name):
                try:
                    return await run_method(self, *args, **kwargs)
                except Exception:
                    status = "error"
                    raise
                finally:
                    agent_invocations_total.labels(agent=self.name, status=status).inc()
                    agent_latency_seconds.labels(agent=self.name).observe(
                        time.perf_counter() - start
                    )

        return async_wrapper

    @wraps(run_method)
    def sync_wrapper(self: "BaseAgent", *args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        status = "success"
        with _tracer.start_as_current_span(self.name):
            try:
                return run_method(self, *args, **kwargs)
            except Exception:
                status = "error"
                raise
            finally:
                agent_invocations_total.labels(agent=self.name, status=status).inc()
                agent_latency_seconds.labels(agent=self.name).observe(
                    time.perf_counter() - start
                )

    return sync_wrapper


class BaseAgent(ABC):
    name: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "run" in cls.__dict__:
            cls.run = _instrument(cls.__dict__["run"])  # type: ignore[method-assign]

    @abstractmethod
    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Executes the agent's work and returns its result."""
