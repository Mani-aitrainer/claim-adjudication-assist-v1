"""Checkpointer factory. local -> AsyncSqliteSaver at settings.sqlite_path.
aws -> AsyncPostgresSaver against RDS (lazy import — psycopg is never imported under
APP_ENV=local). Async because the graph itself is async (PolicyAdjudicatorAgent's
concurrent graph+vector retrieval, and later the streaming API's astream_events).

    async with get_checkpointer(settings) as checkpointer:
        graph = build_graph(checkpointer, ocr_provider, ...)
        ...
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from app.core.settings import Settings


@asynccontextmanager
async def get_checkpointer(settings: Settings) -> AsyncIterator[Any]:
    if settings.app_env == "aws":
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(settings.postgres_dsn) as saver:
            yield saver
        return

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(settings.sqlite_path) as saver:
        await saver.setup()
        yield saver
