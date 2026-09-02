"""FastAPI app factory. All cross-cutting dependencies (graph, stores, cache) are built
once at startup (lifespan) and held on app.state — routes never construct them.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.routes_adjudicate import router as adjudicate_router
from app.api.routes_graph import router as graph_router
from app.api.routes_health import router as health_router
from app.api.routes_runs import router as runs_router
from app.cache.base import get_cache
from app.core.logging_setup import configure_logging, get_logger
from app.core.settings import Settings, get_settings
from app.graph.build_graph import build_graph
from app.memory.long_term import get_memory_store
from app.observability.otel_setup import configure_tracing
from app.ocr.base import OCRProvider
from app.ocr.fixture_provider import FixtureOCRProvider
from app.persistence.checkpointer import get_checkpointer
from app.persistence.run_audit import get_run_audit_store
from app.rag.graph_store import get_graph_store
from app.rag.vector_store import get_vector_store

logger = get_logger(__name__)


def _default_ocr_provider(settings: Settings) -> OCRProvider:
    if settings.app_env == "aws" or settings.use_textract:
        from app.ocr.textract_provider import TextractOCRProvider

        return TextractOCRProvider(settings.aws_region)
    return FixtureOCRProvider(settings.fixture_dir)


def create_app(settings: Settings | None = None, **build_graph_overrides: Any) -> FastAPI:
    """build_graph_overrides (intake_llm, adjudicator_llm, graph_store, vector_store, ...)
    override the real dependencies build_graph() would otherwise construct — used by tests."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    configure_tracing()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with get_checkpointer(resolved_settings) as checkpointer:
            graph_store = build_graph_overrides.get("graph_store") or get_graph_store(
                resolved_settings
            )
            vector_store = build_graph_overrides.get("vector_store") or get_vector_store(
                resolved_settings
            )
            memory_store = build_graph_overrides.get("memory_store") or get_memory_store(
                resolved_settings
            )
            cache = build_graph_overrides.get("cache") or get_cache(resolved_settings)
            ocr_provider = build_graph_overrides.get("ocr_provider") or _default_ocr_provider(
                resolved_settings
            )

            graph = build_graph(
                checkpointer,
                ocr_provider,
                graph_store,
                vector_store,
                intake_llm=build_graph_overrides.get("intake_llm"),
                repair_llm=build_graph_overrides.get("repair_llm"),
                adjudicator_llm=build_graph_overrides.get("adjudicator_llm"),
                auditor_llm=build_graph_overrides.get("auditor_llm"),
                embeddings_client=build_graph_overrides.get("embeddings_client"),
                memory_store=memory_store,
                cache=cache,
            )

            app.state.settings = resolved_settings
            app.state.checkpointer = checkpointer
            app.state.graph = graph
            app.state.graph_store = graph_store
            app.state.vector_store = vector_store
            app.state.cache = cache
            app.state.run_audit_store = get_run_audit_store(resolved_settings)

            logger.info("app_started", app_env=resolved_settings.app_env)
            yield

    app = FastAPI(title="Claim Adjudication Assist", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(adjudicate_router)
    app.include_router(runs_router)
    app.include_router(graph_router)

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
