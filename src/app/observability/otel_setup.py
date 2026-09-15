"""OpenTelemetry tracing: one span per graph run, child span per agent, attributes
run_id/agent/model/tokens/cache_hit. Console exporter locally; OTLP to an ADOT collector
on AWS is a stretch goal, not required.
"""

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

_configured = False


def configure_tracing(service_name: str = "claim-adjudication-assist") -> None:
    global _configured
    if _configured:
        return
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _configured = True


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)
